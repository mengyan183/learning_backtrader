# 守猪待兔清仓线「全系统回放」设计（A1）

- 日期：2026-09-24
- 状态：**设计已获用户确认**（6 节逐节确认），待用户复核本 spec
- 上游裁决：
  - `docs/trading-discipline.md` §13.6 **O4**（守猪待兔早清仓 → 追踪项；触发条件含「组合级 A 证据」）
  - `docs/trading-discipline.md` 第 2603 行附近的**裁决③**（反事实口径与度量）
- 前置：
  - `docs/superpowers/specs/2026-09-24-shoutu-greed-exit-cost-design.md`（**C 阶段**，已完成）
  - `docs/superpowers/specs/2026-09-24-shoutu-history-and-price-design.md`（Step A，已完成）

---

## 1. 背景与目标

**C 阶段（事件研究）**的结论：主判据（`full` = episode 全程）不建议做 A（+3.43pp / +7.56%），
但**补充判据**（`full120` = 120 日固定窗口）的「单次最大卖飞 **+34.33% ≥ 20%**」成立
⇒ 用户裁决：**做 A**。

**本步（A1）的目标**：跑**组合级**回放，出「守猪待兔清仓线」若干口径的
**机制性证据 + 量级判断**。

**为什么 A1 不是「直接把守猪待兔接进生产」**：见 §3 非目标与 §2 现状实测。

---

## 2. 现状实测（2026-09-24，**已逐项核对代码**）

| # | 事实 | 落点 |
|---|---|---|
| 1 | 守猪待兔**完全未接入生产**：`shoutu_symbol_index` / `shoutu_market_saturation` / `shoutu_core_series` **零生产调用点**，只被 `tests/` 与 `scripts/analyze_shoutu_greed.py` 调用 | `pipeline.py:382 / 452 / 471` |
| 2 | **v2 组合链路的 us core 不在 `run()` 里算** —— `run_portfolio` 内部调 `ms_mod.market_target` → `market_core`（`CORE_CAP × MARKET_CORE_RATIO × sat × trend`） | `pipeline.py:613`、`market_signal.py:113` |
| 3 | `run()` 的 `core_position` 是 **v1 legacy**：`CORE_CAP × ZONE_SATURATION[zone_of(idx)]`，**无 RATIO / 无趋势** | `pipeline.py:78`、`signal/legacy.py:81`（`signal.core_position is legacy.core_position` 实测为 `True`） |
| 4 | `config.ZONE_EDGES/ZONE_SATURATION` 被**两条路径共享**：守猪待兔（`pipeline.saturation_of`）与市场指数/加密（`market_signal.zone_of` / `market_core`） | `config.py:93-94`、`market_signal.py:107 / 121`、`pipeline.py:447` |
| 5 | `shoutu_history.csv`（服务端权威日值）**不被 pipeline 消费** | `loader.py:297` 的调用点清单 |
| 6 | 组合级回测的既定做法：**加权篮子 + `FgStrategy` 单组合口径**（执行约束作用于组合整体） | `cli.py:451-462` |
| 7 | ⚠️ **逐 sleeve 回测是已知错误口径**：三条独立 sleeve 的目标只有组合的 1/3（≈8.5%）< `REBALANCE_THRESHOLD` 10pp ⇒ 几乎不交易，实测算出组合回撤 **−72%**（比任何单标的都差） | `pipeline.py:289-299`（`weighted_basket_returns` docstring） |

**⇒ 由事实 2/3 得出一处关键纠正**：变体的注入点**必须在 `run_portfolio` / `market_target`**，
注入 `run()` **传不到组合层**（`run()` 的 core 是 v1 legacy，不参与 v2 组合）。
**⇒ 由事实 7 得出一处口径纠正**：诊断表**不得**用逐 sleeve 回测（见 §7.2）。

**守猪待兔历史**：`Data/raw/shoutu_history.csv`，3587 行，2024-04-23 ~ 2026-09-24，
6 个标的（CONL / GDXU / SOXL / TQQQ / UPRO / YINN）；主样本 `config.SYMBOLS = [TQQQ, SOXL, UPRO]`。

