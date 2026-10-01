"""定位 Runner 启停崩溃：是不是「抓屏进行中被 stop」导致的？

用法：
    .venv/Scripts/python.exe tools\probe_runner_teardown.py          # 每轮跑 0 秒就停
    PROBE_RUNTIME=5 .venv\Scripts\python.exe tools\...py            # 每轮先跑 5 秒再停
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wxbot.config import AppConfig  # noqa: E402
from wxbot.runner import build_default_runner  # noqa: E402
from wxbot.wechat.vision_client import VisionClient  # noqa: E402

LOG = Path(__file__).resolve().parents[1] / "logs" / "runner_teardown_probe.txt"
LOG.parent.mkdir(parents=True, exist_ok=True)
_f = LOG.open("w", encoding="utf-8")


def log(msg: str) -> None:
    _f.write(msg + "\n")
    _f.flush()
    print(msg)


def main() -> int:
    run_time = float(os.environ.get("PROBE_RUNTIME", "0"))
    rounds = int(os.environ.get("PROBE_ROUNDS", "4"))
    log(f"每轮先跑 {run_time}s 再 stop，共 {rounds} 轮")

    cfg = AppConfig()
    cfg.mode = "dry_run"
    cfg.llm.model = "minicpm-v-4.6"
    cfg.whitelist.chats = ("测试",)

    shared_client = VisionClient()
    for i in range(rounds):
        log(f"[{i + 1}] 建 Runner（复用同一个 VisionClient）")
        runner = build_default_runner(cfg, client=shared_client, poll_interval=0.5)
        runner.start()
        log(f"  running={runner.running}")
        if run_time:
            time.sleep(run_time)
        log("  stop() ...")
        ok = runner.stop(timeout=8.0)
        log(f"  stopped={ok} running={runner.running}")
        del runner
    log(f"{rounds} 轮全部完成 —— 没有崩溃")
    _f.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())