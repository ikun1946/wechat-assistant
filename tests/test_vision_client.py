"""视觉客户端解析逻辑测试（不依赖真实微信窗口，OCR 用假的注入）。"""

from __future__ import annotations

import unittest

import numpy as np

from wxbot.wechat.vision_client import VisionClient, _has_red_badge


def fake_ocr_factory(items: list[tuple[str, float, float]]):
    """items: [(text, cx, cy)] -> 伪造 OCR 引擎（返回与 RapidOCR 相同的结构）。"""

    def _ocr(image):
        result = []
        for text, cx, cy in items:
            half_w, half_h = 40.0, 9.0
            box = [
                [cx - half_w, cy - half_h],
                [cx + half_w, cy - half_h],
                [cx + half_w, cy + half_h],
                [cx - half_w, cy + half_h],
            ]
            result.append([box, text, 0.99])
        return result, 0.01

    return _ocr


class RedBadgeTests(unittest.TestCase):
    def make_region(self, color: tuple[int, int, int]) -> np.ndarray:
        region = np.full((40, 60, 3), 240, dtype=np.uint8)  # BGR 近白底
        region[12:28, 20:36] = color  # 中间画一个方块
        return region

    def test_detects_red_badge(self):
        # 微信红点大致是 BGR ≈ (60, 60, 230)
        self.assertTrue(_has_red_badge(self.make_region((60, 60, 230))))

    def test_ignores_gray_area(self):
        self.assertFalse(_has_red_badge(self.make_region((200, 200, 200))))

    def test_ignores_blue_area(self):
        self.assertFalse(_has_red_badge(self.make_region((230, 100, 60))))

    def test_ignores_empty_region(self):
        self.assertFalse(_has_red_badge(np.zeros((0, 0, 3), dtype=np.uint8)))

    def test_ignores_mostly_red_image(self):
        """整块红（比如红色图片）不应被当成未读红点。"""
        region = np.full((60, 60, 3), (60, 60, 230), dtype=np.uint8)
        self.assertFalse(_has_red_badge(region))


