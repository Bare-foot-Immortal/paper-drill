# -*- coding: utf-8 -*-
"""刷题匠 PaperDrill 测试套件（标准库 unittest）。

覆盖：进度存储与题库标识、题库变更后的进度继承、多题库隔离、损坏文件容错、
练习模式队列、选项打乱后的判题正确性、「定」题保护、错题本进出、统计口径、
端到端练习流程、界面无头自检。

运行：python -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import random
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from paperdrill.bank_io import (  # noqa: E402
    bank_stats,
    load_bank,
)
from paperdrill.models import OPTION_LABELS, QType, Question  # noqa: E402
from paperdrill.paper import (  # noqa: E402
    GenerationError,
    PaperBlueprint,
    generate_round,
    min_round_length,
)
from paperdrill.practice import (  # noqa: E402
    ExamSession,
    PracticeMode,
    PracticeSession,
    Scope,
    build_item,
)
from paperdrill.store import (  # noqa: E402
    ProgressStore,
    bank_key_of,
)

FIXTURES = ROOT / "fixtures"
REAL_BANK = FIXTURES / "样例题库.xlsx"          # 合成夹具（tools/make_samples.py 生成）


def _ensure_fixtures() -> None:
    """夹具缺失时立即生成（必须在类定义/装饰器求值之前调用）。"""
    if REAL_BANK.exists():
        return
    import subprocess

    script = ROOT / "tools" / "make_samples.py"
    if script.exists():
        subprocess.run([sys.executable, str(script), "--fixtures-only"],
                       cwd=str(ROOT), check=False, capture_output=True)


_ensure_fixtures()


SAMPLE_BANK = ROOT / "samples" / "示例题库.xlsx"


def make_question(index: int, qtype: QType = QType.SINGLE, n_options: int = 4,
                  fixed: bool = False, answer: "list[str] | None" = None) -> Question:
    if qtype is QType.JUDGE:
        return Question(qid=f"judge-{index:04d}", qtype=QType.JUDGE, stem=f"判断题 {index}",
                        options=[], judge_answer=(index % 2 == 0), fixed_order=fixed,
                        analysis=f"解析 {index}", src_row=index)
    letters = answer or (["A"] if qtype is QType.SINGLE else ["A", "B"])
    return Question(qid=f"{qtype.key}-{index:04d}", qtype=qtype, stem=f"题目 {index}（{qtype.short}）",
                    options=[f"选项{i}{index}" for i in range(n_options)], answer_letters=list(letters),
                    fixed_order=fixed, analysis=f"解析 {index}", src_row=index)


def mixed_bank(count: int = 12) -> list[Question]:
    """构造 单选/多选/判断 混合题库。"""
    out: list[Question] = []
    for i in range(count):
        kind = i % 3
        if kind == 0:
            out.append(make_question(i, QType.SINGLE))
        elif kind == 1:
            out.append(make_question(i, QType.MULTIPLE, n_options=4, answer=["A", "C"]))
        else:
            out.append(make_question(i, QType.JUDGE))
    return out


# ================================================================ 进度存储
class TestProgressStore(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pd_test_"))
        self.questions = mixed_bank(12)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_bank_key_stable_and_content_based(self):
        k1 = bank_key_of("题库A", self.questions)
        k2 = bank_key_of("题库A", self.questions)
        k3 = bank_key_of("题库B", self.questions)
        self.assertEqual(k1, k2)
        self.assertNotEqual(k1, k3)                     # 文件名不同 → 不同题库
        reordered = list(reversed(self.questions))
        self.assertEqual(k1, bank_key_of("题库A", reordered))   # 顺序无关

    def test_apply_and_persist(self):
        store = ProgressStore.load_for("题库A", self.questions, self.tmp)
        q = self.questions[0]
        store.progress.apply_answer(q, False)
        store.progress.apply_answer(q, True)
        store.save()

        again = ProgressStore.load_for("题库A", self.questions, self.tmp)
        rec = again.record_of(q)
        self.assertEqual(rec.right, 1)
        self.assertEqual(rec.wrong, 1)
        self.assertEqual(rec.last, "right")
        self.assertTrue(rec.done)
        self.assertFalse(rec.in_wrong_book)             # 答对后移出错题本

    def test_wrong_book_behaviour(self):
        store = ProgressStore.load_for("题库A", self.questions, self.tmp)
        q = self.questions[1]
        store.progress.apply_answer(q, False)
        self.assertTrue(store.record_of(q).in_wrong_book)
        self.assertEqual(store.progress.stats(self.questions)["wrong_book"], 1)
        store.progress.apply_answer(q, True)
        self.assertFalse(store.record_of(q).in_wrong_book)
        self.assertEqual(store.progress.stats(self.questions)["wrong_book"], 0)

    def test_multi_bank_isolation(self):
        a = ProgressStore.load_for("题库A", self.questions, self.tmp)
        b = ProgressStore.load_for("题库B", self.questions, self.tmp)
        a.progress.apply_answer(self.questions[0], True)
        a.save()
        b.save()
        a2 = ProgressStore.load_for("题库A", self.questions, self.tmp)
        b2 = ProgressStore.load_for("题库B", self.questions, self.tmp)
        self.assertEqual(a2.progress.stats(self.questions)["done"], 1)
        self.assertEqual(b2.progress.stats(self.questions)["done"], 0)

    def test_inherit_after_bank_modified(self):
        """题库增删题目后，内容未变的题仍应保留进度。"""
        store = ProgressStore.load_for("题库A", self.questions, self.tmp)
        for q in self.questions[:9]:
            store.progress.apply_answer(q, q is not self.questions[1])
        store.save()

        changed = self.questions + [make_question(99, QType.SINGLE)]
        new_store = ProgressStore.load_for("题库A", changed, self.tmp)
        self.assertTrue(new_store.progress.inherited_from)
        self.assertEqual(new_store.progress.stats(changed)["done"], 9)
        self.assertEqual(len(list(self.tmp.glob("*.json"))), 2)   # 旧文件保留 + 新文件

    def test_no_inherit_when_bank_unrelated(self):
        store = ProgressStore.load_for("题库A", self.questions, self.tmp)
        store.progress.apply_answer(self.questions[0], True)
        store.save()
        unrelated = [make_question(500 + i, QType.SINGLE) for i in range(10)]
        fresh = ProgressStore.load_for("另一个题库", unrelated, self.tmp)
        self.assertEqual(fresh.progress.inherited_from, "")
        self.assertEqual(fresh.progress.stats(unrelated)["done"], 0)

    def test_corrupted_file_does_not_crash(self):
        store = ProgressStore.load_for("题库A", self.questions, self.tmp)
        store.save()
        store.path.write_text("{ 这不是合法 JSON", encoding="utf-8")
        again = ProgressStore.load_for("题库A", self.questions, self.tmp)
        self.assertEqual(again.progress.stats(self.questions)["done"], 0)

        broken = self.tmp / "坏文件__deadbeef.json"
        broken.write_text("??", encoding="utf-8")
        rows = ProgressStore.list_all(self.tmp)
        self.assertTrue(any(r.get("broken") for r in rows))

    def test_session_position_saved_and_restored(self):
        store = ProgressStore.load_for("题库A", self.questions, self.tmp)
        store.save_session("order", self.questions[5], 5, True, {"n": 1})
        again = ProgressStore.load_for("题库A", self.questions, self.tmp)
        saved = again.saved_session()
        self.assertEqual(saved["mode"], "order")
        self.assertEqual(saved["pos"], 5)
        self.assertEqual(saved["last_fp"], self.questions[5].fingerprint)

    def test_reset_and_delete(self):
        store = ProgressStore.load_for("题库A", self.questions, self.tmp)
        store.progress.apply_answer(self.questions[0], False)
        store.save()
        self.assertTrue(store.path.exists())
        store.reset()
        self.assertEqual(store.progress.stats(self.questions)["done"], 0)
        key = store.progress.bank_key
        self.assertTrue(ProgressStore.delete_by_key(key, self.tmp))
        self.assertFalse((self.tmp / f"{key}.json").exists())

    def test_list_all(self):
        store = ProgressStore.load_for("题库A", self.questions, self.tmp)
        store.progress.apply_answer(self.questions[0], True)
        store.progress.apply_answer(self.questions[1], False)
        store.save()
        rows = [r for r in ProgressStore.list_all(self.tmp) if not r.get("broken")]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["done"], 2)
        self.assertEqual(rows[0]["wrong_book"], 1)
        self.assertAlmostEqual(rows[0]["accuracy"], 0.5)


# ================================================================ 练习渲染/判题
class TestBuildItem(unittest.TestCase):
    def test_judge_item_has_two_options(self):
        q = make_question(1, QType.JUDGE)
        item = build_item(q, random.Random(1), True)
        self.assertEqual(item.texts, ["正确", "错误"])
        self.assertFalse(item.shuffled)

    def test_shuffle_answer_mapping(self):
        q = make_question(2, QType.MULTIPLE, n_options=4, answer=["A", "C"])
        rng = random.Random(7)
        for _ in range(200):
            item = build_item(q, rng, True)
            self.assertTrue(item.shuffled)
            # 用显示答案作答必对；取显示答案对应的文本应与原始答案文本一致
            self.assertTrue(item.judge(item.shown_answer))
            got = {item.texts[OPTION_LABELS.index(c)] for c in item.shown_answer}
            want = {q.options[OPTION_LABELS.index(c)] for c in q.answer_letters}
            self.assertEqual(got, want)

    def test_fixed_order_never_shuffled(self):
        q = make_question(3, QType.MULTIPLE, n_options=4, fixed=True, answer=["B", "C"])
        rng = random.Random(3)
        for _ in range(50):
            item = build_item(q, rng, True)
            self.assertFalse(item.shuffled)
            self.assertEqual(item.texts, q.options)
            self.assertEqual(item.shown_answer, {"B", "C"})
            self.assertEqual(item.answer_display(), "BC")

    def test_shuffle_disabled(self):
        q = make_question(4, QType.SINGLE, n_options=4)
        item = build_item(q, random.Random(1), False)
        self.assertFalse(item.shuffled)
        self.assertEqual(item.texts, q.options)

    def test_judge_strictness(self):
        q_true = make_question(4, QType.JUDGE)      # index%2==0 → 答案「正确」
        item = build_item(q_true, random.Random(1), False)
        self.assertTrue(item.judge({"A"}))
        self.assertTrue(item.judge(True))
        self.assertFalse(item.judge({"B"}))
        self.assertFalse(item.judge(False))
        self.assertFalse(item.judge(None))

    def test_multi_strictly_equals(self):
        q = make_question(6, QType.MULTIPLE, n_options=4, answer=["A", "B", "C"])
        item = build_item(q, random.Random(1), False)
        self.assertTrue(item.judge({"A", "B", "C"}))
        self.assertFalse(item.judge({"A", "B"}))          # 少选
        self.assertFalse(item.judge({"A", "B", "C", "D"}))  # 多选
        self.assertFalse(item.judge({"A", "B", "D"}))     # 错选
        self.assertFalse(item.judge(set()))

    def test_selected_text(self):
        q = make_question(7, QType.MULTIPLE, n_options=4, answer=["A", "C"])
        item = build_item(q, random.Random(1), False)
        self.assertIn("选项0", item.selected_text({"A"}))
        self.assertEqual(item.selected_text(set()), "（未作答）")
        jq = build_item(make_question(8, QType.JUDGE), random.Random(1), False)
        self.assertIn(jq.selected_text({"B"}), ("正确", "错误"))


# ================================================================ 练习会话
class TestPracticeSession(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pd_sess_"))
        self.questions = mixed_bank(12)
        self.store = ProgressStore.load_for("题库A", self.questions, self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _session(self, mode=PracticeMode.ORDER, shuffle=True, seed=1):
        return PracticeSession(self.questions, self.store, mode=mode,
                               shuffle_options=shuffle, seed=seed)

    def test_order_mode(self):
        s = self._session()
        self.assertEqual(s.total, 12)
        self.assertEqual(s.order, list(range(12)))
        self.assertEqual(s.position, 1)

    def test_random_mode_is_permutation(self):
        s = self._session(PracticeMode.RANDOM)
        self.assertEqual(sorted(s.order), list(range(12)))
        self.assertNotEqual(s.order, list(range(12)))   # 12 题同序概率极低

    def test_wrong_mode_queue(self):
        for i, q in enumerate(self.questions):
            self.store.progress.apply_answer(q, correct=(i % 2 == 0))
        self.store.save()
        s = self._session(PracticeMode.WRONG)
        self.assertEqual(s.total, 6)                    # 奇数题答错
        for idx in s.order:
            self.assertTrue(self.store.record_of(self.questions[idx]).in_wrong_book)

    def test_fresh_mode_queue(self):
        for q in self.questions[:5]:
            self.store.progress.apply_answer(q, True)
        self.store.save()
        s = self._session(PracticeMode.FRESH)
        self.assertEqual(s.total, 7)

    def test_submit_records_and_judges(self):
        s = self._session(shuffle=False)
        item = s.current_item()
        result = s.submit(set(item.shown_answer))
        self.assertTrue(result.correct)
        self.assertEqual(s.stats()["done"], 1)
        self.assertEqual(s.stats()["right"], 1)

        s.advance()
        item = s.current_item()
        wrong = {"D"} if "D" in item.labels and "D" not in item.shown_answer else {
            lab for lab in item.labels if lab not in item.shown_answer}
        result = s.submit(wrong)
        self.assertFalse(result.correct)
        self.assertEqual(s.stats()["wrong"], 1)
        self.assertEqual(s.stats()["wrong_book"], 1)

    def test_submit_with_empty_selection_is_wrong_but_recorded(self):
        s = self._session()
        result = s.submit(set())
        self.assertFalse(result.correct)
        self.assertEqual(s.stats()["wrong"], 1)

    def test_judge_question_via_letters_and_bool(self):
        s = self._session(shuffle=False)
        while s.current_item().qtype is not QType.JUDGE:
            s.advance()
        item = s.current_item()
        self.assertTrue(s.submit(set(item.shown_answer)).correct)
        s.rebuild(PracticeMode.ORDER)
        while s.current_item().qtype is not QType.JUDGE:
            s.advance()
        item = s.current_item()
        self.assertTrue(s.submit(bool(item.question.judge_answer)).correct)

    def test_shuffled_session_judging_is_correct(self):
        """打乱选项后，用"显示出的正确选项"作答必须判对，用错误选项必须判错。"""
        s = self._session(shuffle=True, seed=99)
        for _ in range(s.total):
            item = s.current_item()
            if item.qtype is QType.MULTIPLE:
                s.submit(set(item.shown_answer))
            else:
                s.submit(set(item.shown_answer))
            s.advance()
        self.assertEqual(s.stats()["right"], 12)
        self.assertEqual(s.stats()["wrong"], 0)

    def test_item_order_stable_within_session(self):
        s = self._session(shuffle=True, seed=5)
        item1 = s.current_item()
        texts = list(item1.texts)
        s.advance()
        s.retreat()
        self.assertEqual(list(s.current_item().texts), texts)

    def test_navigation_bounds(self):
        s = self._session()
        self.assertFalse(s.retreat())
        self.assertTrue(s.goto(11))
        self.assertFalse(s.advance())
        self.assertTrue(s.goto(0))
        self.assertTrue(s.advance())

    def test_save_and_restore_position(self):
        s = self._session()
        s.goto(4)
        s.save_position()
        s2 = self._session()
        self.assertTrue(s2.restore_position())
        self.assertEqual(s2.position, 5)
        self.assertEqual(s2.current_question().fingerprint, self.questions[4].fingerprint)

    def test_restore_mode_from_disk(self):
        s = self._session()
        s.rebuild(PracticeMode.RANDOM)
        s.save_position()
        s2 = self._session()
        s2.restore_position()
        self.assertIs(s2.mode, PracticeMode.RANDOM)

    def test_empty_wrong_book_session(self):
        s = self._session(PracticeMode.WRONG)
        self.assertTrue(s.empty)
        self.assertEqual(s.total, 0)
        self.assertIsNone(s.current_item())

    def test_clear_wrong_book(self):
        s = self._session()
        item = s.current_item()
        s.submit({lab for lab in item.labels if lab not in item.shown_answer})
        self.assertEqual(s.stats()["wrong_book"], 1)
        cleared = self.store.progress.clear_wrong_book(self.questions)
        self.assertEqual(cleared, 1)
        self.assertEqual(s.stats()["wrong_book"], 0)
        self.assertEqual(s.stats()["wrong"], 1)        # 历史统计保留


# ================================================================ 试卷蓝图与轮次覆盖
class TestPaperRound(unittest.TestCase):
    def setUp(self):
        self.questions = ([make_question(i, QType.SINGLE) for i in range(101)]
                          + [make_question(i, QType.MULTIPLE) for i in range(32)]
                          + [make_question(i, QType.JUDGE) for i in range(30)])
        self.bp = PaperBlueprint(20, 10, 10)

    def test_blueprint_basics(self):
        bp = PaperBlueprint(20, 10, 10)
        self.assertEqual(bp.total, 40)
        self.assertEqual(bp.get(QType.MULTIPLE), 10)
        self.assertEqual(PaperBlueprint.from_dict(bp.to_dict()).total, 40)

    def test_min_round_length(self):
        self.assertEqual(min_round_length(self.questions, self.bp), 6)
        self.assertEqual(min_round_length(self.questions, PaperBlueprint(3, 0, 0)), 34)

    def test_generate_round_coverage(self):
        rnd = generate_round(self.questions, self.bp, seed=42)
        self.assertEqual(rnd.paper_count, 6)
        self.assertTrue(rnd.coverage_ok)
        self.assertEqual(rnd.coverage["single"], (101, 101))
        self.assertEqual(rnd.coverage["multiple"], (32, 32))
        self.assertEqual(rnd.coverage["judge"], (30, 30))
        seen = {pq.question.qid for p in rnd.papers for pq in p.items}
        self.assertEqual(seen, {q.qid for q in self.questions})

    def test_each_paper_matches_blueprint(self):
        rnd = generate_round(self.questions, self.bp, seed=42)
        for p in rnd.papers:
            self.assertEqual(p.total, 40)
            self.assertEqual(p.count_of(QType.SINGLE), 20)
            self.assertEqual(p.count_of(QType.MULTIPLE), 10)
            self.assertEqual(p.count_of(QType.JUDGE), 10)

    def test_fill_up_with_seen_questions(self):
        """多选 32 题、每卷 10 题：第 4 张 = 2 新 + 8 补（需求 3 的补题规则）。"""
        rnd = generate_round(self.questions, self.bp, seed=42)
        paper4 = rnd.papers[3]
        multi = paper4.of_type(QType.MULTIPLE)
        self.assertEqual(len(multi), 10)
        self.assertEqual(sum(1 for pq in multi if pq.reused), 8)
        self.assertEqual(len({pq.question.qid for pq in multi}), 10)     # 卷内不重复

    def test_requirement_example_120_questions(self):
        """需求 3 示例：题库 120 题、每卷 40 题 → 3 张一轮且全部题目出现过。"""
        qs = ([make_question(i, QType.SINGLE) for i in range(60)]
              + [make_question(i, QType.MULTIPLE) for i in range(30)]
              + [make_question(i, QType.JUDGE) for i in range(30)])
        bp = PaperBlueprint(20, 10, 10)
        self.assertEqual(min_round_length(qs, bp), 3)
        rnd = generate_round(qs, bp, seed=7)
        self.assertEqual(rnd.paper_count, 3)
        self.assertTrue(rnd.coverage_ok)
        seen = {pq.question.qid for p in rnd.papers for pq in p.items}
        self.assertEqual(len(seen), 120)
        for p in rnd.papers:
            self.assertEqual(p.total, 40)

    def test_manual_round_length_too_small(self):
        rnd = generate_round(self.questions, self.bp, round_length=3, seed=1)
        self.assertFalse(rnd.coverage_ok)
        self.assertGreater(rnd.uncovered, 0)
        self.assertTrue(any("无法覆盖" in w for w in rnd.warnings))
        for p in rnd.papers:
            self.assertEqual(p.total, 40)

    def test_seed_reproducible(self):
        a = generate_round(self.questions, self.bp, seed=2024)
        b = generate_round(self.questions, self.bp, seed=2024)
        self.assertEqual([[pq.question.qid for pq in p.items] for p in a.papers],
                         [[pq.question.qid for pq in p.items] for p in b.papers])
        c = generate_round(self.questions, self.bp, seed=2025)
        self.assertNotEqual([[pq.question.qid for pq in p.items] for p in a.papers],
                            [[pq.question.qid for pq in p.items] for p in c.papers])

    def test_errors(self):
        with self.assertRaises(GenerationError):
            generate_round([], self.bp)
        with self.assertRaises(GenerationError):
            generate_round(self.questions, PaperBlueprint(0, 0, 0))
        only_single = [make_question(i, QType.SINGLE) for i in range(5)]
        with self.assertRaises(GenerationError):
            generate_round(only_single, PaperBlueprint(2, 1, 0))

    def test_quota_larger_than_bank(self):
        qs = [make_question(i, QType.SINGLE) for i in range(3)]
        rnd = generate_round(qs, PaperBlueprint(5, 0, 0), seed=1)
        self.assertEqual(rnd.paper_count, 1)
        self.assertEqual(rnd.papers[0].total, 5)
        self.assertTrue(any("重复" in w for w in rnd.warnings))

    def test_fixed_order_survives_paper(self):
        q = make_question(999, QType.MULTIPLE, n_options=4, fixed=True, answer=["B", "C"])
        qs = [q] + [make_question(i, QType.SINGLE) for i in range(4)]
        rnd = generate_round(qs, PaperBlueprint(1, 1, 0), seed=3)
        found = [pq for p in rnd.papers for pq in p.items if pq.question.fixed_order]
        self.assertTrue(found)
        self.assertEqual(found[0].question.answer_display, "BC")


# ================================================================ 练习范围
class TestScope(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pd_scope_"))
        self.questions = mixed_bank(12)      # 4 单选 / 4 多选 / 4 判断
        self.store = ProgressStore.load_for("题库", self.questions, self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_scope_labels(self):
        self.assertIs(Scope.from_label("只练多选"), Scope.MULTIPLE)
        self.assertIs(Scope.SINGLE.qtype, QType.SINGLE)
        self.assertIsNone(Scope.ALL.qtype)

    def test_filter_by_type(self):
        for scope, qtype in ((Scope.SINGLE, QType.SINGLE), (Scope.MULTIPLE, QType.MULTIPLE),
                             (Scope.JUDGE, QType.JUDGE)):
            s = PracticeSession(self.questions, self.store, scope=scope, seed=1)
            self.assertEqual(s.total, 4)
            for idx in s.order:
                self.assertIs(self.questions[idx].qtype, qtype)
        s_all = PracticeSession(self.questions, self.store, scope=Scope.ALL, seed=1)
        self.assertEqual(s_all.total, 12)

    def test_scope_combines_with_mode(self):
        for i, q in enumerate(self.questions):
            self.store.progress.apply_answer(q, correct=(i % 2 == 0))
        self.store.save()
        s = PracticeSession(self.questions, self.store, scope=Scope.JUDGE,
                            mode=PracticeMode.WRONG, seed=1)
        for idx in s.order:
            self.assertIs(self.questions[idx].qtype, QType.JUDGE)
            self.assertTrue(self.store.record_of(self.questions[idx]).in_wrong_book)

    def test_scope_stats(self):
        s = PracticeSession(self.questions, self.store, scope=Scope.SINGLE, seed=1)
        self.assertEqual(s.scope_stats()["total"], 4)
        self.assertEqual(s.stats()["total"], 12)

    def test_rebuild_keep_scope(self):
        s = PracticeSession(self.questions, self.store, scope=Scope.MULTIPLE, seed=1)
        s.rebuild(PracticeMode.RANDOM)
        self.assertIs(s.qtype_filter, QType.MULTIPLE)
        self.assertEqual(s.total, 4)


# ================================================================ 打乱分离
class TestSeparateShuffle(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pd_shuf_"))
        self.questions = ([make_question(i, QType.SINGLE, n_options=4) for i in range(6)]
                          + [make_question(i, QType.MULTIPLE, n_options=4, answer=["A", "C"])
                             for i in range(6)])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _session(self, single, multiple):
        store = ProgressStore.load_for("题库", self.questions, self.tmp)
        return PracticeSession(self.questions, store, shuffle_single=single,
                               shuffle_multiple=multiple, seed=5)

    def test_disable_single_only(self):
        s = self._session(False, True)
        for _ in range(s.total):
            item = s.current_item()
            if item.qtype is QType.SINGLE:
                self.assertFalse(item.shuffled)
                self.assertEqual(item.texts, item.question.options)
            else:
                self.assertTrue(item.shuffled)
            s.advance()

    def test_disable_multiple_only(self):
        s = self._session(True, False)
        for _ in range(s.total):
            item = s.current_item()
            if item.qtype is QType.MULTIPLE:
                self.assertFalse(item.shuffled)
                self.assertEqual(item.texts, item.question.options)
            else:
                self.assertTrue(item.shuffled)
            s.advance()

    def test_legacy_shuffle_options_flag(self):
        s = self._session(True, True)
        s2 = PracticeSession(self.questions, s.store, shuffle_options=False, seed=1)
        self.assertFalse(s2.shuffle_single)
        self.assertFalse(s2.shuffle_multiple)

    def test_fixed_never_shuffled_even_when_enabled(self):
        q = make_question(100, QType.MULTIPLE, n_options=4, fixed=True, answer=["B", "C"])
        item = build_item(q, random.Random(1), True)
        self.assertFalse(item.shuffled)
        self.assertEqual(item.texts, q.options)


# ================================================================ 模拟考试
class TestExamSession(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pd_exam_"))
        self.questions = ([make_question(i, QType.SINGLE) for i in range(10)]
                          + [make_question(i, QType.MULTIPLE, answer=["A", "C"]) for i in range(6)]
                          + [make_question(i, QType.JUDGE) for i in range(4)])
        self.store = ProgressStore.load_for("题库", self.questions, self.tmp)
        self.rnd = generate_round(self.questions, PaperBlueprint(5, 3, 2), seed=9)
        self.paper = self.rnd.papers[0]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_paper_composition(self):
        self.assertEqual(self.paper.total, 10)
        self.assertEqual(self.paper.count_of(QType.SINGLE), 5)
        self.assertEqual(self.paper.count_of(QType.MULTIPLE), 3)
        self.assertEqual(self.paper.count_of(QType.JUDGE), 2)

    def test_no_feedback_before_submit(self):
        exam = ExamSession(self.paper, self.store, seed=1)
        self.assertFalse(exam.submitted)
        self.assertIsNone(exam.result)
        exam.set_answer(0, set(exam.item(0).shown_answer))
        self.assertFalse(exam.submitted)
        self.assertEqual(exam.answered_count, 1)

    def test_scoring_and_details(self):
        exam = ExamSession(self.paper, self.store, seed=1)
        exam.set_answer(0, set(exam.item(0).shown_answer))     # 对
        exam.set_answer(1, set(exam.item(0).shown_answer))     # 故意错
        # 其余不答
        result = exam.submit()
        self.assertTrue(exam.submitted)
        self.assertEqual(result.total, 10)
        self.assertEqual(result.correct, 1)
        self.assertEqual(result.wrong, 1)
        self.assertEqual(result.unanswered, 8)
        self.assertAlmostEqual(result.accuracy, 0.1)
        self.assertAlmostEqual(result.score, exam.score_of(exam.item(0).qtype))
        self.assertAlmostEqual(result.full_score, 5 * 1 + 3 * 2 + 2 * 1)
        self.assertEqual(len(result.details), 10)
        self.assertTrue(result.details[0]["correct"])
        self.assertTrue(result.details[9]["unanswered"])

    def test_all_correct_full_score(self):
        exam = ExamSession(self.paper, self.store, seed=1)
        for i in range(exam.total):
            exam.set_answer(i, set(exam.item(i).shown_answer))
        result = exam.submit()
        self.assertEqual(result.correct, exam.total)
        self.assertEqual(result.wrong, 0)
        self.assertEqual(result.unanswered, 0)
        self.assertAlmostEqual(result.score, result.full_score)

    def test_exam_records_progress_and_history(self):
        exam = ExamSession(self.paper, self.store, seed=1)
        exam.set_answer(0, set(exam.item(0).shown_answer))
        exam.set_answer(1, {lab for lab in exam.item(1).labels if lab not in exam.item(1).shown_answer})
        exam.submit()
        stats = self.store.stats(self.questions)
        self.assertEqual(stats["done"], 10)          # 未答也计入"已练"（按错误计）
        self.assertEqual(stats["right"], 1)
        self.assertEqual(stats["wrong"], 9)
        self.assertEqual(stats["wrong_book"], 9)
        self.assertEqual(len(self.store.exam_history()), 1)
        top = self.store.exam_history()[0]
        self.assertEqual(top["paper_label"], self.paper.label)
        self.assertEqual(top["correct"], 1)

    def test_exam_can_skip_progress_recording(self):
        exam = ExamSession(self.paper, self.store, seed=1, record_progress=False)
        exam.set_answer(0, set(exam.item(0).shown_answer))
        exam.submit()
        self.assertEqual(self.store.stats(self.questions)["done"], 0)
        self.assertEqual(len(self.store.exam_history()), 1)   # 成绩仍记录

    def test_submit_is_idempotent(self):
        exam = ExamSession(self.paper, self.store, seed=1)
        r1 = exam.submit()
        r2 = exam.submit()
        self.assertIs(r1, r2)
        self.assertEqual(len(self.store.exam_history()), 1)

    def test_answers_locked_after_submit(self):
        exam = ExamSession(self.paper, self.store, seed=1)
        exam.set_answer(0, set(exam.item(0).shown_answer))
        exam.submit()
        exam.set_answer(1, {"A"})
        self.assertFalse(exam.answered(1))

    def test_exam_options_remapped(self):
        exam = ExamSession(self.paper, self.store, seed=1, shuffle_single=True, shuffle_multiple=True)
        for i, item in enumerate(exam.items):
            if item.qtype is QType.MULTIPLE:
                got = {item.texts[OPTION_LABELS.index(c)] for c in item.shown_answer}
                want = {item.question.options[OPTION_LABELS.index(c)] for c in item.question.answer_letters}
                self.assertEqual(got, want)
            exam.set_answer(i, set(item.shown_answer))
        self.assertEqual(exam.submit().correct, exam.total)

    def test_exam_history_cap(self):
        for _ in range(35):
            ExamSession(self.paper, self.store, seed=1).submit()
        self.assertEqual(len(self.store.exam_history()), 30)


# ================================================================ 端到端（合成题库）
@unittest.skipUnless(REAL_BANK.exists(), f"未找到合成题库：{REAL_BANK}")
class TestRealBankFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pd_e2e_"))
        self.bank = load_bank(REAL_BANK)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_bank_stats(self):
        stats = bank_stats(self.bank.questions)
        self.assertEqual(stats["total"], 52)
        self.assertEqual((stats["single"], stats["multiple"], stats["judge"]), (26, 14, 12))
        self.assertEqual(stats["fixed"], 1)

    def test_practice_then_resume(self):
        """完整流程：练 30 题 → 关软件 → 重开 → 进度与位置恢复。"""
        store = ProgressStore.load_for("样例题库", self.bank.questions, self.tmp)
        s = PracticeSession(self.bank.questions, store, mode=PracticeMode.ORDER,
                            shuffle_options=True, seed=7)
        for i in range(30):
            item = s.current_item()
            select = set(item.shown_answer) if i % 3 else {lab for lab in item.labels
                                                           if lab not in item.shown_answer}
            s.submit(select)
            s.advance()
        s.save_position()

        store2 = ProgressStore.load_for("样例题库", self.bank.questions, self.tmp)
        s2 = PracticeSession(self.bank.questions, store2, mode=PracticeMode.ORDER,
                             shuffle_options=True, seed=8)
        self.assertTrue(s2.restore_position())
        self.assertEqual(s2.stats()["done"], 30)
        self.assertEqual(s2.position, s.position)
        self.assertEqual(s2.stats()["wrong_book"], 10)   # i%3==0 的 10 题答错
        self.assertAlmostEqual(s2.stats()["accuracy"], 20 / 30, places=6)

    def test_all_three_types_practiced(self):
        store = ProgressStore.load_for("样例题库", self.bank.questions, self.tmp)
        s = PracticeSession(self.bank.questions, store, mode=PracticeMode.ORDER,
                            shuffle_options=True, seed=3)
        seen = {QType.SINGLE: 0, QType.MULTIPLE: 0, QType.JUDGE: 0}
        for _ in range(s.total):
            item = s.current_item()
            seen[item.qtype] += 1
            self.assertTrue(s.submit(set(item.shown_answer)).correct,
                            f"按显示答案作答应判对：{item.stem[:20]}")
            s.advance()
        self.assertEqual(seen[QType.SINGLE], 26)
        self.assertEqual(seen[QType.MULTIPLE], 14)
        self.assertEqual(seen[QType.JUDGE], 12)
        self.assertEqual(s.stats()["accuracy"], 1.0)
        self.assertEqual(s.stats()["wrong_book"], 0)

    def test_shuffling_actually_happens(self):
        store = ProgressStore.load_for("样例题库", self.bank.questions, self.tmp)
        s = PracticeSession(self.bank.questions, store, mode=PracticeMode.ORDER,
                            shuffle_options=True, seed=11)
        shuffled = 0
        total_choice = 0
        for _ in range(s.total):
            item = s.current_item()
            if item.qtype is not QType.JUDGE:
                total_choice += 1
                if item.shuffled:
                    shuffled += 1
            s.advance()
        self.assertGreater(shuffled, total_choice * 0.9)   # 绝大多数被打乱

    def test_paper_round_on_fixture_bank(self):
        """合成 52 题库 + 每卷 20/10/10 → 一轮 2 张、覆盖完整、每张 40 题。"""
        bp = PaperBlueprint(20, 10, 10)
        self.assertEqual(min_round_length(self.bank.questions, bp), 2)
        rnd = generate_round(self.bank.questions, bp, seed=2026)
        self.assertEqual(rnd.paper_count, 2)
        self.assertTrue(rnd.coverage_ok)
        self.assertEqual(rnd.coverage, {"single": (26, 26), "multiple": (14, 14), "judge": (12, 12)})
        for p in rnd.papers:
            self.assertEqual(p.total, 40)
            self.assertEqual((p.count_of(QType.SINGLE), p.count_of(QType.MULTIPLE),
                              p.count_of(QType.JUDGE)), (20, 10, 10))
        seen = {pq.question.qid for p in rnd.papers for pq in p.items}
        self.assertEqual(len(seen), 52)

    def test_exam_on_real_bank_paper(self):
        """合成题库上开一场模拟考试：全对得满分，未答按错误计。"""
        rnd = generate_round(self.bank.questions, PaperBlueprint(20, 10, 10), seed=5)
        store = ProgressStore.load_for("样例题库", self.bank.questions, self.tmp)
        exam = ExamSession(rnd.papers[0], store, seed=1)
        self.assertEqual(exam.total, 40)
        self.assertAlmostEqual(exam.full_score, 20 * 1 + 10 * 2 + 10 * 1)
        for i in range(38):
            exam.set_answer(i, set(exam.item(i).shown_answer))
        result = exam.submit()
        self.assertEqual(result.correct, 38)
        self.assertEqual(result.unanswered, 2)
        self.assertEqual(result.wrong, 0)
        self.assertAlmostEqual(result.score + 2 * 1.0, result.full_score)  # 未答的 2 题不得分
        self.assertEqual(result.per_type["single"]["correct"], 20)
        self.assertEqual(len(store.exam_history()), 1)


@unittest.skipUnless(SAMPLE_BANK.exists(), f"未找到示例题库：{SAMPLE_BANK}")
class TestFixedQuestionFromSample(unittest.TestCase):
    """示例题库中含一道「（定）」题，验证其在练习中永不打乱。"""

    def test_fixed_question(self):
        bank = load_bank(SAMPLE_BANK)
        fixed = [q for q in bank.questions if q.fixed_order]
        self.assertEqual(len(fixed), 1)
        q = fixed[0]
        item = build_item(q, random.Random(1), True)
        self.assertFalse(item.shuffled)
        self.assertEqual(item.texts, q.options)
        self.assertEqual(item.answer_display(), "BC")
        self.assertTrue(item.judge({"B", "C"}))
        self.assertFalse(item.judge({"B"}))


# ================================================================ 界面自检
@unittest.skipUnless(REAL_BANK.exists(), f"未找到合成题库：{REAL_BANK}")
class TestGuiSelftest(unittest.TestCase):
    def test_gui_practice_flow(self):
        try:
            import tkinter
            root = tkinter.Tk()
            root.destroy()
        except Exception as exc:
            self.skipTest(f"当前环境不支持 tkinter：{exc}")

        from paperdrill.gui import selftest

        with tempfile.TemporaryDirectory() as tmp:
            result_file = Path(tmp) / "result.json"
            try:
                code = selftest(str(REAL_BANK), str(result_file), str(Path(tmp) / "progress"), 30, 12345)
            except Exception as exc:                   # 例如 CI 上 Tcl 初始化失败
                self.skipTest(f"当前环境无法运行界面自检：{exc}")
            data = json.loads(result_file.read_text(encoding="utf-8")) if result_file.exists() else {}
            self.assertEqual(code, 0, json.dumps(data, ensure_ascii=False)[:1200])
            self.assertTrue(data["tk"]["window_created"])
            self.assertEqual(data["bank"]["total"], 52)
            self.assertEqual(data["answered"], {"correct": 15, "wrong": 15})
            self.assertTrue(data["progress_saved"])
            self.assertTrue(data["progress_restored"])
            # 模拟考试 40 题全部计入进度（与练习过的题目取并集）
            self.assertGreater(data["stats_after_exam"]["done"], 30)
            self.assertEqual(data["stats_restored"], data["stats_after_exam"])
            # 按题型范围
            self.assertEqual(data["scope_single_total"], 26)
            self.assertEqual(data["scope_multiple_total"], 14)
            self.assertEqual(data["scope_judge_total"], 12)
            # 试卷轮次覆盖
            paper = data["paper"]
            self.assertEqual(paper["round_length"], 2)
            self.assertEqual(paper["auto_round_length"], 2)
            self.assertTrue(paper["coverage_ok"])
            self.assertEqual(paper["coverage"], {"single": [26, 26], "multiple": [14, 14],
                                                 "judge": [12, 12]})
            self.assertEqual(paper["totals"], [40, 40])
            self.assertEqual(paper["single_counts"], [20, 20])
            self.assertEqual(paper["multiple_counts"], [10, 10])
            # 补题统计：第 1 张无补题；第 2 张题目取尽后补足
            self.assertEqual(paper["reused"], [0, 28])
            # 模拟考试
            exam = data["exam"]
            self.assertEqual(exam["total"], 40)
            self.assertEqual(exam["correct"], 20)
            self.assertEqual(exam["wrong"], 17)
            self.assertEqual(exam["unanswered"], 3)
            self.assertAlmostEqual(exam["full_score"], 50.0)
            self.assertTrue(data["exam_ui_hides_result"])
            self.assertEqual(data["exam_history"], 1)
            self.assertEqual(data["exam_history_restored"], 1)
            # 快捷键（回归：Enter / 小键盘 Enter / 输入框守卫）
            kb = data["keyboard"]
            for key in ("return_bound", "kp_enter_bound", "key_select_answers",
                        "practice_enter_advances", "exam_enter_advances", "input_guard"):
                self.assertTrue(kb.get(key), f"快捷键校验未通过：{key}")
            # 重做（回归：重新开始本轮 / 错题重练）
            redo = data["redo"]
            for key in ("restart_options_enabled", "restart_reanswerable", "wrong_mode_answerable"):
                self.assertTrue(redo.get(key), f"重做校验未通过：{key}")
            self.assertEqual(redo["restart_position"], 1)
            self.assertGreater(redo["wrong_mode_total"], 0)
            self.assertEqual(data["wrong_mode_total"], data["stats_restored"]["wrong_book"])
            self.assertGreater(data["wrong_cleared"], 0)
            self.assertEqual(data["stats_after_reset"]["done"], 0)
            bad = [m for m in data["messages"] if m["kind"] in ("error", "warn")]
            self.assertEqual(bad, [])


# ================================================================ 快捷键回归
@unittest.skipUnless(REAL_BANK.exists(), f"未找到合成题库：{REAL_BANK}")
class TestKeyboardShortcuts(unittest.TestCase):
    """快捷键回归测试（BUG：Enter / 小键盘 Enter 失效、输入框按键被劫持）。

    通过 ``widget.event_generate(...)`` 投递真实 Tk 事件，与"焦点在该控件时按下按键"
    的 bind tags 派发路径一致。
    """

    @classmethod
    def setUpClass(cls):
        try:
            import tkinter
            root = tkinter.Tk()
            root.destroy()
        except Exception as exc:
            raise unittest.SkipTest(f"当前环境不支持 tkinter：{exc}") from exc

    def setUp(self):
        import paperdrill.store as store_mod
        from paperdrill.config import AppSettings
        from paperdrill.gui import PaperDrillApp

        self.tmp = Path(tempfile.mkdtemp(prefix="pd_key_"))
        self._orig_progress_dir = store_mod.progress_dir
        store_mod.progress_dir = lambda: self.tmp / "progress"
        self.addCleanup(lambda: setattr(store_mod, "progress_dir", self._orig_progress_dir))
        self.addCleanup(shutil.rmtree, self.tmp, True)

        try:
            self.app = PaperDrillApp(None, settings=AppSettings(bank_path="", auto_next_on_correct=False),
                                     settings_path=self.tmp / "settings.json")
        except Exception as exc:                       # 例如 CI 上 Tcl 初始化失败
            self.skipTest(f"当前环境无法创建 Tk 窗口：{exc}")
        self.addCleanup(self._destroy_app)
        # 说明：Tk 的键盘事件按"焦点窗口"派发；同进程内第 2 个及以后的 Tk 根在 withdraw
        # 状态下没有焦点窗口，event_generate 会被丢弃。因此这里把窗口显示出来（缩到最小
        # 并设透明），使其拥有焦点窗口，测试才能真正验证按键派发链路。
        self.app.geometry("1x1+0+0")
        self.app.deiconify()
        self.app.update()
        try:
            self.app.attributes("-alpha", 0.0)
        except Exception:
            pass
        self.app.focus_force()
        self.app.update()
        self.app._import_bank(str(REAL_BANK))
        self.app.update()

    def _destroy_app(self):
        try:
            self.app.destroy()
        except Exception:
            pass

    # ---------------------------------------------------------------- 工具
    def fire(self, widget, sequence="<Return>") -> None:
        """把按键事件投递到指定控件（先让该控件获得焦点，符合 Tk 的焦点路由）。"""
        widget.event_generate(sequence, when="now")
        self.app.update()

    def type_key(self, widget, keysym: str) -> None:
        try:
            widget.focus_set()
            self.app.update()
        except Exception:
            pass
        widget.event_generate("<KeyPress>", keysym=keysym, when="now")
        self.app.update()

    def first_option_widget(self):
        return next((w for w in self.app._answer_widgets if w.winfo_exists()), None)

    def goto_scope(self, scope) -> None:
        self.app._set_scope(scope)
        self.app.update()

    def _find_input_widget(self):
        found = []

        def walk(widget):
            for child in widget.winfo_children():
                if child.winfo_class() in ("TSpinbox", "TEntry", "Entry", "Spinbox"):
                    found.append(child)
                walk(child)

        walk(self.app)
        return found[0] if found else None

    class _FakeEvent:
        """用真实事件对象驱动处理器。

        真实 Tk 的按键事件按"焦点窗口"派发；本自动化环境里进程无法获得系统焦点，
        子控件无法成为焦点窗口（focus_force 无效），因此无法用 event_generate 模拟
        "焦点在输入框里打字"。守卫逻辑只依赖 event.widget，用事件对象驱动即可精确覆盖。
        """

        def __init__(self, widget, char=""):
            self.widget = widget
            self.char = char

    # ---------------------------------------------------------------- 练习页
    def test_enter_advances_after_answering(self):
        """单选题作答后按主键盘 Enter，应进入下一题。"""
        from paperdrill.practice import Scope

        self.goto_scope(Scope.SINGLE)
        widget = self.first_option_widget()
        self.assertIsNotNone(widget)
        widget.invoke()
        self.app.update()
        before = self.app.session.position
        self.fire(self.app)
        self.assertEqual(self.app.session.position, before + 1)

    def test_enter_from_disabled_option_widget(self):
        """作答后控件被禁用、焦点仍在其上时，按 Enter 也应下一题。"""
        from paperdrill.practice import Scope

        self.goto_scope(Scope.SINGLE)
        widget = self.first_option_widget()
        widget.invoke()
        self.app.update()
        before = self.app.session.position
        self.fire(widget)
        self.assertEqual(self.app.session.position, before + 1)

    def test_enter_submits_multiple_choice(self):
        """多选题勾选后按 Enter 应提交并判题。"""
        from paperdrill.practice import Scope

        self.goto_scope(Scope.MULTIPLE)
        item = self.app.session.current_item()
        self.assertEqual(item.qtype, QType.MULTIPLE)
        self.app._multi_vars[item.labels[0]].set(True)
        self.assertFalse(self.app._answered)
        self.fire(self.app)
        self.assertTrue(self.app._answered, "Enter 未触发多选提交")
        self.assertTrue(self.app.session.current_record().done)

    # ---------------------------------------------------------------- 小键盘回车
    def test_keypad_enter_is_bound(self):
        """小键盘回车必须已绑定（Windows 的 Tk 把两个回车都报为 Return，
        因此这里断言绑定存在，并用合成事件直接驱动处理器）。"""
        self.assertTrue(self.app.bind_all("<KP_Enter>"), "<KP_Enter> 未绑定")
        self.assertTrue(self.app.bind_all("<Return>"), "<Return> 未绑定")

    def test_keypad_enter_handler_advances(self):
        """小键盘回车处理器在练习页应等效于主键盘回车。"""
        from paperdrill.practice import Scope

        self.goto_scope(Scope.SINGLE)
        widget = self.first_option_widget()
        widget.invoke()
        self.app.update()
        before = self.app.session.position
        self.app._on_enter_key(self._FakeEvent(self.app))
        self.assertEqual(self.app.session.position, before + 1)

    def test_keypad_enter_handler_advances_in_exam(self):
        """小键盘回车处理器在考试页应跳到下一题。"""
        self._prepare_exam()
        before = self.app.exam_index
        self.app._on_enter_key(self._FakeEvent(self.app))
        self.assertEqual(self.app.exam_index, before + 1)

    def test_keypad_enter_advances_in_exam(self):
        """能合成 KP_Enter 时，事件也应触发（Windows Tk 不支持合成，跳过）。"""
        self._prepare_exam()
        before = self.app.exam_index
        hits: list[int] = []
        real = self.app._on_enter
        self.app._on_enter = lambda: (hits.append(1), real())[1]     # type: ignore[assignment]
        try:
            self.fire(self.app, "<KP_Enter>")
        finally:
            self.app._on_enter = real                                # type: ignore[assignment]
        if not hits and self.app.exam_index == before:
            self.skipTest("当前平台 Tk 无法合成 <KP_Enter>（keymap 无该 keysym），"
                          "已由 test_keypad_enter_handler_advances_in_exam 覆盖处理器逻辑")
        self.assertEqual(self.app.exam_index, before + 1)

    # ---------------------------------------------------------------- 输入框守卫
    def test_shortcuts_do_not_hijack_spinbox_typing_single(self):
        """焦点在输入框（蓝图题量 Spinbox）时，敲数字不得改变练习选项。"""
        spin = self._find_input_widget()
        self.assertIsNotNone(spin, "未找到输入控件")
        before = self.app._option_vars.get("choice").get()
        self.app._on_key(self._FakeEvent(spin, "1"))
        self.assertEqual(self.app._option_vars.get("choice").get(), before)

    def test_shortcuts_do_not_hijack_spinbox_typing_multiple(self):
        """焦点在输入框时，敲数字不得勾选多选题选项。"""
        from paperdrill.practice import Scope

        self.goto_scope(Scope.MULTIPLE)
        spin = self._find_input_widget()
        self.assertIsNotNone(spin)
        before = {k: v.get() for k, v in self.app._multi_vars.items()}
        self.app._on_key(self._FakeEvent(spin, "2"))
        after = {k: v.get() for k, v in self.app._multi_vars.items()}
        self.assertEqual(before, after)

    def test_enter_in_input_box_does_not_jump(self):
        """焦点在输入框时按 Enter 不应跳题（避免录题库参数时误跳）。"""
        spin = self._find_input_widget()
        self.assertIsNotNone(spin)
        pos = self.app.session.position
        self.app._on_enter_key(self._FakeEvent(spin))
        self.assertEqual(self.app.session.position, pos)

    # ---------------------------------------------------------------- 键盘答题
    def test_number_key_answers_single_choice_immediately(self):
        """按数字键选择单选答案后应立即判定（与鼠标点选一致）。"""
        from paperdrill.practice import Scope

        self.goto_scope(Scope.SINGLE)
        self.app.focus_force()
        self.app.update()
        self.assertFalse(self.app._answered)
        self.app.event_generate("<KeyPress>", keysym="1", when="now")
        self.app.update()
        self.assertTrue(self.app._answered, "数字键选择后未立即判定")
        self.assertTrue(self.app.session.current_record().done)

    def test_enter_submits_keyboard_selected_single(self):
        """键盘选中单选后按 Enter 也应能提交（兼容未自动判定的情况）。"""
        from paperdrill.practice import Scope

        self.goto_scope(Scope.SINGLE)
        self.app._option_vars["choice"].set("A")      # 模拟只有选择、尚未判定
        self.assertFalse(self.app._answered)
        self.app._on_enter_key(self._FakeEvent(self.app))
        self.assertTrue(self.app._answered)

    # ---------------------------------------------------------------- 考试页
    def _prepare_exam(self):
        self.app.paper_single_var.set("5")
        self.app.paper_multiple_var.set("3")
        self.app.paper_judge_var.set("2")
        self.app._generate_round()
        self.assertIsNotNone(self.app.round)
        self.app._start_exam(self.app.round.papers[0])
        self.app.notebook.select(1)
        self.app.update()

    def test_enter_advances_in_exam(self):
        """模拟考试页按主键盘 Enter，应跳到下一题。"""
        self._prepare_exam()
        before = self.app.exam_index
        self.fire(self.app)
        self.assertEqual(self.app.exam_index, before + 1, "考试页 Enter 未生效")

    def test_start_exam_switches_to_exam_tab(self):
        """从菜单直接开始考试时，应自动切到「模拟考试」标签页。"""
        self.app.paper_single_var.set("3")
        self.app.paper_multiple_var.set("2")
        self.app.paper_judge_var.set("1")
        self.app._generate_round()
        self.app.notebook.select(0)                  # 先停在练习页
        self.app.update()
        self.assertEqual(self.app.notebook.index("current"), 0)
        self.app._start_exam_selected()              # 相当于菜单/按钮启动
        self.app.update()
        self.assertEqual(self.app.notebook.index("current"), 1, "未自动切换到模拟考试页")

    def test_enter_in_exam_keeps_answer(self):
        """考试页用 Enter 翻页时，已作答内容不应被清除。"""
        self._prepare_exam()
        item = self.app.exam.item(self.app.exam_index)
        letter = item.labels[-1]
        self.app._exam_pick(letter)
        self.app.update()
        self.fire(self.app)
        self.assertTrue(self.app.exam.answered(0))
        self.assertIn(letter, self.app.exam.answers[0])

    def test_enter_at_last_question_hints_submit(self):
        """考试最后一题按 Enter 应提示交卷而不是越界。"""
        self._prepare_exam()
        last = self.app.exam.total - 1
        self.app._exam_goto(last)
        self.app.update()
        self.fire(self.app)
        self.assertEqual(self.app.exam_index, last)
        self.assertIn("交卷", self.app.status_var.get())

    # ---------------------------------------------------------------- 弹窗守卫
    def test_shortcuts_ignored_in_other_windows(self):
        """弹窗/其它窗口中的按键不应影响主窗口练习。"""
        import tkinter as tk

        from paperdrill.practice import Scope

        self.goto_scope(Scope.MULTIPLE)          # 让断言有意义（否则多选变量为空）
        win = tk.Toplevel(self.app)
        self.addCleanup(win.destroy)
        entry = tk.Entry(win)
        entry.pack()
        win.update()
        before = {k: v.get() for k, v in self.app._multi_vars.items()}
        self.assertTrue(before, "多选题选项未渲染，测试无效")

        # 事件来自其它窗口的控件 → 守卫应拒绝
        self.app._on_key(self._FakeEvent(entry, "1"))
        self.app._on_enter_key(self._FakeEvent(entry))
        self.assertEqual({k: v.get() for k, v in self.app._multi_vars.items()}, before)

        # 弹窗自身所在窗口不是主窗口
        self.assertFalse(self.app._shortcut_allowed(self._FakeEvent(entry)))
        self.assertTrue(self.app._shortcut_allowed(self._FakeEvent(self.app)))


# ================================================================ 重做已作答题目
@unittest.skipUnless(REAL_BANK.exists(), f"未找到合成题库：{REAL_BANK}")
class TestRedoAnsweredQuestions(unittest.TestCase):
    """BUG：已作答的题目（回看/重新开始本轮/错题重练）被锁定且剧透答案，无法重做。"""

    @classmethod
    def setUpClass(cls):
        try:
            import tkinter
            root = tkinter.Tk()
            root.destroy()
        except Exception as exc:
            raise unittest.SkipTest(f"当前环境不支持 tkinter：{exc}") from exc

    def setUp(self):
        import paperdrill.store as store_mod
        from paperdrill.config import AppSettings
        from paperdrill.gui import PaperDrillApp

        self.tmp = Path(tempfile.mkdtemp(prefix="pd_redo_"))
        self._orig = store_mod.progress_dir
        store_mod.progress_dir = lambda: self.tmp / "progress"
        self.addCleanup(lambda: setattr(store_mod, "progress_dir", self._orig))
        self.addCleanup(shutil.rmtree, self.tmp, True)

        try:
            self.app = PaperDrillApp(None, settings=AppSettings(bank_path="", auto_next_on_correct=False),
                                     settings_path=self.tmp / "settings.json")
        except Exception as exc:                       # 例如 CI 上 Tcl 初始化失败
            self.skipTest(f"当前环境无法创建 Tk 窗口：{exc}")
        self.addCleanup(lambda: self.app.destroy())
        self.app.withdraw()
        self.app.update()
        self.app._import_bank(str(REAL_BANK))
        self.app.update()

    # ---------------------------------------------------------------- 工具
    def option_widgets(self):
        return [w for w in self.app._answer_widgets if w.winfo_exists()]

    def assert_options_enabled(self, message="选项控件不应被禁用"):
        widgets = self.option_widgets()
        self.assertTrue(widgets, "当前题没有选项控件")
        disabled = [w for w in widgets if "disabled" in w.state()]
        self.assertFalse(disabled, f"{message}（被禁用 {len(disabled)}/{len(widgets)} 项）")

    def answer_current(self, index: int = 0) -> int:
        """作答当前题（多选题会自动提交），返回作答前的作答次数。"""
        from paperdrill.models import QType

        widgets = self.option_widgets()
        self.assertTrue(widgets, "当前题没有选项控件")
        before = self.app.session.current_record().attempts
        widgets[min(index, len(widgets) - 1)].invoke()
        self.app.update()
        item = self.app.session.current_item()
        if item is not None and item.qtype is QType.MULTIPLE and not self.app._answered:
            self.app._submit()
            self.app.update()
        return before

    def goto_scope(self, scope):
        self.app._set_scope(scope)
        self.app.update()

    # ---------------------------------------------------------------- 用例
    def test_restart_round_allows_answering_again(self):
        """「重新开始本轮」后，已作答的题目必须可以重新作答。"""
        from paperdrill.practice import Scope

        self.goto_scope(Scope.SINGLE)
        before = self.answer_current()
        self.assertEqual(self.app.session.current_record().attempts, before + 1)

        self.app._restart_round()
        self.app.update()
        self.assertEqual(self.app.session.position, 1)
        self.assertTrue(self.app.session.current_record().done)
        self.assertFalse(self.app._answered, "回看状态被锁定为「已作答」")
        self.assert_options_enabled("重新开始本轮后选项被禁用")

        baseline = self.app.session.current_record().attempts
        self.answer_current()
        self.assertEqual(self.app.session.current_record().attempts, baseline + 1,
                         "重新开始本轮后无法重新作答")

    def test_wrong_mode_questions_are_answerable(self):
        """错题重练：错题必须能重新作答（这是该模式存在的意义）。"""
        from paperdrill.practice import PracticeMode, Scope

        self.goto_scope(Scope.SINGLE)
        item = self.app.session.current_item()
        wrong_index = next(i for i, lab in enumerate(item.labels) if lab not in item.shown_answer)
        self.answer_current(wrong_index)
        self.assertEqual(self.app.session.current_record().last, "wrong")

        self.app._set_mode(PracticeMode.WRONG)
        self.app.update()
        self.assertEqual(self.app.session.total, 1, "错题重练队列应包含 1 道错题")
        self.assert_options_enabled("错题重练的题目被禁用")
        self.assertFalse(self.app._answered)

        baseline = self.app.session.current_record().attempts
        self.answer_current(wrong_index)
        self.assertEqual(self.app.session.current_record().attempts, baseline + 1,
                         "错题重练中无法重新作答")

    def test_wrong_mode_correct_answer_removes_from_book(self):
        """错题重练中答对，该题应移出错题本。"""
        from paperdrill.practice import PracticeMode, Scope

        self.goto_scope(Scope.SINGLE)
        item = self.app.session.current_item()
        wrong_index = next(i for i, lab in enumerate(item.labels) if lab not in item.shown_answer)
        self.answer_current(wrong_index)

        self.app._set_mode(PracticeMode.WRONG)
        self.app.update()
        item = self.app.session.current_item()
        right_index = next(i for i, lab in enumerate(item.labels) if lab in item.shown_answer)
        self.answer_current(right_index)
        self.assertFalse(self.app.session.current_record().in_wrong_book)
        self.assertEqual(self.app.session.stats()["wrong_book"], 0)

    def test_revisit_answered_question_is_answerable(self):
        """回看已作答的题目时不应锁定，也不应直接剧透答案。"""
        from paperdrill.practice import Scope

        self.goto_scope(Scope.SINGLE)
        self.answer_current()
        self.app._navigate(1)
        self.app._navigate(-1)              # 回到第 1 题
        self.assertTrue(self.app.session.current_record().done)
        self.assertFalse(self.app._answered, "回看时被锁定")
        self.assert_options_enabled("回看已作答题目时选项被禁用")
        self.assertEqual(self.app.analysis_text_var.get(), "", "回看时直接显示了答案/解析")

    def test_revisit_banner_shows_previous_result(self):
        """回看时提示上次结果，并说明可以重新作答。"""
        from paperdrill.practice import Scope

        self.goto_scope(Scope.SINGLE)
        self.answer_current()
        self.app._navigate(1)
        self.app._navigate(-1)
        text = self.app.feedback_var.get()
        self.assertTrue(("上次" in text) or ("重新作答" in text), f"回看提示缺失：{text}")

    def test_show_answer_button_enabled_on_single_question(self):
        """「不会，看答案」按钮在各类题型下都应可用（历史上会被上一题残留状态禁用）。"""
        from paperdrill.practice import Scope

        self.goto_scope(Scope.MULTIPLE)
        self.answer_current()                      # 作答多选题（会禁用两个按钮）
        self.goto_scope(Scope.SINGLE)
        self.assertNotIn("disabled", self.app.show_btn.state(),
                         "切到单选题后「不会，看答案」仍被禁用")
        self.assertIsNotNone(self.app.session.current_item())

    def test_clear_wrong_book_refreshes_wrong_queue(self):
        """清空错题标记后，错题重练队列应同步变空（不留已订正的旧队列）。"""
        from paperdrill.practice import PracticeMode, Scope

        self.goto_scope(Scope.SINGLE)
        item = self.app.session.current_item()
        wrong_index = next(i for i, lab in enumerate(item.labels) if lab not in item.shown_answer)
        self.answer_current(wrong_index)
        self.app._set_mode(PracticeMode.WRONG)
        self.app.update()
        self.assertEqual(self.app.session.total, 1)

        cleared = self.app._do_clear_wrong()
        self.app.update()
        self.assertEqual(cleared, 1)
        self.assertTrue(self.app.session.empty, "清空错题后错题重练队列仍非空")
        self.assertEqual(self.app.session.stats()["wrong_book"], 0)
        self.assertEqual(self.app.session.stats()["wrong"], 1, "历史统计应保留")

    def test_exam_view_locked_after_submit(self):
        """交卷后考试页选项应转为只读，避免显示状态与记录不一致。"""
        import paperdrill.gui as gui_mod

        self.app.paper_single_var.set("3")
        self.app.paper_multiple_var.set("2")
        self.app.paper_judge_var.set("1")
        self.app._generate_round()
        self.app._start_exam(self.app.round.papers[0])
        self.app.notebook.select(1)
        self.app.update()
        self.app._exam_pick(self.app.exam.item(0).labels[0])
        self.app.update()

        original = gui_mod.messagebox.askyesno
        gui_mod.messagebox.askyesno = lambda *a, **k: True
        try:
            self.app._exam_submit()
        finally:
            gui_mod.messagebox.askyesno = original
        self.app.update()
        self.assertTrue(self.app.exam.submitted)
        widgets = [w for w in self.app._exam_widgets if w.winfo_exists()]
        self.assertTrue(widgets)
        self.assertTrue(all("disabled" in w.state() for w in widgets),
                        "交卷后考试页选项仍可点击")

    def test_exam_submit_keeps_practice_position(self):
        """交卷后重建练习队列不应把练习位置重置到第 1 题。"""
        import paperdrill.gui as gui_mod
        from paperdrill.practice import Scope

        self.goto_scope(Scope.ALL)
        self.app._navigate(1)
        self.app._navigate(1)
        self.app._navigate(1)
        pos_before = self.app.session.position

        self.app.paper_single_var.set("5")
        self.app.paper_multiple_var.set("3")
        self.app.paper_judge_var.set("2")
        self.app._generate_round()
        self.app._start_exam(self.app.round.papers[0])
        self.app.notebook.select(1)
        self.app.update()

        original = gui_mod.messagebox.askyesno
        gui_mod.messagebox.askyesno = lambda *a, **k: True
        try:
            self.app._exam_submit()
        finally:
            gui_mod.messagebox.askyesno = original
        self.app.update()
        self.assertEqual(self.app.session.position, pos_before,
                         "交卷后练习位置被重置")


if __name__ == "__main__":
    unittest.main(verbosity=2)
