"""真实发送测试（会真的发出一条微信消息）。

用法：.venv\\Scripts\\python.exe tools\\check_send_live.py

默认：向「文件传输助手」发送「自动回复测试，请忽略」。
发送后会自动抓屏核对，并把截图存到 logs/send_verify.png。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2  # noqa: E402

from wxbot.wechat.capture import grab_bgr  # noqa: E402
from wxbot.wechat.vision_client import VisionClient  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TARGET = "文件传输助手"
MESSAGE = "自动回复测试，请忽略"


def esc(text: str) -> str:
    return text.encode("unicode_escape").decode("ascii")


def main() -> int:
    client = VisionClient()
    available, reason = client.is_available()
    print(f"[avail] {available} ({esc(reason)})")
    if not available:
        return 2

    print(f"[send ] target={esc(TARGET)} message={esc(MESSAGE)}")
    started = time.time()
    ok = client.send_text(TARGET, MESSAGE)
    elapsed = time.time() - started
    print(f"[send ] ok={ok} elapsed={elapsed:.2f}s")
    if client.last_send_detail:
        print(f"[detail] {esc(client.last_send_detail)}")

    window = client._window()
    if window:
        image = grab_bgr(int(window["hwnd"]))
        if image is not None:
            out = PROJECT_ROOT / "logs" / "send_verify.png"
            cv2.imwrite(str(out), image)
            print(f"[shot ] saved {out}")

    return 0 if ok else 4


if __name__ == "__main__":
    raise SystemExit(main())
