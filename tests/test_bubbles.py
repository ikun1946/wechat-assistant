"""气泡左右方向识别测试（判断"谁发的"）——不依赖真实微信窗口。

造一张聊天区图：对方消息靠左、自己的靠右，验证 sender 判定。
"""

from __future__ import annotations

import sys
import threading
import time
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


# 真实抓屏里"对方气泡"的中心大约落在聊天区 0.28 处（138~184 / 568）。
# 早期这里用 40~70这种靠左的值，等于把气泡起点放在聊天区 5% 处 —— 比微信实际布局
# 夸张得多，会被"左边缘碎片过滤"当成会话列表漏进来的噪声丢掉。
# 坐标必须贴近真实布局，否则测试是在验证一个不存在的场景。
THEM_CX = CHAT_W * 0.28
ME_CX = CHAT_W * 0.78


def bubble_client(entries: list[tuple[str, float, str]]):
    """entries: [(text, center_x, sender)] → 假 OCR 返回带坐标的框。

    每条自动排在不同的 y 上（间隔 40px）：`read_chat_bubbles` 现在会先把垂直相邻的
    行合并成同一个气泡，全都堆在同一个 y 会被当成一条换行消息。
    """
    client = VisionClient(ocr=lambda image: ([], None))
    client._ocr = lambda image: (
        [
            (
                [
                    [cx - 30, 20 + index * 40],
                    [cx + 30, 20 + index * 40],
                    [cx + 30, 36 + index * 40],
                    [cx - 30, 36 + index * 40],
                ],
                text,
                0.99,
            )
            for index, (text, cx, _sender) in enumerate(entries)
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
                ("你是谁", THEM_CX, "them"),
                ("我是张三", ME_CX, "me"),
                ("那不对", THEM_CX + 10, "them"),
            ]
        )
        bubbles = client.read_chat_bubbles(self.make_image())
        self.assertEqual(len(bubbles), 3)
        self.assertEqual([b.sender for b in bubbles], ["them", "me", "them"])
        self.assertEqual(bubbles[1].text, "我是张三")

    def test_threshold_is_relative_to_width(self):
        """阈值必须按比例算，窗口变小也要成立。"""
        client = bubble_client(
            [("左边", THEM_CX, "them"), ("右边", CHAT_W * 0.90, "me")]
        )
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
            [("你问的第一句", THEM_CX, "them"), ("我答的第一句", ME_CX, "me")]
        )
        key = "老王！"

        # 第一轮：只记录，不上报
        first = client.read_chat_bubbles(self.make_image())
        self.assertEqual(
            client._diff_incoming_bubbles(key, first), [], "第一次只建立基线"
        )

        # 第二轮：只有我自己又发了一条 → 不应上报
        second = first + [
            ChatBubble(text="我答的第二句", sender="me", center_x=ME_CX, y=100)
        ]
        self.assertEqual(
            client._diff_incoming_bubbles(key, second), [],
            "只有自己的新消息时不应触发回复",
        )

        # 第三轮：对方又发了一条 → 只上报这一条
        third = second + [
            ChatBubble(text="对方追问", sender="them", center_x=THEM_CX, y=130)
        ]
        incoming = client._diff_incoming_bubbles(key, third)
        self.assertEqual(len(incoming), 1)
        self.assertEqual(incoming[0].text, "对方追问")

    def test_consecutive_incoming_all_reported(self):
        """对方连发多条 → 每条都要识别到。"""
        client = bubble_client([("第一条", THEM_CX, "them")])
        key = "老王！"
        base = client.read_chat_bubbles(self.make_image())
        client._diff_incoming_bubbles(key, base)  # 基线

        nxt = base + [
            ChatBubble(text="第二条", sender="them", center_x=THEM_CX, y=60),
            ChatBubble(text="第三条", sender="them", center_x=THEM_CX, y=100),
        ]
        incoming = client._diff_incoming_bubbles(key, nxt)
        self.assertEqual([b.text for b in incoming], ["第二条", "第三条"])

    def test_scrolling_does_not_break_diff(self):
        """聊天区滚动（旧消息从顶部消失）后仍能正确识别新增。"""
        client = bubble_client([("第一条", THEM_CX, "them"), ("我回", ME_CX, "me")])
        key = "老王！"
        first = client.read_chat_bubbles(self.make_image())
        client._diff_incoming_bubbles(key, first)

        # 滚动后：第一条滚出视野，只剩 我回 + 对方新消息
        after_scroll = [
            ChatBubble(text="我回", sender="me", center_x=ME_CX, y=10),
            ChatBubble(text="滚动后的新消息", sender="them", center_x=THEM_CX, y=60),
        ]
        incoming = client._diff_incoming_bubbles(key, after_scroll)
        self.assertEqual([b.text for b in incoming], ["滚动后的新消息"])

    def test_no_ocr_returns_empty(self):
        client = VisionClient(ocr=None, enable_ocr=False)
        self.assertEqual(
            client.read_chat_bubbles(self.make_image()), [], "没有 OCR 时应返回空"
        )


