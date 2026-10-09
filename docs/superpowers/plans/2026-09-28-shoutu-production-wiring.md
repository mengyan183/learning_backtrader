# A2 守猪待兔生产通路 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把守猪待兔（贪恐指数）建成「可作为 `us_equity` 核心仓信号与极端规则触发源」的正式生产通路，**全部开关默认关闭 ⇒ 现有生产行为逐位不变**。

**Architecture:** 新增薄编排入口 `pipeline.run_portfolio_v2()`，把现在散在 `cli.py` 与 `scripts/analyze_shoutu_variants.py` 里的 6 步编排固化成一条链；两个正交开关 `shoutu_variant`（五档 core 来源）与 `shoutu_keyed_extremes`（熔断/极恐触发源）。库层保持纯计算，I/O 与策略集中在编排层。

**Tech Stack:** Python 3.10 / pandas / numpy / pytest；`fg_system` 包；Windows（公司电脑），解释器 `py -3.10`。

**Spec:** `docs/superpowers/specs/2026-09-28-shoutu-production-wiring-design.md`

---

## 文件结构

| 文件 | 动作 | 职责 |
|---|---|---|
| `fg_system/signal/market_signal.py` | 改 | `market_target(..., trigger_index=None)` —— 极端规则的触发源可独立于五档 core |
| `fg_system/pipeline.py` | 改 | `run_portfolio(..., us_trigger_index=None)` + 两个 Series 覆盖率守卫；新增 `shoutu_market_index()`（纯函数）、`run_portfolio_v2()`（编排）、`_require_series_coverage()`、`_check_shoutu_freshness()`（停更检测）、`_report_shoutu()` |
| `fg_system/config.py` | 改 | 新增 `SHOUTU_SIGNAL_MAX_LAG_DAYS = 3`（交易日，信号源陈旧容忍度） |
| `fg_system/cli.py` | 改 | `backtest-v2` 改调 `run_portfolio_v2`；新增 `--shoutu-variant` / `--shoutu-keyed-extremes` |
| `scripts/shoutu_daily.cmd` | 改 | 追加 `fetch_shoutu_history.py`（信号源定期更新） |
| `tests/test_shoutu_cores.py` | 追加 | `shoutu_market_index()` 的纯函数测试 |
| `tests/test_shoutu_variants.py` | 追加 | `market_target` / `run_portfolio` 的等价性红线与守卫测试 |
| `tests/test_shoutu_wiring.py` | **新建** | `run_portfolio_v2` 的等价性、零 I/O、缺失策略、端到端 |
| `docs/trading-discipline.md` | 改 | §14.5 新增 A2 小节；§13.6 O4 观察列；D5 改「待触发」 |

**不动**：`fg_system/shoutu_variants.py`（保持纯计算、无 I/O）。

**⚠️ 全程纪律**：本计划所有改动都必须满足「默认参数 ⇒ 生产逐位不变」。任何一步若发现无法满足，**停下来**，不要为了让测试变绿而放宽红线。

---

## Task 1: 前置实测 —— A1 的 `us_core` 是否含 NaN

**为什么先做这个**：spec §7.5 裁决「在 `run_portfolio` 里加 NaN 守卫」，但 A1 的 `scripts/analyze_shoutu_variants.py` 会传 `us_core` 进去。若它传的 `us_core` 含 NaN，加守卫后该脚本会从「静默降级」变成**抛错** —— 必须先知道事实，才知道要不要重出 A1 的数。

**Files:**
- 不改任何文件（纯探测）

- [ ] **Step 1: 跑探测，确认三个变体的 `us_core` 有没有 NaN**

Run:
```bash
cd /d/3-code/learning_backtrader && py -3.10 -c "import sys;sys.path.insert(0,'.');import pandas as pd;from fg_system import pipeline,shoutu_variants;from fg_system.data import loader;us=pipeline.run_equity_v2();wide=pipeline.load_wide();w=pipeline.risk_weight_series(wide);hist=loader.load_shoutu_history();[print(k, 'n=%d'%len(s), 'nan=%d'%int(s.isna().sum()), 'index_eq=%s'%bool(s.index.equals(us.index))) for k in shoutu_variants.VARIANTS for s in [shoutu_variants.variant_core_series(us,w,hist,k)]]"
```

- [ ] **Step 2: 判定分支**

- **若三行都是 `nan=0`** ⇒ 加守卫后 A1 数字**逐位不变**。在 Task 10 的文档回写里记一句「实测 V1/V2/V3 的 `us_core` 均无 NaN（n=NNN）」，然后继续 Task 2。
- **若某行 `nan>0`** ⇒ **停下来**，把该行记下来（变体名 + NaN 天数），并在 Task 10 的 §14.5 里写清「A1 的哪张表受此影响」+ 重新出数对照。**不要**为了让脚本跑通而放弃守卫。

- [ ] **Step 3: 记录实测输出**

把 Step 1 的完整输出（三行）抄进 Task 10 的 §14.5 回写内容里。本 Task 不产生提交。

---

## Task 2: `shoutu_market_index()` 纯函数

**Files:**
- Modify: `fg_system/pipeline.py`（在 `shoutu_market_saturation` 之后、`shoutu_core_series` 之前插入，约 `:503`）
- Test: `tests/test_shoutu_cores.py`（追加）

- [ ] **Step 1: 写失败的测试**

在 `tests/test_shoutu_cores.py` 末尾追加：

```python
def test_shoutu_market_index_is_weighted_mean_of_symbol_index():
    """`shoutu_market_index` = Σ_i w_i × shoutu_symbol_index_i。"""
    idx = pd.date_range("2024-01-01", periods=5, freq="B")
    us = pd.DataFrame({"fg_index": [50.0] * 5, "trend": [1.0] * 5}, index=idx)
    # 守猪待兔宽表：TQQQ 恒 +60（系统 80），SOXL 恒 -60（系统 20）
    wide = pd.DataFrame({"TQQQ": [60.0] * 5, "SOXL": [-60.0] * 5}, index=idx)
    weights = pd.DataFrame({"TQQQ": [0.75] * 5, "SOXL": [0.25] * 5}, index=idx)
    out = pipeline.shoutu_market_index(
        us, weights, shoutu_wide=wide, symbols=["TQQQ", "SOXL"])
    # 0.75 × 80 + 0.25 × 20 = 65
    assert out.round(6).tolist() == [65.0] * 5


def test_shoutu_market_index_falls_back_to_fg_index_on_empty_history():
    """历史区间无守猪待兔数据 ⇒ 三级回退到 fg_index ⇒ 逐位等于 fg_index。"""
    idx = pd.date_range("2024-01-01", periods=5, freq="B")
    us = pd.DataFrame({"fg_index": [10.0, 30.0, 50.0, 70.0, 90.0],
                       "trend": [1.0] * 5}, index=idx)
    weights = pd.DataFrame({"TQQQ": [0.5] * 5, "SOXL": [0.5] * 5}, index=idx)
    out = pipeline.shoutu_market_index(
        us, weights, shoutu_wide=pd.DataFrame(), symbols=["TQQQ", "SOXL"])
    assert out.round(9).tolist() == us["fg_index"].round(9).tolist()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /d/3-code/learning_backtrader && py -3.10 -m pytest tests/test_shoutu_cores.py -k shoutu_market_index -v`

