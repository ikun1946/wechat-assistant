"""GUI 模型页回归：点「获取模型列表」不得改动当前模型的参数。

回归背景：`_on_models_ok` 在 blockSignals 填充下拉框之后，又**无条件**调了一次
`_on_model_selected()`（而且调了两次），于是点一下「获取模型列表」就会把手工勾选的
「图片」等输入模态按名称元数据覆盖掉 —— 本地视觉模型还会被一律判成纯文本。
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import wxbot.gui as gui  # noqa: E402
from wxbot.brain.model_store import ModelStore  # noqa: E402
from wxbot.config import AppConfig  # noqa: E402

MODEL_IDS = ["minicpm-v-4.6", "gemma-4-e2b", "qwen3-8b"]


class FetchModelListKeepsParamsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls._store_path = Path(cls._tmpdir.name) / "models.json"
        # 隔离模型库，避免测试写进真实的 data/models.json
        gui.ModelStore = lambda *a, **k: ModelStore(cls._store_path)

        cfg = AppConfig()
        cfg.llm.provider = "lmstudio"
        cfg.llm.base_url = "http://127.0.0.1:1234/v1"
        cfg.llm.model = "minicpm-v-4.6"
        cfg.llm.modalities = ["text", "image"]
        cfg.llm.context_length = 8192
        cfg.llm.max_tokens = 2048
        cls._real_load = gui.load_config
        gui.load_config = lambda *a, **k: cfg
        cls.window = gui.MainWindow()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.window.close()
        gui.load_config = cls._real_load
        cls._tmpdir.cleanup()

    def checked(self) -> list[str]:
        return [k for k, c in self.window._modality_checks.items() if c.isChecked()]

    def test_local_vision_model_autofilled_with_image(self):
        """前置：minicpm-v-4.6 是视觉模型，名称元数据应能识别。"""
        self.assertIn("image", self.checked(), "初始应识别为多模态")

    def test_fetch_model_list_keeps_checked_modalities(self):
        self.window._on_models_ok(list(MODEL_IDS))
        self.assertIn("image", self.checked(), "点「获取模型列表」不该取消勾选「图片」")
        self.assertEqual(self.window.ctx_spin.value(), 8192, "上下文长度不该被覆盖")
        self.assertEqual(self.window.max_tokens_spin.value(), 2048, "最大输出不该被覆盖")

    def test_fetch_model_list_keeps_manual_context_edit(self):
        self.window.ctx_spin.setValue(16384)
        self.window._on_models_ok(list(MODEL_IDS))
        self.assertEqual(self.window.ctx_spin.value(), 16384, "手工改过的上下文不该被重置")

    def test_status_mentions_params_unchanged(self):
        self.window._on_models_ok(list(MODEL_IDS))
        self.assertIn("保持不变", self.window.model_status.text())

    def test_switching_model_still_autofills(self):
        """修复不能矫枉过正：真的换了模型，仍然要按元数据重新预填。

        注意用 `setCurrentIndex` 模拟真实的下拉点选：editable 的 QComboBox 上
        `setCurrentText()` 只改输入框文字、**不会**移动 currentIndex，也就不发
        `currentIndexChanged`（实测），所以它并不触发预填。
        """
        app = QApplication.instance()
        self.window._on_models_ok(list(MODEL_IDS))
        self.assertIn("image", self.checked(), "minicpm-v-4.6 是多模态")

        self.window.model_combo.setCurrentIndex(1)  # gemma-4-e2b
        app.processEvents()
        self.assertEqual(self.window.model_combo.currentText(), "gemma-4-e2b")
        self.assertEqual(self.checked(), ["text"], "换到纯文本模型后应取消勾选「图片」")

        self.window.model_combo.setCurrentIndex(0)  # minicpm-v-4.6
        app.processEvents()
        self.assertIn("image", self.checked(), "换回视觉模型应重新勾上「图片」")

    def test_new_models_are_still_synced_into_library(self):
        before = len(ModelStore(self._store_path))
        self.window._on_models_ok(list(MODEL_IDS))
        self.assertEqual(len(ModelStore(self._store_path)), len(MODEL_IDS))
        self.assertGreaterEqual(len(ModelStore(self._store_path)), before)


if __name__ == "__main__":
    unittest.main()
