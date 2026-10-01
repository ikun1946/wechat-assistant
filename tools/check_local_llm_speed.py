"""诊断：本地模型（LM Studio）实际响应有多慢 —— 用真实长度的提示词。

只读探测，不发送任何微信消息。
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wxbot.brain.pipeline import DEFAULT_BASE_PROMPT  # noqa: E402
from wxbot.brain.skills import MANDATORY_RULES, ReplyContext, SkillRegistry  # noqa: E402
from wxbot.config import load_config  # noqa: E402

URL = "http://127.0.0.1:1234/v1/chat/completions"


def probe(model: str, system: str, user: str, timeout: float = 120.0) -> None:
    body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": 64,
        }
    ).encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read())
        elapsed = time.time() - start
        usage = data.get("usage", {})
        text = data["choices"][0]["message"].get("content", "")
        print(
            f"  {model:24s} {elapsed:6.1f}s  "
            f"in={usage.get('prompt_tokens')} out={usage.get('completion_tokens')}  "
            f"{text[:30]!r}"
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  {model:24s} {time.time() - start:6.1f}s  失败 {type(exc).__name__}: {str(exc)[:60]}")


def main() -> int:
    cfg = load_config()
    registry = SkillRegistry(cfg.skills)
    system = registry.build_system_prompt(
        ReplyContext("测试", "你好"),
        cfg.llm.system_prompt.strip() or DEFAULT_BASE_PROMPT,
    )
    print(f"系统提示词 {len(system)} 字符；配置超时 {cfg.llm.timeout_sec} 秒")
    print(f"上下文 {cfg.llm.context_length}，最大输出 {cfg.llm.max_tokens}")
    print()

    short = "你好"
    long_user = "（这是若干历史消息的占位。）" * 40 + "\n你好"

    for label, payload in (("短提示", short), ("长提示(模拟带记忆)", long_user)):
        print(f"[{label}]")
        for model in ("minicpm-v-4.6", "google/gemma-4-e2b"):
            probe(model, system, payload)
        print()
    print(f"（硬性规则长度 {len(MANDATORY_RULES)} 字符）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
