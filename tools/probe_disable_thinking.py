"""找出真正能关掉 qwen3.5 思考的请求参数（精简版：只测最可能的两种）。

背景：`/no_think` 是 Qwen3 的老办法，对 qwen3.5 无效 —— 实测加了它，
75 秒仍然只有 reasoning_content、没有正文。这里验证 `chat_template_kwargs`。
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


def probe(label: str, model: str, system: str, extra: dict, timeout: float) -> bool:
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": "你好"},
        ],
        "temperature": 0.8,
        "max_tokens": 2048,
    }
    body.update(extra)
    req = urllib.request.Request(
        URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read())
        elapsed = time.time() - start
        message = data["choices"][0]["message"]
        text = message.get("content") or ""
        reasoning = message.get("reasoning_content") or ""
        print(
            f"  {elapsed:6.1f}s  {'✅' if text.strip() else '⚠️ '} "
            f"思考 {len(reasoning):4d} 字  {label}"
        )
        if text.strip():
            print(f"            正文: {text[:60]!r}")
            return True
    except Exception as exc:  # noqa: BLE001
        print(f"  {time.time() - start:6.1f}s  ❌ {type(exc).__name__}  {label}")
    return False


def main() -> int:
    cfg = load_config()
    model = cfg.llm.model
    registry = SkillRegistry(cfg.skills)
    system = registry.build_system_prompt(
        ReplyContext("测试", "你好"), cfg.llm.system_prompt.strip() or DEFAULT_BASE_PROMPT
    )
    print(f"模型 {model}\n")

    if probe(
        "chat_template_kwargs.enable_thinking=false",
        model,
        system,
        {"chat_template_kwargs": {"enable_thinking": False}},
        timeout=45.0,
    ):
        print("\n结论：本地服务关思考要用 chat_template_kwargs（程序 v2.5.1 已接上）")
        print("把「模型」页 → 思考等级 设为「关闭」即可。")
        return 0

    print("\n结论：连 chat_template_kwargs 也关不掉 → 这个模型版本不支持关思考。")
    print("出路：① 换一个非思考型模型（minicpm-v-4.6 / gemma-4-e2b）；")
    print("      ② 或把「请求超时」调到 180 秒以上。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
