"""气泡左右方向识别测试（判断"谁发的"）——不依赖真实微信窗口。

造一张聊天区图：对方消息靠左、自己的靠右，验证 sender 判定。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from wxbot.wechat.vision_client import (  # noqa: E402
    SESSION_LIST_WIDTH_RATIO,
    ChatBubble,
    VisionClient,
)

FRAME_W = 882
FRAME_H = 641
PANEL_W = int(FRAME_W * SESSION_LIST_WIDTH_RATIO)  # 264
CHAT_W = FRAME_W - PANEL_W
MIDDLE = CHAT_W / 2


def bubble_client(entries: list[tuple[str, float, str]]):
    """entries: [(text, center_x, sender)] → 假 OCR 返回带坐标的框。"""
    client = VisionClient(ocr=lambda image: ([], None))
    client._ocr = lambda image: (
        [
            (
                [
                    [cx - 30, 10],
                    [cx + 30, 10],
                    [cx + 30, 26],
                    [cx - 30, 26],
                ],
                text,
                0.99,
            )
            for text, cx, _sender in entries
        ],
        0.01,
    )
    return client


class BubbleDirectionTests(unittest.TestCase):
    def make_image(self):
        return np.full((FRAME_H, FRAME_W, 3), 245, dtype=np.uint8)

    def test_left_is_them_right_is_me(self):
        client = bubble_client(
            [
                ("你是谁", 60, "them"),
                ("我是张三", CHAT_W - 80, "me"),
                ("那不对", 70, "them"),
            ]
        )
        bubbles = client.read_chat_bubbles(self.make_image())
        self.assertEqual(len(bubbles), 3)
        self.assertEqual([b.sender for b in bubbles], ["them", "me", "them"])
        self.assertEqual(bubbles[1].text, "我是张三")

    def test_threshold_is_relative_to_width(self):
        """阈值必须按比例算，窗口变小也要成立。"""
        client = bubble_client([("左边", 40, "them"), ("右边", CHAT_W - 30, "me")])
        bubbles = client.read_chat_bubbles(self.make_image())
        self.assertEqual([b.sender for b in bubbles], ["them", "me"])

    def test_center_zone_is_unknown(self):
        """正好在中线上的（可能很长的一段文本）不应武断判定。"""
        client = bubble_client([("横跨中间的长消息", CHAT_W / 2, "unknown")])
        bubbles = client.read_chat_bubbles(self.make_image())
        self.assertEqual(bubbles[0].sender, "unknown")

    def test_only_incoming_are_reported(self):
        """只应上报"对方"的消息，自己的气泡一律忽略。"""
        client = bubble_client(
            [("你问的第一句", 60, "them"), ("我答的第一句", CHAT_W - 60, "me")]
        )
        key = "老王！"

        # 第一轮：只记录，不上报
        first = client.read_chat_bubbles(self.make_image())
        self.assertEqual(
            client._diff_incoming_bubbles(key, first), [], "第一次只建立基线"
        )

        # 第二轮：只有我自己又发了一条 → 不应上报
        second = first + [
            ChatBubble(text="我答的第二句", sender="me", center_x=CHAT_W - 60, y=60)
        ]
        self.assertEqual(
            client._diff_incoming_bubbles(key, second), [],
            "只有自己的新消息时不应触发回复",
        )

        # 第三轮：对方又发了一条 → 只上报这一条
        third = second + [
            ChatBubble(text="对方追问", sender="them", center_x=60, y=90)
        ]
        incoming = client._diff_incoming_bubbles(key, third)
        self.assertEqual(len(incoming), 1)
        self.assertEqual(incoming[0].text, "对方追问")

    def test_consecutive_incoming_all_reported(self):
        """对方连发多条 → 每条都要识别到。"""
        client = bubble_client([("第一条", 60, "them")])
        key = "老王！"
        base = client.read_chat_bubbles(self.make_image())
        client._diff_incoming_bubbles(key, base)  # 基线

        nxt = base + [
            ChatBubble(text="第二条", sender="them", center_x=60, y=40),
            ChatBubble(text="第三条", sender="them", center_x=60, y=70),
        ]
        incoming = client._diff_incoming_bubbles(key, nxt)
        self.assertEqual([b.text for b in incoming], ["第二条", "第三条"])

    def test_scrolling_does_not_break_diff(self):
        """聊天区滚动（旧消息从顶部消失）后仍能正确识别新增。"""
        client = bubble_client([("第一条", 60, "them"), ("我回", CHAT_W - 60, "me")])
        key = "老王！"
        first = client.read_chat_bubbles(self.make_image())
        client._diff_incoming_bubbles(key, first)

        # 滚动后：第一条滚出视野，只剩 我回 + 对方新消息
        after_scroll = [
            ChatBubble(text="我回", sender="me", center_x=CHAT_W - 60, y=10),
            ChatBubble(text="滚动后的新消息", sender="them", center_x=60, y=40),
        ]
        incoming = client._diff_incoming_bubbles(key, after_scroll)
        self.assertEqual([b.text for b in incoming], ["滚动后的新消息"])

    def test_no_ocr_returns_empty(self):
        client = VisionClient(ocr=None, enable_ocr=False)
        self.assertEqual(
            client.read_chat_bubbles(self.make_image()), [], "没有 OCR 时应返回空"
        )


if __name__ == "__main__":
    unittest.main()
