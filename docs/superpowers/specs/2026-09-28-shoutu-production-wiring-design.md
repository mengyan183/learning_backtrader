# A2 设计：守猪待兔接入 `us_equity` 核心仓的通路（**建通路、默认关**）

- 日期：2026-09-28
- 前置：A1（`docs/superpowers/specs/2026-09-24-shoutu-variants-replay-design.md`）已完成，
  结论为「**不建议做 A**」（主样本长 episode `+2.44pp` < 10pp 门槛；单次最大卖飞 `+6.74%` < 20% 门槛）。
- 本 spec 的定位：A1 的 spec §3 第 3 条明写「**不接生产**（把守猪待兔正式接入 `run_portfolio`
  的 `us_equity` 核心仓 = **A2**，另立 spec）」—— 本文件就是那个 spec。

---

## 1. 目标与非目标

### 1.1 目标

**只建通路，不改变默认行为。** 让守猪待兔具备「可作为 `us_equity` 核心仓信号与极端规则触发源」
的**正式生产能力**，并把开关、口径、监控、纪律条款一次补齐 —— 将来想扳开关时不必再动库层。

具体交付 5 块（本次 brainstorming 圈定，见 §3）：

1. **生产入口**：把散落的编排固化为库层正式 API（方案 A，§4）
2. **数据缺失策略**：严格抛错（§7）
3. **信号源口径**：`shoutu_history.csv` 唯一（§6）
4. **开关门槛 + 监控**：沿用 §14.5 O4，不新增量化门槛；生产输出结构化摘要（§8）
5. **keyed extremes**：熔断 / 极恐的触发源也可 keyed 到守猪待兔（独立开关，§9）

### 1.2 非目标（明确不做）

| # | 不做 | 理由 |
|---|---|---|
| 1 | **不把开关设为默认** | A1 结论：不建议做 A。本 spec 的一切开关默认值均为「关」 |
| 2 | 不改 `CORE_CAP` / `MARKET_CORE_RATIO` / `ZONE_EDGES` / `ZONE_SATURATION` 全局值 | 它们被市场指数与加密路径共享（`pipeline.py:451-452` 已写明「不要改全局 config」） |
| 3 | 不改 `run_portfolio` 在 `us_core=None` / `us_trigger_index=None` 下的行为 | 等价性红线（§11.1） |
| 4 | 不用 `shoutu_fng.csv` 作信号源 | 只有 4~5 天/标的（§2 事实 5），当不了历史源；只作留档与旁证 |
| 5 | **不量化 keyed extremes 的效果** | A1 的结论只覆盖「五档 core 来源」。keyed extremes 是新信号面，其量级属**后续**；按 §14.5 O4，扳开前必须有组合级证据（§9.4） |
| 6 | 不动 `RANK_WINDOW`（756） | A1 裁决④：等自然积累（约 2027-04） |

---

## 2. 事实基础（代码现状，逐条带位置）

| # | 事实 | 位置 |
|---|---|---|
| 1 | `run_portfolio(us_features, crypto_features, write=True, us_core=None)` —— 逐日 `core=us_core[dt]` 透传给 `market_target`；**只作用于 `us_equity`**；有硬守卫「必须 `pd.Series`」 | `pipeline.py:619, 639-645, 667-669` |
| 2 | `market_target(index_value, drawdown, trend, state, market, date=None, prices=None, core=None)` —— `core` **替换**五档结果；`full = CORE_CAP × RATIO[market] × trend` 不变 | `market_signal.py:224-251` |
| 3 | **`index_value` 一个入参驱动三件事**：①五档 `market_core` ②`apply_circuit_breaker(state, index_value, ...)` ③`extreme_fear = index_value <= EXTREME_FEAR_TRIGGER`。A1 只覆盖了 ① ⇒ ②③ 仍是市场指数（**混合口径**） | `market_signal.py:239-243, 264-265, 276-279` |
| 4 | 熔断参数：触发 `>= 85`、熔断期核心仓 `× 0.25`、解锁三条件（指数回落至 `60` / 自峰值回落 `15` 点 / 标的自低点反弹 `10%`） | `config.py:101-106`、`market_signal.py:175-220` |
| 5 | 极恐：`index_value <= 10`，冷却 `84` 自然日；组合层 `apply_extreme_fear` 提前释放一批弹药 | `config.py:107,110`、`portfolio.py:153-176` |
| 6 | `shoutu_symbol_index(us_features, shoutu_wide=None, symbols=None, mode=None)` —— **三级回退**：①逐标的分位数（窗口复用 `RANK_WINDOW`，不足返回 NaN）②固定阈值 `(x+100)/2` ③**市场指数 `fg_index`**。**历史区间全部走第 3 级** ⇒ 逐标的指数 = `fg_index` | `pipeline.py:382-434`（关键：`:430-431`） |
| 7 | `shoutu_market_saturation` = `Σ_i w_i × sat_i`（**先查档位再加权**）；`shoutu_core_series` = `CORE_CAP × RATIO × Σ(sat_i·w_i) × trend` | `pipeline.py:481-502, 505-521` |
| 8 | `shoutu_variants.py` **只做纯计算**（无 I/O、不打印）；`VARIANTS` = V1/V2/V3 三张**先验**表；`variant_core_series(us_features, weights, hist, variant)`；`shoutu_wide_from_long` 对空表/无主样本标的**抛错**（拒绝静默回退） | `shoutu_variants.py:6, 29-42, 45-61, 64-83` |
| 9 | `shoutu_variants` **反向 import `pipeline`** ⇒ `pipeline` **不能**在模块级 import 它，必须函数内延迟导入 | `shoutu_variants.py:13`；先例：`pipeline.py:546` |
| 10 | `pipeline` **已** `import loader` ⇒ 读文件不引入新耦合 | `pipeline.py:19` |
| 11 | **生产调用点**：`cli.py:388-389`（`backtest-v2`）。其余：`scripts/portfolio_check.py`、`scripts/analyze_shoutu_variants.py:43`、测试 | grep `run_portfolio(` |
| 12 | 现有编排（要被提升的那 6 步） | `scripts/analyze_shoutu_variants.py:130-136` |
| 13 | 等价性红线已有 4 条 | `tests/test_shoutu_variants.py:76-98, 133-137` |
| 14 | §14.5 ⑨「给 A2 的前置知识」三条：注入点必须在 `run_portfolio`/`market_target`（`run()` 的 `core_position` 是 v1 legacy，注入它传不到组合层）；参数化点清单；`us_core` 必须 `pd.Series` | `docs/trading-discipline.md:2875-2880` |

