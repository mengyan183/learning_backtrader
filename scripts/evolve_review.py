#!/usr/bin/env python3
"""
evolve_review.py — LLM 体检与假说登记自动化（进化闭环 ③→④，不依赖 backtest）。

输入：
  - Data/features.csv 尾部（系统信号：zone/核心仓/弹药/熔断/极端标记/vix 等）
  - Data/accounts.csv + Data/positions.csv 最新行（实盘快照，由 sync_positions.py 产出）
  - evolution/LESSONS.md + 最近 7 天 evolution/memory/*.md（防重复提出已证伪假说）

流程：
  1. 组装"判据先行"prompt（只报现象 → 候选假说；强制 JSON schema）
  2. 调用 Hermes API server(8642)（GLM 主 + NVIDIA fallback）；失败降级 NVIDIA 直连
  3. 解析并校验：候选假说三要素（假设/检验方法/不成立判据）缺一作废
  4. 登记新假说（自动编号 H-xxx，按 assumption 去重）到 evolution/hypotheses.md
  5. 体检报告追加到 evolution/memory/YYYY-MM-DD.md

红线遵守：本脚本只"建议与登记"，永不修改 config.py / 生产代码；登记 ≠ 采纳。
"""
import json
import os
import re
import sys
import csv
import urllib.request
import urllib.error
import subprocess
from datetime import date, datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVO = os.path.join(BASE, "evolution")
MEM_DIR = os.path.join(EVO, "memory")
HYP = os.path.join(EVO, "hypotheses.md")
LESSONS = os.path.join(EVO, "LESSONS.md")
FEATURES = os.path.join(BASE, "Data", "features.csv")
ACCOUNTS = os.path.join(BASE, "Data", "accounts.csv")
POSITIONS = os.path.join(BASE, "Data", "positions.csv")

HERMES_URL = "http://127.0.0.1:8642/v1/chat/completions"
HERMES_KEY = os.environ.get("API_SERVER_KEY", "32b64f3f308f403fffbe1c989acd9a9af32743a9a5e35d7a7b4d293e566f6ddc")
NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
NVIDIA_PROXY = "http://127.0.0.1:7890"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) curl/8.4.0"  # NVIDIA WAF 拦截无 UA 的 urllib 请求


def _read_secret_env():
    """从 ~/.hermes/.env 与 Hermes gateway plist 提取键值对（避免在仓库硬编码 key）。"""
    env = {}
    p = os.path.expanduser("~/.hermes/.env")
    if os.path.exists(p):
        for ln in open(p):
            if "=" in ln and not ln.strip().startswith("#"):
                k, _, v = ln.strip().partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
    plist = os.path.expanduser("~/Library/LaunchAgents/com.xingguo.hermes.gateway.plist")
    if os.path.exists(plist):
        s = open(plist).read()
        for m in re.finditer(r"export\s+(\w+)=([^;\s]+)", s):
            env[m.group(1)] = m.group(2)
    return env


_SECRETS = _read_secret_env()
NVIDIA_KEY = os.environ.get("NVIDIA_API_KEY") or _SECRETS.get("NVIDIA_API_KEY", "")

SCHEMA_HINT = """输出必须是合法 JSON，结构如下（字段名勿改，缺字段即失败）：
{
  "phenomena": ["可核验的现象陈述1", "..."],
  "extreme_flags": ["极端标记（数值化，如：AXTX 浮亏 -58.9%）", "..."],
  "testable_observations": ["未来可检验的观察点（何时看什么数据、如何判定）", "..."],
  "falsification_suggestions": ["对某现象的证伪判据建议", "..."],
  "candidate_hypotheses": [
    {"assumption": "可证伪的假设（单句）",
     "test_method": "检验方法（数据、区间、统计量）",
     "falsify_criteria": "不成立判据（明确数值/条件）",
     "evidence_source": "现象来源（输入中的具体文件/列/日期，必须能指回输入）"}
  ]
}"""


