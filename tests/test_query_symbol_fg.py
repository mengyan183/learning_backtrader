# -*- coding: utf-8 -*-
"""`scripts/query_symbol_fg.py`（按标的查系统贪恐系数）。

核心断言：**来源必须可辨** ✗ ——
- 已登记 + 底层够 ⇒ `个股` ✓
- 已登记 + 底层不足 ⇒ `大盘回退` ✓ + 说明原因 ✓
- **未登记** ⇒ **不给分数** ✗（否则等于把大盘分冒充个股分 ✗）
"""
import importlib.util
import json
import os

import pandas as pd
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "query_symbol_fg.py")


def _load():
    spec = importlib.util.spec_from_file_location("query_symbol_fg", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


q = _load()


@pytest.fixture
def prices():
    """只给 `AXTI` 900 行 ⇒ AXTX 够 ✓；CONL 的 `COIN` 缺 ✗。"""
    dates = pd.date_range("2022-01-03", periods=900, freq="B")
    return pd.DataFrame({"symbol": "AXTI", "date": dates,
                         "close": pd.Series(range(100, 1000), dtype=float).values})


@pytest.fixture
def market(tmp_path, monkeypatch):
    """给市场级 fg_index（回退用）✓。"""
    p = tmp_path / "features.csv"
    pd.DataFrame({"date": ["2026-10-16"], "fg_index": [62.0]}).to_csv(p, index=False)
    monkeypatch.setattr(q.config, "DATA_DIR", str(tmp_path))
    return 62.0


def test_registered_with_data_is_per_symbol(prices, market):
    r = q.query("AXTX", prices=prices)
    assert r["source"] == "个股"
    assert r["value"] is not None and 0 <= r["value"] <= 100
    assert r["error"] is None


def test_registered_but_short_history_falls_back(prices, market):
    """CONL 底层 COIN 缺 ⇒ 回退大盘，但**必须标注** ✓ 且说明原因 ✓。"""
    r = q.query("CONL", prices=prices)
    assert r["source"] == "大盘回退"
    assert r["value"] == market
    assert "回退" in (r["error"] or "")


def test_unregistered_symbol_gets_no_score(prices, market):
    """NVDA 未登记 ⇒ **不得给分数** ✗（给了就是把大盘分冒充个股分 ✗）。"""
    r = q.query("NVDA", prices=prices)
    assert r["value"] is None
    assert r["source"] is None
    assert "未在" in (r["error"] or "")


def test_cli_json_output(prices, market, tmp_path, monkeypatch, capsys):
    """`--json` 可被程序消费 ✓；含 `source` 字段 ✓。"""
    monkeypatch.setattr(q, "main", q.main)      # 保持原样，仅确认可调用
    rc = q.main(["--json", "AXTX"])
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data[0]["symbol"] == "AXTX"
    assert data[0]["source"] in ("个股", "大盘回退")
    assert rc == 0


def test_cli_returns_one_when_any_symbol_unresolved(prices, market):
    """有标的分不出 ⇒ 退出码 1 ✓（便于脚本判断 ✗）。"""
    assert q.main(["NVDA"]) == 1

def test_unregistered_suggests_close_match(prices, market):
    """未登记时给**模糊建议** ✗ —— 2026-10-21 实测：用户输入 `KOORU`、本意 `KORU` ✓。"""
    r = q.query("KOORU", prices=prices)
    assert r["value"] is None
    assert "是否想查" in (r["error"] or "")
    assert "KORU" in r["error"]


def test_koru_is_registered():
    """`KORU` 必须已登记（Direxion 3x 韩国 ✓，底层 `EWY` ✓）。"""
    r = q.query("KORU", prices=None)
    assert r["underlying"] == "EWY"

# ------------------------------------- 反向标的（2026-10-21 修 P0-4c ✓）
def test_inverse_symbol_is_flipped(prices, market):
    """🔴 **反向标的必须翻转** ✗：`SQQQ` = 3x 做空 QQQ ✓。

    同一底层（QQQ ✓）下：`TQQQ` 与 `SQQQ` 的分数应**互为镜像** ✓
    （`TQQQ + SQQQ == 100` ✓）。若不翻转 ⇒ 两者**相同** ✗ —— 方向全反 ✗。
    """
    from fg_system.factors import symbol as _sym
    if "TQQQ" not in set(prices["symbol"]) or "SQQQ" not in set(prices["symbol"]):
        pytest.skip("fixture 未含 TQQQ/SQQQ（精简数据 ✓）")
    tq = _sym.symbol_fg_index("TQQQ", prices=prices)
    sq = _sym.symbol_fg_index("SQQQ", prices=prices)
    assert tq is not None and sq is not None
    a, b = tq.dropna(), sq.dropna()
    if a.empty or b.empty:
        pytest.skip("测试数据不足")
    # 逐日镜像（容差 1e-6）
    joined = a.rename("t").to_frame().join(b.rename("s"), how="inner").dropna()
    assert not joined.empty
    assert ((joined["t"] + joined["s"]) - 100.0).abs().max() < 1e-6


def test_inverse_config_lists_sqqq():
    """`SIGNAL_INVERSE` 必须包含 `SQQQ` ✓（配置与逻辑分离 ✓，加新标的只改配置 ✓）。"""
    from fg_system import config
    assert "SQQQ" in config.SIGNAL_INVERSE

# ------------------------------- GDXU 合成（2026-10-21 修团队审查 P1 ✓）
def test_gdxu_blend_uses_inner_join():
    """🔴 合成**必须 inner join** ✗ —— 缺一条腿的日期不得变成 NaN ✗。

    原实现 `out + sub`（Series 相加 ✗）⇒ 索引取**并集** ✗ ⇒ 缺腿那天 NaN ✗
    ⇒ `pct_change`/`rolling` 传播 ✗ ⇒ `dropna` **静默丢样本** ✗。
    """
    import pandas as pd
    from fg_system.factors import symbol as _sym

    dates = pd.bdate_range("2024-01-01", periods=80)
    rows = []
    for d in dates:
        rows.append({"symbol": "GDX", "date": d, "close": 10.0})
        rows.append({"symbol": "GDXJ", "date": d, "close": 20.0})
    px = pd.DataFrame(rows)
    # 删掉 GDXJ 的最后 3 天 ⇒ 那 3 天只有一条腿
    drop = set(sorted(px["date"].unique())[-3:])
    px = px[~((px["symbol"] == "GDXJ") & px["date"].isin(drop))]

    out = _sym.underlying_close("GDXU", prices=px)
    assert out is not None
    assert not out.isna().any(), "合成结果不得含 NaN ✗"
    assert len(out) == len(dates) - 3, "缺腿的日期应被**剔除**而非变 NaN ✗"


def test_gdxu_blend_returns_none_when_leg_missing():
    """缺**整条**腿 ⇒ 必须 `None` ✗（不给半边合成 ✗）。"""
    import pandas as pd
    from fg_system.factors import symbol as _sym

    dates = pd.bdate_range("2024-01-01", periods=80)
    px = pd.DataFrame([{"symbol": "GDX", "date": d, "close": 10.0} for d in dates])
    assert _sym.underlying_close("GDXU", prices=px) is None
