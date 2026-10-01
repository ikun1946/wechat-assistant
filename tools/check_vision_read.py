"""视觉识别自检：抓一次微信窗口，读出会话列表（只读，不点击不发送）。

用法：.venv/Scripts/python.exe tools/check_vision_read.py
输出：识别到的会话名 / 摘要 / 是否有未读红点，以及抓屏与 OCR 耗时。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wxbot.wechat.vision_client import VisionClient


def main() -> int:
    client = VisionClient()
    available, reason = client.is_available()
    print(f"[可用性] {'✅ 可读' if available else '❌ 不可读'}：{reason}")
    if not available:
        return 2

    started = time.time()
    image = client.capture()
    captured = time.time()
    if image is None:
        print("[抓屏] ❌ 没抓到画面（窗口可能隐藏/最小化）")
        return 3
    print(f"[抓屏] ✅ {image.shape[1]}x{image.shape[0]}，耗时 {captured - started:.2f}s")

    rows = client.read_sessions(image)
    finished = time.time()
    print(f"[识别] 会话列表共 {len(rows)} 行，OCR 耗时 {finished - captured:.2f}s")
    print()
    if not rows:
        print("（没识别到会话行：可能会话列表为空，或窗口布局与预期不同）")
        return 0
    print(f"{'未读':<4} {'会话名':<24} 消息摘要")
    print("-" * 78)
    for row in rows:
        flag = "🔴" if row.unread else "  "
        name = row.name[:22]
        print(f"{flag:<4} {name:<24} {row.preview[:40]}")

    unread = [row for row in rows if row.unread]
    print()
    print(f"其中有未读红点的：{len(unread)} 个")
    for row in unread:
        print(f"  - {row.name}")
    print()
    print("说明：识别基于抓屏 + OCR，只读；不会点击、不会发送任何消息。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