def box_client(entries):
    """entries: [(text, left, right, top, bottom)] → 假 OCR 返回精确坐标的框。"""
    client = VisionClient(ocr=lambda image: ([], None))
    client._ocr = lambda image: (
        [
            (
                [[left, top], [right, top], [right, bottom], [left, bottom]],
                text,
                0.99,
            )
            for text, left, right, top, bottom in entries
        ],
        0.01,
    )
    return client


class WrappedBubbleTests(unittest.TestCase):
    """换行气泡的方向判定 —— 回归"重复回复"那个 bug。

    背景：气泡换行时续行是在气泡内**左对齐**的，所以一条右对齐的绿色气泡，
    第二行的中心会掉到中线左边。只看单行中心就会把"我刚发的话"判成"对方发的"，
    `_latest_definite_bubble` 于是认为最后一条来自对方 → 重复回复（实测踩过）。
    下面坐标全部按真实抓屏标定（2026-10-01 实测，chat_width=568）：
      对方气泡左缘 138/568≈0.24、中心 161
      自己的气泡右缘 479/568≈0.84，第一行中心 325、**续行中心 212（已越过中线）**
    """

    LINE_H = 16
    OWN_L1 = (CHAT_W * 0.30, CHAT_W * 0.84)   # 自己那条换行消息的第一行
    OWN_L2 = (CHAT_W * 0.30, CHAT_W * 0.45)   # 续行：中心 0.375 < 中线，正是踩坑点
    THEM_L1 = (CHAT_W * 0.24, CHAT_W * 0.70)  # 对方长消息第一行可到 ~0.70（气泡最大宽度）
    THEM_L2 = (CHAT_W * 0.24, CHAT_W * 0.45)

    def make_image(self):
        return np.full((FRAME_H, FRAME_W, 3), 245, dtype=np.uint8)

    def own_bubble(self, top=100, gap=4):
        return [
            ("我是钱程月、王静意、掌奇森、十号林、陈波与最", *self.OWN_L1,
             top, top + self.LINE_H),
            ("严厉的父亲~", *self.OWN_L2,
             top + self.LINE_H + gap, top + 2 * self.LINE_H + gap),
        ]

    def them_bubble(self, top=100, gap=4):
        return [
            ("这是一条很长的消息用来测试换行会不会判错方向", *self.THEM_L1,
             top, top + self.LINE_H),
            ("这是它的第二行", *self.THEM_L2,
             top + self.LINE_H + gap, top + 2 * self.LINE_H + gap),
        ]

    def test_wrapped_own_bubble_is_not_treated_as_theirs(self):
        """核心回归：自己发的换行长消息，第二行不能被判成对方发的。"""
        client = box_client(self.own_bubble())
        bubbles = client.read_chat_bubbles(self.make_image())
        self.assertEqual(len(bubbles), 1, "两行应合并成一条气泡")
        self.assertEqual(bubbles[0].sender, "me")
        self.assertEqual(
            client._latest_definite_bubble(bubbles).sender,
            "me",
            "最后一条是我发的 → 绝不能触发回复",
        )

    def test_wrapped_theirs_bubble_still_theirs(self):
        """对方的长消息即使第一行很宽，也仍要识别为对方发的（不能矫枉过正）。"""
        client = box_client(self.them_bubble())
        bubbles = client.read_chat_bubbles(self.make_image())
        self.assertEqual(len(bubbles), 1)
        self.assertEqual(bubbles[0].sender, "them")

    def test_wrapped_bubble_text_is_joined(self):
        client = box_client(self.own_bubble())
        bubbles = client.read_chat_bubbles(self.make_image())
        self.assertEqual(
            bubbles[0].text, "我是钱程月、王静意、掌奇森、十号林、陈波与最严厉的父亲~"
        )

    def test_line_gap_too_large_is_not_merged(self):
        """0.71 倍行高是实测的最小「不同气泡」间距，超过就不合并。"""
        client = box_client(self.own_bubble(gap=int(self.LINE_H * 0.71) + 2))
        bubbles = client.read_chat_bubbles(self.make_image())
        self.assertEqual(len(bubbles), 2)

    def test_lines_far_apart_are_not_merged(self):
        client = box_client(
            [
                ("第一条", CHAT_W * 0.24, CHAT_W * 0.40, 100, 116),
                ("第二条", CHAT_W * 0.24, CHAT_W * 0.40, 300, 316),
            ]
        )
        bubbles = client.read_chat_bubbles(self.make_image())
        self.assertEqual([b.text for b in bubbles], ["第一条", "第二条"])

    def test_timestamp_does_not_join_a_bubble(self):
        """纯时间戳独立成组，不被吸进相邻气泡。"""
        client = box_client(
            [
                ("19:24", CHAT_W * 0.24, CHAT_W * 0.31, 100, 116),
                ("我在忙", CHAT_W * 0.24, CHAT_W * 0.34, 118, 134),
            ]
        )
        bubbles = client.read_chat_bubbles(self.make_image())
        self.assertEqual([b.text for b in bubbles], ["19:24", "我在忙"])

    def test_left_edge_sliver_is_dropped(self):
        """会话列表漏进裁剪区的碎片（又窄又贴左）必须丢掉。"""
        client = box_client(
            [
                ("张三", 4, 42, 100, 116),
                ("你是谁", CHAT_W * 0.24, CHAT_W * 0.32, 140, 156),
            ]
        )
        bubbles = client.read_chat_bubbles(self.make_image())
        self.assertEqual([b.text for b in bubbles], ["你是谁"])

    def test_short_left_message_is_kept(self):
        """贴左但宽度正常的短消息是真实气泡，不能被误删。"""
        client = box_client([("在吗", CHAT_W * 0.24, CHAT_W * 0.31, 100, 116)])
        bubbles = client.read_chat_bubbles(self.make_image())
        self.assertEqual([b.text for b in bubbles], ["在吗"])

    def test_replied_scenario_does_not_reply_again(self):
        """完整回归场景：对方问过、我也用长消息答过 → 不应再回。"""
        client = box_client(
            [("你是谁", CHAT_W * 0.24, CHAT_W * 0.32, 60, 76)] + self.own_bubble(top=140)
        )
        bubbles = client.read_chat_bubbles(self.make_image())
        self.assertEqual([b.sender for b in bubbles], ["them", "me"])
        self.assertEqual(
            client._pending_incoming("老王！", bubbles), [], "已经回过，不应再次上报"
        )

    def test_unanswered_theirs_still_reported(self):
        """对方长消息还没回 → 必须照常上报（别把刹车踩过头）。"""
        client = box_client(
            [("你是谁", CHAT_W * 0.24, CHAT_W * 0.32, 60, 76)] + self.them_bubble(top=140)
        )
        bubbles = client.read_chat_bubbles(self.make_image())
        self.assertEqual([b.sender for b in bubbles], ["them", "them"])
        pending = client._pending_incoming("老王！", bubbles)
        self.assertEqual(len(pending), 1)
        self.assertIn("第二行", pending[0].text)


