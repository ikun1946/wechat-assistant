"""模型库（ModelStore）测试：每个厂商 × 模型独立参数。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from wxbot.brain.model_store import ModelEntry, ModelStore


class ModelStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "models.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_ensure_autofills_meta(self):
        store = ModelStore(self.path)
        entry = store.ensure("openai", "gpt-4o")
        self.assertEqual(entry.provider, "openai")
        self.assertIn("image", entry.modalities)
        self.assertTrue(entry.auto_filled)
        self.assertEqual(len(store), 1)

    def test_ensure_is_idempotent_and_keeps_user_edits(self):
        store = ModelStore(self.path)
        entry = store.ensure("openai", "gpt-4o")
        entry.context_length = 999
        store.upsert(entry)
        again = store.ensure("openai", "gpt-4o")
        self.assertEqual(again.context_length, 999, "重复获取不应覆盖用户改动")

    def test_same_model_different_provider_are_separate(self):
        store = ModelStore(self.path)
        store.ensure("openai", "gpt-4o")
        store.ensure("openrouter", "gpt-4o")
        self.assertEqual(len(store), 2)

    def test_sync_provider_models(self):
        store = ModelStore(self.path)
        entries = store.sync_provider_models("lmstudio", ["qwen3-8b", "qwen2.5-7b-instruct"])
        self.assertEqual(len(entries), 2)
        self.assertEqual(len(store.entries("lmstudio")), 2)
        # 再次同步不会重复
        store.sync_provider_models("lmstudio", ["qwen3-8b", "qwen2.5-7b-instruct", "gemma-3-4b"])
        self.assertEqual(len(store.entries("lmstudio")), 3)

    def test_refill_meta_overwrites(self):
        store = ModelStore(self.path)
        entry = store.ensure("lmstudio", "qwen3-8b")
        entry.context_length = 1
        entry.modalities = ("text", "image")  # 用户乱改
        store.upsert(entry)
        refreshed = store.refill_meta("lmstudio", "qwen3-8b")
        self.assertIsNotNone(refreshed)
        self.assertEqual(refreshed.context_length, 8_192)  # 本地模型保守默认

    def test_remove_and_reload(self):
        store = ModelStore(self.path)
        store.ensure("deepseek", "deepseek-chat")
        self.assertTrue(store.remove("deepseek", "deepseek-chat"))
        self.assertFalse(store.remove("deepseek", "deepseek-chat"))
        self.assertEqual(len(ModelStore(self.path)), 0)

    def test_persistence_roundtrip(self):
        store = ModelStore(self.path)
        entry = store.ensure("anthropic", "claude-sonnet-4-5")
        entry.thinking_level = "high"
        entry.modalities = ("text", "image")
        store.upsert(entry)

        reloaded = ModelStore(self.path).get("anthropic", "claude-sonnet-4-5")
        self.assertIsNotNone(reloaded)
        self.assertEqual(reloaded.thinking_level, "high")
        self.assertEqual(reloaded.modalities, ("text", "image"))

    def test_entry_key_format(self):
        entry = ModelEntry(provider="openai", model="gpt-5")
        self.assertEqual(entry.key, "openai::gpt-5")


if __name__ == "__main__":
    unittest.main()
