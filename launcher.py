# -*- coding: utf-8 -*-
"""PyInstaller 打包入口（被 build_exe.ps1 调用）。

PyInstaller 会把入口脚本当顶层模块执行，包内 ``__main__.py`` 的相对导入会失败；
这里先注册 src 路径再调用包的 main。
"""
from __future__ import annotations

import sys
from pathlib import Path

_here = Path(__file__).resolve().parent
_src = _here / "src"
if _src.is_dir():                      # 源码方式运行时启用
    sys.path.insert(0, str(_src))

from paperdrill.__main__ import main    # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
