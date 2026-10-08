#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C-11 E2 假说/因子绩效衰减自动降级（弱假说归档）。

职责：
  1. 解析 evolution/factors.md 的 F 行 → 按"近窗衰减 horizon 占比"判定状态：
       - 近窗衰减 horizon >= 2/4  → decayed（短窗受限，低优先，仅长窗可用）
       - 样本不足（积累中）       → accumulating（维持登记，数据积累）
       - 其余                    → 维持 draft
  2. 解析 evolution/hypotheses.md 的 H 行 → verifying/adopted 状态监控：
       - 绩效可量化假说（已回测验证，如 H-007）→ 衰减判定走 C-5 季度 walk-forward
       - 观察点/样本积累类（verifying）→ 标注"数据积累监控中"
  3. 输出 evolution/decay-report.md + 写回 factors.md 状态列。

判据口径（与 scripts/drift_monitor.py decide() 同语义）：
  - 近窗 |ICIR| < 全窗 |ICIR| x 0.5 = 衰减；因子登记表里已由 factor_screen 标注
    "X/Y 日近窗衰减"（factor-engine.md §4 门槛"近窗无衰减"）。
  - 方向翻转 → 立即降级（decayed/rejected），本脚本不做方向判定（反向因子语义已核验）。

⚠️ 数字必须可指回 factors.md / hypotheses.md；判据是确定性的（无 LLM 判决）。

用法：.venv/bin/python scripts/evolve_decay.py [--write]
  --write 时写回 factors.md 状态列 + 生成 decay-report.md；否则只输出 dry-run。
"""
import argparse
import os
import re
import sys
from datetime import datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FM = os.path.join(REPO, "evolution", "factors.md")
HM = os.path.join(REPO, "evolution", "hypotheses.md")
OUT = os.path.join(REPO, "evolution", "decay-report.md")

DECAY_THRESHOLD = 2  # 近窗衰减 horizon 数 >= 2/4 → decayed


def parse_factor_rows(text):
    rows = []
    for line in text.splitlines():
        if not line.startswith("| F-"):
            continue
        # 门槛列含 \| 转义：先占位再 split，避免拆裂
        line2 = line.replace("\\|", "\x00")
        cells = [c.strip() for c in line2.strip("|").split("|")]
        if len(cells) < 8:
            continue
        rows.append({"id": cells[0], "date": cells[1], "name": cells[2],
                     "status": cells[6], "note": cells[7]})
    return rows


def decay_horizons(note):
    """统计备注中 'X 日近窗衰减' 的标记数。"""
    # 匹配形如 "5/10 日近窗衰减"、"40 日近窗衰减" 的衰减标记
    hits = re.findall(r"([0-9]+(?:/[0-9]+)*)\s*日近窗衰减", note)
    return len(hits), hits


def classify(row):
    note = row["note"]
    if "样本不足" in note or "积累中" in note:
        return "accumulating", "样本不足，数据积累中"
    n, hits = decay_horizons(note)
    if n >= DECAY_THRESHOLD:
        return "decayed", "近窗衰减 %d/4 horizon（%s），短窗受限、仅长窗可用，低优先" % (
            n, "/".join(hits) if hits else "?")
    if n > 0:
        return row["status"], "近窗衰减 %d/4 horizon（%s），维持观察" % (n, "/".join(hits))
    return row["status"], "无近窗衰减标记，维持"


def main():
    ap = argparse.ArgumentParser(description="C-11 因子/假说衰减降级")
    ap.add_argument("--write", action="store_true",
                    help="写回 factors.md 状态列 + 生成 decay-report.md")
    args = ap.parse_args()

    fm_text = open(FM, encoding="utf-8").read()
    rows = parse_factor_rows(fm_text)
    verdicts = {}
    for r in rows:
        verdicts[r["id"]] = classify(r)

    date_s = datetime.now().strftime("%Y-%m-%d")
    lines = ["# 因子/假说绩效衰减降级报告（C-11，%s）" % date_s, "",
             "> 由 scripts/evolve_decay.py 生成 · 确定性判据（无 LLM 判决）；",
             "> 判据：近窗衰减 horizon >= %d/4 → decayed；样本不足 → accumulating；否则维持。" % DECAY_THRESHOLD,
             "", "## 因子（factors.md F 行）", "",
             "| 编号 | 原状态 | 判定 | 说明 |", "|---|---|---|---|"]
    for r in rows:
        status, why = verdicts[r["id"]]
        lines.append("| %s | %s | **%s** | %s |" % (r["id"], r["status"], status, why))
    lines += ["", "## 假说（hypotheses.md H 行，状态监控）", "",
              "| 编号 | 状态 | 监控判定 |", "|---|---|---|"]
    hm_text = open(HM, encoding="utf-8").read()
    hyp_status = {}
    for line in hm_text.splitlines():
        if not line.startswith("| H-"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 6:
            continue
        hyp_status[cells[0]] = cells[5]
    for hid, st in sorted(hyp_status.items()):
        if st in ("adopted", "verifying", "open"):
            if "回测" in " ".join(hm_text.splitlines()):
                pass
        if st == "adopted":
            lines.append("| %s | %s | 回测/实证型假说：衰减判定走 C-5 季度 walk-forward 重检（本脚本仅登记监控） |"
                         % (hid, st))
        elif st == "verifying":
            lines.append("| %s | %s | 数据积累监控中（观察点/快照不足，随数据自然推进） |" % (hid, st))
        elif st == "open":
            lines.append("| %s | %s | 未验证；H-010~H-022 中 pending-revise 者待登记方修订后检验 |" % (hid, st))
        else:
            lines.append("| %s | %s | 终态，无需监控 |" % (hid, st))

    report = "\n".join(lines) + "\n"
    print(report)
    if args.write:
        # 写回 factors.md 状态列
        out_lines = []
        for line in fm_text.splitlines():
            if line.startswith("| F-") and line.strip():
                cells = [c.strip() for c in line.strip("|").split("|")]
                if len(cells) >= 8:
                    vid = cells[0]
                    if vid in verdicts:
                        new_status, _ = verdicts[vid]
                        cells[6] = new_status
                        line = "| " + " | ".join(cells) + " |"
            out_lines.append(line)
        open(FM, "w", encoding="utf-8").write("\n".join(out_lines) + "\n")
        open(OUT, "w", encoding="utf-8").write(report)
        print("\n✅ 已写回 factors.md 状态列；报告 → %s" % OUT)
    else:
        print("\n(dry-run：未写回，加 --write 生效)")


if __name__ == "__main__":
    main()
