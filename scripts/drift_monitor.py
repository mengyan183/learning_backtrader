#!/usr/bin/env python3
"""概念漂移监控器（E2）：检测系统贪恐指数预测力衰减

- 全窗 IC 基线 vs 近窗（最近 120 交易日）IC 对比（Spearman，窗口 60）
- 市场收益代理：SPY（无杠杆，已入库）
- 告警规则（保守三档）：
   正常  ：近窗 icir >= 0.5 或 近窗 ic_mean >= 全窗 ic_mean - 1σ
   预警  ：近窗 icir < 0.5 且近窗 ic_mean 明显低于全窗
   告警  ：近窗 icir < 0.3 或 近窗 ic_mean < 0 且全窗为正
- 触发告警 → 建议季度 walk-forward 重标定（走变体 + 人工审批，禁止直接调参）

用法:
  .venv/bin/python scripts/drift_monitor.py              # 只出报告
  .venv/bin/python scripts/drift_monitor.py --push       # 报告推飞书
  .venv/bin/python scripts/drift_monitor.py --push-alert # 仅异常(预警/告警)时推飞书
  .venv/bin/python scripts/drift_monitor.py --quality    # 数据质量闸门（R1.5）单独跑

## R1.5 数据质量闸门（freqtrade 数据自检思想）
- 检测 Data/raw/prices.csv（白名单+SPY）、vix.csv、news_sentiment.csv：
  无效值(价格<=0/NaN/负量) / 断档(交易日缺口>5) / 跳空(单日|涨跌|超阈值) / 极端值
- 异常 → 合并写 Data/freshness_warning.txt（[数据质量] 节，不清除停更告警）；
  --push-alert 时推飞书。正常 → 移除本脚本旧的 [数据质量] 节（不留 stale 告警）。
"""
import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
import pandas as pd  # noqa: E402

from fg_system.factors.eval import evaluate, window_stats  # noqa: E402

DATA = REPO / "Data"
HORIZON = 20          # 主要监控前瞻：约一个月
IC_WINDOW = 60        # 滚动 IC 窗口（交易日）
RECENT = 120          # 近窗长度（交易日）


def load():
    feat = pd.read_csv(DATA / "features.csv", parse_dates=["date"])
    feat = feat.dropna(subset=["fg_index"]).set_index("date")
    px = pd.read_csv(DATA / "raw" / "prices.csv", parse_dates=["date"])
    spy = px[px["symbol"] == "SPY"].set_index("date")["close"].sort_index()
    signal = feat["fg_index"].loc[feat.index >= spy.index.min()]
    close = spy.loc[spy.index >= signal.index.min()]
    return signal, close


def decide(full, recent):
    """漂移判定（贪恐指数为逆向指标：IC 恒为负是特性，检测效力衰减与方向翻转）。"""
    if full is None or recent is None:
        return "数据不足", "IC 样本不足，无法判定"
    # 方向翻转 = 真告警：全窗 IC 与近窗 IC 异号（负→正 或 正→负）
    if full["ic_mean"] * recent["ic_mean"] < 0 and abs(full["ic_mean"]) > 0.1:
        return "告警", f"IC 方向翻转(全窗 {full['ic_mean']:.2f} → 近窗 {recent['ic_mean']:.2f})，逆向关系可能失效"
    if abs(recent["icir"]) < 0.3:
        return "告警", f"近窗 |ICIR| {abs(recent['icir']):.2f} < 0.3，预测效力显著衰减"
    if abs(recent["icir"]) < 0.5 or abs(recent["ic_mean"]) < abs(full["ic_mean"]) - full["ic_std"]:
        return "预警", f"近窗 |ICIR| {abs(recent['icir']):.2f} < 0.5 或 |IC| 低于基线一档"
    return "正常", f"逆向信号稳定(全窗 IC {full['ic_mean']:.2f} / 近窗 {recent['ic_mean']:.2f})"


