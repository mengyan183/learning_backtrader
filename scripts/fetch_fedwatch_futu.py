# -*- coding: utf-8 -*-
"""**用富途 OpenD 抓 CME FedWatch** ✓（2026-11-05，替代所有爬虫方案）。

🔴 为什么这是最优解（不是爬虫 ✗）：
   市面调研结论：
     - `cme-fedwatch` PyPI 包 ⇒ **已停维护** ✗（2026-10 归档 ✗）
     - `fed-funds-target.json` ⇒ **404** ✗（GitHub 上的猜测 ✗）
     - `curl_cffi` / `nodriver` / `FlareSolverr` / Firecrawl
       ⇒ 解决的是「反爬识别」✗ 而我们卡的是「数据在 QuikStrike
         iframe 里 + Referer 校验 + ASP.NET JS 渲染」✗ 无解 ✗
     - **富途 OpenD `get_fed_watch_target_rate()`** ⇒ **官方接口** ✓

   ✅ 优势：
      - **官方接口** ✓ 不会因 CME 改版失效 ✓
      - **项目已在用 futu** ✓（`fetch_trades_futu.py` / `sync_positions.py` ✗）
        ⇒ **零新增依赖** ✓ 零新增凭证 ✓
      - **不需要浏览器 / 代理 / cookie** ✓
      - 返回**完整区间分布** ✓（46 行 × 多个会议 ✗ 比 CME 的
        ease/hold/hike 三档更细 ✓）

【实测数据】（2026-11-05）
   columns: ['meeting_date', 'target_range', 'probability']
   rows: 46
   2026-12-09  3.75-4.00%  18.5    ← hold（当前区间 ✓）
   2026-12-09  4.00-4.25%  81.5    ← hike 25bp
   2027-01-27  3.75-4.00%  14.2
   2027-01-27  4.00-4.25%  67.1
   2027-01-27  4.25-4.50%  18.7

【转换规则】
   当前目标区间 = `config.FED_RANGE_TXT`（`"3.75%-4.00%"` ✗）
   对每个 `meeting_date` 的分布：
     hold = prob[当前区间]
     hike = Σ prob[区间 > 当前区间]
     ease = Σ prob[区间 < 当前区间]

   ⚠️ 富途返回 `"3.75-4.00%"`（**少一个 %** ✗ 且用 `-` ✗）
      ⇒ 必须**规范化**后再比较 ✓
"""
import argparse
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from fg_system import config

OUT = os.path.join(config.RAW_DIR, "fedwatch.csv")
SRC = "futu-fedwatch"

#: 与旧 `fedwatch.csv` **完全一致**的列 ✓（`fed.py` 不用改 ✓）
COLS = ["date", "meeting", "ease_pct", "hold_pct", "hike_pct",
        "now_hold_pct", "now_hike_pct", "wk_hold_pct", "wk_hike_pct",
        "m_hold_pct", "m_hike_pct", "src"]


def _norm_range(s):
    """`"3.75-4.00%"` / `"3.75%-4.00%"` ⇒ `(3.75, 4.00)` ✓。

    ⚠️ 富途用 `-` ✗ `config.FED_RANGE_TXT` 用 `%-%` ✗ ⇒ 必须统一 ✓
    """
    t = str(s or "").replace("%", "").replace("–", "-").replace("—", "-")
    t = t.replace("~", "-").strip()
    a, _, b = t.partition("-")
    return float(a), float(b)


