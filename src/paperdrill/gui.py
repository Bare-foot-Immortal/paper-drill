# -*- coding: utf-8 -*-
"""刷题匠 PaperDrill —— 界面（tkinter/ttk）。

两个工作区（标签页）：

* **练习**：范围（整个题库 / 只练单选 / 只练多选 / 只练判断）× 模式（顺序 / 随机 /
  错题重练 / 只练未做）；单选/多选可分别设置是否打乱选项；点选即判、实时反馈。
* **模拟考试**：自定义每卷各题型数量 → 一轮覆盖题库全部题目（末卷不足时随机补题）
  → 选卷作答（**作答期间不给对错反馈**）→ 交卷评分 → 逐题解析与历史成绩。

练习与考试的作答都记入同一份进度文件，进度随题库保留。
"""
from __future__ import annotations

import os
import subprocess
import sys
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import __app_name__, __version__
from .bank_io import bank_stats, load_bank
from .config import AppSettings
from .models import QType
from .paper import GenerationError, generate_round, min_round_length
from .practice import (DEFAULT_SCORES, ExamResult, ExamSession, PracticeMode,
                       PracticeSession, Scope)
from .store import ProgressStore, progress_dir

HELP_TEXT = """【刷题匠 PaperDrill 使用说明】

一、准备题库
  支持 .xlsx / .xlsm / .csv / .txt / .json / .docx / .docm / .pdf。
  · Excel（推荐）：列头为 题型 | 题目标题 | 选项A | 选项B | 选项C | 选项D | … | 解析 | 答案
  · Word：表格型（同上列头）或段落文本型（题干一行、选项一行或分行、答案一行）
  · PDF：取文本层解析，扫描件（图片）无法识别
  · 题型填：单选题 / 多选题 / 判断题
  · 判断题不需要选项
  · 多选题答案写字母组合，例如 ABCD
  · 选项顺序不可打乱的题目，在答案后加「（定）」，例如：BC（定）
  · 段落型题库可以用章节标题标明题型，如「一、单项选择题」「二、多项选择题」「三、判断题」

──────────────────────────────────────────────
二、【练习】标签页
  1. 选择练习范围：整个题库 / 只练单选 / 只练多选 / 只练判断
  2. 选择练习模式：顺序练习 / 随机练习 / 错题重练 / 只练未做
     （范围与模式可以叠加，例如"只练判断题 + 错题重练"）
  3. 答题：
     · 单选题：点一下选项，立即判对错
     · 判断题：点「正确」或「错误」，立即判对错
     · 多选题：勾选若干项后点「提交答案」
     · 快捷键：1~8 或 A~H 选选项，Enter 提交/下一题，← → 上一题/下一题
  4. 选项打乱：单选、多选可分别勾选是否打乱；标注「（定）」的题目永不打乱。

──────────────────────────────────────────────
三、【模拟考试】标签页（真实模拟）
  1. 设置每张试卷的题型数量，例如 单选 20 / 多选 10 / 判断 10 → 每卷 40 题
  2. 一轮张数默认自动计算：
        轮长 N = max( 该题型题库量 ÷ 该题型每卷数量 向上取整 )
     例：题库 120 题、每卷 40 题 → 一轮 3 张，3 张出完题库每道题都出现过；
     某题型取尽时，从本轮已出现过的同题型题目中随机补足，保证每卷题量一致。
  3. 点「生成一轮试卷」→ 查看覆盖校验与每张卷子的题量明细
  4. 选择卷号（A 卷 / B 卷 …）→「开始模拟考试」
  5. 作答过程中**不会提示对错**，可自由跳题、改答案；做完点「交卷」
  6. 交卷后一次性给出：总分、正确数、错误数、未答数、正确率、各题型得分，
     并可逐题查看"你的作答 / 正确答案 / 解析"
  7. 考试成绩同样计入练习进度：已练题数、正确率、错题本都会同步更新

──────────────────────────────────────────────
四、进度自动保留
  每道题的作答记录会实时保存；再次打开同一题库会自动接着上次继续。
  · 题库增删题目、换目录、改文件名，只要题目内容没变，进度依然保留
  · 不同题库各自独立记录，互不干扰
  · 「练习 → 进度管理」可查看/重置各题库进度
  · 进度文件位置：%APPDATA%\\PaperDrill\\progress\\

五、错题本
  答错（练习或考试）的题自动进入错题本；答对后自动移出。
  「练习 → 错题本」可查看错题、一键只练错题、清空错题标记。

六、快捷键
  Ctrl+O 导入题库   Ctrl+W 错题本   Ctrl+P 进度管理   F1 使用说明
  F5 生成一轮试卷    F9 交卷        1~8/A~H 选项    Enter 提交/下一题
"""


