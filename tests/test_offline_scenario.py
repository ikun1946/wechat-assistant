"""场景验证：程序没运行时来了消息，之后再打开程序，还会不会回复？

模拟时序（与真实使用一致）：
  T0  程序未运行 → 对方发来消息 → 微信上出现未读红点
  T1  打开程序（第一次轮询）
  T2  下一轮轮询
  T3  再下一轮

另外验证几种现实情况：
  A. 红点还在（用户没手动点开那个会话）→ 应该回复
  B. 红点被手动读掉（用户自己点开看了）→ 不应该回复（避免重复打扰）
  C. 打开程序那一刻对方又发来消息 → 应该回复
"""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

from unittest import mock  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from wxbot.textutil import names_match  # noqa: E402
from wxbot.wechat.vision_client import VisionClient  # noqa: E402

PANEL_W = 800
ROW_Y = 100


def image_with_badge(badge: bool, preview: str = "在吗"):
    """造一张"会话行 + 可选未读红点"的图。"""
    image = np.full((400, PANEL_W, 3), 245, dtype=np.uint8)
    if badge:
        # 红点必须落在裁剪区（宽度 240）内、且避开左侧导航栏(x<56)
        image[ROW_Y - 8 : ROW_Y + 8, 190 : 206] = (60, 60, 230)
    return image


def make_client(badge: bool, preview: str):
    client = VisionClient()
    client._ocr = None  # 稍后替换
    client._read_sessions = None
    return client


def install_fake(client: VisionClient, badge: bool, preview: str):
    """用假的 read_sessions 覆盖真实 OCR（保持 poll_new_messages 的真实逻辑）。"""

    def fake_read_sessions(image=None):
        from wxbot.wechat.vision_client import SessionRow

        return [SessionRow(name="张三", preview=preview, unread=badge, y_center=ROW_Y)]

    client.read_sessions = fake_read_sessions  # type: ignore[assignment]
    return client


def make_isolated_client(rows_factory):
    """构造一个不碰真实微信的 VisionClient（桩掉抓屏与 OCR）。

    `_refresh` 内部的自动抓屏分支也一并抑制（_last_header_check 设成极大值）。
    """
    client = VisionClient()
    client._ocr = None
    client.read_sessions = rows_factory  # type: ignore[assignment]
    client._window = lambda: None  # type: ignore[assignment]
    client._grab = lambda: np.zeros((565, 811, 3), dtype=np.uint8)  # type: ignore[assignment]
    return client


