# -*- coding: utf-8 -*-
"""界面偏好持久化（与练习进度分开保存）。

位置：``%APPDATA%/PaperDrill/settings.json``
兼容 v1.0 的旧配置（``shuffle_options`` 单开关会自动迁移为单选/多选双开关）。
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .store import progress_dir

__all__ = ["AppSettings", "settings_path"]


def settings_path() -> Path:
    return progress_dir().parent / "settings.json"


@dataclass
class AppSettings:
    """界面偏好（不含练习进度）。"""

    bank_path: str = ""
    # 练习
    mode: str = "order"
    scope: str = "all"
    shuffle_single: bool = True
    shuffle_multiple: bool = True
    auto_next_on_correct: bool = True
    auto_next_delay_ms: int = 700
    show_analysis: bool = True
    # 试卷蓝图（需求 2）
    paper_single: int = 20
    paper_multiple: int = 10
    paper_judge: int = 10
    round_auto: bool = True
    round_length: int = 0
    # 评分
    score_single: float = 1.0
    score_multiple: float = 2.0
    score_judge: float = 1.0
    # 模拟考试
    record_exam_progress: bool = True
    last_paper_label: str = ""
    window_geometry: str = ""

    # ------------------------------------------------------------ 便捷
    def scores(self) -> dict:
        return {"single": float(self.score_single), "multiple": float(self.score_multiple),
                "judge": float(self.score_judge)}

    def blueprint(self):
        from .paper import PaperBlueprint

        return PaperBlueprint(int(self.paper_single), int(self.paper_multiple), int(self.paper_judge))

    def save(self, path: "Path | None" = None) -> Path:
        p = Path(path) if path else settings_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        return p

    @classmethod
    def load(cls, path: "Path | None" = None) -> "AppSettings":
        p = Path(path) if path else settings_path()
        if not p.exists():
            return cls()
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return cls()
        cfg = cls()
        legacy = None
        for key, value in (data or {}).items():
            if key == "shuffle_options":                  # v1.0 兼容
                legacy = bool(value)
                continue
            if hasattr(cfg, key):
                try:
                    setattr(cfg, key, value)
                except Exception:
                    continue
        if legacy is not None:
            cfg.shuffle_single = legacy
            cfg.shuffle_multiple = legacy
        return cfg