class PersistentWgcSessionTests(unittest.TestCase):
    """v2.6.6：WGC 必须是**长驻会话**，不能每次抓帧都建/销一个。

    回归背景：faulthandler 实测，会话攒到一定数量后，下一个会在**原生
    `capture.start()` 里访问冲突**（0xC0000005，崩的是抓屏线程自己）。
    3 秒轮询 = 每 3 秒一个会话，跑上几小时必然踩到。
    （这一组用例不碰 Qt，也不需要真实窗口）
    """

    def test_missing_windows_capture_returns_none(self):
        """没装 windows_capture 时要安静地返回 None，而不是抛异常。"""
        from wxbot.wechat import capture as cap

        saved = cap._SESSION
        cap._SESSION = None
        try:
            # 真实的 0 号 hwnd 不可能抓到任何东西
            self.assertIsNone(cap.grab_frame(0, timeout=0.2, frames=1, settle=0.0))
        finally:
            cap._SESSION = saved

    def test_session_is_reused_not_recreated(self):
        """同一个 hwnd 连续取会话，必须是同一个对象（而不是每次新建）。"""
        from wxbot.wechat import capture as cap

        class _FakeSession:
            def __init__(self, hwnd):
                self.hwnd = hwnd
                self._closed = False
                self.grab_calls = 0

            def grab(self, timeout, settle):
                self.grab_calls += 1
                return np.zeros((4, 4, 3), dtype=np.uint8)

            def close(self):
                self._closed = True

        saved = cap._SESSION
        fake = _FakeSession(123)
        cap._SESSION = fake
        try:
            self.assertIs(cap._get_session(123), fake, "同一 hwnd 应复用同一会话")
            self.assertIs(cap._get_session(123), fake, "再次取也还是同一个")
            # 会话已关闭 → 应该重建（而不是继续用一个废会话）
            fake._closed = True
            self.assertIsNot(cap._get_session(123), fake, "会话失效后要重建")
        finally:
            cap._SESSION = saved

    def test_grab_returns_cached_frame_quickly(self):
        """窗口静止时 WGC 不会送新帧，grab 必须**短等**后返回缓存，不能等满 timeout。"""
        from wxbot.wechat.capture import _WgcSession

        session = _WgcSession.__new__(_WgcSession)  # 不跑 __init__（那会真开会话）
        session._lock = threading.Lock()
        session._new_frame = threading.Event()
        session._image = np.full((4, 4, 3), 7, dtype=np.uint8)
        session._seq = 1
        session._closed = False

        start = time.perf_counter()
        image = session.grab(timeout=3.0, settle=0.2)
        elapsed = time.perf_counter() - start

        self.assertIsNotNone(image, "有缓存帧就该返回它")
        self.assertEqual(int(image[0, 0, 0]), 7)
        self.assertLess(
            elapsed, 1.0, f"有缓存时应短等（settle），不该等满 timeout（实测 {elapsed:.2f}s）"
        )


if __name__ == "__main__":
    unittest.main()
