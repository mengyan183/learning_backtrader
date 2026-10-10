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
    """支持的假说清单与实际注册表一致（防止 --help 与实现漂移）。

    WT-07 起注册表扩展覆盖全部 open 假说 ⇒ 断言从「精确等于旧五条」放宽为
    「包含旧五条」（原五条的注册**未被删除**，仅新增）。
    """
    assert vh.SUPPORTED[:2] == ["H-005", "H-007"]      # 原案保留在前
    assert {"H-024", "H-025", "H-027", "H-029", "H-032"}.issubset(set(vh.HYPOTHESES))
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
    """**触发率类**假说字段限定在 zone/fg_index + trend_blocked_*。

    WT-07 起注册表含 custom / pending 两类（形态不同、字段不同），
    故本断言只覆盖 kind="trigger" 的条目。
    """
    triggers = {h: s for h, s in vh.HYPOTHESES.items() if s["kind"] == "trigger"}
    assert {"H-024", "H-025", "H-029", "H-032"}.issubset(set(triggers))
    for hid, spec in triggers.items():
        assert "trend_blocked" in spec["fields"], hid
        assert spec["selector"] is not None, hid


def _custom_fixture(n=20):
    """custom/pending 都能跑的完整 df（含 zone/core_position 等列）。"""
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame({
        "fg_index": [50.0 + (i % 5) for i in range(n)],
        "zone": [3] * n,
        "core_position": [0.225] * n,
        "us_core": [0.18] * n,
        "target_position": [0.4] * n,
        "trend_blocked_us": [False] * n,
        "trend_blocked_crypto": [False] * n,
    }, index=idx)


def test_verify_revised_runs_without_crash():
    df = _custom_fixture(20)
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


# ================================================================== WT-07 扩展
# 覆盖全部 open 假说（H-006/008/009/010/011/012/013/014~023/026/028/030/031/
# 033~041）。其中：
#   - 有数据可判的（触发率类 / 形态类）⇒ 给判定；
#   - 数据源未接入或样本不足的 ⇒ 走「等待数据」分支，dry-run 报「数据缺失（路径）」。
WT07_NEW = [
    "H-006", "H-008", "H-009",
    "H-010", "H-011", "H-012", "H-013",
    "H-014", "H-015", "H-016", "H-017", "H-018", "H-019", "H-020",
    "H-021", "H-022", "H-023",
    "H-026", "H-028",
    "H-030", "H-031", "H-033", "H-034", "H-035", "H-036", "H-037",
    "H-038", "H-039", "H-040", "H-041",
]


def test_help_lists_all_wt07_hypotheses(capsys):
    """验收标准①：--help 真实输出必须列出 WT-07 新增假说全集。"""
    with pytest.raises(SystemExit) as ei:
        vh.build_arg_parser().parse_args(["--help"])
    assert ei.value.code == 0
    out = capsys.readouterr().out
    for hid in WT07_NEW:
        assert hid in out, "「%s」未出现在 --help 输出" % hid


def test_supported_contains_all_open_hypotheses():
    """SUPPORTED 必须含全部 WT-07 假说，且不重复、原案仍在前。"""
    assert vh.SUPPORTED[:2] == ["H-005", "H-007"]
    assert len(vh.SUPPORTED) == len(set(vh.SUPPORTED))       # 无重复
    missing = [h for h in WT07_NEW if h not in vh.SUPPORTED]
    assert not missing, "SUPPORTED 缺：%s" % missing
    assert set(WT07_NEW).issubset(set(vh.HYPOTHESES))


def test_hypothesis_registry_has_verdict_kind():
    """每条假说必须声明判定方式：trigger / custom / pending（防注册表漂移）。"""
    for hid, spec in vh.HYPOTHESES.items():
        assert spec.get("kind") in ("trigger", "custom", "pending"), hid
        if spec["kind"] == "trigger":
            assert spec["selector"] is not None
        if spec["kind"] == "pending":
            assert spec.get("missing_dep"), hid


# ---------------------------------------------------------- dry-run 退出码 / 缺数据
def test_dry_run_reports_all_missing_data_files(monkeypatch, tmp_path, capsys):
    """dry-run 数据缺失 ⇒ 打印「数据缺失（路径）」+ 退出码 2，不崩溃。"""
    monkeypatch.setattr(vh, "DATA_DEPENDENCIES",
                        lambda: [str(tmp_path / "features.csv"),
                                 str(tmp_path / "portfolio_features.csv")])
    rc = vh.main(["--dry-run"])
    out = capsys.readouterr().out
    assert rc == 2
    assert "数据缺失（路径）" in out
    assert "features.csv" in out    # 路径必须可指回


