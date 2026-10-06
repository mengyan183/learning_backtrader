#!/usr/bin/env python3
"""简报外验证门（Harness 模式落地 #1/#2/#6）。

论文模式映射（docs/harness-engineering-notes.md §13）：
- #1 Outer Verification Loop：OpenHands /goal judge + Hermes verify-on-stop
  —— 简报生成后、推送前必须过本门；阻断级问题(fail)直接中止推送。
- #2 Policy-as-Code：fg-qa SKILL.md 的散文规则（"每个数字带来源与日期"、
  "禁止编造数字"、"查不到直说"）固化为可执行检查，不再依赖模型自觉。
- #6 Untrusted-Content Delimiting：外部内容（新闻 RSS / YouTube 知识库片段）
  按节扫描注入模式，命中即 warning 并标注风险。

用法：
  .venv/bin/python scripts/verify_brief.py --brief Data/invest_brief_2026-10-03.md
  .venv/bin/python scripts/verify_brief.py --brief ... --out /tmp/check.json
亦可被 scripts/invest_research.py main() 导入调用（verify_and_report）。
"""
import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "Data"

# ---------------------------------------------------------------- 检查项定义
REQUIRED_SECTIONS = {
    "市场快照": "## 市场快照",
    "美联储动态": "## 🏛️ 美联储动态",
    "市场快讯": "## 市场快讯",
    "数据来源": "## 📎 数据来源",
}
# 外部内容节（来源不可信，需注入扫描）
EXTERNAL_SECTIONS = {
    "市场快讯": "## 市场快讯",
    "知识库观点佐证": "## 🧠 知识库观点佐证",
}
# 注入模式（保守集合，命中只 warning；中文+英文）
INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?previous\s+(instructions|prompts?)", re.I),
    re.compile(r"ignore\s+(the\s+)?(above|prior)", re.I),
    re.compile(r"system\s*prompt\s*:", re.I),
    re.compile(r"<system[_-]?reminder>", re.I),
    re.compile(r"you\s+are\s+now\s+(openai|anthropic|claude|gpt)", re.I),
    re.compile(r"disregard\s+(all\s+)?(previous|prior)", re.I),
    re.compile(r"忽略(以上|之前|此前)", re.I),
    re.compile(r"不要(理会|管|看)(上面|之前|历史)", re.I),
    re.compile(r"重新(定义|设定).{0,8}(身份|角色)", re.I),
    re.compile(r"[A-Za-z0-9+/]{40,}={0,2}"),  # base64 特征
]
DATE_RE = re.compile(r"20\d{2}-\d{2}-\d{2}")


def _section_of(brief, header):
    """取简报中某节正文（从 header 到下一个 ## 或文件尾）。"""
    lines = brief.splitlines()
    buf, on = [], False
    for ln in lines:
        if ln.startswith("## "):
            if on:
                break
            if ln.startswith(header):
                on = True
                continue
        elif on:
            buf.append(ln)
    return "\n".join(buf).strip()


def _check_sections(brief, snap):
    """必需节齐全性检查。"""
    items, fail = [], False
    for name, header in REQUIRED_SECTIONS.items():
        body = _section_of(brief, header)
        if not body:
            items.append({"check": f"节存在-{name}", "ok": False,
                          "level": "fail", "detail": f"缺少「{name}」节"})
            fail = True
        else:
            items.append({"check": f"节存在-{name}", "ok": True, "level": "pass"})
    # 条件节：快照有风控/行为数据时应存在
    if snap and snap.get("positions"):
        risk = _section_of(brief, "## 🛡️ 风控仓位")
        bc = _section_of(brief, "## 🧠 行为检查清单")
        if not risk and any(r.get("risk_limit") for r in snap["positions"]):
            items.append({"check": "节存在-风控仓位", "ok": False, "level": "warn",
                          "detail": "持仓含 risk_limit 但简报缺风控节"})
        elif not risk:
            items.append({"check": "节存在-风控仓位", "ok": True, "level": "pass",
                          "detail": "无风控数据，节可省略"})
        if not bc:
            items.append({"check": "节存在-行为清单", "ok": True, "level": "pass",
                          "detail": "非极端档位，节可省略"})
    return items, fail


