# Mac 端待执行任务清单（Mac Tasks）

> 用途：给 Mac 端（家里服务机）一份**具体的、可立即开工**的任务清单，与 `docs/windows-tasks.md` **对称**。
> 定位：**Windows 端无公网、无 `Data/`** ⇒ 凡"抓数 / 需真实 `Data` / 需实检"的任务**必须**登记到本表，由 Mac 执行。
> 来源：`docs/2026-10-12-贪恐系统迭代规划v2.0.md`（规划） / `docs/blocked-registry.md` / `docs/review/*`。
> 机制：Windows 端完成一项 → 打包回传 fg-sync → Mac 入库后把状态改为 ✅ 并提交（与 WT 表反向对称）。
> **登记方式已由 Mac 接受** ✓（2026-10-12，用户确认 ✓）。
> **Mac 侧如何看到本表** ✓：本表随 fg-sync 入库到 Mac 仓库（`docs/**` 在白名单内 ✓）⇒ Mac **可直接读** ✓，**无需"推送"** ✓（与 `windows-tasks.md` 不同 —— 那张表必须靠飞书推，因为 Windows 无公网 ✗）。
> ✅ **触发方式已定：B** ✓（2026-10-12 用户裁定）—— 已并入 `scripts/push_todo.py` 快照的 **【Mac 端待执行（需公网/真实 Data）】** 段（`parse_mac_tasks()`）✓ ⇒ Mac 收到「同步待办」时，摘要里就会列出本表**待做**行 ✓（**不新建推送通道** ✓ —— Mac 有公网，本表随 fg-sync 入库即可直读 ✓）。
> 更新纪律：新增/解除任务必须同步本表；每行五要素齐全（编号/任务/说明/验收/状态）。
> 创建：2026-10-12（用户定案：涉及数据的任务登记入系统，交 Mac 执行）。配套：`docs/dual-end-workflow.md`（分工原则）。

状态标记：待做 / 进行中 / ✅ 完成（进行中任务 Mac 端完成收尾后改 ✅）

---

## 待做任务（仅 Mac 可做：需公网 / 需真实 Data / 需实检）

