# -*- coding: utf-8 -*-
"""命令行入口：pipeline | backtest | report | audit（§3.2）。

用法：
    python -m fg_system.cli pipeline
    python -m fg_system.cli backtest
    python -m fg_system.cli report
    python -m fg_system.cli audit
"""
import argparse
import sys

from fg_system import config


def _cmd_pipeline(args):
    from fg_system import pipeline
    out = pipeline.run()
    print(pipeline.instruction_card(out, current_position=args.position))
    print("\n已写入：%s" % config.FEATURES_PATH)


def _cmd_backtest(args):
    from fg_system.backtest import runner
    result = runner.report()
    print("=== 损耗归因 ===")
    print(result["loss_attribution"].to_string(index=False))
    print()
    print("=== 策略评估（vs 买入持有） ===")
    for symbol in config.SYMBOLS:
        m = result[symbol]["metrics"]
        b = result[symbol]["buy_and_hold"]
        print("%-6s 策略年化 %7.2f%%  最大回撤 %7.2f%%  |  买入持有年化 %7.2f%%  最大回撤 %7.2f%%"
              % (symbol, m.get("annual_return", float("nan")) * 100,
                 m.get("max_drawdown", float("nan")) * 100,
                 b.get("annual_return", float("nan")) * 100,
                 b.get("max_drawdown", float("nan")) * 100))


def _cmd_report(args):
    from fg_system import pipeline
    from fg_system.dashboard import report
    out = pipeline.run(write=False)
    path = report.build(out)
    print("仪表盘已生成：%s" % path)


def _cmd_audit(args):
    from fg_system import audit
    from fg_system import pipeline
    log = audit.load_log()
    if log.empty:
        print("暂无交易记录（%s）" % config.TRADE_LOG_PATH)
        return
    feats = pipeline.run(write=False)
    audited = audit.audit(log, feats)
    if audited.empty:
        print("暂无交易记录（%s）" % config.TRADE_LOG_PATH)
        return
    if audit.in_usage_stage():
        print(audited.to_string(index=False))
        print("\n违规率：%.1f%%" % (audit.violation_rate(audited) * 100))
    else:
        print("⚠️ 开发验证阶段（第 13.0 条）：系统**尚未进入使用阶段** ⇒ 下表是"
              "\n   **系统外操作**的记录，**不构成违规**；违规率与第 10.2 条的"
              "降级规则\n   均**不适用**。它们的用途是回答「用户实际持有什么」，"
              "用于第 12.20 条的标的对齐。\n")
        # **显示层改写标签**，不改 `audit.audit()` 的返回值：
        # 否则「下表是系统外操作、不构成违规」与表里的「违规-无指令操作」
        # 会**同屏自相矛盾**，读者仍会把它读成违规。
        shown = audited.copy()
        shown["verdict"] = shown["verdict"].str.replace(
            "违规-", "系统外操作-", regex=False)
        print(shown.to_string(index=False))