Expected: FAIL —— `AttributeError: module 'fg_system.pipeline' has no attribute 'shoutu_market_index'`

- [ ] **Step 3: 实现**

在 `fg_system/pipeline.py` 的 `shoutu_market_saturation`（`:481-502`）之后插入：

```python
def shoutu_market_index(us_features, weights, shoutu_wide=None, symbols=None):
    """守猪待兔口径的**市场级指数**（0~100）—— 逐标的系统口径指数的加权平均。

    `= Σ_i w_i × shoutu_symbol_index_i`（`Σ w_i = 1`）。

    ⚠️ **与 `shoutu_market_saturation` 的区别**：后者**先查档位再加权**
    （`Σ w_i × sat_i`，值域 [0,1]）；本函数**直接加权连续指数** ——
    熔断 / 极恐的阈值判定（`>= 85` / `<= 10`）需要连续量，用饱和度会丢量纲。

    ⚠️ **历史区间自动等价 `fg_index`**：守猪待兔无数据时 `shoutu_symbol_index`
    三级回退到 `fg_index` ⇒ 逐标的指数均等于 `fg_index` ⇒ 因 `Σ w_i = 1`，
    本函数**逐位等于 `fg_index`** ⇒ keyed extremes 在历史区间不改变任何行为。
    ⚠️ **不得把这个性质外推到 core 变体**（V2/V3 在 `2024-04-23` 之前会变）。

    只读不写；`shoutu_wide=None` 时由 `shoutu_symbol_index` 走默认
    （`loader.load_shoutu_fng()`）—— 生产路径**必须**显式传入 history 宽表
    （spec §6：信号源唯一为 `shoutu_history.csv`）。
    """
    symbols = list(symbols) if symbols else list(config.SYMBOLS)
    idx = shoutu_symbol_index(us_features, shoutu_wide, symbols)
    w = weights.reindex(us_features.index).ffill()
    return (idx * w).sum(axis=1, min_count=len(symbols))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /d/3-code/learning_backtrader && py -3.10 -m pytest tests/test_shoutu_cores.py -k shoutu_market_index -v`

Expected: PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
git add fg_system/pipeline.py tests/test_shoutu_cores.py
git commit -m "feat(a2): shoutu_market_index —— 守猪待兔口径的市场级指数（纯函数）"
```

---

## Task 3: `market_target(..., trigger_index=None)`

**Files:**
- Modify: `fg_system/signal/market_signal.py:224-284`
- Test: `tests/test_shoutu_variants.py`（追加）

- [ ] **Step 1: 写失败的测试**

在 `tests/test_shoutu_variants.py` 末尾追加：

```python
def test_market_target_trigger_index_none_is_identical_to_default():
    """等价性红线：不传 `trigger_index` 与传 `trigger_index=None` 逐位相同。"""
    a, _ = ms.market_target(90.0, 0.0, 1.0, ms.MarketState(market="us_equity"), "us_equity")
    b, _ = ms.market_target(90.0, 0.0, 1.0, ms.MarketState(market="us_equity"),
                            "us_equity", trigger_index=None)
    assert a == b


def test_market_target_trigger_index_drives_circuit_breaker():
    """`trigger_index` 驱动熔断：`index_value` 低但 `trigger_index` 极贪 ⇒ 仍熔断。"""
    out, _ = ms.market_target(10.0, 0.0, 1.0, ms.MarketState(market="us_equity"),
                              "us_equity",
                              trigger_index=float(config.EXTREME_GREED_TRIGGER))
    full = config.CORE_CAP * config.MARKET_CORE_RATIO["us_equity"] * 1.0
    assert abs(out.core_position - full * config.EXTREME_GREED_FLOOR) < 1e-9
    assert out.extreme is True


def test_market_target_trigger_index_drives_extreme_fear():
    """`trigger_index` 驱动极恐：`index_value` 中性但 `trigger_index` 极恐 ⇒ 置位。"""
    out, _ = ms.market_target(50.0, 0.0, 1.0, ms.MarketState(market="us_equity"),
                              "us_equity",
                              trigger_index=float(config.EXTREME_FEAR_TRIGGER))
    assert out.extreme_fear is True


def test_market_target_trigger_index_nan_falls_back_to_index_value():
    """`trigger_index` 为 NaN ⇒ 退回 `index_value`（NaN 不是有效信号）。"""
    a, _ = ms.market_target(90.0, 0.0, 1.0, ms.MarketState(market="us_equity"), "us_equity")
    b, _ = ms.market_target(90.0, 0.0, 1.0, ms.MarketState(market="us_equity"),
                            "us_equity", trigger_index=float("nan"))
    assert a == b
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /d/3-code/learning_backtrader && py -3.10 -m pytest tests/test_shoutu_variants.py -k trigger_index -v`

Expected: FAIL —— `TypeError: market_target() got an unexpected keyword argument 'trigger_index'`

- [ ] **Step 3: 实现**

`fg_system/signal/market_signal.py` —— 改签名与文档：

```python
def market_target(index_value, drawdown, trend, state, market, date=None, prices=None,
                  core=None, trigger_index=None):
    """计算单市场的核心仓与极端状态，返回 (MarketOutput, 新 MarketState)。

    `core`（可选）：**替换**五档结果 `market_core(index_value, trend, market)`。
    用于「清仓线变体」的离线回放（A1）。

    `trigger_index`（可选）：**极端规则的触发源**（A2 的 keyed extremes）。
    给定且非 NaN 时，`apply_circuit_breaker` 的触发/解锁判定与 `extreme_fear`
    判定改用 `trigger_index`；**五档 core 的来源仍由 `core=` 决定**，
    `full = CORE_CAP × RATIO × trend` 也**不变**。
    为 `None`（默认）或 NaN 时 ⇒ 一律用 `index_value` ⇒ **逐位不变**。

    ⚠️ 本参数**只用于 `us_equity`**（加密的 `apply_greed_tiers` 仍用
    `index_value`）；`run_portfolio` 只对 `us_equity` 传它。

    ⚠️ `core=None` 且 `trigger_index=None`（默认）时行为与改动前**逐位相同**
    （等价性红线：`tests/test_shoutu_variants.py`）。
    """
```

函数体改动（**只动两处**，其余一字不改）：

把 `:264-265` 的

```python
        state, cb_floor, cb_note = apply_circuit_breaker(
            state, index_value, date, prices or {})
