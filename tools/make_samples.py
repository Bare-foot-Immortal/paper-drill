# -*- coding: utf-8 -*-
"""生成示例题库与集成测试夹具（全部为合成内容，可安全公开）。

用法：
    python tools/make_samples.py                  # 同时生成 samples/ 与 fixtures/
    python tools/make_samples.py --fixtures-only  # 只生成集成测试夹具
    python tools/make_samples.py --out 目录 --fixtures 目录

产物：
    samples/示例题库.csv / .txt / .json        —— 用户可直接导入的示例（文本格式）
    fixtures/样例题库.xlsx                     —— 标准表格题库（26/14/12 布局用的小样：8/5/4）
    fixtures/样例A_段落文本型.docx              —— 答案嵌在题干括号、选项分行
    fixtures/样例B_选项同行.docx                —— 选项写在同一行
    fixtures/样例C_题干答案分行.docx            —— 「题干：/答案：/来源：」版式
    fixtures/样例D_选项无分隔符.docx            —— （  BCE ）+ `A明确…` 无分隔符 + 粘连行
    fixtures/样例E_表格型.docx                  —— Word 表格 + 选项合并在一列
    fixtures/样例题库.pdf                      —— 由样例 A 渲染的文本型 PDF（需 reportlab）
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------- 合成题目数据
# 全部为原创的通用示例题（不含任何真实单位或真实题库内容），可安全公开。
SCENES = [
    "钢筋绑扎", "模板安装", "混凝土浇筑", "脚手架搭设", "起重吊装", "临时用电", "基坑开挖",
    "防水施工", "砌体工程", "抹灰工程", "管道安装", "电气安装", "通风空调", "焊接作业",
    "防腐作业", "保温作业", "装饰装修", "屋面工程", "幕墙安装", "消防设施安装",
    "电梯安装", "智能建筑施工", "园林绿化", "道路施工", "桥梁施工", "隧道施工",
]

_SINGLE_CORRECT = "完成专项方案审批与安全技术交底"
_SINGLE_OTHERS = ["先行安排材料进场验收", "直接组织班组开始作业", "等待建设单位口头同意"]

SINGLE: list[tuple[str, list[str], str]] = []
for _i, _scene in enumerate(SCENES):
    _k = _i % 4
    _opts = _SINGLE_OTHERS[:_k] + [_SINGLE_CORRECT] + _SINGLE_OTHERS[_k:]
    SINGLE.append((f"{_scene}作业开始前，应当首先完成的工作是？", _opts, "ABCD"[_k]))

MULTIPLE = [
    ("施工现场安全检查应当重点关注的内容包括哪些？",
     ["安全防护设施是否齐全", "临时用电是否规范", "作业人员是否持证", "当日材料价格"], "ABC"),
    ("施工技术交底通常应当包含哪些内容？",
     ["施工工艺流程", "质量标准要求", "安全技术措施", "设备采购品牌"], "ABC"),
    ("质量验收记录一般应当包括哪些要素？",
     ["检查项目", "检查结果", "检查人员签字", "当天天气情况"], "ABC"),
    ("属于危险性较大的分部分项工程的有哪些？",
     ["基坑工程", "模板工程及支撑体系", "起重吊装及安装拆卸工程", "脚手架工程"], "ABCD"),
    ("材料进场验收需要核查的资料包括哪些？",
     ["产品合格证", "出厂检验报告", "外观质量检查记录", "运输车辆行驶证"], "ABC"),
    ("隐蔽工程验收前应当完成哪些准备工作？",
     ["施工完成并自检合格", "相关资料准备齐全", "通知相关单位参加", "先行覆盖掩埋"], "ABC"),
    ("施工现场常见的个人劳动防护用品有哪些？",
     ["安全帽", "安全带", "防护手套", "安全鞋"], "ABCD"),
    ("发生生产安全事故后，现场处置应当包括哪些环节？",
     ["立即抢救受伤人员", "保护事故现场", "及时上报有关部门", "自行处理后不再上报"], "ABC"),
    ("施工测量复核工作一般包括哪些内容？",
     ["控制点复核", "轴线与标高复核", "测量记录归档", "设备租赁合同"], "ABC"),
    ("成品保护措施通常包括哪些做法？",
     ["覆盖遮挡", "设置警示标识", "安排专人看护", "提前拆除周转设施"], "ABC"),
    ("工程资料归档应当满足哪些要求？",
     ["内容真实完整", "签字手续齐全", "分类组卷清楚", "可以事后补签"], "ABC"),
    ("应急预案演练应当达到哪些目的？",
     ["检验预案可行性", "磨合应急队伍", "完善处置流程", "替代现场安全检查"], "ABC"),
    ("施工现场环境管理措施包括哪些？",
     ["控制扬尘", "控制噪声", "规范废弃物处置", "夜间无限制连续施工"], "ABC"),
    ("构架吊装就位过程中，应向杯口四周放入（ ）个木楔，并使构件基本（ ）后才能摘钩。",
     ["3～4", "5～6", "垂直", "倾斜"], "BC"),
]

JUDGE = [
    ("未经技术论证擅自压缩合同约定工期，属于重大事故隐患。", "正确"),
    ("可以在电缆沟内充装并存放易燃易爆危险物品。", "错误"),
    ("作业开始前应当对作业人员进行安全技术交底并留有记录。", "正确"),
    ("隐蔽工程可以不经检查验收直接进入下一道工序。", "错误"),
    ("施工中发现设计图纸与现场情况不符时，应当及时上报处理。", "正确"),
    ("特种作业人员可以不取得资格证书直接上岗作业。", "错误"),
    ("进场材料应当按规定进行检验，检验合格后方可使用。", "正确"),
    ("安全防护设施可以根据施工需要随时拆除且无需恢复。", "错误"),
    ("施工日志应当如实记录当天的施工与检查情况。", "正确"),
    ("质量验收不合格的工序可以直接进入下一道工序施工。", "错误"),
    ("施工现场的临时用电应当符合用电安全技术规范要求。", "正确"),
    ("危险性较大的分部分项工程施工时可以不安排专人现场监督。", "错误"),
]

FIXED_INDEX = len(MULTIPLE) - 1      # 最后一道多选为「（定）」固定顺序题


def _types() -> dict:
    from collections import OrderedDict
    return OrderedDict([("单选", SINGLE), ("多选", MULTIPLE), ("判断", JUDGE)])


# ---------------------------------------------------------------- 表格类产物
def _rows() -> list[list]:
    rows = [["题型", "题目标题", "选项A", "选项B", "选项C", "选项D", "解析", "答案"]]
    for stem, opts, ans in SINGLE:
        rows.append(["单选题", stem, *opts, "见相关施工规范。", ans])
    for i, (stem, opts, ans) in enumerate(MULTIPLE):
        answer = f"{ans}（定）" if i == FIXED_INDEX else ans
        rows.append(["多选题", stem, *opts, "见相关施工规范。", answer])
    for stem, ans in JUDGE:
        rows.append(["判断题", stem, "", "", "", "", "见相关管理规定。", ans])
    return rows


def write_xlsx(path: Path) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "题库"
    for row in _rows():
        ws.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def write_csv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        csv.writer(fh).writerows(_rows())


def write_txt(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["\t".join(str(c) for c in row) for row in _rows()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_json(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = _rows()[0]
    data = [dict(zip(header, row)) for row in _rows()[1:]]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_dict_json(path: Path) -> None:
    """英文键版本（等价写法，便于脚本处理）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    items = []
    for row in _rows()[1:]:
        qtype, stem = row[0], row[1]
        opts = {f"option{lab}": row[2 + i] for i, lab in enumerate("ABCD") if row[2 + i]}
        items.append({"type": qtype, "stem": stem, **opts,
                      "analysis": row[6], "answer": row[7]})
    path.write_text(json.dumps({"questions": items}, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


# ---------------------------------------------------------------- Word 夹具
def _docx_new():
    from docx import Document

    return Document()


def _numbered(stem: str, ans: str) -> str:
    """合成段落型题面：把答案嵌进题干括号（题干已有空括号则填入）。"""
    if "（ ）" in stem:
        return stem.replace("（ ）", f"（{ans}）")
    if "（" in stem:
        return stem
    return f"{stem}（{ans}）。"


def write_docx_paragraph_style(path: Path) -> list[str]:
    """样例A：章节标题 + 答案嵌在题干括号 + 选项分行。返回纯文本行（供 PDF 复用）。"""
    doc = _docx_new()
    lines = ["合成示例题库（段落文本型）", "一、单项选择题"]
    doc.add_paragraph(lines[0])
    doc.add_paragraph(lines[1])
    for i, (stem, opts, ans) in enumerate(SINGLE[:4], start=1):
        block = [f"{i}、{_numbered(stem, ans)}"] + [f"{lab}.{o}" for lab, o in zip("ABCD", opts)]
        for line in block:
            doc.add_paragraph(line)
        lines.extend(block)
    lines.append("二、多项选择题")
    doc.add_paragraph(lines[-1])
    for i, (stem, opts, ans) in enumerate(MULTIPLE[:2], start=1):
        block = [f"{i}、{_numbered(stem, ans)}"] + [f"{lab}.{o}" for lab, o in zip("ABCD", opts)]
        for line in block:
            doc.add_paragraph(line)
        lines.extend(block)
    lines.append("三、判断题")
    doc.add_paragraph(lines[-1])
    for i, (stem, ans) in enumerate(JUDGE[:2], start=1):
        mark = "√" if ans == "正确" else "×"
        line = f"{i}、{stem}（{mark}）"
        doc.add_paragraph(line)
        lines.append(line)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    return lines


def write_docx_inline_options(path: Path) -> None:
    """样例B：选项写在同一行（空格分隔）。"""
    doc = _docx_new()
    doc.add_paragraph("一、单项选择题")
    for i, (stem, opts, ans) in enumerate(SINGLE[:3], start=1):
        doc.add_paragraph(f"{i}、{_numbered(stem, ans)}")
        doc.add_paragraph("    ".join(f"{lab}.{o}" for lab, o in zip("ABCD", opts)))
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))