def _print_shoutu_cores(us):
    """打印守猪待兔**逐标的系数**（第 12.26 条 丙）。

    **为什么必须放在 `status` 里**：这是"改用守猪待兔"这件事**唯一可见的地方**。
    历史区间没有守猪待兔数据（当前只有 2 天），逐标的系数会**回退到市场指数**
    ⇒ 回测结果**不变**。若不在 status 里显示，这个改动就是**不可见的**，
    用户无从确认它到底有没有生效。
    """
    import pandas as pd

    from fg_system import pipeline
    from fg_system import shoutu_variants
    from fg_system.data import loader
    from fg_system.signal import market_signal as ms_mod

    # ⚠️ 2026-09-29（第 12.28 条②）：改用**服务端权威源** `shoutu_history.csv`。
    #    `config.py:287-288` 明确：`shoutu_history.csv` 是**服务端权威日值**，
    #    `shoutu_fng.csv` 是**本地 06:30 采样**，两者**口径不同、不要混用**（spec §5.4）。
    #    原来读后者 ⇒ 表里显示的档位可能和生产实际用的**不是同一份数据**。
    # ⚠️ **这是行为变更**：显示的数字会变。已单独提交并记录前后差异（§12.28②）。
    hist = loader.load_shoutu_history()
    if hist.empty:
        print()
        print("=== 守猪待兔逐标的系数（第 12.26 条 丙）===")
        print("（服务端权威源 shoutu_history.csv 为空 —— 请先跑 fetch_shoutu_history.py）")
        return
    try:
        sw = shoutu_variants.shoutu_wide_from_long(hist, config.SHOUTU_SYMBOLS)
    except ValueError as exc:
        print()
        print("=== 守猪待兔逐标的系数（第 12.26 条 丙）===")
        print("（权威源不可用：%s）" % exc)
        return
    # ⚠️ 2026-09-29（第 12.28 条①）：**权重仍按生产口径（3 个标的，Σ=1）算**。
    #    不要改成 `symbols=config.SHOUTU_SYMBOLS` —— 那会把归一化基数从 3 换成 8，
    #    于是「只对生产标的求和的加权平均」会变成旧值的 0.375 倍
    #    ⇒ **生产口径被改**（实测 0.286→0.125、核心仓 10.31%→4.50%）。
    #    本任务只改「显示什么」，改数字是 Task 5 的事（第 8 条「一次只改一件事」）。
    weights = (pipeline.risk_weight_series(pipeline.load_wide())
               .reindex(us.index).ffill())
    last_w = weights.iloc[-1]

    # **用守猪待兔自己的最后一天**，而不是 `us` 的最后一天：
    # 两者不同（价格数据到 09-21，守猪待兔到 09-23）。若用 `us` 的日期，
    # 逐标的系数会**全部回退市场指数** ⇒ 这一节显示不出任何效果，
    # 等于白加（这正是本节存在的唯一理由）。
    day = sw.index[-1]
    row = sw.loc[day]
    mkt_idx = us["fg_index"].iloc[-1]
    mkt_sat = config.ZONE_SATURATION[ms_mod.zone_of(mkt_idx)]
    base = config.CORE_CAP * config.MARKET_CORE_RATIO["us_equity"]

    n_days = int(sw.notna().any(axis=1).sum())
    print()
    print("=== 守猪待兔逐标的系数（第 12.26 条 丙）===")
    print("守猪待兔日期 %s（价格数据最后一日 %s）"
          % (day.strftime("%Y-%m-%d"), us.index[-1].strftime("%Y-%m-%d")))
    print("口径 %s：分位数需 %d 日历史，当前 %d 日 ⇒ %s"
          % (config.SHOUTU_INDEX_MODE, config.RANK_WINDOW, n_days,
             "分位数生效" if n_days >= config.RANK_WINDOW
             else "**回退固定阈值**（Q8 选定的是分位数）"))
    print("%-6s %10s %10s %6s %8s %8s  %s"
          % ("标的", "守猪待兔", "固定阈值口径", "档位", "饱和度", "权重", "类别"))
    sats = {}
    for s in config.SHOUTU_SYMBOLS:
        if s not in row.index or pd.isna(row[s]):
            continue
        v = float(row[s])
        scaled = (v + 100.0) / 2.0
        z = ms_mod.zone_of(scaled)
        sats[s] = config.ZONE_SATURATION[z]
        # ⚠️ `last_w` 只含 3 个**生产**标的 ⇒ 研究标的**不可索引**
        #    （它们不可交易、没有生产权重）。给它们显示一个归一化出来的百分比
        #    会**误导**（让人以为占了组合 12.5%）⇒ 研究标的显示 `—`。
        w_txt = ("%7.1f%%" % (last_w[s] * 100)) if s in config.SYMBOLS else "      —"
        print("%-6s %+10.0f %10.1f %6d %8.2f %8s  %s"
              % (s, v, scaled, z, config.ZONE_SATURATION[z], w_txt,
                 "生产" if s in config.SYMBOLS else "研究"))
    if not sats:
        print("（该日无任何标的的守猪待兔值）")
        return
    # ⚠️ 加权平均**仍只用生产标的** —— 核心仓是生产量，研究标的**不可交易**。
    #    这样本次改动对生产口径**逐位不变**（第 8 条「一次只改一件事」）。
    prod = [s for s in config.SYMBOLS if s in last_w.index]
    avg = sum(sats.get(s, mkt_sat) * last_w[s] for s in prod)
    print("加权平均系数 %.3f  ←  市场指数系数 %.3f（指数 %.1f，档 %d）"
          % (avg, mkt_sat, mkt_idx, ms_mod.zone_of(mkt_idx)))
    print("核心仓（不含趋势）%.2f%%  ←  原市场级 %.2f%%"
          % (base * avg * 100, base * mkt_sat * 100))
    print("注：历史区间无守猪待兔数据 ⇒ 逐标的系数**回退市场指数**，"
          "回测结果不变（第 12.26 条）。")
    # ⚠️ **返回结果**：测试要用**行为**断言「加权平均只用生产标的」，
    #    而不是去匹配源码字符串（那正是 §12.27-① 的弱守卫形态）。
    return {"avg": avg, "mkt_sat": mkt_sat, "base": base,
            "sats": sats, "weights": last_w}


