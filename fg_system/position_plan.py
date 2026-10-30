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
初版参数（下表）**待回测确认** ✗ —— 用户要求「先改参数 → 回测验证 → 多轮后定终版」。
所有数字集中在 `PLAN` 里，回测脚本直接改这个 dict 即可跑变体 ✓。
"""
from fg_system import config

#: 建仓/加仓参数 —— **2026-10-30 定版「C_激进」** ✓（用户裁定：资金量小、偏激进）。
#: 依据：第二轮回测（YINN/GDXU/CONL，2024-04~2026-10）
#:   A 12%/-80 +6.07%/-6.87%（比值 0.88）· E 12%/-75 +5.83%/-6.67%（0.87）
#:   **C 15%/-75 +7.63%/-8.58%（比值 0.89，最高）** · D 现状 20%/-70 +8.00%/-12.20%（0.66）
#: ⇒ C 的风险调整后收益最好，且单笔敞口更大（小资金更需要绝对收益 ✓）。
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
#: AXTX/CRCG 服务端返回 `data: []` ✗ ⇒ 15% 对它们是**未验证**的 ✗
#: ⇒ 未验证的标的用更保守的上限（12% = 第一轮回测里 A 变体的口径 ✓）。
NO_HISTORY_SYMBOLS = {"AXTX", "CRCG"}
NO_HISTORY_CAP = 0.12

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


def build_plan(net_value, symbol, atr_pct, coef, held_value=0.0,
               pnl_pct=None, leveraged_value=0.0, risk_limit=None):
    """算出该标的的建仓 / 加仓计划 ✓。

    :param net_value: 账户净值（美元）
    :param symbol: 标的代码（如 ``YINN``）
    :param atr_pct: **正股** ATR20 占现价比例（小数）；None ⇒ 间距未知
    :param coef: 守猪待兔系数（-100~100）
    :param held_value: 该标的当前市值
    :param pnl_pct: 该标的浮盈亏（%，如 -21.9）
    :param leveraged_value: 杠杆 ETF 总市值（判断总敞口）
    :param risk_limit: 1% 规则给出的上限（美元）；None ⇒ 只用 12%
    :returns: dict（`ok` 表示「现在能不能动手」，`blocked` 给原因）
    """
    lev = leverage_of(symbol)
    # 无守猪待兔历史的标的 ⇒ 敞口打回 12% ✓（15% 对它们未经验证 ✗）
    cap_ratio = (NO_HISTORY_CAP if str(symbol).upper() in NO_HISTORY_SYMBOLS
                 else PLAN["single_cap"])
    single = float(net_value or 0) * cap_ratio
    if risk_limit:
        single = min(single, float(risk_limit))       # 1% 规则更严 ⇒ 以它为准 ✓
    total = float(net_value or 0) * PLAN["total_cap"]

    held = float(held_value or 0)
    room = max(0.0, single - held)
    gap = gap_pct(symbol, atr_pct)

    blocked = None
    if coef is None:
        blocked = "无守猪待兔系数"
    elif float(coef) > PLAN["entry_coef"]:
        blocked = "系数 %.0f 未达 %.0f" % (float(coef), PLAN["entry_coef"])
    elif pnl_pct is not None and float(pnl_pct) <= PLAN["hard_stop"] * 100:
        # 用户裁定：**不清仓**，但也不许加仓 ✓（回本数学，见模块 docstring）
        blocked = "浮亏 %.0f%% 已过 %.0f%% 线：禁止加仓（不清仓）" % (
            float(pnl_pct), PLAN["hard_stop"] * 100)
    elif room <= 0:
        blocked = "已到单标的上限 $%.0f" % single
    elif float(leveraged_value or 0) >= total and held <= 0:
        blocked = "杠杆总敞口已满（上限 $%.0f）" % total

    nv = float(net_value or 0)
    if held <= 0:
        first = min(nv * PLAN["first"], room)
        ladder = [{"round": i + 1, "amount": round(min(nv * a, room - first), 0),
                   "after_gap_pct": round(gap * (i + 1), 2) if gap else None}
                  for i, a in enumerate(PLAN["adds"])]
        return {"ok": blocked is None, "blocked": blocked, "symbol": symbol,
                "leverage": lev, "mode": "建仓", "first": round(first, 0),
                "ladder": ladder, "single_cap": round(single, 0),
                "total_cap": round(total, 0), "gap_pct": None if gap is None else round(gap, 2),
                "min_gap_days": PLAN["min_gap_days"], "room": round(room, 0)}

    ladder = []
    left = room
    for i, a in enumerate(PLAN["adds"]):
        amt = min(nv * a, left)
        if amt <= 0:
            break
        ladder.append({"round": i + 1, "amount": round(amt, 0),
                       "after_gap_pct": round(gap * (i + 1), 2) if gap else None})
        left -= amt
    return {"ok": blocked is None, "blocked": blocked, "symbol": symbol,
            "leverage": lev, "mode": "加仓", "first": 0.0, "ladder": ladder,
            "single_cap": round(single, 0), "total_cap": round(total, 0),
            "gap_pct": None if gap is None else round(gap, 2),
            "min_gap_days": PLAN["min_gap_days"], "room": round(room, 0)}


def brief_line(plan):
    """简报用的一行摘要 ✓（简洁、可执行）。"""
    if not plan:
        return None
    sym = plan["symbol"]
    cap = "上限 $%.0f" % plan["single_cap"]
    if plan["blocked"]:
        # 🔴 2026-10-30 实测：`blocked` 里已经带了「上限 $N」⇒ 再追加一次会重复 ✗
        # （简报里出现「已到单标的上限 $1253 | 上限 $1253」✗）
        blk = str(plan["blocked"])
        if "上限" in blk:
            return "· %s ×%d | %s" % (sym, plan["leverage"], blk)
        return "· %s ×%d | %s | %s" % (sym, plan["leverage"], blk, cap)
    if plan["mode"] == "建仓":
        lad = "、".join(
            "+$%.0f（正股再跌 %.1f%%）" % (x["amount"], x["after_gap_pct"])
            for x in plan["ladder"] if x["amount"] > 0 and x["after_gap_pct"])
        return ("· %s ×%d | 可建仓：首建 $%.0f%s | %s"
                % (sym, plan["leverage"], plan["first"],
                   ("，" + lad) if lad else "", cap))
    lad = "、".join(
        "+$%.0f（正股再跌 %.1f%%）" % (x["amount"], x["after_gap_pct"])
        for x in plan["ladder"] if x["amount"] > 0 and x["after_gap_pct"])
    return ("· %s ×%d | 可加仓：%s | 剩余额度 $%.0f | %s"
            % (sym, plan["leverage"], lad or "已无额度", plan["room"], cap))
