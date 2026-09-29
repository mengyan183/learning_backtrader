# -*- coding: utf-8 -*-
"""数据加载、规范化与质量校验。

设计依据：§4.2 格式规则、§4.3 对齐与缺失、§4.4 拆股异常检测。
"""
import os

import pandas as pd

from fg_system import config


class DataQualityError(Exception):
    """数据质量问题。pipeline 遇到此异常必须中止（fail fast）。"""


PRICE_COLUMNS = ["date", "symbol", "open", "high", "low", "close", "volume"]


def load_prices(path=None, required_symbols=None):
    """读取长表价格数据并规范化。

    - 日期解析：优先按 MM/DD/YYYY（Nasdaq 原始格式）解析，失败再按 ISO 解析
    - 排序：按 (symbol, date) 升序
    - 去重：同 (symbol, date) 只保留最后一条
    """
    path = path or f"{config.RAW_DIR}/prices.csv"
    df = pd.read_csv(path, dtype={"symbol": str})
    missing = [c for c in PRICE_COLUMNS if c not in df.columns]
    if missing:
        raise DataQualityError("价格文件缺少列: %s" % missing)

    df["date"] = _parse_dates(df["date"])
    df = (
        df.dropna(subset=["date"])
        .drop_duplicates(subset=["symbol", "date"], keep="last")
        .sort_values(["symbol", "date"])
        .reset_index(drop=True)
    )
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    required = required_symbols if required_symbols is not None else config.SYMBOLS
    absent = [s for s in required if s not in set(df["symbol"])]
    if absent:
        raise DataQualityError("缺少标的: %s" % absent)
    return df


def check_required_symbols(df, required=None):
    """检查数据是否覆盖全部必需标的（默认 config.SYMBOLS）。

    与 load_prices 内置检查的区别：本函数可对**任意宽表/长表子集**独立调用，
    用于对真实数据文件做显式断言（§4.2 覆盖性要求）。
    """
    required = config.SYMBOLS if required is None else required
    present = set(df["symbol"]) if "symbol" in df.columns else set(
        df.columns.get_level_values(0) if hasattr(df.columns, "levels") else []
    )
    absent = [s for s in required if s not in present]
    if absent:
        raise DataQualityError("缺少标的: %s" % absent)
    return True


def _parse_dates(series):
    """按 MM/DD/YYYY 解析（Nasdaq 口径），失败回退 ISO。"""
    out = pd.to_datetime(series, format="%m/%d/%Y", errors="coerce")
    fallback = out.isna()
    if fallback.any():
        out.loc[fallback] = pd.to_datetime(series[fallback], errors="coerce")
    return out


def to_wide(df, primary_symbol="SPY", value="close"):
    """转成以主日历为索引的宽表：index=交易日，columns=(symbol, field)。

    主日历取 primary_symbol 的交易日；其他标的左连接，缺数据处为 NaN（**不前向填充**，§4.3）。
    """
    wide = df.pivot_table(index="date", columns="symbol", values=value, aggfunc="last")
    if primary_symbol in wide.columns:
        calendar = wide[primary_symbol].dropna().index
        wide = wide.reindex(calendar)
    return wide.sort_index()


def to_wide_ohlcv(df, primary_symbol="SPY"):
    """多字段宽表：columns 为 MultiIndex (symbol, field)。"""
    frames = []
    for field in ["open", "high", "low", "close", "volume"]:
        w = df.pivot_table(index="date", columns="symbol", values=field, aggfunc="last")
        w.columns = pd.MultiIndex.from_product([w.columns, [field]], names=["symbol", "field"])
        frames.append(w)
    wide = pd.concat(frames, axis=1).sort_index()
    if (primary_symbol, "close") in wide.columns:
        wide = wide.reindex(wide[(primary_symbol, "close")].dropna().index)
    return wide.sort_index()


