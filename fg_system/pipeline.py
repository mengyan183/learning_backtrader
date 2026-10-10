# -*- coding: utf-8 -*-
"""全链路编排：loader → factors → index → signal → features.csv（§3.3）。

前视偏差红线（§10）：
  1. 因子只用 ≤ T 日数据
  2. target_position 写入前整体 shift(1)，确保 T 日开盘执行 T-1 收盘信号
  3. 状态化规则按时间顺序逐日推进，禁止全样本统计量
  4. 校验：输入整体后移一天 → 输出也应整体后移一天（见 tests/test_pipeline.py）
"""
import json
import os

import numpy as np
import pandas as pd

from fg_system import config
from fg_system import index as index_mod
from fg_system import signal as signal_mod
from fg_system.data import loader, splits
from fg_system.factors.base import rolling_pct
from fg_system.factors.fed import FedPolicyFactor
from fg_system.signal import market_signal as ms_mod
from fg_system.signal import portfolio as pf_mod

ZONE_NAMES = ["极度恐惧", "恐惧", "中性", "贪婪", "极度贪婪"]


def load_wide(raw_dir=None, shift_inputs=0):
    """读取并组装宽表。

    shift_inputs 仅用于前视偏差校验测试：把全部输入列整体后移 N 天。
    """
    raw_dir = raw_dir or config.RAW_DIR
    prices = loader.load_prices(os.path.join(raw_dir, "prices.csv"))
    loader.check_split_anomalies(prices)
    splits.check_continuity(os.path.join(raw_dir, "prices.csv"),
                            splits.load(os.path.join(raw_dir, "splits.csv")))

    wide = loader.to_wide_ohlcv(prices)

    vix = pd.read_csv(os.path.join(raw_dir, "vix.csv"), parse_dates=["date"]).set_index("date")
    vix3m = pd.read_csv(os.path.join(raw_dir, "vix3m.csv"), parse_dates=["date"]).set_index("date")
    wide[("VIX", "close")] = vix["close"].reindex(wide.index)
    wide[("VIX3M", "close")] = vix3m["close"].reindex(wide.index)
    # F-011 Put-Call（B-6 链路，CBOE 总 P/C 比）：与 vix 同路径入宽表，
    # 随 shift 整体后移 ⇒ 平移测试（前视偏差校验）对 putcall 因子同样成立。
    putcall = pd.read_csv(os.path.join(raw_dir, "putcall.csv"),
                          parse_dates=["date"]).set_index("date")
    wide[("PUT_CALL", "ratio")] = putcall["total_ratio"].reindex(wide.index)
    wide = wide.sort_index()

    if shift_inputs:
        # fed 因子是「日历驱动的离散状态」（政策按生效日取值），不读 wide 列值 ——
        # 若放任它按原日期重算，平移测试中它不会随输入后移，政策切换日那天
        # 的合成指数会混用「后移的 vix/term/price/breadth」+「未后移的 fed」，
        # 触发前视偏差校验的假阳性（tests/test_pipeline.py 实测 2026-01-02 /
        # 2026-09-16 两天 diff）。把 fed 分数先算成列、再整体平移，
        # 即保证「输入整体后移一天 → 输出整体后移一天」的不变量。
        wide[("FED", "score")] = FedPolicyFactor().score(wide)
        wide = wide.shift(shift_inputs)
    return wide


def drawdown_series(wide):
    """标的指数的等权组合回撤（§7.3 约束 2：必须用标的指数，非杠杆 ETF）。"""
    cols = [wide[(config.UNDERLYING_MAP[s], "close")] for s in config.SYMBOLS]
    basket = pd.concat(cols, axis=1).mean(axis=1)
    peak = basket.rolling(config.DRAWDOWN_LOOKBACK,
                          min_periods=config.DRAWDOWN_LOOKBACK).max()
    return 1.0 - basket / peak


def run(raw_dir=None, write=True, shift_inputs=0):
    """执行全链路，返回 features DataFrame（index = 日期）。"""
    wide = load_wide(raw_dir, shift_inputs=shift_inputs)

    scores = index_mod.factor_scores(wide)
    fg_index = index_mod.smooth(index_mod.combine(scores))
    dd = drawdown_series(wide)

    rows = []
    state = signal_mod.SignalState()
    for dt in wide.index:
        date_str = dt.strftime("%Y-%m-%d")
        idx_val = fg_index.get(dt, np.nan)
        dd_val = dd.get(dt, np.nan)
        prices = {s: wide[(s, "close")].get(dt, np.nan) for s in config.SYMBOLS}

        # 顺序严格按 §8.3 优先级：极恐加仓（改弹药状态）→ 弹药释放 → 极贪熔断
        state, _, fear_reason = signal_mod.apply_extreme_fear(state, idx_val, date_str)
        core = signal_mod.core_position(idx_val)
        state, ammo, newly = signal_mod.update_ammo(state, dd_val)
        # warmup 期（指数无效）target 保持 None → 写盘为 NaN，回测自然跳过。
        # 不能写成 0.0——那会被回测当成"策略主动空仓"，污染净值对比与逐年表现。
        target = None if core is None else core + ammo
        extreme = bool(newly) or bool(fear_reason)
        state, target, cb_reason = signal_mod.apply_extremes(
            state, idx_val, date_str, prices, target)

        rows.append({
            "date": dt,
            "fg_index": idx_val,
            "zone": (signal_mod.zone_of(idx_val)
                     if not (idx_val is None or (isinstance(idx_val, float) and np.isnan(idx_val)))
                     else np.nan),
            "core_position": core,
            "ammo_position": ammo,
            "target_position": target,
            "drawdown": dd_val,
            "circuit_breaker": state.circuit_breaker,
            "extreme": extreme,
            "note": cb_reason or fear_reason,
            **{k: scores[k].get(dt, np.nan) for k in scores.columns},
        })

    out = pd.DataFrame(rows).set_index("date").sort_index()

    # §10.3：喂给 backtrader 前整体 shift(1)——T 日开盘执行 T-1 收盘信号
    out["target_position"] = out["target_position"].shift(1)
    out["warmup"] = out["fg_index"].isna()

    if write:
        os.makedirs(os.path.dirname(config.FEATURES_PATH), exist_ok=True)
        out.to_csv(config.FEATURES_PATH, encoding="utf-8")
        with open(config.STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state.to_dict(), f, ensure_ascii=False, indent=2)
    return out


