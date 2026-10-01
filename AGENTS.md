# wxbot 项目内约定（给 AI 协作者的备忘）

## 项目目标

Windows 桌面端「个人微信自动回复」小工具。用户已确认：**全自动模式**（程序直接收发），
以安全为最高优先级（"尽量不封号"）；要求支持**本地模型**、**GUI 设置界面**、**技能系统**。

## 硬性约束（不可违反）

1. 只允许「不侵入微信进程」的技术：WGC 抓屏 / OCR / 键鼠模拟 / UIA 只读。
   **禁止**：Hook 注入、内存读写、协议逆向、改包（封号高危）。
2. 所有真实发送必须先通过 `wxbot.safety.gateway.SafetyGateway.check()`，
   并经过 `ReplyPipeline` 的技能审查；不允许任何绕过路径。
3. 默认 `dry_run`；切 `auto` 前先空跑验证。白名单为空 = 不回复任何人。
4. API Key 来源：环境变量（llm.api_key_env）→ 本地 secrets.toml（已 gitignore，图形界面写入）。
   绝不写进 config.toml / 日志 / 仓库。
5. 不要为了让「回复更多 / 更快」放宽 config.toml 的安全默认值。
6. 自学习产物（data/learned_skills.json）只作为提示词参考注入回复，**不得直接照发**；
   条目可被用户随时停用，停用后不得再注入。

## 本机环境事实（2026-10-01 实测）

- 微信：Weixin 4.1.13.65，安装于 `D:\Program Files\Tencent\Weixin\Weixin.exe`；
  多进程架构；主窗口标题「微信」，窗口类 `mmui::MainWindow`。
- 主窗口经常被收进托盘（隐藏）；隐藏 / 最小化时 WGC 抓不到帧，需先 `ShowWindow` 唤出。
- Python：项目自带 venv `.venv`（uv 创建，CPython 3.12.13）。
  ⚠ PATH 上的 `python` 是坏的（指向不存在的 hermes-agent 解释器），一律用 `.venv\Scripts\python.exe`。
- 依赖已装：mss、rapidocr-onnxruntime、opencv-python、numpy、pillow、pywinauto、
  windows-capture、pyside6-essentials。
- 用户本地模型运行时：**LM Studio**（服务端 `http://127.0.0.1:1234/v1`，已安装且常开；
  2026-10-01 实测 wxbot 联通正常）。硬件：RTX 5060（8GB 显存）/ 32GB RAM / Ryzen 7 7800X3D
  → 本地模型推荐 **Qwen3-8B（Q4_K_M）**；想更聪明可试 Qwen3-14B（部分卸载）。
  config.toml 的 llm.base_url 已预填 LM Studio 地址。

## 技术结论（实测，勿重复踩坑）

- UIA 控件树：只有窗口框架层（标题栏按钮、导航标签，约 28 节点）；
  聊天内容区 `MMUIRenderSubWindowHW` 是 GPU 自绘画布，**无子节点** → 必须走视觉。
- 抓屏方案对比（实测）：

  | 方案 | 窗口被遮挡时 | 结论 |
  | --- | --- | --- |
  | 直接屏幕抓取（mss） | ❌ 截到遮挡物 | 仅窗口在最前时可用（备选） |
  | PrintWindow(PW_RENDERFULLCONTENT) | ❌ 全黑（mean 0.0） | 排除 |
  | **WGC（windows-capture 包）** | ✅ 正常读到内容 | **采用** |

  WGC 用法：`WindowsCapture(window_hwnd=..., draw_border=False, cursor_capture=False)`；
  抓帧尺寸 ≈ 1186x1033（窗口 1200x1040），**点击坐标映射要处理偏移**（发送模块要处理）。
- OCR：RapidOCR 识别质量很好（置信度普遍 0.9+）。

## 模块与命令

