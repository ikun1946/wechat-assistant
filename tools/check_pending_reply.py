"""实测：程序启动时，当前会话里"最后一条是对方发的"应该被识别。

用法：.venv/Scripts/python.exe tools/check_pending_reply.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wxbot.wechat.vision_client import VisionClient  # noqa: E402


def main() -> int:
    print("=== 全新启动（模拟程序刚打开）===")
    client = VisionClient()
    for i in range(1, 4):
        messages = client.poll_new_messages()
        print(f"  第 {i} 轮：识别 {len(messages)} 条")
        for message in messages:
            print(f"     -> {message.chat_name}: {message.text[:60]!r}")
        if messages:
            print()
            print("✅ 成功：启动时就识别到了未回消息（不再被基线吞掉）")
            print("   下一轮不应该重复上报：")
            time.sleep(1.2)
            again = client.poll_new_messages()
            print(f"   第 4 轮：{len(again)} 条（应为 0，避免重复回复）")
            return 0
        time.sleep(1.5)
    print()
    print("❌ 三轮都没识别到。当前会话最后一条可能是我自己发的（已回），属正常。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