```

改成

```python
        # A2 keyed extremes：极端规则的触发源可与五档 core 的来源不同。
        # None / NaN ⇒ 用 index_value（NaN 不是有效信号，不得静默改变触发行为）。
        trig = index_value if (trigger_index is None or _is_nan(trigger_index)) \
            else trigger_index
        state, cb_floor, cb_note = apply_circuit_breaker(
            state, trig, date, prices or {})
```

把 `:276-279` 的

```python
    extreme_fear = (not _is_nan(index_value)
                    and index_value <= (config.CRYPTO_EXTREME_FEAR_TRIGGER
                                        if market == "crypto"
                                        else config.EXTREME_FEAR_TRIGGER))
```

改成

```python
    # ⚠️ `trig` 在 crypto 分支里不会被赋值 ⇒ 这里重新按同一规则取一次。
    # 加密路径生产上从不传 `trigger_index` ⇒ 逐位不变。
    trig = index_value if (trigger_index is None or _is_nan(trigger_index)) \
        else trigger_index
    extreme_fear = (not _is_nan(trig)
                    and trig <= (config.CRYPTO_EXTREME_FEAR_TRIGGER
                                 if market == "crypto"
                                 else config.EXTREME_FEAR_TRIGGER))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /d/3-code/learning_backtrader && py -3.10 -m pytest tests/test_shoutu_variants.py -v`

Expected: 全部 PASS（含既有 4 条等价性红线）

- [ ] **Step 5: 提交**

```bash
git add fg_system/signal/market_signal.py tests/test_shoutu_variants.py
git commit -m "feat(a2): market_target(trigger_index=) —— 极端规则触发源可独立于五档 core"
```

---

## Task 4: `run_portfolio(..., us_trigger_index=None)` + Series 覆盖率守卫

**Files:**
- Modify: `fg_system/pipeline.py:619-669`
- Test: `tests/test_shoutu_variants.py`（追加）

- [ ] **Step 1: 写失败的测试**

在 `tests/test_shoutu_variants.py` 末尾追加：

```python
def test_run_portfolio_us_trigger_index_none_is_identical_to_default():
    """等价性红线：不传 `us_trigger_index` 与传 `None` 逐位相同。"""
    us, cr = _portfolio_inputs()
    a = pipeline.run_portfolio(us, cr, write=False)
    b = pipeline.run_portfolio(us, cr, write=False, us_trigger_index=None)
    pd.testing.assert_frame_equal(a, b)


def test_run_portfolio_us_trigger_index_reaches_market_target():
    """`us_trigger_index` 极贪 ⇒ 熔断，即使 `fg_index` 中性。"""
    us, cr = _portfolio_inputs(fg=50.0)
    trig = pd.Series(float(config.EXTREME_GREED_TRIGGER), index=us.index)
    out = pipeline.run_portfolio(us, cr, write=False, us_trigger_index=trig)
    full = config.CORE_CAP * config.MARKET_CORE_RATIO["us_equity"]
    assert abs(out["us_core"].dropna().iloc[-1] - full * config.EXTREME_GREED_FLOOR) < 1e-9


def test_run_portfolio_rejects_non_series_us_trigger_index():
    """传 list 必须抛错（同 `us_core` 的守卫）。"""
    us, cr = _portfolio_inputs()
    with pytest.raises(TypeError):
        pipeline.run_portfolio(us, cr, write=False, us_trigger_index=[50.0] * len(us))


def test_run_portfolio_rejects_us_core_with_nan():
    """⚠️ 含 NaN 的 `us_core` ⇒ 抛错（拒绝静默退回市场指数口径，spec §7.5）。"""
    us, cr = _portfolio_inputs()
    bad = pd.Series(0.05, index=us.index)
    bad.iloc[3] = float("nan")
    with pytest.raises(ValueError) as e:
        pipeline.run_portfolio(us, cr, write=False, us_core=bad)
    assert "NaN" in str(e.value)


def test_run_portfolio_rejects_us_trigger_index_with_nan():
    """⚠️ 含 NaN 的 `us_trigger_index` ⇒ 抛错（对称守卫）。"""
    us, cr = _portfolio_inputs()
    bad = pd.Series(50.0, index=us.index)
    bad.iloc[3] = float("nan")
    with pytest.raises(ValueError) as e:
        pipeline.run_portfolio(us, cr, write=False, us_trigger_index=bad)
    assert "NaN" in str(e.value)


def test_run_portfolio_allows_warmup_nan_in_us_core():
    """⚠️ warmup 天（`fg_index` 为 NaN）的 `us_core` NaN 是**预期**的，不得抛错。

    实测（Task 1）：A1 三个变体的 `us_core` 各有 **760 天 NaN，恰好等于 warmup**。
    守卫若不放行，每个变体回放都会抛错 ⇒ 打断 warmup 语义。
    """
    idx = pd.date_range("2024-01-01", periods=40, freq="B")
    us = _us_features(idx, [float("nan")] * 10 + [50.0] * 30)
    cr = _cr_features(idx, [50.0] * 40)
    core = pd.Series(0.05, index=idx)
    core.iloc[:10] = float("nan")          # 与 warmup 对齐
    out = pipeline.run_portfolio(us, cr, write=False, us_core=core)
    assert out["us_core"].iloc[:10].isna().all()
    assert out["us_core"].iloc[10:].eq(0.05).all()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /d/3-code/learning_backtrader && py -3.10 -m pytest tests/test_shoutu_variants.py -k "trigger_index or with_nan" -v`

Expected: FAIL —— `TypeError: run_portfolio() got an unexpected keyword argument 'us_trigger_index'`（`with_nan` 两条则因无守卫而**不抛错**）

- [ ] **Step 3: 实现**

`fg_system/pipeline.py` —— 在 `run_portfolio` 之前新增守卫 helper：

```python
def _require_series_coverage(series, index, name, allow_nan=None):
    """拒绝**非预期**的 NaN —— 不得静默退回市场指数口径（A1 spec §5.1）。

    `series` 已 `reindex(index)`；`allow_nan`（可选）是与 `index` 对齐的布尔掩码，
    表示「这些天允许 NaN」。生产路径传的是「市场指数无效」
    （`us_features["fg_index"].isna()`，即 warmup）—— 那些天 `market_target`
    本来就按「指数无效」处理，`core=None` 与 `core=NaN` **同语义**，
    属**预期**行为，不是数据缺口。

    ⚠️ 实测（Task 1）：A1 三个变体的 `us_core` 各有 **760 天 NaN，恰好等于 warmup**
    ⇒ 若不按 `allow_nan` 放行，每个变体回放都会抛错（打断 warmup 语义）。
    """
    if allow_nan is None:
        allow_nan = pd.Series(False, index=index)
    else:
        allow_nan = pd.Series(allow_nan).reindex(index).fillna(False).astype(bool)
    bad = series.index[series.isna() & ~allow_nan]
    if len(bad):
        head = ", ".join(str(d.date()) for d in bad[:10])
        more = "（共 %d 天）" % len(bad) if len(bad) > 10 else ""
        raise ValueError(
            "%s 含 %d 天**非预期**缺失（NaN，已排除 warmup）—— 拒绝静默退回"
            "市场指数口径：%s%s" % (name, len(bad), head, more))
