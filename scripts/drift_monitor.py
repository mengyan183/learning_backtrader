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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true", help="报告推飞书")
    ap.add_argument("--push-alert", action="store_true", help="仅异常(预警/告警)时推飞书")
    args = ap.parse_args()

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
