# -*- coding: utf-8 -*-
"""交易记录 vs 系统指令 → 违规报告（§13.2）。

核心原则（§13.3）：指令之外的操作一律记为违规。
"""
import os

import pandas as pd

from fg_system import config

VERDICT_OK = "合规"
VERDICT_NO_INSTRUCTION = "违规-无指令操作"
VERDICT_REVERSE = "违规-逆向"
VERDICT_COOLDOWN = "违规-超频"
VERDICT_OVERADJUST = "违规-超幅"

_LOG_COLUMNS = ["date", "symbol", "action", "quantity", "price", "reason"]


def load_log(path=None):
    path = path or config.TRADE_LOG_PATH
    if not os.path.exists(path):
        return pd.DataFrame(columns=_LOG_COLUMNS)
    try:
        df = pd.read_csv(path, parse_dates=["date"])
    except pd.errors.EmptyDataError:
        return pd.DataFrame(columns=_LOG_COLUMNS)
    if df.empty:
        return pd.DataFrame(columns=_LOG_COLUMNS)
    return df.sort_values("date").reset_index(drop=True)


def audit(log, features, portfolio_value=None):
    """逐笔判定合规性。features 需含 target_position 与 circuit_breaker。

    portfolio_value：组合总值，用于估算单笔操作的仓位变化幅度以判定「超幅违规」
    （§13.2 第五类）。默认取 config.INITIAL_CASH。
    """
    if log is None or log.empty:
        return pd.DataFrame(columns=["date", "symbol", "action", "reason",
                                     "verdict", "detail"])

    pv = float(portfolio_value or config.INITIAL_CASH)
    rows = []
    last_date = None
    for _, t in log.iterrows():
        d = pd.Timestamp(t["date"])
        feat = features.loc[d] if d in features.index else None
        if feat is not None and isinstance(feat, pd.DataFrame):
            feat = feat.iloc[0]
        target = feat["target_position"] if feat is not None and \
            "target_position" in feat else None
        cb = bool(feat["circuit_breaker"]) if feat is not None and \
            "circuit_breaker" in feat else False
        action = str(t["action"]).lower()
        reason = t.get("reason", "")

        verdict, detail = VERDICT_OK, ""
        if feat is None:
            # 交易日不在指令表内 → 无指令可依
            verdict, detail = VERDICT_NO_INSTRUCTION, "该日无系统指令"
        elif reason == "manual":
            verdict, detail = VERDICT_NO_INSTRUCTION, "人工裁量操作"
        elif cb and action == "buy":
            verdict, detail = VERDICT_NO_INSTRUCTION, "熔断禁买期内买入"
        elif target is not None and not pd.isna(target) and \
                float(target) <= 0.01 and action == "buy":
            verdict, detail = VERDICT_REVERSE, "指令要求空仓仍买入"
        elif pv > 0 and _amount(t) / pv > config.MAX_SINGLE_ADJUST:
            verdict, detail = VERDICT_OVERADJUST, "单笔金额占组合 %.1f%% 超上限 %.0f%%" % (
                _amount(t) / pv * 100, config.MAX_SINGLE_ADJUST * 100)
        elif last_date is not None:
            gap = (d - last_date).days
            if gap < config.REBALANCE_COOLDOWN:
                verdict, detail = VERDICT_COOLDOWN, "距上次操作仅 %d 天" % gap

        rows.append({
            "date": d, "symbol": t["symbol"], "action": t["action"],
            "reason": reason, "verdict": verdict, "detail": detail,
        })
        last_date = d
    return pd.DataFrame(rows)


def _amount(trade):
    """单笔操作金额（quantity × price）。字段缺失或非法时返回 0。"""
    try:
        return abs(float(trade.get("quantity", 0)) * float(trade.get("price", 0)))
    except (TypeError, ValueError):
        return 0.0


def in_usage_stage():
    """系统是否已进入**使用阶段**（第 13.0 条）。

    **为什么要显式判断**：`audit` 的「违规」定义（§13.3：指令之外的操作一律
    记为违规）**预设系统已在使用**。若系统尚未上线，用户那些「系统之外」的
    操作**不是违规**，而是关于「**用户实际持有什么**」的证据（第 12.20 条）。

    把两者混为一谈，会把「系统从未被使用」误报成「用户严重违纪」，
    并进而误触发第 10.2 条的"系统降级" —— 第 13.0 条已明确否定该结论。

    **所有显示层必须走本函数**，不要各自去读 `config.STAGE`：
    否则将来新增显示点时会漏改（两处显示点见 cli.py 的 `_cmd_audit` /
    `_cmd_status`）。
    """
    return config.STAGE == config.STAGE_USAGE


def violation_rate(audited):
    if audited is None or audited.empty:
        return 0.0
    return float((audited["verdict"] != VERDICT_OK).sum()) / len(audited)


def violations(audited):
    """只返回违规记录。"""
    if audited is None or audited.empty:
        return audited
    return audited[audited["verdict"] != VERDICT_OK]
