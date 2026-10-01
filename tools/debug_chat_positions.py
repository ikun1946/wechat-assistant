"""诊断：聊天区每条消息的横坐标分布（用来判断"谁发的"）。

用法：.venv/Scripts/python.exe tools/debug_chat_positions.py

会列出聊天区 OCR 到的每条文本的中心 x，帮你确定左右分界线。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2  # noqa: E402

from wxbot.wechat.capture import find_main_window, grab_bgr  # noqa: E402
from wxbot.wechat.vision_client import SESSION_LIST_WIDTH_RATIO, VisionClient  # noqa: E402


def main() -> int:
    client = VisionClient()
    window = find_main_window()
    if not window:
        print("没有找到微信窗口")
        return 2
    image = grab_bgr(int(window["hwnd"]))
    height, width = image.shape[:2]
    panel_w = int(width * SESSION_LIST_WIDTH_RATIO)
    chat_w = width - panel_w
    print(f"帧尺寸 {width}x{height}  会话列表宽 {panel_w}  聊天区宽 {chat_w}")
    print(f"聊天区中线 x = {panel_w + chat_w / 2:.0f}")

    region = image[int(height * 0.14) : int(height * 0.72), panel_w:]
    cv2.imwrite("logs/chat_region.png", region)
    result, _ = client._ocr(region)
    rows = []
    for box, text, score in (result or []):
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        rows.append((sum(ys) / len(ys), min(xs), max(xs), sum(xs) / len(xs), str(text), float(score)))
    rows.sort()
    print()
    print(f"{'y':>7} {'x0':>6} {'x1':>6} {'中心x':>7}  {'文本':<28} 分数")
    print("-" * 78)
    for y, x0, x1, xc, text, score in rows:
        # 换算成整帧坐标，便于对照截图
        print(f"{y:7.1f} {x0:6.1f} {x1:6.1f} {xc:7.1f}  {text:<28} {score:.2f}")
    print()
    print("提示：中心 x 明显偏左的是对方消息，偏右（贴右边）的是我自己的消息。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
