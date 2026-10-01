"""「模型」页改版原型 —— 独立文件，不影响主程序。

设计目标：把一屏 20 个同权重控件，收敛成**三层意图**：
  1. 当前在用什么   —— 厂商 + 模型（最大、最显眼）+ 状态 + 一个主按钮
  2. 回复什么手感   —— 只留 3 个真正常调的：温度(滑块) / 思考 / 上下文
  3. 管一堆模型     —— 模型库默认折叠，标题带数量徽章

连接地址、API Key、最大输出、输入模态、请求超时、系统提示词
全部收进「更多设置 / 更换服务商」，默认不出现。

运行（深色 / 浅色）：
    .venv\\Scripts\\python.exe prototype\\model_page_prototype.py --theme dark
    .venv\\Scripts\\python.exe prototype\\model_page_prototype.py --theme light

只做视觉稿：控件是静态的，不连真实配置。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from wxbot.theme import Card, build_qss, theme  # noqa: E402


def pill(text: str, fg: str, bg: str) -> QLabel:
    label = QLabel(text)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setStyleSheet(
        f"background: {bg}; color: {fg}; border-radius: 12px;"
        f"padding: 4px 11px; font-size: 12px; font-weight: 600;"
    )
    return label


def caption(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Muted")
    return label


def section_title(text: str, hint: str = "") -> QWidget:
    host = QWidget()
    row = QHBoxLayout(host)
    row.setContentsMargins(0, 0, 0, 0)
    title = QLabel(text)
    title.setObjectName("CardTitle")
    row.addWidget(title)
    if hint:
        note = QLabel(hint)
        note.setObjectName("Faint")
        row.addWidget(note)
    row.addStretch(1)
    return host


class Field(QWidget):
    """一行：标签 + 控件，标签固定宽度，整页对齐。"""

    def __init__(self, label: str, widget: QWidget, hint: str = ""):
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(14)
        tag = QLabel(label)
        tag.setObjectName("Muted")
        tag.setFixedWidth(72)
        row.addWidget(tag)
        row.addWidget(widget, 1)
        if hint:
            note = QLabel(hint)
            note.setObjectName("Faint")
            row.addWidget(note)
        self.widget = widget


class Disclosure(QFrame):
    """一个「点标题才展开」的区块 —— 用来放低频设置。

    刻意不加卡片底色：它已经在一个卡片里了，再套一层框就成了「盒中盒」，
    页面会重新变乱。这里只用一条细分隔线表达层级。
    """

    def __init__(self, title: str, subtitle: str, colors: dict):
        super().__init__()
        self.setObjectName("Disclosure")
        self._colors = colors
        self.setStyleSheet(
            f"#Disclosure {{ border-top: 1px solid {colors['border']}; }}"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 10, 0, 0)
        outer.setSpacing(10)

        self._title = title
        self._button = QPushButton(f"{title}  ▾")
        self._button.setObjectName("DisclosureToggle")
        self._button.setCheckable(True)
        self._button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._button.setStyleSheet(
            f"#DisclosureToggle {{ text-align: left; font-size: 13px; font-weight: 600;"
            f"color: {colors['muted']}; background: transparent; border: none; padding: 2px 0; }}"
            f"#DisclosureToggle:hover {{ color: {colors['accent']}; }}"
            f"#DisclosureToggle:checked {{ color: {colors['accent']}; }}"
        )
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self._button)
        note = QLabel(subtitle)
        note.setObjectName("Faint")
        row.addWidget(note, 1)
        outer.addLayout(row)

        self._body = QWidget()
        self.body_layout = QVBoxLayout(self._body)
        self.body_layout.setContentsMargins(0, 4, 0, 0)
        self.body_layout.setSpacing(10)
        outer.addWidget(self._body)

        self._button.toggled.connect(self._toggle)
        self._toggle(False)

    def _toggle(self, checked: bool) -> None:
        self._body.setVisible(checked)
        self._button.setText(f"{self._title}  {'▴' if checked else '▾'}")

    def set_expanded(self, checked: bool) -> None:
        self._button.setChecked(checked)


def build_provider_combo() -> QComboBox:
    combo = QComboBox()
    combo.addItems(["LM Studio（本地）", "DeepSeek（深度求索）", "Anthropic Claude", "自定义…"])
    return combo


def build_model_combo() -> QComboBox:
    combo = QComboBox()
    combo.setEditable(True)
    combo.addItems(["minicpm-v-4.6", "google/gemma-4-e2b", "qwen3-8b", "text-embedding-nomic"])
    return combo


def build_page(colors: dict) -> QWidget:
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(24, 20, 24, 20)
    layout.setSpacing(14)

    # ============ 1. 当前在用什么 ============
    now = Card()
    now_layout = QVBoxLayout(now)
    now_layout.setContentsMargins(18, 16, 18, 16)
    now_layout.setSpacing(12)

    head = QHBoxLayout()
    head.setSpacing(10)
    title = QLabel("当前模型")
    title.setObjectName("CardTitle")
    head.addWidget(title)
    head.addWidget(pill("● 已连接", colors["success"], colors["surface2"]))
    head.addWidget(pill("本地 · 不走网络", colors["muted"], colors["surface2"]))
    head.addStretch(1)
    now_layout.addLayout(head)

    pick = QGridLayout()
    pick.setHorizontalSpacing(12)
    pick.setVerticalSpacing(10)
    pick.addWidget(caption("厂商"), 0, 0)
    pick.addWidget(build_provider_combo(), 0, 1)
    pick.addWidget(caption("模型"), 0, 2)
    pick.addWidget(build_model_combo(), 0, 3)
    pick.setColumnStretch(1, 3)
    pick.setColumnStretch(3, 4)
    now_layout.addLayout(pick)

    actions = QHBoxLayout()
    actions.setSpacing(10)
    test_btn = QPushButton("试一条回复")
    test_btn.setObjectName("Primary")
    actions.addWidget(test_btn)
    refresh = QPushButton("拉取模型列表")
    refresh.setObjectName("Ghost")
    actions.addWidget(refresh)
    actions.addStretch(1)
    status = QLabel("上下文 8,192 · 输出 2,048 · 文本+图片")
    status.setObjectName("Faint")
    actions.addWidget(status)
    now_layout.addLayout(actions)
    layout.addWidget(now)

    # ============ 2. 回复什么手感 ============
    feel = Card()
    feel_layout = QVBoxLayout(feel)
    feel_layout.setContentsMargins(18, 16, 18, 16)
    feel_layout.setSpacing(12)
    feel_layout.addWidget(section_title("回复手感", "日常只需要动这三个"))

    temp_row = QWidget()
    temp_layout = QHBoxLayout(temp_row)
    temp_layout.setContentsMargins(0, 0, 0, 0)
    temp_layout.setSpacing(14)
    tag = QLabel("温度")
    tag.setObjectName("Muted")
    tag.setFixedWidth(72)
    temp_layout.addWidget(tag)
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setRange(0, 20)
    slider.setValue(8)
    slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    temp_layout.addWidget(slider, 1)
    temp_value = QLabel("0.8")
    temp_value.setFixedWidth(34)
    temp_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    temp_value.setStyleSheet(
        f"color: {colors['text']}; font-size: 15px; font-weight: 600;"
    )
    temp_layout.addWidget(temp_value)
    feel_layout.addWidget(temp_row)

    scale = QHBoxLayout()
    scale.setContentsMargins(86, 0, 48, 0)
    scale.setSpacing(0)
    low = caption("更稳")
    high = caption("更跳脱")
    scale.addWidget(low)
    scale.addStretch(1)
    scale.addWidget(high)
    feel_layout.addLayout(scale)

    thinking = QComboBox()
    thinking.addItems(["自动（跟随模型默认）", "关闭", "低", "中", "高"])
    feel_layout.addWidget(Field("思考", thinking, "让模型先想再答，回复会慢一些"))

    ctx = QSpinBox()
    ctx.setRange(512, 2_000_000)
    ctx.setSingleStep(1024)
    ctx.setValue(8192)
    ctx.setSuffix(" tokens")
    ctx.setToolTip("该模型可用的最大上下文；超出会被服务端截断")
    feel_layout.addWidget(Field("上下文", ctx))

    more = Disclosure("更多设置", "最大输出 · 输入模态 · 请求超时 · 系统提示词", colors)
    out_spin = QSpinBox()
    out_spin.setRange(1, 200_000)
    out_spin.setValue(2048)
    out_spin.setSuffix(" tokens")
    more.body_layout.addWidget(Field("最大输出", out_spin))

    modality_row = QWidget()
    modality_layout = QHBoxLayout(modality_row)
    modality_layout.setContentsMargins(0, 0, 0, 0)
    modality_layout.setSpacing(16)
    for key in ("文本", "图片", "音频", "视频", "文件"):
        box = QCheckBox(key)
        box.setChecked(key in ("文本", "图片"))
        modality_layout.addWidget(box)
    modality_layout.addStretch(1)
    more.body_layout.addWidget(Field("输入模态", modality_row))

    timeout = QSpinBox()
    timeout.setRange(1, 300)
    timeout.setValue(30)
    timeout.setSuffix(" 秒")
    more.body_layout.addWidget(Field("请求超时", timeout))

    prompt = QLineEdit()
    prompt.setPlaceholderText("留空 = 使用程序内置的默认提示词（强烈推荐）")
    more.body_layout.addWidget(Field("系统提示词", prompt, "别在这里写「你是…助手」，会让人设自曝"))
    feel_layout.addWidget(more)
    layout.addWidget(feel)

    # ============ 3. 管一堆模型 ============
    library = Card()
    library_layout = QVBoxLayout(library)
    library_layout.setContentsMargins(18, 14, 18, 14)
    library_row = QHBoxLayout()
    library_row.setSpacing(10)
    lib_title = QLabel("模型库")
    lib_title.setObjectName("CardTitle")
    library_row.addWidget(lib_title)
    library_row.addWidget(pill("12 个", colors["muted"], colors["surface2"]))
    library_row.addStretch(1)
    manage = QPushButton("管理  ▾")
    manage.setObjectName("Ghost")
    library_row.addWidget(manage)
    library_layout.addLayout(library_row)
    lib_note = QLabel("每个厂商的每个模型各自保存一份参数，需要时才展开")
    lib_note.setObjectName("Faint")
    library_layout.addWidget(lib_note)
    layout.addWidget(library)

    layout.addStretch(1)
    return page


def main() -> int:
    parser = argparse.ArgumentParser(description="模型页改版原型")
    parser.add_argument("--theme", default="dark", choices=["dark", "light"])
    parser.add_argument("--width", type=int, default=980)
    parser.add_argument("--height", type=int, default=760)
    parser.add_argument("--shot", default="", help="保存截图到该路径后退出")
    parser.add_argument("--expand", action="store_true", help="展开「更多设置」后截图")
    args = parser.parse_args()

    app = QApplication.instance() or QApplication(sys.argv)
    colors = theme(args.theme)
    app.setStyleSheet(build_qss(colors))

    host = QWidget()
    host.setObjectName("Root")
    root = QVBoxLayout(host)
    root.setContentsMargins(0, 0, 0, 0)

    page = build_page(colors)
    if args.expand:
        for child in page.findChildren(Disclosure):
            child.set_expanded(True)

    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setWidget(page)
    root.addWidget(area)

    host.resize(args.width, args.height)
    host.show()
    app.processEvents()

    if args.shot:
        Path(args.shot).parent.mkdir(parents=True, exist_ok=True)
        host.grab().save(args.shot)
        print(f"saved: {args.shot}")
    else:
        app.exec()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
