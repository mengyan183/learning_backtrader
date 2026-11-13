#!/usr/bin/env python3
"""
evolve_review.py — LLM 体检与假说登记自动化（进化闭环 ③→④，不依赖 backtest）。

输入：
  - Data/features.csv 尾部（系统信号：zone/核心仓/弹药/熔断/极端标记/vix 等）
  - Data/accounts.csv + Data/positions.csv 最新行（实盘快照，由 sync_positions.py 产出）
  - evolution/LESSONS.md + 最近 7 天 evolution/memory/*.md（防重复提出已证伪假说）

流程：
  1. 组装"判据先行"prompt（只报现象 → 候选假说；强制 JSON schema）
  2. 调用 Hermes API server(8642)；**不再降级云端**（2026-11-09 用户要求 ✓）
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
import time
import urllib.request
import urllib.error
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



def _read_secret_env():
    """从 ~/.hermes/.env 与 Hermes gateway plist 提取键值对（避免在仓库硬编码 key）。"""
    env = {}
    p = os.path.expanduser("~/.hermes/.env")
    if os.path.exists(p):
        # encoding 必写 ✗：Windows 默认 GBK ⇒ `.env` 含非 ASCII 就崩 ✗
        # （与 `fg_system/human30/llm.py` 同处读取、那边已写 ✓，此处漏了 ✗）
        for ln in open(p, encoding="utf-8"):
            if "=" in ln and not ln.strip().startswith("#"):
                k, _, v = ln.strip().partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
    plist = os.path.expanduser("~/Library/LaunchAgents/com.xingguo.hermes.gateway.plist")
    if os.path.exists(plist):
        s = open(plist).read()
        for m in re.finditer(r"export\s+(\w+)=([^;\s]+)", s):
            env[m.group(1)] = m.group(2)
    return env



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


#: 🔴 2026-11-13 用户裁定：**短超时 + 重试** ✓（原 240s 单次）
#:    实测：`evolve_review` 连续多天 240s 失败（daily 链告警）
#:    ⇒ 240s 单次的问题：一次卡死就占满 4 分钟，且**没有第二次机会** ✗
#:    ⇒ 改 90s × 2 次（总上限 180s < 240s，且第一次失败还能再试）✓
#:    注：hermes 若**真挂了**，改超时也没用 —— 但「偶发慢」时这个策略明显更好 ✓
LLM_TIMEOUT = 90
LLM_RETRIES = 2


def call_llm(prompt, timeout=None, retries=None):
    """调**本机 Hermes 网关**（127.0.0.1:8642）⇒ 返回 (text, via)。

    🔴 2026-11-09 用户要求：**取消 NVIDIA 云端兜底** ✗ ——
       云端降级会掩盖 Hermes 自己的故障 ✗（11-09 实测：Hermes 超时被静默换通道，
       云端输出又被 max_tokens 截断，最后报了个看不懂的 JSONDecodeError ✗）
       ⇒ Hermes 挂了就**响亮失败** ✓
    """
    body = json.dumps({
        "model": "hermes-agent",
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    _to = timeout if timeout is not None else LLM_TIMEOUT
    _nr = retries if retries is not None else LLM_RETRIES
    _last = None
    for _i in range(max(1, _nr)):
        req = urllib.request.Request(HERMES_URL, data=body, method="POST",
                                     headers={"Authorization": f"Bearer {HERMES_KEY}",
                                              "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=_to) as r:
                d = json.loads(r.read())
            return d["choices"][0]["message"]["content"], "hermes(8642)"
        except Exception as exc:          # noqa: BLE001
            _last = exc
            if _i + 1 < _nr:
                # 重试前等 5 秒：hermes 偶发排队时给一点缓冲 ✓
                print(f"[evolve_review] LLM 第 {_i + 1}/{_nr} 次失败"
                      f"（{type(exc).__name__}），5 秒后重试…")
                time.sleep(5)
    raise RuntimeError("Hermes(8642) 调用失败（%d 次 × %ds）：%s"
                       % (_nr, _to, _last)) from _last


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
    ids = re.findall(r"H-(\d+)", open(HYP, encoding="utf-8").read())
    return f"H-{max((int(i) for i in ids), default=0) + 1:03d}"


# ── MT-51：登记前归一化查重 ──────────────────────────────────────────
# 历史问题：H-079~H-083 五条全是重复登记（与 H-070/H-061/H-074/H-063 同义），
# 旧查重只做 a[:50] 子串匹配，措辞不同即漏过。这里改成 token Jaccard。

_NORMALIZE_STRIP = re.compile(
    r"[，。；：、（）()【】\[\]「」『』\"'`~!@#$%^&*_\-+=<>?/\\|0-9.\s]+"
)
# 无意义停用词（中英文），归一化后剔除
_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "and", "or", "of", "to", "in", "on", "at", "for", "with", "by", "from",
    "when", "if", "then", "than", "that", "this", "these", "those", "it",
    "its", "as", "we", "you", "they", "he", "she", "will", "would", "can",
    "could", "should", "may", "might", "do", "does", "did", "have", "has",
    "had", "not", "no", "but", "so", "such", "also", "into", "over", "under",
    "该", "的", "了", "在", "是", "和", "与", "及", "或", "若", "则", "不", "为",
    "于", "后", "前", "中", "内", "外", "上", "下", "时", "后", "前", "并", "且",
    "也", "都", "就", "只", "被", "把", "让", "向", "从", "到", "将", "此", "其",
    "呈", "为", "即", "均", "全", "个", "项", "条", "次", "日", "天", "年", "月",
}
# 列名/「第 N 列」等引用归一化时直接删掉（不同措辞指同一列）
_COL_REF_RE = re.compile(
    r"features\.csv|positions?\.csv|accounts?\.csv|raw/[a-z_]+\.csv|"
    r"第\s*[0-9、,，\s]+\s*列|"
    r"`?[a-z_]{3,}`?",
    re.IGNORECASE,
)


def _norm_tokens(*texts):
    """把判据文本归一化为 token set：去列名引用/数字/标点/停用词。

    英文用完整词（≥3 字母），中文用单字集合（避免 2-gram 太碎导致 overlap 失真）。
    """
    blob = " ".join(str(t) for t in texts if t)
    # 先删列名引用
    blob = _COL_REF_RE.sub(" ", blob)
    tokens = set()
    for t in re.findall(r"[a-z][a-z_]{2,}", blob.lower()):
        if t not in _STOPWORDS and len(t) >= 3:
            tokens.add(t)
    # 中文单字（剔除停用词单字）
    for ch in re.findall(r"[一-鿿]", blob):
        if ch not in _STOPWORDS:
            tokens.add(ch)
    return tokens


def _load_existing_hypotheses():
    """读 hypotheses.md 所有已有假说的 (id, assumption_tokens)。含 falsified/archived。"""
    if not os.path.exists(HYP):
        return []
    out = []
    for line in open(HYP, encoding="utf-8"):
        m = re.match(r"\|\s*(H-\d+)\s*\|[^|]*\|([^|]*)\|([^|]*)\|([^|]*)\|", line)
        if not m:
            continue
        hid, a, t, f = m.group(1), m.group(2), m.group(3), m.group(4)
        out.append((hid, _norm_tokens(a, t, f)))
    return out


def _is_duplicate(cand_tokens, existing):
    """overlap coefficient ≥ 0.25 判重。

    中文 2-gram 较碎，用 Jaccard 会低估相似度；改用 overlap = inter/min(|a|,|b|)
    更适合「新假说引用了已有假说核心关键词」的场景。
    返回 (hid, sim) 或 None。
    """
    if not cand_tokens:
        return None
    best = None
    for hid, ex_tokens in existing:
        if not ex_tokens:
            continue
        inter = len(cand_tokens & ex_tokens)
        denom = min(len(cand_tokens), len(ex_tokens))
        if denom == 0:
            continue
        sim = inter / denom
        if sim >= 0.25 and (best is None or sim > best[1]):
            best = (hid, sim)
    return best


def register_hypotheses(cands, via):
    today = date.today().isoformat()
    added = []
    # 🔴 2026-10-28：必须显式 utf-8 ✗ —— Windows 默认 GBK，而 hypotheses.md 是 UTF-8，
    # 不写 encoding 会在 Windows 上 UnicodeDecodeError（Mac 上恰好默认 UTF-8 所以没暴露 ✗）
    existing = open(HYP, encoding="utf-8").read() if os.path.exists(HYP) else ""
    existing_hyps = _load_existing_hypotheses()  # MT-51：归一化查重
    # MT-68：每日登记上限（防 LLM 一天刷一堆候选积压；只限流，不改判据/阈值 ✓）
    DAILY_REGISTER_CAP = 3
    n_today = sum(
        1 for ln in existing.splitlines()
        if ln.startswith("| H-") and today in ln.split("|")[2]
    )
    for c in cands or []:
        if n_today >= DAILY_REGISTER_CAP:
            print(f"[evolve_review] 今日登记已达上限 {DAILY_REGISTER_CAP} 条，"
                  f"其余候选跳过（防积压 ✓）")
            break
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
        # MT-51：归一化查重（措辞不同但同义 ⇒ 不登记）
        dup = _is_duplicate(_norm_tokens(a, t, f), existing_hyps)
        if dup:
            hid_existing, sim = dup
            print(f"[evolve_review] 判重跳过（与 {hid_existing} Jaccard={sim:.2f}）：{a[:40]}")
            continue
        # R1.7 列名校验质量门：脆弱/虚构列引用 → pending-revise（不登记为 open）
        reason = validate_column_refs(a, t, f)
        if reason:
            hid = next_hyp_id()
            row = (f"| {hid} | {today} | {a} | {t} | {f} | pending-revise | "
                   f"由 evolve_review 自动登记（{via}）；证据：{e[:60]}；"
                   f"**R1.7 列名校验：{reason}** |")
            with open(HYP, "a", encoding="utf-8") as fh:   # 必须 utf-8，见上方注释
                fh.write(row + "\n")
            added.append(hid)
            existing += row
            n_today += 1
            print(f"[evolve_review] 列名校验未过，登记为 pending-revise：{a[:40]} "
                  f"（{reason}）")
            continue
        hid = next_hyp_id()
        row = (f"| {hid} | {today} | {a} | {t} | {f} | open | "
               f"由 evolve_review 自动登记（{via}）；证据：{e[:60]} |")
        with open(HYP, "a", encoding="utf-8") as fh:       # 必须 utf-8，见上方注释
            fh.write(row + "\n")
        added.append(hid)
        existing += row
        n_today += 1
    return added


_FRAGILE_COL_RE = re.compile(r"第\s*[\d、,，\s]+\s*列")
# features.csv 真实列名（R1.7 校验基准，取当前表头）
_FEATURE_COLS = set()
if os.path.exists(FEATURES):
    with open(FEATURES, newline="") as _f:
        _FEATURE_COLS = set(next(csv.reader(_f)))
# 通用词白名单：出现在 features.csv 上下文中但非列名的词不判虚构
_COMMON_TOKENS = {
    "the", "for", "with", "true", "false", "date", "row", "rows", "column",
    "columns", "value", "values", "sample", "samples", "features", "csv",
    "group", "groups", "between", "within", "over", "under", "when", "and",
    "than", "are", "was", "were", "has", "have", "is", "in", "of", "to",
    "by", "at", "from", "this", "that", "这些", "该", "与", "及", "在", "对",
}


def validate_column_refs(*texts):
    """R1.7 假说登记列名校验质量门。

    返回 None=通过；否则返回驳回原因（登记为 pending-revise）：
      1. 「第 N 列」脆弱引用（列序变化即失效，禁止）；
      2. features.csv 上下文中出现真实表头之外的疑似列名（虚构列）。
    """
    for txt in texts:
        if _FRAGILE_COL_RE.search(txt):
            return "使用「第 N 列」脆弱引用，须改写为真实列名（features.csv 表头）"
    # 虚构列检测：仅检查提到 features.csv 的片段
    for txt in texts:
        for seg in re.finditer(r"features\.csv[^。；;|]{0,80}", txt):
            seg_text = seg.group(0)
            for tok in re.findall(r"[a-z_]{2,}", seg_text.lower()):
                if tok in _FEATURE_COLS or tok in _COMMON_TOKENS:
                    continue
                if re.fullmatch(r"(threshold|column[ns]?|field[ns]?|index[es]?|"
                                r"param[ns]?|num[ns]?|col\d+|c\d+)", tok):
                    return "引用虚构列名 %r（不在 features.csv 表头）" % tok
    return None


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
    # 🔴 2026-11-13 排查：`call_llm(timeout=240)` 超时 ⇒ 整个脚本 rc=1 ✗
    #    而 `log_memory()` 在**最后** ✗ ⇒ LLM 一失败就什么都不落盘 ✗
    #    实测：`evolution/memory/` 最新只到 **2026-10-19** ✗
    #    ⇒ **连续 25 天没有新记忆文件** ✗（LLM 一直超时）
    #    ⇒ 加 try/except：**失败也落盘一条**，让「今天跑过但 LLM 挂了」留痕 ✓
    #       rc 仍返 1（保留告警 ✓），但不再「静默无痕」✗
    try:
        text, via = call_llm(prompt)
        report = extract_json(text)
        if not isinstance(report, dict):
            raise ValueError("LLM 输出不是 JSON 对象")
    except Exception as exc:              # noqa: BLE001
        _err = "%s: %s" % (type(exc).__name__, str(exc)[:200])
        print(f"[evolve_review] ✗ LLM 失败：{_err}")
        try:
            _p = os.path.join(MEM_DIR,
                              "%s.md" % datetime.now().strftime("%Y-%m-%d"))
            os.makedirs(MEM_DIR, exist_ok=True)
            with open(_p, "a", encoding="utf-8") as _f:
                _f.write(f"\n## LLM 体检（evolve_review 自动）\n")
                _f.write(f"✗ **本次失败**：{_err}\n")
                _f.write("⇒ 假说登记与极端标记未生成（下次成功时会补写新的一条）\n")
            print(f"[evolve_review] 已落盘失败记录：{_p}")
        except OSError as _e2:
            print(f"[evolve_review] 落盘失败：{_e2}")
        return 1

    added = register_hypotheses(report.get("candidate_hypotheses"), via)
    log_memory(report, via, added)
    print(f"[evolve_review] 完成（via={via}）")
    print(f"  现象 {len(report.get('phenomena', []))} 条 | 极端标记 {len(report.get('extreme_flags', []))} 条")
    print(f"  新登记假说：{', '.join(added) if added else '无'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
