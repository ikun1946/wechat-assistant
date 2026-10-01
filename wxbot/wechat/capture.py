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

# WGC 抓屏线程的"保活名单"。
# ⚠ 这是一个实测踩过的原生崩溃（v2.6.5 修）：
#   `grab_frame` 里 `thread.join(timeout=0.5)` 超时就直接返回，局部的 `capture`
#   随即被 GC 回收 → **原生 WGC 句柄被释放**，而后台线程还在用它 →
#   0xC0000005 硬崩（症状：循环启停第 2 轮必崩，程序直接闪退）。
#   停不下来的会话就丢进这里保活 —— 宁可泄漏一次，也绝不能让原生对象被提前释放。
_KEEPALIVE: list[tuple[object, threading.Thread]] = []

# WGC 会话**全局串行**。faulthandler 抓到的崩溃栈证明：崩的是**抓屏线程自己**，
# 卡在 `windows_capture/__init__.py:241` 的原生 `capture.start()` 里 ——
# Windows 的图形捕获不允许同一窗口有两个活跃会话，第二个会话一开就访问冲突。
#
# 所以：同一时刻只允许一个会话；上一个没死透就**放弃这一帧**（返回 None）。
# 上层 `poll_new_messages` 见到 None 会安静地跳过这一轮 —— 少抓一帧，
# 远比崩掉整个程序好。
_CAPTURE_LOCK = threading.Lock()

# 还在跑的 WGC 会话线程。faulthandler 实测：崩的是**抓屏线程自己**，卡在
# `windows_capture/__init__.py:241` 的原生 `capture.start()` 里。
# 只要还有一个旧会话没退出就对同一窗口再开一个，就会撞车 —— Windows 图形捕获
# 不支持这种交叠。所以这里做硬闸：**有存活会话就不开新的**，宁可这一帧返回 None。
_LIVE_CAPTURE_THREADS: list[threading.Thread] = []


def _live_capture_count() -> int:
    _LIVE_CAPTURE_THREADS[:] = [t for t in _LIVE_CAPTURE_THREADS if t.is_alive()]
    return len(_LIVE_CAPTURE_THREADS)


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

    ⚠ v2.6.5：整个会话在 `_CAPTURE_LOCK` 里**串行**执行。Windows 图形捕获不允许
    同一窗口有两个活跃会话，并发/交叠开会直接在原生 `capture.start()` 里访问冲突
    （0xC0000005，faulthandler 实测）。拿不到锁就返回 None，由上层跳过这一轮。
    """
    try:
        from windows_capture import WindowsCapture
    except ImportError:
        return None

    # 拿不到锁 = 上一帧的会话还没收干净，**不要**再开一个（会原生崩溃）
    if not _CAPTURE_LOCK.acquire(timeout=0.05):
        return None
    try:
        # 硬闸：还有存活的 WGC 会话就不开新的（交叠开会原生崩溃）
        if _live_capture_count() > 0:
            return None
        return _grab_frame_locked(
            WindowsCapture, hwnd, timeout=timeout, frames=frames, settle=settle
        )
    finally:
        _CAPTURE_LOCK.release()


def _grab_frame_locked(
    WindowsCapture, hwnd: int, *, timeout: float, frames: int, settle: float
):
    """真正的抓屏实现。调用方必须已持有 `_CAPTURE_LOCK`。"""
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

    thread = threading.Thread(target=_run, daemon=True, name="wgc-capture")
    _LIVE_CAPTURE_THREADS.append(thread)  # 硬闸要看到它
    thread.start()
    done.wait(timeout=timeout)

    # ⚠ 关键：必须**先停掉原生抓屏、再等线程真正结束**，才让 capture 离开作用域。
    # 只 join 一小段时间是不够的 —— 超时路径下后台线程还活着，
    # Python 一回收 capture，原生 WGC 句柄就没了，线程里再碰一下就硬崩。
    control = getattr(capture, "capture", None)
    if control is not None:
        try:
            control.stop()
        except Exception:  # noqa: BLE001 - 停止失败也不能让它被提前回收
            pass
    thread.join(timeout=2.0)
    if thread.is_alive():
        # 实在停不下来：保活，绝不能让 GC 在线程还在用的时候回收它
        _KEEPALIVE.append((capture, thread))
        if len(_KEEPALIVE) > 8:  # 只留最近的，旧的已结束的可以丢
            _KEEPALIVE[:] = [item for item in _KEEPALIVE if item[1].is_alive()][-8:]
    return holder.get("image")


def grab_bgr(
    hwnd: int, *, timeout: float = 2.0, frames: int = 1, settle: float = 0.25
) -> np.ndarray | None:
    """抓帧并统一成 3 通道 BGR（默认单帧，约 0.17s）。"""
    return grab_frame(hwnd, timeout=timeout, frames=frames, settle=settle)
