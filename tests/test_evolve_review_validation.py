# -*- coding: utf-8 -*-
"""R1.7 假说登记列名校验质量门：脆弱/虚构列引用 → pending-revise。

覆盖：
- validate_column_refs 三类判定（通过 / 第 N 列脆弱 / 虚构列名）
- 存量 H-042~H-044 已修订为真实列名（不再含「第 N 列」/threshold）
- register_hypotheses 对脆弱引用登记为 pending-revise 而非 open
"""
import re

from scripts.evolve_review import validate_column_refs


def test_valid_refs_pass():
    txts = ("fg_index 进入 68 以上区间时，circuit_breaker/extreme 触发率"
            "不高于 fg_index<60 区间",
            "取 features.csv 的 zone 与 core_position 做分组统计",
            "若 core_position 在 zone=2.0 与 zone=3.0 间存在不同取值")
    assert validate_column_refs(*txts) is None


def test_fragile_column_rejected():
    txt = "features.csv 第5、6列布尔位触发率不高于同期低位区间"
    r = validate_column_refs(txt)
    assert r is not None and "第" in r and "真实列名" in r


def test_fictional_column_rejected():
    txt = "features.csv 的 threshold 由 zone 单一决定，同 zone 对应同 threshold"
    r = validate_column_refs(txt)
    assert r is not None and "虚构列名" in r and "threshold" in r


def test_fictional_column_not_flagged_outside_features_context():
    # 未提到 features.csv 时，普通词不触发虚构列检查
    assert validate_column_refs("threshold 概念仅作背景说明") is None


def test_h042_044_revised_no_fragile_refs():
    txt = open("evolution/hypotheses.md", encoding="utf-8").read()
    for hid in ("H-042", "H-043", "H-044"):
        line = next(l for l in txt.split("\n") if l.startswith("| %s |" % hid))
        assert re.search(r"第\s*\d+\s*列", line) is None, hid
        assert "threshold" not in line, hid
        assert "R1.7 修订" in line, hid
        # H-043 / H-044 已由 MT-35 实跑判定 falsified（hypotheses.md 已回写）；
        # 本断言只约束「仍待验证」的条目保持 open。
        if hid == "H-042":
            assert "| open |" in line, hid  # 修订后保持 open（待验证）


def test_register_marks_pending_revise(monkeypatch, tmp_path):
    """脆弱引用候选 → 登记为 pending-revise（状态列非 open）。"""
    import scripts.evolve_review as ev
    hyp = tmp_path / "hypotheses.md"
    hyp.write_text("", encoding="utf-8")
    monkeypatch.setattr(ev, "HYP", str(hyp))
    monkeypatch.setattr(ev, "next_hyp_id", lambda: "H-999")
    cand = {
        "assumption": "features.csv 第3列由第2列单一决定",
        "test_method": "按第2列分组，检查第3列唯一取值数",
        "falsify_criteria": "同一第2列值下出现 ≥2 个第3列取值则证伪",
        "evidence_source": "features.csv 2026-10-06 实测",
    }
    added = ev.register_hypotheses([cand], "test")
    assert added == ["H-999"]
    row = hyp.read_text(encoding="utf-8")
    assert "pending-revise" in row
    assert "R1.7 列名校验" in row
