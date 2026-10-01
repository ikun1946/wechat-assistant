"""未读检测调试：抓一次微信窗口，输出会话面板与红点检测的中间结果。

用法：.venv/Scripts/python.exe tools/debug_session_panel.py
产出（logs/ 下）：
  panel.png        裁剪出的会话列表面板原图
  panel_red.png    红点检测用的二值掩膜（白色=判定为红色的像素）

只读：不点击、不输入、不发送。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from wxbot.wechat.vision_client import (  # noqa: E402
    SESSION_LIST_WIDTH_RATIO,
    SIDEBAR_ICON_WIDTH,
    VisionClient,
    _find_red_badges,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = PROJECT_ROOT / "logs"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    client = VisionClient()

    available, reason = client.is_available()
    print(f"[可用性] {'可读' if available else '不可读'}：{reason}")
    if not available:
        return 2

    image = client.capture()
    if image is None:
        print("[抓屏] 失败")
        return 3
    height, width = image.shape[:2]
    panel_width = int(width * SESSION_LIST_WIDTH_RATIO)
    print(f"[抓屏] 窗口 {width}x{height}；会话面板裁剪宽度 = {panel_width}px")

    cv2.imwrite(str(OUT_DIR / "panel_full.png"), image)
    panel = image[:, :panel_width]
    cv2.imwrite(str(OUT_DIR / "panel.png"), panel)

    # 红点检测（与 vision_client 内部同一套逻辑）
    badges = _find_red_badges(panel)
    print(f"[红点] 判定为未读红点的：{len(badges)} 个（已排除左侧图标栏 x<{SIDEBAR_ICON_WIDTH} 的红点）")
    for x, y, w, h in sorted(badges, key=lambda b: b[1]):
        print(f"    x={x:4d} y={y:4d} {w}x{h}")

    # 也给一张掩膜图便于人工核对
    hsv = cv2.cvtColor(panel, cv2.COLOR_BGR2HSV)
    mask = cv2.bitwise_or(
        cv2.inRange(hsv, (0, 90, 90), (10, 255, 255)),
        cv2.inRange(hsv, (170, 90, 90), (180, 255, 255)),
    )
    cv2.imwrite(str(OUT_DIR / "panel_red.png"), mask)
    print(f"[红点] 全面板红色像素 {int(cv2.countNonZero(mask))} 个（含被排除的）")

    rows = client.read_sessions(image)
    print(f"[会话行] 识别到 {len(rows)} 行：")
    for row in rows:
        print(f"    {'🔴未读' if row.unread else '    '} y={row.y_center:4d}  {row.name}  |  {row.preview[:30]}")

    print()
    print(f"已保存中间结果到 {OUT_DIR}：panel.png / panel_red.png / panel_full.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
