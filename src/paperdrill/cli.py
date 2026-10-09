# -*- coding: utf-8 -*-
"""命令行辅助入口（本软件为练习工具，主界面是图形界面）。

用途：题库体检、查看进度、发布自检。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __app_name__, __version__
from .bank_io import bank_stats, load_bank, write_template_xlsx
from .store import ProgressStore, progress_dir


def attach_parent_console() -> None:
    """打包为 GUI 程序后，从 cmd/PowerShell 调用时附着父控制台以显示输出。"""
    if sys.stdout is not None and sys.stderr is not None:
        return
    if sys.platform != "win32":
        return
    try:
        import ctypes

        if ctypes.windll.kernel32.AttachConsole(-1):
            sys.stdout = open("CONOUT$", "w", encoding="utf-8", buffering=1, errors="replace")
            sys.stderr = open("CONOUT$", "w", encoding="utf-8", buffering=1, errors="replace")
    except Exception:
        pass


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="PaperDrill",
                                description=f"{__app_name__} v{__version__} 刷题练习工具")
    p.add_argument("bank", nargs="?", help="题库文件（不给则启动图形界面）")
    p.add_argument("--bank", dest="bank_opt", help="题库文件（等价于位置参数）")
    p.add_argument("--stats-only", action="store_true", help="只统计题库，不启动界面")
    p.add_argument("--list-progress", action="store_true", help="列出各题库的练习进度摘要")
    p.add_argument("--show-progress-dir", action="store_true", help="打印进度文件目录")
    p.add_argument("--progress-dir", default="", help="覆盖进度目录（自动化验证用）")
    p.add_argument("--practice", type=int, default=0,
                   help="无界面连续作答 N 题（自动化验证进度保留用）")
    p.add_argument("--mode", default="order", help="无界面练习的模式：order/random/wrong/fresh")
    p.add_argument("--single", type=int, default=20, help="试卷蓝图：每卷单选题数")
    p.add_argument("--multiple", type=int, default=10, help="试卷蓝图：每卷多选题数")
    p.add_argument("--judge", type=int, default=10, help="试卷蓝图：每卷判断题数")
    p.add_argument("--round-length", type=int, default=0, help="一轮张数（0=自动按覆盖计算）")
    p.add_argument("--plan", action="store_true", help="只打印组卷计划（轮长与覆盖），不生成")
    p.add_argument("--exam", default="", help="无界面模拟考试：指定卷号（如 A），交卷后打印成绩")
    p.add_argument("--exam-ratio", type=float, default=0.8, help="模拟考试中答对的比例（0~1）")
    p.add_argument("--make-template", metavar="PATH", help="生成题库模板文件后退出")
    p.add_argument("--gui-selftest", action="store_true", help="界面无头自检（发布验收用）")
    p.add_argument("--out", default="", help="自检时的进度目录")
    p.add_argument("--result", default="", help="自检结果 JSON 路径")
    p.add_argument("--exercises", type=int, default=30, help="自检时作答的题目数")
    p.add_argument("--seed", type=int, default=12345, help="随机种子")
    p.add_argument("--log", default="", help="把命令行输出同时写入指定文本文件（UTF-8）")
    p.add_argument("--version", action="version", version=f"{__app_name__} {__version__}")
    return p


class _Tee:
    """把输出同时写到多个流（控制台 + 日志文件），任一失败不影响另一个。"""

    def __init__(self, *streams) -> None:
        self.streams = [s for s in streams if s is not None]

    def write(self, text: str) -> int:
        for stream in self.streams:
            try:
                stream.write(text)
                stream.flush()
            except Exception:
                pass
        return len(text or "")

    def flush(self) -> None:
        for stream in self.streams:
            try:
                stream.flush()
            except Exception:
                pass


def _headless_practice(bank_path: str, count: int, mode: str) -> int:
    """无界面连续作答若干题（用于自动化验证练习进度是否跨进程保留）。"""
    from pathlib import Path

    from .practice import PracticeMode, PracticeSession

    result = load_bank(bank_path)
    if not result.questions:
        print("[错误] 题库为空。")
        return 3
    store = ProgressStore.load_for(Path(bank_path).stem, result.questions)
    session = PracticeSession(result.questions, store,
                              mode=PracticeMode.from_label(mode), shuffle_options=True)
    restored = session.restore_position(adopt_mode=False)   # 只恢复位置，尊重 --mode
    before = session.stats()
    tag = "继续上次练习" if before["done"] else "新题库，从零开始"
    print(f"[进度] {tag}：已练 {before['done']}/{before['total']}，错题 {before['wrong_book']}，"
          f"正确率 {before['accuracy'] * 100:.1f}%")
    print(f"[队列] {session.mode.label} 共 {session.total} 题，本次从第 {session.position} 题开始"
          + ("（已定位到上次位置）" if restored else ""))

    answered = 0
    while answered < count and not session.empty:
        item = session.current_item()
        if item is None:
            break
        if answered % 2 == 0:
            selected = set(item.shown_answer)
        else:
            others = [lab for lab in item.labels if lab not in item.shown_answer]
            selected = {others[0]} if others else set()
        session.submit(selected)          # 内部即时落盘
        answered += 1
        if not session.advance():
            break
    session.save_position()

    stats = session.stats()
    print(f"[练习] 本次作答 {answered} 题；累计已练 {stats['done']}/{stats['total']}，"
          f"正确率 {stats['accuracy'] * 100:.1f}%，错题 {stats['wrong_book']} 道")
    print(f"[进度] 文件：{session.store.path}")
    return 0


def _headless_paper(bank_path: str, args) -> int:
    """组卷计划 / 无界面模拟考试（自动化验证用）。"""
    from pathlib import Path

    from .models import QType
    from .paper import PaperBlueprint, generate_round, min_round_length
    from .practice import ExamSession

    result = load_bank(bank_path)
    if not result.questions:
        print("[错误] 题库为空。")
        return 3
    bp = PaperBlueprint(args.single, args.multiple, args.judge)
    if bp.total <= 0:
        print("[错误] 每卷题目数量为 0。")
        return 2
    stats = bank_stats(result.questions)
    auto_n = min_round_length(result.questions, bp)
    print(f"[蓝图] 每卷 {bp.total} 题（{bp.describe()}）")
    print(f"[轮长] 覆盖题库全部题目需 {auto_n} 张/轮"
          f"（题库：单选 {stats['single']}、多选 {stats['multiple']}、判断 {stats['judge']}）")

    n = args.round_length if args.round_length > 0 else auto_n
    rnd = generate_round(result.questions, bp, round_length=n, seed=args.seed)
    print(f"[生成] {rnd.summary()}　随机种子 {rnd.seed}")
    for key, (seen, total) in rnd.coverage.items():
        name = {"single": "单选", "multiple": "多选", "judge": "判断"}.get(key, key)
        print(f"       - {name}：{seen}/{total}")
    for warn in rnd.warnings:
        print(f"[警告] {warn}")
    for paper in rnd.papers[:12]:
        print(f"       {paper.label}卷：{paper.total} 题"
              f"（单选 {paper.count_of(QType.SINGLE)}、多选 {paper.count_of(QType.MULTIPLE)}、"
              f"判断 {paper.count_of(QType.JUDGE)}；其中补题 {paper.reused_count} 题）")

    if args.plan or not args.exam:
        return 0

    label = args.exam.strip().upper().rstrip("卷")
    paper = next((p for p in rnd.papers if p.label == label), None)
    if paper is None:
        print(f"[错误] 本轮没有 {label} 卷。")
        return 4

    store = ProgressStore.load_for(Path(bank_path).stem, result.questions)
    exam = ExamSession(paper, store, shuffle_single=True, shuffle_multiple=True,
                       scores={"single": 1.0, "multiple": 2.0, "judge": 1.0})
    total = exam.total
    n_ok = max(0, min(total, int(total * max(0.0, min(1.0, args.exam_ratio)))))
    n_unanswered = min(2, max(0, total - n_ok))
    for i in range(total):
        item = exam.item(i)
        if i < n_ok:
            exam.set_answer(i, set(item.shown_answer))
        elif i < total - n_unanswered:
            others = [lab for lab in item.labels if lab not in item.shown_answer]
            exam.set_answer(i, {others[0]} if others else {sorted(item.shown_answer)[0]})
        else:
            exam.clear_answer(i)
    res = exam.submit()
    print(f"[考试] {res.summary()}")
    for key, data in res.per_type.items():
        print(f"       - {data['name']}：{data['correct']}/{data['total']}，"
              f"得分 {data['score']:g}/{data['full']:g}")
    print(f"[成绩] 已保存，当前历史成绩 {len(store.exam_history())} 条；"
          f"练习进度 已练 {store.stats(result.questions)['done']}/{stats['total']}")
    return 0


def main(argv: "list[str] | None" = None) -> int:
    args = build_parser().parse_args(argv)
    bank = args.bank_opt or args.bank

    if args.log:
        try:
            log_path = Path(args.log)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            handle = log_path.open("w", encoding="utf-8")
            sys.stdout = _Tee(sys.stdout, handle)
            sys.stderr = _Tee(sys.stderr, handle)
        except Exception as exc:
            print(f"[警告] 无法写入日志文件：{exc}")

    import paperdrill.store as store_mod

    if args.progress_dir:
        from pathlib import Path as _Path

        target = _Path(args.progress_dir)
        store_mod.progress_dir = lambda: target      # type: ignore[assignment]

    if args.make_template:
        path = write_template_xlsx(args.make_template)
        print(f"[OK] 题库模板已生成：{path}")
        return 0

    if args.show_progress_dir:
        print(store_mod.progress_dir())
        return 0

    if args.list_progress:
        rows = ProgressStore.list_all()
        if not rows:
            print(f"[空] 尚无练习进度。目录：{store_mod.progress_dir()}")
            return 0
        print(f"进度目录：{store_mod.progress_dir()}")
        print(f"{'题库':<28}{'已练/总题':<14}{'正确率':<10}{'错题':<8}最后更新")
        for r in rows:
            flag = "（文件损坏）" if r.get("broken") else ""
            print(f"{r['name'][:26]:<28}{str(r['done']) + '/' + str(r['total'] or '?'):<14}"
                  f"{r['accuracy'] * 100:>6.1f}%   {r.get('wrong_book', 0):<8}{r['updated']}{flag}")
        return 0

    if args.gui_selftest:
        if not bank:
            print("[错误] 自检需要 --bank 指定题库。")
            return 2
        from .gui import selftest

        return selftest(bank, args.result, args.out, args.exercises, args.seed)

    if args.practice and bank:
        return _headless_practice(bank, args.practice, args.mode)

    if bank and (args.plan or args.exam):
        return _headless_paper(bank, args)

    if bank:
        result = load_bank(bank)
        stats = bank_stats(result.questions)
        print(f"[题库] {bank}")
        print(f"       共 {stats['total']} 题：单选 {stats['single']}、多选 {stats['multiple']}、"
              f"判断 {stats['judge']}；含固定顺序题 {stats['fixed']} 道")
        if result.issues:
            print(f"[警告] 有 {len(result.issues)} 行未能导入：")
            for issue in result.issues[:10]:
                print(f"       - {issue}")
            if len(result.issues) > 10:
                print(f"       - ...（其余 {len(result.issues) - 10} 条省略）")
        return 0

    print("请给出题库文件，或直接运行程序启动图形界面。使用 --help 查看参数。")
    return 0
