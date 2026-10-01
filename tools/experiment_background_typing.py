r"""后台打字能力实验：不置前、不动鼠标，能否把文字送进微信输入框？

用法：.venv\Scripts\python.exe tools\experiment_background_typing.py

步骤（全部用 PostMessage，不移动光标、不发真实按键）：
1) 把别的窗口切前台，确保微信在后台；
2) 后台点击某个会话行（切换会话）；
3) 后台点击输入框；
4) 后台投递 WM_CHAR 逐字输入一段测试文字；
5) 抓屏 OCR 输入框，看文字是否真的进去了；
6) 清理：后台投递 Ctrl+A + Delete，把输入框清空（**不会按回车，不会发出消息**）。
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

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_user32 = ctypes.windll.user32

WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_CHAR = 0x0102
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
MK_LBUTTON = 0x0001
VK_CONTROL = 0x11
VK_A = 0x41
VK_DELETE = 0x2E

TEST_TEXT = "后台输入测试"

_user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.PostMessageW.restype = wintypes.BOOL


def esc(text: str) -> str:
    return text.encode("unicode_escape").decode("ascii")


def lp(x: int, y: int) -> int:
    return (y << 16) | (x & 0xFFFF)


def post_click(hwnd: int, x: int, y: int) -> None:
    _user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, lp(x, y))
    time.sleep(0.03)
    _user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lp(x, y))
    time.sleep(0.03)
    _user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lp(x, y))


def post_char(hwnd: int, char: str) -> None:
    _user32.PostMessageW(hwnd, WM_CHAR, ord(char), 1)


def post_key(hwnd: int, vk: int, *, ctrl: bool = False) -> None:
    if ctrl:
        _user32.PostMessageW(hwnd, WM_KEYDOWN, VK_CONTROL, 0)
    _user32.PostMessageW(hwnd, WM_KEYDOWN, vk, 0)
    _user32.PostMessageW(hwnd, WM_KEYUP, vk, 0)
    if ctrl:
        _user32.PostMessageW(hwnd, WM_KEYUP, VK_CONTROL, 0)


def cursor_pos() -> tuple[int, int]:
    point = wintypes.POINT()
    _user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


def input_box_text(client: VisionClient, frame) -> str:
    height, width = frame.shape[:2]
    panel_width = int(width * SESSION_LIST_WIDTH_RATIO)
    region = frame[int(height * 0.76) : int(height * 0.94), panel_width:]
    if client._ocr is None or region.size == 0:
        return ""
    result, _ = client._ocr(region)
    return " ".join(str(item[1]) for item in (result or []))


def main() -> int:
    client = VisionClient()
    window = client._window()
    if not window:
        print("[err  ] no wechat window")
        return 2
    hwnd = int(window["hwnd"])

    from wxbot.wechat import input as input_ctl

    other = _find_other(hwnd)
    if other:
        input_ctl.set_foreground(other)
        time.sleep(0.5)
    print(f"[state] wechat_foreground={int(_user32.GetForegroundWindow() or 0) == hwnd}")

    frame = grab_bgr(hwnd)
    height, width = frame.shape[:2]
    rows = client.read_sessions(frame)
    if not rows:
        print("[err  ] no session rows")
        return 3
    target = rows[min(2, len(rows) - 1)]
    print(f"[rows ] target name={esc(target.name)} y={target.y_center}")

    cursor_before = cursor_pos()
    print(f"[cursor] before = {cursor_before}")

    print("[post ] click session row ...")
    post_click(hwnd, int(width * SESSION_LIST_WIDTH_RATIO * 0.78), target.y_center)
    time.sleep(0.6)

    panel_width = int(width * SESSION_LIST_WIDTH_RATIO)
    input_x = panel_width + int((width - panel_width) * 0.5)
    input_y = int(height * 0.84)
    print(f"[post ] click input box at ({input_x},{input_y}) ...")
    post_click(hwnd, input_x, input_y)
    time.sleep(0.4)

    print(f"[post ] WM_CHAR x{len(TEST_TEXT)} -> {esc(TEST_TEXT)}")
    for char in TEST_TEXT:
        post_char(hwnd, char)
        time.sleep(0.03)
    time.sleep(0.5)

    after = grab_bgr(hwnd)
    cv2.imwrite(str(PROJECT_ROOT / "logs" / "bg_typing.png"), after)
    typed = input_box_text(client, after)
    print(f"[ocr  ] input box = {esc(typed)}")
    works = TEST_TEXT.replace(" ", "") in typed.replace(" ", "")
    print(f"[result] background typing {'WORKS' if works else 'FAILED'}")

    cursor_after = cursor_pos()
    print(f"[cursor] after = {cursor_after} (moved={cursor_before != cursor_after})")
    print(f"[state] wechat_foreground_after={int(_user32.GetForegroundWindow() or 0) == hwnd}")

    print("[clean] posting Ctrl+A + Delete to clear input box (no Enter, nothing sent)")
    post_key(hwnd, VK_A, ctrl=True)
    time.sleep(0.2)
    post_key(hwnd, VK_DELETE)
    time.sleep(0.4)
    cleared = grab_bgr(hwnd)
    print(f"[ocr  ] after cleanup = {esc(input_box_text(client, cleared))}")
    return 0 if works else 4


def _find_other(exclude_hwnd: int) -> int:
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


if __name__ == "__main__":
    raise SystemExit(main())
