# -*- coding: utf-8 -*-
"""`scripts/bootstrap_data.py` 的**传输结论文案**（2026-09-28）。

【为什么必须测】旧文案**硬编码**了：

    合计约 %s —— **远低于飞书的 100 KB 上限，一个文件就能传**。

而 2026-09-28 实测：`Data/raw/shoutu_history.csv` 已长到 **98.5 KB** ⇒ 不可再生
合计 **102.4 KB**，**已超限** ⇒ 照那句话做会**直接被飞书拦**（而且是发的时候才发现）。

⇒ 结论必须由**实算**得出，**不得写死**。本文件把这条钉住。
"""
import importlib.util
import os

from fg_system import config

_SPEC = os.path.join(config.ROOT, "scripts", "bootstrap_data.py")


def _load():
    spec = importlib.util.spec_from_file_location("bootstrap_data", _SPEC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load()


def test_verdict_says_direct_send_when_under_limit():
    """未超限 ⇒ 明说可以直发（保留原来的便利）。"""
    assert "直接发" in mod._transfer_verdict(50 * 1024)


def test_verdict_points_to_chunked_keep_bundle_when_over_limit():
    """⚠️ 超限时必须指向**分片通道**，且**不得**再出现「远低于」这类写死的判断。"""
    out = mod._transfer_verdict(mod.FEISHU_SINGLE_FILE_LIMIT + 1)
    assert "分片" in out and "keep" in out, "超限时必须指向 keep 包分片"
    assert "feishu_send.py" in out, "应给出可直接照跑的命令"
    assert "远低于" not in out, "不得再出现写死的「远低于」"


def test_limit_leaves_margin_below_the_measured_hard_cap():
    """判据必须**留余量**：实测 90 KB 不过、10 KB 过 ⇒ 上限不得 ≥ 100 KB。"""
    assert mod.FEISHU_SINGLE_FILE_LIMIT <= 90 * 1024


def test_current_irreplaceable_total_is_actually_over_the_limit():
    """**现状快照**：不可再生合计（含 98.5 KB 的 shoutu_history.csv）确实已超限。

    ⚠️ 这条不是在"断言 bug"，而是**记录事实** —— 它保证 `_transfer_verdict` 的
    超限分支在真实数据下**真的会被走到**（否则那句文案等于没测）。
    若哪天文件变小了（如 history 被裁短），本用例会失败并提醒你更新预期。
    """
    total = 0
    for rel, _why in mod.IRREPLACEABLE:
        p = os.path.join(config.ROOT, rel)
        if os.path.isfile(p):
            total += os.path.getsize(p)
    assert total > mod.FEISHU_SINGLE_FILE_LIMIT, (
        "不可再生合计 %d B 已不再超限 —— 请复核本文件的预期" % total)