```

`run_portfolio` 的签名与文档改为：

```python
def run_portfolio(us_features, crypto_features, write=True, us_core=None,
                  us_trigger_index=None):
    """组合级管道：把两个市场的核心仓与共享弹药池合成最终目标仓位（§7）。

    入参是两个市场的 features DataFrame（**未 shift**）。us_features 必须含
    `trend` / `trend_blocked` 列（由 `run_equity_v2` 产出）。

    `us_core`（可选）：**逐日替换** `us_equity` 的五档核心仓（A1 的
    「守猪待兔清仓线变体」离线回放）。含 NaN ⇒ **抛错**（不得静默降级）。
    **只作用于 `us_equity`** —— 加密路径完全不受影响。

    `us_trigger_index`（可选）：**逐日替换** `us_equity` 极端规则（熔断 / 极恐）
    的**触发源**（A2 的 keyed extremes）。含 NaN ⇒ **抛错**。
    **只作用于 `us_equity`**。

    ⚠️ 两者均为 `None`（默认）时行为与改动前**逐位相同**（等价性红线：
    `tests/test_shoutu_variants.py`）。

    返回 portfolio_features（target_position 已 shift(1)）。
    """
```

在 `if us_core is not None:` 块之后补上：

```python
        _require_series_coverage(us_core, joined.index, "us_core", allow_nan)

    if us_trigger_index is not None:
        if not isinstance(us_trigger_index, pd.Series):
            raise TypeError(
                "us_trigger_index 必须是 pd.Series（index = 日期），收到 %s —— "
                "传 list/ndarray 会因 RangeIndex 重索引而**静默全丢**"
                % type(us_trigger_index).__name__)
        us_trigger_index = us_trigger_index.reindex(joined.index)
        _require_series_coverage(us_trigger_index, joined.index,
                                 "us_trigger_index", allow_nan)
```

并在 `joined = us.join(cr, how="left", ...)` 之后、`if us_core is not None:` 之前插入：

```python
    # warmup（`fg_index` 为 NaN）那些天 `market_target` 本就按「指数无效」处理，
    # `core=NaN` 与 `core=None` **同语义** ⇒ 允许 NaN（A2 spec §7.5 实测：
    # A1 三个变体各有 760 天 NaN，恰好等于 warmup）。
    allow_nan = us["fg_index"].isna().reindex(joined.index).fillna(False)
```

把 `:667-669` 的调用改成：

```python
        core_us = None if us_core is None else us_core[dt]
        trig_us = None if us_trigger_index is None else us_trigger_index[dt]
        out_us, us_state = ms_mod.market_target(
            idx_us, dd_us, tr_us, us_state, "us_equity", date_str,
            core=core_us, trigger_index=trig_us)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /d/3-code/learning_backtrader && py -3.10 -m pytest tests/test_shoutu_variants.py tests/test_pipeline_crypto.py -v`

Expected: 全部 PASS。
⚠️ 若有既有测试因 NaN 守卫而失败 ⇒ **停下来**，先判断是「该测试本就传了含 NaN 的 `us_core`」（那说明它在依赖静默降级，属 bug，需在 Task 10 记录）还是「守卫写错了」。

- [ ] **Step 5: 提交**

```bash
git add fg_system/pipeline.py tests/test_shoutu_variants.py
git commit -m "feat(a2): run_portfolio(us_trigger_index=) + Series 覆盖率守卫（拒绝静默降级）"
```

---

## Task 5: `run_portfolio_v2()` —— 生产编排入口

**Files:**
- Modify: `fg_system/pipeline.py`（在 `run_portfolio` 之后追加）
- Test: `tests/test_shoutu_wiring.py`（**新建**）

- [ ] **Step 1: 写失败的测试**

新建 `tests/test_shoutu_wiring.py`：

```python
# -*- coding: utf-8 -*-
"""A2（守猪待兔生产通路）的等价性红线、零 I/O 与缺失策略测试。

设计：docs/superpowers/specs/2026-09-28-shoutu-production-wiring-design.md
"""
import pandas as pd
import pytest

from fg_system import config, pipeline
from fg_system.data import loader


def _us(idx, fg=50.0, trend=1.0):
    return pd.DataFrame({
        "fg_index": [fg] * len(idx), "zone": 2.0, "drawdown": 0.0,
        "core_position": 0.1, "ammo_position": 0.0, "target_position": 0.1,
        "trend": trend, "trend_blocked": trend < 1.0, "warmup": False,
    }, index=idx)


def _cr(idx, fg=50.0, trend=1.0):
    return pd.DataFrame({
        "crypto_fg_index": [fg] * len(idx), "drawdown": 0.0, "trend": trend,
        "trend_blocked": trend < 1.0, "core_position": 0.1,
        "target_position": 0.1, "warmup": False,
    }, index=idx)


def _inputs(n=40):
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return _us(idx), _cr(idx)


def test_default_is_identical_to_manual_chain():
    """等价性红线：默认参数下 `run_portfolio_v2` == 手拼的 cli 链路（逐位相等）。"""
    us, cr = _inputs()
    a = pipeline.run_portfolio_v2(write=False, us_features=us, crypto_features=cr)
    b = pipeline.run_portfolio(us, cr, write=False)
    pd.testing.assert_frame_equal(a, b)


def test_default_does_not_touch_shoutu_history(monkeypatch):
    """开关全关 ⇒ **零 I/O**：`load_shoutu_history` 一次都不被调用。"""
    def boom(*a, **k):
        raise AssertionError("默认参数下不得读 shoutu_history.csv")
    monkeypatch.setattr(loader, "load_shoutu_history", boom)
    us, cr = _inputs()
    pipeline.run_portfolio_v2(write=False, us_features=us, crypto_features=cr)


def test_default_prints_nothing(capsys):
    """开关全关 ⇒ 不打印任何东西（保持现状 stdout 逐字不变）。"""
    us, cr = _inputs()
    pipeline.run_portfolio_v2(write=False, us_features=us, crypto_features=cr)
    assert capsys.readouterr().out == ""


def test_unknown_variant_raises_keyerror():
    us, cr = _inputs()
    with pytest.raises(KeyError):
        pipeline.run_portfolio_v2(write=False, us_features=us, crypto_features=cr,
                                  shoutu_variant="V9")