---

## 3. 非目标（**明确划界，违反任一条即为超出本 spec**）

1. **不排名、不挑「最优清仓线」**（第 13.1 / 13.2 条 + 13.0「不凭回测挑参数」）
2. **不改变生产输出**：所有新增参数**默认 `None` ⇒ 生产路径逐位不变**（由 §10 的等价性红线常驻守卫）
3. **不接生产**（把守猪待兔正式接入 `run_portfolio` 的 us_equity 核心仓 = **A2**，另立 spec）
4. **不把 `shoutu_history.csv` 写进 `Data/features.csv`**（生产产物零改动）
5. **不动全局 `config.ZONE_EDGES / ZONE_SATURATION`**（会同时改掉市场指数与加密 —— 事实 4）
6. **不改 `RANK_WINDOW`**（裁决④：等自然积累）
7. **不做显著性检验**（事件重叠、单段行情 ⇒ 本结论是**量级估计**）

---

## 4. 变体定义

四条曲线：`B0`（基准）+ 三个守猪待兔变体。守猪待兔 → 系统口径映射为 `(x + 100) / 2`。

| 变体 | 含义 | `edges` | `saturation` | 先验推导（第 8 条：**不是"试出来的"**） |
|---|---|---|---|---|
| **B0** | **市场指数基准**（= 现状生产口径） | — | — | 走 `market_target` 的 `market_core`，即现状，无需推导 |
| **V1** | 守猪待兔 **`+60` 清仓**（现状规则） | `[20, 40, 60, 80]` | `[1.00, 0.75, 0.50, 0.25, 0.00]` | 就是现配置，无需推导 |
| **V2** | 守猪待兔 **`+80` 才清仓** | `[20, 40, 60, **90**]` | `[1.00, 0.75, 0.50, 0.25, 0.00]` | 用户定义的清仓线 `+80` ⇒ 系统口径 `(80+100)/2 = 90`；**只挪贪婪侧末档边界，恐惧侧不动** |
| **V3** | 守猪待兔 **不设清仓线** | `[20, 40, 60, 80]` | `[1.00, 0.75, 0.50, 0.25, **0.25**]` | 复用系统**已有**的 `ZONE_SATURATION[3] = 0.25`，与加密「减至 **25% 底仓**（不清仓——避免完全踏空后续反弹）」**同语义** ⇒ **不新造参数**（第 4B.6 条） |

**为什么 `+80` 需要专用 `edges` 而不是改一个阈值**：`ZONE_EDGES` 的**最后一档边界就是 80**，
守猪待兔 `+60 → 80` **已经落在末档**（`sat = 0.00` = 清仓）。要让 `+60 ~ +80`（系统 80 ~ 90）
落在 `sat = 0.25` 而不是 `0.00`，必须把守猪待兔路径的末档边界抬到 90。

### 4.1 两处**必须明示**的口径选择

| 项 | 选择 | 理由 |
|---|---|---|
| 熔断 / 极恐加仓的**触发源** | **仍以「市场指数」为准**（变体只换五档 `core` 的来源） | 与 `shoutu_core_series` 的既定口径一致（`pipeline.py:474-477`：「唯一差别：档位系数来源；`CORE_CAP` / `MARKET_CORE_RATIO` / 趋势系数全部不变」）。⇒ 这是一个**混合口径**，必须随结果一起标注 |
| **「高情绪区间」定义** | `H = {t : fg_index_t ≥ 80}`（系统自己的「极度贪婪」档） | **与变体无关** ⇒ 四条曲线用**同一批日子**，可比。另附 `H_s = {t : 至少一个主标的的守猪待兔值 ≥ +60}` 作对照列，并给出 `|H ∩ H_s|` |

---

## 5. 架构与注入点

**沿用本仓库分工：纯计算放库里、编排放脚本里。**

