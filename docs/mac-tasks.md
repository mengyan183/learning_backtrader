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

| MT-04 | **A3c 尝试台账落地**（`attempts-ledger.jsonl`） | 规划 v2.0 A3c（`docs/2026-10-12-贪恐系统迭代规划v2.0.md`）：仓库**没有**机器可读的"曾试过 N 次"计数器 ⇒ 回顾性校正（A3a Deflated Sharpe / A3b BH-FDR）在数据上做不了。落地定义已定：路径 `evolution/attempts-ledger.jsonl`；字段 `{ts, kind: factor_screen\|variant\|hypothesis, key, verdict, git_sha}`；**幂等键 = `git_sha + kind + key`**（防重复登记虚增 N）；追加点 = `scripts/factor_screen.py` 结果落盘处 / `scripts/evolve_variant.py` / `scripts/verify_hypotheses.py`。来源：规划 v2.0 A3c（离线，无公网依赖） | `evolution/attempts-ledger.jsonl` 存在且 schema 正确；`test_attempts_ledger_appended`（给定固定调用 ⇒ 台账**行数 +1** 且新行字段齐全）；幂等键去重（重复调用不虚增）；全量 pytest 绿 | 待做 |
| MT-05 | **A3b BH-FDR 实现 + 已知答案自检** | 规划 v2.0 A3b：用于「一组并列假设各自检验」（与 A3a 不可互相替代）。落地定义：`test_fdr_known_answers`（用已知 p 值集合校验 BH 实现）；对 H 系列产出"校正后仍成立"清单。依赖 MT-04 台账对未来生效（历史部分标注"不可枚举"）。来源：规划 v2.0 A3b（离线） | `fg_system/`（或 `scripts/`）存在 BH-FDR 实现；`test_fdr_known_answers` 用已知 p 值集合通过；对 H 系列输出校正清单；全量 pytest 绿 | 待做 |
| MT-06 | **A3a Deflated Sharpe 方法就绪（不产结论）** | 规划 v2.0 A3a（v2.2 降级）：现阶段**只出两项** —— ① 方法就绪（公式 + 已知答案样例自证）；② "历史尝试不可枚举"的显式声明。**不得**输出"校正后仍显著"清单（那需要 N，而 N 来自 MT-04 台账满 12 个月）；产出**禁止**喂 `evolve_propose`。来源：规划 v2.0 A3a（离线） | 方法就绪文档 + 已知答案样例自证（公式复算一致）；显式声明"历史尝试不可枚举，A3a 现阶段不出结论"；无任何"校正后仍显著"输出 | 待做 |

## 默认动作（不占编号）

- 每日链 05:30（数据+指数+简报）/ 假说重检 18:00 / C-5 季度 walk-forward：**已由 launchd 自动跑**，无需登记。
- 本清单为空时：以 `docs/dual-end-workflow.md` A 类表 + `docs/NEXT-SESSION.md` 为准自查。

---

## 已完成（留痕）

| 编号 | 任务 | 完成依据 | 完成日期 |
|---|---|---|---|
| （暂无） | | | |
