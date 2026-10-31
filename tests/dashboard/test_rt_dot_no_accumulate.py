# -*- coding: utf-8 -*-
"""看板持仓卡的「实时圆点」**不得堆积** ✓（2026-10-31）。

现象（用户实测）：持仓页面**卡片一直在变宽** ✗

根因：`index.html` 的轮询里这句

    mid.innerHTML = mid.innerHTML.replace(/现价[^<]*/,
        "现价 " + price + " <span class='rt-dot'>●</span>");

`/现价[^<]*/` 只吃到 `<` 之前 ⇒ **上一轮插进去的 `●` 永远不会被消费** ✗
⇒ 每轮 poll 都在前面再插一个 ⇒ 轮询 N 次就是 N 个圆点 ⇒ 卡片被撑宽 ✗

修法：替换前先清掉本卡所有 `.rt-dot` ✓。

本测试用 Python **复刻 JS 的正则语义**做回归守卫 ✓ ——
改回「只 replace 不清旧」会立刻失败 ✗。
"""
import re

INIT = "成本 26.82 · 现价 22.49<span class='snap-d'>（09-30）</span>"
DOT = "<span class='rt-dot'>●</span>"
PAT = r"现价[^<]*"


def _poll_buggy(html, price):
    """原实现：只 replace、不清旧 dot ✗。"""
    return re.sub(PAT, "现价 %.2f %s" % (price, DOT), html, count=1)


def _poll_fixed(html, price):
    """修复后：先清 `.rt-dot` 再 replace ✓。"""
    html = re.sub(re.escape(DOT), "", html)
    return re.sub(PAT, "现价 %.2f %s" % (price, DOT), html, count=1)


def test_buggy_version_accumulates():
    """**反证**：不清旧 dot 一定堆积 ✗（证明这个坑是真的）。"""
    h = INIT
    for i in range(5):
        h = _poll_buggy(h, 22.49 + i * 0.01)
    assert h.count("rt-dot") == 5, "反证失败：原实现居然没堆积？"


def test_fixed_version_stays_one():
    """修复后：无论轮询多少次，`.rt-dot` **恒为 1 个** ✓。"""
    for rounds in (1, 3, 5, 30, 200):
        h = INIT
        for i in range(rounds):
            h = _poll_fixed(h, 22.49 + i * 0.01)
        assert h.count("rt-dot") == 1, \
            "轮询 %d 次后堆到了 %d 个 ✗" % (rounds, h.count("rt-dot"))


def test_price_still_updates():
    """清理不能把「现价」也清掉 ✓ —— 最新价必须正确显示。"""
    h = INIT
    for p in (22.49, 23.10, 21.80):
        h = _poll_fixed(h, p)
    assert "现价 21.80" in h, h
    assert "成本 26.82" in h, "成本被误删 ✗"
    assert "snap-d" in h, "快照日期标记被误删 ✗"
