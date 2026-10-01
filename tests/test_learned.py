"""自学习技能库（LearnedStore）单元测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from wxbot.brain.learned import LearnedItem, LearnedStore


class LearnedStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "learned.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_add_and_persist(self):
        store = LearnedStore(self.path)
        item = LearnedItem.create("style", "global", "风格", "爱用哈哈哈")
        self.assertTrue(store.add(item))
        reloaded = LearnedStore(self.path)
        self.assertEqual(len(reloaded), 1)
        self.assertEqual(reloaded.items()[0].content, "爱用哈哈哈")
        self.assertEqual(reloaded.items()[0].keywords, ())

    def test_duplicate_not_added(self):
        store = LearnedStore(self.path)
        store.add(LearnedItem.create("style", "global", "风格", "爱用哈哈哈"))
        again = LearnedItem.create("style", "global", "另一个标题", "爱用哈哈哈")
        self.assertFalse(store.add(again))
        self.assertEqual(len(store), 1)

    def test_different_scope_is_new(self):
        store = LearnedStore(self.path)
        store.add(LearnedItem.create("note", "张三", "备注", "是我同事"))
        self.assertTrue(store.add(LearnedItem.create("note", "李四", "备注", "是我同事")))

    def test_toggle_and_remove(self):
        store = LearnedStore(self.path)
        item = LearnedItem.create(
            "faq", "global", "加班", "问加班就说到家再说", keywords=("加班",)
        )
        store.add(item)
        self.assertTrue(store.set_enabled(item.id, False))
        self.assertEqual(store.items(enabled_only=True), [])
        self.assertTrue(store.set_enabled(item.id, True))
        self.assertEqual(len(store.items(enabled_only=True)), 1)
        self.assertTrue(store.remove(item.id))
        self.assertEqual(len(LearnedStore(self.path)), 0)
        self.assertFalse(store.remove("不存在"))


if __name__ == "__main__":
    unittest.main()
