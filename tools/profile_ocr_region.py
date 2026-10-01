"""验证假设：RapidOCR 在"极扁"的裁剪区上耗时暴涨。

标题栏裁剪区是 320x45（长宽比约 7:1）。如果 RapidOCR 为了满足
`limit_side_len` 把短边拉到 736，这块 320x45 会被放大约 16 倍，
白白推理一大片空白 —— 猜测如此，实测验证，并给出修法对比。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wxbot.wechat.capture import find_main_window, grab_bgr  # noqa: E402
from wxbot.wechat.vision_client import SESSION_LIST_WIDTH_RATIO, VisionClient  # noqa: E402


def bench(label: str, region: np.ndarray, client: VisionClient, rounds: int = 5) -> float:
    times = []
    for _ in range(rounds):
        start = time.perf_counter()
        client._ocr(region)
        times.append(time.perf_counter() - start)
    avg = sum(times) / len(times)
    print(f"  {label:<38} {region.shape[1]:>4}x{region.shape[0]:<4}  {avg * 1000:7.0f} ms")
    return avg


def main() -> int:
    client = VisionClient()
    window = find_main_window()
    if not window:
        print("没有找到微信窗口")
        return 1
    frame = grab_bgr(int(window["hwnd"]))
    height, width = frame.shape[:2]
    panel_width = int(width * SESSION_LIST_WIDTH_RATIO)
    print(f"窗口 {width}x{height}，会话列表宽 {panel_width}\n")

    header = frame[int(height * 0.05) : int(height * 0.13), panel_width : panel_width + 320]
    chat = frame[int(height * 0.14) : int(height * 0.72), panel_width:]
    sessions = frame[: int(height * 0.95), :panel_width]

    print("现状：")
    base = bench("标题栏（320x45，扁长）", header, client)
    bench("聊天气泡区", chat, client)
    bench("会话列表区", sessions, client)

    print("\n方案 A：把标题区上下补白成正方形比例")
    padded = np.full((320, 320, 3), 30, dtype=np.uint8)
    padded[: header.shape[0], : header.shape[1]] = header
    a = bench("标题栏 + 补白成 320x320", padded, client)

    print("\n方案 B：横向拉伸标题区（让长宽比接近 1:1）")
    wide = np.repeat(header, 4, axis=0)  # 45 -> 180
    b = bench("标题区纵向拉伸 4 倍", wide, client)

    print("\n方案 C：只裁标题文字那一小条（更矮）")
    slim = frame[
        int(height * 0.05) : int(height * 0.10), panel_width : panel_width + 200
    ]
    c = bench("标题区缩小到 200x28", slim, client)

    print(f"\n结论：现状 {base * 1000:.0f} ms")
    print(f"  A 补白正方形      {a * 1000:.0f} ms  （提速 {base / a:.1f}×）")
    print(f"  B 纵向拉伸        {b * 1000:.0f} ms  （提速 {base / b:.1f}×）")
    print(f"  C 缩小裁剪        {c * 1000:.0f} ms  （提速 {base / c:.1f}×）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