def check_split_anomalies(df):
    """拆股/合股异常检测（§4.4）。

    主检测：|杠杆ETF单日收益 − N×标的单日收益| > SPLIT_DEVIATION_THRESHOLD
    辅助检测：|N×标的单日收益| > SPLIT_JUMP_THRESHOLD（标的缺失/异常时兜底）

    判定口径说明（§4.4 第 4 条，仅相对偏离）：
    绝对跳变**不单独作为失败依据**。设计文档 §4.4 阈值的修正记录明确写了这一点——
    SOXL 2025-04-09 真实上涨 +54.79%，若对杠杆 ETF 自身收益套用绝对阈值即误杀。
    相对偏离检测对**拆股两个方向同时生效**（拆股 −50pp、合股 −150pp 的偏离），
    绝对兜底只作用于"3×标的"一侧，即标的自身单日出现 >70% 跳变时兜底拦截。
    """
    problems = []
    for lev, und in config.UNDERLYING_MAP.items():
        n = config.LEVERAGE_RATIO[lev]
        sub = df[df["symbol"].isin([lev, und])]
        lev_s = sub[sub["symbol"] == lev].set_index("date")["close"].sort_index()
        und_s = sub[sub["symbol"] == und].set_index("date")["close"].sort_index()
        if lev_s.empty or und_s.empty:
            problems.append("%s/%s: 价格序列缺失，无法做拆股偏离检测" % (lev, und))
            continue
        lev_r = lev_s.pct_change()
        und_r = und_s.reindex(lev_r.index).pct_change(fill_method=None)

        dev = (lev_r - n * und_r).abs()
        for dt, v in dev[dev > config.SPLIT_DEVIATION_THRESHOLD].items():
            problems.append(
                "%s %s: %s 收益 %+.2f%% 与 %d×%s 收益 %+.2f%% 偏离 %.2fpp"
                % (
                    lev, dt.date(), lev, lev_r.loc[dt] * 100, n, und,
                    (und_r.loc[dt] or 0) * 100, v * 100,
                )
            )
        jump = (n * und_r).abs()
        for dt, v in jump[jump > config.SPLIT_JUMP_THRESHOLD].items():
            problems.append(
                "%s %s: %d×%s 收益 %+.2f%% 超绝对兜底阈值（标的自身异常跳变）"
                % (lev, dt.date(), n, und, v * 100)
            )

    if problems:
        raise DataQualityError(
            "异常跳变（疑似未复权或数据错误），pipeline 中止：\n  " + "\n  ".join(problems)
        )
    return True


def health_report(df):
    """数据健康检查报告（§4.4 第 8 条）。"""
    lines = []
    for sym in sorted(df["symbol"].unique()):
        s = df[df["symbol"] == sym].sort_values("date")
        r = s["close"].pct_change()
        worst = r.abs().idxmax() if r.notna().any() else None
        lines.append(
            {
                "symbol": sym,
                "rows": len(s),
                "start": s["date"].min().strftime("%Y-%m-%d"),
                "end": s["date"].max().strftime("%Y-%m-%d"),
                "max_abs_chg": float(r.loc[worst]) if worst is not None else float("nan"),
                "max_chg_date": s["date"].loc[worst].strftime("%Y-%m-%d") if worst is not None else "",
            }
        )
    return pd.DataFrame(lines)


# ================================================================ v2 加密宽表

CRYPTO_FIELDS = ["open", "high", "low", "close", "volume"]


def to_crypto_wide(raw_dir=None, primary_symbol="SPY"):
    """加密市场的宽表。

    - 主日历：**prices.csv 的 SPY 交易日**（美股日历）。加密 7×24 交易，但 ETF
      只能在美股时段成交，因此必须用美股日历做回测索引（§4.4）。
    - 价格类缺失：保持 NaN，不前向填充（§4.3）。
    - FNG 缺失：前向填充（指数类），与价格类处理不同。
    - BTC 现货缺失：**直接报错**。CF2 与趋势过滤都依赖它，静默降级会产生错误信号。

    **已知的 1 日相位差（必须理解）**：BTC 现货来自 blockchain.info，是 7×24 的
    **日均价**（非收盘价），其统计窗口跨越美股会话，因此 BTC 的日收益与美股 ETF 的
    日收益存在约 1 个交易日的相位差（实测 BITX 与 BTC 收益相关性 lag=0 仅 0.17、
    lag=+1 达 0.77）。**本函数不做相位 shift**——把 BTC 后移一天会构成前视偏差
    （§10 红线）。该相位差对本表的用途影响有限：趋势过滤用 BTC 对自身均线（相位无关），
    CF2 用滚动分位（分布不变），异常检测用 5 日累计（伪影被稀释）。
    """
    raw_dir = raw_dir or config.RAW_DIR
    crypto_path = os.path.join(raw_dir, "crypto_prices.csv")
    btc_path = os.path.join(raw_dir, "crypto_underlying.csv")
    fng_path = os.path.join(raw_dir, "crypto_fng.csv")

    if not os.path.exists(btc_path):
        raise DataQualityError(
            "缺少 BTC 现货文件 %s。CF2 价格因子与趋势过滤都依赖它，无法继续。" % btc_path)

    px = pd.read_csv(crypto_path, dtype={"symbol": str}, parse_dates=["date"])

    frames = []
    for field in CRYPTO_FIELDS:
        w = px.pivot_table(index="date", columns="symbol", values=field, aggfunc="last")
        w.columns = pd.MultiIndex.from_product([w.columns, [field]], names=["symbol", "field"])
        frames.append(w)
    wide = pd.concat(frames, axis=1).sort_index()

    btc = pd.read_csv(btc_path, parse_dates=["date"]).set_index("date")["close"].sort_index()
    wide[("BTC", "close")] = btc.reindex(wide.index)

    fng = pd.read_csv(fng_path, parse_dates=["date"]).set_index("date")["value"].sort_index()
    wide[("FNG", "value")] = fng.reindex(wide.index).ffill()

    # 主日历必须取 **prices.csv 的 SPY**，不能取 crypto_prices.csv 的 SPY——
    # 后者根本不含 SPY（update_crypto_prices 只抓加密标的与 MSTR/COIN）。
    # 且合成轨（Task 3）也用 prices.csv 的 SPY 日历，两者必须一致，
    # 否则 run_portfolio 对齐时会出现错位。
    prices_path = os.path.join(raw_dir, "prices.csv")
    if os.path.exists(prices_path):
        all_px = pd.read_csv(prices_path, dtype={"symbol": str}, parse_dates=["date"])
        spy = (all_px[all_px["symbol"] == primary_symbol]
               .set_index("date")["close"].sort_index())
        wide = wide.reindex(spy.dropna().index)
    elif (primary_symbol, "close") in wide.columns:
        wide = wide.reindex(wide[(primary_symbol, "close")].dropna().index)
    return wide.sort_index()