def _cmd_status(args):
    """使用阶段状态总览（第 13 条）：指令卡 + 状态机 + **真实操作**统计。

    **为什么要它**：系统的有效性与有用性**不能靠回测继续调参来回答**，
    只能靠真实操作记录。本命令把「系统现在要什么」与「我实际做了什么」
    放在同一屏，作为月度/季度复盘的输入。
    """
    from fg_system import audit, pipeline

    us = pipeline.run_equity_v2()
    cr = pipeline.run_crypto(write=False)
    pf = pipeline.run_portfolio(us, cr, write=False)
    snap = pipeline.executable_snapshot(pf)
    if snap is None:
        print("无有效信号（warmup 未完成）")
        return
    # **必须用 executable_snapshot**：分项取自信号日、目标取自执行日，否则
    # 分项之和与目标对不上（实测差 6.75pp），会误导下单。
    # 见 pipeline.executable_snapshot docstring。
    sig_date, exec_date, last, target = snap

    print("=== 系统状态 ===")
    # ---- 待执行（实盘口径：T 日收盘信号 → T+1 开盘执行）----
    pend = pipeline.pending_signal(pf)
    if pend is not None:
        p_date, p_row, p_target = pend
        print("【待执行】信号日 %s（收盘） → 下一交易日开盘"
              % p_date.strftime("%Y-%m-%d"))
        print("  大盘核心仓 %6.2f%%（趋势过滤 %s）  加密核心仓 %6.2f%%（%s）"
              % ((p_row["us_core"] or 0) * 100,
                 "生效" if p_row["trend_blocked_us"] else "未触发",
                 (p_row["crypto_core"] or 0) * 100,
                 "生效" if p_row["trend_blocked_crypto"] else "未触发"))
        print("  弹药        大盘 %6.2f%% / 加密 %6.2f%%（共享池 %.0f%%，已释放 %d 批）"
              % (p_row["ammo_us"] * 100, p_row["ammo_crypto"] * 100,
                 config.AMMO_CAP * 100, int(p_row["ammo_released"])))
        print("  目标总仓位 %6.2f%%   现金 %6.2f%%"
              % (p_target * 100, (1.0 - p_target) * 100))
        if p_row.get("note"):
            print("  说明：%s" % p_row["note"])

    # ---- 对照：最近一个已执行的目标（回测口径）----
    print("【已执行】信号日 %s（收盘） → 执行日 %s（开盘），目标 %.2f%%"
          % (sig_date.strftime("%Y-%m-%d"), exec_date.strftime("%Y-%m-%d"),
             target * 100))

    # ---- 守猪待兔逐标的系数（第 12.26 条 丙）----
    _print_shoutu_cores(us)

    # ------------------------------------------------ 真实操作（第 6 条 / 第 13 条）
    log = audit.load_log()
    usage = audit.in_usage_stage()
    print()
    print("=== 真实操作（%s）===" % config.TRADE_LOG_PATH)
    if not usage:
        print("阶段：**开发验证阶段**（第 13.0 条）—— 系统尚未进入使用阶段，"
              "以下操作发生在**系统之外**。")
    if log.empty:
        print("暂无交易记录——记录必须在下单**当日**完成（第 6.3 条）。")
    else:
        this_month = log[log["date"].dt.to_period("M") ==
                         exec_date.to_period("M")]
        print("累计 %d 笔 | 本月 %d 笔（第 5.3 条上限 4 次/月）"
              % (len(log), len(this_month)))
        print("最近一笔：%s %s %s @ %s（%s）"
              % (log.iloc[-1]["date"].date(), log.iloc[-1]["symbol"],
                 log.iloc[-1]["action"], log.iloc[-1]["price"],
                 log.iloc[-1]["reason"]))
        feats = pipeline.run(write=False)
        audited = audit.audit(log, feats)
        if audited.empty:
            pass
        elif usage:
            rate = audit.violation_rate(audited)
            print("违规率：%.1f%%（第 10.2 条：连续 3 个月 > 10%% 触发系统降级）"
                  % (rate * 100))
            bad = audit.violations(audited)
            if not bad.empty:
                print("违规明细：")
                print(bad.to_string(index=False))
        else:
            # 开发阶段**不计算违规率**（第 13.0 条）。但操作记录本身有用 ——
            # 它回答「系统给不出指令的标的，我实际持有什么」，
            # 正是第 12.20 条「对齐系统到实盘」的输入。隐藏它才是丢信息。
            print("系统外操作按类型汇总（**不构成违规**，第 13.0 条）：")
            off = audit.violations(audited)
            if off.empty:
                print("  （无）")
            else:
                for detail, n in off.groupby("detail").size().sort_values(
                        ascending=False).items():
                    print("  %-22s %d 笔" % (detail, n))
            print("  用途：识别「系统覆盖不到但实际持有」的标的"
                  "（第 12.20 条的对齐输入）。")
            print("  违规率与第 10.2 条的降级规则在开发阶段**不适用**。")
        if len(this_month) > 4:
            print("⚠️ 本月操作 %d 次 > 4 次%s"
                  % (len(this_month),
                     "，触发第 7.1 条强制复盘" if usage
                     else "（开发阶段不计违规；第 5.3 条上限仅供参考）"))

    # ------------------------------------------------ 供复盘对照的回测基准
    print()
    print("=== 回测基准（仅供对照，**不是**预期收益）===")
    print("大盘 sleeve：回撤约 -28.8% / 年化约 11.6%（组合级口径，第 12.12 条）")
    # v2.8（第 12.23 条）：BTC 现货杠杆纳入 `btc_beta` 层后的实测值
    # （A/B 口径：旧 -34.30%/-1.42% ⇒ 新 -29.84%/-1.94%）。
    # **硬编码而非实时计算**：实时跑加密回测需数十秒，`status` 是每日命令。
    # 改动加密层配置时**必须同步更新此字符串**。
    print("加密 sleeve：回撤约 -29.8% / 年化约 -1.9%（合成轨，不代表真实预期）")
    print("系统价值在**避开灾难性回撤**，不在于跑赢买入持有（设计文档 §1.3）。")


