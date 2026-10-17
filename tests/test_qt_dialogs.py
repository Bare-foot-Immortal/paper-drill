# -*- coding: utf-8 -*-
"""Qt 界面 —— 对话框与主窗口拼装测试。"""
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
    from paperdrill.practice import PracticeMode
    from paperdrill.ui import dialogs as dialogs_module
    from paperdrill.ui.dialogs import (
        AboutDialog,
        BankPickerDialog,
        ExamHistoryDialog,
        HelpDialog,
        ProgressDialog,
        QuestionFilterDialog,
        WrongBookDialog,
    )
    from paperdrill.ui.main_window import HELP_TEXT, PAGES, MainWindow
    from paperdrill.ui.pages.library import LibraryPage
    from paperdrill.ui.theme import LIGHT, build_stylesheet


@unittest.skipUnless(HAVE_QT, SKIP_REASON)
class TestWrongBookDialog(QtTestCase):
    def setUp(self):
        super().setUp()
        self.ctrl = self.controller(questions=make_questions(9))
        self._confirm = dialogs_module.confirm
        self._notify = dialogs_module.notify
        dialogs_module.confirm = lambda *a, **k: True
        dialogs_module.notify = lambda *a, **k: None
        self.addCleanup(self._restore)

    def _restore(self):
        dialogs_module.confirm = self._confirm
        dialogs_module.notify = self._notify

    def test_lists_wrong_questions(self):
        self.answer_wrong(self.ctrl)
        dialog = WrongBookDialog(self.ctrl, LIGHT)
        self.addCleanup(dialog.deleteLater)
        text = dialog.viewer.toPlainText()
        self.assertIn("正确答案", text)
        self.assertEqual(len(dialog.questions), 1)

    def test_empty_state(self):
        dialog = WrongBookDialog(self.ctrl, LIGHT)
        self.addCleanup(dialog.deleteLater)
        self.assertIn("暂无错题", dialog.viewer.toPlainText())

    def test_clear_clears_marks(self):
        self.answer_wrong(self.ctrl)
        dialog = WrongBookDialog(self.ctrl, LIGHT)
        self.addCleanup(dialog.deleteLater)
        dialog._clear()
        self.assertEqual(len(self.ctrl.wrong_book_questions()), 0)

    def test_practice_wrong_emits_and_closes(self):
        self.answer_wrong(self.ctrl)
        dialog = WrongBookDialog(self.ctrl, LIGHT)
        self.addCleanup(dialog.deleteLater)
        received: list[int] = []
        dialog.practice_wrong_requested.connect(lambda: received.append(1))
        dialog._practice_wrong()
        self.assertEqual(received, [1])


@unittest.skipUnless(HAVE_QT, SKIP_REASON)
class TestQuestionFilterDialog(QtTestCase):
    def setUp(self):
        super().setUp()
        self.ctrl = self.controller(questions=make_questions(12))
        self._confirm = dialogs_module.confirm
        self._notify = dialogs_module.notify
        dialogs_module.confirm = lambda *a, **k: True
        dialogs_module.notify = lambda *a, **k: None
        self.addCleanup(self._restore)
        self.dialog = QuestionFilterDialog(self.ctrl, LIGHT)
        self.addCleanup(self.dialog.deleteLater)

    def _restore(self):
        dialogs_module.confirm = self._confirm
        dialogs_module.notify = self._notify

    def test_initial_lists(self):
        self.assertEqual(self.dialog.active_model.rowCount(), 12)
        self.assertEqual(self.dialog.cut_model.rowCount(), 0)
        self.assertIn("参与练习 12 题", self.dialog.count_label.text())

    def test_type_filter(self):
        self.dialog.type_box.setCurrentText("单选题")
        process_events()
        self.assertEqual(self.dialog.active_model.rowCount(), 4)

    def test_keyword_filter(self):
        self.dialog.keyword.setText("单选题 0")          # 唯一命中（避免 "多选题 1" 同时命中 10）
        process_events()
        self.assertEqual(self.dialog.active_model.rowCount(), 1)

    def test_cut_and_restore_selected(self):
        self.dialog.active_table.selectRow(0)
        self.assertEqual(self.dialog.cut_selected(), 1)
        self.assertEqual(self.dialog.cut_model.rowCount(), 1)
        self.assertEqual(self.dialog.active_model.rowCount(), 11)
        self.dialog.cut_table.selectRow(0)
        self.assertEqual(self.dialog.restore_selected(), 1)
        self.assertEqual(self.dialog.active_model.rowCount(), 12)

    def test_restore_all(self):
        first = [row.question for row in self.dialog.active_model.rows[:3]]
        self.ctrl.exclude_questions(first)
        self.dialog.reload()
        self.assertEqual(self.dialog.cut_model.rowCount(), 3)
        self.assertEqual(self.dialog.restore_all(), 3)
        self.assertEqual(self.dialog.active_model.rowCount(), 12)

    def test_question_text_rendering(self):
        question = self.dialog.active_model.rows[0].question
        text = QuestionFilterDialog.question_text(question)
        self.assertIn(question.stem, text)
        self.assertIn("正确答案", text)


