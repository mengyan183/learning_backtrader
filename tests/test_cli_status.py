# -*- coding: utf-8 -*-
"""`status` / `audit` 命令测试（第 13 条：使用阶段状态总览）。

`status` 是「指令卡 + 状态机 + 真实操作统计」的组合，本身逻辑很薄，
但它是**使用阶段唯一的入口**——必须保证它在「无交易记录」等边界下也能跑通，
否则第一次实盘就没有可用的状态视图。

**阶段闸门（第 13.0 条）**：默认 `development`。此时**不得**把系统外操作
报成违规、**不得**引用第 10.2 条的降级规则 —— 系统尚未进入使用阶段，
那些操作发生在系统之外（把「系统从未被使用」报成「用户严重违纪」，
是每日都会看到的错误结论）。
"""
import pandas as pd
import pytest

from fg_system import audit, cli, config


_MANUAL_ROW = {"date": "2026-09-18", "symbol": "TQQQ", "action": "buy",
               "quantity": 10, "price": 100.0, "reason": "manual"}


def _write_log(tmp_path, rows):
    log_path = tmp_path / "trade_log.csv"
    pd.DataFrame(rows).to_csv(log_path, index=False)
    return str(log_path)


def _run(capsys, monkeypatch, tmp_path, stage, argv):
    monkeypatch.setattr(config, "STAGE", stage)
    monkeypatch.setattr(config, "TRADE_LOG_PATH",
                        _write_log(tmp_path, [_MANUAL_ROW]))
    cli.main(argv)
    return capsys.readouterr().out


# ---------------------------------------------------------------- 边界
def test_status_runs_without_trade_log(capsys, tmp_path, monkeypatch):
    """**无交易记录**（首次使用）时必须正常输出，不得抛异常。"""
    monkeypatch.setattr(config, "TRADE_LOG_PATH", str(tmp_path / "missing.csv"))
    cli.main(["status"])
    out = capsys.readouterr().out
    assert "系统状态" in out
    assert "暂无交易记录" in out
    assert "回测基准" in out


def test_status_reports_trade_stats(capsys, tmp_path, monkeypatch):
    """有交易记录时必须输出笔数与最近一笔（与阶段无关的客观事实）。"""
    out = _run(capsys, monkeypatch, tmp_path, config.STAGE_DEVELOPMENT, ["status"])
    assert "累计 1 笔" in out
    assert "最近一笔" in out


# ---------------------------------------------------------------- 阶段闸门
def test_default_stage_is_development():
    """**守卫**：默认阶段必须是 `development`（第 13.0 条）。

    切到 `usage` 必须由**用户明确宣布**，不得由代码自动推断
    （如"有交易记录就算上线"）—— 那会把用户的探索性操作误判为承诺。
    """
    assert config.STAGE == config.STAGE_DEVELOPMENT


def test_in_usage_stage_tracks_config(monkeypatch):
    monkeypatch.setattr(config, "STAGE", config.STAGE_USAGE)
    assert audit.in_usage_stage() is True
    monkeypatch.setattr(config, "STAGE", config.STAGE_DEVELOPMENT)
    assert audit.in_usage_stage() is False


@pytest.mark.parametrize("argv", [["status"], ["audit"]])
def test_development_stage_omits_violation_rate(capsys, monkeypatch, tmp_path, argv):
    """开发阶段**两处显示点都不得报告违规率**（第 13.0 条）。

    断言用的是**报告格式** `"违规率："`，而不是裸词 `"违规率"` ——
    后者会出现在"…在开发阶段**不适用**"这类解释性文案里，属于**有意保留**的说明。
    """
    out = _run(capsys, monkeypatch, tmp_path, config.STAGE_DEVELOPMENT, argv)
    assert "违规率：" not in out
    assert "开发验证阶段" in out
    assert "不构成违规" in out


@pytest.mark.parametrize("argv", [["status"], ["audit"]])
def test_usage_stage_reports_violation_rate(capsys, monkeypatch, tmp_path, argv):
    """使用阶段保留原行为（第 6.4 / 10.2 条）。"""
    out = _run(capsys, monkeypatch, tmp_path, config.STAGE_USAGE, argv)
    assert "违规率：" in out
    assert "开发验证阶段" not in out