def write_docx_answer_lines(path: Path) -> None:
    """样例C：题干：/选项一行/答案：/来源："""
    doc = _docx_new()
    doc.add_paragraph("第一部分 单项选择题")
    for stem, opts, ans in SINGLE[:3]:
        doc.add_paragraph(f"题干：{stem}")
        doc.add_paragraph(" ".join(f"{lab}.{o}" for lab, o in zip("ABCD", opts)))
        doc.add_paragraph(f"答案：{ans}")
        doc.add_paragraph("来源：《合成示例管理规定》-第一章第一条")
    doc.add_paragraph("第二部分 多项选择题")
    stem, opts, ans = MULTIPLE[0]
    doc.add_paragraph(f"题干：{stem}")
    doc.add_paragraph(" ".join(f"{lab}.{o}" for lab, o in zip("ABCD", opts)))
    doc.add_paragraph(f"答案：{ans}")
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))


def write_docx_no_separator_options(path: Path) -> None:
    """样例D：（  BCE ）带空格答案 + 选项无分隔符 + 尾行粘连下一题。"""
    doc = _docx_new()
    doc.add_paragraph("二、多项选择题练习")
    doc.add_paragraph("1.下列关于施工现场管理要求的表述中（  ABC  ）应当重点关注。")
    doc.add_paragraph("A正确佩戴防护用品    B落实技术交底    C执行验收程序    D忽略隐患")
    doc.add_paragraph("2.施工准备阶段需要完成的重点工作包括（  ABD  ）。")
    doc.add_paragraph("A方案审批    B材料检验    C随意变更    D人员交底")
    doc.add_paragraph("3.下列属于质量通病防治内容的是（  BCE  ）")
    doc.add_paragraph("A明确质量管理内容")
    doc.add_paragraph("B明确质量责任分工")
    doc.add_paragraph("C建立质量例会制度")
    doc.add_paragraph("D简化验收流程")
    doc.add_paragraph("E完善质量记录")
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))


