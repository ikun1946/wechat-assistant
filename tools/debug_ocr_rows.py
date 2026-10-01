"""诊断：会话列表 OCR 原始输出（看某一行是否被漏识别）。

用法：.venv/Scripts/python.exe tools/debug_ocr_rows.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2  # noqa: E402

from wxbot.wechat.capture import find_main_window, grab_bgr  # noqa: E402
from wxbot.wechat.vision_client import (  # noqa: E402
    ROW_GROUP_GAP,
    SESSION_LIST_WIDTH_RATIO,
    VisionClient,
    _find_red_badges,
)


def main() -> int:
    client = VisionClient()
    window = find_main_window()
    if not window:
        print("没有找到微信窗口")
        return 2
    hwnd = int(window["hwnd"])
    image = grab_bgr(hwnd)
    height, width = image.shape[:2]
    panel_w = int(width * SESSION_LIST_WIDTH_RATIO)
    print(f"窗口帧: {width}x{height}  面板宽: {panel_w}")

    panel = image[:, :panel_w]
    result, _ = client._ocr(panel)
    print(f"面板 OCR 原始条目: {len(result or [])}")
    items = []
    for box, text, score in (result or []):
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        items.append((sum(ys) / len(ys), min(xs), sum(xs) / len(xs), str(text), float(score)))
    items.sort()
    for y, x0, xc, text, score in items:
        print(f"    y={y:6.1f}  x0={x0:5.1f} xc={xc:5.1f}  {text!r}  ({score:.2f})")

    print()
    print(f"红点: {_find_red_badges(panel)}")
    print()
    print("=== 标题区域检测 ===")
    header_region = image[int(height * 0.05) : int(height * 0.13), panel_w : panel_w + 320]
    print(f"  区域: y={int(height*0.05)}~{int(height*0.13)}, x={panel_w}~{panel_w+320}")
    cv2.imwrite("logs/header_region.png", header_region)
    hres, _ = client._ocr(header_region) if header_region.size else (None, None)
    print(f"  OCR 结果: {[str(i[1]) for i in (hres or [])]}")
    print(f"  _read_header() = {client._read_header(image)!r}")

    print()
    print("=== 聊天区内容检测 ===")
    body_region = image[int(height * 0.14) : int(height * 0.72), panel_w:]
    cv2.imwrite("logs/body_region.png", body_region)
    bres, _ = client._ocr(body_region) if body_region.size else (None, None)
    print(f"  OCR 条数: {len(bres or [])}")
    print(f"  read_current_chat_text() = {client.read_current_chat_text(image)[:120]!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
