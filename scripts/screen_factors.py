# -*- coding: utf-8 -*-
"""候选新市场因子筛选（第 13.4 条 **否证性取证**）。

================================================================================
本次任务**不是**参数搜索，**不授权**新建市场
================================================================================
1. 检验的是**先验**：「情绪因子越贪婪 → 未来 N 日收益越低」是否成立。
2. **负面结果 = 永久关闭该问题**（无需改规则，不触发第 8 条流程）。
3. **正面结果也不授权新建市场**——按第 13.4 条第 1 款，启动规则修改必须来自
   **真实操作的复盘**，不能来自回测观察。本次结论只能进「待观察」清单。
4. 含**正对照**（在已上线的 `us_equity` 上跑同一工具）：若工具无法在已知
   可用的市场上检出方向，则它对新市场的任何结论都不可信。

用法：`python scripts/screen_factors.py`
"""
import os

import numpy as np
import pandas as pd

from fg_system import config
from fg_system.data import loader
from fg_system.factors import screening
from fg_system.factors.base import rolling_pct
from fg_system.factors.price import drawdown_52w, rsi

HORIZONS = [20, 60, 120]
W = config.RANK_WINDOW
# 子区间稳健性检验。**必须做**：单一全样本结论可能只由一段行情驱动。
# 切点与生产口径一致（IS/OOS 分界 2022-12-31），但不用于调参，仅用于看符号稳定性。
SPLITS = [("样本内", "2019-10-01", "2022-12-31"),
          ("样本外", "2023-01-01", "2026-12-31")]


# ---------------------------------------------------------------- 候选因子构造
# 全部只用 ≤ T 的数据（rolling 运算），无前视。

def price_composite(s, w=W):
    """价格因子（与生产 F3 同结构）：动量 20/60 + RSI14 + 距 52 周高点 + 波动率反转。"""
    mom = (rolling_pct(s.pct_change(20), w) + rolling_pct(s.pct_change(60), w)) / 2.0
    strength = rolling_pct(rsi(s), w)
    dd = 1.0 - rolling_pct(drawdown_52w(s), w)
    vol = s.pct_change().rolling(20).std() * np.sqrt(252)
    calm = 1.0 - rolling_pct(vol, w)
    return (mom + strength + dd + calm) / 4.0


def rel_strength(a, b, w=W, days=60):
    """相对强弱：`a/b` 比价 **60 日变动**的滚动分位。**相对强 = 贪婪**。

    ⚠️ **不能**对「比价的**水平**」取滚动分位——比价是单调趋势序列，
    `rolling_pct` 会退化为恒 0/1（`base.py` 已记录该数学必然），
    使因子塌缩到单一分组。首轮实测正是这样：`fxi_rel_spy` 的 `spread` 为 NaN。
    改用「变动」后取值连续，不会退化。
    """
    return rolling_pct((a / b).pct_change(days), w)


def vol_reversal(s, w=W):
    """波动率反转：波动高 = 恐惧（低分）。"""
    vol = s.pct_change().rolling(20).std() * np.sqrt(252)
    return 1.0 - rolling_pct(vol, w)


def mom_only(s, w=W, days=60):
    return rolling_pct(s.pct_change(days), w)


# 量价类因子需要 volume。为不改动全部 lambda 签名，用模块级 VOL（**仅研究脚本**，
# 不进生产：`factors/screening.py` 已有红线守卫禁止被生产模块导入）。
VOL = {}


def vol_ratio(sym, w=W, short=20, long=60):
    """量能因子：短期均量 / 长期均量的滚动分位。**放量 = 情绪高（贪婪）**。"""
    v = VOL[sym]
    return rolling_pct(v.rolling(short).mean() / v.rolling(long).mean(), w)


def ma_deviation(s, w=W, days=60):
    """距 N 日均线偏离的滚动分位（正偏离 = 贪婪）。"""
    return rolling_pct(s / s.rolling(days).mean() - 1.0, w)


def rsi_factor(s, w=W):
    """RSI(14) 的滚动分位（单用，不与动量混在一起）。"""
    return rolling_pct(rsi(s), w)


def dd_only(s, w=W):
    """距 52 周高点回撤（**反转**：回撤深 = 恐惧）。"""
    return 1.0 - rolling_pct(drawdown_52w(s), w)


def downside_share(s, w=W, days=20):
    """下行波动占比的滚动分位（**反转**）：下行占比高 = 恐惧。

    与 `vol_reversal` 的区别：它只看**总波动**，本项区分**方向**。
    两者相关但不相同，可用于判断是否构成**独立**的第二因子。
    """
    r = s.pct_change()
    dn = r.clip(upper=0).rolling(days).std()
    up = r.clip(lower=0).rolling(days).std()
    return 1.0 - rolling_pct(dn / (dn + up), w)


