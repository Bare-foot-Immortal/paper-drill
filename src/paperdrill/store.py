# -*- coding: utf-8 -*-
"""进度存储：按题库持久化每道题的作答记录与练习位置。

设计要点
--------
* 记录以**题目指纹**为键，与行号/顺序无关，因此题库增删、重排、换目录后进度仍可保留；
* 文件标识 ``bank_key = 文件名 + 全库指纹摘要``；精确命中失败时按**内容重合度**继承旧进度；
* 保存采用"临时文件 + os.replace"原子替换；读取损坏文件不抛异常。

进度目录：``%APPDATA%/PaperDrill/progress/<bank_key>.json``
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from .models import Question

__all__ = ["QRecord", "ProgressStore", "progress_dir", "bank_key_of", "safe_name"]

INHERIT_THRESHOLD = 0.6      # 内容重合度达到该比例才继承旧进度
SCHEMA_VERSION = 1


def progress_dir() -> Path:
    base = os.environ.get("APPDATA") or os.environ.get("XDG_DATA_HOME")
    root = Path(base) if base else Path.home() / ".local" / "share"
    return root / "PaperDrill" / "progress"


def safe_name(text: str, max_len: int = 60) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", (text or "").strip())
    cleaned = re.sub(r"_{2,}", "_", cleaned).strip(" .")
    return (cleaned or "题库")[:max_len]


def bank_key_of(name: str, questions: Sequence[Question]) -> str:
    """题库标识 = 文件名 + 全库题目指纹摘要。"""
    digest = hashlib.sha1(
        "|".join(sorted(q.fingerprint for q in questions)).encode("utf-8")
    ).hexdigest()[:10]
    return f"{safe_name(name)}__{digest}"


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class QRecord:
    """单题作答记录。"""

    right: int = 0
    wrong: int = 0
    last: str = ""          # "right" / "wrong" / ""
    streak: int = 0         # 连续答对次数
    ts: str = ""

    @property
    def done(self) -> bool:
        return (self.right + self.wrong) > 0

    @property
    def attempts(self) -> int:
        return self.right + self.wrong

    @property
    def in_wrong_book(self) -> bool:
        """最近一次作答为错误 → 在错题本中；答对后自动移出。"""
        return self.done and self.last == "wrong"

    @property
    def mastered(self) -> bool:
        return self.last == "right"

    def apply(self, correct: bool) -> None:
        if correct:
            self.right += 1
            self.streak += 1
            self.last = "right"
        else:
            self.wrong += 1
            self.streak = 0
            self.last = "wrong"
        self.ts = _now()

    def to_dict(self) -> dict:
        return {"right": self.right, "wrong": self.wrong, "last": self.last,
                "streak": self.streak, "ts": self.ts}

    @classmethod
    def from_dict(cls, data: dict) -> "QRecord":
        return cls(right=int(data.get("right", 0)), wrong=int(data.get("wrong", 0)),
                   last=str(data.get("last", "")), streak=int(data.get("streak", 0)),
                   ts=str(data.get("ts", "")))


@dataclass
class BankProgress:
    """一个题库的完整进度（内存模型 + 序列化）。"""

    bank_key: str
    bank_name: str = ""
    question_total: int = 0
    records: dict[str, QRecord] = field(default_factory=dict)
    session: dict = field(default_factory=dict)   # {"mode":..., "last_fp":..., "pos":int, ...}
    exams: list = field(default_factory=list)     # 模拟考试成绩单（最近 30 次）
    created: str = ""
    updated: str = ""
    inherited_from: str = ""                      # 非空表示由旧进度继承而来

    # ------------------------------------------------------------ 统计
    def record_of(self, question: Question) -> QRecord:
        return self.records.get(question.fingerprint, QRecord())

    def get(self, fingerprint: str) -> QRecord:
        return self.records.get(fingerprint, QRecord())

    def stats(self, questions: Sequence[Question]) -> dict:
        done = right = wrong = wrong_book = attempts = 0
        for q in questions:
            rec = self.records.get(q.fingerprint)
            if rec is None or not rec.done:
                continue
            done += 1
            attempts += rec.attempts
            right += rec.right
            wrong += rec.wrong
            if rec.in_wrong_book:
                wrong_book += 1
        accuracy = (right / attempts) if attempts else 0.0
        return {"total": len(questions), "done": done, "right": right, "wrong": wrong,
                "attempts": attempts, "wrong_book": wrong_book,
                "accuracy": accuracy, "done_rate": (done / len(questions)) if questions else 0.0}

    # ------------------------------------------------------------ 记录
    def apply_answer(self, question: Question, correct: bool) -> QRecord:
        fp = question.fingerprint
        rec = self.records.setdefault(fp, QRecord())
        rec.apply(correct)
        self.updated = _now()
        return rec

    def clear_wrong_book(self, questions: Sequence[Question]) -> int:
        """清空错题标记（保留历史统计），返回清理条数。"""
        count = 0
        for q in questions:
            rec = self.records.get(q.fingerprint)
            if rec is not None and rec.in_wrong_book:
                rec.last = "right" if rec.right > 0 else ""
                count += 1
        self.updated = _now()
        return count

    def reset(self) -> None:
        self.records.clear()
        self.session = {}
        self.exams.clear()
        self.updated = _now()

    def prune(self, questions: Sequence[Question]) -> int:
        """删除题库中已不存在的题目的记录（默认不调用，仅在显式清理时使用）。"""
        alive = {q.fingerprint for q in questions}
        removed = [fp for fp in self.records if fp not in alive]
        for fp in removed:
            del self.records[fp]
        if removed:
            self.updated = _now()
        return len(removed)

    # ------------------------------------------------------------ 模拟考试成绩
    def add_exam_record(self, record: dict, keep: int = 30) -> None:
        """追加一条模拟考试成绩（最多保留 keep 条）。"""
        self.exams.append(dict(record))
        if len(self.exams) > keep:
            del self.exams[:-keep]
        self.updated = _now()

    # ------------------------------------------------------------ 序列化
    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA_VERSION,
            "app": "PaperDrill",
            "bank_key": self.bank_key,
            "bank_name": self.bank_name,
            "question_total": self.question_total,
            "created": self.created,
            "updated": self.updated,
            "inherited_from": self.inherited_from,
            "records": {fp: rec.to_dict() for fp, rec in self.records.items() if rec.done},
            "session": self.session,
            "exams": self.exams,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BankProgress":
        prog = cls(bank_key=str(data.get("bank_key", "")),
                   bank_name=str(data.get("bank_name", "")),
                   question_total=int(data.get("question_total", 0)),
                   created=str(data.get("created", "")),
                   updated=str(data.get("updated", "")),
                   inherited_from=str(data.get("inherited_from", "")))
        raw = data.get("records") or {}
        if isinstance(raw, dict):
            for fp, rec in raw.items():
                if isinstance(rec, dict):
                    prog.records[str(fp)] = QRecord.from_dict(rec)
        sess = data.get("session") or {}
        prog.session = sess if isinstance(sess, dict) else {}
        exams = data.get("exams") or []
        prog.exams = [e for e in exams if isinstance(e, dict)] if isinstance(exams, list) else []
        return prog

    def summary_line(self, questions: Sequence[Question]) -> str:
        s = self.stats(questions)
        return (f"{s['done']}/{s['total']} 题已练　正确率 {s['accuracy'] * 100:.1f}%　"
                f"错题 {s['wrong_book']} 道　（更新于 {self.updated or '—'}）")


class ProgressStore:
    """进度读写入口（一个实例对应一个题库）。"""

    def __init__(self, bank: BankProgress, directory: "Path | None" = None) -> None:
        self.progress = bank
        self.dir = Path(directory) if directory else progress_dir()

    # ------------------------------------------------------------ 属性
    @property
    def path(self) -> Path:
        return self.dir / f"{self.progress.bank_key}.json"

    @property
    def records(self) -> dict[str, QRecord]:
        return self.progress.records

    def record_of(self, question: Question) -> QRecord:
        return self.progress.record_of(question)

    # ------------------------------------------------------------ 加载
    @classmethod
    def load_for(cls, bank_name: str, questions: Sequence[Question],
                 directory: "Path | None" = None) -> "ProgressStore":
        """按题库加载进度：精确命中 → 内容继承 → 新建。"""
        directory = Path(directory) if directory else progress_dir()
        key = bank_key_of(bank_name, questions)
        exact = directory / f"{key}.json"
        if exact.exists():
            data = _read_json(exact)
            if data:
                prog = BankProgress.from_dict(data)
                prog.bank_key = key
                prog.bank_name = prog.bank_name or bank_name
                prog.question_total = len(questions)
                prog.inherited_from = ""
                return cls(prog, directory)
        # 内容继承
        inherited = cls._find_inheritable(directory, questions)
        if inherited is not None:
            src_path, prog = inherited
            prog.bank_key = key
            prog.bank_name = bank_name
            prog.question_total = len(questions)
            prog.inherited_from = src_path.name
            store = cls(prog, directory)
            store.save()                      # 立即另存为新标识，旧文件保留
            return store
        return cls(BankProgress(bank_key=key, bank_name=bank_name,
                                question_total=len(questions), created=_now()), directory)

    @staticmethod
    def _find_inheritable(directory: Path, questions: Sequence[Question]):
        """在与当前题库内容重合度最高的旧进度文件中寻找可继承项。"""
        fps = {q.fingerprint for q in questions}
        best = None
        if not directory.exists():
            return None
        for path in sorted(directory.glob("*.json")):
            data = _read_json(path)
            if not data:
                continue
            prog = BankProgress.from_dict(data)
            if not prog.records:
                continue
            overlap = len(set(prog.records) & fps) / len(prog.records)
            if overlap >= INHERIT_THRESHOLD and (best is None or overlap > best[0]):
                best = (overlap, path, prog)
        if best is None:
            return None
        return best[1], best[2]

    # ------------------------------------------------------------ 写入
    def apply_answer(self, question: Question, correct: bool) -> QRecord:
        """记录一次作答并**立即落盘**（练习进度实时保留）。"""
        rec = self.progress.apply_answer(question, correct)
        try:
            self.save()
        except OSError:
            pass
        return rec

    def apply_answers(self, pairs: Sequence[tuple[Question, bool]]) -> None:
        """批量记录作答，只落盘一次（模拟考试交卷时使用）。"""
        for question, correct in pairs:
            self.progress.apply_answer(question, correct)
        try:
            self.save()
        except OSError:
            pass

    def add_exam_record(self, record: dict) -> None:
        self.progress.add_exam_record(record)
        try:
            self.save()
        except OSError:
            pass

    def exam_history(self) -> list:
        """历史成绩，最新在前。"""
        return list(reversed(self.progress.exams))

    def stats(self, questions: Sequence[Question]) -> dict:
        return self.progress.stats(questions)

    def save(self) -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        if not self.progress.created:
            self.progress.created = _now()
        self.progress.updated = _now()
        target = self.path
        tmp = target.with_suffix(".json.tmp")
        payload = json.dumps(self.progress.to_dict(), ensure_ascii=False, indent=2)
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, target)          # 原子替换，避免半截文件
        return target

    def reset(self) -> None:
        self.progress.reset()
        self.save()

    def delete(self) -> bool:
        try:
            if self.path.exists():
                self.path.unlink()
            return True
        except OSError:
            return False

    # ------------------------------------------------------------ 会话位置
    def save_session(self, mode: str, last_question: "Question | None", pos: int,
                     shuffle: bool, extra: "dict | None" = None) -> None:
        self.progress.session = {
            "mode": mode,
            "last_fp": last_question.fingerprint if last_question else "",
            "pos": int(pos),
            "shuffle": bool(shuffle),
            "ts": _now(),
        }
        if extra:
            self.progress.session.update(extra)
        self.save()

    def saved_session(self) -> dict:
        return dict(self.progress.session or {})

    # ------------------------------------------------------------ 目录级操作
    @staticmethod
    def list_all(directory: "Path | None" = None) -> list[dict]:
        """列出全部题库进度摘要（供进度管理界面使用）。"""
        directory = Path(directory) if directory else progress_dir()
        out: list[dict] = []
        if not directory.exists():
            return out
        for path in sorted(directory.glob("*.json")):
            data = _read_json(path)
            if not data:
                out.append({"key": path.stem, "name": path.stem, "broken": True,
                            "path": str(path), "done": 0, "total": 0, "wrong": 0, "updated": ""})
                continue
            prog = BankProgress.from_dict(data)
            right = sum(r.right for r in prog.records.values())
            wrong = sum(r.wrong for r in prog.records.values())
            attempts = right + wrong
            out.append({
                "key": prog.bank_key or path.stem,
                "name": prog.bank_name or path.stem,
                "path": str(path),
                "done": len(prog.records),
                "total": prog.question_total,
                "right": right,
                "wrong": wrong,
                "wrong_book": sum(1 for r in prog.records.values() if r.in_wrong_book),
                "accuracy": (right / attempts) if attempts else 0.0,
                "exams": len(prog.exams),
                "updated": prog.updated,
                "broken": False,
            })
        return out

    @staticmethod
    def delete_by_key(key: str, directory: "Path | None" = None) -> bool:
        directory = Path(directory) if directory else progress_dir()
        path = directory / f"{key}.json"
        try:
            if path.exists():
                path.unlink()
            return True
        except OSError:
            return False


def _read_json(path: Path) -> "dict | None":
    """读取 JSON，损坏时返回 None（不抛异常）。"""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
