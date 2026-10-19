# -*- coding: utf-8 -*-
"""刷题匠 PaperDrill —— 交卷成绩视图（FR-18.9、18.10）。"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSplitter,
    QTableView,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..controller import PaperDrillController, UiState
from ..models import ExamDetailModel
from ..theme import Theme
from ..widgets import Card, ScoreHeader, StatPill, link_clicked

__all__ = ["ExamResultPage"]


class ExamResultPage(QWidget):
    """成绩页：总分 + 题型得分 + 逐题明细 + 解析。"""

    back_requested = Signal()
    share_requested = Signal()          # 预留：以后导出成绩单

    def __init__(self, controller: PaperDrillController, theme: Theme,
                 parent: "QWidget | None" = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.theme = theme
        self._last_result = None
        self._last_row = -1
        self._last_analysis = ""
        self._build()
        self.controller.state_changed.connect(self._on_controller_changed)
        self.refresh(self.controller.state)

    def _on_controller_changed(self, *_args) -> None:
        self.refresh(self.controller.state)

    # ================================================================ 构建
    def _build(self) -> None:
        t = self.theme
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(t.space_md)

        head = Card(t)
        self.score_header = ScoreHeader(t)
        head.add(self.score_header)
        pills = QHBoxLayout()
        pills.setSpacing(t.space_sm)
        self.pill_correct = StatPill("正确", "0", "success", t)
        self.pill_wrong = StatPill("错误", "0", "danger", t)
        self.pill_unanswered = StatPill("未答", "0", "warning", t)
        self.pill_rate = StatPill("正确率", "0%", "primary", t)
        for pill in (self.pill_correct, self.pill_wrong, self.pill_unanswered, self.pill_rate):
            pills.addWidget(pill)
        pills.addStretch(1)
        self.back_button = QPushButton("返回试卷配置")
        link_clicked(self.back_button, self.back_requested)
        pills.addWidget(self.back_button)
        head.add_layout(pills)
        root.addWidget(head)

        # ---- 各题型得分
        per = Card(t, title="各题型得分")
        self.per_row = QHBoxLayout()
        self.per_row.setSpacing(t.space_md)
        per.add_layout(self.per_row)
        self.per_labels: dict[str, QLabel] = {}
        for key, name in (("single", "单选"), ("multiple", "多选"), ("judge", "判断")):
            box = QVBoxLayout()
            box.setSpacing(2)
            title = QLabel(name)
            title.setObjectName("SectionLabel")
            value = QLabel("—")
            value.setStyleSheet("font-weight:700;")
            box.addWidget(title)
            box.addWidget(value)
            holder = QWidget()
            holder.setLayout(box)
            self.per_row.addWidget(holder)
            self.per_labels[key] = value
        self.per_row.addStretch(1)
        root.addWidget(per)

        # ---- 逐题明细 + 解析
        split = QSplitter(Qt.Horizontal)
        left = Card(t, title="逐题明细", hint="点击一行查看题干与解析")
        self.detail_model = ExamDetailModel(t)
        self.detail_table = QTableView()
        self.detail_table.setModel(self.detail_model)
        self.detail_table.setAlternatingRowColors(True)
        self.detail_table.verticalHeader().setVisible(False)
        self.detail_table.setSelectionBehavior(QTableView.SelectRows)
        self.detail_table.setSelectionMode(QTableView.SingleSelection)
        header = self.detail_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        self.detail_table.setMinimumHeight(220)
        left.add(self.detail_table, 1)
        split.addWidget(left)

        right = Card(t, title="题目与解析")
        self.analysis_box = QTextBrowser()
        self.analysis_box.setOpenExternalLinks(False)
        self.analysis_box.setPlaceholderText("（点击左侧任意一行查看该题的题干与解析）")
        right.add(self.analysis_box, 1)
        split.addWidget(right)
        split.setSizes([520, 380])
        root.addWidget(split, 1)

        self.detail_table.selectionModel().selectionChanged.connect(self._on_select)

    # ================================================================ 交互
    def _on_select(self, *_args) -> None:
        rows = self.detail_table.selectionModel().selectedRows()
        if not rows:
            return
        detail = self.detail_model.detail_at(rows[0].row())
        if detail:
            self._last_row = rows[0].row()
            self._last_analysis = self._analysis_of(detail)
            self.analysis_box.setPlainText(self._last_analysis)

    @staticmethod
    def _analysis_of(detail: dict) -> str:
        answer = str(detail.get("answer", "") or "")
        answer_text = str(detail.get("answer_text", "") or "")
        # answer_text 形如 "A. 完成专项方案审批…"，已经包含字母，避免出现 "A A. …"
        if answer_text and not answer_text.startswith(answer):
            answer_line = f"正确答案：{answer}　{answer_text}" if answer else f"正确答案：{answer_text}"
        else:
            answer_line = f"正确答案：{answer_text or answer}"
        lines = [f"{detail.get('number')}. {detail.get('stem', '')}", "",
                 f"题型：{detail.get('qtype', '')}",
                 f"你的作答：{detail.get('selected', '')}",
                 answer_line,
                 f"结果：{'正确' if detail.get('correct') else ('未作答' if detail.get('unanswered') else '错误')}"]
        if detail.get("analysis"):
            lines += ["", f"解析：{detail['analysis']}"]
        return "\n".join(lines)

    def show_detail(self, row: int) -> None:
        """测试辅助：直接查看第 row 行明细。"""
        if 0 <= row < self.detail_model.rowCount():
            self.detail_table.selectRow(row)
            self._on_select()

    # ================================================================ 渲染
    def refresh(self, state: UiState) -> None:
        result = state.exam_result
        if result is None:
            self.score_header.set_score("—", "", "尚无成绩", "交卷后这里显示得分与逐题解析")
            self.detail_model.set_rows([])
            self.analysis_box.clear()
            for pill in (self.pill_correct, self.pill_wrong,
                         self.pill_unanswered, self.pill_rate):
                pill.set_value("—")
            for label in self.per_labels.values():
                label.setText("—")
            return

        self.score_header.set_score(
            f"{result.score:g}", f"{result.full_score:g}",
            f"{result.paper_label}卷　正确率 {result.accuracy * 100:.1f}%",
            f"共 {result.total} 题　交卷时间 {result.ts}")
        self.pill_correct.set_value(str(result.correct))
        self.pill_wrong.set_value(str(result.wrong))
        self.pill_unanswered.set_value(str(result.unanswered))
        self.pill_rate.set_value(f"{result.accuracy * 100:.1f}%")

        for key, label in self.per_labels.items():
            data = result.per_type.get(key)
            if not data:
                label.setText("—")
                continue
            label.setText(f"{data['correct']}/{data['total']} 题　"
                          f"{data['score']:g}/{data['full']:g} 分")

        if result is not self._last_result:
            # 只有成绩对象本身变了才重建明细；否则保留选中行与右侧解析（审计 P3-7）
            self._last_result = result
            self._last_row = -1
            self._last_analysis = ""
            self.detail_model.set_rows(result.details)
            self.analysis_box.setPlainText("（点击左侧任意一行查看该题的题干与解析）")
        elif 0 <= self._last_row < self.detail_model.rowCount():
            self.detail_table.selectRow(self._last_row)
            self.analysis_box.setPlainText(self._last_analysis)

    def apply_theme(self, theme: Theme) -> None:
        self.theme = theme
        self.detail_model.set_theme(theme)
        self.score_header.refresh(theme)
        for pill in (self.pill_correct, self.pill_wrong,
                     self.pill_unanswered, self.pill_rate):
            pill.restyle(theme)
        self.refresh(self.controller.state)
