# -*- coding: utf-8 -*-
"""刷题匠 PaperDrill —— 对话框集合（FR-19.4 ～ 19.6 及帮助/关于）。

约定：对话框只做展示与收集用户确认，**所有数据变更都调用控制器**，
因此对话框关闭后主界面的状态一定是最新的。
"""
from __future__ import annotations

from typing import Callable, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableView,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..models import QType, Question
from .controller import PaperDrillController
from .models import ExamHistoryModel, LibraryModel, ProgressModel, QuestionFilterModel, QuestionFilterRow
from .theme import Theme
from .widgets import MutedLabel, SectionLabel

__all__ = [
    "BaseDialog", "WrongBookDialog", "QuestionFilterDialog", "ProgressDialog",
    "BankPickerDialog", "ExamHistoryDialog", "HelpDialog", "AboutDialog",
    "confirm", "notify", "warn",
]


# ---------------------------------------------------------------- 便捷消息框
def confirm(parent, title: str, text: str) -> bool:
    """是/否确认框（默认否）。"""
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setIcon(QMessageBox.Question)
    box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    box.setDefaultButton(QMessageBox.No)
    return box.exec() == QMessageBox.Yes


def notify(parent, title: str, text: str) -> None:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setIcon(QMessageBox.Information)
    box.exec()


def warn(parent, title: str, text: str) -> None:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setIcon(QMessageBox.Warning)
    box.exec()


class BaseDialog(QDialog):
    """统一外观的对话框基类。"""

    def __init__(self, title: str, theme: Theme, parent: "QWidget | None" = None,
                 size: tuple[int, int] = (760, 560)) -> None:
        super().__init__(parent)
        self.theme = theme
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(*size)
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(theme.space_lg, theme.space_md,
                                     theme.space_lg, theme.space_lg)
        self.root.setSpacing(theme.space_md)

    def add_header(self, title: str, hint: str = "") -> None:
        label = QLabel(title)
        label.setStyleSheet(f"font-size:{self.theme.font_size_title}px;font-weight:700;")
        self.root.addWidget(label)
        if hint:
            self.root.addWidget(MutedLabel(hint, self.theme))

    def add_buttons(self, buttons: Sequence[tuple[str, Callable[[], None], str]]) -> QHBoxLayout:
        """追加一排按钮：``(文案, 回调, kind)``。``kind`` 可为 ``primary``/``danger``/空。"""
        row = QHBoxLayout()
        row.setSpacing(self.theme.space_sm)
        for text, callback, kind in buttons:
            btn = QPushButton(text)
            if kind:
                btn.setProperty("kind", kind)
            btn.clicked.connect(lambda _=False, cb=callback: cb())
            row.addWidget(btn)
        row.addStretch(1)
        self.root.addLayout(row)
        return row

    def add_close_button(self, text: str = "关闭") -> QPushButton:
        row = QHBoxLayout()
        row.addStretch(1)
        btn = QPushButton(text)
        btn.clicked.connect(self.accept)
        row.addWidget(btn)
        self.root.addLayout(row)
        return btn


def _make_table(theme: Theme, model) -> QTableView:
    table = QTableView()
    table.setModel(model)
    table.setAlternatingRowColors(True)
    table.verticalHeader().setVisible(False)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.ExtendedSelection)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    header = table.horizontalHeader()
    header.setStretchLastSection(True)
    return table


# ================================================================ 错题本
class WrongBookDialog(BaseDialog):
    """错题本：列出当前错题、正确答案与解析。"""

    practice_wrong_requested = Signal()

    def __init__(self, controller: PaperDrillController, theme: Theme,
                 parent: "QWidget | None" = None) -> None:
        super().__init__("错题本", theme, parent, (880, 620))
        self.controller = controller
        self.questions: list[Question] = controller.wrong_book_questions()
        self.add_header(f"当前错题 {len(self.questions)} 道",
                        "答对后自动移出；「只练错题」会切到练习页的错题重练模式。")
        self.viewer = QTextBrowser()
        self.viewer.setPlainText(self._render())
        self.root.addWidget(self.viewer, 1)
        self.add_buttons([
            ("只练错题", self._practice_wrong, "primary"),
            ("清空错题标记", self._clear, "danger"),
        ])
        self.add_close_button()

    def _render(self) -> str:
        if not self.questions:
            return "（暂无错题）\n\n答错的题目会自动进入这里。"
        lines: list[str] = []
        for i, q in enumerate(self.questions, start=1):
            lines.append(f"{i}. {q.stem}")
            if q.qtype is not QType.JUDGE:
                for letter, opt in zip("ABCDEFGH", q.options, strict=False):
                    lines.append(f"    {letter}. {opt}")
            ans = q.answer_display + ("（定）" if q.fixed_order else "")
            lines.append(f"    ✔ 正确答案：{ans}")
            if q.analysis:
                lines.append(f"    解析：{q.analysis}")
            lines.append("")
        return "\n".join(lines)

    def _practice_wrong(self) -> None:
        self.practice_wrong_requested.emit()
        self.accept()

    def _clear(self) -> None:
        if not self.questions:
            notify(self, "提示", "当前没有错题。")
            return
        if not confirm(self, "清空错题本",
                       "将把所有题目移出错题本（历史统计保留），确定吗？"):
            return
        count = self.controller.clear_wrong_book()
        self.questions = self.controller.wrong_book_questions()
        self.viewer.setPlainText(self._render())
        notify(self, "完成", f"已清空 {count} 道错题标记。")