| 文件 | 动作 | 内容 | 默认行为 |
|---|---|---|---|
| `fg_system/signal/market_signal.py` | 改 | `market_target(index_value, drawdown, trend, state, market, date=None, prices=None, core=None)` —— `core` 给定时**替换** `market_core(...)` 的结果；`full = CORE_CAP × RATIO × trend` 与 `apply_circuit_breaker` **不变** | `None` ⇒ **逐位不变** |
| `fg_system/pipeline.py` | 改 | `run_portfolio(us_features, crypto_features, write=True, us_core=None)` —— 逐日 `core=us_core[dt]` 透传给 `market_target`（**只作用于 us_equity**，加密不受影响） | `None` ⇒ **逐位不变** |
| `fg_system/pipeline.py` | 改 | `saturation_of(values, edges=None, saturation=None)`；`shoutu_market_saturation(..., edges=None, saturation=None)`；`shoutu_core_series(..., edges=None, saturation=None)` | `None` ⇒ 读全局 `config` ⇒ **逐位不变** |
| `fg_system/shoutu_variants.py` | **新建** | `VARIANTS`（V1/V2/V3 三张表）+ `variant_core_series(us_features, weights, hist, variant)` —— 纯计算、**无 I/O、不打印** | — |
| `scripts/analyze_shoutu_variants.py` | **新建** | 读数据 → 跑 4 变体 × 2 窗口 → 出四张表 + 结论段 | 静态守卫（同既有做法） |
| `tests/test_shoutu_variants.py` | **新建** | 纯函数测试 + **等价性红线**（见 §10） | — |

### 5.1 `variant_core_series` 的契约

```
variant_core_series(us_features, weights, hist, variant)
  → Series（index = us_features.index，值 = 该变体口径下的 us_equity 核心仓）

= CORE_CAP × MARKET_CORE_RATIO["us_equity"]
  × Σ_i( saturation_of(shoutu_symbol_index(...)[i], edges_v, sat_v) × w_i )
  × trend
```

- **必须复用** `pipeline.shoutu_symbol_index` / `pipeline.saturation_of` / `pipeline.risk_weight_series`
  —— **不得**在此重写档位查找或加权逻辑（第 12.26 条⑤：两套写法 = 「分析里的规则 ≠ 生产的规则」）
- `hist` = `loader.load_shoutu_history()` 的**长表**；内部转成宽表（`symbol` 为列、`date` 为索引，
  取 `score` 列）后交给 `shoutu_symbol_index(shoutu_wide=...)`
- **不 shift**：与 `shoutu_core_series` / `market_core` 一致，shift 由下游负责
- `us_features` **必须含 `trend` 列**（由 `run_equity_v2` 产出）；缺列 ⇒ 抛错（不静默按 1.0 处理）
- ⚠️ **数据缺失必须报错**：`hist` 为空、或**主样本三个标的**在 `hist` 里**一个都没有**
  ⇒ 抛错退出，**不得静默回退成基准**（那会把「变体无效应」伪装成「变体无差异」）

---

## 6. 数据流与窗口

```
us_v2  = pipeline.run_equity_v2()          # 只算一次（含 trend），4 变体共用
crypto = pipeline.run_crypto(write=False)  # 只算一次
wide   = pipeline.load_wide(); weights = pipeline.risk_weight_series(wide)
hist   = loader.load_shoutu_history()

B0        : us_core = None
V1/V2/V3  : us_core = shoutu_variants.variant_core_series(us_v2, weights, hist, v)

pf_v   = pipeline.run_portfolio(us_v2, crypto, write=False, us_core=us_core)
base_v = (pf_v["us_core"].fillna(0.0) + pf_v["ammo_us"]).clip(upper=1.0).shift(1)
         # ↑ 与 `cli backtest-v2` 完全同口径（cli.py:395-396）
basket = pipeline.basket_price_series(pipeline.weighted_basket_returns(wide, weights))
f_v    = us_v2.copy()
f_v["target_position"] = base_v
f_v["fg_index"] = us_v2["fg_index"]; f_v["zone"] = us_v2["zone"]
for col in ("open", "high", "low", "close"): f_v[col] = basket
f_v["volume"] = 0.0
strat_v, returns_v = runner.run_single(f_v, "BASKET")   # 组合级（单组合口径）
```

**窗口（双窗口并列）**：

