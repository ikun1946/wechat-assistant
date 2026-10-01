"""诊断：对话历史是否真的传给了模型？模型能否利用上下文？

用法：.venv/Scripts/python.exe tools/check_memory_context.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wxbot.brain.llm import LLMEngine  # noqa: E402
from wxbot.brain.memory import ChatMemory  # noqa: E402
from wxbot.config import LLMConfig, load_config  # noqa: E402


def main() -> int:
    cfg = load_config()
    print(f"当前模型: {cfg.llm.model}")
    print(f"记忆条数上限: {cfg.skills.memory.max_messages}（enabled={cfg.skills.memory.enabled}）")
    print()

    # 1) 看记忆里的会话名是否被劈开
    path = Path("data/chat_memory.json")
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        names = list(data.get("chats", {}).keys())
        from wxbot.textutil import normalize_name

        groups: dict[str, list[str]] = {}
        for name in names:
            groups.setdefault(normalize_name(name), []).append(name)
        print("=== 记忆里的会话名（归一化后分组）===")
        for key, variants in groups.items():
            mark = "  ⚠️ 被劈成多个!" if len(variants) > 1 else ""
            print(f"  {key!r}: {variants}{mark}")
        print()

    # 2) 构造一段历史，看模型能否利用
    print("=== 上下文利用测试 ===")
    engine = LLMEngine(cfg.llm)
    system = "你是微信代回复助手，简短口语化回复。"
    history = [
        ("user", "我叫阿哲，喜欢吃辣"),
        ("assistant", "好的阿哲，记住了"),
        ("user", "我养了一只猫叫年糕"),
        ("assistant", "年糕，好名字"),
    ]
    question = "我叫什么名字？我的猫叫什么？"
    try:
        reply = engine.generate(question, system_prompt=system, history=history)
        print(f"  问题: {question}")
        print(f"  回复: {reply}")
        ok = "阿哲" in reply and "年糕" in reply
        print(f"  {'✅ 能利用上下文' if ok else '⚠️ 没能利用上下文（回答里缺少细节）'}")
    except Exception as exc:  # noqa: BLE001
        print(f"  ❌ 调用失败: {exc}")
        return 1

    # 3) 看看真实记忆能取出多少历史
    memory = ChatMemory()
    print()
    print("=== 真实记忆（归一化后）===")
    for name in memory.chats():
        items = memory.recent(name, 8)
        print(f"  [{name}] 共 {memory.count(name)} 条，取最近 {len(items)} 条：")
        for role, text in items:
            who = "对方" if role == "them" else "我"
            print(f"     {who}: {text[:44]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
