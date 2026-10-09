# 守猪待兔清仓线「全系统回放」（A1）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变生产输出的前提下，跑出「守猪待兔清仓线」4 条曲线（基准 + `+60` / `+80` / 不设清仓线）的组合级回放，产出**机制性证据 + 量级判断**。

**Architecture:** 三层分离 —— ① 给 `market_signal.market_target` / `pipeline.run_portfolio` / `pipeline.saturation_of` 等加**可选参数**（默认 `None` = 现行为，**逐位不变**）；② 新模块 `fg_system/shoutu_variants.py` 放变体表与 `variant_core_series()`（纯计算）；③ `scripts/analyze_shoutu_variants.py` 只做 I/O 编排与出表。

**Tech Stack:** Python 3.10、pandas、numpy、pytest、backtrader（仅既有回测，不新增用法）

**设计依据:** `docs/superpowers/specs/2026-09-24-shoutu-variants-replay-design.md`（已获用户确认）

**测试命令（本机）:** `py -3.10 -m pytest <path> -v`，**cwd 必须是仓库根**
**⚠️ 不要用裸 `python`** —— 系统 Python 3.14 缺 `backtrader`，会产生 3 个收集错误。

---

## 文件结构

| 文件 | 动作 | 职责 |
|---|---|---|
| `fg_system/signal/market_signal.py` | 改 | `market_target(..., core=None)` —— 可选覆盖五档 core |
| `fg_system/pipeline.py` | 改 | `run_portfolio(..., us_core=None)`；`saturation_of` / `shoutu_market_saturation` / `shoutu_core_series` 加 `edges` / `saturation` 参数 |
| `fg_system/shoutu_variants.py` | **新建** | `BASELINE` / `VARIANTS` / `shoutu_wide_from_long()` / `variant_core_series()`，纯计算、无 I/O |
| `scripts/analyze_shoutu_variants.py` | **新建** | 跑 4 变体 × 2 窗口 → 四张表 + 结论段 |
| `tests/test_shoutu_variants.py` | **新建** | 上面全部改动的单测 + **等价性红线** |
| `docs/trading-discipline.md` | 改 | §14.5 新增 A1 小节 + §13.6 O4 更新 |

**关键口径（来自 spec，不得改）**
- 变体注入点 = `run_portfolio` / `market_target`（**不是** `run()`：`run()` 的 `core_position` 是 v1 legacy）
- 熔断 / 极恐加仓**仍以市场指数为触发源**
- 双窗口：全历史 + 纯效应段（`2024-04-23` 起）
- **不排名、不挑最优**；回测**不作为**改规则的依据（第 13.1 / 13.2 / 13.0 条）

---

## Task 1: `market_target(..., core=None)`

**Files:**
- Modify: `fg_system/signal/market_signal.py:224-271`（`market_target`）
- Test: `tests/test_shoutu_variants.py`（新建）

- [ ] **Step 1: 写失败测试**

新建 `tests/test_shoutu_variants.py`：

```python
# -*- coding: utf-8 -*-
"""A1（守猪待兔清仓线全系统回放）的单元测试与等价性红线。

设计：docs/superpowers/specs/2026-09-24-shoutu-variants-replay-design.md
"""
import numpy as np
import pandas as pd
import pytest

from fg_system import config
from fg_system.signal import market_signal as ms


def test_market_target_core_override_replaces_market_core():
    """`core` 给定时替换五档结果（50.0 的默认 core 是 0.18，这里应变成 0.123）。"""
    out, _ = ms.market_target(50.0, 0.0, 1.0, ms.MarketState(market="us_equity"),
                              "us_equity", core=0.123)
    assert out.core_position == pytest.approx(0.123)


def test_market_target_core_none_is_identical_to_default():
    """等价性红线：不传 `core` 与传 `core=None` 逐位相同。"""
    a, _ = ms.market_target(50.0, 0.0, 1.0, ms.MarketState(market="us_equity"), "us_equity")
    b, _ = ms.market_target(50.0, 0.0, 1.0, ms.MarketState(market="us_equity"),
                            "us_equity", core=None)
    assert a == b


def test_market_target_core_nan_is_no_signal():
    """变体 core 为 NaN（warmup）⇒ 与「指数无效」同语义（core_position=None）。"""
    out, _ = ms.market_target(float("nan"), 0.0, 1.0, ms.MarketState(market="us_equity"),
                              "us_equity", core=float("nan"))
    assert out.core_position is None


def test_market_target_circuit_breaker_still_beats_variant_core():
    """⚠️ 熔断仍然生效：极贪触发时，变体 core 必须被 `full × 熔断底仓` 替换。"""
    out, _ = ms.market_target(config.EXTREME_GREED_TRIGGER, 0.0, 1.0,
                              ms.MarketState(market="us_equity"),
                              "us_equity", core=0.123)
    full = config.CORE_CAP * config.MARKET_CORE_RATIO["us_equity"] * 1.0
    assert out.core_position == pytest.approx(full * config.EXTREME_GREED_FLOOR)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `py -3.10 -m pytest tests/test_shoutu_variants.py -v`
Expected: FAIL —— `TypeError: market_target() got an unexpected keyword argument 'core'`

- [ ] **Step 3: 实现**

`fg_system/signal/market_signal.py` —— 把 `market_target` 的签名与开头几行改为：

```python
def market_target(index_value, drawdown, trend, state, market, date=None, prices=None,
                  core=None):
    """计算单市场的核心仓与极端状态，返回 (MarketOutput, 新 MarketState)。

    `core`（可选）：**替换**五档结果 `market_core(index_value, trend, market)`。
    用于「清仓线变体」的离线回放（A1）—— 变体只换五档 core 的**来源**，
    熔断 / 极恐加仓的**触发源仍是 `index_value`（市场指数）**，`full` 基准也不变。

    ⚠️ `core=None`（默认）时行为与改动前**逐位相同**（等价性红线：
    `tests/test_shoutu_variants.py`）。
    """
    state = _copy(state)
    note = ""
    extreme = False

    if core is None:
        core = market_core(index_value, trend, market)
    else:
        # 变体 core 的 NaN（warmup）与 `market_core` 的 None **同语义**
        core = None if _is_nan(core) else core
    if core is None:
        return (MarketOutput(market=market, core_position=None, drawdown=drawdown,
                             trend=trend, trend_blocked=(trend < 1.0),
                             extreme_fear=False, extreme=False, layer_caps={},
                             note="指数无效"),
                state)
