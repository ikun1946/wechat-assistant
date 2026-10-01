"""直接观察 test_N 场景的运行状态。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from wxbot.wechat.vision_client import (  # noqa: E402
    ChatBubble,
    SessionRow,
    VisionClient,
)

client = VisionClient()
client._ocr = None
client.read_sessions = lambda image=None: [  # type: ignore[assignment]
    SessionRow(name="老王！", preview="摘要", unread=False, y_center=90)
]
client._window = lambda: None  # type: ignore[assignment]
client._grab = lambda: np.zeros((565, 811, 3), dtype=np.uint8)  # type: ignore[assignment]
client._read_header = lambda image: ""  # type: ignore[assignment]

bubbles = [ChatBubble("对方: 旧消息", "them", 60, 10)]
client.read_chat_bubbles = lambda image=None: list(bubbles)  # type: ignore[assignment]
client._current_chat = "老王！"
client._last_header_check = 0.0

print("poll1 ->", client.poll_new_messages())
print("  _current_chat=", repr(client._current_chat))
print("  _seen_incoming=", client._seen_incoming)
print("  _baseline_ready=", client._baseline_ready)
print("  _last_header_check=", round(client._last_header_check))

bubbles.append(ChatBubble("对方: 新消息", "them", 60, 40))
import time

client._last_header_check = 0.0
print()
print("poll2 ->", client.poll_new_messages())
print("  _current_chat=", repr(client._current_chat))
print("  _incoming_changed=", client._incoming_changed)
print("  _current_body=", repr(client._current_body))
print("  _seen_incoming=", client._seen_incoming)
print("  time check: now - last_header_check =", round(time.time() - client._last_header_check, 2))
