# -*- coding: utf-8 -*-
"""R1.2 未来函数审计 pytest：把「无未来函数」纪律变成可执行测试。

验收（docs/2026-10-11-贪恐系统发展迭代规划.md R1.2）：
  1. 扫描通过并留档；违规 0；pytest 全绿。
  2. 复用 backtrader Cheat-on-X 模式做对照开关（--cheat-on）。
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts import lookahead_audit as la  # noqa: E402


def _run(argv=None):
    """子进程方式跑审计器（验证 CLI 端到端 + 退出码）。"""
    cmd = [sys.executable, str(REPO / "scripts" / "lookahead_audit.py")] + (argv or [])
    r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout


def test_code_scan_no_violations():
    """生产文件不得出现 shift(-n)/shift(0)；违规 0。"""
    code = la.scan_code()
    assert code["violations"] == [], \
        "生产/未登记文件出现前视 shift：%r" % code["violations"]


def test_research_whitelist_registered():
    """评测/归因文件的 shift(-n) 必须显式登记在白名单（否则审计失败）。"""
    code = la.scan_code()
    assert len(code["whitelisted"]) > 0
    files = {r["file"] for r in code["whitelisted"]}
    # 已知评测/归因文件（R1.2 探查事实）必须全部登记
    assert {"fg_system/factors/screening.py",
            "fg_system/factors/eval.py"} <= files
    # 未归类为 0：任何出现在扫描范围内但不在白名单的 shift(- 都会进 violations（已断言）
    assert code["unclassified"] == []


def test_data_not_ahead_of_raw():
    """features 尾行不得超前原料 raw（vix/sentiment/prices）。"""
    data = la.check_data()
    assert data.get("ahead_of_raw") is False, data.get("violations")
    assert data["features_tail"] is not None


def test_cli_pass_exit_zero_and_artifacts():
    """CLI 端到端：违规 0 → 退出 0；md/json 留档可读。"""
    rc, out = _run(["--json"])
    assert rc == 0, out
    assert "PASS" in out
    md = (REPO / "evolution" / "lookahead-audit.md").read_text(encoding="utf-8")
    assert "# 未来函数审计报告（R1.2" in md
    js = json.loads((REPO / "evolution" / "lookahead-audit.json").read_text(encoding="utf-8"))
    assert js["verdict"] == "PASS"
    assert js["code"]["violations"] == []


def test_cheat_on_switch_keeps_pass():
    """对照开关 --cheat-on：白名单计入已知例外展示，不改变违规结论。"""
    rc, out = _run(["--cheat-on"])
    assert rc == 0, out
    assert "PASS" in out


def test_list_whitelist():
    """--list-whitelist 列出白名单文件。"""
    rc, out = _run(["--list-whitelist"])
    assert rc == 0
    assert "screening.py" in out


def test_data_tolerates_one_day_t1_lag(tmp_path, monkeypatch):
    """数据层容忍 ≤1 自然日上游 T+1 发布滞后；超前 ≥2 天才判违规。"""
    import pandas as pd
    feat = tmp_path / "features.csv"
    raw = tmp_path / "raw"
    raw.mkdir()
    pd.DataFrame({"date": ["2026-10-13"]}).to_csv(feat, index=False)
    for name in ("vix.csv", "sentiment.csv", "prices.csv"):
        pd.DataFrame({"date": ["2026-10-12"]}).to_csv(raw / name, index=False)
    monkeypatch.setattr(la, "FEATURES_PATH", feat)
    monkeypatch.setattr(la, "RAW_DIR", raw)
    assert la.check_data()["ahead_of_raw"] is False  # 超前 1 天 → 容忍

    # 超前 2 天（真停更 / 真前瞻风险）→ 判违规并带 ahead_days
    pd.DataFrame({"date": ["2026-10-14"]}).to_csv(feat, index=False)
    data = la.check_data()
    assert data["ahead_of_raw"] is True
    assert data["violations"] and all(v["ahead_days"] >= 2 for v in data["violations"])


if __name__ == "__main__":
    pytest.main([__file__])
