"""托盘常驻 + 全局急停热键（把脚本变成"应用"的两块拼图）。

为什么需要这两块：
- **托盘常驻**：这是一个常驻后台、偶尔开窗看一眼的程序。关窗口就退出
  意味着用户必须一直开着那个大窗口；而窗口挡住微信又会被误当成机器人输入。
- **全局急停**：这个程序会**代替用户往微信里打字**。万一模型抽风、开始乱回，
  必须有一个"任何时候按一下、立刻停手"的刹车 —— 而且不能要求用户先切到本程序。

设计要点：
- 急停走 `RegisterHotKey`（Win32 全局热键），**不轮询、不抢焦点**；
  触发时只做两件事：关掉运行开关 + 写审计日志，不弹窗、不抢焦点。
- 托盘图标在内存里用 QPainter 画，不依赖外部 .ico 文件（打包时少一个坑）。
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes


def _user32():
    return ctypes.windll.user32


# --- 通知图标消息（不依赖 shell32 的完整定义，写死即可） ---
NIM_ADD = 0x00
NIM_MODIFY = 0x01
NIM_DELETE = 0x02
NIF_MESSAGE = 0x01
NIF_ICON = 0x02
NIF_TIP = 0x04
NIF_INFO = 0x10

IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
LR_DEFAULTSIZE = 0x0040

# 全局热键用到的修饰键 / 虚拟键
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000
VK_Q = 0x51
WM_HOTKEY = 0x0312


class NOTIFYICONDATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", ctypes.c_byte * 16),
        ("hBalloonIcon", wintypes.HICON),
    ]


def register_hotkey(hwnd: int, ident: int, modifiers: int, vk: int) -> bool:
    return bool(_user32().RegisterHotKey(wintypes.HWND(hwnd), ident, modifiers, vk))


def unregister_hotkey(hwnd: int, ident: int) -> None:
    _user32().UnregisterHotKey(wintypes.HWND(hwnd), ident)


def show_tray_bubble(hwnd: int, uid: int, title: str, text: str) -> None:
    data = NOTIFYICONDATA()
    data.cbSize = ctypes.sizeof(NOTIFYICONDATA)
    data.hWnd = wintypes.HWND(hwnd)
    data.uID = uid
    data.uFlags = NIF_INFO
    data.szInfoTitle = title[:63]
    data.szInfo = text[:255]
    data.dwInfoFlags = 0x01  # NIIF_INFO
    _user32().Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(data))


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_dir() -> str:
    """打包后 exe 所在目录；源码运行时返回项目根目录。"""
    import os

    if is_frozen():
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
