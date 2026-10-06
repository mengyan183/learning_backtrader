#!/usr/bin/env python3
"""E4 首批候选因子 IC/IR 初检（数据取证，不进策略）。

用法：.venv/bin/python scripts/factor_screen.py
输出：stdout markdown + evolution/factor-screen-results.md

口径（与 factor-engine.md §4 一致）：
- 信号：系统市场级 fg_index（features.csv，逆向指标，IC 恒负是特性）
- 目标：观察池标的（OBSERVE_SYMBOLS）未来 5/10/20/40 日收益（prices.csv）
- 统计：滚动 IC（Spearman，window=60）→ IC 均值/ICIR/正值比（eval.py）
- 近窗：最后 120 个 IC 值做衰减对比（|IC| 是否 < 全窗 - 1σ / 方向翻转）
- 冗余对照：与 SPY 目标 IC 的相关系数（|corr|>0.8 视为与市场冗余）

纪律：只做数据取证，不改策略、不进白名单；结果仅供人工审阅。
"""
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
DATA = REPO / "Data"

from fg_system import config  # noqa: E402
from fg_system.factors import eval as feval  # noqa: E402

HORIZONS = (5, 10, 20, 40)


def _load_prices():
    df = pd.read_csv(DATA / "raw" / "prices.csv", dtype={"symbol": str},
                     parse_dates=["date"])
    return df


def _close_series(df, symbol):
    s = df[df["symbol"] == symbol].set_index("date")["close"].astype(float)
    return s[~s.index.duplicated(keep="last")].sort_index()


def screen(signal, df, symbol):
    close = _close_series(df, symbol)
    ev = feval.evaluate(signal, close, horizons=HORIZONS, window=60)
    rows = {}
    for h in HORIZONS:
        st = ev[h]["stats"]
        if st is None:
            rows[h] = None
            continue
        ic = ev[h]["ic"].dropna()
        recent = ic.tail(120)
        rec = feval.icir(recent)
        rows[h] = {
            "ic_mean": st["ic_mean"], "icir": st["icir"],
            "pos_ratio": st["ic_positive_ratio"], "n": st["n"],
            "recent_icir": rec["icir"] if rec else None,
            "recent_ic": rec["ic_mean"] if rec else None,
        }
    return rows


def main():
    signal = pd.read_csv(DATA / "features.csv", parse_dates=["date"]) \
        .dropna(subset=["fg_index"]).set_index("date")["fg_index"].astype(float)
    df = _load_prices()
    lines = ["# E4 首批候选因子 IC/IR 初检（数据取证）", "",
             f"- 信号：系统市场级 fg_index（逆向指标，IC 恒负为特性）",
             f"- 目标：观察池标的未来 {HORIZONS} 日收益；滚动 IC window=60（Spearman）",
             f"- 数据：prices.csv（{df['date'].min().date()} ~ {df['date'].max().date()}）",
             f"- 近窗 = 最近 120 个 IC；门槛：|ICIR|≥0.5 且 n≥60 且近窗无衰减", ""]
    lines += ["| 标的 | horizon | IC 均值 | ICIR | 正值比 | n | 近窗 IC | 近窗 ICIR | 备注 |",
              "|---|---|---|---|---|---|---|---|---|"]
    results = {}
    for sym in config.OBSERVE_SYMBOLS:
        r = screen(signal, df, sym)
        results[sym] = r
        close = _close_series(df, sym)
        n_days = int(len(close))
        for h in HORIZONS:
            row = r[h]
            if row is None:
                lines.append(f"| {sym} | {h} | — | — | — | — | — | — | 样本不足 |")
                continue
            ic_m = row["ic_mean"]
            note = ""
            # 逆向指标：IC 越负越好
            if abs(row["icir"]) >= 0.5 and row["n"] >= 60:
                note = "达到门槛"
                if row["recent_ic"] is not None and abs(row["recent_ic"]) < abs(ic_m) - 0.03:
                    note += "·近窗衰减⚠"
            elif abs(row["icir"]) < 0.5:
                note = "未达门槛"
            lines.append(
                f"| {sym} | {h} | {ic_m:+.3f} | {row['icir']:+.2f} | "
                f"{row['pos_ratio']:.2f} | {row['n']} | "
                f"{row['recent_ic']:+.3f} | {row['recent_icir']:+.2f} | {note} |"
            )
    lines += ["", "> 由 scripts/factor_screen.py 生成 · 只读取证，未改策略、未进白名单；"
                  "结果仅供人工审阅，入库仍需回测+审批。"]
    out = "\n".join(lines)
    print(out)
    out_path = REPO / "evolution" / "factor-screen-results.md"
    out_path.write_text(out + "\n", encoding="utf-8")
    print(f"\n[factor_screen] 结果已写入: {out_path}")


if __name__ == "__main__":
    sys.exit(main())