def _cmd_crypto_pipeline(args):
    from fg_system import config, pipeline
    cr = pipeline.run_crypto()
    valid = cr.dropna(subset=["crypto_fg_index"])
    if valid.empty:
        print("加密指数无有效信号（warmup 未完成——CF1 贪恐 2018-02 起，"
              "叠加 756 日滚动窗口，约 2021-02 才生效）")
    else:
        last = valid.iloc[-1]
        print("日期：%s" % valid.index[-1].strftime("%Y-%m-%d"))
        print("加密贪恐指数：%.1f" % last["crypto_fg_index"])
        print("趋势过滤：%s" % ("生效（上限减半）" if last["trend_blocked"] else "未触发"))
        print("极贪档位：%d（0=正常）" % int(last["greed_tier"]))
        print("加密核心仓：%.2f%%" % ((last["core_position"] or 0) * 100))
        print("分层上限：BTC %.2f%% / 高Beta %.2f%% / 经营Beta %.2f%%" % (
            (last["layer_btc_beta"] or 0) * 100,
            (last["layer_stock_high_beta"] or 0) * 100,
            (last["layer_stock_ops_beta"] or 0) * 100))
        if last.get("note"):
            print("说明：%s" % last["note"])
    print("\n已写入：%s" % config.CRYPTO_FEATURES_PATH)


def _cmd_portfolio(args):
    from fg_system import config, pipeline
    us = pipeline.run_equity_v2()          # 含 trend 列（v1 的 run() 不含）
    cr = pipeline.run_crypto(write=True)
    out = pipeline.run_portfolio(us, cr, write=True)
    snap = pipeline.executable_snapshot(out)
    if snap is None:
        print("无有效目标仓位")
    else:
        sig_date, exec_date, last, target = snap
        print("信号日：%s（收盘）   执行日：%s（开盘）"
              % (sig_date.strftime("%Y-%m-%d"), exec_date.strftime("%Y-%m-%d")))
        print("大盘核心仓：%.2f%%（趋势过滤：%s）" % (
            (last["us_core"] or 0) * 100,
            "生效" if last["trend_blocked_us"] else "未触发"))
        print("加密核心仓：%.2f%%（趋势过滤：%s）" % (
            (last["crypto_core"] or 0) * 100,
            "生效" if last["trend_blocked_crypto"] else "未触发"))
        print("弹药仓：%.2f%%（已释放 %d 批，共享池）" % (
            (last["ammo_position"] or 0) * 100, int(last["ammo_released"])))
        print("目标总仓位：%.2f%%" % (target * 100))
        if last.get("note"):
            print("说明：%s" % last["note"])
    print("\n已写入：%s" % config.PORTFOLIO_FEATURES_PATH)