# ---------------------------------------------------------------- R1.5 数据质量闸门
JUMP_SPY = 0.20        # SPY 单日跳空阈值（杠杆外品种）
JUMP_LEV = 0.40        # 杠杆 ETF 单日跳空阈值（3x 日内极端）
JUMP_VIX = 0.30        # VIX 单日跳空阈值
GAP_DAYS = 5           # 交易日缺口 > 5 天 → 断档（周末+节假日≈3，留裕度）
RECENT_DAYS = 30       # 断档/跳空/极端值仅查最近 30 交易日（坏数据发生在最新写入环节；历史真实事件非坏数据）
WARN_PATH = DATA / "freshness_warning.txt"
QUALITY_TAG = "[数据质量]"


def check_price_series(df, symbol, jump=JUMP_LEV):
    """价格序列检测：无效值 / 断档 / 跳空。返回异常行列表。"""
    issues = []
    sub = df[df["symbol"] == symbol].sort_values("date").reset_index(drop=True)
    if sub.empty:
        return ["%s: 数据为空" % symbol]
    close = sub["close"]
    bad = (close <= 0) | close.isna() | (sub["volume"] <= 0)
    if bad.any():
        issues.append("%s: %d 行无效值(close<=0/NaN/volume<=0)" %
                      (symbol, int(bad.sum())))
    d = pd.to_datetime(sub["date"])
    recent = sub.tail(RECENT_DAYS)
    d_r = pd.to_datetime(recent["date"])
    gap = d_r.diff().dt.days
    if (gap > GAP_DAYS).any():
        idx = int(gap[gap > GAP_DAYS].index[0])
        issues.append("%s: 断档 %s→%s（%d 天）" %
                      (symbol, d_r.iloc[idx - 1].date(), d_r.iloc[idx].date(),
                       int(gap.iloc[idx])))
    ret = recent["close"].pct_change()
    big = ret.abs() > jump
    if big.any():
        idx = int(big[big].index[0])
        issues.append("%s: 跳空 %.1f%%（%s）超阈值 %.0f%%" %
                      (symbol, ret.iloc[idx] * 100, d_r.iloc[idx].date(), jump * 100))
    return issues


def check_vix_series(df):
    """VIX 序列检测：无效值 / 断档 / 跳空 / 极端值（>80 罕见危机级）。"""
    issues = []
    if df.empty:
        return ["vix: 数据为空"]
    close = df["close"]
    bad = (close <= 0) | close.isna()
    if bad.any():
        issues.append("vix: %d 行无效值" % int(bad.sum()))
    d = pd.to_datetime(df["date"])
    recent = df.tail(RECENT_DAYS)
    d_r = pd.to_datetime(recent["date"])
    c_r = recent["close"]
    if (c_r > 80).any():
        issues.append("vix: 极端值 %.1f（%s，>80 危机级，需人工确认）" %
                      (c_r.max(), d_r[c_r == c_r.max()].iloc[0].date()))
    gap = d_r.diff().dt.days
    if (gap > GAP_DAYS).any():
        idx = int(gap[gap > GAP_DAYS].index[0])
        issues.append("vix: 断档 %s→%s（%d 天）" %
                      (d_r.iloc[idx - 1].date(), d_r.iloc[idx].date(), int(gap.iloc[idx])))
    ret = c_r.pct_change()
    if (ret.abs() > JUMP_VIX).any():
        idx = int((ret.abs() > JUMP_VIX).idxmax())
        issues.append("vix: 跳空 %.1f%%（%s）超阈值 %.0f%%" %
                      (ret.iloc[idx] * 100, d_r.iloc[idx].date(), JUMP_VIX * 100))
    return issues


def check_sentiment_series(df):
    """情感序列检测：NaN 比例 / 断档。样本少时只做结构检查。"""
    issues = []
    if df.empty:
        return ["news_sentiment: 数据为空"]
    na = df.isna().mean()
    if (na > 0.2).any():
        cols = "、".join(na[na > 0.2].index.tolist())
        issues.append("news_sentiment: 列 NaN 比例超标：%s" % cols)
    d = pd.to_datetime(df["date"])
    gap = d.diff().dt.days
    if (gap > GAP_DAYS).any():
        idx = int(gap[gap > GAP_DAYS].index[0])
        issues.append("news_sentiment: 断档 %s→%s（%d 天）" %
                      (d.iloc[idx - 1].date(), d.iloc[idx].date(), int(gap.iloc[idx])))
    return issues


