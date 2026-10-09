# A2-E keyed extremes 量级量化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 量化「把熔断/极恐的触发源换成守猪待兔口径」（`shoutu_keyed_extremes`）对**组合级**表现的量级影响，为 §14.5 O4 提供组合级证据。

**Architecture:** 复用 A1 的框架（`scripts/analyze_shoutu_variants.py` + 加权篮子 + `FgStrategy` 组合口径），把「4 变体 × 2 窗口」扩成「**8 组合**（`{B0,V1,V2,V3}` × `{keyed=False,True}`）**× 2 窗口**」。生产代码**零改动** —— A2 已交付的 `run_portfolio(us_core=…, us_trigger_index=…)` 就是注入点。

**Tech Stack:** Python 3.10 / pandas / numpy / pytest；`py -3.10`（Windows）。

**Spec:** `docs/superpowers/specs/2026-09-28-keyed-extremes-magnitude-design.md`

> ⚠️ **本计划的代码细节以既有脚本结构为准**：`scripts/analyze_shoutu_variants.py` 已实现 A1 的
> 「4 变体 × 2 窗口」全流程。实施者**必须先完整读它**（以及它调用的 `fg_system/shoutu_analysis.py`
> 与 `pipeline.run_portfolio`），再按同样风格扩展 —— **不要另起一套写法**（第 12.26 条⑤）。

---

## 文件结构

| 文件 | 动作 | 职责 |
|---|---|---|
| `scripts/analyze_shoutu_variants.py` | 改 | 加 `keyed` 维度：8 组合 × 2 窗口；出四张表 + 结论段 |
| `fg_system/shoutu_analysis.py` | 可能改 | 若需要「触发频率 / 换手」的**纯计算**函数（保持该模块「不读文件、不打印」的纪律） |
| `tests/test_shoutu_analysis.py` 或 `tests/test_shoutu_variants.py` | 追加 | 新增纯函数单测 + **keyed 历史区间红线** |
| `docs/trading-discipline.md` §14.5 | 改 | A2 小节的「keyed extremes 量级未评估」→ 指向本项结论 |

**不动**：`pipeline.py` / `market_signal.py` / `shoutu_variants.py` / `cli.py`（通路已就绪）。

---

## Task 1: 脚本扩展支持 keyed 维度 + 红线

**Files:**
- Modify: `scripts/analyze_shoutu_variants.py`
- Test: `tests/test_shoutu_variants.py`（追加红线）

- [ ] **Step 1: 先读既有实现**

完整读 `scripts/analyze_shoutu_variants.py`、`fg_system/shoutu_analysis.py`、`fg_system/shoutu_variants.py`，
以及 `pipeline.run_portfolio`（`fg_system/pipeline.py` 的 `us_core` / `us_trigger_index` 两个入参）。
**确认**：现有的 4 变体循环在哪里、`run_variant()` 如何构造 `us_core`、四张表怎么算出来的。

- [ ] **Step 2: 写红线测试（先失败）**

在 `tests/test_shoutu_variants.py` 末尾追加：

```python
def test_keyed_extremes_is_identity_before_effect_window():
    """⚠️ 守卫：`keyed=True` 在守猪待兔覆盖区间**之前**必须与 `keyed=False` 逐位相同。

    依据 A2 spec §6 的关键性质：历史区间守猪待兔无数据 ⇒ `shoutu_symbol_index` 三级回退到
    `fg_index` ⇒ 因 `Σ w_i = 1`，`shoutu_market_index` **逐位等于 `fg_index`**。
    若这条失败 ⇒ keyed extremes 在历史区间改变了行为，与 spec 冲突（且说明实现有问题）。
    """
    idx = pd.date_range("2024-01-01", periods=40, freq="B")
    us = pd.DataFrame({"fg_index": [50.0] * 40, "trend": [1.0] * 40}, index=idx)
    cr = pd.DataFrame({"crypto_fg_index": [50.0] * 40, "trend": [1.0] * 40,
                       "drawdown": 0.0, "warmup": False}, index=idx)
    # 空的守猪待兔宽表 ⇒ 全部回退 fg_index
    trig = pipeline.shoutu_market_index(us, pd.DataFrame({"TQQQ": [0.5] * 40,
                                                          "SOXL": [0.5] * 40}, index=idx),
                                        shoutu_wide=pd.DataFrame(),
                                        symbols=["TQQQ", "SOXL"])
    assert trig.round(9).tolist() == us["fg_index"].round(9).tolist()
```

