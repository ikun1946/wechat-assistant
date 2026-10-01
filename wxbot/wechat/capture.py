"""微信窗口抓屏（WGC）与窗口可用性检查。

实测结论（微信 4.x + GPU 自绘）：直接截屏只能截到遮挡物、PrintWindow 全黑，
只有 WGC（Windows Graphics Capture）能在窗口被遮挡时读到真实画面；
但窗口被收进托盘 / 最小化时没有帧可抓，需要先唤出窗口。
"""

from __future__ import annotations

import ctypes
import threading
import time

import numpy as np

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

_user32 = ctypes.windll.user32
_user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
_user32.ShowWindow.restype = ctypes.c_bool
_user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
_user32.IsWindowVisible.restype = ctypes.c_bool
_user32.IsIconic.argtypes = [ctypes.c_void_p]
_user32.IsIconic.restype = ctypes.c_bool

SW_SHOW = 5
SW_RESTORE = 9

MAIN_TITLES = {"微信", "Weixin", "WeChat"}

# ---------------------------------------------------------------------------
# 长驻 WGC 会话（v2.6.6 —— 这是闪退的真正修法）
# ---------------------------------------------------------------------------
# 早先每次抓帧都新建 + 销毁一个 WGC 会话。faulthandler 实测：会话攒到一定数量后，
# 下一个会在**原生 `capture.start()` 里访问冲突**（0xC0000005，崩的是抓屏线程自己）。
# 3 秒轮询 = 每 3 秒一个会话，跑上几小时必然踩到 —— 也就是说程序一直带着一颗
# 定时炸弹，跟手动启停无关（启停只是让它提前引爆）。
#
# 正确用法是一个**长驻**会话：`start_free_threaded()` 专门为这个设计。
# 窗口没变化时本来就没有新帧，OCR 那边比的是内容，返回"最近一帧"和每次重抓等价，
# 反而省掉了反复建销的开销。
_SESSION_LOCK = threading.Lock()
_SESSION: "_WgcSession | None" = None


class _WgcSession:
    """一个长驻的 WGC 会话：帧一到就存起来，抓帧时等"比上次新"的那一帧。"""

    def __init__(self, hwnd: int):
        from windows_capture import WindowsCapture

        self.hwnd = hwnd
        self._lock = threading.Lock()
        self._new_frame = threading.Event()
        self._image: np.ndarray | None = None
        self._seq = 0
        self._closed = False

        capture = WindowsCapture(window_hwnd=hwnd, draw_border=False, cursor_capture=False)

        @capture.event
        def on_frame_arrived(frame, capture_control):
            try:
                buffer = frame.frame_buffer   # 零拷贝视图，必须立刻复制
                image = np.array(buffer)
                if image.ndim == 3 and image.shape[2] == 4:
                    image = image[:, :, :3]
                with self._lock:
                    self._image = np.ascontiguousarray(image)
                    self._seq += 1
                self._new_frame.set()
            except Exception:  # noqa: BLE001 - 回调里绝不能抛
                pass

        @capture.event
        def on_closed():
            self._closed = True
            self._new_frame.set()

        self._capture = capture
        self._control = capture.start_free_threaded()

    def grab(self, timeout: float, settle: float) -> np.ndarray | None:
        """等一帧"比上次新"的画面。

        关键：窗口静止时 WGC **根本不会送新帧**，所以绝不能每次都等满 timeout
        （那会让 3 秒轮询变成 2 秒一帧的慢动作）。策略：
        - 已经有缓存帧 → 只短等一会儿（`settle`），没新帧就直接用缓存
          （内容没变，缓存帧就是当前画面）；
        - 一帧都还没有（刚建会话）→ 才等满 `timeout`。
        """
        with self._lock:
            have_cache = self._image is not None

        wait = (settle if have_cache else timeout)
        deadline = time.time() + max(0.05, wait)
        while time.time() < deadline:
            if self._new_frame.wait(timeout=0.05):
                self._new_frame.clear()
                break
            if self._closed:
                break

        with self._lock:
            if self._image is None:
                return None
            return self._image.copy()

    def close(self) -> None:
        self._closed = True
        try:
            self._control.stop()
        except Exception:  # noqa: BLE001
            pass