### 2.1 数据现状（2026-09-28 实测）

| 来源 | 标的数 | 每标的样本 | 覆盖区间 | 更新方式 |
|---|---|---|---|---|
| `shoutu_history.csv` | **6**（AXTX/CRCG 服务端 `data: []`） | **545~627 天** | 2024-04-23 ~ **2026-09-28** | 手工 `bsk` 抓，**未进定时任务** |
| `shoutu_fng.csv` | **8** | **4~5 天** | 2026-09-22/23 ~ 2026-09-26 | **每日 06:30 自动**（`ShoutuDailyFetch`，Tue–Sat） |

- `config.SYMBOLS` = **主样本** `['TQQQ','SOXL','UPRO']`；`config.SHOUTU_SYMBOLS` = 8 标的
- `shoutu_fng.csv` 的 `price` 列**从 2026-09-25 起**才有值（09-22~09-24 回填行为 `NaN`）
- ⚠️ **抓取时机教训（本次实测）**：2026-09-24 那次抓取跑在**美股收盘前**，写入了**未完成的实时值**；
  2026-09-28 重抓后服务端修正了那 6 行（TQQQ `78.17 → 77.095`、GDXU `130.71 → 120.85`，
  连 `score` 都变了，如 UPRO `22 → -1`）⇒ **history 必须在美股收盘后抓**（§10.2）

---

## 3. 决策记录（本次 brainstorming 的 7 项裁决）

| # | 问题 | 裁决 |
|---|---|---|
| 1 | A2 目标 | **建通路、不改默认**（默认 `None` ⇒ 生产逐位不变，沿用 A1 的等价性红线） |
| 2 | A2 范围 | **(a) 生产入口 + (b) 数据缺失策略 + (c) 信号源口径 + (d) 开关门槛&监控** —— 全选 |
| 3 | 信号源 | **`shoutu_history.csv` 唯一** ⇒ 必须把 `fetch_shoutu_history.py` 纳入定时任务 |
| 4 | 数据缺失策略 | **严格抛错**（库层要求全覆盖无 NaN，否则 `raise`） |
| 5 | 开关门槛 | **沿用 §14.5 O4**（「真实操作 ≥ 3 次复盘质疑 / 组合级证据」），**不新增量化门槛**，并**明确保持关闭** |
| 6 | 落点方案 | **方案 A** —— 新增薄编排入口 `run_portfolio_v2(shoutu_variant=None)` |
| 7 | keyed extremes | **拉进 A2**；开关形态取**独立开关** `shoutu_keyed_extremes: bool = False`（与 `shoutu_variant` 正交） |

---

## 4. 架构与注入点（方案 A）

### 4.1 为什么不是 B / C

