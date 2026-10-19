# -*- coding: utf-8 -*-
"""进度存储：按题库持久化每道题的作答记录与练习位置。

设计要点
--------
* 记录以**题目指纹**为键，与行号/顺序无关，因此题库增删、重排、换目录后进度仍可保留；
* 文件标识 ``bank_key = 文件名 + 全库指纹摘要``；精确命中失败时按**内容重合度**继承旧进度；
* **题库删减**（``excluded``）也保存在同一份进度文件里，剔除的题不参与练习与组卷；
* 保存采用"临时文件 + os.replace"原子替换；读取损坏文件不抛异常。

进度目录：``%APPDATA%/PaperDrill/progress/<bank_key>.json``
题库库（最近使用的题库）：``%APPDATA%/PaperDrill/library.json``
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

__all__ = ["QRecord", "ProgressStore", "BankLibrary", "library_path", "progress_dir",
           "bank_key_of", "safe_name", "SESSION_WINDOW"]

INHERIT_THRESHOLD = 0.6      # 内容重合度达到该比例才继承旧进度
SESSION_WINDOW = 4           # 会话位置窗口：当前位置 + 其后 3 题（按指纹依次兜底）


def _as_int(value: object, default: int = 0) -> int:
    """把任意值安全转为 int（进度文件被人为编辑/损坏时不让整个加载失败）。"""
    try:
        return int(value)          # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return default
SCHEMA_VERSION = 2


def progress_dir() -> Path:
    base = os.environ.get("APPDATA") or os.environ.get("XDG_DATA_HOME")
    root = Path(base) if base else Path.home() / ".local" / "share"
    return root / "PaperDrill" / "progress"


def library_path() -> Path:
    """题库库文件（最近使用的题库列表），与进度文件分开放。"""
    return progress_dir().parent / "library.json"


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
    # 「清空错题本」只把题目移出错题本，不篡改"最近一次作答结果"（审计 P3-06）。
    # 旧进度文件没有该字段 → 默认 False，行为与旧版一致。
    wrong_cleared: bool = False

    @property
    def done(self) -> bool:
        return (self.right + self.wrong) > 0

    @property
    def attempts(self) -> int:
        return self.right + self.wrong

    @property
    def in_wrong_book(self) -> bool:
        """最近一次作答为错误、且未被「清空错题本」移出 → 在错题本中。"""
        return self.done and self.last == "wrong" and not self.wrong_cleared

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
        self.wrong_cleared = False
        self.ts = _now()

    def to_dict(self) -> dict:
        return {"right": self.right, "wrong": self.wrong, "last": self.last,
                "streak": self.streak, "ts": self.ts,
                "wrong_cleared": bool(self.wrong_cleared)}

    @classmethod
    def from_dict(cls, data: dict) -> "QRecord":
        return cls(right=_as_int(data.get("right"), 0), wrong=_as_int(data.get("wrong"), 0),
                   last=str(data.get("last", "") or ""), streak=_as_int(data.get("streak"), 0),
                   ts=str(data.get("ts", "") or ""),
                   wrong_cleared=bool(data.get("wrong_cleared", False)))


@dataclass
class BankProgress:
    """一个题库的完整进度（内存模型 + 序列化）。"""

    bank_key: str
    bank_name: str = ""
    question_total: int = 0
    records: dict[str, QRecord] = field(default_factory=dict)
    session: dict = field(default_factory=dict)   # {"mode":..., "last_fp":..., "pos":int, ...}
    exams: list = field(default_factory=list)     # 模拟考试成绩单（最近 30 次）
    excluded: dict = field(default_factory=dict)  # 题库删减：{指纹: {"stem":..., "ts":...}}
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
        """清空错题标记（保留历史统计与"最近一次作答结果"），返回清理条数。"""
        count = 0
        for q in questions:
            rec = self.records.get(q.fingerprint)
            if rec is not None and rec.in_wrong_book:
                rec.wrong_cleared = True
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

    # ------------------------------------------------------------ 题库删减
    def is_excluded(self, question: Question) -> bool:
        return question.fingerprint in self.excluded

    def active_questions(self, questions: Sequence[Question]) -> list[Question]:
        """过滤掉已删减的题目（题库删减后参与练习/组卷的题目集）。"""
        if not self.excluded:
            return list(questions)
        return [q for q in questions if q.fingerprint not in self.excluded]

    def excluded_questions(self, questions: Sequence[Question]) -> list[Question]:
        """在当前题库中找出已被删减的题目（按题库原顺序）。"""
        return [q for q in questions if q.fingerprint in self.excluded]

    def exclude(self, questions: Iterable[Question], stem_len: int = 80) -> int:
        """把题目加入删减集；返回新增加的条数（已在集合中的不重复计数）。"""
        added = 0
        for q in questions:
            fp = q.fingerprint
            if fp in self.excluded:
                continue
            self.excluded[fp] = {"stem": (q.stem or "")[:stem_len], "ts": _now()}
            added += 1
        if added:
            self.updated = _now()
        return added

    def include(self, questions: Iterable[Question]) -> int:
        """把题目从删减集里恢复；返回实际恢复的条数。"""
        removed = 0
        for q in questions:
            if self.excluded.pop(q.fingerprint, None) is not None:
                removed += 1
        if removed:
            self.updated = _now()
        return removed

    def clear_excluded(self) -> int:
        """一键恢复全部删减；返回恢复条数。"""
        count = len(self.excluded)
        if count:
            self.excluded.clear()
            self.updated = _now()
        return count

    def prune_excluded(self, questions: Sequence[Question]) -> int:
        """清理题库中已不存在的剔除记录（题库换版后避免无限累积）。"""
        alive = {q.fingerprint for q in questions}
        stale = [fp for fp in self.excluded if fp not in alive]
        for fp in stale:
            del self.excluded[fp]
        if stale:
            self.updated = _now()
        return len(stale)

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
            "excluded": {fp: dict(info) for fp, info in self.excluded.items()},
            "session": self.session,
            "exams": self.exams,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BankProgress":
        """从 JSON 构造进度；**逐字段容错**，任何非法字段都不应让加载失败。"""
        if not isinstance(data, dict):
            data = {}
        prog = cls(bank_key=str(data.get("bank_key", "") or ""),
                   bank_name=str(data.get("bank_name", "") or ""),
                   question_total=_as_int(data.get("question_total"), 0),
                   created=str(data.get("created", "") or ""),
                   updated=str(data.get("updated", "") or ""),
                   inherited_from=str(data.get("inherited_from", "") or ""))
        raw = data.get("records")
        if isinstance(raw, dict):
            for fp, rec in raw.items():
                if not isinstance(rec, dict):
                    continue
                try:
                    prog.records[str(fp)] = QRecord.from_dict(rec)
                except Exception:                      # 单条记录损坏 → 跳过，不影响其它
                    continue
        sess = data.get("session")
        prog.session = sess if isinstance(sess, dict) else {}
        exams = data.get("exams")
        prog.exams = [e for e in exams if isinstance(e, dict)] if isinstance(exams, list) else []
        # 题库删减（schema 2 新增）：旧文件没有该字段 → 空集，直接可用
        excluded = data.get("excluded")
        if isinstance(excluded, dict):
            for fp, info in excluded.items():
                if not isinstance(fp, str) or not fp:
                    continue
                prog.excluded[fp] = dict(info) if isinstance(info, dict) else {}
        elif isinstance(excluded, list):                   # 容忍手写成列表的旧格式
            prog.excluded = {str(fp): {} for fp in excluded if isinstance(fp, str) and fp}
        return prog

    def summary_line(self, questions: Sequence[Question]) -> str:
        s = self.stats(questions)
        cut = f"　已删减 {len(self.excluded)} 题" if self.excluded else ""
        return (f"{s['done']}/{s['total']} 题已练　正确率 {s['accuracy'] * 100:.1f}%　"
                f"错题 {s['wrong_book']} 道{cut}　（更新于 {self.updated or '—'}）")


class ProgressStore:
    """进度读写入口（一个实例对应一个题库）。"""

    def __init__(self, bank: BankProgress, directory: "Path | None" = None) -> None:
        self.progress = bank
        self.dir = Path(directory) if directory else progress_dir()
        self.last_save_error = ""      # 非空表示最近一次落盘失败（界面据此提示用户）
        # 上次成功落盘时文件里的 updated/文件指纹：用于检测"另一个进程改过文件"并合并写入
        self._disk_updated = str(getattr(bank, "updated", "") or "")
        self._disk_stat = self._stat_target()

    def _stat_target(self) -> "tuple[int, int] | None":
        try:
            st = self.path.stat()
            return (int(st.st_mtime_ns), int(st.st_size))
        except OSError:
            return None

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
            if data is None:
                # 文件损坏/编码异常：先备份，避免随后写入空进度把可恢复内容覆盖掉
                try:
                    backup = exact.with_name(
                        f"{exact.name}.bad-{time.strftime('%Y%m%d%H%M%S')}")
                    if not backup.exists():
                        exact.replace(backup)
                except OSError:
                    pass
            elif isinstance(data, dict):
                try:
                    prog = BankProgress.from_dict(data)
                except Exception:                      # 极端损坏 → 按无进度处理
                    prog = None
                if prog is not None:
                    prog.bank_key = key
                    prog.bank_name = prog.bank_name or bank_name
                    prog.question_total = len(questions)
                    prog.prune(questions)
                    # 改名往返/连续改名：同内容可能留下多份文件，选"更新/更全"的进度合并，
                    # 避免改回旧文件名后看到更少的记录（审计 P2-04）。
                    src = cls._find_inheritable(directory, questions)
                    if (src is not None and src[0].resolve() != exact.resolve()
                            and getattr(src[1], "inherited_from", "") == exact.name):
                        # 只合并"由当前文件改名/继承而来"的兄弟文件；同内容的不同题库
                        # （例如 A库/B库 题目相同）绝不能互相污染（保持多题库隔离）。
                        other = src[1]
                        richness = lambda p: (  # noqa: E731 - 局部排序键，保持可读
                            str(p.updated or ""),
                            sum(r.attempts for r in p.records.values()),
                            len(p.records))
                        if richness(other) > richness(prog):
                            cls._merge_progress(prog, other)
                            prog.prune(questions)
                    return cls(prog, directory)
        # 内容继承
        inherited = cls._find_inheritable(directory, questions)
        if inherited is not None:
            src_path, prog = inherited
            prog.bank_key = key
            prog.bank_name = bank_name
            prog.question_total = len(questions)
            prog.inherited_from = src_path.name
            # 题库删减同样跟随题库内容继承（只保留在新题库中仍能命中的指纹）
            alive = {q.fingerprint for q in questions}
            prog.excluded = {fp: info for fp, info in prog.excluded.items() if fp in alive}
            # 只保留当前题库还能命中的记录，避免"1 题新库继承 30 条幽灵记录"（P2-06）
            prog.prune(questions)
            store = cls(prog, directory)
            store.save()                      # 立即另存为新标识，旧文件保留
            return store
        return cls(BankProgress(bank_key=key, bank_name=bank_name,
                                question_total=len(questions), created=_now()), directory)

    @staticmethod
    def _merge_progress(base: BankProgress, other: BankProgress) -> None:
        """把 ``other`` 里的记录/删减/成绩并入 ``base``（同一指纹取 ts 更新者）。"""
        for fp, rec in other.records.items():
            current = base.records.get(fp)
            if current is None:
                base.records[fp] = QRecord.from_dict(rec.to_dict())
            elif (rec.ts or "") > (current.ts or "") or (
                    rec.ts == current.ts and rec.attempts > current.attempts):
                base.records[fp] = QRecord.from_dict(rec.to_dict())
        base.excluded.update(other.excluded)
        seen = {str(e.get("ts", "")) + str(e.get("paper_label", "")) for e in base.exams}
        for exam in other.exams:
            key = str(exam.get("ts", "")) + str(exam.get("paper_label", ""))
            if key not in seen:
                base.exams.append(dict(exam))
                seen.add(key)
        base.exams.sort(key=lambda e: str(e.get("ts", "")))
        if len(base.exams) > 30:
            del base.exams[:-30]
        if (other.updated or "") > (base.updated or ""):
            base.updated = other.updated
            if other.session:
                base.session = dict(other.session)

    @staticmethod
    def _find_inheritable(directory: Path, questions: Sequence[Question]):
        """在与当前题库内容重合度最高的旧进度文件中寻找可继承项。"""
        fps = {q.fingerprint for q in questions}
        best = None
        if not directory.exists():
            return None
        for path in sorted(directory.glob("*.json")):
            data = _read_json(path)
            if not isinstance(data, dict):
                continue
            try:
                prog = BankProgress.from_dict(data)
            except Exception:                          # 单个坏文件不得影响其它题库
                continue
            if not prog.records:
                continue
            common = len(set(prog.records) & fps)
            # 分母取"旧记录数 / 新题库题数"中较小者：题库删题或扩题时都能正确判定为同一题库
            denominator = max(1, min(len(prog.records), len(fps)))
            overlap = common / denominator
            if overlap < INHERIT_THRESHOLD:
                continue
            # 重合度相同时取 updated 更新、作答次数更多的文件（审计 P2-04）
            score = (overlap, str(prog.updated or ""), sum(r.attempts for r in prog.records.values()))
            if best is None or score > best[0]:
                best = (score, path, prog)
        if best is None:
            return None
        return best[1], best[2]

    # ------------------------------------------------------------ 写入
    def _try_save(self) -> bool:
        """尝试落盘；失败时记录原因（不抛异常），供界面提示"进度未能保存"。"""
        try:
            self.save()
            self.last_save_error = ""
            return True
        except Exception as exc:                       # OSError / 权限 / 路径异常等
            self.last_save_error = f"{type(exc).__name__}: {exc}"
            return False

    def apply_answer(self, question: Question, correct: bool) -> QRecord:
        """记录一次作答并**立即落盘**（练习进度实时保留）。"""
        rec = self.progress.apply_answer(question, correct)
        self._try_save()
        return rec

    def apply_answers(self, pairs: Sequence[tuple[Question, bool]]) -> None:
        """批量记录作答，只落盘一次（模拟考试交卷时使用）。"""
        for question, correct in pairs:
            self.progress.apply_answer(question, correct)
        self._try_save()

    def add_exam_record(self, record: dict) -> bool:
        """追加一条成绩并落盘；返回是否保存成功（失败原因写入 last_save_error）。"""
        self.progress.add_exam_record(record)
        return self._try_save()

    def exam_history(self) -> list:
        """历史成绩，最新在前。"""
        return list(reversed(self.progress.exams))

    def stats(self, questions: Sequence[Question]) -> dict:
        return self.progress.stats(questions)

    # ------------------------------------------------------------ 题库删减
    def active_questions(self, questions: Sequence[Question]) -> list[Question]:
        return self.progress.active_questions(questions)

    def excluded_questions(self, questions: Sequence[Question]) -> list[Question]:
        return self.progress.excluded_questions(questions)

    def is_excluded(self, question: Question) -> bool:
        return self.progress.is_excluded(question)

    def exclude(self, questions: Iterable[Question]) -> int:
        added = self.progress.exclude(questions)
        self._try_save()
        return added

    def include(self, questions: Iterable[Question]) -> int:
        removed = self.progress.include(questions)
        self._try_save()
        return removed

    def clear_excluded(self) -> int:
        count = self.progress.clear_excluded()
        self._try_save()
        return count

    def save(self) -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        if not self.progress.created:
            self.progress.created = _now()
        self.progress.updated = _now()
        target = self.path
        # 多进程并发：若磁盘文件在本进程上次落盘后又被别的进程改过，先按指纹合并，
        # 避免用旧快照整文件覆盖掉另一进程已保存的作答（审计 P2-05）。
        current_stat = self._stat_target()
        if target.exists() and current_stat != self._disk_stat:
            disk_data = _read_json(target)
            if isinstance(disk_data, dict):
                try:
                    disk = BankProgress.from_dict(disk_data)
                except Exception:
                    disk = None
                if disk is not None and (disk.records or disk.exams or disk.excluded):
                    self._merge_progress(self.progress, disk)
                    self.progress.updated = _now()
        tmp = target.with_suffix(f".json.{os.getpid()}.tmp")
        payload = json.dumps(self.progress.to_dict(), ensure_ascii=False, indent=2)
        try:
            tmp.write_text(payload, encoding="utf-8")
            os.replace(tmp, target)          # 原子替换，避免半截文件
        finally:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
        self._disk_updated = self.progress.updated
        self._disk_stat = self._stat_target()
        return target

    def reset(self) -> None:
        """重置进度；落盘失败时回滚内存状态，避免"界面已清空、文件仍旧"（P2-07）。"""
        snapshot = self.progress.to_dict()
        self.progress.reset()
        try:
            self.save()
        except Exception:
            self.progress = BankProgress.from_dict(snapshot)
            raise

    def delete(self) -> bool:
        try:
            if self.path.exists():
                self.path.unlink()
            self._disk_updated = ""
            self._disk_stat = None
            return True
        except OSError:
            return False

    # ------------------------------------------------------------ 会话位置
    def save_session(self, mode: str, last_question: "Question | None", pos: int,
                     shuffle: bool, extra: "dict | None" = None,
                     window: "Sequence[Question] | None" = None,
                     positions: "dict | None" = None) -> None:
        """保存会话位置。

        ``window`` 为**导航窗口**（当前位置起的若干道题），按顺序落盘到 ``pos_fps``。
        只靠 ``pos``（序号）在随机/只练未做模式下会错位，恢复时必须以指纹为准。

        ``positions`` 为**按（模式, 范围）组合键分别记忆**的位置表：
        ``{组合键: {"last_fp": str, "pos_fps": [str], "pos": int, "ts": str}}``。
        传 ``None`` 表示沿用旧 session 里已有的 ``positions``——这样其它直接调用
        ``save_session`` 的代码不会把手写/已有的位置表抹掉。顶层字段保持原样，
        旧版本与旧测试仍按 ``last_fp`` / ``pos`` 读取。
        """
        fps = [q.fingerprint for q in (window or []) if q is not None]
        if not fps and last_question is not None:
            fps = [last_question.fingerprint]
        old = self.progress.session if isinstance(self.progress.session, dict) else {}
        if positions is None:
            kept = old.get("positions")
            positions = dict(kept) if isinstance(kept, dict) else {}
        session = {
            "mode": mode,
            "last_fp": last_question.fingerprint if last_question else (fps[0] if fps else ""),
            "pos_fps": fps,
            "pos": int(pos),
            "shuffle": bool(shuffle),
            "ts": _now(),
        }
        if extra:
            session.update(extra)
        if isinstance(positions, dict) and positions:
            session["positions"] = dict(positions)
        self.progress.session = session
        self._try_save()

    def saved_session(self) -> dict:
        return dict(self.progress.session or {})

    # ------------------------------------------------------------ 目录级操作
    @staticmethod
    def _empty_row(path: Path) -> dict:
        """损坏进度文件的统一行结构（字段与正常行一致，CLI/界面可安全读取）。"""
        return {"key": path.stem, "name": path.stem, "broken": True,
                "path": str(path), "done": 0, "total": 0, "right": 0, "wrong": 0,
                "wrong_book": 0, "accuracy": 0.0, "exams": 0, "excluded": 0,
                "active": 0, "updated": ""}

    @classmethod
    def list_all(cls, directory: "Path | None" = None) -> list[dict]:
        """列出全部题库进度摘要（供进度管理界面使用）。"""
        directory = Path(directory) if directory else progress_dir()
        out: list[dict] = []
        if not directory.exists():
            return out
        for path in sorted(directory.glob("*.json")):
            data = _read_json(path)
            if not isinstance(data, dict):
                out.append(cls._empty_row(path))
                continue
            try:
                prog = BankProgress.from_dict(data)
            except Exception:
                out.append(cls._empty_row(path))
                continue
            right = sum(r.right for r in prog.records.values())
            wrong = sum(r.wrong for r in prog.records.values())
            attempts = right + wrong
            out.append({
                # key 使用文件名：delete_by_key 直接拼接路径，不能信任文件内容里的 bank_key
                "key": path.stem,
                "name": prog.bank_name or path.stem,
                "path": str(path),
                "done": min(len(prog.records), max(0, prog.question_total) or len(prog.records)),
                "total": prog.question_total,
                "right": right,
                "wrong": wrong,
                "wrong_book": sum(1 for r in prog.records.values() if r.in_wrong_book),
                "accuracy": (right / attempts) if attempts else 0.0,
                "exams": len(prog.exams),
                "excluded": len(prog.excluded),
                "active": max(0, prog.question_total - len(prog.excluded)),
                "updated": prog.updated,
                "broken": False,
            })
        return out

    @staticmethod
    def delete_by_key(key: str, directory: "Path | None" = None) -> bool:
        """按题库 key 删除进度文件；拒绝 ``..``/路径分隔符/绝对路径（审计 P3-04）。"""
        directory = Path(directory) if directory else progress_dir()
        name = str(key or "").strip()
        if (not name or name in (".", "..") or "/" in name or "\\" in name
                or name.startswith(".") or ":" in name):
            return False
        path = (directory / f"{name}.json").resolve()
        try:
            if path.parent != directory.resolve():
                return False
            if path.exists():
                path.unlink()
            return True
        except OSError:
            return False


class BankLibrary:
    """题库库：记住最近使用过的题库文件，供"题库选择"界面使用。

    * 与进度文件分离（``library.json``），只保存路径与展示用摘要；
    * 只记录、**绝不删除**磁盘上的题库文件（``forget`` 仅移除记录）；
    * 文件损坏或字段非法 → 整体降级为空库，不影响启动。
    """

    MAX_ENTRIES = 32

    def __init__(self, entries: "Sequence[dict] | None" = None,
                 path: "Path | None" = None) -> None:
        self.path = Path(path) if path else library_path()
        self.entries: list[dict] = []
        for item in entries or []:
            rec = self._clean(item)
            if rec:
                self.entries.append(rec)
        self._dedupe()

    # ------------------------------------------------------------ 构造
    @staticmethod
    def _clean(item: object) -> "dict | None":
        if not isinstance(item, dict):
            return None
        path = str(item.get("path", "") or "").strip()
        if not path:
            return None
        try:
            total = int(item.get("total", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            total = 0
        return {"path": path,
                "name": str(item.get("name", "") or Path(path).stem),
                "total": max(0, min(total, 10_000_000)),
                "last_used": str(item.get("last_used", "") or "")}

    def _dedupe(self) -> None:
        """同一路径只保留一条（保留 last_used 更新的一条），并按最近使用倒序。"""
        merged: dict[str, dict] = {}
        for rec in self.entries:
            key = _norm_path_key(rec["path"])
            old = merged.get(key)
            if old is None or (rec["last_used"] or "") >= (old["last_used"] or ""):
                merged[key] = rec
        self.entries = sorted(merged.values(), key=lambda r: r["last_used"] or "", reverse=True)
        del self.entries[self.MAX_ENTRIES:]

    # ------------------------------------------------------------ 读写
    @classmethod
    def load(cls, path: "Path | None" = None) -> "BankLibrary":
        p = Path(path) if path else library_path()
        try:
            data = _read_json(p)
            if not isinstance(data, dict):
                return cls([], p)
            raw = data.get("banks")
            if not isinstance(raw, list):
                return cls([], p)
            return cls(raw, p)
        except Exception:                    # 字段非法/数值溢出 → 整体降级为空库
            return cls([], p)

    def save(self) -> Path:
        self._dedupe()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"schema": 1, "banks": self.entries},
                             ensure_ascii=False, indent=2)
        tmp = self.path.with_suffix(f".json.{os.getpid()}.tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, self.path)
        return self.path

    # ------------------------------------------------------------ 增删查
    def remember(self, path: "str | Path", name: str = "", total: int = 0) -> dict:
        """记录/更新一条题库（同一路径只保留一条，并置顶）。"""
        p = str(Path(path))
        rec = {"path": p, "name": name or Path(p).stem, "total": max(0, int(total or 0)),
               "last_used": _now()}
        key = _norm_path_key(p)
        self.entries = [e for e in self.entries if _norm_path_key(e["path"]) != key]
        self.entries.insert(0, rec)
        del self.entries[self.MAX_ENTRIES:]
        try:
            self.save()
        except OSError:
            pass
        return rec

    def forget(self, path: "str | Path") -> bool:
        """只从列表移除记录，**不删除磁盘上的题库文件**。"""
        key = _norm_path_key(str(Path(path)))
        before = len(self.entries)
        self.entries = [e for e in self.entries if _norm_path_key(e["path"]) != key]
        changed = len(self.entries) != before
        if changed:
            try:
                self.save()
            except OSError:
                pass
        return changed

    def get(self, path: "str | Path") -> "dict | None":
        key = _norm_path_key(str(Path(path)))
        for e in self.entries:
            if _norm_path_key(e["path"]) == key:
                return dict(e)
        return None

    def most_recent(self, must_exist: bool = True) -> "dict | None":
        """最近使用且（默认）文件仍存在的题库。"""
        for e in self.entries:
            if not must_exist or Path(e["path"]).is_file():
                return dict(e)
        return None

    def existing(self) -> list[dict]:
        return [dict(e) for e in self.entries if Path(e["path"]).is_file()]

    def missing(self) -> list[dict]:
        return [dict(e) for e in self.entries if not Path(e["path"]).is_file()]

    def __len__(self) -> int:
        return len(self.entries)


def _norm_path_key(path: str) -> str:
    """路径去重键：Windows 下大小写与斜杠差异视为同一路径。"""
    try:
        p = str(Path(path))
    except (TypeError, ValueError):
        p = str(path or "")
    return os.path.normcase(os.path.normpath(p)) if p else ""


def _read_json(path: Path) -> "dict | None":
    """读取 JSON，损坏时返回 None（不抛异常）。

    兼容 Windows 记事本写出的 BOM/UTF-16（审计 P3-05）：编码问题不应被当成
    "文件损坏"，否则会被空进度覆盖。
    """
    try:
        data = path.read_bytes()
    except OSError:
        return None
    text = ""
    for enc in ("utf-8-sig", "utf-16", "utf-8"):
        try:
            text = data.decode(enc)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