def test_audit_development_stage_relabels_verdicts(capsys, monkeypatch, tmp_path):
    """开发阶段 `audit` 表格**不得**出现「违规-」标签。

    否则「下表是系统外操作、不构成违规」与表里的「违规-无指令操作」
    会**同屏自相矛盾**，读者仍会把它读成违规。
    """
    out = _run(capsys, monkeypatch, tmp_path, config.STAGE_DEVELOPMENT, ["audit"])
    assert "违规-" not in out
    assert "系统外操作-无指令操作" in out


def test_audit_usage_stage_keeps_original_verdicts(capsys, monkeypatch, tmp_path):
    """使用阶段保留原始判定标签（它们是 `audit.audit()` 的数据模型）。"""
    out = _run(capsys, monkeypatch, tmp_path, config.STAGE_USAGE, ["audit"])
    assert "违规-无指令操作" in out


def test_status_does_not_cite_degradation_rule_in_development(
        capsys, monkeypatch, tmp_path):
    """`status` 在开发阶段**不得**出现"触发系统降级"这个断言。

    这是用户每天看到的那句错误结论 —— 它把一个"系统从未被使用"的事实
    说成了"用户严重违纪、系统要降级"（第 13.0 条已明确否定）。
    """
    out = _run(capsys, monkeypatch, tmp_path, config.STAGE_DEVELOPMENT, ["status"])
    assert "触发系统降级" not in out


def test_status_cites_degradation_rule_in_usage(capsys, monkeypatch, tmp_path):
    """使用阶段保留第 10.2 条的提示（它是真实生效的规则）。"""
    out = _run(capsys, monkeypatch, tmp_path, config.STAGE_USAGE, ["status"])
    assert "触发系统降级" in out


def test_development_stage_keeps_operation_summary(capsys, monkeypatch, tmp_path):
    """开发阶段**不隐藏**操作记录，只改**定性**。

    这些记录回答的是「系统给不出指令的标的，我实际持有什么」，
    正是第 12.20 条「对齐系统到实盘」的输入 —— 隐藏它才是丢信息。
    """
    out = _run(capsys, monkeypatch, tmp_path, config.STAGE_DEVELOPMENT, ["status"])
    assert "系统外操作按类型汇总" in out
    assert "人工裁量操作" in out


# ---------------------------------------------------------------- load_log
def test_audit_load_log_missing_file_is_empty():
    """缺文件时 `load_log` 必须返回空表而不是报错（status 依赖此行为）。"""
    log = audit.load_log("/nonexistent/path/trade_log.csv")
    assert log.empty
    assert list(log.columns) == ["date", "symbol", "action", "quantity",
                                 "price", "reason"]


# ---------------------------------------------------------------- 退出码归一化
def test_non_int_return_from_command_is_success_exit_code():
    """⚠️ **成功必须以 0 退出** —— `sys.exit(dict)` 会以 **1** 退出并把 dict 打到 stderr。

    实测（2026-09-28，`py -3.10 -m fg_system.cli backtest-v2`）：退出码**恒为 1**，
    日志第一行是一个裸 dict `{'total_return': 2.06…}`。根因：`_cmd_backtest_v2`
    返回 `pm`（dict），而 `__main__` 直接 `sys.exit(main())` ⇒ **成功被当成失败**，
    任何用退出码判断成败的自动化都会误判。

    修法：把返回值规范成进程退出码 —— **非 int ⇒ 0**（命令的返回值是供程序化
    使用的数据，不是错误信号）；**int 原样透传**（`return 2` 这类仍能表达失败）。
    """
    assert cli._exit_code({"annual_return": 0.1}) == 0
    assert cli._exit_code([{"a": 1}]) == 0
    assert cli._exit_code(None) == 0
    assert cli._exit_code(0) == 0
    assert cli._exit_code(2) == 2


