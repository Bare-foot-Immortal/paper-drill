# -*- coding: utf-8 -*-
"""生成刷题匠 PaperDrill 图标 assets/PaperDrill.ico（构建期使用）。

青绿配色 + 白色答题卡 + 对勾，与组卷版 PaperForge 的蓝色图标区分。
缺少 Pillow 或中文字体时跳过（打包脚本会退化为默认图标）。
"""
from __future__ import annotations

import sys
from pathlib import Path


def _force_utf8() -> None:
    """Windows 控制台/CI 下强制 UTF-8 输出，避免中文打印触发 UnicodeEncodeError。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")     # type: ignore[union-attr]
        except Exception:
            pass


_force_utf8()


ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "PaperDrill.ico"

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
]


def main() -> int:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("[跳过] 未安装 Pillow，将使用默认图标。")
        return 0

    font_path = next((p for p in FONT_CANDIDATES if Path(p).exists()), None)
    base = 256
    img = Image.new("RGBA", (base, base), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 背景：青绿渐变
    for i in range(base):
        t = i / base
        d.line([(0, i), (base, i)], fill=(int(9 + 20 * t), int(120 + 60 * t), int(110 + 45 * t), 255))
    mask = Image.new("L", (base, base), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, base - 1, base - 1], radius=52, fill=255)
    img.putalpha(mask)

    # 白色答题卡
    d.rounded_rectangle([46, 40, 210, 216], radius=14, fill=(255, 255, 255, 255))
    # 选项行
    for i, y in enumerate(range(70, 150, 26)):
        # 选项框
        d.rounded_rectangle([62, y, 82, y + 20], radius=5, outline=(120, 160, 175, 255), width=3)
        # 文字行
        d.rounded_rectangle([92, y + 6, 190 - i * 14, y + 14], radius=4, fill=(150, 180, 195, 255))
    # 已勾选的两行（模拟刷题进度）
    d.line([(64, 78), (71, 85), (80, 68)], fill=(28, 165, 90, 255), width=5)
    d.line([(64, 130), (71, 137), (80, 120)], fill=(28, 165, 90, 255), width=5)

    # 主标题字
    if font_path:
        try:
            font = ImageFont.truetype(font_path, 86)
            d.text((base / 2, 186), "练", font=font, fill=(9, 105, 100, 255), anchor="mm")
        except Exception:
            pass

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    print(f"[OK] 图标已生成：{OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
