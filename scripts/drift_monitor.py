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
  .venv/bin/python scripts/drift_monitor.py --crosscheck # D2 多源交叉校验（默认 --source vix）
  .venv/bin/python scripts/drift_monitor.py --crosscheck --source fed  # fed：FedWatch vs Kalshi KXFED
  .venv/bin/python scripts/drift_monitor.py --backfill   # D2 自动回填（缺值用副源补齐）

## R1.5 数据质量闸门（freqtrade 数据自检思想）
- 检测 Data/raw/prices.csv（白名单+SPY）、vix.csv、news_sentiment.csv：
  无效值(价格<=0/NaN/负量) / 断档(交易日缺口>5) / 跳空(单日|涨跌|超阈值) / 极端值
- 异常 → 合并写 Data/freshness_warning.txt（[数据质量] 节，不清除停更告警）；
  --push-alert 时推飞书。正常 → 移除本脚本旧的 [数据质量] 节（不留 stale 告警）。

## D2 多源交叉校验 + 自动回填（坏数据不进合成）
- 交叉校验：同一指标**两个数据源**（如 VIX 双源）逐日比对 → **偏差表**（纯函数，
  接收两条序列，**不联网**）。超阈值行由**人工**判定，脚本不据此改仓位。
- 自动回填：主源**缺值**行，用副源回填；但该行副源值相对「主源最近已知值」的
  **相对偏差 > 阈值** ⇒ 判为可疑、**不回填**（宁缺勿滥，坏数据不进合成）。
  回填是**可注入文件路径**的纯函数，默认路径取自 config（不硬编码 Data/）。
