# -*- coding: utf-8 -*-
"""守猪待兔每日抓取（**partner API 通道**）—— 替代 bsk 浏览器会话。

【为什么换掉 bsk】
第 14.5 条记录的 E1 走「已激活的浏览器会话」，因为当时**接口契约未知**。
2026-09-23 用户提供官方开发文档（`docs/查询实时贪恐.docx`），契约已确认，
八个标的的 `lever` / `emo_area` 也全部**实测**确定 ⇒ 可以直接走 API。收益：

  1 **不再需要浏览器** —— 去掉 `bsk` 与 Chrome 扩展依赖，消除 macOS 上
     「唤醒后 Chrome 未运行」这一失败模式（第 14.5 条）
  2 **补上 AXTX / CRCG** —— 这两个**不在**页面「贪恐」表格的 11 个分类内，
     原通道**拿不到**，一直是**手工补录**；API 是逐标的查询，能拿到
  3 **更实时** —— 实测页面表格对部分标的（GDXU）存在刷新滞后
  4 更快：8 次请求 vs 遍历 11 个分类（约 38 秒）

【额度】`query` 30 个标的 / 30 天（**去重**计数，八个标的已全部注册 ⇒ 日常为 0）；
`query_api` 5000 次 / 自然月（日常约 176 次）。

【用法】
    python scripts/fetch_shoutu_api.py
    python scripts/fetch_shoutu_api.py --dry-run     # 只打印，不落盘
    python scripts/fetch_shoutu_api.py --date 2026-09-23

【⚠️ 不要手动跑（除非验证安装）】该指数**实时更新**，而 `append_records` 对同一
`(date, symbol)` 是**覆盖**语义 ⇒ 任何非 06:30 的手动运行都会把当天记录
覆盖成该时刻的快照。详见 `docs/trading-discipline.md` 第 14.5 条。

【不含全市场快照】API 是逐标的查询，**无法**产出 `shoutu_etf_universe.csv`
（379 行全市场表）。该快照仍由 `scripts/fetch_shoutu.py`（bsk）按需生成 ——
它是研究用途（"某标的是否被覆盖"），**不是每日信号所需**。
"""
import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fg_system import config                     # noqa: E402
from fg_system.data import shoutu                # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="只打印取值，不写入文件")
    ap.add_argument("--date", default=None,
                    help="记录日期（默认今天）。⚠️ 非 06:30 会覆盖当天快照")
    args = ap.parse_args()

    day = (pd.Timestamp.today().normalize() if args.date is None
           else pd.Timestamp(args.date))

    recs = shoutu.collect_score_records()
    vals = {s: r["score"] for s, r in recs.items()}
    prices = {s: r["price"] for s, r in recs.items()}     # 参考量，供价格 × 情绪对照
    print("取得 %d 个标的：" % len(vals))
    for sym in config.SHOUTU_SYMBOLS:
        lever, area = config.SHOUTU_API_PARAMS[sym]
        print("  %-5s lever=%s emo_area=%-6s score=%-6s price=%s"
              % (sym, lever, area, vals[sym], prices[sym]))

    if args.dry_run:
        print("（--dry-run：未写入）")
        return 0

    wide, added = shoutu.append_records(
        shoutu.mapping_to_frame(vals, date=day, prices=prices))
    print("逐标的时序已写入：%s（本次 %d 行，累计 %d 行）"
          % (os.path.join(config.RAW_DIR, "shoutu_fng.csv"), added, len(wide)))
    print("覆盖天数：" + " / ".join(
        "%s %d" % (k, v) for k, v in sorted(shoutu.recorded_symbols().items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
