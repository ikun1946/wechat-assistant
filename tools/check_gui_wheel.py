"""GUI 滚轮行为自检：控件不吃滚轮、页面照常滚。

用法：.venv/Scripts/python.exe tools/check_gui_wheel.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import wxbot.gui as gui  # noqa: E402
from wxbot.config import AppConfig  # noqa: E402

failures: list[str] = []


def check(condition: bool, label: str) -> None:
    print(("  ✅ " if condition else "  ❌ ") + label)
    if not condition:
        failures.append(label)


class _FakeWheel:
    """最小可用的滚轮事件替身（只需 type / angleDelta / pixelDelta）。"""

    def __init__(self, delta: int):
        self._type = QEvent.Type.Wheel
        self._angle = QPoint(0, delta)
        self._pixel = QPoint(0, 0)

    def type(self):  # noqa: A003
        return self._type

    def angleDelta(self):  # noqa: N802
        return self._angle

    def pixelDelta(self):  # noqa: N802
        return self._pixel


def make_guard(window):
    """构造一个与界面里同类型的过滤器（用于直接驱动其逻辑）。"""
    return gui._NoWheelFilter(window)


def wheel_on(guard, widget, delta: int = 120) -> bool:
    """让过滤器处理一次滚轮：返回 True 表示事件被吞掉（控件不会响应）。"""
    return guard.eventFilter(widget, _FakeWheel(delta))


def scroll_area_for(widget):
    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent, gui.QScrollArea):
            return parent
        parent = parent.parentWidget()
    return None


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)

    cfg = AppConfig()
    cfg.whitelist.chats = ("张三",)
    cfg.skills.persona.description = "x" * 400  # 让页面足够长，便于验证滚动
    gui.load_config = lambda *a, **k: cfg

    window = gui.MainWindow()
    window.resize(1180, 500)  # 压低窗口，强制出现滚动条
    window.show()
    app.processEvents()
    window._select_page("persona")
    app.processEvents()

    print(f"[info] 已给 {window._guarded_widgets} 个控件装上滚轮过滤")
    check(window._guarded_widgets > 10, "过滤覆盖了下拉框/数字框/文本框")

    print("[1] 悬停下拉框滚动：不应改变选中项")
    guard = make_guard(window)
    combo = window.persona_tone_combo
    combo.setCurrentIndex(0)
    before_index = combo.currentIndex()
    before_text = combo.currentText()
    area = scroll_area_for(combo)
    if area is not None:
        area.verticalScrollBar().setValue(0)
    swallowed = wheel_on(guard, combo, 120)
    app.processEvents()
    check(swallowed, "滚轮事件被吞掉（控件不响应）")
    check(before_index == combo.currentIndex(), f"下拉框选中项未变（{before_text}）")
    check(before_text == combo.currentText(), f"下拉框显示文本未变（{combo.currentText()}）")

    print("[2] 悬停数字框滚动：不应改变数值")
    spin = window.persona_formality
    spin.setValue(20)
    before_value = spin.value()
    wheel_on(guard, spin, 120)
    app.processEvents()
    check(spin.value() == before_value, f"数字框数值未变（{spin.value()}）")

    print("[3] 短文本框：内容不滚动，滚轮交给页面")
    short = window.persona_identity_edit
    short.setPlainText("很短的一句话")
    bar = area.verticalScrollBar() if area else None
    if bar is not None:
        bar.setValue(0)
    inner_before = short.verticalScrollBar().value()
    swallowed = wheel_on(guard, short, 120)
    app.processEvents()
    check(swallowed, "滚轮被吞掉（不让短文本框吃掉）")
    check(
        short.verticalScrollBar().value() == inner_before,
        "短文本框自身没有滚动",
    )
    if bar is not None:
        check(
            bar.value() > 0,
            f"外层页面照常滚动（scrollbar={bar.value()}/{bar.maximum()}）",
        )

    print("[4] 长文本框：内容溢出时允许在框内滚动")
    long_text = window.persona_edit
    long_text.setPlainText("\n".join(f"第{i}行内容" for i in range(1, 60)))
    app.processEvents()
    inner_bar = long_text.verticalScrollBar()
    check(
        inner_bar.maximum() > 0,
        f"长文本框内容确实溢出（可滚范围 0~{inner_bar.maximum()}）",
    )
    passed_through = wheel_on(guard, long_text, 120)
    app.processEvents()
    check(not passed_through, "过滤器放行（滚轮交给文本框自己处理）")
    # 直接驱动文本框自身的滚动条，确认它具备滚动能力
    inner_before = inner_bar.value()
    inner_bar.setValue(inner_bar.value() + 120)
    app.processEvents()
    check(
        inner_bar.value() > inner_before,
        f"文本框自身可滚动（{inner_before} -> {inner_bar.value()}）",
    )

    print("[5] 悬停复选框：不受影响")
    box_state = window.require_mention_check.isChecked()
    wheel_on(guard, window.require_mention_check, 120)
    app.processEvents()
    check(
        window.require_mention_check.isChecked() == box_state,
        "复选框状态未受影响",
    )

    print("[6] 滑块：数值不应被滚轮改变")
    slider_before = window.persona_formality.value()
    wheel_on(guard, window.persona_formality, 120)
    app.processEvents()
    check(window.persona_formality.value() == slider_before, "滑块数值未变")

    print("[7] 反向滚动也有效（往回滚）")
    if bar is not None:
        bar.setValue(300)
        wheel_on(guard, short, -120)
        app.processEvents()
        check(bar.value() == 180, f"反向滚动生效（{bar.value()}）")

    window.close()
    app.quit()

    print()
    if failures:
        print(f"共 {len(failures)} 项未通过：")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("全部通过：控件不吃滚轮，页面滚动正常。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
