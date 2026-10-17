# -*- coding: utf-8 -*-
"""刷题匠 PaperDrill —— Qt 视觉主题（设计令牌 + QSS 生成）。

设计要点
--------
* **令牌集中**：颜色、间距、圆角、字号只在 :data:`PALETTES` 里定义一次，
  QSS 与自绘控件（``ProgressRing`` 等）都从这里取值，改一处即可全局生效；
* **三档主题**：``light`` / ``dark`` / ``system``（跟随系统深浅色）；
* **可校验**：提供对比度计算，测试可断言正文对比度满足 WCAG AA（≥ 4.5:1）；
* Qt 6 默认启用高 DPI 缩放，尺寸一律使用**逻辑像素**。
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Iterable

from PySide6.QtGui import QColor, QFont, QPalette

__all__ = [
    "Theme", "LIGHT", "DARK", "PALETTES", "THEME_MODES",
    "contrast_ratio", "relative_luminance", "resolve_mode",
    "font_family", "build_stylesheet", "apply_theme", "theme_for",
]


# ---------------------------------------------------------------- 字体
FONT_CANDIDATES = (
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "PingFang SC",
    "Noto Sans CJK SC",
    "Source Han Sans SC",
)


def font_family() -> str:
    """返回本机可用的首个中文字体族；都不可用时交给 Qt 默认字体。"""
    try:
        from PySide6.QtGui import QFontDatabase

        families = set(QFontDatabase.families())
        for name in FONT_CANDIDATES:
            if name in families:
                return name
    except Exception:
        pass
    return FONT_CANDIDATES[0]


@dataclass(frozen=True)
class Theme:
    """一套主题的设计令牌。"""

    name: str
    dark: bool

    # 背景层次
    bg: str
    surface: str
    surface_alt: str
    surface_hover: str
    border: str
    border_strong: str

    # 文本
    text: str
    text_muted: str
    text_faint: str
    text_inverse: str

    # 语义色
    primary: str
    primary_hover: str
    primary_weak: str
    success: str
    success_weak: str
    danger: str
    danger_weak: str
    warning: str
    warning_weak: str
    focus: str
    selection: str        # 表格/列表选中行底色（比 primary_weak 更实，保证"看得出选中"）

    # 尺寸与排版
    radius: int = 8
    radius_card: int = 14
    space_xs: int = 4
    space_sm: int = 8
    space_md: int = 12
    space_lg: int = 16
    space_xl: int = 24
    font_size: int = 12
    font_size_stem: int = 13
    font_size_small: int = 11
    font_size_title: int = 15
    font_size_hero: int = 30

    # ------------------------------------------------------------ 便捷
    def color(self, key: str) -> QColor:
        return QColor(getattr(self, key))

    def css_color(self, key: str) -> str:
        return getattr(self, key)

    def to_font(self, size: int | None = None, bold: bool = False) -> QFont:
        font = QFont(font_family(), int(size or self.font_size))
        font.setBold(bool(bold))
        try:
            font.setHintingPreference(QFont.PreferFullHinting)
        except Exception:
            pass
        return font


LIGHT = Theme(
    name="light",
    dark=False,
    bg="#F5F7FA",
    surface="#FFFFFF",
    surface_alt="#EEF2F7",
    surface_hover="#F2F6FB",
    border="#DCE3EC",
    border_strong="#C2CCDA",
    text="#1B2430",
    text_muted="#5B6878",
    text_faint="#8B97A6",
    text_inverse="#FFFFFF",
    # 主色取深到能在其上使用白字的青绿（#FFFFFF on #0B7F72 ≈ 5.2:1，满足 WCAG AA）
    primary="#0B7F72",
    primary_hover="#09695F",
    primary_weak="#E4F6F3",
    success="#128A4B",
    success_weak="#E6F6ED",
    danger="#C62828",
    danger_weak="#FDECEC",
    warning="#B26A00",
    warning_weak="#FDF3E3",
    focus="#0B7FD4",
    selection="#CFEAE5",
)

DARK = Theme(
    name="dark",
    dark=True,
    bg="#11151C",
    surface="#1A2029",
    surface_alt="#222A35",
    surface_hover="#252F3B",
    border="#2C3644",
    border_strong="#3B4757",
    text="#E6EDF5",
    text_muted="#9AA7B6",
    text_faint="#75828F",
    text_inverse="#0E1319",
    primary="#2BC4B0",
    primary_hover="#40D3BF",
    primary_weak="#123B36",
    success="#3CCF82",
    success_weak="#12301F",
    danger="#FF6B6B",
    danger_weak="#3A1D1D",
    warning="#F0B232",
    warning_weak="#3A2E12",
    focus="#57B4FF",
    selection="#1C4A44",
)

PALETTES = {"light": LIGHT, "dark": DARK}
THEME_MODES = ("system", "light", "dark")


def theme_for(mode: str) -> Theme:
    """把 ``system``/``light``/``dark`` 解析为具体主题对象。"""
    return PALETTES["dark" if resolve_mode(mode) == "dark" else "light"]


def resolve_mode(mode: str) -> str:
    """``system`` → 依据系统配色解析为 ``light`` 或 ``dark``；非法值按 ``system``。"""
    mode = (mode or "system").strip().lower()
    if mode in ("light", "dark"):
        return mode
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication

        hints = QGuiApplication.styleHints() if QGuiApplication.instance() else None
        if hints is not None:
            try:
                scheme = hints.colorScheme()
                if scheme == Qt.ColorScheme.Dark:
                    return "dark"
                if scheme == Qt.ColorScheme.Light:
                    return "light"
            except Exception:
                pass
        # 退化：用调色板窗口色的亮度推断
        app = QGuiApplication.instance()
        if app is not None:
            col = app.palette().color(QPalette.Window)
            return "dark" if col.lightness() < 128 else "light"
    except Exception:
        pass
    return "light"


# ---------------------------------------------------------------- 对比度
def _channel(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4


def relative_luminance(color: "str | QColor") -> float:
    """WCAG 相对亮度（0=黑，1=白）。"""
    c = QColor(color) if not isinstance(color, QColor) else color
    r, g, b = _channel(c.redF()), _channel(c.greenF()), _channel(c.blueF())
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(foreground: "str | QColor", background: "str | QColor") -> float:
    """WCAG 对比度（1:1 ~ 21:1）；正文建议 ≥ 4.5。"""
    l1 = relative_luminance(foreground)
    l2 = relative_luminance(background)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


# ---------------------------------------------------------------- 自绘小图标
_ARROW_CACHE: dict[tuple[str, str], str] = {}


def _arrow_icon(color: str, up: bool) -> str:
    """生成 spinbox 上下箭头的小 PNG（QSS 一旦美化 up/down-button 就不再画原生箭头）。

    画到系统临时目录（ASCII 路径，避免中文路径在 QSS url 里出问题），按颜色缓存。
    任何异常都返回空串，让样式退化为"没有箭头"而不是崩溃。
    """
    key = (color, "up" if up else "down")
    cached = _ARROW_CACHE.get(key)
    if cached:
        return cached
    try:
        import tempfile
        from pathlib import Path

        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtGui import QColor, QPainter, QPixmap, QPolygon

        size = 14
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setBrush(QColor(color))
        painter.setPen(Qt.NoPen)
        if up:
            points = [QPoint(3, 9), QPoint(11, 9), QPoint(7, 4)]
        else:
            points = [QPoint(3, 5), QPoint(11, 5), QPoint(7, 10)]
        painter.drawPolygon(QPolygon(points))
        painter.end()

        out = Path(tempfile.gettempdir()) / "paperdrill_ui" / \
            f"arrow_{key[1]}_{color.lstrip('#')}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        pixmap.save(str(out), "PNG")
        _ARROW_CACHE[key] = out.as_posix()
        return _ARROW_CACHE[key]
    except Exception:
        return ""


# ---------------------------------------------------------------- QSS
def build_stylesheet(theme: Theme) -> str:
    """按设计令牌生成整窗 QSS。"""
    t = theme
    family = font_family()
    up_icon = _arrow_icon(t.text_muted, True)
    down_icon = _arrow_icon(t.text_muted, False)
    arrow_css = ""
    if up_icon and down_icon:
        arrow_css = (
            f'QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url("{up_icon}");'
            f' width: 9px; height: 9px; }}\n'
            f'QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url("{down_icon}");'
            f' width: 9px; height: 9px; }}\n'
        )
    return f"""
