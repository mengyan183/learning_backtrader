# -*- coding: utf-8 -*-
"""守猪待兔 partner API 客户端测试（第 14.5 条）。

全部离线：HTTP 用 monkeypatch 注入，**不联网、不消耗额度**。

参数（lever / emo_area）的期望值来自 **2026-09-23 实测**（第 14.5 条 §3），
**不是推断**。其中三处都曾因推断出错而被实测纠正：

    GDXU  曾定为 us     -> 实测 other（黄金按表单提示语属"其他"）
    AXTX  曾推断为 coin -> 实测 us（AXTI 是半导体公司，美概）
    CRCG  曾语义推断 coin -> 实测 other（页面「已查询」存储 + 数值证据）

**判据是「差 0」**（与页面表格精确吻合），不是"最接近"。
"""
import io
import urllib.parse

import pytest

from fg_system import config
from fg_system.data import fetch, shoutu


class _Bad:
    """open 必失败。"""

    def open(self, req, timeout=None):
        raise OSError("boom")


class _Rec:
    """记录请求内容后返回固定 body。"""

    def __init__(self, body=b'{"status":1}'):
        self.body = body
        self.seen = {}

    def open(self, req, timeout=None):
        self.seen["url"] = req.full_url
        self.seen["method"] = req.get_method()
        self.seen["body"] = req.data
        self.seen["headers"] = dict(req.headers)
        return io.BytesIO(self.body)


# ================================================================ 参数表

def test_api_params_match_measured_values():
    """八个标的的 (lever, emo_area) 必须与实测一致。"""
    expected = {
        "TQQQ": (3, "us"),
        "SOXL": (3, "us"),
        "UPRO": (3, "us"),
        "GDXU": (3, "other"),   # 黄金 => 其他（表单提示语）
        "YINN": (3, "a"),       # 富时中国 => 中概
        "CONL": (2, "coin"),    # Coinbase => 币股
        "AXTX": (2, "us"),      # AXTI 半导体 => 美概
        "CRCG": (2, "other"),   # 用户存储「其他」+ 数值证据
    }
    for sym, want in expected.items():
        assert shoutu.api_params(sym) == want, sym


def test_api_params_rejects_unknown_symbol():
    """**守卫**：未知标的必须报错，防录入笔误（同 append_records 的白名单）。"""
    with pytest.raises(shoutu.ShoutuError, match="未知标的"):
        shoutu.api_params("CONLL")


def test_every_shoutu_symbol_has_api_params():
    """**守卫**：白名单与参数表必须完全一致 —— 否则日常抓取会静默漏标的。"""
    missing = set(config.SHOUTU_SYMBOLS) - set(config.SHOUTU_API_PARAMS)
    assert not missing, "以下标的缺 API 参数：%s" % sorted(missing)


def test_api_params_have_no_extra_symbols():
    """反向守卫：参数表不得含白名单外的标的（防遗留、防笔误）。"""
    extra = set(config.SHOUTU_API_PARAMS) - set(config.SHOUTU_SYMBOLS)
    assert not extra, "参数表含白名单外的标的：%s" % sorted(extra)


def test_all_emo_areas_are_valid():
    """**守卫**：emo_area 必须在**页面实测**的 5 个选项内。

    ⚠️ 官方 docx 只列了 4 个（a/us/coin/other），**漏了 `sk`（韩概）**。
    以页面表单为准（第 14.5 条 §5）。
    """
    for sym, (lever, area) in config.SHOUTU_API_PARAMS.items():
        assert area in config.SHOUTU_EMO_AREAS, sym
        assert 1 <= lever <= 4, sym


def test_lever_agrees_with_existing_leverage_ratio():
    """交叉校验：大盘标的的 lever 必须与既有 `LEVERAGE_RATIO` 一致。"""
    for sym, ratio in config.LEVERAGE_RATIO.items():
        assert shoutu.api_params(sym)[0] == ratio, sym


# ================================================================ 响应解析

_OK = {"status": 1, "msg": "成功", "data": {
    "query": 3, "query_api": 1,
    "name": "三倍做多黄金矿业ETN-MicroSectors",
    "price": 145.6, "score": -73, "time": "2026-09-23 14:51:05"}}


def test_parse_score_payload_extracts_fields():
    out = shoutu.parse_score_payload(_OK)
    assert out["score"] == pytest.approx(-73.0)
    assert out["name"] == "三倍做多黄金矿业ETN-MicroSectors"
    assert out["price"] == pytest.approx(145.6)
    assert out["time"] == "2026-09-23 14:51:05"


def test_parse_score_payload_preserves_negative_scale():
    """**关键**：量程是 −100~100，**不得做任何转换**。

    文档示例 `score:71` 曾让人怀疑是 0~100；实测确认与页面**同口径**
    （TQQQ/SOXL/UPRO/YINN/CONL/GDXU 均精确吻合或差 0）。
    若误按 0~100 处理，负数会被当异常值，或静默错判档位。
    """
    out = shoutu.parse_score_payload(_OK)
    assert out["score"] < 0, "负值必须原样保留"


