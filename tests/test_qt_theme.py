# -*- coding: utf-8 -*-
"""Qt 界面 —— 主题（设计令牌 / QSS / 对比度 / 自绘重绘）测试。"""
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
    from paperdrill.ui import theme as theme_module
    from paperdrill.ui.theme import (
        DARK,
        LIGHT,
        PALETTES,
        THEME_MODES,
        build_stylesheet,
        contrast_ratio,
        relative_luminance,
        resolve_mode,
        theme_field_names,
        theme_for,
    )


@unittest.skipUnless(HAVE_QT, SKIP_REASON)
class TestThemeTokens(QtTestCase):
    def test_both_palettes_complete(self):
        self.assertEqual(set(PALETTES), {"light", "dark"})
        light_fields = set(theme_field_names())
        for theme in (LIGHT, DARK):
            for field in light_fields:
                self.assertTrue(getattr(theme, field), f"{theme.name} 缺少令牌 {field}")

    def test_colors_are_valid(self):
        from PySide6.QtGui import QColor

        for theme in (LIGHT, DARK):
            for field in theme_field_names():
                value = getattr(theme, field)
                if isinstance(value, str) and value.startswith("#"):
                    self.assertTrue(QColor(value).isValid(), f"{theme.name}.{field}={value} 非法")

    def test_light_and_dark_inverted(self):
        self.assertGreater(relative_luminance(LIGHT.bg), relative_luminance(DARK.bg))
        self.assertGreater(relative_luminance(LIGHT.bg), relative_luminance(LIGHT.text))
        self.assertLess(relative_luminance(DARK.bg), relative_luminance(DARK.text))

    def test_theme_for_and_resolve(self):
        self.assertIs(theme_for("dark"), DARK)
        self.assertIs(theme_for("light"), LIGHT)
        # 非法值按"跟随系统"处理，结果取决于系统配色，只断言是合法主题
        self.assertIn(theme_for("nonsense").name, ("light", "dark"))
        self.assertIn(resolve_mode("system"), ("light", "dark"))
        self.assertEqual(resolve_mode("dark"), "dark")
        self.assertIn("system", THEME_MODES)

    def test_contrast_helpers(self):
        self.assertAlmostEqual(contrast_ratio("#000000", "#FFFFFF"), 21.0, places=1)
        self.assertAlmostEqual(contrast_ratio("#FFFFFF", "#FFFFFF"), 1.0, places=3)
        self.assertAlmostEqual(relative_luminance("#FFFFFF"), 1.0, places=3)
        self.assertAlmostEqual(relative_luminance("#000000"), 0.0, places=3)


@unittest.skipUnless(HAVE_QT, SKIP_REASON)
class TestAccessibility(QtTestCase):
    def test_body_text_contrast_meets_wcag_aa(self):
        for theme in (LIGHT, DARK):
            for fg, bg, label in (
                (theme.text, theme.bg, "正文/窗口"),
                (theme.text, theme.surface, "正文/卡片"),
                (theme.text_muted, theme.surface, "次要文本/卡片"),
                (theme.text_inverse, theme.primary, "主色上的反白文字"),
            ):
                ratio = contrast_ratio(fg, bg)
                self.assertGreaterEqual(ratio, 4.5,
                                        f"{theme.name} {label} 对比度 {ratio:.2f} < 4.5")
            # 主色用于强调（粗体/大号）与图形元素，按 WCAG 非文本要求 ≥ 3:1
            self.assertGreaterEqual(contrast_ratio(theme.primary, theme.surface), 3.0)

    def test_semantic_colors_distinguishable(self):
        for theme in (LIGHT, DARK):
            self.assertNotEqual(theme.success, theme.danger)
            self.assertGreaterEqual(contrast_ratio(theme.success, theme.surface), 3.0)
            self.assertGreaterEqual(contrast_ratio(theme.danger, theme.surface), 3.0)


@unittest.skipUnless(HAVE_QT, SKIP_REASON)
class TestStylesheet(QtTestCase):
    def test_stylesheet_contains_key_selectors(self):
        qss = build_stylesheet(LIGHT)
        for selector in ("#SideBar", "#Card", "QPushButton[kind=\"primary\"]",
                         "QTableView", "QScrollBar:vertical", "#Feedback[state=\"correct\"]"):
            self.assertIn(selector, qss, f"QSS 缺少 {selector}")

    def test_stylesheets_differ_between_themes(self):
        self.assertNotEqual(build_stylesheet(LIGHT), build_stylesheet(DARK))
        self.assertIn(LIGHT.bg, build_stylesheet(LIGHT))
        self.assertIn(DARK.bg, build_stylesheet(DARK))

    def test_apply_theme_sets_stylesheet_and_palette(self):
        app = self.app
        theme = theme_module.apply_theme(app, "dark")
        self.assertIs(theme, DARK)
        self.assertIn(DARK.bg, app.styleSheet())
        from PySide6.QtGui import QColor, QPalette

        window_color = app.palette().color(QPalette.Window)
        self.assertEqual(window_color.rgb(), QColor(DARK.bg).rgb())
        theme_module.apply_theme(app, "light")
        self.assertIn(LIGHT.bg, app.styleSheet())


@unittest.skipUnless(HAVE_QT, SKIP_REASON)
class TestWindowThemeSwitch(QtTestCase):
    def setUp(self):
        super().setUp()
        self._restore_light()
        self.ctrl = self.controller(questions=make_questions(6))
        self.win = self.window(self.ctrl, theme_mode="light")

    def _restore_light(self):
        """前面的用例可能把全局样式改成了深色，这里复位，避免互相影响。"""
        theme_module.apply_theme(self.app, "light")

    def test_switch_to_dark_and_back(self):
        self.win.apply_theme("dark")
        process_events()
        self.assertTrue(self.win.theme.dark)
        self.assertEqual(self.ctrl.settings.theme, "dark")
        self.win.apply_theme("light")
        process_events()
        self.assertFalse(self.win.theme.dark)

    def test_theme_persisted_and_restored(self):
        from paperdrill.config import AppSettings
        from paperdrill.ui.controller import PaperDrillController

        self.win.apply_theme("dark")
        saved = AppSettings.load(self.settings_file)
        self.assertEqual(saved.theme, "dark")
        ctrl2 = PaperDrillController(settings=AppSettings.load(self.settings_file),
                                     settings_path=self.settings_file,
                                     progress_root=self.progress_root)
        self.assertEqual(ctrl2.settings.theme, "dark")

    def test_pages_receive_theme(self):
        self.win.apply_theme("dark")
        for page in (self.win.practice_page, self.win.exam_setup_page,
                     self.win.exam_run_page, self.win.exam_result_page,
                     self.win.library_page):
            self.assertIs(page.theme, self.win.theme)

    def test_theme_requested_signal_switches(self):
        self.ctrl.theme_requested.emit("dark")
        process_events()
        self.assertTrue(self.win.theme.dark)

    def test_self_painted_widgets_receive_theme(self):
        self.win.apply_theme("dark")
        self.assertIs(self.win.practice_page.ring.theme, self.win.theme)
        self.assertIs(self.win.exam_setup_page.paper_model.theme, self.win.theme)
        self.assertIs(self.win.library_page.library_model.theme, self.win.theme)


if __name__ == "__main__":
    unittest.main(verbosity=2)