def write_docx_table(path: Path) -> None:
    """样例E：Word 表格，选项合并在一列。"""
    doc = _docx_new()
    table = doc.add_table(rows=1, cols=4)
    for i, text in enumerate(["题型", "题目标题", "选项", "答案"]):
        table.cell(0, i).text = text
    for stem, opts, ans in SINGLE[:3]:
        cells = table.add_row().cells
        cells[0].text = "单选题"
        cells[1].text = stem
        cells[2].text = " ".join(f"{lab}.{o}" for lab, o in zip("ABCD", opts))
        cells[3].text = ans
    cells = table.add_row().cells
    cells[0].text = "多选题"
    cells[1].text = MULTIPLE[0][0]
    cells[2].text = " ".join(f"{lab}.{o}" for lab, o in zip("ABCD", MULTIPLE[0][1]))
    cells[3].text = MULTIPLE[0][2] + "（定）"
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))


def write_pdf(path: Path, lines: list[str]) -> bool:
    """把文本行渲染为「Word 导出型」文本 PDF；缺 reportlab 时跳过。"""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.pdfgen import canvas
    except ImportError:
        print("[跳过] 未安装 reportlab，未生成 PDF 夹具。")
        return False

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = A4
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setTitle("合成示例题库")
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
    return True


# ---------------------------------------------------------------- 入口
def build_samples(out: Path) -> None:
    write_xlsx(out / "示例题库.xlsx")
    write_csv(out / "示例题库.csv")
    write_txt(out / "示例题库.txt")
    write_json(out / "示例题库.json")
    write_dict_json(out / "示例题库_英文键.json")
    write_pdf(out / "示例题库.pdf", _pdf_lines())
    print(f"[OK] 示例题库已生成：{out}")