| 窗口 | 区间 | 回答的问题 |
|---|---|---|
| **全历史** | `returns_v` 全段（受指数 warmup 限制，有效信号起点更晚） | 「接入守猪待兔后**长期结果**如何变化」 |
| **纯效应段** | `returns_v.loc["2024-04-23":]` | 「守猪待兔**真正起作用**那段的效应」 |

> ⚠️ **实施修正（2026-09-24）**：本节原写「`2024-04-23` 之前守猪待兔变体会经三级回退
> **与 B0 重合**」—— 该结论**只对 V1 成立**。V2 / V3 改的是**档位表**，而回退后的信号
> （市场指数）**仍会套用各自的变体表**（`pipeline.saturation_of(idx, edges_v, sat_v)`）：
> V2 在 `fg_index ∈ [80, 90)` 给 `0.25`（B0 给 `0.00`）、V3 在 `fg_index ≥ 80` 给 `0.25`
> ⇒ 该日之前 V2 / V3 与基准**不同** ⇒ 全历史窗口对 V2/V3 的含义是
> 「**变体表 + 该日之前用市场指数回退**」，**不是**「效应的稀释版」。
> **实测佐证**：表 2（37 天）与表 2c（8 天）之差 = **+5.07pp**（V2 与 V3 相同），
> 而 V1 两者相同（−0.5589pp）。⇒ 双窗口**仍然必须并列**，但**读法要按上面修正**。

---

## 7. 指标与输出

### 7.1 组合级指标表（变体 × 窗口）

复用 `backtest/runner.py::performance_metrics`（**已有**）：
总收益 / **年化** / **最大回撤** / 年化波动 / Sharpe / **Calmar**。

### 7.2 归因表（回答「谁在拖累」）

⚠️ **不得用逐 sleeve 回测**（事实 7：已知错误口径，实测 −72%）。
改为**归因**：对每个变体，在「高情绪区间 `H`」与「非 `H`」两组日子上，分别汇总
**各标的的加权贡献** `Σ_t (w_i,t × r_i,t)`（`r_i,t` 为该标的 ETF 日收益），
并给出相对 B0 的差。逐标的贡献之和应等于组合篮子收益（可作一致性断言）。

> ⚠️ **实施修正（2026-09-24）**：本节字面公式 `Σ_t (w_i,t × r_i,t)` **不含变体相关项**
> ⇒ 四条曲线的该值**恒等** ⇒「相对基准的差」恒为 0，**无诊断价值**。
> 实现改为 `Σ_t (base_t × w_i,t × r_i,t)`（加各变体**目标仓位** `base_t` 因子），
> 并在 `docs/trading-discipline.md` §14.5 ④ 显式论证该欠定性。

### 7.3 机制性指标表（每变体）

| 指标 | 定义 |
|---|---|
| `sat0_days` / `zero_share` | `core_v == 0` 的天数 / 占有效天数的比例 |
| `avg_flat_run` / `max_flat_run` | 连续 `core_v == 0` 的**平均 / 最长**长度（交易日） |
| `reentry_lag_median` | 从「守猪待兔 `≥ +60` 的 episode 结束」到 `core_v > 0` 的**中位天数**（V3 预期为 0 —— 它从不清仓） |
| `order_count` | `strat_v.order_count`（换手代理；与第 5.3 条「月操作次数 ≤ 4」口径相关） |
| `avg_position` | `base_v` 在**有效天**（非 warmup）的均值 |

### 7.4 高情绪区间相对收益差

- `r_v` = `returns_v`（`runner.run_single` 返回的**组合净值日收益**）
- `Δ_v = Σ_{t ∈ H} (r_v,t − r_B0,t)`（**pp，每 1 元组合**）；同时报 `mean` 与 `Σ`
- 附 `H_s` 对照列与 `|H ∩ H_s|`
- ⚠️ 这是**描述性统计**，**不构成**「谁更好」的判据（见 §8）

### 7.5 结论段（措辞强制）

必须包含以下三点，缺一不可：

1. 一句话**量级**（各变体相对 B0 的差异幅度）
2. **机制性发现**（暴露时长 / 买回延迟的结构性事实）
3. **纪律声明**：「**不排名、不挑最优；回测不作为改规则的依据**；改不改、改哪个值由
   **先验推导 + 真实操作复盘**（§13.6 O4 / 第 8.4 条三振）决定」

