# -*- coding: utf-8 -*-
"""刷题匠 PaperDrill —— Qt 界面测试公共设施。

* 在**导入任何 Qt 模块之前**把平台设为 ``offscreen``，保证无显示环境也能跑；
* PySide6 缺失时整个 Qt 测试集跳过（不阻塞 tkinter-only 环境）；
* 提供一个轻量的 ``QtTestCase``，统一创建/销毁 QApplication 与临时进度目录。

运行：``python -m unittest tests.test_qt_controller -v``
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# 兜底：即使不是以包方式导入（tests/__init__.py 未执行），也保证 offscreen 平台
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

FIXTURE_BANK = ROOT / "fixtures" / "样例题库.xlsx"
SAMPLE_BANK = ROOT / "samples" / "示例题库.xlsx"


def qt_available() -> bool:
    try:
        import PySide6.QtWidgets  # noqa: F401
    except Exception:
        return False
    return True


HAVE_QT = qt_available()
SKIP_REASON = "未安装 PySide6，Qt 界面测试跳过"


def ensure_fixtures() -> None:
    """合成题库缺失时调用生成脚本（与 tkinter 测试一致）。"""
    if FIXTURE_BANK.exists():
        return
    script = ROOT / "tools" / "make_samples.py"
    if script.exists():
        import subprocess

        subprocess.run([sys.executable, str(script), "--fixtures-only"],
                       cwd=str(ROOT), check=False, capture_output=True)


ensure_fixtures()


def qapp():
    """返回进程内唯一的 QApplication（offscreen）。"""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def process_events() -> None:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is not None:
        app.processEvents()


def make_questions(count: int = 12):
    """构造 单选/多选/判断 混合题目（不依赖题库文件）。"""
    from paperdrill.models import QType, Question

    out = []
    for i in range(count):
        kind = i % 3
        if kind == 0:
            out.append(Question(qid=f"single-{i}", qtype=QType.SINGLE, stem=f"单选题 {i}",
                                options=[f"选项{i}-{k}" for k in range(4)],
                                answer_letters=["A"], analysis=f"解析 {i}", src_row=i))
        elif kind == 1:
            out.append(Question(qid=f"multi-{i}", qtype=QType.MULTIPLE, stem=f"多选题 {i}",
                                options=[f"选项{i}-{k}" for k in range(4)],
                                answer_letters=["A", "C"], analysis=f"解析 {i}", src_row=i))
        else:
            out.append(Question(qid=f"judge-{i}", qtype=QType.JUDGE, stem=f"判断题 {i}",
                                options=[], judge_answer=(i % 2 == 0),
                                analysis=f"解析 {i}", src_row=i))
    return out


@unittest.skipUnless(HAVE_QT, SKIP_REASON)
class QtTestCase(unittest.TestCase):
    """所有 Qt 测试的基类：隔离的进度目录 + 独立设置文件。"""

    def setUp(self) -> None:
        app = qapp()
        self.app = app
        from paperdrill.config import AppSettings

        self.tmp = Path(tempfile.mkdtemp(prefix="pd_qt_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.progress_root = self.tmp / "progress"
        self.settings_file = self.tmp / "settings.json"
        # 默认关闭选项打乱：让「A 就是正确答案」这类断言可复现；
        # 打乱本身的正确性由 test_qt_controller.test_multiple_choice_needs_submit
        # 与 test_shuffle_toggle_keeps_position 覆盖（它们按显示答案推导答案）。
        self.settings = AppSettings(bank_path="", mode="order", scope="all",
                                    shuffle_single=False, shuffle_multiple=False,
                                    auto_next_on_correct=False, show_analysis=True)
        process_events()

    def tearDown(self) -> None:
        process_events()

    # ------------------------------------------------------------ 工厂
    def controller(self, questions=None, name: str = "题集", **kwargs):
        """构造一个已装好内存题库的控制器（不读文件，速度更快）。

        ``shuffle=True`` 时按打乱模式构建（用于验证打乱相关行为）。
        """
        from paperdrill.bank_io import BankLoadResult
        from paperdrill.store import BankLibrary
        from paperdrill.ui.controller import PaperDrillController

        shuffle = bool(kwargs.pop("shuffle", False))
        settings = kwargs.pop("settings", self.settings)
        if shuffle:
            from dataclasses import replace

            settings = replace(settings, shuffle_single=True, shuffle_multiple=True)
        ctrl = PaperDrillController(
            settings=settings,
            settings_path=kwargs.pop("settings_path", self.settings_file),
            progress_root=kwargs.pop("progress_root", self.progress_root),
            library=kwargs.pop("library", None) or BankLibrary([], self.tmp / "library.json"))
        bank = kwargs.pop("bank", None)
        if bank is not None or questions is not None:
            qs = questions if questions is not None else list(bank.questions)
            result = bank if bank is not None else BankLoadResult(questions=qs, source=f"{name}.xlsx")
            self.install_bank(ctrl, result)
        return ctrl

    def install_bank(self, ctrl, result) -> None:
        """把题库装进控制器（绕过文件解析，等价于 load_bank 成功后的状态）。"""
        from paperdrill.practice import PracticeMode, PracticeSession, Scope
        from paperdrill.store import ProgressStore

        state = ctrl.state
        state.bank = result
        state.bank_path = str(self.tmp / f"{Path(result.source).stem or '题库'}.xlsx")
        Path(state.bank_path).write_text("placeholder", encoding="utf-8")
        state.store = ProgressStore.load_for(Path(state.bank_path).stem, result.questions,
                                             self.progress_root)
        try:                                   # 与真实 load_bank 一致：立即落盘，进度文件存在
            state.store.save()
        except Exception:
            pass
        # 与 load_bank 的成功路径保持一致：题库同时进入「最近使用」列表
        try:
            ctrl.library.remember(state.bank_path, Path(state.bank_path).stem, len(result.questions))
        except Exception:
            pass
        session = PracticeSession(
            ctrl.active_questions(), state.store, mode=PracticeMode.from_label(
                str(self.settings.mode or "order")),
            qtype_filter=Scope.from_label(str(self.settings.scope or "all")).qtype,
            shuffle_single=state.shuffle_single, shuffle_multiple=state.shuffle_multiple)
        session.restore_position()
        state.session = session
        state.scope = Scope.ALL if session.qtype_filter is None else {
            "单选题": Scope.SINGLE, "多选题": Scope.MULTIPLE, "判断题": Scope.JUDGE,
        }[session.qtype_filter.value]
        state.mode = session.mode
        ctrl._reset_practice_feedback("请作答（单选/判断点选即判，多选勾选后提交）")
        ctrl._refresh_all(raise_practice=True)

    # ------------------------------------------------------------ 便捷
    def answer_correctly(self, ctrl) -> bool:
        from paperdrill.models import QType

        item = ctrl.current_item()
        if item is None:
            return False
        if item.qtype is QType.MULTIPLE:
            for letter in sorted(item.shown_answer):
                ctrl.toggle_option(letter)
            result = ctrl.submit()
        else:
            result = ctrl.toggle_option(sorted(item.shown_answer)[0])
        return bool(result and result.correct)

    def answer_wrong(self, ctrl) -> bool:
        """故意答错当前题。

        多选题若正确答案覆盖了全部选项，则用"少选"制造错误（同样是判错），
        保证任何题型都能稳定造出错题。
        """
        from paperdrill.models import QType

        item = ctrl.current_item()
        if item is None:
            return False
        wrongs = [lab for lab in item.labels if lab not in item.shown_answer]
        if wrongs:
            result = ctrl.toggle_option(wrongs[0])
            if result is None and item.qtype is QType.MULTIPLE:
                result = ctrl.submit()
            return bool(result and not result.correct)
        if item.qtype is QType.MULTIPLE and len(item.shown_answer) >= 2:
            for letter in sorted(item.shown_answer)[:-1]:
                ctrl.toggle_option(letter)
            result = ctrl.submit()
            return bool(result and not result.correct)
        return False

    def window(self, ctrl, theme_mode: str = "light", autoload: bool = False):
        """创建主窗口。

        注意：不依赖 ``QShortcut`` 是否命中——主窗口另有 ``keyPressEvent`` 兜底，
        无头（offscreen）环境下按键同样会被处理。
        """
        from paperdrill.ui.main_window import MainWindow

        win = MainWindow(ctrl, theme_mode=theme_mode, autoload=autoload)
        self.addCleanup(self._destroy_window, win)
        win.show()
        process_events()
        try:
            win.activateWindow()
        except Exception:
            pass
        process_events()
        return win

    @staticmethod
    def _destroy_window(win) -> None:
        try:
            win.close()
            win.deleteLater()
        except Exception:
            pass
        process_events()
