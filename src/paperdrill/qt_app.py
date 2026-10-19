# -*- coding: utf-8 -*-
"""刷题匠 PaperDrill —— Qt 界面门面（入口调用）。

存在的意义：让 ``__main__`` 与打包入口只依赖**一个稳定接口**，而不关心
「PySide6 在不在、能不能起窗口」。任一环节不可用时 :func:`available` 返回 False，
调用方据此回退到 tkinter 界面，保证软件永远能启动（NFR-6）。

注意：``available()`` 会实际创建一个 ``QApplication`` 并**保留引用**
（用于探测平台插件是否可用，例如 Windows 上缺 `qwindows.dll` 会在构造时直接退出）。
后续 :func:`run` 复用它并进入事件循环——因此这里绝不能把 app 丢弃，
否则会触发"重建 QApplication"的不受支持路径。
"""
from __future__ import annotations

__all__ = ["available", "run", "selftest", "fallback_reason", "app"]

_last_error = ""
_app = None


def available() -> bool:
    """判断能否使用 Qt 界面（导入 + 创建 QApplication 都不抛异常）。"""
    global _last_error, _app
    try:
        from PySide6.QtWidgets import QApplication  # noqa: F401
    except BaseException as exc:                        # 未安装 / 动态库缺失 / 架构不符 / SystemExit
        _last_error = f"{type(exc).__name__}: {exc}"
        return False
    try:
        from .ui.application import create_application

        app, _owned = create_application()
        _app = app                                 # 保住引用，供 run() 复用
        _last_error = ""
        return True
    except BaseException as exc:                    # 平台插件缺失等也可能以 SystemExit 形式出现
        _last_error = f"{type(exc).__name__}: {exc}"
        return False


def app():
    """返回 :func:`available` 探测时创建的 QApplication（可能为 None）。"""
    return _app


def fallback_reason() -> str:
    """最近一次 :func:`available` 判定为不可用的原因（供日志/状态栏展示）。"""
    return _last_error


def run(initial_bank: "str | None" = None) -> int:
    """启动 Qt 界面，返回进程退出码。"""
    from .ui import run as _run

    return _run(initial_bank)


def selftest(bank_path: str, result_path: str = "", progress_root: str = "",
             exercises: int = 30, seed: int = 12345) -> int:
    """Qt 界面无头自检。

    直接导入子模块里的 ``run_selftest``：包属性 ``paperdrill.ui.selftest``
    在被 import 后会被替换成模块对象，经包属性转发会拿到 module 而不是函数。
    """
    from .ui.selftest import run_selftest

    return run_selftest(bank_path, result_path, progress_root, exercises, seed)
