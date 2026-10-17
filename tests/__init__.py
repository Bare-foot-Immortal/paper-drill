# -*- coding: utf-8 -*-
"""测试包。

把 ``tests`` 变成包有两个目的：

1. 让 ``from tests.qt_support import …`` 可用（包方式运行测试时）；
2. 在**任何测试模块被导入之前**统一设置 Qt 平台为 ``offscreen``，
   保证 ``python -m unittest discover -s tests`` 在无显示环境（CI）下也能跑 Qt 测试。
   注意：只影响 PySide6，不影响 tkinter 版本的测试。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

__all__: list[str] = []
