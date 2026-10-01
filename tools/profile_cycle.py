"""性能剖析：测量一轮完整轮询的时间分布。

回答三个问题：
1. 抓屏、OCR、气泡识别、列表识别各占多少？
2. 一轮 tick 到底多久？能不能塞进 3 秒轮询间隔？
3. 有没有重复劳动（比如同一帧被 OCR 多次）？

只读，不发消息、不改任何状态。
"""

from __future__ import annotations

import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wxbot.wechat.capture import find_main_window, grab_bgr  # noqa: E402
from wxbot.wechat.vision_client import (  # noqa: E402
    SESSION_LIST_WIDTH_RATIO,
    VisionClient,
)


def timed(label: str, store: dict, fn):
    start = time.perf_counter()
    result = fn()
    store[label] = store.get(label, 0.0) + (time.perf_counter() - start)
    return result


def main() -> int:
    client = VisionClient()
    window = find_main_window()
    if not window:
        print("没有找到微信窗口")
        return 1

    totals: dict[str, float] = defaultdict(float)
    rounds = 5

    for round_index in range(rounds):
        frame = timed("1_抓屏 WGC", totals, lambda: grab_bgr(int(window["hwnd"])))
        if frame is None:
            print("抓屏失败")
            return 1
        height, width = frame.shape[:2]
        panel_width = int(width * SESSION_LIST_WIDTH_RATIO)

        timed("2_读标题", totals, lambda: client._read_header(frame))
        timed("3_读聊天气泡", totals, lambda: client.read_chat_bubbles(frame))
        timed("4_读会话列表", totals, lambda: client.read_sessions(frame))
        timed("5_整条 poll", totals, lambda: client.poll_new_messages())
        print(f"  第 {round_index + 1} 轮完成")

    print(f"\n窗口 {width}x{height}，共 {rounds} 轮，取平均：\n")
    print(f"{'环节':<16}{'平均耗时':>12}")
    print("-" * 28)
    total = 0.0
    for label in sorted(totals):
        avg = totals[label] / rounds
        if label != "5_整条 poll":
            total += avg
        print(f"{label:<16}{avg * 1000:>9.0f} ms")

    tick = totals["5_整条 poll"] / rounds
    print("-" * 28)
    print(f"{'分项合计':<16}{total * 1000:>9.0f} ms")
    print(f"{'整条 poll':<16}{tick * 1000:>9.0f} ms")
    print()
    print(f"轮询间隔 3000 ms → 占用 {tick / 3.0:.0%}，富余 {3000 - tick * 1000:.0f} ms")
    if totals.get("5_整条 poll", 0) / rounds > 3.0:
        print("⚠ 一轮已超过轮询间隔 —— 实际上是在连续满负荷跑，没有停顿")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
