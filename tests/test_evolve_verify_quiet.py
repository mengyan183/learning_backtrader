# -*- coding: utf-8 -*-
"""`evolve_verify.py --quiet`：只播**状态变化**（2026-10-29）。

【背景】用户实测日报 9 行里只有 3 行是当天新结论 ✗：
- `[H-005] 跳过（falsified，不再自动复检）` —— 状态永不再变，纯噪音 ✗
- `[H-006] verifying：样本不足（21/60）` —— 计数没跨阈值，每天一字不差 ✗
- `[H-001] adopted（未发现反证）…` —— 状态没翻转，没有新信息 ✗

`--quiet` 把这三类各压成一行 ✓，**写表与 memory 日志不受影响** ✓。
"""
import importlib.util
import os

from fg_system import config

_SPEC = os.path.join(config.ROOT, "scripts", "evolve_verify.py")


def _load():
    spec = importlib.util.spec_from_file_location("evolve_verify", _SPEC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _stub(monkeypatch, ev, prev):
    """把 main() 的外部依赖全打成桩：数据新鲜、不写表、不写 memory。"""
    monkeypatch.setattr(ev, "_data_is_stale", lambda *a, **k: (False, ""))
    monkeypatch.setattr(ev, "current_status", lambda: dict(prev))
    monkeypatch.setattr(ev, "CHECKS", [
        lambda: {"id": "H-001", "status": "adopted", "evidence": "同前", "note": ""},
        lambda: {"id": "H-002", "status": "verifying", "evidence": "样本不足", "note": ""},
        lambda: {"id": "H-003", "status": "falsified", "evidence": "翻转为伪", "note": ""},
        lambda: {"id": "H-004", "status": "adopted", "evidence": "不该复检", "note": ""},
    ])
    monkeypatch.setattr(ev, "update_hypotheses", lambda rs: None)
    monkeypatch.setattr(ev, "append_memory", lambda rs: None)
    monkeypatch.setattr(ev, "check_table_structure", lambda: 0)


PREV = {"H-001": "adopted", "H-002": "verifying",
        "H-003": "verifying", "H-004": "falsified"}


def test_quiet_prints_only_status_changes(monkeypatch, capsys):
    ev = _load()
    _stub(monkeypatch, ev, PREV)
    ev.main(["--quiet"])
    out = capsys.readouterr().out
    assert "[H-003] falsified" in out, "状态翻转必须播 ✗"
    assert "[H-001]" not in out, "adopted 未变还重播一遍证据 ✗"
    assert "[H-006]" not in out
    # 三类噪音各折叠成一行 ✓
    assert "[跳过] 1 条" in out and "H-004" in out
    assert "[样本不足] 1 条" in out and "H-002" in out
    assert "[维持] 1 条" in out and "H-001" in out


def test_daily_timer_runs_quiet():
    """每日 06:10 的定时器必须带 `--quiet` ✓ —— **副本和安装脚本都要改** ✗。

    2026-10-29：只改 `scripts/*.plist` 副本**不生效** ✗ —— 真身是
    `~/Library/LaunchAgents/*.plist`，由 `install_evolve_tasks.sh` 生成 ✓。
    只改副本的话，下次重装又会把旧参数写回去 ✗。
    """
    root = config.ROOT
    with open(os.path.join(root, "scripts",
                           "com.xingguo.fg-evolve-verify.plist"),
              encoding="utf-8") as fh:
        assert 'evolve_verify.py" --quiet' in fh.read(), "plist 副本没带 --quiet ✗"
    with open(os.path.join(root, "scripts", "install_evolve_tasks.sh"),
              encoding="utf-8") as fh:
        assert 'evolve_verify.py evolve_verify.log "--quiet"' in fh.read(), \
            "安装脚本没传 --quiet ⇒ 重新注册会把旧参数写回 ✗"


def test_without_quiet_everything_still_prints(monkeypatch, capsys):
    """默认行为不许变 ✓ —— 现有调用方（每日链）没有传 `--quiet`。"""
    ev = _load()
    _stub(monkeypatch, ev, PREV)
    ev.main([])
    out = capsys.readouterr().out
    for hid in ("H-001", "H-002", "H-003"):
        assert "[%s]" % hid in out, "%s 在非 quiet 模式下被吞了 ✗" % hid
    assert "跳过（当前状态 falsified" in out
    assert "[维持]" not in out, "非 quiet 模式不该出现折叠行 ✗"
