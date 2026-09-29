# -*- coding: utf-8 -*-
"""守猪待兔**服务端历史**的解析与落盘测试（2026-09-24 spec 的 Step A / A1）。

只测**可离线复现**的部分（解析、幂等、排序、空历史）。
真正驱动浏览器的编排在 `scripts/fetch_shoutu_history.py`（依赖 `bsk`）。

**为什么这块必须锁住**：这是**唯一**能拿到守猪待兔历史的通道（官方文档只有实时端点）。
解析口径错 ⇒ 625 天的历史被静默写坏 ⇒ 而 Step B 的量化结论**全部**建立在它上面。
"""
import os

import pandas as pd
import pytest

from fg_system import config
from fg_system.data import loader, shoutu


def _payload(rows, status=1):
    return {"status": status, "msg": "成功", "data": rows}


_ROWS = [
    {"score": -75, "price": "35.220", "date": "2024-08-16"},
    {"score": -69, "price": "34.930", "date": "2024-08-19"},
]


# ================================================================ 解析

def test_parse_history_payload_basic():
    df = shoutu.parse_history_payload(_payload(_ROWS), "CONL")
    assert list(df.columns) == shoutu.HISTORY_COLUMNS
    assert len(df) == 2
    assert list(df["symbol"]) == ["CONL", "CONL"]
    assert list(df["score"]) == [-75.0, -69.0]
    assert df["price"].iloc[0] == pytest.approx(35.220)
    assert df["date"].iloc[0] == pd.Timestamp("2024-08-16")


def test_parse_history_payload_empty_data_is_not_an_error():
    """**关键**：`data: []` 表示「服务端对该标的**没有**历史」（实测 AXTX / CRCG）。

    必须返回**空表**而不是抛错 —— 抛错会让整次抓取失败，
    掩盖"其余标的是好的"这一事实。调用方据此**打印告警、不写入**。
    """
    df = shoutu.parse_history_payload(_payload([]), "AXTX")
    assert df.empty
    assert list(df.columns) == shoutu.HISTORY_COLUMNS


def test_parse_history_payload_raises_on_status_error():
    with pytest.raises(shoutu.ShoutuError, match="status"):
        shoutu.parse_history_payload(_payload(_ROWS, status=2), "CONL")


def test_parse_history_payload_raises_on_bad_score():
    """score 非数值 ⇒ 报错（**不静默变 NaN**，同 `parse_scan_result` 的原则）。"""
    bad = [{"score": "**", "price": "1", "date": "2024-08-16"}]
    with pytest.raises(shoutu.ShoutuError):
        shoutu.parse_history_payload(_payload(bad), "CONL")
    with pytest.raises(shoutu.ShoutuError):
        shoutu.parse_history_payload(_payload([{"price": "1", "date": "2024-08-16"}]), "CONL")


def test_parse_history_payload_raises_on_bad_date():
    bad = [{"score": 1, "price": "1", "date": "not-a-date"}]
    with pytest.raises(shoutu.ShoutuError):
        shoutu.parse_history_payload(_payload(bad), "CONL")


def test_parse_history_payload_raises_on_out_of_range_score():
    """越界即报错 —— 口径变了必须响，不得静默截断（同 `shoutu_to_system_scale`）。"""
    for bad_score in (-101, 101):
        rows = [{"score": bad_score, "price": "1", "date": "2024-08-16"}]
        with pytest.raises(shoutu.ShoutuError, match="越界"):
            shoutu.parse_history_payload(_payload(rows), "CONL")


def test_parse_history_payload_price_unparsable_becomes_nan():
    """**price 是参考量、不是信号** ⇒ 不可解析时置 NaN，**不报错**
    （价格源抖动不该把整次抓取搞挂）。"""
    rows = [{"score": 5, "price": "N/A", "date": "2024-08-16"},
            {"score": 6, "date": "2024-08-19"}]           # 连 price 都没有
    df = shoutu.parse_history_payload(_payload(rows), "CONL")
    assert len(df) == 2
    assert df["price"].isna().all()


def test_parse_history_payload_unknown_symbol_raises():
    """白名单：防把历史写到不在 `SHOUTU_SYMBOLS` 的代码上。"""
    with pytest.raises(shoutu.ShoutuError, match="未知标的"):
        shoutu.parse_history_payload(_payload(_ROWS), "AAPL")


# ================================================================ 落盘

def test_record_history_creates_file_and_sorts(tmp_path):
    p = str(tmp_path / "h.csv")
    df = shoutu.parse_history_payload(_payload(_ROWS), "CONL")
    out = shoutu.record_history(df, p)
    assert os.path.exists(p)
    assert out["date"].is_monotonic_increasing
    assert len(out) == 2


def test_record_history_is_idempotent(tmp_path):
    """同 `(date, symbol)` 重复抓取**覆盖**而非追加（抓取会重跑，不能越抓越多）。"""
    p = str(tmp_path / "h.csv")
    df = shoutu.parse_history_payload(_payload(_ROWS), "CONL")
    shoutu.record_history(df, p)
    out = shoutu.record_history(df, p)
    assert len(out) == 2


def test_record_history_overwrites_on_correction(tmp_path):
    """更正取**后写入的值**（服务端修订历史时应生效）。"""
    p = str(tmp_path / "h.csv")
    shoutu.record_history(shoutu.parse_history_payload(_payload(_ROWS), "CONL"), p)
    fixed = shoutu.parse_history_payload(
        _payload([{"score": -70, "price": "35.220", "date": "2024-08-16"}]), "CONL")
    out = shoutu.record_history(fixed, p)
    row = out[out["date"] == pd.Timestamp("2024-08-16")]
    assert row["score"].iloc[0] == -70.0


