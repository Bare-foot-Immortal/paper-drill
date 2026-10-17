# -*- coding: utf-8 -*-
"""刷题匠 PaperDrill —— 模拟考试作答视图（FR-18.6 ～ 18.8、18.11）。

要点
----
* 左侧题号网格：当前题高亮、已答题变色，点击跳题；
* 作答期间**不出现任何对错信息**（FR-18.7），因此这里没有正确/错误着色；
* 交卷后所有作答入口禁用（FR-18.11）。
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...models import QType
from ..controller import PaperDrillController, UiState
from ..theme import Theme
from ..widgets import Card, OptionRow, clear_layout, link_clicked

__all__ = ["NumberGrid", "ExamRunPage"]


class NumberGrid(QWidget):
    """题号导航网格：按宽度自动换列，点击发出题号。"""

    go_requested = Signal(int)

    CELL = 38
    GAP = 5

    def __init__(self, theme: Theme, parent: "QWidget | None" = None) -> None:
        super().__init__(parent)
        self.theme = theme
        self.total = 0
        self.current = 0
        self.answered: set[int] = set()
        self._buttons: list[QPushButton] = []
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(self.GAP)
        self._columns = 1
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

    # ------------------------------------------------------------ 构建
    def build(self, total: int, columns: int = 5) -> None:
        clear_layout(self._grid)
        self._buttons = []
        self.total = max(0, int(total))
        self._columns = max(1, int(columns))
        for i in range(self.total):
            btn = QPushButton(str(i + 1), self)
            btn.setFixedSize(QSize(self.CELL, self.CELL))
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, k=i: self.go_requested.emit(k))
            self._grid.addWidget(btn, i // self._columns, i % self._columns)
            self._buttons.append(btn)
        self._restyle()

    def update_state(self, current: int, answered: "set[int]") -> None:
        self.current = max(0, int(current))
        self.answered = set(answered)
        self._restyle()

    def set_columns(self, columns: int) -> None:
        columns = max(1, int(columns))
        if columns == self._columns:
            return
        self._columns = columns
        for i, btn in enumerate(self._buttons):
            self._grid.addWidget(btn, i // columns, i % columns)

    # ------------------------------------------------------------ 绘制
    def _restyle(self, theme: "Theme | None" = None) -> None:
        if theme is not None:
            self.theme = theme
        t = self.theme
        base = (f"padding:0px;font-size:{t.font_size_small}px;"
                f"border-radius:{t.radius}px;")
        for i, btn in enumerate(self._buttons):
            if i == self.current:
                css = (f"background:{t.primary};color:{t.text_inverse};"
                       f"border:1px solid {t.primary};font-weight:700;" + base)
            elif i in self.answered:
                css = (f"background:{t.primary_weak};color:{t.primary};"
                       f"border:1px solid {t.primary};" + base)
            else:
                css = (f"background:{t.surface_alt};color:{t.text_muted};"
                       f"border:1px solid {t.border};" + base)
            btn.setStyleSheet(f"QPushButton{{{css}}} QPushButton:hover{{border-color:{t.primary};}}")
        self.updateGeometry()

    def refresh(self, theme: "Theme | None" = None) -> None:
        self._restyle(theme)

    def sizeHint(self) -> QSize:
        rows = max(1, (self.total + self._columns - 1) // self._columns)
        width = self._columns * self.CELL + (self._columns - 1) * self.GAP
        height = rows * self.CELL + (rows - 1) * self.GAP
        return QSize(width, height)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.CELL, self.CELL)


class ExamRunPage(QWidget):
    """考试作答视图。"""

    submit_requested = Signal()
    exit_requested = Signal()

    def __init__(self, controller: PaperDrillController, theme: Theme,
                 parent: "QWidget | None" = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.theme = theme
        self.option_rows: list[OptionRow] = []
        self._build()
        self.controller.exam_changed.connect(self._on_controller_changed)
        self.controller.state_changed.connect(self._on_controller_changed)
        self.refresh(self.controller.state)

    def _on_controller_changed(self, *_args) -> None:
        self.refresh(self.controller.state)

    # ================================================================ 构建
    def _build(self) -> None:
        t = self.theme
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(t.space_md)

        # ---- 左侧题号面板
        nav_card = Card(t, title="题号", hint="蓝=已答")
        self.number_grid = NumberGrid(t)
        self.number_grid.go_requested.connect(self.controller.exam_goto)
        nav_card.add(self.number_grid)
        nav_card.add_layout(QHBoxLayout())
        legend = QLabel("● 当前题　● 已答　○ 未答")
        legend.setObjectName("Faint")
        legend.setWordWrap(True)
        nav_card.add(legend)
        nav_card.setFixedWidth(238)
        root.addWidget(nav_card)

        # ---- 右侧作答区
        right = QVBoxLayout()
        right.setSpacing(t.space_sm)
        root.addLayout(right, 1)

        head = QHBoxLayout()
        self.title_label = QLabel("")
        self.title_label.setObjectName("CardTitle")
        self.count_label = QLabel("已答 0 / 0")
        self.count_label.setObjectName("Muted")
        head.addWidget(self.title_label)
        head.addStretch(1)
        head.addWidget(self.count_label)
        right.addLayout(head)

        hint = QLabel("作答期间不显示对错；1~8 选择选项，Enter 下一题，← → 翻题，F9 交卷")
        hint.setObjectName("Faint")
        right.addWidget(hint)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        holder = QWidget()
        holder_lay = QVBoxLayout(holder)
        holder_lay.setContentsMargins(0, 0, 0, 0)
        self.card = Card(t)
        self.pos_label = QLabel("")
        self.pos_label.setObjectName("CardTitle")
        self.card.add(self.pos_label)
        self.stem_label = QLabel("")
        self.stem_label.setObjectName("StemText")
        self.stem_label.setWordWrap(True)
        self.stem_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.card.add(self.stem_label)
        self.options_box = QVBoxLayout()
        self.options_box.setSpacing(t.space_sm)
        self.card.add_layout(self.options_box)
        self.type_label = QLabel("")
        self.type_label.setObjectName("Faint")
        self.card.add(self.type_label)
        holder_lay.addWidget(self.card)
        holder_lay.addStretch(1)
        self.scroll.setWidget(holder)
        right.addWidget(self.scroll, 1)

        actions = QHBoxLayout()
        actions.setSpacing(t.space_sm)
        self.prev_button = QPushButton("◀ 上一题")
        self.next_button = QPushButton("下一题 ▶")
        self.clear_button = QPushButton("清除本题作答")
        self.submit_button = QPushButton("交卷（F9）")
        self.submit_button.setProperty("kind", "primary")
        self.submit_button.setToolTip("交卷并评分；有未答题时会二次确认（快捷键 F9）")
        self.exit_button = QPushButton("返回配置")
        self.exit_button.setProperty("kind", "ghost")
        actions.addWidget(self.prev_button)
        actions.addWidget(self.next_button)
        actions.addWidget(self.clear_button)
        actions.addStretch(1)
        actions.addWidget(self.exit_button)
        actions.addWidget(self.submit_button)
        right.addLayout(actions)

        # ---- 信号
        self.prev_button.clicked.connect(
            lambda *_: self.controller.exam_goto(self.controller.state.exam_index - 1))
        self.next_button.clicked.connect(
            lambda *_: self.controller.exam_goto(self.controller.state.exam_index + 1))
        self.clear_button.clicked.connect(lambda *_: self.controller.exam_clear())
        link_clicked(self.submit_button, self.submit_requested)
        link_clicked(self.exit_button, self.exit_requested)

    # ================================================================ 交互
    def press_option(self, letter: str) -> None:
        """作答：多选切换、单选/判断直接设置（两种都只是记录，不判定）。"""
        item = self.controller.exam_item(self.controller.state.exam_index)
        if item is None:
            return
        if item.qtype is QType.MULTIPLE:
            self.controller.exam_toggle(letter)
        else:
            self.controller.exam_set(letter)

    def press_submit(self) -> None:
        self.submit_requested.emit()

    # ================================================================ 渲染
    def refresh(self, state: UiState) -> None:
        exam = state.exam
        item = self.controller.exam_item(state.exam_index)
        readonly = state.exam_readonly

        if exam is None or item is None:
            self.title_label.setText("尚无进行中的考试")
            self.count_label.setText("")
            self.number_grid.build(0)
            clear_layout(self.options_box)
            self.option_rows = []
            self.stem_label.setText("请在「模拟考试」配置页生成一轮试卷并开始考试。")
            self.pos_label.setText("")
            self.type_label.setText("")
            for btn in (self.prev_button, self.next_button, self.clear_button, self.submit_button):
                btn.setEnabled(False)
            return

        paper = exam.paper
        self.title_label.setText(f"{paper.label}卷　共 {exam.total} 题　满分 {exam.full_score:g} 分")
        self.count_label.setText(f"已答 {exam.answered_count} / {exam.total}")
        if self.number_grid.total != exam.total:      # 题量没变就不重建按钮
            self.number_grid.build(exam.total, columns=5)
        self.number_grid.update_state(
            state.exam_index,
            {i for i in range(exam.total) if exam.answered(i)})

        self.pos_label.setText(f"第 {state.exam_index + 1} / {exam.total} 题")
        self.stem_label.setText(f"{state.exam_index + 1}. {(item.stem or '').strip()}")
        if item.qtype is QType.MULTIPLE:
            self.type_label.setText("多选题，选好后可直接下一题")
        else:
            self.type_label.setText(item.qtype.value)

        clear_layout(self.options_box)
        self.option_rows = []
        selection = self.controller.exam_selection()
        for letter, text in item.options():
            option = OptionRow(letter, text, self.theme)
            option.pressed.connect(self.press_option)
            self.options_box.addWidget(option)
            self.option_rows.append(option)
            if readonly:
                option.set_state("disabled")
                option.set_enabled_look(False)
            elif letter in selection:
                option.set_state("selected")
            else:
                option.set_state("default")
        if readonly:
            for option in self.option_rows:
                option.setToolTip("已交卷，卷面只读")

        self.prev_button.setEnabled(state.exam_index > 0)
        self.next_button.setEnabled(state.exam_index < exam.total - 1)
        self.clear_button.setEnabled(not readonly)
        self.submit_button.setEnabled(not readonly)
        self.exit_button.setEnabled(True)

    def apply_theme(self, theme: Theme) -> None:
        self.theme = theme
        for row in self.option_rows:
            row.theme = theme
            row.update()
        self.number_grid.refresh(theme)
        self.refresh(self.controller.state)
