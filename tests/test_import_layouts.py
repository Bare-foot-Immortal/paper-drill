# -*- coding: utf-8 -*-
"""Excel / CSV 题库「非示例排布」兼容性测试。

覆盖用户实际会遇到的整理差异：首行大标题、列头不在第一行、列顺序打乱、
选项列乱序、单列「选项」、缺「题型」列、列头写法变体、多工作表、无列头等。

运行：python -m unittest tests.test_import_layouts -v
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from paperdrill.bank_io import load_bank                       # noqa: E402
from paperdrill.models import QType                            # noqa: E402

HEADER = ["题型", "题目标题", "选项A", "选项B", "选项C", "选项D", "解析", "答案"]
DATA = [
    ["单选题", "题目一是什么？", "甲", "乙", "丙", "丁", "解析一", "B"],
    ["多选题", "题目二有哪些？", "甲", "乙", "丙", "丁", "解析二", "AC（定）"],
    ["判断题", "题目三正确吗？", "", "", "", "", "解析三", "正确"],
]


class LayoutCase(unittest.TestCase):
    """把 xlsx / csv 构造与断言收在一起。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="pd_layout_")
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def xlsx(self, name: str, rows: list[list], sheets: "dict[str, list[list]] | None" = None) -> Path:
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = "题库"
        for row in rows:
            ws.append(row)
        for title, content in (sheets or {}).items():
            extra = wb.create_sheet(title)
            for row in content:
                extra.append(row)
        path = self.dir / f"{name}.xlsx"
        wb.save(path)
        return path

    def csv(self, name: str, rows: list[list], delim: str = ",") -> Path:
        path = self.dir / f"{name}.csv"
        path.write_text("\n".join(delim.join(str(c) for c in row) for row in rows), encoding="utf-8-sig")
        return path

    def load(self, path: Path):
        return load_bank(path)

    def assert_ok(self, path: Path, count: int = 3, header_row: "int | None" = None,
                  kinds: str = "judge,multiple,single"):
        res = self.load(path)
        self.assertEqual(len(res.issues), 0, f"不应有坏行：{res.issues[:2]}")
        self.assertEqual(len(res.questions), count, f"题数不符：{[q.stem for q in res.questions]}")
        got = ",".join(sorted({q.qtype.key for q in res.questions}))
        self.assertEqual(got, kinds)
        if header_row is not None:
            self.assertEqual(res.column_map.get("header_row"), header_row - 1,
                             "列头行号不符合预期")
        return res


# ================================================================ 列头位置
class TestHeaderPosition(LayoutCase):
    def test_standard(self):
        self.assert_ok(self.xlsx("std", [HEADER] + DATA), header_row=1)

    def test_title_row_first(self):
        """首行是题库标题（不是列头），列头在第 2 行。"""
        self.assert_ok(self.xlsx("title", [["2026 年安全知识题库"], HEADER] + DATA), header_row=2)

    def test_title_and_blank_rows(self):
        """标题 + 空行，列头在第 3 行。"""
        self.assert_ok(self.xlsx("blank", [["某单位题库"], [], HEADER] + DATA), header_row=3)

    def test_header_at_row_7(self):
        """列头在第 7 行（原实现只扫前 5 行，会退化为按位置猜）。"""
        rows = [["题库说明"] for _ in range(6)] + [HEADER] + DATA
        self.assert_ok(self.xlsx("row7", rows), header_row=7)

    def test_header_at_row_15(self):
        rows = [[f"说明第 {i} 行"] for i in range(1, 15)] + [HEADER] + DATA
        self.assert_ok(self.xlsx("row15", rows), header_row=15)

    def test_multiple_sheets_picks_bank_sheet(self):
        """第一个工作表是说明页，题库在第二张表。"""
        res = self.assert_ok(self.xlsx("multi", [["使用说明"], ["1. 本表为说明"]],
                                       sheets={"题库数据": [HEADER] + DATA}), header_row=1)
        self.assertEqual(res.sheet, "题库数据")

    def test_no_header_standard_layout(self):
        """完全没有列头行，按标准 12 列位置回退。"""
        rows = [[r[0], r[1], r[2], r[3], r[4], r[5], "", "", "", "", r[6], r[7]] for r in DATA]
        res = self.load(self.xlsx("nohdr", rows))
        self.assertEqual(len(res.questions), 3)
        self.assertEqual(len(res.issues), 0)