# ================================================================ 题库删减
class QuestionFilterDialog(BaseDialog):
    """题库删减：把不想练的题移出练习与组卷（不改题库原文件，可随时恢复）。"""

    def __init__(self, controller: PaperDrillController, theme: Theme,
                 parent: "QWidget | None" = None) -> None:
        super().__init__("题库删减", theme, parent, (1060, 700))
        self.controller = controller
        self.force_replace = False
        if controller.has_unsubmitted_exam():
            self.force_replace = confirm(
                self, "放弃当前考试",
                "当前有一场未交卷的模拟考试；删减/恢复题库题目会作废试卷并丢弃作答。\n"
                "确定继续吗？")
        self.all_questions: list[Question] = controller.all_questions()
        self.by_fp = {q.fingerprint: q for q in self.all_questions}
        self.add_header(
            f"题库删减 —— 「{self._bank_name()}」",
            "被删减的题目不会出现在练习、错题本与模拟考试组卷中；题库原文件不会被修改。")

        bar = QHBoxLayout()
        bar.setSpacing(theme.space_sm)
        bar.addWidget(SectionLabel("题型", theme))
        self.type_box = QComboBox()
        self.type_box.addItems(["全部", "单选题", "多选题", "判断题"])
        self.type_box.currentIndexChanged.connect(lambda *_: self.reload())
        bar.addWidget(self.type_box)
        bar.addSpacing(theme.space_lg)
        bar.addWidget(SectionLabel("搜索题干/选项", theme))
        self.keyword = QLineEdit()
        self.keyword.setPlaceholderText("输入关键词…")
        self.keyword.textChanged.connect(lambda *_: self.reload())
        bar.addWidget(self.keyword, 1)
        self.count_label = QLabel("")
        self.count_label.setObjectName("Muted")
        bar.addWidget(self.count_label)
        self.root.addLayout(bar)

        tabs = QTabWidget()
        self.active_model = QuestionFilterModel(theme)
        self.cut_model = QuestionFilterModel(theme)
        self.active_table = _make_table(theme, self.active_model)
        self.cut_table = _make_table(theme, self.cut_model)
        active_page = QWidget()
        active_lay = QVBoxLayout(active_page)
        active_lay.setContentsMargins(0, theme.space_sm, 0, 0)
        active_lay.addWidget(self.active_table)
        self.active_tab = tabs.addTab(active_page, "参与练习")
        cut_page = QWidget()
        cut_lay = QVBoxLayout(cut_page)
        cut_lay.setContentsMargins(0, theme.space_sm, 0, 0)
        cut_lay.addWidget(self.cut_table)
        self.cut_tab = tabs.addTab(cut_page, "已删减")
        self.tabs = tabs
        self.root.addWidget(tabs, 1)

        self.add_buttons([
            ("删减选中题目 →", self.cut_selected, "primary"),
            ("← 恢复选中题目", self.restore_selected, ""),
            ("全部恢复", self.restore_all, ""),
            ("查看题目内容", self.show_selected_question, ""),
        ])
        self.add_close_button()
        self.reload()

    def _bank_name(self) -> str:
        summary = self.controller.bank_summary()
        return summary.get("name") or "当前题库"

    # ------------------------------------------------------------ 过滤
    def _match(self, q: Question) -> bool:
        wanted = self.type_box.currentText()
        if wanted != "全部" and q.qtype.value != wanted:
            return False
        keyword = self.keyword.text().strip().lower()
        if not keyword:
            return True
        if keyword in (q.stem or "").lower():
            return True
        return any(keyword in (opt or "").lower() for opt in q.options)

    def reload(self) -> None:
        active: list[QuestionFilterRow] = []
        cut: list[QuestionFilterRow] = []
        total_cut = 0
        for index, q in enumerate(self.all_questions, start=1):
            excluded = self.controller.is_excluded(q)
            if excluded:
                total_cut += 1
            if not self._match(q):
                continue
            row = QuestionFilterRow(index=index, question=q, excluded=excluded)
            (cut if excluded else active).append(row)
        self.active_model.set_rows(active)
        self.cut_model.set_rows(cut)
        self.count_label.setText(
            f"参与练习 {len(self.all_questions) - total_cut} 题　｜　已删减 {total_cut} 题"
            f"　（当前筛选：参与 {len(active)} / 已删减 {len(cut)}）")

    # ------------------------------------------------------------ 操作
    def _selected_questions(self, table: QTableView, model: QuestionFilterModel) -> list[Question]:
        rows = sorted({index.row() for index in table.selectionModel().selectedRows()})
        return model.questions_at_rows(rows)

    def cut_selected(self) -> int:
        picked = self._selected_questions(self.active_table, self.active_model)
        if not picked:
            notify(self, "提示", "请先在「参与练习」列表中选择要删减的题目。")
            return 0
        count = self.controller.exclude_questions(picked, force=self.force_replace)
        self.reload()
        if count:
            self.controller.report_status(f"已删减 {count} 道题目（题库原文件未改动）")
        return count

    def restore_selected(self) -> int:
        picked = self._selected_questions(self.cut_table, self.cut_model)
        if not picked:
            notify(self, "提示", "请先在「已删减」列表中选择要恢复的题目。")
            return 0
        count = self.controller.include_questions(picked, force=self.force_replace)
        self.reload()
        if count:
            self.controller.report_status(f"已恢复 {count} 道题目")
        return count

    def restore_all(self) -> int:
        excluded = self.controller.excluded_questions()
        if not excluded:
            notify(self, "提示", "当前没有已删减的题目。")
            return 0
        if not confirm(self, "全部恢复", f"确定把全部 {len(excluded)} 道已删减的题目恢复吗？"):
            return 0
        count = self.controller.restore_all_excluded(force=self.force_replace)
        self.reload()
        return count

    def show_selected_question(self) -> str:
        table, model = (self.cut_table, self.cut_model) if self.tabs.currentIndex() == 1 \
            else (self.active_table, self.active_model)
        rows = table.selectionModel().selectedRows()
        if not rows:
            notify(self, "提示", "请先选择一道题目。")
            return ""
        q = model.question_at(rows[0].row())
        if q is None:
            return ""
        text = self.question_text(q)
        box = QMessageBox(self)
        box.setWindowTitle("题目内容")
        box.setText(text)
        box.setIcon(QMessageBox.Information)
        box.exec()
        return text

    @staticmethod
    def question_text(q: Question) -> str:
        lines = [q.stem, ""]
        if q.qtype is not QType.JUDGE:
            for letter, opt in zip("ABCDEFGH", q.options, strict=False):
                lines.append(f"{letter}. {opt}")
        else:
            lines.append("（判断题）")
        lines.append("")
        lines.append(f"正确答案：{q.answer_display}" + ("（定）" if q.fixed_order else ""))
        if q.analysis:
            lines.append(f"解析：{q.analysis}")
        return "\n".join(lines)


