# -*- coding: utf-8 -*-
"""MT-68：evolve_review 每日登记上限（≤3 条，防积压；只限流不改判据 ✓）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import evolve_review as er


def _cand(i):
    return {
        "assumption": f"候选假设编号{i}：市场温度与持仓风险存在可观测的对应关系",
        "test_method": f"对比候选{i}在 features.csv 尾段的分组均值并做显著性比较",
        "falsify_criteria": f"若候选{i}分组均值无差异则假设不成立",
        "evidence_source": f"2026-10-26 features.csv 尾十行实盘快照",
    }


def test_daily_register_cap_three(tmp_path, monkeypatch):
    hyp = tmp_path / "hypotheses.md"
    hyp.write_text("# hypotheses\n\n", encoding="utf-8")
    monkeypatch.setattr(er, "HYP", str(hyp))

    cands = [_cand(i) for i in range(1, 5)]      # 4 个全新、非重复、过列名校验
    added = er.register_hypotheses(cands, via="test")
    assert len(added) == 3, "每日上限 3 条 ✓，第 4 条必须被跳过"
    body = hyp.read_text(encoding="utf-8")
    assert body.count("候选假设编号4") == 0      # 第 4 条未落盘 ✓


def test_cap_counts_already_registered_today(tmp_path, monkeypatch):
    """今日已登记 2 条 ⇒ 本轮最多再补 1 条 ✓。"""
    hyp = tmp_path / "hypotheses.md"
    today = er.date.today().isoformat()
    hyp.write_text(
        "# hypotheses\n\n"
        f"| H-001 | {today} | 旧假设一 | 方法一 | 判据一 | open | n |\n"
        f"| H-002 | {today} | 旧假设二 | 方法二 | 判据二 | open | n |\n",
        encoding="utf-8")
    monkeypatch.setattr(er, "HYP", str(hyp))
    monkeypatch.setattr(er, "_is_duplicate", lambda *a, **k: None)  # 专注测 cap 计数 ✓

    fresh = [
        {
            "assumption": "美债十年期收益率上行阶段，黄金 ETF 的日内波动显著放大",
            "test_method": "按收益率上行日分组统计黄金 ETF 日收益标准差并对比",
            "falsify_criteria": "若两组标准差无显著差异则假设不成立",
            "evidence_source": "2026-10-26 features.csv 尾段宏观快照",
        },
        {
            "assumption": "美元指数走弱时，离岸人民币结算的中概杠杆相对抗跌",
            "test_method": "按美元指数方向分组比较中概杠杆累计收益",
            "falsify_criteria": "若两组收益无方向差异则假设不成立",
            "evidence_source": "2026-10-26 实盘持仓与汇率快照",
        },
    ]
    added = er.register_hypotheses(fresh, via="test")
    assert len(added) == 1
