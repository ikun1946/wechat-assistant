"""微信视觉客户端：靠抓屏 + OCR 读会话列表，判断哪些会话有新消息。

为什么不用控件树：微信 4.x 聊天区是 GPU 自绘画布，UIA 读不到内容（实测）。
所以这里全部走视觉：WGC 抓帧 → 裁剪左侧会话列表 → OCR → 检测未读红点。

发送：切会话 → 校验标题 → 点击输入框 → 粘贴 → 回车 → 校验已发出（四道保险）。
"""

from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass

import numpy as np

from .base import IncomingMessage, WeChatClient
from .capture import ensure_window_visible, find_main_window, grab_bgr, is_window_ready

# 会话列表占窗口宽度的比例（微信默认布局）
SESSION_LIST_WIDTH_RATIO = 0.30
# 左侧图标导航栏宽度（像素）：未读检测要跳过它，否则会把「微信」导航图标上的红点误判成会话未读
SIDEBAR_ICON_WIDTH = 56
# 同一会话内「名字行 + 摘要行」的纵向间距上限（微信约 24px；跨会话约 40px+）
ROW_GROUP_GAP = 32
# 未读红点的尺寸约束（实测一个红点约 14~16px 见方）
BADGE_MIN_SIZE = 8
BADGE_MAX_SIZE = 26
# 需要忽略的非会话行（搜索框、导航等）
SKIP_NAME_KEYWORDS = ("搜索", "通讯录", "收藏", "朋友圈", "小程序", "设置")
# 同一会话两次上报的最小间隔（秒）。
# 真正的"别重复回同一条"由 _claimed_text / _last_replied_text 精确控制，
# 这里只是防止相邻两轮轮询在极短时间内重复上报，因此必须小于轮询间隔的量级 ——
# 设成 60 秒会挡住用户连发的第二条消息（实测踩过）。
REPORT_COOLDOWN = 5.0

# 换行气泡合并：相邻两行的垂直间隙 <= 0.6 倍行高 → 视为同一个气泡。
# 按真实抓屏标定（2026-10-01，chat_width=568）：同气泡内 0.17~0.36x，
# 不同气泡之间最小 0.71x —— 0.6 落在两者之间，两侧都留了余量。
WRAPPED_LINE_GAP_RATIO = 0.6
# 对方气泡的左边缘（头像右侧）相对聊天区宽度的位置，实测 138/568 ≈ 0.24
THEM_LEFT_RATIO = 0.27
# 对方气泡的右边缘上限：微信气泡最大宽度约 70%，起点 0.24 → 右缘不超过 ~0.70。
# 留 0.78 作分界，超过就说明这组不是对方的普通气泡 → 宁可判 unknown 也不误回。
THEM_RIGHT_MAX_RATIO = 0.78


@dataclass
class SessionRow:
    """会话列表里的一行。"""

    name: str
    preview: str = ""
    unread: bool = False
    y_center: int = 0
    is_group: bool = False


@dataclass
class ChatBubble:
    """聊天区里的一条消息。sender: them=对方 / me=自己 / unknown=位置不明确。"""

    text: str
    sender: str
    center_x: float = 0.0
    y: float = 0.0
    score: float = 0.0


@dataclass
class _OcrLine:
    """聊天区里 OCR 出来的一行文字及其位置（还没合并成气泡）。"""

    text: str
    left: float
    right: float
    top: float
    bottom: float
    score: float = 0.0

    @property
    def center_x(self) -> float:
        return (self.left + self.right) / 2

    @property
    def center_y(self) -> float:
        return (self.top + self.bottom) / 2

    @property
    def height(self) -> float:
        return max(self.bottom - self.top, 1.0)


def _group_wrapped_lines(lines: list[_OcrLine]) -> list[list[_OcrLine]]:
    """把**换行的同一个气泡**的若干 OCR 行合并成一组。

    为什么必须先合并：气泡换行时，续行是在气泡内部**左对齐**的，
    所以一条右对齐的绿色气泡，第二行的中心会掉到中线左边。
    只看单行中心就会把"我刚发的话"判成"对方发的"，
    于是 `_latest_definite_bubble` 认为最后一条来自对方 → **重复回复**（实测踩过）。

    合并阈值 0.6 倍行高是按真实抓屏标定的：同一个气泡内相邻行间距实测
    0.17~0.36 倍行高，而**不同**气泡之间最小也有 0.71 倍（实测 2026-10-01）。
    纯时间戳（18:25）不参与合并，它自己独立成组。
    """
    groups: list[list[_OcrLine]] = []
    for line in lines:
        if groups:
            previous = groups[-1][-1]
            gap = line.top - previous.bottom
            if (
                not _is_timestamp_text(line.text)
                and not _is_timestamp_text(previous.text)
                and gap <= max(previous.height, line.height) * WRAPPED_LINE_GAP_RATIO
            ):
                groups[-1].append(line)
                continue
        groups.append([line])
    return groups


def _looks_like_group(name: str) -> bool:
    """按会话名判断是不是群聊：微信群名通常带成员数，如「家庭群（5）」。"""
    import re

    return bool(re.search(r"[（(]\s*\d+\s*[)）]\s*$", name.strip()))


_TIME_PREFIX = re.compile(r"^\s*(?:\d{1,2}:\d{2}|昨天|星期[一二三四五六日天]|周[一二三四五六日天])\s*")


def _clean_preview(text: str) -> str:
    """去掉摘要里的时间前缀（如「17:32 你好」→「你好」），让文本更干净。"""
    cleaned = _TIME_PREFIX.sub("", text or "").strip()
    return cleaned or (text or "").strip()