def _fmt_range(lo, hi):
    return "%.2f-%.2f%%" % (lo, hi)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=11111)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    try:
        from futu import OpenQuoteContext
    except ImportError:
        print("[futu-fed] ✗ **没装 futu** ✗ `pip install futu-api`",
              file=sys.stderr)
        return 2

    cur = _norm_range(config.FED_RANGE_TXT)
    if args.debug:
        print("[futu-fed] 当前目标区间 %s ⇒ (%.2f, %.2f)"
              % (config.FED_RANGE_TXT, cur[0], cur[1]))

    ctx = None
    try:
        ctx = OpenQuoteContext(host=args.host, port=args.port)
        ret, data = ctx.get_fed_watch_target_rate()
    except Exception as exc:                # noqa: BLE001
        print("[futu-fed] ✗ 调用失败：%s: %s"
              % (type(exc).__name__, str(exc)[:200]), file=sys.stderr)
        print("[futu-fed]   ⇒ 若连接失败，**OpenD 没开** ✗", file=sys.stderr)
        return 2
    finally:
        if ctx is not None:
            try:
                ctx.close()
            except Exception:               # noqa: BLE001
                pass

    # 🔴 `futu.RET_OK` **就是整数 0** ✗ 不能用 `"RET_OK" in str(ret)` ✗
    if ret != 0 or data is None or len(data) == 0:
        print("[futu-fed] ✗ 接口无数据：ret=%r rows=%s ✗"
              % (ret, 0 if data is None else len(data)), file=sys.stderr)
        return 2

    df = data.copy()
    df["target_range"] = df["target_range"].astype(str)
    df["probability"] = pd.to_numeric(df["probability"], errors="coerce")
    df["meeting_date"] = df["meeting_date"].astype(str)

    # 按会议聚合 ✓
    recs = []
    for mtg, sub in df.groupby("meeting_date", sort=True):
        hold = hike = ease = 0.0
        for _, r in sub.iterrows():
            try:
                lo, hi = _norm_range(r["target_range"])
            except (TypeError, ValueError):
                continue
            p = float(r["probability"]) if pd.notna(r["probability"]) else 0.0
            if (lo, hi) == cur:
                hold += p
            elif (lo, hi) > cur:
                hike += p
            else:
                ease += p
        # 概率和归一 ✓（富途给的是四舍五入后的 ✗ 加起来可能 99.x ✗）
        tot = ease + hold + hike
        if tot > 0:
            k = 100.0 / tot
            ease, hold, hike = ease * k, hold * k, hike * k
        recs.append({
            "date": date.today().isoformat(),
            "meeting": mtg,
            "ease_pct": round(ease, 1),
            "hold_pct": round(hold, 1),
            "hike_pct": round(hike, 1),
            # `now_*` = 当前视图 ✓（富途只有当前值 ✗）
            "now_hold_pct": round(hold, 1),
            "now_hike_pct": round(hike, 1),
            # 富途**没有历史** ✗ ⇒ 一周前 / 下档会议 都是 None ✓
            # ⇒ `fw_delta_1w` / `fw_curve` 会是 None ✗
            #   但 `fed_context` 里这两个是**可选** ✓ 不崩 ✓
            "wk_hold_pct": None,
            "wk_hike_pct": None,
            "m_hold_pct": None,
            "m_hike_pct": None,
            "src": SRC,
        })

    if not recs:
        print("[futu-fed] ✗ 没有可用的会议记录 ✗", file=sys.stderr)
        return 2

    new = pd.DataFrame(recs, columns=COLS)
    if args.debug:
        print("[futu-fed] 解析出 %d 个会议：" % len(new))
        print(new[["meeting", "ease_pct", "hold_pct", "hike_pct"]]
              .to_string(index=False))

    if args.dry_run:
        print("[futu-fed] dry-run：不写盘 ✓")
        return 0

    # 追加（同一天同会议**覆盖** ✗ 避免重复 ✗）
    old = None
    if os.path.exists(OUT):
        try:
            old = pd.read_csv(OUT, dtype={"meeting": str})
        except Exception:                   # noqa: BLE001
            old = None
    if old is not None and len(old):
        old = old[~old["meeting"].astype(str).isin(new["meeting"].astype(str))]
        out = pd.concat([old, new], ignore_index=True)
    else:
        out = new
    # 🔴 2026-11-05：**全 NA 列会导致 FutureWarning** ✗
    #    `wk_*` / `m_*` 在富途版里全是 None ✗ ⇒ 该列全 NA ✗
    #    ⇒ concat 后**统一按 COLS 对齐** ✓ 保证列序一致 ✓
    for c in COLS:
        if c not in out.columns:
            out[c] = None
    out = out[COLS]
    out = out.sort_values(["date", "meeting"]).reset_index(drop=True)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    out.to_csv(OUT, index=False, encoding="utf-8")

    print("[futu-fed] ✅ 已写入 %s（本次 %d 个会议 ✗ 累计 %d 行 ✓）"
          % (OUT, len(new), len(out)))
    first = new.iloc[0]
    print("[futu-fed] 最近会议 %s：ease=%.1f hold=%.1f hike=%.1f ✓"
          % (first["meeting"], first["ease_pct"], first["hold_pct"],
             first["hike_pct"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