def _load_state():
    try:
        with open(config.STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def executable_snapshot(out, target_col="target_position"):
    """返回 `(信号日, 执行日, 信号行, 目标值)`；无有效目标返回 None。

    ============================================================================
    为什么必须有它（真实缺陷，第 12.18 条）
    ============================================================================
    管道只对 `target_position` 做 **shift(1)**（T 日执行 T-1 收盘信号，§10.3），
    **`core_position` / `ammo_position` 没有 shift**。于是「最后一行」里
    **分项是今日的、目标是昨日的**——两者之和必然对不上。

    实测（2026-09-21）：分项 `us_core 18.00 + crypto_core 2.25 + ammo 20.00`
    = **40.25%**，而打印的目标是 **33.50%**，差 **6.75pp** ——
    **足以让人按错误的数字下单**。

    两层错位，都必须修（只修一层仍会差一天）：
    1. 分项取自**执行日的前一行**（那一行才是产生该目标的信号日）。
    2. 目标值必须取自**执行日那一行**——因为整列 `target_position` 都被 shift 了，
       信号行自己的 `target_position` 是**更前一天**的。
    修好后 `信号行.core + 信号行.ammo == 目标值` 恒成立（实测 0.335 == 0.3350）。
    """
    valid = out.dropna(subset=[target_col])
    if valid.empty:
        return None
    exec_date = valid.index[-1]
    pos = out.index.get_loc(exec_date)
    if pos == 0:
        return None
    sig_date = out.index[pos - 1]
    return (sig_date, exec_date, out.loc[sig_date],
            float(out.loc[exec_date, target_col]))


def pending_signal(out):
    """最新**待执行**信号：`(信号日, 信号行, 目标值)`；无有效信号返回 None。

    与 `executable_snapshot` 的分工：

    - `executable_snapshot` 走**回测口径**（`target_position` 已 shift(1)），
      回答「**最近一个交易日开盘**该持有什么」。
    - `pending_signal` 走**实盘口径**：`shift(1)` 的注释明确写着「**喂给
      backtrader 前**整体 shift(1)」（§10.3），即 shift 是**为回测**准备的。
      实盘在 T 日收盘后运行 `status`，要执行的是 **T+1 开盘**的目标
      = `core[T] + ammo[T]`（**未 shift** 的值）。

    **为什么必须区分**：`status` 只报回测口径时，报的是**已经过去**的那个交易日
    的目标——今天（09-22）看 `status` 却只看到 09-21 的目标，会漏掉当天该做的调仓。
    """
    valid = out.dropna(subset=["core_position"])
    if valid.empty:
        return None
    sig_date = valid.index[-1]
    row = out.loc[sig_date]
    target = (row["core_position"] or 0) + (row["ammo_position"] or 0)
    return sig_date, row, float(target)


def instruction_card(out, current_position=None, state=None):
    """生成每日指令卡（§13.1）。"""
    snap = executable_snapshot(out)
    if snap is None:
        return "无有效指数（warmup 未完成）"
    sig_date, exec_date, row, target = snap
    if pd.isna(row.get("fg_index")):
        return "无有效指数（warmup 未完成）"

    fg = row["fg_index"]
    zone = int(row["zone"]) if not pd.isna(row["zone"]) else 2

    lines = [
        "信号日：%s（收盘）   执行日：%s（开盘）"
        % (sig_date.strftime("%Y-%m-%d"), exec_date.strftime("%Y-%m-%d")),
        "fg_index：%.1f（%s）" % (fg, ZONE_NAMES[zone]),
        "核心仓：%.1f%%   弹药仓：%.1f%%   目标总仓位：%.1f%%" % (
            (row["core_position"] or 0) * 100,
            (row["ammo_position"] or 0) * 100,
            (target or 0) * 100),
        "熔断状态：%s" % ("熔断中" if row["circuit_breaker"] else "正常"),
    ]
    if row.get("note"):
        lines.append("说明：%s" % row["note"])

    if current_position is None:
        lines.append("指令：请提供当前仓位（--position）以生成操作建议")
        return "\n".join(lines)

    if target is None or pd.isna(target):
        lines.append("指令：不可操作 → 目标仓位无效")
        return "\n".join(lines)

    state = state if state is not None else signal_mod.SignalState.from_dict(_load_state())
    ok, reason = signal_mod.throttle_ok(
        state, current_position, float(target),
        exec_date.strftime("%Y-%m-%d"), extreme=bool(row["extreme"]))
    if ok:
        adjusted = signal_mod.clip_adjustment(current_position, float(target))
        direction = "加仓" if adjusted > current_position else "减仓"
        lines.append("指令：可操作 → %s %.1fpp（调整后目标 %.1f%%）" % (
            direction, abs(adjusted - current_position) * 100, adjusted * 100))
    else:
        lines.append("指令：不可操作 → %s" % reason)
    return "\n".join(lines)


# ================================================================ v2 加密与组合管道


def crypto_drawdown_series(wide, lookback=None):
    """加密回撤基准：**BTC 现货**的滚动 52 周最高（§6.4）。

    必须用 BTC 现货而非 BITX——杠杆 ETF 自身回撤含损耗，长期会"自然"触发，
    与市场情绪无关（v1 §4.5 约束 2 的同一条理由）。
    """
    lookback = lookback or config.DRAWDOWN_LOOKBACK
    btc = wide[("BTC", "close")]
    peak = btc.rolling(lookback, min_periods=lookback).max()
    return 1.0 - btc / peak


def crypto_trend_series(wide):
    """加密趋势系数：BTC 现货相对其 200 日均线（§6.1）。"""
    return ms_mod.trend_factor_series(wide[("BTC", "close")])


def equity_trend_series(wide):
    """大盘趋势系数：QQQ 相对其 200 日均线（§6.1）。"""
    return ms_mod.trend_factor_series(wide[("QQQ", "close")])


# ---------------------------------------------------------------- 标的权重（§7.2 / 第 4C 条）
def blend_close(wide, weights):
    """按**固定权重**把多只标的的 close 合成一条序列（研究用；不参与生产）。

    `weights`：`{symbol: weight}`。用于「一个杠杆 ETF 的底层是多只 ETF 的加权组合」
    的情形——唯一实例是 `GDXU`：它跟踪的指数（CBOE 代码 `MINERS`）=
    `GDX` + `GDXJ` 市值加权，见 `config.GDXU_UNDERLYING_BLEND`。

    三条纪律（都对应「不得静默降级」）：
      1. 权重之和必须为 1 ⇒ 否则**抛错**（不静默归一化：那会把「权重写错」变成
         看不出来的偏差）。
      2. 任一标的缺 `(symbol, "close")` 列 ⇒ **抛错**（不得静默少算一只，
         那等于悄悄换了底层）。
      3. 某日缺价 ⇒ 该日 NaN（**不前向填充**，同 §4.3 对价格类缺失的处理）。
    """
    total = float(sum(weights.values()))
    if abs(total - 1.0) > 1e-9:
        raise ValueError("blend 权重之和必须为 1，收到 %.6f（%s）" % (total, weights))
    missing = [s for s in weights if (s, "close") not in wide.columns]
    if missing:
        raise KeyError(
            "blend 缺少 %s 的 close 列 —— 抓取清单（config.FETCH_SYMBOLS）是否漏了？"
            % missing)
    out = None
    for s, w in weights.items():
        col = wide[(s, "close")].astype(float) * float(w)
        out = col if out is None else out + col
    return out.astype(float)


def _crypto_close(symbol):
    """从 `crypto_prices.csv` 取单标的 close（币股**不在** `prices.csv` 里）。"""
    df = pd.read_csv(config.CRYPTO_PRICES_PATH, dtype={"symbol": str},
                     parse_dates=["date"])
    sub = df[df["symbol"] == symbol].set_index("date")["close"].sort_index()
    if sub.empty:
        raise ValueError(
            "宽表里没有 %s 的 close 列；它是某个守猪待兔标的的无杠杆底层。"
            "若它是币股底层，请检查 crypto_prices.csv（%s）"
            % (symbol, config.CRYPTO_PRICES_PATH))
    return sub


def signal_wide(wide):
    """研究用宽表：在 `wide` 上**只增列**，补齐守猪待兔标的的无杠杆底层。

    从 `scripts/analyze_shoutu_variants.py::_signal_wide` **上移**而来（2026-09-29）。
    为什么必须单源：同一份逻辑现在有**两个**使用方 ——
      1. `scripts/analyze_shoutu_variants.py` 的全样本稳健性对照；
      2. （原计划）`fg_system/cli.py::_print_shoutu_cores` 的逐标的表 ——
         ⚠️ 2026-09-29 裁决：该表**仍用生产口径权重**（3 标的，Σ=1），
         故**不调用**本函数（否则生产口径会变）。本函数目前只有使用方 1。
    两边各写一份必然漂移（第 12.26 条⑤ 的教训）。

    - `config.GDXU_UNDERLYING_COLUMN`：按 `config.GDXU_UNDERLYING_BLEND` 合成
      （GDXU 的真底层是指数 `MINERS` = GDX+GDXJ 市值加权，**不是** GDX 单只）。
    - 其余底层：凡 `config.SIGNAL_UNDERLYING_MAP` 里出现、而 `wide` 没有的列，
      一律到 `crypto_prices.csv` 找（当前只有 CONL 的底层 COIN）。

    ⚠️ **不硬编码任何标的** —— 映射与合成列名都来自 `config`。
    """
    out = wide.copy()
    have = set(out.columns.get_level_values(0))
    # **只补守猪待兔标的的底层**（本函数职责 = SHOUTU inv-vol 权重用底层）。
    # ⚠️ 不能遍历 `SIGNAL_UNDERLYING_MAP` 全值：2026-10-08 C-9 观察池扩池后
    #    map 还含 OBSERVE_SYMBOLS 底层（NVDL→NVDA 等），那些是 `symbol_fg_index`
    #    读 prices 长表用的，**不在** crypto_prices.csv ⇒ 遍历全值会 ValueError。
    #    以 `config.SHOUTU_SYMBOLS` 驱动（同样来自 config，不硬编码，第 12.26 条⑤）。
    needed = set()
    for sym in config.SHOUTU_SYMBOLS:
        und = config.SIGNAL_UNDERLYING_MAP.get(sym)
        if und:
            needed.add(und)
    for und in needed:
        if und in have or und == config.GDXU_UNDERLYING_COLUMN:
            continue
        out[(und, "close")] = _crypto_close(und).reindex(out.index)
    out[(config.GDXU_UNDERLYING_COLUMN, "close")] = blend_close(
        out, config.GDXU_UNDERLYING_BLEND).reindex(out.index)
    return out


def risk_weight_series(wide, symbols=None, window=None, weighting=None,
                       underlying_map=None):
    """`us_equity` 内各标的的滚动权重（Σw = 1）。规则见第 4C 条。

    - 反比波动率（风险平价）：`w_i ∝ 1/σ_i`
    - σ 用**无杠杆底层**（`underlying_map`）的日收益滚动标准差，
      不用 ETF 自身——杠杆 ETF 的自身波动含损耗噪声（同 §4A.1 的理由）
    - **整体 shift(1)**：T 日权重只用 ≤T-1 的数据（§4C.2 前视红线）
    - 不足 `window` 日 / 零波动 ⇒ 该行退化为等权（§4C.6），**永不返回 NaN**
    - 窗口 252 日是先验值，**禁止优化**（§4C.5）

    `underlying_map`：`{symbol: 底层列名}`。默认 `None` ⇒ 用 `config.UNDERLYING_MAP`
    ⇒ **生产逐位不变**。传入别的映射只改「用谁的 σ」这一个口径，其余全部不变；
    研究用途见 `config.SIGNAL_UNDERLYING_MAP`（全样本稳健性对照）。

    返回 DataFrame（index = wide.index，columns = symbols）。
    """
    symbols = list(symbols) if symbols else list(config.SYMBOLS)
    window = config.VOL_WEIGHT_WINDOW if window is None else window
    weighting = config.WEIGHTING if weighting is None else weighting
    underlying_map = config.UNDERLYING_MAP if underlying_map is None else underlying_map
    equal = pd.DataFrame(1.0 / len(symbols), index=wide.index, columns=symbols)

    if weighting == "equal":
        return equal

    vol = pd.DataFrame({
        s: wide[(underlying_map[s], "close")].pct_change(fill_method=None)
        .rolling(window, min_periods=window).std()
        for s in symbols
    }, index=wide.index)

    inv = 1.0 / vol.replace(0.0, np.nan)
    total = inv.sum(axis=1)                 # 默认 skipna，缺一标的时和仍非空
    out = inv.div(total, axis=0)
    # 任一标的缺波动率 ⇒ 整行退化为等权（不混用不完整样本）
    bad = out.isna().any(axis=1) | total.isna() | (total <= 0.0)
    out = out.mask(bad).fillna(equal)
    return out.shift(1).fillna(equal)


def weighted_basket_returns(wide, weights, symbols=None):
    """把各标的的 ETF 日收益按权重合成一条篮子收益序列（§7.2）。

    `basket_ret_t = Σ_i w_i,t × r_i,t`，等价于**每日再平衡到目标权重**的组合。

    **为什么必须有它**：`FgStrategy` 的执行约束（`REBALANCE_THRESHOLD` 10pp、
    `MAX_SINGLE_ADJUST` 30pp）是**绝对值**，必须作用于**组合整体**。
    若把三个标的拆成三条独立 sleeve 各自跑回测，每条的目标只有组合的 1/3
    （≈8.5%），**低于 10pp 阈值 ⇒ 策略几乎不交易** ⇒ 结果被执行假象主导
    （实测该口径算出组合回撤 -72%，**比任何单标的都差**，明显错误）。
    """
    # 默认取**权重的列**，而不是 config.SYMBOLS——加密篮子传进来的是
    # BITX/CONL 等，写死大盘三标的会 KeyError。
    symbols = list(symbols) if symbols else list(weights.columns)
    # fill_method=None：缺失价格必须产生 NaN 收益，**不得**前向填充成 0 收益
    rets = pd.DataFrame(
        {s: wide[(s, "close")].pct_change(fill_method=None) for s in symbols},
        index=wide.index)
    w = weights.reindex(wide.index).ffill()
    # 标的无数据的日期剔除该标的并重新归一化（避免把「缺失」当成 0 收益）
    w = w.where(rets.notna())
    w = w.div(w.sum(axis=1).replace(0.0, np.nan), axis=0)
    return (w * rets).sum(axis=1, min_count=1)


def basket_price_series(basket_returns, start=100.0):
    """把篮子收益序列转成可喂给回测的合成价格序列。

    **前导 NaN 必须保持 NaN**（数据尚未开始），**内部缺口**按 0 收益处理。

    不能整体 `fillna(0)`：加密真实轨的 ETF 2022 年才有数据，
    整体填充会把「还没数据」变成「价格恒定」，从而把年化与最大回撤**双双稀释**
    （实测曾把只有 2 年数据的真实轨算成「2510 日、年化 -0.52%」）。
    """
    r = basket_returns
    first = r.first_valid_index()
    if first is None:
        return pd.Series(np.nan, index=r.index)
    body = r.loc[first:].fillna(0.0)
    out = pd.Series(np.nan, index=r.index)
    out.loc[body.index] = start * (1.0 + body).cumprod()
    return out


def long_to_wide(prices, fields=("open", "high", "low", "close", "volume")):
    """长表价格 → 宽表（columns = MultiIndex (symbol, field)）。

    用于加密**合成轨**：它不在 `crypto_prices.csv` 里，需单独读入
    （`to_crypto_wide` 只读真实轨）。
    """
    # **只 pivot 实际存在的字段**：加密合成轨只有 date/symbol/close，
    # 硬性要求 OHLCV 会 KeyError。
    present = [f for f in fields if f in prices.columns]
    if "close" not in present:
        raise ValueError("价格表必须含 close 列，实际列：%s" % list(prices.columns))
    frames = []
    for f in present:
        w = prices.pivot_table(index="date", columns="symbol", values=f,
                               aggfunc="last")
        w.columns = pd.MultiIndex.from_product([w.columns, [f]],
                                               names=["symbol", "field"])
        frames.append(w)
    return pd.concat(frames, axis=1).sort_index()


def crypto_symbol_weights(symbols=None):
    """加密标的的最终权重（Σ = 1）。规则见第 4B.6 条。

    **层权重 = 层上限归一化**（80/50/30 ⇒ 50% / 31.25% / 18.75%），**层内等权**。
    这样「风险越靠间接的一端、配置越少」（§6.3）真正生效，
    而不是只当一个可能永不触发的上限。
    """
    out = {}
    for layer, members in config.CRYPTO_SYMBOLS.items():
        w_layer = config.CRYPTO_LAYER_WEIGHT[layer]
        for s in members:
            out[s] = w_layer / len(members)
    w = pd.Series(out)
    return w.reindex(symbols) if symbols is not None else w


def weighted_targets(target_position, weights):
    """按权重把组合目标仓位拆到各标的（§7.2）。

    因 Σw_i = 1，故 Σ_i target_i = target_position。
    target_position 为 NaN（warmup）时各标的也写 NaN——**不能写 0.0**，
    那会被回测当成「策略主动空仓」，污染净值与逐年表现（同 `run()` 的约定）。
    """
    w = weights.reindex(target_position.index).ffill()
    return w.mul(target_position, axis=0)


# ---------------------------------------------------------------- 守猪待兔逐标的系数（第 12.26 条 丙）
def shoutu_symbol_index(us_features, shoutu_wide=None, symbols=None, mode=None):
    """各标的的**信号指数**（0~100，供 `zone_of` 使用）。

    **三级回退**，每一级都有明确理由：

    1. **逐标的分位数**（`config.SHOUTU_INDEX_MODE`，默认 `"percentile"`）
       —— 第 12.26 条 Q8 用户选定的口径。窗口**复用 `config.RANK_WINDOW`**
       （756 日，同时是 `WARMUP_DAYS`），**不新造窗口参数** ——
       第 4B.6 条禁止随意新增自由度，而系统已有"滚动百分位"的窗口约定。
       历史不足 756 日时返回 NaN（`rolling_pct` 的既定语义）。
    2. **固定阈值** `(x+100)/2` —— 分位数不可算时使用。这是第 12.26 条的
       原口径，也是**无历史**标的（AXTX/CRCG 只有实时值）的唯一可用口径。
    3. **市场指数** —— 连守猪待兔值都没有时使用（**历史区间全是这种情况**）。

    **为什么第 3 级必须回退而不是留 NaN**：守猪待兔只有 2 天数据。若留 NaN，
    历史区间全部无信号 ⇒ `target_position` 全为 NaN ⇒ **回测彻底失效**
    （`combine` 的约定：NaN 是"无信号"，不是"空仓"）。回退使**历史区间等价于
    原口径** ⇒ 回测结果不变、既有验收结论全部有效。

    **为什么用市场指数而不是跳过该标的**：跳过会让权重和不为 1，
    使 Σ(sat_i·w_i) 失去"加权平均"的性质，总仓位可能**超出**市场级口径
    （与第 12.13 条「不顶边界」冲突）。
    """
    symbols = list(symbols) if symbols else list(config.SYMBOLS)
    market = us_features["fg_index"]
    if shoutu_wide is None:
        shoutu_wide = loader.load_shoutu_fng()
    if shoutu_wide is None or shoutu_wide.empty:
        return pd.DataFrame({s: market for s in symbols}, index=us_features.index)

    # **逐列**调用 `shoutu_to_system_scale`：它只接受 Series（内部做
    # `len(bad)` 判空，传 DataFrame 会触发 "truth value is ambiguous"）。
    scaled = pd.DataFrame(
        {c: loader.shoutu_to_system_scale(shoutu_wide[c])
         for c in shoutu_wide.columns},
        index=shoutu_wide.index)

    mode = config.SHOUTU_INDEX_MODE if mode is None else mode
    if mode == "percentile":
        # rolling_pct 返回 [0,1]，×100 转成与「固定阈值口径」同量纲的 0~100
        pct = scaled.apply(lambda col: rolling_pct(col) * 100.0)
    else:
        pct = pd.DataFrame(np.nan, index=scaled.index, columns=scaled.columns)

    out = {}
    for s in symbols:
        if s in scaled.columns:
            v = pct[s].reindex(us_features.index)
            v = v.fillna(scaled[s].reindex(us_features.index))   # 2 级：固定阈值
            out[s] = v.fillna(market)                            # 3 级：市场指数
        else:
            out[s] = market
    return pd.DataFrame(out, index=us_features.index)


def saturation_of(values, edges=None, saturation=None):
    """指数值 → 档位饱和度（向量化）。

    **必须与 `ms_mod.zone_of` 等价**：`zone_of` 返回**第一个**满足 `idx < edge`
    的档位（边界下闭，`20` 属于档 1）。等价于
    `searchsorted(edges, idx, side="right")` —— 用 `side="left"` 会在
    **恰好等于边界值**时差一档（`20` 会落进档 0 而非档 1），
    使仓位系数整体偏移。等价性由
    `tests/test_shoutu_cores.py::test_saturation_matches_zone_of` 常驻守卫。

    `edges` / `saturation`（可选）：**替换**全局 `config.ZONE_EDGES` /
    `config.ZONE_SATURATION`，用于 A1 的「守猪待兔清仓线变体」
    （例如把末档边界 80 抬到 90、或让末档留 25% 底仓）。
    ⚠️ `None`（默认）时读全局 `config` ⇒ **逐位不变**（等价性红线：
    `tests/test_shoutu_variants.py`）。**不要**改全局 config —— 它被市场指数
    与加密路径共享（`ms_mod.zone_of` / `market_core`）。

    ⚠️ **NaN 输入返回 NaN**（不是末档）：`searchsorted` 会把 NaN 排到末尾 ⇒ 取到
    `saturation[-1]`（= 清仓）⇒ 会把「无信号（warmup / 数据缺失）」静默变成
    「主动清仓」。守猪待兔路径（`shoutu_symbol_index` 回退到市场指数时给出 NaN）
    依赖这条语义。守卫：`tests/test_shoutu_variants.py::test_saturation_of_returns_nan_for_nan_input`。
    """
    edges = config.ZONE_EDGES if edges is None else list(edges)
    table = config.ZONE_SATURATION if saturation is None else list(saturation)
    if len(table) != len(edges) + 1:
        raise ValueError(
            "saturation 长度必须 = len(edges) + 1（档数 = 边界数 + 1）："
            "len(saturation)=%d, len(edges)=%d" % (len(table), len(edges)))
    arr_e = np.asarray(edges, dtype=float)
    arr_t = np.asarray(table, dtype=float)
    if not (np.all(np.isfinite(arr_e)) and np.all(np.isfinite(arr_t))):
        raise ValueError("edges / saturation 含非有限值（NaN / inf）—— "
                         "searchsorted 会给出无意义结果，故直接拒绝")
    vals = np.asarray(values, dtype=float)
    zones = np.searchsorted(arr_e, vals, side="right")
    out = arr_t[zones]
    # ⚠️ **NaN 输入必须返回 NaN**：`searchsorted` 会把 NaN 排到末尾 ⇒ 取到末档
    # （`ZONE_SATURATION[-1] = 0.00` = 清仓）⇒ 会把「**无信号**（warmup / 数据缺失）」
    # 静默变成「**主动清仓**」。市场指数路径由 `market_core` 的 `_is_nan` 守卫兜住，
    # 但守猪待兔路径（`shoutu_symbol_index` 三级回退到市场指数时会给出 NaN）
    # **没有**这层守卫 —— 必须在此拦住。
    return np.where(np.isnan(vals), np.nan, out)


def shoutu_market_saturation(us_features, weights, shoutu_wide=None, symbols=None,
                             edges=None, saturation=None):
    """守猪待兔逐标的系数的**加权平均** —— 等价的市场级系数（第 12.26 条 丙）。

    推导：丙 的原始设计是 `core_i = CORE_CAP × RATIO × sat_i × w_i`。
    因 `Σw_i = 1`，故 `Σ_i core_i = CORE_CAP × RATIO × Σ(sat_i·w_i)`。
    `Σ(sat_i·w_i)` 是 `sat_i` 的**加权平均**，∈ [0,1]
    ⇒ **总仓位不会超过市场级口径**（方向保守，符合第 12.13 条）。

    所以「逐标的系数」不需要新的仓位公式 —— 只需把市场级系数
    `sat_market` 换成 `Σ(sat_i·w_i)` 即可，其余全部不变。

    `edges` / `saturation`：透传给 `saturation_of`（A1 变体用）；
    `None` = 读全局 `config` ⇒ 逐位不变。
    """
    symbols = list(symbols) if symbols else list(config.SYMBOLS)
    idx = shoutu_symbol_index(us_features, shoutu_wide, symbols)
    sat = pd.DataFrame({s: saturation_of(idx[s].values, edges, saturation)
                        for s in symbols},
                       index=us_features.index)
    w = weights.reindex(us_features.index).ffill()
    return (sat * w).sum(axis=1, min_count=len(symbols))


def shoutu_market_index(us_features, weights, shoutu_wide=None, symbols=None):
    """守猪待兔口径的**市场级指数**（0~100）—— 逐标的系统口径指数的加权平均。

    `= Σ_i w_i × shoutu_symbol_index_i`（`Σ w_i = 1`）。

    ⚠️ **与 `shoutu_market_saturation` 的区别**：后者**先查档位再加权**
    （`Σ w_i × sat_i`，值域 [0,1]）；本函数**直接加权连续指数** ——
    熔断 / 极恐的阈值判定（`>= 85` / `<= 10`）需要连续量，用饱和度会丢量纲。

    ⚠️ **历史区间自动等价 `fg_index`**：守猪待兔无数据时 `shoutu_symbol_index`
    三级回退到 `fg_index` ⇒ 逐标的指数均等于 `fg_index` ⇒ 因 `Σ w_i = 1`，
    本函数**逐位等于 `fg_index`** ⇒ keyed extremes 在历史区间不改变任何行为。
    ⚠️ **不得把这个性质外推到 core 变体**（V2/V3 在 `2024-04-23` 之前会变）。

    ⚠️ **上述「逐位等于 `fg_index`」依赖两个前提**：
    (a) `weights` 每行 **Σw = 1** —— 这是 `risk_weight_series` 的约定
    （`pipeline.py:255-264`），本函数**不做归一化**（传 `symbols` 子集时前提
    不成立，结果 = 子集权重和 × 子集指数）。
    (b) **warmup 期**（`fg_index` 为 NaN）：`shoutu_symbol_index` 的最后一级
    `fillna(market)` 取到的也是 NaN ⇒ `idx` 整行 NaN ⇒ `min_count=len(symbols)`
    让**整行返回 NaN**。这与 `fg_index` 的 warmup NaN **同语义**（无信号），
    **不是数据缺口** —— spec §7.5 实测 A1 三个变体各有 760 天 NaN，
    恰好等于 warmup。

    ⚠️ **`weights` 的输入契约**：必须已与 `us_features.index` 对齐
    （生产路径由 `risk_weight_series(wide)` 提供，其 index 与 `wide.index` 一致）。
    本函数做 `weights.reindex(us_features.index).ffill()`：
    - `reindex` 后按 `ffill()` 用**前值**填充 ⇒ 若 `weights.index` 的**最大日期早于**
      `us_features.index` 末尾，会用最后一个已知权重**外推**（对交易日粒度权重，
      周末/停牌沿用前值是有意的）。
    - 若 `weights.index` 的**最小日期晚于** `us_features.index` 开头 ⇒ 开头无前值可填
      ⇒ 权重 NaN ⇒ 与 `min_count` 交互后**整行 NaN**。

    只读不写；`shoutu_wide=None` 时由 `shoutu_symbol_index` 走默认
    （`loader.load_shoutu_fng()`）—— 生产路径**必须**显式传入 history 宽表
    （spec §6：信号源唯一为 `shoutu_history.csv`）。
    """
    symbols = list(symbols) if symbols else list(config.SYMBOLS)
    idx = shoutu_symbol_index(us_features, shoutu_wide, symbols)
    w = weights.reindex(us_features.index).ffill()
    return (idx * w).sum(axis=1, min_count=len(symbols))


def shoutu_core_series(us_features, weights, shoutu_wide=None, symbols=None,
                       edges=None, saturation=None):
    """守猪待兔口径的 `us_equity` 核心仓（第 12.26 条 丙）。

    与 `ms_mod.market_core` 的唯一差别：档位系数取自
    `shoutu_market_saturation`（逐标的加权平均）而非市场指数。
    `CORE_CAP` / `MARKET_CORE_RATIO` / 趋势系数**全部不变** ——
    本改动**不引入任何新的可调参数**（第 4B.6 条）。

    `edges` / `saturation`：透传给 `shoutu_market_saturation`（A1 变体用）；
    `None` = 读全局 `config` ⇒ 逐位不变。
    """
    sat = shoutu_market_saturation(us_features, weights, shoutu_wide, symbols,
                                  edges, saturation)
    trend = us_features["trend"].reindex(us_features.index).fillna(1.0)
    return (config.CORE_CAP * config.MARKET_CORE_RATIO["us_equity"]
            * sat * trend)


def run_equity_v2(raw_dir=None):
    """大盘 features + 趋势列。

    **为什么不直接改 v1 的 `run()`**：v1 的 run() 输出已被测试锁定，
    加列虽看似无害，但任何对已验收代码的改动都是纯风险。本函数调用 v1 的 run()
    再**追加**趋势列，v1 路径零改动。
    """
    us = run(raw_dir=raw_dir, write=False)
    wide = load_wide(raw_dir)
    trend = equity_trend_series(wide).reindex(us.index).fillna(1.0)
    us["trend"] = trend
    us["trend_blocked"] = trend < 1.0
    return us


def run_crypto(raw_dir=None, write=True):
    """执行加密市场全链路，返回 crypto_features（index = 日期）。

    输出列：crypto_fg_index / zone / core_position / trend / trend_blocked /
    layer_* / drawdown / greed_tier / extreme / note / target_position / warmup
    + 两个因子分。
    """
    from fg_system.data import loader

    raw_dir = raw_dir or config.RAW_DIR
    wide = loader.to_crypto_wide(raw_dir)
    loader.check_crypto_anomalies(
        pd.read_csv(config.CRYPTO_PRICES_PATH, dtype={"symbol": str},
                    parse_dates=["date"]).pipe(
            lambda d: pd.concat([d, _btc_long_row()], ignore_index=True)))

    scores = index_mod.factor_scores(wide, market="crypto")
    fg_index = index_mod.build_index(scores, market="crypto")
    dd = crypto_drawdown_series(wide)
    trend = crypto_trend_series(wide)

    rows = []
    state = ms_mod.MarketState(market="crypto")
    for dt in wide.index:
        idx_val = fg_index.get(dt, np.nan)
        out, state = ms_mod.market_target(
            index_value=idx_val,
            drawdown=dd.get(dt, np.nan),
            trend=trend.get(dt, 1.0),
            state=state,
            market="crypto",
            date=dt.strftime("%Y-%m-%d"),
        )
        rows.append({
            "date": dt,
            "crypto_fg_index": idx_val,
            "zone": (ms_mod.zone_of(idx_val)
                     if not (idx_val is None
                             or (isinstance(idx_val, float) and np.isnan(idx_val)))
                     else np.nan),
            "core_position": out.core_position,
            "trend": out.trend,
            "trend_blocked": out.trend_blocked,
            "layer_btc_beta": out.layer_caps.get("btc_beta"),
            "layer_stock_high_beta": out.layer_caps.get("stock_high_beta"),
            "layer_stock_ops_beta": out.layer_caps.get("stock_ops_beta"),
            "drawdown": dd.get(dt, np.nan),
            "greed_tier": state.greed_tier,
            "extreme": out.extreme,
            "note": out.note,
            **{k: scores[k].get(dt, np.nan) for k in scores.columns},
        })

    out_df = pd.DataFrame(rows).set_index("date").sort_index()
    out_df["target_position"] = out_df["core_position"].shift(1)
    out_df["warmup"] = out_df["crypto_fg_index"].isna()

    if write:
        os.makedirs(os.path.dirname(config.CRYPTO_FEATURES_PATH), exist_ok=True)
        out_df.to_csv(config.CRYPTO_FEATURES_PATH, encoding="utf-8")
        with open(config.CRYPTO_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state.to_dict(), f, ensure_ascii=False, indent=2)
    return out_df


def _btc_long_row():
    """把 BTC 现货转成与 crypto_prices.csv 同结构的长表，供异常检测使用。

    必须做这一步：`crypto_prices.csv` **不含 BTC**（它在独立的
    crypto_underlying.csv）。`check_crypto_anomalies` 在缺 BTC 时会 raise
    （不静默跳过），所以调用前必须合并。
    """
    btc = pd.read_csv(config.CRYPTO_UNDERLYING_PATH, parse_dates=["date"])
    btc = btc.copy()
    btc["symbol"] = "BTC"
    btc["open"] = btc["high"] = btc["low"] = btc["close"]
    btc["volume"] = 0.0
    return btc[["date", "symbol", "open", "high", "low", "close", "volume"]]


def _require_series_coverage(series, index, name, allow_nan=None):
    """拒绝**非预期**的 NaN —— 不得静默退回市场指数口径（A1 spec §5.1）。

    `series` 已 `reindex(index)`；`allow_nan`（可选）是与 `index` 对齐的布尔掩码，
    表示「这些天允许 NaN」。生产路径传的是「市场指数无效」
    （`us_features["fg_index"].isna()`，即 warmup）—— 那些天 `market_target`
    本来就按「指数无效」处理，`core=None` 与 `core=NaN` **同语义**，
    属**预期**行为，不是数据缺口。

    ⚠️ 实测（Task 1）：A1 三个变体的 `us_core` 各有 **760 天 NaN，恰好等于 warmup**
    ⇒ 若不按 `allow_nan` 放行，每个变体回放都会抛错（打断 warmup 语义）。

    `index`（以及 `series.index`）**期望**是 `DatetimeIndex`；若不是（整数 /
    字符串索引），日期在错误信息里**以原值呈现**（`str(d)`），**不抛错** ——
    否则 `d.date()` 的 `AttributeError` 会**掩盖**真正的诊断
    （「含 N 天非预期缺失」），正是本守卫要避免的「用另一个错误掩盖真错误」。
    """
    if allow_nan is None:
        allow_nan = pd.Series(False, index=index)
    else:
        allow_nan = pd.Series(allow_nan).reindex(index).fillna(False).astype(bool)
    bad = series.index[series.isna() & ~allow_nan]
    if len(bad):
        # 容错格式化：非 `DatetimeIndex`（整数 / 字符串）时以原值呈现，
        # 不得让 `AttributeError` 掩盖「含 N 天非预期缺失」这个真正的诊断。
        head = ", ".join(str(d.date()) if hasattr(d, "date") else str(d)
                         for d in bad[:10])
        more = "（共 %d 天）" % len(bad) if len(bad) > 10 else ""
        raise ValueError(
            "%s 含 %d 天**非预期**缺失（NaN，已排除 `allow_nan` 标注的预期缺失）"
            "—— 拒绝静默退回市场指数口径：%s%s" % (name, len(bad), head, more))


def run_portfolio(us_features, crypto_features, write=True, us_core=None,
                  us_trigger_index=None):
    """组合级管道：把两个市场的核心仓与共享弹药池合成最终目标仓位（§7）。

    入参是两个市场的 features DataFrame（**未 shift**）。us_features 必须含
    `trend` / `trend_blocked` 列（由 `run_equity_v2` 产出）。

    `us_core`（可选）：**逐日替换** `us_equity` 的五档核心仓（A1 的
    「守猪待兔清仓线变体」离线回放）。含 NaN ⇒ **抛错**（不得静默降级）。
    **只作用于 `us_equity`** —— 加密路径完全不受影响。

    `us_trigger_index`（可选）：**逐日替换** `us_equity` 极端规则（熔断 / 极恐）
    的**触发源**（A2 的 keyed extremes）。含 NaN ⇒ **抛错**。
    **只作用于 `us_equity`**。

    ⚠️ 两者均为 `None`（默认）时行为与改动前**逐位相同**（等价性红线：
    `tests/test_shoutu_variants.py`）。

    返回 portfolio_features（target_position 已 shift(1)）。
    """
    us = us_features.copy()
    cr = crypto_features.copy()

    joined = us.join(cr, how="left", lsuffix="_us", rsuffix="_cr")

    # warmup（`fg_index` 为 NaN）那些天 `market_target` 本就按「指数无效」处理，
    # `core=NaN` 与 `core=None` **同语义** ⇒ 允许 NaN（A2 spec §7.5 实测：
    # A1 三个变体各有 760 天 NaN，恰好等于 warmup）。
    allow_nan = us["fg_index"].isna().reindex(joined.index).fillna(False)

    if us_core is not None:
        if not isinstance(us_core, pd.Series):
            raise TypeError(
                "us_core 必须是 pd.Series（index = 日期），收到 %s —— "
                "传 list/ndarray 会因 RangeIndex 重索引而**静默全丢**"
                % type(us_core).__name__)
        us_core = us_core.reindex(joined.index)
        _require_series_coverage(us_core, joined.index, "us_core", allow_nan)

    if us_trigger_index is not None:
        if not isinstance(us_trigger_index, pd.Series):
            raise TypeError(
                "us_trigger_index 必须是 pd.Series（index = 日期），收到 %s —— "
                "传 list/ndarray 会因 RangeIndex 重索引而**静默全丢**"
                % type(us_trigger_index).__name__)
        us_trigger_index = us_trigger_index.reindex(joined.index)
        _require_series_coverage(us_trigger_index, joined.index,
                                 "us_trigger_index", allow_nan)

    rows = []
    state = pf_mod.PortfolioState()
    # **状态必须建在循环外**：熔断解锁、极贪档位、极恐冷却是跨日状态机，
    # 建在循环内会每轮重置，状态机完全失效。
    us_state = ms_mod.MarketState(market="us_equity")
    cr_state = ms_mod.MarketState(market="crypto")

    for dt in joined.index:
        date_str = dt.strftime("%Y-%m-%d")
        row = joined.loc[dt]
        idx_us = row.get("fg_index", np.nan)
        idx_cr = row.get("crypto_fg_index", np.nan)
        dd_us = row.get("drawdown_us", np.nan)
        dd_cr = row.get("drawdown_cr", np.nan)
        tr_us = row.get("trend_us", 1.0)
        tr_cr = row.get("trend_cr", 1.0)
        tr_us = 1.0 if pd.isna(tr_us) else tr_us
        tr_cr = 1.0 if pd.isna(tr_cr) else tr_cr

        # 必须接收新状态（熔断/档位是跨日状态机）
        core_us = None if us_core is None else us_core[dt]
        trig_us = None if us_trigger_index is None else us_trigger_index[dt]
        out_us, us_state = ms_mod.market_target(
            idx_us, dd_us, tr_us, us_state, "us_equity", date_str,
            core=core_us, trigger_index=trig_us)
        out_cr, cr_state = ms_mod.market_target(
            idx_cr, dd_cr, tr_cr, cr_state, "crypto", date_str)

        state, _, ammo_note = pf_mod.release_ammo(state, [out_us, out_cr])
        state, _, fear_note = pf_mod.apply_extreme_fear(
            state, [out_us, out_cr], date_str)

        target, _ = pf_mod.combine([out_us, out_cr], state)
        cores = [o.core_position for o in (out_us, out_cr)
                 if o.core_position is not None]

        rows.append({
            "date": dt,
            "core_position": sum(cores) if cores else np.nan,
            "ammo_position": pf_mod.ammo_position(state),
            "target_position": target,
            "ammo_released": len(state.ammo_released),
            # 分市场弹药（v2.5）：共享池按市场记账，供加密/大盘各自的 sleeve 口径使用。
            # 不能用整份 ammo_position——那会把另一个市场的弹药算到本市场头上。
            "ammo_us": config.AMMO_PER_BATCH * int(
                state.market_batches.get("us_equity", 0)),
            "ammo_crypto": config.AMMO_PER_BATCH * int(
                state.market_batches.get("crypto", 0)),
            "us_core": out_us.core_position,
            "crypto_core": out_cr.core_position,
            "trend_blocked_us": out_us.trend_blocked,
            "trend_blocked_crypto": out_cr.trend_blocked,
            "extreme": bool(out_us.extreme or out_cr.extreme),
            "note": " | ".join(
                x for x in (ammo_note, fear_note, out_us.note, out_cr.note) if x),
        })

    out = pd.DataFrame(rows).set_index("date").sort_index()
    # §10.3：喂给 backtrader 前整体 shift(1)
    out["target_position"] = out["target_position"].shift(1)
    out["warmup"] = out["core_position"].isna()

    if write:
        os.makedirs(os.path.dirname(config.PORTFOLIO_FEATURES_PATH), exist_ok=True)
        out.to_csv(config.PORTFOLIO_FEATURES_PATH, encoding="utf-8")
        with open(config.STATE_PATH, "w", encoding="utf-8") as f:
            json.dump({"portfolio": state.to_dict(),
                       "us_equity": us_state.to_dict(),
                       "crypto": cr_state.to_dict()},
                      f, ensure_ascii=False, indent=2)
    return out


def _report_shoutu(variant, keyed, us, us_core, us_trigger_index, hist):
    """A2 的监控输出：**一行**结构化摘要（只在开关非默认时调用）。"""
    seg = ["[shoutu] variant=%s keyed_extremes=%s" % (variant, keyed)]
    if hist is not None and not hist.empty:
        seg.append("源 %s" % os.path.basename(config.SHOUTU_HISTORY_PATH))
        seg.append("history 覆盖 %s~%s"
                   % (hist["date"].min().date(), hist["date"].max().date()))
        have = set(hist["symbol"])
        seg.append("主样本 %d/%d"
                   % (sum(1 for s in config.SYMBOLS if s in have), len(config.SYMBOLS)))
    if us_core is not None:
        trend = us["trend"].reindex(us.index).fillna(1.0)
        # ⚠️ **复用** `ms_mod.market_core`，不得在此重写五档公式（第 12.26 条⑤：
        #    两套写法 = 「分析里的规则 ≠ 生产的规则」）。它是标量接口，故逐行调用；
        #    2518 行的一次性开销可忽略。NaN 的 `fg_index` ⇒ `market_core` 返回 None
        #    ⇒ 转成 NaN，与 `us_core` 的 warmup NaN 对齐（均值/最大差都会跳过 NaN）。
        base = pd.Series(
            [ms_mod.market_core(v, t, "us_equity")
             for v, t in zip(us["fg_index"].values, trend.values)],
            index=us.index).astype(float)
        seg.append("us_core 均值 %.4f vs 五档基准 %.4f（差 %+.4f）"
                   % (us_core.mean(), base.mean(), us_core.mean() - base.mean()))
        seg.append("最大日差 %.4f" % float((us_core - base).abs().max()))
    if us_trigger_index is not None:
        fi = us["fg_index"]
        seg.append("trigger_index 均值 %.1f vs fg_index %.1f（差 %+.1f）"
                   % (us_trigger_index.mean(), fi.mean(),
                      us_trigger_index.mean() - fi.mean()))
        seg.append("熔断触发 %d 天" % int(
            (us_trigger_index >= config.EXTREME_GREED_TRIGGER).sum()))
        seg.append("极恐触发 %d 天" % int(
            (us_trigger_index <= config.EXTREME_FEAR_TRIGGER).sum()))
    print(" | ".join(seg))


def _check_shoutu_freshness(hist, us_features):
    """拒绝**陈旧**的信号源 —— 三级回退会掩盖停更，故必须显式检测（spec §7.3）。

    ⚠️ 为什么不能只靠 NaN 守卫：`shoutu_symbol_index` 在守猪待兔无数据时会
    **回退到 `fg_index`**（`pipeline.py:426-434`）⇒ 停更**不产生 NaN** ⇒
    `us_core` 被「旧数据 + 尾部回退」填满并被静默接受 = A1 spec §5.1 禁止的静默降级。

    判据：`hist["date"].max()` 不得早于生产窗口「倒数第 `max_lag + 1` 个交易日」。

    窗口 = 传入 `us_features.index` 的交易日序列；`floor` 是它的倒数第 `lag + 1` 个交易日。
    """
    lag = int(config.SHOUTU_SIGNAL_MAX_LAG_DAYS)
    last_hist = pd.Timestamp(hist["date"].max())
    last_win = pd.Timestamp(us_features.index[-1])
    tail = us_features.index[us_features.index <= last_win]
    floor = pd.Timestamp(tail[max(0, len(tail) - lag - 1)])
    if last_hist < floor:
        raise ValueError(
            "信号源陈旧：history 最后一天 %s，生产窗口最后一天 %s"
            "（滞后超过 %d 个交易日）—— 拒绝静默降级"
            % (last_hist.date(), last_win.date(), lag))


def run_portfolio_v2(raw_dir=None, write=True, shoutu_variant=None,
                     shoutu_keyed_extremes=False, us_features=None,
                     crypto_features=None):
    """**生产组合入口**（A2）—— 把守猪待兔接入 `us_equity` 核心仓的通路。

    `shoutu_variant=None`（默认）且 `shoutu_keyed_extremes=False`（默认）
      ⇒ 与「手拼 `run_equity_v2()` + `run_crypto(write=False)` + `run_portfolio()`」
      **逐位相同**（等价性红线：`tests/test_shoutu_wiring.py`）。

    `shoutu_variant`：`shoutu_variants.VARIANTS` 的键（`"V1"`/`"V2"`/`"V3"`）——
    **替换** `us_equity` 五档核心仓的来源。

    `shoutu_keyed_extremes`：`True` ⇒ 熔断 / 极恐的**触发源**改用守猪待兔口径
    的市场级指数（`shoutu_market_index`）。

    `us_features` / `crypto_features`：可选注入（供 CLI 复用已算好的 features，
    避免重复跑 v1 管道）。为 `None` 时自行计算。

    ⚠️ 注入的 `features` 其 index 必须落在 `load_wide(raw_dir).index` 的覆盖范围内 ——
    否则 `risk_weight_series` 的结果无法 `ffill` 回填，`us_core` 会出现**非 warmup** 的 NaN
    并被覆盖率守卫拦下（那与「陈旧检测」无关）。

    ⚠️ **信号源唯一**：只用 `shoutu_history.csv`（服务端权威日值）。
    `shoutu_fng.csv` 是本地 06:30 采样、口径不同，**不得**进入本通路
    （`loader.py:300-301`）。

    ⚠️ 数据缺失 ⇒ **抛错**，绝不静默退回市场指数口径（spec §7）。
    """
    from fg_system import shoutu_variants      # 延迟导入：shoutu_variants → pipeline 是循环

    if shoutu_variant is not None and not isinstance(shoutu_variant, str):
        raise TypeError(
            "shoutu_variant 必须是 str 或 None，收到 %s —— "
            "传 True/数字会被当成真值静默接受" % type(shoutu_variant).__name__)

    us = run_equity_v2(raw_dir=raw_dir) if us_features is None else us_features
    crypto = (run_crypto(raw_dir=raw_dir, write=False)
              if crypto_features is None else crypto_features)

    us_core = None
    us_trigger_index = None
    hist = None

    if shoutu_variant is not None or shoutu_keyed_extremes:
        wide = load_wide(raw_dir)
        weights = risk_weight_series(wide)
        hist = loader.load_shoutu_history()
        shoutu_wide = shoutu_variants.shoutu_wide_from_long(hist)   # 空/无主样本 ⇒ 抛错
        _check_shoutu_freshness(hist, us)                           # §7.3 停更检测（必须显式）

        # warmup（`fg_index` 为 NaN）的 NaN 属**预期**（spec §7.5 实测）⇒ 放行
        warmup_mask = us["fg_index"].isna()

        if shoutu_variant is not None:
            us_core = shoutu_variants.variant_core_series(
                us, weights, hist, shoutu_variant)
            _require_series_coverage(
                us_core.reindex(us.index), us.index,
                "us_core（变体 %s）" % shoutu_variant, warmup_mask)

        if shoutu_keyed_extremes:
            us_trigger_index = shoutu_market_index(us, weights, shoutu_wide)
            _require_series_coverage(
                us_trigger_index.reindex(us.index), us.index,
                "us_trigger_index（keyed extremes）", warmup_mask)

        _report_shoutu(shoutu_variant, shoutu_keyed_extremes, us, us_core,
                       us_trigger_index, hist)

    return run_portfolio(us, crypto, write=write, us_core=us_core,
                         us_trigger_index=us_trigger_index)