def test_record_history_keeps_multiple_symbols(tmp_path):
    p = str(tmp_path / "h.csv")
    shoutu.record_history(shoutu.parse_history_payload(_payload(_ROWS), "CONL"), p)
    shoutu.record_history(shoutu.parse_history_payload(_payload(_ROWS), "TQQQ"), p)
    out = shoutu.record_history(pd.DataFrame(columns=shoutu.HISTORY_COLUMNS), p)
    assert set(out["symbol"]) == {"CONL", "TQQQ"}
    assert len(out) == 4


def test_record_history_empty_is_noop(tmp_path):
    """空表（AXTX / CRCG）**不得**创建文件、不得报错。"""
    p = str(tmp_path / "h.csv")
    out = shoutu.record_history(shoutu.parse_history_payload(_payload([]), "AXTX"), p)
    assert out.empty
    assert not os.path.exists(p)


# ================================================================ 读取

def test_load_shoutu_history_missing_file_returns_empty(tmp_path):
    assert loader.load_shoutu_history(str(tmp_path / "nope.csv")).empty


def test_load_shoutu_history_roundtrip(tmp_path):
    p = str(tmp_path / "h.csv")
    shoutu.record_history(shoutu.parse_history_payload(_payload(_ROWS), "CONL"), p)
    out = loader.load_shoutu_history(p)
    assert len(out) == 2
    assert out["score"].iloc[0] == -75.0


# ================================================================ 脚本层守卫（静态）

def _script_module():
    import importlib
    import sys
    d = os.path.join(config.ROOT, "scripts")
    if d not in sys.path:
        sys.path.insert(0, d)
    return importlib.import_module("fetch_shoutu_history")


def test_script_only_records_the_history_endpoint():
    """**守卫**：脚本必须**只记录** `stock_emotion/history` 的响应。

    这条是**安全约束**，不是风格偏好：同一次挂钩会经过
    `/api/invest/license/info`，而它的响应里含**明文凭据**
    （会员 token、钉钉机器人密钥）。不过滤就会把凭据写进日志/文件。
    """
    import ast
    p = os.path.join(config.ROOT, "scripts", "fetch_shoutu_history.py")
    src = open(p, encoding="utf-8").read()
    assert "stock_emotion/history" in src, "脚本没有按历史端点过滤"

    # ⚠️ **只查"整文件里出现过 MARK"是不够的** —— 必须钉住**过滤语句本身**。
    # 反例（"加个调试开关临时看看"是极常见的开发动作）：
    #     if(s.indexOf(MARK)<0 && !window.__shoutu_debug)return;
    # 这样改之后：整文件仍含 MARK ⇒ 上面那条断言照样绿；禁词扫描也不受影响；
    # 而 `rec` 是 XHR 与 fetch **两个分支共用的单点** ⇒ 两个分支同时失效，
    # 凭据（license/info 的明文 token）会进缓冲。**静默通过 = 最坏的失败模式。**
    guard = "if(s.indexOf(MARK)<0)return;"
    assert guard in src, \
        "过滤语句被改动（应原样为 %r）—— 安全约束可能已失效" % guard
    assert src.index(guard) < src.index("__shoutu_cap.push"), \
        "过滤语句必须出现在 push **之前**（先记录后过滤 = 凭据已经进缓冲了）"

    tree = ast.parse(src)

    called = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute):
                called.add(f.attr)
            elif isinstance(f, ast.Name):
                called.add(f.id)
    for need in ("parse_history_payload", "record_history"):
        assert need in called, "脚本没有调用 shoutu.%s（解析/落盘必须在库里）" % need

    # 禁词只查**非文档字符串**的字面量：脚本文档**必须**说明"为什么不能碰那些端点"
    # （那是这条安全约束的依据）。裸词匹配会把说明文字误判成违规，逼人删掉文档。
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            d = ast.get_docstring(node)
            if d:
                docs.add(d)
    lits = [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and n.value not in docs]
    for banned in ("license", "dd_token", "localStorage"):
        hits = [s for s in lits if banned in s]
        assert not hits, \
            "脚本的字面量里出现了不该碰的东西：%s → %s" % (banned, hits[:2])


def test_script_prints_fetch_timestamp():
    """**守卫**（spec §12 风险 6 / §10.2）：脚本必须打印**抓取时刻**。

    为什么必须：定时任务在 **06:30** 跑，而「**美股收盘前**抓会写入**未完成的最后
    一行**」—— 实测服务端后来修正了 6 行（TQQQ `78.17 → 77.095`、
    GDXU `130.71 → 120.85`）。日志里没有时刻，就无法事后判断某天的数据是在收盘前
    还是收盘后落的盘（**冬令时 / 夏令时会让 06:30 落错边**）。

    ⚠️ 断言刻意宽松：只要求「有可读时刻」+「`now` 可注入」——不锁死格式细节，
    避免以后调整措辞时误伤。
    """
    import datetime
    mod = _script_module()
    line = mod._now_stamp(datetime.datetime(2026, 9, 28, 6, 30, 0))
    assert "抓取时刻" in line
    assert "2026-09-28 06:30:00" in line
    # 不注入也必须能跑 —— 保证 `main()` 里那一行不会因缺参而抛错
    assert "抓取时刻" in mod._now_stamp()
