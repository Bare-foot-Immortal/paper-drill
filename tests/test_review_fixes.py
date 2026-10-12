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
from paperdrill.store import BankLibrary, ProgressStore  # noqa: E402

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


class TestResumeAndBankFiltering(unittest.TestCase):
    """v1.2.4：进度延续（随机/未做模式）+ 题库删减 + 题库选择。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pd_v124_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _questions(self, n: int, start: int = 0):
        p = xlsx(self.tmp / f"bank_{n}_{start}.xlsx", bank_rows(n, start))
        return load_bank(p).questions

    def _advanced(self, qs, *, mode=PracticeMode.ORDER, answered=0, extra=0):
        """建一个会话，答 answered 题后再往后走 extra 题。"""
        st = ProgressStore.load_for("延续库", qs, self.tmp / "pg")
        s = PracticeSession(qs, st, mode=mode, seed=11)
        for i in range(min(answered, s.total)):
            item = s.current_item()
            sel = set(item.shown_answer) if i % 2 == 0 else {
                lab for lab in item.labels if lab not in item.shown_answer}
            s.submit(sel)
            s.advance()
        for _ in range(extra):
            s.advance()
        s.save_position()
        return st, s

    # ---------------------------------------------------------- 进度延续
    def test_random_mode_resumes_same_question(self):
        """随机练习：重开后必须仍停在关闭前那道题（旧版按序号恢复会漂到别的题）。"""
        qs = self._questions(60)
        _, s = self._advanced(qs, mode=PracticeMode.RANDOM, answered=25, extra=3)
        before = s.current_question()
        self.assertIsNotNone(before)
        # 新会话用不同的随机种子 → 队列顺序与关闭前完全不同
        st2 = ProgressStore.load_for("延续库", qs, self.tmp / "pg")
        s2 = PracticeSession(qs, st2, mode=PracticeMode.ORDER, seed=99)
        self.assertTrue(s2.restore_position())
        self.assertIs(s2.mode, PracticeMode.RANDOM)
        self.assertEqual(s2.current_question().fingerprint, before.fingerprint)

    def test_fresh_mode_resumes_same_question(self):
        """只练未做：作答后队列会被重建，也必须按指纹停回原题。"""
        qs = self._questions(40)
        _, s = self._advanced(qs, mode=PracticeMode.FRESH, answered=10, extra=2)
        before = s.current_question()
        st2 = ProgressStore.load_for("延续库", qs, self.tmp / "pg")
        s2 = PracticeSession(qs, st2, mode=PracticeMode.ORDER, seed=5)
        self.assertTrue(s2.restore_position())
        self.assertEqual(s2.current_question().fingerprint, before.fingerprint)

    def test_position_window_survives_cut_question(self):
        """当前位置的题被移出队列时，靠窗口里的下一题继续，而不是漂到无关的题。"""
        qs = self._questions(40)
        _, s = self._advanced(qs, mode=PracticeMode.ORDER, answered=8)
        window = [q.fingerprint for q in s.navigation_window()]
        self.assertGreaterEqual(len(window), 2)
        # 模拟：窗口第 1 题在重开后已不在队列里（例如被删减）
        from paperdrill.practice import PracticeSession as PS

        st2 = ProgressStore.load_for("延续库", qs, self.tmp / "pg")
        s2 = PS(qs, st2, mode=PracticeMode.ORDER, seed=1)
        s2.order = [i for i in s2.order if qs[i].fingerprint != window[0]]
        self.assertTrue(s2.restore_position())
        self.assertEqual(s2.current_question().fingerprint, window[1])

    def test_legacy_single_fingerprint_session_still_restores(self):
        """兼容旧版进度文件（只有 last_fp，没有 pos_fps）。"""
        qs = self._questions(20)
        st = ProgressStore.load_for("旧会话库", qs, self.tmp / "pg")
        st.progress.session = {"mode": "random", "last_fp": qs[7].fingerprint,
                               "pos": 3, "shuffle": True}
        st.save()
        st2 = ProgressStore.load_for("旧会话库", qs, self.tmp / "pg")
        s2 = PracticeSession(qs, st2, mode=PracticeMode.RANDOM, seed=3)
        self.assertTrue(s2.restore_position())
        self.assertEqual(s2.current_question().fingerprint, qs[7].fingerprint)

    def test_wrong_mode_hit_removed_from_queue_does_not_misfire(self):
        """错题重练：命中的错题答对后移出队列 → 退化为序号兜底，但不许报"精确恢复"。"""
        qs = self._questions(30)
        st = ProgressStore.load_for("错题库", qs, self.tmp / "pg")
        for q in qs[:9]:                      # 制造 9 道错题
            st.progress.apply_answer(q, False)
        st.save()
        s = PracticeSession(qs, st, mode=PracticeMode.WRONG, seed=2)
        s.goto(4)
        target = s.current_question().fingerprint
        s.save_position()
        st2 = ProgressStore.load_for("错题库", qs, self.tmp / "pg")
        s2 = PracticeSession(qs, st2, mode=PracticeMode.WRONG, seed=2)
        self.assertTrue(s2.restore_position())
        self.assertEqual(s2.current_question().fingerprint, target)

    def test_dirty_pos_does_not_fake_success(self):
        """指纹全部落空 + pos 超界 → 夹取到合法位置且返回 False（不是假成功）。"""
        qs = self._questions(10)
        st = ProgressStore.load_for("脏位置库", qs, self.tmp / "pg")
        st.progress.session = {"mode": "order", "last_fp": "deadbeef",
                               "pos_fps": ["nope1", "nope2"], "pos": 9999}
        st.save()
        st2 = ProgressStore.load_for("脏位置库", qs, self.tmp / "pg")
        s2 = PracticeSession(qs, st2, mode=PracticeMode.ORDER, seed=1)
        self.assertFalse(s2.restore_position())
        self.assertEqual(s2.position, 10)     # 夹取到最后一题，不越界

    # ---------------------------------------------------------- 题库删减
    def test_exclude_persists_and_filters(self):
        qs = self._questions(30)
        st = ProgressStore.load_for("删减库", qs, self.tmp / "pg")
        self.assertEqual(st.exclude(qs[:7]), 7)
        self.assertEqual(st.exclude(qs[:7]), 0)            # 幂等
        self.assertEqual(len(st.excluded_questions(qs)), 7)
        active = st.active_questions(qs)
        self.assertEqual(len(active), 23)
        self.assertFalse({q.fingerprint for q in qs[:7]} & {q.fingerprint for q in active})
        # 重开仍生效
        st2 = ProgressStore.load_for("删减库", qs, self.tmp / "pg")
        self.assertEqual(len(st2.progress.excluded), 7)
        self.assertEqual(len(st2.active_questions(qs)), 23)
        self.assertEqual(st2.include(qs[:3]), 3)
        self.assertEqual(len(st2.active_questions(qs)), 26)
        self.assertEqual(st2.clear_excluded(), 4)
        self.assertEqual(len(st2.active_questions(qs)), 30)

    def test_exclude_survives_old_schema_file(self):
        """schema 1 的旧进度文件（无 excluded 字段）必须能直接读，且删减可用。"""
        pg = self.tmp / "pg_old"
        pg.mkdir(parents=True, exist_ok=True)
        qs = self._questions(8)
        from paperdrill.store import bank_key_of

        key = bank_key_of("旧格式库", qs)
        (pg / f"{key}.json").write_text(json.dumps({
            "schema": 1, "bank_key": key, "bank_name": "旧格式库", "question_total": 8,
            "records": {qs[0].fingerprint: {"right": 1, "wrong": 0, "last": "right", "streak": 1}},
            "session": {}, "exams": []}, ensure_ascii=False), encoding="utf-8")
        st = ProgressStore.load_for("旧格式库", qs, pg)
        self.assertEqual(st.stats(qs)["done"], 1)          # 旧记录仍在
        self.assertEqual(st.exclude(qs[1:3]), 2)
        st.save()
        again = json.loads((pg / f"{key}.json").read_text(encoding="utf-8"))
        self.assertEqual(again["schema"], 2)
        self.assertEqual(len(again["excluded"]), 2)
        self.assertIn("stem", again["excluded"][qs[1].fingerprint])

    def test_excluded_inherited_when_bank_renamed(self):
        """题库改名/挪目录时，仍能命中的删减记录随之继承。"""
        pg = self.tmp / "pg_inh"
        full = self._questions(20)
        st = ProgressStore.load_for("甲库", full, pg)
        for q in full:
            st.progress.apply_answer(q, {"A"})             # 保证可继承
        st.exclude(full[:5])
        st.save()
        same = load_bank(xlsx(self.tmp / "renamed.xlsx", bank_rows(20))).questions
        st2 = ProgressStore.load_for("乙库", same, pg)
        self.assertEqual(len(st2.progress.excluded), 5)
        self.assertEqual(len(st2.active_questions(same)), 15)

    def test_prune_excluded_drops_stale_records(self):
        qs = self._questions(10)
        st = ProgressStore.load_for("换版库", qs, self.tmp / "pg")
        st.exclude(qs[:4])
        st.progress.excluded["deadbeefdead"] = {"stem": "已不存在的题"}
        self.assertEqual(st.progress.prune_excluded(qs), 1)
        self.assertEqual(len(st.progress.excluded), 4)

    def test_excluded_does_not_count_as_progress(self):
        """删减只影响参与集合，不影响已作答统计口径。"""
        qs = self._questions(12)
        st = ProgressStore.load_for("口径库", qs, self.tmp / "pg")
        for q in qs:
            st.progress.apply_answer(q, True)
        st.exclude(qs[:4])
        active = st.active_questions(qs)
        self.assertEqual(st.stats(active)["done"], 8)
        self.assertEqual(st.stats(qs)["done"], 12)

    def test_list_all_reports_excluded(self):
        qs = self._questions(15)
        st = ProgressStore.load_for("列表库", qs, self.tmp / "pg")
        st.exclude(qs[:5])
        rows = ProgressStore.list_all(self.tmp / "pg")
        row = next(r for r in rows if r["name"] == "列表库")
        self.assertEqual(row["excluded"], 5)
        self.assertEqual(row["active"], 10)
        self.assertEqual(row["total"], 15)


class TestBankLibrary(unittest.TestCase):
    """v1.2.4：题库库（最近使用的题库）——只记录，不删文件。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pd_lib_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.lib_path = self.tmp / "library.json"

    def _bank_file(self, name: str) -> Path:
        p = self.tmp / f"{name}.xlsx"
        p.write_bytes(b"not a real bank")
        return p

    def test_remember_dedupe_and_order(self):
        lib = BankLibrary([], self.lib_path)
        a, b = self._bank_file("甲"), self._bank_file("乙")
        lib.remember(a, "甲库", 10)
        lib.remember(b, "乙库", 20)
        lib.remember(a, "甲库改名", 12)                    # 同路径 → 更新并置顶
        self.assertEqual(len(lib), 2)
        self.assertEqual(lib.entries[0]["path"], str(a))
        self.assertEqual(lib.entries[0]["name"], "甲库改名")
        self.assertEqual(lib.entries[0]["total"], 12)

    def test_persist_and_missing_detection(self):
        lib = BankLibrary([], self.lib_path)
        a = self._bank_file("存在")
        gone = self.tmp / "不存在.xlsx"
        lib.remember(a, "存在库", 3)
        lib.remember(gone, "丢失库", 0)
        self.assertEqual(lib.save(), self.lib_path)
        again = BankLibrary.load(self.lib_path)
        self.assertEqual(len(again), 2)
        self.assertEqual(len(again.existing()), 1)
        self.assertEqual(len(again.missing()), 1)
        self.assertEqual(again.most_recent()["path"], str(a))   # 跳过不存在的

    def test_forget_keeps_file_on_disk(self):
        lib = BankLibrary([], self.lib_path)
        a = self._bank_file("保留")
        lib.remember(a, "保留库", 1)
        self.assertTrue(lib.forget(a))
        self.assertEqual(len(lib), 0)
        self.assertTrue(a.is_file(), "移除记录不应删除题库文件")
        self.assertFalse(lib.forget(a))                    # 幂等

    def test_corrupt_file_degrades_to_empty(self):
        self.lib_path.write_text("{ not json", encoding="utf-8")
        self.assertEqual(len(BankLibrary.load(self.lib_path)), 0)
        self.lib_path.write_text(json.dumps({"banks": "oops"}), encoding="utf-8")
        self.assertEqual(len(BankLibrary.load(self.lib_path)), 0)
        self.lib_path.write_text(json.dumps({"banks": [{"path": ""}, 7, {"path": "   "}]}),
                                 encoding="utf-8")
        self.assertEqual(len(BankLibrary.load(self.lib_path)), 0)

    def test_entry_limit(self):
        lib = BankLibrary([], self.lib_path)
        for i in range(BankLibrary.MAX_ENTRIES + 10):
            lib.remember(self._bank_file(f"bank{i}"), f"库{i}", i)
        self.assertEqual(len(lib), BankLibrary.MAX_ENTRIES)
        self.assertEqual(lib.entries[0]["name"], f"库{BankLibrary.MAX_ENTRIES + 9}")


