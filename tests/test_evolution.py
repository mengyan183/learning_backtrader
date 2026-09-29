# -*- coding: utf-8 -*-
"""进化就绪度测试（第 14 条）。

本模块是**只读**的：它报告"还差多少"，不改任何参数。
故测试的重点之一是**证明它真的什么都没改**（第 14.1 条的承诺）。
"""
import os

import pandas as pd
import pytest

from fg_system import config, evolution
from fg_system.data import loader


def _wide(days_by_symbol):
    """构造守猪待兔宽表：{symbol: 天数}，值用 0 填充（内容不影响就绪度）。"""
    n = max(days_by_symbol.values())
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    data = {}
    for s, d in days_by_symbol.items():
        col = pd.Series(float("nan"), index=idx)
        col.iloc[:d] = 0.0
        data[s] = col
    return pd.DataFrame(data, index=idx)


def test_insufficient_history_reports_fixed_mode():
    """只有 2 天数据 ⇒ **实际生效**的是 fixed（即使配置是 percentile）。"""
    t = evolution.shoutu_readiness(_wide({"CONL": 2}))
    assert t.loc["CONL", "days"] == 2
    assert t.loc["CONL", "mode"] == "fixed"
    assert t.loc["CONL", "remaining"] == config.RANK_WINDOW - 2


def test_enough_history_reports_percentile_mode():
    """满 `RANK_WINDOW` 天 ⇒ 实际生效 percentile。"""
    t = evolution.shoutu_readiness(_wide({"CONL": config.RANK_WINDOW}))
    assert t.loc["CONL", "mode"] == "percentile"
    assert t.loc["CONL", "remaining"] == 0


def test_mode_is_actual_not_configured():
    """**守卫**：`mode` 必须反映**实际生效**口径，不是配置值。

    配置是 percentile，但数据只有 2 天 ⇒ 实际是 fixed。
    把两者混为一谈，会让人误以为分位数已经在用。
    """
    assert config.SHOUTU_INDEX_MODE == "percentile"     # 配置
    t = evolution.shoutu_readiness(_wide({"CONL": 2}))
    assert t.loc["CONL", "mode"] == "fixed"             # 实际


def test_missing_symbol_reports_zero_days():
    """完全没录入的标的 ⇒ 0 天、fixed、无区间（不得抛异常）。

    **注意用 `pd.isna` 而不是 `is None`**：`last` 是 datetime 列，
    缺值会被 pandas 强制转成 `NaT`，`is None` 拦不住。
    """
    t = evolution.shoutu_readiness(_wide({"CONL": 5}))
    assert t.loc["TQQQ", "days"] == 0
    assert t.loc["TQQQ", "mode"] == "fixed"
    assert pd.isna(t.loc["TQQQ", "last"])


def test_empty_wide_is_handled():
    """空表不得抛异常（系统其余部分不依赖本模块）。"""
    t = evolution.shoutu_readiness(pd.DataFrame())
    assert (t["days"] == 0).all()
    assert (t["mode"] == "fixed").all()


def test_next_upgrade_picks_earliest():
    """`next_upgrade` 取**最早**会升级的标的（还差天数最少）。

    **必须限定 symbols**：`readiness` 默认遍历**全部**白名单标的，
    未录入的标的还差 756 天，会掩盖被测标的的排序。
    """
    r = evolution.readiness(_wide({"CONL": 10, "TQQQ": 5}))
    assert r["next_upgrade"][0] == "CONL"          # 10 天 > 5 天
    assert r["next_upgrade"][1] == config.RANK_WINDOW - 10


def test_next_upgrade_none_when_all_ready():
    """全部标的数据都够 ⇒ 无待升级项。

    必须只传一个标的：默认白名单里的其他标的还没录入，
    它们仍会产出 `remaining > 0`，使 `next_upgrade` 非空。
    """
    t = evolution.shoutu_readiness(_wide({"CONL": config.RANK_WINDOW}),
                                   symbols=["CONL"])
    assert (t["remaining"] == 0).all()
    r = evolution.readiness(_wide({"CONL": config.RANK_WINDOW}))
    assert r["next_upgrade"] is not None           # 其他标的仍未录入
    assert r["next_upgrade"][0] != "CONL"          # 但 CONL 已就绪


