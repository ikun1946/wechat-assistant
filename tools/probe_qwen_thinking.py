"""只问一件事：qwen3.5-9b 到底要多久才能吐出正文？

配合应用真实使用的参数（max_tokens=8192、完整人设提示词）。
只调模型接口，不发微信消息。
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


def call(system: str, question: str, timeout: float) -> None:
    body = {
        "model": "qwen/qwen3.5-9b",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": question},
        ],
        "temperature": 0.8,
        "max_tokens": 8192,
    }
    req = urllib.request.Request(
        URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read())
    except Exception as exc:  # noqa: BLE001
        print(f"  {time.time() - start:6.1f}s  ❌ {type(exc).__name__}  「{question}」")
        return
    elapsed = time.time() - start
    message = data["choices"][0]["message"]
    text = (message.get("content") or "").strip()
    usage = data.get("usage", {})
    reasoning_tokens = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
    print(
        f"  {elapsed:6.1f}s  {'✅' if text else '⚠️无正文'}  "
        f"思考 {reasoning_tokens} token / 输出 {usage.get('completion_tokens')} token  「{question}」"
    )
    if text:
        print(f"          正文: {text[:60]!r}")


def main() -> int:
    cfg = load_config()
    registry = SkillRegistry(cfg.skills)
    system = registry.build_system_prompt(
        ReplyContext("测试", "你好"), cfg.llm.system_prompt.strip() or DEFAULT_BASE_PROMPT
    )
    print(f"qwen3.5-9b，max_tokens=8192，提示词 {len(system)} 字符\n")
    for question in ("你好", "你是谁"):
        call(system, question, timeout=300.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
