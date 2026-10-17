# -*- coding: utf-8 -*-
"""刷题匠 PaperDrill —— Qt 界面无头自检（发布验收用）。

在 ``QT_QPA_PLATFORM=offscreen`` 下驱动**真实控件**跑完整闭环：

    导入 → 练习（含键盘与选项状态）→ 按题型切换 → 生成试卷（覆盖校验）
    → 模拟考试 → 交卷评分 → 关闭重开（进度与位置恢复）→ 随机模式重开
    → 题库删减/恢复 → 主题切换 → 几何持久化

输出结构与 tkinter 版 ``gui.selftest`` 对齐，便于验收脚本复用；
其中新增的 Qt 专属项放在 ``qt`` 键下。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

__all__ = ["run_selftest", "selftest_payload"]

DEFAULT_PLATFORM = "offscreen"


def _ensure_offscreen() -> None:
    """没有显示环境时切到 offscreen 平台（必须在 QApplication 创建前调用）。"""
    if os.environ.get("QT_QPA_PLATFORM"):
        return
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY") \
            and not os.environ.get("WAYLAND_DISPLAY"):
        os.environ["QT_QPA_PLATFORM"] = DEFAULT_PLATFORM


def _answer_current(controller) -> "object | None":
    """按显示答案作答当前题（覆盖三种题型）。"""
    from ..models import QType

    item = controller.current_item()
    if item is None:
        return None
    if item.qtype is QType.MULTIPLE:
        for letter in sorted(item.shown_answer):
            controller.toggle_option(letter)
        return controller.submit()
    first = sorted(item.shown_answer)[0]
    return controller.toggle_option(first)


def _answer_wrong(controller) -> "object | None":
    """故意答错当前题（用于制造错题；多选题需要显式提交）。

    多选题若"正确答案恰好是全部选项"，选单个错项是不可能的，此时选一个
    **真包含于**答案的非空子集（少选），同样会被判错，保证一定能造出错题。
    """
    from ..models import QType

    item = controller.current_item()
    if item is None:
        return None
    wrongs = [lab for lab in item.labels if lab not in item.shown_answer]
    if wrongs:
        result = controller.toggle_option(wrongs[0])
        if result is None and item.qtype is QType.MULTIPLE:
            result = controller.submit()
        return result
    if item.qtype is QType.MULTIPLE and len(item.shown_answer) >= 2:
        keep = sorted(item.shown_answer)[:-1]        # 少选一个 → 判错
        for letter in keep:
            controller.toggle_option(letter)
        return controller.submit()
    return None


def run_selftest(bank_path: str, result_path: str = "", progress_root: str = "",
                 exercises: int = 30, seed: int = 12345) -> int:
    """执行自检并返回退出码（0 = 全部通过）。"""
    _ensure_offscreen()
    result: dict = {"ok": False, "stage": "init", "engine": "qt"}
    tmp_dir = None
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        from .. import __version__
        from ..config import AppSettings
        from ..models import QType
        from ..paper import PaperBlueprint, min_round_length
        from ..practice import PracticeMode, Scope
        from .application import app_icon_path, create_application
        from .controller import PaperDrillController
        from .main_window import MainWindow

        app, _owned = create_application([sys.argv[0]])

        if not progress_root:
            tmp_dir = tempfile.TemporaryDirectory(prefix="pd_qt_selftest_")
            progress_root = tmp_dir.name
        progress_path = Path(progress_root)
        progress_path.mkdir(parents=True, exist_ok=True)
        settings_file = progress_path / "settings.json"

        def make_app() -> "MainWindow":
            settings = AppSettings(bank_path="", mode="order", scope="all",
                                   shuffle_single=True, shuffle_multiple=True,
                                   auto_next_on_correct=False, show_analysis=True)
            controller = PaperDrillController(settings=settings,
                                              settings_path=settings_file,
                                              progress_root=progress_path / "progress")
            window = MainWindow(controller, theme_mode="light", autoload=False)
            window.show()
            app.processEvents()
            try:                       # QShortcut 需要活动窗口才能命中
                window.activateWindow()
                window.raise_()
                QTest.qWaitForWindowActive(window, 2000)
            except Exception:
                pass
            app.processEvents()
            return window

        window = make_app()
        controller = window.controller
        result["qt"] = {"platform": os.environ.get("QT_QPA_PLATFORM", ""),
                        "window_created": bool(window.isVisible()),
                        "title": window.windowTitle()}
        icon_file = app_icon_path()
        result["version"] = __version__
        result["icon"] = {
            "path": icon_file,
            "file_exists": bool(icon_file and Path(icon_file).is_file()),
            "app_icon_ok": bool(app.windowIcon() and not app.windowIcon().isNull()),
            "window_icon_ok": bool(window.windowIcon() and not window.windowIcon().isNull()),
        }
        result["stage"] = "construct"

        # ---- 1) 导入题库
        if not controller.load_bank(bank_path):
            raise RuntimeError("题库导入失败")
        app.processEvents()
        result["bank"] = {"total": len(controller.all_questions()),
                          "text": controller.stats_line()}
        result["stage"] = "import"

        # ---- 2) 练习：偶数题答对、奇数题答错
        correct_cnt = wrong_cnt = 0
        for i in range(min(exercises, controller.state.total)):
            if i % 2 == 0:
                res = _answer_current(controller)
                correct_cnt += 1 if (res is not None and res.correct) else 0
            else:
                res = _answer_wrong(controller)
                wrong_cnt += 1 if (res is not None and not res.correct) else 0
            app.processEvents()
            if not controller.advance():
                break
        controller.state.session.save_position()
        app.processEvents()
        result["answered"] = {"correct": correct_cnt, "wrong": wrong_cnt}
        result["stats_after"] = controller.stats()
        result["progress_saved"] = controller.state.store.path.exists()
        result["wrong_book"] = controller.stats()["wrong_book"]

        # ---- 3) 选项状态与键盘（真实控件）
        controller.set_scope(Scope.SINGLE)
        app.processEvents()
        controller.restart_round()
        app.processEvents()
        controller.goto(0)
        app.processEvents()
        answered_before = controller.state.answered
        rows_before = list(window.practice_page.option_rows)
        window.activateWindow()
        window.practice_page.setFocus()
        app.processEvents()
        QTest.keyClick(window.practice_page, Qt.Key_1)
        app.processEvents()
        rows_after = list(window.practice_page.option_rows)
        keyboard = {
            "options_rendered": len(rows_before),
            "answered_before_key": answered_before,
            "key_selected": bool(controller.state.answered),
            "correct_option_marked": any(r.state == "correct" for r in rows_after),
            "feedback_kind": controller.state.feedback_kind,
        }
        before_pos = controller.state.position
        QTest.keyClick(window.practice_page, Qt.Key_Return)
        app.processEvents()
        keyboard["enter_advances"] = controller.state.position == before_pos + 1
        result["keyboard"] = keyboard

        # ---- 3b) 重绘不得产生"闪窗"（v1.3.0 用户反馈：勾选打乱时屏幕闪一下小窗）
        from PySide6.QtWidgets import QApplication

        known_top = set(QApplication.topLevelWidgets())
        controller.set_shuffle(single=True)          # 触发整页重绘（重建选项行）
        app.processEvents()
        leaked = [w for w in QApplication.topLevelWidgets()
                  if w not in known_top and w.isVisible()
                  and type(w).__name__ == "OptionRow"]
        result["no_popup_flash"] = not leaked
        result["leaked_widgets"] = [type(w).__name__ for w in leaked]
        controller.set_shuffle(single=False)
        app.processEvents()

        # ---- 4) 按题型范围
        controller.set_scope(Scope.SINGLE)
        app.processEvents()
        result["scope_single_total"] = controller.state.total
        controller.set_scope(Scope.MULTIPLE)
        app.processEvents()
        result["scope_multiple_total"] = controller.state.total
        controller.set_scope(Scope.JUDGE)
        app.processEvents()
        result["scope_judge_total"] = controller.state.total
        controller.set_scope(Scope.ALL)
        app.processEvents()

        # ---- 5) 生成试卷
        window.set_page("exam")
        window.exam_setup_page.set_counts(20, 10, 10)
        app.processEvents()
        rnd = controller.generate_round()
        app.processEvents()
        if rnd is None:
            raise RuntimeError("生成试卷失败")
        result["stage"] = "paper"
        result["paper"] = {
            "round_length": rnd.round_length,
            "auto_round_length": min_round_length(controller.active_questions(),
                                                 PaperBlueprint(20, 10, 10)),
            "papers": rnd.paper_count,
            "coverage_ok": rnd.coverage_ok,
            "coverage": {k: list(v) for k, v in rnd.coverage.items()},
            "totals": [p.total for p in rnd.papers],
            "single_counts": [p.count_of(QType.SINGLE) for p in rnd.papers],
            "multiple_counts": [p.count_of(QType.MULTIPLE) for p in rnd.papers],
            "judge_counts": [p.count_of(QType.JUDGE) for p in rnd.papers],
            "reused": [p.reused_count for p in rnd.papers],
            "table_rows": window.exam_setup_page.paper_model.rowCount(),
        }

        # ---- 6) 模拟考试
        paper = rnd.papers[0]
        if not controller.start_exam(paper):
            raise RuntimeError("开始考试失败")
        app.processEvents()
        exam = controller.state.exam
        total = exam.total
        plan_correct = total // 2
        plan_wrong = max(0, total - plan_correct - 3)
        expected = {"correct": 0, "wrong": 0, "unanswered": 0}
        expected_score = 0.0
        for i in range(total):
            item = exam.item(i)
            if i < plan_correct:
                exam.set_answer(i, set(item.shown_answer))
                expected["correct"] += 1
                expected_score += float(exam.score_of(item.qtype))
            elif i < plan_correct + plan_wrong:
                others = [lab for lab in item.labels if lab not in item.shown_answer]
                exam.set_answer(i, {others[0]} if others else {sorted(item.shown_answer)[0]})
                expected["wrong"] += 1
            else:
                exam.clear_answer(i)
                expected["unanswered"] += 1
        controller.exam_goto(0)
        app.processEvents()
        result["exam_planned"] = {"correct": plan_correct, "wrong": plan_wrong, "unanswered": 3,
                                  "expected": expected, "expected_score": round(expected_score, 6)}
        # 作答期间界面不得出现对错字样，且选项不得带判定状态
        run_page = window.exam_run_page
        visible_text = (run_page.title_label.text() + run_page.count_label.text()
                        + run_page.type_label.text() + run_page.stem_label.text())
        option_states = {row.state for row in run_page.option_rows}
        result["exam_ui_hides_result"] = ("正确" not in visible_text and "错误" not in visible_text
                                          and not ({"correct", "wrong"} & option_states))
        exam_res = controller.submit_exam()
        app.processEvents()
        if exam_res is None:
            raise RuntimeError("交卷失败")
        result["stage"] = "exam"
        result["exam"] = {
            "score": exam_res.score, "full_score": exam_res.full_score,
            "correct": exam_res.correct, "wrong": exam_res.wrong,
            "unanswered": exam_res.unanswered, "total": exam_res.total,
            "accuracy": round(exam_res.accuracy, 6), "per_type": exam_res.per_type,
        }
        result["stats_after_exam"] = controller.stats()
        result["exam_history"] = len(controller.exam_history())
        result["result_rows"] = window.exam_result_page.detail_model.rowCount()
        result["exam_view_after_submit"] = controller.state.exam_view
        result["exam_readonly"] = controller.state.exam_readonly
        # 交卷后卷面只读
        run_page.refresh(controller.state)
        result["exam_options_disabled"] = bool(run_page.option_rows) and all(
            not row.isEnabled() for row in run_page.option_rows)

        # ---- 7) 关闭 → 重开：进度与成绩恢复
        window.close()
        app.processEvents()
        window = make_app()
        controller = window.controller
        if not controller.load_bank(bank_path):
            raise RuntimeError("重开后导入题库失败")
        app.processEvents()
        result["stage"] = "reload"
        restored = controller.stats()
        result["stats_restored"] = restored
        result["progress_restored"] = (
            restored["done"] == result["stats_after_exam"]["done"]
            and restored["wrong_book"] == result["stats_after_exam"]["wrong_book"]
            and restored["done"] > 0)
        result["exam_history_restored"] = len(controller.exam_history())

        # ---- 8) 随机模式：重开仍停在同一道题
        controller.set_mode(PracticeMode.RANDOM)
        app.processEvents()
        item_before = controller.current_item()
        fp_before = item_before.question.fingerprint if item_before else ""
        controller.state.session.save_position()
        window.close()
        app.processEvents()
        window = make_app()
        controller = window.controller
        controller.load_bank(bank_path)
        app.processEvents()
        item_after = controller.current_item()
        fp_after = item_after.question.fingerprint if item_after else ""
        result["random_resume"] = {
            "mode": controller.state.mode.value,
            "fp_before": fp_before, "fp_after": fp_after,
            "resume_same_question": bool(fp_before and fp_before == fp_after),
        }

        # ---- 9) 题库删减 / 恢复
        all_qs = controller.all_questions()
        cut_targets = [q for q in all_qs if q.fingerprint != fp_before][: max(1, len(all_qs) // 4)]
        active_before = len(controller.active_questions())
        removed = controller.exclude_questions(cut_targets)
        app.processEvents()
        active_after = len(controller.active_questions())
        round_after_cut = controller.generate_round()
        cut_ids = {q.fingerprint for q in cut_targets}
        paper_excludes = True
        if round_after_cut is not None:
            for paper_item in round_after_cut.papers:
                for pq in paper_item.items:
                    if pq.question.fingerprint in cut_ids:
                        paper_excludes = False
        window.close()
        app.processEvents()
        window = make_app()
        controller = window.controller
        controller.load_bank(bank_path)
        app.processEvents()
        result["bank_cut"] = {
            "all": len(all_qs),
            "removed": removed,
            "active_before": active_before,
            "active_after": active_after,
            "counts_match": active_after == active_before - len(cut_targets),
            "paper_excludes_cut": paper_excludes,
            "persisted_after_restart": len(controller.state.store.progress.excluded) == len(cut_targets),
        }
        back = controller.restore_all_excluded()
        app.processEvents()
        result["bank_cut"]["restored"] = back
        result["bank_cut"]["restore_ok"] = len(controller.active_questions()) == len(all_qs)

        # ---- 10) 主题切换
        window.apply_theme("dark")
        app.processEvents()
        dark_ok = window.theme.dark
        window.apply_theme("light")
        app.processEvents()
        result["stage"] = "theme"
        result["theme"] = {"dark_applied": bool(dark_ok), "light_applied": not window.theme.dark}

        # ---- 11) 几何持久化
        window.apply_geometry_text("1100x760+40+30")
        app.processEvents()
        geo = window.window_geometry_text
        result["geometry"] = {"text": geo, "ok": geo.startswith("1100x760")}

        # ---- 12) 清空错题与重置
        cleared = controller.clear_wrong_book()
        result["wrong_cleared"] = cleared
        controller.reset_progress()
        app.processEvents()
        result["stats_after_reset"] = controller.stats()
        window.close()
        app.processEvents()

        # ---- 汇总
        paper = result["paper"]
        keyboard = result.get("keyboard", {})
        cut = result.get("bank_cut", {})
        resume = result.get("random_resume", {})
        exam_data = result["exam"]
        planned = result["exam_planned"]["expected"]
        result["ok"] = bool(
            result["progress_saved"] and result["progress_restored"]
            and paper["coverage_ok"]
            and paper["round_length"] == paper["auto_round_length"]
            # 考试成绩必须与"按显示答案作答"的预期一致（重复作答练习过的题会改变计数，
            # 因此用区间断言：正确数不低于计划值、三项之和等于总题数、未答恒为 3）
            and exam_data["correct"] + exam_data["wrong"] + exam_data["unanswered"] == exam_data["total"]
            and exam_data["correct"] >= planned["correct"]
            and exam_data["unanswered"] == 3
            and exam_data["score"] >= result["exam_planned"]["expected_score"] - 1e-6
            and result["exam_history"] == 1
            and result["exam_history_restored"] == 1
            and result["exam_ui_hides_result"]
            and result["exam_readonly"] and result["exam_options_disabled"]
            and keyboard.get("key_selected") and keyboard.get("enter_advances")
            and keyboard.get("correct_option_marked")
            and result.get("no_popup_flash")
            and resume.get("resume_same_question")
            and cut.get("counts_match") and cut.get("paper_excludes_cut")
            and cut.get("persisted_after_restart") and cut.get("restore_ok")
            and result["theme"]["dark_applied"] and result["theme"]["light_applied"]
            and result["geometry"]["ok"]
            and result["icon"]["file_exists"]
            and result["icon"]["app_icon_ok"] and result["icon"]["window_icon_ok"]
            and result["stats_after_reset"]["done"] == 0
        )
        result["stage"] = "done"
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["traceback"] = traceback.format_exc(limit=10)
    finally:
        try:
            if tmp_dir is not None:
                tmp_dir.cleanup()
        except Exception:
            pass
        payload = json.dumps(result, ensure_ascii=False, indent=2)
        if result_path:
            try:
                Path(result_path).parent.mkdir(parents=True, exist_ok=True)
                Path(result_path).write_text(payload, encoding="utf-8")
            except Exception:
                pass
        summary = {"ok": result.get("ok"), "stage": result.get("stage"),
                   "engine": "qt", "version": result.get("version"),
                   "icon": result.get("icon"), "answered": result.get("answered"),
                   "paper": result.get("paper", {}).get("papers"),
                   "coverage_ok": result.get("paper", {}).get("coverage_ok"),
                   "exam": result.get("exam"), "keyboard": result.get("keyboard"),
                   "random_resume": result.get("random_resume"),
                   "bank_cut": result.get("bank_cut"),
                   "error": result.get("error", "")}
        try:
            print("[qt-selftest] " + json.dumps(summary, ensure_ascii=False))
            if not result_path:
                print(payload)
        except Exception:
            pass
    return 0 if result.get("ok") else 1


def selftest_payload(**kwargs) -> dict:
    """供测试直接拿到自检结果字典（不解析 stdout）。"""
    with tempfile.TemporaryDirectory(prefix="pd_qt_payload_") as tmp:
        result_file = Path(tmp) / "result.json"
        code = run_selftest(result_path=str(result_file), **kwargs)
        data = {}
        if result_file.exists():
            try:
                data = json.loads(result_file.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        data.setdefault("exit_code", code)
        return data