def quality_gate():
    """汇总三路检测 → 写 freshness_warning.txt 的 [数据质量] 节。返回异常数。"""
    issues = []
    prices = pd.read_csv(DATA / "raw" / "prices.csv", parse_dates=["date"])
    for sym in ["SPY"]:
        issues += check_price_series(prices, sym, jump=JUMP_SPY)
    for sym in ["TQQQ", "SOXL", "UPRO"]:
        issues += check_price_series(prices, sym, jump=JUMP_LEV)
    vix_p = DATA / "raw" / "vix.csv"
    if vix_p.exists():
        issues += check_vix_series(pd.read_csv(vix_p, parse_dates=["date"]))
    sent_p = DATA / "raw" / "news_sentiment.csv"
    if sent_p.exists():
        issues += check_sentiment_series(pd.read_csv(sent_p, parse_dates=["date"]))

    # 合并写 freshness_warning.txt：保留 freshness 停更告警，替换本脚本旧 [数据质量] 节
    old = ""
    if WARN_PATH.exists():
        old = WARN_PATH.read_text(encoding="utf-8").strip()
    kept = "\n".join(ln for ln in old.splitlines() if not ln.startswith(QUALITY_TAG))
    if issues:
        block = "\n".join(QUALITY_TAG + " " + i for i in issues)
        new = (kept + "\n" + block).strip("\n")
    else:
        new = kept
    WARN_PATH.write_text(new + "\n", encoding="utf-8")
    return issues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true", help="报告推飞书")
    ap.add_argument("--push-alert", action="store_true", help="仅异常(预警/告警)时推飞书")
    ap.add_argument("--quality", action="store_true", help="R1.5 数据质量闸门：三路检测并写 freshness_warning.txt")
    args = ap.parse_args()

    if args.quality:
        issues = quality_gate()
        if issues:
            print("数据质量异常 %d 项：" % len(issues))
            for i in issues:
                print(" - " + i)
            print("→ 已写 Data/freshness_warning.txt")
            if args.push_alert:
                from scripts.invest_research import push_feishu
                ok, msg = push_feishu("\n".join(["【数据质量闸门】"] + issues))
                print(f"飞书推送: {'成功' if ok else f'失败 {msg}'}")
        else:
            print("数据质量闸门：全部通过（prices/vix/news_sentiment 无异常）")
        return 0

    signal, close = load()
    ev = evaluate(signal, close, horizons=(HORIZON,), window=IC_WINDOW)
    ws = window_stats(ev, HORIZON, recent=RECENT)
    full, recent = ws["stats"], ws["recent_stats"]

    lines = ["# 概念漂移监控（E2）", ""]
    lines.append(f"信号: 系统贪恐指数 fg_index（{signal.index.min().date()} → {signal.index.max().date()}，{len(signal)} 交易日）")
    lines.append(f"目标: SPY 未来 {HORIZON} 交易日收益 | 滚动 IC 窗口 {IC_WINDOW} | 近窗 {RECENT} 交易日")
    lines.append("")
    if full:
        lines.append("全窗基线: IC均值 {:.3f} | ICIR {:.2f} | IC正值比 {:.1%} | n={}".format(
            full["ic_mean"], full["icir"], full["ic_positive_ratio"], full["n"]))
    if recent:
        lines.append("近窗({}): IC均值 {:.3f} | ICIR {:.2f} | IC正值比 {:.1%} | n={}".format(
            RECENT, recent["ic_mean"], recent["icir"], recent["ic_positive_ratio"], recent["n"]))
    level, note = decide(full, recent)
    lines.append("")
    lines.append(f"漂移判定: {level} —— {note}")
    if level == "告警":
        lines.append("建议: 启动季度 walk-forward 重标定（变体 + 人工审批，OOS 不劣化才进提案；禁止直接调参）")
    report = "\n".join(lines)
    print(report)

    if args.push or (args.push_alert and level in ("预警", "告警")):
        from scripts.invest_research import push_feishu
        ok, msg = push_feishu(report)
        print(f"飞书推送: {'成功' if ok else f'失败 {msg}'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
