# -*- coding: utf-8 -*-
"""WT-17 `scripts/sensitivity_scan.py` 测试。

【为什么必须有】
`sensitivity_scan.py` 是最接近触碰 OOS 红线（禁止调参）的入口 —— 它本身就在
扫参数。当前零测试 ⇒ 没有判别力保护：编排错、参数覆盖没收口、写回生产配置，
都不会被任何测试挡住。

【测试策略】
- **不读真实 Data/**：`config.FEATURES_PATH` / `config.RAW_DIR` 全部指到 tmp_path。
- **mock 计算、保留编排**：把重活（`recompute_targets` 跑 pipeline、
  `_sensitivity_metric` 跑 backtrader）mock 掉，`main()` 的**编排**（参数组合
  数 × 标的数 ⇒ 调用次数、输出文件/列名）与**纯函数**（`sensitivity_table`
  的敏感度标注、`apply_params`/`restore_params` 的内存级还原）跑真实代码。
- **钉不变量**：扫描**不得**写回 `config.py`、**不得**往 `Data/` 写产出。
"""
import importlib.util
import os

import pandas as pd
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "sensitivity_scan.py")


def _load():
    spec = importlib.util.spec_from_file_location("sensitivity_scan", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ss = _load()


# ================================================================ 测试夹具
def _make_features(tmp_path, periods=200, with_cols=True):
    """造一份最小 features.csv（含 fg_index/drawdown/zone/target_position）。

    返回 (features_path, Data 目录)。features 放在 <tmp>/Data/features.csv，
    使 main() 推导的 out_dir = <tmp>/evolution/sensitivity —— **全部落在
    tmp_path 内**，绝不触碰真实 Data/。
    """
    data_dir = tmp_path / "Data"
    data_dir.mkdir()
    idx = pd.date_range("2024-01-01", periods=periods, freq="B")
    cols = {"fg_index": 50.0, "zone": 2, "target_position": 0.4, "drawdown": -0.05}
    if not with_cols:                        # 缺列场景
        cols.pop("fg_index")
        cols.pop("drawdown")
    df = pd.DataFrame(cols, index=idx)
    path = data_dir / "features.csv"
    df.reset_index(names="date").to_csv(path, index=False)
    return str(path), data_dir


def _seed_prices(data_dir, symbols=("TQQQ", "SOXL")):
    """写 RAW_DIR/prices.csv（main 用它筛默认标的）。"""
    rows = []
    for s in symbols:
        rows.append({"date": "2024-01-01", "symbol": s, "open": 1.0, "high": 1.0,
                     "low": 1.0, "close": 1.0, "volume": 1.0})
    pd.DataFrame(rows).to_csv(data_dir / "prices.csv", index=False)


@pytest.fixture
def patched(monkeypatch, tmp_path):
    """把路径与标的指到 tmp_path；mock 掉两处重计算，保留全部编排。"""
    feat, data_dir = _make_features(tmp_path)
    _seed_prices(data_dir)
    monkeypatch.setattr(ss.config, "FEATURES_PATH", feat)
    monkeypatch.setattr(ss.config, "RAW_DIR", str(data_dir))
    monkeypatch.setattr(ss.config, "SYMBOLS", ["TQQQ", "SOXL"])
    return {"data_dir": data_dir, "features": feat, "tmp": tmp_path}


def _mock_heavy(monkeypatch, recompute_calls, metric_calls):
    """mock 重计算，记录调用。编排逻辑与文件写出仍是真实代码。"""
    def fake_recompute(features, group, value):
        recompute_calls.append((group, value))
        return features

    def fake_metric(features, symbol):
        metric_calls.append(symbol)
        return {"annual_return": 0.30, "max_drawdown": -0.20,
                "sharpe": 1.5, "ic": 0.05}

    monkeypatch.setattr(ss, "recompute_targets", fake_recompute)
    monkeypatch.setattr(ss, "_sensitivity_metric", fake_metric)


# ================================================================ argparse
def test_help_runs(monkeypatch, capsys):
    """--help 可运行（argparse 正常，退出 0）。"""
    monkeypatch.setattr("sys.argv", ["sensitivity_scan.py", "--help"])
    with pytest.raises(SystemExit) as exc:
        ss.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--group" in out and "--quick" in out and "--symbols" in out


# ================================================================ 无数据路径
def test_missing_features_file_exits_2(monkeypatch, tmp_path, capsys):
    """features.csv 缺失 ⇒ **退出 2**（不是裸 traceback）。

    退出码 2 = 「环境未就绪，先跑 pipeline 再来」，与 argparse 用法错误同码；
    上层脚本/CI 据此区分「数据没准备好」与「程序本身出错」。
    """
    monkeypatch.setattr(ss.config, "FEATURES_PATH", str(tmp_path / "nope.csv"))
    monkeypatch.setattr(ss.config, "RAW_DIR", str(tmp_path))
    monkeypatch.setattr("sys.argv", ["sensitivity_scan.py"])
    with pytest.raises(SystemExit) as exc:
        ss.main()
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "先跑 pipeline" in err, "退出前必须给出可操作提示"


def test_features_missing_required_columns_exits_2(monkeypatch, tmp_path, capsys):
    """features.csv 存在但缺 fg_index/drawdown ⇒ 同样**退出 2**（口径统一）。"""
    feat, data_dir = _make_features(tmp_path, with_cols=False)
    _seed_prices(data_dir)
    monkeypatch.setattr(ss.config, "FEATURES_PATH", feat)
    monkeypatch.setattr(ss.config, "RAW_DIR", str(data_dir))
    monkeypatch.setattr("sys.argv", ["sensitivity_scan.py"])
    with pytest.raises(SystemExit) as exc:
        ss.main()
    assert exc.value.code == 2
    assert "缺少 fg_index/drawdown" in capsys.readouterr().err


# ================================================================ 编排：组合数
def test_main_scans_grid_times_symbols(monkeypatch, patched, capsys):
    """编排不变量：N 个参数值 × M 个标的 ⇒ recompute/metric 各调用 N×M 次。

    用 --group core（5 个网格值）× 2 个默认标的 = 10 次。
    """
    recompute_calls, metric_calls = [], []
    _mock_heavy(monkeypatch, recompute_calls, metric_calls)
    monkeypatch.setattr("sys.argv", ["sensitivity_scan.py", "--group", "core"])
    ss.main()

    grid = ss.GROUPS["core"]["grid"]
    assert len(grid) == 5
    assert len(recompute_calls) == 5 * 2, "参数值×标的 的组合数不对"
    assert len(metric_calls) == 5 * 2
    # 每个参数值对每个标的各算一次（无遗漏、无重复）
    assert sorted(v for _, v in recompute_calls) == sorted(grid * 2)


def test_main_quick_reduces_grid_to_two(monkeypatch, patched):
    """--quick：网格 > 2 时只取首尾两个值 ⇒ 2 × 标的数。"""
    recompute_calls, metric_calls = [], []
    _mock_heavy(monkeypatch, recompute_calls, metric_calls)
    monkeypatch.setattr("sys.argv", ["sensitivity_scan.py", "--group", "core", "--quick"])
    ss.main()

    assert len(recompute_calls) == 2 * 2


def test_main_symbols_flag_overrides_default(monkeypatch, patched):
    """--symbols 显式指定 ⇒ 只扫指定标的（且不走默认筛选的 prices 读）。"""
    recompute_calls, metric_calls = [], []
    _mock_heavy(monkeypatch, recompute_calls, metric_calls)
    monkeypatch.setattr("sys.argv",
                        ["sensitivity_scan.py", "--group", "core", "--symbols", "TQQQ"])
    ss.main()
    assert metric_calls == ["TQQQ"] * 5


def test_main_all_groups_when_no_group_flag(monkeypatch, patched):
    """不给 --group ⇒ 扫全部 4 组（编排覆盖所有 GROUP）。"""
    recompute_calls, metric_calls = [], []
    _mock_heavy(monkeypatch, recompute_calls, metric_calls)
    monkeypatch.setattr("sys.argv", ["sensitivity_scan.py"])
    ss.main()

    groups_seen = {g for g, _ in recompute_calls}
    assert groups_seen == set(ss.GROUPS)


# ================================================================ 输出格式
def test_output_files_and_columns(monkeypatch, patched):
    """产出落在 evolution/sensitivity/，表头列名正确，README 汇总到位。"""
    recompute_calls, metric_calls = [], []
    _mock_heavy(monkeypatch, recompute_calls, metric_calls)
    monkeypatch.setattr("sys.argv",
                        ["sensitivity_scan.py", "--group", "core", "--symbols", "TQQQ"])
    ss.main()

    out_dir = patched["tmp"] / "evolution" / "sensitivity"
    table = out_dir / "sensitivity_core_TQQQ.md"
    assert table.exists(), "每 (组, 标的) 应出一张表"
    md = table.read_text(encoding="utf-8")
    for col in ["参数值", "年化收益", "最大回撤", "Sharpe", "IC", "敏感度"]:
        assert col in md, "表头缺列：%s" % col
    assert out_dir.joinpath("README.md").exists(), "应产出汇总 README"


# ================================================================ 纯函数：敏感度标注
def test_sensitivity_table_flags_sensitive_and_stable():
    """相对基准偏离超阈 ⇒ 敏感，否则稳定；NaN ⇒ '—'。"""
    baseline = ss.GROUPS["core"]["baseline"]      # 0.45
    results = [
        (0.45, {"annual_return": 0.30, "max_drawdown": -0.2, "sharpe": 1.5, "ic": 0.05}),
        (0.55, {"annual_return": 0.50, "max_drawdown": -0.3, "sharpe": 1.0, "ic": 0.04}),
        (0.35, {"annual_return": 0.305, "max_drawdown": -0.2, "sharpe": 1.4, "ic": 0.05}),
        (0.25, {"annual_return": float("nan"), "max_drawdown": float("nan"),
                "sharpe": float("nan"), "ic": float("nan")}),
    ]
    df = ss.sensitivity_table("core", "TQQQ", results)
    assert df["参数值"].tolist() == [0.45, 0.55, 0.35, 0.25]
    # 0.55 偏离 0.30→0.50 = 0.20 ≥ max(0.02, 0.015) ⇒ 敏感
    assert df.loc[1, "敏感度"] == "敏感"
    # 0.35 偏离 0.005 < 0.02 ⇒ 稳定
    assert df.loc[2, "敏感度"] == "稳定"
    # NaN 年化收益 ⇒ 非数字用 '—'
    assert df.loc[3, "annual_return"] == "—"


def test_sensitivity_table_no_baseline_row_marks_dash():
    """网格里没有基准行 ⇒ 保守不给标注（'—'）。"""
    results = [
        (0.10, {"annual_return": 0.30, "max_drawdown": -0.2, "sharpe": 1.5, "ic": 0.05}),
        (0.20, {"annual_return": 0.50, "max_drawdown": -0.3, "sharpe": 1.0, "ic": 0.04}),
        (0.30, {"annual_return": 0.10, "max_drawdown": -0.1, "sharpe": 0.5, "ic": 0.01}),
    ]
    df = ss.sensitivity_table("core", "TQQQ", results)
    assert set(df["敏感度"].tolist()) == {"—"}


# ================================================================ 不变量：只测量不改参
def test_apply_restore_params_roundtrip(monkeypatch):
    """apply_params 改内存 config；restore_params 精确还原基准值。"""
    for group, attr, baseline in [("core", "CORE_CAP", ss.config.CORE_CAP),
                                  ("zone", "ZONE_EDGES", list(ss.config.ZONE_EDGES))]:
        before = list(baseline) if isinstance(baseline, list) else baseline
        ss.apply_params(group, 0 if group == "core" else [5, 40, 60, 95])
        ss.restore_params(group)
        after = getattr(ss.config, attr)
        after = list(after) if isinstance(after, list) else after
        assert after == before, "%s 未还原到基准" % attr


def test_recompute_restores_params_even_on_pipeline_error(monkeypatch):
    """recompute_targets 的 finally 语义：pipeline.run 抛异常也必须还原 config。

    这是「只测量不改参」的核心不变量——一次异常不能让进程内的 config 停在
    被扫描的临时值上。
    """
    before = ss.config.CORE_CAP

    def boom(*a, **k):
        raise RuntimeError("pipeline 崩了")

    monkeypatch.setattr(ss.pipeline, "run", boom)
    with pytest.raises(RuntimeError):
        ss.recompute_targets(pd.DataFrame({"fg_index": [50.0]}), "core", 0.99)
    assert ss.config.CORE_CAP == before, "pipeline 抛异常后 config 未还原"


def test_recompute_aligns_target_position(monkeypatch):
    """recompute_targets 用 pipeline.run(write=False) 的输出改写 target_position。"""
    seen = {}

    def fake_run(raw_dir=None, write=True, shift_inputs=0):
        seen["write"] = write
        idx = pd.date_range("2024-01-01", periods=5, freq="B")
        return pd.DataFrame({"target_position": [0.1, 0.2, 0.3, 0.4, 0.5]}, index=idx)

    monkeypatch.setattr(ss.pipeline, "run", fake_run)
    features = pd.DataFrame({"fg_index": [50.0] * 5, "target_position": [0.0] * 5},
                            index=pd.date_range("2024-01-01", periods=5, freq="B"))
    out = ss.recompute_targets(features, "core", 0.5)
    assert seen["write"] is False, "必须 write=False，不得回写 features.csv"
    assert out["target_position"].tolist() == [0.1, 0.2, 0.3, 0.4, 0.5]
    assert out.columns.tolist() == features.columns.tolist()


def test_trim_group_is_silent_noop_when_threshold_absent(monkeypatch):
    """现状缺口：config 无 P1_TRIM_THRESHOLD ⇒ trim 组覆盖是**静默空操作**。

    apply_params('trim', v) 因 hasattr 为假而不改任何参数 ⇒ 该组整张表其实在扫
    「常量」——结果全同、敏感性无意义，但脚本不会报错。照实钉住现状。
    """
    if hasattr(ss.config, "P1_TRIM_THRESHOLD"):
        pytest.skip("config 已有 P1_TRIM_THRESHOLD，此缺口不适用")
    snapshot = dict(ss.config.__dict__)
    ss.apply_params("trim", 0.03)
    # 未修改任何 config 值
    for k, v in snapshot.items():
        if k.startswith("_"):
            continue
        assert ss.config.__dict__[k] is v or ss.config.__dict__[k] == v


# ================================================================ 不变量：不写生产
def test_outputs_carry_oos_warning(monkeypatch, patched):
    """WT-26：产物必须带**显式**的 OOS 红线警示（表 + README 都要有）。

    背景：本脚本用**整段** features 扫描参数（无 train/OOS 切分）⇒「只测量不改参」
    此前只写在 docstring 里，产物本身**看不出来**，容易被当成调参依据。
    裁决（2026-10-12，方案②）：不改扫描逻辑，但产物必须显式声明禁止据此调参。
    """
    recompute_calls, metric_calls = [], []
    _mock_heavy(monkeypatch, recompute_calls, metric_calls)
    monkeypatch.setattr("sys.argv",
                        ["sensitivity_scan.py", "--group", "core", "--symbols", "TQQQ"])
    ss.main()

    out_dir = patched["tmp"] / "evolution" / "sensitivity"
    table = (out_dir / "sensitivity_core_TQQQ.md").read_text(encoding="utf-8")
    readme = (out_dir / "README.md").read_text(encoding="utf-8")
    for text, name in ((table, "表"), (readme, "README")):
        assert "OOS" in text, "%s 缺 OOS 声明" % name
        assert "调参" in text, "%s 缺「不得调参」警示" % name
        assert "禁止" in text or "不得" in text, "%s 的警示语气不够硬" % name


def test_main_does_not_write_config_py(monkeypatch, patched):
    """扫描**不得**改 config.py（内存级覆盖的纪律保证）。"""
    before = open(ss.config.__file__, encoding="utf-8").read()
    recompute_calls, metric_calls = [], []
    _mock_heavy(monkeypatch, recompute_calls, metric_calls)
    monkeypatch.setattr("sys.argv",
                        ["sensitivity_scan.py", "--group", "core", "--symbols", "TQQQ"])
    ss.main()
    assert open(ss.config.__file__, encoding="utf-8").read() == before, "config.py 被写了！"


def test_main_writes_nothing_under_data(monkeypatch, patched):
    """扫描**不得**往 Data/ 写产出：产出只进 evolution/sensitivity/。"""
    data_dir = patched["data_dir"]
    before = {p.name for p in data_dir.iterdir()}
    recompute_calls, metric_calls = [], []
    _mock_heavy(monkeypatch, recompute_calls, metric_calls)
    monkeypatch.setattr("sys.argv",
                        ["sensitivity_scan.py", "--group", "core", "--symbols", "TQQQ"])
    ss.main()
    after = {p.name for p in data_dir.iterdir()}
    assert after == before, "Data/ 下出现了新文件：%s" % (after - before)


def test_main_leaves_config_params_at_baseline(monkeypatch, patched):
    """跑完 main() 后进程内 config 参数仍在基准值（无残留覆盖）。"""
    core, edges = ss.config.CORE_CAP, list(ss.config.ZONE_EDGES)
    recompute_calls, metric_calls = [], []
    _mock_heavy(monkeypatch, recompute_calls, metric_calls)
    monkeypatch.setattr("sys.argv", ["sensitivity_scan.py"])
    ss.main()
    assert ss.config.CORE_CAP == core
    assert list(ss.config.ZONE_EDGES) == edges