⚠️ **这条测试的期望值请独立验算**（`shoutu_market_index` 的签名与参数顺序、以及空宽表时的回退路径）。
若你算出不同结论，**以你的验算为准**并在报告里说明。若这条测试与既有测试重复，说明重复之处并改成更有价值的断言。

- [ ] **Step 3: 跑测试确认失败或通过**

Run: `py -3.10 -m pytest tests/test_shoutu_variants.py -k keyed -v`
Expected: 若既有代码已满足 ⇒ **PASS**（那说明 A2 的性质已被覆盖，请在报告中指出并**跳过 Step 4 的实现**，只保留测试）；
若 FAIL ⇒ 继续 Step 4。

- [ ] **Step 4: 扩展脚本**

在 `scripts/analyze_shoutu_variants.py` 里把变体循环扩成**组合**循环：

- 组合集 = `[(variant, keyed) for variant in VARIANT_KEYS for keyed in (False, True)]`（8 个）
- 对每个组合：
  - `us_core` = `None` if `variant == BASELINE` else `shoutu_variants.variant_core_series(us_v2, weights, hist, variant)`
  - `us_trigger_index` = `None` if `not keyed` else `pipeline.shoutu_market_index(us_v2, weights, shoutu_wide)`
  - `pf = pipeline.run_portfolio(us_v2, crypto, write=False, us_core=us_core, us_trigger_index=us_trigger_index)`
- 沿用既有的 `base = (pf["us_core"].fillna(0.0) + pf["ammo_us"]).clip(upper=1.0).shift(1)` 口径
  （**与 `cli backtest-v2` 完全同口径**，脚本里已有注释指明）

- [ ] **Step 5: 跑测试确认通过**

Run: `py -3.10 -m pytest tests/test_shoutu_variants.py -v` ⇒ 全绿
Run: `py -3.10 -m pytest -q` ⇒ **全量**（预期 `776 passed`，零失败）

- [ ] **Step 6: 提交**

```bash
git add scripts/analyze_shoutu_variants.py tests/test_shoutu_variants.py
git commit -m "feat(a2e): analyze_shoutu_variants 支持 keyed 维度（8 组合 × 2 窗口）+ 历史区间红线"
```

---

## Task 2: 出数（四张表 + 结论段）

**Files:**
- Modify: `scripts/analyze_shoutu_variants.py`（输出层）
- 产物：终端输出（不落盘新文件，除非既有脚本已落盘）

- [ ] **Step 1: 实现四张表**

按 spec §7 风险 1 的分表要求输出：

| 表 | 内容 |
|---|---|
| ① 组合级主表 | 8 组合 × 双窗口：年化 / 最大回撤 / Calmar / 高情绪区间相对收益差 |
| ② 增量表 | `keyed=True` 相对 `keyed=False` 的差值（年化差、Calmar 差），逐变体 × 逐窗口 |
| ③ 触发频率 / 换手表 | keyed 口径 vs 市场指数口径的**熔断天数 / 极恐天数**（按窗口分别统计）；以及**调仓次数**（`extreme` 豁免防抖动的后果）；含成本 / 不含成本两版年化 |
| ④ 稳健性对照表 | **主样本（3 标的）** vs **全样本（6 标的）** 的增量对照 |

⚠️ 触发天数 / 换手统计若需要新函数 ⇒ 放进 `fg_system/shoutu_analysis.py`（**纯计算**：不读文件、不打印），
并在 `tests/test_shoutu_analysis.py` 加单测。

