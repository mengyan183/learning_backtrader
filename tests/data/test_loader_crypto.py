# -*- coding: utf-8 -*-
"""加密宽表加载测试。"""
import os

import numpy as np
import pandas as pd
import pytest

from fg_system import config
from fg_system.data import loader


def _write_fixtures(tmp_path):
    """构造最小可用的原始数据文件。

    注意：SPY 写入 **prices.csv**（主日历来源），不写入 crypto_prices.csv
    —— 后者在生产环境不含 SPY。
    """
    spy = pd.DataFrame({
        "date": pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"]),
        "symbol": ["SPY"] * 3,
        "open": [500.0] * 3, "high": [505.0] * 3, "low": [495.0] * 3,
        "close": [500.0, 505.0, 510.0], "volume": [1e6] * 3,
    })
    spy.to_csv(os.path.join(config.RAW_DIR, "prices.csv"), index=False)

    px = pd.DataFrame({
        "date": pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"]),
        "symbol": ["BITX"] * 3,
        "open": [10.0] * 3, "high": [11.0] * 3, "low": [9.0] * 3,
        "close": [10.0, 10.5, 11.0], "volume": [100.0] * 3,
    })
    px.to_csv(config.CRYPTO_PRICES_PATH, index=False)

    btc = pd.DataFrame({
        "date": pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"]),
        "close": [90000.0, 92000.0, 91000.0],
    })
    btc.to_csv(config.CRYPTO_UNDERLYING_PATH, index=False)

    fng = pd.DataFrame({
        "date": pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"]),
        "value": [50.0, 60.0, 55.0],
        "classification": ["Neutral", "Greed", "Greed"],
    })
    fng.to_csv(config.CRYPTO_FNG_PATH, index=False)


@pytest.fixture
def fixtures(tmp_path, monkeypatch):
    """把 config 的三个路径指到临时目录，避免污染真实数据。"""
    monkeypatch.setattr(config, "RAW_DIR", str(tmp_path))
    monkeypatch.setattr(config, "CRYPTO_PRICES_PATH", str(tmp_path / "crypto_prices.csv"))
    monkeypatch.setattr(config, "CRYPTO_UNDERLYING_PATH", str(tmp_path / "crypto_underlying.csv"))
    monkeypatch.setattr(config, "CRYPTO_FNG_PATH", str(tmp_path / "crypto_fng.csv"))
    _write_fixtures(tmp_path)
    return tmp_path


def test_crypto_wide_has_expected_columns(fixtures):
    wide = loader.to_crypto_wide()
    assert ("BITX", "close") in wide.columns
    assert ("BTC", "close") in wide.columns
    assert ("FNG", "value") in wide.columns


