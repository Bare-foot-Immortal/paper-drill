# -*- coding: utf-8 -*-
"""领域模型：题型、题目、试卷蓝图、试卷与统计报告。

本模块为纯数据层：不依赖 GUI、不依赖文件系统、不做 IO，便于单元测试。
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum

__all__ = [
    "QType", "Question", "Blueprint", "PaperItem", "Paper", "GenReport",
    "AnswerParseError", "parse_answer", "normalize_text", "OPTION_LABELS",
]

OPTION_LABELS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# 题型别名 -> 标准题型
_TYPE_ALIASES: dict[str, "QType"] = {}


class QType(Enum):
    """题型：单选、多选、判断。"""

    SINGLE = "单选题"
    MULTIPLE = "多选题"
    JUDGE = "判断题"

    @property
    def short(self) -> str:
        return {"单选题": "单选", "多选题": "多选", "判断题": "判断"}[self.value]

    @property
    def key(self) -> str:
        """英文短键，用于配置/JSON。"""
        return {"单选题": "single", "多选题": "multiple", "判断题": "judge"}[self.value]


def _register_aliases() -> None:
    table = {
        QType.SINGLE: ["单选题", "单选", "单项选择", "单项选择題", "单项选择题", "单选题（单）",
                       "single", "single choice", "choice", "1", "s"],
        QType.MULTIPLE: ["多选题", "多选", "多项选择", "多项选择题", "不定项选择", "多选題",
                         "multiple", "multiple choice", "multi", "2", "m"],
        QType.JUDGE: ["判断题", "判断", "是非题", "对错题", "判断对错", "判断正误",
                      "judge", "true/false", "tf", "t/f", "3", "j"],
    }
    for qtype, names in table.items():
        for name in names:
            _TYPE_ALIASES[normalize_text(name).lower()] = qtype


def normalize_text(text: object) -> str:
    """统一空白与全角/半角，供解析与比对使用（不改写语义字符）。"""
    if text is None:
        return ""
    s = str(text)
    s = s.replace("\u3000", " ").replace("\xa0", " ")
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def parse_qtype(raw: object) -> "QType | None":
    """把题库中的题型文本解析为标准题型；无法识别返回 None。"""
    if raw is None:
        return None
    token = normalize_text(raw).lower().replace(" ", "")
    if token in _TYPE_ALIASES:
        return _TYPE_ALIASES[token]
    # 退化匹配：包含关键字
    if "判断" in token or "是非" in token or "对错" in token:
        return QType.JUDGE
    if "多选" in token or "多项" in token:
        return QType.MULTIPLE
    if "单选" in token or "单项" in token:
        return QType.SINGLE
    return None


class AnswerParseError(ValueError):
    """答案无法解析。"""


# ---------------------------------------------------------------- 答案解析
_JUDGE_TRUE = {"正确", "对", "是", "√", "✓", "T", "TRUE", "Y", "YES", "A", "1", "V"}
_JUDGE_FALSE = {"错误", "错", "否", "×", "x", "X", "F", "FALSE", "N", "NO", "B", "0", "-"}
_FIXED_RE = re.compile(r"[（(]\s*定\s*[）)]|定")


def parse_answer(qtype: QType, raw: object, option_count: int) -> tuple[list[str], "bool | None", bool]:
    """解析答案列。

    返回 ``(answer_letters, judge_answer, fixed_order)``。

    - 选择题：``answer_letters`` 为按字母升序的答案字母，``judge_answer`` 为 None；
    - 判断题：``answer_letters`` 为空，``judge_answer`` 为 True/False；
    - ``fixed_order``：答案中出现「定」标记时为 True（该题选项顺序固定，不打乱）。
    """
    text = normalize_text(raw)
    if not text:
        raise AnswerParseError("答案为空")
    fixed = bool(_FIXED_RE.search(text))

    if qtype is QType.JUDGE:
        token = re.sub(r"[（(]\s*定\s*[）)]", "", text).strip()
        token = token.strip(" .。;；,，")
        upper = token.upper()
        if upper in _JUDGE_TRUE or token in _JUDGE_TRUE:
            return [], True, fixed
        if upper in _JUDGE_FALSE or token in _JUDGE_FALSE:
            return [], False, fixed
        raise AnswerParseError(f"判断题答案无法识别：{text!r}（应为 正确/错误、对/错、√/×、T/F）")

    letters = re.findall(r"[A-Z]", text.upper())
    if not letters:
        raise AnswerParseError(f"选择题答案无法识别：{text!r}（应为 A/B/C/D 等字母组合）")
    # 去重并保序
    seen: list[str] = []
    for ch in letters:
        if ch not in seen:
            seen.append(ch)
    for ch in seen:
        if OPTION_LABELS.index(ch) >= option_count:
            raise AnswerParseError(
                f"答案字母 {ch} 超出选项范围（本题仅 {option_count} 个选项）"
            )
    letters_sorted = sorted(seen)
    if qtype is QType.SINGLE and len(letters_sorted) != 1:
        raise AnswerParseError(f"单选题答案必须且只能为 1 个字母，实际为 {''.join(letters_sorted)}")
    if qtype is QType.MULTIPLE and len(letters_sorted) < 2:
        raise AnswerParseError(f"多选题答案至少 2 个字母，实际为 {''.join(letters_sorted)}")
    return letters_sorted, None, fixed


# ---------------------------------------------------------------- 数据模型
@dataclass
class Question:
    """一道题目。"""

    qid: str
    qtype: QType
    stem: str
    options: list[str] = field(default_factory=list)
    answer_letters: list[str] = field(default_factory=list)
    judge_answer: "bool | None" = None
    fixed_order: bool = False
    analysis: str = ""
    src_row: int = 0

    @property
    def option_count(self) -> int:
        return len(self.options)

    @property
    def answer_display(self) -> str:
        """原始答案的展示文本。"""
        if self.qtype is QType.JUDGE:
            return "正确" if self.judge_answer else "错误"
        return "".join(self.answer_letters)

    @property
    def fingerprint(self) -> str:
        payload = self.stem + "\x1f" + "\x1f".join(self.options)
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]

    def validate(self) -> list[str]:
        """返回问题列表（空列表表示合法）。"""
        problems: list[str] = []
        if not self.stem.strip():
            problems.append("题干为空")
        if self.qtype is QType.JUDGE:
            if self.judge_answer is None:
                problems.append("判断题缺少答案")
        else:
            if len(self.options) < 2:
                problems.append(f"选项少于 2 个（实际 {len(self.options)}）")
            if not self.answer_letters:
                problems.append("缺少答案字母")
        return problems


@dataclass
class Blueprint:
    """一张试卷的题型配额。"""

    single: int = 0
    multiple: int = 0
    judge: int = 0

    def get(self, qtype: QType) -> int:
        return {QType.SINGLE: self.single, QType.MULTIPLE: self.multiple,
                QType.JUDGE: self.judge}[qtype]

    def set(self, qtype: QType, value: int) -> None:
        if qtype is QType.SINGLE:
            self.single = value
        elif qtype is QType.MULTIPLE:
            self.multiple = value
        else:
            self.judge = value

    @property
    def total(self) -> int:
        return self.single + self.multiple + self.judge

    def items(self) -> list[tuple[QType, int]]:
        return [(QType.SINGLE, self.single), (QType.MULTIPLE, self.multiple),
                (QType.JUDGE, self.judge)]

    def describe(self) -> str:
        parts = [f"{t.short} {n}" for t, n in self.items() if n > 0]
        return "、".join(parts) if parts else "（空）"

    def to_dict(self) -> dict:
        return {"single": self.single, "multiple": self.multiple, "judge": self.judge}

    @classmethod
    def from_dict(cls, data: dict) -> "Blueprint":
        return cls(int(data.get("single", 0)), int(data.get("multiple", 0)), int(data.get("judge", 0)))


@dataclass
class PaperItem:
    """试卷中的一道题（含打乱后的展示形式与重映射后的答案）。"""

    question: Question
    labels: list[str]
    texts: list[str]
    answer_display: str
    shuffled: bool
    reused: bool = False

    @property
    def qtype(self) -> QType:
        return self.question.qtype

    @property
    def stem(self) -> str:
        return self.question.stem

    def option_lines(self) -> list[str]:
        return [f"{label}. {text}" for label, text in zip(self.labels, self.texts)]


@dataclass
class Paper:
    """一张试卷。"""

    seq: int                     # 全局序号（1 起）
    round_seq: int               # 轮内序号（1 起）
    label: str                   # 卷标，如 "A"
    items: dict[QType, list[PaperItem]] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return f"{self.label}卷"

    @property
    def total(self) -> int:
        return sum(len(v) for v in self.items.values())

    def all_items(self) -> list[PaperItem]:
        """按 单选 → 多选 → 判断 的固定顺序返回全部题目。"""
        out: list[PaperItem] = []
        for qtype in (QType.SINGLE, QType.MULTIPLE, QType.JUDGE):
            out.extend(self.items.get(qtype, []))
        return out

    def items_of(self, qtype: QType) -> list[PaperItem]:
        return list(self.items.get(qtype, []))

    def count_of(self, qtype: QType) -> int:
        return len(self.items.get(qtype, []))

    def answer_lines(self) -> list[tuple[int, str]]:
        """返回 [(题号, 答案文本)]。"""
        return [(i, item.answer_display) for i, item in enumerate(self.all_items(), start=1)]


@dataclass
class GenReport:
    """一轮生成的完整结果与自检信息。"""

    papers: list[Paper] = field(default_factory=list)
    round_length: int = 0
    rounds: int = 1
    blueprint: Blueprint = field(default_factory=Blueprint)
    coverage: dict[str, tuple[int, int]] = field(default_factory=dict)  # key -> (已出现, 题库总数)
    coverage_ok: bool = True
    uncovered: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    seed: "int | None" = None
    bank_total: int = 0

    @property
    def paper_count(self) -> int:
        return len(self.papers)

    def summary(self) -> str:
        got = sum(v[0] for v in self.coverage.values())
        total = sum(v[1] for v in self.coverage.values())
        flag = "覆盖完整" if self.coverage_ok else f"未覆盖 {len(self.uncovered)} 题"
        return (f"共 {self.paper_count} 张（{self.rounds} 轮 × {self.round_length} 张），"
                f"题库 {total} 题已出现 {got} 题，{flag}")


_register_aliases()
