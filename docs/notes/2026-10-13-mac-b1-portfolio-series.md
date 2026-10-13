# 【Windows 端 → Mac 端】请为 B1 补「组合级日净值序列」（MT-07）

> 本文即发给 Mac 的 prompt 原文（用户手动转发）。留档备查。
> 背景：规划 v2.0 **阶段 2 已开工** ✓ —— **D2 ✓ / D7 ✓ 已完成**；**B1 选「方案 B」**（用**真实组合序列**算 CVaR ✓，不用纸面矩阵 ✗）。

---

**【Windows 端 → Mac 端】请执行 MT-07**

## 为什么要做（实测依据 ✗✓）

B1 要求把 `CORE_CAP`/`AMMO_CAP` 与「**组合级回撤分布（含 CVaR95/CVaR99）**」画成曲线 ✓。
但实测 `evolution/baseline.json` 的 **`portfolio.strategy.full` 只有 6 个汇总指标** ✗：

```
portfolio 键: ['strategy', 'buy_and_hold', 'weights_last', 'meta']
strategy.full 键: ['total_return','annual_return','max_drawdown','annual_vol','sharpe','calmar']
```

⇒ **没有日收益/净值序列** ✗ ⇒ **算不出 CVaR** ✗（`fg_system/risk.py::cvar(returns, alpha)` 需要一条收益序列 ✓）。

**Windows 端当前绕法（临时 ✓，非 B1 原意 ✗）**：改用规划第 12.7 条矩阵的**回撤列**（纸面常量 ✓），已产出 `evolution/drawdown_budget_curve.json` ✓（`margin_pp=4.91` ✓、`tail={cvar95:-0.49945, cvar99:-0.5168}` ✓）—— 但它**不是真实组合回撤分布** ✗ ⇒ 用户已裁定走 **方案 B** ✓。

## 任务（MT-07）

给 `evolution/baseline.json` 的 **`portfolio` 段补「日序列」** ✓（或在 `portfolio` 下新增 `daily` 子段 ✓ / 或单独产出 `evolution/portfolio_series.csv` ✓ —— 你选更顺手的 ✓）。

**口径必须与 MT-01 完全一致** ✓：
- **真实轨** ✓（不是合成轨 ✗）
- **`WEIGHTING="inv_vol"`** ✓（`meta.WEIGHTING` 已是该值 ✓）
- **同时段** ✓（与 `portfolio.strategy` / `portfolio.buy_and_hold` 的 `full` 区间一致 ✓）
- **`shift(1)` 防前视** ✓（MT-01 已用 ✓，保持一致 ✓）

**内容**：逐日 `date, strategy_ret, bh_portfolio_ret`（有净值更好：`strategy_nav, bh_portfolio_nav` ✓）。

**验收**：
1. 序列**可直接喂** `fg_system/risk.py::cvar()` ✓ 算出 `cvar95`/`cvar99` ✓（点数 ≥30 ✓，`cvar` 的门槛 ✓）
2. 附 `meta.generated_at` + `features_range` ✓
3. 若能顺带核对：用该序列算出的 `max_drawdown` 应与现有 `portfolio.strategy.full.max_drawdown`（**-0.387651** ✓）一致 ✓ —— 不一致说明口径有差 ✓，请指出 ✓

## 顺带（本批回传）

`sync_1013f`（随本文一起发 ✓）：B1/D2/D7 三项产出共 **10 个代码/文档文件** ✓ —— 入库后阶段 2 的 **B1（待 MT-07 补序列后重算 ✓）/ D2 ✓ / D7 ✓** 即闭环 ✓。

⚠️ 注意：B1 的 `evolution/drawdown_budget_curve.json` 是**纸面矩阵版** ✓ ⇒ MT-07 交付后**需重跑** `scripts/build_budget_curve.py` 换成真实序列 ✓（届时由 Windows 端或你执行 ✓，请指定 ✓）。

---

**输出方式（二选一）**
1. 直接改 `evolution/baseline.json`（或新增产物）并提交 ✓ + 把 `docs/mac-tasks.md` 的 MT-07 标 ✅ ✓；
2. 或回一份说明（做了什么 + 产物路径 + 验收数字）✓，我来登记。
