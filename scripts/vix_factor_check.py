#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐层打印 VIX / TERM 因子的中间值，定位「源有数据但 features 为空」✓。

【背景（2026-11-23）】
  `Data/raw/vix_history.csv` 已确认到 **2026-11-20**（24.56 / 28.44 / 35.89）✓
  但 `Data/features.csv` 的 2026-11-20 行里 `vix` / `term` **仍是空** ✗
  ⇒ 简报连续报「六因子缺 2 个」✗ 而 pipeline 重跑过两次都没修好 ✗

⇒ 本脚本按数据流**逐层**打印，定位断点：
    ① 源文件 `vix_history.csv` 尾行
    ② `sentiment.csv` 尾行（vix 列是否进去）
    ③ `wide` 里 `(VIX, close)` 等输入列尾值
    ④ `VixFactor.raw()` / `.score()` 尾值
    ⑤ `features.csv` 的 vix/term 尾值
  哪一层开始变空，问题就在那层的上一环 ✓

用法（Mac，经 `run_script`）：
    python scripts/vix_factor_check.py
"""
from __future__ import annotations

import json
import os
import sys

import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)


def _tail(s, n=4):
    """Series/DataFrame 尾 n 行 → 可 JSON 化的 dict ✓（NaN 显示为 null）。"""
    try:
        t = s.tail(n)
        if isinstance(t, pd.DataFrame):
            return {"index": [str(x) for x in t.index],
                    "rows": json.loads(t.to_json(orient="values", date_format="iso"))}
        return {str(k): (None if pd.isna(v) else (round(float(v), 6)
                                                  if isinstance(v, (int, float))
                                                  else str(v)))
                for k, v in t.items()}
    except Exception as e:                       # noqa: BLE001
        return {"error": "%s: %s" % (type(e).__name__, str(e)[:120])}


def main():
    out = {}
    raw_dir = os.path.join(REPO, "Data", "raw")

    # ① 源文件
    try:
        p = os.path.join(raw_dir, "vix_history.csv")
        df = pd.read_csv(p, parse_dates=["date"]).set_index("date")
        out["① vix_history.csv"] = {"rows": len(df),
                                    "columns": list(df.columns),
                                    "tail": _tail(df.iloc[:, 0])}
    except Exception as e:                       # noqa: BLE001
        out["① vix_history.csv"] = {"error": str(e)[:200]}

    # ② sentiment.csv
    try:
        p = os.path.join(raw_dir, "sentiment.csv")
        df = pd.read_csv(p, parse_dates=["date"]).set_index("date")
        out["② sentiment.csv"] = {"rows": len(df),
                                  "columns": list(df.columns),
                                  "tail_vix": _tail(df["vix"]) if "vix" in df else "无 vix 列"}
    except Exception as e:                       # noqa: BLE001
        out["② sentiment.csv"] = {"error": str(e)[:200]}

    # ③ wide 输入列
    try:
        from fg_system import pipeline
        wide = pipeline.load_wide()
        cols = [c for c in wide.columns
                if any(k in str(c).upper() for k in ("VIX", "TERM", "VXV"))]
        out["③ wide"] = {"rows": len(wide),
                         "cols_found": [str(c) for c in cols],
                         "last_index": str(wide.index[-1])[:10]}
        for c in cols:
            out["③ wide"]["tail_%s" % str(c)] = _tail(wide[c])
    except Exception as e:                       # noqa: BLE001
        out["③ wide"] = {"error": "%s: %s" % (type(e).__name__, str(e)[:200])}
        wide = None

    # ④ 因子 raw / score
    for name, cls_path in (("VIX", "fg_system.factors.vix"),
                           ("TERM", "fg_system.factors.term")):
        key = "④ %s 因子" % name
        if wide is None:
            out[key] = {"skipped": "wide 不可用"}
            continue
        try:
            mod = __import__(cls_path, fromlist=["*"])
            klass = next((getattr(mod, n) for n in dir(mod)
                          if n.endswith("Factor") and n != "Factor"), None)
            if klass is None:
                out[key] = {"error": "找不到 Factor 类"}
                continue
            f = klass()
            raw = f.raw(wide)
            score = f.score(wide)
            out[key] = {"class": klass.__name__,
                        "raw_tail": _tail(raw),
                        "score_tail": _tail(score)}
        except Exception as e:                   # noqa: BLE001
            out[key] = {"error": "%s: %s" % (type(e).__name__, str(e)[:200])}

    # ⑤ features.csv
    try:
        p = os.path.join(REPO, "Data", "features.csv")
        df = pd.read_csv(p, parse_dates=["date"]).set_index("date")
        cols = [c for c in ("vix", "term", "price", "breadth", "fed", "putcall")
                if c in df.columns]
        out["⑤ features.csv"] = {"rows": len(df), "cols": cols,
                                 "tail": json.loads(
                                     df[cols].tail(3).to_json(orient="index",
                                                              date_format="iso"))}
    except Exception as e:                       # noqa: BLE001
        out["⑤ features.csv"] = {"error": str(e)[:200]}

    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
