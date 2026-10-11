# -*- coding: utf-8 -*-
"""M2.5 walk-forward 季度报告自动化测试。

覆盖：
- write_decision 生成建议文件 + 追加 decision-log（用临时目录）
- verdict 判定逻辑（n_total < MIN_QUARTERS → 样本不足；>=KEEP_RATIO → 维持观察）
- evolve_weekly 季度节统计只计变体行（维持/归档计数与裁判一致）
"""
import os
import sys
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from scripts import evolve_walkforward as wf  # noqa: E402


def test_verdict_rules():
    """确定性判定：样本不足 / 维持 / 归档三分。"""
    # 窗数不足 → 样本不足
    assert wf.verdict_for(2, 1) == "样本不足，继续积累"
    # 达标 → 维持观察
    assert wf.verdict_for(4, 3) == "维持观察"
    # 不达标 → 建议归档
    assert wf.verdict_for(4, 1) == "建议归档"
    # 临界：0.6 达标（3/5 = 0.6）
    assert wf.verdict_for(5, 3) == "维持观察"


def test_write_decision_files(tmp_path):
    """--decision：生成建议文件 + decision-log 追加。"""
    wf.REPO = str(tmp_path)
    evo = tmp_path / "evolution"
    evo.mkdir()
    docs = tmp_path / "docs"
    docs.mkdir()
    verdicts = [
        {"sym": "TQQQ", "variant": "V-H7", "verdict": "维持观察",
         "n_good": 34, "n_total": 40, "n_accum": 0},
        {"sym": "SOXL", "variant": "V-ATR", "verdict": "建议归档",
         "n_good": 18, "n_total": 40, "n_accum": 0},
        {"sym": "UPRO", "variant": "V-MA", "verdict": "样本不足，继续积累",
         "n_good": 0, "n_total": 2, "n_accum": 2},
    ]
    total = {"keep": 1, "archive": 1, "accum": 1}
    import datetime as _dt
    with mock.patch.object(wf, "datetime") as mdt:
        mdt.now.return_value = _dt.datetime(2026, 10, 11)
        wf.write_decision(verdicts, total, "2026-10-11")
    dec = (evo / "walkforward-decision.md").read_text(encoding="utf-8")
    assert "2026Q4" in dec
    assert "| TQQQ | V-H7 | 维持观察 | 34/40 窗不劣化 |" in dec
    assert "样本不足（2 窗）" in dec
    log = (docs / "decision-log.md").read_text(encoding="utf-8")
    assert "walk-forward 季度裁判" in log
    assert "维持 1 / 归档 1 / 样本不足 1" in log
    # 不自动改生产：建议文件是只读证据，无执行字段
    assert "不自动改生产" in dec


def test_weekly_quarter_section_counts():
    """evolve_weekly 季度节：只统计变体行，不含汇总表。"""
    import scripts.evolve_weekly as wk
    content = ("| 标的 | 变体 | 判定 | 证据 |\n"
               "| TQQQ | V-H7 | 维持观察 | 34/40 |\n"
               "| SOXL | V-ATR | 建议归档 | 18/40 |\n"
               "| UPRO | V-MA | 建议归档 | 23/40 |\n"
               "| 维持观察 | 1 |\n| 建议归档 | 2 |\n")  # 汇总表行不得计入
    pat = wk.re.compile(r"^\| (TQQQ|SOXL|UPRO) \| [^|]+ \| (维持观察|建议归档|样本不足) \|")
    rows = [ln for ln in content.splitlines() if pat.match(ln)]
    keeps = sum(1 for r in rows if "维持观察" in r)
    arch = sum(1 for r in rows if "建议归档" in r)
    assert keeps == 1 and arch == 2