class SessionParsingTests(unittest.TestCase):
    def build_client(self, items) -> VisionClient:
        return VisionClient(ocr=fake_ocr_factory(items))

    def test_pairs_name_with_preview(self):
        client = self.build_client(
            [
                ("Q搜索", 103.0, 56.0),
                ("腾讯新闻", 166.0, 219.0),
                ("25岁女画师约稿被骗4万坠", 170.0, 243.0),
                ("文件传输助手", 161.0, 103.0),
                ("微信团队", 151.0, 363.0),
                ("微信团队欢迎你", 170.0, 387.0),
            ]
        )
        image = np.zeros((641, 882, 3), dtype=np.uint8)
        rows = client.read_sessions(image)

        # 结果按纵向位置排序（会话列表从上到下）
        names = [row.name for row in rows]
        self.assertEqual(names, ["文件传输助手", "腾讯新闻", "微信团队"])
        self.assertEqual(rows[0].preview, "")
        self.assertEqual(rows[1].preview, "25岁女画师约稿被骗4万坠")
        self.assertEqual(rows[2].preview, "微信团队欢迎你")

    def test_search_row_is_skipped(self):
        client = self.build_client([("Q搜索", 103.0, 56.0), ("张三", 150.0, 120.0)])
        image = np.zeros((400, 800, 3), dtype=np.uint8)
        rows = client.read_sessions(image)
        self.assertEqual([row.name for row in rows], ["张三"])

    def test_numeric_row_is_skipped(self):
        client = self.build_client([("3", 150.0, 120.0), ("李四", 150.0, 190.0)])
        image = np.zeros((400, 800, 3), dtype=np.uint8)
        rows = client.read_sessions(image)
        self.assertEqual([row.name for row in rows], ["李四"])

    def test_distant_rows_are_separate_sessions(self):
        """跨会话（间距大）不该被并成一条。"""
        client = self.build_client(
            [
                ("张三", 150.0, 100.0),
                ("在吗", 160.0, 124.0),
                ("李四", 150.0, 260.0),  # 与上一行相距 136px
                ("好的", 160.0, 284.0),
            ]
        )
        image = np.zeros((500, 800, 3), dtype=np.uint8)
        rows = client.read_sessions(image)
        self.assertEqual([row.name for row in rows], ["张三", "李四"])
        self.assertEqual(rows[0].preview, "在吗")

    def test_no_ocr_returns_empty(self):
        client = VisionClient(ocr=None, enable_ocr=False)
        image = np.zeros((300, 600, 3), dtype=np.uint8)
        self.assertEqual(client.read_sessions(image), [])

    def test_unread_flag_from_badge_pixels(self):
        client = self.build_client([("张三", 150.0, 200.0)])
        image = np.full((400, 800, 3), 245, dtype=np.uint8)
        # 会话列表裁剪区宽度 = 800 * 0.30 = 240；红点须画在裁剪区内、且落在
        # 未读检测区间（裁剪区宽度的 55%~100%，即 x >= 132）
        image[192:208, 190:206] = (60, 60, 230)
        rows = client.read_sessions(image)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].unread)

    def test_no_unread_when_clean(self):
        client = self.build_client([("张三", 150.0, 200.0)])
        image = np.full((400, 800, 3), 245, dtype=np.uint8)
        rows = client.read_sessions(image)
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0].unread)

    def test_poll_reports_after_baseline(self):
        """未回的消息会被报出，且不会重复上报。

        注：新规则是"最后一条气泡是对方发的 = 还没回"，
        所以**首轮就可能上报**（不再等第二轮），但只报一次。
        """
        client = self.build_client([("张三", 150.0, 200.0)])
        image = np.full((400, 800, 3), 245, dtype=np.uint8)
        image[192:208, 190:206] = (60, 60, 230)
        client._grab = lambda: image  # type: ignore[assignment]

        baseline = client.poll_new_messages()
        first = client.poll_new_messages()
        second = client.poll_new_messages()
        self.assertEqual(len(baseline) + len(first), 1, "同一条未回消息只应上报一次")
        self.assertEqual(second, [], "冷却期内不应重复回报")

    def test_poll_detects_preview_change_without_badge(self):
        """没有红点也不该漏：消息摘要变化即视为新消息。"""
        client = self.build_client([("张三", 150.0, 200.0)])

        def image_with(preview_text: str):
            def _capture():
                client._ocr = fake_ocr_factory(
                    [("张三", 150.0, 200.0), (preview_text, 160.0, 224.0)]
                )
                return np.full((400, 800, 3), 245, dtype=np.uint8)

            return _capture

        client._grab = image_with("在吗")
        first = client.poll_new_messages()  # 首轮即报出"在吗"（还没回）
        client._remember_sent("张三", "好的")  # 假装我们回过了
        client._last_reported.clear()
        client._grab = image_with("吃了吗")
        messages = client.poll_new_messages()
        self.assertEqual(len(messages), 1, "新摘要应被识别")
        self.assertEqual(messages[0].chat_name, "张三")
        self.assertIn("吃了吗", messages[0].text)

    def test_group_name_detection(self):
        client = self.build_client([("家庭群（5）", 150.0, 100.0)])
        rows = client.read_sessions(np.full((400, 800, 3), 245, dtype=np.uint8))
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].is_group)

    def test_private_chat_not_group(self):
        client = self.build_client([("张三", 150.0, 100.0)])
        rows = client.read_sessions(np.full((400, 800, 3), 245, dtype=np.uint8))
        self.assertFalse(rows[0].is_group)

    def test_unread_count_badge_is_not_taken_as_name(self):
        """未读数量角标（红点里的数字）不能被当成会话名。

        实测踩坑：微信未读 3 条时，OCR 会读到 y=93 的 '3'（角标）排在
        会话名 '老王!' 之前，直接取 group[0] 会把名字误认成 "3" 而丢掉整行。
        """
        client = self.build_client(
            [
                ("3", 110.0, 93.0),        # 未读角标
                ("老王!", 130.0, 103.0),      # 会话名
                ("你不是他们的父亲吗", 172.0, 123.0),  # 摘要
            ]
        )
        image = np.full((400, 800, 3), 245, dtype=np.uint8)
        image[85:101, 100:116] = (60, 60, 230)  # 红点
        rows = client.read_sessions(image)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].name, "老王!", "会话名不能是角标数字")
        self.assertTrue(rows[0].unread)

    def test_numeric_only_row_still_skipped(self):
        client = self.build_client([("3", 110.0, 100.0)])
        rows = client.read_sessions(np.full((400, 800, 3), 245, dtype=np.uint8))
        self.assertEqual(rows, [], "整行都是数字时不应产生会话")

    def test_send_refuses_without_window(self):
        """没有可用窗口时必须拒绝发送（宁可发不出，也不要乱点）。"""
        client = VisionClient(ocr=None, enable_ocr=False)
        client._grab = lambda: None  # type: ignore[assignment]
        self.assertFalse(client.send_text("张三", "你好"))
        self.assertTrue(client.last_send_detail)

    def test_send_rejects_empty_text(self):
        client = VisionClient(ocr=None, enable_ocr=False)
        self.assertFalse(client.send_text("张三", "   "))
        self.assertIn("空文本", client.last_send_detail)

    def test_preview_time_prefix_is_stripped(self):
        client = self.build_client(
            [("张三", 150.0, 100.0), ("17:32 你可以干什么", 160.0, 124.0)]
        )
        rows = client.read_sessions(np.full((400, 800, 3), 245, dtype=np.uint8))
        self.assertEqual(rows[0].preview, "你可以干什么")

    def test_own_sent_message_is_not_treated_as_new(self):
        """自己刚发的消息会出现在摘要里，不能被当成新消息（否则自问自答死循环）。"""
        client = self.build_client([("张三", 150.0, 100.0), ("在吗", 160.0, 124.0)])
        client._grab = lambda: np.full((400, 800, 3), 245, dtype=np.uint8)
        client.poll_new_messages()  # 基线

        client._remember_sent("张三", "我是帮你打字的。")
        client._ocr = fake_ocr_factory(
            [("张三", 150.0, 100.0), ("我是帮你打字的。", 160.0, 124.0)]
        )
        self.assertEqual(client.poll_new_messages(), [], "自己发的消息应被忽略")

    def test_own_message_tolerance_for_halfwidth_name_variance(self):
        """自己发出的记录按归一化名字匹配：「老王！」与「老王!」视为同一会话。"""
        client = self.build_client([("老王！", 150.0, 100.0), ("你好", 160.0, 124.0)])
        client._grab = lambda: np.full((400, 800, 3), 245, dtype=np.uint8)
        client.poll_new_messages()

        client._remember_sent("老王!", "我等你发消息～")
        client._ocr = fake_ocr_factory([("老王！", 150.0, 100.0), ("我等你发消息～", 160.0, 124.0)])
        self.assertEqual(client.poll_new_messages(), [])

    def test_other_person_message_still_detected(self):
        """排除自己消息之后，别人的新消息仍要能识别出来。"""
        client = self.build_client([("张三", 150.0, 100.0), ("在吗", 160.0, 124.0)])
        client._grab = lambda: np.full((400, 800, 3), 245, dtype=np.uint8)
        client.poll_new_messages()  # 首轮会报出这条

        client._remember_sent("张三", "我是帮你打字的。")
        client._last_reported.clear()
        client._ocr = fake_ocr_factory([("张三", 150.0, 100.0), ("吃了吗", 160.0, 124.0)])
        messages = client.poll_new_messages()
        self.assertEqual(len(messages), 1)
        self.assertIn("吃了吗", messages[0].text)
        self.assertEqual(messages[0].text, "吃了吗")


if __name__ == "__main__":
    unittest.main()