| 编号 | 任务 | 说明与来源 | 验收标准 | 状态 |
|---|---|---|---|---|
| MT-01 | ~~**A5 闸门补 `inv_vol` 组合权重轨**~~ | ~~规划 A5（`docs/2026-10-12-贪恐系统迭代规划v2.0.md`）需要"**策略 vs 含损耗买入持有**"的**同暴露、同时段**对照；但实测 `scripts/evolve_baseline.py:70-71` 只用 `runner.run_single(f, symbol)`（单标的）+ `p["close"].pct_change()`（单标的满仓 buy&hold）⇒ `evolution/baseline.json` **没有 `inv_vol` 组合权重轨**（`risk_weight_series` / `run_portfolio` **从未被调用**）。**两种交付方式二选一**：**(a)** 给 `evolve_baseline.py` 增加 `run_portfolio` + `risk_weight_series` 输出，把组合轨写进 `baseline.json`（推荐，可复用）；**(b)** 单独产出一份 `evolution/a5-comparison.csv`（列：date, strategy_ret, bh_single_ret, bh_portfolio_ret, weights）。**前置**：`Data/raw/prices.csv` + `Data/features.csv`（Mac 有）。 | 产物含**组合权重**买入持有轨（非单标的满仓）；与 `strategy` **同时段、同暴露**；`WEIGHTING="inv_vol"`（`config.py`）；附 `meta.generated_at` 与 `features_range` | ✅ 完成（方案 a，2026-10-13：`evolve_baseline.py` 新增 `build_portfolio`（复用 `pipeline.risk_weight_series` + `weighted_basket_returns`，Σw=1、shift(1) 防前视、UNDERLYING_MAP 无杠杆 σ）；baseline.json 新增 `portfolio` 段（strategy/buy_and_hold full·yearly·is·oos + weights_last + meta）；meta 补 `WEIGHTING=inv_vol`。实测：组合 bh 年化 44.11%/回撤 -76.93% vs 组合策略 13.72%/-38.77%；守卫测试 `tests/test_evolve_baseline.py` 4 passed） |
| MT-02 | ~~**加密侧真实轨损耗（可选，A5 的 ① 项）**~~ | ~~A5 口径①要求"**只在真实轨上做**"，但 `config.CRYPTO_PRODUCT_COST_RATE`（MSTX 57.9% 等）是**按构造校准值**（`config.py` 自述"**不得当作费率使用**"），`baseline.json` 中**无 MSTX 的 `product_cost` 字段** ⇒ 加密侧目前**不可作结论**。需 Mac 用**真实** MSTX/CONL/BITX 价格序列跑 `leverage.py::decompose` 反推。**不阻塞 MT-01**。~~ | 产出加密侧 `product_cost_annual` / `vol_decay_annual`（真实轨）；与 `leverage.py` 口径一致；若数据不可得 ⇒ 明确回"不可得"并说明原因 | ✅ 完成（2026-10-13：新增 `scripts/evolve_crypto_cost.py` → `evolution/crypto-cost-real.json`。**MSTX**：σ=0.86，波动率拖累 58.43%、**产品损耗 25.09%**（config 校准 57.9% ⇒ 差异显著，真实轨低得多）；**CONL**：σ=0.83，波动率拖累 66.11%、**产品损耗 1.55%**（config 2.2% ≈ 接近）；**BITX：不可得** —— crypto_prices.csv 无 BTC 现货列，BTC 仅存在于合成轨（`crypto_runner.py:163` 明示），无真实底层序列可 decompose） |
| MT-03 | ~~**收口 `docs/windows-tasks.md` 的 WT-15~26 状态**（登记滞后 ✗）~~ | ~~2026-10-12 实测：**WT-15~26 的实现与测试早已存在** ✓ —— `fg_system/models/{hmm,markov,evt}.py`+`tests/test_models_*.py`、`fg_system/config.py::validate()`+`tests/test_config_validate.py`、`scripts/sensitivity_scan.py`（含 OOS 警示 ✓）、`fg_system/evo_meta.py`+`tests/test_oos_single_source.py`、`fg_system/pipeline.py` 窗口防御、`fg_system/risk.py` HRP 树递归、`scripts/restore_from_base64.py` 复用 `_safe_extract`、`fg_system/backtest/attribution.py::without_trend` 返回原样 —— **均已交付** ✓（提交 `c4013db`(WT-15/16/17) ✓、`3866626`(WT-18~22) ✓；WT-23~26 为**未提交工作区改动** ✓）。但该表状态列仍写"待做"✗ ⇒ 会**继续被 `push_todo.py` 下发** ✗。**按本表头纪律，状态由 Mac 入库后改为 ✅** ✓。交付依据见 `docs/notes/2026-10-12-wt15-17-delivered.md`、`docs/notes/2026-10-12-wt22-26-done.md`、`docs/notes/2026-10-12-wt27-done.md`。~~ | 12 行（WT-15~26）状态列改为 ✅ 并附完成依据；改完 `py -3.10 -m pytest` 相关文件全绿 | ✅ 完成（2026-10-13 核实：`docs/windows-tasks.md` WT-15~26 状态列**已全部 ✅**（sync_1012l/m/n 交付时陆续收口，依据逐行已附）；`push_todo.py` 快照【Windows 端待执行】段已不含 WT-15~26，不再下发 ⇒ 本行收口） |