```

> ⚠️ **`core` 为 None 的分支必须保持原样**：原代码是
> `core = market_core(...)` 后 `if core is None:` —— `market_core` 在 **`trend` 为 NaN** 时
> 会返回 **NaN（不是 None）**，此时原逻辑**不**走「指数无效」分支。上面写法保留了这个行为
> （只有「显式传入的变体 core 为 NaN」才映射成 None）。

- [ ] **Step 4: 跑测试确认通过**

Run: `py -3.10 -m pytest tests/test_shoutu_variants.py -v`
Expected: 4 passed

- [ ] **Step 5: 跑回归确认生产路径未变**

Run: `py -3.10 -m pytest tests/signal tests/test_pipeline_crypto.py -q`
Expected: 全过（数量与改动前一致）

- [ ] **Step 6: 提交**

```bash
git add fg_system/signal/market_signal.py tests/test_shoutu_variants.py
git commit -m "feat(signal): market_target 支持可选 core 覆盖（A1 变体回放用，默认逐位不变） # user-confirmed-commit"
```

---

## Task 2: `run_portfolio(..., us_core=None)`

**Files:**
- Modify: `fg_system/pipeline.py:580-586`（签名与文档）+ `:613-614`（调用点）
- Test: `tests/test_shoutu_variants.py`（追加）

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_shoutu_variants.py`：

```python
from fg_system import pipeline


def _us_features(idx, fg_vals, trend=1.0):
    """最小 `us_equity` features（列名与 `run_equity_v2` 对齐）。

    ⚠️ 若与 `tests/test_pipeline_crypto.py` 的既有 helper 不一致，**以那份为准**
    （它是既有约定；本函数只是让本文件自包含）。
    """
    return pd.DataFrame({
        "fg_index": fg_vals, "zone": 2.0, "drawdown": 0.0,
        "core_position": 0.1, "ammo_position": 0.0, "target_position": 0.1,
        "trend": trend, "trend_blocked": trend < 1.0, "warmup": False,
    }, index=idx)


def _cr_features(idx, fg_vals, trend=1.0):
    return pd.DataFrame({
        "crypto_fg_index": fg_vals, "drawdown": 0.0, "trend": trend,
        "trend_blocked": trend < 1.0, "core_position": 0.1, "target_position": 0.1,
        "warmup": False,
    }, index=idx)


def _portfolio_inputs(n=40, fg=50.0):
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return _us_features(idx, [fg] * n), _cr_features(idx, [fg] * n)


def test_run_portfolio_us_core_none_is_identical_to_default():
    """等价性红线：不传 `us_core` 与传 `us_core=None` **逐位相同**。"""
    us, cr = _portfolio_inputs()
    a = pipeline.run_portfolio(us, cr, write=False)
    b = pipeline.run_portfolio(us, cr, write=False, us_core=None)
    pd.testing.assert_frame_equal(a, b)


def test_run_portfolio_us_core_override_reaches_us_core_column():
    """`us_core` 覆盖后，输出的 `us_core` 列等于传入序列。"""
    us, cr = _portfolio_inputs()
    override = pd.Series(0.05, index=us.index)
    out = pipeline.run_portfolio(us, cr, write=False, us_core=override)
    assert out["us_core"].dropna().eq(0.05).all()


def test_run_portfolio_us_core_override_does_not_touch_crypto():
    """覆盖**只作用于 us_equity**，加密核心仓不受影响。"""
    us, cr = _portfolio_inputs()
    base = pipeline.run_portfolio(us, cr, write=False)
    over = pipeline.run_portfolio(us, cr, write=False,
                                 us_core=pd.Series(0.05, index=us.index))
    pd.testing.assert_series_equal(base["crypto_core"], over["crypto_core"])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `py -3.10 -m pytest tests/test_shoutu_variants.py -v -k run_portfolio`
Expected: FAIL —— `TypeError: run_portfolio() got an unexpected keyword argument 'us_core'`

- [ ] **Step 3: 实现**

`fg_system/pipeline.py` —— 签名与文档：

```python
def run_portfolio(us_features, crypto_features, write=True, us_core=None):
    """组合级管道：把两个市场的核心仓与共享弹药池合成最终目标仓位（§7）。

    入参是两个市场的 features DataFrame（**未 shift**）。us_features 必须含
    `trend` / `trend_blocked` 列（由 `run_equity_v2` 产出）。

    `us_core`（可选）：**逐日替换** `us_equity` 的五档核心仓（用于 A1 的
    「守猪待兔清仓线变体」离线回放）。缺失的日期按「指数无效」处理。
    **只作用于 `us_equity`** —— 加密路径完全不受影响。

    ⚠️ `us_core=None`（默认）时行为与改动前**逐位相同**（等价性红线：
    `tests/test_shoutu_variants.py`）。

    返回 portfolio_features（target_position 已 shift(1)）。
    """
```

调用点（原 `:613-614`）改为：

```python
        core_us = None if us_core is None else us_core.reindex(joined.index)[dt]
        out_us, us_state = ms_mod.market_target(
            idx_us, dd_us, tr_us, us_state, "us_equity", date_str, core=core_us)
```

并在 `joined = us.join(cr, ...)` **之后**加一行（只做一次，不在循环里）：

```python
    if us_core is not None:
        us_core = pd.Series(us_core).reindex(joined.index)
```

> ⚠️ `joined = us.join(cr, how="left", ...)` ⇒ `joined.index == us.index`
> （`how="left"` 保留左表索引），所以 `us_core`（按 `us_features.index` 构造）
> 与 `joined.index` **逐日对齐**，不会有缺日。

- [ ] **Step 4: 跑测试确认通过**

Run: `py -3.10 -m pytest tests/test_shoutu_variants.py -v`
Expected: 7 passed

- [ ] **Step 5: 跑回归**

Run: `py -3.10 -m pytest tests/test_pipeline_crypto.py tests/test_shoutu_cores.py -q`
Expected: 全过

- [ ] **Step 6: 提交**

```bash
git add fg_system/pipeline.py tests/test_shoutu_variants.py
git commit -m "feat(pipeline): run_portfolio 支持可选 us_core 覆盖（A1 变体回放用，默认逐位不变） # user-confirmed-commit"
```

---

## Task 3: `saturation_of` / `shoutu_market_saturation` / `shoutu_core_series` 参数化

**Files:**
- Modify: `fg_system/pipeline.py:437-449`（`saturation_of`）、`:452-468`（`shoutu_market_saturation`）、`:471-482`（`shoutu_core_series`）
- Test: `tests/test_shoutu_variants.py`（追加）

- [ ] **Step 1: 写失败测试**

```python
def test_saturation_of_default_equals_explicit_global_tables():
    """等价性红线：默认参数 == 显式传全局表。"""
    vals = [0.0, 20.0, 39.9, 60.0, 80.0, 99.9]
    a = pipeline.saturation_of(vals)
    b = pipeline.saturation_of(vals, edges=config.ZONE_EDGES,
                              saturation=config.ZONE_SATURATION)
    assert list(a) == list(b)


