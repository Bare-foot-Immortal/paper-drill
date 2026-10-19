# -*- coding: utf-8 -*-
"""练习位置记忆（需求 1）回归测试。

用户需求：在「顺序 / 随机 / 错题重练 / 只练未做」之间切换，或在
「整个题库 / 单选 / 多选 / 判断」之间切换时，切走再切回来应回到上次停下的题，
而不是回到第 1 题；已作答记录、统计、错题本不受影响。

实现要点（本文件锁定这些行为）：
* ``PracticeSession.position_key()`` 以 ``（模式, 范围）`` 组合键区分位置；
* ``ProgressStore.save_session(positions=...)`` 落盘位置表，旧格式顶层字段保持不变；
* 控制器 ``set_mode()`` / ``set_scope()`` 先存旧位置、重建队列、再恢复目标组合键位置。
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

try:                                            # 以包方式运行
    from tests.qt_support import HAVE_QT, SKIP_REASON, QtTestCase, make_questions
except ModuleNotFoundError:                     # 以发现方式运行
    from qt_support import (  # type: ignore[no-redef]
        HAVE_QT,
        SKIP_REASON,
        QtTestCase,
        make_questions,
    )

from paperdrill.models import QType  # noqa: E402
from paperdrill.practice import PracticeMode, PracticeSession, Scope  # noqa: E402
from paperdrill.store import ProgressStore  # noqa: E402


# ================================================================ 领域层
class TestPositionKey(unittest.TestCase):
    """组合键格式：``模式.value:题型key``（整个题库用 ``all``）。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pd_poskey_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.questions = make_questions(12)
        self.store = ProgressStore.load_for("键库", self.questions, self.tmp)

    def test_key_combines_mode_and_scope(self):
        s = PracticeSession(self.questions, self.store, mode=PracticeMode.ORDER)
        self.assertEqual(s.position_key(), "order:all")
        self.assertEqual(s.position_key(PracticeMode.RANDOM), "random:all")
        self.assertEqual(s.position_key(qtype_filter=QType.SINGLE), "order:single")
        self.assertEqual(s.position_key(PracticeMode.WRONG, QType.MULTIPLE), "wrong:multiple")
        # 不传参数时跟随会话当前状态
        s.rebuild(PracticeMode.FRESH, QType.JUDGE)
        self.assertEqual(s.position_key(), "fresh:judge")
        # 显式传 None 表示整个题库
        self.assertEqual(s.position_key(PracticeMode.ORDER, None), "order:all")


