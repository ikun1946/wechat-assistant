"""点击链路深度诊断（ASCII 输出，避免控制台编码干扰）。

用法：.venv\\Scripts\\python.exe tools\\check_click_debug.py [行序号，从0开始]

检查内容：
1) 窗口 rect 与 WGC 帧尺寸，推算屏幕偏移；
2) 会话列表识别结果（打印 UTF-8 转义，避免乱码）；
3) SendInput 是否真的生效（看返回值与光标位置变化）；
4) 点击会话行后，多抓几帧看标题是否变化（排除抓屏时序问题）。
"""

from __future__ import annotations

import ctypes
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2  # noqa: E402

from wxbot.wechat import input as input_ctl  # noqa: E402
from wxbot.wechat.capture import ensure_window_visible, grab_bgr  # noqa: E402
from wxbot.wechat.vision_client import SESSION_LIST_WIDTH_RATIO, VisionClient  # noqa: E402

_user32 = ctypes.windll.user32


def esc(text: str) -> str:
    """把中文转成 \\uXXXX，避免控制台编码把输出变成问号。"""
    return text.encode("unicode_escape").decode("ascii")


def cursor_pos() -> tuple[int, int]:
    point = ctypes.wintypes.POINT()
    _user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


def main() -> int:
    index = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    client = VisionClient()

    available, reason = client.is_available()
    print(f"[avail] {available} ({reason})")
    if not available:
        return 2

    window = client._window()
    hwnd = int(window["hwnd"])
    rect = input_ctl.window_rect(hwnd)
    print(f"[rect ] l,t,r,b = {rect}  size = {rect[2]-rect[0]}x{rect[3]-rect[1]}")

    image = grab_bgr(hwnd)
    print(f"[frame] {image.shape[1]}x{image.shape[0]}")
    offset_x, offset_y = client._screen_offsets(hwnd, image)
    print(f"[off  ] screen offset = ({offset_x},{offset_y})")

    rows = client.read_sessions(image)
    print(f"[rows ] {len(rows)} rows")
    for i, row in enumerate(rows):
        print(f"        #{i} y={row.y_center:4d} unread={row.unread} group={row.is_group} name={esc(row.name)}")

    if index >= len(rows):
        print("[err  ] index out of range")
        return 3
    target = rows[index]

    ensure_window_visible(hwnd)
    print(f"[fg   ] set_foreground -> {input_ctl.set_foreground(hwnd)}  "
          f"fg_hwnd={hex(input_ctl.get_foreground())} target={hex(hwnd)}")

    panel_width = int(image.shape[1] * SESSION_LIST_WIDTH_RATIO)
    click_x = offset_x + int(panel_width * 0.78)
    click_y = offset_y + target.y_center
    print(f"[click] frame point ({int(panel_width*0.78)},{target.y_center}) -> screen ({click_x},{click_y})")

    before = cursor_pos()
    result = input_ctl.click(click_x, click_y)
    after = cursor_pos()
    print(f"[input] SendInput ok; cursor {before} -> {after} (moved={before != after})")
    del result

    for attempt in range(3):
        time.sleep(0.8)
        frame = grab_bgr(hwnd)
        header = client._read_header(frame)
        print(f"[after] attempt {attempt+1}: header = {esc(header)}")
        cv2.imwrite(f"logs/after_click_{attempt+1}.png", frame)

    print("[done ] images saved to logs/after_click_*.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
