"""最终验收：真实发起一次生成，确认**实际请求用的模型**就是配置里那个。

不看配置对象、不看界面，直接抓 LLM 引擎真实发出的请求体。
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wxbot.brain.llm import LLMEngine  # noqa: E402
from wxbot.brain.pipeline import DEFAULT_BASE_PROMPT  # noqa: E402
from wxbot.brain.skills import ReplyContext, SkillRegistry  # noqa: E402
from wxbot.config import load_config  # noqa: E402
from wxbot.runner import build_default_runner  # noqa: E402
from wxbot.wechat.vision_client import VisionClient  # noqa: E402

# 拦截真实的 HTTP 请求体
_real = urllib.request.urlopen
SEEN: list[dict] = []


def _spy(req, *a, **kw):
    body = getattr(req, "data", None)
    if body:
        try:
            SEEN.append(json.loads(body))
        except Exception:  # noqa: BLE001
            pass
    return _real(req, *a, **kw)


urllib.request.urlopen = _spy


def main() -> int:
    cfg = load_config()
    print(f"磁盘配置里的模型: {cfg.llm.model}")
    print(f"厂商: {cfg.llm.provider}   超时: {cfg.llm.timeout_sec}s\n")

    # 1) 走 Runner → Pipeline → LLMEngine 的真实链路
    runner = build_default_runner(cfg, client=VisionClient(), poll_interval=0.5)
    print(f"Runner 里的模型: {runner._config.llm.model}")
    print(f"Pipeline 里的模型: {runner._pipeline._config.llm.model}")
    print(f"网关用的安全配置: {type(runner._gateway._safety).__name__}"
          f"（白名单 {list(runner._gateway._whitelist.chats)}）")

    # 2) 真实生成一次
    registry = SkillRegistry(cfg.skills)
    system = registry.build_system_prompt(
        ReplyContext("测试", "你好"), cfg.llm.system_prompt.strip() or DEFAULT_BASE_PROMPT
    )
    engine = LLMEngine(cfg.llm)
    start = time.perf_counter()
    try:
        result = engine.generate_detailed("你好", system_prompt=system)
    except Exception as exc:  # noqa: BLE001
        print(f"  生成失败: {exc}")
        return 1
    elapsed = time.perf_counter() - start

    print(f"\n真实生成: {elapsed:.1f}s")
    print(f"  回复: {result.text[:50]}")
    print(f"  上下文: {result.context_display}   思考: {len(result.reasoning)} 字")

    # 3) 核对真实发出去的请求体
    print(f"\n实际发出的请求数: {len(SEEN)}")
    if not SEEN:
        print("  ❌ 没有抓到任何请求 —— 无法证明")
        return 1
    sent_model = SEEN[-1].get("model")
    print(f"  请求体里的 model = {sent_model!r}")
    ok = sent_model == cfg.llm.model
    print(f"\n{'✅' if ok else '❌'} 实际调用的模型 == 配置里的模型"
          f"（{cfg.llm.model}）")
    if not ok:
        print(f"  期望 {cfg.llm.model!r}，实际 {sent_model!r}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())