def test_parse_score_payload_raises_on_status_error():
    """业务错误（status≠1）必须报错，且**带上服务端的 msg** 便于定位。"""
    with pytest.raises(shoutu.ShoutuError, match="杠杆倍数错误"):
        shoutu.parse_score_payload({"status": 2, "msg": "杠杆倍数错误", "data": []})


def test_parse_score_payload_raises_on_missing_data():
    with pytest.raises(shoutu.ShoutuError):
        shoutu.parse_score_payload({"status": 1, "msg": "成功"})


def test_parse_score_payload_raises_on_non_numeric_score():
    """页面未激活时数值显示 `**` —— 必须报错，不能静默变 NaN。"""
    with pytest.raises(shoutu.ShoutuError):
        shoutu.parse_score_payload({"status": 1, "data": {"score": "**"}})


# ================================================================ POST 编码

def test_post_form_sends_urlencoded_body(monkeypatch):
    """实测确认 `application/x-www-form-urlencoded` 可用（无需 multipart）。"""
    rec = _Rec()
    monkeypatch.setattr(fetch, "_opener", lambda url: rec)
    monkeypatch.setattr(fetch, "_throttle", lambda *a, **k: None)
    fetch._post_form("https://x/api", {"code": "US.GDXU", "lever": "3"})

    assert rec.seen["method"] == "POST"
    assert rec.seen["url"] == "https://x/api"
    q = urllib.parse.parse_qs(rec.seen["body"].decode("utf-8"))
    assert q["code"] == ["US.GDXU"] and q["lever"] == ["3"]


def test_post_form_sets_xauth_and_content_type(monkeypatch):
    rec = _Rec()
    monkeypatch.setattr(fetch, "_opener", lambda url: rec)
    monkeypatch.setattr(fetch, "_throttle", lambda *a, **k: None)
    fetch._post_form("https://x/api", {"code": "US.GDXU"},
                     headers={"X-Auth": "tok"})

    hdr = {k.lower(): v for k, v in rec.seen["headers"].items()}
    assert hdr["x-auth"] == "tok"
    assert "x-www-form-urlencoded" in hdr["content-type"]


def test_post_form_error_never_leaks_token(monkeypatch):
    """**守卫**：报错信息**不得包含 headers** —— 里面是会员激活码。

    同 `load_token` 的原则：「绝不回显密钥，否则密钥会随报错进入终端记录与日志」。
    """
    monkeypatch.setattr(fetch, "_opener", lambda url: _Bad())
    monkeypatch.setattr(fetch, "_throttle", lambda *a, **k: None)
    monkeypatch.setattr(fetch.time, "sleep", lambda s: None)
    monkeypatch.setattr(config, "FETCH_RETRIES", 1)

    token = "S3CRETTOKEN0123456789ABCDEFGHIJ"
    with pytest.raises(RuntimeError) as exc:
        fetch._post_form("https://x/api", {"code": "US.GDXU"},
                         headers={"X-Auth": token})
    assert token not in str(exc.value), "密钥泄漏进了报错信息"


def test_post_form_throttles_before_every_attempt(monkeypatch):
    """节流必须在**每次尝试前**（第 12.14 条），与 `_get` 一致。"""
    calls = []
    monkeypatch.setattr(fetch, "_opener", lambda url: _Bad())
    monkeypatch.setattr(fetch, "_throttle", lambda *a, **k: calls.append(1))
    monkeypatch.setattr(fetch.time, "sleep", lambda s: None)
    monkeypatch.setattr(config, "FETCH_RETRIES", 3)
    with pytest.raises(RuntimeError):
        fetch._post_form("https://x/api", {"code": "US.GDXU"})
    assert len(calls) == 3


# ================================================================ 编排

def test_fetch_shoutu_score_passes_params_and_token(monkeypatch):
    seen = {}

    def fake_post(url, fields, headers=None, retries=None):
        seen["url"] = url
        seen["fields"] = fields
        seen["headers"] = headers
        return b'{"status":1,"data":{"score":-73}}'

    monkeypatch.setattr(fetch, "_post_form", fake_post)
    monkeypatch.setattr(shoutu, "load_token", lambda path=None: "tok")
    out = fetch.fetch_shoutu_score("GDXU", 3, "other")

    assert seen["url"] == config.SHOUTU_API_URL
    assert seen["fields"] == {"code": "US.GDXU", "lever": "3", "emo_area": "other"}
    assert seen["headers"]["X-Auth"] == "tok"
    assert out["status"] == 1


def test_collect_scores_uses_per_symbol_params():
    """**核心**：每个标的必须用它**自己的** (lever, emo_area)，不得统一。"""
    seen = []

    def fake(symbol, lever, emo_area):
        seen.append((symbol, lever, emo_area))
        return {"status": 1, "data": {"score": float(len(seen))}}

    out = shoutu.collect_scores(["GDXU", "CONL", "YINN"], fetch_one=fake)
    assert seen == [("GDXU", 3, "other"), ("CONL", 2, "coin"), ("YINN", 3, "a")]
    assert out == {"GDXU": 1.0, "CONL": 2.0, "YINN": 3.0}