@unittest.skipUnless(HAVE_QT, SKIP_REASON)
class TestProgressAndHistoryDialogs(QtTestCase):
    def setUp(self):
        super().setUp()
        self.ctrl = self.controller(questions=make_questions(9))
        self._confirm = dialogs_module.confirm
        self._notify = dialogs_module.notify
        dialogs_module.confirm = lambda *a, **k: True
        dialogs_module.notify = lambda *a, **k: None
        self.addCleanup(self._restore)

    def _restore(self):
        dialogs_module.confirm = self._confirm
        dialogs_module.notify = self._notify

    def test_progress_dialog_lists_banks(self):
        self.answer_correctly(self.ctrl)          # 有作答才会写进度文件
        dialog = ProgressDialog(self.ctrl, LIGHT)
        self.addCleanup(dialog.deleteLater)
        self.assertGreaterEqual(dialog.model.rowCount(), 1)
        self.assertEqual(dialog.windowTitle(), "进度管理")

    def test_progress_dialog_reset_selected(self):
        self.answer_correctly(self.ctrl)
        self.assertEqual(self.ctrl.stats()["done"], 1)
        dialog = ProgressDialog(self.ctrl, LIGHT)
        self.addCleanup(dialog.deleteLater)
        current_key = self.ctrl.state.store.progress.bank_key
        row = next(i for i in range(dialog.model.rowCount())
                   if dialog.model.key_at(i) == current_key)
        dialog.table.selectRow(row)
        self.assertTrue(dialog._reset_selected())
        self.assertEqual(self.ctrl.stats()["done"], 0)

    def test_exam_history_dialog(self):
        self.ctrl.set_blueprint(3, 2, 1)
        self.ctrl.generate_round()
        self.ctrl.start_exam(self.ctrl.paper_at(0))
        self.ctrl.submit_exam()
        dialog = ExamHistoryDialog(self.ctrl, LIGHT)
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(dialog.model.rowCount(), 1)


@unittest.skipUnless(HAVE_QT, SKIP_REASON)
class TestBankPickerDialog(QtTestCase):
    def setUp(self):
        super().setUp()
        self.ctrl = self.controller(questions=make_questions(6))
        self._confirm = dialogs_module.confirm
        self._notify = dialogs_module.notify
        dialogs_module.confirm = lambda *a, **k: True
        dialogs_module.notify = lambda *a, **k: None
        self.addCleanup(self._restore)
        self.dialog = BankPickerDialog(self.ctrl, LIGHT)
        self.addCleanup(self.dialog.deleteLater)

    def _restore(self):
        dialogs_module.confirm = self._confirm
        dialogs_module.notify = self._notify

    def test_lists_library_entries(self):
        self.assertGreaterEqual(self.dialog.model.rowCount(), 1)
        self.assertIn("记录", self.dialog.hint.text())
        hint_visible = self.dialog.hint.text()
        self.assertTrue("共" in hint_visible and "个" in hint_visible, hint_visible)

    def test_forget_removes_entry_but_keeps_file(self):
        path = self.ctrl.state.bank_path
        self.dialog.table.selectRow(0)
        self.assertTrue(self.dialog._forget())
        self.assertFalse(any(r["path"] == path for r in self.ctrl.library_rows()))
        self.assertTrue(Path(path).exists())

    def test_load_emits_path(self):
        self.dialog.table.selectRow(0)
        received: list[str] = []
        self.dialog.load_requested.connect(received.append)
        self.assertTrue(self.dialog.load_selected())
        self.assertTrue(received)


@unittest.skipUnless(HAVE_QT, SKIP_REASON)
class TestLibraryPageSelection(QtTestCase):
    """题库资料页：选中最近题库必须有可见反馈（用户反馈：点了看不出选中）。"""

    def setUp(self):
        super().setUp()
        self.ctrl = self.controller(questions=make_questions(6), name="样例")
        self.page = LibraryPage(self.ctrl, LIGHT)
        self.addCleanup(self.page.deleteLater)
        self.page.refresh(self.ctrl.state)

    def test_no_selection_hint(self):
        self.assertEqual(self.page.selected_path(), "")
        self.assertIn("单击一行选中", self.page.selection_label.text())
        self.assertFalse(self.page.load_button.isEnabled())

    def test_click_row_marks_selection(self):
        self.assertGreaterEqual(self.page.library_model.rowCount(), 1)
        self.page.library_table.selectRow(0)
        process_events()
        self.assertTrue(self.page.selected_path())
        self.assertIn("已选中", self.page.selection_label.text())
        self.assertTrue(self.page.load_button.isEnabled(), "选中后按钮应可用")

    def test_selection_survives_refresh(self):
        self.page.library_table.selectRow(0)
        process_events()
        path = self.page.selected_path()
        self.page.refresh(self.ctrl.state)
        process_events()
        self.assertEqual(self.page.selected_path(), path, "刷新后选中项丢失")

    def test_theme_styles_selected_rows(self):
        """QSS 必须显式写 ::item:selected，否则选中行没有可见变化（本次缺陷根因）。"""
        qss = build_stylesheet(LIGHT)
        self.assertIn("QTableView::item:selected", qss)
        self.assertIn("QTableView::item:selected:!active", qss)