| MT-04 | **A3c 尝试台账落地**（`attempts-ledger.jsonl`） | 规划 v2.0 A3c（`docs/2026-10-12-贪恐系统迭代规划v2.0.md`）：仓库**没有**机器可读的"曾试过 N 次"计数器 ⇒ 回顾性校正（A3a Deflated Sharpe / A3b BH-FDR）在数据上做不了。落地定义已定：路径 `evolution/attempts-ledger.jsonl`；字段 `{ts, kind: factor_screen\|variant\|hypothesis, key, verdict, git_sha}`；**幂等键 = `git_sha + kind + key`**（防重复登记虚增 N）；追加点 = `scripts/factor_screen.py` 结果落盘处 / `scripts/evolve_variant.py` / `scripts/verify_hypotheses.py`。来源：规划 v2.0 A3c（离线，无公网依赖） | `evolution/attempts-ledger.jsonl` 存在且 schema 正确；`test_attempts_ledger_appended`（给定固定调用 ⇒ 台账**行数 +1** 且新行字段齐全）；幂等键去重（重复调用不虚增）；全量 pytest 绿 | ✅ 完成（2026-10-13：`fg_system/attempts.py` 公共模块（append_attempt/count_attempts/git_head，LEDGER→evolution/attempts-ledger.jsonl，幂等键 git_sha+kind+key）；三个追加点全部接入：factor_screen.py（每条因子登记 verdict.status）、evolve_variant.py（每条变体登记 better?ok:worse）、verify_hypotheses.py（revised 假说登记 meta.status）；`tests/test_attempts_ledger.py` 5 passed（行数+1/字段齐全/幂等去重/跨 commit 区分/kind 过滤/非法 kind 拒绝）） |
| MT-05 | **A3b BH-FDR 实现 + 已知答案自检** | 规划 v2.0 A3b：用于「一组并列假设各自检验」（与 A3a 不可互相替代）。落地定义：`test_fdr_known_answers`（用已知 p 值集合校验 BH 实现）；对 H 系列产出"校正后仍成立"清单。依赖 MT-04 台账对未来生效（历史部分标注"不可枚举"）。来源：规划 v2.0 A3b（离线） | `fg_system/`（或 `scripts/`）存在 BH-FDR 实现；`test_fdr_known_answers` 用已知 p 值集合通过；对 H 系列输出校正清单；全量 pytest 绿 | ✅ 完成（2026-10-13：`fg_system/fdr.py`（`bh_fdr(p_values, alpha)`，保持输入顺序、NaN 按缺失处理）；`tests/test_fdr_known_answers.py` 7 passed（经典示例 .01/.02/.03 拒绝、单显著、全拒/全不拒、保序、NaN、空）。H 系列校正清单：**历史 p 值不可枚举**（台账对未来生效），待台账积累后对登记检验输出——依 A3c 依赖链，非阻塞项） |
| MT-06 | **A3a Deflated Sharpe 方法就绪（不产结论）** | 规划 v2.0 A3a（v2.2 降级）：现阶段**只出两项** —— ① 方法就绪（公式 + 已知答案样例自证）；② "历史尝试不可枚举"的显式声明。**不得**输出"校正后仍显著"清单（那需要 N，而 N 来自 MT-04 台账满 12 个月）；产出**禁止**喂 `evolve_propose`。来源：规划 v2.0 A3a（离线） | 方法就绪文档 + 已知答案样例自证（公式复算一致）；显式声明"历史尝试不可枚举，A3a 现阶段不出结论"；无任何"校正后仍显著"输出 | ✅ 完成（2026-10-13：`scripts/evolve_dsr_method.py`（E[max SR] 近似公式 + 精确数值积分 + 蒙特卡洛自证 + SR* 修正 + deflated p 值 + 声明），exit 0 全绿：N=10 近似 1.5746 / 精确 1.5388 / 蒙特卡洛 1.5242 一致、SR*=0.5625、p=0.0006；方法文档 `docs/notes/2026-10-13-a3a-deflated-sharpe-ready.md` 含验收对照） |