- 图形界面（推荐入口）：`.venv\Scripts\python.exe -m wxbot gui`
- 状态：`.venv\Scripts\python.exe -m wxbot status`
- 运行循环（等同 GUI 开关）：`.venv\Scripts\python.exe -m wxbot run [--interval 3]`
- 厂商列表：`.venv\Scripts\python.exe -m wxbot providers`
- 模型库：`.venv\Scripts\python.exe -m wxbot models`
- 厂商连通自检：`.venv\Scripts\python.exe tools\check_provider_flow.py [厂商key]`
- GUI 模型页行为自检：`.venv\Scripts\python.exe tools\check_gui_model_tab.py`
- GUI 运行开关自检：`.venv\Scripts\python.exe tools\check_gui_run_switch.py`
- 视觉识别自检（读真实微信会话列表）：`.venv\Scripts\python.exe tools\check_vision_read.py`
- 未读检测调试（输出面板图与红点位置）：`.venv\Scripts\python.exe tools\debug_session_panel.py`
- 点击映射自检（不发消息）：`.venv\Scripts\python.exe tools\check_send_dryrun.py --index 2`
- 输入环节自检（不按回车）：`.venv\Scripts\python.exe tools\check_input_debug.py`
- 真实发送测试（会发出一条消息）：`.venv\Scripts\python.exe tools\check_send_live.py`
- 界面截图（评审用）：`.venv\Scripts\python.exe tools\shot_gui.py shots\run.png --page run --theme dark`
- 界面原型（独立于主程序）：`prototype\redesign_prototype.py`、`prototype\预览原型.bat`
- 学习：`.venv\Scripts\python.exe -m wxbot learn`（AI 复盘聊天记录、整理技能；需先配置模型）
- 测试：`.venv\Scripts\python.exe -m unittest discover -s tests -t tests`（172 项全绿）
  ⚠ `tests` 下没有 `__init__.py`，**必须带 `-t tests`**；写 `-t .` 会报
  `ImportError: Start directory is not importable`。
  ⚠ 本项目**没有装 pytest**，`python -m pytest` 会报 `No module named pytest`，别浪费一轮排查。

## 实测踩坑（微信视觉自动化）

1. **未读红点位置不能靠猜**：实测红点紧跟头像/名字（不是行最右侧），且左侧导航栏「微信」图标上
   也有红点。判定要用「尺寸 + 圆形度」区分真红点与彩色头像（腾讯新闻 logo 含红会误报），
   并用 x 偏移排除导航栏；再配合「会话摘要变化」作为备用信号（无红点也不漏）。
2. **WGC 有旧帧**：抓屏会话刚建立时可能先返回操作前的画面。点击/输入后校验必须
   `grab_bgr(hwnd, frames=3)` 取最后一帧，否则会误判"操作没生效"。
3. **ctypes 剪贴板必须声明 restype**：64 位下 HANDLE 会被默认的 c_int 截断，导致
   `GlobalLock` 拿到无效指针、剪贴板写入静默失败（表现为"粘贴没反应"）。
4. **前台锁定**：非前台进程直接 `SetForegroundWindow` 常被 Windows 静默拒绝，
   要先 `AttachThreadInput` 共享输入队列，仍失败再用 Alt 键解锁后重试。
5. **PowerShell 传中文参数会被破坏**：需要中文时写成脚本文件里的字面量或传序号，
   不要走命令行参数；控制台输出中文也可能变问号，诊断脚本用 unicode_escape 打印。
6. **后台写入的实验结论（别重复试）**：
   - `PostMessage(WM_LBUTTONDOWN/UP)` **可以**在微信处于后台时切换会话（光标不动）；
   - `PostMessage(WM_CHAR)` **不行**，微信输入框只接受真实键盘输入（真实焦点）。
   因此"打字"必须短暂抢前台；已用这些手段降低打扰：发送前等用户空闲（GetLastInputInfo）、
   会话已打开时跳过点击、剪贴板粘贴（仅 2 次按键）、发送后还原光标与前台窗口
   （`input.cursor_pos/set_cursor_pos`、`input.set_foreground(previous)`）。
7. **WGC 静止窗口每次会话只出 1 帧 —— 别写"收集 N 帧"**：
   实测 `frames=3` 恒定等满 timeout（曾设 8s → 每帧 9.02s），因为第 2、3 帧根本不来。
   一次发送要抓 5~6 次屏，于是单个回复卡到 40s+，表现为"连续发送卡住"。
   **正确做法**：每次抓屏用单帧（约 0.17s）；需要"操作后的新画面"就先 `sleep` 再抓一帧。
8. **必须排除"自己刚发出的消息"**：自己的消息会出现在会话摘要里，
   若不加判断会被当成新消息 → 自问自答无限循环（实测日志抓到过）。
   做法：发送成功后记下 `(聊天, 文本)`，轮询时摘要与它匹配（含时间前缀容错）就跳过；
   同时把会话标识做归一化（`老王！`/`老王!` 视为同一个会话），否则会被当成两个聊天。
9. **微信不给"正打开的会话"显示未读红点** —— 靠红点会完全漏掉用户正看着的那个会话。
   已补第三个信号：读聊天区气泡（`read_current_chat_text`）判断内容是否变化；
   这同时也解决了"会话列表摘要被截断"的问题。