class PaperDrillApp(tk.Tk):
    """主窗口。"""

    def __init__(self, initial_bank: str | None = None, settings: "AppSettings | None" = None,
                 settings_path: "Path | None" = None) -> None:
        super().__init__()
        self._settings_path = settings_path
        self.settings = settings if settings is not None else AppSettings.load(settings_path)

        self.bank = None                 # BankLoadResult
        self.store: ProgressStore | None = None
        self.session: PracticeSession | None = None
        self.round = None                # PaperRound
        self.exam: ExamSession | None = None
        self.exam_index = 0

        self._answer_widgets: list = []
        self._option_vars: dict = {}
        self._multi_vars: dict = {}
        self._answered = False
        self._auto_next_job = None
        self._exam_widgets: list = []
        self._exam_vars: dict = {}
        self._num_buttons: list = []

        self.title(f"{__app_name__} v{__version__} —— 题库练习与模拟考试（进度自动保留）")
        self.geometry(self.settings.window_geometry or "1120x820")
        self.minsize(980, 720)

        self._init_vars()
        self._build_menu()
        self._build_layout()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        bank = initial_bank or self.settings.bank_path
        if bank and Path(bank).exists():
            self.after(150, lambda: self._import_bank(bank))

    # ================================================================ 变量
    def _init_vars(self) -> None:
        s = self.settings
        self.bank_var = tk.StringVar(value=s.bank_path or "（尚未导入题库）")
        self.stats_var = tk.StringVar(value="导入题库后开始练习")
        self.scope_var = tk.StringVar(value=Scope.from_label(s.scope).label)
        self.mode_var = tk.StringVar(value=PracticeMode.from_label(s.mode).label)
        self.shuffle_single_var = tk.BooleanVar(value=bool(s.shuffle_single))
        self.shuffle_multiple_var = tk.BooleanVar(value=bool(s.shuffle_multiple))
        self.auto_next_var = tk.BooleanVar(value=bool(s.auto_next_on_correct))
        self.analysis_var = tk.BooleanVar(value=bool(s.show_analysis))
        self.pos_var = tk.StringVar(value="第 0 / 0 题")
        self.type_var = tk.StringVar(value="")
        self.state_var = tk.StringVar(value="")
        self.feedback_var = tk.StringVar(value="导入题库后，这里会显示判题结果")
        self.analysis_text_var = tk.StringVar(value="")
        self.footer_var = tk.StringVar(value="")
        self.progress_var = tk.DoubleVar(value=0.0)
        self.keys_hint_var = tk.StringVar(
            value="快捷键：1~8 / A~H 选项　Enter 提交或下一题　← → 上一题/下一题")
        self.status_var = tk.StringVar(value="就绪")

        # 试卷蓝图
        self.paper_single_var = tk.StringVar(value=str(s.paper_single))
        self.paper_multiple_var = tk.StringVar(value=str(s.paper_multiple))
        self.paper_judge_var = tk.StringVar(value=str(s.paper_judge))
        self.round_auto_var = tk.BooleanVar(value=bool(s.round_auto))
        self.round_length_var = tk.StringVar(value=str(s.round_length or 0))
        self.plan_total_var = tk.StringVar(value="")
        self.plan_hint_var = tk.StringVar(value="导入题库后自动计算覆盖所需张数")
        self.paper_pick_var = tk.StringVar(value="")
        self.cover_var = tk.StringVar(value="尚未生成试卷")
        self.score_single_var = tk.StringVar(value=f"{s.score_single:g}")
        self.score_multiple_var = tk.StringVar(value=f"{s.score_multiple:g}")
        self.score_judge_var = tk.StringVar(value=f"{s.score_judge:g}")
        self.record_exam_var = tk.BooleanVar(value=bool(s.record_exam_progress))

        # 考试
        self.exam_title_var = tk.StringVar(value="")
        self.exam_count_var = tk.StringVar(value="已答 0 / 0")
        self.exam_hint_var = tk.StringVar(
            value="作答期间不显示对错；快捷键：1~8 选项　Enter 下一题　← → 翻题　F9 交卷")

        for var in (self.paper_single_var, self.paper_multiple_var, self.paper_judge_var):
            var.trace_add("write", lambda *_: self._refresh_plan_hint())

    # ================================================================ 菜单
    def _build_menu(self) -> None:
        menubar = tk.Menu(self)
        m_file = tk.Menu(menubar, tearoff=0)
        m_file.add_command(label="导入题库…", accelerator="Ctrl+O", command=self._choose_bank)
        m_file.add_command(label="重新载入当前题库", command=self._reload_bank)
        m_file.add_separator()
        m_file.add_command(label="打开进度目录", command=self._open_progress_dir)
        m_file.add_separator()
        m_file.add_command(label="退出", command=self._on_close)
        menubar.add_cascade(label="文件", menu=m_file)

        m_prac = tk.Menu(menubar, tearoff=0)
        for mode in (PracticeMode.ORDER, PracticeMode.RANDOM, PracticeMode.WRONG, PracticeMode.FRESH):
            m_prac.add_command(label=mode.label, command=lambda m=mode: self._set_mode(m))
        m_prac.add_separator()
        for scope in (Scope.ALL, Scope.SINGLE, Scope.MULTIPLE, Scope.JUDGE):
            m_prac.add_command(label=scope.label, command=lambda s=scope: self._set_scope(s))
        m_prac.add_separator()
        m_prac.add_command(label="重新开始本轮（不清进度）", command=self._restart_round)
        m_prac.add_command(label="重置本题库进度…", command=self._reset_progress)
        m_prac.add_separator()
        m_prac.add_command(label="错题本…", accelerator="Ctrl+W", command=self._show_wrong_book)
        m_prac.add_command(label="进度管理…", accelerator="Ctrl+P", command=self._show_progress_manager)
        menubar.add_cascade(label="练习", menu=m_prac)

        m_exam = tk.Menu(menubar, tearoff=0)
        m_exam.add_command(label="生成一轮试卷", accelerator="F5", command=self._generate_round)
        m_exam.add_command(label="开始/继续模拟考试", command=self._start_exam_selected)
        m_exam.add_command(label="交卷", accelerator="F9", command=self._exam_submit)
        m_exam.add_separator()
        m_exam.add_command(label="历史成绩…", command=self._show_exam_history)
        menubar.add_cascade(label="模拟考试", menu=m_exam)

        m_help = tk.Menu(menubar, tearoff=0)
        m_help.add_command(label="使用说明", accelerator="F1", command=self._show_help)
        m_help.add_command(label="关于", command=self._show_about)
        menubar.add_cascade(label="帮助", menu=m_help)

        self.config(menu=menubar)
        # ---- 全局快捷键 ----
        # 用 bind_all 而非 bind：无论键盘焦点落在哪个子控件（选项、按钮、题号格）都能生效。
        # 回车同时绑定主键盘 <Return> 与小键盘 <KP_Enter>。
        for sequence in ("<Return>", "<KP_Enter>"):
            self.bind_all(sequence, self._on_enter_key, add="+")
        for sequence, handler in (("<Left>", self._on_left_key), ("<Right>", self._on_right_key)):
            self.bind_all(sequence, handler, add="+")
        self.bind_all("<Key>", self._on_key, add="+")
        for sequence, command in (("<Control-o>", self._choose_bank),
                                  ("<Control-w>", self._show_wrong_book),
                                  ("<Control-p>", self._show_progress_manager),
                                  ("<F1>", self._show_help),
                                  ("<F5>", self._generate_round),
                                  ("<F9>", self._exam_submit)):
            self.bind_all(sequence, lambda e, fn=command: (fn(), "break")[1], add="+")

    # ================================================================ 布局
    def _build_layout(self) -> None:
        root = ttk.Frame(self, padding=8)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=1)

        self._build_top(root).grid(row=0, column=0, sticky="ew")
        ttk.Separator(root, orient="horizontal").grid(row=1, column=0, sticky="ew", pady=6)

        self.notebook = ttk.Notebook(root)
        self.notebook.grid(row=2, column=0, sticky="nsew")
        self.practice_tab = ttk.Frame(self.notebook, padding=8)
        self.exam_tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(self.practice_tab, text="  练习  ")
        self.notebook.add(self.exam_tab, text="  模拟考试  ")

        self._build_practice_tab(self.practice_tab)
        self._build_exam_tab(self.exam_tab)

        bar = ttk.Frame(self, relief="sunken", padding=(8, 3))
        bar.pack(fill="x", side="bottom")
        ttk.Label(bar, textvariable=self.status_var, anchor="w").pack(side="left")

    def _build_top(self, parent) -> ttk.Widget:
        box = ttk.Frame(parent)
        box.columnconfigure(1, weight=1)
        row1 = ttk.Frame(box)
        row1.grid(row=0, column=0, sticky="ew")
        row1.columnconfigure(1, weight=1)
        ttk.Label(row1, text="题库：", font=("Microsoft YaHei", 10, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(row1, textvariable=self.bank_var).grid(row=0, column=1, sticky="w", padx=(2, 8))
        ttk.Button(row1, text="导入题库…", command=self._choose_bank).grid(row=0, column=2, padx=2)
        ttk.Button(row1, text="错题本", command=self._show_wrong_book).grid(row=0, column=3, padx=2)
        ttk.Button(row1, text="进度管理", command=self._show_progress_manager).grid(row=0, column=4, padx=2)
        ttk.Label(box, textvariable=self.stats_var, foreground="#046").grid(row=1, column=0, sticky="w", pady=(5, 0))
        return box

    # ---------------------------------------------------------------- 练习页
    def _build_practice_tab(self, parent) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        top = ttk.Frame(parent)
        top.grid(row=0, column=0, sticky="ew")

        row1 = ttk.Frame(top)
        row1.pack(fill="x")
        ttk.Label(row1, text="练习范围：").pack(side="left")
        for scope in (Scope.ALL, Scope.SINGLE, Scope.MULTIPLE, Scope.JUDGE):
            ttk.Radiobutton(row1, text=scope.label, value=scope.label, variable=self.scope_var,
                            command=lambda s=scope: self._set_scope(s)).pack(side="left", padx=(4, 10))
        ttk.Label(row1, text="　练习模式：").pack(side="left")
        for mode in (PracticeMode.ORDER, PracticeMode.RANDOM, PracticeMode.WRONG, PracticeMode.FRESH):
            ttk.Radiobutton(row1, text=mode.label, value=mode.label, variable=self.mode_var,
                            command=lambda m=mode: self._set_mode(m)).pack(side="left", padx=(4, 10))

        row2 = ttk.Frame(top)
        row2.pack(fill="x", pady=(6, 0))
        ttk.Label(row2, text="选项打乱：").pack(side="left")
        ttk.Checkbutton(row2, text="单选题打乱", variable=self.shuffle_single_var,
                        command=self._on_shuffle_toggle).pack(side="left", padx=(0, 10))
        ttk.Checkbutton(row2, text="多选题打乱", variable=self.shuffle_multiple_var,
                        command=self._on_shuffle_toggle).pack(side="left", padx=(0, 14))
        ttk.Checkbutton(row2, text="答对自动下一题", variable=self.auto_next_var,
                        command=self._save_settings).pack(side="left", padx=(0, 10))
        ttk.Checkbutton(row2, text="显示解析", variable=self.analysis_var,
                        command=self._refresh_feedback).pack(side="left", padx=(0, 10))
        ttk.Button(row2, text="重新开始本轮", command=self._restart_round).pack(side="right")

        card = ttk.LabelFrame(parent, text=" 题目 ", padding=10)
        card.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        card.columnconfigure(0, weight=1)
        card.rowconfigure(2, weight=1)

        head = ttk.Frame(card)
        head.grid(row=0, column=0, sticky="ew")
        ttk.Label(head, textvariable=self.pos_var, font=("Microsoft YaHei", 11, "bold")).pack(side="left")
        ttk.Label(head, textvariable=self.type_var, foreground="#a60").pack(side="left", padx=12)
        ttk.Label(head, textvariable=self.state_var, foreground="#0a5").pack(side="left")

        self.stem_label = ttk.Label(card, text="", wraplength=980, justify="left",
                                    font=("Microsoft YaHei", 12))
        self.stem_label.grid(row=1, column=0, sticky="ew", pady=(8, 6))

        self.options_frame = ttk.Frame(card)
        self.options_frame.grid(row=2, column=0, sticky="nsew")
        self.options_frame.columnconfigure(0, weight=1)

        actions = ttk.Frame(card)
        actions.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        self.submit_btn = ttk.Button(actions, text="提交答案", command=self._submit)
        self.submit_btn.pack(side="left")
        self.show_btn = ttk.Button(actions, text="不会，看答案", command=self._reveal)
        self.show_btn.pack(side="left", padx=8)
        ttk.Button(actions, text="下一题 ▶", command=lambda: self._navigate(1)).pack(side="right")
        ttk.Button(actions, text="◀ 上一题", command=lambda: self._navigate(-1)).pack(side="right", padx=8)

        bottom = ttk.Frame(parent)
        bottom.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        bottom.columnconfigure(0, weight=1)
        self.feedback_label = ttk.Label(bottom, textvariable=self.feedback_var,
                                        font=("Microsoft YaHei", 11, "bold"), foreground="#333",
                                        wraplength=1000, justify="left")
        self.feedback_label.pack(anchor="w")
        self.analysis_label = ttk.Label(bottom, textvariable=self.analysis_text_var, foreground="#555",
                                        wraplength=1000, justify="left")
        self.analysis_label.pack(anchor="w")

        bar = ttk.Frame(bottom)
        bar.pack(fill="x", pady=(6, 0))
        bar.columnconfigure(0, weight=1)
        ttk.Progressbar(bar, variable=self.progress_var, maximum=100.0).grid(row=0, column=0, sticky="ew")
        ttk.Label(bar, textvariable=self.footer_var).grid(row=0, column=1, sticky="e", padx=(12, 0))

        hint = ttk.Frame(bottom)
        hint.pack(fill="x", pady=(4, 0))
        ttk.Label(hint, textvariable=self.keys_hint_var, foreground="#888").pack(side="left")

    # ---------------------------------------------------------------- 考试页
    def _build_exam_tab(self, parent) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        self.exam_views: dict[str, ttk.Frame] = {}
        for name in ("setup", "taking", "result"):
            frame = ttk.Frame(parent)
            self.exam_views[name] = frame
        self._build_exam_setup(self.exam_views["setup"])
        self._build_exam_taking(self.exam_views["taking"])
        self._build_exam_result(self.exam_views["result"])
        self._show_exam_view("setup")

    def _show_exam_view(self, name: str) -> None:
        for key, frame in self.exam_views.items():
            if key == name:
                frame.grid(row=0, column=0, sticky="nsew")
            else:
                frame.grid_forget()

    # ---- 配置视图
    def _build_exam_setup(self, parent) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(3, weight=1)

        box = ttk.LabelFrame(parent, text=" ① 试卷蓝图（每张试卷的题目数量，可自定义各题型占比） ", padding=10)
        box.grid(row=0, column=0, sticky="ew")

        row = ttk.Frame(box)
        row.pack(fill="x")
        ttk.Label(row, text="单选题/卷").pack(side="left")
        ttk.Spinbox(row, from_=0, to=999, width=6, textvariable=self.paper_single_var).pack(side="left", padx=(4, 16))
        ttk.Label(row, text="多选题/卷").pack(side="left")
        ttk.Spinbox(row, from_=0, to=999, width=6, textvariable=self.paper_multiple_var).pack(side="left", padx=(4, 16))
        ttk.Label(row, text="判断题/卷").pack(side="left")
        ttk.Spinbox(row, from_=0, to=999, width=6, textvariable=self.paper_judge_var).pack(side="left", padx=(4, 16))
        ttk.Label(row, textvariable=self.plan_total_var, foreground="#036",
                  font=("Microsoft YaHei", 10, "bold")).pack(side="left")

        row2 = ttk.Frame(box)
        row2.pack(fill="x", pady=(8, 0))
        ttk.Label(row2, text="分值：单选").pack(side="left")
        ttk.Spinbox(row2, from_=0.5, to=100, increment=0.5, width=5,
                    textvariable=self.score_single_var).pack(side="left", padx=(4, 8))
        ttk.Label(row2, text="多选").pack(side="left")
        ttk.Spinbox(row2, from_=0.5, to=100, increment=0.5, width=5,
                    textvariable=self.score_multiple_var).pack(side="left", padx=(4, 8))
        ttk.Label(row2, text="判断").pack(side="left")
        ttk.Spinbox(row2, from_=0.5, to=100, increment=0.5, width=5,
                    textvariable=self.score_judge_var).pack(side="left", padx=(4, 16))
        ttk.Checkbutton(row2, text="考试成绩计入练习进度", variable=self.record_exam_var,
                        command=self._save_settings).pack(side="left")

        row3 = ttk.Frame(box)
        row3.pack(fill="x", pady=(8, 0))
        ttk.Label(row3, text="一轮张数：").pack(side="left")
        ttk.Radiobutton(row3, text="自动（覆盖题库所需）", variable=self.round_auto_var, value=True,
                        command=self._refresh_plan_hint).pack(side="left", padx=(4, 6))
        ttk.Radiobutton(row3, text="手动", variable=self.round_auto_var, value=False,
                        command=self._refresh_plan_hint).pack(side="left")
        ttk.Spinbox(row3, from_=1, to=999, width=6, textvariable=self.round_length_var).pack(side="left", padx=6)
        ttk.Button(row3, text="生成一轮试卷（F5）", command=self._generate_round).pack(side="left", padx=(16, 0))
        ttk.Label(row3, textvariable=self.plan_hint_var, foreground="#a60").pack(side="left", padx=(12, 0))

        cover = ttk.LabelFrame(parent, text=" ② 覆盖校验 ", padding=8)
        cover.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        ttk.Label(cover, textvariable=self.cover_var, wraplength=1000, justify="left").pack(anchor="w")

        pick = ttk.LabelFrame(parent, text=" ③ 选择试卷开始模拟考试 ", padding=8)
        pick.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        ttk.Label(pick, text="试卷：").pack(side="left")
        self.paper_combo = ttk.Combobox(pick, textvariable=self.paper_pick_var, state="readonly", width=42)
        self.paper_combo.pack(side="left", padx=6)
        ttk.Button(pick, text="开始模拟考试", command=self._start_exam_selected).pack(side="left", padx=8)
        ttk.Button(pick, text="历史成绩…", command=self._show_exam_history).pack(side="left", padx=4)
        ttk.Button(pick, text="自动取下一张未考卷", command=self._start_next_unused_paper).pack(side="left", padx=4)

        listbox = ttk.LabelFrame(parent, text=" 本轮试卷明细 ", padding=8)
        listbox.grid(row=3, column=0, sticky="nsew", pady=(8, 0))
        listbox.columnconfigure(0, weight=1)
        listbox.rowconfigure(0, weight=1)
        cols = ("label", "total", "single", "multiple", "judge", "reused")
        self.paper_tree = ttk.Treeview(listbox, columns=cols, show="headings", height=8)
        for col, title, width in (("label", "卷号", 90), ("total", "题量", 70),
                                  ("single", "单选", 70), ("multiple", "多选", 70),
                                  ("judge", "判断", 70), ("reused", "其中补题", 100)):
            self.paper_tree.heading(col, text=title)
            self.paper_tree.column(col, width=width, anchor="center")
        self.paper_tree.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(listbox, orient="vertical", command=self.paper_tree.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.paper_tree.configure(yscrollcommand=sb.set)
        self.paper_tree.bind("<<TreeviewSelect>>", lambda e: self._on_paper_row_select())

    # ---- 考试中视图
    def _build_exam_taking(self, parent) -> None:
        parent.columnconfigure(1, weight=1)
        parent.rowconfigure(0, weight=1)

        left = ttk.LabelFrame(parent, text=" 题号（蓝=已答） ", padding=6)
        left.grid(row=0, column=0, sticky="ns")
        self.num_frame = ttk.Frame(left)
        self.num_frame.pack(fill="both", expand=True)

        right = ttk.Frame(parent)
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        head = ttk.Frame(right)
        head.grid(row=0, column=0, sticky="ew")
        ttk.Label(head, textvariable=self.exam_title_var,
                  font=("Microsoft YaHei", 11, "bold")).pack(side="left")
        ttk.Label(head, textvariable=self.exam_count_var, foreground="#036").pack(side="right")
        ttk.Label(head, textvariable=self.exam_hint_var, foreground="#888").pack(side="left", padx=12)

        card = ttk.LabelFrame(right, text=" 试题 ", padding=10)
        card.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        card.columnconfigure(0, weight=1)
        card.rowconfigure(2, weight=1)
        self.exam_pos_var = tk.StringVar(value="")
        self.exam_type_var = tk.StringVar(value="")
        ttk.Label(card, textvariable=self.exam_pos_var, font=("Microsoft YaHei", 11, "bold")).grid(
            row=0, column=0, sticky="w")
        self.exam_stem = ttk.Label(card, text="", wraplength=700, justify="left",
                                   font=("Microsoft YaHei", 12))
        self.exam_stem.grid(row=1, column=0, sticky="ew", pady=(8, 6))
        self.exam_options = ttk.Frame(card)
        self.exam_options.grid(row=2, column=0, sticky="nsew")
        self.exam_options.columnconfigure(0, weight=1)
        ttk.Label(card, textvariable=self.exam_type_var, foreground="#a60").grid(row=3, column=0, sticky="w",
                                                                                pady=(8, 0))

        actions = ttk.Frame(right)
        actions.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(actions, text="◀ 上一题", command=lambda: self._exam_move(-1)).pack(side="left")
        ttk.Button(actions, text="下一题 ▶", command=lambda: self._exam_move(1)).pack(side="left", padx=8)
        ttk.Button(actions, text="清除本题作答", command=self._exam_clear).pack(side="left", padx=8)
        ttk.Button(actions, text="交卷（F9）", command=self._exam_submit).pack(side="right")

    # ---- 成绩视图
    def _build_exam_result(self, parent) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(3, weight=1)

        self.result_head_var = tk.StringVar(value="")
        head = ttk.LabelFrame(parent, text=" 成绩 ", padding=10)
        head.grid(row=0, column=0, sticky="ew")
        ttk.Label(head, textvariable=self.result_head_var, font=("Microsoft YaHei", 14, "bold"),
                  foreground="#0a7a34").pack(anchor="w")

        per = ttk.LabelFrame(parent, text=" 各题型得分 ", padding=8)
        per.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        cols = ("name", "correct", "total", "score", "full")
        self.per_tree = ttk.Treeview(per, columns=cols, show="headings", height=3)
        for col, title, width in (("name", "题型", 120), ("correct", "正确", 80), ("total", "题数", 80),
                                  ("score", "得分", 90), ("full", "满分", 90)):
            self.per_tree.heading(col, text=title)
            self.per_tree.column(col, width=width, anchor="center")
        self.per_tree.pack(fill="x")

        info = ttk.Frame(parent)
        info.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.result_detail_var = tk.StringVar(value="")
        ttk.Label(info, textvariable=self.result_detail_var, foreground="#333").pack(side="left")
        ttk.Button(info, text="返回试卷配置", command=lambda: self._show_exam_view("setup")).pack(side="right")
        ttk.Button(info, text="查看卷面（只读）", command=lambda: self._show_exam_view("taking")).pack(
            side="right", padx=8)

        detail = ttk.LabelFrame(parent, text=" 逐题明细（点击左侧行查看解析） ", padding=8)
        detail.grid(row=3, column=0, sticky="nsew", pady=(8, 0))
        detail.columnconfigure(0, weight=1)
        detail.columnconfigure(1, weight=1)
        detail.rowconfigure(0, weight=1)

        tree_wrap = ttk.Frame(detail)
        tree_wrap.grid(row=0, column=0, sticky="nsew")
        tree_wrap.columnconfigure(0, weight=1)
        tree_wrap.rowconfigure(0, weight=1)
        cols = ("number", "qtype", "result", "selected", "answer")
        self.detail_tree = ttk.Treeview(tree_wrap, columns=cols, show="headings", height=10)
        for col, title, width in (("number", "题号", 60), ("qtype", "题型", 80), ("result", "结果", 80),
                                  ("selected", "你的作答", 240), ("answer", "正确答案", 120)):
            self.detail_tree.heading(col, text=title)
            self.detail_tree.column(col, width=width, anchor="w")
        self.detail_tree.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.detail_tree.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.detail_tree.configure(yscrollcommand=sb.set)
        self.detail_tree.bind("<<TreeviewSelect>>", lambda e: self._on_detail_select())

        ana = ttk.Frame(detail)
        ana.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        ana.columnconfigure(0, weight=1)
        ana.rowconfigure(1, weight=1)
        ttk.Label(ana, text="题目与解析", font=("Microsoft YaHei", 10, "bold")).grid(row=0, column=0, sticky="w")
        self.analysis_box = tk.Text(ana, wrap="word", font=("Microsoft YaHei", 10), width=44)
        self.analysis_box.grid(row=1, column=0, sticky="nsew")
        self.analysis_box.configure(state="disabled")

    # ================================================================ 题库
    def _choose_bank(self) -> None:
        path = filedialog.askopenfilename(
            title="选择题库文件",
            filetypes=[("题库文件", "*.xlsx *.xlsm *.csv *.txt *.json *.docx *.docm *.pdf"),
                       ("Excel 题库", "*.xlsx *.xlsm"),
                       ("Word 题库", "*.docx *.docm"),
                       ("PDF 题库", "*.pdf"),
                       ("文本/JSON 题库", "*.csv *.txt *.json"),
                       ("所有文件", "*.*")])
        if path:
            self._import_bank(path)

    def _reload_bank(self) -> None:
        if self.bank and self.bank.source:
            self._import_bank(self.bank.source)

    def _import_bank(self, path: str) -> None:
        path = (path or "").strip().strip('"')
        if not path or not Path(path).exists():
            messagebox.showerror("题库不存在", f"找不到文件：\n{path}")
            return
        self.config(cursor="watch")
        self.update_idletasks()
        try:
            result = load_bank(path)
        except Exception as exc:
            self.config(cursor="")
            messagebox.showerror("导入失败", f"{exc}")
            return
        self.config(cursor="")
        if not result.questions:
            messagebox.showerror("题库为空", "没有解析到任何可用题目，请检查题库格式。")
            return

        self.bank = result
        self.bank_var.set(Path(path).name)
        self.store = ProgressStore.load_for(Path(path).stem, result.questions)
        try:
            self.store.save()
        except Exception:
            pass
        self._refresh_stats()

        self.settings.bank_path = path
        self._save_settings()

        self.session = PracticeSession(result.questions, self.store,
                                       mode=PracticeMode.from_label(self.mode_var.get()),
                                       qtype_filter=Scope.from_label(self.scope_var.get()).qtype,
                                       shuffle_single=self.shuffle_single_var.get(),
                                       shuffle_multiple=self.shuffle_multiple_var.get())
        restored = self.session.restore_position()
        self.mode_var.set(self.session.mode.label)
        self.scope_var.set(self._scope_of_qtype(self.session.qtype_filter).label)
        self.shuffle_single_var.set(self.session.shuffle_single)
        self.shuffle_multiple_var.set(self.session.shuffle_multiple)
        self.round = None
        self.exam = None
        self._clear_paper_tree()
        self.cover_var.set("尚未生成试卷")
        self._show_exam_view("setup")
        self._refresh_plan_hint()
        self._render_current()
        self._refresh_stats()
        self.set_status(f"已恢复上次练习进度（第 {self.session.position} 题）" if restored
                        else "题库导入成功，开始练习")
        if result.issues:
            detail = "\n".join(str(i) for i in result.issues[:15])
            more = f"\n…… 其余 {len(result.issues) - 15} 条省略" if len(result.issues) > 15 else ""
            messagebox.showwarning("部分行未能导入",
                                   f"以下 {len(result.issues)} 行未进入题库：\n\n{detail}{more}")
            self._restore_focus()

    def _refresh_stats(self) -> None:
        if not self.session:
            return
        s = self.session.stats()
        stats = bank_stats(self.session.questions)
        self.stats_var.set(
            f"共 {stats['total']} 题：单选 {stats['single']}、多选 {stats['multiple']}、"
            f"判断 {stats['judge']}；含固定顺序题 {stats['fixed']} 道"
            f"　｜　已练 {s['done']} 题　正确率 {s['accuracy'] * 100:.1f}%　错题 {s['wrong_book']} 道")

    def _open_progress_dir(self) -> None:
        path = progress_dir()
        try:
            path.mkdir(parents=True, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            messagebox.showerror("无法打开", f"{path}\n{exc}")

    # ================================================================ 练习
    @staticmethod
    def _scope_of_qtype(qtype: "QType | None") -> Scope:
        for s in Scope:
            if s.qtype is qtype:
                return s
        return Scope.ALL

    def _set_scope(self, scope: Scope) -> None:
        self.scope_var.set(scope.label)
        if not self.session:
            self._save_settings()
            return
        self._cancel_auto_next()
        self.session.rebuild(qtype_filter=scope.qtype)
        self._save_settings()
        if self.session.empty:
            self._render_empty(self.session.mode, scope)
            return
        self.session.save_position()
        self._render_current()

    def _set_mode(self, mode: PracticeMode) -> None:
        self.mode_var.set(mode.label)
        if not self.session:
            self._save_settings()
            return
        self._cancel_auto_next()
        self.session.rebuild(mode)
        self._save_settings()
        if self.session.empty:
            self._render_empty(mode, self._scope_of_qtype(self.session.qtype_filter))
            return
        self.session.save_position()
        self._render_current()

    def _on_shuffle_toggle(self) -> None:
        if self.session:
            self.session.shuffle_single = self.shuffle_single_var.get()
            self.session.shuffle_multiple = self.shuffle_multiple_var.get()
            self.session._items.clear()
            self._render_current()
        self._save_settings()

    def _restart_round(self) -> None:
        if not self.session:
            messagebox.showwarning("提示", "请先导入题库。")
            return
        self._cancel_auto_next()
        self.session.rebuild(self.session.mode)
        if self.session.empty:
            self._render_empty(self.session.mode, self._scope_of_qtype(self.session.qtype_filter))
            return
        self.session.save_position()
        self._render_current()
        self.set_status("已重新开始本轮（进度记录保留）")

    def _reset_progress(self) -> None:
        if not self.store:
            return
        if not messagebox.askyesno("重置进度",
                                   f"确定要清空「{self.store.progress.bank_name}」的全部练习记录吗？\n"
                                   "（已练题数、错题本、正确率、历史成绩都会清空，不可撤销）"):
            return
        self.store.reset()
        self.session = PracticeSession(self.bank.questions, self.store, mode=self.session.mode,
                                       qtype_filter=self.session.qtype_filter,
                                       shuffle_single=self.shuffle_single_var.get(),
                                       shuffle_multiple=self.shuffle_multiple_var.get())
        self._render_current()
        self._refresh_stats()
        self.set_status("进度已重置")

    def _navigate(self, delta: int) -> None:
        if not self.session or self.session.empty:
            return
        self._cancel_auto_next()
        moved = self.session.advance() if delta > 0 else self.session.retreat()
        if not moved:
            self.set_status("已经是最后一题" if delta > 0 else "已经是第一题")
            return
        self.session.save_position()
        self._render_current()

    # ---------------------------------------------------------------- 快捷键
    def _restore_focus(self, delay: int = 1) -> None:
        """把键盘焦点还给主窗口。

        对话框/Toplevel 关闭后，Tk 的焦点窗口可能指向已销毁的控件，
        导致键盘事件无处派发（表现为"快捷键突然全部失灵"），这里主动收回焦点。
        """
        try:
            self.after(delay, self.focus_set)
        except Exception:
            pass

    def _bind_dialog_focus(self, win: "tk.Toplevel") -> None:
        """对话框关闭时自动把焦点还给主窗口。"""
        def _on_destroy(event) -> None:
            if event.widget is win:
                self._restore_focus()

        win.bind("<Destroy>", _on_destroy, add="+")
    # 输入类控件：焦点在这些控件里时，按键属于"输入"，不得被练习/考试快捷键劫持
    _INPUT_CLASSES = frozenset({"TEntry", "TSpinbox", "Entry", "Spinbox", "Text",
                                "TCombobox", "Combobox", "TComboboxPopdown"})

    def _shortcut_allowed(self, event) -> bool:
        """判断该按键事件是否应交给本窗口的快捷键处理。

        排除两种情况：
        1. 事件来自其它窗口（弹窗 / 错题本 / 使用说明等 Toplevel），避免误触发主窗口；
        2. 事件发生在输入类控件上（题库路径、蓝图题量、分值等），避免打字被当成选答案。
        """
        widget = getattr(event, "widget", None)
        if widget is None:
            return False
        try:
            if widget.winfo_toplevel() is not self:
                return False
            return widget.winfo_class() not in self._INPUT_CLASSES
        except Exception:
            return False

    def _on_enter_key(self, event):
        """Enter（主键盘 / 小键盘）统一入口。"""
        if not self._shortcut_allowed(event):
            return None
        self._on_enter()
        return "break"

    def _on_left_key(self, event):
        if not self._shortcut_allowed(event):
            return None
        self._on_left()
        return None

    def _on_right_key(self, event):
        if not self._shortcut_allowed(event):
            return None
        self._on_right()
        return None

    def _on_left(self) -> None:
        if self.notebook.index("current") == 0:
            self._navigate(-1)
        else:
            self._exam_move(-1)

    def _on_right(self) -> None:
        if self.notebook.index("current") == 0:
            self._navigate(1)
        else:
            self._exam_move(1)

    def _on_enter(self) -> None:
        """Enter：练习页用于提交/下一题；考试页用于下一题。"""
        if self.notebook.index("current") == 0:
            self._practice_enter()
        else:
            self._exam_enter()

    def _practice_enter(self) -> None:
        if not self.session or self.session.empty:
            return
        if self._answered:
            self._navigate(1)                       # 已作答 → 下一题
            return
        item = self.session.current_item()
        if item is not None and self._selected():
            self._submit()                          # 已选择答案 → 提交
            return
        self.set_status("请先选择答案（单选/判断点选即判，也可按 1~8 选择）")

    def _exam_enter(self) -> None:
        if not self.exam:
            self.set_status("当前没有进行中的模拟考试")
            return
        if self.exam.submitted:
            return
        if self.exam_index + 1 < self.exam.total:
            self._exam_move(1)                      # 考试中 → 下一题
        else:
            self.set_status("已是最后一题，按 F9 交卷")

    def _on_key(self, event) -> None:
        """1~8 或 A~H 选择选项（练习页与考试页通用）。"""
        if not self._shortcut_allowed(event):
            return
        key = (event.char or "").strip().upper()
        if not key:
            return
        index = None
        if key.isdigit() and key != "0":
            index = int(key) - 1
        elif key.isalpha() and "A" <= key <= "Z":
            index = ord(key) - ord("A")
        if index is None:
            return
        if self.notebook.index("current") == 0:
            self._practice_key(index)
        else:
            self._exam_key(index)

    def _practice_key(self, index: int) -> None:
        if not self.session or self.session.empty or self._answered:
            return
        item = self.session.current_item()
        if item is None or index >= item.option_count:
            return
        letter = item.labels[index]
        if item.qtype is QType.MULTIPLE:
            var = self._multi_vars.get(letter)
            if var is not None:
                var.set(not var.get())          # 多选：勾选/取消，等 Enter 或按钮提交
        else:
            self._option_vars["choice"].set(letter)
            self._submit()                      # 单选/判断：与鼠标点选一致，立即判定

    # ---------------------------------------------------------------- 渲染
    def _clear_options(self) -> None:
        for widget in self._answer_widgets:
            widget.destroy()
        self._answer_widgets.clear()
        self._option_vars.clear()
        self._multi_vars.clear()

    def _render_empty(self, mode: PracticeMode, scope: Scope) -> None:
        self._cancel_auto_next()
        self._clear_options()
        self._answered = True
        self.pos_var.set("第 0 / 0 题")
        self.type_var.set(f"{scope.label} ｜ {mode.label}")
        self.state_var.set("")
        if mode is PracticeMode.WRONG:
            self.stem_label.configure(text=f"{scope.label}范围内没有答错的题目（错题本为空）。")
        elif mode is PracticeMode.FRESH:
            self.stem_label.configure(text=f"{scope.label}范围内的题目都已练过。")
        else:
            self.stem_label.configure(text="没有可练习的题目，请更换范围或模式。")
        self.feedback_var.set("可切换练习范围或模式继续。")
        self.analysis_text_var.set("")
        self.feedback_label.configure(foreground="#046")
        self._refresh_footer()

    def _render_current(self) -> None:
        if not self.session:
            return
        if self.session.empty:
            self._render_empty(self.session.mode, self._scope_of_qtype(self.session.qtype_filter))
            return
        self._cancel_auto_next()
        item = self.session.current_item()
        if item is None:
            return
        record = self.session.current_record()
        self._answered = False
        self._clear_options()

        self.pos_var.set(f"第 {self.session.position} / {self.session.total} 题")
        self.type_var.set(f"{item.qtype.value}　｜　{self._scope_of_qtype(self.session.qtype_filter).label}")
        self.state_var.set("此前已作答" if record.done else "")

        self.stem_label.configure(text=f"{self.session.position}. {item.stem.strip()}")

        # 选项控件与按钮状态始终按"当前题型的作答前状态"重置，避免上一题的残留状态
        if item.qtype is QType.MULTIPLE:
            self._build_multi_options(item)
            self.submit_btn.state(["!disabled"])
        else:
            self._build_single_options(item)
            self.submit_btn.state(["disabled"])      # 单选/判断点选即判，无需提交按钮
        self.show_btn.state(["!disabled"])

        self._refresh_footer()
        if record.done:
            self._show_replay(item, record)          # 已作答 → 可重做（不锁定、不剧透）
        else:
            self.feedback_var.set("请作答（单选/判断点选即判，多选勾选后提交）")
            self.analysis_text_var.set("")
            self.feedback_label.configure(foreground="#333")

    def _show_replay(self, item, record) -> None:
        """回看已作答的题目：**保持可作答**，只提示上次结果，不直接公布答案。

        这样「重新开始本轮」「错题重练」「回看上一题」都还能重新练习；
        想看答案可以点「不会，看答案」。
        """
        self._answered = False
        was_right = record.last == "right"
        mark = "✔ 上次回答正确" if was_right else "✘ 上次回答错误"
        times = f"，共作答 {record.attempts} 次" if record.attempts else ""
        self.feedback_var.set(f"{mark}{times}　可重新作答；点「不会，看答案」可直接看答案")
        self.feedback_label.configure(foreground="#0a7a34" if was_right else "#b3261e")
        self.analysis_text_var.set("")
        self.state_var.set("此前已作答，可重做")

    def _build_single_options(self, item) -> None:
        var = tk.StringVar(value="")
        self._option_vars["choice"] = var
        for label, text in item.options():
            rb = ttk.Radiobutton(self.options_frame, text=f"{label}. {text}", value=label,
                                 variable=var, command=self._submit)
            rb.grid(sticky="w", pady=3)
            self._answer_widgets.append(rb)

    def _build_multi_options(self, item) -> None:
        for label, text in item.options():
            var = tk.BooleanVar(value=False)
            self._multi_vars[label] = var
            cb = ttk.Checkbutton(self.options_frame, text=f"{label}. {text}", variable=var)
            cb.grid(sticky="w", pady=3)
            self._answer_widgets.append(cb)

    def _selected(self) -> object:
        item = self.session.current_item()
        if item.qtype is QType.MULTIPLE:
            return {letter for letter, var in self._multi_vars.items() if var.get()}
        return self._option_vars["choice"].get() or None

    def _show_answered(self, item, selected) -> None:
        """展示判题结果并锁定本题（仅用于"刚刚作答"的场景）。"""
        self._answered = True
        for widget in self._answer_widgets:
            widget.state(["disabled"])
        self.submit_btn.state(["disabled"])
        self.show_btn.state(["disabled"])
        if item.judge(selected):
            self.feedback_var.set(f"✔ 回答正确！正确答案：{item.answer_display()}")
            self.feedback_label.configure(foreground="#0a7a34")
        else:
            self.feedback_var.set(
                f"✘ 回答错误。你的作答：{item.selected_text(selected)}　｜　正确答案：{item.answer_display()}")
            self.feedback_label.configure(foreground="#b3261e")
        analysis = item.analysis if (self.analysis_var.get() and item.analysis) else ""
        self.analysis_text_var.set(f"解析：{analysis}" if analysis else "")

    def _submit(self) -> None:
        if not self.session or self.session.empty or self._answered:
            return
        item = self.session.current_item()
        selected = self._selected()
        if item.qtype is QType.MULTIPLE:
            empty = not selected
        else:
            empty = selected is None
        if empty:
            messagebox.showinfo("提示", "请至少勾选一个选项。" if item.qtype is QType.MULTIPLE
                                else "请先选择答案。")
            return
        result = self.session.submit(selected)
        self._show_answered(item, selected)          # 统一结果展示 + 锁定本题
        if result.correct:
            self.state_var.set("已订正 ✔" if result.is_repeat else "")
        else:
            self.state_var.set("已加入错题本")

        self.session.save_position()
        self._refresh_footer()
        self._refresh_stats()
        if result.correct and self.auto_next_var.get():
            self._auto_next_job = self.after(self.settings.auto_next_delay_ms, self._auto_next)

    def _auto_next(self) -> None:
        self._auto_next_job = None
        if self.session and not self.session.empty:
            if self.session.advance():
                self.session.save_position()
                self._render_current()
            else:
                self.set_status("本轮已完成 ✔ 可切换「错题重练」或去「模拟考试」检验")

    def _cancel_auto_next(self) -> None:
        if self._auto_next_job is not None:
            try:
                self.after_cancel(self._auto_next_job)
            except Exception:
                pass
            self._auto_next_job = None

    def _reveal(self) -> None:
        if not self.session or self.session.empty:
            return
        item = self.session.current_item()
        self._answered = True
        for widget in self._answer_widgets:
            widget.state(["disabled"])
        self.feedback_var.set(f"正确答案：{item.answer_display()}（已跳过作答）")
        self.feedback_label.configure(foreground="#a60")
        analysis = item.analysis if (self.analysis_var.get() and item.analysis) else ""
        self.analysis_text_var.set(f"解析：{analysis}" if analysis else "")
        self.show_btn.state(["disabled"])
        self.submit_btn.state(["disabled"])

    def _refresh_feedback(self) -> None:
        if self.session and not self.session.empty and self._answered:
            item = self.session.current_item()
            analysis = item.analysis if (self.analysis_var.get() and item.analysis) else ""
            self.analysis_text_var.set(f"解析：{analysis}" if analysis else "")
        self._save_settings()

    def _refresh_footer(self) -> None:
        if not self.session:
            self.footer_var.set("")
            return
        s = self.session.stats()
        scoped = self.session.scope_stats()
        self.footer_var.set(
            f"本范围 {scoped['done']}/{scoped['total']}　｜　全库 ✔ {s['right']} ✘ {s['wrong']}　"
            f"错题 {s['wrong_book']}　已练 {s['done']}/{s['total']}")
        self.progress_var.set(scoped["done_rate"] * 100.0)

    # ================================================================ 试卷
    def _plan_values(self) -> tuple[int, int, int]:
        def _int(var, default=0):
            try:
                return max(0, int(str(var.get()).strip()))
            except (ValueError, TypeError):
                return default

        return _int(self.paper_single_var, 20), _int(self.paper_multiple_var, 10), _int(self.paper_judge_var, 10)

    def _scores(self) -> dict:
        def _f(var, default):
            try:
                return max(0.0, float(str(var.get()).strip()))
            except (ValueError, TypeError):
                return default

        return {"single": _f(self.score_single_var, 1.0),
                "multiple": _f(self.score_multiple_var, 2.0),
                "judge": _f(self.score_judge_var, 1.0)}

    def _refresh_plan_hint(self) -> None:
        from .paper import PaperBlueprint

        bp = PaperBlueprint(*self._plan_values())
        full = bp.single * self._scores()["single"] + bp.multiple * self._scores()["multiple"] \
            + bp.judge * self._scores()["judge"]
        self.plan_total_var.set(f"→ 每卷合计 {bp.total} 题，满分 {full:g} 分")
        if not self.bank or not self.bank.questions or bp.total <= 0:
            self.plan_hint_var.set("导入题库并设置题量后自动计算覆盖所需张数")
            return
        try:
            n = min_round_length(self.bank.questions, bp)
        except Exception:
            self.plan_hint_var.set("")
            return
        stats = bank_stats(self.bank.questions)
        detail = []
        if bp.single > 0:
            detail.append(f"单选 {stats['single']}÷{bp.single}={-(-stats['single'] // bp.single)}张")
        if bp.multiple > 0:
            detail.append(f"多选 {stats['multiple']}÷{bp.multiple}={-(-stats['multiple'] // bp.multiple)}张")
        if bp.judge > 0:
            detail.append(f"判断 {stats['judge']}÷{bp.judge}={-(-stats['judge'] // bp.judge)}张")
        self.plan_hint_var.set(f"覆盖题库全部题目需 {n} 张/轮（" + "，".join(detail) + "）")
        if not self.round_auto_var.get():
            try:
                if int(self.round_length_var.get()) <= 0:
                    self.round_length_var.set(str(n))
            except ValueError:
                self.round_length_var.set(str(n))

    def _clear_paper_tree(self) -> None:
        if hasattr(self, "paper_tree"):
            self.paper_tree.delete(*self.paper_tree.get_children())

    def _generate_round(self) -> None:
        if not self.bank or not self.bank.questions:
            messagebox.showwarning("提示", "请先导入题库。")
            return
        from .paper import PaperBlueprint

        bp = PaperBlueprint(*self._plan_values())
        if bp.total <= 0:
            messagebox.showwarning("提示", "请至少为一种题型设置每卷数量。")
            return
        round_length = None
        if not self.round_auto_var.get():
            try:
                round_length = int(str(self.round_length_var.get()).strip())
            except ValueError:
                round_length = None
        self.config(cursor="watch")
        self.update_idletasks()
        try:
            rnd = generate_round(self.bank.questions, bp, round_length=round_length)
        except GenerationError as exc:
            self.config(cursor="")
            messagebox.showerror("无法生成试卷", str(exc))
            return
        except Exception as exc:
            self.config(cursor="")
            messagebox.showerror("生成失败", f"{exc}\n\n{traceback.format_exc(limit=3)}")
            return
        self.config(cursor="")
        self.round = rnd

        text = "✔ " + rnd.summary()
        parts = []
        for key, (seen, total) in rnd.coverage.items():
            name = {"single": "单选", "multiple": "多选", "judge": "判断"}.get(key, key)
            parts.append(f"{name} {seen}/{total}")
        text += "（" + "，".join(parts) + f"）　随机种子 {rnd.seed}"
        if rnd.warnings:
            text += "　⚠ " + "；".join(rnd.warnings)
        self.cover_var.set(text)

        self._clear_paper_tree()
        for paper in rnd.papers:
            self.paper_tree.insert("", "end", iid=paper.label, values=(
                f"{paper.label}卷", paper.total, paper.count_of(QType.SINGLE),
                paper.count_of(QType.MULTIPLE), paper.count_of(QType.JUDGE), paper.reused_count))
        labels = [f"第 {p.seq} 张（{p.label}卷，共 {p.total} 题）" for p in rnd.papers]
        self.paper_combo["values"] = labels
        if labels:
            self.paper_pick_var.set(labels[0])
            self.paper_tree.selection_set(rnd.papers[0].label)
        self._save_settings()
        self.set_status(f"已生成一轮 {rnd.paper_count} 张试卷；" +
                        ("覆盖完整 ✔" if rnd.coverage_ok else "覆盖不完整，请调大一轮张数"))
        self._show_exam_view("setup")

    def _on_paper_row_select(self) -> None:
        sel = self.paper_tree.selection()
        if not sel or not self.round:
            return
        label = sel[0]
        for i, paper in enumerate(self.round.papers):
            if paper.label == label:
                if i < len(self.paper_combo["values"]):
                    self.paper_pick_var.set(self.paper_combo["values"][i])
                break

    def _paper_by_selection(self):
        if not self.round:
            return None
        idx = self.paper_combo.current()
        if idx < 0 or idx >= len(self.round.papers):
            idx = 0
        return self.round.papers[idx] if self.round.papers else None

    def _start_exam_selected(self) -> None:
        if not self.round:
            messagebox.showinfo("提示", "请先在「模拟考试」页生成一轮试卷。")
            return
        paper = self._paper_by_selection()
        if paper is None:
            return
        self._start_exam(paper)

    def _start_next_unused_paper(self) -> None:
        if not self.round:
            messagebox.showinfo("提示", "请先生成一轮试卷。")
            return
        used = {e.get("paper_label") for e in (self.store.exam_history() if self.store else [])}
        for paper in self.round.papers:
            if paper.label not in used:
                self._start_exam(paper)
                return
        messagebox.showinfo("提示", "本轮所有试卷都已考过，可重新生成一轮。")

    def _start_exam(self, paper) -> None:
        if not self.store:
            return
        self.exam = ExamSession(paper, self.store,
                                shuffle_single=self.shuffle_single_var.get(),
                                shuffle_multiple=self.shuffle_multiple_var.get(),
                                scores=self._scores(),
                                record_progress=self.record_exam_var.get())
        self.exam_index = 0
        self.exam_title_var.set(f"{paper.label}卷　共 {paper.total} 题　"
                                f"满分 {self.exam.full_score:g} 分")
        self._build_number_grid(paper)
        self._show_exam_view("taking")
        self.notebook.select(1)          # 从菜单启动时自动切到「模拟考试」页
        self._render_exam_question()
        self.set_status(f"{paper.label}卷模拟考试进行中（作答期间不显示对错）")

    def _build_number_grid(self, paper) -> None:
        for widget in self.num_frame.winfo_children():
            widget.destroy()
        self._num_buttons = []
        cols = 5
        for i in range(paper.total):
            btn = tk.Button(self.num_frame, text=str(i + 1), width=3, relief="raised",
                            bg="#f0f0f0", command=lambda k=i: self._exam_goto(k))
            btn.grid(row=i // cols, column=i % cols, padx=1, pady=1)
            self._num_buttons.append(btn)

    def _refresh_number_grid(self) -> None:
        if not self.exam:
            return
        for i, btn in enumerate(self._num_buttons):
            if i == self.exam_index:
                btn.configure(bg="#ffe08a", relief="sunken")
            elif self.exam.answered(i):
                btn.configure(bg="#cfe8ff", relief="raised")
            else:
                btn.configure(bg="#f0f0f0", relief="raised")

    def _exam_goto(self, index: int) -> None:
        if not self.exam:
            return
        self.exam_index = max(0, min(index, self.exam.total - 1))
        self._render_exam_question()

    def _exam_move(self, delta: int) -> None:
        if not self.exam:
            return
        self._exam_goto(self.exam_index + delta)

    def _render_exam_question(self) -> None:
        if not self.exam:
            return
        for widget in self._exam_widgets:
            widget.destroy()
        self._exam_widgets.clear()
        self._exam_vars.clear()
        item = self.exam.item(self.exam_index)
        selected = self.exam.answers.get(self.exam_index, set())

        self.exam_pos_var.set(f"第 {self.exam_index + 1} / {self.exam.total} 题")
        self.exam_type_var.set(item.qtype.value +
                               ("　（多选题，选好后可直接下一题）" if item.qtype is QType.MULTIPLE else ""))
        self.exam_stem.configure(text=f"{self.exam_index + 1}. {item.stem.strip()}")

        if item.qtype is QType.MULTIPLE:
            for label, text in item.options():
                var = tk.BooleanVar(value=(label in selected))
                self._exam_vars[label] = var
                cb = ttk.Checkbutton(self.exam_options, text=f"{label}. {text}", variable=var,
                                     command=lambda lab=label: self._exam_toggle(lab))
                cb.grid(sticky="w", pady=3)
                self._exam_widgets.append(cb)
        else:
            var = tk.StringVar(value=(sorted(selected)[0] if selected else ""))
            self._exam_vars["choice"] = var
            for label, text in item.options():
                rb = ttk.Radiobutton(self.exam_options, text=f"{label}. {text}", value=label,
                                     variable=var, command=lambda lab=label: self._exam_pick(lab))
                rb.grid(sticky="w", pady=3)
                self._exam_widgets.append(rb)

        self.exam_count_var.set(f"已答 {self.exam.answered_count} / {self.exam.total}")
        self._refresh_number_grid()

    def _exam_pick(self, letter: str) -> None:
        if not self.exam or self.exam.submitted:
            return
        self.exam.set_answer(self.exam_index, {letter})
        self.exam_count_var.set(f"已答 {self.exam.answered_count} / {self.exam.total}")
        self._refresh_number_grid()

    def _exam_toggle(self, letter: str) -> None:
        if not self.exam or self.exam.submitted:
            return
        self.exam.toggle(self.exam_index, letter)
        self.exam_count_var.set(f"已答 {self.exam.answered_count} / {self.exam.total}")
        self._refresh_number_grid()

    def _exam_clear(self) -> None:
        if not self.exam or self.exam.submitted:
            return
        self.exam.clear_answer(self.exam_index)
        self._render_exam_question()

    def _exam_key(self, index: int) -> None:
        if not self.exam or self.exam.submitted:
            return
        item = self.exam.item(self.exam_index)
        if index >= item.option_count:
            return
        letter = item.labels[index]
        if item.qtype is QType.MULTIPLE:
            var = self._exam_vars.get(letter)
            if var is not None:
                var.set(not var.get())
            self._exam_toggle(letter)
        else:
            var = self._exam_vars.get("choice")
            if var is not None:
                var.set(letter)
            self._exam_pick(letter)

    def _exam_submit(self) -> None:
        if self.notebook.index("current") != 1:
            return
        if not self.exam:
            messagebox.showinfo("提示", "当前没有进行中的模拟考试。")
            return
        if self.exam.submitted:
            self._show_exam_view("result")
            return
        unanswered = self.exam.total - self.exam.answered_count
        if unanswered and not messagebox.askyesno(
                "确认交卷", f"还有 {unanswered} 题未作答，未答题按错误计分。\n确定交卷吗？"):
            self._restore_focus()
            return
        self.config(cursor="watch")
        self.update_idletasks()
        try:
            result = self.exam.submit()
        except Exception as exc:
            self.config(cursor="")
            messagebox.showerror("交卷失败", f"{exc}\n\n{traceback.format_exc(limit=3)}")
            return
        self.config(cursor="")
        self._render_exam_result(result)
        self._show_exam_view("result")
        # 交卷后考试页转为只读，避免选项显示状态与记录的答案不一致
        for widget in self._exam_widgets:
            try:
                widget.state(["disabled"])
            except Exception:
                pass
        self._refresh_stats()
        if self.session:
            self._refresh_practice_view()      # 让错题/未做队列反映考试结果，同时保住练习位置
            self._refresh_footer()
        self.settings.last_paper_label = result.paper_label
        self._save_settings()
        self.set_status(f"交卷完成：{result.summary()}")

    def _render_exam_result(self, result: ExamResult) -> None:
        self.result_head_var.set(
            f"{result.paper_label}卷　得分 {result.score:g} / {result.full_score:g} 分"
            f"（{result.accuracy * 100:.1f}%）")
        self.result_detail_var.set(
            f"正确 {result.correct} 题　错误 {result.wrong} 题　未答 {result.unanswered} 题　"
            f"共 {result.total} 题　｜　交卷时间 {result.ts}")
        self.per_tree.delete(*self.per_tree.get_children())
        for key in ("single", "multiple", "judge"):
            data = result.per_type.get(key)
            if not data:
                continue
            self.per_tree.insert("", "end", values=(data["name"], f"{data['correct']}/{data['total']}",
                                                    data["total"], f"{data['score']:g}",
                                                    f"{data['full']:g}"))
        self.detail_tree.delete(*self.detail_tree.get_children())
        for d in result.details:
            mark = "✔ 正确" if d["correct"] else ("— 未答" if d["unanswered"] else "✘ 错误")
            self.detail_tree.insert("", "end", iid=str(d["number"]),
                                    values=(d["number"], d["qtype"], mark,
                                            d["selected"][:60], d["answer"]))
        self._analysis_cache = {str(d["number"]): d for d in result.details}
        self._set_analysis("（点击左侧任意一行查看该题的题干与解析）")

    def _set_analysis(self, text: str) -> None:
        self.analysis_box.configure(state="normal")
        self.analysis_box.delete("1.0", "end")
        self.analysis_box.insert("1.0", text)
        self.analysis_box.configure(state="disabled")

    def _on_detail_select(self) -> None:
        sel = self.detail_tree.selection()
        if not sel:
            return
        d = getattr(self, "_analysis_cache", {}).get(sel[0])
        if not d:
            return
        lines = [f"{d['number']}. {d['stem']}", "", f"题型：{d['qtype']}",
                 f"你的作答：{d['selected']}", f"正确答案：{d['answer']} {d['answer_text']}",
                 f"结果：{'正确' if d['correct'] else ('未作答' if d['unanswered'] else '错误')}"]
        if d.get("analysis"):
            lines += ["", f"解析：{d['analysis']}"]
        self._set_analysis("\n".join(lines))

    def _show_exam_history(self) -> None:
        if not self.store:
            messagebox.showwarning("提示", "请先导入题库。")
            return
        win = tk.Toplevel(self)
        win.title("历史成绩")
        win.geometry("760x420")
        win.transient(self)
        self._bind_dialog_focus(win)
        ttk.Label(win, text=f"「{self.store.progress.bank_name}」的模拟考试成绩（最近 30 次）",
                  padding=(10, 8)).pack(anchor="w")
        cols = ("ts", "label", "score", "correct", "wrong", "unanswered", "accuracy")
        tree = ttk.Treeview(win, columns=cols, show="headings", height=14)
        for col, title, width in (("ts", "时间", 150), ("label", "卷", 50), ("score", "得分", 90),
                                  ("correct", "正确", 60), ("wrong", "错误", 60),
                                  ("unanswered", "未答", 60), ("accuracy", "正确率", 80)):
            tree.heading(col, text=title)
            tree.column(col, width=width, anchor="center")
        tree.pack(fill="both", expand=True, padx=10)
        for rec in self.store.exam_history():
            tree.insert("", "end", values=(
                rec.get("ts", ""), rec.get("paper_label", ""),
                f"{rec.get('score', 0):g}/{rec.get('full_score', 0):g}",
                rec.get("correct", 0), rec.get("wrong", 0), rec.get("unanswered", 0),
                f"{float(rec.get('accuracy', 0)) * 100:.1f}%"))
        ttk.Button(win, text="关闭", command=win.destroy).pack(pady=8)

    # ================================================================ 错题本
    def _show_wrong_book(self) -> None:
        if not self.session:
            messagebox.showwarning("提示", "请先导入题库。")
            return
        wrong = [q for q in self.session.questions if self.store.record_of(q).in_wrong_book]
        win = tk.Toplevel(self)
        win.title(f"错题本（{len(wrong)} 道）")
        win.geometry("900x620")
        win.transient(self)
        self._bind_dialog_focus(win)

        head = ttk.Frame(win, padding=(10, 8))
        head.pack(fill="x")
        ttk.Label(head, text=f"当前错题 {len(wrong)} 道　（答对后自动移出）",
                  font=("Microsoft YaHei", 11, "bold")).pack(side="left")

        wrap = ttk.Frame(win, padding=(10, 0, 10, 6))
        wrap.pack(fill="both", expand=True)
        text = tk.Text(wrap, wrap="word", font=("Microsoft YaHei", 10))
        text.pack(fill="both", expand=True)
        for i, q in enumerate(wrong, start=1):
            text.insert("end", f"{i}. {q.stem}\n")
            if q.qtype is not QType.JUDGE:
                for letter, opt in zip("ABCDEFGH", q.options):
                    text.insert("end", f"    {letter}. {opt}\n")
            ans = q.answer_display + ("（定）" if q.fixed_order else "")
            text.insert("end", f"    ✔ 正确答案：{ans}\n")
            if q.analysis:
                text.insert("end", f"    解析：{q.analysis}\n")
            text.insert("end", "\n")
        if not wrong:
            text.insert("end", "（暂无错题）\n")
        text.configure(state="disabled")

        btns = ttk.Frame(win, padding=(10, 6, 10, 10))
        btns.pack(fill="x")
        ttk.Button(btns, text="只练错题", command=lambda: (
            win.destroy(), self.notebook.select(0), self._set_scope(Scope.ALL),
            self._set_mode(PracticeMode.WRONG))).pack(side="left")
        ttk.Button(btns, text="清空错题标记", command=lambda: self._clear_wrong(win)).pack(side="left", padx=8)
        ttk.Button(btns, text="关闭", command=win.destroy).pack(side="right")

    def _refresh_practice_view(self) -> None:
        """按当前模式/范围重建练习队列并刷新界面，尽量停留在原来那道题上。"""
        if not self.session:
            return
        current = self.session.current_question()
        fingerprint = current.fingerprint if current is not None else ""
        self.session.rebuild(self.session.mode)
        if fingerprint:
            self.session.goto_question_fp(fingerprint)
        if self.session.empty:
            self._render_empty(self.session.mode, self._scope_of_qtype(self.session.qtype_filter))
            return
        self.session.save_position()
        self._render_current()

    def _do_clear_wrong(self) -> int:
        """清空错题标记（保留历史统计），并刷新练习队列。返回清理条数。"""
        if not self.store or not self.session:
            return 0
        count = self.store.progress.clear_wrong_book(self.session.questions)
        self.store.save()
        self._refresh_practice_view()          # 错题重练队列需同步刷新
        self._refresh_footer()
        self._refresh_stats()
        return count

    def _clear_wrong(self, win: tk.Toplevel) -> None:
        if not messagebox.askyesno("清空错题本", "将把所有题目移出错题本（历史统计保留），确定吗？"):
            return
        count = self._do_clear_wrong()
        win.destroy()
        messagebox.showinfo("完成", f"已清空 {count} 道错题标记。")

    # ================================================================ 进度管理
    def _show_progress_manager(self) -> None:
        win = tk.Toplevel(self)
        win.title("进度管理")
        win.geometry("900x480")
        win.transient(self)
        self._bind_dialog_focus(win)
        ttk.Label(win, text=f"进度目录：{progress_dir()}", padding=(10, 8)).pack(anchor="w")

        cols = ("name", "total", "done", "accuracy", "wrong", "exams", "updated")
        tree = ttk.Treeview(win, columns=cols, show="headings", height=13)
        for col, title, width in (("name", "题库", 220), ("total", "总题数", 70), ("done", "已练", 60),
                                  ("accuracy", "正确率", 80), ("wrong", "错题", 60),
                                  ("exams", "考试次数", 80), ("updated", "最后更新", 150)):
            tree.heading(col, text=title)
            tree.column(col, width=width, anchor="w")
        tree.pack(fill="both", expand=True, padx=10)

        def reload_list() -> None:
            tree.delete(*tree.get_children())
            for row in ProgressStore.list_all():
                tree.insert("", "end", iid=row["key"], values=(
                    row["name"], row["total"] or "—", row["done"] or "—",
                    f"{row['accuracy'] * 100:.1f}%" if row.get("done") else "—",
                    row.get("wrong_book", 0), row.get("exams", 0), row["updated"] or "—"))

        reload_list()

        btns = ttk.Frame(win, padding=(10, 8))
        btns.pack(fill="x")

        def reset_selected() -> None:
            sel = tree.selection()
            if not sel:
                messagebox.showinfo("提示", "请先在列表中选择一个题库。")
                return
            key = sel[0]
            if not messagebox.askyesno("重置进度", "确定清空该题库的全部练习记录与成绩吗？此操作不可撤销。"):
                return
            if self.store and self.store.progress.bank_key == key:
                self._reset_progress()
            else:
                ProgressStore.delete_by_key(key)
            reload_list()

        ttk.Button(btns, text="重置选中题库进度", command=reset_selected).pack(side="left")
        ttk.Button(btns, text="关闭", command=win.destroy).pack(side="right")

    # ================================================================ 设置/杂项
    def _save_settings(self) -> None:
        s = self.settings
        s.mode = PracticeMode.from_label(self.mode_var.get()).value
        s.scope = Scope.from_label(self.scope_var.get()).value
        s.shuffle_single = bool(self.shuffle_single_var.get())
        s.shuffle_multiple = bool(self.shuffle_multiple_var.get())
        s.auto_next_on_correct = bool(self.auto_next_var.get())
        s.show_analysis = bool(self.analysis_var.get())
        s.record_exam_progress = bool(self.record_exam_var.get())
        s.paper_single, s.paper_multiple, s.paper_judge = self._plan_values()
        s.round_auto = bool(self.round_auto_var.get())
        try:
            s.round_length = int(str(self.round_length_var.get()).strip())
        except (ValueError, TypeError):
            s.round_length = 0
        sc = self._scores()
        s.score_single, s.score_multiple, s.score_judge = sc["single"], sc["multiple"], sc["judge"]
        try:
            s.save(self._settings_path)
        except Exception:
            pass

    def _show_help(self) -> None:
        win = tk.Toplevel(self)
        win.title("使用说明")
        win.geometry("860x680")
        self._bind_dialog_focus(win)
        txt = tk.Text(win, wrap="word", font=("Microsoft YaHei", 10), padx=12, pady=10)
        txt.pack(fill="both", expand=True)
        txt.insert("1.0", HELP_TEXT)
        txt.configure(state="disabled")

    def _show_about(self) -> None:
        messagebox.showinfo(
            "关于",
            f"{__app_name__}  v{__version__}\n\n"
            "题库练习 + 模拟考试工具：实时判题、错题本、进度自动保留、\n"
            "按题型练习、按蓝图生成试卷并模拟考试。\n"
            "支持单选题 / 多选题 / 判断题；标注「（定）」的题目选项顺序固定。\n\n"
            "练习与考试成绩都按题目内容记录，题库增删题目、换目录后依然保留。\n"
            "全部计算在本机完成，不联网、不上传任何数据。\n"
            "单文件 exe，可自由复制分享。\n\n"
            "注：本程序不含试卷导出/打印；如需导出正式试卷，请使用「抽题匠 PaperForge」。")

    def set_status(self, text: str) -> None:
        self.status_var.set(text)

    def _on_close(self) -> None:
        self._cancel_auto_next()
        try:
            if self.session and not self.session.empty:
                self.session.save_position()
            self._save_settings()
            self.settings.window_geometry = self.geometry()
            self.settings.save(self._settings_path)
        except Exception:
            pass
        self.destroy()


def run(initial_bank: str | None = None) -> int:
    """启动界面。"""
    try:
        app = PaperDrillApp(initial_bank)
    except Exception as exc:
        print(f"界面启动失败：{exc}", file=sys.stderr)
        return 1
    app.mainloop()
    return 0


# ---------------------------------------------------------------- 无头自检
def selftest(bank_path: str, result_path: str = "", progress_root: str = "",
             exercises: int = 30, seed: int = 12345) -> int:
    """发布验收用的无头自检：在真实 tkinter 对象上跑完整流程。

    流程：导入 → 练习（含按题型范围）→ 生成一轮试卷（覆盖校验）→ 模拟考试 →
    交卷评分 → 校验进度与成绩落盘 → 重开恢复 → 错题本 → 重置。
    """
    import json

    from tkinter import messagebox as mb

    from .models import QType as _QType
    from .paper import PaperBlueprint as _BP
    from .paper import min_round_length as _min_round

    captured: list[dict] = []
    originals: dict = {}

    def _patch(name: str, kind: str) -> None:
        originals[name] = getattr(mb, name)

        def _fake(*a, **k):
            captured.append({"kind": kind, "text": str(a[0]) if a else ""})
            return False if kind == "ask" else None

        setattr(mb, name, _fake)

    for _n, _k in (("showinfo", "info"), ("showwarning", "warn"),
                   ("showerror", "error"), ("askyesno", "ask")):
        _patch(_n, _k)

    import paperdrill.store as store_mod
    from .config import AppSettings

    if progress_root:
        store_mod.progress_dir = lambda: Path(progress_root)   # type: ignore[assignment]

    work = Path(progress_root or store_mod.progress_dir()).parent
    work.mkdir(parents=True, exist_ok=True)
    settings_file = work / "selftest_settings.json"

    def _fresh_settings() -> AppSettings:
        return AppSettings(bank_path="", mode="order", scope="all",
                           shuffle_single=True, shuffle_multiple=True,
                           auto_next_on_correct=False, show_analysis=True)

    result: dict = {"ok": False, "stage": "init"}
    app: "PaperDrillApp | None" = None
    try:
        app = PaperDrillApp(None, settings=_fresh_settings(), settings_path=settings_file)
        app.withdraw()
        app.update()
        result["tk"] = {"screen": f"{app.winfo_screenwidth()}x{app.winfo_screenheight()}",
                        "window_created": bool(app.winfo_exists()), "title": app.title()}
        result["stage"] = "construct"

        app._import_bank(str(bank_path))
        if not app.session:
            raise RuntimeError("题库导入失败")
        result["bank"] = {"total": len(app.bank.questions), "text": app.stats_var.get()}
        result["stage"] = "import"

        # ---- 1) 顺序练习：偶数题答对、奇数题答错
        correct_cnt = wrong_cnt = 0
        for i in range(min(exercises, app.session.total)):
            item = app.session.current_item()
            if i % 2 == 0:
                selected = set(item.shown_answer)
            else:
                others = [lab for lab in item.labels if lab not in item.shown_answer]
                selected = {others[0]} if others else set()
            res = app.session.submit(selected)
            correct_cnt += 1 if res.correct else 0
            wrong_cnt += 1 if not res.correct else 0
            app.session.advance()
        app.session.save_position()
        app.update()
        result["answered"] = {"correct": correct_cnt, "wrong": wrong_cnt}
        result["stats_after"] = app.session.stats()
        result["progress_saved"] = app.store.path.exists()
        result["wrong_book"] = app.session.stats()["wrong_book"]

        # ---- 1.5) 重做校验：重新开始本轮 / 错题重练后必须仍能作答
        def _live_options() -> list:
            return [w for w in app._answer_widgets if w.winfo_exists()]

        def _all_enabled(widgets: list) -> bool:
            return bool(widgets) and all("disabled" not in w.state() for w in widgets)

        redo: dict = {}
        app._restart_round()
        app.update()
        widgets = _live_options()
        redo["restart_position"] = app.session.position
        redo["restart_options_enabled"] = _all_enabled(widgets)
        if widgets:
            attempts_before = app.session.current_record().attempts
            widgets[0].invoke()
            app.update()
            item = app.session.current_item()
            if item is not None and item.qtype is _QType.MULTIPLE and not app._answered:
                app._submit()
                app.update()
            redo["restart_reanswerable"] = (app.session.current_record().attempts == attempts_before + 1)
        app._set_mode(PracticeMode.WRONG)
        app.update()
        redo["wrong_mode_total"] = app.session.total
        redo["wrong_mode_answerable"] = (app.session.total == 0) or _all_enabled(_live_options())
        result["redo"] = redo
        app._set_mode(PracticeMode.ORDER)

        # ---- 2) 按题型练习（范围筛选）
        app._set_scope(Scope.SINGLE)
        result["scope_single_total"] = app.session.total
        app._set_scope(Scope.MULTIPLE)
        result["scope_multiple_total"] = app.session.total
        app._set_scope(Scope.JUDGE)
        result["scope_judge_total"] = app.session.total
        app._set_scope(Scope.ALL)

        # ---- 2.5) 快捷键校验（Enter / 小键盘 Enter / 输入框守卫）
        class _Ev:
            """构造真实结构的事件对象，直接驱动快捷键处理器（不依赖窗口焦点）。"""

            def __init__(self, widget, char: str = "") -> None:
                self.widget = widget
                self.char = char

        kb: dict = {
            "return_bound": bool(app.bind_all("<Return>")),
            "kp_enter_bound": bool(app.bind_all("<KP_Enter>")),
        }
        app._set_scope(Scope.SINGLE)
        app._render_current()
        app.update()
        pos_before = app.session.position
        app._on_key(_Ev(app, "1"))                       # 按 1 选择单选 → 应立即判定
        kb["key_select_answers"] = bool(app._answered)
        app._on_enter_key(_Ev(app))                      # Enter → 下一题
        kb["practice_enter_advances"] = (app.session.position == pos_before + 1)
        spin = None

        def _walk(widget):
            nonlocal spin
            for child in widget.winfo_children():
                if spin is None and child.winfo_class() in ("TSpinbox", "TEntry"):
                    spin = child
                    return
                _walk(child)

        _walk(app)
        if spin is not None:
            kb["input_guard"] = not app._shortcut_allowed(_Ev(spin, "1"))
        result["keyboard"] = kb
        app._set_scope(Scope.ALL)

        # ---- 3) 生成一轮试卷并校验覆盖
        app.paper_single_var.set("20")
        app.paper_multiple_var.set("10")
        app.paper_judge_var.set("10")
        app.round_auto_var.set(True)
        app._generate_round()
        rnd = app.round
        if rnd is None:
            raise RuntimeError("生成试卷失败")
        result["stage"] = "paper"
        result["paper"] = {
            "round_length": rnd.round_length,
            "auto_round_length": _min_round(app.bank.questions, _BP(20, 10, 10)),
            "papers": rnd.paper_count,
            "coverage_ok": rnd.coverage_ok,
            "coverage": {k: list(v) for k, v in rnd.coverage.items()},
            "totals": [p.total for p in rnd.papers],
            "single_counts": [p.count_of(_QType.SINGLE) for p in rnd.papers],
            "multiple_counts": [p.count_of(_QType.MULTIPLE) for p in rnd.papers],
            "judge_counts": [p.count_of(_QType.JUDGE) for p in rnd.papers],
            "reused": [p.reused_count for p in rnd.papers],
        }

        # ---- 4) 模拟考试：第 1 张卷子，前一半答对、其余答错、末尾 3 题不答
        paper = rnd.papers[0]
        app._start_exam(paper)
        exam = app.exam
        if exam is None:
            raise RuntimeError("开始考试失败")
        total = exam.total
        plan_correct = total // 2
        plan_wrong = max(0, total - plan_correct - 3)
        for i in range(total):
            item = exam.item(i)
            if i < plan_correct:
                exam.set_answer(i, set(item.shown_answer))
            elif i < plan_correct + plan_wrong:
                others = [lab for lab in item.labels if lab not in item.shown_answer]
                if others:
                    exam.set_answer(i, {others[0]})
                else:
                    # 选项全对的多选题：只选其中一个 → 少选，判错
                    exam.set_answer(i, {sorted(item.shown_answer)[0]})
            else:
                exam.clear_answer(i)
        result["exam_planned"] = {"correct": plan_correct, "wrong": plan_wrong, "unanswered": 3}
        app.update()
        app.exam_index = 0
        app._render_exam_question()
        # 考试页 Enter 应跳到下一题
        app._on_enter_key(_Ev(app))
        result["keyboard"]["exam_enter_advances"] = (app.exam_index == 1)
        app._exam_goto(0)
        # 真实模拟：作答期间界面不得出现对错信息
        text_before = app.exam_hint_var.get() + app.exam_count_var.get() + app.exam_type_var.get()
        result["exam_ui_hides_result"] = ("正确" not in text_before and "错误" not in text_before)
        exam_res = exam.submit()
        result["stage"] = "exam"
        result["exam"] = {
            "score": exam_res.score, "full_score": exam_res.full_score,
            "correct": exam_res.correct, "wrong": exam_res.wrong,
            "unanswered": exam_res.unanswered, "total": exam_res.total,
            "accuracy": round(exam_res.accuracy, 6),
            "per_type": exam_res.per_type,
        }
        result["stats_after_exam"] = app.session.stats()
        result["exam_history"] = len(app.store.exam_history())

        # ---- 5) 关闭软件 → 重开恢复
        app._on_close()
        app = None
        app2 = PaperDrillApp(None, settings=_fresh_settings(), settings_path=settings_file)
        app2.withdraw()
        app2.update()
        app2._import_bank(str(bank_path))
        result["stage"] = "reload"
        restored = app2.session.stats()
        result["stats_restored"] = restored
        result["progress_restored"] = (restored["done"] == result["stats_after_exam"]["done"]
                                       and restored["wrong_book"] == result["stats_after_exam"]["wrong_book"]
                                       and restored["done"] > 0)
        result["exam_history_restored"] = len(app2.store.exam_history())

        # ---- 6) 错题重练 / 只练未做
        app2._set_mode(PracticeMode.WRONG)
        result["wrong_mode_total"] = app2.session.total
        app2._set_mode(PracticeMode.FRESH)
        result["fresh_mode_total"] = app2.session.total

        # ---- 7) 清空错题 + 重置
        cleared = app2.store.progress.clear_wrong_book(app2.session.questions)
        app2.store.save()
        result["wrong_cleared"] = cleared
        app2.store.reset()
        result["stats_after_reset"] = app2.session.stats()
        app2._on_close()
        app2 = None

        plan = result["exam_planned"]
        keyboard = result.get("keyboard", {})
        redo = result.get("redo", {})
        result["ok"] = bool(
            result["progress_saved"] and result["progress_restored"]
            and result["paper"]["coverage_ok"]
            and result["paper"]["round_length"] == result["paper"]["auto_round_length"]
            and result["exam"]["correct"] == plan["correct"]
            and result["exam"]["wrong"] == plan["wrong"]
            and result["exam"]["unanswered"] == plan["unanswered"]
            and result["exam_history"] == 1
            and result["exam_history_restored"] == 1
            and result["exam_ui_hides_result"]
            and keyboard.get("return_bound") and keyboard.get("kp_enter_bound")
            and keyboard.get("key_select_answers") and keyboard.get("practice_enter_advances")
            and keyboard.get("exam_enter_advances") and keyboard.get("input_guard")
            and redo.get("restart_options_enabled") and redo.get("restart_reanswerable")
            and redo.get("wrong_mode_answerable")
            and result["stats_after_reset"]["done"] == 0)
        result["stage"] = "done"
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["traceback"] = traceback.format_exc(limit=8)
    finally:
        result["messages"] = captured
        for _n, _f in originals.items():
            setattr(mb, _n, _f)
        try:
            if app is not None:
                app.destroy()
        except Exception:
            pass
        payload = json.dumps(result, ensure_ascii=False, indent=2)
        if result_path:
            try:
                Path(result_path).parent.mkdir(parents=True, exist_ok=True)
                Path(result_path).write_text(payload, encoding="utf-8")
            except Exception:
                pass
        summary = {"ok": result.get("ok"), "stage": result.get("stage"),
                   "answered": result.get("answered"), "paper": result.get("paper", {}).get("papers"),
                   "coverage_ok": result.get("paper", {}).get("coverage_ok"),
                   "exam": result.get("exam"), "keyboard": result.get("keyboard"),
                   "redo": result.get("redo"),
                   "progress_restored": result.get("progress_restored"),
                   "error": result.get("error", "")}
        try:
            print("[gui-selftest] " + json.dumps(summary, ensure_ascii=False))
            if not result_path:
                print(payload)
        except Exception:
            pass
    return 0 if result.get("ok") else 1