def test_saturation_of_variant_tables_land_on_expected_zones():
    """V2 边界：守猪待兔 +60→系统 80 落档 3（0.25）；+80→系统 90 落档 4（0.00）。"""
    got = pipeline.saturation_of([80.0, 90.0], edges=[20.0, 40.0, 60.0, 90.0],
                                saturation=[1.00, 0.75, 0.50, 0.25, 0.00])
    assert list(got) == [0.25, 0.00]


def test_saturation_of_v3_never_clears():
    """V3：末档留 25% 底仓 ⇒ 任何值都不给 0。"""
    got = pipeline.saturation_of([0.0, 50.0, 80.0, 100.0],
                                edges=[20.0, 40.0, 60.0, 80.0],
                                saturation=[1.00, 0.75, 0.50, 0.25, 0.25])
    assert min(got) == pytest.approx(0.25)


def test_saturation_of_rejects_table_length_mismatch():
    """档数必须 = 边界数 + 1。"""
    with pytest.raises(ValueError):
        pipeline.saturation_of([50.0], edges=[20.0, 40.0],
                               saturation=[1.0, 0.5, 0.0, 0.0])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `py -3.10 -m pytest tests/test_shoutu_variants.py -v -k saturation`
Expected: FAIL —— `TypeError: saturation_of() got an unexpected keyword argument 'edges'`

- [ ] **Step 3: 实现**

`fg_system/pipeline.py` —— `saturation_of` 整体替换为：

```python
def saturation_of(values, edges=None, saturation=None):
    """指数值 → 档位饱和度（向量化）。

    **必须与 `ms_mod.zone_of` 等价**：`zone_of` 返回**第一个**满足 `idx < edge`
    的档位（边界下闭，`20` 属于档 1）。等价于
    `searchsorted(edges, idx, side="right")` —— 用 `side="left"` 会在
    **恰好等于边界值**时差一档（`20` 会落进档 0 而非档 1），
    使仓位系数整体偏移。等价性由
    `tests/test_shoutu_cores.py::test_saturation_matches_zone_of` 常驻守卫。

    `edges` / `saturation`（可选）：**替换**全局 `config.ZONE_EDGES` /
    `config.ZONE_SATURATION`，用于 A1 的「守猪待兔清仓线变体」
    （例如把末档边界 80 抬到 90、或让末档留 25% 底仓）。
    ⚠️ `None`（默认）时读全局 `config` ⇒ **逐位不变**（等价性红线：
    `tests/test_shoutu_variants.py`）。**不要**改全局 config —— 它被市场指数
    与加密路径共享（`ms_mod.zone_of` / `market_core`）。
    """
    edges = config.ZONE_EDGES if edges is None else list(edges)
    table = config.ZONE_SATURATION if saturation is None else list(saturation)
    if len(table) != len(edges) + 1:
        raise ValueError(
            "saturation 长度必须 = len(edges) + 1（档数 = 边界数 + 1）："
            "len(saturation)=%d, len(edges)=%d" % (len(table), len(edges)))
    zones = np.searchsorted(np.asarray(edges, dtype=float),
                            np.asarray(values, dtype=float), side="right")
    return np.asarray(table, dtype=float)[zones]
```

`shoutu_market_saturation` —— 签名加两个参数，内部那一行改为：

```python
def shoutu_market_saturation(us_features, weights, shoutu_wide=None, symbols=None,
                             edges=None, saturation=None):
    """（docstring 保持原文，末尾追加：）

    `edges` / `saturation`：透传给 `saturation_of`（A1 变体用）；`None` = 全局 config。
    """
    symbols = list(symbols) if symbols else list(config.SYMBOLS)
    idx = shoutu_symbol_index(us_features, shoutu_wide, symbols)
    sat = pd.DataFrame({s: saturation_of(idx[s].values, edges, saturation)
                        for s in symbols},
                       index=us_features.index)
    w = weights.reindex(us_features.index).ffill()
    return (sat * w).sum(axis=1, min_count=len(symbols))
```

`shoutu_core_series` —— 签名加两个参数：

```python
def shoutu_core_series(us_features, weights, shoutu_wide=None, symbols=None,
                       edges=None, saturation=None):
    """（docstring 保持原文，末尾追加：）

    `edges` / `saturation`：透传给 `shoutu_market_saturation`（A1 变体用）；
    `None` = 全局 config ⇒ 逐位不变。
    """
    sat = shoutu_market_saturation(us_features, weights, shoutu_wide, symbols,
                                  edges, saturation)
    trend = us_features["trend"].reindex(us_features.index).fillna(1.0)
    return (config.CORE_CAP * config.MARKET_CORE_RATIO["us_equity"]
            * sat * trend)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `py -3.10 -m pytest tests/test_shoutu_variants.py tests/test_shoutu_cores.py -v`
Expected: 全过（新增 4 条 + 既有 `test_saturation_matches_zone_of` 等）

- [ ] **Step 5: 提交**

```bash
git add fg_system/pipeline.py tests/test_shoutu_variants.py
git commit -m "feat(pipeline): saturation_of/shoutu_core_series 支持变体档位表（默认读全局 config，逐位不变） # user-confirmed-commit"
```

---

## Task 4: 新模块 `fg_system/shoutu_variants.py`

**Files:**
- Create: `fg_system/shoutu_variants.py`
- Test: `tests/test_shoutu_variants.py`（追加）

- [ ] **Step 1: 写失败测试**

```python
from fg_system import shoutu_variants


def _hist_long(n=30):
    """构造一条守猪待兔长表：三个主标的，值在 0~100 之间来回。"""
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    rows = []
    for s in config.SYMBOLS:
        for i, d in enumerate(idx):
            rows.append({"date": d, "symbol": s, "score": 70.0 if i % 2 else 10.0,
                         "price": 100.0 + i})
    return pd.DataFrame(rows)


def test_variants_tables_have_valid_lengths():
    """档数必须 = 边界数 + 1（先验表的自检）。"""
    for key, v in shoutu_variants.VARIANTS.items():
        assert len(v["saturation"]) == len(v["edges"]) + 1, key


