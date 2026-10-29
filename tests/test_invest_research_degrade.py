# -*- coding: utf-8 -*-
"""`invest_research.py` 的**降级契约**（2026-10-29）。

【背景】2026-10-27/28 连续两天收不到「多智能体投研简报」✗。
根因之一：`main()` 里

    if not (sentiment and attribution and judge):
        return                       # 整条简报扣下不发 ✗

—— 任一 AI 阶段缺失就**整条不发** ✗，而模块 docstring 写的是「任一阶段失败自动降级」，
`build_brief_sections()` 也早就给缺失阶段写好了「（跳过：X 不可用）」占位 ✓。
守卫把已有的降级能力废掉了 ✗，而且只 print 一行到日志 ⇒ 用户完全无感 ✗。
"""
import importlib.util
import os
import sys
import types

from fg_system import config

_SPEC = os.path.join(config.ROOT, "scripts", "invest_research.py")


def _load():
    spec = importlib.util.spec_from_file_location("invest_research", _SPEC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_date_label_shows_both_dates_when_out_of_sync():
    """**守卫**：指数日与持仓日不一致时**两个都写** ✓（2026-10-29 裁定方案 ②）。

    原来只写 `snap["date"]`（持仓快照日）✗ —— 持仓同步失败那天，标题显示 10-26
    而正文指数是 10-27 的 ✗，`verify_brief` 报「数据不同步」✗。
    """
    m = _load()
    assert m._date_label({"date": "2026-10-26",
                          "index_date": "2026-10-27"}) == \
        "2026-10-27（指数）/ 10-26（持仓）"
    # 一致时只写一个 ✓（别啰嗦）
    assert m._date_label({"date": "2026-10-27",
                          "index_date": "2026-10-27"}) == "2026-10-27"
    # 缺 index_date（老快照/异常）⇒ 退回持仓日 ✓ 不能崩 ✗
    assert m._date_label({"date": "2026-10-26"}) == "2026-10-26"


def test_title_first_date_is_index_date():
    """标题后**第一个**日期必须是指数日 ✓ —— `verify_brief` 就取它做比对 ✓。

    取错的话会拿持仓日去比 features 尾行 ⇒ 又报「数据不同步」✗。
    """
    import re

    m = _load()
    label = m._date_label({"date": "2026-10-26", "index_date": "2026-10-27"})
    got = re.search(r"多智能体投研简报\s*(20\d{2}-\d{2}-\d{2})",
                    "# 多智能体投研简报 " + label).group(1)
    assert got == "2026-10-27", "verify_brief 会取到持仓日 ⇒ 又报数据不同步 ✗"


def test_stages_run_concurrently(monkeypatch):
    """三个**互不依赖**的阶段必须并发 ✓。

    2026-10-29 实测：串行跑一次简报 **478 秒** ✗ —— 新闻 / Hermes / NIM 是三个
    2~3 分钟的 LLM 调用，排队等 ✗。并发后只等最慢那个 ✓。

    ⚠️ `stage_judge` **不在**并发之列 ✗ —— 它的入参就是 sentiment 与 attribution
    的产出，必须等它们回来 ✓。
    """
    import threading
    import time

    m = _load()
    peak = {"now": 0, "max": 0}
    lock = threading.Lock()

    def slow(tag):
        with lock:
            peak["now"] += 1
            peak["max"] = max(peak["max"], peak["now"])
        time.sleep(0.25)
        with lock:
            peak["now"] -= 1
        return tag

    monkeypatch.setattr(m, "fetch_news", lambda snap: slow("news"))
    monkeypatch.setattr(m, "_read_hermes_key", lambda: "k")
    monkeypatch.setattr(m, "_read_nim_key", lambda: "k")
    monkeypatch.setattr(m, "stage_sentiment", lambda k, snap: slow("sent"))
    monkeypatch.setattr(m, "stage_attribution",
                        lambda k, snap, kb=None: slow("attr"))

    t0 = time.time()
    news, sent, attr = m._run_stages({"date": "2026-10-29"})
    took = time.time() - t0

    assert (news, sent, attr) == ("news", "sent", "attr")
    assert peak["max"] == 3, "三个阶段没有真正并发（峰值 %d）✗" % peak["max"]
    assert took < 0.6, "看起来还是串行（%.2fs）✗" % took


def test_stage_progress_is_logged(tmp_path, monkeypatch):
    """阶段级进度必须**落盘** ✓。

    2026-10-29 实测：队列动作 600 秒超时，`subprocess` 杀掉进程 ⇒ stdout 全丢 ✗
    ⇒ 只知道「超时」，不知道卡在新闻还是某个 LLM 阶段 ✗。
    """
    m = _load()
    monkeypatch.setattr(m, "REPO", str(tmp_path))
    monkeypatch.setattr(m, "fetch_news", lambda snap: "n")
    monkeypatch.setattr(m, "_read_hermes_key", lambda: "k")
    monkeypatch.setattr(m, "_read_nim_key", lambda: "k")
    monkeypatch.setattr(m, "stage_sentiment", lambda k, snap: "s")
    monkeypatch.setattr(m, "stage_attribution", lambda k, snap, kb=None: "a")

    m._run_stages({"date": "2026-10-29"})

    txt = (tmp_path / "Data" / "health" / "invest_stages.log").read_text(
        encoding="utf-8")
    assert txt.count("start") == 3, "三个阶段都该有 start 记录 ✗"
    assert "done  新闻抓取" in txt
    assert "done  Hermes 阶段" in txt


def test_one_stage_failure_does_not_kill_others(monkeypatch):
    """一个阶段挂了只影响它自己 ✓ —— 与串行版的降级语义一致 ✓。"""
    m = _load()

    def boom(*a, **k):
        raise RuntimeError("hermes down")

    monkeypatch.setattr(m, "fetch_news", lambda snap: "news")
    monkeypatch.setattr(m, "_read_hermes_key", lambda: "k")
    monkeypatch.setattr(m, "_read_nim_key", lambda: "k")
    monkeypatch.setattr(m, "stage_sentiment", boom)
    monkeypatch.setattr(m, "stage_attribution", lambda *a, **k: "attr")

    news, sent, attr = m._run_stages({"date": "2026-10-29"})
    assert news == "news" and attr == "attr", "一个阶段挂了连累了别的 ✗"
    assert sent is None, "挂掉的阶段应为 None（下游写「跳过：X 不可用」）✗"


def test_brief_is_pushed_even_when_a_stage_fails(monkeypatch, tmp_path):
    """**守卫**：任一 AI 阶段缺失也必须推送 ✓（用户要的是「每天收到」✗）。"""
    m = _load()
    (tmp_path / "Data").mkdir()
    sent = []

    # 三个内部依赖都是 `main()` 里现 import 的 ⇒ 塞假模块，别碰真实文件
    for name, attrs in (("verify_brief", {"verify_and_report": lambda b, s: False}),
                        ("decision_log", {"append": lambda s, j: None}),
                        ("archive_briefs", {"archive": lambda keep_days=7: None})):
        fake = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(fake, k, v)
        monkeypatch.setitem(sys.modules, name, fake)

    monkeypatch.setattr(m, "REPO", tmp_path)
    monkeypatch.setattr(m, "build_snapshot", lambda: {"date": "2026-10-29"})
    monkeypatch.setattr(m, "fetch_news", lambda snap: None)
    monkeypatch.setattr(m, "stage_sentiment", lambda *a: None)      # ← 情绪阶段挂掉
    monkeypatch.setattr(m, "stage_attribution", lambda *a: "归因")
    monkeypatch.setattr(m, "stage_judge", lambda *a: "裁判")
    monkeypatch.setattr(m, "build_brief", lambda *a: "# 简报\n")
    monkeypatch.setattr(m, "build_brief_sections", lambda *a: [("t", "b")])
    monkeypatch.setattr(m, "push_feishu_rich",
                        lambda t, s: sent.append(t) or (True, "ok"))
    monkeypatch.setattr(sys, "argv", ["invest_research.py"])

    m.main()

    assert sent, "某阶段缺失时又把整条简报扣下了 ✗（用户会再次静默收不到）"
    assert "2026-10-29" in sent[0], "推送标题里必须带简报日期 ✗"
