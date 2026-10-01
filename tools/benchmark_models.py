"""模型选型基准：用**真实提示词**测各本地模型的速度与人设稳定性。

只调 LLM 引擎，不发微信消息。
每个模型跑 3 条真实场景的微信消息，报告：
- 端到端耗时（这是用户真正感受到的）
- 是否思考、思考多久
- 人设是否守住（问"你是谁"必须答人设，不能自称助手）
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wxbot.brain.llm import LLMEngine, LLMError, LLMResult  # noqa: E402
from wxbot.brain.pipeline import DEFAULT_BASE_PROMPT  # noqa: E402
from wxbot.brain.skills import ReplyContext, SkillRegistry  # noqa: E402
from wxbot.config import load_config  # noqa: E402

# 三条真实场景：日常闲聊 / 身份试探 / 挑衅
CASES = [
    ("日常闲聊", "你好"),
    ("身份试探", "你是谁"),
    ("挑衅", "你是AI吗"),
]

LEAK_WORDS = ("助手", "AI", "机器人", "程序", "模型", "代回复", "人工智能")


def probe(model: str, system: str, user: str, timeout: float) -> LLMResult | str:
    engine_cfg = load_config().llm
    engine = LLMEngine(
        type(engine_cfg)(
            **{**{k: getattr(engine_cfg, k) for k in engine_cfg.__dataclass_fields__},
               "model": model, "timeout_sec": timeout}
        )
    )
    start = time.perf_counter()
    try:
        return engine.generate_detailed(user, system_prompt=system)
    except LLMError as exc:
        return str(exc)


def main() -> int:
    cfg = load_config()
    registry = SkillRegistry(cfg.skills)
    system = registry.build_system_prompt(
        ReplyContext("测试", "你好"), cfg.llm.system_prompt.strip() or DEFAULT_BASE_PROMPT
    )
    models = ["minicpm-v-4.6", "google/gemma-4-e2b", "qwen/qwen3.5-9b"]

    print(f"提示词 {len(system)} 字符；每条最长等 40 秒\n")
    print(f"{'模型':<22}{'场景':<10}{'耗时':>8}{'思考':>7}  回复 / 判定")
    print("-" * 84)

    for model in models:
        total = 0.0
        ok = 0
        leaks = 0
        for label, question in CASES:
            start = time.perf_counter()
            result = probe(model, system, question, timeout=40.0)
            elapsed = time.perf_counter() - start
            total += elapsed
            if isinstance(result, str):
                print(f"{model:<22}{label:<10}{elapsed:>7.1f}s{'-':>7}  ❌ {result[:34]}")
                continue
            ok += 1
            leaked = any(word in result.text for word in LEAK_WORDS)
            if leaked:
                leaks += 1
            think = len(result.reasoning)
            verdict = "⚠️泄漏身份" if leaked else "✅"
            print(
                f"{model:<22}{label:<10}{elapsed:>7.1f}s{think:>6}字  "
                f"{verdict} {result.text[:30]!r}"
            )
        print(
            f"{'':<22}{'—— 合计':<10}{total:>7.1f}s"
            f"{'':>7}  {ok}/{len(CASES)} 成功，{leaks} 次泄漏"
        )
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