| 方案 | 做法 | 为何不选 |
|---|---|---|
| **A（选）** | 新增薄编排入口 `run_portfolio_v2()`，把 6 步编排固化 | I/O 与策略集中在编排层；`shoutu_variants.py` 保持纯计算；严格抛错集中一处 |
| B | 在 `run_portfolio` 上加 `shoutu_variant=`，消费侧自己 load history | `run_portfolio` 从「纯组合合成」变成「会读文件」，职责变混，其等价性测试要处理文件依赖 |
| C | 在 `run_equity_v2` 上加参数、返回带 `us_core` 列的 features | 污染 features schema；且 **`run_equity_v2` 根本不调 `run_portfolio`**（它只返回 features），调用方仍得自己取出来传下去 ⇒ 编排又摊回调用点 |

> ⚠️ **一处必须纠正的常见误解**：`run_equity_v2()`（`pipeline.py:524-536`）**不调用** `run_portfolio()`；
> `run_portfolio` 是**调用方**（`cli.py:389`、脚本）另外调的。所以「在 `run_equity_v2` 上加参数、
> 由它传给 `run_portfolio`」在代码上**不成立**。

### 4.2 新增函数签名

```python
def run_portfolio_v2(raw_dir=None, write=True,
                     shoutu_variant=None, shoutu_keyed_extremes=False):
    """生产组合入口（A2）。

    `shoutu_variant=None` 且 `shoutu_keyed_extremes=False`（默认）
      ⇒ 与「今天 cli backtest-v2 手拼的那条链」**逐位相同**（等价性红线 §11.1）。
    """
```

内部步骤（**后半段仅在开关非默认时执行**）：

```
us     = run_equity_v2(raw_dir=raw_dir)
crypto = run_crypto(raw_dir=raw_dir, write=False)

us_core = us_trigger_index = None
if shoutu_variant is not None or shoutu_keyed_extremes:
    from fg_system import shoutu_variants        # 延迟导入：避开 shoutu_variants → pipeline 循环
    wide    = load_wide(raw_dir)
    weights = risk_weight_series(wide)
    hist    = loader.load_shoutu_history()
    shoutu_wide = shoutu_variants.shoutu_wide_from_long(hist)   # 空/无主样本 ⇒ 抛错（已有）
    _check_shoutu_freshness(hist, us)                                # §7.3 停更检测（必须显式）
    if shoutu_variant is not None:
        us_core = shoutu_variants.variant_core_series(us, weights, hist, shoutu_variant)
        _require_series_coverage(us_core.reindex(us.index), us.index,
                                 "us_core（变体 %s）" % shoutu_variant)      # §7.1-4
    if shoutu_keyed_extremes:
        us_trigger_index = shoutu_market_index(us, weights, shoutu_wide)
        _require_series_coverage(us_trigger_index.reindex(us.index), us.index,
                                 "us_trigger_index（keyed extremes）")      # §7.1-5
    _report_shoutu(shoutu_variant, shoutu_keyed_extremes, us, us_core, us_trigger_index, hist)  # §8

return run_portfolio(us, crypto, write=write,
                     us_core=us_core, us_trigger_index=us_trigger_index)
```

### 4.3 组件与改动清单

| 文件 | 动作 | 内容 |
|---|---|---|
| `fg_system/pipeline.py` | **新增** | `run_portfolio_v2()`、`_require_series_coverage()`（把原设计的 `_check_us_core` / `_check_us_trigger` **合并为一个 DRY helper**）、`_check_shoutu_freshness()`（§7.3）、`_report_shoutu()`、`shoutu_market_index()`（§9.2） |
| `fg_system/config.py` | 改 | 新增 `SHOUTU_SIGNAL_MAX_LAG_DAYS = 3`（交易日，§7.3） |
| `fg_system/pipeline.py` | 改 | `run_portfolio(..., us_trigger_index=None)` 透传（§9.2）；`us_core` 的 **NaN 守卫**（§7.3） |
| `fg_system/signal/market_signal.py` | 改 | `market_target(..., trigger_index=None)`（§9.2） |
| `fg_system/cli.py` | 改 | `backtest-v2` 改调 `run_portfolio_v2`；新增 flag `--shoutu-variant`（默认 `None`）与 `--shoutu-keyed-extremes`（默认 `False`）= **扳开关的操作面** |
| `scripts/shoutu_daily.cmd` | 改 | 追加一次 `fetch_shoutu_history.py`（§10.1） |
| `fg_system/shoutu_variants.py` | **不改** | 保持纯计算、无 I/O |
| `tests/test_shoutu_wiring.py` | **新建** | 编排层测试：等价性红线、零 I/O、缺失策略、端到端（§11） |
| `tests/test_shoutu_cores.py` | 追加 | `shoutu_market_index()` 纯函数测试（与 `saturation_of` / `shoutu_core_series` 同类，放同一文件） |

---

## 5. 接口契约

