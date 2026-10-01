"""人设效果验证：完整走程序实际使用的提示词，测"你是谁"这类问题的回答。

用法：.venv/Scripts/python.exe tools/check_persona_identity.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wxbot.brain.llm import LLMEngine, LLMError  # noqa: E402
from wxbot.brain.pipeline import DEFAULT_BASE_PROMPT  # noqa: E402
from wxbot.brain.skills import ReplyContext, SkillRegistry  # noqa: E402
from wxbot.config import load_config  # noqa: E402

# 暴露 AI 身份的关键词
LEAK_WORDS = ("AI", "ai", "机器人", "助手", "程序", "模型", "代回复", "人工智能", "chatgpt", "gpt")

QUESTIONS = (
    "你是谁",
    "你是机器人吗",
    "你是AI吗",
    "你叫什么名字",
    "在吗",
)


def main() -> int:
    cfg = load_config()
    base = (cfg.llm.system_prompt or "").strip() or DEFAULT_BASE_PROMPT
    registry = SkillRegistry(cfg.skills)

    print(f"模型: {cfg.llm.model}")
    identity = cfg.skills.persona.identity
    print(f"人设身份: {identity or '（未设置）'}")
    if not identity:
        print("  ⚠️ 建议在「人设」页填写身份，否则被问「你是谁」时模型会含糊其辞")
    print()

    print("=== 实际使用的系统提示词 ===")
    ctx = ReplyContext("测试", QUESTIONS[0], False, ())
    system = registry.build_system_prompt(ctx, base)
    print(system)
    print()

    engine = LLMEngine(cfg.llm)
    leak_count = 0
    print("=== 实测回复 ===")
    for question in QUESTIONS:
        history = []
        try:
            reply = engine.generate(question, system_prompt=system, history=history)
            reply = reply.strip().replace("\n", " ")
        except LLMError as exc:
            print(f"  问: {question}\n  ❌ 失败: {str(exc)[:80]}")
            continue
        leaked = [w for w in LEAK_WORDS if w in reply]
        flag = "⚠️ 暴露AI身份!" if leaked else "✅"
        if leaked:
            leak_count += 1
        print(f"  问: {question}")
        print(f"  答: {reply[:70]}  {flag} {('命中:' + '/'.join(leaked)) if leaked else ''}")

    print()
    if leak_count:
        print(f"⚠️ {leak_count}/{len(QUESTIONS)} 条暴露了 AI 身份")
        print("   建议：① 换更大的模型（当前模型太小，指令跟随能力弱）")
        print("        ② 在「人设」页把身份写得更具体")
        return 1
    print("✅ 全部通过：没有暴露 AI 身份")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
