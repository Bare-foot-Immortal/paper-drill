# -*- coding: utf-8 -*-
"""审计修复回归测试（2026-10 全量缺陷修复）。

覆盖：导入解析、配置容错、进度存储、CLI、练习位置、考试保护等。
每个用例都对应审计报告中的一条已确认缺陷，防止回归。
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from paperdrill import cli  # noqa: E402
from paperdrill.bank_io import (  # noqa: E402
    TextLine,
    lines_to_questions,
    load_bank,
    rows_to_questions,
)
from paperdrill.config import AppSettings  # noqa: E402
from paperdrill.models import QType, parse_answer  # noqa: E402
from paperdrill.paper import PaperBlueprint, generate_round  # noqa: E402
from paperdrill.practice import (  # noqa: E402
    ExamSession,
    PracticeMode,
    PracticeSession,
)
from paperdrill.store import ProgressStore  # noqa: E402

try:
    from tests.qt_support import (  # type: ignore[attr-defined]
        HAVE_QT,
        SKIP_REASON,
        QtTestCase,
        make_questions,
    )
except ModuleNotFoundError:  # pragma: no cover
    from qt_support import HAVE_QT, SKIP_REASON, QtTestCase, make_questions  # type: ignore[no-redef]


def write_xlsx(path: Path, rows: list[list[object]], sheet: str = "题库") -> Path:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    for row in rows:
        ws.append(row)
    wb.save(path)
    return path


class TestAnswerParsing(unittest.TestCase):
    def test_fixed_marker_requires_brackets(self):
        letters, _judge, fixed = parse_answer(QType.SINGLE, "B（稳定）", 4)
        self.assertEqual(letters, ["B"])
        self.assertFalse(fixed, "「（稳定）」不是固定顺序标记")
        self.assertTrue(parse_answer(QType.SINGLE, "B（定）", 4)[2])
        self.assertTrue(parse_answer(QType.SINGLE, "B【定】", 4)[2])

    def test_numeric_answer_maps_to_letters(self):
        self.assertEqual(parse_answer(QType.SINGLE, "3", 4)[0], ["C"])
        self.assertEqual(parse_answer(QType.MULTIPLE, "1、3", 4)[0], ["A", "C"])

    def test_judge_answers_still_work(self):
        self.assertTrue(parse_answer(QType.JUDGE, "正确", 2)[1])
        self.assertFalse(parse_answer(QType.JUDGE, "×", 2)[1])


class TestParagraphParser(unittest.TestCase):
    def test_analysis_lines_do_not_change_answer(self):
        lines = [
            TextLine("一、单项选择题"),
            TextLine("1、题干一"),
            TextLine("A.甲    B.乙    C.丙    D.丁"),
            TextLine("答案：A"),
            TextLine("答案解析：B项更符合题意"),
            TextLine("2、题干二"),
            TextLine("A.甲    B.乙    C.丙    D.丁"),
            TextLine("答案：A"),
            TextLine("【解析】这是解释"),
        ]
        qs, issues, _ = lines_to_questions(lines)
        self.assertEqual(len(qs), 2, issues)
        self.assertEqual(qs[0].answer_letters, ["A"])
        self.assertIn("B项更符合题意", qs[0].analysis)
        self.assertEqual(qs[1].options, ["甲", "乙", "丙", "丁"])
        self.assertEqual(qs[1].analysis, "这是解释")

    def test_question_number_followed_by_digits(self):
        lines = [TextLine("一、单项选择题")]
        for i in range(1, 58):
            lines += [TextLine(f"{i}、题干{i}"), TextLine("A.甲    B.乙"),
                      TextLine("答案：A")]
        lines += [TextLine("58.2022 版规范规定（ B ）"), TextLine("A.甲    B.乙"),
                  TextLine("答案：B")]
        qs, issues, _ = lines_to_questions(lines)
        self.assertEqual(len(qs), 58, issues)
        self.assertIn("2022 版规范", qs[-1].stem)
        self.assertEqual(qs[-1].answer_letters, ["B"])

    def test_question_number_with_space(self):
        lines = [
            TextLine("一、单项选择题"),
            TextLine("1、题干一"), TextLine("A.甲    B.乙"), TextLine("答案：A"),
            TextLine("2 门窗工程复检项目有（ B ）"), TextLine("A.甲    B.乙"),
            TextLine("答案：B"),
        ]
        qs, issues, _ = lines_to_questions(lines)
        self.assertEqual(len(qs), 2, issues)
        self.assertIn("门窗工程", qs[1].stem)

    def test_glued_next_question_with_inline_answer(self):
        lines = [
            TextLine("一、单项选择题"),
            TextLine("1、题干一"), TextLine("答案：A"),
            TextLine("A.甲    B.乙    C.丙    D.丁2.高强螺栓应能自由穿入（ C ）"),
            TextLine("A.1.5    B.2.0    C.1.2    D.1.0"),
            TextLine("答案：C"),
        ]
        qs, issues, _ = lines_to_questions(lines)
        self.assertEqual(len(qs), 2, issues)
        self.assertEqual(qs[0].options[-1], "丁")
        self.assertTrue(qs[1].stem.startswith("高强螺栓"))
        self.assertEqual(qs[1].answer_letters, ["C"])

    def test_no_false_glue_for_digit_option_text(self):
        lines = [
            TextLine("一、单项选择题"),
            TextLine("1、题干一"), TextLine("答案：A"),
            TextLine("A. 约 5、7 米    B. 约 8、9 米"),
        ]
        qs, issues, _ = lines_to_questions(lines)
        self.assertEqual(len(qs), 1, issues)
        self.assertEqual(qs[0].options, ["约 5、7 米", "约 8、9 米"])

    def test_question_number_over_1000(self):
        lines = [TextLine("一、单项选择题")]
        for i in range(1, 1003):
            lines += [TextLine(f"{i}、题干{i}"), TextLine("A.甲    B.乙"),
                      TextLine("答案：A")]
        qs, issues, _ = lines_to_questions(lines)
        self.assertEqual(len(qs), 1002, issues)

    def test_heading_style_skips_subjective_section(self):
        lines = [
            TextLine("一、单项选择题", is_heading=True),
            TextLine("1、题干一"), TextLine("A.甲    B.乙"), TextLine("答案：A"),
            TextLine("二、简答题", is_heading=True),
            TextLine("1、请简述"), TextLine("A.甲    B.乙"), TextLine("答案：A"),
        ]
        qs, _issues, meta = lines_to_questions(lines)
        self.assertEqual([q.stem for q in qs], ["题干一"])
        self.assertEqual(meta["skipped_sections"], 1)

    def test_first_question_without_number(self):
        lines = [
            TextLine("一、单项选择题"),
            TextLine("下列关于安全的说法正确的是（ ）"),
            TextLine("A.甲    B.乙"),
            TextLine("答案：A"),
        ]
        qs, issues, _ = lines_to_questions(lines)
        self.assertEqual(len(qs), 1, issues)

    def test_continuity_warning(self):
        lines = [
            TextLine("一、单项选择题"),
            TextLine("1、题干一"), TextLine("A.甲    B.乙"), TextLine("答案：A"),
            TextLine("3、题干三"), TextLine("A.甲    B.乙"), TextLine("答案：A"),
        ]
        qs, _issues, meta = lines_to_questions(lines)
        self.assertEqual(len(qs), 2)
        self.assertTrue(any("题号不连续" in w for w in meta["warnings"]))


class TestTableParser(unittest.TestCase):
    def test_type_column_ambiguity(self):
        rows = [
            ["分类", "题型", "题干", "选项A", "选项B", "答案"],
            ["安全管理", "单选题", "题干一", "甲", "乙", "A"],
        ]
        qs, issues, _h, _c = rows_to_questions(rows)
        self.assertEqual(len(qs), 1, issues)
        self.assertEqual(qs[0].options, ["甲", "乙"])

    def test_answer_option_column_is_options(self):
        rows = [
            ["试题正文", "答案选项", "试题答案"],
            ["题干一", "A.甲 B.乙 C.丙 D.丁", "A"],
        ]
        qs, issues, _h, _c = rows_to_questions(rows)
        self.assertEqual(len(qs), 1, issues)
        self.assertEqual(qs[0].options, ["甲", "乙", "丙", "丁"])

    def test_two_row_header(self):
        rows = [
            ["题型", "题干", "选项", "", "", "", "答案"],
            ["", "", "A", "B", "C", "D", ""],
            ["单选题", "题干一", "甲", "乙", "丙", "丁", "A"],
        ]
        qs, issues, _h, _c = rows_to_questions(rows)
        self.assertEqual(len(qs), 1, issues)

    def test_missing_option_letter_is_reported(self):
        rows = [
            ["题型", "题干", "选项A", "选项B", "选项D", "答案"],
            ["单选题", "题干一", "甲", "乙", "丁", "D"],
        ]
        qs, issues, _h, _c = rows_to_questions(rows)
        self.assertEqual(qs, [])
        self.assertTrue(any("选项列不连续" in str(i) for i in issues))

    def test_content_alias(self):
        rows = [["题型", "内容", "选项A", "选项B", "答案"],
                ["单选题", "题干一", "甲", "乙", "A"]]
        qs, issues, _h, _c = rows_to_questions(rows)
        self.assertEqual(len(qs), 1, issues)

    def test_empty_bank_has_issue(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_xlsx(Path(tmp) / "empty.xlsx", [])
            res = load_bank(path)
        self.assertEqual(res.questions, [])
        self.assertTrue(res.issues)

    def test_utf16_text_file(self):
        body = "题型,题目标题,选项A,选项B,答案\r\n单选题,题干一,甲,乙,A\r\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bank.txt"
            path.write_bytes(body.encode("utf-16"))
            res = load_bank(path)
        self.assertEqual(len(res.questions), 1)
        self.assertEqual(res.questions[0].stem, "题干一")

    def test_content_keeps_fullwidth_punctuation(self):
        rows = [["题型", "题干", "选项A", "选项B", "答案"],
                ["单选题", "面积 100㎡，哪项对①？", "甲，乙", "丙", "A"]]
        qs, _issues, _h, _c = rows_to_questions(rows)
        self.assertEqual(qs[0].stem, "面积 100㎡，哪项对①？")
        self.assertEqual(qs[0].options[0], "甲，乙")


    def test_pdf_fallback_returns_value_error_instead_of_tuple(self):
        try:
            from reportlab.pdfgen import canvas
        except Exception:  # pragma: no cover - 缺 reportlab 时跳过
            self.skipTest("未安装 reportlab")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plain.pdf"
            c = canvas.Canvas(str(path))
            c.drawString(72, 760, "This document has no question structure.")
            c.drawString(72, 740, "Each line has only single spaces.")
            c.save()
            with self.assertRaises(ValueError):
                load_bank(path)


class TestConfigTolerance(unittest.TestCase):
    def test_non_object_json_falls_back(self):
        for payload in ("[1,2]", '"abc"', "42"):
            with tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp) / "settings.json"
                p.write_text(payload, encoding="utf-8")
                cfg = AppSettings.load(p)
            self.assertEqual(cfg.paper_single, 20, payload)

    def test_field_type_and_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "settings.json"
            p.write_text(json.dumps({
                "paper_single": 1_000_000_000,
                "shuffle_single": "false",
                "bank_path": None,
                "score_single": float("inf"),
                "__class__": 1,
            }), encoding="utf-8")
            cfg = AppSettings.load(p)
        self.assertLessEqual(cfg.paper_single, 10_000)
        self.assertFalse(cfg.shuffle_single)
        self.assertEqual(cfg.bank_path, "")
        self.assertEqual(cfg.score_single, 1.0)

    def test_bom_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "settings.json"
            p.write_bytes(("\ufeff" + json.dumps({"paper_single": 5})).encode("utf-8"))
            self.assertEqual(AppSettings.load(p).paper_single, 5)


class TestStoreRegressions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.questions = make_questions(12)

    def tearDown(self):
        self.tmp.cleanup()

    def test_list_all_broken_row_fields(self):
        (self.dir / "bad.json").write_text("{ 坏 JSON", encoding="utf-8")
        rows = ProgressStore.list_all(self.dir)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["broken"])
        self.assertEqual(rows[0]["accuracy"], 0.0)
        self.assertEqual(rows[0]["wrong_book"], 0)

    def test_delete_by_key_rejects_traversal(self):
        victim = self.dir.parent / "victim.json"
        victim.write_text("{}", encoding="utf-8")
        self.assertFalse(ProgressStore.delete_by_key("../victim", self.dir))
        self.assertTrue(victim.exists())
        self.assertFalse(ProgressStore.delete_by_key(str(victim.with_suffix("")), self.dir))

    def test_bom_progress_file_is_readable(self):
        store = ProgressStore.load_for("题库", self.questions, self.dir)
        store.apply_answer(self.questions[0], True)
        path = store.path
        path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
        again = ProgressStore.load_for("题库", self.questions, self.dir)
        self.assertEqual(again.stats(self.questions)["done"], 1)

    def test_clear_wrong_book_keeps_last_result(self):
        store = ProgressStore.load_for("题库", self.questions, self.dir)
        q = self.questions[0]
        store.progress.apply_answer(q, False)
        store.progress.clear_wrong_book([q])
        rec = store.record_of(q)
        self.assertEqual(rec.last, "wrong")
        self.assertFalse(rec.in_wrong_book)
        self.assertEqual(rec.wrong, 1)

    def test_inherit_prunes_records(self):
        old = ProgressStore.load_for("旧库", self.questions, self.dir)
        for q in self.questions:
            old.progress.apply_answer(q, True)
        old.save()
        tiny = [self.questions[0]]
        new_store = ProgressStore.load_for("新库", tiny, self.dir)
        self.assertEqual(len(new_store.progress.records), 1)

    def test_concurrent_saves_merge(self):
        s1 = ProgressStore.load_for("题库", self.questions, self.dir)
        s2 = ProgressStore.load_for("题库", self.questions, self.dir)
        s1.apply_answer(self.questions[0], True)
        s2.apply_answer(self.questions[1], True)
        merged = ProgressStore.load_for("题库", self.questions, self.dir)
        self.assertEqual(merged.stats(self.questions)["done"], 2)

    def test_reset_failure_rolls_back_memory(self):
        store = ProgressStore.load_for("题库", self.questions, self.dir)
        store.apply_answer(self.questions[0], True)
        self.assertTrue(store.path.exists())
        os.chmod(store.path, 0o444)
        try:
            with self.assertRaises((OSError, PermissionError)):
                store.reset()
            self.assertEqual(store.stats(self.questions)["done"], 1)
        finally:
            os.chmod(store.path, 0o666)


class TestPracticeRegressions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.questions = make_questions(12)

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_combo_position_starts_from_beginning(self):
        store = ProgressStore.load_for("题库", self.questions, self.dir)
        s = PracticeSession(self.questions, store, mode=PracticeMode.ORDER)
        s.goto(5)
        s.save_position()
        # 新（模式, 范围）组合从未记录过位置 → 必须从第 1 题开始
        s.rebuild(qtype_filter=QType.MULTIPLE)
        self.assertFalse(s.restore_position(adopt_mode=False))
        self.assertEqual(s.position, 1)

    def test_exam_blueprint_matches_paper(self):
        rnd = generate_round(self.questions, PaperBlueprint(2, 1, 0), seed=1)
        store = ProgressStore.load_for("题库", self.questions, self.dir)
        exam = ExamSession(rnd.papers[0], store, seed=1)
        bp = exam.paper_blueprint_dict()
        self.assertEqual(bp, {"single": 2, "multiple": 1, "judge": 0})


class TestCliRegressions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.questions = make_questions(6)
        self.bank = write_xlsx(self.dir / "bank.xlsx", [
            ["题型", "题目标题", "选项A", "选项B", "答案"],
            *[["单选题", f"题干{i}", "甲", "乙", "A"] for i in range(6)],
        ])

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(argv)
        return code, out.getvalue() + err.getvalue()

    def test_progress_dir_isolation(self):
        import paperdrill.store as store_mod
        orig = store_mod.progress_dir
        try:
            code, text = self._run(["--list-progress", "--progress-dir", str(self.dir / "p")])
            self.assertEqual(code, 0, text)
        finally:
            store_mod.progress_dir = orig

    def test_list_progress_tolerates_broken_file(self):
        import paperdrill.store as store_mod
        orig = store_mod.progress_dir
        pdir = self.dir / "p"
        pdir.mkdir()
        (pdir / "bad.json").write_text("{坏", encoding="utf-8")
        try:
            code, text = self._run(["--list-progress", "--progress-dir", str(pdir)])
            self.assertEqual(code, 0, text)
            self.assertIn("文件损坏", text)
        finally:
            store_mod.progress_dir = orig

    def test_practice_respects_excluded(self):
        import paperdrill.store as store_mod
        orig = store_mod.progress_dir
        pdir = self.dir / "p"
        try:
            res = load_bank(self.bank)
            store = ProgressStore.load_for("bank", res.questions, pdir)
            store.exclude(res.questions[:3])
            code, text = self._run([
                "--practice", "6", "--progress-dir", str(pdir), str(self.bank)])
            self.assertEqual(code, 0, text)
            self.assertIn("共 3 题", text)
        finally:
            store_mod.progress_dir = orig

    def test_stats_only_conflicts_with_practice(self):
        code, text = self._run(["--stats-only", "--practice", "1", str(self.bank)])
        self.assertEqual(code, 2)
        self.assertIn("不能同时使用", text)

    def test_negative_practice_rejected(self):
        code, _text = self._run(["--practice", "-1", str(self.bank)])
        self.assertEqual(code, 2)

    def test_missing_bank_is_friendly(self):
        code, text = self._run([str(self.dir / "nope.xlsx")])
        self.assertEqual(code, 2)
        self.assertIn("不存在", text)
        self.assertNotIn("Traceback", text)

    def test_empty_bank_exit_code(self):
        empty = write_xlsx(self.dir / "empty.xlsx", [])
        code, text = self._run([str(empty)])
        self.assertEqual(code, 3, text)


@unittest.skipUnless(HAVE_QT, SKIP_REASON)
class TestControllerRegressions(QtTestCase):
    def _ctrl(self, count: int = 12):
        return self.controller(questions=make_questions(count))

    def test_used_paper_labels_reset_on_new_round(self):
        ctrl = self._ctrl(12)
        ctrl.set_blueprint(2, 2, 2)
        rnd = ctrl.generate_round()
        for paper in rnd.papers:
            ctrl.start_exam(paper)
            ctrl.submit_exam()
        self.assertEqual(ctrl.used_paper_labels(), {p.label for p in rnd.papers})
        ctrl.generate_round()
        self.assertEqual(ctrl.used_paper_labels(), set())
        self.assertTrue(ctrl.start_next_unused_paper())

    def test_start_exam_guard(self):
        ctrl = self._ctrl(12)
        ctrl.set_blueprint(2, 2, 2)
        rnd = ctrl.generate_round()
        self.assertTrue(ctrl.start_exam(rnd.papers[0]))
        ctrl.exam_set("A")
        self.assertFalse(ctrl.start_exam(rnd.papers[1]))
        self.assertTrue(ctrl.start_exam(rnd.papers[1], allow_replace=True))
        self.assertEqual(ctrl.state.exam.answered_count, 0)

    def test_forget_current_bank_clears_memory_and_file(self):
        ctrl = self._ctrl(12)
        self.assertTrue(self.answer_correctly(ctrl))
        self.assertEqual(ctrl.stats()["done"], 1)
        cleaned = ctrl.forget_with_progress(ctrl.state.bank_path)
        self.assertEqual(cleaned, 1)
        self.assertEqual(ctrl.stats()["done"], 0)
        self.assertEqual(ctrl.state.store.progress.records, {})

    def test_reveal_clears_selection(self):
        ctrl = self._ctrl(12)
        ctrl.state.selection = {"B"}
        self.assertTrue(ctrl.reveal())
        self.assertEqual(ctrl.state.selection, set())

    def test_save_error_clears_after_recovery(self):
        ctrl = self._ctrl(12)
        store = ctrl.state.store
        calls = {"n": 0}
        original = store.save

        def flaky(*_a, **_k):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise OSError("模拟磁盘只读")
            return original()

        store.save = flaky
        self.answer_correctly(ctrl)
        self.assertTrue(ctrl.state.save_error)
        for _ in range(3):
            self.answer_correctly(ctrl)
            ctrl.advance()
        self.assertFalse(ctrl.state.save_error)


if __name__ == "__main__":
    unittest.main(verbosity=2)