10. **未读数量角标会被 OCR 读成会话名**：未读 3 条时，面板里 y 靠上的 `'3'`（角标）会排在
   会话名之前，取 `group[0]` 会把整行丢掉。分组后要**剔除纯数字项**再取名字。
11. `elif` 链陷阱：判断"摘要是否变化"用了 `elif key in self._last_preview:`，当摘要没变时
   会命中该分支，**后面所有 elif 都不再执行**。补充判断要写成独立的 `if not reason and ...`。
12. **判断"谁发的"要靠气泡左右位置，不要靠文本匹配**：对方消息气泡靠左、自己的靠右
   （绿色气泡）。用「中心 x 相对聊天区中线的比例」判定（阈值必须按比例，窗口任意大小都成立）。
   早期用「整段内容里是否含我刚发的文字」排除回显 → 聊天区内容累积后，
   对方第二条消息也被吞（只回第一条）。现在直接只取 sender=="them" 的气泡做差分。
12b. ⚠ **换行气泡必须先合并再判方向**（v2.4.1 修，实测踩过）：气泡换行时续行是在气泡内
   **左对齐**的，所以一条右对齐的绿色气泡，第二行中心会掉到中线左边 ——
   只看单行中心就会把"我刚发的话"判成"对方发的"，于是"最后一条是对方发的=还没回"
   这条规则被触发 → **对同一条消息重复回复**（真实案例：程序刚启动就又回了一遍已答过的"你是谁"）。
   `read_chat_bubbles` 现在先把垂直相邻的 OCR 行合并成一条气泡（`_group_wrapped_lines`），
   再用**整块外接矩形**判方向：判"me"要**同时**满足右缘越过阈值且左缘不在对方起点
   （`THEM_LEFT_RATIO`），判不准落 `unknown` —— **宁可漏回，绝不乱回**。
   合并阈值 `WRAPPED_LINE_GAP_RATIO = 0.6` 是按真实抓屏标定的：同气泡内实测 0.17~0.36 倍行高，
   不同气泡之间最小 0.71 倍。**改这个值前先用 `tools/debug_bubble_boxes.py` 看真实间距**。
   另外单行气泡的判定保持原样（按中心 x），不要一起改。
13. 聊天区会滚动（旧的行从顶部消失），差分要**从后往前**找"上次见过且这次还在"的行，
   不能只找公共前缀。
14. **单点失败不能拖垮整体**（实测症状："回了几条就彻底卡住"）：
   - `read_sessions()` 返回空时不能直接 `return []` —— 那样整个当前会话检测被跳过；
   - 读不到标题时**不能清空 `_current_chat`** —— 状态一丢，后续检测全部失效。
   原则：读不到就"沿用上次已知的值"，只有"明确读到标题但该会话不在列表里"才清空。
15. 轮询里**只抓一帧**，供会话列表 / 标题 / 气泡三处复用（省一次抓屏 ≈ 0.2s）。
16. **判断"要不要回"用"最后一条气泡是谁发的"，不要用"和上一轮比差异"**（实测症状：
   会话正打开着 + 程序启动前就收到消息 → 没有红点 → 又被基线跳过 → 永远不回复）。
   规则：`_latest_definite_bubble()` 取最后一条能确定发送方的气泡，
   若是 `them` 且不等于 `_last_replied_text` → 需要回。
17. **去重要精确，冷却期要短**：`_claimed_text`（已认领）+ `_last_replied_text`（已回复）
   负责去重；`REPORT_COOLDOWN` 只是防相邻两轮重复上报，**不能设成 60s**，
   否则用户连发时第二条会被挡（实测踩过）。当前 5s。