def test_non_string_variant_raises_typeerror():
    """`shoutu_variant=True` 不得被当成真值静默接受。"""
    us, cr = _inputs()
    with pytest.raises(TypeError):
        pipeline.run_portfolio_v2(write=False, us_features=us, crypto_features=cr,
                                  shoutu_variant=True)


def test_stale_history_raises(monkeypatch):
    """⚠️ 停更检测：history 落后生产窗口超过容忍 ⇒ 抛错。

    为什么必须有这条：`shoutu_symbol_index` 三级回退到 `fg_index` ⇒ 停更**不产生 NaN**
    ⇒ NaN 守卫抓不到（spec §7.3）。
    """
    idx = pd.date_range("2024-01-01", periods=40, freq="B")
    stale = pd.DataFrame({"date": [idx[0]], "symbol": ["TQQQ"],
                          "score": [0.0], "price": [1.0]})
    monkeypatch.setattr(loader, "load_shoutu_history", lambda *a, **k: stale)
    with pytest.raises(ValueError) as e:
        pipeline.run_portfolio_v2(write=False, us_features=_us(idx),
                                  crypto_features=_cr(idx), shoutu_variant="V1")
    assert "陈旧" in str(e.value)


def test_history_within_lag_does_not_raise(monkeypatch):
    """滞后在容忍范围内（1 个交易日 <= SHOUTU_SIGNAL_MAX_LAG_DAYS）⇒ 不抛错。"""
    idx = pd.date_range("2024-01-01", periods=40, freq="B")
    fresh = pd.DataFrame({"date": [idx[-2]], "symbol": ["TQQQ"],
                          "score": [0.0], "price": [1.0]})
    monkeypatch.setattr(loader, "load_shoutu_history", lambda *a, **k: fresh)
    pipeline.run_portfolio_v2(write=False, us_features=_us(idx),
                              crypto_features=_cr(idx), shoutu_variant="V1")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /d/3-code/learning_backtrader && py -3.10 -m pytest tests/test_shoutu_wiring.py -v`

Expected: FAIL —— `AttributeError: module 'fg_system.pipeline' has no attribute 'run_portfolio_v2'`

- [ ] **Step 3: 实现**

先在 `fg_system/config.py` 的守猪待兔配置区（`SHOUTU_*` 常量旁）追加：

```python
# 信号源**陈旧**容忍度（交易日）。三级回退会把「停更」变成「用 fg_index」而**不产生 NaN**
# ⇒ 必须显式检测（spec §7.3）。正常抓取滞后约 1 个交易日，3 个交易日足以吸收周末与节日。
# ⚠️ 这是**安全阈值**，不是可优化参数（第 4B.6 条：禁止用回测调它）。
SHOUTU_SIGNAL_MAX_LAG_DAYS = 3
```

然后在 `fg_system/pipeline.py` 的 `run_portfolio` 之后追加：

```python
def _report_shoutu(variant, keyed, us, us_core, us_trigger_index, hist):
    """A2 的监控输出：**一行**结构化摘要（只在开关非默认时调用）。"""
    seg = ["[shoutu] variant=%s keyed_extremes=%s" % (variant, keyed)]
    if hist is not None and not hist.empty:
        seg.append("源 %s" % os.path.basename(config.SHOUTU_HISTORY_PATH))
        seg.append("history 覆盖 %s~%s"
                   % (hist["date"].min().date(), hist["date"].max().date()))
        have = set(hist["symbol"])
        seg.append("主样本 %d/%d"
                   % (sum(1 for s in config.SYMBOLS if s in have), len(config.SYMBOLS)))
    if us_core is not None:
        trend = us["trend"].reindex(us.index).fillna(1.0)
        base = pd.Series(saturation_of(us["fg_index"].values), index=us.index) \
            * trend * config.CORE_CAP * config.MARKET_CORE_RATIO["us_equity"]
        seg.append("us_core 均值 %.4f vs 五档基准 %.4f（差 %+.4f）"
                   % (us_core.mean(), base.mean(), us_core.mean() - base.mean()))
        seg.append("最大日差 %.4f" % float((us_core - base).abs().max()))
    if us_trigger_index is not None:
        fi = us["fg_index"]
        seg.append("trigger_index 均值 %.1f vs fg_index %.1f（差 %+.1f）"
                   % (us_trigger_index.mean(), fi.mean(),
                      us_trigger_index.mean() - fi.mean()))
    print(" | ".join(seg))


def _check_shoutu_freshness(hist, us_features):
    """拒绝**陈旧**的信号源 —— 三级回退会掩盖停更，故必须显式检测（spec §7.3）。

    ⚠️ 为什么不能只靠 NaN 守卫：`shoutu_symbol_index` 在守猪待兔无数据时会
    **回退到 `fg_index`**（`pipeline.py:426-434`）⇒ 停更**不产生 NaN** ⇒
    `us_core` 被「旧数据 + 尾部回退」填满并被静默接受 = A1 spec §5.1 禁止的静默降级。

    判据：`hist["date"].max()` 不得早于生产窗口「倒数第 `max_lag + 1` 个交易日」。
    """
    lag = int(config.SHOUTU_SIGNAL_MAX_LAG_DAYS)
    last_hist = pd.Timestamp(hist["date"].max())
    last_win = pd.Timestamp(us_features.index[-1])
    tail = us_features.index[us_features.index <= last_win]
    floor = pd.Timestamp(tail[max(0, len(tail) - lag - 1)])
    if last_hist < floor:
        raise ValueError(
            "信号源陈旧：history 最后一天 %s，生产窗口最后一天 %s"
            "（滞后超过 %d 个交易日）—— 拒绝静默降级"
            % (last_hist.date(), last_win.date(), lag))