/* ---------------- 基础 ---------------- */
QWidget {{
    background: transparent;
    color: {t.text};
    font-family: "{family}";
    font-size: {t.font_size}px;
}}
QMainWindow, QDialog, #AppRoot {{
    background: {t.bg};
}}
QToolTip {{
    background: {t.surface};
    color: {t.text};
    border: 1px solid {t.border};
    border-radius: {t.radius}px;
    padding: 6px 8px;
}}

/* ---------------- 侧边导航 ---------------- */
#SideBar {{
    background: {t.surface};
    border-right: 1px solid {t.border};
}}
#SideBarBrand {{
    color: {t.primary};
    font-size: {t.font_size_title + 2}px;
    font-weight: 700;
}}
#SideBarSub {{
    color: {t.text_muted};
    font-size: {t.font_size_small}px;
}}
QPushButton#NavButton {{
    background: transparent;
    border: none;
    border-radius: {t.radius}px;
    color: {t.text_muted};
    padding: 10px 12px;
    text-align: left;
    font-size: {t.font_size}px;
}}
QPushButton#NavButton:hover {{
    background: {t.surface_hover};
    color: {t.text};
}}
QPushButton#NavButton:focus {{
    outline: none;
    border: 1px solid {t.focus};
}}
QPushButton#NavButton[active="true"] {{
    background: {t.primary_weak};
    color: {t.primary};
    font-weight: 700;
}}