- 核心模块：
  - `wxbot/safety/gateway.py` —— 安全网关（白名单 / 静默 / 限速 / 熔断 / 随机延迟）
  - `wxbot/brain/pipeline.py` —— 回复流水线（网关 → 技能闸门 → 生成 → 审查 → 计划）
  - `wxbot/brain/skills.py` —— 技能系统（persona / memory / safety / group_policy / learned）
  - `wxbot/theme.py` —— 主题（深/浅配色 + QSS + Switch/StatCard/StatusPill/Card 自定义控件）
  - `wxbot/runner.py` —— 运行控制器（启动/停止开关 + 主循环 + 统计，GUI 与命令行共用）
  - `wxbot/wechat/capture.py` —— WGC 抓屏与窗口可用性（frames>1 可取最后一帧，避开旧帧）
  - `wxbot/wechat/input.py` —— 键鼠输入与剪贴板（ctypes；含前台解锁）
  - `wxbot/wechat/vision_client.py` —— 会话识别 + 未读检测 + **真实发送**（四道校验）
  - `wxbot/textutil.py` —— 名称归一化（全角/半角差异容错）
  - `wxbot/providers.py` —— 厂商注册表（19 家）+ 模型元数据库（按名称推断上下文/模态/思考等级）
  - `wxbot/brain/model_store.py` —— 模型库（data/models.json，每个厂商×模型一套参数）
  - `wxbot/brain/llm.py` —— 模型引擎（OpenAI / Anthropic 双协议 + 思考等级落地）
  - `wxbot/brain/learned.py` —— 自学习技能库（data/learned_skills.json，GUI 可逐条开关）
  - `wxbot/brain/learner.py` —— 技能自学习器（AI 复盘聊天记录 → 技能条目）
  - `wxbot/brain/memory.py` —— 短期记忆（data/chat_memory.json）
    ⚠ 会话名**必须归一化后作 key**（否则「老王！」/「老王!」= 两份记忆，模型只看到一半对话）；
    入库前要清洗角标数字与时间前缀。迁移脚本 `tools/migrate_memory.py`。
  - `wxbot/brain/llm.py` —— LLM 引擎（本地 Ollama / LM Studio 与云端 OpenAI 兼容服务）
  - `wxbot/gui.py` —— 图形界面（保存配置按模板重写 config.toml；未暴露字段自动继承）
- 工具：`tools/probe_uia*.py|ps1`、`tools/smoke_vision.py`、`tools/test_capture.py`、
  `tools/test_wgc.py`、`tools/check_local_llm.py`
- GUI 启动：双击 `启动界面.bat`（等价于用 uv base pythonw 无窗口启动）。
  ⚠ 不要从后台直接 `.venv\Scripts\pythonw.exe -m wxbot gui`——uv 的启动器会弹一个
  Windows Terminal 控制台窗口，且关掉那个窗口会把 GUI 一起杀掉。

## GUI 陷阱（踩过）

PySide6 滚轮：`QComboBox` / `QSpinBox` / `QSlider` 默认会**用滚轮改值**（在 ScrollArea 里尤其坑，
鼠标一扫模型就换了）。已用 `_NoWheelFilter` 拦截，滚动量转交外层滚动区域。
两个易错点：① 方向 —— `delta > 0`（向上滚）对应滚动条值**增大**；
② 不能一遇到有 `verticalScrollBar` 的控件就返回（短文本框 `maximum == 0` 滚不动，要继续往上找）。

**⚠ 文本框必须"页面优先"（v2.6.2 修，用户报的"滚动窗口就闪"）**：
早先规则是"内容溢出就把滚轮放行给文本框"，于是内容在**光标底下**移动时，
光标下的控件每滚一格就换一个，两个滚动条交替接管 → 闪动。
现在：**从 `obj.parentWidget()` 开始找可滚动容器**（跳过文本框自己，它自带滚动条），
页面真滚不动了才放行给文本框。行为单向固定，不再跳变。

**⚠ `_scroll_ancestor` 必须确认滚动条真的动了**：
页面到底时 `setValue(value + delta)` 会被 Qt **静默钳位**，值没变。
只判断"找到滚动条就 return True"会导致事件被吞掉、文本框永远拿不到滚轮。

写滚轮相关测试时注意：造控件树要**让内容真的比视口高**（`addStretch` 撑不出滚动条，
要用固定高度的控件），否则页面压根滚不动，测试会假红。

PySide6 里给 QGroupBox 建了子控件后，**必须把 QGroupBox 加进某个布局/父窗口**，
否则它会被 Python GC 回收，连带子控件一起销毁，报
`libshiboken: Internal C++ object already deleted`（症状是 init 阶段就崩）。

QGroupBox 做「卡片」样式时，要给 `QGroupBox::title` 设 `background-color: <卡片底色>`，
否则卡片边框会从标题文字中间穿过去，看起来像被划掉。

未显式设 `objectName` 的 QPushButton 在深色 QSS 下会退回系统原生外观，对比度极低；
要补一条通用 `QPushButton {...}` 兜底样式。日志富文本用 `QTextEdit`（`QPlainTextEdit` 无 setHtml）。
改完样式务必**逐页截图自查**（`widget.grab().save(path)`）。

QGroupBox 只能配**竖向**布局：`group.setLayout(QHBoxLayout())` 之后往
`group.layout().addWidget(...)` 加的"正文"会被当成标题行的同级控件摆到**右边**并溢出卡片。
想做成"标题一行 + 可折叠正文"，正确写法是外层 `QVBoxLayout` + 把标题行包成一个子 `QWidget`
（见「模型」页的"高级设置"）。