def run_portfolio_v2(raw_dir=None, write=True, shoutu_variant=None,
                     shoutu_keyed_extremes=False, us_features=None,
                     crypto_features=None):
    """**生产组合入口**（A2）—— 把守猪待兔接入 `us_equity` 核心仓的通路。

    `shoutu_variant=None`（默认）且 `shoutu_keyed_extremes=False`（默认）
      ⇒ 与「手拼 `run_equity_v2()` + `run_crypto(write=False)` + `run_portfolio()`」
      **逐位相同**（等价性红线：`tests/test_shoutu_wiring.py`）。

    `shoutu_variant`：`shoutu_variants.VARIANTS` 的键（`"V1"`/`"V2"`/`"V3"`）——
    **替换** `us_equity` 五档核心仓的来源。

    `shoutu_keyed_extremes`：`True` ⇒ 熔断 / 极恐的**触发源**改用守猪待兔口径
    的市场级指数（`shoutu_market_index`）。

    `us_features` / `crypto_features`：可选注入（供 CLI 复用已算好的 features，
    避免重复跑 v1 管道）。为 `None` 时自行计算。

    ⚠️ **信号源唯一**：只用 `shoutu_history.csv`（服务端权威日值）。
    `shoutu_fng.csv` 是本地 06:30 采样、口径不同，**不得**进入本通路
    （`loader.py:300-301`）。

    ⚠️ 数据缺失 ⇒ **抛错**，绝不静默退回市场指数口径（spec §7）。
    """
    from fg_system import shoutu_variants      # 延迟导入：shoutu_variants → pipeline 是循环

    if shoutu_variant is not None and not isinstance(shoutu_variant, str):
        raise TypeError(
            "shoutu_variant 必须是 str 或 None，收到 %s —— "
            "传 True/数字会被当成真值静默接受" % type(shoutu_variant).__name__)

    us = run_equity_v2(raw_dir=raw_dir) if us_features is None else us_features
    crypto = (run_crypto(raw_dir=raw_dir, write=False)
              if crypto_features is None else crypto_features)

    us_core = None
    us_trigger_index = None
    hist = None

    if shoutu_variant is not None or shoutu_keyed_extremes:
        wide = load_wide(raw_dir)
        weights = risk_weight_series(wide)
        hist = loader.load_shoutu_history()
        shoutu_wide = shoutu_variants.shoutu_wide_from_long(hist)   # 空/无主样本 ⇒ 抛错
        _check_shoutu_freshness(hist, us)                           # §7.3 停更检测（必须显式）

        # warmup（`fg_index` 为 NaN）的 NaN 属**预期**（spec §7.5 实测）⇒ 放行
        warmup_mask = us["fg_index"].isna()

        if shoutu_variant is not None:
            us_core = shoutu_variants.variant_core_series(
                us, weights, hist, shoutu_variant)
            _require_series_coverage(
                us_core.reindex(us.index), us.index,
                "us_core（变体 %s）" % shoutu_variant, warmup_mask)

        if shoutu_keyed_extremes:
            us_trigger_index = shoutu_market_index(us, weights, shoutu_wide)
            _require_series_coverage(
                us_trigger_index.reindex(us.index), us.index,
                "us_trigger_index（keyed extremes）", warmup_mask)

        _report_shoutu(shoutu_variant, shoutu_keyed_extremes, us, us_core,
                       us_trigger_index, hist)

    return run_portfolio(us, crypto, write=write, us_core=us_core,
                         us_trigger_index=us_trigger_index)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /d/3-code/learning_backtrader && py -3.10 -m pytest tests/test_shoutu_wiring.py -v`

Expected: 7 passed

- [ ] **Step 5: 提交**

```bash
git add fg_system/pipeline.py tests/test_shoutu_wiring.py
git commit -m "feat(a2): run_portfolio_v2 —— 生产组合入口（两开关默认关，零 I/O）"
```

---

## Task 6: CLI 接线 + 两个开关 flag

**Files:**
- Modify: `fg_system/cli.py:388-389`（`_cmd_backtest_v2` 的函数体）与 `:590-593`（argparse）

- [ ] **Step 1: 改 argparse**

`fg_system/cli.py:590-593` 改为：

```python
    p3 = sub.add_parser("backtest-v2", help="v2 大盘回测（趋势过滤 + 标的权重）")
    p3.add_argument("--weighting", choices=["inv_vol", "equal", "full"], default=None,
                    help="标的权重口径（默认取 config.WEIGHTING）")
    p3.add_argument("--shoutu-variant", default=None, choices=["V1", "V2", "V3"],
                    help="用守猪待兔替换 us_equity 五档核心仓的来源（A2）。"
                         "默认关闭。⚠️ 打开前必须满足 §14.5 O4 的触发条件")
    p3.add_argument("--shoutu-keyed-extremes", action="store_true",
                    help="熔断/极恐的触发源改用守猪待兔口径（A2）。"
                         "默认关闭。⚠️ 其量级尚未评估")
    p3.set_defaults(func=_cmd_backtest_v2)
```

- [ ] **Step 2: 改函数体**

`fg_system/cli.py:388-389` 的

```python
    us = pipeline.run_equity_v2()
    pf = pipeline.run_portfolio(us, pipeline.run_crypto(write=False), write=False)
```

改为

```python
    us = pipeline.run_equity_v2()
    # A2：走正式生产入口（两开关默认关 ⇒ 与旧链路逐位相同）。
    # `us_features=us` 是**复用**已算好的 features，避免重复跑 v1 管道。
    pf = pipeline.run_portfolio_v2(
        write=False, us_features=us,
        shoutu_variant=getattr(args, "shoutu_variant", None),
        shoutu_keyed_extremes=bool(getattr(args, "shoutu_keyed_extremes", False)))