def test_readiness_does_not_mutate_config():
    """**守卫**：本模块**不得**修改任何配置（第 14.1 条的承诺）。

    "自动发现问题可以、自动改变参数不行" —— 若本模块改了 config，
    那条边界就被悄悄打破了，而且是在最不该的地方（一个只读报告里）。
    """
    keys = [k for k in dir(config) if k.isupper()]
    before = {k: getattr(config, k) for k in keys}
    evolution.readiness(_wide({"CONL": 2}))
    after = {k: getattr(config, k) for k in keys}
    assert before == after


def test_cmd_scripts_are_ascii_only():
    """**守卫**：`scripts/*.cmd` 必须**纯 ASCII**（2026-09-23 实测踩坑）。

    `cmd.exe` 读取 `.bat/.cmd` 用的是**系统代码页（本机 GBK）**，不是 UTF-8。
    非 ASCII 字节会被错位解码；GBK 是**双字节**编码，错位时会**吃掉换行符**，
    使注释与下一行**合并**并被当成命令执行：

        '...' 不是内部或外部命令，也不是可运行的程序或批处理文件。

    纯 ASCII 文件在 GBK 与 ASCII 下解码**完全一致** ⇒ 不可能再错位。
    中文说明放在 `docs/trading-discipline.md` 第 14.5 条。
    """
    import glob
    files = sorted(glob.glob(os.path.join(config.ROOT, "scripts", "*.cmd")))
    assert files, "未找到任何 .cmd 文件（路径约定变了？）"
    for path in files:
        raw = open(path, "rb").read()
        bad = [b for b in raw if b > 127]
        assert not bad, "%s 含非 ASCII 字节 %s" % (
            os.path.basename(path), bad[:5])


def test_sh_scripts_use_lf_only():
    """**守卫**：`scripts/*.sh` 必须**纯 LF**换行（2026-09-23，macOS 迁移）。

    这是上面 `.cmd` 守卫的**镜像**，防的是同一类问题的另一面：

    Windows 上编辑过的 `.sh` 会带 CRLF。macOS / Linux 的 shebang 解析器
    读到 `#!/usr/bin/env bash\\r` 时，会把 `\\r` 当成解释器路径的一部分，
    报：

        bad interpreter: /usr/bin/env bash^M: no such file or directory

    这个错误**不会指向真正的原因**（换行符），排查成本很高。
    `\\r` 在任何 POSIX shell 脚本里都没有正当用途，故一律禁止。

    注意：本守卫**不检查 .sh 的 ASCII 性** —— 与 `.cmd` 相反，`.sh` 在
    macOS/Linux 下由 shell 按 UTF-8 读取，中文注释完全安全。
    """
    import glob
    files = sorted(glob.glob(os.path.join(config.ROOT, "scripts", "*.sh")))
    assert files, "未找到任何 .sh 文件（路径约定变了？）"
    for path in files:
        raw = open(path, "rb").read()
        assert b"\r" not in raw, (
            "%s 含 CR 字节（CRLF 换行）。macOS 上会报 "
            "'bad interpreter: ...^M'，请改为 LF。" % os.path.basename(path))


def test_cli_evolution_runs(capsys, monkeypatch, tmp_path):
    """`evolution` 命令必须能跑通并给出关键结论。"""
    from fg_system import cli
    monkeypatch.setattr(loader, "load_shoutu_fng",
                        lambda path=None: _wide({"CONL": 2, "TQQQ": 1}))
    cli.main(["evolution"])
    out = capsys.readouterr().out
    assert "进化就绪度" in out
    assert "下一次" in out and "自动" in out
    assert "只报告" in out          # 必须显式声明边界
    assert "fixed" in out and "percentile" in out
