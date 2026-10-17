# -*- coding: utf-8 -*-
"""刷题匠 PaperDrill —— Qt 页面包。"""
from __future__ import annotations

__all__ = [
    "PracticePage", "ExamSetupPage", "ExamRunPage", "ExamResultPage", "LibraryPage",
]


def __getattr__(name: str):        # 延迟导入，避免仅需一个页面时拉起全部依赖
    if name == "PracticePage":
        from .practice import PracticePage

        return PracticePage
    if name == "ExamSetupPage":
        from .exam import ExamSetupPage

        return ExamSetupPage
    if name == "ExamRunPage":
        from .exam_run import ExamRunPage

        return ExamRunPage
    if name == "ExamResultPage":
        from .result import ExamResultPage

        return ExamResultPage
    if name == "LibraryPage":
        from .library import LibraryPage

        return LibraryPage
    raise AttributeError(name)
