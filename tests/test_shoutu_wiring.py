# -*- coding: utf-8 -*-
"""A2（守猪待兔生产通路）的等价性红线、零 I/O 与缺失策略测试。

设计：docs/superpowers/specs/2026-09-28-shoutu-production-wiring-design.md
"""
import os

import pandas as pd
import pytest

from fg_system import config, pipeline
from fg_system.data import loader


def _us(idx, fg=50.0, trend=1.0):
    return pd.DataFrame({
        "fg_index": [fg] * len(idx), "zone": 2.0, "drawdown": 0.0,
        "core_position": 0.1, "ammo_position": 0.0, "target_position": 0.1,
        "trend": trend, "trend_blocked": trend < 1.0, "warmup": False,
    }, index=idx)


def _cr(idx, fg=50.0, trend=1.0):
    return pd.DataFrame({
        "crypto_fg_index": [fg] * len(idx), "drawdown": 0.0, "trend": trend,
        "trend_blocked": trend < 1.0, "core_position": 0.1,
        "target_position": 0.1, "warmup": False,
    }, index=idx)


def _inputs(n=40):
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return _us(idx), _cr(idx)


def test_default_is_identical_to_manual_chain():
    """等价性红线：默认参数下 `run_portfolio_v2` == 手拼的 cli 链路（逐位相等）。"""
    us, cr = _inputs()
    a = pipeline.run_portfolio_v2(write=False, us_features=us, crypto_features=cr)
    b = pipeline.run_portfolio(us, cr, write=False)
    pd.testing.assert_frame_equal(a, b)


def test_default_does_not_touch_shoutu_history(monkeypatch):
    """开关全关 ⇒ **零 I/O**：`load_shoutu_history` 一次都不被调用。"""
    def boom(*a, **k):
        raise AssertionError("默认参数下不得读 shoutu_history.csv")
    monkeypatch.setattr(loader, "load_shoutu_history", boom)
    us, cr = _inputs()
    pipeline.run_portfolio_v2(write=False, us_features=us, crypto_features=cr)


def test_default_prints_nothing(capsys):
    """开关全关 ⇒ 不打印任何东西（保持现状 stdout 逐字不变）。"""
    us, cr = _inputs()
    pipeline.run_portfolio_v2(write=False, us_features=us, crypto_features=cr)
    assert capsys.readouterr().out == ""


def test_unknown_variant_raises_keyerror():
    us, cr = _inputs()
    with pytest.raises(KeyError):
        pipeline.run_portfolio_v2(write=False, us_features=us, crypto_features=cr,
                                  shoutu_variant="V9")


def test_non_string_variant_raises_typeerror():
    """`shoutu_variant=True` 不得被当成真值静默接受。"""
    us, cr = _inputs()
    with pytest.raises(TypeError):
        pipeline.run_portfolio_v2(write=False, us_features=us, crypto_features=cr,
                                  shoutu_variant=True)


def test_stale_history_raises(monkeypatch):
    """⚠️ 停更检测：history 落后生产窗口超过容忍 ⇒ 抛错。

    为什么必须有这条：`shoutu_symbol_index` 三级回退到 `fg_index` ⇒ 停更**不产生 NaN**
    ⇒ NaN 守卫抓不到（spec §7.3）。
    """
    idx = pd.date_range("2024-01-01", periods=40, freq="B")
    stale = pd.DataFrame({"date": [idx[0]], "symbol": ["TQQQ"],
                          "score": [0.0], "price": [1.0]})
    monkeypatch.setattr(loader, "load_shoutu_history", lambda *a, **k: stale)
    with pytest.raises(ValueError) as e:
        pipeline.run_portfolio_v2(write=False, us_features=_us(idx),
                                  crypto_features=_cr(idx), shoutu_variant="V1")
    assert "陈旧" in str(e.value)


