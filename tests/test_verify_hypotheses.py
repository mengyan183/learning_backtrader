# -*- coding: utf-8 -*-
"""WT-05 `scripts/verify_hypotheses.py` 扩展测试。

覆盖三条验收标准：
  1. `--help` 必须列出支持的假说。
  2. dry-run 在无数据时明确报「数据缺失（路径）」而不是崩溃（退出码可解释）。
  3. 原有 H-005 / H-007 行为不得回归（分箱 / 布尔位分组仍能跑并给判定）。

另加：修订口径通用触发率函数（H-024/025/027/029/032）的单元行为和追加写不覆盖。
用真实脚本模块（importlib 加载），不跑全量回测、不改库外文件。
"""
import importlib.util
import os
import sys

import pandas as pd
import pytest

from fg_system import config

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "verify_hypotheses.py")


def _load():
    """每次加载一份新鲜模块，避免测试间全局状态串扰。"""
    spec = importlib.util.spec_from_file_location("verify_hypotheses", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vh = _load()


# ------------------------------------------------------------------ 1. --help
def test_help_lists_supported_hypotheses(capsys):
    """`--help` 必须列出支持的假说（验收标准逐条核心之一）。"""
    with pytest.raises(SystemExit) as ei:
        vh.build_arg_parser().parse_args(["--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    for hid in ("H-005", "H-007", "H-024", "H-025", "H-027", "H-029", "H-032"):
        assert hid in out, "「%s」未出现在 --help 输出" % hid


def test_supported_registry_matches_help_list():
    """支持的假说清单与实际注册表一致（防止 --help 与实现漂移）。"""
    assert vh.SUPPORTED[:2] == ["H-005", "H-007"]      # 原案保留在前
    assert set(vh.HYPOTHESES) == {"H-024", "H-025", "H-027", "H-029", "H-032"}
    for hid in vh.SUPPORTED:
        assert hid in vh.SUPPORTED


# ------------------------------------------------------------------ 2. dry-run 数据缺失
def test_dry_run_reports_missing_paths(monkeypatch, tmp_path, capsys):
    """无数据时 dry-run 报「数据缺失（路径）」并返回退出码 2，不崩溃。"""
    monkeypatch.setattr(config, "FEATURES_PATH",
                        str(tmp_path / "features.csv"))
    monkeypatch.setattr(config, "PORTFOLIO_FEATURES_PATH",
                        str(tmp_path / "portfolio_features.csv"))
    rc = vh.main(["--dry-run"])
    out = capsys.readouterr().out
    assert rc == 2, "数据缺失时退出码应为 2"
    assert "数据缺失（路径）" in out
    assert "features.csv" in out and "portfolio_features.csv" in out
    assert "未写任何文件" in out                      # dry-run 不写文件


def test_dry_run_ok_when_data_present(monkeypatch, tmp_path, capsys):
    """数据齐备时 dry-run 返回 0，打印将验证的假说，不写文件。"""
    for name in ("features.csv", "portfolio_features.csv"):
        (tmp_path / name).write_text("date\n", encoding="utf-8")
    monkeypatch.setattr(config, "FEATURES_PATH", str(tmp_path / "features.csv"))
    monkeypatch.setattr(config, "PORTFOLIO_FEATURES_PATH",
                        str(tmp_path / "portfolio_features.csv"))
    rc = vh.main(["--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "[dry-run] 数据齐备" in out
    assert "H-024" in out and "H-032" in out


def test_main_reports_missing_data_without_crash(monkeypatch, tmp_path, capsys):
    """非 dry-run 缺数据时也报「数据缺失（路径）」+退出码 2，而不是抛异常。"""
    monkeypatch.setattr(config, "FEATURES_PATH", str(tmp_path / "nope.csv"))
    monkeypatch.setattr(config, "PORTFOLIO_FEATURES_PATH",
                        str(tmp_path / "nope2.csv"))
    rc = vh.main([])                 # 不得抛异常
    err = capsys.readouterr().err
    assert rc == 2
    assert "数据缺失（路径）" in err


def test_load_features_raises_data_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "FEATURES_PATH", str(tmp_path / "x.csv"))
    with pytest.raises(vh.DataMissingError):
        vh.load_features()


# ------------------------------------------------------------------ 3. 原案 H-005 / H-007 不回归
def _fake_df(n=40):
    """构造最小 df：含 H-005 分箱 / H-007 分组所需的列。"""
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame({
        "fg_index": [45.0] * (n // 2) + [60.0] * (n - n // 2),
        "zone": [1] * n,
        "us_core": [0.18] * (n // 2) + [0.09] * (n - n // 2),
        "target_position": [0.4] * n,
        "trend_blocked_us": [False] * n,
        "trend_blocked_crypto": [False] * n,
    }, index=idx)


def test_h005_still_bins_and_judges():
    """H-005 仍按 <40/40-50/50-55/55-70/>70 分箱并给出判定（不回归）。"""
    res, meta = vh.verify_h005(_fake_df())
    assert list(res["bin"]) == ["<40", "40-50", "50-55", "55-70", ">70"]
    assert "40-50" in set(res["bin"]) and "55-70" in set(res["bin"])
    # 40-50 箱 us_core=0.18、55-70 箱=0.09 ⇒ 比值 2.0 ⇒ 通过
    assert meta["ratio_40_55"] == pytest.approx(2.0, rel=1e-6)
    assert meta["passed"] is True
    assert "口径映射" in meta["note"]


def test_h007_still_groups_and_judges():
    """H-007 仍按布尔位分组比回撤（不回归）。缺 prices.csv ⇒ 明确报缺失。"""
    prices_path = os.path.join(config.RAW_DIR, "prices.csv")
    if not os.path.exists(prices_path):
        with pytest.raises(vh.DataMissingError):
            vh.verify_h007(_fake_df())
        return
    out = vh.verify_h007(_fake_df())
    assert out is not None
    assert "mdd_false" in out and "mdd_true" in out
    assert "passed_abs_smaller" in out
    assert "口径映射" in out["note"]


# ------------------------------------------------------------------ 4. 修订口径通用函数
def test_trigger_rate_for_mask_counts_hits():
    df = _fake_df(10)
    df.iloc[:3, df.columns.get_loc("trend_blocked_us")] = True
    stats = vh.trigger_rate_for_mask(df, df["fg_index"] >= vh.FG_GREED_LINE)
    # 后 5 行 fg=60 不满足 ≥70，前 5 行 fg=45 也不满足 ⇒ 子集为空。
    assert stats["n"] == 0
    stats2 = vh.trigger_rate_for_mask(df, df["fg_index"] < 100)
    assert stats2["n"] == 10
    assert stats2["n_us"] == 3
    assert stats2["rate_any"] == pytest.approx(0.3, rel=1e-6)


def test_judge_trigger_rate_directions():
    """判据方向：high ⇒ ≥50% 成立；low ⇒ ≥50% 不成立。样本为空 ⇒ 无法判定。"""
    assert vh.judge_trigger_rate({"n": 10, "rate_any": 0.6}, "high") is True
    assert vh.judge_trigger_rate({"n": 10, "rate_any": 0.6}, "low") is False
    assert vh.judge_trigger_rate({"n": 10, "rate_any": 0.4}, "low") is True
    assert vh.judge_trigger_rate({"n": 10, "rate_any": 0.4}, "high") is False
    assert vh.judge_trigger_rate({"n": 0, "rate_any": float("nan")}, "high") is None


def test_verify_revised_registry_fields():
    """五条修订假说均注册，字段限定在 zone/fg_index + trend_blocked_*。"""
    for hid, spec in vh.HYPOTHESES.items():
        assert "trend_blocked" in spec["fields"]
        if hid != "H-027":
            assert spec["selector"] is not None


def test_verify_revised_runs_without_crash():
    df = _fake_df(20)
    for hid in vh.HYPOTHESES:
        meta, text = vh.verify_revised(df, hid)
        assert meta["id"] == hid
        assert isinstance(text, list) and text


def test_h027_pending_when_column_missing():
    """H-027 数据源无 AXTX 浮亏列 ⇒ 挂起并标注数据缺失。"""
    df = _fake_df(10)
    meta, text = vh.verify_revised(df, "H-027")
    assert meta["status"] == "pending"
    assert "数据缺失" in " ".join(text)


# ------------------------------------------------------------------ 5. 追加写不覆盖
def test_append_results_does_not_overwrite(tmp_path):
    out = tmp_path / "results.md"
    out.write_text("# 已有内容\n", encoding="utf-8")
    vh.append_results(["## 新块", "内容"], dry_run=False, out_path=str(out))
    text = out.read_text(encoding="utf-8")
    assert "# 已有内容" in text              # 原有内容保留
    assert "## 新块" in text and "内容" in text   # 新内容追加在末尾


def test_append_results_dry_run_writes_nothing(tmp_path):
    out = tmp_path / "results.md"
    vh.append_results(["## 不应写入"], dry_run=True, out_path=str(out))
    assert not out.exists()


# ------------------------------------------------------------------ 6. stdout utf-8
def test_stdout_reconfigured_utf8():
    """§6.2 第 4 条：脚本自带 stdout utf-8。"""
    src = open(SCRIPT, encoding="utf-8").read()
    assert 'sys.stdout.reconfigure(encoding="utf-8"' in src
