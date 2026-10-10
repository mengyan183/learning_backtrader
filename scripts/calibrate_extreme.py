#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B-8 极端规则校准（85 熔断 / 10 极恐）—— **只测量，不改 config** ✓（WT-03）。

【红线】
  · OOS 禁直接调参 ⇒ 本脚本**只产出证据表** ✓，**不写任何参数** ✗、不碰 config.py ✗。
  · 数据只读 ✓。

【它测什么】
  `Data/features.csv` 已有真实列 `circuit_breaker` / `extreme` ✓ ⇒ 本脚本**反推**
  这两条极端规则的实际触发边界与后果 ✓：
    1. 历史触发次数；
    2. 触发当日 `fg_index` 的实际取值范围（⇒ 与标称的 85 / 10 对照 ✓）；
    3. 触发后 4 / 8 / 16 个交易日的标的收益（`Data/raw/prices.csv` ✓）。
  ⇒ 得到"标称阈值 vs 实测边界 vs 触发后果"的证据表 ✓，供后续走变体+审批 ✓。

【样本不足时】
  触发次数 < MIN_EVENTS ⇒ 打印「样本不足」并 **exit 0** ✓（验收要求 ✓；
  快照/历史还在积累时这是**正常结果** ✓，不是错误 ✗）。

用法：.venv/bin/python scripts/calibrate_extreme.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Windows 控制台默认 GBK ✗ ⇒ 本脚本要打印 ⚠️/✅ ⇒ 显式 utf-8 ✓（同 evolve_approve ✓）
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
FEATURES = os.path.join(REPO, "Data", "features.csv")
PRICES = os.path.join(REPO, "Data", "raw", "prices.csv")
MIN_EVENTS = 10
HORIZONS = (4, 8, 16)
NOMINAL = {"circuit_breaker": 85.0, "extreme": 10.0}   # 标称阈值（85 熔断 / 10 极恐）


def _read_csv(path):
    import csv
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _is_true(v):
    return str(v).strip().lower() in ("true", "1", "yes")


def load_triggers():
    """返回 {flag: [(date, fg_index)]} ✓；文件缺失返回 None ✓。"""
    if not os.path.isfile(FEATURES):
        return None
    rows = _read_csv(FEATURES)
    out = {k: [] for k in NOMINAL}
    for r in rows:
        try:
            fg = float(r.get("fg_index") or "nan")
        except ValueError:
            continue
        for flag in NOMINAL:
            if _is_true(r.get(flag)):
                out[flag].append((r.get("date", ""), fg))
    return out


def load_prices(symbols):
    """{symbol: [(date, close)]} ✓（按日期升序 ✓）。"""
    if not os.path.isfile(PRICES):
        return {}
    series = {}
    for r in _read_csv(PRICES):
        sym = (r.get("symbol") or "").strip()
        if symbols and sym not in symbols:
            continue
        try:
            series.setdefault(sym, []).append((r.get("date", ""), float(r["close"])))
        except (ValueError, KeyError):
            continue
    for s in series:
        series[s].sort(key=lambda x: x[0])
    return series


def forward_return(series, date, horizon):
    """`date` 之后第 `horizon` 个交易日的收益 ✓；数据不足返回 None ✓。"""
    idx = next((i for i, (d, _) in enumerate(series) if d == date), None)
    if idx is None or idx + horizon >= len(series):
        return None
    base, later = series[idx][1], series[idx + horizon][1]
    return (later / base - 1.0) if base else None


def main():
    trig = load_triggers()
    if trig is None:
        print("样本不足：缺少 %s（数据由 Mac 侧积累，本机通常无最新快照）" % FEATURES)
        return 0

    try:
        sys.path.insert(0, REPO)
        from fg_system import config
        symbols = set(getattr(config, "SYMBOLS", []) or [])
    except Exception:                                             # noqa: BLE001
        symbols = set()
    prices = load_prices(symbols)
    print("价格序列：%s" % ("、".join(sorted(prices)) or "（无可用）"))
    print("阈值口径：熔断 `circuit_breaker`（标称 85）｜极恐 `extreme`（标称 10）")
    print()

    insufficient = []
    for flag, nominal in NOMINAL.items():
        ev = trig[flag]
        print("=== %s（标称 %s）===" % (flag, nominal))
        print("  历史触发次数：**%d**" % len(ev))
        if not ev:
            print("  ⇒ 样本不足（0 次触发）")
            insufficient.append(flag)
            print()
            continue
        fgs = [f for _, f in ev if f == f]        # 滤掉 nan ✓（extreme 行常见 ✓）
        if fgs:
            print("  触发当日 fg_index 实测范围：%.2f ~ %.2f（均值 %.2f）"
                  % (min(fgs), max(fgs), sum(fgs) / len(fgs)))
        else:
            print("  触发当日 fg_index 全为无效值（nan）⇒ 无法给出实测范围 ✗"
                  "（该列在 extreme 行常为空 ⇒ 需先补数据 ✓）")
        print("  首次/末次触发：%s / %s" % (ev[0][0], ev[-1][0]))

        if len(ev) < MIN_EVENTS:
            print("  ⇒ **样本不足**（%d < %d 次）—— 仅登记，不判结论"
                  % (len(ev), MIN_EVENTS))
            insufficient.append(flag)
            print()
            continue

        print("  触发后前瞻收益（按标的 ✓，交易日口径）：")
        print("    %-8s %s" % ("标的", "  ".join("T+%-3d" % h for h in HORIZONS)))
        for sym in sorted(prices):
            cells = []
            for h in HORIZONS:
                vals = [forward_return(prices[sym], d, h) for d, _ in ev]
                vals = [v for v in vals if v is not None]
                cells.append(("%+.2f%%" % (100 * sum(vals) / len(vals))
                              if vals else "  n/a"))
            print("    %-8s %s" % (sym, "  ".join("%-6s" % c for c in cells)))
        print()

    if insufficient:
        print("⚠️ 样本不足的项：%s —— 待实盘快照积累后重跑 ✓（本次不判结论 ✓）"
              % "、".join(insufficient))
    print("✅ 校准证据表产出完成（只测量，未改动任何参数 ✓）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
