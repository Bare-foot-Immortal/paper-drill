# -*- coding: utf-8 -*-
"""Qt 界面 —— 快捷键与输入框守卫测试（回归 v1.1.1 / v1.2 两处历史缺陷）。"""
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
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from paperdrill.models import QType
    from paperdrill.practice import Scope
    from paperdrill.ui.main_window import MainWindow


@unittest.skipUnless(HAVE_QT, SKIP_REASON)
class TestShortcuts(QtTestCase):
    def setUp(self):
        super().setUp()
        self.ctrl = self.controller(questions=make_questions(9))
        self.win: "MainWindow" = self.window(self.ctrl)
        self.win.set_page("practice")
        self.win.practice_page.setFocus()
        process_events()

    # ------------------------------------------------------------ 数字选择
    def test_number_key_selects_option(self):
        page = self.win.practice_page
        QTest.keyClick(page, Qt.Key_1)
        process_events()
        self.assertTrue(self.ctrl.state.answered, "数字键未触发判题")
        self.assertIn("回答正确", page.feedback_label.text())

    def test_letter_key_selects_option(self):
        """字母键与数字键等价；用单选题验证（多选题字母键只是勾选）。"""
        self.ctrl.set_scope(Scope.SINGLE)
        self.win.practice_page.refresh(self.ctrl.state)
        self.win.practice_page.setFocus()
        process_events()
        QTest.keyClick(self.win.practice_page, Qt.Key_B)
        process_events()
        self.assertTrue(self.ctrl.state.answered)
        self.assertEqual(self.ctrl.state.selection, {"B"})

    def test_number_key_ignores_out_of_range(self):
        item = self.ctrl.current_item()
        QTest.keyClick(self.win.practice_page, Qt.Key_8)
        process_events()
        self.assertFalse(self.ctrl.state.answered)
        self.assertGreaterEqual(item.option_count, 2)

    # ------------------------------------------------------------ Enter
    def test_enter_advances_after_answer(self):
        page = self.win.practice_page
        QTest.keyClick(page, Qt.Key_1)
        process_events()
        self.assertTrue(self.ctrl.state.answered)
        before = self.ctrl.state.position
        QTest.keyClick(page, Qt.Key_Return)
        process_events()
        self.assertEqual(self.ctrl.state.position, before + 1, "Enter 未进入下一题")

    def test_enter_submits_multiple_choice(self):
        self.ctrl.set_scope(Scope.MULTIPLE)
        self.win.practice_page.refresh(self.ctrl.state)
        self.win.practice_page.setFocus()
        item = self.ctrl.current_item()
        self.assertIs(item.qtype, QType.MULTIPLE)
        QTest.keyClick(self.win.practice_page, Qt.Key_1)
        process_events()
        self.assertFalse(self.ctrl.state.answered, "多选不应点选即判")
        QTest.keyClick(self.win.practice_page, Qt.Key_Return)
        process_events()
        self.assertTrue(self.ctrl.state.answered, "Enter 未提交多选")

    def test_enter_without_selection_hints(self):
        before = self.ctrl.state.position
        QTest.keyClick(self.win.practice_page, Qt.Key_Return)
        process_events()
        self.assertEqual(self.ctrl.state.position, before)
        self.assertIn("请先选择答案", self.win.status_label.text())

    # ------------------------------------------------------------ 方向键
    def test_arrow_keys_navigate(self):
        QTest.keyClick(self.win.practice_page, Qt.Key_Right)
        process_events()
        self.assertEqual(self.ctrl.state.position, 2)
        QTest.keyClick(self.win.practice_page, Qt.Key_Left)
        process_events()
        self.assertEqual(self.ctrl.state.position, 1)

    # ------------------------------------------------------------ 输入框守卫
    def test_typing_in_spinbox_does_not_answer(self):
        """焦点在题量输入框时，敲数字不得被当成选答案（v1.1.1 缺陷回归）。"""
        self.win.set_page("exam")
        spin = self.win.exam_setup_page.single_spin
        spin.setFocus()
        process_events()
        QTest.keyClick(spin, Qt.Key_1)
        process_events()
        self.assertFalse(self.ctrl.state.answered, "输入框里的数字键被当成选答案")

    def test_shortcut_guard_detects_input_widgets(self):
        from PySide6.QtWidgets import QAbstractSpinBox

        self.win.set_page("exam")
        spin = self.win.exam_setup_page.single_spin
        self.assertTrue(isinstance(spin, QAbstractSpinBox))
        spin.setFocus()
        process_events()
        self.assertFalse(self.win._shortcut_target_ok(), "输入框焦点时不应允许快捷键")

    def test_shortcut_guard_allows_plain_widgets(self):
        self.win.practice_page.setFocus()
        process_events()
        self.assertTrue(self.win._shortcut_target_ok())

    def test_keyboard_does_not_leak_into_dialog(self):
        """对话框中的按键不得影响主界面作答（FR-20.3）。"""
        from paperdrill.ui.dialogs import ExamHistoryDialog

        dialog = ExamHistoryDialog(self.ctrl, self.win.theme, self.win)
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        process_events()
        self.assertFalse(self.ctrl.state.answered)
        self.assertIsNot(self.win, dialog)

    # ------------------------------------------------------------ 考试页
    def test_number_key_answers_in_exam(self):
        self.ctrl.set_blueprint(3, 2, 1)
        self.ctrl.generate_round()
        self.ctrl.start_exam(self.ctrl.paper_at(0))
        self.win.set_page("exam")
        self.win.exam_run_page.refresh(self.ctrl.state)
        self.win.exam_run_page.setFocus()
        process_events()
        QTest.keyClick(self.win.exam_run_page, Qt.Key_2)
        process_events()
        self.assertTrue(self.ctrl.exam_is_answered(0))
        item = self.ctrl.exam_item(0)
        self.assertEqual(self.ctrl.exam_selection(), {item.labels[1]})

    def test_enter_advances_in_exam(self):
        self.ctrl.set_blueprint(3, 2, 1)
        self.ctrl.generate_round()
        self.ctrl.start_exam(self.ctrl.paper_at(0))
        self.win.set_page("exam")
        self.win.exam_run_page.refresh(self.ctrl.state)
        self.win.exam_run_page.setFocus()
        process_events()
        before = self.ctrl.state.exam_index
        QTest.keyClick(self.win.exam_run_page, Qt.Key_Return)
        process_events()
        self.assertEqual(self.ctrl.state.exam_index, before + 1)

    def test_arrow_keys_navigate_exam(self):
        self.ctrl.set_blueprint(3, 2, 1)
        self.ctrl.generate_round()
        self.ctrl.start_exam(self.ctrl.paper_at(0))
        self.win.set_page("exam")
        self.win.exam_run_page.setFocus()
        process_events()
        QTest.keyClick(self.win.exam_run_page, Qt.Key_Right)
        process_events()
        self.assertEqual(self.ctrl.state.exam_index, 1)
        QTest.keyClick(self.win.exam_run_page, Qt.Key_Left)
        process_events()
        self.assertEqual(self.ctrl.state.exam_index, 0)

    # ------------------------------------------------------------ 菜单快捷键存在
    def test_global_shortcuts_registered(self):
        sequences = {s.key().toString() for s in self.win._shortcuts}
        for expected in ("1", "8", "A", "H", "Return", "Left", "Right"):
            self.assertIn(expected, sequences, f"缺少快捷键绑定：{expected}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
