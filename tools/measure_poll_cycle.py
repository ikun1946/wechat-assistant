"""测量真实轮询耗时（定位"回了一会儿就卡住"的节奏问题）。

用法：.venv/Scripts/python.exe tools/measure_poll_cycle.py [轮数]
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wxbot.wechat.capture import find_main_window, grab_bgr  # noqa: E402
from wxbot.wechat.vision_client import VisionClient  # noqa: E402


def main() -> int:
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    client = VisionClient()

    window = find_main_window()
    if not window:
        print("没有找到微信窗口")
        return 2
    hwnd = int(window["hwnd"])

    image = grab_bgr(hwnd)
    if image is not None:
        print(f"窗口帧: {image.shape[1]}x{image.shape[0]}")

    print()
    print("--- 分步耗时 ---")
    t0 = time.time()
    image = grab_bgr(hwnd)
    t_capture = time.time() - t0

    t0 = time.time()
    rows = client.read_sessions(image)
    t_sessions = time.time() - t0

    t0 = time.time()
    header = client._read_header(image)
    t_header = time.time() - t0

    t0 = time.time()
    bubbles = client.read_chat_bubbles(image)
    t_bubbles = time.time() - t0

    print(f"  抓屏            {t_capture:5.2f}s")
    print(f"  读会话列表      {t_sessions:5.2f}s  -> {len(rows)} 行")
    print(f"  读标题          {t_header:5.2f}s  -> {header!r}")
    print(f"  读聊天气泡      {t_bubbles:5.2f}s  -> {len(bubbles)} 条")
    single = t_capture + t_sessions + t_header + t_bubbles
    print(f"  单轮合计        {single:5.2f}s")

    print()
    print(f"--- 连续 {rounds} 轮真实轮询（含间隔 3s）---")
    client2 = VisionClient()
    for i in range(rounds):
        t0 = time.time()
        messages = client2.poll_new_messages()
        dt = time.time() - t0
        print(
            f"  轮 {i+1}: 本轮耗时 {dt:5.2f}s  识别 {len(messages)} 条"
            f"  当前会话={client2._current_chat!r}  会话行数={len(rows)}"
        )
        time.sleep(3.0)

    print()
    print(f"注意：单轮 {single:.2f}s + 间隔 3s = 实际每 {single + 3:.2f}s 才轮询一次")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
