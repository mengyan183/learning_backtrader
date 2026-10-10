#!/usr/bin/env python3
"""简报归档轮转（Harness 模式落地 #5：Lineage Compaction 文件版）。

论文映射（docs/harness-engineering-notes.md §13）：Hermes lineage compaction
的轻量文件版——长期简报不销毁（祖先链），但当前工作区只保留最近 N 份，
更早的按月份归档，并维护一个可检索索引 Data/briefs/index.md。

用法：
  .venv/bin/python scripts/archive_briefs.py            # 保留最近 7 天
  .venv/bin/python scripts/archive_briefs.py --keep 30  # 自定义保留天数
"""
import argparse
import re
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "Data"
BRIEFS_DIR = DATA / "briefs"
ARCHIVE = BRIEFS_DIR / "archive"
INDEX = BRIEFS_DIR / "index.md"
PATTERN = re.compile(r"invest_brief_(\d{4}-\d{2}-\d{2})\.md$")


def _brief_summary(path):
    """取简报标题行与首个二级标题作为索引摘要。"""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception as e:
        # G-4：读不到就退回文件名，但**说一声** —— 否则索引里静默少一摘要，
        # 没人知道是文件坏了还是本来就没内容。
        print("[archive_briefs] 读取 %s 失败（摘要留空）: %s" % (path, e),
              file=sys.stderr)
        return ""
    title = next((l.lstrip("# ").strip() for l in lines if l.startswith("# ")), path.name)
    sub = next((l.lstrip("# ").strip() for l in lines if l.startswith("## ")), "")
    return title + (" / " + sub if sub else "")


def archive(keep_days=7):
    moved = []
    cutoff = datetime.now() - timedelta(days=keep_days)
    for p in sorted(DATA.glob("invest_brief_*.md")):
        m = PATTERN.match(p.name)
        if not m:
            continue
        d = datetime.strptime(m.group(1), "%Y-%m-%d")
        if d < cutoff:
            month_dir = ARCHIVE / m.group(1)[:7]
            month_dir.mkdir(parents=True, exist_ok=True)
            dest = month_dir / p.name
            if not dest.exists():
                shutil.move(str(p), str(dest))
            moved.append(dest)
    # 重写索引（重建：根目录最近 N 份 + 全部归档，按日期倒序）
    entries = []
    for p in sorted(DATA.glob("invest_brief_*.md"), reverse=True):
        m = PATTERN.match(p.name)
        if m:
            entries.append((m.group(1), "Data/" + p.name, "active"))
    for p in sorted(ARCHIVE.rglob("invest_brief_*.md"), reverse=True):
        m = PATTERN.match(p.name)
        if m:
            entries.append((m.group(1), "Data/briefs/archive/" + p.relative_to(BRIEFS_DIR).as_posix(), "archive"))
    entries.sort(key=lambda x: x[0], reverse=True)
    lines = ["# 简报索引（Lineage）", "",
             "> 由 scripts/archive_briefs.py 自动维护 · active=工作区保留 · archive=按月归档不销毁",
             ""]
    for date, rel, kind in entries[:500]:
        lines.append(f"- `{date}` [{kind}] {rel}")
    lines.append("")
    BRIEFS_DIR.mkdir(parents=True, exist_ok=True)
    INDEX.write_text("\n".join(lines), encoding="utf-8")
    n_active = sum(1 for e in entries if e[2] == "active")
    print(f"[archive] 归档 {len(moved)} 份，工作区活跃 {n_active} 份，索引 {INDEX}")
    return moved


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", type=int, default=7, help="保留最近 N 天（默认 7）")
    args = ap.parse_args()
    archive(keep_days=args.keep)


if __name__ == "__main__":
    sys.exit(main())
