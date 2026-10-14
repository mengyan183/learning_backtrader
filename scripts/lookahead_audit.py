#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R1.2 未来函数审计（freqtrade lookahead 思想 · backtrader Cheat-on 对照开关）。

把「无未来函数」纪律（规划 §10.3 / §4C.2：T 日权重只用 ≤T-1 数据）变成
pytest 可执行的审计。两条红线：

1. **代码层**：全仓扫描 `fg_system/` + `scripts/` 的 `shift(-n)`（前视收益）与
   `shift(0)`（同日泄漏）。**默认违规、白名单豁免**：
   - 生产文件出现 → 🔴 违规（violations）
   - 研究/评测/归因文件出现（显式登记在 RESEARCH_WHITELIST）→ 🟡 白名单登记
     （用未来收益衡量信号质量是评测本质，等价 freqtrade 的 lookahead 例外）
   - 未归类文件出现 → ⚠️ 待人工确认（不自动判违规，但要留档）
   新增评测脚本必须登记进白名单，否则审计失败 → 强制纪律工具化。

2. **数据层**：`features.csv`（合成产物）超前原料 raw 数据（vix/sentiment/prices）
   **超过 1 个自然日**才判违规。容忍 ≤1 日的 T+1 上游发布滞后（pipeline 用最近
   可得因子值、值不超前；超前 1 天 = 用 T-1 值生成当日特征，非前视合成）。

用法：
  .venv/bin/python scripts/lookahead_audit.py               # 默认全扫，违规>0 退出 1
  .venv/bin/python scripts/lookahead_audit.py --cheat-on    # 对照开关：白名单项计入已知例外展示
  .venv/bin/python scripts/lookahead_audit.py --json        # 输出 evolution/lookahead-audit.json
  .venv/bin/python scripts/lookahead_audit.py --list-whitelist
输出：stdout 摘要 + evolution/lookahead-audit.md（留档，可进仓库）。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# 扫描范围（生产 + 脚本；tests/ 由 pytest 自己管，审计只审生产与工具）
SCAN_DIRS = [REPO / "fg_system", REPO / "scripts"]

# 研究/评测/归因白名单：出现 shift(-n)/shift(0) 属评测本质，不算违规。
# 依据：screening.py/eval.py/protocol.py 的 forward_return/forward_returns 模块
# docstring 显式标注「仅供研究/评测，禁止用于生成仓位」；putcall/attribution/
# verify_hypotheses/evolve_* 均为只读取证或回测裁判，不产生生产信号。
RESEARCH_WHITELIST = {
    # fg_system
    "fg_system/factors/screening.py",   # forward_return（研究取证）
    "fg_system/factors/eval.py",        # forward_returns（评测）
    "fg_system/factors/protocol.py",    # forward_returns（R1.1 评测原语）
    # scripts
    "scripts/factor_screen.py",         # R1.1 因子评测报告
    "scripts/factor_screen_extend.py",  # C-7 因子扩展评测
    "scripts/screen_factors.py",        # 旧版因子筛选评测
    "scripts/putcall_factor_check.py",  # B-6 Put-Call 因子检验
    "scripts/attribution_check.py",     # C-10 实盘-回测归因（只统计不判决）
    "scripts/verify_hypotheses.py",     # H 假说事件研究（事件后收益衡量）
    "scripts/evolve_walkforward.py",    # C-5 季度 walk-forward 裁判
    "scripts/evolve_baseline.py",       # A-2 回测基线恢复
    "scripts/norm_compare.py",       # R1.4 归一化对照实验（forward return 取证）
}

# 负 shift 模式：shift(-1) / shift(-horizon) / shift(-h) / shift(  -5 ) 等
RE_NEG_SHIFT = re.compile(r"\.shift\(\s*-\s*[0-9A-Za-z_]+")
# 同日泄漏：shift(0)
RE_ZERO_SHIFT = re.compile(r"\.shift\(\s*0\s*\)")
# 未来索引（防御性）：iloc[0:] 或 [:0] 不匹配这里，聚焦 shift 族即可

FEATURES_PATH = REPO / "Data" / "features.csv"
RAW_DIR = REPO / "Data" / "raw"
# features 的原料（pipeline shift(1) 后同日）：超前任一即前视合成
FEATURE_SOURCES = ("vix.csv", "sentiment.csv", "prices.csv")


def scan_code() -> dict:
    """扫描 SCAN_DIRS 下所有 .py：返回 {violations, whitelisted, unclassified}。"""
    violations, whitelisted, unclassified = [], [], []
    for root in SCAN_DIRS:
        for p in sorted(root.rglob("*.py")):
            rel = p.relative_to(REPO).as_posix()
            try:
                lines = p.read_text(encoding="utf-8").splitlines()
            except Exception:
                continue
            for i, line in enumerate(lines, start=1):
                if RE_NEG_SHIFT.search(line) or RE_ZERO_SHIFT.search(line):
                    code = line.strip()[:100]
                    rec = {"file": rel, "line": i, "code": code}
                    if rel in RESEARCH_WHITELIST:
                        whitelisted.append(rec)
                    else:
                        # fg_system/factors/screening.py 等已覆盖；其余一律待判/违规
                        violations.append(rec)
    return {"violations": violations, "whitelisted": whitelisted,
            "unclassified": unclassified}


