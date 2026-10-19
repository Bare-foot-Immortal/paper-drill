# -*- coding: utf-8 -*-
"""程序入口。

* 无参数（或双击 exe）→ 启动界面，并自动恢复上次的题库与进度；
* 唯一参数是题库文件 → 启动界面并直接打开该题库（支持把文件拖到 exe 上）；
* 其他参数 → 命令行辅助模式（题库统计、进度列表、自检）。

界面选择：**优先 Qt（PySide6）**；导入失败或窗口创建失败时自动回退 tkinter，
两者读写同一份进度与配置，用户感知不到差异（只有观感不同）。
"""
from __future__ import annotations

import sys
from pathlib import Path

from .bank_io import SUPPORTED_SUFFIXES

__all__ = ["main", "pick_gui"]


def pick_gui() -> str:
    """返回本次应使用的界面：``"qt"`` 或 ``"tk"``。"""
    try:
        from .qt_app import available, fallback_reason

        if available():
            return "qt"
        reason = fallback_reason()
        if reason:
            print(f"[界面] Qt 界面不可用，回退 tkinter：{reason}", file=sys.stderr)
    except BaseException as exc:            # 含 SystemExit：损坏的 Qt 也必须能回退
        print(f"[界面] Qt 界面不可用，回退 tkinter：{exc}", file=sys.stderr)
    return "tk"


def run_gui(initial_bank: "str | None", gui: str = "") -> int:
    """按选定的界面启动。"""
    choice = gui or pick_gui()
    if choice == "qt":
        try:
            from .qt_app import run as run_qt

            return run_qt(initial_bank)
        except Exception as exc:
            print(f"[界面] Qt 界面启动失败，回退 tkinter：{exc}", file=sys.stderr)
    from .gui import run as run_tk

    return run_tk(initial_bank)


def main(argv: "list[str] | None" = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    if args and args[0] in ("--gui",):
        rest = args[1:]
        if len(rest) > 1:
            print("[错误] --gui 只接受一个题库路径参数。", file=sys.stderr)
            return 2
        return run_gui(rest[0] if rest else None)

    if len(args) == 1 and not args[0].startswith("-"):
        candidate = Path(args[0])
        if candidate.exists() and candidate.suffix.lower() in SUPPORTED_SUFFIXES:
            return run_gui(str(candidate))

    if args:
        from .cli import attach_parent_console
        from .cli import main as run_cli

        attach_parent_console()
        try:
            return run_cli(args)
        finally:
            try:
                sys.stdout.flush()
                sys.stderr.flush()
            except Exception:
                pass

    return run_gui(None)


if __name__ == "__main__":
    raise SystemExit(main())