离屏截图（`QT_QPA_PLATFORM=offscreen`）**没有中文字体**，截出来全是 □，
看不出任何排版问题 —— 视觉自查必须用真实显示（不设 `QT_QPA_PLATFORM`）跑 `shot_gui.py`。

⚠ 用 `Start-Process ... -WindowStyle Hidden` 启动 GUI 会把 `SW_HIDE` 传给 Qt 主窗口：
进程在跑、窗口标题也存在，但 `IsWindowVisible=False`，人眼完全看不到。
后台启动 GUI **不要加这个参数**。

## 配置热更新：别 stop/start（v2.6.5）

**换配置时不要「停掉 Runner 再建一个」** —— 每建一个新 Runner 都会走到 WGC 抓屏，
而 Windows 图形捕获在「同一窗口反复建/销抓屏会话」这个模式上**原生就会崩**。

faulthandler 实测的崩溃栈（0xC0000005）：

```
Current thread:  windows_capture/__init__.py:241 in start   ← 崩的是抓屏线程自己
Thread (runner): capture.py done.wait()                      ← 正等着这一次抓屏
Thread (main):    runner.py:154 in stop → Thread.join()
```

**第 2 轮启动必崩**，也就是说连用户手动「关总开关再开」都会闪退 —— ��是既有隐患。

正确做法：`Runner.apply_config(cfg)` **就地**替换配置对象。
`_loop` 每轮都读 `self._config`，所以下一轮 poll 就用新模型，既不停线程也不碰 WGC。

`apply_config` 必须**一路换到底**，换一半等于没换（模型名变了、实际生成还是旧的）：

| 持有者 | 字段 |
| --- | --- |
| Runner | `_config` |
| ReplyPipeline | `_config` |
| SkillRegistry | `_skills`（按 `config.skills` 重建） |
| SafetyGateway | `_safety` / `_whitelist` / `_quiet_spans` |

另外 `grab_frame` 也加了保活 + 全局串行 + 硬闸（见 `wechat/capture.py`），
但那是兜底，**真正的修复是不再反复重建 Runner**。

回归：`tests/test_runner.py::SaveRestartsRunnerTests`、
端到端 `tools/check_save_applies_model.py`（真实 MainWindow 上换两次模型）。

## 改了配置为什么还在用旧模型（v2.6.4 修）

**Runner 存的是 cfg 引用，不是拷贝**（`self._config = config`）。
所以问题不在 Runner 缓存了旧值，而在 **GUI 的 `_on_save` 写完磁盘就完事**——
它构造了一个全新的 `AppConfig`（`_collect_config()` 的返回值）写进文件，
**却从没把这个新对象告诉正在运行的 Runner**。Runner 手里还是启动时那个旧对象。

早先的提示是"配置已保存；正在运行的循环仍用旧配置，重新启动开关后生效"——
诚实，但没人会记得。于是用户换了模型、点了保存，看到的仍是旧模型在跑。

现在 `_on_save` 检测到 Runner 在跑就 **stop + 用新 cfg 重建 + start**，
换模型不用重启程序。要点：

- 重建要用 `_collect_config()` 拿到的**新对象**，不能复用旧 cfg（那就等于什么都没做）。
- 重建失败要 `run_switch.setChecked(False)`，否则界面显示"运行中"而实际没跑。
- `Runner.start()` 会重置 `RunnerStats`，计数器归零 —— 这是可接受的（配置本来就变了）。
- 同样地，**「测试生成」「立即试一次」等用 `_collect_config()` 的路径本来就是对的**，
  只有 `_on_save` 漏了。别把"配置什么时候生效"搞混：
  凡是**当场**用 `_collect_config()` 的操作（试生成、试一次、启动）都立刻生效；
  **只有保存到磁盘又不重建 Runner** 的路径会滞后。

回归测试 `tests/test_runner.py::SaveRestartsRunnerTests`。

## 滚轮过滤器装在哪些控件上（v2.6.3）

`install_wheel_guard` 除了 guarded 类型（下拉框 / 数字框 / 滑块 / 文本框），
**还给每个 `QScrollArea` 里的 page widget 装上**。

因为页面上大部分区域是**空白**（卡片之间、标签之间），那里没有 guarded 控件，
wheel 事件没人接管 —— 而 Qt 默认的 `QScrollArea` 滚轮路径在 PySide6 下不可靠
（实测：全新的 `QScrollArea` + 干净的 wheel 事件送 viewport，**不滚**）。
装了之后安装数从 31 涨到 37（6 个页面 widget）。

排查工具 `tools/debug_page_wheel.py`（跑遍 6 页看各控件的滚轮路径）。