class TestSessionPositionMemory(unittest.TestCase):
    """PracticeSession 按组合键保存/恢复位置。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pd_posmem_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.questions = make_questions(12)
        self.store = ProgressStore.load_for("位置记忆库", self.questions, self.tmp)

    def _session(self, mode=PracticeMode.ORDER, qtype_filter=None, seed=3):
        return PracticeSession(self.questions, self.store, mode=mode,
                               qtype_filter=qtype_filter, seed=seed)

    def _reopen(self, mode=PracticeMode.ORDER, qtype_filter=None, seed=11):
        """模拟重启：同一进度目录重新加载 store 后再建会话。"""
        store = ProgressStore.load_for("位置记忆库", self.questions, self.tmp)
        return PracticeSession(self.questions, store, mode=mode,
                               qtype_filter=qtype_filter, seed=seed), store

    def test_two_modes_are_remembered_independently(self):
        s = self._session()
        s.goto(3)
        order_fp = s.current_question().fingerprint
        s.save_position()
        s.rebuild(PracticeMode.RANDOM)
        s.goto(5)
        random_fp = s.current_question().fingerprint
        s.save_position()

        saved = self.store.saved_session()
        positions = saved.get("positions")
        self.assertIsInstance(positions, dict)
        self.assertIn("order:all", positions)
        self.assertIn("random:all", positions)
        # 顶层旧格式字段仍然存在（旧版本/旧测试据此读取）
        self.assertIn("last_fp", saved)
        self.assertIn("pos", saved)

        order_again, _ = self._reopen(mode=PracticeMode.ORDER)
        self.assertTrue(order_again.restore_position(adopt_mode=False))
        self.assertEqual(order_again.current_question().fingerprint, order_fp)
        self.assertEqual(order_again.position, 4)

        random_again, _ = self._reopen(mode=PracticeMode.RANDOM)
        self.assertTrue(random_again.restore_position(adopt_mode=False))
        self.assertEqual(random_again.current_question().fingerprint, random_fp)

    def test_scope_and_mode_combined_key_is_isolated(self):
        s = self._session(qtype_filter=QType.SINGLE)
        s.goto(2)
        fp = s.current_question().fingerprint
        s.save_position()
        # 同一模式下换范围 → 不共享位置
        s.rebuild(qtype_filter=QType.MULTIPLE)
        s.goto(3)
        s.save_position()
        positions = self.store.saved_session()["positions"]
        self.assertIn("order:single", positions)
        self.assertIn("order:multiple", positions)

        back, _ = self._reopen(mode=PracticeMode.ORDER, qtype_filter=QType.SINGLE)
        self.assertTrue(back.restore_position(adopt_mode=False))
        self.assertEqual(back.current_question().fingerprint, fp)
        self.assertEqual(back.position, 3)

    def test_legacy_format_without_positions_still_restores(self):
        """旧进度文件（只有 last_fp/pos）行为不变：指纹优先。"""
        self.store.progress.session = {
            "mode": "order", "last_fp": self.questions[7].fingerprint,
            "pos": 3, "shuffle": True,
        }
        self.store.save()
        s, _ = self._reopen(seed=1)
        self.assertTrue(s.restore_position())
        self.assertEqual(s.current_question().fingerprint, self.questions[7].fingerprint)

    def test_new_format_missing_combo_key_starts_from_beginning(self):
        """新格式已有 positions 时，当前（模式, 范围）组合键缺失 → 从头开始。

        不能回退到顶层旧字段：那属于"上一个队列"，会造成首次切到
        「只练单选 / 只练未做」时停在前一个队列的随机位置（审计 B-F5）。
        """
        self.store.progress.session = {
            "mode": "order", "last_fp": self.questions[5].fingerprint,
            "pos_fps": [self.questions[5].fingerprint], "pos": 5, "shuffle": True,
            "positions": {"random:all": {"pos_fps": [], "last_fp": "", "pos": 0}},
        }
        self.store.save()
        s, _ = self._reopen(seed=1)
        self.assertFalse(s.restore_position(adopt_mode=False))
        self.assertEqual(s.position, 1)
        self.assertEqual(s.current_question().fingerprint, self.questions[0].fingerprint)

    def test_dirty_positions_never_raise(self):
        """positions 脏数据（非 dict / 条目非 dict / pos 非数字）不得抛异常。"""
        dirty_cases = [
            "not-a-dict",
            {"order:all": "not-a-dict"},
            {"order:all": {"pos": "abc", "pos_fps": 7, "last_fp": None}},
            {"order:all": {"pos": float("inf"), "pos_fps": ["deadbeef"]}},
        ]
        for i, positions in enumerate(dirty_cases):
            with self.subTest(case=i):
                self.store.progress.session = {
                    "mode": "order", "last_fp": "deadbeef", "pos": 0,
                    "positions": positions,
                }
                s = self._session(seed=i)
                self.assertFalse(s.restore_position())        # 序号兜底，不是精确恢复
                self.assertGreaterEqual(s.position, 1)
                s.save_position()                            # 也不能在保存时崩溃

    def test_empty_queue_save_position_is_safe(self):
        """空队列（如无错题）保存位置不得抛异常，也不覆盖其它组合键。"""
        s = self._session()
        s.goto(4)
        s.save_position()
        s.rebuild(PracticeMode.WRONG)                        # 没有错题 → 空队列
        self.assertTrue(s.empty)
        s.save_position()
        positions = self.store.saved_session()["positions"]
        self.assertIn("order:all", positions)
        self.assertEqual(positions["order:all"]["pos"], 4)


class TestStoreSessionPositions(unittest.TestCase):
    """ProgressStore.save_session 的 positions 关键字参数。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pd_posstore_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.questions = make_questions(9)
        self.store = ProgressStore.load_for("存储位置库", self.questions, self.tmp)

    def test_positions_roundtrip(self):
        entry = {"last_fp": self.questions[2].fingerprint,
                 "pos_fps": [self.questions[2].fingerprint, self.questions[3].fingerprint],
                 "pos": 2, "ts": ""}
        self.store.save_session("order", self.questions[2], 2, False,
                                window=[self.questions[2], self.questions[3]],
                                positions={"order:all": entry})
        again = ProgressStore.load_for("存储位置库", self.questions, self.tmp)
        saved = again.saved_session()
        self.assertEqual(saved["positions"]["order:all"], entry)
        self.assertEqual(saved["pos"], 2)
        self.assertEqual(saved["last_fp"], self.questions[2].fingerprint)

    def test_none_preserves_existing_positions(self):
        entry = {"last_fp": self.questions[4].fingerprint, "pos_fps": [], "pos": 4, "ts": ""}
        self.store.save_session("order", self.questions[4], 4, False,
                                positions={"order:all": entry})
        # 其它代码直接调用 save_session（不传 positions）→ 位置表必须保留
        self.store.save_session("random", self.questions[1], 1, False, {"n": 2})
        saved = self.store.saved_session()
        self.assertEqual(saved["positions"]["order:all"], entry)
        self.assertEqual(saved["mode"], "random")
        self.assertEqual(saved["n"], 2)

    def test_new_file_without_positions_keeps_old_shape(self):
        """不传 positions 且旧 session 无位置表 → 不凭空写入 positions 字段。"""
        self.store.save_session("order", self.questions[0], 0, True)
        saved = self.store.saved_session()
        self.assertNotIn("positions", saved)
        self.assertIn("last_fp", saved)


