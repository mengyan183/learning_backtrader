# -*- coding: utf-8 -*-
"""富途连接健康：端口预检 / 状态落盘 / 简报可见（2026-10-29）。

【背景】2026-10-28 每日链卡死在 futu SDK 的**无界重连**里 ✗ ——
`/tmp/fg_daily.log` 从 05:30 一直刷到 08:27 的 `_init_connect_sync: init connect fail`，
链是 `;` 串行 ⇒ 后面的 `invest_research.py`（投研简报）根本没轮到 ✗
⇒ 用户连续两天收不到简报，且**没有任何提示** ✗。

三道防线（用户裁定：「连接有问题就在简报里体现，不要卡死」✓）：
1. `preflight()` 先用 2 秒 socket 探端口 ⇒ 连不上**立刻退出**，绝不进 SDK ✓
2. `guard()` `signal.alarm` 硬超时 ⇒ 到点 `os._exit(0)`，不陪 SDK 线程耗 ✓
3. `write_status()` 落盘 ⇒ 简报里明说「富途不可用」✓
"""
import importlib.util
import os
import socket
import sys

from fg_system import config


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(config.ROOT, rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _futu_health():
    return _load("futu_health", "scripts/futu_health.py")


def test_preflight_fails_when_opend_down(monkeypatch):
    """OpenD 没开 ⇒ 必须返回 False ✓（调用方据此**跳过 SDK** ✗）。"""
    fh = _futu_health()
    # 绑一个端口再关掉 ⇒ 保证没人监听（比猜端口稳 ✓）
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    monkeypatch.setattr(fh, "OPEND_PORT", port)
    ok, why = fh.preflight(timeout=0.5)
    assert ok is False
    assert "连不上" in why


def test_status_roundtrip(tmp_path, monkeypatch):
    fh = _futu_health()
    monkeypatch.setattr(fh, "STATUS_PATH", str(tmp_path / "futu.json"))
    fh.write_status(False, "OpenD 连不上", "sync_positions")
    st = fh.read_status()
    assert st["ok"] is False and "连不上" in st["reason"]
    assert st["step"] == "sync_positions" and st["at"]
    fh.write_status(True, "ok", "x")
    assert fh.read_status()["ok"] is True


def test_read_status_missing_returns_none(tmp_path, monkeypatch):
    fh = _futu_health()
    monkeypatch.setattr(fh, "STATUS_PATH", str(tmp_path / "nope.json"))
    assert fh.read_status() is None


def test_brief_shows_futu_unavailable(monkeypatch, tmp_path):
    """简报必须**明说**富途不可用 ✓ —— 不能安静地少一段 ✗。"""
    ir = _load("invest_research", "scripts/invest_research.py")
    fh = _futu_health()
    monkeypatch.setattr(fh, "STATUS_PATH", str(tmp_path / "f.json"))
    fh.write_status(False, "OpenD 127.0.0.1:11111 连不上", "sync_positions")
    monkeypatch.setitem(sys.modules, "futu_health", fh)

    txt = ir._futu_health_block()

    assert "不可用" in txt, "富途挂了但简报没提 ✗"
    assert "连不上" in txt, "简报必须带上**具体原因** ✗"
    assert "上一交易日" in txt, "要提示数据可能陈旧 ✗"


def test_health_is_one_line_when_everything_ok(tmp_path, monkeypatch):
    """全都正常时压成**一行** ✓ —— 每天铺三行「正常」纯属占版面 ✗。

    2026-10-29 扩展：健康块从「只报富途」扩到「富途 + AI 三阶段 + 六因子」，
    正常态必须仍然只有一行（否则等于把噪音搬到了顶部 ✗）。
    """
    ir = _load("invest_research", "scripts/invest_research.py")
    fh = _futu_health()
    monkeypatch.setattr(fh, "STATUS_PATH", str(tmp_path / "nope.json"))
    monkeypatch.setitem(sys.modules, "futu_health", fh)
    monkeypatch.setattr(ir, "_missing_factor_count", lambda: 0)

    txt = ir._data_health_block({}, "s", "a", "j")

    assert txt == "全部正常 ✓（富途 OpenD / AI 三阶段 / 六因子）", txt


def test_health_treats_judge_error_text_as_missing(monkeypatch):
    """裁判返回**失败文案**时也必须算「缺裁判」✓。

    2026-10-29 实测漏报 ✗：简报正文写着「裁判调用失败（NIM）…」，
    而健康块只报「缺 情绪、归因」✗ —— 因为 `stage_judge` 失败时返回的是
    **字符串**（保留原因给用户看），健康块把非空字符串当成了「可用」✗。
    """
    ir = _load("invest_research", "scripts/invest_research.py")
    monkeypatch.setitem(sys.modules, "futu_health",
                        type("X", (), {"read_status": staticmethod(lambda: None)}))
    monkeypatch.setattr(ir, "_missing_factor_count", lambda: 0)

    txt = ir._data_health_block(
        {}, "有情绪", "有归因",
        "裁判调用失败（NIM）：调用失败(1次): The read operation timed out，本次以归因结论为准。")

    assert "缺 裁判" in txt, txt
    assert "缺 情绪" not in txt, "情绪明明有，别误报 ✗"


def test_health_lists_missing_stages(monkeypatch):
    """AI 阶段缺失必须**在顶部点名** ✓（2026-10-29 实测：NIM 超时那行却只写「富途正常」✗）。"""
    ir = _load("invest_research", "scripts/invest_research.py")
    monkeypatch.setitem(sys.modules, "futu_health",
                        type("X", (), {"read_status": staticmethod(lambda: None)}))
    monkeypatch.setattr(ir, "_missing_factor_count", lambda: 2)

    txt = ir._data_health_block({}, "s", None, None)

    assert "缺 归因、裁判" in txt, txt
    assert "六因子：**缺 2 个**" in txt
