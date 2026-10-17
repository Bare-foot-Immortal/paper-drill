# -*- coding: utf-8 -*-
"""测试健康检查：防止"大量用例被静默跳过但 CI 仍然绿灯发版"。

用法： pytest -q --junitxml=pytest.xml && python tools/check_test_health.py pytest.xml

判定（任一不满足即失败）：
* 收集到的用例数 >= --min-tests（默认 300；v1.3.0 起含约 120 项 Qt 界面测试，
  领域层基线约 190 项，合计 300+）
* 跳过数 <= --max-skips（默认 60；CI 的 Windows runner 可能没有可用 Tcl，
  按设计会跳过约 30 个 tkinter 界面/键盘用例，属于预期；
  夹具缺失或 PySide6 未装上导致的"整片静默跳过"会明显超过该值）

v1.3.0 说明：Qt 测试自身也会在 PySide6 缺失时整片跳过，
因此 CI 另有一条"确认 PySide6 可用"的前置步骤（见 .github/workflows/build.yml），
避免"没装 Qt 依旧绿灯"。
"""
from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("report", help="pytest --junitxml 产出的 XML 文件")
    ap.add_argument("--min-tests", type=int, default=300)
    ap.add_argument("--max-skips", type=int, default=60)
    args = ap.parse_args()

    path = Path(args.report)
    if not path.exists():
        print(f"[失败] 未找到测试报告：{path}")
        return 1
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    total = sum(int(s.get("tests", 0)) for s in suites)
    skipped = sum(int(s.get("skipped", 0)) for s in suites)
    failures = sum(int(s.get("failures", 0)) + int(s.get("errors", 0)) for s in suites)
    print(f"[测试健康] 用例 {total} 个，失败 {failures} 个，跳过 {skipped} 个")

    problems = []
    if failures:
        problems.append(f"存在 {failures} 个失败")
    if total < args.min_tests:
        problems.append(f"收集到的用例过少（{total} < {args.min_tests}），可能夹具缺失导致整片跳过")
    if skipped > args.max_skips:
        problems.append(f"跳过过多（{skipped} > {args.max_skips}），请检查测试是否被静默跳过")
    if problems:
        for msg in problems:
            print(f"[失败] {msg}")
        return 1
    print("[通过] 测试健康检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
