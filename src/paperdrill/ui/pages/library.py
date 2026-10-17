# -*- coding: utf-8 -*-
"""刷题匠 PaperDrill —— 题库资料页（FR-19.1 ～ 19.3）。

展示当前题库的完整信息（路径、构成、删减、统计、导入问题）与最近使用的题库列表。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..controller import PaperDrillController, UiState
from ..models import LibraryModel
from ..theme import Theme
from ..widgets import Card, MutedLabel, SectionLabel, link_clicked

__all__ = ["LibraryPage"]


class LibraryPage(QWidget):
    """题库资料页。"""

    bank_switch_requested = Signal(str)        # 参数：题库路径
    import_requested = Signal()
    scan_requested = Signal()
    filter_requested = Signal()                # 题库删减…
    exclude_requested = Signal(str)            # 移除记录
    exclude_with_progress_requested = Signal(str)  # 移除记录并清空进度

    def __init__(self, controller: PaperDrillController, theme: Theme,
                 parent: "QWidget | None" = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.theme = theme
        self._build()
        self.controller.state_changed.connect(self._on_controller_changed)
        self.controller.library_changed.connect(self._on_controller_changed)
        self.refresh(self.controller.state)

    # ================================================================ 构建
    def _build(self) -> None:
        t = self.theme
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(t.space_md)

        # ---- 当前题库
        current = Card(t, title="当前题库")
        self.bank_name_label = QLabel("（尚未导入题库）")
        self.bank_name_label.setStyleSheet(f"font-size:{t.font_size_title}px;font-weight:700;")
        current.add(self.bank_name_label)
        self.bank_path_label = QLabel("")
        self.bank_path_label.setObjectName("Muted")
        self.bank_path_label.setWordWrap(True)
        self.bank_path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        current.add(self.bank_path_label)

        grid = QGridLayout()
        grid.setHorizontalSpacing(t.space_lg)
        grid.setVerticalSpacing(t.space_xs)
        self.fact_labels: dict[str, QLabel] = {}
        for col, (key, title) in enumerate((("total", "题数"), ("types", "构成"),
                                            ("done", "已练"), ("accuracy", "正确率"),
                                            ("wrong_book", "错题"), ("excluded", "已删减"))):
            cap = SectionLabel(title, t)
            value = QLabel("—")
            value.setStyleSheet("font-weight:700;")
            grid.addWidget(cap, 0, col)
            grid.addWidget(value, 1, col)
            self.fact_labels[key] = value
        current.add_layout(grid)

        self.issues_label = MutedLabel("", t)
        self.issues_label.hide()
        current.add(self.issues_label)

        actions = QHBoxLayout()
        actions.setSpacing(t.space_sm)
        self.import_button = QPushButton("导入题库…")
        self.import_button.setProperty("kind", "primary")
        self.import_button.setToolTip("选择题库文件导入（快捷键 Ctrl+O）")
        self.scan_button = QPushButton("扫描文件夹…")
        self.scan_button.setToolTip("递归找出某目录下所有题库文件并加入最近列表")
        self.filter_button = QPushButton("题库删减…")
        self.filter_button.setToolTip("把不想练的题目移出练习与组卷（不改题库原文件）")
        self.reload_button = QPushButton("重新载入")
        self.reload_button.setToolTip("重新解析当前题库文件（题库被更新后使用）")
        for btn in (self.import_button, self.scan_button, self.filter_button, self.reload_button):
            actions.addWidget(btn)
        actions.addStretch(1)
        current.add_layout(actions)
        root.addWidget(current)

        # ---- 最近题库
        recent = Card(t, title="最近使用的题库", hint="双击载入")
        self.library_model = LibraryModel(t)
        self.library_table = QTableView()
        self.library_table.setModel(self.library_model)
        self.library_table.setAlternatingRowColors(True)
        self.library_table.verticalHeader().setVisible(False)
        self.library_table.setSelectionBehavior(QTableView.SelectRows)
        self.library_table.setSelectionMode(QTableView.SingleSelection)
        header = self.library_table.horizontalHeader()
        # 题库名/题数/最后使用给固定宽度（ResizeToContents 会把中文名挤成"样例题…"），路径列拉伸
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Interactive)
        self.library_table.setColumnWidth(0, 220)
        self.library_table.setColumnWidth(1, 80)
        self.library_table.setColumnWidth(3, 180)
        self.library_table.setMinimumHeight(180)
        self.library_table.doubleClicked.connect(self._on_double_clicked)
        recent.add(self.library_table, 1)

        # 选中状态文字反馈：即使主题对比度不足，也能确认"选的是哪一条"
        self.selection_label = MutedLabel("", t)
        self.selection_label.setObjectName("Muted")
        recent.add(self.selection_label)

        btns = QHBoxLayout()
        btns.setSpacing(t.space_sm)
        self.load_button = QPushButton("载入选中题库")
        self.forget_button = QPushButton("移除记录")
        self.forget_reset_button = QPushButton("移除记录并清空进度")
        self.forget_reset_button.setProperty("kind", "danger")
        btns.addWidget(self.load_button)
        btns.addWidget(self.forget_button)
        btns.addWidget(self.forget_reset_button)
        btns.addStretch(1)
        recent.add_layout(btns)
        root.addWidget(recent, 1)

        # ---- 信号
        link_clicked(self.import_button, self.import_requested)
        link_clicked(self.scan_button, self.scan_requested)
        link_clicked(self.filter_button, self.filter_requested)
        self.reload_button.clicked.connect(lambda *_: self.controller.reload_bank())
        self.load_button.clicked.connect(lambda *_: self.load_selected_entry())
        self.forget_button.clicked.connect(lambda *_: self._forget_selected())
        self.forget_reset_button.clicked.connect(lambda *_: self._forget_selected_with_progress())
        self.library_table.selectionModel().selectionChanged.connect(
            lambda *_: self._update_selection_label())

    def _on_controller_changed(self, *_args) -> None:
        self.refresh(self.controller.state)

    # ================================================================ 交互
    def selected_row_object(self) -> "dict | None":
        rows = self.library_table.selectionModel().selectedRows()
        if not rows:
            return None
        return self.library_model.row_object(rows[0].row())

    def selected_path(self) -> str:
        obj = self.selected_row_object()
        return str(obj.get("path", "")) if obj else ""

    def _update_selection_label(self) -> None:
        """把"当前选中了哪条"显示出来，并同步按钮可用状态。"""
        obj = self.selected_row_object()
        if obj:
            name = obj.get("name") or Path(str(obj.get("path", ""))).stem
            total = obj.get("total")
            count = f"（{total} 题）" if total else ""
            self.selection_label.setText(f"已选中：{name}{count}　双击即载入")
        else:
            self.selection_label.setText("单击一行选中；双击直接载入")
        has_selection = obj is not None
        for button in (self.load_button, self.forget_button, self.forget_reset_button):
            if button.isEnabled() != has_selection:
                button.setEnabled(has_selection)

    def load_selected_entry(self) -> None:
        path = self.selected_path()
        if path:
            self.bank_switch_requested.emit(path)

    def _on_double_clicked(self, *_args) -> None:
        """双击一行即载入（只发出信号，由 MainWindow 负责真正载入）。"""
        self.load_selected_entry()

    def _forget_selected(self) -> None:
        path = self.selected_path()
        if path:
            self.exclude_requested.emit(path)

    def _forget_selected_with_progress(self) -> None:
        path = self.selected_path()
        if path:
            self.exclude_with_progress_requested.emit(path)

    def choose_file(self) -> str:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择题库文件", "",
            "题库文件 (*.xlsx *.xlsm *.csv *.txt *.json *.docx *.docm *.pdf);;所有文件 (*.*)")
        return path

    # ================================================================ 渲染
    def refresh(self, state: UiState) -> None:
        summary = self.controller.bank_summary()
        if not summary:
            self.bank_name_label.setText("（尚未导入题库）")
            self.bank_path_label.setText(
                "用「导入题库…」选择 Excel / CSV / Word / PDF 题库，或在下方从最近使用的题库里选一个。")
            for label in self.fact_labels.values():
                label.setText("—")
            self.issues_label.hide()
        else:
            self.bank_name_label.setText(summary.get("name") or "（未命名题库）")
            sheet = f"　工作表：{summary['sheet']}" if summary.get("sheet") else ""
            self.bank_path_label.setText(f"{summary.get('path', '')}{sheet}")
            self.fact_labels["total"].setText(f"{summary.get('total', 0)} 题")
            self.fact_labels["types"].setText(
                f"单选 {summary.get('single', 0)}　多选 {summary.get('multiple', 0)}"
                f"　判断 {summary.get('judge', 0)}")
            self.fact_labels["done"].setText(f"{summary.get('done', 0)} 题")
            self.fact_labels["accuracy"].setText(f"{summary.get('accuracy', 0) * 100:.1f}%")
            self.fact_labels["wrong_book"].setText(f"{summary.get('wrong_book', 0)} 道")
            self.fact_labels["excluded"].setText(f"{summary.get('excluded', 0)} 题")
            issues = summary.get("issues") or []
            if issues:
                preview = "\n".join(issues[:8])
                more = f"\n…… 其余 {len(issues) - 8} 条省略" if len(issues) > 8 else ""
                self.issues_label.setText(f"⚠ 有 {len(issues)} 行未能导入：\n{preview}{more}")
                self.issues_label.show()
            else:
                self.issues_label.hide()

        # 重建列表时保留原来选中的那一行（按路径匹配），否则任何状态刷新都会"丢选中"
        previous_path = self.selected_path()
        rows = self.controller.library_rows()
        self.library_model.set_rows(rows)
        if previous_path:
            for index, row in enumerate(rows):
                if str(row.get("path", "")) == previous_path:
                    self.library_table.selectRow(index)
                    break
        self._update_selection_label()
        self.filter_button.setEnabled(bool(summary))
        self.reload_button.setEnabled(bool(summary))

    def apply_theme(self, theme: Theme) -> None:
        self.theme = theme
        self.library_model.set_theme(theme)
        self.bank_name_label.setStyleSheet(
            f"font-size:{theme.font_size_title}px;font-weight:700;")
        self.refresh(self.controller.state)