/* ---------------- 卡片 ---------------- */
#Card {{
    background: {t.surface};
    border: 1px solid {t.border};
    border-radius: {t.radius_card}px;
}}
#CardTitle {{
    color: {t.text};
    font-size: {t.font_size + 1}px;
    font-weight: 700;
}}
#CardHint {{
    color: {t.text_muted};
    font-size: {t.font_size_small}px;
}}
#SectionLabel {{
    color: {t.text_muted};
    font-size: {t.font_size_small}px;
    letter-spacing: 0.5px;
}}
#HeroNumber {{
    color: {t.text};
    font-size: {t.font_size_hero}px;
    font-weight: 700;
}}
#Muted {{
    color: {t.text_muted};
}}
#Faint {{
    color: {t.text_faint};
    font-size: {t.font_size_small}px;
}}
#Feedback[state="correct"] {{ color: {t.success}; font-weight: 700; }}
#Feedback[state="wrong"]   {{ color: {t.danger};  font-weight: 700; }}
#Feedback[state="reveal"]  {{ color: {t.warning}; font-weight: 700; }}
#Feedback[state="info"]    {{ color: {t.primary}; font-weight: 600; }}
#Feedback[state="empty"]   {{ color: {t.text_muted}; font-weight: 600; }}
#Feedback[state="idle"]    {{ color: {t.text_muted}; }}
#AnalysisText {{ color: {t.text_muted}; }}
#StemText {{
    color: {t.text};
    font-size: {t.font_size_stem}px;
}}
#TopBar {{
    background: {t.surface};
    border-bottom: 1px solid {t.border};
}}
#StatusBar {{
    background: {t.surface};
    border-top: 1px solid {t.border};
    color: {t.text_muted};
    font-size: {t.font_size_small}px;
}}

