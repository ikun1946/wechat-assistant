"""记忆迁移：合并被劈开的会话名、清洗脏文本、可选清除指定会话。

用法：
    .venv/Scripts/python.exe tools/migrate_memory.py             # 合并 + 清洗（保留全部）
    .venv/Scripts/python.exe tools/migrate_memory.py --drop 张三  # 顺便清掉某个会话
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wxbot.brain.memory import ChatMemory, clean_message_text  # noqa: E402
from wxbot.config import DATA_DIR  # noqa: E402

PATH = DATA_DIR / "chat_memory.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="记忆迁移")
    parser.add_argument("--drop", action="append", default=[], help="要清掉的会话名（可多次）")
    args = parser.parse_args()

    if not PATH.exists():
        print("没有记忆文件，无需迁移")
        return 0

    import json

    raw = json.loads(PATH.read_text(encoding="utf-8"))
    before = raw.get("chats", {})
    print("=== 迁移前 ===")
    for name, items in before.items():
        print(f"  {name!r}: {len(items)} 条")

    memory = ChatMemory(PATH)  # 加载时已按归一化合并
    # 清洗脏文本（角标数字 / 时间前缀）
    cleaned = 0
    for bucket in memory._chats.values():  # noqa: SLF001
        for item in bucket:
            new_text = clean_message_text(str(item.get("text", "")))
            if new_text != item.get("text"):
                item["text"] = new_text
                cleaned += 1
    for name in args.drop:
        memory.clear(name)
    memory.save()

    print()
    print("=== 迁移后 ===")
    for name, items in memory._chats.items():  # noqa: SLF001
        print(f"  {name!r}: {len(items)} 条")
        for role, text in [(i.get("role"), i.get("text")) for i in items[-4:]]:
            who = "对方" if role == "them" else "我"
            print(f"     {who}: {str(text)[:46]}")

    print()
    print(f"清洗了 {cleaned} 条脏文本")
    if args.drop:
        print(f"已清掉：{'、'.join(args.drop)}")
    print(f"文件：{PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
