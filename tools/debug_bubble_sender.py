"""诊断：打印当前微信会话里"代码看见的气泡"及其左右判定。

只读，不发消息。用法：
    .venv/Scripts/python.exe tools/debug_bubble_sender.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wxbot.wechat.capture import find_main_window, grab_bgr  # noqa: E402
from wxbot.wechat.vision_client import VisionClient  # noqa: E402
from wxbot.textutil import normalize_name  # noqa: E402


def main() -> int:
    client = VisionClient()
    window = find_main_window()
    if not window:
        print("没有找到微信窗口")
        return 1
    frame = grab_bgr(int(window["hwnd"]))
    if frame is None:
        print("抓屏失败")
        return 1

    h, w = frame.shape[:2]
    print(f"窗口尺寸: {w}x{h}   中线 x = {w / 2:.0f}")
    header = client._read_header(frame)
    print(f"当前会话标题: {header!r}  (归一化 {normalize_name(header or '')!r})")
    print()

    bubbles = client.read_chat_bubbles(frame)
    print(f"识别到 {len(bubbles)} 条气泡：")
    for i, b in enumerate(bubbles):
        ratio = b.center_x / w if w else 0
        print(
            f"  [{i}] sender={b.sender:7s} center_x={b.center_x:6.0f} "
            f"(占宽 {ratio:.0%}) y={b.y:6.0f} score={b.score:.2f}  {b.text[:40]!r}"
        )

    print()
    latest = client._latest_definite_bubble(bubbles)
    if latest is None:
        print("_latest_definite_bubble -> None  → 不会回复")
    else:
        verdict = "会回复！" if latest.sender == "them" else "不会回复"
        print(f"_latest_definite_bubble -> sender={latest.sender}  {verdict}")
        print(f"   文本: {latest.text[:50]!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
