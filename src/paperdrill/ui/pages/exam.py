# -*- coding: utf-8 -*-
"""刷题匠 PaperDrill —— 模拟考试页。

本文件只负责**考试配置视图**（FR-18.1 ～ 18.5）：蓝图、分值、轮长、覆盖校验、选卷。
作答视图在 ``exam_run.py``，成绩视图在 ``result.py``。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..controller import PaperDrillController, UiState
from ..models import PaperDetailModel
from ..theme import Theme
from ..widgets import Card, MutedLabel, SectionLabel, link_clicked

__all__ = ["ExamSetupPage"]


class ExamSetupPage(QWidget):
    """考试配置视图。"""

    start_requested = Signal(int)          # 参数：所选试卷下标
    history_requested = Signal()
    next_unused_requested = Signal()

    def __init__(self, controller: PaperDrillController, theme: Theme,
                 parent: "QWidget | None" = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.theme = theme
        self._syncing = False
        self._build()
        # 页面自己订阅控制器：这样它既能被 MainWindow 驱动，也能单独实例化使用/测试
        self.controller.paper_changed.connect(self._on_controller_changed)
        self.controller.state_changed.connect(self._on_controller_changed)
        self.refresh(self.controller.state)

    # ================================================================ 构建
    def _build(self) -> None:
        t = self.theme
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(t.space_md)

        # ---- ① 试卷蓝图
        blueprint = Card(t, title="① 试卷蓝图", hint="每张试卷的题型数量")
        grid = QGridLayout()
        grid.setHorizontalSpacing(t.space_lg)
        grid.setVerticalSpacing(t.space_sm)
        self.single_spin = self._make_count_spin(t, "单选题 / 卷", grid, 0, 0)
        self.multiple_spin = self._make_count_spin(t, "多选题 / 卷", grid, 0, 1)
        self.judge_spin = self._make_count_spin(t, "判断题 / 卷", grid, 0, 2)
        self.total_label = QLabel("")
        self.total_label.setStyleSheet(f"color:{t.primary};font-weight:700;")
        grid.addWidget(self.total_label, 1, 0, 1, 3)

        self.score_single = self._make_score_spin(t, "单选分值", grid, 2, 0)
        self.score_multiple = self._make_score_spin(t, "多选分值", grid, 2, 1)
        self.score_judge = self._make_score_spin(t, "判断分值", grid, 2, 2)

        row3 = QHBoxLayout()
        row3.setSpacing(t.space_sm)
        row3.addWidget(SectionLabel("一轮张数", t))
        self.auto_radio = QRadioButton("自动（覆盖题库所需）")
        self.manual_radio = QRadioButton("手动")
        self.auto_radio.setChecked(True)
        row3.addWidget(self.auto_radio)
        row3.addWidget(self.manual_radio)
        self.round_spin = QSpinBox()
        self.round_spin.setRange(1, 999)
        self.round_spin.setFixedWidth(76)
        row3.addWidget(self.round_spin)
        row3.addStretch(1)
        self.generate_button = QPushButton("生成一轮试卷（F5）")
        self.generate_button.setProperty("kind", "primary")
        self.generate_button.setToolTip("按当前蓝图生成一轮覆盖题库的试卷（快捷键 F5）")
        row3.addWidget(self.generate_button)
        grid.addLayout(row3, 3, 0, 1, 3)

        self.plan_hint = MutedLabel("导入题库后自动计算覆盖所需张数", t)
        grid.addWidget(self.plan_hint, 4, 0, 1, 3)
        blueprint.add_layout(grid)
        root.addWidget(blueprint)

        # ---- ② 覆盖校验
        cover = Card(t, title="② 覆盖校验")
        self.cover_label = MutedLabel("尚未生成试卷", t)
        self.cover_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        cover.add(self.cover_label)
        root.addWidget(cover)

        # ---- ③ 选择试卷
        picker = Card(t, title="③ 选择试卷开始模拟考试")
        pick_row = QHBoxLayout()
        pick_row.setSpacing(t.space_sm)
        self.paper_combo = QComboBox()
        self.paper_combo.setMinimumWidth(280)
        pick_row.addWidget(self.paper_combo, 1)
        self.start_button = QPushButton("开始模拟考试")
        self.start_button.setProperty("kind", "primary")
        pick_row.addWidget(self.start_button)
        self.next_unused_button = QPushButton("自动取下一张未考卷")
        pick_row.addWidget(self.next_unused_button)
        self.history_button = QPushButton("历史成绩…")
        pick_row.addWidget(self.history_button)
        picker.add_layout(pick_row)
        root.addWidget(picker)

        # ---- ④ 本轮试卷明细
        detail = Card(t, title="本轮试卷明细")
        self.paper_model = PaperDetailModel(t)
        self.paper_table = QTableView()
        self.paper_table.setModel(self.paper_model)
        self.paper_table.setAlternatingRowColors(True)
        self.paper_table.verticalHeader().setVisible(False)
        self.paper_table.setSelectionBehavior(QTableView.SelectRows)
        self.paper_table.setSelectionMode(QTableView.SingleSelection)
        self.paper_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.paper_table.setMinimumHeight(150)
        detail.add(self.paper_table, 1)
        root.addWidget(detail, 1)

        # ---- 信号
        for spin in (self.single_spin, self.multiple_spin, self.judge_spin):
            spin.valueChanged.connect(self._on_blueprint_changed)
        for spin in (self.score_single, self.score_multiple, self.score_judge):
            spin.valueChanged.connect(self._on_score_changed)
        self.auto_radio.toggled.connect(self._on_round_mode_changed)
        self.round_spin.valueChanged.connect(self._on_round_length_changed)
        self.generate_button.clicked.connect(lambda *_: self.controller.generate_round())
        self.start_button.clicked.connect(lambda *_: self._emit_start())
        link_clicked(self.next_unused_button, self.next_unused_requested)
        link_clicked(self.history_button, self.history_requested)
        self.paper_table.selectionModel().selectionChanged.connect(self._on_row_selected)

    # ---------------------------------------------------------------- 控制器订阅
    def _on_controller_changed(self, *_args) -> None:
        """控制器状态变化后自动重绘（页面可独立于 MainWindow 使用）。"""
        self.refresh(self.controller.state)

    # ---------------------------------------------------------------- 构造小工具
    def _make_count_spin(self, t: Theme, label: str, grid: QGridLayout,
                         row: int, col: int) -> QSpinBox:
        box = QVBoxLayout()
        box.setSpacing(2)
        cap = SectionLabel(label, t)
        spin = QSpinBox()
        spin.setRange(0, 999)
        spin.setFixedWidth(96)
        box.addWidget(cap)
        box.addWidget(spin)
        holder = QWidget()
        holder.setLayout(box)
        grid.addWidget(holder, row, col)
        return spin

    def _make_score_spin(self, t: Theme, label: str, grid: QGridLayout,
                         row: int, col: int) -> QDoubleSpinBox:
        box = QVBoxLayout()
        box.setSpacing(2)
        cap = SectionLabel(label, t)
        spin = QDoubleSpinBox()
        spin.setRange(0.0, 100.0)
        spin.setSingleStep(0.5)
        spin.setDecimals(1)
        spin.setFixedWidth(96)
        box.addWidget(cap)
        box.addWidget(spin)
        holder = QWidget()
        holder.setLayout(box)
        grid.addWidget(holder, row, col)
        return spin

    # ================================================================ 交互
    def _on_blueprint_changed(self, *_args) -> None:
        if self._syncing:
            return
        self.controller.set_blueprint(self.single_spin.value(),
                                      self.multiple_spin.value(),
                                      self.judge_spin.value())
        self.refresh(self.controller.state)

    def _on_score_changed(self, *_args) -> None:
        if self._syncing:
            return
        self.controller.set_scores(self.score_single.value(),
                                   self.score_multiple.value(),
                                   self.score_judge.value())
        self.refresh(self.controller.state)

    def _on_round_mode_changed(self, *_args) -> None:
        if self._syncing:
            return
        auto = self.auto_radio.isChecked()
        self.round_spin.setEnabled(not auto)
        self.controller.set_round_length(self.round_spin.value(), auto)
        self.refresh(self.controller.state)

    def _on_round_length_changed(self, value: int) -> None:
        if self._syncing or self.auto_radio.isChecked():
            return
        self.controller.set_round_length(int(value), False)

    def _emit_start(self) -> None:
        self.start_requested.emit(max(0, self.paper_combo.currentIndex()))

    def _on_row_selected(self, *_args) -> None:
        if self._syncing:
            return
        rows = self.paper_table.selectionModel().selectedRows()
        if rows:
            self._syncing = True
            try:
                self.paper_combo.setCurrentIndex(rows[0].row())
            finally:
                self._syncing = False

    def selected_index(self) -> int:
        return max(0, self.paper_combo.currentIndex())

    # ================================================================ 渲染
    def refresh(self, state: UiState) -> None:
        self._syncing = True
        try:
            bp = state.blueprint
            self.single_spin.setValue(int(bp.single))
            self.multiple_spin.setValue(int(bp.multiple))
            self.judge_spin.setValue(int(bp.judge))
            scores = state.scores
            self.score_single.setValue(float(scores.get("single", 1.0)))
            self.score_multiple.setValue(float(scores.get("multiple", 2.0)))
            self.score_judge.setValue(float(scores.get("judge", 1.0)))
            self.auto_radio.setChecked(bool(state.round_auto))
            self.manual_radio.setChecked(not state.round_auto)
            self.round_spin.setEnabled(not state.round_auto)
            manual = int(state.round_length or self.controller.min_round_length())
            if self.round_spin.value() != max(1, manual):
                self.round_spin.setValue(max(1, manual))
        finally:
            self._syncing = False

        self.total_label.setText(
            f"→ 每卷合计 {self.controller.blueprint_total()} 题，"
            f"满分 {self.controller.blueprint_full_score():g} 分")
        self.plan_hint.setText(self.controller.plan_hint())
        self.cover_label.setText(self.controller.coverage_text())

        rnd = state.round
        self.paper_model.set_rows(rnd.papers if rnd is not None else [])
        labels = self.controller.paper_labels()
        current = self.paper_combo.currentIndex()
        self.paper_combo.blockSignals(True)
        self.paper_combo.clear()
        self.paper_combo.addItems(labels)
        if labels:
            self.paper_combo.setCurrentIndex(min(max(0, current), len(labels) - 1))
        self.paper_combo.blockSignals(False)
        self.start_button.setEnabled(bool(labels))
        self.next_unused_button.setEnabled(bool(labels))
        self.generate_button.setEnabled(bool(self.controller.active_questions()))
        if rnd is not None and rnd.papers:
            self.paper_table.selectRow(self.selected_index())

    def apply_theme(self, theme: Theme) -> None:
        self.theme = theme
        self.paper_model.set_theme(theme)
        for label in (self.total_label,):
            label.setStyleSheet(f"color:{theme.primary};font-weight:700;")
        self.refresh(self.controller.state)

    # ---------------------------------------------------------------- 测试辅助
    def set_counts(self, single: int, multiple: int, judge: int) -> None:
        """以用户操作的方式设置蓝图（会触发控制器）。"""
        self.single_spin.setValue(int(single))
        self.multiple_spin.setValue(int(multiple))
        self.judge_spin.setValue(int(judge))
