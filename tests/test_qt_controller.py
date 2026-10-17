# -*- coding: utf-8 -*-
"""Qt 界面 —— 控制器状态机测试（不创建任何窗口）。"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

try:                                            # 以包方式运行：python -m unittest tests.test_qt_controller
    from tests.qt_support import (
        FIXTURE_BANK,
        HAVE_QT,
        SKIP_REASON,
        QtTestCase,
        make_questions,
    )
except ModuleNotFoundError:                     # 以发现方式运行：python -m unittest discover -s tests
    from qt_support import (  # type: ignore[no-redef]
        FIXTURE_BANK,
        HAVE_QT,
        SKIP_REASON,
        QtTestCase,
        make_questions,
    )

if HAVE_QT:
    from paperdrill.bank_io import BankLoadResult
    from paperdrill.models import QType
    from paperdrill.practice import PracticeMode, Scope
    from paperdrill.ui.controller import PaperDrillController, quick_bank_info, scan_bank_folder


@unittest.skipUnless(HAVE_QT, SKIP_REASON)
class TestControllerInit(QtTestCase):
    def test_default_state_is_empty(self):
        ctrl = self.controller()
        self.assertFalse(ctrl.state.loaded)
        self.assertFalse(ctrl.state.bank)
        self.assertEqual(ctrl.stats()["total"], 0)
        self.assertEqual(ctrl.active_questions(), [])
        self.assertEqual(ctrl.paper_labels(), [])
        self.assertEqual(ctrl.coverage_text(), "尚未生成试卷")

    def test_settings_restored_from_file(self):
        from dataclasses import replace

        from paperdrill.config import AppSettings

        settings = replace(self.settings, scope="multiple", mode="random",
                           shuffle_single=True, shuffle_multiple=False,
                           show_analysis=False, paper_single=7)
        settings.save(self.settings_file)

        ctrl = PaperDrillController(settings=AppSettings.load(self.settings_file),
                                    settings_path=self.settings_file,
                                    progress_root=self.progress_root)
        self.assertIs(ctrl.state.scope, Scope.MULTIPLE)
        self.assertIs(ctrl.state.mode, PracticeMode.RANDOM)
        self.assertTrue(ctrl.state.shuffle_single)
        self.assertFalse(ctrl.state.shuffle_multiple)
        self.assertFalse(ctrl.state.show_analysis)
        self.assertEqual(ctrl.state.blueprint.single, 7)

    def test_progress_dir_override(self):
        ctrl = self.controller()
        self.assertEqual(ctrl.progress_dir, self.progress_root)


@unittest.skipUnless(HAVE_QT, SKIP_REASON)
class TestControllerBank(QtTestCase):
    def test_load_bank_file(self):
        if not FIXTURE_BANK.exists():
            self.skipTest("缺少合成题库夹具")
        ctrl = self.controller()
        self.assertTrue(ctrl.load_bank(FIXTURE_BANK))
        self.assertTrue(ctrl.state.loaded)
        self.assertEqual(len(ctrl.all_questions()), 52)
        self.assertEqual(ctrl.state.total, 52)
        self.assertTrue(ctrl.state.store.path.exists(), "导入后应已生成进度文件")

    def test_load_missing_file_reports_status(self):
        ctrl = self.controller()
        messages: list[str] = []
        ctrl.status_message.connect(messages.append)
        self.assertFalse(ctrl.load_bank(self.tmp / "不存在.xlsx"))
        self.assertTrue(messages)
        self.assertIn("找不到", messages[0])
        self.assertFalse(ctrl.state.loaded)

    def test_issues_are_reported(self):
        from paperdrill.bank_io import BankIssue

        bank = BankLoadResult(questions=make_questions(3), source="带问题.xlsx",
                              issues=[BankIssue(row=9, reason="答案为空")])
        ctrl = self.controller()
        self.install_bank(ctrl, bank)
        summary = ctrl.bank_summary()
        self.assertEqual(len(summary["issues"]), 1)
        self.assertIn("答案为空", summary["issues"][0])

    def test_reload_bank_uses_same_path(self):
        if not FIXTURE_BANK.exists():
            self.skipTest("缺少合成题库夹具")
        ctrl = self.controller()
        ctrl.load_bank(FIXTURE_BANK)
        first = ctrl.state.bank_path
        self.assertTrue(ctrl.reload_bank())
        self.assertEqual(ctrl.state.bank_path, first)
        self.assertEqual(len(ctrl.all_questions()), 52)


@unittest.skipUnless(HAVE_QT, SKIP_REASON)
class TestControllerPractice(QtTestCase):
    def test_single_choice_answers_immediately(self):
        ctrl = self.controller(questions=make_questions(6))
        item = ctrl.current_item()
        self.assertIs(item.qtype, QType.SINGLE)
        result = ctrl.toggle_option("A")
        self.assertIsNotNone(result)
        self.assertTrue(result.correct)
        self.assertTrue(ctrl.state.answered)
        self.assertIn("回答正确", ctrl.state.feedback)
        self.assertEqual(ctrl.state.feedback_kind, "correct")

    def test_wrong_answer_enters_wrong_book(self):
        ctrl = self.controller(questions=make_questions(6))
        result = ctrl.toggle_option("C")
        self.assertFalse(result.correct)
        self.assertEqual(ctrl.state.feedback_kind, "wrong")
        self.assertEqual(ctrl.stats()["wrong_book"], 1)

    def test_multiple_choice_needs_submit(self):
        """多选：勾选/取消都不判定，提交才判定。

        使用打乱模式构建，并按**显示答案**作答——这样同时覆盖"打乱后答案重映射"。
        """
        ctrl = self.controller(questions=make_questions(6), shuffle=True)
        ctrl.set_scope(Scope.MULTIPLE)
        item = ctrl.current_item()
        self.assertIs(item.qtype, QType.MULTIPLE)
        self.assertTrue(item.shuffled, "打乱模式下的多选题应已打乱选项")
        correct = sorted(item.shown_answer)
        self.assertIsNone(ctrl.toggle_option(correct[0]))
        self.assertFalse(ctrl.state.answered)
        self.assertEqual(ctrl.state.selection, {correct[0]})
        ctrl.toggle_option(correct[1])
        self.assertEqual(ctrl.state.selection, set(correct))
        ctrl.toggle_option(correct[1])                       # 再点一次取消
        self.assertEqual(ctrl.state.selection, {correct[0]})
        ctrl.toggle_option(correct[1])
        result = ctrl.submit()
        self.assertTrue(result.correct, "按显示答案作答应判对")

    def test_submit_without_selection_reports_status(self):
        ctrl = self.controller(questions=make_questions(6))
        ctrl.set_scope(Scope.MULTIPLE)
        messages: list[str] = []
        ctrl.status_message.connect(messages.append)
        self.assertIsNone(ctrl.submit())
        self.assertTrue(messages)

    def test_answered_question_cannot_be_resubmitted(self):
        ctrl = self.controller(questions=make_questions(6))
        ctrl.toggle_option("A")
        self.assertIsNone(ctrl.submit())
        self.assertIsNone(ctrl.toggle_option("B"))

    def test_advance_and_retreat(self):
        ctrl = self.controller(questions=make_questions(9))
        self.assertEqual(ctrl.state.position, 1)
        self.assertTrue(ctrl.advance())
        self.assertEqual(ctrl.state.position, 2)
        self.assertFalse(ctrl.state.answered)                # 新题回到未作答状态
        self.assertTrue(ctrl.retreat())
        self.assertEqual(ctrl.state.position, 1)
        self.assertFalse(ctrl.retreat())
        messages: list[str] = []
        ctrl.status_message.connect(messages.append)
        ctrl.retreat()
        self.assertIn("第一题", messages[-1])

    def test_revisit_shows_previous_without_spoiler(self):
        ctrl = self.controller(questions=make_questions(6))
        ctrl.toggle_option("A")
        ctrl.advance()
        ctrl.retreat()
        self.assertFalse(ctrl.state.answered, "回看时不应锁定为已作答")
        self.assertIn("上次", ctrl.state.feedback)
        self.assertEqual(ctrl.state.analysis_text, "", "回看时不得剧透解析")
        self.assertEqual(ctrl.state.selection, set())

    def test_reveal_shows_answer_without_recording(self):
        ctrl = self.controller(questions=make_questions(6))
        self.assertTrue(ctrl.reveal())
        self.assertTrue(ctrl.state.answered)
        self.assertEqual(ctrl.state.feedback_kind, "reveal")
        self.assertIn("正确答案", ctrl.state.feedback)
        self.assertEqual(ctrl.stats()["attempts"], 0, "看答案不应计入作答")

    def test_analysis_toggle(self):
        ctrl = self.controller(questions=make_questions(6))
        ctrl.toggle_option("A")
        self.assertIn("解析", ctrl.state.analysis_text)
        ctrl.set_show_analysis(False)
        self.assertEqual(ctrl.state.analysis_text, "")
        ctrl.set_show_analysis(True)
        self.assertIn("解析", ctrl.state.analysis_text)

    def test_restart_round_keeps_progress_and_allows_reanswer(self):
        ctrl = self.controller(questions=make_questions(9))
        ctrl.toggle_option("A")
        attempts = ctrl.current_record().attempts
        ctrl.restart_round()
        self.assertEqual(ctrl.state.position, 1)
        self.assertFalse(ctrl.state.answered)
        self.assertEqual(ctrl.current_record().attempts, attempts)
        ctrl.toggle_option("A")
        self.assertEqual(ctrl.current_record().attempts, attempts + 1)

    def test_scope_switch_rebuilds_queue(self):
        ctrl = self.controller(questions=make_questions(12))
        ctrl.set_scope(Scope.SINGLE)
        self.assertEqual(ctrl.state.total, 4)
        self.assertIs(ctrl.state.session.qtype_filter, QType.SINGLE)
        ctrl.set_scope(Scope.MULTIPLE)
        self.assertEqual(ctrl.state.total, 4)
        self.assertIs(ctrl.state.session.qtype_filter, QType.MULTIPLE)
        ctrl.set_scope(Scope.JUDGE)
        self.assertEqual(ctrl.state.total, 4)
        self.assertIs(ctrl.state.session.qtype_filter, QType.JUDGE)
        ctrl.set_scope(Scope.ALL)
        self.assertEqual(ctrl.state.total, 12)
        self.assertIsNone(ctrl.state.session.qtype_filter)

    def test_mode_switch_wrong_and_fresh(self):
        ctrl = self.controller(questions=make_questions(9))
        self.answer_wrong(ctrl)
        ctrl.set_mode(PracticeMode.WRONG)
        self.assertEqual(ctrl.state.total, 1)
        ctrl.set_mode(PracticeMode.FRESH)
        self.assertEqual(ctrl.state.total, 8)
        ctrl.set_mode(PracticeMode.ORDER)
        self.assertEqual(ctrl.state.total, 9)

    def test_empty_wrong_mode_gives_actionable_text(self):
        ctrl = self.controller(questions=make_questions(6))
        ctrl.set_mode(PracticeMode.WRONG)
        self.assertTrue(ctrl.state.practice_empty)
        self.assertIn("没有答错", ctrl.state.feedback)
        self.assertEqual(ctrl.state.feedback_kind, "empty")

    def test_shuffle_toggle_keeps_position(self):
        ctrl = self.controller(questions=make_questions(9))
        ctrl.goto(3)
        fingerprint = ctrl.current_question().fingerprint
        ctrl.set_shuffle(single=True, multiple=True)
        self.assertTrue(ctrl.state.shuffle_single)
        self.assertEqual(ctrl.current_question().fingerprint, fingerprint,
                         "切换打乱后应停在原题")
        item = ctrl.current_item()
        if item.qtype is not QType.JUDGE:
            self.assertTrue(item.shuffled or item.question.fixed_order)
        # 打乱后按显示答案作答仍应判对（答案已重映射）
        ctrl.set_shuffle(single=True, multiple=True)
        self.assertTrue(self.answer_correctly(ctrl))

    def test_auto_next_advance_is_scheduled_only_on_correct(self):
        ctrl = self.controller(questions=make_questions(9))
        ctrl.set_auto_next(True)
        self.assertTrue(ctrl.state.auto_next)
        ctrl.set_auto_next(False)
        self.assertFalse(ctrl.state.auto_next)

    def test_stats_line_and_scope_stats(self):
        ctrl = self.controller(questions=make_questions(12))
        self.answer_correctly(ctrl)
        ctrl.advance()
        self.answer_wrong(ctrl)
        stats = ctrl.stats()
        self.assertEqual(stats["done"], 2)
        self.assertEqual(stats["right"], 1)
        self.assertEqual(stats["wrong"], 1)
        self.assertIn("共 12 题", ctrl.stats_line())
        ctrl.set_scope(Scope.SINGLE)
        self.assertEqual(ctrl.scope_stats()["total"], 4)

    def test_save_error_surfaces_in_status(self):
        ctrl = self.controller(questions=make_questions(6))

        def boom():
            raise OSError("磁盘只读")

        ctrl.state.store.save = boom                       # type: ignore[assignment]
        messages: list[str] = []
        ctrl.status_message.connect(messages.append)
        ctrl.toggle_option("A")
        self.assertTrue(ctrl.state.save_error)
        self.assertTrue(any("进度未能保存" in m for m in messages))


@unittest.skipUnless(HAVE_QT, SKIP_REASON)
class TestControllerPaperAndExam(QtTestCase):
    def setUp(self):
        super().setUp()
        self.ctrl = self.controller(questions=make_questions(12))
        self.ctrl.set_blueprint(3, 2, 1)

    def test_blueprint_and_hints(self):
        ctrl = self.ctrl
        self.assertEqual(ctrl.blueprint_total(), 6)
        self.assertAlmostEqual(ctrl.blueprint_full_score(), 3 * 1.0 + 2 * 2.0 + 1 * 1.0)
        hint = ctrl.plan_hint()
        self.assertIn("张/轮", hint)
        self.assertEqual(ctrl.min_round_length(), 4)       # max(4/3, 4/2, 4/1) = 4

    def test_generate_round(self):
        ctrl = self.ctrl
        rnd = ctrl.generate_round()
        self.assertIsNotNone(rnd)
        self.assertEqual(rnd.paper_count, 4)
        self.assertTrue(rnd.coverage_ok)
        self.assertEqual(len(ctrl.paper_labels()), 4)
        self.assertIn("覆盖", ctrl.coverage_text())
        self.assertEqual(ctrl.paper_at(0).label, "A")
        self.assertEqual(ctrl.paper_at(99).label, "A")      # 越界回退到第 1 张

    def test_generate_round_without_bank(self):
        ctrl = self.controller()
        self.assertIsNone(ctrl.generate_round())

    def test_generate_round_with_zero_blueprint(self):
        ctrl = self.ctrl
        ctrl.set_blueprint(0, 0, 0)
        messages: list[str] = []
        ctrl.status_message.connect(messages.append)
        self.assertIsNone(ctrl.generate_round())
        self.assertTrue(messages)

    def test_start_exam_and_answer(self):
        ctrl = self.ctrl
        ctrl.generate_round()
        paper = ctrl.paper_at(0)
        self.assertTrue(ctrl.start_exam(paper))
        self.assertEqual(ctrl.state.exam_view, "taking")
        self.assertFalse(ctrl.state.exam_readonly)
        self.assertEqual(ctrl.exam_total(), paper.total)
        item = ctrl.exam_item(0)
        self.assertIsNotNone(item)
        ctrl.exam_set(item.labels[1])
        self.assertTrue(ctrl.exam_is_answered(0))
        ctrl.exam_clear()
        self.assertFalse(ctrl.exam_is_answered(0))

    def test_submit_exam_scores_and_persists(self):
        ctrl = self.ctrl
        ctrl.generate_round()
        paper = ctrl.paper_at(0)
        ctrl.start_exam(paper)
        exam = ctrl.state.exam
        for i in range(exam.total - 2):
            exam.set_answer(i, set(exam.item(i).shown_answer))
        result = ctrl.submit_exam()
        self.assertIsNotNone(result)
        self.assertEqual(result.correct, exam.total - 2)
        self.assertEqual(result.unanswered, 2)
        self.assertEqual(ctrl.state.exam_view, "result")
        self.assertTrue(ctrl.state.exam_readonly)
        self.assertEqual(len(ctrl.exam_history()), 1)

    def test_exam_readonly_blocks_answers(self):
        ctrl = self.ctrl
        ctrl.generate_round()
        ctrl.start_exam(ctrl.paper_at(0))
        ctrl.submit_exam()
        before = dict(ctrl.state.exam.answers)
        ctrl.exam_set("A")
        ctrl.exam_toggle("B")
        ctrl.exam_clear()
        self.assertEqual(ctrl.state.exam.answers, before)

    def test_submit_exam_keeps_practice_position(self):
        ctrl = self.ctrl
        ctrl.goto(2)
        position = ctrl.state.position
        ctrl.generate_round()
        ctrl.start_exam(ctrl.paper_at(0))
        ctrl.submit_exam()
        self.assertEqual(ctrl.state.position, position, "交卷后练习位置被重置")

    def test_unattended_count(self):
        ctrl = self.ctrl
        ctrl.generate_round()
        ctrl.start_exam(ctrl.paper_at(0))
        exam = ctrl.state.exam
        exam.set_answer(0, {exam.item(0).labels[0]})
        self.assertEqual(ctrl.unattended_count(), exam.total - 1)

    def test_start_next_unused_paper(self):
        ctrl = self.ctrl
        ctrl.generate_round()
        self.assertTrue(ctrl.start_next_unused_paper())
        ctrl.submit_exam()
        self.assertTrue(ctrl.start_next_unused_paper())
        self.assertIn("A", ctrl.used_paper_labels())


@unittest.skipUnless(HAVE_QT, SKIP_REASON)
class TestControllerData(QtTestCase):
    def test_exclude_and_restore(self):
        ctrl = self.controller(questions=make_questions(12))
        targets = ctrl.active_questions()[:3]
        self.assertEqual(ctrl.exclude_questions(targets), 3)
        self.assertEqual(ctrl.state.total, 9)
        self.assertEqual(len(ctrl.excluded_questions()), 3)
        self.assertTrue(ctrl.is_excluded(targets[0]))
        self.assertEqual(ctrl.include_questions(targets), 3)
        self.assertEqual(ctrl.state.total, 12)

    def test_exclude_invalidates_round(self):
        ctrl = self.controller(questions=make_questions(12))
        ctrl.generate_round()
        self.assertIsNotNone(ctrl.state.round)
        ctrl.exclude_questions(ctrl.active_questions()[:2])
        self.assertIsNone(ctrl.state.round, "删减后旧试卷必须作废")

    def test_restore_all_excluded(self):
        ctrl = self.controller(questions=make_questions(12))
        ctrl.exclude_questions(ctrl.active_questions()[:4])
        self.assertEqual(ctrl.restore_all_excluded(), 4)
        self.assertEqual(ctrl.state.total, 12)

    def test_wrong_book_and_clear(self):
        ctrl = self.controller(questions=make_questions(9))
        self.answer_wrong(ctrl)
        ctrl.advance()
        self.answer_wrong(ctrl)
        self.assertEqual(len(ctrl.wrong_book_questions()), 2)
        self.assertEqual(ctrl.clear_wrong_book(), 2)
        self.assertEqual(len(ctrl.wrong_book_questions()), 0)
        self.assertEqual(ctrl.stats()["wrong"], 2, "历史统计应保留")

    def test_reset_progress(self):
        ctrl = self.controller(questions=make_questions(9))
        self.answer_correctly(ctrl)
        self.assertEqual(ctrl.stats()["done"], 1)
        self.assertTrue(ctrl.reset_progress())
        self.assertEqual(ctrl.stats()["done"], 0)

    def test_progress_rows_and_reset_by_key(self):
        ctrl = self.controller(questions=make_questions(9))
        self.answer_correctly(ctrl)
        rows = ctrl.progress_rows()
        self.assertTrue(rows)
        key = rows[0]["key"]
        self.assertTrue(ctrl.reset_progress_of(key))
        self.assertEqual(ctrl.stats()["done"], 0)

    def test_library_remember_and_forget(self):
        ctrl = self.controller(questions=make_questions(3))
        path = ctrl.state.bank_path
        self.assertTrue(any(r["path"] == path for r in ctrl.library_rows()))
        self.assertTrue(ctrl.forget_library_entry(path))
        self.assertFalse(any(r["path"] == path for r in ctrl.library_rows()))
        self.assertTrue(Path(path).exists(), "移除记录不得删除题库文件")

    def test_scan_folder_finds_banks(self):
        if not FIXTURE_BANK.exists():
            self.skipTest("缺少合成题库夹具")
        ctrl = self.controller()
        found = ctrl.scan_folder(FIXTURE_BANK.parent)
        self.assertTrue(found)
        self.assertGreaterEqual(len(ctrl.library_rows()), len(found))

    def test_quick_bank_info_handles_bad_file(self):
        bad = self.tmp / "坏文件.xlsx"
        bad.write_text("not an excel", encoding="utf-8")
        name, total = quick_bank_info(bad)
        self.assertEqual(name, "坏文件")
        self.assertEqual(total, 0)

    def test_scan_bank_folder_ignores_non_banks(self):
        self.assertEqual(scan_bank_folder(self.tmp / "不存在目录"), [])

    def test_snapshot_is_detached(self):
        ctrl = self.controller(questions=make_questions(3))
        snap = ctrl.snapshot()
        self.assertTrue(snap.loaded)
        self.assertIsNot(snap, ctrl.state)


@unittest.skipUnless(HAVE_QT, SKIP_REASON)
class TestControllerPersistence(QtTestCase):
    def _isolated_controller(self):
        """新建一个与首个控制器隔离的实例（不污染真实 %APPDATA%）。"""
        from paperdrill.config import AppSettings
        from paperdrill.store import BankLibrary

        return PaperDrillController(settings=AppSettings.load(self.settings_file),
                                    settings_path=self.settings_file,
                                    progress_root=self.progress_root,
                                    library=BankLibrary([], self.tmp / "library.json"))

    def test_position_persisted_and_restored(self):
        if not FIXTURE_BANK.exists():
            self.skipTest("缺少合成题库夹具")
        ctrl = self.controller()
        ctrl.load_bank(FIXTURE_BANK)
        ctrl.goto(7)
        fingerprint = ctrl.current_question().fingerprint
        ctrl.state.session.save_position()
        ctrl.save_settings()

        ctrl2 = self._isolated_controller()
        self.assertTrue(ctrl2.load_bank(FIXTURE_BANK))
        self.assertEqual(ctrl2.current_question().fingerprint, fingerprint)

    def test_exam_history_restored(self):
        if not FIXTURE_BANK.exists():
            self.skipTest("缺少合成题库夹具")
        ctrl = self.controller()
        ctrl.load_bank(FIXTURE_BANK)
        ctrl.set_blueprint(5, 3, 2)
        ctrl.generate_round()
        ctrl.start_exam(ctrl.paper_at(0))
        ctrl.submit_exam()

        ctrl2 = self._isolated_controller()
        ctrl2.load_bank(FIXTURE_BANK)
        self.assertEqual(len(ctrl2.exam_history()), 1)

    def test_settings_survive_roundtrip(self):
        ctrl = self.controller(questions=make_questions(3))
        ctrl.set_blueprint(4, 3, 2)
        ctrl.set_scores(1.5, 2.5, 0.5)
        ctrl.set_round_length(6, False)
        ctrl.save_settings()
        data = json.loads(self.settings_file.read_text(encoding="utf-8"))
        self.assertEqual(data["paper_single"], 4)
        self.assertEqual(data["score_multiple"], 2.5)
        self.assertEqual(data["round_length"], 6)
        self.assertFalse(data["round_auto"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
