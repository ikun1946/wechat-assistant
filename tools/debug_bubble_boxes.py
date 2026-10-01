"""诊断：打印聊天区 OCR 的原始框，用真实数据标定"换行合并"的垂直阈值。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wxbot.wechat.capture import find_main_window, grab_bgr  # noqa: E402
from wxbot.wechat.vision_client import SESSION_LIST_WIDTH_RATIO  # noqa: E402
from wxbot.wechat.vision_client import VisionClient  # noqa: E402


def main() -> int:
    client = VisionClient()
    window = find_main_window()
    if not window:
        print("没有找到微信窗口")
        return 1
    frame = grab_bgr(int(window["hwnd"]))
    height, width = frame.shape[:2]
    panel_width = int(width * SESSION_LIST_WIDTH_RATIO)
    chat_width = width - panel_width
    region = frame[int(height * 0.14) : int(height * 0.72), panel_width:]
    result, _ = client._ocr(region)
    if not result:
        print("OCR 无结果")
        return 1

    rows = []
    for box, text, score in result:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        rows.append((min(ys), max(ys), min(xs), max(xs), str(text).strip()))
    rows.sort()

    print(f"chat_width={chat_width}  中线={chat_width/2:.0f}  自己的阈值={chat_width/2 + chat_width*0.12:.0f}")
    print(f"{'top':>5} {'bot':>5} {'h':>4} {'left':>5} {'right':>6} {'center':>7}  文本")
    prev_bot = None
    for top, bot, left, right, text in rows:
        gap = "" if prev_bot is None else f" gap={top - prev_bot:5.0f} ({((top-prev_bot)/max(bot-top,1)):4.2f}x高)"
        print(
            f"{top:5.0f} {bot:5.0f} {bot-top:4.0f} {left:5.0f} {right:6.0f} "
            f"{(left+right)/2:7.0f}{gap}  {text[:32]}"
        )
        prev_bot = bot
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
