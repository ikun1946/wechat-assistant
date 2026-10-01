"""检查对话记忆：找出泄露身份的旧回复、截断的半句、重复的同一条消息。"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

LEAK_WORDS = ("助手", "AI", "机器人", "程序", "模型", "代回复")
MEMORY_PATH = Path(__file__).resolve().parents[1] / "data" / "chat_memory.json"


def main() -> int:
    data = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
    chats = data.get("chats", {})
    for name, messages in chats.items():
        print(f"=== {name}（{len(messages)} 条）===")
        for index, message in enumerate(messages):
            role = "对方" if message.get("role") == "them" else "我方"
            text = message.get("text", "")
            flags = []
            if any(word in text for word in LEAK_WORDS):
                flags.append("泄露身份")
            if text and text[-1] in "，,、 " and len(text) < 14:
                flags.append("截断半句")
            mark = "  <== " + " / ".join(flags) if flags else ""
            print(f"  [{index:2d}] {role}: {text[:46]}{mark}")

        counts = Counter((m.get("role"), m.get("text", "").strip()) for m in messages)
        repeated = {k: v for k, v in counts.items() if v > 1}
        if repeated:
            print(f"  ⚠ 重复条目 {len(repeated)} 种：")
            for (role, text), count in sorted(repeated.items(), key=lambda kv: -kv[1]):
                who = "对方" if role == "them" else "我方"
                print(f"      {who}「{text[:30]}」× {count}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