def _cmd_attribution(args):
    import pandas as pd
    from fg_system import config, pipeline
    from fg_system.backtest import attribution
    us = pipeline.run_equity_v2()
    px = pd.read_csv(config.RAW_DIR + "/prices.csv", dtype={"symbol": str},
                     parse_dates=["date"])
    qqq = px[px["symbol"] == "QQQ"].set_index("date")["close"].sort_index()
    table = attribution.full_report(us, qqq)
    print("=== 趋势过滤贡献度归因（基准 QQQ）===")
    print(table.T.to_string())
    v = attribution.verdict(attribution.contribution_table(us, qqq))
    print("\n判定：%s" % v["reason"])


def _cmd_crypto_backtest(args):
    import os

    import pandas as pd
    from fg_system import config, pipeline
    from fg_system.backtest import crypto_runner, runner

    out = crypto_runner.report()
    px = pd.read_csv(config.RAW_DIR + "/prices.csv", dtype={"symbol": str},
                     parse_dates=["date"])
    qqq = px[px["symbol"] == "QQQ"].set_index("date")["close"].sort_index()
    crypto_runner.print_report(out, us_close=qqq)

    # ---------------------------------------------------------- v2.5 组合级口径
    print("=== 加密组合级（策略，第 4B.7 条）===")
    w = pipeline.crypto_symbol_weights()
    print("标的权重：" + " / ".join("%s %.2f%%" % (s, w[s] * 100) for s in w.index))

    cr = pipeline.run_crypto(write=False)
    us = pipeline.run_equity_v2()
    pf = pipeline.run_portfolio(us, cr, write=False)
    # **加密 sleeve** 的目标 = 加密核心仓 + 加密**自己的**弹药（不是整份共享池）。
    # **不 fillna(0.0)**：warmup 期（无信号）必须保持 NaN 并被回测跳过，
    # 写 0 会被当成「策略主动空仓」，把年化与回撤双双稀释（同 pipeline.run 的约定）。
    target = (pf["crypto_core"] + pf["ammo_crypto"]) \
        .clip(upper=1.0).shift(1)

    for track, path in (("合成轨", config.SYNTHETIC_PATH),
                        ("真实轨", config.CRYPTO_PRICES_PATH)):
        if not os.path.exists(path):
            continue
        long = pd.read_csv(path, dtype={"symbol": str}, parse_dates=["date"])
        r = crypto_runner.portfolio_backtest(
            long, target, w, cr["crypto_fg_index"])
        if r is None or r.empty:
            print("  %-6s 无有效数据（warmup 未完成或该轨过短）" % track)
            continue
        m = runner.performance_metrics(r)
        print("  %-6s 年化 %+8.2f%%   最大回撤 %+8.2f%%   波动率 %6.2f%%   "
              "(%s ~ %s, %d 日)"
              % (track, m["annual_return"] * 100, m["max_drawdown"] * 100,
                 m["annual_vol"] * 100, r.index[0].date(), r.index[-1].date(),
                 len(r)))
    print("  注：合成轨仅验证策略逻辑，**不代表真实预期**（第 4B.5 条）。")
    print()


