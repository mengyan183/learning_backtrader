"""MT-46 连带修复：update_crypto_prices 空返回 / 单标的异常不再静默容忍。

此前行为：fetch_crypto_symbol 返回空 DataFrame 或抛异常 ⇒ 函数正常返回、日志无痕
⇒ 加密数据停更无人知晓。现在：
- fromdate 距今 >1 天仍 0 行 ⇒ 打印 ⚠️ 并在末尾汇总
- 单标的异常 ⇒ 打印但不中断整批（旧数据保留）
- fromdate=今天（已最新）⇒ 空 frames 属正常，不告警
"""
import pandas as pd

from fg_system.data import fetch as fmod


def _old_csv(tmp_path, rows):
    p = tmp_path / "crypto.csv"
    pd.DataFrame(rows).to_csv(p, index=False)
    return str(p)


def _patch_base(monkeypatch, fromdate):
    """公共 mock：CRYPTO_FETCH_SYMBOLS 置空（只留 MSTR/COIN）、missing_ranges 固定 fromdate、不真睡。"""
    monkeypatch.setattr(fmod.config, "CRYPTO_FETCH_SYMBOLS", [])
    monkeypatch.setattr(fmod, "missing_ranges", lambda old, sym: (fromdate, None))
    monkeypatch.setattr(fmod.time, "sleep", lambda s: None)


def test_warns_when_stale(monkeypatch, capsys, tmp_path):
    """fromdate 距今 >1 天仍抓到 0 行 ⇒ 打印 ⚠️ 告警（不再静默）"""
    old = _old_csv(tmp_path, {
        "symbol": ["MSTR"] * 3,
        "date": pd.to_datetime(["2026-09-29", "2026-09-30", "2026-10-01"]),
        "close": [1.0, 1.1, 1.2],
    })
    stale_from = pd.Timestamp.today().normalize() - pd.Timedelta(days=10)
    _patch_base(monkeypatch, stale_from)
    monkeypatch.setattr(fmod, "fetch_crypto_symbol", lambda symbol, **kw: pd.DataFrame())

    fmod.update_crypto_prices(path=old, sleep=0)
    out = capsys.readouterr().out
    assert "⚠️" in out
    assert "MSTR" in out
    assert "COIN" in out  # 两个标的都应进 stale 列表


def test_survives_per_symbol_exception(monkeypatch, tmp_path):
    """单标的抛异常 ⇒ 打印但不中断整批；其他标的正常新增；旧数据保留"""
    old = _old_csv(tmp_path, {
        "symbol": ["MSTR", "COIN"],
        "date": pd.to_datetime(["2026-10-19", "2026-10-19"]),
        "close": [1.0, 2.0],
    })
    today = pd.Timestamp.today().normalize()
    _patch_base(monkeypatch, today)

    def fake_fetch(symbol, **kw):
        if symbol == "MSTR":
            raise RuntimeError("Nasdaq 限流")
        return pd.DataFrame({
            "symbol": [symbol],
            "date": pd.to_datetime([today]),
            "close": [9.9],
        })

    monkeypatch.setattr(fmod, "fetch_crypto_symbol", fake_fetch)

    merged, added = fmod.update_crypto_prices(path=old, sleep=0)
    assert added["MSTR"] == 0           # 异常标的无新增
    assert added["COIN"] == 1           # 其他标的正常新增
    assert "MSTR" in merged["symbol"].unique()  # 旧数据保留
    assert "COIN" in merged["symbol"].unique()


def test_no_warn_when_up_to_date(monkeypatch, capsys, tmp_path):
    """fromdate=今天（old 已最新）⇒ 空 frames 是「无新数据」的正常情况，不告警"""
    old = _old_csv(tmp_path, {
        "symbol": ["MSTR"],
        "date": pd.to_datetime(["2026-10-19"]),
        "close": [1.0],
    })
    today = pd.Timestamp.today().normalize()
    _patch_base(monkeypatch, today)
    monkeypatch.setattr(fmod, "fetch_crypto_symbol", lambda symbol, **kw: pd.DataFrame())

    fmod.update_crypto_prices(path=old, sleep=0)
    out = capsys.readouterr().out
    assert "⚠️" not in out