def test_v1_matches_existing_shoutu_core_series():
    """⚠️ 构造一致性：V1（现状表）必须与现成 `shoutu_core_series(...)` 逐位相同。"""
    us = _us_features(pd.date_range("2024-01-01", periods=30, freq="B"), [50.0] * 30)
    w = pd.DataFrame(1.0 / 3.0, index=us.index, columns=config.SYMBOLS)
    hist = _hist_long()
    wide = shoutu_variants.shoutu_wide_from_long(hist)
    got = shoutu_variants.variant_core_series(us, w, hist, "V1")
    exp = pipeline.shoutu_core_series(us, w, shoutu_wide=wide)
    pd.testing.assert_series_equal(got, exp)


def test_v3_never_clears_while_v1_does():
    """V3（末档 25%）在档位 4 的日子 core > 0，而 V1 为 0。"""
    idx = pd.date_range("2024-01-01", periods=30, freq="B")
    us = _us_features(idx, [50.0] * 30)
    w = pd.DataFrame(1.0 / 3.0, index=idx, columns=config.SYMBOLS)
    hist = _hist_long()
    v1 = shoutu_variants.variant_core_series(us, w, hist, "V1")
    v3 = shoutu_variants.variant_core_series(us, w, hist, "V3")
    assert (v1 == 0.0).any(), "V1 应当出现清仓日（守猪待兔 >= +60）"
    assert (v3 > 0.0).all(), "V3 从不清仓"


def test_variant_core_requires_trend_column():
    idx = pd.date_range("2024-01-01", periods=10, freq="B")
    us = _us_features(idx, [50.0] * 10).drop(columns=["trend"])
    with pytest.raises(ValueError):
        shoutu_variants.variant_core_series(us, None, _hist_long(), "V1")


def test_variant_core_rejects_unknown_variant_and_empty_history():
    idx = pd.date_range("2024-01-01", periods=10, freq="B")
    us = _us_features(idx, [50.0] * 10)
    with pytest.raises(KeyError):
        shoutu_variants.variant_core_series(us, None, _hist_long(), "V9")
    with pytest.raises(ValueError):
        shoutu_variants.variant_core_series(us, None, pd.DataFrame(), "V1")


def test_shoutu_wide_from_long_rejects_no_main_symbols():
    """主样本零覆盖 ⇒ 抛错（**不得静默回退成基准**）。"""
    other = pd.DataFrame({"date": [pd.Timestamp("2024-01-02")], "symbol": ["CONL"],
                          "score": [10.0], "price": [1.0]})
    with pytest.raises(ValueError):
        shoutu_variants.shoutu_wide_from_long(other)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `py -3.10 -m pytest tests/test_shoutu_variants.py -v -k "variant or wide"`
Expected: FAIL —— `ModuleNotFoundError: No module named 'fg_system.shoutu_variants'`

- [ ] **Step 3: 实现**

新建 `fg_system/shoutu_variants.py`：

```python
# -*- coding: utf-8 -*-
"""守猪待兔「清仓线」变体的定义与 core 序列计算（A1）。

设计：docs/superpowers/specs/2026-09-24-shoutu-variants-replay-design.md

**本模块只做纯计算**：不读文件、不打印、不做 I/O。
编排（读数据、跑回放、出表）在 `scripts/analyze_shoutu_variants.py`。

⚠️ 变体表是**先验定义**，不是从回测里搜出来的（第 8 条 / 第 13.1 条）。
"""
import pandas as pd

from fg_system import config, pipeline

# 基准（市场指数口径）的标识。它**不走本模块**（core=None），
# 只是给编排层一个统一的枚举值，避免在脚本里散落字符串。
BASELINE = "B0"

# 三个守猪待兔变体。`edges` / `saturation` 都是**系统口径（0~100）** ——
# 守猪待兔原值 → 系统口径的映射是 `(x + 100) / 2`（`loader.shoutu_to_system_scale`）。
#
# 先验推导（第 8 条：不是"试出来的"）：
#   V1 = 现状规则（守猪待兔 +60 ⇒ 系统 80 ⇒ 末档 sat 0.00 = 清仓）
#   V2 = 清仓线抬到守猪待兔 +80 ⇒ 系统 90 ⇒ **只把末档边界**从 80 挪到 90，
#        使 +60 ~ +80（系统 80 ~ 90）落在 sat 0.25（贪婪档）而不是 0.00
#   V3 = 不设清仓线 ⇒ **复用系统已有**的 `ZONE_SATURATION[3] = 0.25` 作末档
#        （与加密「减至 25% 底仓（不清仓——避免完全踏空后续反弹）」同语义）
#        ⇒ **不新造参数**（第 4B.6 条）
VARIANTS = {
    "V1": {"label": "守猪待兔 +60 清仓（现状）",
           "edges": [20.0, 40.0, 60.0, 80.0],
           "saturation": [1.00, 0.75, 0.50, 0.25, 0.00]},
    "V2": {"label": "守猪待兔 +80 才清仓",
           "edges": [20.0, 40.0, 60.0, 90.0],
           "saturation": [1.00, 0.75, 0.50, 0.25, 0.00]},
    "V3": {"label": "守猪待兔 不设清仓线（末档留 25% 底仓）",
           "edges": [20.0, 40.0, 60.0, 80.0],
           "saturation": [1.00, 0.75, 0.50, 0.25, 0.25]},
}

# 编排层要跑的**全部**变体键（含基准），顺序固定（基准在最前）。
VARIANT_KEYS = (BASELINE,) + tuple(VARIANTS)


def shoutu_wide_from_long(hist, symbols=None):
    """守猪待兔**长表** → 宽表（index = date，columns = symbol，值 = `score`）。

    `hist`：`loader.load_shoutu_history()` 的输出（列 `date,symbol,score,price`）。

    ⚠️ `hist` 为空、或**主样本三个标的一个都没有** ⇒ **抛错**。
    **不得**静默回退成基准 —— 那会把「变体无效应」伪装成「变体无差异」
    （spec §5.1）。
    """
    symbols = list(symbols) if symbols else list(config.SYMBOLS)
    if hist is None or hist.empty:
        raise ValueError("守猪待兔历史为空 —— 无法构造变体 core（不得静默回退成基准）")
    sub = hist[hist["symbol"].isin(symbols)]
    if sub.empty:
        raise ValueError(
            "守猪待兔历史里没有任何主样本标的 %s —— 无法构造变体 core" % (symbols,))
    return sub.pivot(index="date", columns="symbol", values="score").sort_index()


def variant_core_series(us_features, weights, hist, variant, symbols=None):
    """某个变体口径下的 `us_equity` 核心仓序列（**未 shift**）。

    `= CORE_CAP × MARKET_CORE_RATIO["us_equity"] × Σ_i(sat_i(edges_v, sat_v) · w_i) × trend`

    ⚠️ **必须复用** `pipeline.shoutu_symbol_index` / `pipeline.saturation_of` /
    `pipeline.risk_weight_series` —— **不得**在此重写档位查找或加权逻辑
    （第 12.26 条⑤：两套写法 = 「分析里的规则 ≠ 生产的规则」）。

    `us_features` **必须含 `trend` 列**（由 `run_equity_v2` 产出）；缺列 ⇒ 抛错。
    """
    if variant not in VARIANTS:
        raise KeyError("未知变体 %r；可选：%s" % (variant, tuple(VARIANTS)))
    if "trend" not in us_features.columns:
        raise ValueError("us_features 缺 trend 列（应由 pipeline.run_equity_v2 产出）")
    spec = VARIANTS[variant]
    wide = shoutu_wide_from_long(hist, symbols)
    return pipeline.shoutu_core_series(
        us_features, weights, shoutu_wide=wide, symbols=symbols,
        edges=spec["edges"], saturation=spec["saturation"])
```

