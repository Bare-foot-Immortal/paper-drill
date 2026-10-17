# -*- coding: utf-8 -*-
"""刷题匠 PaperDrill —— Qt 界面包。

对外只暴露三件事：

* :func:`run`      —— 启动 Qt 界面（返回进程退出码）；
* :func:`selftest` —— 无头自检（发布验收用，输出 JSON）；
* :func:`available` —— 当前环境是否可用的判断（供入口决定是否回退 tkinter）。

界面实现位于 ``controller``（状态）、``pages``（页面）、``dialogs``（对话框）、
``main_window``（拼装）与 ``theme``（视觉）。
"""
from __future__ import annotations

__all__ = ["run", "selftest", "available", "MainWindow", "PaperDrillController"]


def available() -> bool:
    """PySide6 是否可导入（不创建窗口，可在任何环境下安全调用）。"""
    try:
        import PySide6.QtWidgets  # noqa: F401
    except Exception:
        return False
    return True


def run(initial_bank: "str | None" = None) -> int:
    """启动 Qt 界面并进入事件循环。异常时抛出，由入口决定是否回退 tkinter。"""
    from .application import create_application

    app, _owned = create_application()
    from ..config import AppSettings
    from .controller import PaperDrillController
    from .main_window import MainWindow

    settings = AppSettings.load()
    if initial_bank:
        settings.bank_path = initial_bank
    controller = PaperDrillController(settings=settings)
    window = MainWindow(controller, theme_mode=getattr(settings, "theme", "system") or "system")
    window.show()
    window.activateWindow()
    # 无论 QApplication 是不是本次创建（available() 探测时可能已创建），
    # 都必须进入事件循环，否则窗口一闪即退。
    return int(app.exec())


def selftest(bank_path: str, result_path: str = "", progress_root: str = "",
             exercises: int = 30, seed: int = 12345) -> int:
    """无头自检：驱动真实主线流程并输出 JSON（见 ``ui/selftest.py``）。"""
    from .selftest import run_selftest

    return run_selftest(bank_path, result_path, progress_root, exercises, seed)
