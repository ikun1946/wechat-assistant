"""端到端验证：当前配置能不能真的生成一条回复。

走完整流水线（安全网关 → 技能 → 真实模型 → 回复审查），不发送微信。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wxbot.brain.memory import ChatMemory  # noqa: E402
from wxbot.brain.pipeline import ReplyPipeline  # noqa: E402
from wxbot.config import load_config  # noqa: E402
from wxbot.safety.gateway import SafetyGateway  # noqa: E402
from wxbot.wechat.base import IncomingMessage  # noqa: E402


def main() -> int:
    cfg = load_config()
    print(f"provider={cfg.llm.provider}  model={cfg.llm.model}")
    print(f"timeout={cfg.llm.timeout_sec}s  thinking={cfg.llm.thinking_level}")
    print(f"白名单={list(cfg.whitelist.chats)}  引擎={cfg.reply.engine}\n")

    # 临时记忆文件，不碰真实的 data/chat_memory.json
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        gateway = SafetyGateway(cfg.safety, cfg.whitelist)
        pipeline = ReplyPipeline(cfg, gateway, ChatMemory(Path(tmp) / "probe.json"))
        for question in ("你好", "你是谁"):
            start = time.perf_counter()
            result = pipeline.handle(
                IncomingMessage(chat_name=cfg.whitelist.chats[0], text=question)
            )
            elapsed = time.perf_counter() - start
            print(f"[{question}] {elapsed:.1f}s  action={result.action}")
            if result.action == "replied":
                print(f"    回复: {result.reply_text}")
                print(f"    上下文: {result.context_display}  思考: {len(result.reasoning)} 字")
            else:
                print(f"    未回复: {result.reason[:110]}")
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