## 降低"机器特征"的既有措施（改动前请确认不要破坏）

- 回复随机延迟（config `safety.min_reply_delay_sec` / `max_reply_delay_sec`，默认 2~6s）
- 三级限速 + 静默时段 + 熔断（`safety` 段）
- 点击坐标**随机抖动 + 平滑移动**（`_do_send` 里的 `self._rng`；不要改回固定像素点）
- 粘贴后按文本长度停顿再回车（模拟打字节奏）
- 绝不主动发起对话；群聊默认要求 @（group_policy）

## 人设（persona）——已独立成页

配置在 `[skills.persona]`：`identity/tone/formality/length/emoji/catchphrases/avoid`。
提示词拼装入口：`brain/skills.py: build_persona_prompt()` + `SkillRegistry.build_system_prompt()`。
人设页预览、「试生成」、真实回复都走同一条路径 —— 改动时务必保持"预览 = 实际注入"。

**⚠️ 不许暴露 AI 身份必须是硬性规则**（`MANDATORY_RULES`），永远追加在系统提示词**末尾**：
把它放进可编辑的提示词里，用户一改就容易写出「你是代回复助手，但不要暴露身份」
这种自相矛盾的话，模型就会自曝（实测踩过）。
默认提示词 `DEFAULT_BASE_PROMPT` 也不能自称"代回复助手"。

自检：`tools/check_persona_identity.py`（是否泄漏 AI 身份）、`tools/compare_persona_models.py`（换模型对比）。

### 系统提示词与人设的分工（v2.3.1）

最终注入顺序固定：`默认提示词 → system_prompt（留空则跳过）→ 各技能 → MANDATORY_RULES`。
所以**日常只改人设页**，`config.toml` 的 `[llm].system_prompt` 保持空字符串。

它已被收进「模型」页**默认折叠的「高级设置」**（`gui.py` 的 `adv_group`），
并带实时冲突检测 `_check_sys_prompt_conflict()`：命中
`助手/机器人/AI/代回复/程序/模型` 任一字眼就弹橙色警告。
新增风险词时同步改这个列表；**不要**把 system_prompt 重新挪回主区域。

自检：`tools/check_sys_prompt_conflict.py`。

## 模型参数自动预填（v2.4，改动前必读）

「模型」页的**上下文 / 输入模态 / 思考等级 / 最大输出**会被「按名称自动预填」整体覆盖。
这条链路踩过两次，**改之前先看这里**：

1. **拉列表 ≠ 改参数。** `_on_models_ok` 只允许在**当前模型真的变了**时调
   `_on_model_selected()`。早先它在 `blockSignals` 填充下拉框之后又无条件重跑了一遍
   （而且跑两次），导致点一下「获取模型列表」就把用户手工勾的「图片」抹掉。
   信号已经 `blockSignals`，**不要再手动补调**。
2. **本地厂商不能短路规则表。** `lookup_model_meta` 里 `provider.local` 分支只覆盖
   **上下文**（固定 8K 保守值），模态 / 思考等级仍走 `_RULES`。
   早先直接 `return ("text",)`，把整张表作废，`minicpm-v` / `qwen2-vl` 全被判成不支持图片。
3. **强视觉标识优先于家族默认值。** `_VISION_RE`（vl / vision / omni / llava / internvl /
   `-v-<数字>`）在家族规则**之后**做兜底升级，否则 `^llama-3` 会把 `llama-3.2-vision` 否掉。
4. **editable QComboBox 的 `setCurrentText()` 不触发 `currentIndexChanged`**
   （只改输入框文字、index 不动）。所以"手输模型名"不会触发预填，只有真从下拉里选才会。
   测试里要模拟用户点选必须用 `setCurrentIndex()`。

排查工具：`tools/check_model_modalities.py`（比对模型库与名称元数据）、
`tools/fix_model_modalities.py [--apply]`（只修 modalities，已备份）。
回归测试：`tests/test_gui_model_fetch.py`、`tests/test_providers.py::LocalModelMetaTests`。

## 聊天气泡判向的调试与测试（v2.4.1）

三个工具，改阈值前**先跑第一个看真实数据**：

```powershell
.\.venv\Scripts\python.exe tools\debug_bubble_boxes.py    # 打印原始 OCR 框 + 垂直间距
.\.venv\Scripts\python.exe tools\debug_bubble_sender.py   # 打印合并后的气泡 + 最终判定
```

写气泡相关测试时注意两条（都踩过）：

1. **假 OCR 的坐标必须贴近真实布局。** 早期测试把"对方气泡"放在聊天区 5% 处，
   比微信实际（≈24%，138/568）夸张太多，结果被"左边缘碎片过滤"正确地丢掉了 ——
   测试红了不是代码错，是测试在验证一个不存在的场景。
