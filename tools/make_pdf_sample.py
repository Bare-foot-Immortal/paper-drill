# -*- coding: utf-8 -*-
"""生成 PDF 测试样例（模拟"Word 导出的文本型 PDF"）。

用途：PDF 导入功能的测试夹具（fixture）。构建期运行一次，产物提交到 samples/，
测试只读取产物，不需要 reportlab。

用法：
    python tools/make_pdf_sample.py            # 用内置题库内容生成 samples/示例题库.pdf
    python tools/make_pdf_sample.py --from-docx fixtures/样例A_段落文本型.docx
"""
from __future__ import annotations

import sys

import argparse
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

BUILTIN_LINES = [
    "示例题库（PDF 版）",
    "一、单项选择题",
    "1、深基坑工程中，开挖深度超过（A）米（含）的基坑（槽）支护、降水工程属于危大工程？",
    "A.3",
    "B.5",
    "C.7",
    "D.10",
    "2、模板工程及支撑体系中，搭设高度超过（B）米（含）的混凝土模板支撑工程需组织专家论证？",
    "A.5",
    "B.8",
    "C.10",
    "D.12",
    "二、多项选择题",
    "1、下列属于深基坑工程危大工程的有（ABCD）？",
    "A.开挖深度超过 3 米的基坑支护",
    "B.开挖深度超过 5 米的基坑支护",
    "C.地下暗挖工程",
    "D.顶管工程",
    "2、危大工程安全技术交底的内容应包括（ABC）？",
    "A.施工方法", "B.安全技术措施", "C.应急处置措施", "D.财务预算方案",
    "3、构支架吊装时，当柱脚接近杯底时，应从柱四周向杯口放入（ ）个木楔，"
    "同时收紧四周缆风绳，确认缆风绳全部固定并使立柱基本（ ）后，才能松大钩。",
    "A.3～4", "B.4～5", "C.垂直", "D.平行",
    "答案：BC（定）",
    "三、判断题",
    "1、未经论证的情况下压缩合同约定工期，属于重大事故隐患。（√）",
    "2、可以在电缆沟内充装易燃易爆危险品。（×）",
    "3、施工单位应当对危大工程进行施工监测和安全巡视。（正确）",
]


def build_pdf(lines: list[str], out: Path, *, title: str = "示例题库") -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    out.parent.mkdir(parents=True, exist_ok=True)

    width, height = A4
    c = canvas.Canvas(str(out), pagesize=A4)
    c.setTitle(title)
    c.setFont("STSong-Light", 10.5)
    y = height - 50
    for line in lines:
        if y < 50:
            c.showPage()
            c.setFont("STSong-Light", 10.5)
            y = height - 50
        c.drawString(50, y, line)
        y -= 16
    c.save()
    return out


def docx_lines(path: Path) -> list[str]:
    from docx import Document

    doc = Document(str(path))
    lines: list[str] = []
    for p in doc.paragraphs:
        text = p.text.strip()
        if text:
            lines.extend(part.strip() for part in text.split("\n") if part.strip())
    return lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-docx", default="", help="从 docx 取文本再渲染成 PDF")
    ap.add_argument("--out", default="samples/示例题库.pdf")
    args = ap.parse_args()

    if args.from_docx:
        src = Path(args.from_docx)
        if not src.is_absolute():
            src = ROOT / src
        lines = docx_lines(src)
        title = src.stem
    else:
        lines = BUILTIN_LINES
        title = "示例题库"

    out = ROOT / args.out
    build_pdf(lines, out, title=title)
    print(f"[OK] PDF 样例已生成：{out}（{len(lines)} 行，{out.stat().st_size} 字节）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
