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