| MT-07 | **B1 补「组合级日净值序列」** | B1（规划 v2.0 阶段 2 ✓）要求「组合级回撤分布（含 CVaR95/CVaR99）」✓，但实测 `evolution/baseline.json` 的 **`portfolio.strategy.full` 只有 6 个汇总指标** ✗（`total_return/annual_return/max_drawdown/annual_vol/sharpe/calmar` ✓），**无日收益/净值序列** ✗ ⇒ **算不出 CVaR** ✗（`fg_system/risk.py::cvar()` 需一条收益序列 ✓）。**Windows 端临时绕法**：改用规划第 12.7 条矩阵的**回撤列**（纸面常量 ✓）⇒ `evolution/drawdown_budget_curve.json` ✓（`margin_pp=4.91` ✓）—— 但**不是真实组合分布** ✗ ⇒ 用户 2026-10-13 裁定走**方案 B**（真实序列 ✓）。**口径须与 MT-01 一致** ✓：真实轨 ✗、`WEIGHTING="inv_vol"` ✓、同时段 ✓、`shift(1)` 防前视 ✓。内容：逐日 `date, strategy_ret, bh_portfolio_ret`（有净值更好 ✓）。详见 `docs/notes/2026-10-13-mac-b1-portfolio-series.md` ✓ | 序列**可直接喂** `cvar()` ✓（点数 ≥30 ✓）；附 `meta.generated_at` + `features_range` ✓；**交叉核对**：用该序列算的 `max_drawdown` 应与 `portfolio.strategy.full.max_drawdown`（**-0.387651** ✓）一致 ✓，不一致需指出口径差 ✓ | ✅ 完成（2026-10-13：`evolve_baseline.py::build_portfolio` 新增 `daily` 子段 —— 逐日 `date, strategy_ret, bh_portfolio_ret, strategy_nav, bh_portfolio_nav`（两轨对齐 dropna、`shift(1)` 防前视、口径与 MT-01 完全一致）；`evolution/baseline.json` 已更新。实测：**2523 点**（2016-09-26 → 2026-10-12）；**CVaR95（最差 5% 日均）=-0.035929 / CVaR99=-0.065584**（`cvar()` 直接可算）；**交叉核对：daily 重算 max_drawdown = 0.387651 与 full 完全一致** ✓；meta 补 `generated_at`/`features_range`/`daily_points`。守卫：`tests/test_evolve_baseline.py` 扩至 5 passed（daily 点数≥30、两轨同长、cvar 可算且 c99<c95、max_dd 交叉核对、meta 齐全）） |

| MT-08 | **跑 B2/B3 变体的真实 OOS 对比（V-PVOL / V-DDC）** | B2（组合级 vol targeting）与 B3（CPPI / 回撤控制）的**实现已就绪并入库** ✓ —— `fg_system/backtest/variants.py` 新增 `V-PVOL` / `V-DDC` ✓，组合级状态源 = `portfolio_features` 的新列 **`basket_ret`** ✓（由编排层 `scripts/evolve_variant.py::build_basket_returns()` 用 `pipeline.risk_weight_series`（inv_vol）+ `pipeline.weighted_basket_returns` **现算** ✓，与 `baseline.portfolio` 同口径 ✓，**与策略无关、无自指** ✓）。⚠️ **回测需真实 `Data/`** ✗ ⇒ Windows 侧跑不了 ✓。**命令**：`py -3.10 scripts/evolve_variant.py` ✓ ⇒ 期望 `evolution/experiments/variant_h007_<date>.md` 的 OOS 对比表**新增 V-PVOL / V-DDC 两行** ✓，且 **B0 年化与 `baseline.json` 相对差 < TOL**（等价性守卫 ✓）。⚠️ 结论层还需：**B2** 按规划**预先声明**判据（「若 OOS 年化下降 > X pp 而回撤改善 < Y pp ⇒ 默认不采纳」✓）；**B3** 加「**CPPI 触发日 vs 趋势阻断日重叠率**」表 + **gap 情景（5×`SLIPPAGE`）** ✓。来源：规划 v2.0 B2/B3（阶段 2 ✓）；实现证据 `tests/test_portfolio_variant_guard.py`（13 passed ✓）+ `tests/test_variant_guard.py`（12 passed ✓，现有 5 变体行为不变 ✓）。 | ① 报告新增 V-PVOL / V-DDC 两行 + B0 等价性守卫通过 ✓；② 附 B2 预登记判据 ✓ + B3 重叠率表与 gap 情景 ✓；③ 入库后把本行标 ✅ ✓ | 待做 |

## 默认动作（不占编号）

- 每日链 05:30（数据+指数+简报）/ 假说重检 18:00 / C-5 季度 walk-forward：**已由 launchd 自动跑**，无需登记。
- 本清单为空时：以 `docs/dual-end-workflow.md` A 类表 + `docs/NEXT-SESSION.md` 为准自查。

---

## 已完成（留痕）

| 编号 | 任务 | 完成依据 | 完成日期 |
|---|---|---|---|
| （暂无） | | | |