def test_history_within_lag_does_not_raise(monkeypatch):
    """滞后在容忍范围内（1 个交易日 <= SHOUTU_SIGNAL_MAX_LAG_DAYS）⇒ 不抛错。

    ⚠️ **窗口必须从真实交易日 `2024-01-02` 起**，不能从 `2024-01-01` 起（元旦、非交易日）。
    本测试走 `shoutu_variant="V1"` 路径 ⇒ `run_portfolio_v2` 会取**真实**的
    `risk_weight_series(load_wide())`；若合成窗口的第一天落在真实权重序列之前
    （或不在其中），`reindex(...).ffill()` 在该日**无前值可填** ⇒ 权重 NaN ⇒ 该日
    `us_core` 为 NaN（**非 warmup**）⇒ 被 §7.1-4 的覆盖率守卫拦截
    （那与「陈旧检测」无关，是本测试**未意图**触发的另一条守卫）。
    从真实交易日（`2024-01-02`）起算即与该守卫正交，断言仍完整保留。
    """
    idx = pd.date_range("2024-01-02", periods=40, freq="B")
    fresh = pd.DataFrame({"date": [idx[-2]], "symbol": ["TQQQ"],
                          "score": [0.0], "price": [1.0]})
    monkeypatch.setattr(loader, "load_shoutu_history", lambda *a, **k: fresh)
    pipeline.run_portfolio_v2(write=False, us_features=_us(idx),
                              crypto_features=_cr(idx), shoutu_variant="V1")


def test_report_shoutu_prints_trigger_counts_for_keyed_extremes(capsys):
    """⚠️ 守卫：keyed extremes 打开时必须打印熔断/极恐触发天数（spec §8）。

    若这条失败 ⇒ 监控输出与 spec §8 脱节，keyed extremes 是否真触发无从判断。
    """
    pipeline.run_portfolio_v2(write=False, shoutu_keyed_extremes=True)
    out = capsys.readouterr().out
    assert "[shoutu]" in out
    assert "keyed_extremes=True" in out
    assert "熔断触发" in out
    assert "极恐触发" in out


def test_report_shoutu_prints_us_core_stats_for_variant(capsys):
    """⚠️ 守卫：变体打开时必须打印 `us_core` 与五档基准的对比（spec §8）。"""
    pipeline.run_portfolio_v2(write=False, shoutu_variant="V3")
    out = capsys.readouterr().out
    assert "[shoutu]" in out
    assert "variant=V3" in out
    assert "us_core 均值" in out
    assert "五档基准" in out


def test_shoutu_daily_cmd_is_ascii_only():
    """⚠️ cmd.exe 按 GBK 读 .cmd ⇒ 非 ASCII 字节会吞换行导致串行执行（2026-09-23 事故）。"""
    path = os.path.join(config.ROOT, "scripts", "shoutu_daily.cmd")
    with open(path, "rb") as f:
        raw = f.read()
    raw.decode("ascii")            # 非 ASCII ⇒ 直接抛 UnicodeDecodeError


def test_shoutu_daily_cmd_fetches_shoutu_history():
    """A2：定时任务必须定期抓守猪待兔历史（否则生产信号源停更）。"""
    path = os.path.join(config.ROOT, "scripts", "shoutu_daily.cmd")
    with open(path, "rb") as f:
        text = f.read().decode("ascii")
    assert "fetch_shoutu_history.py" in text


def test_shoutu_daily_sh_fetches_shoutu_history():
    """A2 的 **Mac 侧**对应守卫：Mac 定时任务也必须抓守猪待兔历史。

    ⚠️ **2026-09-28 发现的缺口**：`.cmd`（Windows）第 98 行会跑
    `fetch_shoutu_history.py`，但 `.sh`（Mac）**只跑 API 通道** ⇒ Mac 上
    `shoutu_history.csv`（A2 的**生产信号源**）**永不更新** ⇒ 超过
    `SHOUTU_SIGNAL_MAX_LAG_DAYS`（3 个交易日）后，一开开关 `run_portfolio_v2` 就抛错。
    （默认关 ⇒ 现状生产不受影响，但**能力在 Mac 上是断的**。）

    ⚠️ **与 `.cmd` 的关键差异 —— 这次调用必须是「可选」的**：
    `fetch_shoutu_history.py` 依赖 `bsk` + Chrome，而 **`bsk` 在 macOS 未实测**
    （文档自称「唯一阻塞项」）⇒ 必须先探测 `bsk` 是否可用，不可用就**跳过并记日志**，
    **不得**让它决定任务成败（主路径 `fetch_shoutu_api.py` 的 RC 才决定）。
    """
    path = os.path.join(config.ROOT, "scripts", "shoutu_daily.sh")
    text = open(path, encoding="utf-8").read()
    assert "fetch_shoutu_history.py" in text, "Mac 定时任务没有抓守猪待兔历史"
    assert "bsk" in text, "必须显式探测 bsk 可用性（macOS 未实测，不可用要跳过）"