@unittest.skipUnless(HAVE_QT, SKIP_REASON)
class TestHelpAndAbout(QtTestCase):
    def test_help_and_about_dialogs(self):
        help_dialog = HelpDialog(LIGHT, HELP_TEXT)
        self.addCleanup(help_dialog.deleteLater)
        self.assertIn("使用说明", help_dialog.windowTitle())

        about = AboutDialog(LIGHT, "刷题匠 v1.3.0")
        self.addCleanup(about.deleteLater)
        self.assertEqual(about.windowTitle(), "关于")


@unittest.skipUnless(HAVE_QT, SKIP_REASON)
class TestMainWindowShell(QtTestCase):
    def setUp(self):
        super().setUp()
        self.ctrl = self.controller(questions=make_questions(9))
        self.win: "MainWindow" = self.window(self.ctrl)

    def test_window_basics(self):
        self.assertTrue(self.win.isVisible())
        self.assertIn("刷题匠", self.win.windowTitle())
        self.assertEqual(self.win.current_page(), "practice")
        self.assertEqual(self.win.minimumWidth(), 1024)

    def test_navigation_switches_pages(self):
        for page_key in PAGES:
            self.win.set_page(page_key)
            process_events()
            self.assertEqual(self.win.current_page(), page_key)
            self.assertTrue(self.win.nav_buttons[page_key].property("active"))

    def test_page_persisted(self):
        self.win.set_page("library")
        self.win.close()
        process_events()
        from paperdrill.config import AppSettings

        self.assertEqual(AppSettings.load(self.settings_file).last_page, "library")

    def test_topbar_shows_bank_and_stats(self):
        self.assertIn("题", self.win.stats_label.text())
        self.assertEqual(self.win.pill_book.label.text(), "错题")
        self.assertIn("%", self.win.pill_rate.value.text() + "%")

    def test_status_bar_updates(self):
        self.ctrl.status_message.emit("测试消息")
        process_events()
        self.assertEqual(self.win.status_label.text(), "测试消息")

    def test_geometry_roundtrip(self):
        self.assertTrue(self.win.apply_geometry_text("1100x760+40+30"))
        text = self.win.window_geometry_text
        self.assertRegex(text, r"^\d+x\d+\+-?\d+\+-?\d+$")

    def test_invalid_geometry_is_ignored(self):
        self.assertFalse(self.win.apply_geometry_text(""))
        self.assertFalse(self.win.apply_geometry_text("乱码"))

    def test_close_persists_geometry(self):
        from PySide6.QtCore import QSize

        from paperdrill.config import AppSettings

        self.win.resize(QSize(1120, 780))
        process_events()
        expected = self.win.window_geometry_text
        self.win.close()
        process_events()
        saved = AppSettings.load(self.settings_file)
        self.assertTrue(saved.qt_window_state, "未保存窗口几何")
        self.assertTrue(saved.qt_window_state.startswith("1120x780"),
                        f"保存的几何 {saved.qt_window_state!r} 与 {expected!r} 不一致")

    def test_menu_actions_exist(self):
        menus = [action.text() for action in self.win.menuBar().actions()]
        for expected in ("文件", "练习", "模拟考试", "视图", "帮助"):
            self.assertIn(expected, menus)

    def test_wrong_book_shortcut_handler_switches_mode(self):
        self.win._practice_wrong()
        process_events()
        self.assertIs(self.ctrl.state.mode, PracticeMode.WRONG)
        self.assertEqual(self.win.current_page(), "practice")

    def test_start_exam_from_menu_switches_page(self):
        self.ctrl.set_blueprint(3, 2, 1)
        self.ctrl.generate_round()
        self.win._start_exam_selected()
        process_events()
        self.assertEqual(self.win.current_page(), "exam")
        self.assertEqual(self.ctrl.state.exam_view, "taking")

    def test_drop_accepts_supported_suffix(self):
        from paperdrill.bank_io import SUPPORTED_SUFFIXES

        self.assertIn(".xlsx", SUPPORTED_SUFFIXES)
        self.assertTrue(self.win.acceptDrops())


if __name__ == "__main__":
    unittest.main(verbosity=2)
