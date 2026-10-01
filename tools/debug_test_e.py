"""直接调试 test_E 的失败原因。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from wxbot.textutil import normalize_name  # noqa: E402
from wxbot.wechat.vision_client import SessionRow, VisionClient  # noqa: E402

client = VisionClient()
client._ocr = None
client.read_sessions = lambda image=None: [  # type: ignore[assignment]
    SessionRow(name="老王！", preview="你不是他们的父亲吗", unread=False, y_center=90)
]
client._window = lambda: None  # type: ignore[assignment]
client._grab = lambda: np.zeros((565, 811, 3), dtype=np.uint8)  # type: ignore[assignment]

client.set_current_chat_state("老王！", "旧内容")
print("after set(1):", "incoming_changed=", client._incoming_changed,
      "| current_chat=", repr(client._current_chat), "| body=", repr(client._current_body))

first = client.poll_new_messages()
print("poll1 ->", first)
print("  state: baseline=", client._baseline_ready, "incoming_changed=", client._incoming_changed,
      "current_chat=", repr(client._current_chat))
print("  _last_preview=", client._last_preview)
print("  _last_header_check=", client._last_header_check)

client.set_current_chat_state("老王！", "旧内容\n你不是他们的父亲吗", changed=True)
print()
print("after set(2): incoming_changed=", client._incoming_changed,
      "| body=", repr(client._current_body))

second = client.poll_new_messages()
print("poll2 ->", second)
print("  is_current would be:", normalize_name("老王！") == normalize_name(client._current_chat or ""))
print("  incoming_changed now:", client._incoming_changed)
