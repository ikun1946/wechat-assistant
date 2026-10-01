"""验证：关闭思考（/no_think）能不能让本地模型在超时内返回正文。

对应 GUI「模型」页 → 思考等级 = 关闭。
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
        message = data["choices"][0]["message"]
        text = message.get("content") or ""
        reasoning = message.get("reasoning_content") or ""
        verdict = "✅ 有正文" if text.strip() else "❌ 只有思考、无正文"
        print(
            f"  {elapsed:6.1f}s  思考 {len(reasoning):4d} 字  {verdict}  "
            f"{text[:30]!r}"
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  {time.time() - start:6.1f}s  ❌ {type(exc).__name__}  ← 顶穿了超时")


def main() -> int:
    cfg = load_config()
    model = cfg.llm.model
    registry = SkillRegistry(cfg.skills)
    base = cfg.llm.system_prompt.strip() or DEFAULT_BASE_PROMPT
    print(f"当前模型 {model}，配置超时 {cfg.llm.timeout_sec}s，thinking={cfg.llm.thinking_level}\n")

    normal = registry.build_system_prompt(ReplyContext("测试", "你好"), base)
    # 思考等级设为「关闭」时，程序会给 Qwen3 系模型追加 /no_think
    no_think = normal + " /no_think"

    print("[思考开启 · max_tokens 8192 · 超时 30s]  ← 你日志里的情况")
    probe(model, normal, "你好", 8192, 30.0)

    print("\n[思考关闭(/no_think) · max_tokens 2048 · 超时 30s]  ← 建议的设置")
    probe(model, no_think, "你好", 2048, 30.0)

    print("\n[思考关闭(/no_think) · max_tokens 2048 · 超时 90s]")
    probe(model, no_think, "你好", 2048, 90.0)

    print("\n[思考关闭 · 带真实人设问「你是谁」]")
    probe(model, no_think, "你是谁", 2048, 90.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
