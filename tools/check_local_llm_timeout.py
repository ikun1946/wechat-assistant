"""诊断：复现程序真实请求 —— max_tokens=8192 且不关思考，看要多久。

只读探测，不发微信消息。
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wxbot.brain.pipeline import DEFAULT_BASE_PROMPT  # noqa: E402
from wxbot.brain.skills import ReplyContext, SkillRegistry  # noqa: E402
from wxbot.config import load_config  # noqa: E402

URL = "http://127.0.0.1:1234/v1/chat/completions"


def probe(model: str, system: str, user: str, max_tokens: int, timeout: float) -> None:
    body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.8,
            "max_tokens": max_tokens,
        }
    ).encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read())
        elapsed = time.time() - start
        usage = data.get("usage", {})
        message = data["choices"][0]["message"]
        text = message.get("content") or ""
        reasoning = message.get("reasoning_content") or message.get("reasoning") or ""
        finish = data["choices"][0].get("finish_reason")
        print(
            f"  max_tokens={max_tokens:<6} {elapsed:6.1f}s  "
            f"out={usage.get('completion_tokens'):<6} finish={finish!s:<10} "
            f"正文={text[:24]!r} 思考={len(reasoning)}字"
        )
    except Exception as exc:  # noqa: BLE001
        print(
            f"  max_tokens={max_tokens:<6} {time.time() - start:6.1f}s  "
            f"❌ {type(exc).__name__}  ← 程序在这里就报 timed out"
        )


def main() -> int:
    cfg = load_config()
    registry = SkillRegistry(cfg.skills)
    system = registry.build_system_prompt(
        ReplyContext("测试", "你好"),
        cfg.llm.system_prompt.strip() or DEFAULT_BASE_PROMPT,
    )
    print(f"程序配置：max_tokens={cfg.llm.max_tokens}  timeout={cfg.llm.timeout_sec}s  "
          f"thinking={cfg.llm.thinking_level}  model={cfg.llm.model}")
    print()
    for model in ("minicpm-v-4.6", "google/gemma-4-e2b"):
        print(f"[{model}]")
        for max_tokens in (2048, 8192):
            probe(model, system, "你好", max_tokens, timeout=cfg.llm.timeout_sec)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