> ⚠️ `test_variant_core_requires_trend_column` / `..._rejects_unknown_variant...` 里
> 传 `weights=None`：因为这两个分支都在**用到 weights 之前**就抛错。若实现顺序调整导致
> `weights=None` 先崩，请把断言改成「传合法 weights」，**不要**放宽断言。

- [ ] **Step 4: 跑测试确认通过**

Run: `py -3.10 -m pytest tests/test_shoutu_variants.py -v`
Expected: 13 passed

- [ ] **Step 5: 提交**

```bash
git add fg_system/shoutu_variants.py tests/test_shoutu_variants.py
git commit -m "feat(shoutu): 新增 shoutu_variants（清仓线变体表 + variant_core_series） # user-confirmed-commit"
```

---

## Task 5: 编排脚本 `scripts/analyze_shoutu_variants.py`

**Files:**
- Create: `scripts/analyze_shoutu_variants.py`
- Test: `tests/test_shoutu_variants.py`（追加静态守卫）

- [ ] **Step 1: 写静态守卫测试（失败）**

```python
import ast
import os


def _script_src():
    p = os.path.join(config.ROOT, "scripts", "analyze_shoutu_variants.py")
    return open(p, encoding="utf-8").read()


def test_script_uses_library_functions():
    """计算必须走库层，不得在脚本里重写档位/指标逻辑。"""
    called = set()
    for node in ast.walk(ast.parse(_script_src())):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute):
                called.add(f.attr)
            elif isinstance(f, ast.Name):
                called.add(f.id)
    for need in ("variant_core_series", "run_portfolio", "performance_metrics",
                 "run_single"):
        assert need in called, "脚本没有调用 %s" % need


def test_script_does_not_hardcode_symbols_or_variant_tables():
    """标的与变体表都必须来自 config / shoutu_variants，不得硬编码。"""
    src = _script_src()
    lits = [n.value for n in ast.walk(ast.parse(src))
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    for sym in config.SHOUTU_SYMBOLS:
        assert not any(s == sym for s in lits), "脚本里硬编码了标的 %s" % sym
    assert not any(s in ("V1", "V2", "V3") for s in lits), \
        "变体键必须来自 shoutu_variants.VARIANTS，不得在脚本里硬编码"


def test_script_does_not_read_global_zone_tables():
    """变体档位表必须来自 shoutu_variants，不得在脚本里读/改全局 ZONE_*。"""
    src = _script_src()
    assert "ZONE_EDGES" not in src
    assert "ZONE_SATURATION" not in src
```

- [ ] **Step 2: 跑测试确认失败**

Run: `py -3.10 -m pytest tests/test_shoutu_variants.py -v -k script`
Expected: FAIL —— `FileNotFoundError`

- [ ] **Step 3: 实现脚本**

新建 `scripts/analyze_shoutu_variants.py`：