class TestBankFolderScan(unittest.TestCase):
    """v1.2.4：题库选择里的「扫描文件夹」（递归、按后缀过滤、跳过临时文件）。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pd_scan_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_scan_finds_supported_and_skips_others(self):
        from paperdrill.gui import scan_bank_folder

        (self.tmp / "sub").mkdir()
        xlsx(self.tmp / "a.xlsx", bank_rows(3))
        xlsx(self.tmp / "sub" / "b.xlsx", bank_rows(3))
        (self.tmp / "note.txt").write_text("x", encoding="utf-8")     # txt 是支持的
        (self.tmp / "readme.md").write_text("x", encoding="utf-8")    # 不支持
        (self.tmp / "~$lock.xlsx").write_bytes(b"x")                  # Excel 临时文件
        (self.tmp / "image.png").write_bytes(b"x")
        found = [p.name for p in scan_bank_folder(self.tmp)]
        self.assertIn("a.xlsx", found)
        self.assertIn("b.xlsx", found)
        self.assertIn("note.txt", found)
        self.assertNotIn("readme.md", found)
        self.assertNotIn("~$lock.xlsx", found)
        self.assertNotIn("image.png", found)

    def test_scan_respects_limit_and_bad_folder(self):
        from paperdrill.gui import scan_bank_folder

        for i in range(6):
            xlsx(self.tmp / f"b{i}.xlsx", bank_rows(2))
        self.assertEqual(len(scan_bank_folder(self.tmp, limit=3)), 3)
        self.assertEqual(scan_bank_folder(self.tmp / "nope"), [])
        not_a_dir = self.tmp / "file.xlsx"
        not_a_dir.write_bytes(b"x")
        self.assertEqual(scan_bank_folder(not_a_dir), [])

    def test_quick_bank_info_counts_and_degrades(self):
        from paperdrill.gui import quick_bank_info

        p = xlsx(self.tmp / "ok.xlsx", bank_rows(7))
        name, total = quick_bank_info(p)
        self.assertEqual(name, "ok")
        self.assertEqual(total, 7)
        bad = self.tmp / "bad.xlsx"
        bad.write_bytes(b"not a workbook")
        name2, total2 = quick_bank_info(bad)          # 不得抛异常
        self.assertEqual(name2, "bad")
        self.assertEqual(total2, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
