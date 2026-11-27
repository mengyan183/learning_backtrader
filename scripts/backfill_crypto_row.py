#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把某个交易日的 **crypto 行**按前一交易日的值补齐（2026-11-27 用户裁定）。

【背景】
  11-26 ClashX 代理异常 ⇒ OKX 同步失败 ⇒ `sync_positions` 静默跳过
  ⇒ `positions.csv` / `accounts.csv` 的 11-26 **只有 stock 行**，crypto 整个没了 ✗
  ⇒ 而 11-26 的旧行在当天已被剔除，**文件里没有可保留的** ✗
  ⇒ 代理对 OKX 仍不通（`curl (35) Connection reset`）⇒ 无法重跑恢复 ✓

【本脚本做什么】
  ① 读 `Data/positions.csv` / `Data/accounts.csv`
  ② 取 `--from` 日（默认 11-25）的 crypto 行
  ③ 复制到 `--to` 日（默认 11-26），**note 里明确标注「推断值」** ✓
  ④ `--to` 日已有 crypto 行 ⇒ **跳过**（幂等，不覆盖真实数据）✓
  ⑤ 默认 dry-run，`--apply` 才写盘 ✓

⚠️ **这是推断数据，不是同步数据** ✗
  前提是「11-25 到 11-26 之间没有加密交易」。若期间有买卖，补出来的行是错的 ✗
  所以 note 里必须写明来源，且**不能**让下游把它当真实快照 ✓
"""
from __future__ import annotations

import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "Data")


def _backfill(fn, dfrom, dto, apply):
    p = os.path.join(DATA, fn)
    if not os.path.exists(p):
        return {"file": fn, "ok": False, "error": "文件不存在"}
    df = pd.read_csv(p)
    if "account" not in df.columns or "date" not in df.columns:
        return {"file": fn, "ok": False,
                "error": "缺 date/account 列：%s" % list(df.columns)}

    dfrom = str(dfrom)
    dto = str(dto)
    has_to = bool(((df["date"].astype(str) == dto)
                   & (df["account"] == "crypto")).any())
    if has_to:
        return {"file": fn, "ok": True, "skipped": True,
                "reason": "%s 已有 crypto 行（幂等跳过）" % dto}

    src = df[(df["date"].astype(str) == dfrom)
             & (df["account"] == "crypto")].copy()
    if src.empty:
        return {"file": fn, "ok": False,
                "error": "%s 没有 crypto 行可复制" % dfrom}

    src["date"] = dto
    if "note" in src.columns:
        src["note"] = (src["note"].astype(str)
                       + " ｜ ⚠️ **推断值**：由 %s 复制（OKX 同步失败，"
                         "非实际同步）" % dfrom)
    out = pd.concat([df, src], ignore_index=True)
    out = out.sort_values(["date", "account", "symbol"]
                          if "symbol" in out.columns
                          else ["date", "account"]).reset_index(drop=True)
    if apply:
        out.to_csv(p, index=False)
    return {"file": fn, "ok": True, "skipped": False,
            "copied_rows": int(len(src)),
            "written": bool(apply),
            "preview": src.to_dict(orient="records")[:2]}


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="dfrom", default="2026-11-25")
    ap.add_argument("--to", dest="dto", default="2026-11-26")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    res = [{"from": args.dfrom, "to": args.dto, "apply": args.apply}]
    for fn in ("positions.csv", "accounts.csv"):
        res.append(_backfill(fn, args.dfrom, args.dto, args.apply))
    import json
    print(json.dumps(res, ensure_ascii=False, indent=2))
    ok = all(r.get("ok") for r in res[1:])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
