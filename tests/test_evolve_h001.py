# -*- coding: utf-8 -*-
"""WT-08 `scripts/evolve_h001.py` 测试。

**不读真实 Data/**：用 monkeypatch 把 POS_CSV / ACC_CSV / HYP / MEM_DIR
指到 tmp_path；只测纯函数与状态机分支。
"""
import importlib.util
import os

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "evolve_h001.py")


def _load():
    spec = importlib.util.spec_from_file_location("evolve_h001", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


h1 = _load()


def _write_pos(tmp_path, rows):
    """rows: (date, symbol, market_value)。"""
    path = tmp_path / "positions.csv"
    header = "date,symbol,market_value\n"
    body = "".join("%s,%s,%s\n" % r for r in rows)
    path.write_text(header + body, encoding="utf-8")
    return str(path)


def _write_acc(tmp_path, rows):
    """rows: (date, account, net_value)。"""
    path = tmp_path / "accounts.csv"
    header = "date,account,net_value\n"
    body = "".join("%s,%s,%s\n" % r for r in rows)
    path.write_text(header + body, encoding="utf-8")
    return str(path)


@pytest.fixture
def patched(monkeypatch, tmp_path):
    monkeypatch.setattr(h1, "POS_CSV", str(tmp_path / "positions.csv"))
    monkeypatch.setattr(h1, "ACC_CSV", str(tmp_path / "accounts.csv"))
    monkeypatch.setattr(h1, "HYP", str(tmp_path / "hypotheses.md"))
    monkeypatch.setattr(h1, "MEM_DIR", str(tmp_path / "memory"))
    return tmp_path


# ------------------------------------------------------------------ 纯函数
def test_pearson_insufficient_points_returns_zero():
    assert h1.pearson([1.0], [1.0]) == 0.0
    assert h1.pearson([], []) == 0.0


def test_pearson_perfect_positive_and_negative():
    assert h1.pearson([1.0, 2.0, 3.0], [2.0, 4.0, 6.0]) == pytest.approx(1.0)
    assert h1.pearson([1.0, 2.0, 3.0], [6.0, 4.0, 2.0]) == pytest.approx(-1.0)


def test_pearson_zero_variance_returns_zero():
    # y 无方差 ⇒ 分母 0 ⇒ 返回 0.0（不抛异常）
    assert h1.pearson([1.0, 2.0, 3.0], [5.0, 5.0, 5.0]) == 0.0


# ------------------------------------------------------------------ load_series
def test_load_series_only_watch_symbols_and_stock_account(patched):
    _write_pos(patched, [
        ("2026-01-01", "AXTX", 1000),
        ("2026-01-01", "OTHER", 999),       # 非 WATCH → 不计
        ("2026-01-01", "CRCG", 500),
    ])
    _write_acc(patched, [
        ("2026-01-01", "stock", 2000),
        ("2026-01-01", "crypto", 8888),     # 非 stock → 不计
    ])
    dates, mv, nv = h1.load_series()
    assert dates == ["2026-01-01"]
    assert mv == [1500.0]                    # 1000 + 500
    assert nv == [2000.0]


def test_load_series_intersects_dates(patched):
    """净值缺失的日期被三者**同时**剔除（同源同长度）。

    口径：先取 positions 与 accounts 的**日期交集**，再各自映射。
    2026-10-10 修复前 mv 先于交集构建 ⇒ mv 比 nv 长 ⇒ `zip(dmv, dnv)` 错配日期。
    """
    _write_pos(patched, [("2026-01-01", "AXTX", 100),
                         ("2026-01-02", "AXTX", 110)])
    _write_acc(patched, [("2026-01-02", "stock", 1000)])   # 仅 02 有净值
    dates, mv, nv = h1.load_series()
    assert dates == ["2026-01-02"]           # 交集：仅 02
    assert nv == [1000.0]
    assert mv == [110.0]                     # 与 dates/nv 同源同长度
    assert len(dates) == len(mv) == len(nv)


# ------------------------------------------------------------------ main 状态机
def test_main_verifying_when_few_observations(patched, capsys):
    """观察点 < MIN_OBS ⇒ 仍在 verifying，返回 0。"""
    n = h1.MIN_OBS - 1
    _write_pos(patched, [("2026-01-%02d" % d, "AXTX", 100 + d)
                         for d in range(1, n + 1)])
    _write_acc(patched, [("2026-01-%02d" % d, "stock", 1000 + d)
                         for d in range(1, n + 1)])
    rc = h1.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "仍在 verifying" in out
    assert "观察点" in out


def test_decision_logic_falsify_on_rebound(patched):
    """判据 1：市值合计反弹 >= 10% ⇒ cond1 为真（纯计算，不写文件）。

    只验判据数学。写回分支另见 test_update_hypotheses_writes_back_utf8 ——
    2026-10-10 已修 `open(HYP)` 缺 encoding 的缺陷（Windows GBK 会崩），
    故写回现在可测。
    """
    n = h1.MIN_OBS
    _write_pos(patched, [("2026-01-%02d" % d, "AXTX",
                          100.0 + (30.0 * (d - 1) / (n - 1)))
                         for d in range(1, n + 1)])
    _write_acc(patched, [("2026-01-%02d" % d, "stock", 1000 + d)
                         for d in range(1, n + 1)])
    _, mv, nv = h1.load_series()
    rebound = (mv[-1] - mv[0]) / mv[0]
    assert rebound >= h1.REBOUND_FALSIFY          # 30% >= 10% ⇒ 证伪条件成立


def test_decision_logic_rho_falsify_threshold(patched):
    """判据 2（2026-10-26 修正）：ρ ≤ 0.3 ⇒ cond2 成立（证伪）；市值持平时 ρ=0。

    原断言 `rho >= RHO_FALSIFY`（配 `RHO_FALSIFY=-0.3`）**编码的正是 bug 语义** ✗
    —— 该式几乎恒真 ⇒ 假说永不能成立 ✗。现改为 `rho <= 0.3` ✓。
    """
    n = h1.MIN_OBS
    _write_pos(patched, [("2026-01-%02d" % d, "AXTX", 100.0)
                         for d in range(1, n + 1)])
    _write_acc(patched, [("2026-01-%02d" % d, "stock", 1000 + d)
                         for d in range(1, n + 1)])
    _, mv, nv = h1.load_series()
    dmv = [b - a for a, b in zip(mv, mv[1:])]
    dnv = [b - a for a, b in zip(nv, nv[1:])]
    rho = h1.pearson(dmv, dnv)
    assert rho == pytest.approx(0.0)              # 市值无变动 ⇒ ρ=0
    assert rho <= h1.RHO_FALSIFY                  # 0 <= 0.3 ⇒ 相关性弱 ⇒ 证伪 ✓


# ------------------------------------------------------------------ stdout utf-8
def test_stdout_encoding_ok():
    """§6.2：本脚本用 csv/utf-8 读；此处确认脚本源码可 utf-8 读取。"""
    src = open(SCRIPT, encoding="utf-8").read()
    assert "def main(" in src


# ------------------------------------------------------------------ 写回分支
def test_update_hypotheses_writes_back_utf8(patched):
    """写回分支回归：含中文时不再因 Windows 默认 GBK 崩溃（2026-10-10 修复）。

    修复前 `open(HYP)` / `open(HYP, "w")` / `open(mem, "a")` 均无 encoding
    ⇒ 读含中文的 hypotheses.md 直接 `UnicodeDecodeError`，写回分支等于不可用。
    """
    hyp = patched / "hypotheses.md"
    hyp.write_text("| H-001 | 中文假说 | open | 中文备注 |\n", encoding="utf-8")
    (patched / "memory").mkdir(exist_ok=True)

    h1.update_hypotheses("adopted", "测试结论")

    text = hyp.read_text(encoding="utf-8")
    assert "| adopted |" in text
    assert "| open |" not in text
    assert list((patched / "memory").glob("*.md")), "memory 日志未写出"


# ---------------------------------------------------------------- 2026-10-26 回归
def test_rho_falsify_sign_is_correct():
    """🔴 判据 2 必须为「ρ ≤ 0.3 ⇒ 证伪」✓。

    历史 bug：`RHO_FALSIFY = -0.3` + `rho >= RHO_FALSIFY` ⇒ 该式**几乎恒真** ✗
    ⇒ H-001 永不能成立 ✗；且 ρ=0.844 的强正相关（本是**支持**证据）被判证伪 ✗。
    """
    assert h1.RHO_FALSIFY == 0.3
    src = open(SCRIPT, encoding="utf-8").read()
    assert "cond2 = rho <= RHO_FALSIFY" in src, "判据 2 方向被改回 ✗"
    assert not (0.844 <= h1.RHO_FALSIFY)   # 强正相关 ⇒ **不**证伪 ✓
    assert 0.0 <= h1.RHO_FALSIFY           # 无相关 ⇒ 证伪 ✓


def test_strip_cashflow_removes_deposits():
    """加仓不得被误读成「反弹」✗。"""
    dates = ["d1", "d2", "d3"]
    mv = [100.0, 200.0, 200.0]                    # d2 加仓 100
    inv = {"d1": 100.0, "d2": 200.0, "d3": 200.0}
    assert h1.strip_cashflow(mv, dates, inv) == [100.0, 100.0, 100.0]


def test_strip_cashflow_without_cost_columns_degrades():
    """没有 qty/cost ⇒ 退化为原样 ✓，不报错。"""
    assert h1.strip_cashflow([1.0, 2.0], ["a", "b"], {}) == [1.0, 2.0]


def test_update_hypotheses_can_revoke_falsified(patched, tmp_path):
    """`falsified` 必须能改回 `verifying` ✓（原实现只认 `| open |` ✗）。"""
    hyp = tmp_path / "hypotheses.md"
    hyp.write_text(
        "| ID | 日期 | 名称 | 方向 | 方法 | 状态 | 备注 |\n"
        "|---|---|---|---|---|---|---|\n"
        "| H-001 | 2026-10-01 | n | d | m | falsified | 备注 |\n",
        encoding="utf-8")
    (tmp_path / "memory").mkdir(exist_ok=True)      # update_hypotheses 会追加日志 ✓
    h1.update_hypotheses("verifying", "撤销错误证伪")
    text = hyp.read_text(encoding="utf-8")
    assert "| verifying |" in text
    assert "| falsified |" not in text
