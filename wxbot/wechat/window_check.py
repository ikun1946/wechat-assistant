"""检测本机微信窗口（只读，不触碰微信进程内部）。

用 Win32 API 枚举顶层窗口，筛选进程名为 Weixin.exe / WeChat.exe 的窗口。
微信 4.x（Weixin.exe）是多进程架构，主窗口可能挂在其一子进程上，
这里按「进程名过滤 + 有标题/可见」收集，供状态检查与后续客户端接入使用。
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_WEIXIN_EXE_NAMES = {"weixin.exe", "wechat.exe"}

_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

_user32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
_user32.EnumWindows.restype = wintypes.BOOL
_user32.IsWindowVisible.argtypes = [wintypes.HWND]
_user32.IsWindowVisible.restype = wintypes.BOOL
_user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
_user32.GetWindowTextLengthW.restype = ctypes.c_int
_user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.GetWindowTextW.restype = ctypes.c_int
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD

_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
]
_kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL


def _process_exe(pid: int) -> str:
    handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        ok = _kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size))
        return buf.value if ok else ""
    finally:
        _kernel32.CloseHandle(handle)


def _exe_basename(path: str) -> str:
    return path.replace("/", "\\").rsplit("\\", 1)[-1].lower()


def find_wechat_windows() -> list[dict]:
    """返回可见的微信顶层窗口列表：[{hwnd, pid, exe, title}, ...]"""
    windows: list[dict] = []

    def _callback(hwnd, _lparam):
        pid = wintypes.DWORD(0)
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        exe = _process_exe(pid.value)
        if _exe_basename(exe) not in _WEIXIN_EXE_NAMES:
            return True
        visible = bool(_user32.IsWindowVisible(hwnd))
        length = _user32.GetWindowTextLengthW(hwnd)
        title_buf = ctypes.create_unicode_buffer(length + 1)
        _user32.GetWindowTextW(hwnd, title_buf, length + 1)
        title = title_buf.value
        ignored = title in {"WxTrayIconMessageWindow", "MSCTFIME UI", "Default IME"} or title.endswith("IME")
        if ignored:
            return True  # 跳过输入法/托盘消息窗等辅助窗口
        if not visible and not title:
            return True  # 跳过隐藏且无标题的辅助窗口
        windows.append(
            {
                "hwnd": int(hwnd),
                "pid": pid.value,
                "exe": exe.rsplit("\\", 1)[-1] if exe else "",
                "title": title,
                "visible": visible,
            }
        )
        return True

    _user32.EnumWindows(_WNDENUMPROC(_callback), 0)
    return windows
