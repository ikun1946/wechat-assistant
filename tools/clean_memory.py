"""清理对话记忆里的脏数据（先预览，加 --apply 才写）。

清理三类：
1. **泄露 AI 身份的旧回复** —— 「…代回复助手…」「…我是 AI…」。它们会被当成
   few-shot 示例喂回给模型，教它继续自称助手，必须删掉。
2. **截断的半句** —— 换行气泡被拆开时存进来的「我是钱程月、王静意、」。
3. **连续重复的同一条消息** —— 生成失败重试时每次都记一遍造成的（实测攒到 17 条「你好」）。

保留真正的对话往来。用法：
    .venv/Scripts/python.exe tools/clean_memory.py          # 预览
    .venv/Scripts/python.exe tools/clean_memory.py --apply  # 写入（自动备份）
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

LEAK_WORDS = ("代回复助手", "代回复", "我是 AI", "我是AI", "人工智能助手", "机器人助手")
MEMORY_PATH = Path(__file__).resolve().parents[1] / "data" / "chat_memory.json"


def classify(entry: dict) -> str:
    text = (entry.get("text") or "").strip()
    if not text:
        return "empty"
    if any(word in text for word in LEAK_WORDS):
        return "leak"
    if text[-1] in "，,、" and len(text) < 16:
        return "truncated"
    return ""


def main() -> int:
    apply = "--apply" in sys.argv
    data = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))

    for name, messages in list(data.get("chats", {}).items()):
        seen_run: set[str] = set()
        kept: list[dict] = []
        dropped: list[tuple[str, str, str]] = []

        for entry in messages:
            reason = classify(entry)
            text = (entry.get("text") or "").strip()
            key = f"{entry.get('role')}|{text}"
            if reason:
                dropped.append((reason, entry.get("role", ""), text))
                continue
            # 连续重复（同一方、同文本、且中间没有别人说话）→ 只留第一条
            if key in seen_run:
                dropped.append(("duplicate", entry.get("role", ""), text))
                continue
            seen_run = {key}
            kept.append(entry)

        if not dropped:
            continue
        print(f"=== {name}：{len(messages)} → {len(kept)} 条 ===")
        for reason, role, text in dropped:
            who = "对方" if role == "them" else "我方"
            print(f"  删除[{reason}] {who}: {text[:44]}")
        data["chats"][name] = kept
        print()

    if apply:
        backup = MEMORY_PATH.with_suffix(".json.bak")
        shutil.copy2(MEMORY_PATH, backup)
        MEMORY_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"已写入，备份在 {backup.name}")
    else:
        print("这是预览。确认后加 --apply 真正写入。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
