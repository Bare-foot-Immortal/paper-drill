# -*- coding: utf-8 -*-
"""程序入口。

* 无参数（或双击 exe）→ 启动练习界面，并自动恢复上次的题库与进度；
* 唯一参数是题库文件 → 启动界面并直接打开该题库（支持把文件拖到 exe 上）；
* 其他参数 → 命令行辅助模式（题库统计、进度列表、自检）。
"""
from __future__ import annotations

import sys
from pathlib import Path

from .bank_io import SUPPORTED_SUFFIXES


def main(argv: "list[str] | None" = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    if args and args[0] in ("--gui",):
        args = args[1:]
        from .gui import run as run_gui

        return run_gui(args[0] if args else None)

    if len(args) == 1 and not args[0].startswith("-"):
        candidate = Path(args[0])
        if candidate.exists() and candidate.suffix.lower() in SUPPORTED_SUFFIXES:
            from .gui import run as run_gui

            return run_gui(str(candidate))

    if args:
        from .cli import attach_parent_console, main as run_cli

        attach_parent_console()
        try:
            return run_cli(args)
        finally:
            try:
                sys.stdout.flush()
                sys.stderr.flush()
            except Exception:
                pass

    from .gui import run as run_gui

    return run_gui()


if __name__ == "__main__":
    raise SystemExit(main())