def _capture_parser(monkeypatch):
    """跑一次 `cli.main`，在它即将解析参数时**截获**那个 parser 实例。

    `main()` 里的 parser 是**局部变量**，没有注入点，所以只能拦截
    `argparse.ArgumentParser.parse_args`（在 `parse_args` 内 raise 即可
    中止执行，parser 已经构造完毕）。"""
    import argparse

    from fg_system import cli

    cap = {}
    real = argparse.ArgumentParser.parse_args

    def spy(self, args=None, namespace=None):
        cap["parser"] = self
        raise SystemExit(0)

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", spy)
    try:
        with pytest.raises(SystemExit):
            cli.main(["backtest-v2"])
    finally:
        # **必须立刻复原**：下面的行为断言还要用真实 `parse_args`。
        monkeypatch.setattr(argparse.ArgumentParser, "parse_args", real)
    return cap["parser"]


def _subparser(parser, name):
    import argparse
    for a in parser._actions:
        if isinstance(a, argparse._SubParsersAction):
            return a.choices[name]
    raise AssertionError("未找到 subparser %r" % name)


def test_cli_shoutu_variant_choices_come_from_variants_table(monkeypatch):
    """⚠️ 守卫：CLI 的 `--shoutu-variant` 合法取值必须**单源**于 `VARIANTS`。

    若这条失败 ⇒ CLI 的 `choices` 被硬编码成了一份**独立清单**：将来新增变体
    （如 `V4`）时库层接受、CLI 却静默拒绝（argparse 报 invalid choice）——
    同一规则两套写法（第 12.26 条⑤）。

    **它为什么能真的抓住硬编码**：不比对字面量，而是往 `shoutu_variants.VARIANTS`
    里**临时注入一个假的 `V4`**，再断言真实 parser 的 choices **跟上了**这个注入。
    硬编码的清单绝不会随 `VARIANTS` 变化 ⇒ 必然失败；只有「choices 取自
    `VARIANTS`」才能通过。这比「读源码断言某行不含 'V1'」更强：后者会因
    换行/别名/重构误报或漏报，前者直接验证**行为**。
    """
    from fg_system import shoutu_variants

    monkeypatch.setitem(shoutu_variants.VARIANTS, "V4",
                        {"label": "fake", "edges": [], "saturation": []})
    parser = _capture_parser(monkeypatch)
    action = [a for a in _subparser(parser, "backtest-v2")._actions
              if a.dest == "shoutu_variant"][0]

    assert action.choices is not None, "`--shoutu-variant` 丢了 choices 约束"
    assert sorted(action.choices) == sorted(shoutu_variants.VARIANTS), (
        "CLI 的 --shoutu-variant choices 与 shoutu_variants.VARIANTS 已脱节："
        "choices=%s VARIANTS=%s" % (sorted(action.choices),
                                    sorted(shoutu_variants.VARIANTS)))
    assert "V4" in action.choices, (
        "注入 VARIANTS 的新键未被 CLI 接受 ⇒ choices 是硬编码的独立清单")

    # 真行为验证：每个 VARIANTS 键都被 argparse 接受，未知键被拒绝。
    sub = _subparser(parser, "backtest-v2")
    for v in shoutu_variants.VARIANTS:
        ns = sub.parse_args(["--shoutu-variant", v])
        assert ns.shoutu_variant == v
    with pytest.raises(SystemExit):
        sub.parse_args(["--shoutu-variant", "V9"])
