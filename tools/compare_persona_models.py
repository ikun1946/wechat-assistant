"""对比不同模型的人设遵循能力（哪个模型不容易自曝 AI 身份）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wxbot.brain.llm import LLMEngine  # noqa: E402
from wxbot.brain.pipeline import DEFAULT_BASE_PROMPT  # noqa: E402
from wxbot.brain.skills import ReplyContext, SkillRegistry  # noqa: E402
from wxbot.config import LLMConfig, load_config  # noqa: E402

LEAK = ("AI", "ai", "机器人", "助手", "程序", "模型", "代回复")


def main() -> int:
    cfg = load_config()
    registry = SkillRegistry(cfg.skills)
    ctx = ReplyContext("t", "你是谁", False, ())
    base = cfg.llm.system_prompt.strip() or DEFAULT_BASE_PROMPT
    system = registry.build_system_prompt(ctx, base)

    for model in ("minicpm-v-4.6", "google/gemma-4-e2b"):
        conf = LLMConfig(
            provider=cfg.llm.provider,
            base_url=cfg.llm.base_url,
            model=model,
            api_style=cfg.llm.api_style,
            api_key_env="",
            temperature=cfg.llm.temperature,
            max_tokens=cfg.llm.max_tokens,
            timeout_sec=90.0,
        )
        print(f"===== {model} =====")
        try:
            engine = LLMEngine(conf)
            for question in ("你是谁", "你是AI吗", "你叫什么名字"):
                reply = engine.generate(question, system_prompt=system, history=[]).strip()
                hits = [w for w in LEAK if w in reply]
                mark = "LEAK:" + "/".join(hits) if hits else "OK"
                print(f"  {question} -> {reply[:52]}  [{mark}]")
        except Exception as exc:  # noqa: BLE001
            print(f"  ERR {str(exc)[:90]}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