def test_status_shoutu_table_covers_all_shoutu_symbols(capsys):
    """**守卫**：逐标的表必须覆盖**权威源里实际有的**守猪待兔标的。

    第 12.28 条①：原来只遍历 `config.SYMBOLS`（3 个）⇒
    CONL / YINN / GDXU 等**在表里完全不出现**，用户看不到它们的档位与饱和度。

    ⚠️ 判据**从数据推导**，不硬编码「哪几个缺」：权威源对 AXTX / CRCG
    **无历史**（服务端限制，见 `logs/shoutu_daily.log`），这两只**预期**不出现在表里。
    """
    from fg_system import cli
    from fg_system.data import loader

    rc = cli.main(["status"])
    # ⚠️ `cli.main()` 对成功命令返回 `None`（`_cmd_status` 无 return；
    #    退出码归一化 `_exit_code()` 只在 `__main__` 里用）。
    assert rc is None
    out = capsys.readouterr().out

    hist = loader.load_shoutu_history()
    have = [s for s in config.SHOUTU_SYMBOLS if s in set(hist["symbol"])]
    assert len(have) >= 6, "权威源覆盖的标的太少（预期至少 6 个）"
    missing = [s for s in have if s not in out]
    assert not missing, "逐标的表漏了权威源里有的这些标的：%s" % missing


def test_shoutu_avg_covers_only_production_symbols(monkeypatch):
    """**守卫**：加权平均**只用生产标的**（第 8 条「一次只改一件事」）。

    ⚠️ 用**行为**断言，**不用** `inspect.getsource` + 字符串匹配 ——
    那正是 §12.27-① 抓到的弱守卫形态。

    做法：造一份**生产标的（TQQQ/SOXL/UPRO）score 全为 NaN、研究标的有值**的
    权威源长表 ⇒ 生产标的在循环里被 `pd.isna` 跳过 ⇒ `sats` 只有研究标的
    ⇒ 若加权平均把研究标的算进去，`avg` 会偏离市场指数系数；
    ⇒ 只算生产标的时，生产标的全部缺值 ⇒ 每个都回退 `mkt_sat`
      ⇒ `avg` 必须**恰好等于** `mkt_sat`。

    ⚠️ 长表**必须含至少一个生产标的**（否则 `shoutu_wide_from_long` 按设计抛
    ValueError —— 不得静默回退成基准）；这里让它们的 `score` 为 NaN，
    既满足该前置条件、又让它们在值行里缺值。
    """
    from fg_system import cli
    from fg_system.data import loader

    # ⚠️ `date` 用 `pd.Timestamp`（不是字符串）—— `_load_shoutu_long` 会做
    #    `pd.to_datetime(df["date"])`，真实长表的 `date` 是 datetime；
    #    若这里给字符串，`pivot(index="date")` 后的 `sw.index` 就是 str，
    #    `cli._print_shoutu_cores` 里的 `day.strftime(...)` 会 AttributeError。
    rows = []
    for s in config.SHOUTU_SYMBOLS:
        rows.append({"date": pd.Timestamp("2026-09-22"), "symbol": s,
                     "score": float("nan") if s in config.SYMBOLS else 10.0})
        rows.append({"date": pd.Timestamp("2026-09-23"), "symbol": s,
                     "score": float("nan") if s in config.SYMBOLS else -10.0})
    fake = pd.DataFrame(rows)
    monkeypatch.setattr(loader, "load_shoutu_history", lambda *a, **k: fake)

    us = pd.DataFrame({"fg_index": [58.3]},
                      index=pd.to_datetime(["2026-09-23"]))
    ret = cli._print_shoutu_cores(us)
    assert ret is not None, "没有返回值 —— 无法做行为断言"
    assert ret["avg"] == pytest.approx(ret["mkt_sat"]), \
        "生产标的全缺值时 avg 必须恰好等于市场指数系数 ⇒ 说明把研究标的算进去了"


def test_shoutu_table_reads_authoritative_history_not_local_sample():
    """**守卫**：逐标的表必须读**服务端权威源**，不是本地 06:30 采样表。

    第 12.28 条②：`config.py:287-288` 明确两者口径不同、**不要混用**
    （spec §5.4）。原实现读 `load_shoutu_fng()`（本地采样）⇒
    表里显示的档位可能和生产实际用的**不是同一份数据**。

    ⚠️ 用 **AST** 断言（不是字符串匹配）—— 见 §12.27-①：
    字符串守卫会被「换个写法绕开」。
    """
    import ast
    import inspect

    from fg_system import cli
    tree = ast.parse(inspect.getsource(cli._print_shoutu_cores))
    called = {n.func.attr for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert "load_shoutu_history" in called, "没有读服务端权威源"
    assert "load_shoutu_fng" not in called, \
        "仍在读本地 06:30 采样表 —— 与生产信号源不是同一份数据"
