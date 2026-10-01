"""验证能否切换模型：逐个用配置好的模型真实生成一次。

用法：.venv/Scripts/python.exe tools/check_model_switch.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wxbot.brain.llm import LLMEngine, LLMError  # noqa: E402
from wxbot.brain.model_store import ModelStore  # noqa: E402
from wxbot.config import LLMConfig, load_config  # noqa: E402

SAMPLE = "在吗？用一句话说你是谁。"


def main() -> int:
    cfg = load_config()
    store = ModelStore()
    models = [e.model for e in store.entries(cfg.llm.provider)] or [cfg.llm.model]
    if not models:
        print("模型库为空")
        return 2

    print(f"厂商: {cfg.llm.provider}   地址: {cfg.llm.base_url}")
    print(f"可切换模型: {models}")
    print()

    ok_count = 0
    for model in models:
        test = LLMConfig(
            provider=cfg.llm.provider,
            base_url=cfg.llm.base_url,
            model=model,
            api_style=cfg.llm.api_style,
            api_key_env=cfg.llm.api_key_env,
            temperature=cfg.llm.temperature,
            max_tokens=cfg.llm.max_tokens,
            timeout_sec=120.0,
        )
        started = time.time()
        try:
            text = LLMEngine(test).generate(
                SAMPLE, system_prompt=cfg.llm.system_prompt, history=[]
            )
            elapsed = time.time() - started
            ok_count += 1
            preview = text.strip().replace("\n", " ")[:60]
            print(f"  ✅ {model}")
            print(f"      {elapsed:5.1f}s  {preview}")
        except LLMError as exc:
            elapsed = time.time() - started
            print(f"  ❌ {model}")
            print(f"      {elapsed:5.1f}s  {str(exc)[:110]}")

    print()
    print(f"可用 {ok_count}/{len(models)} 个")
    return 0 if ok_count else 3


if __name__ == "__main__":
    raise SystemExit(main())