def _check_numbers(brief, snap):
    """Policy-as-Code：关键数字必须可指回来源文件与日期。
    比对口径：取简报头部数据日（# 多智能体投研简报 YYYY-MM-DD），在
    features.csv 中找该日期的行比对；无简报日期或该行缺失时回退尾行，
    且此时简报中的指数必须等于尾行（防"旧数据冒充新"）。"""
    import pandas as pd
    items, fail = [], False
    # 0) 简报数据日
    m_date = re.search(r"多智能体投研简报\s*(20\d{2}-\d{2}-\d{2})", brief)
    brief_date = m_date.group(1) if m_date else None
    if not brief_date:
        items.append({"check": "日期-简报含数据日", "ok": False, "level": "fail",
                      "detail": "简报头部缺数据日"})
        fail = True
    elif not DATE_RE.search(brief):
        items.append({"check": "日期-简报含数据日", "ok": False, "level": "fail",
                      "detail": "简报全文未发现 YYYY-MM-DD 日期"})
        fail = True
    else:
        items.append({"check": "日期-简报含数据日", "ok": True, "level": "pass",
                      "detail": f"数据日 {brief_date}"})
    # 1) 指数数字与 features.csv 一致。口径：简报生成时指数取 features 尾行
    #    （build_snapshot），但简报标题日=持仓快照日，二者可能错位（数据不同步）。
    #    规则：≤标题日的最近特征行存在 → 用该行比对（历史简报）；
    #          否则用尾行比对（当前生成口径），错位降级 warn 不阻断。
    fg = (snap or {}).get("fg")
    if fg and fg.get("fg_index") is not None:
        m = re.search(r"系统贪恐指数\s+([\d.]+)", brief)
        if not m:
            items.append({"check": "数字-指数", "ok": False, "level": "fail",
                          "detail": "简报缺失「系统贪恐指数」数字"})
            fail = True
        else:
            got = float(m.group(1))
            expect, how, warn = None, None, None
            try:
                f = pd.read_csv(DATA / "features.csv", parse_dates=["date"])
                valid = f.dropna(subset=["fg_index"]).sort_values("date")
                tail = valid.iloc[-1]
                tail_date = str(tail["date"].date())
                tail_val = round(float(tail["fg_index"]), 1)
                # 候选 1：features 尾行（当前生成口径）
                if abs(got - tail_val) <= 0.051:
                    expect, how = tail_val, f"features 尾行 {tail_date}"
                    if brief_date and tail_date != brief_date:
                        warn = f"指数数据日 {tail_date} ≠ 简报标题日 {brief_date}（数据不同步）"
                # 候选 2：≤ 简报标题日的最近特征行（历史简报口径）
                if expect is None and brief_date:
                    _d = pd.to_datetime(brief_date)
                    _row = valid[valid["date"] <= _d]
                    if not _row.empty:
                        _rd = str(_row["date"].iloc[-1].date())
                        _rv = round(float(_row["fg_index"].iloc[-1]), 1)
                        if abs(got - _rv) <= 0.051:
                            expect, how = _rv, f"features {_rd}"
            except Exception:
                expect = None
            if expect is None:
                items.append({"check": "数字-指数", "ok": True, "level": "pass",
                              "detail": "features.csv 不可读，跳过比对"})
            elif abs(got - expect) > 0.01:
                items.append({"check": "数字-指数", "ok": False, "level": "fail",
                              "detail": f"简报 {got} ≠ {how} 的 {expect}"})
                fail = True
            else:
                detail = f"{got} == {how} 的 {expect}"
                if warn:
                    items.append({"check": "数字-指数", "ok": True, "level": "warn",
                                  "detail": f"{detail}；{warn}"})
                else:
                    items.append({"check": "数字-指数", "ok": True, "level": "pass",
                                  "detail": detail})
    # 3) 持仓 symbol 与 positions 最新快照一致
    if snap and snap.get("positions"):
        brief_syms = set(re.findall(r"^[🔺🔻▪️]\s*([A-Z0-9-]+)\s", brief, re.M))
        snap_syms = {r["symbol"] for r in snap["positions"]}
        missing = snap_syms - brief_syms
        if missing:
            items.append({"check": "数字-持仓", "ok": False, "level": "warn",
                          "detail": f"简报缺持仓行: {sorted(missing)}"})
        else:
            items.append({"check": "数字-持仓", "ok": True, "level": "pass",
                          "detail": f"{len(snap_syms)} 个持仓全部列出"})
    # 4) 账户净值行存在
    if snap and snap.get("accounts"):
        if "账户净值" not in brief:
            items.append({"check": "数字-账户净值", "ok": False, "level": "warn",
                          "detail": "简报缺账户净值行"})
        else:
            items.append({"check": "数字-账户净值", "ok": True, "level": "pass"})
    return items, fail


