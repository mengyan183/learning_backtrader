#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""因子评测的**统一渲染层** ✓（2026-11-02 工程加固）。

🔴 问题：`eval_baa10y` / `eval_erp` / `eval_ene` 三个脚本各自写了一遍
   `_fmt()` / `_spy_close()` / IC 表格打印 ✗
   ⇒ 三处重复（约 30 行 × 3）✗ 加第四个因子还要抄第四遍 ✗
   ⇒ 而且口径已经漂了：`eval_ene` 的 `_fmt` 少了 `scale` 参数 ✗、
     表格列也不一致（有的有 `pearson_ICIR`、有的没有）✗

⇒ 统一到这里 ✓ 脚本只负责「取信号 → 调 `screen_report` → 调本模块渲染」✓

设计原则：
  - **只渲染，不算** ✗ —— 统计一律来自 `protocol.screen_report` ✓
  - 缺值一律打 `—` ✓ 不编造 ✗
  - **必须带 IC 自相关与 n_eff** ✓ —— ICIR 已降级为参考 ✗
    （滚动窗 + 重叠收益 + 慢变因子会让 ICIR 结构性虚高 ✗）
"""
import pandas as pd

from fg_system.factors import protocol as fproto

#: 评测默认前瞻期（日频）✓
HORIZONS_DAILY = (5, 10, 20, 40)
#: 月频对照期（仅作参照，不作采纳依据）✗
HORIZONS_MONTHLY = (60, 120, 240)
#: IC 滚动窗 ✓
WINDOW = 60


def fmt(v, spec="+.3f", scale=1.0):
    """`None` ⇒ `—` ✓。

    🔴 2026-10-29 Mac 实测：样本不足时 `screen_report` 把 `ic` 各字段给 `None` ✗
    直接 `{v:+.3f}` 会 `TypeError` ✗ ⇒ 整条评测崩掉、结果只剩「样本不足」✗
    """
    return "—" if v is None else format(v * scale, spec)


def load_prices(data_dir):
    """读 `prices.csv` ✓（统一入口，避免各脚本重复写）。"""
    return pd.read_csv(data_dir / "raw" / "prices.csv", parse_dates=["date"])


def close_series(prices, sym):
    """某标的的收盘序列 ✓（去重、排序、去空）。"""
    s = prices[prices["symbol"] == sym].set_index("date")["close"].astype(float)
    return s[~s.index.duplicated(keep="last")].sort_index().dropna()


def forward_return(close, h):
    """`h` 日前瞻收益 ✓。"""
    return close.shift(-h) / close - 1.0


def ic_table(rep, horizons, sig=None, close=None, window=WINDOW, extra=None):
    """渲染 IC 表格（markdown）✓ —— **含自相关与有效样本数** ✗。

    :param rep: `protocol.screen_report()` 的返回
    :param horizons: 要渲染的 horizon 列表
    :param sig: 信号序列（给了才可能算自相关 ✓）
    :param close: 目标收盘序列（同上）
    :param extra: 额外列 `[(表头, 取值函数(rep, h) -> str)]` ✓
        （`eval_baa10y` 要「近窗ICIR / 分层mono / top-bottom」✗
         而 `eval_erp`/`eval_ene` 不要 ⇒ 参数化 ✓）
    """
    extra = extra or []
    head = ("| horizon | rank_ic_mean | rank_ICIR | pearson_ICIR | n |"
            " IC自相关 | n_eff |" + "".join(" %s |" % t for t, _f in extra))
    lines = [head, "|---|---|---|---|---|---|---|" + "---|" * len(extra)]
    for h in horizons:
        ic = (rep.get("ic") or {}).get(h) or {}
        ac1 = n_eff = None
        if sig is not None and close is not None:
            try:
                tgt = forward_return(close, h)
                ac1, n_eff = fproto.ic_autocorr(sig, tgt, window=window)
            except Exception:              # noqa: BLE001 —— 算不出不阻塞 ✓
                ac1 = n_eff = None
        warn = " ⚠️虚高" if (ac1 is not None and ac1 > 0.8) else ""
        row = ("| %d | %s | %s | %s | %s | %s%s | %s |"
               % (h, fmt(ic.get("rank_ic_mean")),
                  fmt(ic.get("rank_icir")),
                  fmt(ic.get("pearson_icir")),
                  ic.get("n") or 0,
                  fmt(ac1, ".2f"), warn,
                  "—" if n_eff is None else "%.0f" % n_eff))
        row += "".join(" %s |" % f(rep, h) for _t, f in extra)
        lines.append(row)
    return "\n".join(lines)


def verdict_line(rep):
    """判定行 ✓ —— 明确「ICIR 仅作参考」✗。"""
    v = rep.get("verdict") or {}
    out = ["判定：%s —— %s"
           % (v.get("status") or "—", v.get("detail") or "—")]
    if v.get("passed"):
        out.append("  达标 horizon：%s" % v["passed"])
    return "\n".join(out)


def report_block(rep, label, horizons, sig=None, close=None, window=WINDOW):
    """完整一节（标题 + 判定 + 表格）✓。"""
    return "\n".join([
        "## %s（%s）" % (label, "/".join(str(h) for h in horizons)),
        verdict_line(rep),
        ic_table(rep, horizons, sig=sig, close=close, window=window),
    ])
