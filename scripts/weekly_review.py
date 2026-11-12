#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""周度复盘 ✓（2026-11-03 用户裁定要做）。

【做什么】
  回顾最近 N 个交易日的：
    ① 各持仓的**实际涨跌** ✓
    ② 系统当时给的**减仓建议**（从 `Data/briefs/archive/` 的简报里解析 ✗）
    ③ 对照：建议减仓的标的，之后涨了还是跌了 ⇒ 判断质量 ✓

🔴 **必须在 Mac 上跑** ✗（2026-11-03 用户澄清）
   `Data/raw/*.csv` 在 **Windows 侧永远是旧的** ✗ —— 它只是
   Mac 抓完数据后 **git 提交过来的快照** ✗ 实测停在 2026-10-12 ✗
   ⇒ **不要在 Windows 判断数据新鲜度** ✗ 会得出「断流 22 天」的假警报 ✗
   ⇒ 本脚本要下发到 Mac 跑（`weekly_review` 队列动作）✓

【为什么从简报解析而不是从结构化数据】
  ⚠️ 诚实地讲：**结构化数据更可靠** ✗ 但「当时建议什么」只在简报里 ✗
     `positions.csv` 只有持仓 ✗ 没有「建议」✗
  ⇒ 只能解析文本 ✗ 解析失败时**明确跳过** ✓ 不编造 ✗

【解析目标】简报里的这一段：
    **ENE 减仓触发**（ratio=1.0；仅杠杆 ETF ✓...）：
    · GDXU 通道位置 **0.00 超卖** ⇒ 均值回归视角可持有 ✓
    · AXTX 通道位置 **0.85 超买** ⇒ 建议减至 **15%** 仓位
    **减仓顺序**（浮亏深度×杠杆倍数...）：AXTX（-82%×2x） > GDXU（-40%×3x） ...
  以及逐标的行：
    · AXTX 市值779/上限215 | ... → 减仓至上限215

用法：
  .venv/bin/python scripts/weekly_review.py            # 最近 7 天
  .venv/bin/python scripts/weekly_review.py --days 14
