# -*- coding: utf-8 -*-
"""刷题匠 PaperDrill —— Qt 通用组件。

所有组件只负责"怎么画"，不持有业务状态：颜色从 :class:`Theme` 取，数据由调用方喂进来。
自绘组件（``OptionRow`` / ``ProgressRing`` / ``ScoreHeader``）在主题切换后调用 ``refresh()`` 重绘。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .theme import Theme

__all__ = [
    "Card", "SectionLabel", "MutedLabel", "Badge", "StatPill", "SegmentedControl",
    "OptionRow", "OptionData", "OPTION_STATES", "ProgressRing", "ScoreHeader", "EmptyState",
    "HLine", "QuestionNavigator", "smooth_fade", "elide_text", "wrap_lines", "clear_layout",
    "iter_children", "link_clicked",
]


OPTION_STATES = ("default", "selected", "correct", "wrong", "dim", "disabled")


# ---------------------------------------------------------------- 工具
def elide_text(text: str, font: QFont, width: int, mode: Qt.TextElideMode = Qt.ElideRight) -> str:
    """按像素宽度省略文本。"""
    if width <= 0:
        return ""
    return QFontMetrics(font).elidedText(text or "", mode, width)


def wrap_lines(text: str, font: QFont, width: int) -> list[str]:
    """把文本按像素宽度折行（用于自绘控件计算高度）。"""
    if width <= 0:
        return [text or ""]
    metrics = QFontMetrics(font)
    lines: list[str] = []
    for paragraph in (text or "").split("\n"):
        if not paragraph:
            lines.append("")
            continue
        current = ""
        for ch in paragraph:
            candidate = current + ch
            if metrics.horizontalAdvance(candidate) > width and current:
                lines.append(current)
                current = ch
            else:
                current = candidate
        lines.append(current)
    return lines or [""]


def smooth_fade(color: QColor, alpha: int) -> QColor:
    """返回带透明度的颜色副本（用于弱化/高亮）。"""
    out = QColor(color)
    out.setAlpha(max(0, min(255, int(alpha))))
    return out


# ---------------------------------------------------------------- 基础容器
class Card(QFrame):
    """圆角卡片容器（QSS 中 ``#Card``）。"""

    def __init__(self, theme: Theme, title: str = "", hint: str = "",
                 parent: "QWidget | None" = None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.setObjectName("Card")
        self.setFrameShape(QFrame.NoFrame)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(theme.space_lg, theme.space_md, theme.space_lg, theme.space_lg)
        outer.setSpacing(theme.space_sm)
        if title:
            head = QHBoxLayout()
            head.setSpacing(theme.space_sm)
            self.title_label = QLabel(title, self)
            self.title_label.setObjectName("CardTitle")
            head.addWidget(self.title_label)
            self.hint_label = QLabel(hint, self)
            self.hint_label.setObjectName("CardHint")
            head.addWidget(self.hint_label)
            head.addStretch(1)
            outer.addLayout(head)
        else:
            self.title_label = None
            self.hint_label = None
        self.body = QVBoxLayout()
        self.body.setSpacing(theme.space_sm)
        outer.addLayout(self.body, 1)

    def set_hint(self, text: str) -> None:
        if self.hint_label is not None:
            self.hint_label.setText(text)

    def add(self, widget: QWidget, stretch: int = 0) -> QWidget:
        self.body.addWidget(widget, stretch)
        return widget

    def add_layout(self, layout, stretch: int = 0) -> None:
        self.body.addLayout(layout, stretch)


class HLine(QFrame):
    """一条主题色分隔线。"""

    def __init__(self, theme: Theme, parent: "QWidget | None" = None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.setFixedHeight(1)
        self._restyle()

    def _restyle(self) -> None:
        self.setStyleSheet(f"background:{self.theme.border};border:none;")

    def refresh(self, theme: "Theme | None" = None) -> None:
        """主题切换后重新取色。"""
        if theme is not None:
            self.theme = theme
        self._restyle()


class QuestionNavigator(QWidget):
    """题号导览：5 列方格网格，内嵌滚动，按作答状态着色。

    布局与交互
    ----------
    * 固定约 5 行高（≈194px），题目更多时在内部滚动，不撑高侧栏；
    * 5 列自适应宽度、高 34px 的矩形格，显示 1..N；
    * 点击格子发出 :attr:`go_requested`（被点击题的**队列下标**，0 基）。

    性能
    ----
    ``set_questions`` 只在题量变化时重建按钮（300+ 题也只建一次），其余情况仅对
    样式签名发生变化的格子调用 ``setStyleSheet``，避免每次刷新全量重绘。
    """

    go_requested = Signal(int)

    COLUMNS = 5
    CELL_HEIGHT = 34
    GAP = 4
    VISIBLE_ROWS = 5
    STATUSES = ("todo", "correct", "wrong")

    def __init__(self, theme: Theme, parent: "QWidget | None" = None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.total = 0
        self.current = 0
        self.statuses: list[str] = []
        self.buttons: list[QPushButton] = []
        self._signatures: list[tuple] = []

        self._host = QWidget(self)
        # widgetResizable 的 QScrollArea 会把内部控件缩到视口大小；这里按行数给容器
        # 固定内容高度，题多时才会真正出现内部滚动（而不是把 34px 格子压扁）。
        self._host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._grid = QGridLayout(self._host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(self.GAP)
        for column in range(self.COLUMNS):
            self._grid.setColumnStretch(column, 1)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.setWidget(self._host)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.scroll)

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        # 5 行的确切高度（186px）+ 4px 余量：第 6 行正好落在视口之外，不出现半行
        self.setFixedHeight(self.CELL_HEIGHT * self.VISIBLE_ROWS
                            + self.GAP * (self.VISIBLE_ROWS - 1) + 4)
        self.setAccessibleName("题目导览")

    # ------------------------------------------------------------ 数据
    def set_questions(self, total: int, current: int = 0,
                      statuses: "Sequence[str] | None" = None) -> None:
        """更新总题数 / 当前题（0 基）/ 各题状态。"""
        total = max(0, int(total or 0))
        rebuilt = total != self.total or len(self.buttons) != total
        if rebuilt:
            self._rebuild(total)

        previous = self.current
        self.current = max(0, min(int(current or 0), total - 1)) if total else 0

        raw = list(statuses or ())
        normalized: list[str] = []
        for index in range(total):
            value = str(raw[index]) if index < len(raw) else "todo"
            normalized.append(value if value in self.STATUSES else "todo")
        self.statuses = normalized

        self._apply_styles()
        if total and (rebuilt or self.current != previous):
            self._scroll_to_current()

    def _rebuild(self, total: int) -> None:
        clear_layout(self._grid)
        self.buttons = []
        self._signatures = []
        self.total = total
        for index in range(total):
            btn = QPushButton(str(index + 1), self._host)
            # 不抢焦点：点过题号后 Enter / 方向键仍由主窗口快捷键处理
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(self.CELL_HEIGHT)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.setMinimumWidth(0)
            btn.setToolTip(f"第 {index + 1} 题")
            btn.clicked.connect(lambda _=False, k=index: self.go_requested.emit(k))
            self._grid.addWidget(btn, index // self.COLUMNS, index % self.COLUMNS)
            self.buttons.append(btn)
        rows = (total + self.COLUMNS - 1) // self.COLUMNS
        content_height = rows * self.CELL_HEIGHT + max(0, rows - 1) * self.GAP
        self._host.setFixedHeight(content_height)
        # 立即排版，保证随后 ensureWidgetVisible 使用的是最新的格子位置
        self._grid.activate()

    def _scroll_to_current(self) -> None:
        if 0 <= self.current < len(self.buttons):
            self.scroll.ensureWidgetVisible(self.buttons[self.current], 0, 0)

    # ------------------------------------------------------------ 绘制
    def _css(self, status: str, is_current: bool) -> str:
        t = self.theme
        if status == "correct":
            bg, fg, border = t.success_weak, t.success, t.success
        elif status == "wrong":
            bg, fg, border = t.danger_weak, t.danger, t.danger
        else:
            bg, fg, border = t.surface, t.text_muted, t.border
        width = 1
        weight = 600
        if is_current:
            border = t.primary
            width = 2
            weight = 700
            if status not in ("correct", "wrong"):
                # 未答的当前题用浅灰底，接近参考截图里的当前格
                bg = t.surface_alt
        radius = max(3, t.radius - 2)
        return (
            f"QPushButton{{background:{bg};color:{fg};border:{width}px solid {border};"
            f"border-radius:{radius}px;padding:0px;font-size:{t.font_size_small}px;"
            f"font-weight:{weight};}}"
            f"QPushButton:hover{{border-color:{t.primary};}}"
            f"QPushButton:pressed{{background:{t.surface_hover};}}"
        )

    def _apply_styles(self) -> None:
        """只更新样式签名变化的格子（刷新时不做全量 setStyleSheet）。"""
        for index, btn in enumerate(self.buttons):
            status = self.statuses[index] if index < len(self.statuses) else "todo"
            signature = (self.theme.name, status, index == self.current)
            if index < len(self._signatures) and self._signatures[index] == signature:
                continue
            btn.setStyleSheet(self._css(status, index == self.current))
            if index < len(self._signatures):
                self._signatures[index] = signature
            else:
                self._signatures.append(signature)
        if len(self._signatures) > len(self.buttons):
            del self._signatures[len(self.buttons):]

    def refresh_theme(self, theme: "Theme | None" = None) -> None:
        """主题切换：换令牌并强制重算所有格子的样式。"""
        if theme is not None:
            self.theme = theme
        self._signatures = []
        self._apply_styles()
        self.update()

    # 与其它自绘组件保持一致的别名
    def refresh(self, theme: "Theme | None" = None) -> None:
        self.refresh_theme(theme)


class SectionLabel(QLabel):
    """小节标题（灰色小字）。"""

    def __init__(self, text: str, theme: Theme, parent: "QWidget | None" = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("SectionLabel")
        self.theme = theme


class MutedLabel(QLabel):
    """次要文本，支持折行。"""

    def __init__(self, text: str = "", theme: "Theme | None" = None,
                 wrap: bool = True, parent: "QWidget | None" = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("Muted")
        if wrap:
            self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)


class Badge(QLabel):
    """圆角小徽标：题型、状态、卷号等。"""

    TONES = ("primary", "success", "danger", "warning", "neutral")

    def __init__(self, text: str = "", tone: str = "primary",
                 theme: "Theme | None" = None, parent: "QWidget | None" = None) -> None:
        super().__init__(text, parent)
        self.theme = theme
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.set_tone(tone)

    def set_tone(self, tone: str) -> None:
        self.tone = tone if tone in self.TONES else "neutral"
        self._restyle()

    def set_text(self, text: str, tone: "str | None" = None) -> None:
        self.setText(text)
        if tone:
            self.set_tone(tone)

    def _restyle(self) -> None:
        t = self.theme
        if t is None:
            return
        bg, fg = {
            "primary": (t.primary_weak, t.primary),
            "success": (t.success_weak, t.success),
            "danger": (t.danger_weak, t.danger),
            "warning": (t.warning_weak, t.warning),
            "neutral": (t.surface_alt, t.text_muted),
        }[self.tone]
        self.setStyleSheet(
            f"background:{bg};color:{fg};border-radius:{t.radius}px;"
            f"padding:3px 9px;font-size:{t.font_size_small}px;font-weight:700;")

    def refresh(self, theme: "Theme | None" = None) -> None:
        if theme is not None:
            self.theme = theme
        self._restyle()


class StatPill(QWidget):
    """顶栏统计胶囊：``标签 + 数值``，可选语义色。"""

    def __init__(self, label: str, value: str = "0", tone: str = "neutral",
                 theme: "Theme | None" = None, parent: "QWidget | None" = None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.tone = tone
        self._label_text = label
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 4, 10, 4)
        lay.setSpacing(6)
        self.label = QLabel(label, self)
        self.value = QLabel(value, self)
        self.value.setStyleSheet("font-weight:700;")
        lay.addWidget(self.label)
        lay.addWidget(self.value)
        self.restyle()

    def set_value(self, text: str) -> None:
        self.value.setText(str(text))

    def set_tone(self, tone: str) -> None:
        self.tone = tone
        self.restyle()

    def restyle(self, theme: "Theme | None" = None) -> None:
        if theme is not None:
            self.theme = theme
        t = self.theme
        if t is None:
            return
        color = {"success": t.success, "danger": t.danger, "warning": t.warning,
                 "primary": t.primary, "neutral": t.text_muted}.get(self.tone, t.text_muted)
        self.setStyleSheet(
            f"StatPill{{background:{t.surface_alt};border-radius:{t.radius + 2}px;}}")
        self.label.setStyleSheet(f"color:{t.text_muted};font-size:{t.font_size_small}px;")
        self.value.setStyleSheet(f"color:{color};font-weight:700;font-size:{t.font_size + 1}px;")


class SegmentedControl(QWidget):
    """分段控件（范围 / 模式切换）：互斥按钮组，选中项高亮。"""

    changed = Signal(str)

    def __init__(self, options: Sequence[tuple[str, str]], theme: Theme,
                 parent: "QWidget | None" = None) -> None:
        super().__init__(parent)
        self.theme = theme
        self._options = list(options)
        self._buttons: dict[str, QPushButton] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(2)
        for key, label in self._options:
            btn = QPushButton(label, self)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            btn.clicked.connect(lambda _=False, k=key: self._on_click(k))
            self._group.addButton(btn)
            self._buttons[key] = btn
            lay.addWidget(btn)
        self.restyle()
        if self._options:
            self.set_current(self._options[0][0], emit=False)

    # ------------------------------------------------------------ 状态
    def current(self) -> str:
        for key, btn in self._buttons.items():
            if btn.isChecked():
                return key
        return self._options[0][0] if self._options else ""

    def set_current(self, key: str, emit: bool = False) -> None:
        btn = self._buttons.get(key)
        if btn is None:
            return
        for other in self._buttons.values():
            other.setChecked(other is btn)
        if emit:
            self.changed.emit(key)

    def _on_click(self, key: str) -> None:
        self.set_current(key)
        self.changed.emit(key)

    def restyle(self, theme: "Theme | None" = None) -> None:
        if theme is not None:
            self.theme = theme
        t = self.theme
        self.setStyleSheet(f"SegmentedControl{{background:{t.surface_alt};"
                           f"border-radius:{t.radius + 2}px;}}")
        for btn in self._buttons.values():
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; border: none;
                    border-radius: {t.radius}px; padding: 6px 14px;
                    color: {t.text_muted};
                }}
                QPushButton:hover {{ background: {t.surface_hover}; color: {t.text}; }}
                QPushButton:checked {{
                    background: {t.surface}; color: {t.primary}; font-weight: 700;
                }}
                QPushButton:focus {{ border: 1px solid {t.focus}; }}
            """)


# ---------------------------------------------------------------- 选项行
@dataclass
class OptionData:
    letter: str
    text: str
    state: str = "default"          # OPTION_STATES 之一
    mark: str = ""                  # "check" / "cross" / ""


class OptionRow(QWidget):
    """自绘选项行：整行可点、支持判定后着色、支持键盘焦点。

    ``pressed`` 发出被点击的字母；``state`` 由页面根据判定结果设置。
    """

    pressed = Signal(str)

    def __init__(self, letter: str, text: str, theme: Theme,
                 parent: "QWidget | None" = None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.letter = str(letter)
        self.text = str(text)
        self.state = "default"
        self.mark = ""
        self._hover = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.setAttribute(Qt.WA_Hover, True)
        self.setMinimumHeight(44)

    # ------------------------------------------------------------ 数据
    def set_state(self, state: str, mark: str = "") -> None:
        self.state = state if state in OPTION_STATES else "default"
        self.mark = mark
        self.setCursor(Qt.PointingHandCursor if self.state in ("default", "selected")
                       else Qt.ArrowCursor)
        self.update()

    def set_enabled_look(self, enabled: bool) -> None:
        self.setEnabled(bool(enabled))
        self.update()

    def is_selectable(self) -> bool:
        return self.state in ("default", "selected")

    # ------------------------------------------------------------ 尺寸
    def _text_width(self) -> int:
        pad = self.theme.space_lg * 2 + self.theme.space_lg + 26
        return max(40, self.width() - pad)

    def height_for_width(self, width: int) -> int:
        pad = self.theme.space_lg * 2 + self.theme.space_lg + 26
        inner = max(40, width - pad)
        lines = wrap_lines(self.text, self.theme.to_font(self.theme.font_size + 1), inner)
        line_h = QFontMetrics(self.theme.to_font(self.theme.font_size + 1)).height()
        return max(self.minimumHeight(), len(lines) * line_h + self.theme.space_md * 2)

    def sizeHint(self) -> QSize:
        return QSize(420, self.height_for_width(420))

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - Qt 接口
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt 接口
        return self.height_for_width(width)

    # ------------------------------------------------------------ 交互
    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and self.isEnabled() and self.is_selectable():
            self.pressed.emit(self.letter)
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter) and self.is_selectable():
            self.pressed.emit(self.letter)
            event.accept()
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------ 绘制
    def _colors(self) -> tuple[QColor, QColor, QColor, QColor, QColor]:
        """返回 (背景, 描边, 主文字, 徽标字色, 徽标底色)。"""
        t = self.theme
        bg = t.color("surface")
        border = t.color("border")
        text = t.color("text")
        badge_fg = t.color("text_muted")
        badge_bg = t.color("surface_alt")
        if self.state == "selected":
            bg = t.color("primary_weak")
            border = t.color("primary")
            text = t.color("text")
            badge_fg = t.color("text_inverse")
            badge_bg = t.color("primary")
        elif self.state == "correct":
            bg = t.color("success_weak")
            border = t.color("success")
            text = t.color("text")
            badge_fg = t.color("text_inverse")
            badge_bg = t.color("success")
        elif self.state == "wrong":
            bg = t.color("danger_weak")
            border = t.color("danger")
            text = t.color("text")
            badge_fg = t.color("text_inverse")
            badge_bg = t.color("danger")
        elif self.state == "dim":
            bg = t.color("surface")
            border = t.color("border")
            text = t.color("text_muted")
            badge_fg = t.color("text_faint")
            badge_bg = t.color("surface_alt")
        elif self.state == "disabled":
            bg = t.color("surface_alt")
            border = t.color("border")
            text = t.color("text_faint")
            badge_fg = t.color("text_faint")
            badge_bg = t.color("surface")
        if self._hover and self.is_selectable():
            border = t.color("primary")
            if self.state == "default":
                bg = t.color("surface_hover")
        return bg, border, text, badge_fg, badge_bg

    def paintEvent(self, event) -> None:  # noqa: N802
        t = self.theme
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        bg, border, text, badge_fg, badge_bg = self._colors()
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = t.radius + 2

        # 背景 + 描边
        painter.setPen(QPen(border, 2.0 if self.state in ("selected", "correct", "wrong") else 1.0))
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, radius, radius)

        # 焦点环
        if self.hasFocus() and self.isEnabled():
            painter.setPen(QPen(t.color("focus"), 1.4, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rect.adjusted(2, 2, -2, -2), radius - 2, radius - 2)

        # 字母徽标
        badge_size = 26
        badge = QRectF(rect.left() + t.space_lg, rect.center().y() - badge_size / 2,
                       badge_size, badge_size)
        painter.setPen(Qt.NoPen)
        painter.setBrush(badge_bg)
        painter.drawRoundedRect(badge, badge_size / 2, badge_size / 2)
        painter.setPen(QPen(badge_fg))
        painter.setFont(t.to_font(t.font_size_small, bold=True))
        painter.drawText(badge, Qt.AlignCenter, self.letter)

        # 正文（按宽度折行）
        text_rect = QRectF(badge.right() + t.space_lg, rect.top() + t.space_md,
                           rect.width() - (badge.right() - rect.left()) - t.space_lg * 2 - 22,
                           rect.height() - t.space_md * 2)
        painter.setPen(QPen(text))
        painter.setFont(t.to_font(t.font_size + 1))
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft | Qt.TextWordWrap, self.text)

        # 结果标记
        if self.mark in ("check", "cross") or self.state in ("correct", "wrong"):
            mark = self.mark or ("check" if self.state == "correct" else "cross")
            color = t.color("success") if mark == "check" else t.color("danger")
            center = QPointF(rect.right() - t.space_lg - 8, rect.center().y())
            painter.setPen(QPen(color, 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            if mark == "check":
                painter.drawLine(QPointF(center.x() - 6, center.y()),
                                 QPointF(center.x() - 1, center.y() + 5))
                painter.drawLine(QPointF(center.x() - 1, center.y() + 5),
                                 QPointF(center.x() + 7, center.y() - 6))
            else:
                painter.drawLine(QPointF(center.x() - 6, center.y() - 6),
                                 QPointF(center.x() + 6, center.y() + 6))
                painter.drawLine(QPointF(center.x() + 6, center.y() - 6),
                                 QPointF(center.x() - 6, center.y() + 6))
        painter.end()


# ---------------------------------------------------------------- 环形进度
class ProgressRing(QWidget):
    """环形进度（练习完成率 / 考试成绩）。居中显示百分比。"""

    def __init__(self, theme: Theme, value: float = 0.0, size: int = 116,
                 caption: str = "", parent: "QWidget | None" = None) -> None:
        super().__init__(parent)
        self.theme = theme
        self._value = max(0.0, min(1.0, float(value)))
        self._caption = caption
        self.setFixedSize(QSize(size, size))

    def set_value(self, value: float, caption: "str | None" = None) -> None:
        self._value = max(0.0, min(1.0, float(value)))
        if caption is not None:
            self._caption = caption
        self.update()

    def value(self) -> float:
        return self._value

    def refresh(self, theme: "Theme | None" = None) -> None:
        if theme is not None:
            self.theme = theme
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        t = self.theme
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        thickness = 10.0
        rect = QRectF(self.rect()).adjusted(thickness / 2 + 1, thickness / 2 + 1,
                                            -thickness / 2 - 1, -thickness / 2 - 1)
        painter.setPen(QPen(t.color("surface_alt"), thickness, Qt.SolidLine, Qt.RoundCap))
        painter.drawEllipse(rect)

        if self._value > 0:
            color = t.color("primary")
            if self._value >= 0.999:
                color = t.color("success")
            pen = QPen(color, thickness, Qt.SolidLine, Qt.RoundCap)
            painter.setPen(pen)
            span = int(-self._value * 360 * 16)
            painter.drawArc(rect, 90 * 16, span)

        painter.setPen(QPen(t.color("text")))
        painter.setFont(t.to_font(int(t.font_size * 1.7), bold=True))
        # 百分比放上半部、说明放下半部，避免小圆环里两行文字重叠
        painter.drawText(QRectF(rect.left(), rect.top() + rect.height() * 0.30,
                                rect.width(), rect.height() * 0.30),
                         Qt.AlignCenter, f"{self._value * 100:.0f}%")
        if self._caption:
            painter.setPen(QPen(t.color("text_muted")))
            painter.setFont(t.to_font(t.font_size_small))
            painter.drawText(QRectF(rect.left(), rect.top() + rect.height() * 0.62,
                                    rect.width(), 16),
                             Qt.AlignHCenter | Qt.AlignTop, self._caption)
        painter.end()


class ScoreHeader(QWidget):
    """成绩页头部：大号分数 + 满分 + 结论。"""

    def __init__(self, theme: Theme, parent: "QWidget | None" = None) -> None:
        super().__init__(parent)
        self.theme = theme
        self._score = "—"
        self._full = ""
        self._title = ""
        self._sub = ""
        # 头部包含：大号分数（≈44px）+ 标题行 + 说明行，留足高度避免裁切
        self.setMinimumHeight(136)

    def set_score(self, score: str, full: str = "", title: str = "", sub: str = "") -> None:
        self._score, self._full, self._title, self._sub = score, full, title, sub
        self.update()

    def refresh(self, theme: "Theme | None" = None) -> None:
        if theme is not None:
            self.theme = theme
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        t = self.theme
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        base = self.theme.to_font(t.font_size_hero + 4, bold=True)
        left = t.space_lg
        top = t.space_sm
        painter.setFont(base)
        painter.setPen(QPen(t.color("primary")))
        painter.drawText(QRectF(left, top, self.width() - left * 2, 52),
                         Qt.AlignLeft | Qt.AlignVCenter, self._score)
        if self._full:
            metrics = QFontMetrics(base)
            x = left + metrics.horizontalAdvance(self._score) + 8
            painter.setPen(QPen(t.color("text_muted")))
            painter.setFont(t.to_font(t.font_size + 2))
            painter.drawText(QRectF(x, top + 12, 240, 32),
                             Qt.AlignLeft | Qt.AlignVCenter, f"/ {self._full} 分")
        if self._title:
            painter.setPen(QPen(t.color("text")))
            painter.setFont(t.to_font(t.font_size + 2, bold=True))
            painter.drawText(QRectF(left, top + 62, self.width() - left * 2, 26),
                             Qt.AlignLeft | Qt.AlignVCenter, self._title)
        if self._sub:
            painter.setPen(QPen(t.color("text_muted")))
            painter.setFont(t.to_font(t.font_size_small))
            painter.drawText(QRectF(left, top + 92, self.width() - left * 2, 22),
                             Qt.AlignLeft | Qt.AlignVCenter, self._sub)
        painter.end()


class EmptyState(QWidget):
    """空态占位：一句主文案 + 一句建议。"""

    def __init__(self, theme: Theme, title: str = "", hint: str = "",
                 parent: "QWidget | None" = None) -> None:
        super().__init__(parent)
        self.theme = theme
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 24, 0, 24)
        lay.setSpacing(6)
        self.title = QLabel(title, self)
        self.title.setAlignment(Qt.AlignCenter)
        self.title.setStyleSheet(f"color:{theme.text};font-size:{theme.font_size_title}px;"
                                 "font-weight:700;")
        self.hint = QLabel(hint, self)
        self.hint.setAlignment(Qt.AlignCenter)
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet(f"color:{theme.text_muted};")
        lay.addWidget(self.title)
        lay.addWidget(self.hint)
        lay.addStretch(1)

    def set_text(self, title: str, hint: str = "") -> None:
        self.title.setText(title)
        self.hint.setText(hint)

    def refresh(self, theme: "Theme | None" = None) -> None:
        if theme is not None:
            self.theme = theme
        self.title.setStyleSheet(f"color:{self.theme.text};"
                                 f"font-size:{self.theme.font_size_title}px;font-weight:700;")
        self.hint.setStyleSheet(f"color:{self.theme.text_muted};")


def clear_layout(layout) -> None:
    """清空布局里的全部控件（界面"整段重绘"时使用）。

    必须先 ``hide()`` 再 ``setParent(None)``：Qt 中把**可见**的子控件摘成无父控件时，
    它会立刻变成一个顶层窗口并显示出来——表现为界面刷新时"闪一下小窗"
    （v1.3.0 实测缺陷：勾选「单选打乱选项」触发重绘，选项行就是这样闪一下）。
    """
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child = item.layout()
        if widget is not None:
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        elif child is not None:
            clear_layout(child)


def iter_children(widget: QWidget) -> Iterable[QWidget]:
    """递归遍历子控件（测试与主题刷新用）。"""
    for child in widget.findChildren(QWidget):
        yield child


def link_clicked(button: QPushButton, signal) -> None:
    """把按钮点击接到一个"无参数信号"的 emit 上。

    ``QPushButton.clicked`` 会带一个 ``checked: bool`` 实参，而页面上的
    ``next_requested`` / ``submit_requested`` 等是无参信号；直接
    ``clicked.connect(sig.emit)`` 在不同 PySide 版本上可能因实参不匹配而报错。
    统一用这个包装把实参吃掉，语义不变且跨版本稳定。
    """
    button.clicked.connect(lambda *_: signal.emit())
