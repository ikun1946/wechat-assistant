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
    """
    try:
        from windows_capture import WindowsCapture
    except ImportError:
        return None

    wanted = max(1, int(frames))
    holder: dict = {}
    seen = 0
    first_frame_at: float | None = None

    try:
        capture = WindowsCapture(
            window_hwnd=hwnd, draw_border=False, cursor_capture=False
        )
    except TypeError:
        capture = WindowsCapture(window_hwnd=hwnd)

    done = threading.Event()

    @capture.event
    def on_frame_arrived(frame, capture_control):
        nonlocal seen, first_frame_at
        try:
            buffer = frame.frame_buffer
            # frame_buffer 是零拷贝视图，必须立刻复制
            image = np.array(buffer)
            if image.ndim == 3 and image.shape[2] == 4:
                holder["image"] = image[:, :, :3].copy()
            elif image.ndim == 3:
                holder["image"] = image.copy()
            else:
                holder["image"] = None
            seen += 1
            now = time.time()
            if first_frame_at is None:
                first_frame_at = now
            if seen >= wanted or (now - first_frame_at) >= settle:
                capture_control.stop()
                done.set()
        except Exception as exc:  # noqa: BLE001
            holder["error"] = repr(exc)
            capture_control.stop()
            done.set()

    @capture.event
    def on_closed():
        done.set()

    def _run():
        try:
            capture.start()
        except Exception as exc:  # noqa: BLE001
            holder["error"] = repr(exc)
            done.set()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    done.wait(timeout=timeout)
    thread.join(timeout=0.5)
    return holder.get("image")


def grab_bgr(
    hwnd: int, *, timeout: float = 2.0, frames: int = 1, settle: float = 0.25
) -> np.ndarray | None:
    """抓帧并统一成 3 通道 BGR（默认单帧，约 0.17s）。"""
    return grab_frame(hwnd, timeout=timeout, frames=frames, settle=settle)