/* ---------------- 按钮 ---------------- */
QPushButton {{
    background: {t.surface_alt};
    border: 1px solid {t.border};
    border-radius: {t.radius}px;
    color: {t.text};
    padding: 7px 14px;
    min-height: 18px;
}}
QPushButton:hover {{
    background: {t.surface_hover};
    border-color: {t.border_strong};
}}
QPushButton:pressed {{
    background: {t.border};
}}
QPushButton:focus {{
    outline: none;
    border: 1px solid {t.focus};
}}
QPushButton:disabled {{
    color: {t.text_faint};
    background: {t.surface_alt};
    border-color: {t.border};
}}
QPushButton[kind="primary"] {{
    background: {t.primary};
    border: 1px solid {t.primary};
    color: {t.text_inverse};
    font-weight: 700;
}}
QPushButton[kind="primary"]:hover {{
    background: {t.primary_hover};
    border-color: {t.primary_hover};
}}
QPushButton[kind="primary"]:disabled {{
    background: {t.surface_alt};
    border-color: {t.border};
    color: {t.text_faint};
}}
QPushButton[kind="ghost"] {{
    background: transparent;
    border: 1px solid transparent;
    color: {t.text_muted};
}}
QPushButton[kind="ghost"]:hover {{
    background: {t.surface_hover};
    color: {t.text};
}}
QPushButton[kind="danger"] {{
    background: transparent;
    border: 1px solid {t.danger};
    color: {t.danger};
}}
QPushButton[kind="danger"]:hover {{
    background: {t.danger_weak};
}}

/* ---------------- 菜单栏 ---------------- */
QMenuBar {{
    background: {t.surface};
    color: {t.text};
    border-bottom: 1px solid {t.border};
    padding: 3px 6px;
}}
QMenuBar::item {{
    background: transparent;
    padding: 5px 10px;
    border-radius: 6px;
}}
QMenuBar::item:selected {{
    background: {t.primary_weak};
    color: {t.text};
}}
QMenuBar::item:pressed {{
    background: {t.primary_weak};
}}

/* ---------------- 输入 ---------------- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {t.surface};
    border: 1px solid {t.border};
    border-radius: {t.radius}px;
    padding: 5px 8px;
    color: {t.text};
    selection-background-color: {t.primary};
    selection-color: {t.text_inverse};
    min-height: 18px;
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border: 1px solid {t.focus};
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 16px;
    margin: 3px 3px 0 0;
    border: none;
    border-radius: 3px;
    background: {t.surface_alt};
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 16px;
    margin: 0 3px 3px 0;
    border: none;
    border-radius: 3px;
    background: {t.surface_alt};
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background: {t.border};
}}
{arrow_css}QComboBox QAbstractItemView {{
    background: {t.surface};
    border: 1px solid {t.border};
    selection-background-color: {t.primary_weak};
    selection-color: {t.text};
    outline: none;
}}
QCheckBox, QRadioButton {{
    spacing: 7px;
    color: {t.text};
}}
/* 勾选框/单选框：自绘 indicator（原生绘制在深色主题下对勾几乎不可见）。
   不用图片资源：勾选态用实心方块、单选态用圆点+浅色环，深浅主题都清晰。 */
QCheckBox::indicator {{
    width: 15px;
    height: 15px;
    border: 1px solid {t.border_strong};
    border-radius: 3px;
    background: {t.surface};
}}
QCheckBox::indicator:hover {{ border-color: {t.primary}; }}
QCheckBox::indicator:checked {{
    background: {t.primary};
    border-color: {t.primary};
}}
QRadioButton::indicator {{
    width: 15px;
    height: 15px;
    border: 1px solid {t.border_strong};
    border-radius: 8px;
    background: {t.surface};
}}
QRadioButton::indicator:hover {{ border-color: {t.primary}; }}
/* 选中态用实心圆点（与勾选框的实心方块风格一致），深浅主题都一眼可辨 */
QRadioButton::indicator:checked {{
    background: {t.primary};
    border: 1px solid {t.primary};
    border-radius: 8px;
}}
QCheckBox:disabled, QRadioButton:disabled {{ color: {t.text_faint}; }}

/* ---------------- 表格与列表 ---------------- */
QTableView, QTreeView, QListView {{
    background: {t.surface};
    alternate-background-color: {t.surface_alt};
    border: 1px solid {t.border};
    border-radius: {t.radius}px;
    gridline-color: {t.border};
    selection-background-color: {t.primary_weak};
    selection-color: {t.text};
    outline: none;
}}
QTableView::item, QTreeView::item {{
    padding: 4px 6px;
    border: none;
}}
/* 选中行：整行淡主色 + 左侧主色竖条，一眼能看出选的是哪一行。
   注意必须显式写 :selected —— 一旦用 QSS 定制了 ::item，默认选中底色就不再绘制，
   这也是"单击一行看不出变化"的根因。 */
