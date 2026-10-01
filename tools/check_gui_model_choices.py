"""验证「模型下拉框能正常切换」。

用法：.venv/Scripts/python.exe tools/check_gui_model_choices.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication, QComboBox  # noqa: E402

import wxbot.gui as gui  # noqa: E402
from wxbot.brain.model_store import ModelStore  # noqa: E402
from wxbot.config import AppConfig  # noqa: E402

failures: list[str] = []


def check(condition: bool, label: str) -> None:
    print(("  ✅ " if condition else "  ❌ ") + label)
    if not condition:
        failures.append(label)


def combo_items(combo: QComboBox) -> list[str]:
    return [combo.itemText(i) for i in range(combo.count())]


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)

    # 造两个厂商的模型库数据
    store = ModelStore()
    store.upsert(store_entry("lmstudio", "gemma-x"))
    store.upsert(store_entry("lmstudio", "qwen-local"))
    store.upsert(store_entry("deepseek", "deepseek-chat"))
    store.upsert(store_entry("deepseek", "deepseek-reasoner"))

    cfg = AppConfig()
    cfg.llm.provider = "lmstudio"
    cfg.llm.model = "gemma-x"
    gui.load_config = lambda *a, **k: cfg

    window = gui.MainWindow()
    window.show()
    app.processEvents()
    window._select_page("model")
    app.processEvents()

    print("[1] 启动时下拉框应已填好当前厂商的模型")
    items = combo_items(window.model_combo)
    check(len(items) > 0, f"下拉框非空（{items}）")
    check(
        all("deepseek" not in item for item in items),
        "不包含其它厂商的模型",
    )
    check(window.model_combo.currentText() == "gemma-x", "保留当前选中的模型")

    print("[2] 下拉选择另一个模型 → 生效")
    index = window.model_combo.findText("qwen-local")
    check(index >= 0, "目标模型在列表里")
    window.model_combo.setCurrentIndex(index)
    app.processEvents()
    check(window.model_combo.currentText() == "qwen-local", "下拉框已切换")
    collected = window._collect_config()
    check(collected.llm.model == "qwen-local", "保存配置时会写入新模型")

    print("[3] 切换厂商 → 下拉框换成新厂商的模型")
    pidx = window.provider_combo.findData("deepseek")
    window.provider_combo.setCurrentIndex(pidx)
    app.processEvents()
    items = combo_items(window.model_combo)
    check(
        "deepseek-chat" in items and "deepseek-reasoner" in items,
        f"已换成 DeepSeek 的模型（{items}）",
    )
    check(
        all("qwen-local" not in item for item in items),
        "不再显示上一个厂商的模型",
    )

    print("[4] 空模型库时给出提示")
    window.provider_combo.setCurrentIndex(window.provider_combo.findData("groq"))
    app.processEvents()
    check(
        "下拉框为空" in window.model_choices_hint.text(),
        f"提示文案：{window.model_choices_hint.text()[:40]}",
    )

    print("[5] 可以手动输入任意模型名")
    window.model_combo.setEditText("some/custom-model")
    app.processEvents()
    check(
        window._collect_config().llm.model == "some/custom-model",
        "手动输入的模型名能被保存",
    )

    window.close()
    app.quit()
    print()
    if failures:
        print(f"共 {len(failures)} 项未通过：")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("全部通过：模型可以自由切换。")
    return 0


def store_entry(provider: str, model: str):
    from wxbot.brain.model_store import ModelEntry

    return ModelEntry(provider=provider, model=model, context_length=8192)


if __name__ == "__main__":
    raise SystemExit(main())