```python
# -*- coding: utf-8 -*-
"""守猪待兔「清仓线」全系统回放（A1）。

设计：docs/superpowers/specs/2026-09-24-shoutu-variants-replay-design.md

【结论纪律】第 13.1 / 13.2 / 13.0 条 ⇒ 本脚本只出**机制性证据 + 量级判断**：
**不排名、不挑「最优清仓线」**；**回测不作为改规则的依据**。

【两条口径（必须明示）】
  1. 熔断 / 极恐加仓仍以**市场指数**为触发源（变体只换五档 core 的来源）。
  2. 「高情绪区间」= `fg_index >= 80` 的交易日（**与变体无关** ⇒ 四条曲线同一批日子）。

【未建模】汇率 / 税 / 申购赎回 / 借券成本；`RANK_WINDOW=756` 未满 ⇒ 实际走 `fixed` 口径。

用法：
    py -3.10 scripts/analyze_shoutu_variants.py
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fg_system import config, pipeline, shoutu_variants   # noqa: E402
from fg_system.backtest import runner                     # noqa: E402
from fg_system.data import loader                         # noqa: E402

EFFECT_START = "2024-04-23"      # 守猪待兔历史起点 ⇒ 「纯效应段」起点（spec §6）
HIGH_MOOD_INDEX = 80.0           # 「高情绪」= 系统口径的极度贪婪档（spec §4.1）
SHOUTU_GREED_LINE = config.SHOUTU_GREED_LINE   # 守猪待兔贪婪线（+60），用于对照列


def _label(key):
    if key == shoutu_variants.BASELINE:
        return "基准（市场指数）"
    return shoutu_variants.VARIANTS[key]["label"]


def run_variant(key, us_v2, crypto, weights, hist, basket):
    """跑一个变体，返回 `{"strat", "returns", "base", "pf"}`。"""
    core = (None if key == shoutu_variants.BASELINE
            else shoutu_variants.variant_core_series(us_v2, weights, hist, key))
    pf = pipeline.run_portfolio(us_v2, crypto, write=False, us_core=core)
    # 与 `cli backtest-v2` 完全同口径（cli.py:395-396）
    base = (pf["us_core"].fillna(0.0) + pf["ammo_us"]).clip(upper=1.0).shift(1)
    f = us_v2.copy()
    f["target_position"] = base
    f["fg_index"] = us_v2["fg_index"]
    f["zone"] = us_v2["zone"]
    for col in ("open", "high", "low", "close"):
        f[col] = basket
    f["volume"] = 0.0
    strat, returns = runner.run_single(f, "BASKET")
    return {"strat": strat, "returns": returns, "base": base, "pf": pf}


def metrics_frame(results, start=None):
    """组合级指标表（复用 `runner.performance_metrics`）。"""
    rows = []
    for key, r in results.items():
        rets = r["returns"] if start is None else r["returns"].loc[start:]
        m = runner.performance_metrics(rets)
        rows.append({
            "变体": key, "说明": _label(key), "有效天": int(rets.dropna().shape[0]),
            "总收益%": 100 * m["total_return"], "年化%": 100 * m["annual_return"],
            "最大回撤%": 100 * m["max_drawdown"], "年化波动%": 100 * m["annual_vol"],
            "Sharpe": m["sharpe"], "Calmar": m["calmar"],
        })
    return pd.DataFrame(rows)


def flat_stats(core):
    """连续「core == 0」的统计：天数占比 / 平均长度 / 最长长度。"""
    valid = core.notna()
    zero = (core == 0.0) & valid
    n_valid = int(valid.sum())
    runs, cur = [], 0
    for flag in zero.tolist():
        if flag:
            cur += 1
        elif cur:
            runs.append(cur)
            cur = 0
    if cur:
        runs.append(cur)
    return {
        "zero_days": int(zero.sum()),
        "zero_share": (float(zero.sum()) / n_valid) if n_valid else float("nan"),
        "avg_flat_run": (sum(runs) / len(runs)) if runs else 0.0,
        "max_flat_run": max(runs) if runs else 0,
    }


def high_mood_masks(us_v2, hist):
    """`(H, Hs, overlap)`：高情绪（fg_index>=80）、守猪待兔高情绪（任一主标的 >=+60）。"""
    H = (us_v2["fg_index"] >= HIGH_MOOD_INDEX).reindex(us_v2.index).fillna(False)
    wide = shoutu_variants.shoutu_wide_from_long(hist)
    Hs = (wide >= SHOUTU_GREED_LINE).any(axis=1).reindex(us_v2.index).fillna(False)
    return H, Hs, int((H & Hs).sum())


def main():
    us_v2 = pipeline.run_equity_v2()
    crypto = pipeline.run_crypto(write=False)
    wide = pipeline.load_wide()
    weights = pipeline.risk_weight_series(wide)
    hist = loader.load_shoutu_history()
    basket = pipeline.basket_price_series(
        pipeline.weighted_basket_returns(wide, weights))

    results = {k: run_variant(k, us_v2, crypto, weights, hist, basket)
               for k in shoutu_variants.VARIANT_KEYS}

    pd.set_option("display.width", 240)
    print("数据：shoutu_history.csv（%s ~ %s）；主样本 %s"
          % (hist["date"].min().date(), hist["date"].max().date(),
             " / ".join(config.SYMBOLS)))
    print("权重口径：%s；组合级 = 加权篮子 + FgStrategy 单组合口径" % config.WEIGHTING)
    print()

    print("=== 表 1：组合级指标（窗口 = 全历史）===")
    print(metrics_frame(results).round(4).to_string(index=False))
    print()
    print("=== 表 1b：组合级指标（窗口 = 纯效应段，%s 起）===" % EFFECT_START)
    print(metrics_frame(results, EFFECT_START).round(4).to_string(index=False))
    print()

    H, Hs, overlap = high_mood_masks(us_v2, hist)
    print("=== 表 2：高情绪区间相对收益差（H = fg_index >= %.0f；共 %d 天）==="
          % (HIGH_MOOD_INDEX, int(H.sum())))
    base_rets = results[shoutu_variants.BASELINE]["returns"]
    rows = []
    for key, r in results.items():
        rets = r["returns"].reindex(base_rets.index)
        diff = (rets[H.reindex(rets.index).fillna(False)]
                - base_rets[H.reindex(base_rets.index).fillna(False)])
        rows.append({"变体": key, "说明": _label(key), "n_H": int(len(diff)),
                     "Σ差(pp)": 100 * diff.sum(), "均值差(pp)": 100 * diff.mean()})
    print(pd.DataFrame(rows).round(4).to_string(index=False))
    print("对照：守猪待兔高情绪日（任一主标的 >= %+.0f）= %d 天；与 H 重叠 %d 天"
          % (SHOUTU_GREED_LINE, int(Hs.sum()), overlap))
    print()

    print("=== 表 3：机制性指标（core == 0 的暴露与换手）===")
    rows = []
    for key, r in results.items():
        st = flat_stats(r["pf"]["us_core"])
        rows.append({"变体": key, "说明": _label(key),
                     "清仓天数": st["zero_days"], "清仓占比": st["zero_share"],
                     "平均连续清仓": st["avg_flat_run"], "最长连续清仓": st["max_flat_run"],
                     "操作次数": r["strat"].order_count,
                     "平均目标仓位": float(r["base"].dropna().mean())})
    print(pd.DataFrame(rows).round(4).to_string(index=False))
    print()

    print("=== 结论（量级 + 机制 + 纪律声明）===")
    print("1) 量级：见上表；两个窗口必须并列读（全历史含 2024-04-23 之前的稀释段）。")
    print("2) 机制：见「表 3」—— 清仓占比与最长连续清仓说明规则的实际离场暴露。")
    print("3) 纪律：**不排名、不挑最优**；**回测不作为改规则的依据**；")
    print("   改不改、改哪个值由**先验推导 + 真实操作复盘**（第 13.6 条 O4 / 第 8.4 条）决定。")
    print("   明示：熔断/极恐仍以市场指数为触发源；RANK_WINDOW=756 未满 ⇒ 实际走 fixed 口径；")
    print("   守猪待兔历史仅约 2.4 年 ⇒ 年化/Calmar 为量级估计；不做显著性检验。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

> ⚠️ **实施修正（2026-09-24）**：上文「与基准重合 / 稀释版」**只对 V1 成立**；
> V2/V3 改的是**档位表**，回退到市场指数后仍套用各自变体表 ⇒ 对 V2/V3 是
> 「变体表 + 市场指数回退」，**不是**效应稀释。详见 spec §6 实施修正注。

- [ ] **Step 4: 跑测试确认通过**

Run: `py -3.10 -m pytest tests/test_shoutu_variants.py -v`
Expected: 16 passed

- [ ] **Step 5: 跑脚本，人工核对合理性**

Run: `py -3.10 scripts/analyze_shoutu_variants.py`
Expected: 打出表 1 / 1b / 2 / 3 + 结论段。**人工核对**：
- 基准（B0）的组合级年化应与 `cli backtest-v2` 的组合级结果**同量级**（同口径）
- V1 的「清仓占比」应 **> 0**；V3 的应 **== 0**
- 表 2 里 V1 的「Σ差」应为**正**（清仓导致高情绪区间少赚）

- [ ] **Step 6: 提交**

```bash
git add scripts/analyze_shoutu_variants.py tests/test_shoutu_variants.py
git commit -m "feat(scripts): 守猪待兔清仓线全系统回放脚本（4 变体 × 2 窗口 + 四张表） # user-confirmed-commit"
```

---

## Task 6: 出数 + 回写文档

**Files:**
- Modify: `docs/trading-discipline.md`（§14.5 新增小节；§13.6 O4 更新）

- [ ] **Step 1: 跑全量测试**

Run: `py -3.10 -m pytest -q`
Expected: 全过（`716 + 新增数`）。**记录实际数字**。

- [ ] **Step 2: 跑脚本并留档**

Run: `py -3.10 scripts/analyze_shoutu_variants.py`
**把完整输出留档**（回写文档要用）。

- [ ] **Step 3: 回写 `docs/trading-discipline.md`**

在 §14.5 的 **Step B（C 阶段）结论**小节**之后**、`#### E2 的调度依据` **之前**，
新增同级小节（数字以 Step 2 实际输出为准）：