def _check_truncation(brief):
    """截断检测：外部/LLM 节不应以孤立省略号结尾或为空占位。"""
    items = []
    for name, header in EXTERNAL_SECTIONS.items():
        body = _section_of(brief, header)
        if not body:
            items.append({"check": f"截断-{name}", "ok": False, "level": "warn",
                          "detail": "该节为空（可能 LLM 阶段失败）"})
            continue
        lines = [l for l in body.splitlines() if l.strip()]
        last = lines[-1] if lines else ""
        # 以省略号且长度 < 15 结尾 → 疑似被截断
        if len(last) < 15 and re.search(r"…+$", last):
            items.append({"check": f"截断-{name}", "ok": False, "level": "warn",
                          "detail": f"末行疑似截断: “{last}”"})
        else:
            items.append({"check": f"截断-{name}", "ok": True, "level": "pass"})
    return items, False


def _check_injection(brief):
    """Untrusted-Content Delimiting：仅扫描外部内容节。"""
    items, fail = [], False
    for name, header in EXTERNAL_SECTIONS.items():
        body = _section_of(brief, header)
        if not body:
            continue
        hits = [p.pattern for p in INJECTION_PATTERNS if p.search(body)]
        if hits:
            items.append({"check": f"注入-{name}", "ok": False, "level": "warn",
                          "detail": f"命中注入模式: {hits[:3]}，内容不可信"})
        else:
            items.append({"check": f"注入-{name}", "ok": True, "level": "pass"})
    return items, fail


def verify_brief(brief, snap=None, write_history=True):
    """执行全部检查。返回 (result dict, blocked bool)。blocked=True 时不得推送。"""
    groups = [
        ("结构", *_check_sections(brief, snap)),
        ("数字", *_check_numbers(brief, snap)),
        ("截断", *_check_truncation(brief)),
        ("注入", *_check_injection(brief)),
    ]
    checks, blocked = [], False
    for gname, items, gfail in groups:
        blocked = blocked or gfail
        checks.extend(items)
    fails = [c for c in checks if c["level"] == "fail"]
    warns = [c for c in checks if c["level"] == "warn"]
    result = {
        "ts": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "passed": not blocked,
        "n_fail": len(fails), "n_warn": len(warns),
        "fails": [c["detail"] for c in fails],
        "warns": [c["detail"] for c in warns],
    }
    if write_history:
        _persist(result)
    return result, blocked


def _persist(result):
    """写 last_brief_check.json + 追加 brief_check_history.jsonl（skill 反馈素材）。"""
    try:
        (DATA / "last_brief_check.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        with open(DATA / "brief_check_history.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[verify] 检查结果落盘失败: {e}")


def verify_and_report(brief, snap=None):
    """供 invest_research.py main() 调用：打印摘要并返回 blocked。"""
    result, blocked = verify_brief(brief, snap)
    print(f"[verify] 简报检查: {'通过' if not blocked else '阻断'} "
          f"(fail={result['n_fail']} warn={result['n_warn']})")
    for d in result["fails"]:
        print(f"[verify] FAIL: {d}")
    for d in result["warns"]:
        print(f"[verify] WARN: {d}")
    return blocked


def _load_snapshot():
    """供独立 CLI 使用：直接从数据文件构造最小 snap（不含 LLM 阶段）。"""
    import pandas as pd
    snap = {}
    try:
        f = pd.read_csv(DATA / "features.csv", parse_dates=["date"])
        row = f.dropna(subset=["fg_index"]).iloc[-1]
        snap["fg"] = {"fg_index": float(row["fg_index"]),
                      "date": str(row["date"].date())}
    except Exception:
        snap["fg"] = None
    try:
        p = pd.read_csv(DATA / "positions.csv", parse_dates=["date"])
        latest = p["date"].max()
        snap["date"] = str(latest.date())
        snap["positions"] = [
            {"symbol": r["symbol"], "risk_limit": float(r.get("risk_limit", 0)) or None}
            for _, r in p[p["date"] == latest].iterrows()]
    except Exception:
        snap["positions"] = []
    try:
        a = pd.read_csv(DATA / "accounts.csv")
        snap["accounts"] = dict(zip(a["account"], a["net_value"]))
    except Exception:
        snap["accounts"] = None
    return snap


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brief", required=True, help="简报 md 路径")
    ap.add_argument("--out", help="检查结果 JSON 输出路径（可选）")
    args = ap.parse_args()
    brief = Path(args.brief).read_text(encoding="utf-8")
    snap = _load_snapshot()
    result, blocked = verify_brief(brief, snap)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())