SHOUTU_COLUMNS = ["date", "symbol", "value"]


def load_shoutu_fng(path=None):
    """读取**守猪待兔贪恐指数**（第 12.26 条），返回宽表 index=date, columns=symbol。

    **为什么用文件而不是 API**：该服务的 token **限制单一设备使用**，
    从开发机直连可能挤掉用户手机。API 直连待确认，先用手动录入保底。

    缺文件时返回**空表**（而不是报错）：系统其余部分不依赖它，
    未接入前不应因缺文件而中断。
    """
    path = path or config.SHOUTU_FNG_PATH
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path, dtype={"symbol": str}, parse_dates=["date"])
    if df.empty:
        return pd.DataFrame()
    wide = df.pivot_table(index="date", columns="symbol", values="value",
                          aggfunc="last").sort_index()
    return wide


def _load_shoutu_long(path, required, optional):
    """读守猪待兔的 CSV **长表**；缺的 `optional` 列**补 NaN**（向后兼容旧文件）。

    与 `load_shoutu_fng` 的分工：那个返回**宽表**（只含 `value`，供 pipeline 用），
    这个返回**长表**（保留全部列，供 `append_records` 做**无损**合并）。
    """
    cols = list(required) + list(optional)
    if not os.path.exists(path):
        return pd.DataFrame(columns=cols)
    df = pd.read_csv(path, dtype={"symbol": str})
    if df.empty:
        return pd.DataFrame(columns=cols)
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise DataQualityError(
            "守猪待兔文件缺少必需列：%s（%s）" % (missing, path))
    for c in optional:
        if c not in df.columns:
            df[c] = pd.NA
        # 显式转数值：否则旧文件缺列时该列是 object/all-NA，参与 concat 会触发
        # pandas 的 "empty or all-NA entries" FutureWarning（本仓库要求输出无告警）。
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    # 必需列**不得有脏值** —— 与上面"缺列报错"同一态度。旧行的脏日期若静默变
    # NaT，会参与 sort_values / drop_duplicates ⇒ 被当成"同一天"合并掉；而调用方
    # 只校验**新**数据的 date（见 `shoutu.append_records` 的 `new[...].isna()`），
    # 抓不到**旧**行 ⇒ 静默篡改分布。
    bad = df[df["date"].isna() | df["symbol"].isna()
             | (df["symbol"].astype(str).str.strip() == "")]
    if len(bad):
        raise DataQualityError(
            "守猪待兔文件含无法解析的行（%s）：\n%s"
            % (path, bad.head(5).to_string(index=False)))
    return df[cols]


def load_shoutu_records(path=None):
    """前向录入的**长表**（`date,symbol,value,price`），供 `append_records` 无损合并。

    **为什么需要它**：`load_shoutu_fng` 返回**宽表**（只有 `value`）—— 若用它
    重读旧数据再并新行，旧行的 `price` 会被**静默丢掉**（2026-09-24 实机踩到）。
    缺 `price` 列时补 NaN ⇒ 现网 3 列文件照常可读、可续写。
    """
    path = path or config.SHOUTU_FNG_PATH
    return _load_shoutu_long(path, ["date", "symbol", "value"], ["price"])


def load_shoutu_history(path=None):
    """服务端**历史**长表（`date,symbol,score,price`）。

    ⚠️ 与 `load_shoutu_fng` 的**口径不同**：这里是**服务端权威日值**，
    那边是**本地 06:30 采样**。**不要混用**（spec §5.4）。
    """
    path = path or config.SHOUTU_HISTORY_PATH
    return _load_shoutu_long(path, ["date", "symbol", "score"], ["price"])


