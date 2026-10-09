# -*- coding: utf-8 -*-
"""练习与考试引擎（不含界面）。

包含三部分：
* 题目渲染 ``build_item``：按题型决定是否打乱选项，并重映射答案；「定」题恒不打乱；
* 练习会话 ``PracticeSession``：练习范围（整库/按题型）× 练习模式（顺序/随机/错题/未做）；
* 模拟考试 ``ExamSession``：按蓝图生成的整卷作答、交卷评分与逐题明细。
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Sequence

from .models import OPTION_LABELS, QType, Question
from .paper import Paper, PaperBlueprint
from .store import ProgressStore, QRecord

__all__ = ["PracticeMode", "Scope", "PracticeItem", "AnswerResult", "PracticeSession",
           "ExamSession", "ExamResult", "build_item", "DEFAULT_SCORES"]


class PracticeMode(Enum):
    ORDER = "order"
    RANDOM = "random"
    WRONG = "wrong"
    FRESH = "fresh"

    @property
    def label(self) -> str:
        return {"order": "顺序练习", "random": "随机练习",
                "wrong": "错题重练", "fresh": "只练未做"}[self.value]

    @classmethod
    def from_label(cls, label: str) -> "PracticeMode":
        for m in cls:
            if m.label == label or m.value == label:
                return m
        return cls.ORDER


class Scope(Enum):
    """练习范围（需求 6 前半）。"""

    ALL = "all"
    SINGLE = "single"
    MULTIPLE = "multiple"
    JUDGE = "judge"

    @property
    def label(self) -> str:
        return {"all": "整个题库", "single": "只练单选",
                "multiple": "只练多选", "judge": "只练判断"}[self.value]

    @property
    def qtype(self) -> "QType | None":
        return {"all": None, "single": QType.SINGLE,
                "multiple": QType.MULTIPLE, "judge": QType.JUDGE}[self.value]

    @classmethod
    def from_label(cls, label: str) -> "Scope":
        for s in cls:
            if s.label == label or s.value == label:
                return s
        return cls.ALL


DEFAULT_SCORES = {"single": 1.0, "multiple": 2.0, "judge": 1.0}


@dataclass
class PracticeItem:
    """一道题的"显示形态"：选项顺序 + 重映射后的答案。"""

    question: Question
    order: list[int] = field(default_factory=list)      # 显示顺序（原始选项索引）
    labels: list[str] = field(default_factory=list)     # 显示字母
    texts: list[str] = field(default_factory=list)      # 显示文本
    shown_answer: set[str] = field(default_factory=set)  # 选择题正确答案（显示字母）
    shuffled: bool = False

    @property
    def qtype(self) -> QType:
        return self.question.qtype

    @property
    def stem(self) -> str:
        return self.question.stem

    @property
    def analysis(self) -> str:
        return self.question.analysis

    @property
    def option_count(self) -> int:
        return len(self.texts)

    @property
    def fixed_order(self) -> bool:
        return self.question.fixed_order

    def answer_display(self) -> str:
        """展示用正确答案文本。"""
        if self.qtype is QType.JUDGE:
            return "正确" if self.question.judge_answer else "错误"
        return "".join(sorted(self.shown_answer, key=OPTION_LABELS.index))

    def options(self) -> list[tuple[str, str]]:
        return list(zip(self.labels, self.texts, strict=False))

    def _as_letters(self, selected) -> "set[str]":
        """把作答统一为显示字母集合（判断题支持 bool 入参）。"""
        if selected is None:
            return set()
        if isinstance(selected, bool):
            if self.qtype is not QType.JUDGE:
                return set()
            return {"A"} if selected else {"B"}
        if isinstance(selected, str):
            return {selected} if selected else set()
        return set(selected)

    def judge(self, selected: "Iterable[str] | bool | None") -> bool:
        """判题。可传显示字母集合（或判断题 bool）；多选要求集合完全相等。"""
        if selected is None:
            return False
        if isinstance(selected, str):
            letters = {selected} if selected else set()
        elif isinstance(selected, bool):
            if self.qtype is not QType.JUDGE:
                return False
            letters = {"A"} if selected else {"B"}
        else:
            letters = set(selected)
        if not letters:
            return False
        return letters == set(self.shown_answer)

    def selected_text(self, selected: "Iterable[str] | bool | None") -> str:
        """把用户的作答渲染为可读文本（用于反馈与错题本）。"""
        letters = self._as_letters(selected)
        if not letters:
            return "（未作答）"
        if self.qtype is QType.JUDGE:
            idx = OPTION_LABELS.index(sorted(letters)[0])
            return self.texts[idx] if idx < len(self.texts) else "（未作答）"
        parts = []
        for letter in sorted(letters, key=OPTION_LABELS.index):
            idx = OPTION_LABELS.index(letter)
            text = self.texts[idx] if 0 <= idx < len(self.texts) else ""
            parts.append(f"{letter}. {text}")
        return "；".join(parts)

    def answer_text(self) -> str:
        """正确答案的可读文本（含选项内容）。"""
        if self.qtype is QType.JUDGE:
            return self.answer_display()
        return "；".join(f"{lab}. {txt}" for lab, txt in
                         ((lab, self.texts[OPTION_LABELS.index(lab)]) for lab in
                          sorted(self.shown_answer, key=OPTION_LABELS.index)))


@dataclass
class AnswerResult:
    """一次判题的结果（练习模式）。"""

    correct: bool
    selected: object
    correct_answer: str
    selected_answer: str
    analysis: str
    is_repeat: bool = False
    in_wrong_book: bool = False
    record: "QRecord | None" = None


def build_item(question: Question, rng: random.Random, shuffle: bool) -> PracticeItem:
    """构建一道题的显示形态。

    * 判断题：统一为「A. 正确 / B. 错误」两个选项，便于界面与判题复用单选逻辑；
    * 选择题：``shuffle`` 为真且非「定」题时打乱选项并重映射答案；
    * 「定」题与判断题**永不打乱**。
    """
    if question.qtype is QType.JUDGE:
        return PracticeItem(
            question=question, order=[0, 1], labels=["A", "B"], texts=["正确", "错误"],
            shown_answer={"A" if question.judge_answer else "B"}, shuffled=False)

    n = question.option_count
    allow = shuffle and n >= 2 and not question.fixed_order
    if allow:
        order = list(range(n))
        rng.shuffle(order)
        labels = [OPTION_LABELS[j] for j in range(n)]
        texts = [question.options[i] for i in order]
        position = {orig: pos for pos, orig in enumerate(order)}
        shown = {OPTION_LABELS[position[OPTION_LABELS.index(c)]] for c in question.answer_letters}
        return PracticeItem(question=question, order=order, labels=labels, texts=texts,
                            shown_answer=shown, shuffled=True)
    labels = [OPTION_LABELS[j] for j in range(n)]
    shown = set(question.answer_letters)
    return PracticeItem(question=question, order=list(range(n)), labels=labels,
                        texts=list(question.options), shown_answer=shown, shuffled=False)


class PracticeSession:
    """练习会话：维护出题队列、当前位置与判题。"""

    def __init__(self, questions: Sequence[Question], store: ProgressStore,
                 mode: PracticeMode = PracticeMode.ORDER,
                 shuffle_single: bool = True, shuffle_multiple: bool = True,
                 seed: "int | None" = None, qtype_filter: "QType | None" = None,
                 scope: "Scope | None" = None, shuffle_options: "bool | None" = None) -> None:
        if shuffle_options is not None:            # 兼容 v1.0 的单开关写法
            shuffle_single = shuffle_multiple = bool(shuffle_options)
        if scope is not None:
            qtype_filter = scope.qtype
        self.questions: list[Question] = list(questions)
        self.store = store
        self.mode = mode
        self.shuffle_single = bool(shuffle_single)
        self.shuffle_multiple = bool(shuffle_multiple)
        self.qtype_filter: "QType | None" = qtype_filter
        self._rng = random.Random(seed)
        self.order: list[int] = []
        self.cursor: int = 0
        self._items: dict[int, PracticeItem] = {}
        self.rebuild(mode)

    # ------------------------------------------------------------ 打乱开关
    def shuffle_for(self, qtype: QType) -> bool:
        """按题型决定是否打乱（判断题恒不打乱）。"""
        if qtype is QType.SINGLE:
            return self.shuffle_single
        if qtype is QType.MULTIPLE:
            return self.shuffle_multiple
        return False

    # ------------------------------------------------------------ 队列
    def rebuild(self, mode: "PracticeMode | None" = None,
                qtype_filter: "QType | None | str" = "keep") -> None:
        """重建练习队列（不清除进度）。``qtype_filter`` 传 "keep" 表示保持当前范围。"""
        if mode is not None:
            self.mode = mode
        if qtype_filter != "keep":
            self.qtype_filter = qtype_filter  # type: ignore[assignment]
        idx = list(range(len(self.questions)))
        if self.qtype_filter is not None:
            idx = [i for i in idx if self.questions[i].qtype is self.qtype_filter]
        if self.mode is PracticeMode.RANDOM:
            self._rng.shuffle(idx)
        elif self.mode is PracticeMode.WRONG:
            idx = [i for i in idx if self.store.record_of(self.questions[i]).in_wrong_book]
        elif self.mode is PracticeMode.FRESH:
            idx = [i for i in idx if not self.store.record_of(self.questions[i]).done]
        self.order = idx
        self.cursor = 0
        self._items.clear()

    # ------------------------------------------------------------ 位置
    @property
    def total(self) -> int:
        return len(self.order)

    @property
    def empty(self) -> bool:
        return not self.order

    @property
    def position(self) -> int:
        return self.cursor + 1 if self.order else 0

    def current_index(self) -> "int | None":
        if self.empty or not (0 <= self.cursor < len(self.order)):
            return None
        return self.order[self.cursor]

    def current_question(self) -> "Question | None":
        idx = self.current_index()
        return self.questions[idx] if idx is not None else None

    def current_item(self) -> "PracticeItem | None":
        idx = self.current_index()
        if idx is None:
            return None
        if idx not in self._items:
            q = self.questions[idx]
            self._items[idx] = build_item(q, self._rng, self.shuffle_for(q.qtype))
        return self._items[idx]

    def current_record(self) -> QRecord:
        q = self.current_question()
        return self.store.record_of(q) if q else QRecord()

    def advance(self) -> bool:
        if self.cursor + 1 < len(self.order):
            self.cursor += 1
            return True
        return False

    def retreat(self) -> bool:
        if self.cursor > 0:
            self.cursor -= 1
            return True
        return False

    def goto(self, position: int) -> bool:
        if 0 <= position < len(self.order):
            self.cursor = position
            return True
        return False

    def goto_question_fp(self, fingerprint: str) -> bool:
        if not fingerprint:
            return False
        for pos, idx in enumerate(self.order):
            if self.questions[idx].fingerprint == fingerprint:
                self.cursor = pos
                return True
        return False

    # ------------------------------------------------------------ 作答
    def submit(self, selected: "Iterable[str] | bool | None") -> AnswerResult:
        item = self.current_item()
        if item is None:
            raise RuntimeError("当前没有可作答的题目")
        question = item.question
        record = self.store.record_of(question)
        was_done = record.done
        correct = item.judge(selected)
        record = self.store.apply_answer(question, correct)
        return AnswerResult(correct=correct, selected=selected,
                            correct_answer=item.answer_display(),
                            selected_answer=item.selected_text(selected),
                            analysis=question.analysis, is_repeat=was_done,
                            in_wrong_book=record.in_wrong_book, record=record)

    # ------------------------------------------------------------ 统计
    def stats(self) -> dict:
        return self.store.progress.stats(self.questions)

    def scope_stats(self) -> dict:
        """当前范围的题目统计（按题型过滤后）。"""
        qs = self.questions if self.qtype_filter is None else \
            [q for q in self.questions if q.qtype is self.qtype_filter]
        return self.store.progress.stats(qs)

    # ------------------------------------------------------------ 会话持久化
    def save_position(self, extra: "dict | None" = None) -> None:
        self.store.save_session(self.mode.value, self.current_question(), self.cursor,
                                self.shuffle_single and self.shuffle_multiple,
                                extra={"shuffle_single": self.shuffle_single,
                                       "shuffle_multiple": self.shuffle_multiple,
                                       "scope": self.qtype_filter.key if self.qtype_filter else "all",
                                       **(extra or {})})

    def restore_position(self, adopt_mode: bool = True) -> bool:
        """依据已保存的会话信息恢复练习位置。

        ``adopt_mode=True``（界面默认）会连同上次的模式、范围与打乱开关一起恢复；
        ``adopt_mode=False`` 只恢复位置，保留调用方显式指定的参数。
        """
        saved = self.store.saved_session()
        if not saved:
            return False
        if adopt_mode:
            mode = PracticeMode.from_label(str(saved.get("mode", "")))
            scope = Scope.from_label(str(saved.get("scope", "all")))
            need_rebuild = mode is not self.mode or scope.qtype is not self.qtype_filter
            self.mode = mode
            self.qtype_filter = scope.qtype
            if "shuffle_single" in saved:
                self.shuffle_single = bool(saved["shuffle_single"])
            if "shuffle_multiple" in saved:
                self.shuffle_multiple = bool(saved["shuffle_multiple"])
            if need_rebuild:
                self.rebuild(mode)
            else:
                self._items.clear()
        fp = str(saved.get("last_fp", ""))
        if fp and self.goto_question_fp(fp):
            return True
        pos = int(saved.get("pos", 0) or 0)
        if 0 <= pos < len(self.order):
            self.cursor = pos
            return True
        return False


# ================================================================ 模拟考试
@dataclass
class ExamResult:
    """模拟考试成绩。"""

    paper_label: str
    blueprint: dict
    score: float
    full_score: float
    correct: int
    wrong: int
    unanswered: int
    total: int
    accuracy: float
    per_type: dict = field(default_factory=dict)     # key -> {correct,total,score,full}
    details: list = field(default_factory=list)      # 每题明细
    ts: str = ""

    def summary(self) -> str:
        return (f"{self.paper_label}卷：{self.score:g}/{self.full_score:g} 分，"
                f"正确 {self.correct}、错误 {self.wrong}、未答 {self.unanswered}，"
                f"正确率 {self.accuracy * 100:.1f}%")

    def to_dict(self) -> dict:
        return {"paper_label": self.paper_label, "blueprint": self.blueprint,
                "score": self.score, "full_score": self.full_score,
                "correct": self.correct, "wrong": self.wrong, "unanswered": self.unanswered,
                "total": self.total, "accuracy": round(self.accuracy, 6),
                "per_type": self.per_type, "ts": self.ts}


class ExamSession:
    """一场模拟考试：整卷作答 → 交卷评分（作答期间不给任何对错反馈）。"""

    def __init__(self, paper: Paper, store: ProgressStore, *,
                 shuffle_single: bool = True, shuffle_multiple: bool = True,
                 seed: "int | None" = None, scores: "dict | None" = None,
                 record_progress: bool = True) -> None:
        self.paper = paper
        self.store = store
        self.scores = dict(DEFAULT_SCORES)
        if scores:
            self.scores.update({k: float(v) for k, v in scores.items()})
        self.record_progress = record_progress
        self._rng = random.Random(seed)
        self.items: list[PracticeItem] = []
        for pq in paper.items:
            q = pq.question
            shuffle = (shuffle_single if q.qtype is QType.SINGLE
                       else shuffle_multiple if q.qtype is QType.MULTIPLE else False)
            self.items.append(build_item(q, self._rng, shuffle))
        self.answers: dict[int, set[str]] = {}
        self.submitted = False
        self.result: "ExamResult | None" = None

    # ------------------------------------------------------------ 作答
    @property
    def total(self) -> int:
        return len(self.items)

    @property
    def answered_count(self) -> int:
        return len(self.answers)

    def item(self, index: int) -> PracticeItem:
        return self.items[index]

    def answered(self, index: int) -> bool:
        return bool(self.answers.get(index))

    def set_answer(self, index: int, letters: Iterable[str]) -> None:
        if self.submitted:
            return
        value = set(letters)
        if value:
            self.answers[index] = value
        else:
            self.answers.pop(index, None)

    def toggle(self, index: int, letter: str) -> None:
        """多选：勾选/取消；单选与判断：直接设为该字母。"""
        if self.submitted:
            return
        item = self.items[index]
        if item.qtype is QType.MULTIPLE:
            current = set(self.answers.get(index, set()))
            current.symmetric_difference_update({letter})
            self.set_answer(index, current)
        else:
            self.set_answer(index, {letter})

    def clear_answer(self, index: int) -> None:
        if not self.submitted:
            self.answers.pop(index, None)

    def score_of(self, qtype: QType) -> float:
        return float(self.scores.get(qtype.key, 1.0))

    @property
    def full_score(self) -> float:
        return sum(self.score_of(it.qtype) for it in self.items)

    # ------------------------------------------------------------ 交卷
    def submit(self) -> ExamResult:
        if self.submitted and self.result is not None:
            return self.result
        per_type: dict[str, dict] = {}
        details: list[dict] = []
        score = 0.0
        correct_n = wrong_n = unanswered_n = 0
        pairs: list[tuple[Question, bool]] = []

        for i, item in enumerate(self.items):
            selected = self.answers.get(i, set())
            is_unanswered = not selected
            ok = (not is_unanswered) and item.judge(selected)
            if is_unanswered:
                unanswered_n += 1
            elif ok:
                correct_n += 1
            else:
                wrong_n += 1
            per = per_type.setdefault(item.qtype.key,
                                      {"name": item.qtype.short, "correct": 0, "total": 0,
                                       "score": 0.0, "full": 0.0})
            per["total"] += 1
            per["full"] += self.score_of(item.qtype)
            if ok:
                per["correct"] += 1
                per["score"] += self.score_of(item.qtype)
                score += self.score_of(item.qtype)
            pairs.append((item.question, ok))
            details.append({
                "number": i + 1,
                "qtype": item.qtype.value,
                "stem": item.stem,
                "correct": bool(ok),
                "unanswered": is_unanswered,
                "selected": item.selected_text(selected) if selected else "（未作答）",
                "answer": item.answer_display(),
                "answer_text": item.answer_text(),
                "analysis": item.analysis,
            })

        if self.record_progress:
            self.store.apply_answers(pairs)     # 计入练习进度（一次性落盘）
        import time

        self.result = ExamResult(
            paper_label=self.paper.label, blueprint=self.paper_blueprint_dict(),
            score=score, full_score=self.full_score, correct=correct_n, wrong=wrong_n,
            unanswered=unanswered_n, total=self.total,
            accuracy=(correct_n / self.total) if self.total else 0.0,
            per_type=per_type, details=details,
            ts=time.strftime("%Y-%m-%d %H:%M:%S"))
        self.submitted = True
        try:
            self.store.add_exam_record(self.result.to_dict())
        except Exception:
            pass
        return self.result

    def paper_blueprint_dict(self) -> dict:
        bp = PaperBlueprint()
        for it in self.items:
            bp.set(it.qtype, bp.get(it.qtype) + 1)
        return bp.to_dict()
