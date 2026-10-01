r"""后台写入能力实验：不置前、不动鼠标，能否点击微信会话行？

用法：.venv\Scripts\python.exe tools\experiment_background_click.py --index 2

原理：用 PostMessage 直接向微信窗口投递 WM_LBUTTONDOWN/UP（lParam 为客户区坐标）。
如果 Qt 接受投递的鼠标消息，就能实现"后台点击"——不抢前台、不动用户鼠标。

严格的对照：实验前先把**别的窗口**切到前台，确保微信真的在后台，
再投递点击，最后确认 ① 会话切换了 ② 微信仍在后台。
本实验只做点击（切换会话），不输入、不发送。
"""

from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2  # noqa: E402

from wxbot.wechat.capture import grab_bgr  # noqa: E402
from wxbot.wechat.vision_client import SESSION_LIST_WIDTH_RATIO, VisionClient  # noqa: E402

_user32 = ctypes.windll.user32

WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_MOUSEMOVE = 0x0200
MK_LBUTTON = 0x0001

_user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.PostMessageW.restype = wintypes.BOOL
_user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.SendMessageW.restype = ctypes.c_ssize_t


def esc(text: str) -> str:
    return text.encode("unicode_escape").decode("ascii")


def make_lparam(x: int, y: int) -> int:
    return (y << 16) | (x & 0xFFFF)


def find_other_window(exclude_hwnd: int) -> int:
    """找一个别的顶层窗口（优先自己的 GUI），用来把微信挤到后台。"""
    CB = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    found: list[tuple[int, str]] = []

    def callback(hwnd, _lparam):
        if not _user32.IsWindowVisible(hwnd):
            return True
        length = _user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        _user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value
        if int(hwnd) == exclude_hwnd or "IME" in title:
            return True
        found.append((int(hwnd), title))
        return True

    _user32.EnumWindows(CB(callback), 0)
    for hwnd, title in found:
        if "wxbot" in title:
            return hwnd
    return found[0][0] if found else 0


def main() -> int:
    index = 2
    argv = sys.argv[1:]
    if "--index" in argv:
        index = int(argv[argv.index("--index") + 1])

    client = VisionClient()
    window = client._window()
    if not window:
        print("[err  ] no wechat window")
        return 2
    hwnd = int(window["hwnd"])

    # 先把别的窗口切到前台，确保微信真的在后台
    other = find_other_window(hwnd)
    if other:
        from wxbot.wechat import input as input_ctl

        input_ctl.set_foreground(other)
        time.sleep(0.5)
    foreground = int(_user32.GetForegroundWindow() or 0)
    print(f"[state] foreground={hex(foreground)} wechat={hex(hwnd)} "
          f"wechat_is_foreground={foreground == hwnd}")

    image = grab_bgr(hwnd)
    height, width = image.shape[:2]
    rows = client.read_sessions(image)
    if index >= len(rows):
        print(f"[err  ] index {index} out of range ({len(rows)} rows)")
        return 3
    target = rows[index]

    print(f"[rows ] target #{index} y={target.y_center} name={esc(target.name)}")
    print(f"[head ] before = {esc(client._read_header(image))}")

    client_x = int(width * SESSION_LIST_WIDTH_RATIO * 0.78)
    client_y = target.y_center
    print(f"[post ] client point ({client_x},{client_y}) via PostMessage (no cursor move)")

    _user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, make_lparam(client_x, client_y))
    time.sleep(0.05)
    _user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, make_lparam(client_x, client_y))
    time.sleep(0.05)
    _user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, make_lparam(client_x, client_y))
    time.sleep(0.9)

    after = grab_bgr(hwnd)
    header = client._read_header(after)
    cv2.imwrite(str(Path(__file__).resolve().parents[1] / "logs" / "bg_click.png"), after)
    foreground_after = int(_user32.GetForegroundWindow() or 0)
    print(f"[head ] after  = {esc(header)}")
    print(f"[state] wechat_still_background = {foreground_after != hwnd}")

    ok = bool(header) and header.strip() == target.name.strip()
    print(f"[result] background click {'WORKS' if ok else 'FAILED'}")
    return 0 if ok else 4


if __name__ == "__main__":
    raise SystemExit(main())
