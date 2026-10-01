"""确认崩溃源：重复创建 RapidOCR 引擎，还是 VisionClient 本身？

只读探针，不启动任何线程。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wxbot.wechat.vision_client import VisionClient  # noqa: E402

LOG = Path(__file__).resolve().parents[1] / "logs" / "ocr_reinit_probe.txt"
LOG.parent.mkdir(parents=True, exist_ok=True)
_f = LOG.open("w", encoding="utf-8")


def log(msg: str) -> None:
    _f.write(msg + "\n")
    _f.flush()
    print(msg)


def main() -> int:
    # 1) 反复建 RapidOCR
    try:
        from rapidocr_onnxruntime import RapidOCR

        for i in range(3):
            log(f"[RapidOCR] 第 {i + 1} 次创建 ...")
            engine = RapidOCR()
            log(f"[RapidOCR] 第 {i + 1} 次 OK")
            del engine
        log("[RapidOCR] 三次都成功 —— 崩溃源不是 RapidOCR 重建")
    except Exception as exc:
        log(f"[RapidOCR] 失败: {type(exc).__name__}: {exc}")

    # 2) 反复建 VisionClient（不启线程）
    for i in range(3):
        log(f"[VisionClient] 第 {i + 1} 次创建 ...")
        client = VisionClient()
        log(f"[VisionClient] 第 {i + 1} 次 OK，ocr={client._ocr is not None}")
        del client
    log("三轮 VisionClient 创建都完成")

    _f.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())