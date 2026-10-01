"""调试：为什么同一条消息会被上报两次。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from wxbot.wechat.vision_client import SessionRow, VisionClient  # noqa: E402


def fake_ocr_factory(header: str, input_text: str, chat_text: str = ""):
    def _ocr(image):
        height, _w = image.shape[:2]
        if height <= 60:
            text = header
        elif height > 200:
            text = chat_text
        else:
            text = input_text
        box = [[10, 5], [90, 5], [90, height - 5], [10, height - 5]]
        return ([[box, text, 0.99]] if text else []), 0.01

    return _ocr


def main() -> int:
    client = VisionClient(ocr=fake_ocr_factory("张三", "在吗"))
    client._window = lambda: {"hwnd": 1}  # type: ignore[assignment]
    frame = np.full((400, 800, 3), 245, dtype=np.uint8)
    frame[192:208, 190:206] = (60, 60, 230)
    client._grab = lambda: frame  # type: ignore[assignment]
    client.read_sessions = lambda image=None: [  # type: ignore[assignment]
        SessionRow(name="张三", preview="在吗", unread=True, y_center=200)
    ]

    for i in range(1, 4):
        msgs = client.poll_new_messages()
        print(f"轮{i}: {len(msgs)} 条")
        for m in msgs:
            print(f"     -> {m.chat_name}: {m.text!r}")
        print(f"     _claimed_text     = {client._claimed_text}")
        print(f"     _last_replied_text= {client._last_replied_text}")
        print(f"     _last_reported    = {client._last_reported}")
        print(f"     _incoming_changed = {client._incoming_changed}")
        print(f"     _current_chat     = {client._current_chat!r}")
        print(f"     _baseline_ready   = {client._baseline_ready}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