def shoutu_to_system_scale(series):
    """守猪待兔量程（−100 ~ 100）→ 系统口径（0 ~ 100）：`(x + 100) / 2`。

    **这个映射是"对的"，不是凑的**：用户定义的贪婪线 **60 → 80**、
    恐惧线 **−60 → 20**，与系统既有的 `ZONE_EDGES = [20, 40, 60, 80]`
    **边界精确重合** —— 两套口径本来就同构，无需额外调参。

    越界值**直接报错**而不是截断：越界说明数据源或口径变了，
    静默截断会把"口径错误"伪装成"极值信号"（同 §4.3 对缺失值的原则）。
    """
    lo, hi = config.SHOUTU_FNG_MIN, config.SHOUTU_FNG_MAX
    bad = series.dropna()
    if len(bad) and ((bad < lo).any() or (bad > hi).any()):
        raise DataQualityError(
            "守猪待兔指数越界：量程应为 [%g, %g]，实际 min=%g max=%g。"
            "请确认数据源口径是否变化，不要静默截断。"
            % (lo, hi, bad.min(), bad.max()))
    return (series + 100.0) / 2.0


def _cum_return(series, window):
    """window 日累计收益：series[t] / series[t-window] - 1。"""
    return series / series.shift(window) - 1.0


def check_crypto_anomalies(df, threshold=None, jump_threshold=None, window=None):
    """加密标的的拆股/合股异常检测（§4.3）。

    与 v1 `check_split_anomalies` 的三处差异（必须理解，否则会误改）：

    1. **用 window 日累计收益而非单日收益**。BTC 现货来自 blockchain.info，是
       7×24 的**日均价**（API 原文 "Average USD market price across major bitcoin
       exchanges"），其统计窗口跨越美股会话，与 ETF 单日收益存在约 1 个交易日的
       相位差（实测：BITX 与 BTC 收益相关性 lag=0 仅 0.17、lag=+1 达 0.77）。
       用单日收益比对会产生 47pp 的**假偏离**（是真实市场日，非数据错误）。
       改用 5 日累计后相位伪影被稀释约 5 倍，而拆股仍表现为 50pp/150pp 跳变。

    2. **不做相位 shift**。虽然把 BTC 后移一天能显著提升相关性，但那意味着用
       「明天」的 BTC 数据配「今天」的 ETF —— 这是**前视偏差红线**（§10）。
       宁可接受 1 日陈旧，也不引入未来信息。

    3. **缺数据必须报错，不能静默跳过**。v1 的 `check_split_anomalies` 在缺数据时
       `raise`；本函数初稿写成 `continue`，导致 `crypto_prices.csv` 不含 BTC 时
       BITX/BITU 这两个最大层**从未被检测却输出「通过」**。
    """
    threshold = (config.CRYPTO_SPLIT_DEVIATION_THRESHOLD
                 if threshold is None else threshold)
    jump_threshold = (config.CRYPTO_SPLIT_JUMP_THRESHOLD
                      if jump_threshold is None else jump_threshold)
    window = config.CRYPTO_ANOMALY_WINDOW if window is None else window

    problems = []
    for lev, und in config.CRYPTO_UNDERLYING.items():
        n = config.CRYPTO_LEVERAGE[lev]
        lev_s = df[df["symbol"] == lev].set_index("date")["close"].sort_index()
        und_s = df[df["symbol"] == und].set_index("date")["close"].sort_index()
        if lev_s.empty or und_s.empty:
            raise DataQualityError(
                "%s/%s: 价格序列缺失（%s=%d 行, %s=%d 行），无法做拆股偏离检测。"
                "注意 BTC 在 crypto_underlying.csv 而非 crypto_prices.csv，"
                "调用前必须把两者合并成同一张长表。"
                % (lev, und, lev, len(lev_s), und, len(und_s)))

        lev_r = _cum_return(lev_s, window)
        und_on_lev = und_s.reindex(lev_s.index).ffill()
        und_r = _cum_return(und_on_lev, window)

        dev = (lev_r - n * und_r).abs()
        for dt, v in dev[dev > threshold].items():
            problems.append(
                "%s %s: %d 日累计 %s %+.2f%% 与 %d×%s %+.2f%% 偏离 %.2fpp"
                % (lev, dt.date(), window, lev, lev_r.loc[dt] * 100, n, und,
                   und_r.loc[dt] * 100, v * 100))
        jump = (n * und_r).abs()
        for dt, v in jump[jump > jump_threshold].items():
            problems.append(
                "%s %s: %d×%s 的 %d 日累计 %+.2f%% 超绝对兜底阈值"
                % (lev, dt.date(), n, und, window, v * 100))

    if problems:
        raise DataQualityError(
            "加密标的异常跳变（疑似未复权或数据错误），pipeline 中止：\n  "
            + "\n  ".join(problems))
    return True
