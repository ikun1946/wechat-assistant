"""wxbot 界面重设计原型（独立文件，不修改项目代码）。

用法：
    .venv\\Scripts\\python.exe prototype\\redesign_prototype.py
    .venv\\Scripts\\python.exe prototype\\redesign_prototype.py --theme light
    .venv\\Scripts\\python.exe prototype\\redesign_prototype.py --page model --shot out.png

设计语言：
- 卡片式布局 + 圆角 + 细边框；深色为默认，浅色可切换；
- 左侧竖向导航；顶部状态胶囊 + 主开关（滑动开关，不是普通按钮）；
- 数据用「指标卡」呈现；日志用等宽 + 颜色分级；
- 强调色使用蓝紫渐变，状态色：绿=正常 / 橙=注意 / 红=危险。
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPropertyAnimation,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

APP_NAME = "wxbot"
APP_SUBTITLE = "微信自动回复助手"

# ---------------------------------------------------------------- 主题配色

THEMES = {
    "dark": {
        "bg": "#0e1014",
        "sidebar": "#13161c",
        "surface": "#181c23",
        "surface2": "#1e232c",
        "border": "#262c37",
        "text": "#e8eaf0",
        "muted": "#8b93a7",
        "faint": "#5d6577",
        "accent": "#5b8cff",
        "accent2": "#8b5cf6",
        "success": "#34d399",
        "warn": "#fbbf24",
        "danger": "#f87171",
        "input": "#12151b",
        "hover": "#1f242e",
    },
    "light": {
        "bg": "#f6f7f9",
        "sidebar": "#ffffff",
        "surface": "#ffffff",
        "surface2": "#f2f4f7",
        "border": "#e4e7ec",
        "text": "#16181d",
        "muted": "#6b7280",
        "faint": "#9aa1ae",
        "accent": "#3b6ef5",
        "accent2": "#7c3aed",
        "success": "#0f9d63",
        "warn": "#c77700",
        "danger": "#dc2626",
        "input": "#ffffff",
        "hover": "#eef1f6",
    },
}


def build_qss(t: dict) -> str:
    return f"""
    QWidget {{
        font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
        font-size: 13px;
        color: {t['text']};
    }}
    #Root {{ background: {t['bg']}; }}
    #Sidebar {{ background: {t['sidebar']}; border-right: 1px solid {t['border']}; }}
    #BrandName {{ font-size: 17px; font-weight: 700; letter-spacing: 0.5px; }}
    #BrandSub {{ color: {t['muted']}; font-size: 11px; }}

    QPushButton#Nav {{
        text-align: left;
        padding: 10px 12px;
        border: none;
        border-radius: 10px;
        color: {t['muted']};
        font-size: 13.5px;
        background: transparent;
    }}
    QPushButton#Nav:hover {{ background: {t['hover']}; color: {t['text']}; }}
    QPushButton#Nav:checked {{
        background: {t['surface2']};
        color: {t['text']};
        font-weight: 600;
    }}

    QFrame#Card {{
        background: {t['surface']};
        border: 1px solid {t['border']};
        border-radius: 14px;
    }}
    QFrame#CardFlat {{
        background: {t['surface2']};
        border: 1px solid {t['border']};
        border-radius: 12px;
    }}
    QLabel#CardTitle {{ font-size: 14px; font-weight: 600; }}
    QLabel#Muted {{ color: {t['muted']}; }}
    QLabel#Faint {{ color: {t['faint']}; font-size: 11.5px; }}
    QLabel#StatValue {{ font-size: 26px; font-weight: 700; }}
    QLabel#StatLabel {{ color: {t['muted']}; font-size: 12px; }}
    QLabel#PageTitle {{ font-size: 21px; font-weight: 700; }}
    QLabel#PageDesc {{ color: {t['muted']}; font-size: 12.5px; }}

    QLabel#Pill {{
        border-radius: 13px;
        padding: 5px 12px;
        font-size: 12px;
        font-weight: 600;
    }}

    QPushButton#Primary {{
        border: none;
        border-radius: 10px;
        padding: 9px 16px;
        font-weight: 600;
        color: #ffffff;
        background: {t['accent']};
    }}
    QPushButton#Primary:hover {{ background: {t['accent2']}; }}

    QPushButton#Ghost {{
        border: 1px solid {t['border']};
        border-radius: 10px;
        padding: 8px 14px;
        background: transparent;
        color: {t['text']};
    }}
    QPushButton#Ghost:hover {{ background: {t['hover']}; }}

    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
        background: {t['input']};
        border: 1px solid {t['border']};
        border-radius: 9px;
        padding: 7px 10px;
        selection-background-color: {t['accent']};
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
        border: 1px solid {t['accent']};
    }}
    QComboBox::drop-down {{ border: none; width: 22px; }}

    QPlainTextEdit, QTextEdit {{
        background: {t['input']};
        border: 1px solid {t['border']};
        border-radius: 10px;
        padding: 6px;
        font-family: "Cascadia Mono", "Consolas", monospace;
        font-size: 12px;
    }}

    QScrollArea {{ border: none; background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {t['border']}; border-radius: 4px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {t['faint']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0px; }}

    QSlider::groove:horizontal {{ height: 5px; background: {t['surface2']}; border-radius: 3px; }}
    QSlider::sub-page:horizontal {{ background: {t['accent']}; border-radius: 3px; }}
    QSlider::handle:horizontal {{
        background: #ffffff; border: 2px solid {t['accent']};
        width: 13px; height: 13px; margin: -6px 0; border-radius: 8px;
    }}

    QCheckBox {{ spacing: 8px; color: {t['text']}; }}
    QCheckBox::indicator {{
        width: 16px; height: 16px; border-radius: 5px;
        border: 1px solid {t['border']}; background: {t['input']};
    }}
    QCheckBox::indicator:checked {{ background: {t['accent']}; border-color: {t['accent']}; }}

    QTableWidget {{
        background: transparent;
        border: 1px solid {t['border']};
        border-radius: 10px;
        gridline-color: {t['border']};
    }}
    QHeaderView::section {{
        background: {t['surface2']};
        border: none;
        border-bottom: 1px solid {t['border']};
        padding: 8px 10px;
        color: {t['muted']};
        font-weight: 600;
    }}
    QTableWidget::item {{ padding: 6px 10px; }}
    QTableWidget::item:selected {{ background: {t['hover']}; color: {t['text']}; }}
    """


# ---------------------------------------------------------------- 自定义控件


class Switch(QWidget):
    """滑动开关（现代感的关键控件）。"""

    toggled = Signal(bool)

    def __init__(self, checked: bool = False, *, colors: dict, width: int = 52, height: int = 28):
        super().__init__()
        self._colors = colors
        self._checked = checked
        self._offset = 1.0 if checked else 0.0
        self.setFixedSize(width, height)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._anim = QPropertyAnimation(self, b"offset", self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def get_offset(self) -> float:
        return self._offset

    def set_offset(self, value: float) -> None:
        self._offset = float(value)
        self.update()

    offset = Property(float, get_offset, set_offset)

    def isChecked(self) -> bool:  # noqa: N802 (对齐 Qt 命名)
        return self._checked

    def setChecked(self, checked: bool, *, animate: bool = True) -> None:  # noqa: N802
        if self._checked == checked and animate:
            return
        self._checked = checked
        target = 1.0 if checked else 0.0
        if animate:
            self._anim.stop()
            self._anim.setStartValue(self._offset)
            self._anim.setEndValue(target)
            self._anim.start()
        else:
            self.set_offset(target)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.setChecked(not self._checked)
            self.toggled.emit(self._checked)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        radius = rect.height() / 2

        def mix(c1: QColor, c2: QColor, ratio: float) -> QColor:
            return QColor(
                int(c1.red() * (1 - ratio) + c2.red() * ratio),
                int(c1.green() * (1 - ratio) + c2.green() * ratio),
                int(c1.blue() * (1 - ratio) + c2.blue() * ratio),
            )

        # 轨道：关闭态是灰底，打开态过渡到强调色渐变
        off = QColor(self._colors["surface2"])
        on = mix(QColor(self._colors["accent"]), QColor(self._colors["accent2"]), self._offset)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(mix(off, on, self._offset))
        painter.drawRoundedRect(rect, radius, radius)

        # 打开时给轨道描一圈同色边框，增强"点亮"感
        if self._checked or self._offset > 0.05:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(on)
            painter.drawRoundedRect(rect, radius, radius)

        # 滑块
        knob_d = rect.height() - 6
        x = rect.left() + 3 + self._offset * (rect.width() - knob_d - 6)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(int(x), rect.top() + 3, knob_d, knob_d)


class Card(QFrame):
    """带阴影的卡片容器。"""

    def __init__(self, *, flat: bool = False, shadow: bool = True):
        super().__init__()
        self.setObjectName("CardFlat" if flat else "Card")
        if shadow and not flat:
            effect = QGraphicsDropShadowEffect(self)
            effect.setBlurRadius(22)
            effect.setOffset(0, 4)
            effect.setColor(QColor(0, 0, 0, 60))
            self.setGraphicsEffect(effect)


class StatCard(Card):
    def __init__(self, label: str, value: str, hint: str, accent: str):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(2)

        top = QHBoxLayout()
        name = QLabel(label)
        name.setObjectName("StatLabel")
        dot = QLabel("●")
        dot.setStyleSheet(f"color: {accent}; font-size: 11px;")
        top.addWidget(name)
        top.addStretch(1)
        top.addWidget(dot)
        layout.addLayout(top)

        number = QLabel(value)
        number.setObjectName("StatValue")
        layout.addWidget(number)

        sub = QLabel(hint)
        sub.setObjectName("Faint")
        layout.addWidget(sub)


class StatusPill(QLabel):
    def __init__(self, text: str, color: str, bg: str):
        super().__init__(text)
        self.setObjectName("Pill")
        self.setStyleSheet(f"background: {bg}; color: {color}; border-radius: 13px;")


def make_card(title: str, subtitle: str = "") -> tuple[Card, QVBoxLayout]:
    card = Card()
    layout = QVBoxLayout(card)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(10)
    head = QHBoxLayout()
    name = QLabel(title)
    name.setObjectName("CardTitle")
    head.addWidget(name)
    head.addStretch(1)
    if subtitle:
        sub = QLabel(subtitle)
        sub.setObjectName("Faint")
        head.addWidget(sub)
    layout.addLayout(head)
    return card, layout


def log_view(theme: dict) -> QTextEdit:
    view = QTextEdit()
    view.setReadOnly(True)
    rows = [
        ("17:06:12", "系统", "已启动（模式：dry_run，轮询间隔 3s）", theme["accent"]),
        ("17:06:15", "识别", "腾讯新闻：25岁女画师约稿被骗4万坠", theme["success"]),
        ("17:06:15", "拦截", "不在白名单：腾讯新闻", theme["muted"]),
        ("17:06:21", "识别", "文件传输助手：在吗", theme["success"]),
        ("17:06:23", "拟回复", "在的，稍后回你～（延迟 4.2s，未发送）", theme["warn"]),
        ("17:06:30", "识别", "工作交流群：@我 帮忙看下这个", theme["success"]),
        ("17:06:33", "跳过", "群聊消息未包含触发词", theme["muted"]),
        ("17:06:41", "错误", "生成失败：模型未响应（已重试 1 次）", theme["danger"]),
    ]
    # 统一补齐到 3 个汉字宽，保证分类列对齐
    padded = {"系统": "系统 ", "识别": "识别 ", "拦截": "拦截 ",
              "跳过": "跳过 ", "拟回复": "拟回复", "错误": "错误 "}
    html = []
    for stamp, level, text, color in rows:
        label = padded.get(level, level)
        html.append(
            f'<div style="white-space:nowrap">'
            f'<span style="color:{theme["faint"]}">{stamp}</span>'
            f'<span style="color:{color}">&nbsp;{label}</span>'
            f'<span style="color:{theme["text"]}">&nbsp;{text}</span></div>'
        )
    view.setHtml("<br>".join(html))
    return view


# ---------------------------------------------------------------- 页面


def page_run(theme: dict, state: dict) -> QWidget:
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(14)

    # 主控卡片
    control = Card()
    control_layout = QHBoxLayout(control)
    control_layout.setContentsMargins(20, 18, 20, 18)
    control_layout.setSpacing(18)

    left = QVBoxLayout()
    left.setSpacing(6)
    title = QLabel("自动对话总开关")
    title.setObjectName("CardTitle")
    left.addWidget(title)
    desc = QLabel(
        "启动后才会抓屏识别微信、走安全网关与回复流程；停止则立即停工，不做任何后续动作。"
    )
    desc.setObjectName("PageDesc")
    desc.setWordWrap(True)
    left.addWidget(desc)
    control_layout.addLayout(left, 1)

    switch_box = QVBoxLayout()
    switch_box.setSpacing(6)
    switch = Switch(checked=False, colors=theme, width=60, height=32)

    state_label = QLabel("已停止")
    state_label.setObjectName("Muted")
    state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def on_toggle(checked: bool) -> None:
        state["running"] = checked
        state_label.setText("运行中" if checked else "已停止")
        state_label.setStyleSheet(
            f"color: {theme['success'] if checked else theme['muted']}; font-weight: 600;"
        )

    switch.toggled.connect(on_toggle)
    switch_box.addWidget(switch, 0, Qt.AlignmentFlag.AlignRight)
    switch_box.addWidget(state_label)
    control_layout.addLayout(switch_box)
    layout.addWidget(control)

    # 指标卡
    stats = QHBoxLayout()
    stats.setSpacing(12)
    stats.addWidget(StatCard("识别到", "128", "较昨日 +12", theme["accent"]))
    stats.addWidget(StatCard("拟回复", "43", "dry_run 模式", theme["warn"]))
    stats.addWidget(StatCard("已发送", "0", "发送器待接入", theme["muted"]))
    stats.addWidget(StatCard("拦截", "9", "白名单外 7 / 群聊 2", theme["danger"]))
    layout.addLayout(stats)

    # 参数 + 日志
    bottom = QHBoxLayout()
    bottom.setSpacing(14)

    settings, settings_layout = make_card("运行参数", "随时可改")
    row1 = QHBoxLayout()
    row1.addWidget(QLabel("识别间隔"))
    interval = QSlider(Qt.Orientation.Horizontal)
    interval.setRange(1, 20)
    interval.setValue(3)
    interval.setFixedWidth(150)
    row1.addWidget(interval)
    interval_value = QLabel("3.0 秒")
    interval_value.setObjectName("Muted")
    row1.addWidget(interval_value)
    row1.addStretch(1)
    interval.valueChanged.connect(lambda v: interval_value.setText(f"{v:.1f} 秒"))
    settings_layout.addLayout(row1)

    row2 = QHBoxLayout()
    row2.addWidget(QLabel("运行模式"))
    mode = QComboBox()
    mode.addItems(["仅记录（dry_run）", "全自动（真实发送）"])
    mode.setFixedWidth(190)
    row2.addWidget(mode)
    row2.addStretch(1)
    settings_layout.addLayout(row2)

    row3 = QLabel("白名单")
    settings_layout.addWidget(row3)
    chips = QHBoxLayout()
    chips.setSpacing(6)
    for name in ("张三", "家庭群", "工作交流群"):
        chip = QLabel(name)
        chip.setStyleSheet(
            f"background:{theme['surface2']}; border:1px solid {theme['border']};"
            f"border-radius:11px; padding:4px 10px; color:{theme['text']};"
        )
        chips.addWidget(chip)
    add_chip = QLabel("+ 添加")
    add_chip.setStyleSheet(
        f"border:1px dashed {theme['border']}; border-radius:11px; padding:4px 10px;"
        f"color:{theme['muted']};"
    )
    chips.addWidget(add_chip)
    chips.addStretch(1)
    settings_layout.addLayout(chips)
    settings_layout.addStretch(1)
    settings.setFixedWidth(400)
    bottom.addWidget(settings)

    logs, logs_layout = make_card("实时日志", "本次运行")
    logs_layout.addWidget(log_view(theme))
    bottom.addWidget(logs, 1)
    layout.addLayout(bottom, 1)
    return page


def page_model(theme: dict) -> QWidget:
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(14)

    providers, pl = make_card("厂商", "选中即自动填好地址与 Key 配置")
    grid = QHBoxLayout()
    grid.setSpacing(8)
    provider_names = [
        ("LM Studio", True),
        ("Ollama", False),
        ("DeepSeek", False),
        ("Moonshot Kimi", False),
        ("智谱 GLM", False),
        ("OpenAI", False),
        ("Claude", False),
        ("Gemini", False),
    ]
    for name, active in provider_names:
        chip = QLabel(("● " if active else "") + name)
        if active:
            chip.setStyleSheet(
                f"background:{theme['accent']}; color:#fff; border-radius:11px;"
                f"padding:5px 12px; font-weight:600;"
            )
        else:
            chip.setStyleSheet(
                f"background:{theme['surface2']}; color:{theme['muted']};"
                f"border:1px solid {theme['border']}; border-radius:11px; padding:5px 12px;"
            )
        grid.addWidget(chip)
    grid.addStretch(1)
    pl.addLayout(grid)

    form = QHBoxLayout()
    form.setSpacing(10)
    url = QLineEdit("http://127.0.0.1:1234/v1")
    url.setMinimumWidth(240)
    form.addWidget(QLabel("地址"))
    form.addWidget(url, 1)
    key = QLineEdit("")
    key.setPlaceholderText("本地模型无需 Key")
    key.setMinimumWidth(180)
    form.addWidget(QLabel("API Key"))
    form.addWidget(key)
    fetch = QPushButton("获取模型列表")
    fetch.setObjectName("Primary")
    form.addWidget(fetch)
    pl.addLayout(form)
    layout.addWidget(providers)

    detail = QHBoxLayout()
    detail.setSpacing(14)

    params, params_layout = make_card("当前模型参数", "切换模型自动预填")
    for label, value in (("上下文长度", "8,192 tokens"), ("最大输出", "2,048 tokens")):
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        row.addStretch(1)
        val = QLabel(value)
        val.setObjectName("Muted")
        row.addWidget(val)
        params_layout.addLayout(row)

    modality_row = QHBoxLayout()
    modality_row.addWidget(QLabel("输入模态"))
    modality_row.addStretch(1)
    for name, checked in (("文本", True), ("图片", False), ("音频", False), ("视频", False)):
        box = QCheckBox(name)
        box.setChecked(checked)
        modality_row.addWidget(box)
    params_layout.addLayout(modality_row)

    thinking_row = QHBoxLayout()
    thinking_row.addWidget(QLabel("思考等级"))
    thinking_row.addStretch(1)
    thinking = QComboBox()
    thinking.addItems(["自动（跟随模型默认）", "关闭思考（最快）", "低", "中", "高"])
    thinking.setFixedWidth(210)
    thinking_row.addWidget(thinking)
    params_layout.addLayout(thinking_row)

    temp_row = QHBoxLayout()
    temp_row.addWidget(QLabel("温度"))
    temp_row.addStretch(1)
    temp = QDoubleSpinBox()
    temp.setValue(0.8)
    temp.setSingleStep(0.1)
    temp.setFixedWidth(90)
    temp_row.addWidget(temp)
    params_layout.addLayout(temp_row)
    params_layout.addStretch(1)
    detail.addWidget(params, 1)

    library, library_layout = make_card("模型库", "每个厂商 × 每个模型各一套参数")
    from PySide6.QtWidgets import QHeaderView, QTableWidget, QTableWidgetItem

    table = QTableWidget(0, 5)
    table.setHorizontalHeaderLabels(["厂商", "模型", "上下文", "模态", "思考"])
    table.verticalHeader().setVisible(False)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setShowGrid(False)
    header = table.horizontalHeader()
    for column in (0, 2, 3, 4):
        header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

    rows = [
        ("LM Studio", "qwen3-8b", "8,192", "文本", "自动"),
        ("DeepSeek", "deepseek-chat", "131,072", "文本", "自动"),
        ("Claude", "claude-sonnet-4-5", "200,000", "文本/图片", "中"),
        ("Gemini", "gemini-2.5-flash", "1,000,000", "全模态", "自动"),
        ("OpenAI", "gpt-5-mini", "400,000", "文本/图片", "中"),
    ]
    for provider, model, ctx, modality, thinking_name in rows:
        row = table.rowCount()
        table.insertRow(row)
        for column, value in enumerate((provider, model, ctx, modality, thinking_name)):
            item = QTableWidgetItem(value)
            if column == 2:
                item.setForeground(QColor(theme["accent"]))
            elif column == 4:
                item.setForeground(QColor(theme["success"]))
            elif column == 0:
                item.setForeground(QColor(theme["muted"]))
            table.setItem(row, column, item)
    library_layout.addWidget(table)
    detail.addWidget(library, 1)
    layout.addLayout(detail, 1)
    return page


def page_skills(theme: dict) -> QWidget:
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(14)

    skills = [
        ("人设模仿", "让 AI 用你的说话风格回复", "说话简短、爱用「～」和表情；不端着。", True),
        ("对话记忆", "记得最近的聊天上下文", "参考最近 12 条消息", True),
        ("安全护栏", "敏感话题不接茬、不替你做承诺", "禁谈：转账 / 密码 / 验证码 / 银行卡", True),
        ("群聊策略", "群里默认只回 @我 的消息", "额外触发词：小马、老板", True),
        ("自学习技能", "AI 复盘聊天记录后自动整理", "已整理 14 条（问答习惯 6 / 备注 3 / 风格 5）", True),
    ]
    for name, desc, detail, enabled in skills:
        card = Card(flat=True)
        row = QHBoxLayout(card)
        row.setContentsMargins(16, 13, 16, 13)
        row.setSpacing(14)

        text_box = QVBoxLayout()
        text_box.setSpacing(2)
        head = QLabel(name)
        head.setObjectName("CardTitle")
        text_box.addWidget(head)
        sub = QLabel(desc)
        sub.setObjectName("Muted")
        text_box.addWidget(sub)
        meta = QLabel(detail)
        meta.setObjectName("Faint")
        text_box.addWidget(meta)
        row.addLayout(text_box, 1)

        configure = QPushButton("配置")
        configure.setObjectName("Ghost")
        row.addWidget(configure)

        switch = Switch(checked=enabled, colors=theme, width=48, height=26)
        row.addWidget(switch, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(card)

    layout.addStretch(1)
    return page


def page_speed(theme: dict) -> QWidget:
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(14)

    card, card_layout = make_card("回复速度与限流", "拟人化：宁可慢一点，也别像机器")

    for label, value, low, high, suffix in (
        ("回复延迟下限", 20, 5, 60, " 秒"),
        ("回复延迟上限", 60, 5, 120, " 秒"),
    ):
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(low, high)
        slider.setValue(value)
        row.addWidget(slider, 1)
        readout = QLabel(f"{value / 10:.1f}{suffix}")
        readout.setObjectName("Muted")
        readout.setFixedWidth(70)
        slider.valueChanged.connect(lambda v, s=suffix: readout.setText(f"{v / 10:.1f}{s}"))
        row.addWidget(readout)
        card_layout.addLayout(row)

    limits = QHBoxLayout()
    limits.setSpacing(14)
    for label, value in (("每分钟上限", 2), ("每小时上限", 20), ("每天上限", 60)):
        box = QVBoxLayout()
        name = QLabel(label)
        name.setObjectName("StatLabel")
        box.addWidget(name)
        spin = QSpinBox()
        spin.setValue(value)
        spin.setRange(1, 99999)
        box.addWidget(spin)
        limits.addLayout(box)
    limits.addStretch(1)
    card_layout.addLayout(limits)

    trip = QHBoxLayout()
    trip.addWidget(QLabel("连续发送失败自动熔断"))
    trip_spin = QSpinBox()
    trip_spin.setValue(5)
    trip_spin.setFixedWidth(80)
    trip.addWidget(trip_spin)
    trip.addWidget(QLabel("次"))
    trip.addStretch(1)
    card_layout.addLayout(trip)
    layout.addWidget(card)

    rules, rules_layout = make_card("关键词规则", "回复引擎=规则时生效")
    rules_view = QPlainTextEdit()
    rules_view.setPlainText("在吗,在么 => 在的，稍后回你～\n晚安 => 晚安～\n谢谢 => 不客气～")
    rules_view.setFixedHeight(120)
    rules_layout.addWidget(rules_view)
    layout.addWidget(rules)
    layout.addStretch(1)
    return page


# ---------------------------------------------------------------- 主窗口


class PrototypeWindow(QWidget):
    def __init__(self, theme_name: str = "dark", page: str = "run"):
        super().__init__()
        self.theme = THEMES[theme_name]
        self.setObjectName("Root")
        self.setWindowTitle(f"{APP_NAME} — {APP_SUBTITLE}（界面原型）")
        self.resize(1180, 780)
        self.setStyleSheet(build_qss(self.theme))

        self.state = {"running": False}
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_sidebar())

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(22, 18, 22, 18)
        body_layout.setSpacing(14)
        body_layout.addLayout(self._build_header())

        self.stack = QStackedWidget()
        pages = {
            "run": page_run(self.theme, self.state),
            "reply": page_speed(self.theme),
            "model": page_model(self.theme),
            "skills": page_skills(self.theme),
        }
        for key in ("run", "reply", "model", "skills"):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(pages[key])
            self.stack.addWidget(scroll)
        body_layout.addWidget(self.stack, 1)
        root.addWidget(body, 1)

        self._select_page(page)

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(196)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(14, 18, 14, 16)
        layout.setSpacing(6)

        brand = QVBoxLayout()
        brand.setSpacing(0)
        name = QLabel(APP_NAME)
        name.setObjectName("BrandName")
        sub = QLabel(APP_SUBTITLE)
        sub.setObjectName("BrandSub")
        brand.addWidget(name)
        brand.addWidget(sub)
        layout.addLayout(brand)
        layout.addSpacing(18)

        self.nav_buttons: dict[str, QPushButton] = {}
        for key, glyph, text in (
            ("run", "◉", "运行"),
            ("reply", "≈", "回复与速度"),
            ("model", "◈", "模型"),
            ("skills", "✦", "技能"),
        ):
            button = QPushButton(f"  {glyph}   {text}")
            button.setObjectName("Nav")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, k=key: self._select_page(k))
            layout.addWidget(button)
            self.nav_buttons[key] = button

        layout.addStretch(1)

        footer = QVBoxLayout()
        footer.setSpacing(4)
        version = QLabel("v0.6 · 本地运行")
        version.setObjectName("Faint")
        footer.addWidget(version)
        mode = QLabel("模式：dry_run")
        mode.setObjectName("Faint")
        footer.addWidget(mode)
        layout.addLayout(footer)
        return sidebar

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setSpacing(10)

        self.page_titles = {
            "run": ("运行", "控制自动对话的启停，查看识别与回复情况"),
            "reply": ("回复与速度", "调整拟人化延迟与限流，配置关键词规则"),
            "model": ("模型", "选择厂商与模型，逐模型配置上下文 / 模态 / 思考等级"),
            "skills": ("技能", "让 AI 更懂你的说话方式，并守住安全边界"),
        }
        titles = QVBoxLayout()
        titles.setSpacing(1)
        self.page_title = QLabel("运行")
        self.page_title.setObjectName("PageTitle")
        self.page_desc = QLabel("")
        self.page_desc.setObjectName("PageDesc")
        titles.addWidget(self.page_title)
        titles.addWidget(self.page_desc)
        header.addLayout(titles)
        header.addStretch(1)

        self.pill = StatusPill("● 已停止", self.theme["muted"], self.theme["surface2"])
        header.addWidget(self.pill)
        wechat = StatusPill("微信窗口：已检测", self.theme["success"], self.theme["surface2"])
        header.addWidget(wechat)
        return header

    def _select_page(self, key: str) -> None:
        order = {"run": 0, "reply": 1, "model": 2, "skills": 3}
        self.stack.setCurrentIndex(order.get(key, 0))
        title, desc = self.page_titles.get(key, ("", ""))
        self.page_title.setText(title)
        self.page_desc.setText(desc)
        for name, button in self.nav_buttons.items():
            button.setChecked(name == key)


def main() -> int:
    parser = argparse.ArgumentParser(description="wxbot 界面原型")
    parser.add_argument("--theme", default="dark", choices=sorted(THEMES))
    parser.add_argument("--page", default="run", choices=["run", "reply", "model", "skills"])
    parser.add_argument("--shot", help="渲染成图片后退出（不显示窗口）")
    parser.add_argument("--size", default="1180x780")
    args = parser.parse_args()

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    window = PrototypeWindow(args.theme, args.page)

    if args.shot:
        width, height = (int(part) for part in args.size.lower().split("x"))
        window.resize(width, height)
        window.show()
        app.processEvents()
        window.grab().save(args.shot)
        print(f"saved: {args.shot} ({width}x{height})")
        return 0

    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
