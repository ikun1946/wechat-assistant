"""输入环节分步诊断（不会发送消息）。

用法：.venv\\Scripts\\python.exe tools\\check_input_debug.py

步骤：置前 → 点击输入框 → 写剪贴板 → 粘贴 → 抓屏 OCR 输入框看是否出现文字
→ 清空输入框（Ctrl+A / Delete）。全程不按回车，不会发出任何消息。
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

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MESSAGE = "输入测试请在发送前删除"
VK_A = 0x41
VK_DELETE = 0x2E


def esc(text: str) -> str:
    return text.encode("unicode_escape").decode("ascii")


def main() -> int:
    client = VisionClient()
    window = client._window()
    if not window:
        print("[err  ] no wechat window")
        return 2
    hwnd = int(window["hwnd"])
    ensure_window_visible(hwnd)

    print(f"[fg   ] set_foreground -> {input_ctl.set_foreground(hwnd)}")
    image = grab_bgr(hwnd)
    height, width = image.shape[:2]
    offset_x, offset_y = client._screen_offsets(hwnd, image)
    panel_width = int(width * SESSION_LIST_WIDTH_RATIO)
    input_x = offset_x + panel_width + int((width - panel_width) * 0.5)
    input_y = offset_y + int(height * 0.84)
    print(f"[geom ] frame {width}x{height} panel={panel_width} offset=({offset_x},{offset_y})")
    print(f"[geom ] input click at screen ({input_x},{input_y}) = frame ({input_x-offset_x},{input_y-offset_y})")

    print("[click] clicking input box ...")
    input_ctl.click(input_x, input_y)

    wrote = input_ctl.set_clipboard_text(MESSAGE)
    print(f"[clip ] set_clipboard_text -> {wrote}")
    print(f"[clip ] read back -> {esc(input_ctl.get_clipboard_text()[:40])}")

    print("[paste] ctrl+V ...")
    input_ctl.paste()
    time.sleep(0.4)

    frame = grab_bgr(hwnd)
    cv2.imwrite(str(PROJECT_ROOT / "logs" / "input_debug.png"), frame)
    region = frame[int(height * 0.76) : int(height * 0.94), panel_width:]
    if client._ocr is not None:
        result, _ = client._ocr(region)
        texts = [str(item[1]) for item in (result or [])]
        print(f"[ocr  ] input area texts = {[esc(t) for t in texts]}")
    else:
        print("[ocr  ] no ocr engine")

    print("[clean] clearing input box (ctrl+A, delete) ...")
    input_ctl._send(  # noqa: SLF001 - 诊断脚本，直接用底层按键
        input_ctl._key_input(0x11),  # Ctrl
        input_ctl._key_input(VK_A),
        input_ctl._key_input(VK_A, input_ctl.KEYEVENTF_KEYUP),
        input_ctl._key_input(0x11, input_ctl.KEYEVENTF_KEYUP),
    )
    time.sleep(0.15)
    input_ctl.press(VK_DELETE)
    time.sleep(0.3)

    after = grab_bgr(hwnd)
    cv2.imwrite(str(PROJECT_ROOT / "logs" / "input_debug_cleared.png"), after)
    print("[done ] images: logs/input_debug.png, logs/input_debug_cleared.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
