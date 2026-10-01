"""键鼠输入与剪贴板（ctypes 实现，不引入额外依赖）。

用于「发送」环节：把窗口置前 → 点击坐标 → 粘贴文本 → 回车。
所有坐标都是**屏幕绝对坐标**（调用方负责把抓屏坐标换算成屏幕坐标）。
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32

# ---------- DPI 感知（必须在取坐标前设置） ----------
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        _user32.SetProcessDPIAware()
    except Exception:
        pass

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
VK_CONTROL = 0x11
VK_RETURN = 0x0D
VK_V = 0x56
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

SW_RESTORE = 9
SW_SHOW = 5


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


def _send(*inputs: _INPUT) -> None:
    array = (_INPUT * len(inputs))(*inputs)
    _user32.SendInput(len(inputs), array, ctypes.sizeof(_INPUT))


def _mouse_input(flags: int, dx: int = 0, dy: int = 0) -> _INPUT:
    item = _INPUT()
    item.type = INPUT_MOUSE
    item.u.mi = _MOUSEINPUT(dx, dy, 0, flags, 0, None)
    return item


def _key_input(vk: int, flags: int = 0, scan: int = 0) -> _INPUT:
    item = _INPUT()
    item.type = INPUT_KEYBOARD
    item.u.ki = _KEYBDINPUT(vk, scan, flags, 0, None)
    return item


# ---------- 窗口 ----------
VK_ALT = 0x12

_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.c_void_p]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
_user32.AttachThreadInput.restype = wintypes.BOOL
_user32.SetForegroundWindow.argtypes = [wintypes.HWND]
_user32.SetForegroundWindow.restype = wintypes.BOOL
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.BringWindowToTop.argtypes = [wintypes.HWND]
_user32.BringWindowToTop.restype = wintypes.BOOL


def set_foreground(hwnd: int) -> bool:
    """把窗口置前并激活。

    Windows 有「前台锁定」：非前台进程直接调用 SetForegroundWindow 常被静默拒绝。
    这里按常规做法依次尝试：AttachThreadInput 共享输入队列 → SetForegroundWindow →
    仍失败则先用 Alt 键解锁前台锁定再试一次。
    """
    handle = ctypes.c_void_p(hwnd)
    if _user32.IsIconic(handle):
        _user32.ShowWindow(handle, SW_RESTORE)
    _user32.ShowWindow(handle, SW_SHOW)

    if int(_user32.GetForegroundWindow() or 0) == hwnd:
        return True

    foreground = int(_user32.GetForegroundWindow() or 0)
    our_thread = _kernel32.GetCurrentThreadId()
    fg_thread = 0
    if foreground:
        fg_thread = int(_user32.GetWindowThreadProcessId(ctypes.c_void_p(foreground), None))

    attached = False
    if fg_thread and fg_thread != our_thread:
        attached = bool(_user32.AttachThreadInput(fg_thread, our_thread, True))
    try:
        _user32.BringWindowToTop(handle)
        _user32.SetForegroundWindow(handle)
        time.sleep(0.3)
    finally:
        if attached:
            _user32.AttachThreadInput(fg_thread, our_thread, False)

    if int(_user32.GetForegroundWindow() or 0) == hwnd:
        return True

    # 最后手段：模拟一次 Alt 按键解除前台锁定，再试一次
    _send(_key_input(VK_ALT), _key_input(VK_ALT, KEYEVENTF_KEYUP))
    time.sleep(0.05)
    _user32.BringWindowToTop(handle)
    _user32.SetForegroundWindow(handle)
    time.sleep(0.3)
    return int(_user32.GetForegroundWindow() or 0) == hwnd


def get_foreground() -> int:
    return int(_user32.GetForegroundWindow())


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    rect = wintypes.RECT()
    _user32.GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


# ---------- 光标 ----------
class _POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


_user32.GetCursorPos.argtypes = [ctypes.POINTER(_POINT)]
_user32.GetCursorPos.restype = wintypes.BOOL
_user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
_user32.SetCursorPos.restype = wintypes.BOOL


def cursor_pos() -> tuple[int, int]:
    point = _POINT()
    if not _user32.GetCursorPos(ctypes.byref(point)):
        return (0, 0)
    return point.x, point.y


def set_cursor_pos(x: int, y: int) -> None:
    _user32.SetCursorPos(int(x), int(y))


# ---------- 用户活跃度 ----------
class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


_user32.GetLastInputInfo.argtypes = [ctypes.POINTER(_LASTINPUTINFO)]
_user32.GetLastInputInfo.restype = wintypes.BOOL
_kernel32.GetTickCount.argtypes = []
_kernel32.GetTickCount.restype = wintypes.DWORD


def user_idle_seconds() -> float:
    """距离用户最后一次键鼠操作过了多少秒（用于"别在人家打字时抢焦点"）。"""
    info = _LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(info)
    if not _user32.GetLastInputInfo(ctypes.byref(info)):
        return 999.0
    return max(0.0, (_kernel32.GetTickCount() - info.dwTime) / 1000.0)


def wait_until_user_idle(*, threshold: float = 1.5, max_wait: float = 8.0) -> bool:
    """等用户停手（空闲超过 threshold 秒）再动手，最多等 max_wait 秒。

    返回 True 表示等到空闲；False 表示等超时了（仍然会继续发送，只是可能打扰到用户）。
    """
    deadline = time.time() + max(0.0, max_wait)
    while time.time() < deadline:
        if user_idle_seconds() >= threshold:
            return True
        time.sleep(0.4)
    return user_idle_seconds() >= threshold


# ---------- 鼠标 ----------
def move_to(x: int, y: int, *, steps: int = 4, step_delay: float = 0.015) -> None:
    """把光标移到目标（分几步走，避免"瞬移"这种明显的机器特征）。"""
    start_x, start_y = cursor_pos()
    steps = max(1, int(steps))
    for index in range(1, steps + 1):
        ratio = index / steps
        _user32.SetCursorPos(
            int(start_x + (x - start_x) * ratio),
            int(start_y + (y - start_y) * ratio),
        )
        time.sleep(step_delay)


def click(x: int, y: int, *, settle: float = 0.45, smooth: bool = True) -> None:
    """在屏幕绝对坐标 (x, y) 单击（默认先平滑移动过去）。"""
    if smooth:
        move_to(x, y)
    else:
        _user32.SetCursorPos(int(x), int(y))
    screen_w = _user32.GetSystemMetrics(0)
    screen_h = _user32.GetSystemMetrics(1)
    abs_x = int(x * 65535 / max(1, screen_w - 1))
    abs_y = int(y * 65535 / max(1, screen_h - 1))
    _send(_mouse_input(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, abs_x, abs_y))
    time.sleep(0.05)
    _send(_mouse_input(MOUSEEVENTF_LEFTDOWN), _mouse_input(MOUSEEVENTF_LEFTUP))
    time.sleep(settle)


# ---------- 键盘 ----------
def press(vk: int, *, settle: float = 0.08) -> None:
    _send(_key_input(vk), _key_input(vk, KEYEVENTF_KEYUP))
    time.sleep(settle)


def type_unicode(text: str, *, per_char_delay: float = 0.012) -> None:
    """逐字以 Unicode 事件输入（适合中文，不占用剪贴板）。"""
    for char in text:
        code = ord(char)
        _send(
            _key_input(0, KEYEVENTF_UNICODE, code),
            _key_input(0, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, code),
        )
        time.sleep(per_char_delay)


def press_enter(*, settle: float = 0.5) -> None:
    press(VK_RETURN, settle=settle)


# ---------- 剪贴板 ----------
# ⚠ 必须显式声明 argtypes/restype：64 位下句柄是 64 位，ctypes 默认按 c_int 处理会把
#   句柄截断成 32 位，导致 GlobalLock 拿到无效指针、剪贴板写入静默失败。
_user32.OpenClipboard.argtypes = [wintypes.HWND]
_user32.OpenClipboard.restype = wintypes.BOOL
_user32.EmptyClipboard.argtypes = []
_user32.EmptyClipboard.restype = wintypes.BOOL
_user32.CloseClipboard.argtypes = []
_user32.CloseClipboard.restype = wintypes.BOOL
_user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
_user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
_user32.GetClipboardData.argtypes = [wintypes.UINT]
_user32.GetClipboardData.restype = wintypes.HANDLE
_user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
_user32.SetClipboardData.restype = wintypes.HANDLE

_kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
_kernel32.GlobalAlloc.restype = wintypes.HANDLE
_kernel32.GlobalLock.argtypes = [wintypes.HANDLE]
_kernel32.GlobalLock.restype = ctypes.c_void_p
_kernel32.GlobalUnlock.argtypes = [wintypes.HANDLE]
_kernel32.GlobalUnlock.restype = wintypes.BOOL
_kernel32.GlobalFree.argtypes = [wintypes.HANDLE]
_kernel32.GlobalFree.restype = wintypes.HANDLE


def get_clipboard_text() -> str:
    """读取当前剪贴板文本（用于发送前备份、发送后还原）。"""
    if not _user32.OpenClipboard(None):
        return ""
    try:
        if not _user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return ""
        handle = _user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return ""
        pointer = _kernel32.GlobalLock(handle)
        if not pointer:
            return ""
        try:
            return ctypes.wstring_at(pointer)
        finally:
            _kernel32.GlobalUnlock(handle)
    finally:
        _user32.CloseClipboard()


def set_clipboard_text(text: str, *, retries: int = 5) -> bool:
    """把文本写入剪贴板（粘贴中文比逐字输入更稳）。剪贴板被占用时重试几次。"""
    data = text.encode("utf-16-le") + b"\x00\x00"
    for attempt in range(max(1, retries)):
        if not _user32.OpenClipboard(None):
            time.sleep(0.12)
            continue
        try:
            if not _user32.EmptyClipboard():
                time.sleep(0.12)
                continue
            handle = _kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
            if not handle:
                time.sleep(0.12)
                continue
            pointer = _kernel32.GlobalLock(handle)
            if not pointer:
                _kernel32.GlobalFree(handle)
                time.sleep(0.12)
                continue
            ctypes.memmove(pointer, data, len(data))
            _kernel32.GlobalUnlock(handle)
            if not _user32.SetClipboardData(CF_UNICODETEXT, handle):
                _kernel32.GlobalFree(handle)
                time.sleep(0.12)
                continue
            return True  # 所有权已交给系统，不能再 GlobalFree
        except Exception:
            time.sleep(0.12)
        finally:
            _user32.CloseClipboard()
    return False


def paste(*, settle: float = 0.35) -> None:
    """Ctrl+V 粘贴。"""
    _send(_key_input(VK_CONTROL), _key_input(VK_V), _key_input(VK_V, KEYEVENTF_KEYUP), _key_input(VK_CONTROL, KEYEVENTF_KEYUP))
    time.sleep(settle)
