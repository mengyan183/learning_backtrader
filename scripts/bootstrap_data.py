# -*- coding: utf-8 -*-
"""在**家里 Mac** 上重建 `Data/raw/` —— 让飞书只需传几十 KB。

【为什么需要这个脚本】
公司电脑 → 家里的传输**只走飞书**，而飞书实测**拦截 100 KB 以上的文件**
（5.7 KB 能过、100 KB 不过）。而 `Data/raw/` 压缩后仍有 **1.5 MB**，
要切成 **19 片**才传得过去 —— 太麻烦。

**但 Mac 有公网，公司电脑没有**（公司走内网 Nexus + 代理）。
而 `Data/raw/` 里**绝大部分是公开数据**，Mac 自己就能抓回来：

    prices.csv             Nasdaq 官方 API        ← 2.5 MB，可重抓
    vix.csv / vix3m.csv    CBOE cdn               ← 471 KB，可重抓
    crypto_prices.csv      Nasdaq 官方 API        ← 379 KB，可重抓
    crypto_underlying.csv  blockchain.info        ← 73 KB，可重抓
    crypto_fng.csv         alternative.me         ← 78 KB，可重抓
    putcall_*.csv          CBOE（2019 已停更）     ← **生产代码零引用**，不用管

⇒ 真正**不可再生**的只剩几十 KB（用 `--irreplaceable` 列出来）。
  连同代码一起，飞书 **3 个文件**就传完了。

【⚠️ 不可再生的东西 —— 必须从公司电脑手动拷】
    最要紧的是 `Data/raw/shoutu_history.csv`（2026-09-24 新增）：
    **服务端权威日值**，6 个标的共 3587 个交易日。虽可由
    `scripts/fetch_shoutu_history.py` 重抓，但**依赖会员有效期**（至 2027-01-16）
    —— 过期就抓不回来，故按**不可再生**对待。
    其次是 `Data/raw/shoutu_fng.csv`：**本地 06:30 采样**，逐日累积 ——
    API 只能查"现在"、**查不了历史**，丢了就**永远补不回来**。

【⚠️ 必须先设代理为空】
`config.PROXY` 默认是**公司代理**，Mac 上访问不到它，所有请求都会超时：

    export FG_PROXY=""

用法（Mac 上）：
    export FG_PROXY=""
    .venv/bin/python scripts/bootstrap_data.py --irreplaceable   # 先看必须手动拷什么
    .venv/bin/python scripts/bootstrap_data.py --dry-run         # 看要抓什么
    .venv/bin/python scripts/bootstrap_data.py                   # 真抓（约 2~5 分钟）
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fg_system import config                     # noqa: E402
from fg_system.data import fetch                 # noqa: E402

# 公司电脑上**必须手动拷**过来的东西（Mac 造不出来）
IRREPLACEABLE = [
    ("Data/raw/shoutu_history.csv",
     "守猪待兔**服务端权威日值**（6 标的 3587 行，2026-09-24 新增）"),
    ("Data/raw/shoutu_fng.csv", "守猪待兔每日贪恐值，**逐日累积、不可再生**"),
    ("Data/raw/splits.csv", "手工维护的拆股表"),
    ("Data/state.json", "仓位与冷却状态"),
    ("Data/crypto_state.json", "加密仓位状态"),
    ("Data/accounts.csv", "手工录入的实盘净值"),
    ("Data/positions.csv", "手工录入的持仓明细"),
    ("Data/trade_log.csv", "交易记录"),
    ("Data/shoutu_token", "凭据（被 .gitignore，git 带不过来）"),
    ("Data/tstoken", "凭据（同上）"),
]

# Mac 自己抓得到的（公开数据源）
FETCHABLE = [
    ("prices.csv", "Nasdaq 官方 API", "update_prices()"),
    ("vix.csv / vix3m.csv", "CBOE cdn", "update_indices()"),
    ("crypto_prices.csv", "Nasdaq 官方 API", "update_crypto_prices()"),
    ("crypto_underlying.csv", "blockchain.info（BTC 现货）", "update_crypto_aux()"),
    ("crypto_fng.csv", "alternative.me", "update_crypto_aux()"),
    ("putcall_*.csv", "CBOE（2019 停更）—— **生产零引用，不必抓**", "—"),
]


def _human(n):
    return ("%.1f KB" % (n / 1024)) if n < 1048576 else ("%.1f MB" % (n / 1048576))


# 飞书**单文件**上限的判据值（**实测经验值**，不是官方文档值）：
# 实测「非压缩包：10 KB 过、90 KB 不过」，且「100 KB 以上被拦」。取 **90 KB** 作判据。
FEISHU_SINGLE_FILE_LIMIT = 90 * 1024


def _transfer_verdict(total):
    """给「不可再生文件合计大小」配一句**不会过期**的结论。

    ⚠️ **为什么必须实算**（2026-09-28 修正）：原实现把结论**写死**为
    「**远低于**飞书的 100 KB 上限，一个文件就能传」。而 `shoutu_history.csv`
    已长到 **98.5 KB** ⇒ 合计 **102.4 KB**、**已超限** ⇒ 照那句话做会**直接被飞书拦**，
    而且是发的时候才发现。⇒ 结论必须由 `total` 算出。
    """
    if total <= FEISHU_SINGLE_FILE_LIMIT:
        return "**低于飞书单文件上限（%s），可以直接发**。" % _human(FEISHU_SINGLE_FILE_LIMIT)
    return ("**超过飞书单文件上限（%s）⇒ 必须走 `keep` 包分片**：\n"
            "        py -3.10 scripts/make_feishu_bundle.py --minimal --strip --with-tests --text\n"
            "        py -3.10 scripts/feishu_send.py"
            % _human(FEISHU_SINGLE_FILE_LIMIT))


def show_irreplaceable():
    print("以下文件由**公司电脑**手工维护（Mac 无法自动生成）：")
    print()
    total = 0
    missing = []
    for rel, why in IRREPLACEABLE:
        p = os.path.join(config.ROOT, rel)
        if os.path.isfile(p):
            size = os.path.getsize(p)
            total += size
            mark = _human(size)
            status = "✓"
        else:
            mark = "（本机没有）"
            status = "✗"
            missing.append(rel)
        print("    %s  %-28s %9s   %s" % (status, rel, mark, why))
    print()
    if missing:
        print("    ⚠️ **%d 项本机缺失**，需从公司电脑补拷：%s" % (len(missing), "、".join(missing)))
        print("      已就位合计约 %s —— %s" % (_human(total), _transfer_verdict(total)))
    else:
        print("    ✅ 全部 %d 项已在本机就位，无需传输。" % len(IRREPLACEABLE))
    print()
    print("    ⚠️ 其中 `Data/raw/shoutu_fng.csv` 最要紧：它是**逐日累积**的，")
    print("       API 查不了历史，丢了永远补不回来。建议另存一份备份。")


def show_fetchable():
    print("Mac 自己抓得到的（公开数据源，无需传输）：")
    print()
    for name, src, fn in FETCHABLE:
        print("    %-24s %-34s %s" % (name, src, fn))
    print()
    print("    ⇒ `Data/raw/` 压缩后 1.5 MB（要切 19 片）**可以完全不用传**。")


def check_proxy():
    """默认的公司代理在 Mac 上不通 —— 这是最容易卡住的一步。"""
    if not config.PROXY:
        print("代理：**已关闭**（FG_PROXY 为空）—— 直连，正确。")
        return True
    if "10.30.6.49" in config.PROXY or "10.1.82.22" in config.PROXY:
        print("⚠️ 代理仍是**公司地址**：%s" % config.PROXY)
        print("   家里 Mac 访问不到它，所有抓取都会超时。请先：")
        print("       export FG_PROXY=\"\"")
        return False
    print("代理：%s" % config.PROXY)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--irreplaceable", action="store_true",
                    help="只列「必须手动拷」的清单")
    ap.add_argument("--dry-run", action="store_true",
                    help="只说明要抓什么，不实际抓")
    args = ap.parse_args()

    if args.irreplaceable:
        show_irreplaceable()
        return 0

    show_fetchable()
    print()
    if not check_proxy():
        return 2
    if args.dry_run:
        print()
        print("（--dry-run：未实际抓取）")
        return 0

    print()
    print("开始抓取（约 2~5 分钟；数据源有请求前节流，属正常等待）……")
    print()
    try:
        _, added = fetch.update_prices()
        print("  prices.csv           %d 个标的，新增 %d 行"
              % (len(added), sum(added.values())))

        idx = fetch.update_indices()
        print("  vix / vix3m          %s" % idx)

        _, cadded = fetch.update_crypto_prices()
        print("  crypto_prices.csv    %d 个标的，新增 %d 行"
              % (len(cadded), sum(cadded.values())))

        aux = fetch.update_crypto_aux()
        print("  crypto_underlying    %d 行（BTC 现货）" % aux["btc_rows"])
        print("  crypto_fng           %d 行" % aux["fng_rows"])
    except Exception as exc:
        print()
        print("[X] 抓取失败：%s: %s" % (type(exc).__name__, exc))
        print("    先确认 `FG_PROXY` 为空、Mac 能上外网。")
        return 1

    print()
    print("[OK] 数据已重建。接着跑一次自检：")
    print("     .venv/bin/python -m pytest -q")
    print()
    show_irreplaceable()
    return 0


if __name__ == "__main__":
    sys.exit(main())
