# -*- coding: utf-8 -*-
"""Qt 界面 —— 无头自检（``paperdrill.ui.selftest``）与回退分支测试。"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

try:
    from tests.qt_support import (
        FIXTURE_BANK,
        HAVE_QT,
        SKIP_REASON,
        QtTestCase,
        process_events,
    )
except ModuleNotFoundError:
    from qt_support import (  # type: ignore[no-redef]
        FIXTURE_BANK,
        HAVE_QT,
        SKIP_REASON,
        QtTestCase,
        process_events,
    )


class TestGuiSelection(unittest.TestCase):
    """入口界面选择（不需要真正创建窗口）。"""

    def test_pick_gui_prefers_qt_when_available(self):
        from paperdrill import __main__ as entry

        with mock.patch("paperdrill.qt_app.available", return_value=True):
            self.assertEqual(entry.pick_gui(), "qt")

    def test_pick_gui_falls_back_to_tk(self):
        from paperdrill import __main__ as entry

        with mock.patch("paperdrill.qt_app.available", return_value=False), \
                mock.patch("paperdrill.qt_app.fallback_reason", return_value="ImportError: boom"):
            self.assertEqual(entry.pick_gui(), "tk")

    def test_run_gui_falls_back_when_qt_raises(self):
        from paperdrill import __main__ as entry

        called: list[object] = []

        def fake_tk(initial_bank=None):
            called.append(initial_bank)
            return 0

        with mock.patch("paperdrill.gui.run", fake_tk), \
                mock.patch("paperdrill.qt_app.run", side_effect=RuntimeError("qt 崩了")):
            code = entry.run_gui("题库.xlsx", gui="qt")
        self.assertEqual(code, 0)
        self.assertEqual(called, ["题库.xlsx"])

    def test_run_gui_uses_qt_when_selected(self):
        from paperdrill import __main__ as entry

        with mock.patch("paperdrill.qt_app.run", return_value=7) as qt_run:
            code = entry.run_gui(None, gui="qt")
        self.assertEqual(code, 7)
        qt_run.assert_called_once_with(None)

    def test_qt_app_reports_unavailable_gracefully(self):
        from paperdrill import qt_app

        with mock.patch.dict(sys.modules, {"PySide6.QtWidgets": None}):
            self.assertFalse(qt_app.available())
            self.assertTrue(qt_app.fallback_reason())

    def test_qt_app_reports_available(self):
        if not HAVE_QT:
            self.skipTest("未安装 PySide6")
        from paperdrill import qt_app

        self.assertTrue(qt_app.available())
        self.assertEqual(qt_app.fallback_reason(), "")


@unittest.skipUnless(HAVE_QT, SKIP_REASON)
class TestQtSelftest(QtTestCase):
    """端到端自检：真实控件上跑完整闭环。"""

    def _run(self):
        if not FIXTURE_BANK.exists():
            self.skipTest("缺少合成题库夹具")
        from paperdrill.ui.selftest import run_selftest

        result_file = self.tmp / "selftest.json"
        code = run_selftest(str(FIXTURE_BANK), str(result_file),
                            str(self.tmp / "selftest_progress"), 30, 12345)
        process_events()
        data = json.loads(result_file.read_text(encoding="utf-8"))
        return code, data

    def test_selftest_passes(self):
        code, data = self._run()
        self.assertEqual(code, 0, json.dumps(data, ensure_ascii=False)[:2000])
        self.assertTrue(data["ok"], data.get("error", ""))

    def test_selftest_stage_progression(self):
        code, data = self._run()
        self.assertEqual(code, 0)
        self.assertEqual(data["stage"], "done")
        self.assertEqual(data["engine"], "qt")
        self.assertTrue(data["qt"]["window_created"])

    def test_selftest_practice_and_exam_numbers(self):
        code, data = self._run()
        self.assertEqual(code, 0)
        self.assertEqual(data["bank"]["total"], 52)
        self.assertEqual(data["answered"], {"correct": 15, "wrong": 15})
        self.assertTrue(data["progress_restored"])
        self.assertEqual(data["stats_restored"], data["stats_after_exam"])
        self.assertEqual(data["paper"]["round_length"], 2)
        self.assertTrue(data["paper"]["coverage_ok"])
        self.assertEqual(data["paper"]["totals"], [40, 40])
        exam = data["exam"]
        planned = data["exam_planned"]
        self.assertEqual(exam["total"], 40)
        self.assertEqual(exam["unanswered"], 3)
        self.assertEqual(exam["correct"] + exam["wrong"] + exam["unanswered"], 40)
        self.assertGreaterEqual(exam["correct"], planned["expected"]["correct"])
        self.assertAlmostEqual(exam["full_score"], 50.0)
        self.assertGreaterEqual(exam["score"], 0.0)

    def test_selftest_qt_specific_checks(self):
        code, data = self._run()
        self.assertEqual(code, 0)
        self.assertTrue(data["exam_ui_hides_result"])
        self.assertTrue(data["exam_readonly"])
        self.assertTrue(data["exam_options_disabled"])
        self.assertTrue(data["keyboard"]["key_selected"])
        self.assertTrue(data["keyboard"]["enter_advances"])
        self.assertTrue(data["keyboard"]["correct_option_marked"])
        self.assertTrue(data["random_resume"]["resume_same_question"])
        self.assertTrue(data["bank_cut"]["restore_ok"])
        self.assertTrue(data["theme"]["dark_applied"])
        self.assertTrue(data["theme"]["light_applied"])
        self.assertTrue(data["geometry"]["ok"])
        from paperdrill import __version__

        self.assertEqual(data["version"], __version__)
        self.assertTrue(data["icon"]["file_exists"], data["icon"])
        self.assertTrue(data["icon"]["app_icon_ok"], data["icon"])
        self.assertTrue(data["icon"]["window_icon_ok"], data["icon"])

    def test_selftest_fails_gracefully_on_bad_bank(self):
        from paperdrill.ui.selftest import run_selftest

        result_file = self.tmp / "bad.json"
        code = run_selftest(str(self.tmp / "不存在.xlsx"), str(result_file),
                            str(self.tmp / "bad_progress"), 1, 1)
        data = json.loads(result_file.read_text(encoding="utf-8"))
        self.assertEqual(code, 1)
        self.assertFalse(data["ok"])
        self.assertIn("error", data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
