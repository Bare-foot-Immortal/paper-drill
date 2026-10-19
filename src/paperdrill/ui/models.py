# -*- coding: utf-8 -*-
"""刷题匠 PaperDrill —— 表格模型（Qt Model/View）。

用 ``QAbstractTableModel`` 而不是 ``QTableWidget``：题库删减对话框可能有上万道题，
模型只按需提供单元格文本，视图做虚拟化渲染，不会一次性创建上万个控件。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QBrush, QColor, QFont

from ..models import QType, Question
from .theme import Theme

__all__ = [
    "Column", "TableModel", "PaperDetailModel", "ExamDetailModel",
    "ExamHistoryModel", "LibraryModel", "ProgressModel", "QuestionFilterModel",
]


@dataclass(frozen=True)
class Column:
    """一列的定义：标题、取值函数、对齐、宽度。"""

    title: str
    value: Callable[[object], object]
    width: int = 100
    align: int = Qt.AlignLeft | Qt.AlignVCenter
    tone: "Callable[[object], str] | None" = None      # 行级语义色 key


class TableModel(QAbstractTableModel):
    """通用只读表格模型：行对象 + 列定义。"""

    def __init__(self, columns: Sequence[Column], rows: Sequence[object] = (),
                 theme: "Theme | None" = None, parent=None) -> None:
        super().__init__(parent)
        self.columns = list(columns)
        self.rows: list[object] = list(rows)
        self.theme = theme

    # ------------------------------------------------------------ 基本接口
    # 说明：Qt 的 Model 接口要求 parent 默认是一个无效 QModelIndex，
    # 这是官方惯用法，B008（默认值里调用函数）在此豁免。
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802, B008
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802, B008
        return 0 if parent.isValid() else len(self.columns)

    def headerData(self, section: int, orientation: Qt.Orientation,  # noqa: N802
                   role: int = Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            if 0 <= section < len(self.columns):
                return self.columns[section].title
            return None
        return str(section + 1)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._row_at(index.row())
        if row is None:
            return None
        col = self.columns[index.column()]
        if role == Qt.DisplayRole:
            value = col.value(row)
            if value is None:
                return ""
            return str(value)
        if role == Qt.TextAlignmentRole:
            return int(col.align)
        if role == Qt.ForegroundRole and self.theme is not None and col.tone is not None:
            key = col.tone(row)
            if key:
                return QBrush(QColor(getattr(self.theme, key, self.theme.text)))
        if role == Qt.FontRole and self.theme is not None:
            return QFont(self.theme.to_font(self.theme.font_size))
        if role == Qt.UserRole:
            return row
        return None

    # ------------------------------------------------------------ 数据更新
    def _row_at(self, index: int):
        if 0 <= index < len(self.rows):
            return self.rows[index]
        return None

    def row_object(self, index: int):
        return self._row_at(index)

    def set_rows(self, rows: Sequence[object]) -> None:
        self.beginResetModel()
        self.rows = list(rows)
        self.endResetModel()

    def set_theme(self, theme: Theme) -> None:
        self.theme = theme
        if self.rows:
            self.dataChanged.emit(self.index(0, 0),
                                  self.index(len(self.rows) - 1, len(self.columns) - 1))

    # ------------------------------------------------------------ 列宽
    def column_widths(self) -> list[int]:
        return [c.width for c in self.columns]


# ================================================================ 具体模型
def _paper_detail_columns() -> list[Column]:
    Q = QType
    return [
        Column("卷号", lambda p: f"{p.label}卷", 84, Qt.AlignCenter),
        Column("题量", lambda p: p.total, 70, Qt.AlignCenter),
        Column("单选", lambda p: p.count_of(Q.SINGLE), 70, Qt.AlignCenter),
        Column("多选", lambda p: p.count_of(Q.MULTIPLE), 70, Qt.AlignCenter),
        Column("判断", lambda p: p.count_of(Q.JUDGE), 70, Qt.AlignCenter),
        Column("其中补题", lambda p: p.reused_count, 100, Qt.AlignCenter),
    ]


class PaperDetailModel(TableModel):
    """一轮试卷的逐卷明细。"""

    def __init__(self, theme: "Theme | None" = None, parent=None) -> None:
        super().__init__(_paper_detail_columns(), [], theme, parent)


def _exam_detail_columns() -> list[Column]:
    def result_text(d: dict) -> str:
        if d.get("correct"):
            return "✔ 正确"
        return "— 未答" if d.get("unanswered") else "✘ 错误"

    def result_tone(d: dict) -> str:
        if d.get("correct"):
            return "success"
        return "text_muted" if d.get("unanswered") else "danger"

    return [
        Column("题号", lambda d: d.get("number"), 60, Qt.AlignCenter),
        Column("题型", lambda d: d.get("qtype"), 80, Qt.AlignCenter),
        Column("结果", result_text, 84, Qt.AlignCenter, result_tone),
        Column("你的作答", lambda d: d.get("selected"), 300),
        Column("正确答案", lambda d: d.get("answer"), 100, Qt.AlignCenter),
    ]


class ExamDetailModel(TableModel):
    """交卷后的逐题明细。"""

    def __init__(self, theme: "Theme | None" = None, parent=None) -> None:
        super().__init__(_exam_detail_columns(), [], theme, parent)

    def detail_at(self, row: int) -> "dict | None":
        return self._row_at(row)


def _exam_history_columns() -> list[Column]:
    return [
        Column("时间", lambda r: r.get("ts", ""), 150, Qt.AlignCenter),
        Column("卷", lambda r: r.get("paper_label", ""), 54, Qt.AlignCenter),
        Column("得分", lambda r: f"{_num(r.get('score', 0)):g}/{_num(r.get('full_score', 0)):g}", 96,
               Qt.AlignCenter),
        Column("正确", lambda r: r.get("correct", 0), 64, Qt.AlignCenter),
        Column("错误", lambda r: r.get("wrong", 0), 64, Qt.AlignCenter),
        Column("未答", lambda r: r.get("unanswered", 0), 64, Qt.AlignCenter),
        Column("正确率", lambda r: f"{_num(r.get('accuracy', 0)) * 100:.1f}%", 84,
               Qt.AlignCenter),
    ]


def _num(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


class ExamHistoryModel(TableModel):
    """历史成绩（最新在前）。"""

    def __init__(self, theme: "Theme | None" = None, parent=None) -> None:
        super().__init__(_exam_history_columns(), [], theme, parent)


def _library_columns() -> list[Column]:
    return [
        Column("题库", lambda r: r.get("name") or "", 220),
        Column("题数", lambda r: r.get("total") or "—", 72, Qt.AlignCenter),
        Column("路径", lambda r: r.get("path") or "", 380),
        Column("最后使用", lambda r: r.get("last_used") or "—", 150, Qt.AlignCenter),
    ]


class LibraryModel(TableModel):
    """题库库（最近使用的题库）。"""

    def __init__(self, theme: "Theme | None" = None, parent=None) -> None:
        super().__init__(_library_columns(), [], theme, parent)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        row = self.row_object(index.row())
        if row is not None and role == Qt.ForegroundRole and not row.get("exists", True):
            if self.theme is not None:
                return QBrush(QColor(self.theme.text_faint))
        return super().data(index, role)


def _progress_columns() -> list[Column]:
    return [
        Column("题库", lambda r: r.get("name") or "", 200),
        Column("参与练习", lambda r: r.get("active", r.get("total") or 0) or 0, 90, Qt.AlignCenter),
        Column("总题数", lambda r: r.get("total") or "—", 84, Qt.AlignCenter),
        Column("已删减", lambda r: r.get("excluded", 0) or "—", 84, Qt.AlignCenter),
        Column("已练", lambda r: r.get("done") or "—", 72, Qt.AlignCenter),
        Column("正确率", lambda r: (f"{float(r.get('accuracy', 0) or 0) * 100:.1f}%"
                                   if r.get("done") else "—"), 84, Qt.AlignCenter),
        Column("错题", lambda r: r.get("wrong_book", 0), 72, Qt.AlignCenter),
        Column("考试次数", lambda r: r.get("exams", 0), 90, Qt.AlignCenter),
        Column("最后更新", lambda r: r.get("updated") or "—", 160, Qt.AlignCenter),
    ]


class ProgressModel(TableModel):
    """进度管理：各题库进度摘要。"""

    def __init__(self, theme: "Theme | None" = None, parent=None) -> None:
        super().__init__(_progress_columns(), [], theme, parent)

    def key_at(self, row: int) -> str:
        obj = self.row_object(row)
        return str(obj.get("key", "")) if obj else ""


@dataclass
class QuestionFilterRow:
    """题库删减对话框的一行。"""

    index: int
    question: Question
    excluded: bool = False

    @property
    def fingerprint(self) -> str:
        return self.question.fingerprint

    @property
    def type_short(self) -> str:
        return self.question.qtype.short

    @property
    def stem_flat(self) -> str:
        return (self.question.stem or "").replace("\n", " ")


def _question_filter_columns() -> list[Column]:
    return [
        Column("原序号", lambda r: r.index, 76, Qt.AlignCenter),
        Column("题型", lambda r: r.type_short, 76, Qt.AlignCenter),
        Column("题干", lambda r: r.stem_flat, 760),
    ]


class QuestionFilterModel(TableModel):
    """题库删减：参与练习 / 已删减 两个视图共用的数据模型。"""

    def __init__(self, theme: "Theme | None" = None, parent=None) -> None:
        super().__init__(_question_filter_columns(), [], theme, parent)

    def set_rows(self, rows: Sequence[QuestionFilterRow]) -> None:
        super().set_rows(rows)

    def question_at(self, row: int) -> "Question | None":
        obj = self.row_object(row)
        return obj.question if obj is not None else None

    def questions_at_rows(self, rows: Iterable[int]) -> list[Question]:
        out: list[Question] = []
        for row in rows:
            q = self.question_at(int(row))
            if q is not None:
                out.append(q)
        return out
