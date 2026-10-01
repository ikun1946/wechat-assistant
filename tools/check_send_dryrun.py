"""发送链路「不发送」验证：只验证坐标换算与标题校验，绝不输入/发送任何内容。

用法：
    .venv\\Scripts\\python.exe tools\\check_send_dryrun.py            # 默认第 2 行开始试
    .venv\\Scripts\\python.exe tools\\check_send_dryrun.py --index 3  # 指定第 3 行（从 0 开始）

做的事情：
1) 把微信窗口置前；
2) 按识别到的会话行坐标点击该行（只是切换显示的聊天，不会发消息）；
3) 重新抓屏（多帧，避开旧画面），OCR 顶部标题，确认标题与目标一致。

⚠ 不要用中文命令行参数：PowerShell 传给子进程的中文可能被破坏，导致目标匹配失败。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wxbot.textutil import names_match  # noqa: E402
from wxbot.wechat import input as input_ctl  # noqa: E402
from wxbot.wechat.capture import ensure_window_visible, grab_bgr  # noqa: E402
from wxbot.wechat.vision_client import SESSION_LIST_WIDTH_RATIO, VisionClient  # noqa: E402


def esc(text: str) -> str:
    return text.encode("unicode_escape").decode("ascii")


def main() -> int:
    index = 2
    argv = sys.argv[1:]
    if "--index" in argv:
        index = int(argv[argv.index("--index") + 1])

    client = VisionClient()
    available, reason = client.is_available()
    print(f"[avail] {available} ({esc(reason)})")
    if not available:
        return 2

    window = client._window()
    hwnd = int(window["hwnd"])
    if not ensure_window_visible(hwnd):
        print("[win  ] window not visible")
        return 3
    if not input_ctl.set_foreground(hwnd):
        print("[win  ] cannot bring to foreground")
        return 4

    image = grab_bgr(hwnd)
    rows = client.read_sessions(image)
    print(f"[rows ] {len(rows)} rows:")
    for i, row in enumerate(rows):
        print(f"        #{i} y={row.y_center:4d} name={esc(row.name)}")
    if index >= len(rows):
        print(f"[err  ] index {index} out of range")
        return 5
    target = rows[index]

    offset_x, offset_y = client._screen_offsets(hwnd, image)
    height, width = image.shape[:2]
    panel_width = int(width * SESSION_LIST_WIDTH_RATIO)
    click_x = offset_x + int(panel_width * 0.78)
    click_y = offset_y + target.y_center
    print(f"[coord] frame {width}x{height} offset ({offset_x},{offset_y})")
    print(f"[coord] row y={target.y_center} -> screen ({click_x},{click_y})")

    print("[click] clicking the session row only (no message is sent)")
    input_ctl.click(click_x, click_y)
    time.sleep(0.6)

    header = ""
    for attempt in range(3):
        frame = grab_bgr(hwnd)
        header = client._read_header(frame)
        print(f"[check] attempt {attempt+1}: header = {esc(header)}")
        if header and names_match(header, target.name):
            print("[result] OK: click mapping and header check are reliable")
            return 0
        time.sleep(0.6)

    print("[result] FAIL: header does not match target; abort (nothing sent)")
    return 6


if __name__ == "__main__":
    raise SystemExit(main())

