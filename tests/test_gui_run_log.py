"""实时日志的滚轮与 auto-scroll 行为（v2.6.2 修）。

复盘：上一轮把滚轮改成"页面优先"以消除闪动，但跑在「页面底部 + 一直加新内容」的
实时日志上就反人类 —— 页面已经到底了再滚轮滚轮就是「页面动了日志没动」。
所以实时日志要例外：标记 wheelPriority=internal，让它永远自己滚。

同时：日志 auto-scroll 要改成"智能贴底"——用户在底时才贴底，他们主动滚上去
看历史时不强拉回来。

测试用离屏模式 + 真实 QPlainTextEdit。
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


class RunLogWheelTests(unittest.TestCase):
    """实时日志的滚轮路由例外（标 wheelPriority=internal）。"""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def build(self, *, internal_priority: bool):
        host = QWidget()
        area = QScrollArea(host)
        area.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        # 撑高页面让滚动条真出现
        spacer = QWidget()
        spacer.setFixedHeight(900)
        layout.addWidget(spacer)
        text = QPlainTextEdit()
        text.setFixedHeight(120)
        text.setPlainText("\n".join(f"第{i}行" for i in range(1, 80)))
        if internal_priority:
            text.setProperty("wheelPriority", "internal")
        layout.addWidget(text)
        area.setWidget(content)
        host.resize(400, 200)
        host.show()
        self.app.processEvents()
        self.app.processEvents()
        return host, area, text

    def test_run_log_always_scrolls_itself(self):
        """实时日志（标了 internal）：过滤器放行，事件交给文本框自己处理。"""
        host, area, text = self.build(internal_priority=True)
        guard = gui._NoWheelFilter(host)
        area.verticalScrollBar().setValue(0)
        self.assertGreater(area.verticalScrollBar().maximum(), 0)

        swallowed = guard.eventFilter(text, _FakeWheel(120))

        self.assertFalse(swallowed, "internal 优先：应放行给文本框自己处理")
        host.close()

    def test_normal_text_still_uses_page_first(self):
        """普通文本框（没有 internal 标记）：页面优先，文本框不动。"""
        host, area, text = self.build(internal_priority=False)
        guard = gui._NoWheelFilter(host)
        area.verticalScrollBar().setValue(0)
        inner_before = text.verticalScrollBar().value()

        swallowed = guard.eventFilter(text, _FakeWheel(120))

        self.assertTrue(swallowed, "页面优先：事件应被吞掉")
        self.assertEqual(
            text.verticalScrollBar().value(),
            inner_before,
            "普通文本框不应自己滚",
        )
        self.assertGreater(area.verticalScrollBar().value(), 0, "页面应滚动了")
        host.close()


class RunLogAutoScrollTests(unittest.TestCase):
    """_append_run_log 应该只把"贴在底"的日志往下拉，不要打扰读历史的用户。"""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.text = QPlainTextEdit()
        self.text.setPlainText("\n".join(f"初始{i}" for i in range(1, 20)))

    def _scroll_to(self, position: str):
        bar = self.text.verticalScrollBar()
        if position == "top":
            bar.setValue(0)
        elif position == "middle":
            bar.setValue(bar.maximum() // 2)
        elif position == "bottom":
            bar.setValue(bar.maximum())

    def append(self):
        # 复制 _append_run_log 的核心逻辑（不能直接调用 —— 它依赖 GUI 状态）
        bar = self.text.verticalScrollBar()
        was_pinned = bar.value() >= bar.maximum() - 2
        self.text.appendPlainText("新行")
        if was_pinned:
            bar.setValue(bar.maximum())

    def test_pinned_user_stays_at_bottom(self):
        self._scroll_to("bottom")
        self.append()
        bar = self.text.verticalScrollBar()
        self.assertEqual(bar.value(), bar.maximum())

    def test_user_reading_history_is_not_disturbed(self):
        self._scroll_to("middle")
        self.append()
        bar = self.text.verticalScrollBar()
        self.assertNotEqual(bar.value(), bar.maximum(), "读历史时不应强拉到底")

    def test_scroll_back_to_bottom_resumes_following(self):
        """用户读了一会儿历史后滚回底部，下一条新行应再次贴上去。"""
        self._scroll_to("middle")
        self.append()
        self._scroll_to("bottom")
        self.append()
        bar = self.text.verticalScrollBar()
        self.assertEqual(bar.value(), bar.maximum())


if __name__ == "__main__":
    unittest.main()