| 参数 | 类型 | 默认 | 语义 | 关闭时的等价性 |
|---|---|---|---|---|
| `shoutu_variant` | `str \| None` | `None` | 合法值 = `shoutu_variants.VARIANTS` 键（`"V1"`/`"V2"`/`"V3"`）；给定 ⇒ **替换** `us_equity` 五档核心仓的来源 | `None` ⇒ 不算序列、不读 history、`us_core=None` ⇒ **逐位不变** |
| `shoutu_keyed_extremes` | `bool` | `False` | `True` ⇒ 熔断 / 极恐的**触发源**改用守猪待兔口径市场级指数 | `False` ⇒ `us_trigger_index=None` ⇒ **逐位不变** |

**正交性**：两参数可任意组合（4 种有效组合：`(None,False)` / `(Vx,False)` / `(None,True)` / `(Vx,True)`）。
`(None, True)` 是**有意义**的对照 —— 「只换极端触发源，五档 core 仍用市场指数」。

**⚠️ 明示项**：`VARIANTS` 的变体表是**先验定义**（第 8 条 / 第 13.1 条），**不得**从回测里搜参数；
本 spec 不新增任何变体表。

---

## 6. 数据流

```
shoutu_history.csv  (6 标的 × 545~627 天, 前复权, 到 2026-09-28)
  └─ loader.load_shoutu_history()                    # loader.py:297，长表 date,symbol,score,price
       └─ shoutu_variants.shoutu_wide_from_long()     # 空/无主样本 ⇒ 抛错
            └─ wide(date × symbol, score)
                 ├─ variant_core_series(us, weights, hist, variant)   # → us_core
                 └─ shoutu_market_index(us, weights, wide)            # → us_trigger_index
                      └─ run_portfolio(us_core=…, us_trigger_index=…)
```

**信号源唯一性**：只允许 `shoutu_history.csv`。`shoutu_fng.csv` **不得**进入本通路
（`loader.py:300-301` 已写明「两者口径不同，**不要混用**」）。

**关键性质（必须随结果一起标注）**：历史区间守猪待兔无数据 ⇒ `shoutu_symbol_index` 三级回退到
`fg_index` ⇒ 逐标的指数均等于 `fg_index` ⇒

- `Σ_i w_i × idx_i = fg_index × Σ_i w_i = fg_index`（因 `Σ w_i = 1`）
- 故 **`shoutu_market_index` 在历史区间逐位等价于 `fg_index`** ⇒ keyed extremes 在历史区间
  **不改变任何行为**

> ⚠️ **不得把这个性质外推到 core 变体**：`V2` / `V3` 在 `2024-04-23` 之前**会**改变输出 ——
> 因为回退到市场指数后仍套用各自的变体表（`§14.5` 已记「只有 V1 在该日之前与基准逐位重合」）。
> keyed extremes 之所以不同，是因为它的**阈值判定用的是连续量**，而回退后该连续量恰好等于 `fg_index`。

---

## 7. 错误处理：严格抛错

### 7.1 拒绝条件（`shoutu_variant is not None` 时）

| # | 条件 | 抛错来源 |
|---|---|---|
| 1 | `shoutu_variant` 不在 `VARIANTS` | `KeyError`（`shoutu_variants.py:75-76`，已有） |
| 2 | `shoutu_history.csv` 不存在或空 | `ValueError`（`shoutu_variants.py:55-56`，已有） |
| 3 | 主样本 3 标的（`config.SYMBOLS`）在窗口内**全缺** | `ValueError`（`shoutu_variants.py:58-60`，已有） |
| 4 | **`us_core` 有「非预期」NaN**（`isna() & ~allow_nan`，`allow_nan = fg_index.isna()`） | `ValueError`（**新增**，`_require_series_coverage`）；⚠️ **warmup 的 NaN 属预期，不抛错**（§7.5 实测） |
| 5 | **`us_trigger_index` 有「非预期」NaN**（同上判据，仅 `shoutu_keyed_extremes=True` 时） | `ValueError`（**新增**，`_require_series_coverage`）；诊断字段同 §7.2 |
| 6 | **信号源陈旧**：`hist["date"].max()` 落后生产窗口最后一天超过 `SHOUTU_SIGNAL_MAX_LAG_DAYS` 个交易日 | `ValueError`（**新增**，`_check_shoutu_freshness`，见 §7.3）；诊断含「history 最后一天」与「生产窗口最后一天」 |

### 7.2 错误信息必须包含的诊断字段

`_require_series_coverage` / `_check_shoutu_freshness` 抛出的信息**必须**含
①变体名 ②缺失日期（最多列 10 个 + 总数）③覆盖率 `已覆盖/总天数` ④缺哪些标的。示例：

```
us_core 在生产窗口内有 3 天缺失（覆盖率 624/627）：变体 V3；
缺失日期：2026-09-26, 2026-09-27, 2026-09-28（共 3 天）；
主样本缺失标的：无（窗口内 3/3 齐全）
```