# ================================================================ 列顺序
class TestColumnOrder(LayoutCase):
    def test_reordered_columns(self):
        """答案/解析在前，选项与题干在后 → 按列名映射，顺序无关。"""
        rows = [["答案", "解析", "题型", "选项D", "选项C", "选项B", "选项A", "题目标题"]] + [
            [r[7], r[6], r[0], r[5], r[4], r[3], r[2], r[1]] for r in DATA]
        res = self.assert_ok(self.xlsx("order", rows), header_row=1)
        self.assertEqual(res.questions[1].answer_letters, ["A", "C"])
        self.assertEqual(res.questions[1].options, ["甲", "乙", "丙", "丁"])

    def test_option_columns_out_of_order(self):
        """选项C 排在 选项A 前面，选项文本仍要按 A/B/C/D 归位。"""
        rows = [["题型", "题目标题", "选项C", "选项A", "选项D", "选项B", "解析", "答案"]] + [
            [r[0], r[1], r[4], r[2], r[5], r[3], r[6], r[7]] for r in DATA]
        res = self.assert_ok(self.xlsx("optorder", rows), header_row=1)
        self.assertEqual(res.questions[0].options, ["甲", "乙", "丙", "丁"])

    def test_type_column_last(self):
        rows = [["题目标题", "选项A", "选项B", "选项C", "选项D", "解析", "答案", "题型"]] + [
            [r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[0]] for r in DATA]
        self.assert_ok(self.xlsx("typelast", rows), header_row=1)


# ================================================================ 列头写法
class TestHeaderWording(LayoutCase):
    def test_english_headers(self):
        rows = [["type", "stem", "optionA", "optionB", "optionC", "optionD", "answer", "analysis"]] + [
            [r[0], r[1], r[2], r[3], r[4], r[5], r[7], r[6]] for r in DATA]
        self.assert_ok(self.xlsx("en", rows), header_row=1)

    def test_fullwidth_and_newline_headers(self):
        rows = [["题 型", "题干\n题目", "选项 A", "选项Ｂ", "选项C ", " 选项D", "解析", "答案 "]] + DATA
        self.assert_ok(self.xlsx("fw", rows), header_row=1)

    def test_option1_digit_headers(self):
        rows = [["题型", "题目标题", "选项1", "选项2", "选项3", "选项4", "解析", "答案"]] + DATA
        self.assert_ok(self.xlsx("digit", rows), header_row=1)

    def test_letter_suffix_headers(self):
        rows = [["题目类型", "题干", "A选项", "选项 B", "C、", "选项D", "答案解析", "正确答案"]] + DATA
        self.assert_ok(self.xlsx("affix", rows), header_row=1)

    def test_type_with_suffix_note(self):
        rows = [HEADER] + [
            ["单选题（每题1分）", "题目一是什么？", "甲", "乙", "丙", "丁", "解析一", "B"],
            ["多选题（少选不得分）", "题目二有哪些？", "甲", "乙", "丙", "丁", "解析二", "AC（定）"],
            ["判断题", "题目三正确吗？", "", "", "", "", "解析三", "正确"]]
        self.assert_ok(self.xlsx("note", rows), header_row=1)