```

- [ ] **Step 3: 跑既有测试确认没打破东西**

Run: `cd /d/3-code/learning_backtrader && py -3.10 -m pytest tests/test_check_deploy_set.py tests/test_shoutu_wiring.py -v`

Expected: 全部 PASS

- [ ] **Step 4: 手工确认默认输出不变**

Run: `cd /d/3-code/learning_backtrader && py -3.10 -m fg_system.cli backtest-v2 2>&1 | head -20`

Expected: 与改动前**逐字相同**的输出（无 `[shoutu]` 行）。
⚠️ 若本机无法跑通（缺数据/网络），改为 `py -3.10 -c "from fg_system import cli; print(cli.main(['backtest-v2']))"` 观察退出码，并在 Task 10 记录「未做真机确认」。

- [ ] **Step 5: 提交**

```bash
git add fg_system/cli.py
git commit -m "feat(a2): cli backtest-v2 接入 run_portfolio_v2 + 两个默认关闭的开关"
```

---

## Task 7: 额度核对（spec §10.3 裁决 (i)）—— **用 bsk 自动化**

**为什么**：`fetch_shoutu_history.py` 要进定时任务，而「历史端点是否消耗额度」**从未验证**
（`docs/trading-discipline.md:2621-2626`）。定时任务每天跑 ⇒ 必须先知道消耗。

**Files:** 不改文件（只记录读数，回写见 Task 9）

**技能**：本 Task 全程用 `browser-skill`（`bsk`）—— 它驱动用户已登录的 Chromium。
⚠️ **只读页面上展示的额度文本；严禁读取 storage / cookie / token 等凭据面**。

- [ ] **Step 1: 起 session**

Run: `bsk session start`

记录打印出的 4 字母 session id（下称 `<id>`）。**后面的每条命令都要带 `--session <id>`。**

- [ ] **Step 2: 导航到额度页并观察**

```bash
bsk navigate "https://fe.szdt.tech/invest/#/stock_scan_history" --session <id>
bsk observe --session <id>
```

- 若页面要求登录 ⇒ `bsk request-help --session <id>` 请用户完成登录，返回后**重新** `bsk observe`
- 若 `observe` 里看不到额度数字 ⇒ 依次升级：`bsk snapshot` → `bsk get-html`
  （`get-html` 用来定位额度所在的节点，**不要**用它去读凭据面）

- [ ] **Step 3: 读**抓取前**的额度 → 记为 `BEFORE`**

```bash
bsk evaluate "document.body.innerText" --session <id> --json
```

从返回的 `innerText` 里抄出额度相关行（剩余额度 / 已用额度）记为 `BEFORE`。
⚠️ `evaluate` 必须检查返回的 `.ok` 为 `true`（CLI 退出码 0 不代表 JS 没抛异常）。

- [ ] **Step 4: 跑一次只含 1 个标的的 history 抓取**

Run:
```bash
cd /d/3-code/learning_backtrader && PYTHONUTF8=1 PYTHONPATH=. py -3.10 scripts/fetch_shoutu_history.py --symbols TQQQ
```

Expected: 输出形如 `  TQQQ  627 天（2024-04-23 ~ 2026-09-28）`，末尾 `已写入：...`

⚠️ 必须在**美股收盘后**跑（spec §10.2：收盘前抓会写入未完成的最后一行）。

- [ ] **Step 5: 重新导航后再读一次额度 → 记为 `AFTER`**

```bash
bsk navigate "https://fe.szdt.tech/invest/#/stock_scan_history" --session <id>
bsk evaluate "document.body.innerText" --session <id> --json
```

- [ ] **Step 6: 判定 + **无论如何都要停 session**

- `AFTER == BEFORE` ⇒ 结论「历史端点**不消耗**额度」⇒ Task 8 走「加入定时任务」分支
- `AFTER < BEFORE` ⇒ 记下差值；若按 Tue–Sat 每天一次会耗尽 ⇒ Task 8 走
  「**不加入**定时任务，改手工按需抓」分支

```bash
bsk session stop <id>
```

⚠️ **成功路径与失败路径都必须 stop**（browser-skill 硬要求：不依赖空闲超时清理）。

- [ ] **Step 7: 记录**

把 `BEFORE` / `AFTER` / 差值 / 结论 四项抄进 Task 9 的 §14.5 回写内容。

---

## Task 8: 定时任务改造（按 Task 7 结论）

**Files:**
- Modify: `scripts/shoutu_daily.cmd:87-90`
- Test: `tests/test_check_deploy_set.py` 或 `tests/test_shoutu_wiring.py`（追加静态守卫）

- [ ] **Step 1: 写静态守卫测试（先失败）**

在 `tests/test_shoutu_wiring.py` 末尾追加：

```python
def test_shoutu_daily_cmd_is_ascii_only():
    """⚠️ cmd.exe 按 GBK 读 .cmd ⇒ 非 ASCII 字节会吞换行导致串行执行（2026-09-23 事故）。"""
    path = os.path.join(config.ROOT, "scripts", "shoutu_daily.cmd")
    with open(path, "rb") as f:
        raw = f.read()
    raw.decode("ascii")            # 非 ASCII ⇒ 直接抛 UnicodeDecodeError


def test_shoutu_daily_cmd_fetches_shoutu_history():
    """A2：定时任务必须定期抓守猪待兔历史（否则生产信号源停更）。"""
    path = os.path.join(config.ROOT, "scripts", "shoutu_daily.cmd")
    with open(path, "rb") as f:
        text = f.read().decode("ascii")
    assert "fetch_shoutu_history.py" in text
```

并在 `tests/test_shoutu_wiring.py` 顶部补 `import os`。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /d/3-code/learning_backtrader && py -3.10 -m pytest tests/test_shoutu_wiring.py -k daily_cmd -v`

Expected: `test_shoutu_daily_cmd_fetches_shoutu_history` FAIL（断言失败）；ASCII 那条 PASS

- [ ] **Step 3: 改 `scripts/shoutu_daily.cmd`**

在 `:87` 的 `:shoutu_done` 之后、`:89` 的 `for /f %%i in (...)` 之前插入
（**纯 ASCII**，缩进与现有风格一致）：

```bat
REM ---------------------------------------------------------------------------
REM A2 (2026-09-28): shoutu HISTORY -- the production signal source.
REM fetch_shoutu.py above only records the 06:30 SNAPSHOT (Data/raw/shoutu_fng.csv,
REM 4-5 days per symbol, not a history source). A2 wires shoutu_history.csv into
REM the us_equity core, so it must be refreshed on a schedule.
REM Run AFTER the US close: 06:30 Beijing = 18:30 ET previous day (DST) -- closed.
REM Failure here does NOT change RC (the main path decides the task result),
REM but its own exit code is logged separately.
REM ---------------------------------------------------------------------------
"C:\Users\260023\AppData\Local\Programs\Python\Python310\python.exe" scripts\fetch_shoutu_history.py >> logs\shoutu_daily.log 2>&1
set RC2=%ERRORLEVEL%
echo ===== shoutu_history exit=%RC2% ===== >> logs\shoutu_daily.log
```

> **若 Task 7 的结论是「消耗额度且余量不足」** ⇒ **不要**插入上面这段；
> 改为在文件头部注释区加一段 ASCII 说明「history 需手工按需抓，见 spec §10.3」，
> 并把 `test_shoutu_daily_cmd_fetches_shoutu_history` 改为断言该说明存在。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /d/3-code/learning_backtrader && py -3.10 -m pytest tests/test_shoutu_wiring.py -v`

Expected: 全部 PASS（7 passed）

- [ ] **Step 5: 提交**

```bash
git add scripts/shoutu_daily.cmd tests/test_shoutu_wiring.py
git commit -m "feat(a2): 定时任务追加守猪待兔历史抓取（生产信号源）"
```

---

## Task 9: 文档回写

**Files:**
- Modify: `docs/trading-discipline.md`（§14.5 新增 A2 小节；§13.6 O4；D5 状态）

- [ ] **Step 1: §14.5 新增 A2 小节**

在 `docs/trading-discipline.md` 的 §14.5 内、A1 小节之后追加（内容必须含下面全部要点）：

```markdown
#### A2（2026-09-28）：守猪待兔接入 `us_equity` 核心仓的**通路**（默认关）

设计：`docs/superpowers/specs/2026-09-28-shoutu-production-wiring-design.md`

**一句话**：A1 回答了「要不要改」（**不建议**），A2 只把「怎么改」的**开关装好并锁上**。

| 项 | 结论 |
|---|---|
| 生产入口 | 新增 `pipeline.run_portfolio_v2(shoutu_variant=None, shoutu_keyed_extremes=False)` |
| 开关状态 | **两个开关均默认关闭** ⇒ 生产逐位不变（4 条等价性红线常驻守卫） |
| 信号源 | **唯一** `Data/raw/shoutu_history.csv`（服务端权威日值）。`shoutu_fng.csv` 是本地 06:30 采样、口径不同，**不得**混用 |
| 数据缺失 | **严格抛错**（含缺失日期与覆盖率诊断）；**禁止**静默退回市场指数口径（A1 spec §5.1） |
| keyed extremes | 熔断 / 极恐的**触发源**也可 keyed 到守猪待兔（独立开关）；⚠️ **其量级尚未评估** |
| 扳开条件 | **沿用 §13.6 O4**（真实操作 ≥ 3 次复盘质疑 / **组合级证据**），**不新增量化门槛** |