### 7.3 过期（停更）检测 —— **必须显式做**（2026-09-28 修正）

⚠️ **本节初稿的结论是错的，按下面这版理解**。初稿写的是「数据停更 ⇒ `us_core` 尾部缺失
⇒ 即 NaN ⇒ 被条件 4 覆盖」—— 推理不成立：`shoutu_symbol_index` 是**三级回退**
（percentile → 固定阈值 → **市场指数 `fg_index`**，`pipeline.py:426-434`），守猪待兔没数据的
那些天会**回退成 `fg_index`**，**不产生 NaN** ⇒ NaN 守卫**抓不到停更**。
不加显式检测的后果：`us_core` 被「旧守猪待兔数据 + 尾部 `fg_index` 回退」填满并被静默接受
—— 正是 A1 spec §5.1 明令禁止的**静默降级**。

**判据（§7.1 条件 6）：`_check_shoutu_freshness(hist, us_features)`**

- 令 `last_hist = hist["date"].max()`，`last_win = us_features.index[-1]`
- 令 `max_lag = config.SHOUTU_SIGNAL_MAX_LAG_DAYS`（**新增常量，默认 `3`，单位＝交易日**）
- 取 `us_features.index` 中 **≤ `last_win` 的最后 `max_lag + 1` 个交易日**，令 `floor` 为其最早一天
- **`last_hist >= floor` 才算新鲜**；否则 `raise ValueError`，信息必须含两个日期，例如：
  `信号源陈旧：history 最后一天 2026-09-11，生产窗口最后一天 2026-09-28（滞后超过 3 个交易日）`

**为什么容忍 `3` 个交易日**：定时任务在 06:30 北京抓取（= ET 前一日 18:30/19:30，美股已收盘）
⇒ 正常情况下 `history` 比生产窗口**滞后约 1 个交易日**；`3` 足够吸收周末与节日，
又能拦住「停更数周」。

⚠️ 该常量是**安全阈值**，不是可优化参数（第 4B.6 条：**禁止**用回测去调它）。

### 7.4 绝对禁止

- ❌ `fillna(0)` / `fillna(method="ffill")` 静默填充
- ❌ 缺失日静默 `core=None` 退回市场指数口径 —— A1 spec §5.1 明令禁止
  （「会把『变体无效应』伪装成『变体无差异』」）

### 7.5 ⚠️ 已知边界：`run_portfolio` 现在的静默降级路径

`run_portfolio` 对 `us_core` 只做 `reindex`（`pipeline.py:645`）；NaN 会被 `market_target`
的 `_is_nan` 当成「指数无效」⇒ 返回 `core_position=None` ⇒ **静默降级**。

⇒ **裁决（2026-09-28 用户裁决）：在 `run_portfolio` 内加 NaN 守卫**，但仅在 `us_core is not None`
时生效（`us_core=None` 路径完全不受影响 ⇒ 不破坏等价性红线）。
理由：「静默降级」正是 A1 明令禁止的，而守卫应贴着**消费点**，不能只靠上游自觉。

**前置实测结果（2026-09-28，已执行）**

```
V1  n=2518  nan=760  index_eq_us=True
V2  n=2518  nan=760  index_eq_us=True
V3  n=2518  nan=760  index_eq_us=True

warmup=760  fg_nan=760  nan_eq_warmup=True  nan_eq_fgnan=True
```

⇒ **760 天 NaN 恰好就是 warmup**（`fg_index` 为 NaN 的日子），是**预期语义**、不是数据缺口：
那些天 `market_target` 本来就按「指数无效」处理，`core=NaN` 与 `core=None` **同语义**。

**⚠️ 因此守卫必须按「非 warmup」限定**（否则每个变体回放都会抛错，等于打断 warmup 语义）：

`_require_series_coverage(series, index, name, allow_nan=None)`
—— **只对 `series.isna() & ~allow_nan` 抛错**；生产路径传
`allow_nan = us_features["fg_index"].isna()`（与 `market_target` 的 `_is_nan(index_value)`
判据**完全一致**，即「消费者自己认为指数无效的那些天」）。

**结论：按此限定后 A1 的既有数字逐位不变**（NaN 全部落在 `allow_nan` 内）⇒ 本项无风险，
且**不需要重出 A1 的数**。

---

## 8. 监控输出

`shoutu_variant is not None` 或 `shoutu_keyed_extremes` 为真时，打印**一行**结构化摘要
（**不改 features schema**，只写 stdout）：

```
[shoutu] variant=V3 keyed_extremes=True | 源 Data/raw/shoutu_history.csv
       | history 覆盖 627/627 天（2024-04-23~2026-09-28）| 主样本 3/3
       | us_core 均值 0.123 vs 基准 0.150（差 -0.027）| 最大日差 0.045
       | trigger_index 均值 52.1 vs fg_index 55.3（差 -3.2）| 熔断触发 0 天 | 极恐触发 2 天
```

