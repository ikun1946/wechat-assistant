"""wxbot 图形界面：模型 / 回复速度 / 白名单 / 技能 设置与状态查看。

启动：python -m wxbot gui
（也可以用 pythonw.exe -m wxbot gui 启动，不弹控制台窗口。）
"""

from __future__ import annotations

import sys
import traceback
from ctypes import wintypes
from collections import deque

try:
    from PySide6.QtCore import (
    QAbstractNativeEventFilter,
    QEvent,
    QObject,
    Qt,
    QThread,
    Signal,
)
    from PySide6.QtWidgets import (
        QAbstractSpinBox,
        QApplication,
        QCheckBox,
        QComboBox,
        QDoubleSpinBox,
        QFormLayout,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMenu,
        QMessageBox,
        QPlainTextEdit,
        QProgressBar,
        QPushButton,
        QScrollArea,
        QSlider,
        QSpinBox,
        QStackedWidget,
        QSystemTrayIcon,
        QTableWidget,
        QTableWidgetItem,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:  # pragma: no cover - 环境缺依赖时的友好提示
    raise SystemExit("未安装 PySide6：请运行  uv pip install pyside6-essentials") from exc

from .brain.learned import LearnedStore
from .brain.learner import ConversationSample, SkillLearner
from .brain.llm import LLMEngine
from .brain.memory import ChatMemory
from .brain.model_store import ModelEntry, ModelStore
from . import __version__
from .providers import (
    MODALITIES,
    MODALITY_LABELS,
    THINKING_LABELS,
    THINKING_LEVELS,
    all_providers,
    get_provider,
    lookup_model_meta,
)
from .config import (
    DEFAULT_CONFIG_PATH,
    EMOJI_LABELS,
    EMOJIS,
    LENGTH_LABELS,
    LENGTHS,
    TONE_LABELS,
    TONES,
    AppConfig,
    ConfigError,
    GroupPolicySkillConfig,
    LLMConfig,
    LearnedSkillConfig,
    MemorySkillConfig,
    PersonaSkillConfig,
    PROJECT_ROOT,
    ReplyConfig,
    ReplyRule,
    SafetyConfig,
    SafetySkillConfig,
    SkillsConfig,
    UiConfig,
    WhitelistConfig,
    dump_config_text,
    load_config,
    load_secret_api_key,
    parse_config_text,
    save_secret_api_key,
)
from .journal import Journal
from .runner import Runner, build_default_runner
from .theme import (
    THEME_DARK,
    THEME_LIGHT,
    Card,
    CollapsibleCard,
    StatCard,
    StatusPill,
    Switch,
    build_qss,
    theme as get_theme,
)
from .wechat import window_check

APP_TITLE = "wxbot — 微信自动回复助手（安全优先）"

# 永远不允许用滚轮改动自身（避免误改下拉框选中项 / 数字框数值 / 滑块）
_WHEEL_GUARDED_TYPES = (
    QComboBox,
    QAbstractSpinBox,   # QSpinBox / QDoubleSpinBox
    QSlider,
)

# 多行文本框：只有"内容装不下"时才允许在框内滚动；
# 装得下时把滚轮交回页面（否则短文本框会让整页滚不动）
_WHEEL_GUARDED_TEXT_TYPES = (QPlainTextEdit, QTextEdit)


class _NoWheelFilter(QObject):
    """滚轮一律先滚**外层页面**，页面到底了才给控件自己。

    这样既不会出现"悬停在下拉框上整页滚不动"，也不会误改下拉框选中项 / 数字框数值。

    ⚠ 为什么文本框也必须"页面优先"（v2.6.2 修，用户报的闪动 bug）：
    早先的规则是"文本框内容溢出就放行给它"。但内容是在**光标底下**移动的 ——
    滚一下页面，光标下就换成了另一个内容溢出的文本框；下一格滚轮它就抢走，
    页面纹丝不动；再滚一下又变回页面……两个滚动条方向相反地交替接管，
    视觉上就是"滚动窗口就闪"。

    规则改成**单向**：只要页面还能滚就滚页面，页面到底/到顶了才给文本框。
    行为固定下来，就不会有交替，也就不会闪。
    """

    def eventFilter(self, obj, event):  # noqa: N802 (Qt 命名)
        if event.type() != QEvent.Type.Wheel:
            return False
        delta = event.angleDelta().y() or event.pixelDelta().y()
        is_text = isinstance(obj, _WHEEL_GUARDED_TEXT_TYPES)
        # 例外：标了 wheelPriority=internal 的文本框永远自己滚（不应用页面优先）
        # —— 给实时日志这类"在页面底部、内容不断追加"的视图用，
        # 否则页面已经到底了再滚轮直接吞掉，体验是「页面动了日志没动」。
        if is_text and obj.property("wheelPriority") == "internal":
            return False
        # 页面优先：从**父级**开始找可滚动容器，跳过文本框自己
        # （文本框自带滚动条，从 obj 自身起找就会先命中它，永远滚不到页面）
        start = obj.parentWidget() if is_text else obj
        if self._scroll_ancestor(start, delta):
            return True
        # 页面已经到头，才允许在文本框内部滚（日志区这类长内容才看得完）
        if is_text and _can_scroll_inside(obj):
            return False
        return True  # 控件自己不再处理

    @staticmethod
    def _scroll_ancestor(obj: QWidget, delta: int) -> bool:
        """把 delta 交给最近的、有可用滚动条的祖先容器。

        ⚠ 方向（v2.6.7 修，用户报「鼠标下滚、页面却往上滚」）：
        Qt 的 `angleDelta().y() > 0` 表示**滚轮往前推**（向上看），
        这时应该看**更靠前**的内容 → 滚动条值**减小**。
        所以这里必须 `value - delta`；早先写成 `value + delta` 方向正好反了 ——
        滚轮往下拉本该看更靠后的内容，滚动条却减小，页面就往上跑。

        注意：不能一遇到有 verticalScrollBar 的控件就返回 —— 例如 QPlainTextEdit
        自己也提供滚动条，但内容不满时 maximum == 0（滚不动），此时应继续往上找。

        也必须确认滚动条**真的动了**：页面已经到底时 `setValue` 会被 Qt 静默钳位
        （值没变）。若此时就返回 True，上层会以为「页面滚过了」，于是把滚轮吞掉，
        文本框就永远拿不到滚轮（v2.6.2 实测发现）。
        """
        node: QWidget | None = obj
        while node is not None:
            getter = getattr(node, "verticalScrollBar", None)
            if callable(getter):
                try:
                    scroll_bar = getter()
                except (TypeError, RuntimeError):
                    scroll_bar = None
                if scroll_bar is not None and scroll_bar.maximum() > scroll_bar.minimum():
                    before = scroll_bar.value()
                    scroll_bar.setValue(before - delta)
                    if scroll_bar.value() != before:
                        return True
                    # 滚不动（到顶 / 到底）→ 继续往上找别的容器
            node = node.parentWidget()
        return False


def _can_scroll_inside(widget: QWidget) -> bool:
    """文本框内容是否溢出（溢出了才值得在框内滚）。"""
    getter = getattr(widget, "verticalScrollBar", None)
    if not callable(getter):
        return False
    try:
        bar = getter()
    except (TypeError, RuntimeError):
        return False
    return bar is not None and bar.maximum() > bar.minimum()


# ---- 托盘与全局热键 ----
TRAY_UID = 0x7731
HOTKEY_ESTOP_ID = 0xB001


class _HotkeyFilter(QAbstractNativeEventFilter):
    """把 Windows 的 WM_HOTKEY 消息转给窗口处理。"""

    def __init__(self, window):
        super().__init__(window)
        self._window = window

    def nativeEventFilter(self, event_type, message):  # noqa: N802 (Qt 命名)
        try:
            from .tray import WM_HOTKEY

            if event_type in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY and (msg.wParam & 0xFFFF) == HOTKEY_ESTOP_ID:
                    self._window._emergency_stop()
        except Exception:  # noqa: BLE001
            pass
        return False, 0


def install_wheel_guard(widget: QWidget) -> int:
    """给 widget 及其所有子控件装上滚轮过滤，返回安装数量。

    ⚠ v2.6.3 修（用户报"整个页面滚动有问题"）：
    除了 guarded 类型，**还给所有直接放在 QScrollArea 里的页面 widget
    也装上过滤器**。空白的页面光标下没有 guarded 控件，wheel 没人接——Qt 默认
    QScrollArea 滚动路径在 PySide6 / 某些事件投递下不工作。

    装了过滤器之后，无论鼠标停在页面哪里（控件上还是纯空白），
    都能走 `_scroll_ancestor` 让滚动条动起来。
    """
    guard = _NoWheelFilter(widget)
    count = 0
    targets = set()
    for child in widget.findChildren(QWidget):
        if isinstance(child, _WHEEL_GUARDED_TYPES + _WHEEL_GUARDED_TEXT_TYPES):
            targets.add(child)
    # 找所有 QScrollArea，把它们装的 page widget 也加进来
    for scroll in widget.findChildren(QScrollArea):
        page_widget = scroll.widget()
        if page_widget is not None:
            targets.add(page_widget)
    for target in targets:
        target.installEventFilter(guard)
        count += 1
    return count

NAV_ITEMS = (    ("run", "◉", "运行", "控制自动对话的启停，查看识别与回复情况"),
    ("reply", "≈", "回复与速度", "调整拟人化延迟与限流，配置关键词规则"),
    ("persona", "✧", "人设", "AI 是谁、怎么说话——决定回复像不像你"),
    ("model", "◈", "模型", "选择厂商与模型，逐模型配置上下文 / 模态 / 思考等级"),
    ("skills", "✦", "技能", "让 AI 更懂你的说话方式，并守住安全边界"),
    ("logs", "▤", "日志", "本地审计日志，可回溯每一次决策"),
)


def _escape(text: str) -> str:
    """HTML 转义 —— 模型思考过程要放进 QTextEdit.setHtml。"""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _render_reasoning(text: str) -> str:
    """把思考过程渲染成可读 HTML。

    模型思考里满是 markdown 粗体（`**Analyze**`），原样显示是一堆星号，
    这里做个**最小**渲染：只处理 `**粗体**`，其余保持纯文本。
    """
    import re as _re

    escaped = _escape(text)
    escaped = _re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
    return escaped.replace("\n", "<br>")


def _split_by_chars(text: str) -> list[str]:
    """按中英文逗号/顿号/分号/换行切分，去空白。"""
    parts: list[str] = []
    current = ""
    for ch in text:
        if ch in ",，、;\n\r":
            if current.strip():
                parts.append(current.strip())
            current = ""
        else:
            current += ch
    if current.strip():
        parts.append(current.strip())
    return parts


def _parse_rules_text(text: str) -> tuple[ReplyRule, ...]:
    rules: list[ReplyRule] = []
    for index, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        if "=>" not in line:
            raise ValueError(f"规则第 {index} 行缺少「=>」（示例：在吗,在么 => 在的～）")
        left, _, right = line.partition("=>")
        keywords = tuple(k for k in _split_by_chars(left) if k)
        reply = right.strip()
        if not keywords or not reply:
            raise ValueError(f"规则第 {index} 行不完整：关键词或回复为空")
        rules.append(ReplyRule(keywords=keywords, reply=reply))
    return tuple(rules)


def _make_card(title: str, subtitle: str = "", *, colors: dict | None = None):
    """普通内容卡：标题 +（可选）右侧说明，返回 (卡片, 内容布局)。"""
    alpha = (colors or {}).get("shadow", 60)
    card = Card(shadow_alpha=alpha)
    box = QVBoxLayout(card)
    box.setContentsMargins(16, 13, 16, 13)
    box.setSpacing(10)
    head = QHBoxLayout()
    name = QLabel(title)
    name.setObjectName("CardTitle")
    head.addWidget(name)
    head.addStretch(1)
    if subtitle:
        sub = QLabel(subtitle)
        sub.setObjectName("Faint")
        head.addWidget(sub)
    box.addLayout(head)
    return card, box


def _format_rules(rules: tuple[ReplyRule, ...]) -> str:
    return "\n".join(f"{','.join(rule.keywords)} => {rule.reply}" for rule in rules)


class _RunnerBridge(QObject):
    """把 Runner 的后台事件安全地转发到 GUI 线程。"""

    event = Signal(object)

    def handle(self, event) -> None:  # 在 Runner 线程里被调用
        self.event.emit(event)


class _ListModelsWorker(QThread):
    succeeded = Signal(list)
    failed = Signal(str)

    def __init__(self, cfg: LLMConfig):
        super().__init__()
        self._cfg = cfg

    def run(self) -> None:
        try:
            models = LLMEngine(self._cfg).list_models()
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.succeeded.emit(models)


class _TestChatWorker(QThread):
    """模型连通性 + 生成能力自检。"""

    succeeded = Signal(str)
    failed = Signal(str)

    def __init__(self, cfg: LLMConfig):
        super().__init__()
        self._cfg = cfg

    def run(self) -> None:
        try:
            text = LLMEngine(self._cfg).test_chat("你好，请回复「测试成功」四个字。")
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.succeeded.emit(text)


class _PollOnceWorker(QThread):
    """「立即试一次」：只抓屏识别一轮，不启动循环。"""

    finished_with = Signal(list)
    failed = Signal(str)

    def __init__(self, cfg: AppConfig, poll_interval: float):
        super().__init__()
        self._cfg = cfg
        self._interval = poll_interval

    def run(self) -> None:
        try:
            runner = build_default_runner(self._cfg, poll_interval=self._interval)
            messages = runner.poll_once()
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
            return
        self.finished_with.emit(list(messages))


class _PersonaTestWorker(QThread):
    """用当前人设试生成一条回复（不改配置、不发送）。"""

    succeeded = Signal(str, str)  # (system_prompt, reply)
    failed = Signal(str)

    SAMPLE = "在吗？今天忙不忙呀"

    def __init__(self, cfg: AppConfig):
        super().__init__()
        self._cfg = cfg

    def run(self) -> None:
        try:
            from .brain.pipeline import DEFAULT_BASE_PROMPT
            from .brain.skills import ReplyContext, SkillRegistry

            learned = LearnedStore()
            registry = SkillRegistry(self._cfg.skills, learned)
            ctx = ReplyContext(chat_name="（试生成）", incoming_text=self.SAMPLE)
            base = self._cfg.llm.system_prompt.strip() or DEFAULT_BASE_PROMPT
            system_prompt = registry.build_system_prompt(ctx, base)
            reply = LLMEngine(self._cfg.llm).generate(
                self.SAMPLE, system_prompt=system_prompt, history=[]
            )
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
            return
        self.succeeded.emit(system_prompt, reply)


class _LearnWorker(QThread):
    succeeded = Signal(dict)
    failed = Signal(str)

    def __init__(self, cfg: AppConfig, chat: str | None = None, limit: int = 80):
        super().__init__()
        self._cfg = cfg
        self._chat = chat
        self._limit = limit

    def run(self) -> None:
        try:
            memory = ChatMemory()
            chats = [self._chat] if self._chat else memory.chats()
            if not chats:
                self.failed.emit("暂无聊天记录可学习：等主循环跑起来积累一些消息后再试")
                return
            samples = []
            for chat_name in chats:
                messages = memory.recent(chat_name, max(2, self._limit))
                if len(messages) >= 2:
                    samples.append(
                        ConversationSample(chat_name=chat_name, messages=tuple(messages))
                    )
            if not samples:
                self.failed.emit("聊天记录太少（每条会话至少需要 2 条消息）")
                return
            engine = LLMEngine(self._cfg.llm)
            learner = SkillLearner(LearnedStore(), generator=engine.generate)
            report = learner.learn_from(samples)
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.succeeded.emit(
            {
                "added": report.added,
                "duplicates": report.duplicates,
                "invalid": report.invalid,
                "total": report.total,
            }
        )


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(960, 720)
        self._worker: _ListModelsWorker | None = None
        self._test_worker: _TestChatWorker | None = None
        self._persona_test_worker: _PersonaTestWorker | None = None
        self._learn_worker: _LearnWorker | None = None
        self._poll_worker: _PollOnceWorker | None = None
        self._runner: Runner | None = None
        self._theme_name = THEME_DARK
        self._bridge = _RunnerBridge()
        self._bridge.event.connect(self._on_runner_event)
        self._loading_learned = False
        self._base_cfg = AppConfig()
        # 常驻应用：托盘 + 全局急停热键
        self._tray = None
        self._tray_run_action = None
        self._really_quit = False
        self._hotkey_hwnd = None
        self._native_filter = None
        self._first_run_notice = ""
        self._build_ui()
        self._load_into_form()
        self._refresh_status()
        self._build_tray()
        self._setup_hotkey()
        self._log_startup_diagnostics()
        if self._first_run_notice:
            self._append_run_log(self._first_run_notice)
            try:
                from .tray import show_tray_bubble

                show_tray_bubble(
                    int(self.winId()),
                    TRAY_UID,
                    "已生成默认配置",
                    "首次运行已自动创建 config.toml，请检查后保存。",
                )
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("Root")
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_sidebar())

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(22, 18, 22, 18)
        body_layout.setSpacing(12)
        body_layout.addLayout(self._build_header())

        self.stack = QStackedWidget()
        self._page_index: dict[str, int] = {}
        # VisionClient **只建一次**、反复复用（v2.6.5）。
        # 为什么：Runner 线程正卡在 `grab_bgr` 的 WGC 原生帧里时，如果 VisionClient
        # 被 GC 回收，原生句柄随之释放 → 硬崩 0xC0000005（实测：第 2 轮启停必崩）。
        # 复用还顺带带来两个好处：OCR 引擎只加载一次（启动更快），
        # 以及 `_last_replied_text` / `_claimed_text` 这些去重状态**跨重启保留** ——
        # 否则改一次配置就会清空记忆，有重复回复的风险。
        self._vision_client = None
        builders = {
            "run": self._tab_run,
            "reply": self._tab_reply,
            "persona": self._tab_persona,
            "model": self._tab_model,
            "skills": self._tab_skills,
            "logs": self._tab_logs,
        }
        for key, _glyph, _title, _desc in NAV_ITEMS:
            page = builders[key]()
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(page)
            self._page_index[key] = self.stack.count()
            self.stack.addWidget(scroll)
        body_layout.addWidget(self.stack, 1)
        root.addWidget(body, 1)

        self._select_page("run")
        self._apply_theme()
        # 控件不吃滚轮（避免误改下拉框/数值），滚动交给外层页面
        self._guarded_widgets = install_wheel_guard(self)

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(200)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(14, 18, 14, 16)
        layout.setSpacing(6)

        brand = QVBoxLayout()
        brand.setSpacing(0)
        name = QLabel("wxbot")
        name.setObjectName("BrandName")
        sub = QLabel("微信自动回复助手")
        sub.setObjectName("BrandSub")
        brand.addWidget(name)
        brand.addWidget(sub)
        layout.addLayout(brand)
        layout.addSpacing(16)

        self._nav_buttons: dict[str, QPushButton] = {}
        for key, glyph, title, _desc in NAV_ITEMS:
            button = QPushButton(f"  {glyph}   {title}")
            button.setObjectName("Nav")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, k=key: self._select_page(k))
            layout.addWidget(button)
            self._nav_buttons[key] = button

        layout.addStretch(1)

        save_btn = QPushButton("保存配置")
        save_btn.setObjectName("Primary")
        save_btn.clicked.connect(self._on_save)
        refresh_btn = QPushButton("刷新状态")
        refresh_btn.setObjectName("Ghost")
        refresh_btn.clicked.connect(self._refresh_status)
        layout.addWidget(save_btn)
        layout.addWidget(refresh_btn)

        version = QLabel(f"v{__version__} · 本地运行")
        version.setObjectName("Faint")
        layout.addWidget(version)
        return sidebar

    def _build_header(self) -> QVBoxLayout:
        block = QVBoxLayout()
        block.setSpacing(6)

        row = QHBoxLayout()
        row.setSpacing(10)
        titles = QVBoxLayout()
        titles.setSpacing(1)
        self.page_title = QLabel("运行")
        self.page_title.setObjectName("PageTitle")
        self.page_desc = QLabel("")
        self.page_desc.setObjectName("PageDesc")
        titles.addWidget(self.page_title)
        titles.addWidget(self.page_desc)
        row.addLayout(titles)
        row.addStretch(1)

        self.state_pill = StatusPill("● 已停止", "#8b93a7", "#1e232c")
        row.addWidget(self.state_pill)

        self.wechat_pill = StatusPill("微信窗口：检测中", "#8b93a7", "#1e232c")
        row.addWidget(self.wechat_pill)

        self.theme_btn = QPushButton("浅色")
        self.theme_btn.setObjectName("Ghost")
        self.theme_btn.setToolTip("切换深色 / 浅色主题")
        self.theme_btn.clicked.connect(self._on_toggle_theme)
        row.addWidget(self.theme_btn)
        block.addLayout(row)

        self.status_label = QLabel("（正在读取状态…）")
        self.status_label.setObjectName("Faint")
        self.status_label.setWordWrap(True)
        block.addWidget(self.status_label)
        return block

    def _select_page(self, key: str) -> None:
        index = self._page_index.get(key, 0)
        self.stack.setCurrentIndex(index)
        for name, button in self._nav_buttons.items():
            button.setChecked(name == key)
        for item_key, _glyph, title, desc in NAV_ITEMS:
            if item_key == key:
                self.page_title.setText(title)
                self.page_desc.setText(desc)
                break

    # ------------------------------------------------------------- 主题
    def _current_theme_name(self) -> str:
        return getattr(self, "_theme_name", THEME_DARK)

    def _on_toggle_theme(self) -> None:
        self._theme_name = (
            THEME_LIGHT if self._current_theme_name() == THEME_DARK else THEME_DARK
        )
        self._apply_theme()

    def _apply_theme(self) -> None:
        colors = get_theme(self._current_theme_name())
        self.setStyleSheet(build_qss(colors))
        for widget in self.findChildren(Switch):
            widget.apply_theme(colors)
        for card in self.findChildren(CollapsibleCard):
            card.apply_theme(colors)
        self.theme_btn.setText("浅色" if self._current_theme_name() == THEME_DARK else "深色")
        # 状态胶囊跟随主题
        self._restyle_pills()
        if hasattr(self, "model_status"):
            self._refresh_model_table()

    def _restyle_pills(self) -> None:
        colors = get_theme(self._current_theme_name())
        running = self._runner is not None and self._runner.running
        fg = colors["success"] if running else colors["muted"]
        self.state_pill.set_colors(fg, colors["surface2"])
        self.state_pill.setText("● 运行中" if running else "● 已停止")
        windows = window_check.find_wechat_windows()
        if windows:
            self.wechat_pill.set_colors(colors["success"], colors["surface2"])
            self.wechat_pill.setText("微信窗口：已检测")
        else:
            self.wechat_pill.set_colors(colors["warn"], colors["surface2"])
            self.wechat_pill.setText("微信窗口：未检测到")

    def _tab_run(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        # ---- 总开关 ----
        control = QGroupBox()
        control_layout = QHBoxLayout(control)
        control_layout.setContentsMargins(20, 16, 20, 16)
        control_layout.setSpacing(18)

        left = QVBoxLayout()
        left.setSpacing(4)
        title = QLabel("自动对话总开关")
        title.setObjectName("CardTitle")
        left.addWidget(title)
        desc = QLabel(
            "启动后才会抓屏识别微信、走安全网关与回复流程；停止则立即停工，不做任何后续动作。"
        )
        desc.setObjectName("PageDesc")
        desc.setWordWrap(True)
        left.addWidget(desc)
        self.run_progress = QLabel("")
        self.run_progress.setObjectName("Faint")
        left.addWidget(self.run_progress)
        control_layout.addLayout(left, 1)

        switch_box = QVBoxLayout()
        switch_box.setSpacing(6)
        switch_box.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.run_switch = Switch(
            checked=False, colors=get_theme(self._current_theme_name()), width=62, height=32
        )
        self.run_switch.toggled.connect(self._on_run_switch)
        self.run_state_label = QLabel("已停止")
        self.run_state_label.setObjectName("Muted")
        self.run_state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        switch_box.addWidget(self.run_switch, 0, Qt.AlignmentFlag.AlignRight)
        switch_box.addWidget(self.run_state_label)
        control_layout.addLayout(switch_box)
        layout.addWidget(control)

        # ---- 指标卡 ----
        stats_row = QHBoxLayout()
        stats_row.setSpacing(12)
        self.stat_received = StatCard("识别到", "0", "条新消息", "#5b8cff")
        self.stat_replied = StatCard("拟回复", "0", "待发送", "#fbbf24")
        self.stat_sent = StatCard("已发送", "0", "真实发出", "#34d399")
        self.stat_blocked = StatCard("拦截", "0", "安全网关拦下", "#f87171")
        for card in (self.stat_received, self.stat_replied, self.stat_sent, self.stat_blocked):
            stats_row.addWidget(card)
        layout.addLayout(stats_row)

        # ---- 上下文窗口占用 + 模型思考 ----
        layout.addWidget(self._build_context_card())

        # ---- 参数 + 日志 ----
        bottom = QHBoxLayout()
        bottom.setSpacing(14)

        params = QGroupBox("运行参数")
        params_layout = QVBoxLayout(params)
        params_layout.setSpacing(10)

        interval_row = QHBoxLayout()
        interval_row.addWidget(QLabel("识别间隔"))
        self.poll_interval_spin = QDoubleSpinBox()
        self.poll_interval_spin.setRange(1.0, 60.0)
        self.poll_interval_spin.setDecimals(1)
        self.poll_interval_spin.setSingleStep(0.5)
        self.poll_interval_spin.setValue(3.0)
        self.poll_interval_spin.setSuffix(" 秒")
        self.poll_interval_spin.setToolTip("每次抓屏识别的间隔；越短越灵敏，但抓屏更频繁")
        self.poll_interval_spin.setFixedWidth(120)
        interval_row.addWidget(self.poll_interval_spin)
        interval_row.addStretch(1)
        params_layout.addLayout(interval_row)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("运行模式"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("仅记录（dry_run：不发送，只记录拟回复）", "dry_run")
        self.mode_combo.addItem("全自动（auto：真实发送）", "auto")
        mode_row.addWidget(self.mode_combo, 1)
        params_layout.addLayout(mode_row)

        hint = QLabel(
            "建议先用 dry_run 空跑，确认「读到的消息、拟回复内容」都正常后再切全自动。"
        )
        hint.setObjectName("Faint")
        hint.setWordWrap(True)
        params_layout.addWidget(hint)

        params_layout.addWidget(QLabel("白名单（每行一个，需与微信显示完全一致）"))
        self.whitelist_edit = QPlainTextEdit()
        self.whitelist_edit.setPlaceholderText("例如：\n张三\n家庭群")
        self.whitelist_edit.setFixedHeight(90)
        params_layout.addWidget(self.whitelist_edit)

        quiet_row = QHBoxLayout()
        quiet_row.addWidget(QLabel("静默时段"))
        self.quiet_edit = QLineEdit()
        self.quiet_edit.setPlaceholderText("如：23:00-08:00（多段用逗号分隔）")
        quiet_row.addWidget(self.quiet_edit, 1)
        params_layout.addLayout(quiet_row)

        self.run_log_check = QCheckBox("在「运行」页显示实时日志")
        self.run_log_check.setChecked(True)
        params_layout.addWidget(self.run_log_check)

        test_row = QHBoxLayout()
        self.poll_once_btn = QPushButton("立即试一次")
        self.poll_once_btn.setObjectName("Ghost")
        self.poll_once_btn.setToolTip("不启动循环，只抓屏识别一次（用于调试）")
        self.poll_once_btn.clicked.connect(self._on_poll_once)
        test_row.addWidget(self.poll_once_btn)
        test_row.addStretch(1)
        params_layout.addLayout(test_row)
        params.setFixedWidth(400)
        params.setSizePolicy(params.sizePolicy().horizontalPolicy(), params.sizePolicy().verticalPolicy())
        bottom.addWidget(params)

        logs = QGroupBox("实时日志")
        logs_layout = QVBoxLayout(logs)
        self.run_log_view = QPlainTextEdit()
        self.run_log_view.setReadOnly(True)
        self.run_log_view.setMaximumBlockCount(800)
        # 实时日志是"页面底部 + 一直加新内容" —— 标记 wheelPriority=internal
        # 让 _NoWheelFilter 走"文本框优先"分支，避免「页面动了日志没动」。
        self.run_log_view.setProperty("wheelPriority", "internal")
        self.run_log_view.setPlaceholderText(
            "停止状态：打开右侧开关开始识别，或点「立即试一次」做单次识别。\n"
            "启动后这里会逐条显示：识别到的消息、拟回复内容、拦截原因。"
        )
        logs_layout.addWidget(self.run_log_view, 1)
        bottom.addWidget(logs, 1)

        layout.addLayout(bottom, 1)
        return page

    def _build_context_card(self) -> QWidget:
        """「上下文窗口占用」+「最近一次思考过程」。

        为什么需要：上下文快满时模型会开始答非所问、或者直接报错，
        但界面上完全看不出来；思考型模型（qwen3.5 / o 系列）更是先想几十秒才吐字，
        不显示思考过程就会以为程序卡死了。
        """
        colors = get_theme(self._current_theme_name())
        card = Card()
        outer = QVBoxLayout(card)
        outer.setContentsMargins(16, 13, 16, 13)
        outer.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(10)
        title = QLabel("上下文窗口")
        title.setObjectName("CardTitle")
        head.addWidget(title)
        self.ctx_usage_label = QLabel("尚未生成")
        self.ctx_usage_label.setObjectName("Faint")
        head.addWidget(self.ctx_usage_label)
        head.addStretch(1)
        self.ctx_model_label = QLabel("")
        self.ctx_model_label.setObjectName("Faint")
        head.addWidget(self.ctx_model_label)
        outer.addLayout(head)

        # 占用条
        self.ctx_bar = QProgressBar()
        self.ctx_bar.setRange(0, 1000)  # 千分比，避免 0~100 整数不够用
        self.ctx_bar.setValue(0)
        self.ctx_bar.setTextVisible(False)
        self.ctx_bar.setFixedHeight(8)
        self.ctx_bar.setToolTip(
            "本次请求的提示词占用了多少上下文窗口。\n"
            "接近 100% 时模型会答非所问或直接报错 —— 调小「技能→对话记忆」的条数即可。"
        )
        outer.addWidget(self.ctx_bar)

        # 思考过程（默认折叠）
        self.think_toggle = QPushButton("最近一次思考过程  ▾")
        self.think_toggle.setObjectName("Ghost")
        self.think_toggle.setCheckable(True)
        self.think_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.think_toggle.setStyleSheet(
            f"text-align: left; font-size: 12.5px; font-weight: 600;"
            f"color: {colors['muted']}; background: transparent; border: none; padding: 2px 0;"
        )
        self.think_toggle.toggled.connect(self._on_think_toggle)
        self.think_view = QTextEdit()  # 富文本：思考内容用弱化色，和正文区分开
        self.think_view.setReadOnly(True)
        self.think_view.setFixedHeight(130)
        self.think_view.setPlaceholderText("这个模型不会输出思考过程（说明它直接给答案）。")
        self.think_view.setVisible(False)
        outer.addWidget(self.think_toggle)
        outer.addWidget(self.think_view)

        self._colors = colors
        return card

    def _on_think_toggle(self, checked: bool) -> None:
        self.think_view.setVisible(checked)
        self.think_toggle.setText(
            f"最近一次思考过程  {'▴' if checked else '▾'}"
        )

    def _update_context_display(self, stats) -> None:
        """把 runner 的上下文占用与思考过程刷到界面上。"""
        used = int(getattr(stats, "context_used", 0) or 0)
        total = int(getattr(stats, "context_total", 0) or 0)
        if used > 0 and total > 0:
            ratio = min(1.0, used / total)
            self.ctx_bar.setValue(int(ratio * 1000))
            self.ctx_usage_label.setText(
                f"{used:,} / {total:,} tokens · 占用 {ratio:.0%}"
            )
            # 越满越红，早点给warning信号
            colors = self._colors
            if ratio >= 0.9:
                color = colors["danger"]
            elif ratio >= 0.7:
                color = colors["warn"]
            else:
                color = colors["accent"]
            self.ctx_bar.setStyleSheet(
                f"QProgressBar {{ background: {colors['surface2']}; border: none;"
                f" border-radius: 4px; }}"
                f"QProgressBar::chunk {{ background: {color}; border-radius: 4px; }}"
            )
        else:
            self.ctx_bar.setValue(0)
            self.ctx_usage_label.setText("尚未生成")

        reasoning = str(getattr(stats, "last_reasoning", "") or "")
        if reasoning:
            self.think_view.setHtml(
                f'<div style="color:{self._colors["faint"]};font-size:12px;'
                f'line-height:150%;">{_render_reasoning(reasoning)}</div>'
            )
            self.think_toggle.setText(f"最近一次思考过程（{len(reasoning)} 字）  ▾")
        else:
            self.think_view.setHtml("")

    def _tab_reply(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)

        self.engine_combo = QComboBox()
        self.engine_combo.addItem("关键词规则（rules：固定回复，简单可控）", "rules")
        self.engine_combo.addItem("大模型（llm：结合技能生成智能回复）", "llm")
        form.addRow("回复引擎", self.engine_combo)

        self.delay_min = QDoubleSpinBox()
        self.delay_min.setRange(0.5, 60.0)
        self.delay_min.setDecimals(1)
        self.delay_min.setSingleStep(0.5)
        self.delay_min.setSuffix(" 秒")
        self.delay_max = QDoubleSpinBox()
        self.delay_max.setRange(0.5, 120.0)
        self.delay_max.setDecimals(1)
        self.delay_max.setSingleStep(0.5)
        self.delay_max.setSuffix(" 秒")
        form.addRow("回复延迟下限", self.delay_min)
        form.addRow("回复延迟上限", self.delay_max)

        self.limit_minute = QSpinBox()
        self.limit_minute.setRange(1, 999)
        self.limit_hour = QSpinBox()
        self.limit_hour.setRange(1, 9999)
        self.limit_day = QSpinBox()
        self.limit_day.setRange(1, 99999)
        form.addRow("每分钟上限", self.limit_minute)
        form.addRow("每小时上限", self.limit_hour)
        form.addRow("每天上限", self.limit_day)

        self.trip_spin = QSpinBox()
        self.trip_spin.setRange(1, 99)
        form.addRow("连续失败自动熔断次数", self.trip_spin)

        self.rules_edit = QPlainTextEdit()
        self.rules_edit.setPlaceholderText(
            "每行一条：关键词1,关键词2 => 回复文本\n例如：\n在吗,在么 => 在的，稍后回你～"
        )
        self.rules_edit.setFixedHeight(150)
        form.addRow("关键词规则（回复引擎=规则时生效）", self.rules_edit)
        return page

    def _tab_persona(self) -> QWidget:
        """人设页：他是谁 / 说话方式 / 语言习惯 + 实时预览。"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        colors = get_theme(self._current_theme_name())

        # ---- 头部：总开关 ----
        header = Card(shadow_alpha=colors.get("shadow", 60))
        head_row = QHBoxLayout(header)
        head_row.setContentsMargins(16, 13, 16, 13)
        head_row.setSpacing(14)
        head_text = QVBoxLayout()
        head_text.setSpacing(2)
        head_title = QLabel("AI 人设")
        head_title.setObjectName("CardTitle")
        head_text.addWidget(head_title)
        head_desc = QLabel("AI 会以这个身份、这种语气替你回复。写得越具体，回复越像你本人。")
        head_desc.setObjectName("Muted")
        head_desc.setWordWrap(True)
        head_text.addWidget(head_desc)
        self.persona_status_label = QLabel("")
        self.persona_status_label.setObjectName("Faint")
        head_text.addWidget(self.persona_status_label)
        head_row.addLayout(head_text, 1)
        self.persona_group = Switch(colors=colors, width=62, height=32)
        self.persona_group.toggled.connect(lambda _checked: self._refresh_persona_status())
        head_row.addWidget(self.persona_group, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(header)

        # ---- 他是谁 ----
        identity_card, identity_box = _make_card(
            "他是谁", "对方问「你是谁 / 你是机器人吗」时会用这里的身份回答", colors=colors
        )
        self.persona_identity_edit = QPlainTextEdit()
        self.persona_identity_edit.setPlaceholderText(
            "写你是谁，不要写「我是」开头也可以。例如：\n"
            "我是张三，30 岁，做游戏开发，住在杭州"
        )
        self.persona_identity_edit.setFixedHeight(66)
        identity_box.addWidget(self.persona_identity_edit)
        identity_tip = QLabel(
            "⚠ 不要写「AI / 机器人 / 助手 / 代回复」—— "
            "程序已内置规则：绝对不许暴露 AI 身份，被问到时按这里回答。"
        )
        identity_tip.setObjectName("Faint")
        identity_tip.setWordWrap(True)
        identity_box.addWidget(identity_tip)
        layout.addWidget(identity_card)

        # ---- 说话方式 ----
        style_card, style_box = _make_card("说话方式", "语气 / 正式程度 / 长度 / 表情", colors=colors)
        grid_row = QHBoxLayout()
        grid_row.setSpacing(14)

        tone_box = QVBoxLayout()
        tone_box.addWidget(QLabel("语气"))
        self.persona_tone_combo = QComboBox()
        for key in TONES:
            self.persona_tone_combo.addItem(TONE_LABELS[key], key)
        tone_box.addWidget(self.persona_tone_combo)
        grid_row.addLayout(tone_box, 2)

        length_box = QVBoxLayout()
        length_box.addWidget(QLabel("回复长度"))
        self.persona_length_combo = QComboBox()
        for key in LENGTHS:
            self.persona_length_combo.addItem(LENGTH_LABELS[key], key)
        length_box.addWidget(self.persona_length_combo)
        grid_row.addLayout(length_box, 2)

        emoji_box = QVBoxLayout()
        emoji_box.addWidget(QLabel("表情符号"))
        self.persona_emoji_combo = QComboBox()
        for key in EMOJIS:
            self.persona_emoji_combo.addItem(EMOJI_LABELS[key], key)
        emoji_box.addWidget(self.persona_emoji_combo)
        grid_row.addLayout(emoji_box, 2)
        style_box.addLayout(grid_row)

        formality_row = QHBoxLayout()
        formality_row.addWidget(QLabel("随意"))
        self.persona_formality = QSlider(Qt.Orientation.Horizontal)
        self.persona_formality.setRange(0, 100)
        self.persona_formality.setValue(30)
        formality_row.addWidget(self.persona_formality, 1)
        formality_row.addWidget(QLabel("正式"))
        self.persona_formality_label = QLabel("")
        self.persona_formality_label.setObjectName("Muted")
        self.persona_formality_label.setFixedWidth(76)
        formality_row.addWidget(self.persona_formality_label)
        style_box.addLayout(formality_row)

        style_box.addWidget(QLabel("说话风格补充"))
        self.persona_edit = QPlainTextEdit()
        self.persona_edit.setPlaceholderText(
            "例如：说话简短、口语化，偶尔用「～」；不用书面语；不说教。"
        )
        self.persona_edit.setFixedHeight(70)
        style_box.addWidget(self.persona_edit)
        layout.addWidget(style_card)

        # ---- 语言习惯 ----
        habit_card, habit_box = _make_card("语言习惯", "口头禅 / 禁忌", colors=colors)
        habit_box.addWidget(QLabel("常用口头禅（逗号分隔）"))
        self.persona_catch_edit = QLineEdit()
        self.persona_catch_edit.setPlaceholderText("例如：哈哈哈,emmm,行吧,～")
        habit_box.addWidget(self.persona_catch_edit)
        habit_box.addWidget(QLabel("绝对不要做的事（逗号分隔）"))
        self.persona_avoid_edit = QLineEdit()
        self.persona_avoid_edit.setPlaceholderText("例如：长篇大论,用书面语,提自己是AI,发广告")
        habit_box.addWidget(self.persona_avoid_edit)
        layout.addWidget(habit_card)

        # ---- 预览与试生成 ----
        preview_card, preview_box = _make_card(
            "预览", "下面就是 AI 实际收到的人设指令", colors=colors
        )
        buttons = QHBoxLayout()
        refresh_preview = QPushButton("刷新预览")
        refresh_preview.setObjectName("Ghost")
        refresh_preview.clicked.connect(self._refresh_persona_preview)
        self.persona_test_btn = QPushButton("试生成一条回复")
        self.persona_test_btn.setObjectName("Primary")
        self.persona_test_btn.clicked.connect(self._on_persona_test)
        buttons.addWidget(refresh_preview)
        buttons.addWidget(self.persona_test_btn)
        buttons.addStretch(1)
        self.persona_test_status = QLabel("")
        self.persona_test_status.setObjectName("Faint")
        self.persona_test_status.setWordWrap(True)
        buttons.addWidget(self.persona_test_status, 1)
        preview_box.addLayout(buttons)

        self.persona_preview = QPlainTextEdit()
        self.persona_preview.setReadOnly(True)
        self.persona_preview.setFixedHeight(150)
        preview_box.addWidget(self.persona_preview)
        layout.addWidget(preview_card)

        layout.addStretch(1)

        # 任一输入变化就刷新预览
        for widget in (
            self.persona_identity_edit,
            self.persona_edit,
            self.persona_catch_edit,
            self.persona_avoid_edit,
        ):
            widget.textChanged.connect(self._refresh_persona_preview)
        for combo in (
            self.persona_tone_combo,
            self.persona_length_combo,
            self.persona_emoji_combo,
        ):
            combo.currentIndexChanged.connect(self._refresh_persona_preview)
        self.persona_formality.valueChanged.connect(self._refresh_persona_preview)
        return page

    # ------------------------------------------------------------- 人设
    def _persona_config_from_form(self):
        return PersonaSkillConfig(
            enabled=self.persona_group.isChecked(),
            identity=self.persona_identity_edit.toPlainText().strip(),
            description=self.persona_edit.toPlainText().strip(),
            tone=str(self.persona_tone_combo.currentData()),
            formality=self.persona_formality.value(),
            length=str(self.persona_length_combo.currentData()),
            emoji=str(self.persona_emoji_combo.currentData()),
            catchphrases=tuple(_split_by_chars(self.persona_catch_edit.text())),
            avoid=tuple(_split_by_chars(self.persona_avoid_edit.text())),
        )

    def _refresh_persona_status(self) -> None:
        colors = get_theme(self._current_theme_name())
        enabled = self.persona_group.isChecked()
        self.persona_status_label.setText(
            "● 已启用：人设会注入每次回复" if enabled else "○ 已停用：不做人设约束，AI 按默认风格回复"
        )
        self.persona_status_label.setStyleSheet(
            f"color: {colors['success'] if enabled else colors['faint']}; font-size: 11.5px;"
        )

    def _refresh_persona_preview(self) -> None:
        from .brain.skills import build_persona_prompt

        if not hasattr(self, "persona_preview"):
            return
        value = self.persona_formality.value()
        if value <= 30:
            label = "很随意"
        elif value >= 70:
            label = "比较正式"
        else:
            label = "中等"
        self.persona_formality_label.setText(f"{label}（{value}）")

        config = self._persona_config_from_form()
        text = build_persona_prompt(config)
        if not self.persona_group.isChecked():
            text = "（人设已停用：下面内容不会注入回复）\n\n" + text
        self.persona_preview.setPlainText(text or "（还没有填任何内容）")

    def _on_persona_test(self) -> None:
        try:
            cfg = self._collect_config()
        except (ConfigError, ValueError) as exc:
            QMessageBox.warning(self, "配置有误", str(exc))
            return
        if not (cfg.llm.base_url and cfg.llm.model):
            QMessageBox.warning(
                self, "先配置模型", "试生成需要调用模型：请先在「模型」页选好服务与模型。"
            )
            return
        self.persona_test_btn.setEnabled(False)
        self.persona_test_status.setText("正在用当前人设生成…")
        self._persona_test_worker = _PersonaTestWorker(cfg)
        self._persona_test_worker.succeeded.connect(self._on_persona_test_ok)
        self._persona_test_worker.failed.connect(self._on_persona_test_fail)
        self._persona_test_worker.start()

    def _on_persona_test_ok(self, system_prompt: str, reply: str) -> None:
        self.persona_test_btn.setEnabled(True)
        self.persona_preview.setPlainText(system_prompt)
        self.persona_test_status.setText(f"✅ 试生成成功，AI 回复：{reply}")

    def _on_persona_test_fail(self, message: str) -> None:
        self.persona_test_btn.setEnabled(True)
        self.persona_test_status.setText(f"❌ 试生成失败：{message}")

    def _tab_model(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # ---- 厂商 + 模型（合并成一块，两列紧凑布局，减少页面高度） ----
        top_group = QGroupBox("厂商与模型（选中厂商即自动填好地址与 Key 配置）")
        top_layout = QGridLayout(top_group)
        top_layout.setHorizontalSpacing(14)
        top_layout.setVerticalSpacing(8)
        top_layout.setColumnStretch(1, 1)
        top_layout.setColumnStretch(3, 1)

        def label_at(text: str, row: int, column: int) -> None:
            item = QLabel(text)
            item.setObjectName("Muted")
            top_layout.addWidget(item, row, column)

        label_at("厂商", 0, 0)
        self.provider_combo = QComboBox()
        for provider in all_providers():
            self.provider_combo.addItem(provider.label, provider.key)
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        top_layout.addWidget(self.provider_combo, 0, 1)

        label_at("模型", 0, 2)
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.setToolTip("下拉选择已配置的模型；也可以直接手动输入模型名")
        self.model_combo.currentIndexChanged.connect(self._on_model_selected)
        top_layout.addWidget(self.model_combo, 0, 3)

        label_at("服务地址", 1, 0)
        self.base_url_edit = QLineEdit()
        self.base_url_edit.setPlaceholderText("如 http://127.0.0.1:1234/v1")
        top_layout.addWidget(self.base_url_edit, 1, 1)

        label_at("Key 环境变量名", 1, 2)
        self.api_env_edit = QLineEdit()
        self.api_env_edit.setPlaceholderText("云端填写，如 DEEPSEEK_API_KEY；本地留空")
        top_layout.addWidget(self.api_env_edit, 1, 3)

        label_at("API Key", 2, 0)
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("可留空；填写后保存到本地 secrets.toml")
        top_layout.addWidget(self.api_key_edit, 2, 1)

        label_at("申请 Key", 2, 2)
        self.console_label = QLabel("")
        self.console_label.setOpenExternalLinks(True)
        top_layout.addWidget(self.console_label, 2, 3)

        action_row = QHBoxLayout()
        self.list_btn = QPushButton("获取模型列表")
        self.list_btn.setObjectName("Primary")
        self.list_btn.clicked.connect(self._on_list_models)
        self.test_btn = QPushButton("测试生成")
        self.test_btn.clicked.connect(self._on_test_chat)
        reset_hint = QLabel("手改过地址想恢复默认？")
        reset_hint.setObjectName("Faint")
        reset_btn = QPushButton("重置")
        reset_btn.setObjectName("Ghost")
        reset_btn.clicked.connect(self._on_reset_provider_defaults)
        action_row.addWidget(self.list_btn)
        action_row.addWidget(self.test_btn)
        action_row.addSpacing(16)
        action_row.addWidget(reset_hint)
        action_row.addWidget(reset_btn)
        action_row.addStretch(1)
        top_layout.addLayout(action_row, 3, 0, 1, 4)

        self.model_choices_hint = QLabel("")
        self.model_choices_hint.setObjectName("Faint")
        self.model_choices_hint.setWordWrap(True)
        top_layout.addWidget(self.model_choices_hint, 4, 0, 1, 4)
        layout.addWidget(top_group)

        # ---- 当前模型参数（两列网格） ----
        param_group = QGroupBox("当前模型参数（切换模型后自动按名称预填）")
        param_grid = QGridLayout(param_group)
        param_grid.setHorizontalSpacing(14)
        param_grid.setVerticalSpacing(8)
        param_grid.setColumnStretch(1, 1)
        param_grid.setColumnStretch(3, 1)

        def param_label(text: str, row: int, column: int) -> None:
            item = QLabel(text)
            item.setObjectName("Muted")
            param_grid.addWidget(item, row, column)

        param_label("上下文长度", 0, 0)
        self.ctx_spin = QSpinBox()
        self.ctx_spin.setRange(512, 2_000_000)
        self.ctx_spin.setSingleStep(1024)
        self.ctx_spin.setSuffix(" tokens")
        self.ctx_spin.setToolTip("该模型可用的最大上下文；超出会被服务端截断或报错")
        param_grid.addWidget(self.ctx_spin, 0, 1)

        param_label("最大输出", 0, 2)
        self.max_tokens_spin = QSpinBox()
        self.max_tokens_spin.setRange(1, 200_000)
        self.max_tokens_spin.setSuffix(" tokens")
        self.max_tokens_spin.setToolTip("单次回复的最大输出长度")
        param_grid.addWidget(self.max_tokens_spin, 0, 3)

        param_label("思考等级", 1, 0)
        self.thinking_combo = QComboBox()
        for level in THINKING_LEVELS:
            self.thinking_combo.addItem(THINKING_LABELS[level], level)
        param_grid.addWidget(self.thinking_combo, 1, 1)

        param_label("温度", 1, 2)
        self.temp_spin = QDoubleSpinBox()
        self.temp_spin.setRange(0.0, 2.0)
        self.temp_spin.setDecimals(1)
        self.temp_spin.setSingleStep(0.1)
        param_grid.addWidget(self.temp_spin, 1, 3)

        param_label("输入模态", 2, 0)
        modality_row = QHBoxLayout()
        modality_row.setSpacing(10)
        self._modality_checks: dict[str, QCheckBox] = {}
        for key in MODALITIES:
            check = QCheckBox(MODALITY_LABELS[key])
            self._modality_checks[key] = check
            modality_row.addWidget(check)
        modality_row.addStretch(1)
        modality_widget = QWidget()
        modality_widget.setLayout(modality_row)
        param_grid.addWidget(modality_widget, 2, 1, 1, 3)

        param_label("请求超时", 3, 0)
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(1, 300)
        self.timeout_spin.setSuffix(" 秒")
        param_grid.addWidget(self.timeout_spin, 3, 1)
        layout.addWidget(param_group)

        # ---- 高级：系统提示词（默认折叠，一般不需要改） ----
        # 注意：QGroupBox 的布局必须是**竖向**的，标题行作为一个子布局整体放进去。
        # 早先这里直接把 QHBoxLayout 设成 group 的布局，正文就会被当成标题行的
        # 同级控件摆到右边去，文本框和警告条会溢出卡片（截图实测发现）。
        adv_group = QGroupBox("高级设置")
        adv_group.setCheckable(False)
        adv_group.setToolTip("一般不需要改；乱改容易和「人设」自相矛盾")
        adv_toggle = QPushButton("展开 ▾")
        adv_toggle.setObjectName("Ghost")
        adv_toggle.setCheckable(True)
        adv_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        adv_header = QHBoxLayout()
        adv_header.setContentsMargins(0, 0, 0, 0)
        adv_header.addWidget(adv_toggle)
        adv_header.addWidget(QLabel("系统提示词（留空 = 使用程序内置的默认提示词）"))
        adv_header.addStretch(1)
        adv_header_widget = QWidget()
        adv_header_widget.setLayout(adv_header)

        adv_body = QWidget()
        adv_body_layout = QVBoxLayout(adv_body)
        adv_body_layout.setContentsMargins(0, 6, 0, 0)
        self.sys_prompt_edit = QPlainTextEdit()
        self.sys_prompt_edit.setFixedHeight(70)
        self.sys_prompt_edit.setPlaceholderText(
            "留空 = 使用内置提示词（强烈推荐）\n"
            "只有当你要完全自定义 AI 的整体行为时才填；"
            "写「你是…助手/机器人/AI」这类字眼会让人设自曝身份。"
        )
        self.sys_prompt_edit.textChanged.connect(self._check_sys_prompt_conflict)
        adv_body_layout.addWidget(self.sys_prompt_edit)
        self.sys_prompt_warn = QLabel("")
        self.sys_prompt_warn.setWordWrap(True)
        self.sys_prompt_warn.setVisible(False)
        adv_body_layout.addWidget(self.sys_prompt_warn)

        adv_outer = QVBoxLayout(adv_group)
        adv_outer.setContentsMargins(12, 10, 12, 12)
        adv_outer.setSpacing(6)
        adv_outer.addWidget(adv_header_widget)
        adv_outer.addWidget(adv_body)

        def toggle_adv(checked: bool) -> None:
            adv_body.setVisible(checked)
            adv_toggle.setText("收起 ▴" if checked else "展开 ▾")

        adv_toggle.toggled.connect(toggle_adv)
        toggle_adv(False)
        layout.addWidget(adv_group)

        # ---- 模型库 ----
        library_group = QGroupBox("模型库（每个厂商的每个模型各自保存一份参数）")
        library_layout = QVBoxLayout(library_group)
        library_row = QHBoxLayout()
        save_model_btn = QPushButton("保存当前模型参数到模型库")
        save_model_btn.clicked.connect(self._on_save_model_entry)
        autofill_btn = QPushButton("按名称重新自动填充")
        autofill_btn.clicked.connect(self._on_autofill_current)
        apply_btn = QPushButton("应用选中行到当前配置")
        apply_btn.clicked.connect(self._on_apply_selected_model)
        delete_btn = QPushButton("删除选中行")
        delete_btn.clicked.connect(self._on_delete_model_entry)
        for btn in (save_model_btn, autofill_btn, apply_btn, delete_btn):
            library_row.addWidget(btn)
        library_row.addStretch(1)
        library_layout.addLayout(library_row)

        self.model_table = QTableWidget(0, 6)
        self.model_table.setHorizontalHeaderLabels(
            ["厂商", "模型", "上下文", "模态", "思考等级", "最大输出"]
        )
        self.model_table.verticalHeader().setVisible(False)
        self.model_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        model_header = self.model_table.horizontalHeader()
        for column in range(5):
            model_header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        model_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        library_layout.addWidget(self.model_table)
        layout.addWidget(library_group)

        self.model_status = QLabel("")
        self.model_status.setWordWrap(True)
        layout.addWidget(self.model_status)
        return page

    def _tab_skills(self) -> QWidget:
        """技能页：技能卡片列表（收起时一行，点「设置」展开细节）。"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        colors = get_theme(self._current_theme_name())

        # ---- 顶部说明 ----
        hint_card = Card(shadow_alpha=colors.get("shadow", 60), flat=True)
        hint_layout = QHBoxLayout(hint_card)
        hint_layout.setContentsMargins(16, 11, 16, 11)
        hint_icon = QLabel("✦")
        hint_icon.setStyleSheet(f"color: {colors['accent']}; font-size: 15px;")
        hint_layout.addWidget(hint_icon)
        hint = QLabel(
            "技能只作用于「大模型」回复引擎：开启的技能会把自己的规则注入提示词。"
            "「人设」已独立成页，在左侧「人设」里配置。"
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        hint_layout.addWidget(hint, 1)
        layout.addWidget(hint_card)

        self._skill_cards: list[CollapsibleCard] = []

        # ---- 对话记忆 ----
        self.memory_group = Switch(colors=colors, width=48, height=26)
        card = CollapsibleCard(
            "对话记忆",
            "回复时参考最近的聊天上下文，避免答非所问",
            self.memory_group,
            colors=colors,
            glyph="◆",
        )
        memory_row = QHBoxLayout()
        memory_row.addWidget(QLabel("参考最近"))
        self.memory_spin = QSpinBox()
        self.memory_spin.setRange(1, 50)
        self.memory_spin.setSuffix(" 条")
        self.memory_spin.setFixedWidth(110)
        memory_row.addWidget(self.memory_spin)
        memory_row.addWidget(QLabel("消息作为上下文"))
        memory_row.addStretch(1)
        card.body_layout.addLayout(memory_row)
        self._skill_cards.append(card)
        layout.addWidget(card)

        # ---- 安全护栏 ----
        self.safety_group = Switch(colors=colors, width=48, height=26)
        card = CollapsibleCard(
            "安全护栏",
            "敏感话题不接茬、不替你做承诺，并对生成的回复做最后审查",
            self.safety_group,
            colors=colors,
            glyph="◇",
        )
        card.body_layout.addWidget(QLabel("禁谈话题（逗号分隔）"))
        self.safety_topics_edit = QLineEdit()
        self.safety_topics_edit.setPlaceholderText("例如：转账,密码,验证码")
        card.body_layout.addWidget(self.safety_topics_edit)
        self.commitment_check = QCheckBox("禁止替我做承诺（不答应时间 / 办事 / 金额）")
        card.body_layout.addWidget(self.commitment_check)
        self._skill_cards.append(card)
        layout.addWidget(card)

        # ---- 群聊策略 ----
        self.group_group = Switch(colors=colors, width=48, height=26)
        card = CollapsibleCard(
            "群聊策略",
            "群里默认只在被 @ 或包含触发词时才回复",
            self.group_group,
            colors=colors,
            glyph="⊞",
        )
        self.require_mention_check = QCheckBox("群消息必须包含触发词才回复")
        card.body_layout.addWidget(self.require_mention_check)
        card.body_layout.addWidget(QLabel("额外触发词（逗号分隔）"))
        self.group_triggers_edit = QLineEdit()
        self.group_triggers_edit.setPlaceholderText("例如：小马,老板")
        card.body_layout.addWidget(self.group_triggers_edit)
        self._skill_cards.append(card)
        layout.addWidget(card)

        # ---- 自学习技能 ----
        self.learned_group = Switch(colors=colors, width=48, height=26)
        card = CollapsibleCard(
            "自学习技能",
            "AI 复盘聊天记录后自动整理成「问答习惯 / 会话备注 / 风格补充」，可逐条开关",
            self.learned_group,
            colors=colors,
            glyph="✧",
            expanded=True,
        )
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.learn_btn = QPushButton("立即学习（分析最近聊天）")
        self.learn_btn.setObjectName("Primary")
        self.learn_btn.clicked.connect(self._on_learn)
        learned_refresh_btn = QPushButton("刷新列表")
        learned_refresh_btn.setObjectName("Ghost")
        learned_refresh_btn.clicked.connect(self._refresh_learned)
        toolbar.addWidget(self.learn_btn)
        toolbar.addWidget(learned_refresh_btn)
        toolbar.addStretch(1)
        toolbar.addWidget(QLabel("自动学习：每"))
        self.learn_auto_spin = QSpinBox()
        self.learn_auto_spin.setRange(0, 1000)
        self.learn_auto_spin.setFixedWidth(72)
        toolbar.addWidget(self.learn_auto_spin)
        auto_hint = QLabel("条真实回复整理一次（0=关闭）")
        auto_hint.setObjectName("Faint")
        toolbar.addWidget(auto_hint)
        card.body_layout.addLayout(toolbar)

        self.learned_table = QTableWidget(0, 4)
        self.learned_table.setHorizontalHeaderLabels(["启用", "类型", "范围", "内容"])
        self.learned_table.verticalHeader().setVisible(False)
        self.learned_table.setShowGrid(False)
        self.learned_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.learned_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.learned_table.setMinimumHeight(200)
        learned_header = self.learned_table.horizontalHeader()
        for column in (0, 1, 2):
            learned_header.setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        learned_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.learned_table.itemChanged.connect(self._on_learned_item_changed)
        card.body_layout.addWidget(self.learned_table)

        self.learned_status = QLabel("")
        self.learned_status.setObjectName("Faint")
        self.learned_status.setWordWrap(True)
        card.body_layout.addWidget(self.learned_status)
        self._skill_cards.append(card)
        layout.addWidget(card)

        layout.addStretch(1)
        return page

    def _tab_logs(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        row = QHBoxLayout()
        refresh_btn = QPushButton("刷新日志")
        refresh_btn.clicked.connect(self._refresh_logs)
        row.addWidget(refresh_btn)
        row.addWidget(QLabel("来自 logs/journal.jsonl（本地审计日志）"))
        row.addStretch(1)
        layout.addLayout(row)
        self.logs_view = QPlainTextEdit()
        self.logs_view.setReadOnly(True)
        layout.addWidget(self.logs_view, 1)
        return page

    # ------------------------------------------------------------- 数据装载
    def _load_into_form(self) -> None:
        try:
            cfg = load_config()
        except ConfigError as exc:
            # 首次运行（尤其是打包后的 exe）根本没有 config.toml。
            # 早先这里弹模态框，**启动就被一个"提示"挡住**，看起来像程序坏了。
            # 现在自动写一份默认配置，并只在运行日志里记一行，不打断启动。
            try:
                DEFAULT_CONFIG_PATH.write_text(
                    dump_config_text(AppConfig()), encoding="utf-8"
                )
                self._first_run_notice = (
                    f"首次运行：已在 {DEFAULT_CONFIG_PATH} 生成默认配置。"
                    f"请到各页检查后再点「保存配置」。"
                )
            except OSError as write_err:
                self._first_run_notice = f"读取配置失败（{exc}），且无法写入新配置：{write_err}"
            cfg = AppConfig()
        self._base_cfg = cfg
        self._populate(cfg)
        key_exists = load_secret_api_key() is not None
        self.model_status.setText(
            "本地密钥（secrets.toml）：已保存" if key_exists else "本地密钥（secrets.toml）：未保存"
        )
        self._refresh_learned()
        self._refresh_model_table()
        self._update_provider_info()
        self._apply_theme()
        self._update_run_ui()

    def _populate(self, cfg: AppConfig) -> None:
        index = self.mode_combo.findData(cfg.mode)
        if index >= 0:
            self.mode_combo.setCurrentIndex(index)
        self.whitelist_edit.setPlainText("\n".join(cfg.whitelist.chats))
        self.quiet_edit.setText("，".join(cfg.safety.quiet_hours))
        self.poll_interval_spin.setValue(cfg.ui.poll_interval_sec)
        self._theme_name = cfg.ui.theme if cfg.ui.theme in (THEME_DARK, THEME_LIGHT) else THEME_DARK

        index = self.engine_combo.findData(cfg.reply.engine)
        if index >= 0:
            self.engine_combo.setCurrentIndex(index)
        self.delay_min.setValue(cfg.safety.min_reply_delay_sec)
        self.delay_max.setValue(cfg.safety.max_reply_delay_sec)
        self.limit_minute.setValue(cfg.safety.max_per_minute)
        self.limit_hour.setValue(cfg.safety.max_per_hour)
        self.limit_day.setValue(cfg.safety.max_per_day)
        self.trip_spin.setValue(cfg.safety.auto_trip_on_failures)
        self.rules_edit.setPlainText(_format_rules(cfg.reply.rules))

        provider_index = self.provider_combo.findData(cfg.llm.provider)
        if provider_index >= 0:
            self.provider_combo.blockSignals(True)
            self.provider_combo.setCurrentIndex(provider_index)
            self.provider_combo.blockSignals(False)
        self.base_url_edit.setText(cfg.llm.base_url)
        self.model_combo.setEditText(cfg.llm.model)
        self.api_env_edit.setText(cfg.llm.api_key_env)
        self.api_key_edit.clear()
        self.temp_spin.setValue(cfg.llm.temperature)
        self.max_tokens_spin.setValue(cfg.llm.max_tokens)
        self.ctx_spin.setValue(cfg.llm.context_length)
        self.thinking_combo.setCurrentIndex(
            max(0, self.thinking_combo.findData(cfg.llm.thinking_level))
        )
        for key, check in self._modality_checks.items():
            check.setChecked(key in cfg.llm.modalities)
        self.timeout_spin.setValue(int(cfg.llm.timeout_sec))
        self.sys_prompt_edit.setPlainText(cfg.llm.system_prompt)
        self._check_sys_prompt_conflict()

        # 模型下拉框：按当前厂商填充模型库里已有的条目
        self._refresh_model_choices()

        # ---- 人设 ----
        persona = cfg.skills.persona
        tone_index = self.persona_tone_combo.findData(persona.tone)
        if tone_index >= 0:
            self.persona_tone_combo.setCurrentIndex(tone_index)
        length_index = self.persona_length_combo.findData(persona.length)
        if length_index >= 0:
            self.persona_length_combo.setCurrentIndex(length_index)
        emoji_index = self.persona_emoji_combo.findData(persona.emoji)
        if emoji_index >= 0:
            self.persona_emoji_combo.setCurrentIndex(emoji_index)
        self.persona_formality.setValue(persona.formality)
        self.persona_catch_edit.setText("，".join(persona.catchphrases))
        self.persona_avoid_edit.setText("，".join(persona.avoid))
        self.persona_group.setChecked(persona.enabled)
        self.persona_identity_edit.setPlainText(persona.identity)
        self.persona_edit.setPlainText(persona.description)
        self._refresh_persona_status()
        self._refresh_persona_preview()

        # ---- 其它技能 ----
        self.memory_group.setChecked(cfg.skills.memory.enabled)
        self.memory_spin.setValue(cfg.skills.memory.max_messages)
        self.safety_group.setChecked(cfg.skills.safety.enabled)
        self.safety_topics_edit.setText("，".join(cfg.skills.safety.banned_topics))
        self.commitment_check.setChecked(cfg.skills.safety.commitment_guard)
        self.group_group.setChecked(cfg.skills.group_policy.enabled)
        self.require_mention_check.setChecked(cfg.skills.group_policy.require_mention)
        self.group_triggers_edit.setText("，".join(cfg.skills.group_policy.extra_triggers))
        self.learned_group.setChecked(cfg.skills.learned.enabled)
        self.learn_auto_spin.setValue(cfg.skills.learned.auto_after_replies)

    def _collect_config(self) -> AppConfig:
        quiet = _split_by_chars(self.quiet_edit.text())
        return AppConfig(
            mode=str(self.mode_combo.currentData()),
            route=self._base_cfg.route,
            safety=SafetyConfig(
                quiet_hours=tuple(quiet) or ("23:00-08:00",),
                max_per_minute=self.limit_minute.value(),
                max_per_hour=self.limit_hour.value(),
                max_per_day=self.limit_day.value(),
                min_reply_delay_sec=self.delay_min.value(),
                max_reply_delay_sec=self.delay_max.value(),
                auto_trip_on_failures=self.trip_spin.value(),
            ),
            whitelist=WhitelistConfig(
                enabled=True,
                allow_all=False,
                chats=tuple(_split_by_chars(self.whitelist_edit.toPlainText())),
            ),
            reply=ReplyConfig(
                engine=str(self.engine_combo.currentData()),
                rules=_parse_rules_text(self.rules_edit.toPlainText()),
                default_enabled=self._base_cfg.reply.default_enabled,
                default_text=self._base_cfg.reply.default_text,
            ),
            llm=LLMConfig(
                provider=self._current_provider_key(),
                base_url=self.base_url_edit.text().strip(),
                model=self.model_combo.currentText().strip(),
                api_style=get_provider(self._current_provider_key()).api_style,
                api_key_env=self.api_env_edit.text().strip(),
                system_prompt=self.sys_prompt_edit.toPlainText().strip(),
                temperature=self.temp_spin.value(),
                max_tokens=self.max_tokens_spin.value(),
                context_length=self.ctx_spin.value(),
                modalities=tuple(
                    k for k, c in self._modality_checks.items() if c.isChecked()
                ) or ("text",),
                thinking_level=str(self.thinking_combo.currentData()),
                timeout_sec=float(self.timeout_spin.value()),
            ),
            skills=SkillsConfig(
                persona=self._persona_config_from_form(),
                memory=MemorySkillConfig(
                    enabled=self.memory_group.isChecked(),
                    max_messages=self.memory_spin.value(),
                ),
                safety=SafetySkillConfig(
                    enabled=self.safety_group.isChecked(),
                    banned_topics=tuple(_split_by_chars(self.safety_topics_edit.text())),
                    commitment_guard=self.commitment_check.isChecked(),
                ),
                group_policy=GroupPolicySkillConfig(
                    enabled=self.group_group.isChecked(),
                    require_mention=self.require_mention_check.isChecked(),
                    extra_triggers=tuple(_split_by_chars(self.group_triggers_edit.text())),
                ),
                learned=LearnedSkillConfig(
                    enabled=self.learned_group.isChecked(),
                    auto_after_replies=self.learn_auto_spin.value(),
                ),
            ),
            ui=UiConfig(
                theme=self._current_theme_name(),
                poll_interval_sec=float(self.poll_interval_spin.value()),
            ),
        )

    def _get_vision_client(self):
        """拿到复用的 VisionClient（懒建一次，之后一直用同一个）。"""
        if self._vision_client is None:
            from .wechat.vision_client import VisionClient

            self._vision_client = VisionClient()
        return self._vision_client

    def _build_runner(self, cfg, *, poll_interval: float):
        """按给定配置建 Runner，但**复用同一个 VisionClient**。"""
        return build_default_runner(
            cfg,
            client=self._get_vision_client(),
            on_event=self._bridge.handle,
            poll_interval=poll_interval,
        )

    # ------------------------------------------------------------- 动作
    def _on_save(self) -> None:
        try:
            cfg = self._collect_config()
            text = dump_config_text(cfg)
            parse_config_text(text)  # 自校验
        except (ConfigError, ValueError) as exc:
            QMessageBox.warning(self, "无法保存", str(exc))
            return
        DEFAULT_CONFIG_PATH.write_text(text, encoding="utf-8")
        self._base_cfg = cfg
        message = f"配置已写入：\n{DEFAULT_CONFIG_PATH}"
        api_key = self.api_key_edit.text().strip()
        if api_key:
            save_secret_api_key(api_key)
            self.api_key_edit.clear()
            message += "\n\nAPI Key 已保存到本地 secrets.toml（不会提交到版本库）"
        # 如果循环在跑，**就地**把新配置换进去 —— 不重启循环。
        # 不能用「stop + 重建 Runner」：每次重启都会新建 Runner，而 WGC 抓屏在
        # 「同一窗口反复建/销抓屏会话」这个模式上原生就会崩（0xC0000005），
        # 连用户手动关开关再开都会闪退。`apply_config` 只换配置对象，下一轮 poll
        # 就用新模型，既不碰 WGC，也不丢去重状态。
        applied = False
        if self._runner is not None and self._runner.running:
            try:
                self._runner.apply_config(cfg)
                applied = True
            except Exception as exc:  # noqa: BLE001
                self._append_run_log(f"⚠ 新配置没能热更新，将在你下次启动时生效：{exc}")
        if applied:
            message += "\n\n识别和循环已热更新为新配置（无需重启，也不会打断正在识别的会话）"
        else:
            message += "\n\n提示：自动对话总开关关着，新配置下次打开时生效。"
        QMessageBox.information(self, "已保存", message)
        self._refresh_status()

    # ------------------------------------------------------------- 模型 / 厂商
    def _current_provider_key(self) -> str:
        return str(self.provider_combo.currentData())

    def _refresh_model_choices(self) -> None:
        """按当前厂商填充模型下拉框（用模型库里已配置的条目）。

        解决"下拉框空着、没法换模型"的问题：启动时和切换厂商后都会自动填充。
        """
        if not hasattr(self, "model_combo"):
            return
        provider_key = self._current_provider_key()
        current = self.model_combo.currentText().strip()
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        entries = ModelStore().entries(provider_key)
        for entry in entries:
            self.model_combo.addItem(entry.model)
        if current:
            self.model_combo.setEditText(current)  # 保留用户当前选择
        self.model_combo.blockSignals(False)
        self._update_model_choices_hint(len(entries))

    def _update_model_choices_hint(self, count: int) -> None:
        if not hasattr(self, "model_choices_hint"):
            return
        provider = get_provider(self._current_provider_key())
        if count:
            self.model_choices_hint.setText(
                f"已列出 {count} 个（点「获取模型列表」可从 {provider.label} 拉取最新）"
            )
        else:
            self.model_choices_hint.setText(
                f"下拉框为空：点「获取模型列表」从 {provider.label} 拉取，或直接手动输入模型名"
            )

    def _update_provider_info(self) -> None:
        """只更新厂商说明与控制台链接，不动地址 / Key 配置（用于加载已保存配置）。"""
        provider = get_provider(self._current_provider_key())
        note = f"（{provider.note}）" if provider.note else ""
        if provider.console_url:
            self.console_label.setText(
                f'<a href="{provider.console_url}">{provider.console_url}</a>{note}'
            )
        else:
            self.console_label.setText(note or "—")

    def _check_sys_prompt_conflict(self) -> None:
        """检测系统提示词里是否写了"自曝身份"这类会与人设冲突的内容。"""
        if not hasattr(self, "sys_prompt_warn"):
            return
        text = self.sys_prompt_edit.toPlainText().strip()
        colors = get_theme(self._current_theme_name())
        if not text:
            self.sys_prompt_warn.setVisible(False)
            return
        risky = [w for w in ("助手", "机器人", "AI", "代回复", "程序", "模型") if w in text]
        if risky:
            self.sys_prompt_warn.setText(
                f"⚠️ 这里写了「{'、'.join(risky)}」，可能让人设自曝 AI 身份。"
                "建议清空（留空即用内置提示词），或把这些说法删掉。"
            )
            self.sys_prompt_warn.setStyleSheet(f"color: {colors['warn']};")
            self.sys_prompt_warn.setVisible(True)
        else:
            self.sys_prompt_warn.setVisible(False)

    def _on_provider_changed(self) -> None:
        """切换厂商：立刻把地址 / Key 配置换成该厂商的（无需再点按钮）。"""
        provider = get_provider(self._current_provider_key())
        self._update_provider_info()

        # 地址：有预设就填；自定义厂商保留用户已填内容
        if provider.base_url:
            self.base_url_edit.setText(provider.base_url)

        # Key 配置：本地厂商清空，云端填对应环境变量名
        self.api_env_edit.setText(provider.key_env)

        if provider.local:
            tail = "本地服务无需 Key，启动服务后点「获取模型列表」。"
        else:
            tail = "需在厂商控制台申请 Key（见上方链接），填进「API Key」后保存。"
        self.model_status.setText(f"当前厂商：{provider.label}｜已自动填好地址与 Key 配置。{tail}")

        # 换厂商后，模型下拉框要换成新厂商的模型（否则会显示上一个厂商的）
        if hasattr(self, "model_combo"):
            self._refresh_model_choices()

    def _on_reset_provider_defaults(self) -> None:
        """把手改过的地址 / Key 变量名恢复成该厂商的默认值。"""
        provider = get_provider(self._current_provider_key())
        if not provider.base_url:
            QMessageBox.information(
                self, "无默认值", f"「{provider.label}」没有内置地址，请手动填写。"
            )
            return
        self.base_url_edit.setText(provider.base_url)
        self.api_env_edit.setText(provider.key_env)
        self.model_status.setText(f"已重置为 {provider.label} 的默认地址与 Key 配置。")

    def _on_list_models(self) -> None:
        base_url = self.base_url_edit.text().strip()
        model = self.model_combo.currentText().strip() or "placeholder"
        if not base_url:
            QMessageBox.warning(self, "先填写服务地址", "请先选择厂商（或手填 base_url）。")
            return
        cfg = LLMConfig(
            provider=self._current_provider_key(),
            base_url=base_url,
            model=model,
            api_style=get_provider(self._current_provider_key()).api_style,
            api_key_env=self.api_env_edit.text().strip(),
            timeout_sec=float(self.timeout_spin.value()),
        )
        self.list_btn.setEnabled(False)
        self.model_status.setText("正在连接…")
        self._worker = _ListModelsWorker(cfg)
        self._worker.succeeded.connect(self._on_models_ok)
        self._worker.failed.connect(self._on_models_fail)
        self._worker.start()

    def _on_models_ok(self, models: list) -> None:
        self.list_btn.setEnabled(True)
        provider_key = self._current_provider_key()
        model_ids = [str(m) for m in models]
        current = self.model_combo.currentText().strip()

        # 批量入库：新模型按元数据库自动预填参数
        store = ModelStore()
        before = len(store)
        store.sync_provider_models(provider_key, model_ids)
        added = len(store) - before

        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.addItems(model_ids)
        if current and current in model_ids:
            self.model_combo.setCurrentText(current)
            new_current = current
        elif model_ids:
            self.model_combo.setCurrentIndex(0)
            new_current = self.model_combo.currentText().strip()
        else:
            new_current = ""
        self.model_combo.blockSignals(False)
        self._update_model_choices_hint(len(model_ids))
        self._refresh_model_table()

        # ⚠ 只有「当前模型真的换了」才重新预填参数。
        # 早先这里无条件调用 _on_model_selected()（而且调了两次），导致点一下「获取模型列表」
        # 就把手工勾选的「图片」等模态按名称元数据覆盖掉 —— 本地视觉模型还会被一律判成纯文本。
        switched = bool(new_current) and new_current != current
        if switched:
            self._on_model_selected()
            param_note = f"已切到「{new_current}」并预填参数"
        else:
            param_note = "当前模型参数保持不变"

        preview = "、".join(model_ids[:6])
        more = f" 等 {len(model_ids)} 个" if len(model_ids) > 6 else ""
        self.model_status.setText(
            f"✅ 连接成功，发现 {len(model_ids)} 个模型（新入库 {added} 个，已按名称自动预填参数）；"
            f"{param_note}：{preview}{more}"
        )

    def _on_models_fail(self, message: str) -> None:
        self.list_btn.setEnabled(True)
        provider = get_provider(self._current_provider_key())
        hint = "（本地模型请确认 LM Studio / Ollama 已启动本地服务）" if provider.local else "（请检查网络、base_url 与 API Key）"
        self.model_status.setText(f"❌ 连接失败：{message}\n{hint}")

    def _on_test_chat(self) -> None:
        try:
            cfg = self._collect_config()
        except (ConfigError, ValueError) as exc:
            QMessageBox.warning(self, "配置有误", str(exc))
            return
        if not (cfg.llm.base_url and cfg.llm.model):
            QMessageBox.warning(self, "先选择模型", "请先获取模型列表并选中一个模型。")
            return
        self.test_btn.setEnabled(False)
        self.model_status.setText("正在测试生成…")
        self._test_worker = _TestChatWorker(cfg.llm)
        self._test_worker.succeeded.connect(self._on_test_ok)
        self._test_worker.failed.connect(self._on_test_fail)
        self._test_worker.start()

    def _on_test_ok(self, text: str) -> None:
        self.test_btn.setEnabled(True)
        self.model_status.setText(f"✅ 生成成功，模型回复：{text[:120]}")

    def _on_test_fail(self, message: str) -> None:
        self.test_btn.setEnabled(True)
        self.model_status.setText(f"❌ 生成失败：{message}")

    # ---- 当前模型参数 ----
    def _apply_meta_to_form(self, provider_key: str, model: str) -> None:
        """按名称自动预填当前模型的各项参数。"""
        meta = lookup_model_meta(provider_key, model)
        self.ctx_spin.setValue(meta.context_length)
        self.max_tokens_spin.setValue(meta.max_output_tokens)
        self.thinking_combo.setCurrentIndex(
            max(0, self.thinking_combo.findData(meta.default_thinking))
        )
        for key, check in self._modality_checks.items():
            check.setChecked(key in meta.modalities)
        if meta.note:
            self.model_status.setText(f"已按模型名自动预填：{meta.note}")

    def _on_model_selected(self) -> None:
        """下拉框选中已有模型时，优先读模型库里保存的参数。"""
        provider_key = self._current_provider_key()
        model = self.model_combo.currentText().strip()
        if not model:
            return
        entry = ModelStore().get(provider_key, model)
        if entry is not None:
            self._entry_to_form(entry)
        else:
            self._apply_meta_to_form(provider_key, model)

    def _entry_to_form(self, entry: ModelEntry) -> None:
        self.ctx_spin.setValue(entry.context_length)
        self.max_tokens_spin.setValue(entry.max_output_tokens)
        self.thinking_combo.setCurrentIndex(
            max(0, self.thinking_combo.findData(entry.thinking_level))
        )
        for key, check in self._modality_checks.items():
            check.setChecked(key in entry.modalities)
        self.temp_spin.setValue(entry.temperature)

    def _form_to_entry(self) -> ModelEntry:
        provider_key = self._current_provider_key()
        model = self.model_combo.currentText().strip()
        modalities = tuple(k for k, c in self._modality_checks.items() if c.isChecked()) or ("text",)
        return ModelEntry(
            provider=provider_key,
            model=model,
            context_length=self.ctx_spin.value(),
            modalities=modalities,
            thinking_level=str(self.thinking_combo.currentData()),
            max_output_tokens=self.max_tokens_spin.value(),
            temperature=self.temp_spin.value(),
        )

    def _on_save_model_entry(self) -> None:
        model = self.model_combo.currentText().strip()
        if not model:
            QMessageBox.warning(self, "没有模型", "请先获取或填写模型名。")
            return
        entry = self._form_to_entry()
        ModelStore().upsert(entry)
        self._refresh_model_table()
        self.model_status.setText(f"✅ 已保存到模型库：{entry.provider}｜{entry.model}")

    def _on_autofill_current(self) -> None:
        provider_key = self._current_provider_key()
        model = self.model_combo.currentText().strip()
        if not model:
            return
        store = ModelStore()
        store.ensure(provider_key, model)
        entry = store.refill_meta(provider_key, model)
        if entry is not None:
            self._entry_to_form(entry)
            # 模型库里的条目也被刷新
            entry.temperature = self.temp_spin.value()
            store.upsert(entry)
        self._refresh_model_table()
        self.model_status.setText(f"已按名称重新自动填充：{model}")

    def _refresh_model_table(self) -> None:
        entries = ModelStore().entries()
        self.model_table.setRowCount(0)
        for entry in entries:
            row = self.model_table.rowCount()
            self.model_table.insertRow(row)
            values = (
                get_provider(entry.provider).label,
                entry.model,
                f"{entry.context_length:,}",
                "/".join(MODALITY_LABELS.get(m, m) for m in entry.modalities),
                THINKING_LABELS.get(entry.thinking_level, entry.thinking_level),
                f"{entry.max_output_tokens:,}",
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                if column == 1:
                    cell.setData(Qt.ItemDataRole.UserRole, entry.key)
                if entry.note:
                    cell.setToolTip(entry.note)
                self.model_table.setItem(row, column, cell)

    def _selected_entry_key(self) -> str | None:
        row = self.model_table.currentRow()
        if row < 0:
            return None
        cell = self.model_table.item(row, 1)
        return str(cell.data(Qt.ItemDataRole.UserRole)) if cell else None

    def _on_apply_selected_model(self) -> None:
        key = self._selected_entry_key()
        if not key:
            QMessageBox.information(self, "未选择", "请先在模型库列表里选中一行。")
            return
        provider_key, _, model = key.partition("::")
        index = self.provider_combo.findData(provider_key)
        if index >= 0:
            # 切换厂商会自动填好地址与 Key 配置
            self.provider_combo.setCurrentIndex(index)
        self.model_combo.setEditText(model)
        entry = ModelStore().get(provider_key, model)
        if entry is not None:
            self._entry_to_form(entry)
        self._refresh_model_choices()
        self.model_status.setText(
            f"已应用：{get_provider(provider_key).label}｜{model}"
            f"（记得点左下「保存配置」）"
        )

    def _on_delete_model_entry(self) -> None:
        key = self._selected_entry_key()
        if not key:
            return
        provider_key, _, model = key.partition("::")
        if ModelStore().remove(provider_key, model):
            self._refresh_model_table()
            self.model_status.setText(f"已从模型库删除：{model}")

    # ------------------------------------------------------------- 运行开关
    def _append_run_log(self, text: str) -> None:
        from datetime import datetime

        if not self.run_log_check.isChecked():
            return
        stamp = datetime.now().strftime("%H:%M:%S")
        scrollbar = self.run_log_view.verticalScrollBar()
        was_pinned = scrollbar.value() >= scrollbar.maximum() - 2  # 容差 2 点
        self.run_log_view.appendPlainText(f"[{stamp}] {text}")
        # 只有用户本来就贴着底（看最新）时，才把新行贴上去；
        # 否则让他们从历史里自由看。新行还在追加，只是滚到尾巴后面一点就能看到。
        if was_pinned:
            scrollbar.setValue(scrollbar.maximum())

    def _on_toggle_runner(self) -> None:
        """以编程方式切换运行状态（等价于用户点一下开关）。"""
        self.run_switch.setChecked(not self.run_switch.isChecked())
        self._on_run_switch(self.run_switch.isChecked())

    def _on_run_switch(self, checked: bool) -> None:
        if not checked:
            if self._runner is not None and self._runner.running:
                self._append_run_log("正在停止…")
                stopped = self._runner.stop()
                self._runner = None
                if stopped:
                    self._append_run_log("已停止：不再抓屏识别，也不执行任何后续动作")
            self._update_run_ui()
            return

        # 启动前把界面上的配置收集好（不写文件，避免误改磁盘）
        try:
            cfg = self._collect_config()
        except (ConfigError, ValueError) as exc:
            QMessageBox.warning(self, "配置有误", f"请先修正配置再启动：\n{exc}")
            self.run_switch.setChecked(False)
            return

        warnings: list[str] = []
        if not cfg.whitelist.chats:
            warnings.append("白名单为空 → 启动后不会回复任何人（只会识别并记录）")
        if cfg.reply.engine == "llm" and not (cfg.llm.base_url and cfg.llm.model):
            warnings.append("回复引擎是大模型，但还没选好模型 → 生成会失败")
        if cfg.mode == "auto":
            warnings.append("当前是全自动模式")

        try:
            self._runner = self._build_runner(
                cfg, poll_interval=max(1.0, self.poll_interval_spin.value())
            )
        except Exception as exc:  # noqa: BLE001
            self._runner = None
            QMessageBox.warning(self, "启动失败", str(exc))
            self.run_switch.setChecked(False)
            return

        for warning in warnings:
            self._append_run_log(f"提示：{warning}")
        self._runner.start()
        self._update_run_ui()

    def _on_poll_once(self) -> None:
        try:
            cfg = self._collect_config()
        except (ConfigError, ValueError) as exc:
            QMessageBox.warning(self, "配置有误", str(exc))
            return
        self.poll_once_btn.setEnabled(False)
        self._append_run_log("手动试一次：正在抓屏识别…")
        self._poll_worker = _PollOnceWorker(cfg, max(1.0, self.poll_interval_spin.value()))
        self._poll_worker.finished_with.connect(self._on_poll_once_ok)
        self._poll_worker.failed.connect(self._on_poll_once_fail)
        self._poll_worker.start()

    def _on_poll_once_ok(self, messages: list) -> None:
        self.poll_once_btn.setEnabled(True)
        if not messages:
            self._append_run_log("手动试一次：本次没有识别到新消息（或微信窗口不可读）")
            return
        for message in messages:
            self._append_run_log(f"📩 识别到新消息 ← {message.chat_name}：{message.text}")

    def _on_poll_once_fail(self, reason: str) -> None:
        self.poll_once_btn.setEnabled(True)
        self._append_run_log(f"❌ 手动试一次失败：{reason}")

    def _on_runner_event(self, event) -> None:
        prefix = {
            "started": "✅",
            "stopped": "⏹",
            "message": "📩",
            "reply": "💬",
            "thinking": "🧠",
            "info": "·",
            "warn": "⚠",
            "error": "❌",
        }.get(event.kind, "·")
        self._append_run_log(f"{prefix} {event.text}")

        if self._runner is not None:
            stats = self._runner.stats
            self._update_context_display(stats)
            self.stat_received.set_value(str(stats.received))
            self.stat_replied.set_value(str(stats.replied))
            self.stat_sent.set_value(str(stats.sent))
            self.stat_blocked.set_value(str(stats.denied))
            self.stat_received.set_hint(
                f"{stats.polls} 次轮询 · 跳过 {stats.skipped}"
            )
            self.stat_replied.set_hint(
                "dry_run 模式" if str(self.mode_combo.currentData()) != "auto" else "待发送"
            )
            self.stat_sent.set_hint(
                f"发送失败 {stats.errors} 次" if stats.errors else "真实发出"
            )
            self.stat_blocked.set_hint("安全网关拦下")
            self.run_progress.setText(
                f"运行中 · 轮询 {stats.polls} 次 · 出错 {stats.errors} 次"
                + (f" · 最近错误：{stats.last_error}" if stats.last_error else "")
            )
        self._update_run_ui()

    def _update_run_ui(self) -> None:
        running = self._runner is not None and self._runner.running
        mode = str(self.mode_combo.currentData())
        mode_text = "全自动（真实发送）" if mode == "auto" else "仅记录（dry_run）"
        if running:
            self.run_switch.setChecked(True, animate=False)
            self.run_state_label.setText("运行中")
            self.run_state_label.setStyleSheet("font-weight: 600;")
            client = getattr(self._runner, "_client", None)
            send_state = ""
            if client is not None and not getattr(client, "can_send", True):
                send_state = "；发送能力不可用"
            elif mode_text.startswith("全自动"):
                send_state = "；识别到消息会真实发送"
            self.run_progress.setText(f"运行中 · {mode_text}{send_state}")
            self.mode_combo.setEnabled(False)
            self.poll_interval_spin.setEnabled(False)
        else:
            self.run_switch.setChecked(False, animate=False)
            self.run_state_label.setText("已停止")
            self.run_state_label.setStyleSheet("")
            if not self.run_progress.text().startswith("运行中"):
                self.run_progress.setText("停止状态下不会抓屏识别，也不会执行任何后续动作")
            self.mode_combo.setEnabled(True)
            self.poll_interval_spin.setEnabled(True)
        self._restyle_pills()
        self._sync_tray_action()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        """关窗口 = 收进托盘（常驻应用），不是退出。

        真正退出走托盘菜单的「退出」，或按 Ctrl+Q。
        """
        if self._tray is not None and not self._really_quit:
            # 忽略这次关闭，隐藏窗口继续在托盘常驻
            event.ignore()
            self.hide()
            return
        self._teardown()
        super().closeEvent(event)

    def _teardown(self) -> None:
        """真正退出前的清理：注销热键、停循环、移除托盘图标。"""
        if self._hotkey_hwnd:
            try:
                from .tray import unregister_hotkey

                unregister_hotkey(int(self._hotkey_hwnd), HOTKEY_ESTOP_ID)
            except Exception:  # noqa: BLE001
                pass
            self._hotkey_hwnd = None
        if self._native_filter is not None:
            try:
                QApplication.instance().removeNativeEventFilter(self._native_filter)
            except Exception:  # noqa: BLE001
                pass
            self._native_filter = None
        if self._runner is not None and self._runner.running:
            self._runner.stop()
        self._runner = None
        if self._tray is not None:
            self._tray.hide()   # Qt 会自己发 NIM_DELETE
            self._tray = None

    def _setup_hotkey(self) -> bool:
        """注册全局急停热键（Ctrl+Alt+Q）。

        任何时候按一下立刻停止自动回复 —— 这个程序会代替用户往微信打字，
        必须有一个不要求切窗口、不抢焦点的刹车。
        """
        try:
            from .tray import MOD_ALT, MOD_CONTROL, MOD_NOREPEAT, VK_Q, register_hotkey
        except Exception:  # noqa: BLE001
            return False
        try:
            hwnd = int(self.winId())
        except Exception:  # noqa: BLE001
            return False
        ok = register_hotkey(
            hwnd, HOTKEY_ESTOP_ID, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_Q
        )
        if ok:
            self._hotkey_hwnd = hwnd
            self._native_filter = _HotkeyFilter(self)
            QApplication.instance().installNativeEventFilter(self._native_filter)
            self._append_run_log("全局急停热键已启用：Ctrl+Alt+Q")
        else:
            # 被别的软件占用是很常见的，不该因此让程序起不来
            self._append_run_log(
                "⚠ 全局急停热键（Ctrl+Alt+Q）注册失败，可能被其他软件占用；"
                "仍可用托盘菜单或运行页开关来停止。"
            )
        return ok

    # ------------------------------------------------------------- 托盘
    def _log_startup_diagnostics(self) -> None:
        """启动时把关键依赖状态写进审计日志。

        打包成 exe 后出了问题（比如 onnxruntime 没打进去），界面上只会闪一句
        "OCR 引擎不可用"，截图也不好抓。写进 logs/journal.jsonl 才是真正能查的。
        """
        try:
            from .wechat.vision_client import VisionClient

            client = self._get_vision_client()
            ocr_ok = getattr(client, "_ocr", None) is not None
            import sys as _sys

            from .tray import is_frozen

            Journal().log(
                "startup_diagnostics",
                frozen=is_frozen(),
                python=_sys.version.split()[0],
                executable=_sys.executable,
                ocr_ok=ocr_ok,
                ocr_error=getattr(client, "ocr_error", ""),
                ocr_traceback=(getattr(client, "ocr_traceback", "") or "")[-800:],
                config_path=str(DEFAULT_CONFIG_PATH),
                hotkey=self._hotkey_hwnd is not None,
                tray=self._tray is not None,
            )
        except Exception as exc:  # noqa: BLE001
            try:
                Journal().log("startup_diagnostics", failed=str(exc))
            except Exception:  # noqa: BLE001
                pass

    def _build_tray(self) -> None:
        """建托盘图标 + 菜单。失败不影响主窗口（老系统可能不支持）。"""
        try:
            from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
        except Exception:  # noqa: BLE001
            return
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        # 内存里画一个图标，省掉外部 .ico（打包时少一个坑）
        pixmap = QPixmap(64, 64)
        pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor("#5b8cff"))
        painter.setPen(QColor("#ffffff"))
        painter.drawRoundedRect(2, 2, 60, 60, 16, 16)
        font = painter.font()
        font.setBold(True)
        font.setPixelSize(34)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "微")
        painter.end()

        icon = QIcon(pixmap)
        self.setWindowIcon(icon)

        self._tray = QSystemTrayIcon(icon, self)
        menu = QMenu()

        self._tray_run_action = QAction("启动自动回复", self)
        self._tray_run_action.triggered.connect(self._on_toggle_runner)
        menu.addAction(self._tray_run_action)

        show_action = QAction("显示主界面", self)
        show_action.triggered.connect(self._show_from_tray)
        menu.addAction(show_action)

        menu.addSeparator()
        quit_action = QAction("退出", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self._quit_app)
        menu.addAction(quit_action)

        self._tray.setToolTip("微信自动回复助手")
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.messageClicked.connect(self._show_from_tray)
        self._tray.show()

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._show_from_tray()

    def _show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit_app(self) -> None:
        self._really_quit = True
        self._teardown()
        QApplication.quit()

    def _emergency_stop(self) -> None:
        """全局急停：立刻停止自动回复。不弹窗、不抢焦点。"""
        was_running = self._runner is not None and self._runner.running
        self.run_switch.setChecked(False, animate=False)
        self._on_run_switch(False)
        if was_running:
            self._append_run_log("🚨 急停热键触发：已立即停止自动回复")
        try:
            from .journal import Journal

            Journal().log("emergency_stop", via="global_hotkey")
        except Exception:  # noqa: BLE001
            pass
        try:
            from .tray import show_tray_bubble

            show_tray_bubble(
                int(self.winId()),
                TRAY_UID,
                "已急停",
                "自动回复已停止，检查无误后再重新启动。",
            )
        except Exception:  # noqa: BLE001
            pass

    def _sync_tray_action(self) -> None:
        """托盘菜单文字跟着运行状态走。"""
        if self._tray_run_action is not None:
            running = self._runner is not None and self._runner.running
            self._tray_run_action.setText("停止自动回复" if running else "启动自动回复")

    def _refresh_status(self) -> None:
        engines = {"rules": "关键词规则", "llm": "大模型"}
        mode = str(self.mode_combo.currentData())
        engine = str(self.engine_combo.currentData())
        model = self.model_combo.currentText().strip()
        whitelist_count = len(_split_by_chars(self.whitelist_edit.toPlainText()))
        windows = window_check.find_wechat_windows()
        wechat_state = f"已检测到（{windows[0]['title']}）" if windows else "未检测到（请打开微信窗口）"
        text = (
            f"模式：{mode} ｜ 回复引擎：{engines.get(engine, engine)}"
            + (f"（{model}）" if model else "")
            + f" ｜ 白名单：{whitelist_count} 项 ｜ 微信窗口：{wechat_state}"
        )
        self.status_label.setText(text)
        self._restyle_pills()

    # ------------------------------------------------------------- 自学习技能
    def _refresh_learned(self) -> None:
        self._loading_learned = True
        try:
            items = LearnedStore().items()
            self.learned_table.setRowCount(0)
            type_names = {"faq": "问答习惯", "note": "会话备注", "style": "风格补充"}
            for item in items:
                row = self.learned_table.rowCount()
                self.learned_table.insertRow(row)
                check = QTableWidgetItem("")
                check.setFlags(
                    Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled
                )
                check.setCheckState(
                    Qt.CheckState.Checked if item.enabled else Qt.CheckState.Unchecked
                )
                check.setData(Qt.ItemDataRole.UserRole, item.id)
                self.learned_table.setItem(row, 0, check)
                values = (
                    type_names.get(item.type, item.type),
                    item.scope,
                    f"{item.title}：{item.content}",
                )
                for column, value in enumerate(values, start=1):
                    cell = QTableWidgetItem(value)
                    cell.setFlags(Qt.ItemFlag.ItemIsEnabled)
                    if item.examples:
                        cell.setToolTip("依据：" + " / ".join(item.examples))
                    self.learned_table.setItem(row, column, cell)
            self.learned_status.setText(
                f"技能库共 {len(items)} 条（勾选 = 用于回复；还没有内容就先点「立即学习」）"
            )
        finally:
            self._loading_learned = False

    def _on_learned_item_changed(self, item) -> None:
        if self._loading_learned or item.column() != 0:
            return
        item_id = item.data(Qt.ItemDataRole.UserRole)
        if not item_id:
            return
        store = LearnedStore()
        store.set_enabled(str(item_id), item.checkState() == Qt.CheckState.Checked)

    def _on_learn(self) -> None:
        try:
            cfg = self._collect_config()
        except (ConfigError, ValueError) as exc:
            QMessageBox.warning(self, "配置有误", str(exc))
            return
        if not (cfg.llm.base_url and cfg.llm.model):
            QMessageBox.warning(
                self, "先配置模型", "学习需要调用大模型：请先在「模型」页填好服务地址和模型。"
            )
            return
        self.learn_btn.setEnabled(False)
        self.learned_status.setText("正在学习（调用模型分析聊天记录）…")
        self._learn_worker = _LearnWorker(cfg)
        self._learn_worker.succeeded.connect(self._on_learn_ok)
        self._learn_worker.failed.connect(self._on_learn_fail)
        self._learn_worker.start()

    def _on_learn_ok(self, report: dict) -> None:
        self.learn_btn.setEnabled(True)
        self._refresh_learned()
        self.learned_status.setText(
            f"✅ 学习完成：新增 {report['added']} 条、重复 {report['duplicates']} 条、"
            f"无效 {report['invalid']} 条（技能库共 {report['total']} 条）"
        )

    def _on_learn_fail(self, message: str) -> None:
        self.learn_btn.setEnabled(True)
        self.learned_status.setText(f"❌ 学习失败：{message}")

    def _refresh_logs(self) -> None:
        from .journal import DEFAULT_JOURNAL_PATH

        path = DEFAULT_JOURNAL_PATH
        if not path.exists():
            self.logs_view.setPlainText("（还没有日志：主循环运行后这里会显示记录）")
            return
        try:
            with path.open("r", encoding="utf-8") as fh:
                lines = deque(fh, maxlen=300)
        except OSError as exc:
            self.logs_view.setPlainText(f"读取失败：{exc}")
            return
        self.logs_view.setPlainText("".join(lines))


def _log_crash(exc: BaseException) -> None:
    """pythonw / 打包后的 exe 没有控制台，把异常写到日志里方便排查。

    ⚠ 用 `APP_DIR`（exe 所在目录）而不是 `PROJECT_ROOT`：冻结后 `PROJECT_ROOT`
    在 PyInstaller 的临时解包目录里，程序一退出就没了，报错根本留不住。
    """
    try:
        from .config import APP_DIR

        path = APP_DIR / "logs" / "gui_error.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(traceback.format_exception(exc)), encoding="utf-8")
    except Exception:
        pass


def run_gui() -> int:
    try:
        app = QApplication.instance() or QApplication(sys.argv)
        app.setApplicationName("wxbot")
        sys.excepthook = lambda exc_type, exc, tb: _log_crash(exc)
        window = MainWindow()
        window.show()
        return app.exec()
    except Exception as exc:
        _log_crash(exc)
        raise


if __name__ == "__main__":
    raise SystemExit(run_gui())
