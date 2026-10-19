# -*- coding: utf-8 -*-
"""界面偏好持久化（与练习进度分开保存）。

位置：``%APPDATA%/PaperDrill/settings.json``
兼容 v1.0 的旧配置（``shuffle_options`` 单开关会自动迁移为单选/多选双开关）。

容错约定（审计 P1-5 / P2-21）：配置文件是**合法 JSON 但结构/字段类型不对**时
一律忽略该项并使用默认值，绝不让软件因为配置损坏而打不开。
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .store import progress_dir

__all__ = ["AppSettings", "settings_path"]

# 数值字段的合理上限：避免被手改成 1e9 后组卷卡死/OOM
_LIMITS = {
    "auto_next_delay_ms": (0, 60_000),
    "paper_single": (0, 10_000),
    "paper_multiple": (0, 10_000),
    "paper_judge": (0, 10_000),
    "round_length": (0, 10_000),
    "score_single": (0.0, 1_000.0),
    "score_multiple": (0.0, 1_000.0),
    "score_judge": (0.0, 1_000.0),
}
_STR_CHOICES = {
    "mode": {"order", "random", "wrong", "fresh"},
    "scope": {"all", "single", "multiple", "judge"},
    "theme": {"system", "light", "dark"},
    "last_page": {"practice", "exam", "library"},
}


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
    # 界面（v1.3.0 Qt 版新增；旧配置文件缺这些字段时取默认值，互不影响）
    theme: str = "system"              # system / light / dark
    last_page: str = "practice"        # practice / exam / library
    qt_window_state: str = ""          # Qt 主窗口几何 "WxH+X+Y"

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
            # utf-8-sig：兼容 Windows 记事本另存为「UTF-8 带 BOM」
            raw = p.read_text(encoding="utf-8-sig")
            data = json.loads(raw)
        except Exception:
            return cls()
        if not isinstance(data, dict):
            # 数组 / 字符串 / 数字都是"合法 JSON 但结构不对"，按空配置处理（P1-5）
            return cls()

        cfg = cls()
        dataclass_fields = {f.name for f in fields(cls)}
        legacy = None
        for key, value in data.items():
            if key == "shuffle_options":                  # v1.0 兼容
                if isinstance(value, bool):
                    legacy = value
                continue
            if key not in dataclass_fields:               # 不写未定义字段（含 __class__ 等）
                continue
            current = getattr(cfg, key)
            try:
                if isinstance(current, bool):
                    if isinstance(value, bool):
                        converted = value
                    elif isinstance(value, (int, float)) and not isinstance(value, bool):
                        converted = bool(value)
                    elif isinstance(value, str) and value.strip().lower() in (
                            "true", "1", "yes", "on", "false", "0", "no", "off"):
                        converted = value.strip().lower() in ("true", "1", "yes", "on")
                    else:
                        continue
                elif isinstance(current, int):
                    if isinstance(value, bool):
                        continue
                    converted = int(value)
                    if key in _LIMITS:
                        lo, hi = _LIMITS[key]
                        converted = max(int(lo), min(int(hi), converted))
                elif isinstance(current, float):
                    if isinstance(value, bool):
                        continue
                    converted = float(value)
                    if not math.isfinite(converted):
                        continue
                    if key in _LIMITS:
                        lo, hi = _LIMITS[key]
                        converted = max(float(lo), min(float(hi), converted))
                elif isinstance(current, str):
                    if not isinstance(value, str):
                        continue                          # null/数字/对象 → 保留默认值
                    converted = value
                    choices = _STR_CHOICES.get(key)
                    if choices is not None and converted not in choices:
                        continue
                elif isinstance(current, (list, tuple)):
                    if not isinstance(value, (list, tuple)):
                        continue
                    converted = type(current)(value)
                elif isinstance(current, dict):
                    if not isinstance(value, dict):
                        continue
                    converted = dict(value)
                else:
                    converted = value
            except (TypeError, ValueError, OverflowError):
                continue
            setattr(cfg, key, converted)
        if legacy is not None:
            cfg.shuffle_single = legacy
            cfg.shuffle_multiple = legacy
        return cfg
