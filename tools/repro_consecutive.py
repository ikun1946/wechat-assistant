"""复现「连续两条消息，第二条不回复」：逐轮驱动真实轮询，打印每轮判定。

用法：.venv/Scripts/python.exe tools/repro_consecutive.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wxbot.wechat.vision_client import VisionClient  # noqa: E402


def main() -> int:
    client = VisionClient()
    print("请在接下来的 40 秒内，让「老王!」连续发来 2~3 条消息。")
    print("（每轮间隔 1 秒，逐轮打印程序看到了什么）")
    print()

    deadline = time.time() + 40
    round_no = 0
    last_state = None
    while time.time() < deadline:
        round_no += 1
        messages = client.poll_new_messages()
        # 用「当前会话内容」做一个可视化状态指纹
        state = (client._current_chat, client._current_body[-60:])
        if state != last_state:
            print(f"[{round_no:3d}] 状态变化 →")
            print(f"      当前会话: {client._current_chat!r}")
            print(f"      内容尾部: {client._current_body[-70:]!r}")
            if messages:
                for m in messages:
                    print(f"      ★ 识别到消息: {m.chat_name} = {m.text[-60:]!r}")
            last_state = state
        time.sleep(1.0)

    print()
    print(f"共 {round_no} 轮")
    print(f"识别到的会话名: {client._last_known_names}")
    print(f"最近上报时间: {list(client._last_reported.items())}")
    print()
    print("如果第二条消息没被识别，看上面「内容尾部」是否随第二条消息变化了。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