```markdown
#### Step A1 结论：守猪待兔清仓线「全系统回放」（2026-09-24）

**目的**：出「守猪待兔清仓线」4 条曲线（基准 + `+60` / `+80` / 不设清仓线）的
**机制性证据 + 量级判断**。设计见 `docs/superpowers/specs/2026-09-24-shoutu-variants-replay-design.md`。

**① 口径（必须与结果一起读）**

- 变体只换 `us_equity` **五档 core 的来源**；**熔断 / 极恐加仓仍以市场指数为触发源**。
- 双窗口并列：**全历史** + **纯效应段**（`2024-04-23` 起）。后者之前守猪待兔会经
  三级回退**与基准重合** ⇒ 全历史窗口的差异是**稀释版**。

> ⚠️ **实施修正（2026-09-24）**：上文「与基准重合 / 稀释版」**只对 V1 成立**；
> V2/V3 改的是**档位表**，回退到市场指数后仍套用各自变体表 ⇒ 对 V2/V3 是
> 「变体表 + 市场指数回退」，**不是**效应稀释。详见 spec §6 实施修正注。

- `RANK_WINDOW = 756` 未满 ⇒ 实际走 **`fixed`** 口径（裁决④）。
- 组合级 = **加权篮子 + `FgStrategy` 单组合口径**（本仓库既定做法）。
- 守猪待兔历史仅约 **2.4 年** ⇒ 年化 / Calmar 是**量级估计**；**不做显著性检验**。

**② 四张表**（<贴 Step 2 的表 1 / 1b / 2 / 3>）

**③ 结论纪律（第 13.1 / 13.2 / 13.0 条）**

**不排名、不挑「最优清仓线」**；**回测不作为改规则的依据**。
本步只回答「这条规则值得不值得继续研究 / 差异有多大」；
改不改、改哪个值由**先验推导 + 真实操作复盘**（§13.6 O4 / 第 8.4 条三振）决定。

**④ 可复现**

- 脚本：`scripts/analyze_shoutu_variants.py`（可重跑）
- 纯计算：`fg_system/shoutu_variants.py`（`VARIANTS` / `variant_core_series`）
- 生产零改动：新增参数默认 `None` ⇒ **逐位不变**（等价性红线在 `tests/test_shoutu_variants.py`）

**⑤ 给 A2 的前置知识（两处纠正）**

1. 变体注入点必须在 `run_portfolio` / `market_target` —— `run()` 的 `core_position`
   是 **v1 legacy**（`CORE_CAP × 饱和度`，无 RATIO / 趋势），注入它**传不到组合层**。
2. **不得**用逐 sleeve 回测做诊断 —— 每条 sleeve 的目标仅 ≈8.5% < `REBALANCE_THRESHOLD`
   ⇒ 几乎不交易（本仓库实测曾据此算出组合回撤 −72%，是错误口径）。
```

并把 §13.6 的 **O4** 行更新为（把 A1 结论并入「观察」列，**保持**触发条件为真实操作口径）：

```markdown
| O4 | 守猪待兔「早清仓」规则（贪恐 ≥ +60 ⇒ 目标仓位 0）在**上涨阶段**可能过早离场。C 阶段（事件研究）：主判据 +3.43pp / +7.56%、补充判据（120 日窗口）单次最大卖飞 +34.33% ≥ 20%。**A1（全系统回放）**：机制性事实见 §14.5「Step A1 结论」——规则一旦清仓**只在档位 0 才买回**，高情绪区间长期空仓；**但按第 13.1 / 13.2 / 13.0 条，回测结论不构成改规则的依据** | 第 14.5 条 Step B（2026-09-24）+ Step A1（2026-09-24） | **持续优化卖出操作准入门槛**：真实操作中出现「上涨阶段被清仓后明显卖飞」**≥ 3 次复盘质疑**（第 8.4 条）⇒ 才可动规则参数 |
```

- [ ] **Step 4: 提交**

```bash
git add docs/trading-discipline.md
git commit -m "docs(shoutu): Step A1 结论 —— 守猪待兔清仓线全系统回放（机制性证据 + 量级判断） # user-confirmed-commit"
```

---

## 自审（spec 覆盖检查）

| spec 要求 | 落在哪个 Task |
|---|---|
| §4 变体表（V1/V2/V3 边界与 25% 底仓） | Task 4（`VARIANTS`）+ Task 3（边界测试） |
| §4.1 熔断仍以市场指数为触发源 | Task 1（`test_..._circuit_breaker_still_beats_variant_core`） |
| §4.1 「高情绪区间」定义 + `H_s` 对照列 | Task 5（`high_mood_masks` + 表 2） |
| §5 注入点 = `run_portfolio` / `market_target` | Task 1 + Task 2 |
| §5 `saturation_of` 等参数化 | Task 3 |
| §5.1 `variant_core_series` 契约（复用 + 缺列抛错 + 零覆盖抛错） | Task 4 |
| §6 双窗口 | Task 5（`EFFECT_START` + 表 1 / 1b） |
| §7.1 组合级指标 | Task 5（`metrics_frame`） |
| §7.2 归因表 | Task 5b（库层 `attribution_contributions` + 表 2b） |
| §7.3 机制性指标 | Task 5（`flat_stats` + 表 3） |
| §7.4 高情绪区间相对收益差 | Task 5（表 2） |
| §7.5 结论段（三点） | Task 5（结论段打印） |
| §8 结论纪律 | Task 5 + Task 6（③） |
| §9 错误处理与明示项 | Task 3（长度校验）+ Task 4（抛错）+ Task 6（①） |
| §10.1 等价性红线（4 条） | Task 1 / 2 / 3 |
| §10.2 变体表正确性 | Task 3 + Task 4 |
| §10.3 静态守卫 | Task 5 |
| §12 回写事项 | Task 6 |