2. **假 OCR 的每行要排在不同的 y 上。** 现在会合并垂直相邻的行；
   全堆在同一个 y 会被当成一条换行消息合并成一条气泡。

回归测试：`tests/test_bubbles.py::WrappedBubbleTests`。

## 生成失败的重试与熔断（v2.5.0，改动前必读）

真实症状（用户日志）：模型一直连不上时，日志每 34 秒重复一次
「识别到新消息 ← 你好 / 生成失败 timed out」，**无限循环**；被网关拦截的
「微信团队」也一轮轮重复上报。两个原因：

1. **`gateway.note_failure()` 以前只在"发送失败"时调用**，生成失败不计数 ——
   `safety.auto_trip_on_failures` 形同虚设。现在生成失败也会 `note_failure()`，
   成功发送则 `note_success()`。
2. **没有任何重试上限**。现在 `Runner` 按「会话+文本」指纹记住处理进度
   （`_decisions` / `_attempts` / `_retry_after`）：
   - 拦截 / 跳过 / 发送失败 = **终态**，同一条不再重复处理；
   - 生成失败 = 退避重试 `RETRY_BACKOFF_SEC`，超过 `MAX_GENERATE_ATTEMPTS` 次
     就记为放弃并**打日志**，**新消息不受影响**照常处理。
   - `stop()` 会清空这三张表，重启后重新开始。

**不要**用「清空 `_retry_after`」的方式在生产代码里绕过退避 ——
那只是测试里模拟"时间过去了"的手法。

## OCR 区域补白（v2.6.0 性能，实测提速 2×）

**为什么**：RapidOCR 预处理时会把输入的**短边**放大到 `limit_side_len`（默认 736）。
一块"扁长"的区域因此被成倍放大 —— 标题栏 320x45（长宽比 7:1）实测 **575ms**，
同样内容补白成正方形只要 **105ms**。慢的是凭空多出来的那一大片空白，
跟像素量无关（320x320 比 320x45 还大，却快 5.5 倍）。

**做法**：所有 OCR 调用统一走 `VisionClient._ocr_region(region, need_coords=...)`，
它会先 `pad_for_ocr()` 补成正方形（比例已正常的区域原样返回，不浪费）。

三个必须记住的点：

1. **补白会平移坐标。** `read_chat_bubbles` 靠 `center_x` 判"谁发的"，
   所以它必须传 `need_coords=True` 把偏移扣掉，**否则会误判 → 重复回复**。
2. **填色必须按通道分别取中位数**：`tuple(int(np.median(region[:,:,c])) for c in ...)`。
   写成 `int(np.median(region))` 会把 RGB 混在一起求中位数，
   深色底 `(12,20,28)` 被算成灰色 `(20,20,20)`（自己踩过）。
3. **测试夹具别靠"图片高度"猜区域**。补白会改变高度，`test_send_flow.py` 早先
   就是靠 `height<=60 是标题栏` 判区域的，补白后全错。
   现在改成给三个区域涂不同底色、按中位色识别 —— 颜色是内容属性，补白不会改。

实测收益（811x565 窗口，5 轮平均）：

| 环节 | 优化前 | 优化后 |
| --- | --- | --- |
| 读标题 | 601 ms | **124 ms** |
| 读聊天气泡 | 333 ms | 235 ms |
| 读会话列表 | 258 ms | 144 ms |
| **整轮 poll** | **1175 ms** | **596 ms** |

剖析工具：`tools/profile_cycle.py`（各环节耗时）、`tools/profile_ocr_region.py`（补白前后对比）。

## 观测数据：上下文占用与思考过程（v2.6.0）

「运行」页要显示这两样，所以观测数据**必须一路透传到界面**，改动时别在中间截断：

```
模型响应 usage/reasoning_content
  → LLMResult (brain/llm.py)        prompt_tokens / completion_tokens / reasoning / context_length
  → PipelineResult (brain/pipeline.py)  同样四个字段 + context_ratio / context_display
  → RunnerStats (runner.py)         context_used / context_total / last_reasoning
  → gui._update_context_display()   占用条 + 「最近一次思考过程」
```

要点：

- `LLMEngine.generate()` **保持返回 str**（很多调用方和测试依赖它）；
  带元信息的走 `generate_detailed()` → `LLMResult`。改的时候别把 `generate` 的签名改了。
- 思考内容在 OpenAI 兼容层叫 `reasoning_content`，Claude 在 `thinking` 块里，两个都要读。
- Runner 额外发一个 `kind="thinking"` 的事件，日志里用 `🧠` 显示摘要；
  完整内容在 `event.data["reasoning"]`。