def test_crypto_wide_index_is_equity_calendar(fixtures):
    """索引必须来自 prices.csv 的 SPY 交易日。"""
    wide = loader.to_crypto_wide()
    assert list(wide.index) == list(pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"]))


def test_crypto_wide_does_not_forward_fill_prices(fixtures):
    """价格缺失必须保持 NaN（§4.3），不能前向填充。"""
    px = pd.read_csv(config.CRYPTO_PRICES_PATH)
    px = px[~((px["symbol"] == "BITX") & (px["date"] == "2026-01-05"))]
    px.to_csv(config.CRYPTO_PRICES_PATH, index=False)
    wide = loader.to_crypto_wide()
    assert pd.isna(wide.loc[pd.Timestamp("2026-01-05"), ("BITX", "close")])


def test_crypto_wide_fng_is_forward_filled(fixtures):
    """FNG 缺失前向填充（指数类），与价格类处理不同。"""
    fng = pd.read_csv(config.CRYPTO_FNG_PATH)
    fng = fng[fng["date"] != "2026-01-05"]
    fng.to_csv(config.CRYPTO_FNG_PATH, index=False)
    wide = loader.to_crypto_wide()
    assert wide.loc[pd.Timestamp("2026-01-05"), ("FNG", "value")] == pytest.approx(50.0)


def test_crypto_wide_raises_on_missing_underlying(fixtures):
    """缺 BTC 现货时必须报错——CF2 与趋势过滤都依赖它。"""
    os.remove(config.CRYPTO_UNDERLYING_PATH)
    with pytest.raises(loader.DataQualityError):
        loader.to_crypto_wide()


def test_crypto_wide_btc_aligned_to_equity_calendar(fixtures):
    """BTC 是 7 天日历，必须 reindex 到美股交易日。"""
    wide = loader.to_crypto_wide()
    assert wide.loc[pd.Timestamp("2026-01-05"), ("BTC", "close")] == pytest.approx(92000.0)


def _rows(idx, symbol, close):
    """把一条 close 序列展开成长表的多行（OHLCV 同值，仅 close 有信息）。"""
    return pd.DataFrame({
        "date": list(idx), "symbol": symbol,
        "open": close, "high": close, "low": close,
        "close": close, "volume": 1.0,
    })


def test_crypto_anomalies_raises_on_missing_underlying():
    """缺 BTC 时必须报错，不能静默跳过 BITX/BITU。"""
    idx = pd.bdate_range("2024-01-01", periods=30)
    df = pd.DataFrame({
        "date": list(idx), "symbol": ["BITX"] * 30,
        "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "volume": 1.0,
    })
    with pytest.raises(loader.DataQualityError, match="缺失"):
        loader.check_crypto_anomalies(df)


def test_crypto_anomalies_uses_window_not_single_day():
    """用 5 日累计：单日反向跳变但 5 日累计一致时不应报错。

    构造逻辑（夹具设计说明）：

    1. 底层 BTC 取恒定的日收益 r=0.1%（30 天），ETF 恰好 2×（日收益 2r）。
       这样两者的 1 日与 5 日累计收益在无扰动时都严格一致。
    2. 在第 20 天注入**自消脉冲**：`etf[20] *= 0.8`、`etf[21] /= 0.8`。
       第 21 天起 ETF 回到原轨迹，因此**跨越 21 日之后的 5 日窗口**累计不变；
       但 19→20（−19.84%）与 20→21（+56.56%）的单日收益被大幅打乱，
       使得跨脉冲边界的 5 日累计出现约 25pp 的残差。
    3. 取 threshold=0.50（50pp）：单日检测的最大偏离为 56.36pp → 会被标记（失败）；
       5 日检测的最大偏离为 25.25pp → 不标记（通过）。
       这正是「5 日累计稀释相位伪影」的判别点，若实现退回单日收益本测试必挂。
    """
    idx = pd.bdate_range("2024-01-01", periods=30)
    r = 0.001
    und = 100.0 * np.cumprod([1 + r] * 30)
    etf = 100.0 * np.cumprod([1 + 2 * r] * 30)
    etf[20] *= 0.80
    etf[21] /= 0.80

    # 必须提供 CRYPTO_UNDERLYING 的**全部**配对——缺任一即报错（这正是要测的行为）。
    # 其余配对用「2× 严格一致」的干净序列，不会触发任何偏离。
    rows = [_rows(idx, "BITX", etf), _rows(idx, "BTC", und)]
    added = {"BITX", "BTC"}
    for other_lev, other_und in config.CRYPTO_UNDERLYING.items():
        for sym in (other_lev, other_und):
            if sym in added:
                continue
            added.add(sym)
            base = 100.0 * np.cumprod([1 + r] * 30)
            series = base if sym == other_und else 100.0 * np.cumprod([1 + 2 * r] * 30)
            rows.append(_rows(idx, sym, series))
    df = pd.concat(rows, ignore_index=True)

    # 单日收益在 2024-01-30 的偏离 56.36pp > 50pp → 单日实现会失败
    lev_r = pd.Series(etf, index=idx).pct_change()
    und_r = pd.Series(und, index=idx).pct_change()
    assert (lev_r - 2 * und_r).abs().max() > 0.50

    # 5 日累计偏离 < 50pp → 本实现通过
    loader.check_crypto_anomalies(df, threshold=0.50, jump_threshold=5.0)


def test_cum_return_window():
    s = pd.Series([100.0, 110.0, 121.0, 133.1],
                  index=pd.bdate_range("2024-01-01", periods=4))
    r = loader._cum_return(s, 2)
    assert pd.isna(r.iloc[1])
    assert r.iloc[2] == pytest.approx(0.21)
