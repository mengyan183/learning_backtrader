# -*- coding: utf-8 -*-
"""杠杆 ETF 的建仓 / 加仓计划（2026-10-30 用户裁定）。

【为什么需要】
2026 三季度财报季复盘：在杠杆 ETF 上「越跌越买」是**负期望** ✗ ——
3x 从 -50% 回本要 +100%、从 -75% 要 +300%，且震荡市还有 vol decay ✗。
用户要求「少赚少亏但不能巨亏」⇒ 需要把「首建多少、跌多少加、加到哪为止」
写成可执行规则，而不是凭感觉补仓 ✗。

【与既有规则的关系（必须一致，不能各说各话）】
- **纪律 4C.4**：波动率用**无杠杆底层**算（`SIGNAL_UNDERLYING_MAP` 已有映射 ✓）
  ⇒ 本模块的 `atr_pct` 传的是**正股** ATR，不是杠杆 ETF 自身的 ✗
- **纪律 5.1**：相邻两次操作 ≥5 个交易日 ⇒ 加仓间距取 `max(ATR 间距, 5 交易日)` ✓
- **纪律 5.3**：单月 ≤4 次 ⇒ 首建 + **2** 档加仓 = 3 次，留 1 次给减仓 ✓
- **`risk.position_limit`**：1% 规则（净值×1% / 2×ATR20）是**更严**的单标的约束 ✓

【参数状态】
**定版 C（2026-10-30 用户裁定）** ✓，但 **回测样本太少，待丰富回测样本** ✗ ——
6 标的复验后样本外全负、前后半段方向不一致 ⇒ **现有回测不支持该规则** ✗，
既不足以证实也不足以证伪 ✓。
所有数字集中在 `PLAN` 里，回测脚本直接改这个 dict 即可跑变体 ✓。
"""
from fg_system import config

#: 建仓/加仓参数 —— **2026-10-30 定版「C_激进」** ✓（用户裁定：资金量小、偏激进）。
#: 依据：第二轮回测（YINN/GDXU/CONL，2024-04~2026-10）
#:   A 12%/-80 +6.07%/-6.87%（比值 0.88）· E 12%/-75 +5.83%/-6.67%（0.87）
#:   **C 15%/-75 +7.63%/-8.58%（比值 0.89，最高）** · D 现状 20%/-70 +8.00%/-12.20%（0.66）
#: ⇒ C 的风险调整后收益最好，且单笔敞口更大（小资金更需要绝对收益 ✓）。
#: 🔴 **2026-11-24 用户裁定：建仓/加仓规则「废弃」** ✗
#:
#:    回测（`scripts/backtest_position_plan.py`，2024-04 ~ 2026-11，6 标的）：
#:      变体       全样本    样本外    前半段    后半段
#:      A_初版    +1.55%   −1.94%   +3.90%   −2.35%
#:      B_保守    +1.08%   −0.88%   +2.22%   −1.14%
#:      C_激进    +4.40%   −2.39%   +7.86%   −3.46%
#:      D_对照    +3.53%   −2.75%   +7.82%   −4.28%  ← **最烂做法反而最高** ✗
#:
#:    ⇒ **样本外全部为负** ✗；**前后半段方向全部不一致** ✗
#:    ⇒ 平均持仓 0.4~1.3% ⇒ 收益主要来自「几乎空仓」，不是规则 ✗
#:    ⇒ 对照实验（`--source history` 排除口径混用）两版差异 **< 0.2pp**
#:      ⇒ 不是数据口径问题，是规则本身无效 ✓
#:
#:    ⚠️ **废弃的是「建仓/加仓规则」**，不是整个模块 ✗
#:      `leverage_of` / `gap_pct` / `atr_pct_underlying` 仍被
#:      `risk.py` 与简报使用 ✓
#:      `PLAN` 字典**保留**（简报仍展示，但已标注「已废弃」）✓
#:    ⇒ 本条**不构成建仓/加仓依据** ✗
PLAN = {
    "single_cap": 0.15,      # 单标的上限：净值 15%
    "total_cap": 0.20,       # 杠杆 ETF 总敞口：净值 20%（⇒ 满配 1 个 + 半配 1 个 ✓）
    "first": 0.08,           # 首建：净值 8%
    "adds": (0.04, 0.03),    # 2 档加仓 ⇒ 8+4+3 = 15% 正好打满
    "atr_k": 1.2,            # 间距 = 1.2 × ATR20(正股) × 杠杆倍数
    "min_gap_days": 5,       # 纪律 5.1
    "entry_coef": -75.0,     # 守猪待兔系数建仓/加仓线
    "hard_stop": -0.60,      # 浮亏超过 60% ⇒ 禁止加仓（**不清仓** ✓ 用户裁定）
}

