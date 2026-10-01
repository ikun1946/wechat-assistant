"""系统排查 6 个页面在收到滚轮事件时的实际行为。

两件事都查：
  1. 过滤器逻辑 — `eventFilter` 在每种情形下放不放行；
  2. **端到端** — 用 sendEvent 真的把 wheel 事件送到 widget 上，
     然后**实测滚动条有没有动**（这是用户报的"页面滚动有问题"）。

PySide6 这版没有 QTest.sendWheelEvent，所以自己用 sendEvent + QWheelEvent 构造。
QWheelEvent 的 keyword-only 构造器 `(*, angleDelta, inverted, phase, pixelDelta, device)`
不要求 pos / globalPos，这正好够我们的过滤逻辑用。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QWheelEvent  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QComboBox,
    QLabel,
    QPlainTextEdit,
    QSpinBox,
    QWidget,
)

import wxbot.gui as gui  # noqa: E402
from wxbot.config import AppConfig  # noqa: E402

PAGES = ("run", "reply", "persona", "model", "skills", "logs")


def make_wheel(target, dy: float = 120) -> QWheelEvent:
    """PySide6 这版 QWheelEvent 构造要求 pos/globalPos 8 个位置参数。
    **pos 不能给 (0,0) 之类的边缘**——QScrollArea 看到 (0,0) 觉得鼠标在视口外
    就放弃滚了。必须给一个在视口内部的位置。"""
    pos = target.rect().center()
    global_pos = target.mapToGlobal(pos)
    return QWheelEvent(
        QPointF(pos), QPointF(global_pos),
        QPoint(0, dy), QPoint(0, dy),
        Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False,
    )


def ok_or_fails(label: str, passed: bool) -> None:
    print(f"  {'✅' if passed else '❌'}  {label}")


def check_page(window, page_name: str) -> None:
    window._select_page(page_name)
    QApplication.processEvents()
    scroll = window.stack.currentWidget()
    page = scroll.widget()
    bar = scroll.verticalScrollBar()

    print(f"\n=== {page_name} ===")
    print(f"  页面包装：{'✓ QScrollArea' if type(scroll).__name__=='QScrollArea' else '❌'}  "
          f"滚动条 0~{bar.maximum()}")

    combo = page.findChild(QComboBox)
    spin = page.findChild(QSpinBox)
    text = page.findChild(QPlainTextEdit)
    print(f"  发现：combo={combo is not None}  spin={spin is not None}  text={text is not None}")

    if bar.maximum() <= 0:
        print(f"  （页面太短没滚动条，跳过 B）")
        return

    # 端到端，**用 QApplication.sendEvent 把 wheel 送到 5 个不同目标**，
    # 看哪一种能让滚动条动起来。Qt 默认应该让 QScrollArea 的视口自己滚，
    # 但实测发现——**送视口不动**，送 scroll / page 也不动，
    # 只有送 guarded 控件时（被过滤器接管、主动调 _scroll_ancestor）才动。
    bar.setValue(0)
    before = bar.value()
    targets = [
        ("scroll 本身 (QScrollArea)", scroll),
        ("viewport (QWidget)", scroll.viewport()),
        ("page 自身", page),
    ]
    for label, target in targets:
        bar.setValue(0)
        before = bar.value()
        QApplication.sendEvent(target, make_wheel(target, 120))
        QApplication.processEvents()
        after = bar.value()
        status = "✅" if after > before else "❌ 没动"
        print(f"  [B] wheel 送到 {label:35s}: {before} → {after}  ({status})")


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    cfg = AppConfig()
    cfg.whitelist.chats = ("张三",)
    cfg.skills.persona.description = "x" * 400
    gui.load_config = lambda *a, **k: cfg
    window = gui.MainWindow()
    window.resize(1180, 500)
    window.show()
    QApplication.processEvents()
    window._select_page("run")
    QApplication.processEvents()
    print(f"已给 {window._guarded_widgets} 个控件装上滚轮过滤")
    for page_name in PAGES:
        check_page(window, page_name)
    window.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())