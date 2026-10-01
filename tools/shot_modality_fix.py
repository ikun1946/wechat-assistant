"""可视化验证：模拟点「获取模型列表」前后，输入模态不应被改动。

用真实显示（不设 QT_QPA_PLATFORM）跑，否则截出来全是 □。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication  # noqa: E402

from wxbot.gui import MainWindow  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "prototype" / "shots"
MODELS = ["minicpm-v-4.6", "google/gemma-4-e2b", "qwen-local", "gemma-x"]


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    window._theme_name = "dark"
    window._apply_theme()
    window.resize(1180, 820)
    window.show()
    app.processEvents()
    window._select_page("model")
    app.processEvents()

    def checked() -> list[str]:
        return [k for k, c in window._modality_checks.items() if c.isChecked()]

    # 模拟用户手工勾上「图片」
    window._modality_checks["image"].setChecked(True)
    window.ctx_spin.setValue(16384)
    app.processEvents()
    print("点击前  :", checked(), "ctx =", window.ctx_spin.value())
    window.grab().save(str(OUT / "v22-modality-before.png"))

    # 模拟点「获取模型列表」返回结果
    window._on_models_ok(list(MODELS))
    app.processEvents()
    print("点击后  :", checked(), "ctx =", window.ctx_spin.value())
    window.grab().save(str(OUT / "v22-modality-after.png"))

    # 模拟真从下拉里换一个模型：应当照常重新预填
    index = window.model_combo.findText("google/gemma-4-e2b")
    window.model_combo.setCurrentIndex(index)
    app.processEvents()
    print("换到 gemma:", checked(), "（纯文本模型，取消勾选图片 = 正确）")
    window.grab().save(str(OUT / "v22-modality-switched.png"))

    window.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