def test_dry_run_exit0_when_all_data_present(monkeypatch, tmp_path, capsys):
    p1 = tmp_path / "features.csv"
    p2 = tmp_path / "portfolio_features.csv"
    p1.write_text("date\n", encoding="utf-8")
    p2.write_text("date\n", encoding="utf-8")
    monkeypatch.setattr(vh, "DATA_DEPENDENCIES", lambda: [str(p1), str(p2)])
    rc = vh.main(["--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "[dry-run] 数据齐备" in out
    for hid in WT07_NEW:
        assert hid in out, "dry-run 未列出 %s" % hid


def test_dry_run_reports_waiting_data_hypotheses(monkeypatch, tmp_path, capsys):
    """数据源未接入的假说（H-030/H-034 等）在 dry-run 中明确标注「等待数据」。"""
    p1 = tmp_path / "features.csv"
    p2 = tmp_path / "portfolio_features.csv"
    p1.write_text("date\n", encoding="utf-8")
    p2.write_text("date\n", encoding="utf-8")
    monkeypatch.setattr(vh, "DATA_DEPENDENCIES", lambda: [str(p1), str(p2)])
    vh.main(["--dry-run"])
    out = capsys.readouterr().out
    assert "等待数据" in out
    assert "H-030" in out and "H-034" in out


# ---------------------------------------------------------- 形态类：H-010 / H-012
def _feats_df():
    """最小 features 型 df：zone 由 fg_index 的固定边界决定（无重叠）。

    边界 [20,40,60,80]：fg=5/25/45/70/90 → zone 0/1/2/3/4；
    fg=50/55 → zone 2；fg=65/75 → zone 3。
    """
    idx = pd.date_range("2024-01-01", periods=10, freq="B")
    fg = [5.0, 25.0, 45.0, 70.0, 90.0,                        # 各档 1 天
          50.0, 55.0, 60.0, 65.0, 75.0]                       # 仅 zone 2/3
    zone = [0, 1, 2, 3, 4, 2, 2, 2, 3, 3]
    return pd.DataFrame({"fg_index": fg, "zone": zone}, index=idx)


def _pf_with_booleans(fg_values):
    """给定 fg 序列，构造 trend_blocked 布尔位（前半 True、后半 False）。"""
    idx = pd.date_range("2024-01-01", periods=len(fg_values), freq="B")
    n = len(fg_values)
    return pd.DataFrame({
        "fg_index": fg_values,
        "zone": [2] * n,
        "core_position": [0.225] * n,
        "us_core": [0.18] * n,
        "target_position": [0.4] * n,
        "trend_blocked_us": [True] * (n // 2) + [False] * (n - n // 2),
        "trend_blocked_crypto": [False] * n,
    }, index=idx)


def test_h010_boundary_overlap_judgement():
    """H-010：zone/fg_index 固定边界驱动 —— 区间重叠率 ≤20% ⇒ 成立。"""
    df = _feats_df()
    out = vh.verify_h010(df)
    assert "overlap" in out and "passed" in out
    # fg=50/55/60 zone2；65/70/75 zone3 ⇒ 区间 [50,60] 与 [65,75] 不重叠
    assert out["passed"] is True
    assert "口径" in out["note"]


def test_h012_extreme_dependency_judgement():
    """H-012：True 行 fg_index 落 [35,80] 比例 ≤20% ⇒ 极值依赖成立。"""
    fg = [90.0, 95.0, 88.0, 5.0, 10.0, 20.0, 30.0, 40.0, 50.0, 60.0]
    df = _pf_with_booleans(fg)          # 前 5 行 True（fg 均 ≥80 或 ≤35）
    out = vh.verify_h012(df)
    assert "frac_in_band" in out and "passed" in out
    assert out["passed"] is True         # True 行全部落在极值区外 ⇒ 依赖成立
    assert "口径" in out["note"]


def test_h012_falsified_when_true_rows_in_band():
    """H-012 反例：>20% 的 True 行落在 [35,80] ⇒ 极值依赖被证伪。"""
    fg = [40.0, 45.0, 50.0, 55.0, 60.0, 90.0, 5.0, 88.0, 70.0, 75.0]
    df = _pf_with_booleans(fg)
    out = vh.verify_h012(df)
    assert out["passed"] is False


# ---------------------------------------------------------- 有数据的修订口径类
def test_h013_amplitude_after_switch():
    """H-013：切换点后滚动 10 日振幅收窄 ⇒ 成立。"""
    idx = pd.date_range("2024-01-01", periods=60, freq="B")
    # 前半大幅波动（±15 振荡），后半窄幅（±1 振荡）⇒ 切换后振幅收窄。
    fg = [60.0 + (15.0 if i % 2 else -15.0) for i in range(30)] + \
         [50.0 + (1.0 if i % 2 else -1.0) for i in range(30)]
    df = pd.DataFrame({"fg_index": fg, "zone": [3] * 30 + [2] * 30}, index=idx)
    out = vh.verify_h013(df, switch_idx=30)
    assert "amplitude_before" in out and "amplitude_after" in out
    assert out["passed"] is True
    assert out["amplitude_after"] < out["amplitude_before"]


def test_h014_zone_interval_overlap_monotonic():
    """H-014：zone 越高 fg_index 区间越高且无重叠 ⇒ 单调映射成立。"""
    df = pd.DataFrame({
        "fg_index": [10.0, 30.0, 50.0, 70.0, 90.0, 20.0, 40.0],
        "zone": [0, 1, 2, 3, 4, 1, 2],
    }, index=pd.date_range("2024-01-01", periods=7, freq="B"))
    out = vh.verify_h014(df)
    assert "overlap" in out and "passed" in out
    assert out["passed"] is True


def test_h015_zone_coreposition_inverse_binding():
    """H-015：zone 降档时 core_position 同向升高（反向绑定）⇒ 成立。"""
    df = pd.DataFrame({
        "zone": [3.0, 3.0, 2.0, 2.0],
        "core_position": [0.1125, 0.1125, 0.225, 0.225],
    }, index=pd.date_range("2024-01-01", periods=4, freq="B"))
    out = vh.verify_h015(df)
    assert "n_switches" in out and "passed" in out
    assert out["passed"] is True


def test_h019_zone_fg_rank_correlation():
    """H-019：zone 与 fg_index 秩相关为正 ⇒ 同向联动成立。"""
    df = pd.DataFrame({
        "zone": [1, 2, 3, 4, 2, 3, 1],
        "fg_index": [30.0, 50.0, 70.0, 90.0, 52.0, 68.0, 32.0],
    }, index=pd.date_range("2024-01-01", periods=7, freq="B"))
    out = vh.verify_h019(df)
    assert "spearman" in out and "passed" in out
    assert out["passed"] is True


def test_h020_core_position_interval_bool_counts():
    """H-020：core_position=0.225 区间内布尔位零触发 ⇒ 假设成立。"""
    n = 6
    df = pd.DataFrame({
        "core_position": [0.225] * n,
        "trend_blocked_us": [False] * n,
        "trend_blocked_crypto": [False] * n,
    }, index=pd.date_range("2024-01-01", periods=n, freq="B"))
    out = vh.verify_h020(df)
    assert out["n"] == n
    assert out["n_any"] == 0
    assert out["passed"] is True


def test_h021_zone2_below_prior_zone3():
    """H-021：zone=2.0 行 fg_index 均低于相邻 zone=3.0 行 ⇒ 成立。"""
    df = pd.DataFrame({
        "zone": [3.0, 3.0, 2.0, 2.0, 3.0],
        "fg_index": [67.0, 63.0, 55.0, 52.0, 62.0],
    }, index=pd.date_range("2024-01-01", periods=5, freq="B"))
    out = vh.verify_h021(df)
    assert "n_violations" in out and "passed" in out
    assert out["passed"] is True


def test_h037_trigger_rate_at_greed():
    """H-037：fg≥70 触发率 <50% ⇒ 成立（与 H-024 同数据、判据相反）。"""
    fg = [75.0] * 8 + [50.0] * 2
    n = len(fg)
    df = pd.DataFrame({
        "fg_index": fg,
        "zone": [3] * n,
        "us_core": [0.18] * n,
        "target_position": [0.4] * n,
        "trend_blocked_us": [False] * 7 + [True] + [False] * 2,
        "trend_blocked_crypto": [False] * n,
    }, index=pd.date_range("2024-01-01", periods=n, freq="B"))
    meta, text = vh.verify_revised(df, "H-037")
    assert meta["status"] == "ok"
    assert meta["passed"] is True         # 触发率 1/8 = 12.5% < 50%


# ---------------------------------------------------------- pending / 等待数据
def test_waiting_data_hypotheses_are_pending():
    """数据源未接入 / 样本不足 ⇒ status=pending 且标注数据缺失，不硬凑结论。"""
    for hid in ("H-030", "H-031", "H-034", "H-006", "H-008", "H-009"):
        spec = vh.HYPOTHESES[hid]
        assert spec["kind"] == "pending", hid
        assert spec.get("missing_dep"), hid


def test_verify_any_pending_returns_pending_status():
    df = _fake_df(10)
    meta, text = vh.verify_revised(df, "H-030")
    assert meta["status"] == "pending"
    assert "数据缺失" in " ".join(text)


def test_all_supported_hypotheses_run_without_crash():
    """全部支持假说必须能跑而不抛异常（有数据给判定，无数据给挂起）。"""
    df = _pf_with_booleans([70.0] * 10)
    for hid in vh.SUPPORTED:
        if hid == "H-005":
            vh.verify_h005(df)
        elif hid == "H-007":
            try:
                vh.verify_h007(df)
            except vh.DataMissingError:
                pass
        else:
            meta, text = vh.verify_revised(df, hid)
            assert meta["id"] == hid
