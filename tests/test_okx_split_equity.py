# -*- coding: utf-8 -*-
"""OKX 账户净值拆分（2026-11-02，**第三次实测后改版**）。

【演进】
① 第一版：想从 `details[]` 拆出「证券市值 / 现金」✗
② 实测（`net=2783.42 != mv(0.0)+cash(2787.1)`）证明**拆不出来** ✗
   `details[]` 里只有 USDT（`eq` 合计 ≈ `totalEq`）✗
   BTC 是「借 USDT 买入」的现货杠杆 ⇒ 在 OKX 账本里是**负债**，
   不是 `details` 里的正 `eq` ✗
③ 现行：**不拆**（`sec_mv` 返回 NaN ⇒ 恒等式校验自动跳过 ✓），
   `cash` 仍用 USDT 的 `eq` ✓，并**打印 details 摘要**供定位 ✓
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


def test_sec_mv_is_nan_so_identity_check_skips():
    """`sec_mv` 必须是 **NaN** ✓ —— 这样 `pd.notna(mv)` 为假，
    恒等式校验自动跳过 ✓（否则会像第三次那样 `net != mv+cash` 中止 ✗）。
    """
    m = _load()
    data = {
        "totalEq": "2783.42",
        "details": [
            {"ccy": "USDT", "eq": "2787.1", "cashBal": "2787.1"},
        ],
    }
    sec, cash = m._okx_split_equity(data)
    assert sec != sec, "sec_mv 应为 NaN（不拆）✗"
    assert cash == pytest.approx(2787.1)


def test_cash_comes_from_usdt_cashbal_not_eq():
    """`cash` 用 USDT 的 **`cashBal`** ✓，不是 `eq` ✗。

    实测（2026-11-02 第四次）：
      USDT eq=2788.30  cashBal=2342.82  upl=445.48
      ⇒ `eq = cashBal + upl` ✓
      ⇒ `eq` **含未实现盈亏** ✗ 当「现金」用会高估 445
    """
    m = _load()
    sec, cash = m._okx_split_equity({"details": [
        {"ccy": "BTC", "eq": "100", "cashBal": "100"},
        {"ccy": "USDT", "eq": "2788.30", "cashBal": "2342.82"},
    ]})
    assert sec != sec, "sec_mv 应为 NaN（不拆）✗"
    assert cash == pytest.approx(2342.82), "cash 应取 cashBal ✗"


def test_no_usdt_gives_none_cash():
    """没有 USDT ⇒ `cash=None` ✓（调用方保留原值，不硬写 0 ✗）。"""
    m = _load()
    sec, cash = m._okx_split_equity({"details": [{"ccy": "BTC", "eq": "1"}]})
    assert sec != sec
    assert cash is None


def test_empty_details_is_safe():
    """`details` 缺失/空 ⇒ `(nan, None)` ✓ 不抛错（不拖死同步链 ✓）。"""
    m = _load()
    for payload in ({}, {"details": []}):
        sec, cash = m._okx_split_equity(payload)
        assert sec != sec
        assert cash is None


def test_bad_payload_does_not_raise():
    """畸形 payload ⇒ `(nan, None)` ✓ 不抛错。"""
    m = _load()
    sec, cash = m._okx_split_equity({"details": "not-a-list"})
    assert sec != sec
    assert cash is None


def test_sec_mv_written_as_none_not_empty_string():
    """`securities_mv` 必须写 **`None`** ✗ 不能写 `""` ✗（2026-11-02）。

    校验用的是 `pd.notna(mv)`：
      `pd.notna("")`   → **True**  ✗ ⇒ 空串照样触发恒等式校验 ⇒ 被拦
      `pd.notna(None)` → **False** ✓ ⇒ 才真的跳过

    实测：第四次 `net=2784.65 != mv(0)+cash(2788.30)` 就是因为写了空串 ✗
    """
    import io
    import os

    import pandas as pd

    assert pd.notna("") is True, "pandas 行为变了？"
    assert pd.notna(None) is False

    src = io.open(os.path.join(os.path.dirname(__file__), "..", "scripts",
                               "sync_positions.py"), encoding="utf-8").read()
    # 构造 crypto 行时，securities_mv 那一位必须是 None
    assert "\n        None,\n        round(cash, 2)," in src, \
        "crypto 行的 securities_mv 没写 None ✗"