class OfflineMessageScenarioTests(unittest.TestCase):
    def test_A_red_dot_still_present_after_startup(self):
        """A. 程序未运行期间的消息，微信还挂着红点 → 打开程序后应该回复。"""
        client = install_fake(VisionClient(), badge=True, preview="在吗")

        first = client.poll_new_messages()   # T1 打开程序（建立基线）
        second = client.poll_new_messages()  # T2 下一轮
        third = client.poll_new_messages()   # T3 再下一轮（冷却期内不重复）

        self.assertEqual(first, [], "第一次轮询只建立基线，不回复（避免启动瞬间刷屏）")
        self.assertEqual(len(second), 1, "第二轮应识别到这条未读并回复")
        self.assertEqual(second[0].chat_name, "张三")
        self.assertEqual(second[0].text, "在吗")
        self.assertEqual(third, [], "同一条未读不重复回复")

    def test_A2_baseline_delay_is_one_poll(self):
        """A2. 确认"晚一轮"的代价：默认 3 秒间隔 → 约 3 秒内回复。"""
        client = install_fake(VisionClient(), badge=True, preview="在吗")
        client.poll_new_messages()
        messages = client.poll_new_messages()
        self.assertEqual(len(messages), 1)

    def test_B_red_dot_cleared_by_user_reading_it(self):
        """B. 用户自己手动点开看过 → 红点消失 → 程序不该再回复。"""
        client = install_fake(VisionClient(), badge=False, preview="在吗")
        client.poll_new_messages()  # 基线

        # 用户在微信里读掉了消息（红点没了，但摘要变了）
        client.read_sessions = lambda image=None: [  # type: ignore[assignment]
            __import__(
                "wxbot.wechat.vision_client", fromlist=["SessionRow"]
            ).SessionRow(name="张三", preview="在吗", unread=False, y_center=ROW_Y)
        ]
        client._baseline_ready = False  # 假装程序中途才启动
        messages = client.poll_new_messages()
        self.assertEqual(messages, [], "红点已消失 → 不会回复（用户已自行处理）")

    def test_C_message_arrives_while_program_running(self):
        """C. 程序运行中对方发来消息（红点出现）→ 应该回复。"""
        client = install_fake(VisionClient(), badge=False, preview="旧内容")
        client.poll_new_messages()  # 基线：没有红点

        # 对方发来消息 → 红点出现 + 摘要变化
        install_fake(client, badge=True, preview="新消息来了")
        messages = client.poll_new_messages()
        self.assertEqual(len(messages), 1, "运行中来的新消息应被回复")
        self.assertEqual(messages[0].text, "新消息来了")

    def test_D_whitelist_still_applies(self):
        """D. 即使是未运行期间的消息，白名单外依然不回复。"""
        from wxbot.safety.gateway import SafetyGateway
        from wxbot.config import SafetyConfig, WhitelistConfig

        cfg = SafetyConfig(quiet_hours=())
        wl = WhitelistConfig(enabled=True, chats=("别人",))
        gateway = SafetyGateway(cfg, wl)
        client = install_fake(VisionClient(), badge=True, preview="在吗")
        client.poll_new_messages()
        detected = client.poll_new_messages()
        self.assertEqual(len(detected), 1, "识别层面应检测到")
        decision = gateway.check(detected[0].chat_name)
        self.assertFalse(decision.allowed, "但白名单外仍然拦截")


    def test_E_current_open_chat_without_badge(self):
        """E. 当前正打开的会话（微信不给它显示红点）也要能识别新消息。"""
        from wxbot.wechat.vision_client import ChatBubble, SessionRow

        state = {"bubbles": [ChatBubble("你: 你不是他们的父亲吗", "them", 60, 10)]}
        client = make_isolated_client(
            lambda image=None: [
                SessionRow(name="老王！", preview="你不是他们的父亲吗", unread=False, y_center=90)
            ]
        )
        client.read_chat_bubbles = lambda image=None: list(state["bubbles"])  # type: ignore[assignment]
        client._current_chat = "老王！"
        client._last_header_check = 0.0
        # ⚠ 新语义：最后一条气泡是对方发的 = 还没回 → **首轮就应上报**
        first = client.poll_new_messages()
        self.assertEqual(len(first), 1, "启动时就该识别到未回消息")
        self.assertEqual(first[0].chat_name, "老王！")
        self.assertIn("你不是他们的父亲吗", first[0].text)

        # 同一条不应重复上报
        client._last_header_check = 0.0
        self.assertEqual(client.poll_new_messages(), [], "同一条不应重复上报")

        # 对方又发一条 → 应再次上报（清掉上报记录 = 模拟冷却期已过）
        state["bubbles"] = state["bubbles"] + [
            ChatBubble("你: 那不对啊", "them", 60, 40)
        ]
        client._last_reported.clear()
        client._last_header_check = 0.0
        second = client.poll_new_messages()
        self.assertEqual(len(second), 1, "新的未回消息应被识别")
        self.assertIn("那不对啊", second[0].text)

        # 我回复了 → 不应再报
        client._remember_sent("老王！", "收到")
        state["bubbles"] = state["bubbles"] + [ChatBubble("我: 收到", "me", 500, 70)]
        client._last_header_check = 0.0
        self.assertEqual(client.poll_new_messages(), [], "我已回复后不应再报")

    def test_F_current_open_chat_unchanged_is_silent(self):
        """F. 当前会话内容没变 → 不重复回报（避免对着打开的会话一直刷）。"""
        from wxbot.wechat.vision_client import SessionRow

        client = make_isolated_client(
            lambda image=None: [
                SessionRow(name="老王！", preview="旧摘要", unread=False, y_center=90)
            ]
        )
        client.set_current_chat_state("老王！", "内容A")
        client.poll_new_messages()
        for _ in range(3):
            self.assertEqual(client.poll_new_messages(), [], "内容没变不应重复回报")

    def test_G_own_message_in_current_chat_not_echoed(self):
        """G. 当前会话里刚发出去的消息，不应被当成"对方又说话了"。

        按真实流程模拟：_last_body_lines 停在"上次看到的内容"，
        由 poll_new_messages 内部的差分逻辑自己判断有没有新增。
        """
        from wxbot.wechat.vision_client import SessionRow

        client = make_isolated_client(
            lambda image=None: [
                SessionRow(name="老王！", preview="我发的回复", unread=False, y_center=90)
            ]
        )
        # 上一轮看到的内容：对方问 + 我已回复
        client.set_current_chat_state("老王！", "对方：在吗\n我：在的～")
        client._last_header_check = 10**9
        client._last_header_check = 10**9
        # 关掉自动抓屏（无窗口），并手动把"这轮读到的新内容"喂进去
        client._last_body_lines["老王！"] = ["对方：在吗", "我：在的～"]
        client._remember_sent("老王！", "在的～")

        # 下一轮读到的内容：多了我自己的回显（应该被过滤掉）
        added = client._diff_new_body_lines(
            "老王！", "对方：在吗\n我：在的～"
        )
        self.assertEqual(added, [], "自己刚发的回显不应算作新增")
        self.assertFalse(
            any(not client._is_own_line(line, time.time()) for line in added),
            "过滤后不应剩下任何行",
        )

    def test_H_current_open_chat_reports_once_only(self):
        """H. 当前会话新增对方消息 → 报一次；状态不变时不重复报。"""
        from wxbot.wechat.vision_client import ChatBubble, SessionRow

        state = {"bubbles": [ChatBubble("你: 在吗", "them", 60, 10)]}
        client = make_isolated_client(
            lambda image=None: [
                SessionRow(name="老王！", preview="摘要", unread=False, y_center=90)
            ]
        )
        client.read_chat_bubbles = lambda image=None: list(state["bubbles"])  # type: ignore[assignment]
        client._current_chat = "老王！"
        client._last_header_check = 0.0
        first = client.poll_new_messages()
        self.assertEqual(len(first), 1, "启动时应报出最后一条未回消息")

        # 状态不变时不重复上报
        for _ in range(2):
            client._last_header_check = 0.0
            self.assertEqual(client.poll_new_messages(), [], "同一状态不应重复回报")

        # 我回了一条 → 最后一条变成 me → 不应再报
        state["bubbles"] = state["bubbles"] + [ChatBubble("我: 好的", "me", 500, 70)]
        client._last_reported.clear()
        client._last_header_check = 0.0
        self.assertEqual(client.poll_new_messages(), [], "我已回复后不应再报")


    def test_I_consecutive_messages_not_swallowed(self):
        """I. 连发多条都能识别：自己的回复留在聊天区里，不应把对方新消息也吞掉。

        这是实测踩到的 bug：早期用「整体内容是否包含我刚发的文字」来排除回显，
        而聊天区内容是累积的（对方消息 + 我的回复 + 对方新消息），
        于是第二条消息被误判成"自己发的"而永不回复。
        """
        client = make_isolated_client(
            lambda image=None: [
                SessionRow(name="老王！", preview="你不是他们的父亲吗", unread=False, y_center=90)
            ]
        )
        key = "老王！"
        body = "你: 你不是他们的父亲吗"
        client._last_body_lines[key] = [line for line in body.splitlines() if line.strip()]
        client.set_current_chat_state("老王！", "对方: 你不是他们的父亲吗")

        # 我回复了 → 聊天区多出我自己的气泡（应被过滤）
        client._remember_sent("老王！", "是我，他们家的老爸～")
        lines = client._diff_new_body_lines(key, f"{body}\n我: 是我，他们家的老爸～")
        added = [line for line in lines if not client._is_own_line(line, time.time())]
        self.assertEqual(added, [], "自己刚发的回显应被过滤")

        # 对方又发来一条 → 内容里仍然含我的旧回复，但新增行是对方的
        lines = client._diff_new_body_lines(
            key, f"{body}\n我: 是我，他们家的老爸～\n对方: 那不对啊"
        )
        added = [line for line in lines if not client._is_own_line(line, time.time())]
        self.assertEqual(len(added), 1, "对方第二条消息必须被识别出来")
        self.assertIn("那不对啊", added[0])

    def test_J_scrolling_chat_does_not_break_diff(self):
        """J. 聊天区滚动（旧行从顶部消失）后差分仍正确。"""
        client = make_isolated_client(lambda image=None: [])
        key = "老王！"
        first = "18:01\n你: 第一条\n我: 我的回复"
        second = "你: 第一条\n我: 我的回复\n对方: 第二条"

        client._last_body_lines[key] = [l for l in first.splitlines() if l.strip()]
        added = client._diff_new_body_lines(key, second)
        self.assertEqual(added, ["对方: 第二条"])

    def test_K_no_new_content_is_silent(self):
        """K. 内容没变时不该误报。"""
        client = make_isolated_client(lambda image=None: [])
        key = "老王！"
        body = "你: 在吗\n我: 在的"
        client._last_body_lines[key] = [l for l in body.splitlines() if l.strip()]
        self.assertEqual(client._diff_new_body_lines(key, body), [])


    def test_L_session_list_failure_does_not_blind_current_chat(self):
        """L. 会话列表识别失败（窗口太小）时，当前会话的检测仍要工作。

        实测踩坑：read_sessions() 返回空时直接 return []，
        导致整个当前会话检测被跳过 → 表现为"回了几条就彻底卡住"。
        """
        from wxbot.wechat.vision_client import ChatBubble, SESSION_LIST_WIDTH_RATIO

        chat_w = 882 - int(882 * SESSION_LIST_WIDTH_RATIO)
        state = {"bubbles": [ChatBubble("对方: 第一句", "them", 60, 10)]}
        client = make_isolated_client(lambda image=None: [])
        client.read_chat_bubbles = lambda image=None: list(state["bubbles"])  # type: ignore[assignment]
        client.set_current_chat_state("老王！", "对方: 第一句")
        client.poll_new_messages()  # 基线

        # 对方又发一条 → 气泡列表变化
        state["bubbles"] = state["bubbles"] + [
            ChatBubble("对方: 第二句", "them", 60, 40)
        ]
        client.set_current_chat_state("老王！", "对方: 第一句")
        client._seen_incoming["老王！"] = [("对方: 第一句", 10.0)]
        messages = client.poll_new_messages()
        self.assertEqual(len(messages), 1, "列表失效也不该让当前会话检测失明")
        self.assertIn("第二句", messages[0].text)
        del chat_w

    def test_M_poll_uses_single_capture(self):
        """M. 一轮轮询只抓一次屏（供列表/标题/气泡复用），避免变慢。"""
        from unittest import mock

        client = make_isolated_client(lambda image=None: [])
        client._window = lambda: {"hwnd": 1}  # type: ignore[assignment]
        with mock.patch.object(client, "_grab", return_value=np.zeros((565, 811, 3), np.uint8)) as grab:
            client.poll_new_messages()
        self.assertEqual(grab.call_count, 1, "一轮只应抓一次屏")

    def test_N_header_failure_keeps_known_current_chat(self):
        """N. 标题读不出来时，沿用上次已知的当前会话，不要整个丢掉。"""
        from wxbot.wechat.vision_client import (
            ChatBubble,
            SESSION_LIST_WIDTH_RATIO,
            SessionRow,
        )

        client = make_isolated_client(
            lambda image=None: [
                SessionRow(name="老王！", preview="摘要", unread=False, y_center=90)
            ]
        )
        # 标题 OCR 失败（返回空）
        client._read_header = lambda image: ""  # type: ignore[assignment]
        bubbles = [ChatBubble("对方: 旧消息", "them", 60, 10)]
        client.read_chat_bubbles = lambda image=None: list(bubbles)  # type: ignore[assignment]
        client._current_chat = "老王！"
        client._last_header_check = 0.0
        baseline = client.poll_new_messages()  # 首轮：报出未回的"旧消息"

        bubbles.append(ChatBubble("对方: 新消息", "them", 60, 40))
        client._last_reported.clear()
        client._last_header_check = 0.0
        messages = client.poll_new_messages()
        self.assertEqual(
            client._current_chat, "老王！", "标题读不出来时不应清空已知的当前会话"
        )
        self.assertEqual(len(baseline), 1, "首轮应报出未回消息")
        self.assertEqual(len(messages), 1, "标题失效但气泡有效时仍应上报")
        self.assertIn("新消息", messages[0].text)


if __name__ == "__main__":
    unittest.main()