def _get_session(hwnd: int) -> "_WgcSession | None":
    """拿到（必要时建立）长驻会话。失败返回 None，调用方按"这一帧没抓到"处理。"""
    global _SESSION
    with _SESSION_LOCK:
        if _SESSION is not None and _SESSION.hwnd == hwnd and not _SESSION._closed:
            return _SESSION
        if _SESSION is not None:
            try:
                _SESSION.close()
            except Exception:  # noqa: BLE001
                pass
        try:
            _SESSION = _WgcSession(hwnd)
        except Exception:  # noqa: BLE001
            _SESSION = None
        return _SESSION


def find_wechat_windows() -> list[dict]:
    """复用 window_check 的枚举逻辑。"""
    from . import window_check

    return window_check.find_wechat_windows()


def find_main_window() -> dict | None:
    for win in find_wechat_windows():
        if win["title"].strip() in MAIN_TITLES:
            return win
    return None


def is_window_ready(hwnd: int) -> tuple[bool, str]:
    """窗口是否处于「可抓屏」状态（可见且未最小化）。"""
    if not hwnd:
        return False, "未找到微信窗口"
    if not _user32.IsWindowVisible(ctypes.c_void_p(hwnd)):
        return False, "微信窗口当前隐藏（可能收在托盘），正在尝试唤出"
    if _user32.IsIconic(ctypes.c_void_p(hwnd)):
        return False, "微信窗口已最小化，正在尝试还原"
    return True, "ok"


def ensure_window_visible(hwnd: int, *, attempts: int = 4) -> bool:
    """把隐藏 / 最小化的窗口唤出（等同点一下托盘图标）。"""
    for _ in range(max(1, attempts)):
        ready, _reason = is_window_ready(hwnd)
        if ready:
            return True
        _user32.ShowWindow(ctypes.c_void_p(hwnd), SW_SHOW)
        _user32.ShowWindow(ctypes.c_void_p(hwnd), SW_RESTORE)
        time.sleep(0.8)
    ready, _reason = is_window_ready(hwnd)
    return ready


def grab_frame(
    hwnd: int,
    *,
    timeout: float = 2.0,
    frames: int = 1,
    settle: float = 0.25,
) -> np.ndarray | None:
    """用 WGC 抓帧（BGR）。窗口被遮挡也能抓到；隐藏 / 最小化时返回 None。

    ⚠ 实测结论（微信 4.x）：**静止窗口的每次抓屏会话通常只产出 1 帧**。
    因此 `frames > 1` 没有意义——等不到后续帧，只会白等到 timeout（实测每帧 2.5 秒，
    曾经是"连续发送卡顿"的根因）。需要"操作后的新画面"时，正确做法是
    **先 sleep 一小会儿再抓一帧**（每次抓屏拿到的都是当前画面），而不是多收几帧。

    这里保留 frames/settle 参数只是为了让调用方能表达"最多等到几帧"，
    默认 1 帧即可；timeout 是"完全没有帧"时的兜底。

    ⚠ v2.6.6：改用**长驻** WGC 会话（`_WgcSession`），不再每次抓帧都建/销一个会话。
    每 3 秒建一个会话，跑久了必然在原生 `capture.start()` 里访问冲突（0xC0000005）。
    窗口没变化时本来就没有新帧，而调用方比的是内容 —— 返回"最近一帧"与重抓等价。
    """
    try:
        import windows_capture  # noqa: F401
    except ImportError:
        return None

    session = _get_session(int(hwnd))
    if session is None:
        return None
    return session.grab(timeout=timeout, settle=settle)


def grab_bgr(
    hwnd: int, *, timeout: float = 2.0, frames: int = 1, settle: float = 0.25
) -> np.ndarray | None:
    """抓帧并统一成 3 通道 BGR（默认单帧，约 0.17s）。"""
    return grab_frame(hwnd, timeout=timeout, frames=frames, settle=settle)
