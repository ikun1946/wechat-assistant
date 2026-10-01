"""实时验证：程序能否抓到"当前打开的会话"里的新消息（微信不给它显示红点）。

用法：.venv/Scripts/python.exe tools/check_current_chat.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wxbot.wechat.vision_client import VisionClient  # noqa: E402


def main() -> int:
    client = VisionClient()
    print("=== 第 1 轮（建立基线）===")
    started = time.time()
    first = client.poll_new_messages()
    print(f"  耗时 {time.time() - started:.2f}s，识别到 {len(first)} 条")
    print(f"  当前打开的会话: {client._current_chat!r}")
    body = client._current_body
    print(f"  当前会话内容（前 80 字）: {body[:80]!r}")
    print(f"  会话列表行数: {len(client.read_sessions())}")

    print()
    print("=== 第 2 轮（正常轮询）===")
    started = time.time()
    second = client.poll_new_messages()
    print(f"  耗时 {time.time() - started:.2f}s，识别到 {len(second)} 条")
    for message in second:
        print(f"    - {message.chat_name}: {message.text[:70]!r}")

    print()
    print("说明：如果对方此时再发一条新消息，第 2 轮（或下一轮）应该能抓到，")
    print("      即使该会话正打开、微信没有显示未读红点。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
