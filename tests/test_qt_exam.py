# -*- coding: utf-8 -*-
"""Qt 界面 —— 模拟考试（配置 / 作答 / 成绩）测试。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

try:
    from tests.qt_support import HAVE_QT, SKIP_REASON, QtTestCase, make_questions, process_events
except ModuleNotFoundError:
    from qt_support import (  # type: ignore[no-redef]
        HAVE_QT,
        SKIP_REASON,
        QtTestCase,
        make_questions,
        process_events,
    )

if HAVE_QT:
    from paperdrill.models import QType
    from paperdrill.ui.pages.exam import ExamSetupPage
    from paperdrill.ui.pages.exam_run import ExamRunPage, NumberGrid
    from paperdrill.ui.pages.result import ExamResultPage
    from paperdrill.ui.theme import LIGHT


@unittest.skipUnless(HAVE_QT, SKIP_REASON)
class TestExamSetupPage(QtTestCase):
    def setUp(self):
        super().setUp()
        self.ctrl = self.controller(questions=make_questions(12))
        self.ctrl.set_blueprint(3, 2, 1)
        self.page = ExamSetupPage(self.ctrl, LIGHT)
        self.addCleanup(self.page.deleteLater)
        self.page.refresh(self.ctrl.state)

    def test_counts_and_scores_rendered(self):
        self.assertEqual(self.page.single_spin.value(), 3)
        self.assertEqual(self.page.multiple_spin.value(), 2)
        self.assertEqual(self.page.judge_spin.value(), 1)
        self.assertIn("6 题", self.page.total_label.text())
        self.assertIn("张/轮", self.page.plan_hint.text())

    def test_changing_count_updates_controller(self):
        self.page.single_spin.setValue(4)
        process_events()
        self.assertEqual(self.ctrl.state.blueprint.single, 4)
        self.assertIn("每卷合计 7 题", self.page.total_label.text())

    def test_changing_score_updates_controller(self):
        self.page.score_multiple.setValue(3.0)
        process_events()
        self.assertEqual(self.ctrl.state.scores["multiple"], 3.0)
        self.assertIn("满分", self.page.total_label.text())

    def test_generate_button_populates_table(self):
        self.page.generate_button.click()
        process_events()
        self.assertIsNotNone(self.ctrl.state.round)
        self.assertEqual(self.page.paper_model.rowCount(), 4)
        self.assertEqual(self.page.paper_combo.count(), 4)
        self.assertIn("覆盖", self.page.cover_label.text())

    def test_start_emits_index(self):
        self.page.generate_button.click()
        process_events()
        self.page.paper_combo.setCurrentIndex(1)
        received: list[int] = []
        self.page.start_requested.connect(received.append)
        self.page.start_button.click()
        process_events()
        self.assertEqual(received, [1])

    def test_manual_round_length(self):
        self.page.manual_radio.setChecked(True)
        process_events()
        self.assertTrue(self.page.round_spin.isEnabled())
        self.page.round_spin.setValue(7)
        process_events()
        self.assertFalse(self.ctrl.state.round_auto)
        self.assertEqual(self.ctrl.state.round_length, 7)

    def test_no_bank_disables_generate(self):
        ctrl = self.controller()
        page = ExamSetupPage(ctrl, LIGHT)
        self.addCleanup(page.deleteLater)
        page.refresh(ctrl.state)
        self.assertFalse(page.generate_button.isEnabled())
        self.assertFalse(page.start_button.isEnabled())


@unittest.skipUnless(HAVE_QT, SKIP_REASON)
class TestExamRunPage(QtTestCase):
    def setUp(self):
        super().setUp()
        self.ctrl = self.controller(questions=make_questions(12))
        self.ctrl.set_blueprint(3, 2, 1)
        self.ctrl.generate_round()
        self.ctrl.start_exam(self.ctrl.paper_at(0))
        self.page = ExamRunPage(self.ctrl, LIGHT)
        self.addCleanup(self.page.deleteLater)
        self.page.refresh(self.ctrl.state)

    def test_number_grid_built(self):
        self.assertEqual(self.page.number_grid.total, self.ctrl.exam_total())
        self.assertEqual(len(self.page.number_grid._buttons), self.ctrl.exam_total())

    def test_question_rendered(self):
        item = self.ctrl.exam_item(0)
        self.assertIn(item.stem, self.page.stem_label.text())
        self.assertIn("第 1 /", self.page.pos_label.text())
        self.assertEqual(len(self.page.option_rows), item.option_count)

    def test_answering_never_shows_correctness(self):
        item = self.ctrl.exam_item(0)
        self.page.press_option(item.labels[0])
        process_events()
        states = {row.state for row in self.page.option_rows}
        self.assertNotIn("correct", states)
        self.assertNotIn("wrong", states)
        combined = (self.page.title_label.text() + self.page.count_label.text()
                    + self.page.type_label.text() + self.page.stem_label.text())
        self.assertNotIn("正确", combined)
        self.assertNotIn("错误", combined)

    def test_single_choice_sets_answer(self):
        item = self.ctrl.exam_item(0)
        self.page.press_option(item.labels[1])
        process_events()
        self.assertEqual(self.ctrl.exam_selection(), {item.labels[1]})
        self.assertTrue(self.ctrl.exam_is_answered(0))

    def test_multiple_choice_toggles(self):
        index = next(i for i in range(self.ctrl.exam_total())
                     if self.ctrl.exam_item(i).qtype is QType.MULTIPLE)
        self.ctrl.exam_goto(index)
        self.page.refresh(self.ctrl.state)
        item = self.ctrl.exam_item(index)
        self.page.press_option(item.labels[0])
        self.page.press_option(item.labels[1])
        process_events()
        self.assertEqual(self.ctrl.exam_selection(), {item.labels[0], item.labels[1]})
        self.page.press_option(item.labels[1])
        process_events()
        self.assertEqual(self.ctrl.exam_selection(), {item.labels[0]})

    def test_number_grid_click_navigates(self):
        self.page.number_grid.go_requested.emit(3)
        process_events()
        self.assertEqual(self.ctrl.state.exam_index, 3)

    def test_clear_answer(self):
        item = self.ctrl.exam_item(0)
        self.page.press_option(item.labels[0])
        self.page.clear_button.click()
        process_events()
        self.assertFalse(self.ctrl.exam_is_answered(0))

    def test_submit_signal(self):
        received: list[int] = []
        self.page.submit_requested.connect(lambda: received.append(1))
        self.page.submit_button.click()
        process_events()
        self.assertEqual(received, [1])

    def test_readonly_after_submit(self):
        self.ctrl.submit_exam()
        self.page.refresh(self.ctrl.state)
        self.assertTrue(all(not row.isEnabled() for row in self.page.option_rows))
        self.assertFalse(self.page.submit_button.isEnabled())
        self.assertFalse(self.page.clear_button.isEnabled())

    def test_answered_numbers_highlighted(self):
        item = self.ctrl.exam_item(0)
        self.page.press_option(item.labels[0])
        self.page.refresh(self.ctrl.state)
        self.assertIn(0, self.page.number_grid.answered)
        self.assertEqual(self.page.number_grid.current, 0)


@unittest.skipUnless(HAVE_QT, SKIP_REASON)
class TestExamResultPage(QtTestCase):
    def setUp(self):
        super().setUp()
        self.ctrl = self.controller(questions=make_questions(12))
        self.ctrl.set_blueprint(3, 2, 1)
        self.ctrl.generate_round()
        self.ctrl.start_exam(self.ctrl.paper_at(0))
        exam = self.ctrl.state.exam
        for i in range(exam.total - 1):
            exam.set_answer(i, set(exam.item(i).shown_answer))
        self.result = self.ctrl.submit_exam()
        self.page = ExamResultPage(self.ctrl, LIGHT)
        self.addCleanup(self.page.deleteLater)
        self.page.refresh(self.ctrl.state)

    def test_header_and_pills(self):
        self.assertEqual(self.page.pill_correct.value.text(), str(self.result.correct))
        self.assertEqual(self.page.pill_unanswered.value.text(), "1")
        self.assertIn("正确率", self.page.score_header._title)

    def test_per_type_scores(self):
        for key in ("single", "multiple", "judge"):
            data = self.result.per_type.get(key)
            if data:
                self.assertIn(f"{data['correct']}/{data['total']}", self.page.per_labels[key].text())

    def test_detail_rows(self):
        self.assertEqual(self.page.detail_model.rowCount(), self.result.total)
        first = self.result.details[0]
        self.assertEqual(self.page.detail_model.detail_at(0)["number"], first["number"])

    def test_selecting_row_shows_analysis(self):
        self.page.show_detail(0)
        text = self.page.analysis_box.toPlainText()
        self.assertIn("正确答案", text)
        self.assertIn("题型", text)

    def test_back_signal(self):
        received: list[int] = []
        self.page.back_requested.connect(lambda: received.append(1))
        self.page.back_button.click()
        process_events()
        self.assertEqual(received, [1])

    def test_empty_result_state(self):
        ctrl = self.controller(questions=make_questions(3))
        page = ExamResultPage(ctrl, LIGHT)
        self.addCleanup(page.deleteLater)
        page.refresh(ctrl.state)
        self.assertEqual(page.detail_model.rowCount(), 0)
        self.assertIn("尚无成绩", page.score_header._title)


@unittest.skipUnless(HAVE_QT, SKIP_REASON)
class TestNumberGrid(QtTestCase):
    def test_build_and_columns(self):
        grid = NumberGrid(LIGHT)
        self.addCleanup(grid.deleteLater)
        grid.build(12, columns=5)
        self.assertEqual(len(grid._buttons), 12)
        grid.set_columns(3)
        self.assertEqual(grid._columns, 3)

    def test_update_state_highlight(self):
        grid = NumberGrid(LIGHT)
        self.addCleanup(grid.deleteLater)
        grid.build(5)
        grid.update_state(2, {0, 4})
        self.assertEqual(grid.current, 2)
        self.assertEqual(grid.answered, {0, 4})


if __name__ == "__main__":
    unittest.main(verbosity=2)
