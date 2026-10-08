# -*- coding: utf-8 -*-
"""守猪待兔双通道对照：页面表格（bsk） vs partner API（第 14.5 条）。

【为什么保留这个对照】
用户决定 `scripts/shoutu_daily.cmd`（Windows）**不切换**到 API，理由是
「目前还需要 API 数据和浏览器页面数据进行对照」。本脚本即该对照工具，
**随时可跑**。

【它验证什么】
  1 API 与页面是否**同口径** —— 实测同一时刻最大差 **0.0**
  2 `emo_area` 是否填错 —— 这是**唯一**会**静默给出错误数值**的字段。
     实测 GDXU 用错 area 时 `us` 给 −61、页面 −73（差 12）；正确 area 差 0。
  3 页面 sweep 是否漏读分类 —— 实测出现过 369 行 / 10 分类（应为 379 / 11）。
  4 **覆盖全部 8 个标的**（2026-09-24 起）—— 11 张分类表**不含** AXTX / CRCG，
     故步骤 1b 会去个股贪恐视图（`#/stock_scan`）补取。不做这一步它们恒为
     `page_missing` ⇒ 那两个标的**从不参与对照**，而它们恰是**实盘持仓**。

【代价】步骤 1b 会对**分类表未覆盖**的标的各发一次「查询」（实测 2 次）。
该查询受「30 个标的 / 30 天」限制，但服务端按标的**去重计数** ⇒ 对已查询过的
标的**不扣额度**（第 14.5 条）。

【用法】
    python scripts/compare_shoutu.py
    python scripts/compare_shoutu.py --tol 1        # 收紧容差
    python scripts/compare_shoutu.py --api-only     # 不读页面，只打印 API 值

退出码：0 = 表内标的全部在容差内；1 = 有超差，或页面零命中。

【只读】不写任何数据文件。
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fg_system import config                     # noqa: E402
from fg_system.data import shoutu                # noqa: E402

import fetch_shoutu as fs                        # noqa: E402

PAGE = "https://fe.szdt.tech/invest/#/etf"
SYMS = list(config.SHOUTU_SYMBOLS)


def read_page_table():
    """**只读**页面 `/#/etf` 全表，返回 `(DataFrame, 读到的行数)`。不落盘。"""
    session = fs.bsk(["session", "start", "--no-focus"]).strip().splitlines()[-1].strip()
    try:
        fs.bsk(["navigate", PAGE], session)
        time.sleep(6)
        raw = fs.bsk_eval(fs.SWEEP, session)
        lines = [l for l in str(raw).split("\n") if l.strip()]
        return shoutu.parse_universe_rows(lines), len(lines)
    finally:
        fs.bsk(["session", "stop", session])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tol", type=float, default=3.0,
                    help="容差（默认 3.0）。该指数实时更新，读页面到调 API 之间"
                         "有几十秒时差；实测同一时刻差 0.0")
    ap.add_argument("--api-only", action="store_true",
                    help="不读页面（不需要 bsk），只打印 API 值")
    args = ap.parse_args()

    page = {}
    if not args.api_only:
        print("=== 1) 页面 %s ===" % PAGE)
        df = None
        try:
            df, n = read_page_table()
            print("  读到 %d 行，解析 %d 行，%d 个分类"
                  % (n, len(df), df["category"].nunique() if len(df) else 0))
            if len(df):
                print("  分类：" + " / ".join(
                    "%s %d" % (k, v) for k, v in df["category"].value_counts().items()))
                # 与 fetch_shoutu.py **共用** universe_values 取值 —— 不许另写一套
                # 后缀匹配：两套写法会造成「判定为已覆盖、却取不到值」的静默缺口。
                page = shoutu.universe_values(df)
        except Exception as exc:
            print("  ⚠️ 页面读取失败：%s: %s" % (type(exc).__name__, exc))
            print("  （bsk 不可用时可用 --api-only 跳过页面）")

        # **分类表未覆盖的标的**（实测 AXTX / CRCG）⇒ 补走个股贪恐视图。
        # 不做这一步它们**恒为 page_missing** ⇒ 那两个标的**从不参与对照**，
        # 等于放弃了「API 与页面同口径」的验证 —— 而 `emo_area` 填错（唯一会
        # **静默给出错误数值**的字段）正是靠这个对照发现的。
        missing = shoutu.missing_symbols(df) if (df is not None and len(df)) else []
        if missing:
            print()
            print("=== 1b) 个股贪恐视图（补分类表未覆盖的：%s）==="
                  % " / ".join(missing))
            try:
                page.update(fs.fetch_scan_scores(missing))
            except Exception as exc:
                print("  ⚠️ 查询失败：%s: %s" % (type(exc).__name__, exc))
                print("  （这些标的会显示为 page_missing，不参与判定）")

    print()
    print("=== 2) API（紧接着同一时刻）===")
    api = shoutu.collect_scores()
    for sym in SYMS:
        lever, area = config.SHOUTU_API_PARAMS[sym]
        print("  %-5s lever=%s emo_area=%-6s score=%s" % (sym, lever, area, api[sym]))

    if args.api_only:
        return 0

    print()
    print("=== 3) 对照（容差 %.1f）===" % args.tol)
    rows, ok = shoutu.compare_page_vs_api(page, api, tol=args.tol)
    print("  %-6s %12s %10s %8s   %s" % ("标的", "页面", "API", "差", "状态"))
    for r in rows:
        fmt = lambda v: "不在表内" if v is None else "%12.1f" % v  # noqa: E731
        print("  %-6s %s %10.1f %8s   %s"
              % (r["symbol"], fmt(r["page"]), r["api"],
                 "—" if r["diff"] is None else "%.1f" % r["diff"], r["status"]))

    covered = [r for r in rows if r["status"] in ("ok", "diff")]
    missing = [r["symbol"] for r in rows if r["status"] == "page_missing"]
    print()
    print("  表内标的 %d 个，最大差 %.1f"
          % (len(covered), max([r["diff"] for r in covered], default=0.0)))
    if missing:
        print("  不在页面表内（API 独有）：%s" % " ".join(missing))
    print("  结论：%s" % ("✅ 一致" if ok else "❌ 超差或页面零命中 —— 需排查 emo_area"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
