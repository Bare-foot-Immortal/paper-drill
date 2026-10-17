# -*- coding: utf-8 -*-
"""Qt 界面 —— 应用图标与版本号一致性回归测试。

用户反馈「软件打开后不显示软件图标」，根因有两处：
* ``app_icon_path()`` 少算了一级目录，源码运行时找不到仓库根目录的 ``assets/PaperDrill.ico``；
* PyInstaller 只把 ico 当 exe 文件图标（``--icon``），没有把它加入运行时资源（``--add-data``），
  于是打包后 ``_MEIPASS/assets/PaperDrill.ico`` 不存在，窗口/任务栏图标为空。

本文件锁定：图标文件可定位、QApplication/主窗口都真正拿到非空图标、
``packaging/version_info.txt`` 与 ``__version__`` 保持同步。
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
        qapp,
    )
except ModuleNotFoundError:
    from qt_support import (  # type: ignore[no-redef]
        HAVE_QT,
        SKIP_REASON,
        QtTestCase,
        make_questions,
        qapp,
    )

from paperdrill import __version__  # noqa: E402


class TestIconResource(unittest.TestCase):
    def test_icon_file_is_found(self):
        from paperdrill.ui.application import app_icon_path

        path = app_icon_path()
        self.assertTrue(path, "未找到 assets/PaperDrill.ico（源码/打包路径都不对）")
        icon = Path(path)
        self.assertTrue(icon.is_file())
        self.assertEqual(icon.name, "PaperDrill.ico")
        self.assertGreater(icon.stat().st_size, 1000, "图标文件异常偏小")


class TestVersionMetadata(unittest.TestCase):
    """版本号必须同时更新：包版本 / PyInstaller 资源 / 说明文档标题。"""

    def test_version_format(self):
        self.assertRegex(__version__, r"^\d+\.\d+\.\d+$")

    def test_packaging_version_info_matches(self):
        text = (ROOT / "packaging" / "version_info.txt").read_text(encoding="utf-8")
        major, minor, patch = __version__.split(".")
        windows_version = f"{major}, {minor}, {patch}, 0"
        self.assertIn(f"filevers=({windows_version})", text)
        self.assertIn(f"prodvers=({windows_version})", text)
        self.assertIn(f"'{__version__}.0'", text, "FileVersion/ProductVersion 未同步")

    def test_user_docs_show_current_version(self):
        for name in ("README.md", "使用说明.md"):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertIn(__version__, text, f"{name} 未更新版本号")
        # 界面标题里的 v{版本} 由 __init__.__version__ 生成，避免出现旧版本字样
        source = (ROOT / "src" / "paperdrill" / "ui" / "main_window.py").read_text(encoding="utf-8")
        self.assertIn('{__version__}', source)


@unittest.skipUnless(HAVE_QT, SKIP_REASON)
class TestApplicationIcon(QtTestCase):
    def test_apply_app_icon_sets_window_icon(self):
        from paperdrill.ui.application import apply_app_icon

        app = qapp()
        path = apply_app_icon(app)
        self.assertTrue(path)
        self.assertFalse(app.windowIcon().isNull(), "QApplication 未拿到窗口图标")

    def test_main_window_has_icon_and_version_title(self):
        from paperdrill.ui.main_window import MainWindow

        ctrl = self.controller(questions=make_questions(6))
        win = MainWindow(ctrl, theme_mode="light", autoload=False)
        self.addCleanup(win.deleteLater)
        self.assertFalse(win.windowIcon().isNull(), "主窗口没有图标")
        self.assertIn(__version__, win.windowTitle())


if __name__ == "__main__":
    unittest.main(verbosity=2)
