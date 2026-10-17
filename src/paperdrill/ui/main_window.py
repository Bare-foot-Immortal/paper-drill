# -*- coding: utf-8 -*-
"""刷题匠 PaperDrill —— Qt 主窗口。

职责：拼装侧边导航 / 顶栏 / 页面栈 / 状态栏，绑定菜单与快捷键，
把控制器信号接到页面刷新，并在关闭时持久化窗口几何。
"""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QCursor, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .. import __app_name__, __version__
from ..bank_io import SUPPORTED_SUFFIXES
from ..practice import PracticeMode, Scope
from . import theme as theme_module
from .application import app_icon_path
from .controller import PaperDrillController
from .dialogs import (
    AboutDialog,
    BankPickerDialog,
    ExamHistoryDialog,
    HelpDialog,
    ProgressDialog,
    QuestionFilterDialog,
    WrongBookDialog,
    confirm,
    notify,
    warn,
)
from .pages.exam import ExamSetupPage
from .pages.exam_run import ExamRunPage
from .pages.library import LibraryPage
from .pages.practice import PracticePage
from .pages.result import ExamResultPage
from .theme import Theme, theme_for
from .widgets import StatPill

__all__ = ["MainWindow", "HELP_TEXT", "PAGES"]

HELP_TEXT = """【刷题匠 PaperDrill 使用说明】

一、准备题库
  · 支持 .xlsx / .xlsm / .csv / .txt / .json / .docx / .docm / .pdf
  · Excel 列头：题型 | 题目标题 | 选项A…选项H | 解析 | 答案
  · Word：表格型（同列头）或段落文本型（题干一行、选项一行或分行、答案一行）
  · PDF：取文本层解析，扫描件无法识别
  · 答案标记「（定）」的题目选项顺序永不打乱

二、练习
  1. 选范围（整个题库 / 只练单选 / 只练多选 / 只练判断）
  2. 选模式（顺序 / 随机 / 错题重练 / 只练未做）
  3. 单选与判断点选即判；多选勾选后点「提交答案」
  4. 已作答的题可以重新作答；「不会，看答案」直接看答案与解析
  5. 右侧「本范围进度」下方是题目导览：点题号直接跳题
     （绿=答对、红=答错、灰=未答）；「提交答案 / 上一题 / 下一题」
     按钮就在题卡内部最底部

三、模拟考试
  1. 设置每卷各题型数量与分值，系统自动算出覆盖题库所需的轮长
  2. 「生成一轮试卷」→ 覆盖校验 → 选卷 → 开始模拟考试
  3. 作答期间不显示对错；交卷后给出得分、各题型得分与逐题解析

四、进度与数据
  · 每答一题即时保存；重开软件自动接着上次继续
  · 「练习 → 题库删减…」把不想练的题移出（不改题库原文件，可随时恢复）
  · 「文件 → 选择题库…」查看最近用过的题库并一键切换
  · 进度目录：%APPDATA%\\PaperDrill\\progress\\

五、快捷键
  Ctrl+O 导入题库　Ctrl+B 选择题库　Ctrl+W 错题本　Ctrl+P 进度管理
  F1 使用说明　F5 生成一轮试卷　F9 交卷
  1~8 / A~H 选选项　Enter 提交或下一题　← → 上一题 / 下一题

六、界面
  · 左下角「主题」可切换 浅色 / 深色 / 跟随系统
  · 把题库文件直接拖到窗口上即可打开
  · 练习页最下方固定一条快捷键提示条（横跨整页，翻页/作答时一直可见）
"""

PAGES = ("practice", "exam", "library")

_NAV_ITEMS = (
    ("practice", "练习"),
    ("exam", "模拟考试"),
    ("library", "题库资料"),
)

_INPUT_TYPES = (QLineEdit, QAbstractSpinBox, QComboBox, QTextEdit)