def _cmd_backtest_v2(args):
    """v2 大盘回测：含趋势过滤 + 标的权重（§7.2 / 第 4C 条）。

    为什么必须单独跑：v1 的 `backtest` 读 `Data/features.csv`，那是 v1 管道的产物
    （**不含趋势过滤**），跑出来仍是 v1 的 -61.53%，无法反映 v2 的核心改动。

    **三种口径**（`--weighting`）：
      - `inv_vol`（默认）反比波动率权重 —— **这是实际持仓口径**
      - `equal`           等权（对照）
      - `full`            把整份 target_position 压到单一标的 —— **仅诊断用**。
                          测的是「假设全仓某一只」的**单标的最坏值**，
                          **不是实际组合**（v2.1/v2.2 报告引用的历史数字即此口径）。

    **验收判定以「组合级」为准**（Σ 各标的加权收益）；逐标的仅用于识别谁在拖累。
    弹药池是共享的，此处把它整份计入大盘，属**近似**——加密部分见
    `crypto-backtest`，两市场合成见 `portfolio`。
    """
    import pandas as pd
    from fg_system import config, pipeline
    from fg_system.backtest import runner

    mode = args.weighting or config.WEIGHTING
    us = pipeline.run_equity_v2()
    # A2：走正式生产入口（两开关默认关 ⇒ 与旧链路逐位相同）。
    # `us_features=us` 是**复用**已算好的 features，避免重复跑 v1 管道。
    pf = pipeline.run_portfolio_v2(
        write=False, us_features=us,
        shoutu_variant=args.shoutu_variant,
        shoutu_keyed_extremes=bool(args.shoutu_keyed_extremes))

    # **大盘 sleeve** 的目标 = 大盘核心仓（已含趋势过滤）+ **大盘自己的**弹药。
    # **不能**用整份 `ammo_position`——共享池是「先到先得」，实测**加密把 3 批全拿走、
    # 大盘拿到 0 批**。把整份计入大盘会严重高估大盘暴露
    # （曾据此算出最大暴露 51.5%，实际只有 31.5%）。见第 12.8.1 条。
    base = (pf["us_core"].fillna(0.0) + pf["ammo_us"]) \
        .clip(upper=1.0).shift(1)

    prices = pd.read_csv(config.RAW_DIR + "/prices.csv", dtype={"symbol": str},
                         parse_dates=["date"])

    if mode == "full":
        # 旧口径：把**整份** target_position 压到单一标的（仅诊断，非实际组合）
        print("=== v2 大盘回测（趋势过滤）===")
        print("权重口径：单标的满仓（**仅诊断，非实际组合**）")
        print()
        print("%-6s %12s %12s | %12s %12s" % (
            "标的", "策略年化", "策略回撤", "买入持有年化", "买入持有回撤"))
        rows = []
        for symbol in config.SYMBOLS:
            f = us.copy()
            f["target_position"] = base
            f["fg_index"] = us["fg_index"]
            f["zone"] = us["zone"]
            p = prices[prices["symbol"] == symbol].set_index("date").sort_index()
            f = f.join(p[["open", "high", "low", "close", "volume"]], how="inner")
            _, returns = runner.run_single(f, symbol)
            m = runner.performance_metrics(returns) if returns is not None else {}
            bh = runner.performance_metrics(p["close"].pct_change().dropna())
            rows.append((symbol, m, bh))
            print("%-6s %11.2f%% %11.2f%% | %11.2f%% %11.2f%%" % (
                symbol, m.get("annual_return", float("nan")) * 100,
                m.get("max_drawdown", float("nan")) * 100,
                bh.get("annual_return", float("nan")) * 100,
                bh.get("max_drawdown", float("nan")) * 100))
        print()
        print("注：此口径**不是**实际组合——实际组合同时持有三者。见默认口径。")
        return rows

    wide = pipeline.load_wide()
    weights = pipeline.risk_weight_series(wide, weighting=mode) \
        .reindex(us.index).ffill()
    label = "反比波动率（风险平价）" if mode == "inv_vol" else "等权"
    last_w = weights.iloc[-1]

    print("=== v2 大盘回测（趋势过滤 + 标的权重）===")
    print("权重口径：%s" % label)
    print("最新权重：" + " / ".join("%s %.1f%%" % (s, last_w[s] * 100)
                                    for s in config.SYMBOLS))
    print("弹药归属：大盘 %.2f%% / 加密 %.2f%%（共享池上限 %.0f%%）"
          % (pf["ammo_us"].iloc[-1] * 100, pf["ammo_crypto"].iloc[-1] * 100,
             config.AMMO_CAP * 100))
    print()
    print("%-6s %10s %14s %14s" % ("标的", "最新权重", "买入持有年化", "买入持有回撤"))
    for symbol in config.SYMBOLS:
        p = prices[prices["symbol"] == symbol].set_index("date")["close"].sort_index()
        bh = runner.performance_metrics(p.pct_change().dropna())
        print("%-6s %9.1f%% %13.2f%% %13.2f%%" % (
            symbol, last_w[symbol] * 100, bh["annual_return"] * 100,
            bh["max_drawdown"] * 100))

    # 组合级：把三者按权重合成一条篮子，**执行约束作用于组合整体**（不是逐 sleeve）
    basket = pipeline.basket_price_series(
        pipeline.weighted_basket_returns(wide, weights))
    f = us.copy()
    f["target_position"] = base
    f["fg_index"] = us["fg_index"]
    f["zone"] = us["zone"]
    for col in ("open", "high", "low", "close"):
        f[col] = basket
    f["volume"] = 0.0
    _, returns = runner.run_single(f, "BASKET")
    pm = runner.performance_metrics(returns)

    print()
    print("=== 组合级（加权篮子，单组合口径）===")
    print("组合   年化 %7.2f%%   最大回撤 %7.2f%%   Calmar %.3f"
          % (pm["annual_return"] * 100, pm["max_drawdown"] * 100, pm["calmar"]))
    print()
    print("目标：大盘最大回撤 <= -40%（以**组合级**为准）")
    return pm