- [ ] **Step 2: 跑出数并人工核对**

Run: `cd /d/3-code/learning_backtrader && PYTHONUTF8=1 PYTHONPATH=. py -3.10 scripts/analyze_shoutu_variants.py`

**核对点（必须逐条报告）**：
1. 8 条曲线的指标是否都算出来了（无 NaN 行被静默吞掉）
2. **触发频率对照**是否与 A2 最终评审的已知值一致（单窗口 keyed：熔断 60 天 / 极恐 17 天；
   市场指数：3 天 / 4 天）—— 若差很多，说明口径不同，**必须查明并说明**
3. 历史区间（`2024-04-23` 之前）`keyed=True` 与 `keyed=False` 是否**逐位相同**（红线）
4. 是否出现「差异完全由少数几天主导」的情况（spec §7 风险 5）⇒ 报告触发日的分布

- [ ] **Step 3: 提交**

```bash
git add -A
git commit -m "feat(a2e): keyed extremes 四张表出数（组合级 / 增量 / 触发频率与换手 / 稳健性对照）"
```

---

## Task 3: 文档回写

**Files:**
- Modify: `docs/trading-discipline.md`（§14.5 的 A2 小节）

- [ ] **Step 1: 替换「量级尚未评估」**

把 §14.5 A2 小节里 `keyed extremes` 那行的「⚠️ **其量级尚未评估**」替换为指向本项结论的表述，
并新增一段「**keyed extremes 的量级（A2-E，2026-09-28）**」，内容必须含：
1. 口径（8 组合 × 双窗口、主/全样本、只换指数条件）
2. 四张表的要点数字（**逐位抄自 Task 2 的真实输出，不得概括或四舍五入到失真**）
3. **触发频率对照**（keyed vs 市场指数）
4. ⚠️ **明示：本项只提供组合级证据，不构成扳开建议**（判据不设 go 门，沿用 §14.5 O4）
5. ⚠️ 明示：守猪待兔仅 2.4 年 ⇒ 量级估计；不做显著性检验

- [ ] **Step 2: 提交**

```bash
git add docs/trading-discipline.md
git commit -m "docs(a2e): §14.5 回写 keyed extremes 的量级（组合级证据）"
```

---

## Task 4: 最终验证

- [ ] **Step 1: 全量测试** ⇒ `py -3.10 -m pytest -q`，记录 passed 总数，**零失败**
- [ ] **Step 2: 确认生产代码零改动** ⇒ `git --no-pager diff --stat cc24a25..HEAD -- fg_system/` 只应含
      `shoutu_analysis.py`（若新增纯函数）；`pipeline.py` / `market_signal.py` / `shoutu_variants.py` /
      `cli.py` **不得**出现在本项（A2-E）的 diff 里
- [ ] **Step 3: 确认两个开关默认仍关** ⇒ `py -3.10 -c "import sys;sys.path.insert(0,'.');import inspect;from fg_system import pipeline;print(inspect.signature(pipeline.run_portfolio_v2))"`
- [ ] **Step 4: 工作区干净** ⇒ `git status --porcelain` 为空
- [ ] **Step 5: 记录最终 HEAD**

---

## 自检清单（执行者用）

- [ ] 8 组合 × 2 窗口全部跑出，**无 NaN 静默吞掉**
- [ ] **触发频率对照**已报告，并与已知值（60/17 vs 3/4）对齐或说明差异原因
- [ ] **换手 / 交易次数变化**已报告（`extreme` 豁免防抖动的后果）
- [ ] 含成本 / 不含成本**两版**年化都已报告
- [ ] 历史区间 `keyed=True` == `keyed=False`（红线）
- [ ] 主样本 vs 全样本对照已报告
- [ ] 生产代码零改动（`pipeline.py` / `market_signal.py` / `shoutu_variants.py` / `cli.py` 未变）
- [ ] 文档里**没有**「建议扳开 / 建议不扳开」的措辞