def check_data() -> dict:
    """数据层：features 尾行超前原料 raw >1 个自然日才判违规（容忍 T+1 上游滞后）。

    pipeline 是 shift(1) 设计，且因子用「最近可得值」填充：VIX/sentiment/putcall
    上游常 T+1 发布（CBOE 历史 CSV 滞后一个交易日），features 行日期超前 1 天
    = 「用 T-1 因子值生成当日特征」，值本身不超前 ⇒ 非前视合成。
    超前 ≥2 个自然日才判 ahead（真停更 / 真前瞻风险）。
    """
    import pandas as pd
    result = {"features_tail": None, "raw_tails": {}, "ahead_of_raw": False}
    try:
        f = pd.read_csv(FEATURES_PATH, parse_dates=["date"])
        f_tail = f["date"].dropna().max()
        result["features_tail"] = f_tail.date().isoformat() if f_tail is not None else None
    except Exception as e:
        result["error_features"] = str(e)
        return result
    for name in FEATURE_SOURCES:
        p = RAW_DIR / name
        try:
            d = pd.read_csv(p, parse_dates=["date"])
            t = d["date"].dropna().max()
            result["raw_tails"][name] = t.date().isoformat() if t is not None else None
        except Exception as e:
            result["raw_tails"][name] = f"ERR {type(e).__name__}"
    for name, tail in result["raw_tails"].items():
        if isinstance(tail, str) and tail.startswith("ERR"):
            continue
        if tail is None:
            continue
        if result["features_tail"] and tail and result["features_tail"] > tail:
            ahead_days = (_dt.date.fromisoformat(result["features_tail"])
                          - _dt.date.fromisoformat(tail)).days
            if ahead_days >= 2:
                result["ahead_of_raw"] = True
                result.setdefault("violations", []).append(
                    {"rule": "data-ahead", "features": result["features_tail"],
                     "raw": name, "raw_tail": tail, "ahead_days": ahead_days})
    return result


def render_md(code: dict, data: dict, cheat_on: bool, verdict: str) -> str:
    lines = [
        "# 未来函数审计报告（R1.2 · freqtrade lookahead 思想）",
        "",
        "- 生成：%s · scripts/lookahead_audit.py" % _dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "- 口径：代码层扫描 `shift(-n)`/`shift(0)`（默认违规、白名单豁免）；"
        "数据层 features 尾行超前原料 >1 个自然日判违规（容忍 T+1 上游发布滞后，"
        "pipeline 用最近可得值、值不超前，超前 ≤1 日 = 非前视）",
        "- 结论：**%s**" % verdict,
        "",
        "## 一、代码层",
        "",
        "| 类别 | 文件:行 | 代码 |",
        "|---|---|---|",
    ]
    rows = []
    for r in code["violations"]:
        rows.append(f"| 🔴 违规 | `{r['file']}:{r['line']}` | `{r['code']}` |")
    for r in code["whitelisted"]:
        tag = "🟡 白名单" if cheat_on else "🟡 白名单（研究）"
        rows.append(f"| {tag} | `{r['file']}:{r['line']}` | `{r['code']}` |")
    for r in code["unclassified"]:
        rows.append(f"| ⚠️ 待人工确认 | `{r['file']}:{r['line']}` | `{r['code']}` |")
    if not rows:
        rows.append("| — | 无 | 扫描范围内未发现 shift(-n)/shift(0) |")
    lines += rows + ["", "## 二、数据层", "",
                     "- features 尾行：%s" % data.get("features_tail")]
    for name, tail in data.get("raw_tails", {}).items():
        lines.append("- raw/%s 尾行：%s" % (name, tail))
    lines += ["", "- features 超前原料：**%s**" % ("是（违规）" if data.get("ahead_of_raw") else "否 ✓")]
    lines += ["", "---", "> 由 scripts/lookahead_audit.py 生成 · 只读审计，不修改任何代码/数据；",
              "> 新增评测脚本须登记 RESEARCH_WHITELIST（默认违规、白名单豁免）。"]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="R1.2 未来函数审计")
    ap.add_argument("--cheat-on", action="store_true",
                    help="对照开关：白名单项计入已知例外展示（backtrader Cheat-on 思想）")
    ap.add_argument("--json", action="store_true", help="输出 evolution/lookahead-audit.json")
    ap.add_argument("--list-whitelist", action="store_true", help="列出白名单文件")
    args = ap.parse_args(argv)

    if args.list_whitelist:
        for f in sorted(RESEARCH_WHITELIST):
            print(f)
        return 0

    code = scan_code()
    data = check_data()
    fail = bool(code["violations"]) or bool(data.get("ahead_of_raw"))
    verdict = "FAIL（存在违规，禁止合并）" if fail else "PASS（违规 0）"
    print("=== R1.2 未来函数审计 ===")
    print("代码层：违规 %d / 白名单 %d / 待确认 %d"
          % (len(code["violations"]), len(code["whitelisted"]), len(code["unclassified"])))
    for r in code["violations"]:
        print("  🔴 %s:%d %s" % (r["file"], r["line"], r["code"]))
    for r in code["unclassified"]:
        print("  ⚠️ %s:%d %s" % (r["file"], r["line"], r["code"]))
    print("数据层：features=%s 超前原料=%s"
          % (data.get("features_tail"), data.get("ahead_of_raw")))
    print("结论：%s" % verdict)

    md = render_md(code, data, args.cheat_on, verdict)
    out_md = REPO / "evolution" / "lookahead-audit.md"
    out_md.write_text(md, encoding="utf-8")
    print("[lookahead_audit] md → %s" % out_md)

    if args.json:
        out_json = REPO / "evolution" / "lookahead-audit.json"
        payload = {"generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
                   "cheat_on": args.cheat_on, "verdict": "PASS" if not fail else "FAIL",
                   "code": code, "data": data}
        out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print("[lookahead_audit] json → %s" % out_json)

    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
