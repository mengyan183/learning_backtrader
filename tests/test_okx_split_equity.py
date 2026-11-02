# -*- coding: utf-8 -*-
"""OKX 账户净值拆分（2026-11-02）。

问题：`sync_okx` 原来把 `securities_mv` 写死**空串** ✗、`cash` 常为 NaN ✗
⇒ 简报里「加密净值 2,792 vs BTC 市值 2,344，差 448」永远解释不了 ✗

修法：从 `/account/balance` 的 `details[]` 里拆 ✓
  证券市值 = 非 USDT 币种 `eq` 之和
  现金     = USDT 的 `eq`
"""
import importlib.util
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))


def _load():
    p = os.path.join(os.path.dirname(__file__), "..", "scripts",
                     "sync_positions.py")
    spec = importlib.util.spec_from_file_location("sp", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_split_equity_typical():
    """BTC 2344 + USDT 448 = totalEq 2792 ✓（正是简报里那个 448 差额）。"""
    m = _load()
    data = {
        "totalEq": "2792.3",
        "details": [
            {"ccy": "USDT", "eq": "448.3", "cashBal": "448.3"},
            {"ccy": "BTC", "eq": "2344.0", "cashBal": "0.0299"},
        ],
    }
    sec, cash = m._okx_split_equity(data)
    assert sec == pytest.approx(2344.0)
    assert cash == pytest.approx(448.3)
    assert sec + cash == pytest.approx(2792.3, abs=0.01), \
        "拆分后相加应等于 totalEq ✗"


def test_split_equity_no_usdt():
    """没有 USDT 余额 ⇒ cash 返回 None ✓（调用方保留原值，不硬写 0 ✗）。"""
    m = _load()
    sec, cash = m._okx_split_equity(
        {"details": [{"ccy": "BTC", "eq": "1000"}]})
    assert sec == pytest.approx(1000.0)
    assert cash is None


def test_split_equity_empty_details():
    """`details` 缺失/空 ⇒ `(0.0, None)` ✓ 不抛错（不拖死同步链 ✓）。"""
    m = _load()
    assert m._okx_split_equity({}) == (0.0, None)
    assert m._okx_split_equity({"details": []}) == (0.0, None)


def test_split_equity_bad_payload_returns_nan():
    """畸形 payload ⇒ `(nan, None)` ✓（调用方据此留空，不写假数 ✗）。"""
    m = _load()
    sec, cash = m._okx_split_equity({"details": "not-a-list"})
    assert sec != sec, "畸形数据应返回 NaN ✗"
    assert cash is None