"""
import argparse
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
import pandas as pd  # noqa: E402

from fg_system import config  # noqa: E402
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


# ---------------------------------------------------------------- D2 多源交叉校验
# 交叉校验偏差阈值（**相对偏差** = |副源−主源| / |主源|）。
# 先验值，**禁止用回测优化**（第 4B.6 条精神）；仅作为"哪些行需要人工看"的筛选线，
# **不得**据它自动改仓位或自动调参（规划 D2 结论层·人工）。
CROSSCHECK_THRESHOLD = 0.05
# 偏差表列名（**固定**，消费方据此取字段）。
CROSSCHECK_COLUMNS = ["date", "primary", "secondary", "abs_dev", "rel_dev", "breach"]
# 回填明细列名（**固定**）。
BACKFILL_COLUMNS = ["date", "value", "source"]
# 自动回填的默认目标文件：主源 VIX（路径取自 config，**不硬编码 Data/**）。
BACKFILL_DEFAULT_PATH = os.path.join(config.RAW_DIR, "vix.csv")


def _to_date_series(s):
    """把输入规整为「index=日期、值=float」的干净 Series（不改入参）。"""
    if not isinstance(s, pd.Series):
        s = pd.Series(s)
    out = s.astype("float64").copy()
    out.index = pd.to_datetime(out.index)
    return out.sort_index()


def crosscheck_series(primary, secondary, threshold=CROSSCHECK_THRESHOLD):
    """**多源交叉校验**（纯函数）：两条同指标序列逐日比对 → 偏差表。

    参数：
      primary   —— 主源序列（index 为日期，值为数值；如 CBOE VIX）
      secondary —— 副源序列（如 Nasdaq VIX）
      threshold —— 相对偏差阈值（|差|/|主源|），超此值为 `breach=True`

    返回 DataFrame，列固定为 `CROSSCHECK_COLUMNS`：
      date / primary / secondary / abs_dev / rel_dev / breach

    - 仅在**共同日期**上比对（inner join）：缺一天属停更，不当作偏差。
    - **不联网、不改入参**。`breach` 只作"需人工看"的标记，**不触发任何自动调仓**。
    """
    p = _to_date_series(primary)
    s = _to_date_series(secondary)
    common = p.index.intersection(s.index)
    p = p.loc[common]
    s = s.loc[common]
    abs_dev = (s - p).abs()
    denom = p.abs().replace(0.0, pd.NA).astype("float64")
    rel_dev = (abs_dev / denom).astype("float64")
    df = pd.DataFrame({
        "date": [d.strftime("%Y-%m-%d") for d in common],
        "primary": p.to_numpy(dtype="float64"),
        "secondary": s.to_numpy(dtype="float64"),
        "abs_dev": abs_dev.to_numpy(dtype="float64"),
        "rel_dev": rel_dev.to_numpy(dtype="float64"),
        "breach": (rel_dev > threshold).fillna(False).to_numpy(dtype=bool),
    })
    return df[CROSSCHECK_COLUMNS]


def breach_rows(dev_table):
    """从偏差表挑出**超阈值**行（供报告/告警展示）。空表 ⇒ 空子表。"""
    if dev_table is None or len(dev_table) == 0:
        cols = dev_table.columns if dev_table is not None else CROSSCHECK_COLUMNS
        return pd.DataFrame(columns=list(cols))
    return dev_table[dev_table["breach"]].reset_index(drop=True)[list(dev_table.columns)]


def backfill_from_secondary(path, primary_col, secondary_col,
                            threshold=CROSSCHECK_THRESHOLD):
    """**自动回填**（可注入文件路径的纯函数）：主源缺值行用副源补齐。

    触发条件（**守住"坏数据不进合成"**）：
      - 仅考虑『主源为 NaN/空 且副源有值』的行；
      - 逐行比对：副源值相对**主源最近已知值**（该行之前最近的非缺失主源值；
        若无，则取之后最近的）的**相对偏差 ≤ threshold** 才回填；超阈值 ⇒ 判为可疑，
        **保留 NaN 不回填**（宁缺勿滥）。
      - 主源已有值 ⇒ 绝不覆盖（副源不得改写历史）。

    回填后就地写回 `path`（无回填则不写，保证幂等），返回明细 DataFrame
    （列固定 `BACKFILL_COLUMNS`）。`path` 由调用方注入（测试用 tmp_path）；
    CLI 默认取 `BACKFILL_DEFAULT_PATH`。
    """
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"])
    p = df[primary_col].astype("float64")
    s = df[secondary_col].astype("float64")

    known = p.ffill()          # 主源最近已知值（向前填充，不改入参 df）
    known_bfill = p.bfill()    # 若该行之前全缺，用之后最近值兜底
    ref = known.where(known.notna(), known_bfill)

    # 逐行相对偏差 = |副源 − 主源最近已知| / |主源最近已知|
    denom = ref.abs().replace(0.0, pd.NA).astype("float64")
    rel = (s - ref).abs() / denom
    need = p.isna() & s.notna() & ref.notna()
    fill_idx = df.index[need & (rel <= threshold)]

    record = []
    if len(fill_idx):
        filled_vals = s.loc[fill_idx].to_numpy(dtype="float64")
        df.loc[fill_idx, primary_col] = filled_vals
        for pos, i in enumerate(fill_idx):
            record.append({"date": df.loc[i, "date"].strftime("%Y-%m-%d"),
                           "value": float(filled_vals[pos]),
                           "source": secondary_col})
        df.to_csv(path, index=False, encoding="utf-8")
    filled = pd.DataFrame(record, columns=BACKFILL_COLUMNS)
    return filled


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


def _load_vix_source(path):
    """读一个 VIX 源 CSV（date,close）→ index=日期 的 close 序列；不存在返回空序列。"""
    if not os.path.exists(path):
        return pd.Series(dtype="float64")
    row = pd.read_csv(path, parse_dates=["date"])
    return row.set_index("date")["close"].sort_index().astype("float64")


def _load_source(path, value_col):
    """读一个交叉校验源 CSV（date,<value_col>）→ index=日期 的取值序列。

    源文件不存在 ⇒ 返回**空序列**（调用方据此走「有源为空」安全跳过分支）；
    统一走 `date` + 指定列，避免各源列名差异散落在报告逻辑里。
    """
    if not os.path.exists(path):
        return pd.Series(dtype="float64")
    row = pd.read_csv(path, parse_dates=["date"])
    return row.set_index("date")[value_col].sort_index().astype("float64")


# 交叉校验的**源组**：按名字选一组可比的主/副源（`--source`）。
# - vix：VIX 双源（主 CBOE vix.csv / 副 Nasdaq vix_alt.csv），列 = close。
#   行为与历史一致（默认源）。
# - fed：美联储利率决议**市场隐含概率**双源 ——
#     主源 = 原 fed 源 fedwatch.csv（CME FedWatch，fg_system/fed.py 消费），
#     副源 = kalshi_fed.csv（Kalshi KXFED，scripts/fetch_kalshi_fed.py 产出）。
#   ⚠️ 口径提示：两源均为「市场隐含概率(%)」，可比的是**同列 hike_pct**；
#   但 Kalshi 是 **Kalshi 自有市场**的隐含概率、FedWatch 是 **CME 期货**隐含概率，
#   两者都非**实际利率**——不可与 FRED DFF（实际有效联邦基金利率）直接比。
#   偏差仅作「需人工复核」标记，**不自动改仓位/调参**。
SOURCES = {
    "vix": {
        "primary": os.path.join(config.RAW_DIR, "vix.csv"),
        "secondary": os.path.join(config.RAW_DIR, "vix_alt.csv"),
        "value": "close",
        "label": "VIX 双源（close）",
    },
    "fed": {
        "primary": os.path.join(config.RAW_DIR, "fedwatch.csv"),
        "secondary": os.path.join(config.RAW_DIR, "kalshi_fed.csv"),
        "value": "hike_pct",
        "label": "fed 市场隐含加息概率（hike_pct）",
    },
}
DEFAULT_SOURCE = "vix"


def crosscheck_report(primary_path=None, secondary_path=None,
                      threshold=CROSSCHECK_THRESHOLD, source=DEFAULT_SOURCE):
    """多源交叉校验报告（**只出偏差表与需人工看行**，不改仓位/不调参）。

    `source` 选一组可比源（见 `SOURCES`，默认 `vix`）；**仅按名取默认路径**，
    显式注入 `primary_path`/`secondary_path` 时优先（测试用，保持向后兼容位置参数）：
      - `vix`：主源 `config.RAW_DIR/vix.csv`（CBOE）/ 副源 `.../vix_alt.csv`。
      - `fed`：主源 `config.RAW_DIR/fedwatch.csv`（CME FedWatch，原 fed 源）
        / 副源 `.../kalshi_fed.csv`（Kalshi KXFED）；比对列 `hike_pct`。

    **任一源缺失 ⇒ 视为缺源，报告明示并跳过**（不得据此回填）。
    返回 (报告文本, 偏差表)。
    """
    if source not in SOURCES:
        raise ValueError("未知交叉校验源 %r（可选：%s）"
                         % (source, "、".join(SOURCES)))
    cfg = SOURCES[source]
    value_col = cfg["value"]
    primary_path = primary_path or cfg["primary"]
    secondary_path = secondary_path or cfg["secondary"]
    p = _load_source(primary_path, value_col)
    s = _load_source(secondary_path, value_col)
    lines = ["# 多源交叉校验（D2）", ""]
    lines.append("源组: %s（%s）" % (source, cfg["label"]))
    lines.append(f"主源: {primary_path}（{len(p)} 行）")
    lines.append(f"副源: {secondary_path}（{len(s)} 行）")
    lines.append(f"阈值: 相对偏差 > {threshold:.2%} 记为可疑（**仅人工复核，不自动改仓位**）")
    lines.append("")
    if len(p) == 0 or len(s) == 0:
        lines.append("⚠️ 有源为空：无重叠可比对，跳过交叉校验（不得据此回填）。")
        return "\n".join(lines), pd.DataFrame(columns=CROSSCHECK_COLUMNS)
    dev = crosscheck_series(p, s, threshold=threshold)
    bad = breach_rows(dev)
    lines.append("共同日期 %d 天，超阈值 %d 天" % (len(dev), len(bad)))
    if len(bad):
        lines.append("")
        lines.append("date | primary | secondary | abs_dev | rel_dev | breach")
        for _, r in bad.iterrows():
            lines.append("%s | %.2f | %.2f | %.2f | %.2f%% | %s" % (
                r["date"], r["primary"], r["secondary"], r["abs_dev"],
                r["rel_dev"] * 100, r["breach"]))
    else:
        lines.append("全部在阈值内（两源一致）。")
    return "\n".join(lines), dev


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true", help="报告推飞书")
    ap.add_argument("--push-alert", action="store_true", help="仅异常(预警/告警)时推飞书")
    ap.add_argument("--quality", action="store_true", help="R1.5 数据质量闸门：三路检测并写 freshness_warning.txt")
    ap.add_argument("--crosscheck", action="store_true", help="D2 多源交叉校验：出双源偏差表")
    ap.add_argument("--backfill", action="store_true", help="D2 自动回填：主源缺值行用副源补齐（带可信度闸）")
    ap.add_argument("--source", choices=sorted(SOURCES), default=DEFAULT_SOURCE,
                    help="交叉校验源组（默认 %s）：vix=VIX 双源；"
                         "fed=CME FedWatch vs Kalshi KXFED（hike_pct）" % DEFAULT_SOURCE)
    ap.add_argument("--threshold", type=float, default=CROSSCHECK_THRESHOLD,
                    help="交叉校验相对偏差阈值（默认 %.2f）" % CROSSCHECK_THRESHOLD)
    args = ap.parse_args()

    if args.crosscheck or args.backfill:
        if args.backfill:
            path = BACKFILL_DEFAULT_PATH
            row = pd.read_csv(path)
            cols = list(row.columns)
            if "close" in cols and "close_alt" in cols:
                filled = backfill_from_secondary(path, "close", "close_alt",
                                                 threshold=args.threshold)
                print("自动回填 %d 行（主源缺值、副源可信）：" % len(filled))
                for _, r in filled.iterrows():
                    print(" - %s ← %s = %.4f" % (r["date"], r["source"], r["value"]))
            else:
                print("⚠️ %s 无 close/close_alt 双源列，跳过回填（不臆造列）。" % path)
        report, _ = crosscheck_report(source=args.source, threshold=args.threshold)
        print(report)
        if args.push or args.push_alert:
            from scripts.invest_research import push_feishu
            ok, msg = push_feishu(report)
            print(f"飞书推送: {'成功' if ok else f'失败 {msg}'}")
        return 0

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