**约束**：两个开关都为默认值（`None` / `False`）时 ⇒ **不打印任何东西**
（保持现状 stdout 逐字不变，避免污染既有验收输出）。

---

## 9. keyed extremes（独立开关）

### 9.1 目标

把**熔断**与**极恐加仓**的触发源，从市场指数 `fg_index` 改为**守猪待兔口径的市场级指数**，
消除 §2 事实 3 的「混合口径」。

### 9.2 改动

| 文件 | 改动 | 语义 |
|---|---|---|
| `pipeline.py` | **新增纯函数** `shoutu_market_index(us_features, weights, shoutu_wide=None, symbols=None)` | = `Σ_i w_i × shoutu_symbol_index_i`（逐标的系统口径指数 0~100 的**加权平均**）。⚠️ 与 `shoutu_market_saturation` 的区别：后者**先查档位再加权**（`Σ w_i × sat_i`），本函数**直接加权指数**（阈值判定需要连续量，不能用饱和度） |
| `market_signal.py` | `market_target(..., trigger_index=None)` | **给定且非 NaN** 时：`apply_circuit_breaker` 的触发/解锁判定与 `extreme_fear` 判定改用 `trigger_index`；`market_core` 的来源仍由 `core=` 决定；`full = CORE_CAP × RATIO × trend` **不变** |
| `pipeline.py` | `run_portfolio(..., us_trigger_index=None)` | 逐日 `trigger_index=us_trigger_index[dt]` 透传；**只作用于 `us_equity`** |
| `pipeline.py` | `run_portfolio_v2(..., shoutu_keyed_extremes=False)` | 编排（§4.2） |
| `cli.py` | flag `--shoutu-keyed-extremes` | 默认 `False` |

### 9.3 四条必须写进文档的性质

1. `trigger_index=None`（默认）⇒ **逐位不变** ⇒ 等价性红线新增一条（§11.1）
2. 历史区间自动等价现状（§6 的关键性质）⇒ 只有纯效应段（`2024-04-23` 起）才可能有差异
3. 熔断**解锁的价格条件**（标的自低点反弹 `10%`，`market_signal.py:213-218`）**不变**；
   只换**指数条件**（回落至 `60` / 自峰值回落 `15` 点）
4. ⚠️ **量级未评估**：A1 的结论**只覆盖五档 core 来源**，不含 keyed extremes

### 9.4 与开关门槛的关系（衔接 §14.5 O4）

按裁决 5，扳开条件沿用 §14.5 O4 的「真实操作 ≥ 3 次复盘质疑 / **组合级证据**」。
⇒ **keyed extremes 的效果量化属于「组合级证据」的一部分，必须在扳开前完成**，
但**不在本 spec 范围内**（本 spec 只建通路）。这一点必须写进 §14.5 的 A2 小节，
避免「通路建好了就顺手打开」。

---

## 10. 定时任务改造与两个风险

### 10.1 改造

`scripts/shoutu_daily.cmd` 追加一行（与现有两行同构）：

```bat
"C:\Users\260023\AppData\Local\Programs\Python\Python310\python.exe" scripts\fetch_shoutu_history.py >> logs\shoutu_daily.log 2>&1
```

**理由**：信号源不更新 ⇒ 通路无意义。`shoutu_history.csv` 现在**没有任何定期更新机制**
（`fetch_shoutu_history.py` 是手工脚本，见 §2 事实 11 与 §2.1）。

**约束**：该文件**必须保持 ASCII-only**（`install_shoutu_task.cmd:20-23` 记载：cmd.exe 按 GBK
读取 .bat/.cmd，非 ASCII 字节可能吞掉换行导致串行执行 —— 2026-09-23 真实发生过）。

### 10.2 风险 1：抓取时机（**已实测确认**）

- 2026-09-24 那次抓取跑在**美股收盘前** ⇒ 写入未完成的实时值 ⇒ 服务端后来修正了那 6 行
  （§2.1 的教训）。**抓取必须在美国收盘后**。
- 定时任务定在 **06:30 北京（Tue–Sat）** = ET 前一日 18:30（DST）/ 19:30（标准时）⇒ 美股已收盘 ✓
  时机**正确**。`install_shoutu_task.cmd:7-15` 已记录这个窗口的推导。

### 10.3 风险 2：额度（**未验证，必须明示**）

`docs/trading-discipline.md:2621-2626` 记载：**历史端点是否消耗额度未验证** ——
当时**没有**做前后差值核对（spec §9.1 曾列为待办，漏了）。已知的只有抓取期间额度读数仍为 28，
但 28 是「查询实时贪恐」的标的额度，而本脚本走网页登录会话、不是 partner API 的 `X-Auth`
⇒ 两套是否同一套额度**没有证据**。