- `_generate()` 允许注入的测试生成器返回**纯字符串**，要包成 `LLMResult`（向后兼容）。

## 记忆只记"真的处理了"的消息（v2.5.1，改动前必读）

**不要**在 `ReplyPipeline.handle()` 的第 2 步（取历史之后、生成之前）就写记忆。
早期版本写在那里，结果**每次生成失败/超时都会把同一条用户消息再塞一遍**：
重试 3 次后提示词里就有 4 条「你好」，越重试越长越乱。
真实日志（LM Studio 19:40~19:42）里能直接看到消息列表从 2 条「你好」涨到 4 条。

现在统一挪到第 6 步：**只有真的产出回复了才记账**。失败/跳过/拦截都不写。

排查工具：

```powershell
.\.venv\Scripts\python.exe tools\check_memory_hygiene.py        # 找泄露身份/截断半句/重复条目
.\.venv\Scripts\python.exe tools\clean_memory.py [--apply]      # 清理（自动备份）
```

**记忆里的旧回复会被当成 few-shot 示例喂回模型** —— 所以修复前那些
「我不是任何人，只是个代回复助手呢」必须在清理时删掉，
否则模型会照着学，继续自称助手（实测：模型在 reasoning 里写
"the model previously violated rules (admitting to be an assistant)"）。

## 本地模型慢 / 超时的排查（v2.5.0）

```powershell
.\.venv\Scripts\python.exe tools\check_local_llm_speed.py    # 各模型实际耗时
.\.venv\Scripts\python.exe tools\check_local_llm_timeout.py  # 复现程序真实请求
.\.venv\Scripts\python.exe tools\probe_qwen_thinking.py      # qwen3.5-9b 到底要多久
```

**先看 LM Studio 的生成日志，别急着改超时。** 判读要点：

- `n_gen` 一直涨、`tg = 13~14 t/s`，但 `content` 始终是 `""`、
  `reasoning_content` 越来越长 → **模型在思考，不是卡死**。
  此时 `Client disconnected. Stopping generation...` 是**我们自己的超时**踢的。
- 根因是 `max_tokens: 8192` 给思考留了太多空间（实测 30 秒只够 ~400 reasoning token，
  永远轮不到正文）。

### ⚠ qwen/qwen3.5-9b 关不掉思考（2026-10-01 实测；用户确认仍要用它）

**能发的都试过了，模型一律无视：**

| 写法 | 结果 |
| --- | --- |
| `chat_template_kwargs: {"enable_thinking": false}` | **参数被 LM Studio 接受，模型照想不误** |
| 顶层 `enable_thinking: false` | 无效 |
| 系统提示词末尾加 `/no_think` | 无效（Qwen3 老办法，新版不认） |
| `reasoning_effort` | 无效 |

**不限时实测，它其实能答对，只是要 1~5 分钟，而且波动极大：**

| 消息 | 耗时 | 思考量 | 结果 |
| --- | --- | --- | --- |
| 你好 | 167 s | 2167 token | ✅ |
| 你是谁 | 196 s | 2530 token | ✅ |
| 你好 | 78 s | 3343 字 | ✅ |
| 你是谁 | **291 s** | 12906 字 | ✅ |

**结论**：`timeout_sec` 必须 **600 秒**（291 秒只差 9 秒就会把 300 打爆）。
生成期间主循环**阻塞**，这段时间不识别新消息 —— 这是选这个模型的固有代价，
用户知情后仍选择保留，**别再劝换**。

对照（同一份 LM Studio 日志）：

- `gemma-4-e2b` 不思考时：prompt 341ms + eval 162ms = **总计 503ms**
- `minicpm-v-4.6`：2.1~2.9s，思考 112~136 token
- `qwen3.5-9b`：2200~2500 thinking token，13.5 t/s → **167~196 秒**

排查本地模型超时，先看 LM Studio 里加载了几个模型 —— 8GB 显卡只该常驻 1~2 个
（但这不是主因，13.5 t/s 的生成速度其实很健康）。

> 跑测试前先确认没有后台探测在占用 GPU —— 资源被抢时会有 3~4 项计时相关测试抖动。

## 下一步（按顺序）

1. 托盘常驻 + 全局急停热键（停止开关之外的"一键刹车"）
2. 用「文件传输助手」做 dry_run → auto 的完整回归
3. PyInstaller 打包成 exe

（发送器已完成：会话切换 → 标题校验 → 输入 → 输入框校验 → 回车 → 发送后校验）
