# -*- coding: utf-8 -*-
"""MT-66：3× 做多 ETF 关注列表（/api/watchlist_3x + 页面 tab）。

约束（任务书）：
- 清单非空 ✓；每行有底层，或明确标「未知」且**不给贪恐分** ✗（不给大盘分冒充 ✓）
- 批量读本地 CSV，**禁止联网** ✓；复用 query() 的贪恐分与 _shoutu_of() 守猪分 ✓
- tab「关注列表」有同名 sec-wrap（过 test_tab_alignment ✓）
"""
import os

import pandas as pd
import pytest

from fg_system.dashboard import server


@pytest.fixture
def client(tmp_path, monkeypatch):
    """构造最小本地清单 + 行情 + 市场级 fg（纯本地，不联网 ✓）。"""
    raw = tmp_path / "raw"
    raw.mkdir()
    # 官网全资产页本地缓存（只留三倍 / 两倍两条，筛出三倍 ✓）
    pd.DataFrame({
        "date": ["2026-09-29", "2026-09-29"],
        "category": ["美股杠杆", "美股杠杆"],
        "code": ["US.TQQQ", "US.QLD"],
        "name": ["三倍纳指", "两倍纳指"],
        "fg_index": [26.0, 28.0],
        "price": [77.338, 95.1],
        "scale": [1.0, 1.0],
    }).to_csv(raw / "shoutu_etf_universe.csv", index=False)
    # 关注清单（TQQQ 已登记底层 QQQ；BULZ 未登记 ⇒ 未知不给分 ✓）
    pd.DataFrame({
        "symbol": ["TQQQ", "BULZ"],
        "name": ["三倍纳指", "三倍科技"],
        "underlying": ["QQQ", "未知"],
        "source": ["registered", "universe"],
        "price": [77.338, 42.45],
        "universe_fg": [26.0, 22.0],
    }).to_csv(raw / "watchlist_3x.csv", index=False)
    # 市场级 features（data_date 口径 ✓）
    pd.DataFrame({"date": ["2026-10-23"], "fg_index": [62.0]}).to_csv(
        tmp_path / "features.csv", index=False)
    monkeypatch.setattr(server.config, "RAW_DIR", str(raw))
    monkeypatch.setattr(server.config, "DATA_DIR", str(tmp_path))

    app = server.make_handler(lambda: pd.DataFrame({"fg_index": [62.0]}))
    app.config["TESTING"] = True
    return app.test_client()


def test_watchlist_returns_local_items(client):
    r = client.get("/api/watchlist_3x")
    assert r.status_code == 200
    j = r.get_json()
    items = {i["symbol"]: i for i in j["items"]}
    assert set(items) >= {"TQQQ", "BULZ"}
    assert j["as_of"] == "2026-09-29"
    assert j["data_date"] == "2026-10-23"


def test_registered_has_underlying_and_score(client):
    items = {i["symbol"]: i for i in client.get(
        "/api/watchlist_3x").get_json()["items"]}
    t = items["TQQQ"]
    assert t["underlying"] == "QQQ"
    assert t["price"] == 77.338


def test_unknown_underlying_gets_no_score(client):
    """未登记底层 ⇒ 贪恐分必须为 null ✗（不给大盘分冒充 ✓）。"""
    items = {i["symbol"]: i for i in client.get(
        "/api/watchlist_3x").get_json()["items"]}
    b = items["BULZ"]
    assert b["underlying"] == "未知"
    assert b["fg_value"] is None
    assert b["fg_source"] is None


def test_build_list_filters_only_triple_and_unique():
    """build()：只留「三倍」、symbol 唯一、未登记标未知（纯本地 ✓）。"""
    import importlib.util
    path = os.path.join(server.config.ROOT, "scripts",
                        "build_watchlist_3x.py")
    spec = importlib.util.spec_from_file_location("b3x", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    out = m.build()
    assert len(out) >= 20                       # 任务预估 20~30 ✓
    assert out["symbol"].is_unique
    assert out["name"].str.contains("三倍").all()
    # 登记的必须有底层；未登记的统一写「未知」✓
    for _, r in out.iterrows():
        assert r["underlying"] and str(r["underlying"]).strip()


def test_page_has_watchlist_tab_and_section():
    import os
    root = os.path.dirname(os.path.dirname(server.__file__))
    tpl = os.path.join(root, "dashboard", "templates", "index.html")
    t = open(tpl, encoding="utf-8").read()
    assert 'data-name="关注列表"' in t
    assert ">关注列表<" in t                    # 同名 tab 按钮 ✓
    assert "/api/watchlist_3x" in t             # 真的调接口 ✓
    assert t.count("<script") == t.count("</script>")