def read_features_tail(n=10):
    if not os.path.exists(FEATURES):
        return "(features.csv 不存在，本次跳过信号侧输入)"
    with open(FEATURES, newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return "(features.csv 为空)"
    tail = rows[-n:]
    return "\n".join(
        " | ".join(r.get(k, "") for k in ("date", "zone", "core_position", "ammo_position",
                                          "drawdown", "circuit_breaker", "extreme", "vix"))
        for r in tail
    )


def read_snapshot():
    acc, pos = [], []
    if os.path.exists(ACCOUNTS):
        with open(ACCOUNTS, newline="") as f:
            acc = [r for r in csv.DictReader(f) if r.get("account") == "stock"]
    if os.path.exists(POSITIONS):
        with open(POSITIONS, newline="") as f:
            pos = list(csv.DictReader(f))
    acc_txt = "\n".join(" | ".join(r.get(k, "") for k in ("date", "net_value", "securities_mv",
                          "cash", "day_pnl")) for r in acc[-1:]) or "(无快照)"
    pos_txt = "\n".join(" | ".join(r.get(k, "") for k in ("date", "symbol", "name", "qty",
                          "price", "market_value")) for r in pos[-8:]) or "(无持仓)"
    return acc_txt, pos_txt


def read_recent_context():
    lines = []
    if os.path.exists(LESSONS):
        lines.append("== LESSONS.md ==")
        lines.append(open(LESSONS).read()[:800])
    today = date.today()
    for i in range(7):
        d = (today - timedelta(days=i)).isoformat()
        p = os.path.join(MEM_DIR, f"{d}.md")
        if os.path.exists(p):
            lines.append(f"== memory/{d}.md ==")
            lines.append(open(p).read()[:600])
    return "\n".join(lines) or "(无历史日志)"


def build_prompt():
    feat = read_features_tail()
    acc_txt, pos_txt = read_snapshot()
    ctx = read_recent_context()
    return f"""你是贪恐交易系统的"进化建议者"（只读研究通道，禁止给操作建议）。

输入（今日信号 + 实盘快照 + 历史日志）：
--- 系统信号尾部（features.csv 最近行） ---
{feat}
--- 实盘快照（股票账户） ---
{acc_txt}
--- 持仓快照 ---
{pos_txt}
--- 历史记忆（防重复假说） ---
{ctx}

任务：
1. 体检：只陈述可核验的现象与极端标记，不给"应该怎么办"的操作建议。
2. 从现象中提炼候选假说：每条必须四要素齐全（assumption/test_method/falsify_criteria/evidence_source），
   缺任一要素的候选作废。evidence_source 必须写明输入中的具体文件、列与日期
   （如"features.csv 尾行 2026-10-02 zone=2"），不能写"模型分析/经验判断"这类不可指回来源。
   与历史日志重复的假说不要重复提出。
3. 严格按以下 schema 输出合法 JSON，不要输出 JSON 以外的文字。

{SCHEMA_HINT}"""


def call_llm(prompt, timeout=240):
    """先 Hermes 8642；失败/超时降级 NVIDIA 直连（curl 子进程，WAF 对 urllib 拦截）。返回 (text, via)。"""
    body = json.dumps({
        "model": "hermes-agent",
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(HERMES_URL, data=body, method="POST",
                                 headers={"Authorization": f"Bearer {HERMES_KEY}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read())
            return d["choices"][0]["message"]["content"], "hermes(8642)"
    except Exception as e:
        print(f"[evolve_review] Hermes 失败：{e}，降级 NVIDIA 直连", file=sys.stderr)
    if not NVIDIA_KEY:
        raise RuntimeError("Hermes 不可用且无 NVIDIA_API_KEY")
    nv_body = json.dumps({
        "model": "deepseek-ai/deepseek-v4.1-flash",
        "messages": [{"role": "user", "content": prompt}],
        "chat_template_kwargs": {"thinking": False},
        "max_tokens": 1600,
    })
    tmp = os.path.join("/tmp", f"nv_req_{os.getpid()}.json")
    with open(tmp, "w") as f:
        f.write(nv_body)
    try:
        out = subprocess.run(
            ["curl", "-s", "-m", "300", "-x", NVIDIA_PROXY,
             NVIDIA_URL,
             "-H", f"Authorization: Bearer {NVIDIA_KEY}",
             "-H", "Content-Type: application/json",
             "--data-binary", f"@{tmp}"],
            capture_output=True, text=True, timeout=320)
    finally:
        os.remove(tmp)
    if out.returncode != 0:
        raise RuntimeError(f"NVIDIA curl 失败 rc={out.returncode}: {out.stderr[:200]}")
    d = json.loads(out.stdout)
    return d["choices"][0]["message"]["content"], "nvidia-direct"


def extract_json(text):
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.S)
    if m:
        text = m.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise


def next_hyp_id():
    if not os.path.exists(HYP):
        return "H-001"
    ids = re.findall(r"H-(\d+)", open(HYP).read())
    return f"H-{max((int(i) for i in ids), default=0) + 1:03d}"


def register_hypotheses(cands, via):
    today = date.today().isoformat()
    added = []
    existing = open(HYP).read() if os.path.exists(HYP) else ""
    for c in cands or []:
        if not isinstance(c, dict):
            continue
        a = str(c.get("assumption", "")).strip()
        t = str(c.get("test_method", "")).strip()
        f = str(c.get("falsify_criteria", "")).strip()
        e = str(c.get("evidence_source", "")).strip()
        if not (a and t and f):
            print(f"[evolve_review] 三要素不全，作废：{a[:40] or '(空假设)'}")
            continue
        if not e or e.lower() in ("模型分析", "经验判断", "历史经验", "常识"):
            print(f"[evolve_review] 缺证据来源，作废：{a[:40]}")
            continue
        if a[:50] in existing:
            print(f"[evolve_review] 已登记过，跳过：{a[:40]}")
            continue
        hid = next_hyp_id()
        row = (f"| {hid} | {today} | {a} | {t} | {f} | open | "
               f"由 evolve_review 自动登记（{via}）；证据：{e[:60]} |")
        with open(HYP, "a") as fh:
            fh.write(row + "\n")
        added.append(hid)
        existing += row
    return added


def log_memory(report, via, added):
    os.makedirs(MEM_DIR, exist_ok=True)
    p = os.path.join(MEM_DIR, date.today().isoformat() + ".md")
    with open(p, "a") as f:
        f.write(f"\n## LLM 体检（evolve_review 自动，{via}）\n")
        f.write(f"现象 {len(report.get('phenomena', []))} 条；极端标记 {len(report.get('extreme_flags', []))} 条\n")
        f.write(f"极端标记：{'；'.join(report.get('extreme_flags', []))[:400]}\n")
        f.write(f"观察点：{'；'.join(report.get('testable_observations', []))[:400]}\n")
        f.write(f"登记假说：{', '.join(added) if added else '无（三要素不全或重复）'}\n")


def main():
    prompt = build_prompt()
    text, via = call_llm(prompt)
    report = extract_json(text)
    if not isinstance(report, dict):
        raise ValueError("LLM 输出不是 JSON 对象")
    added = register_hypotheses(report.get("candidate_hypotheses"), via)
    log_memory(report, via, added)
    print(f"[evolve_review] 完成（via={via}）")
    print(f"  现象 {len(report.get('phenomena', []))} 条 | 极端标记 {len(report.get('extreme_flags', []))} 条")
    print(f"  新登记假说：{', '.join(added) if added else '无'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
