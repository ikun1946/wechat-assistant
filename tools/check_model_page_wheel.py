"""模型页滚轮行为实测：滚轮划过各类控件，页面是否正常滚动。

用法：.venv/Scripts/python.exe tools/check_model_page_wheel.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEvent, QPoint  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import wxbot.gui as gui  # noqa: E402
from wxbot.config import AppConfig  # noqa: E402

failures: list[str] = []


def check(condition: bool, label: str) -> None:
    print(("  ✅ " if condition else "  ❌ ") + label)
    if not condition:
        failures.append(label)


class FakeWheel:
    def __init__(self, delta: int):
        self._t = QEvent.Type.Wheel
        self._angle = QPoint(0, delta)
        self._pixel = QPoint(0, 0)

    def type(self):  # noqa: A003
        return self._t

    def angleDelta(self):  # noqa: N802
        return self._angle

    def pixelDelta(self):  # noqa: N802
        return self._pixel


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    cfg = AppConfig()
    cfg.skills.persona.description = "x" * 200
    gui.load_config = lambda *a, **k: cfg

    window = gui.MainWindow()
    window.resize(1180, 560)  # 压低，强制需要滚动
    window.show()
    app.processEvents()
    window._select_page("model")
    app.processEvents()

    scroll = window.stack.currentWidget()
    bar = scroll.verticalScrollBar()
    guard = gui._NoWheelFilter(window)

    print(f"[info] 模型页滚动条范围 0~{bar.maximum()}")

    print("[1] 悬停在模型下拉框上滚动 → 选中项不变、页面滚动")
    combo = window.model_combo
    combo.setEditText("google/gemma-4-e2b")
    before_text = combo.currentText()
    bar.setValue(0)
    swallowed = guard.eventFilter(combo, FakeWheel(120))
    app.processEvents()
    check(swallowed, "滚轮被吞（下拉框不响应）")
    check(combo.currentText() == before_text, f"下拉框内容未变（{combo.currentText()}）")
    check(bar.value() > 0, f"页面正常滚动（{bar.value()}/{bar.maximum()}）")

    print("[2] 悬停在模态复选框上滚动 → 勾选状态不变、页面滚动")
    box = window._modality_checks["image"]
    before_checked = box.isChecked()
    bar.setValue(0)
    swallowed = guard.eventFilter(box, FakeWheel(120))
    app.processEvents()
    check(box.isChecked() == before_checked, "复选框勾选状态未变")
    check(bar.value() > 0, f"页面滚动（{bar.value()}）")

    print("[3] 悬停在模型库表格上滚动 → 表格自身滚动（表格是列表，滚轮应滚它）")
    bar.setValue(0)
    table_bar = window.model_table.verticalScrollBar()
    print(f"      表格行数={window.model_table.rowCount()} 表格可滚={table_bar.maximum()}")
    if table_bar.maximum() > 0:
        before = table_bar.value()
        # 表格未装过滤器 → 事件直接给表格（这里只验证它的滚动条能力）
        table_bar.setValue(before + 60)
        check(table_bar.value() > before, "表格可独立滚动")
    else:
        check(True, "表格内容不满，无需滚动（不影响页面滚动）")

    print("[4] 悬停在温度数字框上滚动 → 数值不变、页面滚动")
    spin = window.temp_spin
    before_value = spin.value()
    bar.setValue(0)
    swallowed = guard.eventFilter(spin, FakeWheel(120))
    app.processEvents()
    check(spin.value() == before_value, f"温度数值未变（{spin.value()}）")
    check(bar.value() > 0, f"页面滚动（{bar.value()}）")

    print("[5] 反向滚动 → 页面能往上滚")
    bar.setValue(200)
    guard.eventFilter(window.model_combo, FakeWheel(-120))
    app.processEvents()
    check(bar.value() == 80, f"反向滚动生效（{bar.value()}）")

    print("[6] 地址输入框（单行）→ 内容不被改动，页面滚动")
    line = window.base_url_edit
    before_url = line.text()
    bar.setValue(0)
    swallowed = guard.eventFilter(line, FakeWheel(120))
    app.processEvents()
    check(line.text() == before_url, "地址输入框内容未变")
    check(bar.value() > 0, f"页面滚动（{bar.value()}）")

    window.close()
    app.quit()
    print()
    if failures:
        print(f"共 {len(failures)} 项未通过：")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("全部通过：模型页滚轮行为正常。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
