# -*- coding: utf-8 -*-
"""Human 3.0 自评打卡 CLI（组合骨架）。

用法：
  python scripts/human30_cli.py --set --mind 70 --body 55 --spirit 60 --vocation 50 [--note "..."]
      # 四象限自评打卡（0-100，当日重复则覆盖）
  python scripts/human30_cli.py --latest
      # 当前状态：Level / 均分 / 短板 / 建议
  python scripts/human30_cli.py --history [N]
      # 最近 N 条记录（默认 7）
  无参数默认 --latest。
"""
import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from fg_system import human30


def _print_latest():
    rec = human30.latest()
    if not rec:
        print("Human 3.0 尚无自评记录。打卡：python scripts/human30_cli.py --set --mind .. --body .. --spirit .. --vocation ..")
        return
    agg = human30.aggregate(rec)
    print(f"日期 {rec['date']}  |  {agg['level_name']}")
    print(f"四象限均分 {agg['avg']}  |  平衡度 std {agg['std']}{'（失衡）' if agg['imbalanced'] else ''}")
    for q in human30.QUADRANTS:
        print(f"  {human30.LABELS[q]}: {rec[q]:.0f}")
    print(f"短板：{agg['weakest_label']} {agg['weakest_val']:.0f}")
    print("建议：")
    for a in human30.advice(rec, human30.history(2)[-2] if len(human30.history(2)) >= 2 else None):
        print(f"  - {a}")
    if rec.get("note"):
        print(f"备注：{rec['note']}")


def main():
    p = argparse.ArgumentParser(description="Human 3.0 四象限自评打卡")
    p.add_argument("--set", action="store_true", help="打卡")
    p.add_argument("--mind", type=float)
    p.add_argument("--body", type=float)
    p.add_argument("--spirit", type=float)
    p.add_argument("--vocation", type=float)
    p.add_argument("--note", default="")
    p.add_argument("--latest", action="store_true")
    p.add_argument("--history", nargs="?", const=7, type=int)
    args = p.parse_args()

    if args.set:
        if any(v is None for v in (args.mind, args.body, args.spirit, args.vocation)):
            print("打卡需四象限齐全：--mind --body --spirit --vocation（0-100）", file=sys.stderr)
            sys.exit(2)
        rec = human30.record(args.mind, args.body, args.spirit, args.vocation, args.note)
        print(f"✅ 已记录 {rec['date']}：mind {rec['mind']:.0f} / body {rec['body']:.0f} / "
              f"spirit {rec['spirit']:.0f} / vocation {rec['vocation']:.0f}")
        _print_latest()
    elif args.history is not None:
        for r in human30.history(args.history):
            print(f"{r['date']}  mind {r['mind']:.0f} body {r['body']:.0f} "
                  f"spirit {r['spirit']:.0f} vocation {r['vocation']:.0f}"
                  + (f"  | {r['note']}" if r.get("note") else ""))
    else:
        _print_latest()


if __name__ == "__main__":
    main()