def _pdf_lines() -> list[str]:
    """「Word 导出型」PDF 示例的文本行：题干/答案分行，含一道判断题与一道「（定）」题。"""
    lines = ["合成示例题库（PDF 版）", "一、单项选择题"]
    for i, (stem, opts, ans) in enumerate(SINGLE[:5], start=1):
        lines.append(f"题干：{stem}")
        lines.append(" ".join(f"{lab}.{o}" for lab, o in zip("ABCD", opts)))
        lines.append(f"答案：{ans}")
        lines.append("来源：《合成示例管理规定》")
    lines.append("二、多项选择题")
    for i, idx in enumerate([0, 1, FIXED_INDEX], start=1):     # 第 3 道为「（定）」固定顺序题
        stem, opts, ans = MULTIPLE[idx]
        lines.append(f"题干：{stem}")
        lines.append(" ".join(f"{lab}.{o}" for lab, o in zip("ABCD", opts)))
        lines.append(f"答案：{ans}{'（定）' if i == 3 else ''}")
    lines.append("三、判断题")
    for stem, ans in JUDGE[:2]:
        lines.append(f"题干：{stem}")
        lines.append(f"答案：{ans}")
    return lines


def build_fixtures(fix: Path) -> None:
    write_xlsx(fix / "样例题库.xlsx")
    write_docx_paragraph_style(fix / "样例A_段落文本型.docx")
    write_docx_inline_options(fix / "样例B_选项同行.docx")
    write_docx_answer_lines(fix / "样例C_题干答案分行.docx")
    write_docx_no_separator_options(fix / "样例D_选项无分隔符.docx")
    write_docx_table(fix / "样例E_表格型.docx")
    write_pdf(fix / "样例题库.pdf", _pdf_lines())
    print(f"[OK] 测试夹具已生成：{fix}")


def main() -> int:
    ap = argparse.ArgumentParser(description="生成示例题库与测试夹具")
    ap.add_argument("--out", default="samples", help="示例输出目录（默认 samples/）")
    ap.add_argument("--fixtures", default="fixtures", help="夹具输出目录（默认 fixtures/）")
    ap.add_argument("--fixtures-only", action="store_true", help="只生成夹具")
    ap.add_argument("--samples-only", action="store_true", help="只生成文本示例")
    args = ap.parse_args()

    if not args.fixtures_only:
        build_samples(ROOT / args.out)
    if not args.samples_only:
        build_fixtures(ROOT / args.fixtures)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
