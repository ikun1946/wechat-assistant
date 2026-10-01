"""短期记忆（ChatMemory）单元测试 —— 含"会话名归一化"这个关键行为。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from wxbot.brain.memory import ChatMemory, clean_message_text


class NormalizeKeyTests(unittest.TestCase):
    """实测踩坑：OCR 把「老王！」读成「老王!」时，会被当成两个会话，模型只看到一半对话。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "mem.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_fullwidth_and_halfwidth_share_memory(self):
        memory = ChatMemory(self.path)
        memory.add("老王！", "them", "在吗")
        memory.add("老王!", "me", "在的")
        self.assertEqual(len(memory.chats()), 1, "全角/半角应合并为一个会话")
        self.assertEqual(len(memory.recent("老王！", 10)), 2)
        self.assertEqual(len(memory.recent("老王!", 10)), 2, "两种写法都能取到同一份")

    def test_load_merges_existing_split_entries(self):
        """旧文件里已经是两份 → 加载时应自动合并。"""
        payload = {
            "version": 1,
            "chats": {
                "老王！": [{"role": "them", "text": "第一条", "ts": 1}],
                "老王!": [{"role": "me", "text": "第二条", "ts": 2}],
            },
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        memory = ChatMemory(self.path)
        self.assertEqual(len(memory.chats()), 1, "加载时应合并")
        items = memory.recent("老王！", 10)
        self.assertEqual([t for _r, t in items], ["第一条", "第二条"], "按时间排序")

    def test_whitespace_insensitive(self):
        memory = ChatMemory(self.path)
        memory.add("张 三", "them", "你好")
        self.assertEqual(len(memory.recent("张三", 5)), 1, "空格差异应视为同一会话")


class CleanTextTests(unittest.TestCase):
    def test_strips_trailing_badge_digits(self):
        self.assertEqual(
            clean_message_text("你不是他们的父亲吗 3 3"), "你不是他们的父亲吗"
        )

    def test_strips_time_prefix(self):
        self.assertEqual(clean_message_text("17:32 你可以干什么"), "你可以干什么")

    def test_keeps_normal_text(self):
        self.assertEqual(clean_message_text("在吗"), "在吗")

    def test_keeps_internal_digits(self):
        self.assertEqual(clean_message_text("我有 3 个猫"), "我有 3 个猫")


class BasicMemoryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "mem.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_add_and_recent_order(self):
        memory = ChatMemory(self.path)
        memory.add("张三", "them", "在吗")
        memory.add("张三", "me", "在的")
        self.assertEqual(memory.recent("张三", 5), [("them", "在吗"), ("me", "在的")])

    def test_persistence_roundtrip(self):
        memory = ChatMemory(self.path)
        memory.add("家庭群", "them", "晚上回来吃饭吗")
        reloaded = ChatMemory(self.path)
        self.assertEqual(
            reloaded.recent("家庭群", 3), [("them", "晚上回来吃饭吗")]
        )
        self.assertEqual(reloaded.chats(), ["家庭群"])

    def test_trim_keeps_latest(self):
        memory = ChatMemory(self.path, max_per_chat=3)
        for i in range(5):
            memory.add("张三", "them", f"m{i}")
        self.assertEqual([t for _r, t in memory.recent("张三", 10)], ["m2", "m3", "m4"])

    def test_clear_single_and_all(self):
        memory = ChatMemory(self.path)
        memory.add("张三", "them", "hi")
        memory.add("李四", "them", "hi")
        memory.clear("张三")
        self.assertEqual(memory.recent("张三", 3), [])
        self.assertEqual(len(memory.recent("李四", 3)), 1)
        memory.clear()
        self.assertEqual(memory.chats(), [])

    def test_ignores_empty_chat_name(self):
        memory = ChatMemory(self.path)
        memory.add("", "them", "hi")
        self.assertEqual(memory.chats(), [])

    def test_corrupt_file_does_not_crash(self):
        self.path.write_text("{not json", encoding="utf-8")
        memory = ChatMemory(self.path)  # 不应抛异常
        self.assertEqual(memory.chats(), [])


if __name__ == "__main__":
    unittest.main()