---

## Task 5b: 归因表（回答「谁在拖累」）

⚠️ **不得**用逐 sleeve 回测替代（spec §2 事实 7：每条 sleeve 的目标只有组合的 1/3
≈ 8.5% < `REBALANCE_THRESHOLD` 10pp ⇒ 几乎不交易，本仓库实测曾据此算出组合回撤 −72%，
是**已知错误口径**）。归因表在**库层**实现（纯计算），脚本只负责打印。

**Files:**
- Modify: `fg_system/shoutu_variants.py`（追加 `attribution_contributions`）
- Modify: `scripts/analyze_shoutu_variants.py`（追加表 2b）
- Test: `tests/test_shoutu_variants.py`（追加）

- [ ] **Step 1: 写失败测试**

```python
def test_attribution_sums_to_basket_return():
    """一致性（构造保证）：各标的加权贡献之和 == `Σ_t base_t × 篮子收益_t`。

    ⚠️ 若 `pipeline.weighted_basket_returns` 内部对首日 NaN 的处理与
    `pct_change(fill_method=None)` 不同，请以**库内实现**为准对齐期望值
    —— **只对齐口径，不得放宽断言**（仍必须是 `pytest.approx` 严格相等）。
    """
    idx = pd.date_range("2024-01-01", periods=20, freq="B")
    wide = pd.DataFrame({(s, "close"): [100.0 + i for i in range(20)]
                         for s in config.SYMBOLS}, index=idx)
    w = pd.DataFrame(1.0 / 3.0, index=idx, columns=config.SYMBOLS)
    base = pd.Series(0.5, index=idx)
    mask = pd.Series(True, index=idx)
    got = shoutu_variants.attribution_contributions(wide, w, base, mask)
    basket = pipeline.weighted_basket_returns(wide, w)
    assert got.sum() == pytest.approx(float((base * basket).sum()))
    assert list(got.index) == list(config.SYMBOLS)


def test_attribution_respects_mask():
    """掩码外的日子不计入。"""
    idx = pd.date_range("2024-01-01", periods=10, freq="B")
    wide = pd.DataFrame({(s, "close"): [100.0 + i for i in range(10)]
                         for s in config.SYMBOLS}, index=idx)
    w = pd.DataFrame(1.0 / 3.0, index=idx, columns=config.SYMBOLS)
    base = pd.Series(0.5, index=idx)
    mask = pd.Series([True, False] * 5, index=idx)
    got = shoutu_variants.attribution_contributions(wide, w, base, mask)
    all_on = shoutu_variants.attribution_contributions(
        wide, w, base, pd.Series(True, index=idx))
    assert (got < all_on).all()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `py -3.10 -m pytest tests/test_shoutu_variants.py -v -k attribution`
Expected: FAIL —— `AttributeError: module 'fg_system.shoutu_variants' has no attribute 'attribution_contributions'`

- [ ] **Step 3: 实现（库层）**

追加到 `fg_system/shoutu_variants.py`：

```python
def attribution_contributions(wide, weights, base, mask, symbols=None):
    """各标的的**加权贡献** `Σ_{t ∈ mask} base_t × w_i,t × r_i,t`。

    回答「谁在拖累」。⚠️ **不得**用逐 sleeve 回测替代（spec §2 事实 7：
    每条 sleeve 的目标只有组合的 1/3，低于 `REBALANCE_THRESHOLD` ⇒ 几乎不交易，
    是已知错误口径）。

    返回 Series（index = symbol）。**各标的之和 == `Σ_t base_t × 篮子收益_t`**
    （因 `篮子收益_t = Σ_i w_i,t × r_i,t`）—— 由
    `tests/test_shoutu_variants.py::test_attribution_sums_to_basket_return` 常驻守卫。
    """
    symbols = list(symbols) if symbols else list(config.SYMBOLS)
    rets = pd.DataFrame(
        {s: wide[(s, "close")] for s in symbols}).pct_change(fill_method=None)
    w = weights.reindex(rets.index).ffill()
    b = pd.Series(base).reindex(rets.index).fillna(0.0)
    contrib = w.mul(rets).mul(b, axis=0)
    m = pd.Series(mask).reindex(rets.index).fillna(False).astype(bool)
    return contrib[m].sum()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `py -3.10 -m pytest tests/test_shoutu_variants.py -v -k attribution`
Expected: 2 passed

- [ ] **Step 5: 接进脚本（表 2b）**

在 `scripts/analyze_shoutu_variants.py` 的 `main()` 里，**表 2 之后**追加：

```python
    print("=== 表 2b：归因（各标的加权贡献 Σ_t base_t × w_i,t × r_i,t；单位 pp）===")
    rows = []
    for key, r in results.items():
        c_h = shoutu_variants.attribution_contributions(wide, weights, r["base"], H)
        c_o = shoutu_variants.attribution_contributions(wide, weights, r["base"], ~H)
        row = {"变体": key, "说明": _label(key)}
        for s in config.SYMBOLS:
            row["H·" + s] = 100 * float(c_h[s])
        row["非H合计"] = 100 * float(c_o.sum())
        rows.append(row)
    print(pd.DataFrame(rows).round(4).to_string(index=False))
    print()
```

> ⚠️ 归因表是**诊断**：用来识别「高情绪区间里哪个标的在拖累」，
> **不得**据此挑标的或挑权重（第 13.1 / 13.2 条）。

- [ ] **Step 6: 跑脚本核对**

Run: `py -3.10 scripts/analyze_shoutu_variants.py`
Expected: 打出表 2b；**人工核对**：V1 在 `H` 区间的各标的贡献之和应**小于**基准（少赚）

- [ ] **Step 7: 提交**

```bash
git add fg_system/shoutu_variants.py scripts/analyze_shoutu_variants.py tests/test_shoutu_variants.py
git commit -m "feat(shoutu): A1 归因表（各标的加权贡献，替代已知错误的逐 sleeve 回测口径） # user-confirmed-commit"
```
