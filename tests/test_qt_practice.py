# -*- coding: utf-8 -*-
"""Qt 界面 —— 练习页渲染与交互测试。"""
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
    )
except ModuleNotFoundError:
    from qt_support import (  # type: ignore[no-redef]
        HAVE_QT,
        SKIP_REASON,
        QtTestCase,
        make_questions,
        process_events,
    )

if HAVE_QT:
    from PySide6.QtWidgets import QApplication

    from paperdrill.models import QType
    from paperdrill.practice import PracticeMode, Scope
    from paperdrill.ui.pages.practice import PracticePage
    from paperdrill.ui.theme import DARK, LIGHT
    from paperdrill.ui.widgets import OptionRow


@unittest.skipUnless(HAVE_QT, SKIP_REASON)
class TestPracticePageRendering(QtTestCase):
    def setUp(self):
        super().setUp()
        self.ctrl = self.controller(questions=make_questions(9))
        self.page = PracticePage(self.ctrl, LIGHT)
        self.addCleanup(self.page.deleteLater)
        self.page.refresh(self.ctrl.state)

    def test_option_rows_match_options(self):
        item = self.ctrl.current_item()
        self.assertEqual(len(self.page.option_rows), item.option_count)
        self.assertEqual([row.letter for row in self.page.option_rows], item.labels)
        self.assertEqual([row.text for row in self.page.option_rows], item.texts)

    def test_stem_and_counter_rendered(self):
        item = self.ctrl.current_item()
        self.assertIn(item.stem, self.page.stem_label.text())
        self.assertIn("第 1 / 9 题", self.page.pos_label.text())
        self.assertEqual(self.page.type_badge.text(), QType.SINGLE.value)

    def _correct_row(self):
        """取"正确选项"对应的那一行（按显示答案推导，不硬编码字母）。"""
        item = self.ctrl.current_item()
        letter = sorted(item.shown_answer)[0]
        return next(row for row in self.page.option_rows if row.letter == letter)

    def _wrong_row(self):
        item = self.ctrl.current_item()
        letter = next(lab for lab in item.labels if lab not in item.shown_answer)
        return next(row for row in self.page.option_rows if row.letter == letter)

    def test_clicking_option_answers_immediately(self):
        row = self._correct_row()
        row.pressed.emit(row.letter)                 # 等价于点一下
        process_events()
        self.assertTrue(self.ctrl.state.answered)
        self.assertIn("回答正确", self.page.feedback_label.text())
        self.assertEqual(self.page.feedback_label.property("state"), "correct")

    def test_clicking_wrong_option_marks_it(self):
        row = self._wrong_row()
        row.pressed.emit(row.letter)
        process_events()
        self.assertIn("回答错误", self.page.feedback_label.text())
        self.assertEqual(self.page.feedback_label.property("state"), "wrong")

    def test_correct_and_wrong_options_are_marked(self):
        item = self.ctrl.current_item()
        wrong_letter = next(lab for lab in item.labels if lab not in item.shown_answer)
        self.ctrl.toggle_option(wrong_letter)
        self.page.refresh(self.ctrl.state)
        states = {row.letter: row.state for row in self.page.option_rows}
        for letter in item.shown_answer:
            self.assertEqual(states[letter], "correct", "正确选项未标绿")
        self.assertEqual(states[wrong_letter], "wrong", "错选项未标红")
        others = [lab for lab in item.labels if lab not in item.shown_answer and lab != wrong_letter]
        for letter in others:
            self.assertEqual(states[letter], "dim", "无关选项未弱化")

    def test_options_disabled_after_answer(self):
        self.ctrl.toggle_option(sorted(self.ctrl.current_item().shown_answer)[0])
        self.page.refresh(self.ctrl.state)
        self.assertTrue(all(not row.isEnabled() for row in self.page.option_rows))

    def test_multiple_choice_shows_selection_state(self):
        self.ctrl.set_scope(Scope.MULTIPLE)
        self.page.refresh(self.ctrl.state)
        item = self.ctrl.current_item()
        self.assertIs(item.qtype, QType.MULTIPLE)
        self.page.press_option(item.labels[0])
        process_events()
        self.assertEqual(self.page.option_rows[0].state, "selected")
        self.assertTrue(self.page.submit_button.isEnabled(), "多选提交按钮应可用")
        self.assertFalse(self.ctrl.state.answered)

    def test_single_choice_submit_button_disabled(self):
        self.assertFalse(self.page.submit_button.isEnabled(), "单选无需提交按钮")
        self.assertTrue(self.page.reveal_button.isEnabled())

    def test_reveal_shows_answer_and_disables_buttons(self):
        self.page.press_reveal()
        process_events()
        self.assertIn("正确答案", self.page.feedback_label.text())
        self.assertEqual(self.page.feedback_label.property("state"), "reveal")
        self.assertFalse(self.page.reveal_button.isEnabled())
        self.assertTrue(all(not row.isEnabled() for row in self.page.option_rows))

    def test_analysis_shown_when_enabled(self):
        self.ctrl.toggle_option(self.ctrl.current_item().labels[0])
        self.page.refresh(self.ctrl.state)
        self.assertIn("解析", self.page.analysis_label.text())
        self.ctrl.set_show_analysis(False)
        self.page.refresh(self.ctrl.state)
        self.assertEqual(self.page.analysis_label.text(), "")

    def test_navigation_buttons_and_handlers(self):
        self.assertFalse(self.page.prev_button.isEnabled())
        self.assertTrue(self.page.next_button.isEnabled())
        received: list[int] = []
        self.page.next_requested.connect(lambda: received.append(1))
        self.page.next_button.click()
        process_events()
        self.assertEqual(received, [1], "「下一题」按钮应发出 next_requested")
        # 翻题动作由持有页面的窗口执行（MainWindow），这里直接驱动控制器验证效果
        self.ctrl.advance()
        process_events()
        self.assertEqual(self.ctrl.state.position, 2)
        self.assertTrue(self.page.prev_button.isEnabled())

    def test_scope_control_reflects_controller(self):
        self.ctrl.set_scope(Scope.JUDGE)
        self.page.refresh(self.ctrl.state)
        self.assertEqual(self.page.scope_control.current(), Scope.JUDGE.value)

    def test_mode_control_reflects_controller(self):
        self.ctrl.set_mode(PracticeMode.RANDOM)
        self.page.refresh(self.ctrl.state)
        self.assertEqual(self.page.mode_control.current(), PracticeMode.RANDOM.value)

    def test_toggles_sync_back(self):
        self.page.auto_next_box.setChecked(True)
        process_events()
        self.assertTrue(self.ctrl.state.auto_next)
        self.assertFalse(self.ctrl.state.shuffle_single)
        self.page.shuffle_single_box.setChecked(True)
        process_events()
        self.assertTrue(self.ctrl.state.shuffle_single)

    def test_empty_state_when_no_bank(self):
        ctrl = self.controller()
        page = PracticePage(ctrl, self.page.theme)
        self.addCleanup(page.deleteLater)
        page.refresh(ctrl.state)
        self.assertIn("尚未导入题库", page.empty_state.title.text())
        self.assertFalse(page.submit_button.isEnabled())
        self.assertEqual(page.option_rows, [])

    def test_empty_wrong_mode_message(self):
        self.ctrl.set_mode(PracticeMode.WRONG)
        self.page.refresh(self.ctrl.state)
        self.assertIn("没有答错", self.page.empty_state.hint.text())
        self.assertEqual(page_feedback_kind(self.page), "empty")

    def test_revisit_keeps_options_answerable(self):
        item = self.ctrl.current_item()
        self.ctrl.toggle_option(item.labels[0])
        self.ctrl.advance()
        self.ctrl.retreat()
        self.page.refresh(self.ctrl.state)
        self.assertTrue(all(row.isEnabled() for row in self.page.option_rows),
                        "回看已作答题目时选项应可再次作答")
        self.assertIn("上次", self.page.feedback_label.text())
        self.assertEqual(self.page.analysis_label.text(), "", "回看时不得剧透解析")

    def test_side_stats_update(self):
        self.ctrl.toggle_option(sorted(self.ctrl.current_item().shown_answer)[0])
        self.page.refresh(self.ctrl.state)
        self.assertEqual(self.page.pill_right.value.text(), "1")
        self.assertIn("题", self.page.scope_done_label.text())

    def test_theme_change_recolors_options(self):
        self.page.apply_theme(DARK)
        self.assertIs(self.page.theme, DARK)
        self.assertTrue(self.page.option_rows)
        for row in self.page.option_rows:
            self.assertIs(row.theme, DARK)

    def test_theme_switch_refreshes_navigator_and_shortcut_bar(self):
        self.page.apply_theme(DARK)
        self.assertIs(self.page.navigator.theme, DARK)
        self.assertIn(DARK.surface_alt, self.page.shortcut_bar.styleSheet())
        self.page.apply_theme(LIGHT)
        self.assertIs(self.page.navigator.theme, LIGHT)
        self.assertIn(LIGHT.surface_alt, self.page.shortcut_bar.styleSheet())

    # ---------------------------------------------------------------- 布局合并
    def test_action_buttons_inside_question_card(self):
        """提交 / 看答案 / 上一题 / 下一题已并入题卡底部，不再占侧栏卡片。"""
        page = self.page
        for button in (page.submit_button, page.reveal_button,
                       page.prev_button, page.next_button):
            self.assertTrue(page.question_card.isAncestorOf(button),
                            "作答按钮应是题卡的后代（题卡内部底部）")
            self.assertFalse(page.side_scroll.isAncestorOf(button),
                             "作答按钮不应再出现在右侧栏")

    def test_sidebar_has_no_actions_or_shortcut_card(self):
        page = self.page
        from PySide6.QtWidgets import QLabel

        self.assertFalse(page.side_scroll.isAncestorOf(page.submit_button))
        self.assertFalse(page.side_scroll.isAncestorOf(page.shortcut_bar))
        # 侧栏不应再有整条快捷键说明卡片
        labels = page.side_scroll.findChildren(QLabel)
        self.assertFalse(
            [label for label in labels if "F5" in label.text() and "F9" in label.text()],
            "右侧栏不应再包含快捷键卡片")

    def test_shortcut_bar_is_last_root_item(self):
        page = self.page
        layout = page.layout()
        self.assertGreaterEqual(layout.count(), 1)
        last = layout.itemAt(layout.count() - 1).widget()
        self.assertIs(last, page.shortcut_bar, "快捷键长条应是页面根布局的最后一项")
        self.assertEqual(page.shortcut_bar.objectName(), "ShortcutBar")
        self.assertTrue(30 <= page.shortcut_bar.minimumHeight() <= 34,
                        "快捷键长条高度应约 30~34px")
        self.assertEqual(page.shortcut_bar.minimumWidth(), 0)
        text = page.shortcut_label.text()
        for token in ("1~8", "A~H", "Enter", "上一题", "下一题", "F5", "F9"):
            self.assertIn(token, text, f"快捷键长条缺少提示：{token}")
        self.assertIn("快捷键", page.shortcut_title.text())

    # ---------------------------------------------------------------- 闪窗回归
    def test_refresh_does_not_leak_visible_top_level_widgets(self):
        """重绘时旧选项行不得变成"可见的顶层窗口"。

        回归 v1.3.0 实测缺陷：`clear_layout` 对**可见**子控件直接 `setParent(None)`，
        Qt 会把它提升为顶层窗口并显示一帧——用户看到的是"点一下按钮屏幕闪个小窗"。
        """
        win = self.window(self.ctrl)
        win.set_page("practice")
        process_events()
        known = set(QApplication.topLevelWidgets())
        win.practice_page.shuffle_single_box.setChecked(True)   # 触发整页重绘
        process_events()
        leaked = [w for w in QApplication.topLevelWidgets()
                  if w not in known and w.isVisible() and isinstance(w, OptionRow)]
        self.assertEqual(leaked, [], "重绘后仍有多余的可见顶层窗口（会造成闪窗）")
        # 新选项行必须已经挂在页面上（而不是漂在外面）
        for row in win.practice_page.option_rows:
            self.assertIsNotNone(row.parentWidget())
            self.assertFalse(row.isWindow())


def page_feedback_kind(page) -> str:
    return str(page.feedback_label.property("state"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