"""
import argparse
import re
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                           # noqa: BLE001
    pass

DATA = REPO / "Data"
ARCHIVE = DATA / "briefs" / "archive"

#: 从简报里抓「减仓至上限 XXX」的标的 ✓
RE_CAP = re.compile(r"·\s*([A-Z]{2,6})\s*市值[\d.]+/上限([\d.]+)")
#: 抓「XXX 通道位置 **0.85 超买** ⇒ 建议减至 **15%** 仓位」
RE_ENE = re.compile(r"·\s*([A-Z]{2,6})\s*通道位置\s*\*\*([\d.]+)\s*超买\*\*"
                    r"\s*⇒\s*建议减至\s*\*\*(\d+)%")
#: 文件名里的日期
RE_DATE = re.compile(r"invest_brief_(\d{4}-\d{2}-\d{2})\.md$")


def _briefs(days):
    """最近 `days` 天内的简报文件 ✓（含 archive 与工作区根目录）。

    🔴 2026-11-12 用户要求**去重** ✓ —— 原实现同时扫 `ARCHIVE` 和 `DATA` ✗
       同一份简报若两处都有 ⇒ **被算两次** ✗
       （实测 2026-11-04 的四条记录各出现 2 次 ✗
         「16 条」里只有 12 条是真数据 ✗）
    ⇒ 按**日期**去重 ✓，同日多份取 `ARCHIVE` 优先（归档是权威副本 ✓）
    """
    seen = {}
    for d in (ARCHIVE, DATA):
        for p in d.rglob("invest_brief_*.md"):
            m = RE_DATE.match(p.name)
            if not m:
                continue
            day = m.group(1)
            # `ARCHIVE` 先扫 ⇒ 已存在就不被 `DATA` 覆盖 ✓
            seen.setdefault(day, p)
    files = sorted(seen.items(), reverse=True)
    return files[:days]


def _advice_from_data(date_s):
    """从**结构化数据重算**当日「减仓建议」✓（不再解析简报文本 ✗）

    🔴 2026-11-12 用户要求（原 `_parse` 的替代）：
       原实现靠正则抠简报里的 `· XXX 市值123/上限456` 和 ENE 行 ✗
       而 **P1/P3 瘦身正好删掉了这两类** ✗
       ⇒ 最近 3 份简报全部「解析不到建议」✗（11-09/10/11）
       ⇒ 简报格式会继续变 ⇒ 正则解析是**结构性脆弱** ✗
       ⇒ 改成用**与简报同源**的规则重算 ✓：
         `risk_mod.atr_pct_effective` + `risk_mod.position_limit`
         （`invest_research.py:460-467` 用的是同一对函数 ✓）
       ⇒ 只要 `positions.csv` + `raw/prices.csv` + `accounts.csv` 在，永远能算 ✓

    返回 `{symbol: {"cap": 上限}}` —— 只含**超上限**的标的（即「建议减仓」）✓
    数据缺失 ⇒ 返回 `{}`（上层标「数据缺失」而不是「解析失败」✓）
    """
    try:
        pos = pd.read_csv(DATA / "positions.csv")
        px = pd.read_csv(DATA / "raw" / "prices.csv")
        acc = pd.read_csv(DATA / "accounts.csv")
    except Exception:                       # noqa: BLE001
        return {}
    for d in (pos, acc):
        if "date" in d.columns:
            d["date"] = d["date"].astype(str).str[:10]
    cur = pos[pos["date"] == date_s]
    a = acc[(acc["date"] == date_s) & (acc.get("account") == "stock")]
    if cur.empty or a.empty or "net_value" not in a.columns:
        return {}
    try:
        stock_net = float(a["net_value"].iloc[0])
    except (TypeError, ValueError):
        return {}
    if not stock_net:
        return {}

    sys.path.insert(0, str(REPO))
    try:
        from fg_system import risk as risk_mod
    except Exception:                       # noqa: BLE001
        return {}

    out = {}
    for _, r in cur.iterrows():
        sym = str(r.get("symbol") or "").replace("-USDT", "")
        try:
            mv0 = float(r.get("market_value") or 0)
            px_now = float(r.get("price") or 0)
        except (TypeError, ValueError):
            continue
        if not (sym and mv0 and px_now):
            continue
        try:
            atrp = risk_mod.atr_pct_effective(px, sym, px_now)
            lim, _ = risk_mod.position_limit(stock_net, mv0, atrp)
        except Exception:                   # noqa: BLE001
            continue
        if lim and mv0 > lim:
            out[sym] = {"cap": round(float(lim), 2)}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7, help="回顾最近 N 份简报")
    args = ap.parse_args(argv)

    prices = pd.read_csv(DATA / "raw" / "prices.csv", parse_dates=["date"])

    def close(sym):
        s = (prices[prices["symbol"] == sym].set_index("date")["close"]
             .astype(float))
        return s[~s.index.duplicated(keep="last")].sort_index()

    briefs = _briefs(args.days)
    if not briefs:
        print("✗ 找不到简报（Data/briefs/archive/ 或 Data/ 下无 invest_brief_*.md）")
        return 2

    print("# 周度复盘（最近 %d 份简报：%s ~ %s）\n"
          % (len(briefs), briefs[-1][0], briefs[0][0]))

    rows = []
    n_parse_fail = n_no_price = 0
    last_price_date = None
    for date_s, p in briefs:
        # 🔴 2026-11-12：改成**从结构化数据重算** ✓（不再解析简报文本 ✗）
        #    简报只用于**枚举日期** ✓ —— 它有哪些天，就重算哪些天 ✓
        sig = _advice_from_data(date_s)
        if not sig:
            print("· %s —— **当日无减仓建议** ✓（市值未超 1%% 上限）" % date_s)
            n_parse_fail += 1
            continue
        d0 = pd.Timestamp(date_s)
        for sym, s in sorted(sig.items()):
            c = close(sym)
            if c.empty:
                print("· %s %s —— 无价格数据 ✗" % (date_s, sym))
                n_no_price += 1
                continue
            last_price_date = c.index[-1]
            after = c[c.index > d0]
            if after.empty:
                # 🔴 2026-11-03 修：原来这里**静默 continue** ✗
                #    导致「无未来价格」被误报成「解析不到建议」✗
                #    （Mac 上实测就是这个 ✗ 而 prices 停在 10-12 ✗）
                n_no_price += 1
                continue
            # 之后 5 个交易日 / 到最新的涨幅 ✓
            r5 = (after.iloc[min(4, len(after) - 1)] / after.iloc[0] - 1.0) * 100
            advice = []
            if "ene" in s:
                advice.append("ENE 减至%.0f%%" % s["ene"])
            if "cap" in s:
                advice.append("减至上限%.0f" % s["cap"])
            rows.append({
                "date": date_s, "sym": sym, "advice": " / ".join(advice),
                "r5": r5,
                # 「减仓」建议 ⇒ 之后**跌**才算对 ✓
                "hit": r5 < 0,
            })

    if not rows:
        print("\n## ✗ 没有可对照的记录\n")
        print("| 原因 | 条数 |")
        print("|---|---|")
        print("| **当日无减仓建议**（市值未超上限）| %d |" % n_parse_fail)
        print("| **无未来价格**（`prices.csv` 太旧）| %d |" % n_no_price)
        if last_price_date is not None:
            print("\n`prices.csv` 最新日期：**%s**" % last_price_date.date())
            print("最新简报日期：**%s**" % briefs[0][0])
            if str(last_price_date.date()) < briefs[0][0]:
                print("\n⇒ 🔴 **价格比简报还旧** ✗ —— 数据抓取停了 ✗")
                print("   在 Mac 上查：`tail -3 Data/raw/prices.csv`")
                print("   和 `/tmp/fg_daily.log` 里的 `fetch_prices` 段 ✓")
        return 0

    print("\n## 建议 vs 实际（减仓建议 ⇒ 之后跌 = 对 ✓）\n")
    print("| 日期 | 标的 | 建议 | 之后 5 日 | 判断 |")
    print("|---|---|---|---|---|")
    for r in rows:
        print("| %s | %s | %s | %+.2f%% | %s |"
              % (r["date"], r["sym"], r["advice"], r["r5"],
                 "✓ 对" if r["hit"] else "✗ 错"))

    n = len(rows)
    hit = sum(1 for r in rows if r["hit"])
    print("\n## 汇总\n")
    print("| 项 | 值 |")
    print("|---|---|")
    print("| 建议条数 | %d |" % n)
    print("| 判断正确 | %d（%.0f%%）|" % (hit, 100.0 * hit / n))
    print("| 平均「之后 5 日」 | %+.2f%% |" % (sum(r["r5"] for r in rows) / n))
    print("\n⚠️ **样本很小** ✗ —— 一周的建议条数通常 < 20 ✗")
    print("   ⇒ 单周胜率**不能**当因子有效性证据 ✗ 要看**连续 8-12 周**趋势 ✓")
    return 0


def _run_with_persist(argv=None):
    """跑 `main` 并把 stdout **同时落盘**到 `evolution/memory/weekly-<date>.md` ✓

    🔴 2026-11-12 用户要求：原来只 `print()` ✗ ⇒ 内容全在 Mac 的
       `/tmp/fg_weekly_review.log` 里 ✗ —— `/tmp` 重启就没、也没进 git ✗
       ⇒ 复盘结论**必须落盘**才能被后续追踪 ✓
       （`evolution/memory/` 里原有的是 `evolve_h001.py` 写的 H-001 记忆 ✗
         不是复盘产出 ✗，此前一直被误当成「复盘没跑」✗）

    用 Tee 而不是改所有 `print` ✓ —— main 里有 3 个 return 点、20+ 处 print ✗
    """
    import io as _io

    _buf = _io.StringIO()
    _old = sys.stdout

    class _Tee:
        def write(self, s):
            _old.write(s)
            _buf.write(s)

        def flush(self):
            _old.flush()

    sys.stdout = _Tee()
    try:
        rc = main(argv)
    finally:
        sys.stdout = _old

    txt = _buf.getvalue()
    if rc == 0 and txt.strip():
        try:
            out_dir = REPO / "evolution" / "memory"
            out_dir.mkdir(parents=True, exist_ok=True)
            stamp = pd.Timestamp.now().strftime("%Y-%m-%d")
            p = out_dir / ("weekly-%s.md" % stamp)
            p.write_text(txt, encoding="utf-8")
            _old.write("\n[落盘] %s\n" % p)
        except OSError as exc:            # 落盘失败不改变退出码 ✓
            _old.write("\n[落盘失败] %s\n" % str(exc)[:120])
    return rc


if __name__ == "__main__":
    sys.exit(_run_with_persist())
