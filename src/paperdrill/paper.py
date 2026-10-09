# -*- coding: utf-8 -*-
"""试卷蓝图与轮次覆盖抽题（需求 2、3）。

算法（与组卷版 PaperForge 一致，此处只保留"抽题"部分，不做任何导出）:

1. 按题型各自维护一个牌堆（题库洗牌后的顺序列表）；
2. 第 i 张卷从牌堆顺序切出第 i 块，块长 = 该题型每卷配额 k；
3. 牌堆取尽后进入补题：剩余题目先全部放入，差额从**本轮已出现过**的
   同题型题目中随机补足，使每张卷子题量严格等于配额；
4. 一轮张数 N = max(⌈该题型题库量 ÷ 该题型配额⌉)，因此一轮结束后
   每种题型的题库都被完整覆盖。
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from .models import OPTION_LABELS, QType, Question

__all__ = ["PaperBlueprint", "PaperQuestion", "Paper", "PaperRound",
           "GenerationError", "generate_round", "min_round_length", "group_by_type"]


class GenerationError(Exception):
    """蓝图或题库不满足生成条件。"""


@dataclass
class PaperBlueprint:
    """一张试卷的题型配额（需求 2）。"""

    single: int = 20
    multiple: int = 10
    judge: int = 10

    def get(self, qtype: QType) -> int:
        return {QType.SINGLE: self.single, QType.MULTIPLE: self.multiple,
                QType.JUDGE: self.judge}[qtype]

    def set(self, qtype: QType, value: int) -> None:
        if qtype is QType.SINGLE:
            self.single = int(value)
        elif qtype is QType.MULTIPLE:
            self.multiple = int(value)
        else:
            self.judge = int(value)

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
    def from_dict(cls, data: dict) -> "PaperBlueprint":
        return cls(int(data.get("single", 0)), int(data.get("multiple", 0)), int(data.get("judge", 0)))


@dataclass
class PaperQuestion:
    """试卷中的一道题。"""

    question: Question
    reused: bool = False        # True 表示"题目取尽后从本轮已出现题目中补抽"

    @property
    def qtype(self) -> QType:
        return self.question.qtype


@dataclass
class Paper:
    """一张试卷。"""

    seq: int                                  # 全局序号（1 起）
    label: str                                # 卷标 A/B/C…
    items: list[PaperQuestion] = field(default_factory=list)

    @property
    def name(self) -> str:
        return f"{self.label}卷"

    @property
    def total(self) -> int:
        return len(self.items)

    def of_type(self, qtype: QType) -> list[PaperQuestion]:
        return [it for it in self.items if it.qtype is qtype]

    def count_of(self, qtype: QType) -> int:
        return len(self.of_type(qtype))

    @property
    def reused_count(self) -> int:
        return sum(1 for it in self.items if it.reused)


@dataclass
class PaperRound:
    """一轮试卷及覆盖自检结果。"""

    papers: list[Paper] = field(default_factory=list)
    blueprint: PaperBlueprint = field(default_factory=PaperBlueprint)
    round_length: int = 0
    coverage: dict[str, tuple[int, int]] = field(default_factory=dict)
    coverage_ok: bool = True
    uncovered: int = 0
    warnings: list[str] = field(default_factory=list)
    seed: int = 0
    bank_total: int = 0

    @property
    def paper_count(self) -> int:
        return len(self.papers)

    def summary(self) -> str:
        got = sum(v[0] for v in self.coverage.values())
        total = sum(v[1] for v in self.coverage.values())
        flag = "覆盖完整" if self.coverage_ok else f"缺 {total - got} 题"
        return (f"一轮 {self.paper_count} 张，题库 {total} 题已覆盖 {got} 题（{flag}）")


def group_by_type(questions: list[Question]) -> dict[QType, list[Question]]:
    groups: dict[QType, list[Question]] = {QType.SINGLE: [], QType.MULTIPLE: [], QType.JUDGE: []}
    for q in questions:
        groups[q.qtype].append(q)
    return groups


def min_round_length(questions: list[Question], blueprint: PaperBlueprint) -> int:
    """覆盖题库全部题目所需的最少张数（轮长）。"""
    groups = group_by_type(questions)
    need = 1
    for qtype, quota in blueprint.items():
        if quota <= 0:
            continue
        need = max(need, math.ceil(len(groups[qtype]) / quota))
    return need


def _label_for(index: int) -> str:
    if index < 26:
        return OPTION_LABELS[index]
    return str(index + 1)


def generate_round(questions: list[Question], blueprint: PaperBlueprint,
                   round_length: "int | None" = None, seed: "int | None" = None) -> PaperRound:
    """生成一轮试卷（需求 3）。"""
    bank = list(questions)
    if not bank:
        raise GenerationError("题库为空，无法生成试卷。")
    if blueprint.total <= 0:
        raise GenerationError("每张试卷的题目数量为 0，请至少为一种题型设置数量。")

    groups = group_by_type(bank)
    active = [(t, k) for t, k in blueprint.items() if k > 0]
    for qtype, quota in active:
        if not groups[qtype]:
            raise GenerationError(f"试卷要求「{qtype.value}」{quota} 题，但题库中没有{qtype.value}。")

    auto_n = min_round_length(bank, blueprint)
    n = int(round_length or auto_n)
    if n <= 0:
        n = auto_n
    if seed is None:
        seed = random.SystemRandom().randrange(1, 2 ** 31 - 1)
    rng = random.Random(seed)

    warnings: list[str] = []
    if n < auto_n:
        warnings.append(f"一轮设置为 {n} 张，少于覆盖题库所需的 {auto_n} 张，无法覆盖全部题目。")
    for qtype, quota in active:
        if len(groups[qtype]) < quota:
            warnings.append(f"题库中{qtype.value}仅 {len(groups[qtype])} 题，少于每卷 {quota} 题，"
                            f"卷内将出现重复题目。")

    # 每题型 → 每张卷的取题结果
    draws: dict[QType, list[list[tuple[Question, bool]]]] = {}
    seen_union: dict[QType, set[str]] = {}
    for qtype, quota in active:
        deck = list(groups[qtype])
        rng.shuffle(deck)
        per_paper: list[list[tuple[Question, bool]]] = []
        for i in range(n):
            start = i * quota
            chunk = [(q, False) for q in deck[start:start + quota]]
            if len(chunk) < quota:
                pool = deck[:start]                     # 本轮已出现过的题目
                need = quota - len(chunk)
                if pool:
                    take = min(need, len(pool))
                    for q in rng.sample(pool, take):
                        chunk.append((q, True))
                    need -= take
                while need > 0:                          # 题库总量 < 配额
                    chunk.append((rng.choice(deck), True))
                    need -= 1
            per_paper.append(chunk)
        draws[qtype] = per_paper
        seen_union[qtype] = {q.qid for chunk in per_paper for q, _ in chunk}

    papers: list[Paper] = []
    for i in range(n):
        items: list[PaperQuestion] = []
        for qtype, _quota in active:                     # 按 单选→多选→判断 排列
            items.extend(PaperQuestion(question=q, reused=reused) for q, reused in draws[qtype][i])
        papers.append(Paper(seq=i + 1, label=_label_for(i), items=items))

    coverage: dict[str, tuple[int, int]] = {}
    coverage_ok = True
    uncovered = 0
    for qtype, _quota in active:
        total = len(groups[qtype])
        seen = len(seen_union[qtype])
        coverage[qtype.key] = (seen, total)
        if seen < total:
            coverage_ok = False
            uncovered += total - seen

    return PaperRound(papers=papers, blueprint=blueprint, round_length=n, coverage=coverage,
                      coverage_ok=coverage_ok, uncovered=uncovered, warnings=warnings,
                      seed=seed, bank_total=len(bank))