# ================================================================ 单列选项 / 缺题型
class TestFallbacks(LayoutCase):
    def test_single_combined_option_column(self):
        """选项全部写在一列（`A.甲 B.乙 C.丙 D.丁`）→ 自动展开。"""
        rows = [["题型", "题目标题", "选项", "答案"],
                ["单选题", "题目一是什么？", "A.甲 B.乙 C.丙 D.丁", "B"],
                ["多选题", "题目二有哪些？", "A.甲   B.乙   C.丙   D.丁", "AC（定）"]]
        res = self.assert_ok(self.xlsx("combo", rows), count=2, header_row=1,
                             kinds="multiple,single")
        self.assertEqual(res.questions[0].options, ["甲", "乙", "丙", "丁"])
        self.assertTrue(res.questions[1].fixed_order, "「（定）」标记必须保留")

    def test_missing_type_column_inferred(self):
        """没有「题型」列 → 由答案形态推断（多字母→多选、√→判断、单字母→单选）。"""
        rows = [["题目标题", "选项A", "选项B", "选项C", "选项D", "答案"]] + [
            [r[1], r[2], r[3], r[4], r[5], r[7]] for r in DATA]
        res = self.assert_ok(self.xlsx("notype", rows), header_row=1)
        self.assertEqual([q.qtype for q in res.questions],
                         [QType.SINGLE, QType.MULTIPLE, QType.JUDGE])

    def test_missing_type_column_judge_without_options(self):
        rows = [["题目", "答案"],
                ["未经论证压缩工期属于重大事故隐患。", "√"],
                ["可以在电缆沟内充装易燃易爆危险品。", "×"]]
        res = self.assert_ok(self.xlsx("judgeonly", rows), count=2, header_row=1, kinds="judge")
        self.assertTrue(res.questions[0].judge_answer)
        self.assertFalse(res.questions[1].judge_answer)

    def test_wrong_type_text_still_reported(self):
        """题型列写了无法识别的值 → 仍要报错，不能被答案推断掩盖。"""
        rows = [HEADER, ["选择题", "题目一是什么？", "甲", "乙", "丙", "丁", "解析一", "B"]]
        res = self.load(self.xlsx("badtype", rows))
        self.assertEqual(len(res.questions), 0)
        self.assertEqual(len(res.issues), 1)
        self.assertIn("题型无法识别", str(res.issues[0]))

    def test_choice_without_option_columns_reported_clearly(self):
        """无选项列的单选题无法作答 → 拒绝并给出可读原因（判断题仍收录）。"""
        rows = [["题型", "题干", "答案"]] + [[r[0], r[1], r[7]] for r in DATA]
        res = self.load(self.xlsx("noopt", rows))
        self.assertEqual(len(res.questions), 1)
        self.assertIs(res.questions[0].qtype, QType.JUDGE)
        self.assertEqual(len(res.issues), 2)
        self.assertIn("缺少选项", str(res.issues[0]))


# ================================================================ 其它格式
class TestOtherFormats(LayoutCase):
    def test_csv_reordered_columns(self):
        """CSV 与 Excel 共用同一套映射，顺序打乱同样可识别。"""
        rows = [["答案", "题干", "类型", "B", "A", "C", "D"]] + [
            [r[7], r[1], r[0], r[3], r[2], r[4], r[5]] for r in DATA]
        res = self.load(self.csv("order", rows))
        self.assertEqual(len(res.questions), 3)
        self.assertEqual(len(res.issues), 0)

    def test_csv_single_combined_option(self):
        rows = [["题型", "题干", "选项", "答案"],
                ["单选题", "题目一？", "A.甲 B.乙 C.丙 D.丁", "D"],
                ["多选题", "题目二？", "A.甲 B.乙 C.丙 D.丁", "AB"]]
        res = self.load(self.csv("combo", rows))
        self.assertEqual(len(res.questions), 2)
        self.assertEqual(res.questions[0].options, ["甲", "乙", "丙", "丁"])
        self.assertEqual(res.questions[1].answer_letters, ["A", "B"])

    def test_real_bank_still_works(self):
        """真实 52 题题库（标准列头）不得因本轮放宽而回归。"""
        candidates = [ROOT.parent / "例" / "样例题库.xlsx",
                      ROOT.parent / "样例题库.xlsx"]
        bank = next((c for c in candidates if c.exists()), None)
        if bank is None:
            self.skipTest("未找到合成题库")
        res = self.load(bank)
        self.assertEqual(len(res.questions), 163)
        self.assertEqual(len(res.issues), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