# ================================================================ 进度管理
class ProgressDialog(BaseDialog):
    """进度管理：查看/重置各题库进度。"""

    def __init__(self, controller: PaperDrillController, theme: Theme,
                 parent: "QWidget | None" = None) -> None:
        super().__init__("进度管理", theme, parent, (980, 520))
        self.controller = controller
        self.add_header("题库进度", f"进度目录：{controller.progress_dir}")
        self.model = ProgressModel(theme)
        self.table = _make_table(theme, self.model)
        self.root.addWidget(self.table, 1)
        self.add_buttons([
            ("题库删减…", self._open_filter, ""),
            ("重置选中题库进度", self._reset_selected, "danger"),
        ])
        self.add_close_button()
        self.reload()

    def reload(self) -> None:
        self.model.set_rows(self.controller.progress_rows())

    def _selected_key(self) -> str:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return ""
        return self.model.key_at(rows[0].row())

    def _reset_selected(self) -> bool:
        key = self._selected_key()
        if not key:
            notify(self, "提示", "请先在列表中选择一个题库。")
            return False
        if not confirm(self, "重置进度", "确定清空该题库的全部练习记录与成绩吗？此操作不可撤销。"):
            return False
        ok = self.controller.reset_progress_of(key)
        self.reload()
        return ok

    def _open_filter(self) -> None:
        self.accept()
        self.controller.report_status("请在主界面「练习 → 题库删减…」中操作当前题库")