---

## 8. 结论纪律（**本 spec 的核心约束**）

| 条文 | 原文要点 | 对本步的约束 |
|---|---|---|
| 第 **13.1** 条 | 「**自此停止以回测为依据的参数迭代**」 | A1 **不得**用于挑清仓线 |
| 第 **13.2** 条 | 「**禁止**再用「回测年化 / 回撤」讨论系统的**有效性**」 | A1 的年化/回撤/Calmar 只能作**机制性描述**，**不得**作有效性判据 |
| 第 **13.0** 条 | 13.4 闸门**不适用**；但「先文档、一次只改一件、能写出**先验推导**、**不凭回测挑参数**」**继续适用** | 若后续要改规则，必须先有**先验推导**，不得以 A1 的数字为依据 |

**⇒ A1 只回答**：「这条规则值得不值得继续研究 / 差异有多大」。
**⇒ A1 不回答**：「哪个清仓线最好」。

---

## 9. 错误处理与必须随结果标注的明示项

**错误处理**：
- 守猪待兔数据缺失/空/主样本零覆盖 ⇒ **抛错退出**（不静默回退，见 §5.1）
- 变体表与 `saturation` 长度不匹配（`len(saturation) != len(edges) + 1`）⇒ 抛错
- 窗口内有效收益为空 ⇒ 该行指标写 `NaN` 并**明确标注**，不填 0

**明示项（必须随结果一起写进文档）**：

| # | 明示内容 | 方向影响 |
|---|---|---|
| 1 | `RANK_WINDOW = 756`（3 年）未满 ⇒ 实际走 **`fixed`** 口径（`(x+100)/2`），**不是** `percentile`（裁决④：不改窗口，等自然积累，约 2027-04） | 结论只属 `fixed` 口径 |
| 2 | 守猪待兔历史仅 **2.4 年**（2024-04-23 ~ 2026-09-24）⇒ 年化 / Calmar 是**量级估计**，被单段行情主导 | 不可当统计推断 |
| 3 | **熔断 / 极恐加仓仍以市场指数为触发源**（混合口径，§4.1） | 变体只换五档 core 来源 |
| 4 | 组合级用「**加权篮子 + `FgStrategy` 单组合口径**」（本仓库既定做法） | 与真实多标的执行有差 |
| 5 | 佣金 / 滑点按 `config.COMMISSION` / `config.SLIPPAGE` 计入（回测内），但**未建模**：汇率、税、申购赎回、借券成本 | — |
| 6 | **不做显著性检验**（事件重叠、单段行情、非独立样本） | 量级估计 |

---

## 10. 测试策略（TDD）

### 10.1 等价性红线（**最重要，逐条常驻**）

| 断言 | 意义 |
|---|---|
| `saturation_of(v)` == `saturation_of(v, config.ZONE_EDGES, config.ZONE_SATURATION)` | 参数化不改默认 |
| `market_target(...)`（不传 `core`）== `market_target(..., core=None)` | 同上 |
| `run_portfolio(us, cr, write=False)` == `run_portfolio(us, cr, write=False, us_core=None)`（**逐位相等**） | 生产组合路径零改动 |
| `shoutu_core_series(us, w, wide)` == `shoutu_core_series(us, w, wide, edges=config.ZONE_EDGES, saturation=config.ZONE_SATURATION)` | 同上 |

### 10.2 变体表正确性

- **V1 一致性**：`variant_core_series(..., V1)` == 现成 `shoutu_core_series(...)`（**构造一致性**）
- **V2 边界**：`saturation_of([80, 90], edges=[20,40,60,90], sat=...)` ⇒ `[0.25, 0.00]`
  （守猪待兔 `+60`→系统 `80` 落**档 3**；`+80`→系统 `90` 落**档 4**）
- **V3 非零**：非 warmup 期 `variant_core_series(..., V3) > 0` 恒成立
- **V1 vs V3 差异**：存在日子使 V3 的 core > V1 的 core（否则变体没生效）
- 变体表长度约束（§9）与缺失数据抛错（§5.1）