def _cmd_shoutu_record(args):
    """录入守猪待兔贪恐指数（第 12.26 条）。

    **为什么需要它**：该指数的历史数据三条路全不通（API 曾因 token 绑单设备被否、
    App 导出仅图片、图片数字化已证伪），而丙方案（逐标的分位数）**依赖历史分布**
    ⇒ 只能**前向记录**，积累到足够长度（如 1 年）再实施。

    **幂等**：同一天重复录入会**覆盖**而非追加，因此补录/更正可放心重跑。
    不带 `--values` 时只**显示**已录入内容，不写文件。
    """
    from fg_system.data import loader, shoutu

    mapping = {}
    for part in (args.values or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            print("格式错误（应为 SYMBOL=值）：%s" % part)
            return 1
        key, val = part.split("=", 1)
        mapping[key.strip().upper()] = float(val)

    if not mapping:
        wide = loader.load_shoutu_fng()
        if wide.empty:
            print("尚未录入任何守猪待兔数据（%s）" % config.SHOUTU_FNG_PATH)
            return 0
        print("已录入（%s）：" % config.SHOUTU_FNG_PATH)
        print(wide.to_string())
    else:
        wide, n = shoutu.append_records(shoutu.mapping_to_frame(mapping, date=args.date))
        print("已录入 %d 条（日期 %s）" % (n, args.date or "今天"))
        print(wide.to_string())
        print("\n已写入：%s" % config.SHOUTU_FNG_PATH)

    counts = shoutu.recorded_symbols()
    print("\n各标的覆盖天数：" + " / ".join("%s %d" % (k, v) for k, v in sorted(counts.items())))
    missing = [s for s in config.SHOUTU_SYMBOLS if s not in counts]
    if missing:
        print("尚未录入：%s" % missing)
    print("⚠️ 丙方案（逐标的分位数）需要足够长的历史（如 1 年）才能实施；"
          "当前累计 %d 天。" % (len(wide) if not wide.empty else 0))
    return 0


def _cmd_evolution(args):
    """进化就绪度报告（第 14 条）。

    **本命令只报告，不改任何参数。** 第 14.1 条：
    自动「发现问题」可以，自动「改变参数」不行 —— 后者是拟合历史（第 13.1 条）。

    **为什么需要它**：系统已有的自动进化（口径自动切换）是**静默**的 ——
    数据没到位就回退、到位了就切换。不显示出来，用户无从知道
    "下一次自动升级是什么时候"，也无从判断瓶颈在数据还是在算法。
    """
    import pandas as pd

    from fg_system import evolution

    r = evolution.readiness()
    print("=== 进化就绪度（第 14 条）===")
    print("阶段：%s（第 13.0 条）" % r["stage"])
    print("守猪待兔档位口径：配置 %s（实际生效见下表）" % r["shoutu_mode"])
    print()
    t = r["shoutu"]
    print("%-6s %8s %8s %8s %13s %-12s"
          % ("标的", "已积累", "所需", "还差", "实际生效", "最后一日"))
    for s, row in t.iterrows():
        # **必须用 `pd.isna` 而不是 `is not None`**：`last` 是 datetime 列，
        # 缺值会被 pandas 强制转成 `NaT`（不是 None），`is not None` 拦不住，
        # 随后 `.strftime` 会抛 "NaTType does not support strftime"。
        last = row["last"]
        last_str = "—" if (last is None or pd.isna(last)) else last.strftime("%Y-%m-%d")
        print("%-6s %8d %8d %8s %13s %-12s" % (
            s, row["days"], row["needed"],
            row["remaining"] if row["remaining"] else "—",
            row["mode"], last_str))
    print()
    if r["next_upgrade"]:
        s, n = r["next_upgrade"]
        print("下一次**自动**升级：%s 还差 %d 个交易日 ⇒ 届时自动从 fixed 切到 percentile"
              % (s, n))
        print("  （按每年约 252 个交易日估算，约 %.1f 年）" % (n / 252.0))
    else:
        print("所有标的均已生效分位数口径。")
    print()
    print("⚠️ 第 14.1 条：本命令**只报告**，不自动改任何参数。")
    print("   自动「发现问题」可以，自动「改变参数」不行 —— 后者是拟合历史（第 13.1 条）。")
    return 0


def _exit_code(result):
    """把 `main()` 的返回值规范成**进程退出码**。

    ⚠️ **为什么必须归一化**：若干命令返回的是**数据**而不是状态码 ——
    `_cmd_backtest_v2` 返回 `pm`（dict），`--weighting full` 时返回 `rows`（list）。
    直接 `sys.exit(dict)` 会**以 1 退出**并把 dict 打到 stderr ⇒ **成功被当成失败**。
    实测（2026-09-28）：`py -3.10 -m fg_system.cli backtest-v2` 退出码恒为 **1**，
    日志第一行是一个裸 dict `{'total_return': 2.06…}` —— 任何用退出码判断成败的
    自动化都会误判。

    规则：**非 int ⇒ 0**（返回值是供程序化使用的数据，不是错误信号）；
    **int 原样透传**（`return 2` 这类仍能表达失败）。
    """
    return 0 if not isinstance(result, int) else result


def main(argv=None):
    # 单源化（TODO-3）：合法变体清单取自 `shoutu_variants.VARIANTS`，**不得**在此
    # 再抄一遍 —— 否则新增变体（如 V4）时库层接受、CLI 却静默拒绝（第 12.26 条⑤）。
    # **延迟导入**：与 `pipeline.py` 对同一模块的写法一致（`shoutu_variants` ↔ `pipeline`
    # 相互引用，顶层导入需依赖加载顺序）；且 `main()` 每次调用**重新取**该模块，
    # 使 `VARIANTS` 在运行时的改动（如测试 monkeypatch 注入假变体）能真正生效。
    from fg_system import shoutu_variants

    parser = argparse.ArgumentParser(prog="fg_system")
    sub = parser.add_subparsers(dest="command", required=True)

    p1 = sub.add_parser("pipeline", help="跑全链路并输出指令卡")
    p1.add_argument("--position", type=float, default=None, help="当前仓位（0-1）")
    p1.set_defaults(func=_cmd_pipeline)

    sub.add_parser("backtest", help="跑回测与损耗归因").set_defaults(func=_cmd_backtest)
    sub.add_parser("report", help="生成 HTML 仪表盘").set_defaults(func=_cmd_report)
    sub.add_parser("audit", help="交易记录违规审计").set_defaults(func=_cmd_audit)

    sub.add_parser("status", help="使用阶段状态总览（指令卡 + 真实操作统计）"
                   ).set_defaults(func=_cmd_status)

    p2 = sub.add_parser("crypto-pipeline", help="跑加密市场管道并输出指令卡")
    p2.add_argument("--position", type=float, default=None)
    p2.set_defaults(func=_cmd_crypto_pipeline)

    sub.add_parser("portfolio", help="跑组合级管道（统一资金池）").set_defaults(
        func=_cmd_portfolio)
    sub.add_parser("attribution", help="输出趋势过滤贡献度归因").set_defaults(
        func=_cmd_attribution)
    sub.add_parser("crypto-backtest", help="输出加密双轨回测与跨市场相关性").set_defaults(
        func=_cmd_crypto_backtest)
    p3 = sub.add_parser("backtest-v2", help="v2 大盘回测（趋势过滤 + 标的权重）")
    p3.add_argument("--weighting", choices=["inv_vol", "equal", "full"], default=None,
                    help="标的权重口径（默认取 config.WEIGHTING）")
    p3.add_argument("--shoutu-variant", default=None,
                    choices=sorted(shoutu_variants.VARIANTS),
                    help="用守猪待兔替换 us_equity 五档核心仓的来源（A2）。"
                         "默认关闭。⚠️ 打开前必须满足 §14.5 O4 的触发条件")
    p3.add_argument("--shoutu-keyed-extremes", action="store_true",
                    help="熔断/极恐的触发源改用守猪待兔口径（A2）。"
                         "默认关闭。⚠️ 其量级尚未评估")
    p3.set_defaults(func=_cmd_backtest_v2)

    sub.add_parser("evolution",
                   help="进化就绪度报告（第 14 条，只报告不改参数）"
                   ).set_defaults(func=_cmd_evolution)

    p4 = sub.add_parser("shoutu-record",
                        help="录入守猪待兔贪恐指数（第 12.26 条）")
    p4.add_argument("--values", default=None,
                    help='形如 "CONL=24,YINN=-41"；省略则只显示已录入内容')
    p4.add_argument("--date", default=None, help="录入日期 YYYY-MM-DD（默认今天）")
    p4.set_defaults(func=_cmd_shoutu_record)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(_exit_code(main()))