**处理：裁决 —— 取 (i)「先核对」**（2026-09-28 用户裁决）：

1. **实施顺序**：定时任务改造（§10.1）**之前**，先按 spec §9.1 的办法做一次额度核对 ——
   抓取前后各读一次页面 `#/stock_scan_history` 的额度使用明细，把两次读数记进 §14.5。
2. **判定分支**：
   - 若**不消耗**额度 ⇒ 直接把 history 抓取加进 `shoutu_daily.cmd`（§10.1）
   - 若**消耗**额度 ⇒ 先评估额度余量能否支撑 Tue–Sat 每日一次；不足则**不加入定时任务**，
     改为「手工按需抓」，并在 §14.5 明示「信号源需手工更新」这一运维前提
3. **无论结果如何**，§14.5 的 A2 小节都要记录该读数与结论。

---

## 11. 测试策略（TDD）

### 11.1 等价性红线（最重要）

| # | 断言 | 意义 |
|---|---|---|
| 1 | `run_portfolio_v2(write=False)` == `run_portfolio(run_equity_v2(), run_crypto(write=False), write=False)`（**逐位相等**） | 生产路径零改动 |
| 2 | `run_portfolio(us, cr, write=False, us_trigger_index=None)` == `run_portfolio(us, cr, write=False)` | 新参数默认零影响 |
| 3 | `market_target(..., trigger_index=None)` == `market_target(...)` | 同上 |
| 4 | `run_portfolio_v2(shoutu_variant="V3", write=False)` 的 `us_core` == A1 脚本里 V3 的 `us_core` | **A1 结论可复现**（裁决 7 的独立开关不破坏 A1 的既有数字） |

### 11.2 不读文件（开关关闭时零 I/O）

`shoutu_variant=None` 且 `shoutu_keyed_extremes=False` 时，
`loader.load_shoutu_history` **未被调用**（monkeypatch 计数断言）。

### 11.3 参数校验

- 未知变体 ⇒ `KeyError`
- `shoutu_variant` 传非字符串（如 `True`）⇒ 明确抛错（不得被当成真值静默接受）

### 11.4 缺失 / 陈旧策略

| 构造 | 期望 |
|---|---|
| **history 停更**（`date.max()` 落后窗口超过 `SHOUTU_SIGNAL_MAX_LAG_DAYS` 个交易日） | `ValueError`，信息含两个日期（§7.3）—— **这是「陈旧」的唯一有效判据** |
| history 停更但在容忍范围内（滞后 1~3 个交易日） | **不抛错**，正常出信号 |
| history 缺主样本某个标的（如无 TQQQ） | `ValueError`（`shoutu_wide_from_long` 抛出） |
| `shoutu_history.csv` 为空/不存在 | `ValueError` |
| `run_portfolio(us_core=含 NaN 的 Series)` | `ValueError`（§7.5 的守卫）—— ⚠️ **防御性测试**：真实数据下 `us_core` 因三级回退**不会**产生 NaN，故须 monkeypatch 构造 |
| `run_portfolio(us_trigger_index=含 NaN 的 Series)` | 同上（对称守卫） |

### 11.5 端到端

- `shoutu_variant="V3"` 能跑通，且 `us_core` 与基准**不相等**（差异非零）
- `shoutu_keyed_extremes=True` 且 `shoutu_variant=None` 能跑通，且 `us_equity` 的
  `extreme` / `extreme_fear` 至少有一天与基准不同（纯效应段内）
- `shoutu_keyed_extremes=True` 且 `shoutu_variant=None` 时，历史区间（`2024-04-23` 之前）
  输出与基准**逐位相同**（§6 的关键性质：`us_trigger_index == fg_index`）
- ⚠️ `shoutu_variant="V2"/"V3"` 在 `2024-04-23` 之前**会**改变输出
  （A1 已记：只有 V1 与该日之前的基准重合）—— 这是**期望**行为，不是 bug

### 11.6 静态守卫

- `scripts/shoutu_daily.cmd` 仍 **ASCII-only** 且含 `fetch_shoutu_history` 调用
- `fetch_shoutu_history.py` 的安全约束不回归：**只记录 URL 含 `stock_emotion/history` 的响应体**
  （`tests/data/test_shoutu_history.py::test_script_only_records_the_history_endpoint` 已钉死）

---

## 12. 风险与未知