# ================================================================ 控制器
@unittest.skipUnless(HAVE_QT, SKIP_REASON)
class TestControllerPositionMemory(QtTestCase):
    """切换模式 / 范围后，切回来必须回到上次停下的那道题。"""

    def test_mode_switch_roundtrip_restores_question(self):
        ctrl = self.controller(questions=make_questions(12))
        self.assertTrue(ctrl.goto(3))
        fingerprint = ctrl.current_question().fingerprint
        self.assertEqual(ctrl.state.position, 4)

        ctrl.set_mode(PracticeMode.RANDOM)
        self.assertIs(ctrl.state.mode, PracticeMode.RANDOM)
        ctrl.set_mode(PracticeMode.ORDER)

        self.assertIs(ctrl.state.mode, PracticeMode.ORDER)
        self.assertEqual(ctrl.current_question().fingerprint, fingerprint,
                         "切到随机再切回顺序后应回到原题，而不是第 1 题")
        self.assertEqual(ctrl.state.position, 4)

    def test_scope_switch_roundtrip_restores_question(self):
        ctrl = self.controller(questions=make_questions(12))
        ctrl.set_scope(Scope.SINGLE)
        self.assertEqual(ctrl.state.total, 4)
        self.assertTrue(ctrl.goto(2))                       # 单选范围内第 3 题
        fingerprint = ctrl.current_question().fingerprint
        self.assertIs(ctrl.current_question().qtype, QType.SINGLE)

        ctrl.set_scope(Scope.MULTIPLE)
        ctrl.set_scope(Scope.SINGLE)

        self.assertIs(ctrl.state.scope, Scope.SINGLE)
        self.assertIs(ctrl.state.session.qtype_filter, QType.SINGLE)
        self.assertEqual(ctrl.state.total, 4)
        self.assertEqual(ctrl.current_question().fingerprint, fingerprint,
                         "切到多选再切回单选后应回到原题，而不是第 1 题")
        self.assertEqual(ctrl.state.position, 3)

    def test_positions_persist_both_keys_and_survive_restart(self):
        ctrl = self.controller(questions=make_questions(12))
        self.assertTrue(ctrl.goto(3))
        order_fp = ctrl.current_question().fingerprint
        ctrl.set_mode(PracticeMode.RANDOM)
        random_fp = ctrl.current_question().fingerprint

        store = ctrl.state.store
        positions = store.saved_session().get("positions")
        self.assertIsInstance(positions, dict)
        self.assertIn("order:all", positions, "切换前的位置应记忆在旧组合键下")
        self.assertIn("random:all", positions, "新组合键也应写入位置表")

        # 模拟重启：同一进度文件重新加载，按目标组合键恢复
        reopened = ProgressStore.load_for("题集", ctrl.active_questions(),
                                          self.progress_root)
        order_again = PracticeSession(ctrl.active_questions(), reopened,
                                      mode=PracticeMode.ORDER, seed=21)
        self.assertTrue(order_again.restore_position(adopt_mode=False))
        self.assertEqual(order_again.current_question().fingerprint, order_fp)
        self.assertEqual(order_again.position, 4)

        # 默认 restore_position() 沿用最后保存的模式（随机）并回到随机位置
        any_again = PracticeSession(ctrl.active_questions(), reopened,
                                    mode=PracticeMode.ORDER, seed=22)
        self.assertTrue(any_again.restore_position())
        self.assertIs(any_again.mode, PracticeMode.RANDOM)
        self.assertEqual(any_again.current_question().fingerprint, random_fp)

    def test_empty_wrong_mode_keeps_order_position(self):
        """切到空的「错题重练」再切回来：不崩溃、位置仍恢复。"""
        ctrl = self.controller(questions=make_questions(12))
        self.assertTrue(ctrl.goto(3))
        fingerprint = ctrl.current_question().fingerprint

        ctrl.set_mode(PracticeMode.WRONG)
        self.assertTrue(ctrl.state.practice_empty)
        self.assertEqual(ctrl.state.feedback_kind, "empty")

        ctrl.set_mode(PracticeMode.ORDER)                   # 空队列不得抛异常
        self.assertFalse(ctrl.state.practice_empty)
        self.assertEqual(ctrl.current_question().fingerprint, fingerprint)
        self.assertEqual(ctrl.state.position, 4)
        self.assertIn("wrong:all", ctrl.state.store.saved_session()["positions"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
