# -*- coding: utf-8 -*-
"""`/api/symbol_fg` —— 页面上的「按标的查贪恐系数」入口（WT-51）。

页面必须能分辨**来源三态** ✗（这是本轮修的核心缺陷 ✓）：
- `个股` ✓
- `大盘回退` ✓（已登记但底层 < 816 行 ✗）
- `null` ✗（未登记 ⇒ `value` 也必须是 null ✗，绝不能给大盘分冒充 ✗）
"""
import pandas as pd
import pytest

from fg_system.dashboard import server


@pytest.fixture
def client(tmp_path, monkeypatch):
    """只给 `AXTI` 900 行 ⇒ AXTX 个股分 ✓；CONL 的 COIN 缺 ✗；NVDA 未登记 ✗。"""
    dates = pd.date_range("2022-01-03", periods=900, freq="B")
    prices = pd.DataFrame({"symbol": "AXTI", "date": dates,
                           "close": pd.Series(range(100, 1000), dtype=float).values})
    prices.to_csv(tmp_path / "prices.csv", index=False)
    pd.DataFrame({"date": ["2026-10-16"], "fg_index": [62.0]}).to_csv(
        tmp_path / "features.csv", index=False)

    monkeypatch.setattr(server.config, "RAW_DIR", str(tmp_path))
    monkeypatch.setattr(server.config, "DATA_DIR", str(tmp_path))

    app = server.make_handler(lambda: pd.DataFrame({"fg_index": [62.0]}))
    app.config["TESTING"] = True
    return app.test_client()


def test_returns_per_symbol_with_source(client):
    r = client.get("/api/symbol_fg?symbols=AXTX,CONL,NVDA")
    assert r.status_code == 200
    j = r.get_json()
    items = {i["symbol"]: i for i in j["items"]}

    assert items["AXTX"]["source"] == "个股" and items["AXTX"]["value"] is not None
    assert items["CONL"]["source"] == "大盘回退" and "回退" in items["CONL"]["error"]
    # 🔴 未登记 ⇒ 不给分（否则就是把大盘分冒充个股分 ✗）
    assert items["NVDA"]["value"] is None and items["NVDA"]["source"] is None
    assert j["data_date"] == "2026-10-16"          # 页面必须显示数据日期 ✓


def test_missing_symbols_returns_400(client):
    r = client.get("/api/symbol_fg")
    assert r.status_code == 400
    assert "symbols" in r.get_json()["error"]


def test_chinese_comma_and_upper(client):
    """中文逗号也认 ✓、代码自动大写 ✓。"""
    r = client.get("/api/symbol_fg?symbols=axtx，conl")
    items = r.get_json()["items"]
    assert [i["symbol"] for i in items] == ["AXTX", "CONL"]


def test_page_has_query_widget():
    """页面上真的有输入框 + 按钮 + 调接口（否则「入口在页面上」就是空话 ✗）。"""
    import os
    tpl = os.path.join(os.path.dirname(os.path.dirname(server.__file__)),
                       "dashboard", "templates", "index.html")
    t = open(tpl, encoding="utf-8").read()
    assert 'id="sfgInput"' in t          # 输入框
    assert 'id="sfgBtn"' in t            # 查询按钮
    assert "/api/symbol_fg" in t          # 调接口
    assert "大盘回退" in t                 # 来源三态说明（防止页面误导 ✗）
    # 🔴 逐项数据日期 + 滞后标红（Mac 实测：CONL 的 COIN 只到 10-01 ✗）
    assert "数据日期" in t
    assert "滞后" in t
    assert "it.date" in t                 # 真的用了接口透出的 date ✓


def test_api_exposes_per_item_date(client):
    """接口必须透出**每项** `date` 与 `data_date` ✓ —— 页面才有东西可标滞后 ✓。"""
    j = client.get("/api/symbol_fg?symbols=AXTX,CONL").get_json()
    assert j["data_date"] is not None
    for it in j["items"]:
        assert "date" in it               # 字段存在（值可为 None ✓）