| # | 风险 / 未知 | 处理 |
|---|---|---|
| 1 | 通路建成后有人「顺手打开」开关 | §9.4 + §14.5 A2 小节明写「默认关 + 扳开需组合级证据」；`cli.py` 的 flag 帮助文本也要写 |
| 2 | `shoutu_history.csv` 只有 6 标的（AXTX/CRCG 服务端无历史） | 明示；`shoutu_wide_from_long` 已按「主样本齐全」抛错，主样本 3 标的均可用 |
| 3 | 守猪待兔历史仅 2.4 年 | 明示为量级估计（沿用 A1 §9-2） |
| 4 | keyed extremes 的量级**完全未评估** | 明示（§9.3-4）；属后续「组合级证据」 |
| 5 | 定时任务新增 history 抓取 ⇒ 额度未计量 | §10.3 二选一 |
| 6 | 抓取时机不当会写入未完成行 | §10.2；另建议在 `fetch_shoutu_history.py` 输出里打印抓取时刻 |
| 7 | 新增参数面（`shoutu_variant` / `shoutu_keyed_extremes` / `us_trigger_index` / `trigger_index`） | 全部默认「关」+ §11.1 四条等价性红线 |
| 8 | D5（fng 的 `price` 复权口径）仍未判定 | 改为「**待触发**」：除息日约在 9/12 月下旬，而 fng 的 `price` 从 2026-09-25 起才有 ⇒ 需等 **2026-12 下旬**除息日落入 fng 序列后重跑判据（`shoutu_analysis.price_divergence`） |
| 9 | **停更被三级回退静默掩盖**（守猪待兔无数据 ⇒ 回退 `fg_index` ⇒ **不产生 NaN** ⇒ NaN 守卫抓不到） | **已修**：§7.3 显式陈旧判据 + §7.1 条件 6（`SHOUTU_SIGNAL_MAX_LAG_DAYS = 3`）—— 这是本 spec 自查阶段发现并修掉的真缺陷 |

---

## 13. 实施任务清单

1. **前置实测**（§7.5 裁决）：`analyze_shoutu_variants.py` 的 `us_core` 是否含 NaN
   （V1/V2/V3 × 双窗口断言 `notna().all()`）—— 决定第 5 步后是否需要重出 A1 的数
2. **配置**：`config.SHOUTU_SIGNAL_MAX_LAG_DAYS = 3`（§7.3）
3. **库层**：`shoutu_market_index()` 纯函数 + 测试（含「历史区间 == `fg_index`」性质）
4. **库层**：`market_target(..., trigger_index=None)` + 等价性红线
5. **库层**：`run_portfolio(..., us_trigger_index=None)` + **两个 Series 覆盖率守卫**
   （§7.5 裁决：加）+ 等价性红线
6. **库层**：`run_portfolio_v2()` + `_require_series_coverage()` + `_check_shoutu_freshness()`
   + `_report_shoutu()`
7. **测试**：§11 全部（TDD：先写失败测试）
8. **CLI**：`backtest-v2` 改调 `run_portfolio_v2`；新增两个 flag（默认关）
9. **额度核对**（§10.3 裁决 (i)）：抓取前后各读一次 `#/stock_scan_history` 的额度明细，
   记录两次读数与结论
10. **定时任务**：按第 9 步结论决定是否把 history 抓取加进 `shoutu_daily.cmd`
    （ASCII-only）+ 静态守卫测试
11. **验证**：全量 `pytest` + 真机跑一次 `--shoutu-variant V3` 与 `--shoutu-keyed-extremes`
12. **文档回写**：§14（含第 9 步的额度读数）

---

## 14. 文档回写

| 文件 | 内容 |
|---|---|
| `docs/trading-discipline.md` §14.5 | 新增 **A2 小节**：通路已建、**开关明确保持关闭**、扳开条件沿用 O4、keyed extremes 量级未评估 |
| `docs/trading-discipline.md` §13.6 O4 | 观察列加一行「A2 通路就绪（默认关），触发条件不变」 |
| `docs/trading-discipline.md` §14.5 ⑨ | D5 从「待办」改为「**待触发**（2026-12 下旬）」；补记「抓取时机」教训（§10.2） |
| 本 spec 附录 | 记录 7 项裁决（§3）与方案对比（§4.1） |

---

## 附：本 spec 与 A1 的关系

| | A1 | A2（本 spec） |
|---|---|---|
| 做了什么 | **量化**「清仓线」规则的代价（4 变体 × 2 窗口） | **建通路**：让守猪待兔可作为核心仓信号与极端规则触发源 |
| 结论 | **不建议做 A**（不改规则 + 归档 + 关议题） | **默认关**；开关就绪但明确不扳 |
| 注入点 | `market_target(core=)` / `run_portfolio(us_core=)` | 追加 `market_target(trigger_index=)` / `run_portfolio(us_trigger_index=)` |
| 等价性 | 4 条红线 | 追加 4 条红线（§11.1） |
| 新增信号面 | 五档 `core` 来源 | 熔断 / 极恐的**触发源** |

**一句话**：A1 回答了「要不要改」，A2 只把「怎么改」的**开关装好并锁上**。
