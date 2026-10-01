"""端到端验证：用真实模型响应检查 token 用量与思考过程是否解析正确。

不发微信消息，只调 LLM 引擎。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wxbot.brain.llm import LLMEngine  # noqa: E402
from wxbot.brain.pipeline import DEFAULT_BASE_PROMPT  # noqa: E402
from wxbot.brain.skills import ReplyContext, SkillRegistry  # noqa: E402
from wxbot.config import load_config  # noqa: E402


def main() -> int:
    cfg = load_config()
    registry = SkillRegistry(cfg.skills)
    system = registry.build_system_prompt(
        ReplyContext("测试", "你好"), cfg.llm.system_prompt.strip() or DEFAULT_BASE_PROMPT
    )

    for model in ("google/gemma-4-e2b", "minicpm-v-4.6"):
        engine_cfg = type(cfg.llm)(
            **{
                **{k: getattr(cfg.llm, k) for k in cfg.llm.__dataclass_fields__},
                "model": model,
            }
        )
        engine = LLMEngine(engine_cfg)
        try:
            result = engine.generate_detailed(
                "你好", system_prompt=system, history=[("user", "在吗"), ("assistant", "在的～")]
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[{model}] 失败：{exc}")
            continue
        print(f"[{model}]")
        print(f"  正文            : {result.text[:60]!r}")
        print(f"  prompt_tokens   : {result.prompt_tokens}")
        print(f"  completion      : {result.completion_tokens}")
        print(f"  context_length  : {result.context_length}")
        print(f"  占用比例        : {result.context_ratio:.1%}")
        print(f"  界面文案        : {result.context_display}")
        print(f"  思考字数        : {len(result.reasoning)}")
        print(f"  finish_reason   : {result.finish_reason}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
