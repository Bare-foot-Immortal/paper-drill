# -*- coding: utf-8 -*-
"""刷题匠 PaperDrill —— Qt 界面的会话控制器（与具体控件无关）。

设计意图
--------
把 v1.2 tkinter 版本里散落在 ``PaperDrillApp`` 上的业务状态收敛到一个**唯一权威**的对象上：

* 界面控件只做两件事——**读取** :class:`UiState` 渲染、**调用**控制器方法表达用户意图；
* 控制器负责调用领域层（``practice`` / ``paper`` / ``store`` / ``bank_io``），
  再通过 Qt 信号通知界面重绘；
* 因此不存在"控件自己记着上一题的状态"这类残留问题的生存空间。

本模块只依赖 ``PySide6.QtCore``（信号），不依赖任何 QtWidgets，可在无界面环境下完整测试。
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Iterable

from PySide6.QtCore import QObject, Signal

from ..bank_io import SUPPORTED_SUFFIXES, BankLoadResult, bank_stats, load_bank
from ..config import AppSettings
from ..models import QType, Question
from ..paper import GenerationError, Paper, PaperRound, generate_round, min_round_length

# 用组卷层的蓝图类型：generate_round / PaperRound 约定的就是它（默认 20/10/10）
from ..paper import PaperBlueprint as Blueprint
from ..practice import AnswerResult, ExamResult, ExamSession, PracticeMode, PracticeSession, Scope
from ..store import BankLibrary, ProgressStore, bank_key_of, progress_dir

__all__ = [
    "MAX_SCAN_FILES", "PRACTICE_FEEDBACK_KINDS", "UiState", "PaperDrillController",
    "scan_bank_folder", "quick_bank_info",
]


MAX_SCAN_FILES = 500          # 扫描文件夹时最多收录多少个题库文件（防止误选超大目录）

# 练习反馈的类型（界面据此选择配色）
PRACTICE_FEEDBACK_KINDS = ("idle", "info", "correct", "wrong", "reveal", "empty")


def scan_bank_folder(folder: "str | Path", limit: int = MAX_SCAN_FILES) -> list[Path]:
    """递归扫描文件夹，返回受支持的题库文件（按路径排序，最多 ``limit`` 个）。"""
    root = Path(folder)
    if not root.is_dir():
        return []
    out: list[Path] = []
    try:
        for path in sorted(root.rglob("*")):
            if len(out) >= limit:
                break
            if not path.is_file() or path.name.startswith("~$"):
                continue
            if path.suffix.lower() in SUPPORTED_SUFFIXES:
                out.append(path)
    except OSError:
        pass
    return out


def quick_bank_info(path: "str | Path") -> tuple[str, int]:
    """快速取题库的显示名与题数；解析失败时返回 ``(文件名, 0)``，不抛异常。"""
    p = Path(path)
    try:
        result = load_bank(str(p))
        return (p.stem, len(result.questions))
    except Exception:
        return (p.stem, 0)


def _scope_of_qtype(qtype: "QType | None") -> Scope:
    for scope in Scope:
        if scope.qtype is qtype:
            return scope
    return Scope.ALL


def _int_value(text: str, default: int = 0) -> int:
    try:
        return max(0, int(str(text).strip()))
    except (TypeError, ValueError):
        return default


def _float_value(text: str, default: float) -> float:
    try:
        return max(0.0, float(str(text).strip()))
    except (TypeError, ValueError):
        return default


@dataclass
class UiState:
    """界面需要渲染的全部状态。

    不可变使用（``replace``）不是强制的，但**所有字段只在控制器内部被修改**；
    页面永远只读，避免双向绑定带来的状态不一致。
    """

    # ---- 题库
    bank: "BankLoadResult | None" = None
    store: "ProgressStore | None" = None
    bank_path: str = ""

    # ---- 练习
    session: "PracticeSession | None" = None
    answered: bool = False                     # 当前题是否刚被判定（答题后锁定）
    selection: set = field(default_factory=set)  # 当前选中/勾选的字母
    feedback: str = ""
    feedback_kind: str = "idle"
    analysis_text: str = ""
    scope: Scope = Scope.ALL
    mode: PracticeMode = PracticeMode.ORDER
    shuffle_single: bool = True
    shuffle_multiple: bool = True
    show_analysis: bool = True
    auto_next: bool = True

    # ---- 试卷与考试
    round: "PaperRound | None" = None
    round_used_labels: set = field(default_factory=set)   # 本轮已考过的卷号（只随本轮存活）
    exam: "ExamSession | None" = None
    exam_result: "ExamResult | None" = None
    exam_index: int = 0
    exam_view: str = "config"                  # config | taking | result
    blueprint: "Blueprint" = field(default_factory=Blueprint)
    scores: dict = field(default_factory=lambda: {"single": 1.0, "multiple": 2.0, "judge": 1.0})
    round_auto: bool = True
    round_length: int = 0
    record_exam_progress: bool = True

    # ---- 运行期提示
    save_error: str = ""

    # ------------------------------------------------------------ 便捷属性
    @property
    def loaded(self) -> bool:
        return self.session is not None

    @property
    def practice_empty(self) -> bool:
        return self.session is None or self.session.empty

    @property
    def position(self) -> int:
        return self.session.position if self.session else 0

    @property
    def total(self) -> int:
        return self.session.total if self.session else 0

    @property
    def exam_taking(self) -> bool:
        return self.exam is not None and not self.exam.submitted

    @property
    def exam_readonly(self) -> bool:
        """交卷后卷面只读（FR-18.11）。"""
        return self.exam is not None and self.exam.submitted


class PaperDrillController(QObject):
    """会话控制器：Qt 界面的唯一业务状态源。"""

    # ---- 信号
    state_changed = Signal()
    practice_changed = Signal()
    exam_changed = Signal()
    paper_changed = Signal()
    stats_changed = Signal()
    library_changed = Signal()
    status_message = Signal(str)
    theme_requested = Signal(str)          # "system" / "light" / "dark"

    def __init__(self, settings: "AppSettings | None" = None,
                 settings_path: "Path | None" = None,
                 progress_root: "Path | None" = None,
                 library: "BankLibrary | None" = None,
                 parent: "QObject | None" = None) -> None:
        super().__init__(parent)
        self._settings_path = Path(settings_path) if settings_path else None
        self.settings = settings if settings is not None else AppSettings.load(self._settings_path)
        self._progress_root = Path(progress_root) if progress_root else None
        self.state = UiState()
        self.library = library if library is not None else BankLibrary.load()
        self._auto_next_seq = 0

        # 从设置恢复界面偏好
        st = self.state
        st.scope = Scope.from_label(str(self.settings.scope or "all"))
        st.mode = PracticeMode.from_label(str(self.settings.mode or "order"))
        st.shuffle_single = bool(self.settings.shuffle_single)
        st.shuffle_multiple = bool(self.settings.shuffle_multiple)
        st.show_analysis = bool(self.settings.show_analysis)
        st.auto_next = bool(self.settings.auto_next_on_correct)
        st.blueprint = Blueprint(int(self.settings.paper_single), int(self.settings.paper_multiple),
                                 int(self.settings.paper_judge))
        st.scores = self.settings.scores()
        st.round_auto = bool(self.settings.round_auto)
        st.round_length = int(self.settings.round_length or 0)
        st.record_exam_progress = bool(self.settings.record_exam_progress)

    # ================================================================ 设置
    @property
    def progress_dir(self) -> Path:
        return self._progress_root if self._progress_root else progress_dir()

    def save_settings(self) -> None:
        """把界面偏好写回配置文件（失败不抛异常，只提示）。"""
        self._write_settings()

    def save_window_state(self, geometry: str, page: str = "") -> None:
        """持久化主窗口几何与当前页面（关闭窗口时调用）。"""
        self.settings.qt_window_state = str(geometry or "")
        if page:
            self.settings.last_page = str(page)
        self._write_settings()

    def _write_settings(self) -> None:
        s = self.settings
        st = self.state
        s.bank_path = st.bank_path or s.bank_path
        s.mode = st.mode.value
        s.scope = st.scope.value
        s.shuffle_single = bool(st.shuffle_single)
        s.shuffle_multiple = bool(st.shuffle_multiple)
        s.show_analysis = bool(st.show_analysis)
        s.auto_next_on_correct = bool(st.auto_next)
        s.record_exam_progress = bool(st.record_exam_progress)
        s.paper_single = int(st.blueprint.single)
        s.paper_multiple = int(st.blueprint.multiple)
        s.paper_judge = int(st.blueprint.judge)
        s.round_auto = bool(st.round_auto)
        s.round_length = int(st.round_length or 0)
        s.score_single = float(st.scores.get("single", 1.0))
        s.score_multiple = float(st.scores.get("multiple", 2.0))
        s.score_judge = float(st.scores.get("judge", 1.0))
        try:
            s.save(self._settings_path)
        except Exception:
            pass

    # ================================================================ 题库
    def all_questions(self) -> list[Question]:
        """题库原文件解析出的全量题目（不扣除删减）。"""
        return list(self.state.bank.questions) if self.state.bank else []

    def active_questions(self) -> list[Question]:
        """扣掉「题库删减」后真正参与练习与组卷的题目。"""
        questions = self.all_questions()
        store = self.state.store
        if not questions or store is None:
            return questions
        try:
            return store.active_questions(questions)
        except Exception:
            return questions

    def bank_stats(self) -> dict:
        return bank_stats(self.active_questions())

    def load_bank(self, path: "str | Path", remember: bool = True) -> bool:
        """载入题库并恢复上次练习会话。返回是否成功（失败不弹窗，通过信号报告）。"""
        raw = str(path or "").strip().strip('"')
        if not raw or not Path(raw).is_file():
            self._emit_status(f"找不到题库文件：{raw or '（空路径）'}")
            return False
        try:
            result = load_bank(raw)
        except Exception as exc:                      # 解析器内部异常不应让界面崩溃
            self._emit_status(f"题库解析失败：{exc}")
            return False
        if not result.questions:
            detail = ""
            if getattr(result, "issues", None):
                detail = f"（首个原因：{result.issues[0]}）"
            self._emit_status(f"题库为空：没有解析到任何可用题目{detail}，请检查题库格式。")
            return False

        st = self.state
        st.bank = result
        st.bank_path = raw
        try:
            st.store = ProgressStore.load_for(Path(raw).stem, result.questions, self.progress_dir)
        except Exception as exc:                       # 进度文件异常 → 以空进度继续
            from ..store import BankProgress

            st.store = ProgressStore(
                BankProgress(bank_key=bank_key_of(Path(raw).stem, result.questions),
                             bank_name=Path(raw).stem,
                             question_total=len(result.questions)),
                self.progress_dir)
            self._emit_status(f"读取原有进度时出现问题，已按空进度继续：{exc}")
        self._renormalize()
        self._check_save_error()
        # 首次导入时也立刻落一份进度文件：既是"进度自动保留"的语义，
        # 也让「进度管理」页能马上看到这个题库。
        if st.store is not None:
            try:
                st.store.save()
            except Exception:
                pass
            self._check_save_error()

        if remember:
            try:
                self.library.remember(raw, Path(raw).stem, len(result.questions))
            except Exception:
                pass

        # 重建练习会话并恢复上次位置
        session = PracticeSession(
            self.active_questions(), st.store, mode=st.mode,
            qtype_filter=st.scope.qtype,
            shuffle_single=st.shuffle_single, shuffle_multiple=st.shuffle_multiple)
        restored = False
        try:
            restored = session.restore_position()
        except Exception:
            restored = False
        st.session = session
        st.scope = _scope_of_qtype(session.qtype_filter)
        st.mode = session.mode
        st.shuffle_single = session.shuffle_single
        st.shuffle_multiple = session.shuffle_multiple
        st.round = None
        st.round_used_labels = set()
        st.exam = None
        st.exam_result = None
        st.exam_index = 0
        st.exam_view = "config"

        self.settings.bank_path = raw
        self.save_settings()
        self._reset_practice_feedback("请作答（单选/判断点选即判，多选勾选后提交）")
        if restored:
            self._emit_status(f"已恢复上次练习进度（第 {session.position} 题）"
                              + (f"（已删减 {len(st.store.progress.excluded)} 题）"
                                 if st.store.progress.excluded else ""))
        else:
            self._emit_status("题库导入成功，开始练习"
                              + (f"（已删减 {len(st.store.progress.excluded)} 题）"
                                 if st.store.progress.excluded else ""))
        if result.issues:
            self._emit_status(f"注意：有 {len(result.issues)} 行未能导入（详见题库资料页）")
        self._refresh_all(raise_practice=True)
        return True

    def reload_bank(self) -> bool:
        if not self.state.bank_path:
            return False
        return self.load_bank(self.state.bank_path)

    def recent_bank(self) -> dict | None:
        """题库库中最近可用（文件仍存在）的题库。"""
        return self.library.most_recent()

    # ---------------------------------------------------------------- 删减维护
    def _renormalize(self) -> None:
        """题库换版后清理已失效的删减/记录（题目已不存在）。"""
        st = self.state
        if st.store is None or not st.bank:
            return
        try:
            if st.store.progress.prune_excluded(st.bank.questions):
                st.store.save()
        except Exception:
            pass

    # ================================================================ 练习
    def _reset_practice_feedback(self, text: str = "", kind: str = "idle") -> None:
        st = self.state
        st.answered = False
        st.selection = set()
        st.feedback = text
        st.feedback_kind = kind
        st.analysis_text = ""

    def set_scope(self, scope: Scope) -> None:
        st = self.state
        st.scope = scope
        self.settings.scope = scope.value
        self.save_settings()
        if not st.session:
            self._reset_practice_feedback()
            self._refresh_all(raise_practice=True)
            return
        self._auto_next_seq += 1                     # 作废未执行的自动跳题
        self._save_position()                        # 先记住切换前（旧范围）的位置
        st.session.rebuild(qtype_filter=scope.qtype)
        st.scope = _scope_of_qtype(st.session.qtype_filter)
        if st.session.empty:
            self._apply_empty_state()
        else:
            # 回到该范围上次停下的位置（各范围分别记忆，切走再切回来不丢进度）
            st.session.restore_position(adopt_mode=False)
            self._save_position()
            self._reset_practice_feedback("请作答（单选/判断点选即判，多选勾选后提交）")
        self._refresh_all(raise_practice=True)

    def set_mode(self, mode: PracticeMode) -> None:
        st = self.state
        st.mode = mode
        self.settings.mode = mode.value
        self.save_settings()
        if not st.session:
            self._reset_practice_feedback()
            self._refresh_all(raise_practice=True)
            return
        self._auto_next_seq += 1
        self._save_position()                        # 先记住切换前（旧模式）的位置
        st.session.rebuild(mode)
        if st.session.empty:
            self._apply_empty_state()
        else:
            # 回到该模式上次停下的位置（各模式分别记忆，切走再切回来不丢进度）
            st.session.restore_position(adopt_mode=False)
            self._save_position()
            self._reset_practice_feedback("请作答（单选/判断点选即判，多选勾选后提交）")
        self._refresh_all(raise_practice=True)

    def set_shuffle(self, single: "bool | None" = None, multiple: "bool | None" = None) -> None:
        st = self.state
        if single is not None:
            st.shuffle_single = bool(single)
        if multiple is not None:
            st.shuffle_multiple = bool(multiple)
        self.settings.shuffle_single = st.shuffle_single
        self.settings.shuffle_multiple = st.shuffle_multiple
        self.save_settings()
        if st.session:
            # 打乱开关影响"这道题显示成什么样"，因此重建会话（按指纹停回原题）而不是原地改字段，
            # 否则其它题目已缓存的显示形态会与设置不一致。
            current = st.session.current_question()
            fingerprint = current.fingerprint if current is not None else ""
            st.session = PracticeSession(
                st.session.questions, st.session.store, mode=st.session.mode,
                qtype_filter=st.session.qtype_filter,
                shuffle_single=st.shuffle_single, shuffle_multiple=st.shuffle_multiple)
            if fingerprint:
                st.session.goto_question_fp(fingerprint)
            if st.session.empty:
                self._apply_empty_state()
            else:
                self._save_position()
                self._render_practice_question()
        self._refresh_all(raise_practice=True)

    def set_show_analysis(self, show: bool) -> None:
        self.state.show_analysis = bool(show)
        self.settings.show_analysis = bool(show)
        self.save_settings()
        st = self.state
        if st.answered and st.session and not st.session.empty:
            item = st.session.current_item()
            st.analysis_text = self._analysis_of(item) if item is not None else ""
        self._refresh_all(raise_practice=True)

    def set_auto_next(self, enabled: bool) -> None:
        self.state.auto_next = bool(enabled)
        self.settings.auto_next_on_correct = bool(enabled)
        self.save_settings()
        self.state_changed.emit()

    # ---------------------------------------------------------------- 作答
    def current_item(self):
        st = self.state
        return st.session.current_item() if st.session and not st.session.empty else None

    def current_question(self) -> "Question | None":
        st = self.state
        return st.session.current_question() if st.session else None

    def current_record(self):
        st = self.state
        return st.session.current_record() if st.session else None

    def toggle_option(self, letter: str) -> "AnswerResult | None":
        """用户点选一个选项。

        * 单选题 / 判断题：立即判定（与 v1.2 行为一致）；
        * 多选题：切换勾选状态，等待 :meth:`submit`。
        """
        st = self.state
        item = self.current_item()
        if item is None or st.answered:
            return None
        letter = str(letter or "").upper()
        if letter not in item.labels:
            return None
        if item.qtype is QType.MULTIPLE:
            selection = set(st.selection)
            if letter in selection:
                selection.discard(letter)
            else:
                selection.add(letter)
            st.selection = selection
            self.practice_changed.emit()
            self.state_changed.emit()
            return None
        st.selection = {letter}
        return self.submit()

    def submit(self) -> "AnswerResult | None":
        """提交当前答案（多选必须显式提交；单选/判断通常已由点选触发）。"""
        st = self.state
        item = self.current_item()
        if item is None or st.answered:
            return None
        selected = set(st.selection)
        if not selected:
            self._emit_status("请至少勾选一个选项。" if item.qtype is QType.MULTIPLE
                              else "请先选择答案。")
            return None
        result = st.session.submit(selected)
        st.answered = True
        st.selection = set(selected)
        st.feedback, st.feedback_kind = self._feedback_of(item, result)
        st.analysis_text = self._analysis_of(item)
        self._save_position()
        self._check_save_error()
        self._refresh_all(raise_practice=True)
        if result.correct:
            self._schedule_auto_next()
        return result

    def reveal(self) -> bool:
        """「不会，看答案」：展示答案与解析，不计入作答。"""
        st = self.state
        item = self.current_item()
        if item is None:
            return False
        st.answered = True
        st.selection = set()          # 看答案不算作答：别把未提交的勾选画成红叉（P3-2）
        st.feedback = f"正确答案：{item.answer_display()}（已跳过作答）"
        st.feedback_kind = "reveal"
        st.analysis_text = self._analysis_of(item)
        self._refresh_all(raise_practice=True)
        return True

    def cancel_auto_next(self) -> None:
        """作废待执行的「答对自动下一题」（离开练习页/打开对话框时调用）。"""
        self._auto_next_seq += 1

    def _schedule_auto_next(self) -> None:
        """答对且开启自动下一题时，延迟跳题；通过序号作废被后续操作取代的跳转。"""
        st = self.state
        if not st.auto_next:
            return
        self._auto_next_seq += 1
        seq = self._auto_next_seq

        def _tick() -> None:
            if seq != self._auto_next_seq:           # 已被新的操作取代
                return
            st_now = self.state
            if not st_now.loaded or not st_now.answered:   # 状态已变（如已翻题/换题库）
                return
            if not self.advance():
                self._emit_status("本轮已完成 ✔ 可切换「错题重练」或去「模拟考试」检验")

        delay = max(0, int(getattr(self.settings, "auto_next_delay_ms", 700) or 0))
        QTimerSingleShot(delay, _tick)

    def advance(self) -> bool:
        st = self.state
        if not st.session or st.session.empty:
            return False
        self._auto_next_seq += 1
        if not st.session.advance():
            self._emit_status("已经是最后一题")
            return False
        self._save_position()
        self._render_practice_question()
        return True

    def retreat(self) -> bool:
        st = self.state
        if not st.session or st.session.empty:
            return False
        self._auto_next_seq += 1
        if not st.session.retreat():
            self._emit_status("已经是第一题")
            return False
        self._save_position()
        self._render_practice_question()
        return True

    def goto(self, position: int) -> bool:
        st = self.state
        if not st.session or st.session.empty:
            return False
        if not st.session.goto(max(0, int(position))):
            return False
        self._save_position()
        self._render_practice_question()
        return True

    def restart_round(self) -> None:
        st = self.state
        if not st.session:
            self._emit_status("请先导入题库。")
            return
        self._auto_next_seq += 1
        st.session.rebuild(st.session.mode)
        if st.session.empty:
            self._apply_empty_state()
        else:
            self._save_position()
            self._reset_practice_feedback("请作答（单选/判断点选即判，多选勾选后提交）")
        self._refresh_all(raise_practice=True)
        self._emit_status("已重新开始本轮（进度记录保留）")

    def _render_practice_question(self) -> None:
        """切题后重建"答题前"状态。

        已作答过的题**不锁定、不剧透**（v1.2 缺陷回归点）：只提示上次结果，允许重新作答。
        """
        st = self.state
        item = self.current_item()
        if item is None:
            return
        record = st.session.current_record() if st.session else None
        st.answered = False
        st.selection = set()
        st.analysis_text = ""
        if record is not None and record.done:
            mark = "✔ 上次回答正确" if record.last == "right" else "✘ 上次回答错误"
            times = f"，共作答 {record.attempts} 次" if record.attempts else ""
            st.feedback = f"{mark}{times}　可重新作答；点「不会，看答案」可直接看答案"
            st.feedback_kind = "info"
        else:
            st.feedback = "请作答（单选/判断点选即判，多选勾选后提交）"
            st.feedback_kind = "idle"
        self._refresh_all(raise_practice=True)

    def _apply_empty_state(self) -> None:
        st = self.state
        if st.mode is PracticeMode.WRONG:
            text = f"{st.scope.label}范围内没有答错的题目（错题本为空）。"
        elif st.mode is PracticeMode.FRESH:
            text = f"{st.scope.label}范围内的题目都已练过。"
        else:
            text = "没有可练习的题目，请更换范围或模式。"
        st.answered = True
        st.selection = set()
        st.feedback = text
        st.feedback_kind = "empty"
        st.analysis_text = ""

    # ---------------------------------------------------------------- 反馈文本
    def _analysis_of(self, item) -> str:
        if item is None or not self.state.show_analysis or not getattr(item, "analysis", ""):
            return ""
        return f"解析：{item.analysis}"

    @staticmethod
    def _feedback_of(item, result) -> tuple[str, str]:
        if result.correct:
            return (f"✔ 回答正确！正确答案：{item.answer_display()}", "correct")
        return (f"✘ 回答错误。你的作答：{result.selected_answer}"
                f"　｜　正确答案：{item.answer_display()}", "wrong")

    # ================================================================ 统计
    def stats(self) -> dict:
        st = self.state
        if not st.session:
            return {"total": 0, "done": 0, "right": 0, "wrong": 0, "attempts": 0,
                    "wrong_book": 0, "accuracy": 0.0, "done_rate": 0.0}
        return st.session.stats()

    def scope_stats(self) -> dict:
        st = self.state
        if not st.session:
            return {"total": 0, "done": 0, "right": 0, "wrong": 0, "attempts": 0,
                    "wrong_book": 0, "accuracy": 0.0, "done_rate": 0.0}
        return st.session.scope_stats()

    def stats_line(self) -> str:
        st = self.state
        if not st.bank:
            return "尚未导入题库"
        s = self.bank_stats()
        cut = len(st.store.progress.excluded) if st.store else 0
        cut_note = f"　｜　已删减 {cut} 题" if cut else ""
        live = self.stats()
        return (f"共 {s['total']} 题：单选 {s['single']}、多选 {s['multiple']}、"
                f"判断 {s['judge']}；含固定顺序题 {s['fixed']} 道{cut_note}"
                f"　｜　已练 {live['done']} 题　正确率 {live['accuracy'] * 100:.1f}%　"
                f"错题 {live['wrong_book']} 道")

    def bank_summary(self) -> dict:
        """题库资料页所需的摘要。"""
        st = self.state
        if not st.bank:
            return {}
        stats = self.bank_stats()
        live = self.stats()
        all_qs = self.all_questions()
        return {
            "path": st.bank_path,
            "name": Path(st.bank_path).stem if st.bank_path else "",
            "sheet": getattr(st.bank, "sheet", "") or "",
            "issues": [str(i) for i in getattr(st.bank, "issues", [])],
            **stats,
            "excluded": len(st.store.progress.excluded) if st.store else 0,
            "done": live["done"],
            "accuracy": live["accuracy"],
            "wrong_book": live["wrong_book"],
            "all_total": len(all_qs),
        }

    # ================================================================ 试卷
    def set_blueprint(self, single: int, multiple: int, judge: int) -> None:
        st = self.state
        st.blueprint = Blueprint(max(0, min(10_000, int(single))),
                                 max(0, min(10_000, int(multiple))),
                                 max(0, min(10_000, int(judge))))
        self.save_settings()
        self.paper_changed.emit()
        self.state_changed.emit()

    def set_scores(self, single: "float | str", multiple: "float | str",
                   judge: "float | str") -> None:
        st = self.state
        st.scores = {"single": _float_value(single, 1.0),
                     "multiple": _float_value(multiple, 2.0),
                     "judge": _float_value(judge, 1.0)}
        self.save_settings()
        self.paper_changed.emit()
        self.state_changed.emit()

    def set_round_length(self, length: "int | None", auto: bool) -> None:
        st = self.state
        st.round_auto = bool(auto)
        st.round_length = max(0, min(10_000, int(length or 0)))
        self.save_settings()
        self.paper_changed.emit()
        self.state_changed.emit()

    def blueprint_total(self) -> int:
        return self.state.blueprint.total

    def blueprint_full_score(self) -> float:
        bp = self.state.blueprint
        sc = self.state.scores
        return (bp.single * sc.get("single", 1.0) + bp.multiple * sc.get("multiple", 2.0)
                + bp.judge * sc.get("judge", 1.0))

    def min_round_length(self) -> int:
        questions = self.active_questions()
        if not questions or self.state.blueprint.total <= 0:
            return 1
        try:
            return min_round_length(questions, self.state.blueprint)
        except Exception:
            return 1

    def plan_hint(self) -> str:
        """组卷页的轮长提示（覆盖题库需 N 张 + 推导明细）。"""
        questions = self.active_questions()
        bp = self.state.blueprint
        if not questions or bp.total <= 0:
            return "导入题库并设置题量后自动计算覆盖所需张数"
        stats = self.bank_stats()
        parts = []
        if bp.single > 0:
            parts.append(f"单选 {stats['single']}÷{bp.single}={-(-stats['single'] // bp.single)}张")
        if bp.multiple > 0:
            parts.append(f"多选 {stats['multiple']}÷{bp.multiple}={-(-stats['multiple'] // bp.multiple)}张")
        if bp.judge > 0:
            parts.append(f"判断 {stats['judge']}÷{bp.judge}={-(-stats['judge'] // bp.judge)}张")
        return f"覆盖题库全部题目需 {self.min_round_length()} 张/轮（" + "，".join(parts) + "）"

    def generate_round(self, force: bool = False) -> "PaperRound | None":
        st = self.state
        if self.has_unsubmitted_exam() and not force:
            self._emit_status("当前有未交卷的模拟考试：请先交卷，或确认放弃后再重新生成试卷。")
            return None
        questions = self.active_questions()
        if not questions:
            self._emit_status("请先导入题库（或题库题目已被全部删减）。")
            return None
        if st.blueprint.total <= 0:
            self._emit_status("请至少为一种题型设置每卷数量。")
            return None
        manual = None if st.round_auto else (st.round_length or None)
        try:
            rnd = generate_round(questions, st.blueprint, round_length=manual)
        except GenerationError as exc:
            self._emit_status(f"无法生成试卷：{exc}")
            return None
        except Exception as exc:
            self._emit_status(f"生成失败：{exc}")
            return None
        st.round = rnd
        st.round_used_labels = set()
        st.exam = None
        st.exam_result = None
        st.exam_index = 0
        st.exam_view = "config"
        if st.round_auto:
            st.round_length = rnd.round_length
        self.save_settings()
        self.paper_changed.emit()
        self._emit_status(f"已生成一轮 {rnd.paper_count} 张试卷；"
                          + ("覆盖完整 ✔" if rnd.coverage_ok
                             else "覆盖不完整，请调大一轮张数"))
        self.state_changed.emit()
        return rnd

    def coverage_text(self) -> str:
        rnd = self.state.round
        if rnd is None:
            return "尚未生成试卷"
        names = {QType.SINGLE.key: "单选", QType.MULTIPLE.key: "多选", QType.JUDGE.key: "判断"}
        parts = [f"{names.get(k, k)} {seen}/{total}" for k, (seen, total) in rnd.coverage.items()]
        text = "✔ " + rnd.summary() + "（" + "，".join(parts) + f"）　随机种子 {rnd.seed}"
        if rnd.warnings:
            text += "　⚠ " + "；".join(rnd.warnings)
        return text

    def paper_labels(self) -> list[str]:
        rnd = self.state.round
        if rnd is None:
            return []
        return [f"第 {p.seq} 张（{p.label}卷，共 {p.total} 题）" for p in rnd.papers]

    def paper_at(self, index: int) -> "Paper | None":
        rnd = self.state.round
        if rnd is None or not rnd.papers:
            return None
        if index < 0 or index >= len(rnd.papers):
            index = 0
        return rnd.papers[index]

    def used_paper_labels(self) -> set[str]:
        """本轮已考过的卷号。

        只看**当前这一轮**（``round_used_labels``）：历史成绩里的卷号 A/B/C 每轮都会
        重复，拿历史判定"未考"会让重新生成一轮后永远提示"本轮已考完"（审计 P2-5）。
        """
        return set(self.state.round_used_labels)

    # ================================================================ 考试
    def has_unsubmitted_exam(self) -> bool:
        """当前是否有未交卷的模拟考试（作答只在内存，丢弃前必须确认）。"""
        exam = self.state.exam
        return exam is not None and not exam.submitted

    def start_exam(self, paper: "Paper | None", allow_replace: bool = False) -> bool:
        st = self.state
        if paper is None or st.store is None:
            return False
        if self.has_unsubmitted_exam() and not allow_replace:
            self._emit_status("当前有未交卷的模拟考试：请先交卷，或确认放弃后重新开始。")
            return False
        try:
            st.exam = ExamSession(
                paper, st.store,
                shuffle_single=st.shuffle_single, shuffle_multiple=st.shuffle_multiple,
                scores=dict(st.scores), record_progress=st.record_exam_progress)
        except Exception as exc:
            self._emit_status(f"开始考试失败：{exc}")
            return False
        st.exam_index = 0
        st.exam_result = None
        st.exam_view = "taking"
        self._refresh_all()
        self._emit_status(f"{paper.label}卷模拟考试进行中（作答期间不显示对错）")
        return True

    def start_next_unused_paper(self, allow_replace: bool = False) -> bool:
        rnd = self.state.round
        if rnd is None:
            self._emit_status("请先生成一轮试卷。")
            return False
        used = self.used_paper_labels()
        for paper in rnd.papers:
            if paper.label not in used:
                return self.start_exam(paper, allow_replace=allow_replace)
        self._emit_status("本轮所有试卷都已考过，可重新生成一轮。")
        return False

    def exam_total(self) -> int:
        return self.state.exam.total if self.state.exam else 0

    def exam_answered_count(self) -> int:
        return self.state.exam.answered_count if self.state.exam else 0

    def exam_is_answered(self, index: int) -> bool:
        exam = self.state.exam
        return bool(exam and exam.answered(int(index)))

    def exam_item(self, index: int):
        exam = self.state.exam
        if exam is None:
            return None
        index = max(0, min(int(index), exam.total - 1))
        return exam.item(index)

    def exam_selection(self) -> set:
        exam = self.state.exam
        if exam is None:
            return set()
        return set(exam.answers.get(self.state.exam_index, set()))

    def exam_goto(self, index: int) -> bool:
        st = self.state
        if st.exam is None:
            return False
        st.exam_index = max(0, min(int(index), st.exam.total - 1))
        self.exam_changed.emit()
        self.state_changed.emit()
        return True

    def exam_set(self, letter: str) -> None:
        st = self.state
        if st.exam is None or st.exam.submitted:
            return
        st.exam.set_answer(st.exam_index, {str(letter).upper()})
        self.exam_changed.emit()
        self.state_changed.emit()

    def exam_toggle(self, letter: str) -> None:
        st = self.state
        if st.exam is None or st.exam.submitted:
            return
        st.exam.toggle(st.exam_index, str(letter).upper())
        self.exam_changed.emit()
        self.state_changed.emit()

    def exam_clear(self) -> None:
        st = self.state
        if st.exam is None or st.exam.submitted:
            return
        st.exam.clear_answer(st.exam_index)
        self.exam_changed.emit()
        self.state_changed.emit()

    def submit_exam(self) -> "ExamResult | None":
        st = self.state
        if st.exam is None:
            self._emit_status("当前没有进行中的模拟考试。")
            return None
        if st.exam.submitted and st.exam.result is not None:
            st.exam_result = st.exam.result
            st.exam_view = "result"
            self._refresh_all()
            return st.exam.result
        try:
            result = st.exam.submit()
        except Exception as exc:
            self._emit_status(f"交卷失败：{exc}")
            return None
        st.exam_result = result
        st.exam_view = "result"
        st.round_used_labels = set(st.round_used_labels) | {str(result.paper_label)}
        self.settings.last_paper_label = result.paper_label
        self.save_settings()
        # 错题本 / 未做队列已变化 → 重建练习队列，但**练习位置保持不变**
        self._refresh_practice_view()
        self._refresh_all()
        self._emit_status(f"交卷完成：{result.summary()}")
        return result

    def unattended_count(self) -> int:
        exam = self.state.exam
        if exam is None:
            return 0
        return exam.total - exam.answered_count

    def exam_history(self) -> list[dict]:
        st = self.state
        return st.store.exam_history() if st.store else []

    def _refresh_practice_view(self) -> None:
        """交卷/删减/清空错题后按当前模式重建练习队列，尽量停在原来那道题上。"""
        st = self.state
        if st.session is None:
            return
        current = st.session.current_question()
        fingerprint = current.fingerprint if current is not None else ""
        previous_cursor = st.session.cursor
        st.session.rebuild(st.session.mode)
        if fingerprint:
            located = st.session.goto_question_fp(fingerprint)
        else:
            located = False
        if not located and st.session.order:
            # 原题可能因本次考试/删减离开了当前模式的队列（例如错题重练已订正），
            # 退到重建前的相邻位置，避免练习位置突然跳回第 1 题。
            st.session.cursor = max(0, min(previous_cursor, len(st.session.order) - 1))
        if st.session.empty:
            self._apply_empty_state()
            return
        self._save_position()
        self._render_practice_question()

    # ================================================================ 数据管理
    def exclude_questions(self, questions: Iterable[Question], force: bool = False) -> int:
        st = self.state
        if st.store is None:
            return 0
        if self.has_unsubmitted_exam() and not force:
            self._emit_status("当前有未交卷的模拟考试：删减题库题目会作废试卷，请先交卷或确认放弃。")
            return 0
        added = st.store.exclude(list(questions))
        if added:
            self._apply_filter_change(f"已删减 {added} 道题目")
        return added

    def include_questions(self, questions: Iterable[Question], force: bool = False) -> int:
        st = self.state
        if st.store is None:
            return 0
        if self.has_unsubmitted_exam() and not force:
            self._emit_status("当前有未交卷的模拟考试：恢复题库题目会作废试卷，请先交卷或确认放弃。")
            return 0
        back = st.store.include(list(questions))
        if back:
            self._apply_filter_change(f"已恢复 {back} 道题目")
        return back

    def restore_all_excluded(self, force: bool = False) -> int:
        st = self.state
        if st.store is None:
            return 0
        if self.has_unsubmitted_exam() and not force:
            self._emit_status("当前有未交卷的模拟考试：恢复题库题目会作废试卷，请先交卷或确认放弃。")
            return 0
        count = st.store.clear_excluded()
        if count:
            self._apply_filter_change(f"已恢复全部 {count} 道题目")
        return count

    def excluded_questions(self) -> list[Question]:
        st = self.state
        if st.store is None:
            return []
        return st.store.excluded_questions(self.all_questions())

    def is_excluded(self, question: Question) -> bool:
        st = self.state
        return bool(st.store and st.store.is_excluded(question))

    def _apply_filter_change(self, note: str = "") -> None:
        """删减/恢复后：重建练习队列，并作废旧试卷（基于旧题目集生成）。"""
        st = self.state
        if st.session is None:
            self._refresh_all()
            return
        current = st.session.current_question()
        fingerprint = current.fingerprint if current is not None else ""
        st.session.questions = self.active_questions()
        st.session.rebuild(st.session.mode)
        if not (fingerprint and st.session.goto_question_fp(fingerprint)):
            if not st.session.empty:
                st.session.cursor = 0
        st.round = None
        st.round_used_labels = set()
        st.exam = None
        st.exam_result = None
        st.exam_index = 0
        st.exam_view = "config"
        if st.session.empty:
            self._apply_empty_state()
        else:
            self._save_position()
            self._render_practice_question()
        self._refresh_all(raise_practice=True)
        if note:
            self._emit_status(note + "　（题库原文件未改动，可随时恢复）")

    def wrong_book_questions(self) -> list[Question]:
        st = self.state
        if not st.session or st.store is None:
            return []
        return [q for q in st.session.questions if st.store.record_of(q).in_wrong_book]

    def clear_wrong_book(self) -> int:
        st = self.state
        if st.store is None or st.session is None:
            return 0
        count = st.store.progress.clear_wrong_book(st.session.questions)
        try:
            st.store.save()
        except Exception as exc:                    # 磁盘只读/占用时不让对话框崩掉
            self._emit_status(f"⚠ 错题本未能保存：{exc}")
        self._check_save_error()
        self._refresh_practice_view()
        self._refresh_all()
        return count

    def reset_progress(self) -> bool:
        st = self.state
        if st.store is None or st.session is None:
            return False
        try:
            st.store.reset()
        except Exception as exc:
            st.save_error = f"{type(exc).__name__}: {exc}"
            self._emit_status(f"⚠ 进度未能重置：{st.save_error}")
            return False
        # 同时清空界面上的"旧考试/旧试卷"，否则成绩页会继续显示已被清掉的分数
        st.round = None
        st.round_used_labels = set()
        st.exam = None
        st.exam_result = None
        st.exam_index = 0
        st.exam_view = "config"
        st.session = PracticeSession(
            self.active_questions(), st.store, mode=st.session.mode,
            qtype_filter=st.session.qtype_filter,
            shuffle_single=st.shuffle_single, shuffle_multiple=st.shuffle_multiple)
        self._reset_practice_feedback("请作答（单选/判断点选即判，多选勾选后提交）")
        self._refresh_all(raise_practice=True)
        self._emit_status("进度已重置")
        return True

    def reset_progress_of(self, bank_key: str) -> bool:
        """重置任意题库的进度（进度管理对话框用）。"""
        st = self.state
        if st.store is not None and st.store.progress.bank_key == bank_key:
            return self.reset_progress()
        ok = ProgressStore.delete_by_key(bank_key, self.progress_dir)
        self._emit_status("已重置该题库进度" if ok else "重置失败：文件可能正被占用")
        return ok

    def progress_rows(self) -> list[dict]:
        return ProgressStore.list_all(self.progress_dir)

    # ---------------------------------------------------------------- 题库库
    def library_rows(self) -> list[dict]:
        rows = []
        for rec in self.library.entries:
            path = Path(rec["path"])
            exists = path.is_file()
            rows.append({**rec, "exists": exists, "name": rec.get("name") or path.stem})
        return rows

    def scan_folder(self, folder: "str | Path") -> list[Path]:
        found = scan_bank_folder(folder)
        for path in found:
            name, total = quick_bank_info(path)
            try:
                self.library.remember(path, name, total)
            except Exception:
                pass
        if found:
            self.library_changed.emit()
        return found

    def forget_library_entry(self, path: "str | Path") -> bool:
        changed = self.library.forget(path)
        if changed:
            self.library_changed.emit()
        return changed

    def forget_with_progress(self, path: "str | Path") -> int:
        """移除题库记录并清理其进度；返回清理的进度文件数。

        * 当前正在使用的题库：走 ``reset_progress()``（同时清空内存与文件），
          否则下一次作答会把旧记录整份写回（审计 P2-2）；
        * 题库文件已缺失/损坏：按进度文件里的 ``bank_name`` 兜底匹配，
          不再留下永远删不掉的孤儿进度（审计 P2-3）。
        """
        st = self.state
        target = Path(path)
        hit_key = ""
        try:
            loaded = load_bank(str(path))
            if loaded.questions:
                hit_key = bank_key_of(target.stem, loaded.questions)
        except Exception:
            hit_key = ""

        cleaned = 0
        if hit_key and st.store is not None and st.store.progress.bank_key == hit_key:
            self.reset_progress()                     # 当前题库：内存 + 文件一起清
            cleaned = 1
        elif hit_key and ProgressStore.delete_by_key(hit_key, self.progress_dir):
            cleaned = 1
        else:
            # 兜底：题库文件读不到时，按文件名/题库名匹配进度文件
            for row in ProgressStore.list_all(self.progress_dir):
                name = str(row.get("name", ""))
                key = str(row.get("key", ""))
                if target.stem not in (name, key) and name != target.stem:
                    continue
                if (st.store is not None and st.store.path.stem == key):
                    self.reset_progress()
                    cleaned += 1
                elif ProgressStore.delete_by_key(key, self.progress_dir):
                    cleaned += 1
        self.library.forget(path)
        self.library_changed.emit()
        return cleaned

    # ================================================================ 刷新
    def report_status(self, text: str) -> None:
        """供对话框等外部模块报告一句话状态（保持"状态只走控制器"的约定）。"""
        self._emit_status(text)

    def _emit_status(self, text: str) -> None:
        self.status_message.emit(str(text))

    def _check_save_error(self) -> None:
        st = self.state
        err = getattr(st.store, "last_save_error", "") if st.store else ""
        if err:
            st.save_error = err
            self._emit_status(f"⚠ 进度未能保存：{err}")
        else:
            # 落盘恢复正常 → 清掉旧的告警，不能永久残留（审计 P3-1）
            st.save_error = ""

    def _save_position(self) -> None:
        """保存练习位置；**任何落盘异常都不得让界面操作失败**（磁盘只读/占用/满）。

        只记录原因并提示用户，界面继续可用——与「进度自动保留」的承诺一致：
        保存失败要让人看得见，但不能把答题流程打断。
        """
        st = self.state
        if st.session is None:
            return
        try:
            st.session.save_position()
        except Exception as exc:
            st.save_error = f"{type(exc).__name__}: {exc}"
            self._emit_status(f"⚠ 进度未能保存：{st.save_error}")
            return
        if not getattr(st.store, "last_save_error", ""):
            st.save_error = ""            # 落盘恢复后清掉旧告警

    def _refresh_all(self, raise_practice: bool = False) -> None:
        self.state_changed.emit()
        self.stats_changed.emit()
        if raise_practice:
            self.practice_changed.emit()

    def snapshot(self) -> UiState:
        """返回当前状态的浅拷贝（供测试与只读展示）。"""
        return replace(self.state)


def QTimerSingleShot(delay_ms: int, callback) -> None:  # noqa: N802 - 与 Qt 命名风格保持一致
    """延迟回调（单独封装，便于测试替换而不必启动事件循环）。"""
    try:
        from PySide6.QtCore import QTimer

        QTimer.singleShot(int(max(0, delay_ms)), callback)
    except Exception:
        callback()
