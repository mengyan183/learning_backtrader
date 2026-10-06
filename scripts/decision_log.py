#!/usr/bin/env python3
"""Agent-Maintained Memory（Harness 模式落地 #7，人工门控变体）。

论文映射（docs/harness-engineering-notes.md §13）：Codex agent 自主记忆的
"人工审阅"变体——每次简报生成后，把当日决策事实（指数/档位/熔断/持仓动作/
裁判结论）沉淀进 docs/decision-log.md；文件头明示「自动生成、人工确认后
才构成有效记忆」，人审通过即成为系统进化素材（供 H 假说观察/规则校准）。

用法：
  .venv/bin/python scripts/decision_log.py               # 直接读 Data/ 沉淀当日
  .venv/bin/python scripts/decision_log.py --dry-run     # 只打印不写入
也可被 scripts/invest_research.py main() 导入调用（decision_log_append(snap, judge)）。
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "Data"
LOG = REPO / "docs" / "decision-log.md"

HEADER = """# 贪恐系统决策日志（Agent-Maintained Memory）

> **人工门控声明**：本日志由 `scripts/decision_log.py` 自动生成，记录系统
> 运行时的决策事实快照，**未经人工确认不构成系统采纳的记忆/规则**。
> 确认方式：在对应条目下勾选/批复，或直接改写为规则写入 fg_system/。
> 用途：H 假说观察点、极端规则校准、信号分级复盘（docs/roadmap.md）。

<!-- auto-log: 每次 invest_research 简报生成后追加一条 -->
"""


def _latest_feature_row():
    import pandas as pd
    f = pd.read_csv(DATA / "features.csv", parse_dates=["date"])
    row = f.dropna(subset=["fg_index"]).iloc[-1]
    out = {"date": str(row["date"].date()),
           "fg_index": round(float(row["fg_index"]), 2),
           "zone": int(row["zone"]) if pd.notna(row.get("zone")) else None}
    for k in ("vix", "term", "price", "breadth", "fed"):
        if k in row.index and pd.notna(row[k]):
            out[k] = round(float(row[k]), 2)
    if pd.notna(row.get("drawdown")):
        out["drawdown"] = round(float(row["drawdown"]), 4)
    return out


def _latest_state():
    try:
        s = json.load(open(DATA / "state.json"))
        out = {"circuit_breaker": bool(s.get("circuit_breaker"))}
        if s.get("last_extreme_fear_date"):
            out["last_extreme_fear_date"] = s["last_extreme_fear_date"]
        return out
    except Exception:
        return {}


def _latest_positions():
    import pandas as pd
    try:
        p = pd.read_csv(DATA / "positions.csv", parse_dates=["date"])
        latest = p["date"].max()
        rows = []
        for _, r in p[p["date"] == latest].iterrows():
            q = {"symbol": r["symbol"]}
            if pd.notna(r.get("cost")):
                q["cost"] = float(r["cost"])
            if pd.notna(r.get("price")):
                q["price"] = float(r["price"])
            if pd.notna(r.get("qty")):
                q["qty"] = float(r["qty"])
            rows.append(q)
        return {"date": str(latest.date()), "rows": rows}
    except Exception:
        return {}


def build_entry(snap=None, judge=None):
    """构造一条决策日志 markdown。snap/judge 缺省时直接读 Data/。"""
    if snap is None:
        snap = {}
    try:
        feat = _latest_feature_row()
    except Exception:
        feat = {}
    state = _latest_state()
    pos = _latest_positions()
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [f"### {now}", ""]
    if feat:
        parts = [f"系统贪恐指数 {feat['fg_index']}"]
        if feat.get("zone") is not None:
            zname = {0: "极度恐惧", 1: "恐惧", 2: "中性", 3: "贪婪", 4: "极度贪婪"}.get(feat["zone"], "?")
            parts.append(f"档位{zname}")
        if feat.get("drawdown") is not None:
            parts.append(f"回撤 {feat['drawdown']:.2%}")
        lines.append("- 指数：" + " / ".join(parts) + f"（数据日 {feat.get('date')}）")
        factors = {k: v for k, v in feat.items() if k in ("vix", "term", "price", "breadth", "fed")}
        if factors:
            lines.append("- 因子：" + " / ".join(f"{k.upper()} {v}" for k, v in factors.items()))
    if state:
        lines.append("- 熔断：" + ("已触发" if state.get("circuit_breaker") else "未触发")
                     + (f"；最近极端恐惧日 {state['last_extreme_fear_date']}" if state.get("last_extreme_fear_date") else ""))
    if pos.get("rows"):
        pnl_parts = []
        for r in pos["rows"][:12]:
            if r.get("cost") and r.get("price"):
                pct = (r["price"] / r["cost"] - 1) * 100
                pnl_parts.append(f"{r['symbol']} {pct:+.1f}%")
        lines.append(f"- 持仓快照（{pos.get('date')}）："
                     + ("；".join(pnl_parts) if pnl_parts else f"{len(pos['rows'])} 个标的"))
    if judge and isinstance(judge, str) and judge.strip():
        brief_judge = judge.strip().replace("\n", " ")[:220]
        lines.append(f"- 裁判裁决摘要（NIM）：{brief_judge}")
    lines.append("- 待人工确认：以上为运行事实快照，是否采纳为规则/假说观察点？（Y/N）")
    return "\n".join(lines) + "\n"


def append(snap=None, judge=None, dry_run=False):
    entry = build_entry(snap, judge)
    if dry_run:
        print(entry)
        return
    LOG.parent.mkdir(parents=True, exist_ok=True)
    if not LOG.exists():
        LOG.write_text(HEADER + "\n", encoding="utf-8")
    txt = LOG.read_text(encoding="utf-8")
    if not txt.startswith("# 贪恐系统决策日志"):
        txt = HEADER + "\n" + txt
    txt = txt.rstrip() + "\n\n" + entry
    LOG.write_text(txt, encoding="utf-8")
    print(f"[decision-log] 已追加: {LOG}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    append(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