**三条必须随任何使用一起读的口径**

1. **`shoutu_variant="V2"/"V3"` 在 `2024-04-23` 之前会改变输出**（回退到市场指数后仍套用
   各自的变体表）—— 只有 V1 与该日之前的基准逐位重合（同 A1）。
2. **`shoutu_keyed_extremes` 在历史区间不改变任何行为** —— 因 `Σ w_i = 1`，
   `shoutu_market_index` 逐位等于 `fg_index`。⚠️ **不得把这个性质外推到 core 变体**。
3. **keyed extremes 的效果完全未量化** ⇒ 它不是「已验证的改进」，是「已就绪的能力」。

**实测记录（Task 1 / Task 7）**

- A1 的 `us_core` 是否含 NaN：`<抄 Task 1 Step 1 的三行输出>`
  ⇒ 结论：`<加守卫后 A1 数字是否逐位不变 / 哪张表受影响>`
- 历史端点额度核对：抓取前 `<读数>` → 抓取后 `<读数>`，差 `<差值>`
  ⇒ 结论：`<不消耗 ⇒ 已加入定时任务 / 消耗 ⇒ 改手工按需抓>`
- 抓取时机教训（2026-09-24 实测）：在**美股收盘前**抓会写入**未完成的最后一行**
  （服务端后来修正了那 6 行：TQQQ `78.17 → 77.095`、GDXU `130.71 → 120.85`，
  连 `score` 都变了，如 UPRO `22 → -1`）⇒ **history 必须在美国收盘后抓**。
```

- [ ] **Step 2: §13.6 O4 观察列加一行**

在 O4 的「观察」列末尾追加：

```markdown
| A2 通路已就绪（`run_portfolio_v2`，两开关**默认关**）；触发条件不变 —— 仍是「真实操作 ≥ 3 次复盘质疑 / 组合级证据」 |
```

- [ ] **Step 3: D5 状态改为「待触发」**

把 §14.5 ⑨ 里「剩余待办（数据层确认）」那段改为：

```markdown
**⇒ 状态：待触发（2026-09-28 更新）**

判据（`shoutu_analysis.price_divergence`）需要 fng 与参照源覆盖**同一日**，且**跨越至少一个除息日**。
实测（2026-09-28）：fng 的 `price` 从 **2026-09-25** 起才有值，而 TQQQ 类产品的除息日约在
**9 / 12 月下旬** —— 唯一的除息日恰好卡在 fng 序列**起点之前** ⇒ 当前重叠只有 1 天、
日收益点 0 个 ⇒ `corr_dret = NaN` ⇒ **判据不可计算**。

⇒ **触发条件：等下一个除息日（约 2026-12 下旬）落入 fng 序列后重跑判据。**
旁证（不作判据）：`history/prices` 比值在 `2026-09-17 ~ 09-23` **恒定 0.99807**（−0.19%，
纯报价/结算口径差），从 `09-24` 起跳变（TQQQ `0.98111`、`09-25` `0.99019`）
⇒ 除息日确实落在 `09-23/09-24` 之间，与「9 月下旬除息」吻合。
```

- [ ] **Step 4: 提交**

```bash
git add docs/trading-discipline.md
git commit -m "docs(a2): §14.5 新增 A2 小节 + O4 观察列 + D5 改「待触发」"
```

---

## Task 10: 最终验证

**Files:** 不改文件

- [ ] **Step 1: 全量测试**

Run: `cd /d/3-code/learning_backtrader && py -3.10 -m pytest -q`

Expected: 全部 PASS（基线 742 passed + 本次新增约 18 条）。记录总数。

- [ ] **Step 2: 确认默认路径零影响（真机）**

Run:
```bash
cd /d/3-code/learning_backtrader && py -3.10 -c "import sys;sys.path.insert(0,'.');from fg_system import pipeline;a=pipeline.run_portfolio(write=False);b=pipeline.run_portfolio_v2(write=False);import pandas as pd;pd.testing.assert_frame_equal(a,b);print('IDENTICAL rows=%d'%len(a))"
```

Expected: `IDENTICAL rows=NNN`（无异常）

- [ ] **Step 3: 确认开关打开时能跑通且确实有差异**

Run:
```bash
cd /d/3-code/learning_backtrader && py -3.10 -c "import sys;sys.path.insert(0,'.');from fg_system import pipeline;a=pipeline.run_portfolio(write=False);b=pipeline.run_portfolio_v2(write=False,shoutu_variant='V3');d=(a['us_core']-b['us_core']).abs();print('max_diff=%.6f nonzero_days=%d'%(d.max(),int((d>1e-12).sum())))"
```

Expected: `max_diff` > 0，`nonzero_days` > 0（变体确实生效）；若 `max_diff == 0` ⇒ **停下来查**（说明变体没接上）

- [ ] **Step 3b: 确认 keyed extremes 也能跑通且确实有差异**

Run:
```bash
cd /d/3-code/learning_backtrader && py -3.10 -c "import sys;sys.path.insert(0,'.');from fg_system import pipeline;a=pipeline.run_portfolio(write=False);b=pipeline.run_portfolio_v2(write=False,shoutu_keyed_extremes=True);d=(a['us_core']-b['us_core']).abs();print('max_diff=%.6f nonzero_days=%d'%(d.max(),int((d>1e-12).sum())))"
```

Expected: 能跑通并打印 `[shoutu] variant=None keyed_extremes=True | ...` 一行；
`nonzero_days` 应 > 0（纯效应段内熔断/极恐触发日与基准不同）。
若 `max_diff == 0` ⇒ **停下来查**（说明 `trigger_index` 没接上，或历史区间掩盖了差异 —— 后者说明只跑了历史区间，需确认窗口）。

- [ ] **Step 4: 确认工作区干净**

Run: `cd /d/3-code/learning_backtrader && git status --porcelain`

Expected: 空输出

- [ ] **Step 5: 记录最终 HEAD**

Run: `cd /d/3-code/learning_backtrader && git --no-pager log --oneline -8`

把 8 行抄进交付说明。

---

## 自检清单（执行者用）

- [ ] 每一步的等价性红线都跑过，且**默认参数下生产逐位不变**
- [ ] `shoutu_variants.py` **一个字节都没改**
- [ ] `shoutu_fng.csv` **没有**被接进生产通路
- [ ] 两个开关的默认值分别是 `None` 和 `False`
- [ ] `scripts/shoutu_daily.cmd` 仍是纯 ASCII
- [ ] §14.5 的 A2 小节里「实测记录」三项（NaN / 额度 / 抓取时机）都填了真实数字，没有留占位
