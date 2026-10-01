"""滚轮过滤器的行为测试（离屏，不需要真实窗口）。

回归背景（v2.6.2）：用户报"滚动窗口时鼠标正好在文本框上，窗口会闪动"。
根因是旧规则"文本框内容溢出就把滚轮给它"—— 而内容是在**光标底下**移动的，
滚一下页面光标下就换成另一个溢出文本框，下一格它就抢走，页面纹丝不动，
再滚一下又变回页面。两个滚动条交替接管，视觉上就是闪动。
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEvent, QPoint  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QLabel,
    QPlainTextEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

import wxbot.gui as gui  # noqa: E402


class _FakeWheel:
    def __init__(self, delta: int):
        self._angle = QPoint(0, delta)
        self._pixel = QPoint(0, 0)

    def type(self):  # noqa: A003
        return QEvent.Type.Wheel

    def angleDelta(self):  # noqa: N802
        return self._angle

    def pixelDelta(self):  # noqa: N802
        return self._pixel


class WheelGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def build(self, *, long_text: bool):
        """造一个「页面可滚 + 里面放着一个长文本框」的真实控件树。"""
        host = QWidget()
        area = QScrollArea(host)
        area.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.addWidget(QLabel("上面"))
        self.text = QPlainTextEdit()
        self.text.setFixedHeight(80)
        if long_text:
            self.text.setPlainText("\n".join(f"第{i}行" for i in range(1, 60)))
        else:
            self.text.setPlainText("很短")
        layout.addWidget(self.text)
        # 撑高内容，让页面真的出现滚动条（加 stretch 是撑不出滚动的）
        filler = QLabel("填充")
        filler.setFixedHeight(900)
        layout.addWidget(filler)
        area.setWidget(content)
        host.resize(400, 200)
        host.show()
        self.app.processEvents()
        self.app.processEvents()
        return host, area

    def wheel(self, guard, obj, delta=120):
        return guard.eventFilter(obj, _FakeWheel(delta))

    # ---------- 核心回归 ----------
    def test_page_wins_over_long_text(self):
        """长文本框不能抢走滚轮 —— 这是闪动的根因。"""
        host, area = self.build(long_text=True)
        guard = gui._NoWheelFilter(host)
        self.assertGreater(self.text.verticalScrollBar().maximum(), 0, "前提：文本框确实溢出")

        bar = area.verticalScrollBar()
        bar.setValue(0)
        inner_before = self.text.verticalScrollBar().value()

        swallowed = self.wheel(guard, self.text)

        self.app.processEvents()
        self.assertTrue(swallowed, "事件应被吞掉（先滚页面）")
        self.assertGreater(bar.value(), 0, "页面应该滚动")
        self.assertEqual(
            self.text.verticalScrollBar().value(),
            inner_before,
            "文本框自身不应滚动",
        )
        host.close()

    def test_repeated_wheels_are_stable(self):
        """连续滚很多格，行为必须始终一致，不能在页面/文本框之间跳变。"""
        host, area = self.build(long_text=True)
        guard = gui._NoWheelFilter(host)
        bar = area.verticalScrollBar()
        inner = self.text.verticalScrollBar()

        for _ in range(6):
            bar.setValue(50)
            inner.setValue(0)
            before_page = bar.value()
            self.wheel(guard, self.text)
            self.app.processEvents()
            self.assertGreater(bar.value(), before_page, "每一格都应该滚页面")
            self.assertEqual(inner.value(), 0, "文本框一次都不该动")
        host.close()

    # ---------- 页面到底后才交给文本框 ----------
    def test_text_gets_wheel_when_page_is_at_end(self):
        host, area = self.build(long_text=True)
        guard = gui._NoWheelFilter(host)
        bar = area.verticalScrollBar()
        bar.setValue(bar.maximum())
        self.app.processEvents()

        passed_through = self.wheel(guard, self.text)

        self.assertFalse(passed_through, "页面到底后应放行给文本框")
        host.close()

    def test_no_false_success_when_scroll_is_clamped(self):
        """页面到底时 setValue 会被静默钳位 —— 不能再当成'滚成功了'。

        早先的写法只要找到滚动条就 return True，页面到底时也返回 True，
        于是事件被吞掉，文本框永远拿不到滚轮。
        """
        host, area = self.build(long_text=True)
        bar = area.verticalScrollBar()
        bar.setValue(bar.maximum())
        self.app.processEvents()
        # 从页面内容开始问"页面滚得动吗"：到底时必须回答"滚不动"
        self.assertFalse(
            gui._NoWheelFilter._scroll_ancestor(area.widget(), 120),
            "页面到底时必须返回 False",
        )
        # 页面还能滚时才返回 True
        bar.setValue(bar.maximum() - 200)
        self.app.processEvents()
        self.assertTrue(
            gui._NoWheelFilter._scroll_ancestor(area.widget(), 120),
            "页面还能滚时应返回 True",
        )
        host.close()

    # ---------- 原有行为不能退化 ----------
    def test_short_text_still_passes_to_page(self):
        host, area = self.build(long_text=False)
        guard = gui._NoWheelFilter(host)
        bar = area.verticalScrollBar()
        bar.setValue(0)
        inner_before = self.text.verticalScrollBar().value()

        swallowed = self.wheel(guard, self.text)

        self.app.processEvents()
        self.assertTrue(swallowed)
        self.assertEqual(self.text.verticalScrollBar().value(), inner_before)
        self.assertGreater(bar.value(), 0)
        host.close()

    def test_reverse_direction(self):
        host, area = self.build(long_text=True)
        guard = gui._NoWheelFilter(host)
        bar = area.verticalScrollBar()
        bar.setValue(300)
        self.app.processEvents()
        self.wheel(guard, self.text, -120)
        self.app.processEvents()
        self.assertEqual(bar.value(), 180, "反向滚动应把页面往上带")


if __name__ == "__main__":
    unittest.main()