MARKETS = {
    "us_equity(正对照)": {
        "underlying": "QQQ", "tradable": "TQQQ",
        "factors": {
            "qqq_price": lambda c: price_composite(c["QQQ"]),
            "qqq_mom60": lambda c: mom_only(c["QQQ"]),
        },
    },
    "gold_miners": {
        "underlying": "GDX", "tradable": "GDXU",
        "factors": {
            "gdx_price": lambda c: price_composite(c["GDX"]),
            "gdx_mom60": lambda c: mom_only(c["GDX"]),
            "gld_price": lambda c: price_composite(c["GLD"]),
            "gdx_rel_gld": lambda c: rel_strength(c["GDX"], c["GLD"]),
            "gdx_vol": lambda c: vol_reversal(c["GDX"]),
            "slv_price": lambda c: price_composite(c["SLV"]),
        },
    },
    "china_equity": {
        "underlying": "FXI", "tradable": "YINN",
        "factors": {
            "fxi_price": lambda c: price_composite(c["FXI"]),
            "fxi_mom60": lambda c: mom_only(c["FXI"]),
            "fxi_rel_spy": lambda c: rel_strength(c["FXI"], c["SPY"]),
            "fxi_vol": lambda c: vol_reversal(c["FXI"]),
            "kweb_price": lambda c: price_composite(c["KWEB"]),
            "mchi_price": lambda c: price_composite(c["MCHI"]),
            "ashr_price": lambda c: price_composite(c["ASHR"]),
        },
    },
    # 第 12.20 条：用户选择「对齐系统到实盘」，故补测实际持仓 AXTX / CRCG。
    "axtx(AXTI)": {
        "underlying": "AXTI", "tradable": "AXTX",
        "factors": {
            # 已通过（第 12.20 条）
            "axti_vol": lambda c: vol_reversal(c["AXTI"]),
            # 第 5.4 条要求 >=2 个有效因子，以下为候选第二因子
            "axti_dnvol": lambda c: downside_share(c["AXTI"]),
            "axti_volratio": lambda c: vol_ratio("AXTI"),
            "axti_rsi": lambda c: rsi_factor(c["AXTI"]),
            "axti_dd52w": lambda c: dd_only(c["AXTI"]),
            "axti_madev60": lambda c: ma_deviation(c["AXTI"]),
            "axti_rel_soxx": lambda c: rel_strength(c["AXTI"], c["SOXX"]),
            "soxx_price": lambda c: price_composite(c["SOXX"]),
            "soxx_vol": lambda c: vol_reversal(c["SOXX"]),
        },
    },
    "crcg(CRCL)": {
        "underlying": "CRCL", "tradable": "CRCG",
        "factors": {
            "crcl_price": lambda c: price_composite(c["CRCL"]),
            "crcl_mom60": lambda c: mom_only(c["CRCL"]),
            "crcl_vol": lambda c: vol_reversal(c["CRCL"]),
        },
    },
}


def main():
    prices = loader.load_prices(os.path.join(config.RAW_DIR, "prices.csv"))
    wide = loader.to_wide_ohlcv(prices)
    close = pd.DataFrame({s: wide[(s, "close")] for s in wide.columns.levels[0]})
    VOL.update({s: wide[(s, "volume")] for s in wide.columns.levels[0]})

    print("=" * 100)
    print("因子筛选（第 13.4 条**否证性取证**）")
    print("先验：因子高（贪婪）→ 未来 N 日收益**低**  ⇒  期望 IC < 0、spread > 0、hit > 0.5")
    print("数据：%s ~ %s，%d 个交易日；滚动分位窗口 %d 日"
          % (wide.index.min().date(), wide.index.max().date(), len(wide), W))
    print("=" * 100)

    for mkt, spec in MARKETS.items():
        und, trad = spec["underlying"], spec["tradable"]
        print()
        print("-" * 100)
        print("市场 %s   无杠杆底层 %s   候选可交易标的 %s" % (mkt, und, trad))
        print("-" * 100)
        print("%-14s %5s %9s %7s %10s %7s %6s"
              % ("因子", "horiz", "IC", "单调", "spread", "hit", "n"))
        print()
        print("  【子区间 IC 稳健性】符号是否稳定？只在两段**同号**才算通过。")
        print("  %-14s %5s %10s %10s %10s"
              % ("因子", "horiz", "全样本", SPLITS[0][0], SPLITS[1][0]))
        for fname, fn in spec["factors"].items():
            f = fn(close)
            for h in HORIZONS:
                fwd = screening.forward_return(close[und], h)
                ics = [screening.spearman_ic(f, fwd)]
                for _, a, b in SPLITS:
                    m = (f.index >= a) & (f.index <= b)
                    ics.append(screening.spearman_ic(f[m], fwd[m]))
                stable = (not any(pd.isna(x) for x in ics)) and \
                         all(x < 0 for x in ics)
                print("  %-14s %5d %10.3f %10.3f %10.3f%s"
                      % (fname, h, ics[0], ics[1], ics[2],
                         "  ← 三段全为负(方向稳定)" if stable else ""))
        print()

        best = []
        for fname, fn in spec["factors"].items():
            f = fn(close)
            for h in HORIZONS:
                fwd = screening.forward_return(close[und], h)
                out = screening.screen(f, fwd)
                flag = ""
                if out["degenerate"]:
                    flag = "  ← 退化(组为空)，结论不可信"
                elif (out["ic"] < 0) and (out["spread"] > 0) and (out["hit"] > 0.5):
                    flag = "  ← 方向符合先验"
                print("%-14s %5d %9.3f %7.2f %9.2f%% %7.3f %6d%s"
                      % (fname, h, out["ic"], out["mono"],
                         out["spread"] * 100, out["hit"], out["n"], flag))
                best.append((out["ic"], fname, h, out))
        print()
        print("  【%s 的分组明细】按 IC 最负（方向最符合先验）的一个组合：" % mkt)
        ic, fname, h, out = min(best)
        print("    因子 %s / horizon %d 日" % (fname, h))
        print("    " + out["table"].to_string().replace("\n", "\n    "))


if __name__ == "__main__":
    main()