# ================================================================ 题库选择
class BankPickerDialog(BaseDialog):
    """题库选择：最近使用的题库，一键切换 / 扫描 / 移除记录。"""

    load_requested = Signal(str)
    import_requested = Signal()
    scan_requested = Signal()

    def __init__(self, controller: PaperDrillController, theme: Theme,
                 parent: "QWidget | None" = None) -> None:
        super().__init__("选择题库", theme, parent, (940, 560))
        self.controller = controller
        self.add_header("已记录题库（双击载入）",
                        "「移除记录」只从列表移除，不会删除磁盘上的题库文件。")
        self.model = LibraryModel(theme)
        self.table = _make_table(theme, self.model)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.doubleClicked.connect(lambda *_: self.load_selected())
        self.root.addWidget(self.table, 1)
        self.hint = MutedLabel("", theme)
        self.root.addWidget(self.hint)
        self.add_buttons([
            ("载入选中题库", self.load_selected, "primary"),
            ("导入题库文件…", self._import, ""),
            ("扫描文件夹…", self._scan, ""),
            ("移除记录", self._forget, ""),
            ("移除记录并清空进度", self._forget_reset, "danger"),
        ])
        self.add_close_button()
        self.reload()

    def reload(self) -> None:
        rows = self.controller.library_rows()
        self.model.set_rows(rows)
        missing = sum(1 for r in rows if not r.get("exists", True))
        self.hint.setText(f"共 {len(rows)} 个记录，其中 {missing} 个文件已不存在")

    def selected_path(self) -> str:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return ""
        obj = self.model.row_object(rows[0].row())
        return str(obj.get("path", "")) if obj else ""

    def load_selected(self) -> bool:
        path = self.selected_path()
        if not path:
            notify(self, "提示", "请先在列表中选择一个题库。")
            return False
        self.load_requested.emit(path)
        self.accept()
        return True

    def _import(self) -> None:
        self.import_requested.emit()
        self.accept()

    def _scan(self) -> None:
        self.scan_requested.emit()
        self.accept()

    def _forget(self) -> bool:
        path = self.selected_path()
        if not path:
            notify(self, "提示", "请先在列表中选择一个题库。")
            return False
        if not confirm(self, "移除记录",
                       f"从题库列表移除这条记录吗？\n{path}\n\n"
                       "注意：只是不再显示在列表里，不会删除题库文件。"):
            return False
        self.controller.forget_library_entry(path)
        self.reload()
        return True

    def _forget_reset(self) -> bool:
        path = self.selected_path()
        if not path:
            notify(self, "提示", "请先在列表中选择一个题库。")
            return False
        if not confirm(self, "移除记录并清空进度",
                       f"移除记录，并删除该题库保存的练习进度吗？\n{path}\n\n"
                       "练习记录、错题本与历史成绩都会清空，不可撤销；题库文件不会被删除。"):
            return False
        cleaned = self.controller.forget_with_progress(path)
        self.reload()
        notify(self, "完成", f"已移除记录，并清理 {cleaned} 份进度文件。")
        return True


# ================================================================ 历史成绩
class ExamHistoryDialog(BaseDialog):
    """历史成绩（最近 30 次）。"""

    def __init__(self, controller: PaperDrillController, theme: Theme,
                 parent: "QWidget | None" = None) -> None:
        super().__init__("历史成绩", theme, parent, (820, 460))
        self.controller = controller
        summary = controller.bank_summary()
        name = summary.get("name") or "当前题库"
        self.add_header(f"「{name}」的模拟考试成绩", "最近 30 次，按时间倒序")
        self.model = ExamHistoryModel(theme)
        self.table = _make_table(theme, self.model)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.root.addWidget(self.table, 1)
        self.model.set_rows(controller.exam_history())
        self.add_close_button()


# ================================================================ 帮助 / 关于
class HelpDialog(BaseDialog):
    """使用说明。"""

    def __init__(self, theme: Theme, text: str, parent: "QWidget | None" = None) -> None:
        super().__init__("使用说明", theme, parent, (880, 680))
        viewer = QTextBrowser()
        viewer.setPlainText(text)
        self.root.addWidget(viewer, 1)
        self.add_close_button()


class AboutDialog(BaseDialog):
    """关于。"""

    def __init__(self, theme: Theme, text: str, parent: "QWidget | None" = None) -> None:
        super().__init__("关于", theme, parent, (560, 420))
        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.root.addWidget(label, 1)
        self.add_close_button("知道了")