def _is_timestamp_text(text: str) -> bool:
    """判断是不是纯时间戳（如 '18:25' / '昨天 15:08'）。"""
    stripped = (text or "").strip()
    if not stripped:
        return True
    return bool(re.fullmatch(r"(?:\d{1,2}:\d{2}|昨天|前天|星期[一二三四五六日天]|周[一二三四五六日天])", stripped))


# RapidOCR 在预处理时会把输入的**短边**放大到 limit_side_len（默认 736）。
# 于是一块"扁长"的区域会被成倍放大：标题栏 320x45（长宽比 7:1）实测要 575ms，
# 而同样内容补白成正方形只要 105ms —— 慢的是凭空多出来的那一大片空白。
# 比例正常的区域（聊天气泡 1.7:1、会话列表 2.2:1）不受影响。
_OCR_MAX_ASPECT = 1.7  # 长边 / 短边 的上限


def pad_for_ocr(region: np.ndarray) -> tuple[np.ndarray, int, int]:
    """把过扁/过长的裁剪区补成正方形再送进 OCR。

    补的是**纯色空白**，不含任何文字，不影响识别结果，只是省掉无意义的放大推理。
    实测（2026-10-01，811x565 窗口）：标题栏 575ms → 105ms。

    返回 `(补白后的图, 左边距, 上边距)`。
    ⚠ 补白会让 OCR 返回的坐标整体平移 —— **依赖坐标的调用方必须把偏移扣掉**
    （统一走 `VisionClient._ocr_region(..., need_coords=True)`）。
    """
    if region is None or region.size == 0:
        return region, 0, 0
    height, width = region.shape[:2]
    if height == 0 or width == 0:
        return region, 0, 0
    long_side, short_side = max(height, width), min(height, width)
    if long_side <= short_side * _OCR_MAX_ASPECT:
        return region, 0, 0  # 比例本来就正常，不动它
    size = long_side
    top = (size - height) // 2
    left = (size - width) // 2
    # 用区域自身的中位色做填充，贴近真实背景（深色/浅色主题都不突兀）。
    # ⚠ 必须**按通道分别**取中位数：`int(np.median(region))` 会把 RGB 三通道
    # 混在一起求中位数，深色底 (12,20,28) 会被算成灰色 (20,20,20)。
    channels = region.shape[2] if region.ndim == 3 else 1
    fill = tuple(int(np.median(region[:, :, c])) for c in range(channels))
    canvas = np.empty((size, size, channels), dtype=region.dtype)
    canvas[:, :] = fill
    canvas[top : top + height, left : left + width] = region
    return canvas, left, top


def _find_red_badges(panel: np.ndarray) -> list[tuple[int, int, int, int]]:
    """找出面板里像「未读红点」的红色小圆点。

    实测要点（微信 4.x）：
    - 红点不在最右侧，而是紧跟在会话头像/名字附近，位置随窗口宽度变化；
    - 左侧导航栏「微信」图标上也有红点，必须靠 x 偏移排除；
    - 头像本身可能含红色（如腾讯新闻的彩色 logo），靠形状（圆形度）与尺寸区分：
      红点是接近正圆的小色块，logo 红色区域多是不规则长条。
    """
    if panel.size == 0 or panel.ndim != 3:
        return []
    import cv2

    hsv = cv2.cvtColor(panel, cv2.COLOR_BGR2HSV)
    mask1 = cv2.inRange(hsv, (0, 90, 90), (10, 255, 255))
    mask2 = cv2.inRange(hsv, (170, 90, 90), (180, 255, 255))
    mask = cv2.bitwise_or(mask1, mask2)

    height, width = panel.shape[:2]
    x_offset = min(SIDEBAR_ICON_WIDTH, int(width * 0.25))

    badges: list[tuple[int, int, int, int]] = []
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area = float(cv2.contourArea(contour))
        perimeter = float(cv2.arcLength(contour, True))
        if perimeter <= 0 or area <= 0:
            continue
        if not (BADGE_MIN_SIZE <= w <= BADGE_MAX_SIZE and BADGE_MIN_SIZE <= h <= BADGE_MAX_SIZE):
            continue  # 尺寸不像红点（太大=头像色块，太扁=图标边缘）
        if min(w, h) / max(w, h) < 0.6:
            continue  # 明显不是方的/圆的
        circularity = 4 * 3.14159 * area / (perimeter * perimeter)
        if circularity < 0.6:
            continue  # 红点接近正圆；logo 红色区域形状不规则
        if x < x_offset:
            continue  # 左侧导航栏上的红点，不属于会话列表
        badges.append((x, y, w, h))
    return badges


def _has_red_badge(region: np.ndarray) -> bool:
    """区域里是否有微信未读红点（供单点判断/测试使用）。"""
    return bool(_find_red_badges(region))