def test_collect_scores_defaults_to_whitelist():
    seen = []

    def fake(symbol, lever, emo_area):
        seen.append(symbol)
        return {"status": 1, "data": {"score": 1.0}}

    shoutu.collect_scores(fetch_one=fake)
    assert seen == list(config.SHOUTU_SYMBOLS)


def test_collect_scores_raises_on_any_failure():
    """**任一标的失败必须抛错**，不得静默跳过。

    静默跳过会让当天记录**悄悄缺标的**，而 `append_records` 是覆盖语义，
    缺的那只当天就是空的 —— 序列出现空洞，且事后难以发现。
    （`_post_form` 已重试 5 次并指数退避，能走到这里说明是真故障。）
    """
    def fake(symbol, lever, emo_area):
        if symbol == "YINN":
            return {"status": 2, "msg": "杠杆倍数错误"}
        return {"status": 1, "data": {"score": 1.0}}

    with pytest.raises(shoutu.ShoutuError, match="YINN"):
        shoutu.collect_scores(["GDXU", "YINN"], fetch_one=fake)


def test_collect_scores_error_names_the_symbol():
    """报错必须**指明是哪个标的**，否则 8 个标的里排查要逐个试。"""
    def fake(symbol, lever, emo_area):
        return {"status": 2, "msg": "参数校验失败"}

    with pytest.raises(shoutu.ShoutuError) as exc:
        shoutu.collect_scores(["CRCG"], fetch_one=fake)
    assert "CRCG" in str(exc.value)


# ================================================================ 与存储层衔接

def test_collected_scores_flow_into_append_records(tmp_path):
    """端到端（离线）：collect_scores 的结果可直接交给 append_records。"""
    def fake(symbol, lever, emo_area):
        return {"status": 1, "data": {"score": -73.0}}

    vals = shoutu.collect_scores(["GDXU"], fetch_one=fake)
    p = str(tmp_path / "shoutu_fng.csv")
    wide, n = shoutu.append_records(
        shoutu.mapping_to_frame(vals, date="2026-09-23"), p)
    assert n == 1
    assert wide.loc["2026-09-23", "GDXU"] == pytest.approx(-73.0)


# ================================================================ 页面 / API 对照
# 用户决定**保留 bsk 通道**（`shoutu_daily.cmd` 不切 API），理由是"还需要 API 数据
# 和浏览器页面数据进行对照"。以下函数即该对照的判定逻辑（第 14.5 条）。

def test_compare_all_equal_is_ok():
    rows, ok = shoutu.compare_page_vs_api({"TQQQ": 33.0}, {"TQQQ": 33.0})
    assert ok is True
    assert rows[0]["status"] == "ok"
    assert rows[0]["diff"] == pytest.approx(0.0)


def test_compare_within_tolerance_is_ok():
    """实时指数在"读页面→调 API"的几十秒内会小幅波动，故允许容差。"""
    rows, ok = shoutu.compare_page_vs_api({"TQQQ": 33.0}, {"TQQQ": 35.0}, tol=3.0)
    assert ok is True
    assert rows[0]["status"] == "ok"


def test_compare_beyond_tolerance_fails():
    """**核心**：超容差必须报 diff —— 这正是 `emo_area` 填错时的表现。

    实测：GDXU 用错 area 时 `us` 给 −61、页面 −73，差 12（正确 area 差 0）。
    """
    rows, ok = shoutu.compare_page_vs_api({"GDXU": -73.0}, {"GDXU": -61.0}, tol=3.0)
    assert ok is False
    assert rows[0]["status"] == "diff"
    assert rows[0]["diff"] == pytest.approx(12.0)


def test_compare_marks_symbols_absent_from_page():
    """AXTX / CRCG **不在**页面 11 个分类表内 —— 标为 page_missing，
    且**不参与**判定（否则会误报"不一致"）。"""
    rows, ok = shoutu.compare_page_vs_api(
        {"TQQQ": 33.0}, {"TQQQ": 33.0, "AXTX": -21.0})
    st = {r["symbol"]: r["status"] for r in rows}
    assert st["AXTX"] == "page_missing"
    assert ok is True, "表外标的不应影响判定"


def test_compare_empty_page_is_failure():
    """页面零命中必须判失败 —— 可能是页面改版、未登录，或 sweep 漏读。"""
    rows, ok = shoutu.compare_page_vs_api({}, {"TQQQ": 33.0})
    assert ok is False
    assert rows[0]["status"] == "page_missing"


def test_compare_rows_are_sorted_by_symbol():
    rows, _ = shoutu.compare_page_vs_api(
        {"TQQQ": 1.0, "CONL": 1.0}, {"TQQQ": 1.0, "CONL": 1.0})
    assert [r["symbol"] for r in rows] == ["CONL", "TQQQ"]
