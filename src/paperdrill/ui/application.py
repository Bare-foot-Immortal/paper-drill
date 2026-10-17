# -*- coding: utf-8 -*-
"""刷题匠 PaperDrill —— Qt 应用引导（QApplication 创建与全局设置）。"""
from __future__ import annotations

import os
import sys

from .. import __app_name__, __version__

__all__ = ["create_application", "enable_high_dpi", "app_icon_path", "apply_app_icon"]


def _set_windows_app_id() -> None:
    """设置 Windows AppUserModelID，让任务栏使用本程序的图标而不是默认图标。

    必须在创建任何顶层窗口之前调用（``create_application`` 在 MainWindow 之前执行）。
    """
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PaperDrill.App")
    except Exception:
        pass


def app_icon_path() -> str:
    """打包与源码运行时都能找到的图标路径（找不到返回空串）。

    候选顺序：PyInstaller 解包目录（``_MEIPASS``）→ 源码仓库根目录 ``assets/`` →
    安装后的包内 ``assets/`` → exe 同目录 ``assets/``。
    """
    ui_dir = os.path.dirname(os.path.abspath(__file__))        # …/paperdrill/ui
    package_dir = os.path.dirname(ui_dir)                      # …/paperdrill
    project_dir = os.path.dirname(os.path.dirname(package_dir))  # 源码布局下是仓库根
    frozen_dir = getattr(sys, "_MEIPASS", "") or ""
    exe_dir = os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, "frozen", False) else ""
    candidates = (
        os.path.join(frozen_dir, "assets", "PaperDrill.ico") if frozen_dir else "",
        os.path.join(project_dir, "assets", "PaperDrill.ico"),
        os.path.join(package_dir, "assets", "PaperDrill.ico"),
        os.path.join(exe_dir, "assets", "PaperDrill.ico") if exe_dir else "",
    )
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    return ""


def apply_app_icon(app) -> str:
    """把 ``assets/PaperDrill.ico`` 应用到 QApplication，返回实际使用的路径。"""
    path = app_icon_path()
    if not path:
        return ""
    try:
        from PySide6.QtGui import QIcon

        app.setWindowIcon(QIcon(path))
    except Exception:
        return ""
    return path


def enable_high_dpi() -> None:
    """高 DPI 相关设置（须在 QApplication 创建前设置的部分放这里）。

    Qt 6 默认启用高 DPI 缩放；这里只把取整策略设为 ``PassThrough``，
    避免 125% / 150% 缩放下因取整导致的模糊与一像素错位。
    """
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication

        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except Exception:
        pass


def create_application(argv: "list[str] | None" = None):
    """创建（或复用）QApplication，并应用名称、图标与主题。

    返回 ``(app, owned)``：``owned=True`` 表示由本函数创建，调用方负责 ``exec()``。
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from . import theme as theme_module

    enable_high_dpi()
    _set_windows_app_id()
    app = QApplication.instance()
    owned = app is None
    if app is None:
        app = QApplication(list(argv) if argv is not None else sys.argv[:1])
    app.setApplicationName("PaperDrill")
    app.setApplicationDisplayName(__app_name__)
    app.setApplicationVersion(__version__)
    app.setOrganizationName("PaperDrill")
    apply_app_icon(app)
    try:
        theme_module.apply_theme(app, os.environ.get("PAPERDRILL_THEME", "system"))
    except Exception:
        pass
    try:
        app.setAttribute(Qt.AA_DontShowIconsInMenus, False)
    except Exception:
        pass
    return app, owned
