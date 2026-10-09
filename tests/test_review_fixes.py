# -*- coding: utf-8 -*-
"""代码审查（Agent Team）发现问题的回归测试。

每个用例对应一条被确认的缺陷，防止修复后再次回归：
解析层：无章节标题时单选被误判判断 / 无列头乱猜列 / 表头下方合并列 / 答案行写法 / 粘连短题干；
存储层：损坏进度文件拖垮全库 / 删题后进度归零 / 脏 session 崩溃 / 保存失败不可见。
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from openpyxl import Workbook  # noqa: E402

from paperdrill.bank_io import TextLine, lines_to_questions, load_bank  # noqa: E402
from paperdrill.models import QType  # noqa: E402
from paperdrill.practice import PracticeMode, PracticeSession  # noqa: E402
from paperdrill.store import ProgressStore  # noqa: E402

FIXTURE_BANK = ROOT / "fixtures" / "样例题库.xlsx"


def xlsx(path: Path, rows: list[list]) -> Path:
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


HEADER12 = ["题型", "题目标题", "选项A", "选项B", "选项C", "选项D", "解析", "答案"]


def bank_rows(n: int, start: int = 0) -> list[list]:
    return [HEADER12] + [["单选题", f"题目{i}", "甲", "乙", "丙", "丁", "", "A"]
                         for i in range(start, start + n)]


# ================================================================ 解析层
class TestParserReviewFixes(unittest.TestCase):
    def test_letter_answer_without_section_is_single_choice(self):
        """无章节标题时，答案 `（B）` 不得把单选题误判为判断题（并丢掉选项）。"""
        qs, issues, _ = lines_to_questions([
            TextLine("1、模板安装作业开始前应当首先完成的工作是（B）。"),
            TextLine("A.先行安排材料验收    B.完成方案审批与安全技术交底"),
            TextLine("C.直接组织班组作业    D.等待口头同意")])
        self.assertEqual(issues, [])
        self.assertEqual(len(qs), 1)
        self.assertIs(qs[0].qtype, QType.SINGLE)
        self.assertEqual(len(qs[0].options), 4)
        self.assertEqual(qs[0].answer_letters, ["B"])

    def test_letter_answer_with_judge_like_options_stays_judge(self):
        """选项本身就是「正确/错误」时，`（A）` 仍应判为判断题（修复不得过头）。"""
        qs, issues, _ = lines_to_questions([
            TextLine("1、未经论证压缩合同约定工期属于重大事故隐患。（A）"),
            TextLine("A.正确    B.错误")])
        self.assertEqual(issues, [])
        self.assertEqual(len(qs), 1)
        self.assertIs(qs[0].qtype, QType.JUDGE)
        self.assertTrue(qs[0].judge_answer)

    def test_judge_symbols_still_work(self):
        qs, issues, _ = lines_to_questions([
            TextLine("三、判断题"),
            TextLine("1、可以在电缆沟内充装易燃易爆危险品。（×）"),
            TextLine("2、施工单位应当对危大工程进行监测。（√）")])
        self.assertEqual(issues, [])
        self.assertEqual([q.judge_answer for q in qs], [False, True])

    def test_headerless_odd_width_is_rejected_loudly(self):
        """无列头且列数不在已知模板内时：明确报错，不得按位置猜列。"""
        tmp = Path(tempfile.mkdtemp(prefix="pd_rev_"))
        self.addCleanup(shutil.rmtree, tmp, True)
        for width, rows in (
                (6, [["单选题", "题目一", "甲", "乙", "丙", "丁"]]),
                (7, [["单选题", "题目一", "甲", "乙", "丙", "丁", "A"]])):
            with self.subTest(width=width):
                p = xlsx(tmp / f"w{width}.xlsx", rows)
                with self.assertRaises(ValueError) as ctx:
                    load_bank(p)
                self.assertIn("列头", str(ctx.exception))

    def test_headerless_standard_layout_still_supported(self):
        """12 列标准布局（无列头）仍按位置回退解析，不受上面收紧影响。"""
        tmp = Path(tempfile.mkdtemp(prefix="pd_rev_"))
        self.addCleanup(shutil.rmtree, tmp, True)
        rows = [["单选题", "题目一", "甲", "乙", "丙", "丁", "", "", "", "", "解析", "A"],
                ["判断题", "题目二", "", "", "", "", "", "", "", "", "", "正确"]]
        res = load_bank(xlsx(tmp / "std.xlsx", rows))
        self.assertEqual(len(res.questions), 2)
        self.assertEqual(len(res.issues), 0)

    def test_combined_option_column_below_title_rows(self):
        """表头不在第 1 行（上方有标题/空行）时，「选项」合并列仍应展开。"""
        tmp = Path(tempfile.mkdtemp(prefix="pd_rev_"))
        self.addCleanup(shutil.rmtree, tmp, True)
        res = load_bank(xlsx(tmp / "combo.xlsx", [
            ["2026 年度安全知识题库"], [],
            ["题型", "题目标题", "选项", "答案"],
            ["单选题", "题目一", "A.甲 B.乙 C.丙 D.丁", "B"],
            ["多选题", "题目二", "A.甲 B.乙 C.丙 D.丁", "AC（定）"]]))
        self.assertEqual(len(res.issues), 0)
        self.assertEqual(len(res.questions), 2)
        self.assertEqual(res.questions[0].options, ["甲", "乙", "丙", "丁"])
        self.assertTrue(res.questions[1].fixed_order)

    def test_answer_line_variants(self):
        """`【答案】A` / `答案 A` / `[答案]A` 等写法都应识别。"""
        for text in ("【答案】A", "答案 A", "[答案]A", "答案：A", "正确答案：A"):
            with self.subTest(line=text):
                qs, issues, _ = lines_to_questions([
                    TextLine("一、单项选择题"), TextLine("1、题干一？"),
                    TextLine("A.甲 B.乙"), TextLine(text)])
                self.assertEqual(issues, [], f"{text} 未识别为答案行")
                self.assertEqual(qs[0].answer_letters, ["A"])

    def test_glue_splits_short_next_stem(self):
        """选项行尾部粘连"下一题题干很短（≤8 字）"时也必须切开。"""
        qs, issues, _ = lines_to_questions([
            TextLine("一、单项选择题"),
            TextLine("1、题干一（A）。"),
            TextLine("A.甲    B.乙    C.丙    D.丁5、正确（B）。"),
            TextLine("A.甲    B.乙")])
        self.assertEqual(len(qs), 2)
        self.assertEqual(qs[1].answer_letters, ["B"])
        self.assertIn("正确", qs[1].stem)


# ================================================================ 存储层
class TestStoreReviewFixes(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pd_rev_store_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.bank = load_bank(FIXTURE_BANK) if FIXTURE_BANK.exists() else None

    def _questions(self, n: int, start: int = 0):
        p = xlsx(self.tmp / f"bank_{n}_{start}.xlsx", bank_rows(n, start))
        return load_bank(p).questions

    def test_broken_progress_file_does_not_break_other_banks(self):
        """任一进度文件字段类型损坏，不得让其它题库无法加载。"""
        pg = self.tmp / "progress"
        pg.mkdir(parents=True, exist_ok=True)
        (pg / "poison.json").write_text(json.dumps({
            "bank_key": "poison", "bank_name": "坏库", "question_total": "abc",
            "records": {"aa": {"right": "x"}}, "session": {}, "exams": []},
            ensure_ascii=False), encoding="utf-8")
        qs = self._questions(5)
        store = ProgressStore.load_for("无关题库", qs, pg)     # 不应抛异常
        self.assertEqual(store.stats(qs)["done"], 0)

    def test_progress_inherited_after_bank_shrinks(self):
        """题库删掉一半后进度仍应继承（分母用较小一方，避免整库归零）。"""
        pg = self.tmp / "progress2"
        full, small = self._questions(40), None
        st = ProgressStore.load_for("原库", full, pg)
        for q in full:
            st.progress.apply_answer(q, {"A"})
        st.save()
        small = self._questions(20)                            # 前 20 题（旧记录都存在）
        st2 = ProgressStore.load_for("缩减库", small, pg)
        inherited = sum(1 for q in small if st2.progress.record_of(q).done)
        self.assertEqual(inherited, len(small))

    def test_dirty_session_does_not_crash_restore(self):
        """session 字段脏数据时，恢复位置不应抛异常。"""
        pg = self.tmp / "progress3"
        qs = self._questions(10)
        st = ProgressStore.load_for("脏会话库", qs, pg)
        st.progress.session = {"pos": "abc", "mode": "顺序练习"}
        st.save()
        st2 = ProgressStore.load_for("脏会话库", qs, pg)
        s = PracticeSession(qs, st2, mode=PracticeMode.ORDER, seed=1)
        s.restore_position()                                  # 不应抛异常
        self.assertGreaterEqual(s.position, 1)

    def test_save_failure_is_visible(self):
        """进度无法落盘时，store 必须暴露失败状态（而不是静默丢失）。"""
        qs = self._questions(5)
        bad_dir = self.tmp / "not_a_dir"
        bad_dir.write_text("x", encoding="utf-8")             # 用文件占位目录 → mkdir 失败
        store = ProgressStore.load_for("保存失败库", qs, bad_dir)
        store.apply_answer(qs[0], True)
        self.assertTrue(store.last_save_error, "保存失败未被记录")

    def test_inheritance_is_by_content_not_name(self):
        """同名题库内容不同 → 不继承；不同名但内容相同 → 继承（按内容而非名称）。"""
        pg = self.tmp / "progress4"
        a = self._questions(10)
        st = ProgressStore.load_for("甲库", a, pg)
        for q in a[:5]:
            st.progress.apply_answer(q, {"A"})
        st.save()
        same_other_name = load_bank(xlsx(self.tmp / "renamed.xlsx", bank_rows(10))).questions
        inherited = ProgressStore.load_for("乙库", same_other_name, pg)
        self.assertEqual(sum(1 for q in same_other_name if inherited.progress.record_of(q).done), 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
