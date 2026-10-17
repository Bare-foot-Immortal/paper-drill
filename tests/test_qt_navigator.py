# -*- coding: utf-8 -*-
"""Qt 界面 —— 题目导览（QuestionNavigator）组件与练习页整合测试。

覆盖：
* 5 列方格构建、题号文案、NoFocus；
* 点击发出队列下标 ``go_requested``；
* 未答 / 答对 / 答错 / 当前题的样式（颜色取自主题令牌，不硬编码色值）；
* 题量不变时不重建按钮（300+ 题流畅），题量变化时重建；
* 练习页把会话队列映射到导览，答对/答错后格子状态变化；
* MainWindow 接线后点击题号真的跳题。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

try:
    from tests.qt_support import (
        HAVE_QT,
        SKIP_REASON,
        QtTestCase,
        make_questions,
        process_events,
        qapp,
    )
except ModuleNotFoundError:
    from qt_support import (  # type: ignore[no-redef]
        HAVE_QT,
        SKIP_REASON,
        QtTestCase,
        make_questions,
        process_events,
        qapp,
    )

if HAVE_QT:
    from PySide6.QtCore import Qt

    from paperdrill.ui.pages.practice import PracticePage
    from paperdrill.ui.theme import DARK, LIGHT
    from paperdrill.ui.widgets import QuestionNavigator


@unittest.skipUnless(HAVE_QT, SKIP_REASON)
class TestQuestionNavigatorWidget(unittest.TestCase):
    """纯组件测试：不依赖控制器。"""

    def setUp(self):
        qapp()
        self.nav = QuestionNavigator(LIGHT)
        self.addCleanup(self.nav.deleteLater)

    def _row_column(self, index: int) -> tuple[int, int]:
        item = self.nav._grid.indexOf(self.nav.buttons[index])
        row, column, _row_span, _col_span = self.nav._grid.getItemPosition(item)
        return row, column

    # ------------------------------------------------------------ 构建
    def test_builds_five_column_grid(self):
        self.nav.set_questions(40, 0, ["todo"] * 40)
        self.assertEqual(self.nav.total, 40)
        self.assertEqual(len(self.nav.buttons), 40)
        self.assertEqual([btn.text() for btn in self.nav.buttons],
                         [str(i + 1) for i in range(40)])
        # 5 列：第 6 个格子换到第二行第 1 列
        self.assertEqual(self._row_column(0), (0, 0))
        self.assertEqual(self._row_column(4), (0, 4))
        self.assertEqual(self._row_column(5), (1, 0))

    def test_cells_do_not_steal_focus(self):
        """点过题号后 Enter / 方向键必须继续被主窗口快捷键处理。"""
        self.nav.set_questions(9)
        for btn in self.nav.buttons:
            self.assertEqual(btn.focusPolicy(), Qt.NoFocus)

    def test_fixed_height_shows_about_five_rows(self):
        # 5 行 × 34px + 4 个间距 ≈ 190~200px
        height = self.nav.minimumHeight()
        self.assertTrue(190 <= height <= 220, f"导览高度 {height} 不在 5 行区间")
        self.assertEqual(self.nav.minimumHeight(), self.nav.maximumHeight())

    # ------------------------------------------------------------ 交互
    def test_click_emits_zero_based_index(self):
        self.nav.set_questions(9, 0, ["todo"] * 9)
        received: list[int] = []
        self.nav.go_requested.connect(received.append)
        self.nav.buttons[4].click()
        process_events()
        self.assertEqual(received, [4], "点击第 5 格应发出队列下标 4")

    # ------------------------------------------------------------ 样式
    def test_status_colors_come_from_theme(self):
        self.nav.set_questions(3, 0, ["correct", "wrong", "todo"])
        styles = [btn.styleSheet() for btn in self.nav.buttons]
        self.assertIn(LIGHT.success_weak, styles[0])
        self.assertIn(LIGHT.success, styles[0])
        self.assertIn(LIGHT.danger_weak, styles[1])
        self.assertIn(LIGHT.danger, styles[1])
        self.assertIn(LIGHT.surface, styles[2])
        self.assertIn(LIGHT.text_muted, styles[2])

    def test_current_cell_has_primary_border_and_bold(self):
        self.nav.set_questions(3, 1, ["todo", "todo", "todo"])
        current = self.nav.buttons[1].styleSheet()
        self.assertIn(f"2px solid {LIGHT.primary}", current)
        self.assertIn("font-weight:700", current)
        # 未答的当前格用浅灰底
        self.assertIn(LIGHT.surface_alt, current)
        # 非当前格只有 1px 边框
        self.assertIn(f"1px solid {LIGHT.border}", self.nav.buttons[0].styleSheet())

    def test_answered_current_keeps_status_color(self):
        self.nav.set_questions(2, 1, ["todo", "correct"])
        current = self.nav.buttons[1].styleSheet()
        self.assertIn(LIGHT.success_weak, current)
        self.assertIn(f"2px solid {LIGHT.primary}", current)

    def test_theme_refresh_recolors_all_cells(self):
        self.nav.set_questions(3, 1, ["correct", "wrong", "todo"])
        self.nav.refresh_theme(DARK)
        self.assertIs(self.nav.theme, DARK)
        self.assertIn(DARK.success, self.nav.buttons[0].styleSheet())
        self.assertIn(DARK.danger, self.nav.buttons[1].styleSheet())
        self.assertIn(DARK.surface, self.nav.buttons[2].styleSheet())
        # 当前格（答错）保持 danger 底色 + 主色高亮边框
        self.assertIn(f"2px solid {DARK.primary}", self.nav.buttons[1].styleSheet())
        # 再切回浅色也不崩
        self.nav.refresh_theme(LIGHT)
        self.assertIn(LIGHT.success, self.nav.buttons[0].styleSheet())

    # ------------------------------------------------------------ 重建策略
    def test_same_total_keeps_button_objects(self):
        self.nav.set_questions(9, 0, ["todo"] * 9)
        first = [id(btn) for btn in self.nav.buttons]
        self.nav.set_questions(9, 3, ["todo"] * 9)
        self.assertEqual([id(btn) for btn in self.nav.buttons], first,
                         "题量不变时不应重建按钮")
        self.assertEqual(self.nav.current, 3)
        self.assertIn(f"2px solid {LIGHT.primary}", self.nav.buttons[3].styleSheet())
        self.assertNotIn(f"2px solid {LIGHT.primary}", self.nav.buttons[0].styleSheet())

    def test_shrink_and_clear(self):
        self.nav.set_questions(9)
        self.nav.set_questions(3, 1, ["todo"] * 3)
        self.assertEqual(len(self.nav.buttons), 3)
        self.assertEqual(self.nav.current, 1)
        self.nav.set_questions(0)
        self.assertEqual(self.nav.total, 0)
        self.assertEqual(self.nav.buttons, [])
        self.assertEqual(self.nav.statuses, [])

    def test_300_questions_offscreen(self):
        self.nav.set_questions(300, 0, ["todo"] * 300)
        self.assertEqual(self.nav.total, 300)
        self.assertEqual(len(self.nav.buttons), 300)
        first = [id(btn) for btn in self.nav.buttons]
        # 只更新当前位置：不重建、不抛异常
        self.nav.set_questions(300, 299, ["todo"] * 300)
        self.assertEqual([id(btn) for btn in self.nav.buttons], first)
        self.assertEqual(self.nav.current, 299)
        self.nav.set_questions(300, 299, ["correct"] * 299 + ["wrong"])
        self.assertIn(LIGHT.danger, self.nav.buttons[299].styleSheet())

    def test_statuses_are_normalized(self):
        self.nav.set_questions(3, 0, ["correct", "unknown", "wrong"])
        self.assertEqual(self.nav.statuses, ["correct", "todo", "wrong"])
        # 状态列表比题数短：其余补 todo
        self.nav.set_questions(4, 0, ["correct"])
        self.assertEqual(self.nav.statuses, ["correct", "todo", "todo", "todo"])


@unittest.skipUnless(HAVE_QT, SKIP_REASON)
class TestPracticeNavigatorIntegration(QtTestCase):
    def setUp(self):
        super().setUp()
        self.ctrl = self.controller(questions=make_questions(12))
        self.page = PracticePage(self.ctrl, LIGHT)
        self.addCleanup(self.page.deleteLater)
        self.page.refresh(self.ctrl.state)

    def test_navigator_matches_session(self):
        nav = self.page.navigator
        self.assertEqual(nav.total, self.ctrl.state.total)
        self.assertEqual(nav.current, self.ctrl.state.session.cursor)
        self.assertEqual(len(nav.buttons), self.ctrl.state.total)
        self.assertEqual(self.page.nav_hint_label.text(), f"本轮 {self.ctrl.state.total} 题")

    def test_correct_and_wrong_cells_change_status(self):
        nav = self.page.navigator
        self.assertTrue(self.answer_correctly(self.ctrl))
        self.page.refresh(self.ctrl.state)
        self.assertEqual(nav.statuses[0], "correct")
        self.assertIn(LIGHT.success, nav.buttons[0].styleSheet())

        self.ctrl.advance()
        self.assertTrue(self.answer_wrong(self.ctrl))
        self.page.refresh(self.ctrl.state)
        self.assertEqual(nav.statuses[1], "wrong")
        self.assertEqual(nav.statuses[2], "todo", "未作答的题应保持 todo")

    def test_current_cell_tracks_cursor(self):
        self.page.navigator.buttons[4].click()
        process_events()
        # 页面自身不导航，只转发信号；这里直接驱动控制器验证映射
        self.ctrl.goto(4)
        self.page.refresh(self.ctrl.state)
        self.assertEqual(self.page.navigator.current, 4)
        self.ctrl.advance()
        self.page.refresh(self.ctrl.state)
        self.assertEqual(self.page.navigator.current, 5)

    def test_navigator_click_emits_goto_requested(self):
        received: list[int] = []
        self.page.goto_requested.connect(received.append)
        self.page.navigator.buttons[6].click()
        process_events()
        self.assertEqual(received, [6])

    def test_window_wiring_jumps_to_clicked_question(self):
        win = self.window(self.ctrl)
        win.set_page("practice")
        process_events()
        page = win.practice_page
        page.navigator.buttons[6].click()
        process_events()
        self.assertEqual(self.ctrl.state.session.cursor, 6)
        self.assertEqual(self.ctrl.state.position, 7)
        self.assertEqual(page.pos_label.text(), "第 7 / 12 题")

    def test_theme_switch_refreshes_navigator(self):
        self.page.apply_theme(DARK)
        process_events()
        self.assertIs(self.page.navigator.theme, DARK)
        self.assertIn(DARK.surface_alt, self.page.shortcut_bar.styleSheet())
        self.page.apply_theme(LIGHT)
        process_events()
        self.assertIs(self.page.navigator.theme, LIGHT)


@unittest.skipUnless(HAVE_QT, SKIP_REASON)
class TestPracticeWithManyQuestions(QtTestCase):
    def test_300_question_page_navigates_without_error(self):
        ctrl = self.controller(questions=make_questions(300))
        page = PracticePage(ctrl, LIGHT)
        self.addCleanup(page.deleteLater)
        page.refresh(ctrl.state)
        nav = page.navigator
        self.assertEqual(nav.total, 300)
        self.assertEqual(len(nav.buttons), 300)
        self.assertTrue(ctrl.goto(299))
        page.refresh(ctrl.state)
        self.assertEqual(nav.current, 299)
        self.assertEqual(ctrl.state.position, 300)
        # 主题切换后仍可渲染
        page.apply_theme(DARK)
        process_events()
        self.assertEqual(len(nav.buttons), 300)


if __name__ == "__main__":
    unittest.main(verbosity=2)