class MainWindow(QMainWindow):
    """应用主窗口。"""

    def __init__(self, controller: PaperDrillController, theme_mode: str = "system",
                 autoload: bool = True, parent: "QWidget | None" = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.theme_mode = theme_mode if theme_mode in theme_module.THEME_MODES else "system"
        self.theme: Theme = theme_for(self.theme_mode)
        self.setWindowTitle(f"{__app_name__} v{__version__} —— 题库练习与模拟考试")
        self.setMinimumSize(QSize(1024, 700))
        self.resize(QSize(1180, 820))
        self.setAcceptDrops(True)
        icon_path = app_icon_path()
        if icon_path:
            self.setWindowIcon(QIcon(icon_path))

        self._build_ui()
        self._build_menu()
        self._build_shortcuts()
        self._connect_controller()

        self.apply_theme(self.theme_mode)
        self.controller.state_changed.connect(self._sync_chrome)
        self.controller.stats_changed.connect(self._sync_chrome)
        self.controller.status_message.connect(self.set_status)
        self.controller.practice_changed.connect(self._refresh_practice)
        self.controller.exam_changed.connect(self._refresh_exam)
        self.controller.paper_changed.connect(self._refresh_exam)
        self.controller.library_changed.connect(self._refresh_library)
        self.controller.theme_requested.connect(self.apply_theme)

        self._sync_chrome()
        self._refresh_practice()
        self._refresh_exam()
        self._refresh_library()

        if not self.apply_geometry_text(getattr(self.controller.settings, "qt_window_state", "")):
            legacy = getattr(self.controller.settings, "window_geometry", "") or ""
            self._apply_legacy_geometry(legacy)

        last_page = str(getattr(self.controller.settings, "last_page", "") or "")
        if last_page in PAGES:
            self.set_page(last_page, persist=False)

        if autoload:
            pending = self.controller.settings.bank_path
            if pending and Path(pending).is_file():
                self.controller.load_bank(pending)
            else:
                recent = self.controller.recent_bank()
                if recent:
                    self.controller.load_bank(recent["path"])
                elif pending:
                    self.set_status(f"上次的题库已不存在：{pending}（文件 → 选择题库… 可重新指定）")
        self._sync_chrome()

    # ================================================================ 构建
    def _build_ui(self) -> None:
        t = self.theme
        central = QWidget()
        central.setObjectName("AppRoot")
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_sidebar())

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        right.addWidget(self._build_topbar())
        self.stack = QStackedWidget()
        right.addWidget(self.stack, 1)
        layout.addLayout(right, 1)
        self.setCentralWidget(central)

        # ---- 页面
        self.practice_page = PracticePage(self.controller, t)
        self.stack.addWidget(self.practice_page)

        self.exam_container = QWidget()
        exam_lay = QVBoxLayout(self.exam_container)
        exam_lay.setContentsMargins(t.space_lg, t.space_md, t.space_lg, t.space_md)
        exam_lay.setSpacing(0)
        self.exam_views = QStackedWidget()
        self.exam_setup_page = ExamSetupPage(self.controller, t)
        self.exam_run_page = ExamRunPage(self.controller, t)
        self.exam_result_page = ExamResultPage(self.controller, t)
        # 配置页内容较高（蓝图 + 覆盖校验 + 选卷 + 明细表），高 DPI 或小窗口下会被挤压裁切，
        # 因此放进可滚动容器：内容按自身最小高度展开，空间不够时出现滚动条。
        self.exam_setup_scroll = QScrollArea()
        self.exam_setup_scroll.setWidgetResizable(True)
        self.exam_setup_scroll.setFrameShape(QScrollArea.NoFrame)
        self.exam_setup_scroll.setWidget(self.exam_setup_page)
        self.exam_views.addWidget(self.exam_setup_scroll)
        self.exam_views.addWidget(self.exam_run_page)
        self.exam_views.addWidget(self.exam_result_page)
        exam_lay.addWidget(self.exam_views)
        self.stack.addWidget(self.exam_container)

        self.library_page = LibraryPage(self.controller, t)
        self.stack.addWidget(self.library_page)

        # 练习页需要外边距
        self.practice_page.layout().setContentsMargins(
            t.space_lg, t.space_md, t.space_lg, t.space_md)

        # ---- 状态栏
        bar = QFrame()
        bar.setObjectName("StatusBar")
        bar_lay = QHBoxLayout(bar)
        bar_lay.setContentsMargins(t.space_lg, 4, t.space_lg, 4)
        self.status_label = QLabel("就绪")
        self.status_label.setObjectName("Muted")
        bar_lay.addWidget(self.status_label, 1)
        self.save_error_label = QLabel("")
        self.save_error_label.setStyleSheet(f"color:{t.danger};font-weight:700;")
        bar_lay.addWidget(self.save_error_label)
        self.statusBar().addPermanentWidget(bar, 1)

        # ---- 页面信号
        self.practice_page.next_requested.connect(self._practice_next)
        self.practice_page.previous_requested.connect(self._practice_prev)
        self.practice_page.goto_requested.connect(self.controller.goto)
        self.practice_page.restart_requested.connect(self.controller.restart_round)
        self.exam_setup_page.start_requested.connect(self._start_exam_at)
        self.exam_setup_page.next_unused_requested.connect(self._start_next_unused)
        self.exam_setup_page.history_requested.connect(self._show_exam_history)
        self.exam_run_page.submit_requested.connect(self._submit_exam)
        self.exam_run_page.exit_requested.connect(lambda: self._show_exam_view("config"))
        self.exam_result_page.back_requested.connect(lambda: self._show_exam_view("config"))
        self.library_page.import_requested.connect(self._choose_bank)
        self.library_page.scan_requested.connect(self._scan_folder)
        self.library_page.bank_switch_requested.connect(self._load_bank_path)
        self.library_page.filter_requested.connect(self._show_question_filter)
        self.library_page.exclude_requested.connect(self._forget_entry)
        self.library_page.exclude_with_progress_requested.connect(self._forget_entry_with_progress)
        # 双击载入由 LibraryPage 自己发 bank_switch_requested（这里不要再连一次，
        # 否则一次双击会载入两遍）
        self.library_page.library_table.selectionModel().selectionChanged.connect(
            lambda *_: self._sync_library_buttons())

        # 初始页先不落盘：等 __init__ 里恢复 last_page 之后再确定
        self.set_page("practice", persist=False)

    def _build_sidebar(self) -> QWidget:
        t = self.theme
        side = QFrame()
        side.setObjectName("SideBar")
        side.setFixedWidth(196)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(t.space_md, t.space_lg, t.space_md, t.space_md)
        lay.setSpacing(t.space_xs)

        brand = QLabel("刷题匠")
        brand.setObjectName("SideBarBrand")
        lay.addWidget(brand)
        sub = QLabel(f"PaperDrill v{__version__}")
        sub.setObjectName("SideBarSub")
        lay.addWidget(sub)
        lay.addSpacing(t.space_lg)

        self.nav_buttons: dict[str, QPushButton] = {}
        for key, label in _NAV_ITEMS:
            btn = QPushButton(label)
            btn.setObjectName("NavButton")
            btn.setCheckable(False)
            # 导航只做页面切换：不抢焦点，避免"当前页"与"焦点框"同时高亮造成混淆
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, k=key: self.set_page(k))
            btn.setProperty("active", False)
            lay.addWidget(btn)
            self.nav_buttons[key] = btn

        lay.addStretch(1)
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("跟随系统", "system")
        self.theme_combo.addItem("浅色", "light")
        self.theme_combo.addItem("深色", "dark")
        index = max(0, self.theme_combo.findData(self.theme_mode))
        self.theme_combo.setCurrentIndex(index)
        self.theme_combo.currentIndexChanged.connect(
            lambda *_: self.apply_theme(self.theme_combo.currentData()))
        lay.addWidget(QLabel("主题"))
        lay.addWidget(self.theme_combo)
        return side

    def _build_topbar(self) -> QWidget:
        t = self.theme
        bar = QFrame()
        bar.setObjectName("TopBar")
        bar.setFixedHeight(74)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(t.space_lg, t.space_sm, t.space_lg, t.space_sm)
        lay.setSpacing(t.space_md)

        info = QVBoxLayout()
        info.setSpacing(2)
        self.bank_label = QLabel("（尚未导入题库）")
        self.bank_label.setStyleSheet("font-size:15px;font-weight:700;")
        self.stats_label = QLabel("导入题库后开始练习")
        self.stats_label.setObjectName("Muted")
        info.addWidget(self.bank_label)
        info.addWidget(self.stats_label)
        lay.addLayout(info, 1)

        self.pill_done = StatPill("已练", "0", "primary", t)
        self.pill_rate = StatPill("正确率", "—", "neutral", t)
        self.pill_book = StatPill("错题", "0", "warning", t)
        for pill in (self.pill_done, self.pill_rate, self.pill_book):
            lay.addWidget(pill)
        return bar

    # ================================================================ 菜单
    def _build_menu(self) -> None:
        m_file = self.menuBar().addMenu("文件")
        self._action(m_file, "导入题库…", self._choose_bank, "Ctrl+O")
        self._action(m_file, "选择题库…", self._show_bank_picker, "Ctrl+B")
        self._action(m_file, "重新载入当前题库", self.controller.reload_bank)
        m_file.addSeparator()
        self._action(m_file, "打开进度目录", self._open_progress_dir)
        m_file.addSeparator()
        self._action(m_file, "退出", self.close)

        m_prac = self.menuBar().addMenu("练习")
        for mode in (PracticeMode.ORDER, PracticeMode.RANDOM,
                     PracticeMode.WRONG, PracticeMode.FRESH):
            self._action(m_prac, mode.label,
                         lambda _checked=False, m=mode: self._set_mode(m))
        m_prac.addSeparator()
        for scope in (Scope.ALL, Scope.SINGLE, Scope.MULTIPLE, Scope.JUDGE):
            self._action(m_prac, scope.label,
                         lambda _checked=False, s=scope: self._set_scope(s))
        m_prac.addSeparator()
        self._action(m_prac, "重新开始本轮（不清进度）", self.controller.restart_round)
        self._action(m_prac, "重置本题库进度…", self._reset_progress)
        m_prac.addSeparator()
        self._action(m_prac, "题库删减…", self._show_question_filter)
        self._action(m_prac, "错题本…", self._show_wrong_book, "Ctrl+W")
        self._action(m_prac, "进度管理…", self._show_progress_manager, "Ctrl+P")

        m_exam = self.menuBar().addMenu("模拟考试")
        self._action(m_exam, "生成一轮试卷", self.controller.generate_round, "F5")
        self._action(m_exam, "开始/继续模拟考试", self._start_exam_selected)
        self._action(m_exam, "交卷", self._submit_exam, "F9")
        m_exam.addSeparator()
        self._action(m_exam, "历史成绩…", self._show_exam_history)

        m_view = self.menuBar().addMenu("视图")
        for label, mode in (("跟随系统主题", "system"), ("浅色主题", "light"), ("深色主题", "dark")):
            self._action(m_view, label, lambda _checked=False, m=mode: self.apply_theme(m))

        m_help = self.menuBar().addMenu("帮助")
        self._action(m_help, "使用说明", self._show_help, "F1")
        self._action(m_help, "关于", self._show_about)

    def _action(self, menu: QMenu, text: str, slot, shortcut: str = ""):
        action = menu.addAction(text)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(lambda _checked=False: slot())
        return action

    # ================================================================ 快捷键
    def _build_shortcuts(self) -> None:
        """全局快捷键。

        用 ``WidgetWithChildrenShortcut`` 绑定在主窗口：只在本窗口及其子控件内生效，
        对话框里的按键不会触发主界面作答（FR-20.3）。
        """
        self._shortcuts: list[QShortcut] = []

        def add(sequence: str, callback) -> None:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(callback)
            self._shortcuts.append(shortcut)

        for key in "12345678":
            add(key, lambda k=key: self._select_index(int(k) - 1))
        # 注意：QKeySequence("A") 与 QKeySequence("a") 归一为同一按键，注册两条会让
        # QShortcutMap 判定为 ambiguous（activated 不再发射），因此只注册大写一次。
        for index, letter in enumerate("ABCDEFGH"):
            add(letter, lambda i=index: self._select_index(i))
        for sequence in ("Return", "Enter"):
            add(sequence, self._on_enter)
        add("Left", lambda: self._on_arrow(-1))
        add("Right", lambda: self._on_arrow(1))

    def _shortcut_target_ok(self) -> bool:
        """焦点在输入类控件上时不劫持按键（FR-20.2）。"""
        widget = QApplication.focusWidget()
        if widget is None:
            return True
        return not isinstance(widget, _INPUT_TYPES)

    def _select_index(self, index: int) -> None:
        if index < 0 or not self._shortcut_target_ok():
            return
        page = self.current_page()
        if page == "practice":
            item = self.controller.current_item()
            if item is None or index >= item.option_count:
                return
            self.controller.toggle_option(item.labels[index])
        elif page == "exam" and self.controller.state.exam_view == "taking":
            item = self.controller.exam_item(self.controller.state.exam_index)
            if item is None or index >= item.option_count:
                return
            self.exam_run_page.press_option(item.labels[index])

    def _on_enter(self) -> None:
        if not self._shortcut_target_ok():
            return
        page = self.current_page()
        if page == "practice":
            state = self.controller.state
            if not state.loaded:
                return
            if state.answered:
                self._practice_next()
            elif state.selection:
                self.controller.submit()
            else:
                self.set_status("请先选择答案（单选/判断点选即判，也可按 1~8 选择）")
        elif page == "exam" and self.controller.state.exam_view == "taking":
            exam = self.controller.state.exam
            if exam is None:
                return
            if self.controller.state.exam_index + 1 < exam.total:
                self.controller.exam_goto(self.controller.state.exam_index + 1)
            else:
                self.set_status("已是最后一题，按 F9 或点「交卷」提交")

    def _on_arrow(self, delta: int) -> None:
        if not self._shortcut_target_ok():
            return
        page = self.current_page()
        if page == "practice":
            if delta > 0:
                self._practice_next()
            else:
                self._practice_prev()
        elif page == "exam" and self.controller.state.exam_view == "taking":
            self.controller.exam_goto(self.controller.state.exam_index + delta)

    # ---------------------------------------------------------------- 原生按键兜底
    def keyPressEvent(self, event) -> None:  # noqa: N802
        """主窗口级按键兜底。

        ``QShortcut`` 依赖窗口处于 active 状态（无头/远程桌面/焦点被系统拿走时可能不触发），
        因此同时在主窗口上处理一次未被子控件消费的按键：未处理的按键事件会从焦点控件
        冒泡到父控件，最终到达这里。两处调用同一个处理器，不会重复执行——
        命中 QShortcut 时事件已被消费，不会再冒泡。
        """
        if self.handle_key(event.key(), event.modifiers()):
            event.accept()
            return
        super().keyPressEvent(event)

    def handle_key(self, key: int, modifiers: "Qt.KeyboardModifier" = Qt.NoModifier) -> bool:
        """把按键映射到具体动作；返回是否已处理（供快捷键与 keyPressEvent 共用）。"""
        if not self._shortcut_target_ok():
            return False
        if modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
            return False
        key_map = {
            Qt.Key_1: 0, Qt.Key_2: 1, Qt.Key_3: 2, Qt.Key_4: 3,
            Qt.Key_5: 4, Qt.Key_6: 5, Qt.Key_7: 6, Qt.Key_8: 7,
            Qt.Key_A: 0, Qt.Key_B: 1, Qt.Key_C: 2, Qt.Key_D: 3,
            Qt.Key_E: 4, Qt.Key_F: 5, Qt.Key_G: 6, Qt.Key_H: 7,
        }
        if key in key_map:
            self._select_index(key_map[key])
            return True
        if key in (Qt.Key_Return, Qt.Key_Enter):
            self._on_enter()
            return True
        if key == Qt.Key_Left:
            self._on_arrow(-1)
            return True
        if key == Qt.Key_Right:
            self._on_arrow(1)
            return True
        return False

    # ================================================================ 控制器接线
    def _connect_controller(self) -> None:
        self.controller.state_changed.connect(self._on_controller_state_changed)

    def _on_controller_state_changed(self) -> None:
        """只负责"考试页该显示哪个视图"，页面内容由各自的信号驱动刷新。"""
        view = self.controller.state.exam_view
        index = {"config": 0, "taking": 1, "result": 2}.get(view, 0)
        if self.exam_views.currentIndex() != index:
            self.exam_views.setCurrentIndex(index)

    def current_page(self) -> str:
        return PAGES[max(0, min(self.stack.currentIndex(), len(PAGES) - 1))]

    def set_page(self, key: str, persist: bool = True) -> None:
        if key not in PAGES:
            return
        index = PAGES.index(key)
        self.stack.setCurrentIndex(index)
        for name, button in self.nav_buttons.items():
            active = name == key
            button.setProperty("active", active)
            style = button.style()
            style.unpolish(button)
            style.polish(button)
        # 页面选择在关闭窗口时统一落盘（见 closeEvent）；初始化恢复时传 persist=False
        if persist:
            self.controller.settings.last_page = key

    # ---------------------------------------------------------------- 练习
    def _practice_next(self) -> None:
        self.controller.advance()

    def _practice_prev(self) -> None:
        self.controller.retreat()

    def _set_mode(self, mode: PracticeMode) -> None:
        self.set_page("practice")
        self.controller.set_mode(mode)

    def _set_scope(self, scope: Scope) -> None:
        self.set_page("practice")
        self.controller.set_scope(scope)

    def _refresh_practice(self) -> None:
        self.practice_page.refresh(self.controller.state)

    # ---------------------------------------------------------------- 考试
    def _show_exam_view(self, name: str) -> None:
        """切换考试三视图（配置 / 作答 / 成绩），并同步控制器记录的视图名。"""
        index = {"config": 0, "taking": 1, "result": 2}.get(name, 0)
        self.exam_views.setCurrentIndex(index)
        self.controller.state.exam_view = name
        # 视图切换后让作答页按最新状态重绘（只读/可用状态随之更新）
        self.exam_run_page.refresh(self.controller.state)

    def _refresh_exam(self) -> None:
        state = self.controller.state
        self.exam_setup_page.refresh(state)
        self.exam_run_page.refresh(state)
        self.exam_result_page.refresh(state)
        index = {"config": 0, "taking": 1, "result": 2}.get(state.exam_view, 0)
        if self.exam_views.currentIndex() != index:
            self.exam_views.setCurrentIndex(index)

    def _start_exam_at(self, index: int) -> None:
        self.set_page("exam")
        paper = self.controller.paper_at(int(index))
        if paper is None:
            notify(self, "提示", "请先在「模拟考试」页生成一轮试卷。")
            return
        self.controller.start_exam(paper)

    def _start_exam_selected(self) -> None:
        self._start_exam_at(self.exam_setup_page.selected_index())

    def _start_next_unused(self) -> None:
        self.set_page("exam")
        self.controller.start_next_unused_paper()

    def _exam_in_progress(self) -> bool:
        """当前是否有一场「未交卷且正在作答视图」的考试。

        F9 交卷既可能从菜单/按钮触发，也可能从练习页误触，这里统一判定：
        必须先有一场未交卷的考试，且当前视图是作答视图（或当前页就是模拟考试页）。
        """
        state = self.controller.state
        if state.exam is None or state.exam.submitted:
            return False
        return state.exam_view == "taking" or self.current_page() == "exam"

    def _submit_exam(self) -> None:
        state = self.controller.state
        if state.exam is not None and state.exam.submitted:
            self._show_exam_view("result")
            return
        if not self._exam_in_progress():
            notify(self, "提示", "当前没有进行中的模拟考试。")
            return
        self.set_page("exam")
        unattended = self.controller.unattended_count()
        if unattended and not confirm(
                self, "确认交卷",
                f"还有 {unattended} 题未作答，未答题按错误计分。\n确定交卷吗？"):
            return
        QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
        try:
            self.controller.submit_exam()
        finally:
            QApplication.restoreOverrideCursor()
        self._show_exam_view("result")

    # ---------------------------------------------------------------- 数据
    def _sync_chrome(self) -> None:
        state = self.controller.state
        if state.bank:
            name = Path(state.bank_path).stem
            self.bank_label.setText(name)
            self.stats_label.setText(self.controller.stats_line())
        else:
            self.bank_label.setText("（尚未导入题库）")
            self.stats_label.setText("用「文件 → 导入题库…」或把题库文件拖到窗口上开始")
        live = self.controller.stats()
        self.pill_done.set_value(str(live["done"]))
        self.pill_rate.set_value(f"{live['accuracy'] * 100:.0f}%" if live["attempts"] else "—")
        self.pill_book.set_value(str(live["wrong_book"]))
        if state.save_error:
            self.save_error_label.setText("⚠ 进度未能保存")
            self.save_error_label.setToolTip(state.save_error)
        else:
            self.save_error_label.setText("")
            self.save_error_label.setToolTip("")

    def set_status(self, text: str) -> None:
        self.status_label.setText(str(text))

    def _refresh_library(self) -> None:
        self.library_page.refresh(self.controller.state)
        self._sync_library_buttons()

    def _sync_library_buttons(self) -> None:
        """只有选中了题库条目时，「载入 / 移除」按钮才可用。"""
        page = self.library_page
        has_selection = bool(page.library_table.selectionModel().selectedRows())
        for button in (page.load_button, page.forget_button, page.forget_reset_button):
            if button.isEnabled() != has_selection:
                button.setEnabled(has_selection)

    # ================================================================ 题库操作
    def _choose_bank(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            self, "选择题库文件", "",
            "题库文件 (*.xlsx *.xlsm *.csv *.txt *.json *.docx *.docm *.pdf);;所有文件 (*.*)")
        if path:
            self._load_bank_path(path)

    def _load_bank_path(self, path: str) -> None:
        QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
        try:
            ok = self.controller.load_bank(path)
        finally:
            QApplication.restoreOverrideCursor()
        self._sync_chrome()
        self._refresh_library()
        if not ok:
            warn(self, "导入失败", self.status_label.text())

    def _scan_folder(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        folder = QFileDialog.getExistingDirectory(self, "选择存放题库的文件夹（会递归扫描）")
        if not folder:
            return
        found = self.controller.scan_folder(folder)
        self.library_page.refresh(self.controller.state)
        if not found:
            notify(self, "没有找到题库",
                   "该文件夹下没有找到受支持的题库文件。\n\n支持：" + "、".join(SUPPORTED_SUFFIXES))
        else:
            notify(self, "扫描完成",
                   f"共发现 {len(found)} 个题库文件，已加入列表（不会自动载入）。")

    def _show_bank_picker(self) -> None:
        dialog = BankPickerDialog(self.controller, self.theme, self)
        dialog.import_requested.connect(self._choose_bank)
        dialog.scan_requested.connect(self._scan_folder)
        dialog.load_requested.connect(self._load_bank_path)
        dialog.exec()
        self.library_page.refresh(self.controller.state)

    def _forget_entry(self, path: str) -> None:
        if confirm(self, "移除记录",
                   f"从题库列表移除这条记录吗？\n{path}\n\n"
                   "注意：只是不再显示在列表里，不会删除题库文件。"):
            self.controller.forget_library_entry(path)
            self.library_page.refresh(self.controller.state)

    def _forget_entry_with_progress(self, path: str) -> None:
        if not confirm(self, "移除记录并清空进度",
                       f"移除记录，并删除该题库保存的练习进度吗？\n{path}\n\n"
                       "练习记录、错题本与历史成绩都会清空，不可撤销；题库文件不会被删除。"):
            return
        cleaned = self.controller.forget_with_progress(path)
        self.library_page.refresh(self.controller.state)
        notify(self, "完成", f"已移除记录，并清理 {cleaned} 份进度文件。")

    def _open_progress_dir(self) -> None:
        path = self.controller.progress_dir
        try:
            path.mkdir(parents=True, exist_ok=True)
            if os.name == "nt":
                os.startfile(path)          # type: ignore[attr-defined]
            else:
                import subprocess

                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            warn(self, "无法打开", f"{path}\n{exc}")

    # ================================================================ 对话框
    def _show_wrong_book(self) -> None:
        if not self.controller.state.loaded:
            warn(self, "提示", "请先导入题库。")
            return
        dialog = WrongBookDialog(self.controller, self.theme, self)
        dialog.practice_wrong_requested.connect(self._practice_wrong)
        dialog.exec()
        self.practice_page.refresh(self.controller.state)
        self._sync_chrome()

    def _practice_wrong(self) -> None:
        self.set_page("practice")
        self.controller.set_scope(Scope.ALL)
        self.controller.set_mode(PracticeMode.WRONG)

    def _show_question_filter(self) -> None:
        if not self.controller.state.loaded:
            warn(self, "提示", "请先导入题库。")
            return
        dialog = QuestionFilterDialog(self.controller, self.theme, self)
        dialog.exec()
        self.practice_page.refresh(self.controller.state)
        self.exam_setup_page.refresh(self.controller.state)
        self._sync_chrome()

    def _show_progress_manager(self) -> None:
        dialog = ProgressDialog(self.controller, self.theme, self)
        dialog.exec()
        self.practice_page.refresh(self.controller.state)
        self.exam_setup_page.refresh(self.controller.state)
        self._sync_chrome()

    def _show_exam_history(self) -> None:
        if not self.controller.state.store:
            warn(self, "提示", "请先导入题库。")
            return
        ExamHistoryDialog(self.controller, self.theme, self).exec()

    def _reset_progress(self) -> None:
        if not self.controller.state.store:
            return
        name = self.controller.state.store.progress.bank_name
        if not confirm(self, "重置进度",
                       f"确定要清空「{name}」的全部练习记录吗？\n"
                       "（已练题数、错题本、正确率、历史成绩都会清空，不可撤销）"):
            return
        self.controller.reset_progress()

    def _show_help(self) -> None:
        HelpDialog(self.theme, HELP_TEXT, self).exec()

    def _show_about(self) -> None:
        text = (f"{__app_name__}  v{__version__}\n\n"
                "题库练习 + 模拟考试工具：实时判题、错题本、进度自动保留、\n"
                "按题型练习、按蓝图生成试卷并模拟考试。\n\n"
                "界面基于 Qt（PySide6）与 tkinter 双实现：\n"
                "· Qt 界面：现代卡片式布局、深浅主题、高 DPI\n"
                "· tkinter 界面：PySide6 不可用时的兼容回退\n\n"
                "全部计算在本机完成，不联网、不上传任何数据。")
        AboutDialog(self.theme, text, self).exec()

    # ================================================================ 主题
    def apply_theme(self, mode: str) -> None:
        self.theme_mode = mode if mode in theme_module.THEME_MODES else "system"
        app = QApplication.instance()
        if app is not None:
            self.theme = theme_module.apply_theme(app, self.theme_mode)
        else:
            self.theme = theme_for(self.theme_mode)
        self.controller.settings.theme = self.theme_mode
        self.controller.save_settings()
        index = self.theme_combo.findData(self.theme_mode)
        if index >= 0 and self.theme_combo.currentIndex() != index:
            self.theme_combo.blockSignals(True)
            self.theme_combo.setCurrentIndex(index)
            self.theme_combo.blockSignals(False)
        for page in (self.practice_page, self.exam_setup_page, self.exam_run_page,
                     self.exam_result_page, self.library_page):
            page.apply_theme(self.theme)

    # ================================================================ 拖放
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        urls = event.mimeData().urls() if event.mimeData().hasUrls() else []
        for url in urls:
            path = url.toLocalFile()
            if path and Path(path).suffix.lower() in SUPPORTED_SUFFIXES:
                event.acceptProposedAction()
                return
        event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path and Path(path).suffix.lower() in SUPPORTED_SUFFIXES:
                self._load_bank_path(path)
                event.acceptProposedAction()
                return
        event.ignore()

    # ================================================================ 关闭
    @property
    def window_geometry_text(self) -> str:
        """``WxH+X+Y`` 形式的窗口几何（写入配置，重启后恢复）。"""
        geo = self.geometry()
        return f"{geo.width()}x{geo.height()}+{geo.x()}+{geo.y()}"

    def apply_geometry_text(self, text: str) -> bool:
        """按 ``WxH+X+Y`` 恢复窗口几何；非法字符串返回 False。"""
        raw = (text or "").strip()
        if not raw:
            return False
        try:
            size, _, rest = raw.partition("+")
            width, _, height = size.lower().partition("x")
            pos = rest.split("+") if rest else []
            self.resize(QSize(int(width), int(height)))
            if len(pos) >= 2:
                self.move(QPoint(int(pos[0]), int(pos[1])))
            return True
        except (TypeError, ValueError):
            return False

    def _apply_legacy_geometry(self, text: str) -> bool:
        """兼容 tkinter 版写下的 ``WxH+X+Y``（Tk 的 geometry 字符串格式一致）。"""
        return self.apply_geometry_text(text)

    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            state = self.controller.state
            if state.session and not state.session.empty:
                state.session.save_position()
            self.controller.save_window_state(self.window_geometry_text, self.current_page())
        except Exception:
            pass
        super().closeEvent(event)
