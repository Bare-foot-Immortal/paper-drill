# -*- coding: utf-8 -*-
"""刷题匠 PaperDrill —— 练习页（FR-17）。

布局：顶部工具栏 → 左侧题目工作区（可滚动，避免长题/多选项被截断）+ 右侧进度侧栏
（进度环、统计胶囊、题目导览）→ 页面最底部的快捷键长条。
所有渲染都由 :class:`~paperdrill.ui.controller.PaperDrillController` 的状态驱动，
页面本身不保存"当前题"等业务状态。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...models import QType
from ...practice import PracticeMode, Scope
from ..controller import PaperDrillController, UiState
from ..theme import Theme
from ..widgets import (
    Card,
    EmptyState,
    HLine,
    OptionRow,
    ProgressRing,
    QuestionNavigator,
    SectionLabel,
    SegmentedControl,
    StatPill,
    clear_layout,
    link_clicked,
)

__all__ = ["PracticePage"]

SCOPE_OPTIONS = [(s.value, s.label) for s in
                 (Scope.ALL, Scope.SINGLE, Scope.MULTIPLE, Scope.JUDGE)]
MODE_OPTIONS = [(m.value, m.label) for m in
                (PracticeMode.ORDER, PracticeMode.RANDOM, PracticeMode.WRONG, PracticeMode.FRESH)]

# 页面底部快捷键长条文案（横跨整页，一直可见）
SHORTCUT_HINT = ("1~8 / A~H 选择选项　·　Enter 提交 / 下一题　·　← / → 上一题 / 下一题　·　"
                 "F5 生成试卷　·　F9 交卷")


class PracticePage(QWidget):
    """练习页。"""

    next_requested = Signal()
    previous_requested = Signal()
    restart_requested = Signal()
    goto_requested = Signal(int)      # 题目导览：跳转到队列下标（0 基）

    def __init__(self, controller: PaperDrillController, theme: Theme,
                 parent: "QWidget | None" = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.theme = theme
        self.option_rows: list = []
        self._build()
        # 自订阅控制器信号：页面可独立实例化（测试/嵌入式使用）也会保持最新
        # 只订阅 state_changed：控制器每次变化都会发它，避免与 practice_changed 重复刷新
        self.controller.state_changed.connect(self._on_controller_changed)
        self.refresh(self.controller.state)

    def _on_controller_changed(self, *_args) -> None:
        self.refresh(self.controller.state)

    # ================================================================ 构建
    def _build(self) -> None:
        t = self.theme
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(t.space_md)

        # ---- 工具栏
        tools = Card(t)
        row = QHBoxLayout()
        row.setSpacing(t.space_md)
        row.addWidget(SectionLabel("练习范围", t))
        self.scope_control = SegmentedControl(SCOPE_OPTIONS, t)
        row.addWidget(self.scope_control)
        row.addSpacing(t.space_lg)
        row.addWidget(SectionLabel("练习模式", t))
        self.mode_control = SegmentedControl(MODE_OPTIONS, t)
        row.addWidget(self.mode_control)
        row.addStretch(1)
        tools.add_layout(row)

        toggles = QHBoxLayout()
        toggles.setSpacing(t.space_lg)
        self.shuffle_single_box = QCheckBox("单选打乱选项")
        self.shuffle_multiple_box = QCheckBox("多选打乱选项")
        self.auto_next_box = QCheckBox("答对自动下一题")
        self.analysis_box = QCheckBox("显示解析")
        for box in (self.shuffle_single_box, self.shuffle_multiple_box,
                    self.auto_next_box, self.analysis_box):
            toggles.addWidget(box)
        toggles.addStretch(1)
        self.restart_button = QPushButton("重新开始本轮")
        self.restart_button.setProperty("kind", "ghost")
        toggles.addWidget(self.restart_button)
        tools.add_layout(toggles)
        root.addWidget(tools)

        # ---- 主体：左题面 / 右侧栏
        body = QHBoxLayout()
        body.setSpacing(t.space_md)
        root.addLayout(body, 1)

        # 左：可滚动题面
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        holder = QWidget()
        holder.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        scroll_lay = QVBoxLayout(holder)
        scroll_lay.setContentsMargins(0, 0, 0, 0)
        scroll_lay.setSpacing(0)

        self.question_card = Card(t)
        hdr = QHBoxLayout()
        hdr.setSpacing(t.space_md)
        self.pos_label = QLabel("第 0 / 0 题")
        self.pos_label.setObjectName("CardTitle")
        self.type_badge = QLabel("")
        self.type_badge.setStyleSheet("font-weight:700;")
        self.state_label = QLabel("")
        self.state_label.setObjectName("Muted")
        hdr.addWidget(self.pos_label)
        hdr.addWidget(self.type_badge)
        hdr.addWidget(self.state_label)
        hdr.addStretch(1)
        self.question_card.add_layout(hdr)

        self.stem_label = QLabel("导入题库后开始练习")
        self.stem_label.setObjectName("StemText")
        self.stem_label.setWordWrap(True)
        self.stem_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.stem_label.setMinimumHeight(28)
        self.question_card.add(self.stem_label)

        self.options_box = QVBoxLayout()
        self.options_box.setSpacing(t.space_sm)
        self.question_card.add_layout(self.options_box)

        self.empty_state = EmptyState(t)
        self.empty_state.hide()
        self.question_card.add(self.empty_state)

        self.feedback_label = QLabel("")
        self.feedback_label.setObjectName("Feedback")
        self.feedback_label.setProperty("state", "idle")
        self.feedback_label.setWordWrap(True)
        self.question_card.add(self.feedback_label)

        self.analysis_label = QLabel("")
        self.analysis_label.setObjectName("AnalysisText")
        self.analysis_label.setWordWrap(True)
        self.analysis_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.question_card.add(self.analysis_label)
        # 卡片会随窗口拉伸；把多余高度交给末尾的 stretch，避免各文本行被均匀撑开。
        # 作答按钮组放在 stretch 之后 = 题卡内部最底部（不再占用独立侧栏卡片）。
        self.question_card.body.addStretch(1)
        self.question_divider = HLine(t)
        self.question_card.body.addWidget(self.question_divider)

        actions = QHBoxLayout()
        actions.setSpacing(t.space_sm)
        self.submit_button = QPushButton("提交答案")
        self.submit_button.setProperty("kind", "primary")
        self.submit_button.setMinimumHeight(38)
        self.reveal_button = QPushButton("不会，看答案")
        self.reveal_button.setMinimumHeight(38)
        self.prev_button = QPushButton("◀ 上一题")
        self.next_button = QPushButton("下一题 ▶")
        self.next_button.setProperty("kind", "primary")
        actions.addWidget(self.submit_button)
        actions.addWidget(self.reveal_button)
        actions.addStretch(1)
        actions.addWidget(self.prev_button)
        actions.addWidget(self.next_button)
        self.question_card.add_layout(actions)

        scroll_lay.addWidget(self.question_card, 1)
        self.scroll.setWidget(holder)
        body.addWidget(self.scroll, 1)

        # 右侧栏：放进可滚动容器，高 DPI / 小窗口下卡片不会被压扁（避免环与胶囊重叠）
        side_widget = QWidget()
        side = QVBoxLayout(side_widget)
        side.setSpacing(t.space_md)
        side.setContentsMargins(0, 0, 0, 0)
        side_scroll = QScrollArea(self)
        side_scroll.setWidgetResizable(True)
        side_scroll.setFrameShape(QScrollArea.NoFrame)
        side_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        side_scroll.setFixedWidth(360)
        side_scroll.setWidget(side_widget)
        body.addWidget(side_scroll)

        progress_card = Card(t, title="本范围进度")
        ring_row = QHBoxLayout()
        self.ring = ProgressRing(t, 0.0, 108)
        ring_row.addWidget(self.ring)
        info = QVBoxLayout()
        info.setSpacing(t.space_xs)
        self.scope_done_label = QLabel("0 / 0 题")
        self.scope_done_label.setStyleSheet("font-weight:700;")
        self.scope_rate_label = QLabel("正确率 —")
        self.scope_rate_label.setObjectName("Muted")
        info.addWidget(self.scope_done_label)
        info.addWidget(self.scope_rate_label)
        info.addStretch(1)
        ring_row.addLayout(info, 1)
        progress_card.add_layout(ring_row)

        pills = QHBoxLayout()
        pills.setSpacing(t.space_sm)
        self.pill_right = StatPill("答对", "0", "success", t)
        self.pill_wrong = StatPill("答错", "0", "danger", t)
        self.pill_book = StatPill("错题", "0", "warning", t)
        for pill in (self.pill_right, self.pill_wrong, self.pill_book):
            pills.addWidget(pill)
        progress_card.add_layout(pills)

        # ---- 题目导览（Spec：5 列方格、可滚动、点击跳题、按对错着色）
        self.nav_divider = HLine(t)
        progress_card.add(self.nav_divider)
        nav_head = QHBoxLayout()
        nav_head.setSpacing(t.space_sm)
        nav_head.addWidget(SectionLabel("题目导览", t))
        nav_head.addStretch(1)
        self.nav_hint_label = QLabel("本轮 0 题")
        self.nav_hint_label.setObjectName("CardHint")
        nav_head.addWidget(self.nav_hint_label)
        progress_card.add_layout(nav_head)

        self.navigator = QuestionNavigator(t, progress_card)
        progress_card.add(self.navigator)

        self.nav_legend = QLabel("点击题号跳题；绿=答对、红=答错")
        self.nav_legend.setObjectName("Faint")
        self.nav_legend.setWordWrap(True)
        progress_card.add(self.nav_legend)
        side.addWidget(progress_card)
        side.addStretch(1)
        self.side_scroll = side_scroll

        # ---- 页面最底部：横跨整页的快捷键长条（不再是右侧卡片）
        self.shortcut_bar = QFrame(self)
        self.shortcut_bar.setObjectName("ShortcutBar")
        self.shortcut_bar.setFixedHeight(32)
        self.shortcut_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        shortcut_lay = QHBoxLayout(self.shortcut_bar)
        shortcut_lay.setContentsMargins(t.space_lg, 0, t.space_lg, 0)
        shortcut_lay.setSpacing(t.space_sm)
        self.shortcut_title = QLabel("快捷键")
        self.shortcut_label = QLabel(SHORTCUT_HINT)
        self.shortcut_label.setWordWrap(False)
        # 窗口变窄时由标签吸收压缩（文字只被裁剪），不允许把页面撑宽变形
        self.shortcut_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.shortcut_label.setMinimumWidth(0)
        self.shortcut_label.setToolTip(SHORTCUT_HINT)
        shortcut_lay.addWidget(self.shortcut_title)
        shortcut_lay.addWidget(self.shortcut_label, 1)
        root.addWidget(self.shortcut_bar)
        self._restyle_shortcut_bar(t)

        # ---- 信号
        self.scope_control.changed.connect(self._on_scope)
        self.mode_control.changed.connect(self._on_mode)
        self.shuffle_single_box.toggled.connect(
            lambda checked: self.controller.set_shuffle(single=checked))
        self.shuffle_multiple_box.toggled.connect(
            lambda checked: self.controller.set_shuffle(multiple=checked))
        self.auto_next_box.toggled.connect(self.controller.set_auto_next)
        self.analysis_box.toggled.connect(self.controller.set_show_analysis)
        link_clicked(self.restart_button, self.restart_requested)
        self.submit_button.clicked.connect(lambda *_: self.controller.submit())
        self.reveal_button.clicked.connect(lambda *_: self.controller.reveal())
        link_clicked(self.prev_button, self.previous_requested)
        link_clicked(self.next_button, self.next_requested)
        self.navigator.go_requested.connect(
            lambda index: self.goto_requested.emit(int(index)))

    # ================================================================ 事件
    def _on_scope(self, key: str) -> None:
        self.controller.set_scope(Scope.from_label(key))

    def _on_mode(self, key: str) -> None:
        self.controller.set_mode(PracticeMode.from_label(key))

    def press_option(self, letter: str) -> None:
        self.controller.toggle_option(letter)

    def press_submit(self) -> None:
        self.controller.submit()

    def press_reveal(self) -> None:
        self.controller.reveal()

    # ================================================================ 渲染
    def refresh(self, state: UiState) -> None:
        self._sync_toolbar(state)
        self._render_question(state)
        self._render_side(state)

    def _sync_toolbar(self, state: UiState) -> None:
        """把控制器状态同步回控件（只在值不同时设置，避免触发循环信号）。"""
        scope_key = state.scope.value
        if self.scope_control.current() != scope_key:
            self.scope_control.set_current(scope_key)
        mode_key = state.mode.value
        if self.mode_control.current() != mode_key:
            self.mode_control.set_current(mode_key)
        for box, value in ((self.shuffle_single_box, state.shuffle_single),
                           (self.shuffle_multiple_box, state.shuffle_multiple),
                           (self.auto_next_box, state.auto_next),
                           (self.analysis_box, state.show_analysis)):
            if box.isChecked() != bool(value):
                box.blockSignals(True)
                box.setChecked(bool(value))
                box.blockSignals(False)

    def _render_question(self, state: UiState) -> None:
        clear_layout(self.options_box)
        self.option_rows = []
        item = self.controller.current_item() if state.loaded else None

        if item is None:
            self.question_card.show()
            self.stem_label.hide()
            self.empty_state.show()
            if state.loaded and state.session is not None and state.session.empty:
                self.empty_state.set_text("没有可练习的题目", state.feedback or "请更换范围或模式。")
            else:
                self.empty_state.set_text("尚未导入题库",
                                          "用「文件 → 导入题库…」或把题库文件拖到窗口上开始。")
            self._set_feedback(state.feedback or "", state.feedback_kind)
            self.analysis_label.setText(state.analysis_text)
            self.pos_label.setText("第 0 / 0 题")
            self.type_badge.setText("")
            self.state_label.setText("")
            self._sync_answer_buttons(state, None)
            return

        self.empty_state.hide()
        self.question_card.show()
        self.stem_label.show()
        self.pos_label.setText(f"第 {state.position} / {state.total} 题")
        self.type_badge.setText(item.qtype.value)
        self.type_badge.setStyleSheet(f"color:{self.theme.warning};font-weight:700;")
        self.state_label.setText(self._state_text(state, item))
        self.stem_label.setText(f"{state.position}. {(item.stem or '').strip()}")

        answered = state.answered
        selection = set(state.selection)
        for letter, text in item.options():
            option = OptionRow(letter, text, self.theme)
            option.pressed.connect(self.press_option)
            self.options_box.addWidget(option)
            self.option_rows.append(option)

            state_name = "default"
            mark = ""
            if answered:
                is_answer = letter in item.shown_answer
                if is_answer:
                    state_name = "correct"
                    mark = "check"
                elif letter in selection:
                    state_name = "wrong"
                    mark = "cross"
                else:
                    state_name = "dim"
            elif letter in selection:
                state_name = "selected"
            option.set_state(state_name, mark)
            option.set_enabled_look(not answered)

        self._set_feedback(state.feedback, state.feedback_kind)
        self.analysis_label.setText(state.analysis_text)
        self._sync_answer_buttons(state, item)

    def _state_text(self, state: UiState, item) -> str:
        if state.answered:
            return ""
        record = self.controller.current_record()
        if record is not None and record.done:
            return "此前已作答，可重做"
        # 题型已由左侧徽标展示，这里只给操作提示，避免"单选题 单选题："重复
        if item.qtype is QType.MULTIPLE:
            return "勾选全部正确项后提交"
        return "点选即判"

    def _sync_answer_buttons(self, state: UiState, item) -> None:
        multiple = bool(item is not None and item.qtype is QType.MULTIPLE)
        if item is None:
            self.submit_button.setEnabled(False)
            self.reveal_button.setEnabled(False)
        else:
            self.submit_button.setEnabled(multiple and not state.answered)
            self.reveal_button.setEnabled(not state.answered)
        self.prev_button.setEnabled(state.loaded and state.position > 1)
        self.next_button.setEnabled(state.loaded and state.position < state.total)

    def _set_feedback(self, text: str, kind: str) -> None:
        self.feedback_label.setText(text)
        self.feedback_label.setProperty("state", kind or "idle")
        # 动态属性变化后需要重新求值 QSS
        style = self.feedback_label.style()
        style.unpolish(self.feedback_label)
        style.polish(self.feedback_label)

    def _render_side(self, state: UiState) -> None:
        scoped = self.controller.scope_stats()
        # 环里只放百分比；"已练 / 总数"由右侧标签展示，避免同一信息出现两遍
        self.ring.set_value(scoped["done_rate"], "")
        self.scope_done_label.setText(f"{scoped['done']} / {scoped['total']} 题")
        rate = f"{scoped['accuracy'] * 100:.1f}%" if scoped["attempts"] else "—"
        self.scope_rate_label.setText(f"正确率 {rate}")
        live = self.controller.stats()
        self.pill_right.set_value(str(live["right"]))
        self.pill_wrong.set_value(str(live["wrong"]))
        self.pill_book.set_value(str(live["wrong_book"]))

        # 题目导览：按本轮队列顺序取每题的最近一次作答结果
        session = state.session
        store = state.store
        if session is None or session.empty or store is None:
            total, current, statuses = 0, 0, []
        else:
            total = session.total
            current = session.cursor
            statuses = [self._question_status(store, session.questions[index])
                        for index in session.order]
        self.navigator.set_questions(total, current, statuses)
        # 没有可练题目时隐藏空网格，避免进度卡里出现一块无意义的空白区域
        has_queue = bool(total)
        self.navigator.setVisible(has_queue)
        self.nav_legend.setVisible(has_queue)
        self.nav_hint_label.setText(f"本轮 {total} 题" if has_queue else "暂无题目")

    @staticmethod
    def _question_status(store, question) -> str:
        record = store.record_of(question)
        if record is None or not record.done:
            return "todo"
        if record.last == "right":
            return "correct"
        if record.last == "wrong":
            return "wrong"
        return "todo"

    def _restyle_shortcut_bar(self, theme: Theme) -> None:
        """快捷键长条配色（主题令牌，页面里用内联 QSS，避免改全局样式表）。"""
        t = theme
        radius = max(4, t.radius)
        self.shortcut_bar.setStyleSheet(
            f"#ShortcutBar{{background:{t.surface_alt};border:1px solid {t.border};"
            f"border-radius:{radius}px;}}")
        self.shortcut_title.setStyleSheet(
            f"color:{t.text};font-size:{t.font_size_small}px;font-weight:700;"
            "background:transparent;")
        self.shortcut_label.setStyleSheet(
            f"color:{t.text_muted};font-size:{t.font_size_small}px;background:transparent;")

    # ================================================================ 主题
    def apply_theme(self, theme: Theme) -> None:
        self.theme = theme
        for row in self.option_rows:
            row.theme = theme
            row.update()
        self.ring.refresh(theme)
        self.empty_state.refresh(theme)
        for pill in (self.pill_right, self.pill_wrong, self.pill_book):
            pill.restyle(theme)
        self.scope_control.restyle(theme)
        self.mode_control.restyle(theme)
        self.navigator.refresh_theme(theme)
        self.nav_divider.refresh(theme)
        self.question_divider.refresh(theme)
        self._restyle_shortcut_bar(theme)
        self.refresh(self.controller.state)