#: **无守猪待兔服务端历史**的标的 ⇒ 单标的敞口打回 12% ✓（2026-10-30 用户裁定）
#: 理由：15% 是**回测验证过**的参数（YINN/GDXU/CONL 有 560~640 天历史）；
#: 无历史 ⇒ 15% 对它们是**未验证**的 ✗ ⇒ 用更保守的上限 ✓。
#: 🔴 2026-10-30 用户裁定：**不写死名单** ✗ —— 改成**实时查 `shoutu_history.csv`** ✓
#: ⇒ 服务端哪天补了历史，自动解除 12% 限制，不用改代码 ✓。
HIST_MIN_DAYS = 250          # 至少这么多天才算「有历史」（够跑 1 年滚动 ✓）
NO_HISTORY_CAP = 0.12

#: 最小建仓额（美元）✓ —— 总敞口只剩几美元时不给出「首建 $1」这种无意义建议 ✗
#: （2026-11-23：`total_cap` 改成「剩余额度」后新增的边界 ✓）
MIN_ENTRY = 100.0

_HIST_CACHE = None


def history_days(symbol):
    """该标的在 `shoutu_history.csv` 里的**有效天数** ✓；读不到 ⇒ 0（保守 ✓）。"""
    global _HIST_CACHE
    if _HIST_CACHE is None:
        counts = {}
        try:
            import pandas as pd
            df = pd.read_csv(config.SHOUTU_HISTORY_PATH)
            counts = df.groupby("symbol").size().to_dict()
        except Exception:                  # noqa: BLE001 —— 文件缺/坏 ⇒ 全按无历史 ✓
            counts = {}
        _HIST_CACHE = counts
    return int(_HIST_CACHE.get(str(symbol or "").upper(), 0))


def has_history(symbol, min_days=None):
    """是否有足够的守猪待兔历史 ✓（决定给 15% 还是 12%）。"""
    return history_days(symbol) >= (min_days or HIST_MIN_DAYS)

#: 杠杆倍数分组（复用 config 的守猪待兔分组，避免两处口径打架 ✗）
LEVERAGE = {}
for _s in config.SHOUTU_LINES_3X:
    LEVERAGE[_s] = 3
for _s in config.SHOUTU_LINES_2X:
    LEVERAGE[_s] = 2
for _s in config.SHOUTU_LINES_1X:
    LEVERAGE[_s] = 1


def leverage_of(symbol):
    """标的的杠杆倍数 ✓；未登记 ⇒ 1（按无杠杆处理，不猜 ✗）。"""
    return LEVERAGE.get(str(symbol or "").replace("-USDT", ""), 1)


def gap_pct(symbol, atr_pct):
    """加仓间距（%）：`1.5 × ATR20(正股) × L` ✓ —— 纪律 4C.4 的口径。

    `atr_pct` 必须是**正股**的 ATR（小数，如 0.015 = 1.5%）✗ 不能传杠杆 ETF 自身的 ✗。
    ATR 缺失 ⇒ 返回 None（不猜 ✗）。
    """
    if atr_pct is None:
        return None
    return PLAN["atr_k"] * float(atr_pct) * leverage_of(symbol) * 100.0

# ============================================================================
# 🔴 **2026-11-25 已删除**：`build_plan` / `brief_line` / `has_history` /
#    `history_days`（约 150 行）✗
#
#    原因（`docs/rules-2026-11-20.md` 12.64 / 12.66）：
#      回测 2024-04~2026-11、6 标的 ⇒ **样本外全部为负**（−0.88% ~ −2.75%）
#      **前后半段方向全部不一致** · 平均持仓仅 **0.4~1.3%**
#      ⇒ 收益来自「几乎空仓」，不是规则 ✗
#
#    删除前的状态：唯一调用方 `invest_research.position_plan_brief` 已恒返回
#    None（2026-11-25 第一步清理）⇒ 这 4 个函数**无任何生产调用方** ✓
#
#    ⚠️ **规则本身没有消失** —— 可执行定义在 `scripts/backtest_position_plan.py`
#       的 `VARIANTS`（A/B/C/D/E 五个变体）里，随时可用
#       `python scripts/backtest_position_plan.py --source history` 重新验证 ✓
#       ⇒ 所以「样本变长后重新验证」**不需要重写这 150 行** ✓
#
#    **保留**（仍被生产使用）：
#      · `PLAN`（`atr_k` 被 `gap_pct` 用；`total_cap` 被 `risk_brief_text` 用）
#      · `leverage_of` / `gap_pct`（`risk.py` 依赖）
# ============================================================================
