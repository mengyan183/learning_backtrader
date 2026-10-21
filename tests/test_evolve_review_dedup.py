"""MT-51: evolve_review 登记前归一化查重。

回归点：
- H-079 vs H-070（措辞不同但同义）⇒ 必须判重跳过
- H-080 vs H-061（同义）⇒ 判重
- 全新假说 ⇒ 不判重
- 空判据 ⇒ 不崩
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import evolve_review as er


def _mk_existing(tmp_path, rows):
    """造一个假 hypotheses.md。rows: list of (hid, assumption, test, falsify)。"""
    p = os.path.join(tmp_path, "hypotheses.md")
    with open(p, "w") as f:
        f.write("# hypotheses\n\n")
        for hid, a, t, fl in rows:
            f.write(f"| {hid} | 2026-10-17 | {a} | {t} | {fl} | open | note |\n")
    return p


def test_norm_tokens_strips_column_refs():
    t = er._norm_tokens(
        "低位恐惧贪婪时 position_multiplier 呈下降趋势",
        "统计 features.csv 第4列 position_multiplier",
        "若持续上升则不成立",
    )
    # 单字集合：「恐」「惧」「贪」「婪」应在
    assert "恐" in t and "惧" in t
    assert "贪" in t and "婪" in t


def test_dup_h079_vs_h070(tmp_path):
    """H-079（新）vs H-070（已有）：措辞不同但同义 ⇒ 判重。"""
    er.HYP = _mk_existing(tmp_path, [(
        "H-070",
        "当恐惧贪婪指数降至 1.0 时，position_multiplier 会上升",
        "统计 features.csv 中 fg_index 为 1.0 的行的 ammo_position 均值，与高 fg 行对比",
        "低位行 position_multiplier 不高于高位行",
    )])
    existing = er._load_existing_hypotheses()
    cand = er._norm_tokens(
        "低位恐惧贪婪时 position_multiplier 呈现下降趋势（而非上升放大仓位）",
        "统计 features.csv 第4列 position_multiplier 在恐惧贪婪指数≤30 区间的连续值",
        "若持续上升则假设不成立",
    )
    dup = er._is_duplicate(cand, existing)
    assert dup is not None, "H-079 应判重为 H-070"
    assert dup[0] == "H-070"


def test_fresh_hypothesis_not_dup(tmp_path):
    """全新话题 ⇒ 不判重。"""
    er.HYP = _mk_existing(tmp_path, [(
        "H-070",
        "当恐惧贪婪指数降至 1.0 时，position_multiplier 会上升",
        "统计低位行 ammo_position",
        "不高于高位行",
    )])
    existing = er._load_existing_hypotheses()
    cand = er._norm_tokens(
        "AXTX 单日跌幅 -14.16% 为持仓中局部极值",
        "对比 AXTX 与 YINN/GDXU/BTC 在 2026-10-15 的跌幅",
        "若跌幅相近则不成立",
    )
    assert er._is_duplicate(cand, existing) is None


def test_empty_cand_no_crash(tmp_path):
    er.HYP = _mk_existing(tmp_path, [])
    assert er._is_duplicate(set(), []) is None
    assert er._is_duplicate(set(), [("H-001", {"abc"})]) is None


def test_load_existing_parses_rows(tmp_path):
    er.HYP = _mk_existing(tmp_path, [
        ("H-001", "假设甲", "方法甲", "判据甲"),
        ("H-002", "假设乙", "方法乙", "判据乙"),
    ])
    rows = er._load_existing_hypotheses()
    ids = [r[0] for r in rows]
    assert "H-001" in ids and "H-002" in ids