class VisionClient(WeChatClient):
    """抓屏读会话列表；发送能力暂未接入。"""

    def __init__(self, *, ocr=None, enable_ocr: bool = True, rng=None):
        self._ocr = ocr
        self._enable_ocr = enable_ocr
        self._rng = rng or random.Random()
        self._last_reported: dict[str, float] = {}
        self._last_preview: dict[str, str] = {}
        self._last_known_names: tuple[str, ...] = ()
        self._sent_recently: dict[str, tuple[str, float]] = {}
        self._baseline_ready = False
        self._hwnd: int | None = None
        self.last_send_detail = ""
        self._current_chat: str = ""
        self._last_header_check = 0.0
        self._current_body: str = ""
        self._incoming_changed = False
        self._last_current_body: dict[str, str] = {}
        self._last_body_lines: dict[str, list[str]] = {}
        self._seen_incoming: dict[str, list[tuple[str, float]]] = {}
        self._last_replied_text: dict[str, str] = {}
        self._claimed_text: dict[str, str] = {}
        # OCR 引擎起不来的真实原因（打包场景下这行信息是救命稻草）
        self.ocr_error: str = ""
        self.ocr_traceback: str = ""
        self._refresh_ocr()

    # ---------- 基础设施 ----------
    def _refresh_ocr(self) -> None:
        """初始化 OCR 引擎。

        ⚠ 失败原因**必须留下来**（`self.ocr_error`）。早先这里 `except Exception: pass`
        一样吞掉，报给用户的只有"请确认已安装 rapidocr-onnxruntime"这种毫无信息量的
        提示 —— 打包成 exe 后 onnxruntime 加载失败时，根本无从下手。
        """
        if self._ocr is not None or not self._enable_ocr:
            return
        try:
            from rapidocr_onnxruntime import RapidOCR

            self._ocr = RapidOCR()
            self.ocr_error = ""
        except Exception as exc:  # noqa: BLE001 - 真的要留住原因
            self._ocr = None
            self.ocr_error = f"{type(exc).__name__}: {exc}"
            import traceback

            self.ocr_traceback = traceback.format_exc()

    def _window(self) -> dict | None:
        window = find_main_window()
        self._hwnd = window["hwnd"] if window else None
        return window

    def _ocr_region(self, region, *, need_coords: bool = False):
        """统一的 OCR 入口：先把过扁的区域补成正方形，再送进 OCR。

        `need_coords=True` 时会自动把补白偏移扣掉，返回的坐标仍相对**原始裁剪区**
        —— 气泡方向判定依赖 center_x，坐标错了会直接导致误判"谁发的"。
        """
        padded, left, top = pad_for_ocr(region)
        result, elapsed = self._ocr(padded)
        if result and need_coords and (left or top):
            result = [
                ([[point[0] - left, point[1] - top] for point in box], text, score)
                for box, text, score in result
            ]
        return result, elapsed

    def _grab(self):
        """抓一帧微信窗口（单帧，约 0.2s）。测试可替换此方法来桩掉真实抓屏。"""
        window = self._window()
        if not window:
            return None
        return grab_bgr(int(window["hwnd"]))

    # ---------- WeChatClient ----------
    @property
    def can_send(self) -> bool:
        """已实现真实发送（切会话 → 校验标题 → 粘贴 → 回车 → 校验）。"""
        return True

    def is_available(self) -> tuple[bool, str]:
        window = self._window()
        if not window:
            return False, "未找到微信窗口（请先启动并登录微信）"
        hwnd = int(window["hwnd"])
        ready, reason = is_window_ready(hwnd)
        if not ready:
            ensure_window_visible(hwnd)
            ready, reason = is_window_ready(hwnd)
        if not ready:
            return False, reason
        if self._ocr is None:
            # 把真实原因带出去，别只说一句"请确认已安装"（打包成 exe 时多半是
            # onnxruntime 的 DLL 没打进去，用户看到那句话完全无从下手）
            detail = f"：{self.ocr_error}" if self.ocr_error else ""
            return False, f"OCR 引擎不可用{detail}"
        return True, "ok"

    def capture(self) -> np.ndarray | None:
        window = self._window()
        if not window:
            return None
        hwnd = int(window["hwnd"])
        if not ensure_window_visible(hwnd):
            return None
        return grab_bgr(hwnd)

    def read_sessions(self, image: np.ndarray | None = None) -> list[SessionRow]:
        """读取左侧会话列表：[{name, preview, unread}]。"""
        if image is None:
            image = self.capture()
        if image is None or self._ocr is None:
            return []

        height, width = image.shape[:2]
        panel = image[:, : int(width * SESSION_LIST_WIDTH_RATIO)]
        result, _ = self._ocr_region(panel)
        if not result:
            return []

        # OCR 结果按 y 聚成「行」
        items = []
        for box, text, score in result:
            ys = [point[1] for point in box]
            xs = [point[0] for point in box]
            items.append(
                {
                    "text": str(text).strip(),
                    "y": float(sum(ys) / len(ys)),
                    "x0": float(min(xs)),
                    "x1": float(max(xs)),
                    "score": float(score),
                }
            )
        items.sort(key=lambda item: item["y"])

        rows: list[SessionRow] = []
        used: set[int] = set()
        badges = _find_red_badges(panel)
        for index, item in enumerate(items):
            if index in used or not item["text"]:
                continue
            y = item["y"]
            # 同一会话：名字行与摘要行纵向间距较小，按 ROW_GROUP_GAP 归组
            group = [item]
            used.add(index)
            for other_index in range(index + 1, len(items)):
                if other_index in used:
                    continue
                if abs(items[other_index]["y"] - y) <= ROW_GROUP_GAP:
                    group.append(items[other_index])
                    used.add(other_index)
            group.sort(key=lambda entry: (entry["y"], entry["x0"]))

            # 未读数量角标（红点里的数字，如 '3'）会混进分组，且位置最靠上，
            # 直接取 group[0] 会把会话名误认成 "3"。这里剔除纯数字项。
            name_candidates = [
                entry for entry in group if not entry["text"].isdigit()
            ]
            if not name_candidates:
                continue
            group = name_candidates + [
                entry for entry in group if entry["text"].isdigit()
            ]
            name = group[0]["text"]
            preview = _clean_preview(" ".join(entry["text"] for entry in group[1:]))
            combined = f"{name} {preview}"
            if not name or any(keyword in combined for keyword in SKIP_NAME_KEYWORDS):
                continue
            # 纯符号行不是会话名
            if all(not ch.isalnum() and ch not in "微信" for ch in name):
                continue

            # 未读判定：该行纵向范围内是否存在红点（红点位置随布局变化，不做横向假设）
            row_top = group[0]["y"] - 22
            row_bottom = group[-1]["y"] + 22
            unread = any(
                row_top <= (by + bh / 2) <= row_bottom for _bx, by, _bw, bh in badges
            )
            rows.append(
                SessionRow(
                    name=name,
                    preview=preview,
                    unread=unread,
                    y_center=int(y),
                    is_group=_looks_like_group(name),
                )
            )
        return rows

    def poll_new_messages(self) -> list[IncomingMessage]:
        """返回检测到有新消息的会话。

        三个互补信号（缺一不可，各有盲区）：
        1) 会话行出现未读红点 —— 但**会话正打开时微信不显示红点**；
        2) 会话摘要文字变化 / 新会话冒到列表顶部；
        3) **当前打开的会话**（靠气泡左右位置判断发送方）—— 它既没有红点，
           摘要又可能长时间不变，必须单独盯住，否则用户正看着的会话永远等不到回复。

        另外必须排除"这条摘要就是我们自己刚发的"，否则会自问自答无限循环。
        首次读取只建立基线，不回报（避免启动瞬间把所有会话当成新消息）。
        """
        from ..textutil import names_match, normalize_name

        # 只抓一帧，供会话列表 / 标题 / 气泡三处复用（省一次抓屏 ≈ 0.2s）
        frame = self._grab()
        if frame is None:
            return []
        rows = self.read_sessions(frame)
        if not rows:
            # ⚠ 会话列表识别失败（常见于窗口被缩得太小），**不能就此放弃** ——
            #   当前打开的会话检测并不依赖会话列表，标题读不出来时仍要靠气泡差分工作。
            rows = []

        # 检查"当前打开的会话"（读标题 + 气泡）。这一步独立于会话列表。
        now = time.time()
        if now - self._last_header_check >= 1.0:
            self._last_header_check = now
            header = self._read_header(frame)
            bubbles = self.read_chat_bubbles(frame)
            current_key = normalize_name(header or "")
            kept_previous = False
            if not current_key:
                # 标题读不出来（窗口太小等）→ 沿用上次已知的当前会话。
                # 绝不能因此清空：状态一丢，后续所有当前会话检测都会失效，
                # 表现为"回了几条就彻底卡住"。
                current_key = normalize_name(self._current_chat or "")
                kept_previous = bool(current_key)
            in_list = any(names_match(row.name, header) for row in rows) if header else False
            # kept_previous=True 表示"这次没读到标题，但上次知道"，照样继续检测；
            # 否则要求"明确读到标题且该会话在列表里"，或"列表不可用时也继续"。
            should_check = bool(current_key) and (in_list or kept_previous or not rows)
            if should_check:
                if header:
                    self._current_chat = header
                incoming = self._pending_incoming(current_key, bubbles)
                if incoming:
                    from ..textutil import normalize_name

                    self._claimed_text[current_key] = normalize_name(incoming[0].text)
                self._incoming_changed = bool(incoming)
                self._current_body = (
                    "\n".join(bubble.text for bubble in incoming) if incoming else ""
                )
            elif header:
                # 明确读到标题、但该会话不在列表里 → 确实没有打开的会话
                self._current_chat = ""
                self._current_body = ""
                self._incoming_changed = False

        if not rows:
            # 会话列表不可用时，只要当前会话有新增就应该照常上报
            messages: list[IncomingMessage] = []
            if self._incoming_changed and self._current_body:
                messages.append(
                    IncomingMessage(
                        chat_name=self._current_chat or "(当前会话)",
                        text=self._current_body,
                        is_group=False,
                    )
                )
                self._incoming_changed = False
            if not self._baseline_ready:
                self._baseline_ready = True
            return messages

        # 记住本轮识别到的会话名，供 _read_header 判断"哪个文本才是标题"
        self._last_known_names = tuple(row.name for row in rows)

        if not self._baseline_ready:
            for row in rows:
                self._last_preview[normalize_name(row.name)] = row.preview
            self._baseline_ready = True
            # ⚠ 首轮也要看"当前会话最后一条是不是还没回" ——
            #   否则程序启动前收到的未回消息会被基线吞掉（实测踩到过：
            #   会话正打开着 → 没有红点 → 又被基线跳过 → 永远不回复）。
            #   这里只回"最后一条"，不会造成刷屏。
            if self._incoming_changed and self._current_body and self._current_chat:
                key = normalize_name(self._current_chat)
                # 也要记进"已上报"，否则主循环的冷却期拦不住，会被重复上报
                self._last_reported[key] = time.time()
                return [
                    IncomingMessage(
                        chat_name=self._current_chat,
                        text=self._current_body,
                        is_group=False,
                    )
                ]
            return []

        known_top = min(
            (row.y_center for row in rows if normalize_name(row.name) in self._last_preview),
            default=None,
        )
        messages: list[IncomingMessage] = []
        for row in rows:
            key = normalize_name(row.name)

            # ① 排除"这条摘要就是我们自己刚发的"
            if self._is_own_recent_message(key, row.preview, now):
                continue

            is_current = key == normalize_name(self._current_chat or "")
            reason = ""
            if row.unread:
                reason = "有未读红点"
            elif key in self._last_preview:
                if row.preview and row.preview != self._last_preview[key]:
                    reason = "消息摘要变化"
            elif known_top is not None and row.y_center < known_top:
                reason = "新会话出现在列表顶部"
            if not reason and is_current and self._incoming_changed and self._current_body:
                # ② 当前正打开的会话：微信不显示未读红点，摘要也可能长期不变。
                #    改为看"聊天区里新增的对方气泡"（靠左右位置判断发送方）。
                #    注意：这里必须独立判断，不能放进上面的 elif 链 ——
                #    因为"摘要没变"时会命中 key in _last_preview 分支，后面的分支就永远不会执行。
                reason = "当前会话有新消息"
            if not reason:
                continue

            last = self._last_reported.get(key)
            if last is not None and now - last < REPORT_COOLDOWN:
                continue

            # 当前会话用"新增的聊天内容"作为消息文本（比会话列表摘要准确）
            text = self._current_body if is_current and reason == "当前会话有新消息" else row.preview
            self._last_reported[key] = now
            messages.append(
                IncomingMessage(
                    chat_name=row.name,
                    text=text,
                    is_group=row.is_group,
                )
            )

        self._incoming_changed = False
        for row in rows:
            self._last_preview[normalize_name(row.name)] = row.preview
        return messages

    # ---------- 供外部/测试：手动设置"当前打开的会话"状态 ----------
    def set_current_chat_state(
        self, chat_name: str, body: str, *, changed: bool = False
    ) -> None:
        from ..textutil import normalize_name

        key = normalize_name(chat_name or "")
        self._current_chat = chat_name
        self._current_body = body
        self._incoming_changed = changed
        self._last_current_body[key] = body
        self._last_body_lines[key] = [
            line.strip() for line in (body or "").splitlines() if line.strip()
        ]
        self._last_header_check = 10**9  # 抑制自动抓屏刷新

    # ---------- 自己发出的消息 ----------
    OWN_MESSAGE_WINDOW = 180.0  # 秒：这段时间内摘要与本机发出的内容相同，就认定是自己发的

    # ---------- 聊天区内容判断 ----------
    def _latest_definite_bubble(self, bubbles: list[ChatBubble]) -> ChatBubble | None:
        """取"最后一条能确定发送方"的气泡（跳过居中的时间戳等 unknown 项）。

        判断规则：**最后一条是对方发的 = 还没回**，需要回复；是我发的 = 已回。
        这比"和上一轮做差分"稳健得多 —— 差分会漏掉程序启动前就存在的未回消息，
        而且聊天区滚动时容易错位。
        """
        for bubble in reversed(bubbles):
            if bubble.sender not in ("them", "me"):
                continue
            if _is_timestamp_text(bubble.text):
                continue  # 纯时间戳不算消息
            return bubble
        return None

    def _pending_incoming(self, key: str, bubbles: list[ChatBubble]) -> list[ChatBubble]:
        """当前会话里"对方发的、且我们还没回过"的最后一条消息。

        同一轮被识别出来后记为"已认领"，避免在真正发送之前反复上报；
        发送成功后 `_remember_sent` 会更新对照值。
        """
        latest = self._latest_definite_bubble(bubbles)
        if latest is None or latest.sender != "them":
            return []
        from ..textutil import normalize_name

        normalized = normalize_name(latest.text)
        if self._last_replied_text.get(key) == normalized:
            return []  # 这一条已经回过了
        if self._claimed_text.get(key) == normalized:
            return []  # 已经上报过、正在等发送结果
        return [latest]

    def _diff_incoming_bubbles(
        self, key: str, bubbles: list[ChatBubble]
    ) -> list[ChatBubble]:
        """返回"相对上次新增的**对方**消息气泡"。

        对方消息 = sender == "them"（靠左）；自己的气泡直接忽略 —— 这样就不需要
        再靠文本匹配去排除回显，也就不会出现"自己的旧回复把对方新消息一起吞掉"。

        差分方式：从后往前找"上次见过、且这次还在"的最后一条对方气泡，取其后新增部分
        （聊天区会滚动，旧的行会从顶部消失，所以不能只找公共前缀）。
        """
        incoming = [bubble for bubble in bubbles if bubble.sender == "them"]
        old = self._seen_incoming.get(key) or []
        self._seen_incoming[key] = [(bubble.text, round(bubble.y, 1)) for bubble in incoming]

        if not old:
            return []  # 第一次只记录，不回报
        if not incoming:
            return []

        old_texts = [text for text, _y in old]
        start = 0
        for index in range(len(old_texts) - 1, -1, -1):
            if old_texts[index] in [bubble.text for bubble in incoming]:
                start = [bubble.text for bubble in incoming].index(old_texts[index]) + 1
                break
        return incoming[start:]

    def _diff_new_body_lines(self, key: str, body: str) -> list[str]:
        """返回聊天区"相对上次新增"的那些行。

        聊天区会滚动（旧的行从顶部消失），所以不能简单地找公共前缀：
        做法是从后往前找"上次见过、且这次还在"的最后一行，取它之后的部分。
        """
        new_lines = [line.strip() for line in (body or "").splitlines() if line.strip()]
        old_lines = self._last_body_lines.get(key) or []
        if not old_lines:
            self._last_body_lines[key] = new_lines
            return new_lines

        start = 0
        for index in range(len(old_lines) - 1, -1, -1):
            line = old_lines[index]
            if line in new_lines:
                start = new_lines.index(line) + 1
                break
        added = new_lines[start:]
        self._last_body_lines[key] = new_lines
        return added

    def _is_own_line(self, line: str, now: float) -> bool:
        """这一行是不是我自己刚发出去的（回显）。"""
        from ..textutil import normalize_name

        needle = normalize_name(line)
        if not needle:
            return True
        for sent_text, sent_at in self._sent_recently.values():
            if now - sent_at > self.OWN_MESSAGE_WINDOW:
                continue
            if sent_text[:10] and sent_text[:10] in needle:
                return True
            if needle[:10] and needle[:10] in sent_text:
                return True
        return False

    def _remember_sent(self, chat_name: str, text: str) -> None:
        from ..textutil import normalize_name

        key = normalize_name(chat_name)
        self._sent_recently[key] = (normalize_name(text), time.time())
        # 记下"我们最后回的那条"，用于判断"最后一条是不是还没回"
        self._last_replied_text[key] = normalize_name(text)
        self._claimed_text.pop(key, None)

    def _is_own_recent_message(self, chat_key: str, preview: str, now: float) -> bool:
        """摘要是否就是本机刚发出的那条消息（避免自己回复自己）。"""
        from ..textutil import normalize_name

        record = self._sent_recently.get(chat_key)
        if record is None:
            return False
        sent_text, sent_at = record
        if now - sent_at > self.OWN_MESSAGE_WINDOW:
            return False
        needle = normalize_name(preview)
        if not needle or not sent_text:
            return False
        # 微信摘要通常带时间前缀（如「17:32 你好呀」），所以用"包含"判断
        return sent_text[:12] in needle or needle[:12] in sent_text

    def send_text(self, chat_name: str, text: str) -> bool:
        """真实发送：切换会话 → 校验标题 → 点击输入框 → 粘贴 → 回车 → 校验已发出。

        每一步都可失败即中止（宁可发不出去，也不要在错误的会话里乱打字）。

        关于"打扰"：点击与输入必须让窗口拿到真实焦点（Windows 限制，投递消息打字无效，
        已实测），所以会短暂把微信置前；但发送完成后会**还原你原来的前台窗口和鼠标位置**，
        并且如果目标会话已经打开，就跳过"点会话行"这一步。
        """
        from . import input as input_ctl

        self.last_send_detail = ""
        if not text.strip():
            self.last_send_detail = "空文本"
            return False

        window = self._window()
        if not window:
            self.last_send_detail = "未找到微信窗口"
            return False
        hwnd = int(window["hwnd"])
        if not ensure_window_visible(hwnd):
            self.last_send_detail = "窗口不可见（可能在托盘）"
            return False

        # 记下"打扰前"的状态：用户原本在看哪个窗口、鼠标在哪 —— 发完立刻还原
        previous_foreground = input_ctl.get_foreground()
        saved_cursor = input_ctl.cursor_pos()
        try:
            return self._do_send(hwnd, chat_name, text, previous_foreground)
        finally:
            input_ctl.set_cursor_pos(*saved_cursor)
            if previous_foreground and previous_foreground != hwnd:
                input_ctl.set_foreground(previous_foreground)

    def _do_send(self, hwnd: int, chat_name: str, text: str, previous_foreground: int) -> bool:
        del previous_foreground  # 前台还原由 send_text 的 finally 统一负责
        from . import input as input_ctl
        from ..textutil import names_match

        # 如果你正在用电脑（打字/操作），先等一小会儿再动手；
        # 等不到也照发 —— 不能因为你一直在用电脑就永远不回复。
        if not input_ctl.wait_until_user_idle(threshold=1.2, max_wait=3.0):
            self.last_send_detail = "（发送前你正在操作电脑，等待超时后仍继续）"

        if not input_ctl.set_foreground(hwnd):
            self.last_send_detail = "无法把微信窗口置前（可能被系统阻止），已放弃点击"
            return False

        image = grab_bgr(hwnd, timeout=2.0)
        if image is None:
            self.last_send_detail = "抓屏失败"
            return False
        rows = self.read_sessions(image)
        target = next((row for row in rows if names_match(row.name, chat_name)), None)
        if target is None:
            self.last_send_detail = f"会话列表中没找到「{chat_name}」（当前识别到：{[r.name for r in rows]}）"
            return False

        offset_x, offset_y = self._screen_offsets(hwnd, image)
        height, width = image.shape[:2]
        panel_width = int(width * SESSION_LIST_WIDTH_RATIO)

        # 1) 如果当前已经打开的就是目标会话，就不必再点一次（少一次打扰）
        current_header = self._read_header(image)
        if not (current_header and names_match(current_header, chat_name)):
            # 点击位置加一点随机抖动（固定像素点反复点击是很明显的机器特征）
            click_x = offset_x + int(panel_width * self._rng.uniform(0.62, 0.86))
            click_y = offset_y + target.y_center + self._rng.randint(-6, 6)
            input_ctl.click(click_x, click_y)
            time.sleep(0.35)

            # 2) 校验聊天标题确实是目标会话（多抓几帧，避开点击前的旧帧）
            after = grab_bgr(hwnd, timeout=2.0)
            if after is None:
                self.last_send_detail = "切换会话后抓屏失败"
                return False
            header = self._read_header(after)
            if header and not names_match(header, chat_name):
                time.sleep(0.4)
                retry_image = grab_bgr(hwnd, timeout=2.0)
                if retry_image is not None:
                    after = retry_image
                    header = self._read_header(after)
            if header and not names_match(header, chat_name):
                self.last_send_detail = (
                    f"切换后标题是「{header}」，与目标「{chat_name}」不符，已中止发送"
                )
                return False
        else:
            after = image

        # 3) 点击输入框（聊天区底部中央，同样加抖动）
        height, width = after.shape[:2]
        panel_width = int(width * SESSION_LIST_WIDTH_RATIO)
        input_x = (
            offset_x
            + panel_width
            + int((width - panel_width) * 0.5)
            + self._rng.randint(-30, 30)
        )
        input_y = offset_y + int(height * 0.84) + self._rng.randint(-15, 15)
        input_ctl.click(input_x, input_y)

        # 4) 输入文本：先剪贴板粘贴；粘贴后**确认输入框确实有内容**才按回车
        original_clipboard = input_ctl.get_clipboard_text()
        if input_ctl.set_clipboard_text(text):
            input_ctl.paste()
        if not self._input_box_contains(text):
            input_ctl.type_unicode(text)  # 剪贴板路线没成功，退回逐字输入
        if not self._input_box_contains(text):
            self.last_send_detail = "文本没有进入输入框（剪贴板与逐字输入都失败），已中止且未按回车"
            return False

        # 像人一样：贴完字停一小会儿再按回车（时间与文本长度相关）
        time.sleep(min(1.5, 0.25 + len(text) * 0.05) + self._rng.uniform(0, 0.4))
        input_ctl.press_enter()
        if original_clipboard and original_clipboard != text:
            input_ctl.set_clipboard_text(original_clipboard)

        # 5) 校验：抓屏看这条消息是否出现在聊天区
        time.sleep(0.5)
        verify = grab_bgr(hwnd, frames=1)
        if verify is not None and self._text_appears(verify, text):
            self._remember_sent(chat_name, text)
            return True

        time.sleep(0.5)
        verify = grab_bgr(hwnd, frames=1)
        if verify is not None and self._text_appears(verify, text):
            self._remember_sent(chat_name, text)
            return True
        self.last_send_detail = "已执行发送动作，但未在聊天区确认到该消息（可能未发出或未及时渲染）"
        return False

    # ---------- 发送辅助 ----------
    def _screen_offsets(self, hwnd: int, image) -> tuple[int, int]:
        """抓屏帧坐标 → 屏幕坐标的偏移（帧比窗口略小，按边框居中估算）。"""
        from . import input as input_ctl

        left, top, right, bottom = input_ctl.window_rect(hwnd)
        frame_h, frame_w = image.shape[:2]
        win_w, win_h = right - left, bottom - top
        return left + max(0, (win_w - frame_w) // 2), top + max(0, (win_h - frame_h) // 2)

    def _read_header(self, image) -> str:
        """读聊天窗口顶部标题（当前会话名）。

        标题栏里除了会话名还可能有别的短文本（如时间、图标），这里取
        "最像会话名"的一个：优先与已知会话名匹配，其次取较长的非数字文本。
        """
        if self._ocr is None:
            return ""
        height, width = image.shape[:2]
        panel_width = int(width * SESSION_LIST_WIDTH_RATIO)
        region = image[int(height * 0.05) : int(height * 0.13), panel_width : panel_width + 320]
        if region.size == 0:
            return ""
        result, _ = self._ocr_region(region)
        if not result:
            return ""
        from ..textutil import names_match

        known = set(self._last_known_names)
        candidates: list[tuple[str, float]] = []
        for item in result:
            text = str(item[1]).strip()
            if not text or text.isdigit():
                continue
            score = 1.0
            if known and any(names_match(text, name) for name in known):
                score = 10.0  # 与会话列表里的名字对得上 → 优先采信
            candidates.append((text, score * len(text)))
        if not candidates:
            return ""
        candidates.sort(key=lambda pair: pair[1], reverse=True)
        return candidates[0][0]

    def _input_box_contains(self, text: str) -> bool:
        """确认输入框里确实已经出现要发送的文字（按回车前的最后一道保险）。"""
        from ..textutil import normalize_name

        if self._ocr is None:
            return True  # 没有 OCR 时无法校验，交给上层判断（不阻塞发送）
        window = self._window()
        if not window:
            return False
        image = grab_bgr(int(window["hwnd"]))
        if image is None:
            return False
        height, width = image.shape[:2]
        panel_width = int(width * SESSION_LIST_WIDTH_RATIO)
        region = image[int(height * 0.76) : int(height * 0.94), panel_width:]
        if region.size == 0:
            return False
        result, _ = self._ocr_region(region)
        if not result:
            return False
        combined = normalize_name(" ".join(str(item[1]) for item in result))
        needle = normalize_name(text)[:6]
        return bool(needle) and needle in combined

    # ---------- 消息气泡识别（靠左右位置判断是谁发的） ----------
    def read_chat_bubbles(self, image=None) -> list[ChatBubble]:
        """读聊天区每一条消息，并判断"谁发的"。

        依据（微信布局约定）：
        - 对方的消息：气泡与头像在**左**侧；
        - 自己的消息：气泡在**右**侧（绿色气泡）。

        因此用气泡中心的横向位置相对聊天区中线来判定方向 —— 这比"文本是否
        包含我刚发的话"可靠得多，也不受聊天区内容累积影响。

        阈值用相对比例（而不是绝对像素），窗口任意大小都适用：
        中心 x < 中线 → 对方；> 中线 + 10% 宽 → 自己；中间地带视为不确定。
        """
        if self._ocr is None:
            return []
        if image is None:
            window = self._window()
            if not window:
                return []
            image = grab_bgr(int(window["hwnd"]))
        if image is None:
            return []

        height, width = image.shape[:2]
        panel_width = int(width * SESSION_LIST_WIDTH_RATIO)
        chat_width = max(1, width - panel_width)
        middle = chat_width / 2
        # 自己这一侧要更靠近右边缘才算，避免长文本跨过中线被误判
        own_threshold = middle + chat_width * 0.12

        region = image[int(height * 0.14) : int(height * 0.72), panel_width:]
        if region.size == 0:
            return []
        # ⚠ 这里必须 need_coords=True：气泡方向判定靠 center_x，
        # 补白平移了坐标却不修正，就会把"我发的"判成"对方发的"→ 重复回复。
        result, _ = self._ocr_region(region, need_coords=True)
        if not result:
            return []

        lines: list[_OcrLine] = []
        # 聊天区左边缘的"碎片行"过滤：裁剪起点是按 SESSION_LIST_WIDTH_RATIO 估的，
        # 实际分隔线会差几个像素，于是会话列表最右边的一小条会被裁进来。
        # 这种又窄又贴左边的行不是聊天内容（真气泡都从头像右侧起头），
        # 留着会被当成一条"对方发的消息"而触发回复。
        sliver_left = chat_width * 0.08
        sliver_right = chat_width * 0.20
        for box, text, score in result:
            content = str(text).strip()
            if not content:
                continue
            xs = [point[0] for point in box]
            ys = [point[1] for point in box]
            left, right = min(xs), max(xs)
            if left < sliver_left and right < sliver_right:
                continue
            lines.append(
                _OcrLine(
                    text=content,
                    left=left,
                    right=right,
                    top=min(ys),
                    bottom=max(ys),
                    score=float(score),
                )
            )
        lines.sort(key=lambda line: (line.top, line.left))

        items: list[ChatBubble] = []
        for group in _group_wrapped_lines(lines):
            if len(group) == 1:
                # 单行气泡：用中心判定（这是原来一直有效的规则，保持不变）
                line = group[0]
                if line.center_x < middle:
                    sender = "them"
                elif line.center_x > own_threshold:
                    sender = "me"
                else:
                    sender = "unknown"
                text = line.text
                center_x = line.center_x
                y = line.center_y
            else:
                # 换行气泡：续行在气泡内左对齐，**单行中心不可信**。
                # 改用整块的外接矩形，而且判"我发的"要求**两个条件同时满足**：
                # 右缘越过自己的阈值，且左缘不在对方的起始位置 ——
                # 否则一条很宽的对方长消息会被误当成自己发的（那会漏回）。
                # 判不准就落 unknown：宁可漏回，也绝不乱回。
                left = min(line.left for line in group)
                right = max(line.right for line in group)
                if right > own_threshold and left >= chat_width * THEM_LEFT_RATIO:
                    sender = "me"
                elif left < middle and right < chat_width * THEM_RIGHT_MAX_RATIO:
                    sender = "them"
                else:
                    sender = "unknown"
                text = "".join(line.text for line in group)
                center_x = (left + right) / 2
                y = (group[0].top + group[-1].bottom) / 2
            items.append(
                ChatBubble(
                    text=text,
                    sender=sender,
                    center_x=center_x,
                    y=y,
                    score=min(line.score for line in group),
                )
            )
        items.sort(key=lambda bubble: bubble.y)
        return items

    def read_current_chat_text(self, image=None, *, max_chars: int = 400) -> str:
        """读当前打开会话的**完整可见内容**（比会话列表摘要准确得多）。

        用于两个场景：
        1) 当前会话正打开时微信不显示未读红点，只能靠这里判断"有没有新消息"；
        2) 会话列表摘要被截断（长消息只显示开头），这里能拿到完整气泡文本。
        """
        if self._ocr is None:
            return ""
        if image is None:
            window = self._window()
            if not window:
                return ""
            image = grab_bgr(int(window["hwnd"]))
        if image is None:
            return ""
        height, width = image.shape[:2]
        panel_width = int(width * SESSION_LIST_WIDTH_RATIO)
        # 只取聊天区（排除标题栏与输入框）
        region = image[int(height * 0.14) : int(height * 0.72), panel_width:]
        if region.size == 0:
            return ""
        result, _ = self._ocr_region(region)
        if not result:
            return ""
        # 按纵向位置排序（从上到下 = 聊天顺序）
        ordered = sorted(
            result,
            key=lambda item: sum(point[1] for point in item[0]) / len(item[0]),
        )
        texts = [str(item[1]).strip() for item in ordered if str(item[1]).strip()]
        return "\n".join(texts)[:max_chars]

    def _text_appears(self, image, text: str) -> bool:
        """OCR 聊天区，确认文本是否出现（用于发送后校验）。"""
        from ..textutil import normalize_name

        if self._ocr is None:
            return False
        height, width = image.shape[:2]
        panel_width = int(width * SESSION_LIST_WIDTH_RATIO)
        region = image[int(height * 0.12) : int(height * 0.80), panel_width:]
        if region.size == 0:
            return False
        result, _ = self._ocr_region(region)
        if not result:
            return False
        needle = normalize_name(text)[:8]
        if not needle:
            return False
        combined = normalize_name(" ".join(str(item[1]) for item in result))
        return needle in combined
