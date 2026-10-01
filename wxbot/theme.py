"""界面主题：配色、样式表（QSS）与自定义控件。

集中管理视觉，避免样式散落在 gui.py 里：
- THEMES：深色（默认）/ 浅色两套配色；
- build_qss()：生成整窗样式表；
- Switch / StatCard / StatusPill / Card：自定义控件（Qt 原生控件没有的设计元素）。
"""

from __future__ import annotations

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

THEME_DARK = "dark"
THEME_LIGHT = "light"
THEMES = {
    THEME_DARK: {
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
        "shadow": 70,
    },
    THEME_LIGHT: {
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
        "shadow": 34,
    },
}


def theme(name: str) -> dict:
    return THEMES.get(name, THEMES[THEME_DARK])


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
    #PageTitle {{ font-size: 21px; font-weight: 700; }}
    #PageDesc {{ color: {t['muted']}; font-size: 12.5px; }}

    QPushButton {{
        border: 1px solid {t['border']}; border-radius: 9px;
        padding: 7px 12px; background: {t['surface2']}; color: {t['text']};
    }}
    QPushButton:hover {{ background: {t['hover']}; }}
    QPushButton:pressed {{ background: {t['border']}; }}
    QPushButton:disabled {{ color: {t['faint']}; background: {t['surface']}; }}

    QPushButton#Nav {{
        text-align: left; padding: 10px 12px; border: none; border-radius: 10px;
        color: {t['muted']}; font-size: 13.5px; background: transparent;
    }}
    QPushButton#Nav:hover {{ background: {t['hover']}; color: {t['text']}; }}
    QPushButton#Nav:checked {{ background: {t['surface2']}; color: {t['text']}; font-weight: 600; }}

    QFrame#Card, QGroupBox {{
        background: {t['surface']};
        border: 1px solid {t['border']};
        border-radius: 14px;
        margin-top: 10px;
        padding-top: 8px;
        font-weight: 600;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: 14px;
        padding: 0 6px;
        color: {t['text']};
        font-size: 13.5px;
        background-color: {t['surface']};
    }}
    QGroupBox::indicator {{ width: 16px; height: 16px; border-radius: 5px; }}
    QFrame#CardFlat {{ background: {t['surface2']}; border: 1px solid {t['border']}; border-radius: 12px; }}

    QLabel#CardTitle {{ font-size: 14px; font-weight: 600; }}
    QLabel#Muted {{ color: {t['muted']}; font-weight: normal; }}
    QLabel#Faint {{ color: {t['faint']}; font-size: 11.5px; font-weight: normal; }}
    QLabel#StatValue {{ font-size: 26px; font-weight: 700; }}
    QLabel#StatLabel {{ color: {t['muted']}; font-size: 12px; font-weight: normal; }}
    QLabel {{ font-weight: normal; }}

    QPushButton#Primary {{
        border: none; border-radius: 10px; padding: 9px 16px;
        font-weight: 600; color: #ffffff; background: {t['accent']};
    }}
    QPushButton#Primary:hover {{ background: {t['accent2']}; }}
    QPushButton#Primary:disabled {{ background: {t['surface2']}; color: {t['faint']}; }}

    QPushButton#Ghost {{
        border: 1px solid {t['border']}; border-radius: 10px;
        padding: 8px 14px; background: transparent; color: {t['text']};
    }}
    QPushButton#Ghost:hover {{ background: {t['hover']}; }}
    QPushButton#Ghost:disabled {{ color: {t['faint']}; }}

    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
        background: {t['input']}; border: 1px solid {t['border']};
        border-radius: 9px; padding: 6px 10px; min-height: 20px;
        selection-background-color: {t['accent']};
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
        border: 1px solid {t['accent']};
    }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{
        background: {t['surface']}; border: 1px solid {t['border']};
        border-radius: 8px; selection-background-color: {t['hover']};
        selection-color: {t['text']};
    }}
    QSpinBox::up-button, QDoubleSpinBox::up-button,
    QSpinBox::down-button, QDoubleSpinBox::down-button {{ width: 16px; border: none; }}

    QPlainTextEdit, QTextEdit {{
        background: {t['input']}; border: 1px solid {t['border']};
        border-radius: 10px; padding: 6px;
        font-family: "Cascadia Mono", "Consolas", monospace; font-size: 12px;
    }}

    QScrollArea {{ border: none; background: transparent; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {t['border']}; border-radius: 4px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {t['faint']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0px; }}
    QScrollBar:horizontal {{ background: transparent; height: 9px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {t['border']}; border-radius: 4px; min-width: 30px; }}

    QSlider::groove:horizontal {{ height: 5px; background: {t['surface2']}; border-radius: 3px; }}
    QSlider::sub-page:horizontal {{ background: {t['accent']}; border-radius: 3px; }}
    QSlider::handle:horizontal {{
        background: #ffffff; border: 2px solid {t['accent']};
        width: 13px; height: 13px; margin: -6px 0; border-radius: 8px;
    }}

    QCheckBox {{ spacing: 8px; }}
    QCheckBox::indicator {{
        width: 16px; height: 16px; border-radius: 5px;
        border: 1px solid {t['border']}; background: {t['input']};
    }}
    QCheckBox::indicator:checked {{ background: {t['accent']}; border-color: {t['accent']}; }}

    QTableWidget {{
        background: transparent; border: 1px solid {t['border']};
        border-radius: 10px; gridline-color: {t['border']};
    }}
    QHeaderView::section {{
        background: {t['surface2']}; border: none;
        border-bottom: 1px solid {t['border']};
        padding: 8px 10px; color: {t['muted']}; font-weight: 600;
    }}
    QTableWidget::item {{ padding: 6px 10px; }}
    QTableWidget::item:selected {{ background: {t['hover']}; color: {t['text']}; }}

    QToolTip {{
        background: {t['surface']}; color: {t['text']};
        border: 1px solid {t['border']}; padding: 4px 8px; border-radius: 6px;
    }}
    QMessageBox {{ background: {t['surface']}; }}
    QMessageBox QLabel {{ color: {t['text']}; }}
    """


class Switch(QWidget):
    """滑动开关（Qt 原生没有，需自绘）。"""

    toggled = Signal(bool)

    def __init__(self, checked: bool = False, *, colors: dict, width: int = 52, height: int = 28):
        super().__init__()
        self._colors = colors
        self._checked = bool(checked)
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

    def apply_theme(self, colors: dict) -> None:
        self._colors = colors
        self.update()

    def isChecked(self) -> bool:  # noqa: N802 (对齐 Qt 命名)
        return self._checked

    def setChecked(self, checked: bool, *, animate: bool = True) -> None:  # noqa: N802
        checked = bool(checked)
        if self._checked == checked:
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

        off = QColor(self._colors["surface2"])
        on = mix(QColor(self._colors["accent"]), QColor(self._colors["accent2"]), self._offset)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(mix(off, on, self._offset))
        painter.drawRoundedRect(rect, radius, radius)

        if self._checked or self._offset > 0.05:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(on)
            painter.drawRoundedRect(rect, radius, radius)

        knob_d = rect.height() - 6
        x = rect.left() + 3 + self._offset * (rect.width() - knob_d - 6)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(int(x), rect.top() + 3, knob_d, knob_d)


class Card(QFrame):
    """带柔和阴影的卡片。"""

    def __init__(self, *, shadow_alpha: int = 60, flat: bool = False):
        super().__init__()
        self.setObjectName("CardFlat" if flat else "Card")
        if not flat:
            effect = QGraphicsDropShadowEffect(self)
            effect.setBlurRadius(22)
            effect.setOffset(0, 4)
            effect.setColor(QColor(0, 0, 0, shadow_alpha))
            self.setGraphicsEffect(effect)


class StatCard(Card):
    """指标卡：小标题 + 大数字 + 说明。"""

    def __init__(self, label: str, value: str, hint: str, accent: str):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 13, 16, 13)
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

        self.value_label = QLabel(value)
        self.value_label.setObjectName("StatValue")
        layout.addWidget(self.value_label)

        self.hint_label = QLabel(hint)
        self.hint_label.setObjectName("Faint")
        layout.addWidget(self.hint_label)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)

    def set_hint(self, hint: str) -> None:
        self.hint_label.setText(hint)


class StatusPill(QLabel):
    """顶部状态胶囊。"""

    def __init__(self, text: str, fg: str, bg: str):
        super().__init__(text)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_colors(fg, bg)

    def set_colors(self, fg: str, bg: str) -> None:
        self.setStyleSheet(
            f"background: {bg}; color: {fg}; border-radius: 13px;"
            f"padding: 5px 12px; font-size: 12px; font-weight: 600;"
        )


class CollapsibleCard(Card):
    """技能卡：标题 + 说明 + 状态 + 滑动开关 +「设置」展开区。

    收起来时只有一行（列表清爽），点「设置」才展开细节。
    """

    def __init__(
        self,
        title: str,
        subtitle: str,
        switch: "Switch",
        *,
        colors: dict,
        glyph: str = "",
        expanded: bool = False,
    ):
        super().__init__(shadow_alpha=colors.get("shadow", 60))
        self._colors = colors
        self._switch = switch

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 13, 16, 13)
        outer.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(12)

        if glyph:
            icon = QLabel(glyph)
            icon.setStyleSheet(f"color: {colors['accent']}; font-size: 16px;")
            icon.setFixedWidth(20)
            header.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)

        text_box = QVBoxLayout()
        text_box.setSpacing(2)
        name = QLabel(title)
        name.setObjectName("CardTitle")
        text_box.addWidget(name)
        desc = QLabel(subtitle)
        desc.setObjectName("Muted")
        desc.setWordWrap(True)
        text_box.addWidget(desc)
        self.status_label = QLabel("")
        self.status_label.setObjectName("Faint")
        text_box.addWidget(self.status_label)
        header.addLayout(text_box, 1)

        self.toggle_btn = QPushButton("设置")
        self.toggle_btn.setObjectName("Ghost")
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_btn.clicked.connect(self._on_toggle_clicked)
        header.addWidget(self.toggle_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        header.addWidget(switch, 0, Qt.AlignmentFlag.AlignVCenter)
        outer.addLayout(header)

        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 2, 0, 0)
        self.body_layout.setSpacing(8)
        outer.addWidget(self.body)

        self._toggle_body(expanded, animate=False)
        switch.toggled.connect(lambda _checked: self._refresh_status())
        self._refresh_status()

    # ---------- 状态 ----------
    def _refresh_status(self) -> None:
        enabled = self._switch.isChecked()
        if enabled:
            self.status_label.setText("● 已启用")
            self.status_label.setStyleSheet(f"color: {self._colors['success']}; font-size: 11.5px;")
        else:
            self.status_label.setText("○ 已停用")
            self.status_label.setStyleSheet(f"color: {self._colors['faint']}; font-size: 11.5px;")
        self.body.setEnabled(enabled)

    def apply_theme(self, colors: dict) -> None:
        self._colors = colors
        self._switch.apply_theme(colors)
        self._refresh_status()

    # ---------- 展开 / 收起 ----------
    def _on_toggle_clicked(self) -> None:
        self._toggle_body(self.toggle_btn.isChecked())

    def _toggle_body(self, expanded: bool, *, animate: bool = True) -> None:
        del animate
        self.toggle_btn.setChecked(expanded)
        self.toggle_btn.setText("收起 ▴" if expanded else "设置 ▾")
        self.body.setVisible(expanded)

    def set_expanded(self, expanded: bool) -> None:
        self._toggle_body(expanded, animate=False)

    @property
    def switch(self) -> "Switch":
        return self._switch