QTableView::item:selected, QTreeView::item:selected, QListView::item:selected {{
    background: {t.selection};
    color: {t.text};
    border-left: 3px solid {t.primary};
}}
QTableView::item:selected:!active, QTreeView::item:selected:!active,
QListView::item:selected:!active {{
    background: {t.surface_alt};
    color: {t.text_muted};
    border-left: 3px solid {t.border_strong};
}}
QHeaderView::section {{
    background: {t.surface_alt};
    color: {t.text_muted};
    border: none;
    border-bottom: 1px solid {t.border};
    padding: 6px 8px;
    font-weight: 600;
}}
QTableCornerButton::section {{
    background: {t.surface_alt};
    border: none;
}}

/* ---------------- 滚动条 ---------------- */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {t.border_strong};
    border-radius: 5px;
    min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background: {t.text_faint}; }}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {t.border_strong};
    border-radius: 5px;
    min-width: 28px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---------------- 其它 ---------------- */
QScrollArea {{ border: none; background: transparent; }}
QSplitter::handle {{ background: {t.bg}; }}
QSplitter::handle:horizontal {{ width: 8px; }}
QSplitter::handle:hover {{ background: {t.border}; }}
QProgressBar {{
    background: {t.surface_alt};
    border: none;
    border-radius: 5px;
    height: 10px;
    text-align: center;
}}
QProgressBar::chunk {{
    background: {t.primary};
    border-radius: 5px;
}}
QTabWidget::pane {{
    border: 1px solid {t.border};
    border-radius: {t.radius}px;
    background: {t.surface};
}}
QTabBar::tab {{
    background: transparent;
    color: {t.text_muted};
    padding: 7px 16px;
    border: none;
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:selected {{
    color: {t.primary};
    border-bottom: 2px solid {t.primary};
    font-weight: 700;
}}
QMenu {{
    background: {t.surface};
    border: 1px solid {t.border};
    border-radius: {t.radius}px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 24px 6px 20px;
    border-radius: 6px;
}}
QMenu::item:selected {{
    background: {t.primary_weak};
    color: {t.text};
}}
QMenu::separator {{
    height: 1px;
    background: {t.border};
    margin: 4px 8px;
}}
QMessageBox, QFileDialog {{ background: {t.bg}; }}
"""


def _build_palette(theme: Theme) -> QPalette:
    """同步原生绘制的调色板（工具提示、滚动条箭头等）。"""
    pal = QPalette()
    pal.setColor(QPalette.Window, theme.color("bg"))
    pal.setColor(QPalette.WindowText, theme.color("text"))
    pal.setColor(QPalette.Base, theme.color("surface"))
    pal.setColor(QPalette.AlternateBase, theme.color("surface_alt"))
    pal.setColor(QPalette.Text, theme.color("text"))
    pal.setColor(QPalette.Button, theme.color("surface_alt"))
    pal.setColor(QPalette.ButtonText, theme.color("text"))
    pal.setColor(QPalette.Highlight, theme.color("primary"))
    pal.setColor(QPalette.HighlightedText, theme.color("text_inverse"))
    pal.setColor(QPalette.ToolTipBase, theme.color("surface"))
    pal.setColor(QPalette.ToolTipText, theme.color("text"))
    pal.setColor(QPalette.PlaceholderText, theme.color("text_faint"))
    pal.setColor(QPalette.Disabled, QPalette.Text, theme.color("text_faint"))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, theme.color("text_faint"))
    pal.setColor(QPalette.Disabled, QPalette.WindowText, theme.color("text_faint"))
    return pal


def apply_theme(app, mode: str = "system") -> Theme:
    """把主题应用到 ``QApplication``，返回实际生效的主题对象。"""
    theme = theme_for(mode)
    try:
        app.setStyleSheet(build_stylesheet(theme))
        app.setPalette(_build_palette(theme))
    except Exception:
        pass
    try:
        app.setProperty("paperdrill_theme", theme.name)
    except Exception:
        pass
    return theme


def theme_field_names() -> Iterable[str]:
    """令牌字段名（测试用来断言两套主题字段齐全）。"""
    return tuple(f.name for f in fields(Theme) if f.name not in ("name", "dark"))