### 10.3 静态守卫（`tests/test_analyze_shoutu_variants.py`，同既有做法）

- 脚本**必须**调用 `shoutu_variants.*` 与 `runner.performance_metrics`（不得自算指标）
- 脚本**不得**出现 `"TQQQ" / "SOXL" / "UPRO"` 字符串字面量（走 `config`）
- 脚本**不得**直接读 `config.ZONE_EDGES` 覆盖变体（变体表必须来自 `shoutu_variants.VARIANTS`）

---

## 11. 实施任务清单

1. **库层**：`market_target(..., core=None)` + 等价性红线测试
2. **库层**：`run_portfolio(..., us_core=None)` + 等价性红线测试
3. **库层**：`saturation_of` / `shoutu_market_saturation` / `shoutu_core_series` 参数化 + 等价性红线测试
4. **库层**：新建 `fg_system/shoutu_variants.py`（`VARIANTS` + `variant_core_series`）+ 测试（§10.2）
5. **脚本**：新建 `scripts/analyze_shoutu_variants.py` + 静态守卫
6. **出数**：四张表 + 结论段（§7）
7. **回写**：结论进 `docs/trading-discipline.md`（§12）

---

## 12. 实施后需回写 `trading-discipline.md` 的事项

1. **A1 的四张表**（组合级指标 / 归因 / 机制性 / 高情绪区间）
2. **结论纪律声明**（§8：不排名、不挑最优、不构成改规则授权）
3. **明示项 1~6**（§9）
4. **§13.6 O4 更新**：把 A1 的结论写进 O4 的「观察」列（含机制性事实，如买回延迟），
   并保持触发条件为「真实操作 ≥ 3 次复盘质疑 / 组合级证据」
5. **本 spec 的两处纠正**（§2 事实 2/3 的注入点纠正、事实 7 的诊断口径纠正）——
   它们也是**给 A2 的前置知识**，必须在文档里留痕

---

## 13. 风险与未知

| # | 风险 / 未知 | 处理 |
|---|---|---|
| 1 | 守猪待兔仅 2.4 年 ⇒ 年化/Calmar 不稳 | 双窗口并列 + 明示为量级估计（§9-2） |
| 2 | 2024-04 前回退 ⇒ 全历史窗口稀释 | 双窗口并列（§6）；⚠️ **只有 V1 在 `2024-04-23` 之前与基准重合**，V2/V3 为「变体表 + 市场指数回退」（见 §6 实施修正注） |
| 3 | 参数化引入新参数面（`edges` / `saturation` / `core` / `us_core`） | **默认 `None` 零影响** + 4 条等价性红线（§10.1） |
| 4 | 混合口径（熔断/极恐仍市场指数触发） | 明示（§4.1 / §9-3）；「守猪待兔 keyed extremes」列为**未做**，属 A2 范围 |
| 5 | 「高情绪区间」定义有多种合理选择 | 用 `fg_index ≥ 80`（与变体无关）+ 附 `H_s` 对照列（§4.1） |
| 6 | 单段行情（2024-2026）可能不代表未来 | 明示；不做显著性检验（§9-6） |

---

## 附：为什么选「参数化 + 离线跑批」（方案 A）而不是 B / C

| 方案 | 做法 | 为何不选 |
|---|---|---|
| **A** | 给 `market_target` / `run_portfolio` / `saturation_of` 等加**可选参数**（默认 `None` = 现行为）+ 新建离线编排脚本 | ✅ **选它** —— day loop / 状态机 / 熔断 / 弹药池**只有一份实现**，且默认路径**逐位不变**（可被等价性红线常驻锁住） |
| B | 新建 `fg_system/variant.py` **复制** day loop 换成守猪待兔 core | ❌ ammo / 熔断 / 跨日状态机出现**两份** ⇒ 未来任何修正都要改两处，正是第 12.26 条⑤ 那类静默分歧 |
| C | 纯脚本自算 core + target（不复用 pipeline） | ❌ 等于**重写**仓位合成 ⇒ 分歧风险最高，且无法复用既有回归测试 |
