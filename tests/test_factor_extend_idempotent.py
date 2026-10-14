# -*- coding: utf-8 -*-
"""守卫：factor_screen_extend.py 的产物写入必须幂等（重复运行不产生重复段/重复登记行）。

背景（同类非幂等 bug）：
- scripts/factor_screen_extend.py 曾用 `open(res_path, "a")` **无条件追加**结果段，
  并用 `open(fm_path, "w")` 把 6 条登记行**无条件拼接**进 factors.md。
- 实测 evolution/factor-screen-results.md 里 `## 登记已追加 F-007~F-009` 出现两次；
  evolution/factors.md 里 F-007/F-008/F-009 各被登记两次（2026-10-08 与 2026-10-09）。

本测试用 tmp_path 构造输入，**不碰真实产物**。
"""
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load_extend():
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    spec = importlib.util.spec_from_file_location(
        "factor_screen_extend", REPO / "scripts" / "factor_screen_extend.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# 幂等键：段标题（稳定，不含日期）——直接引用脚本内常量，避免测试与实现漂移。
SECTION_TITLE = _load_extend().SCREEN_SECTION_TITLE


def _section(date="2026-10-09", marker="RESULTS-A"):
    """构造一段 factor_screen_extend 风格的结果段（首行=幂等键标题）。"""
    return "\n".join([
        SECTION_TITLE,
        "- 生成：%s · scripts/factor_screen_extend.py" % date,
        "",
        "## F-007 守猪待兔市场温度（跨标的日均值）→ SPY",
        "",
        "样本：14 个交易日",
        "",
        "## F-009 OKX 资金费率（funding_btc）→ BTC",
        "",
        "样本：7 个交易日 ⇒ **样本不足，登记积累中**",
        "",
        marker,
        "",
    ])


def test_write_screen_section_twice_keeps_single_copy(tmp_path):
    """① 同一输入连续写两次 ⇒ 结果文件里该段标题只出现一次。"""
    mod = _load_extend()
    path = tmp_path / "factor-screen-results.md"

    mod.write_screen_section(str(path), _section())
    mod.write_screen_section(str(path), _section())

    text = path.read_text(encoding="utf-8")
    assert text.count(SECTION_TITLE) == 1, f"段标题重复 {text.count(SECTION_TITLE)} 次：\n{text}"
    assert text.count("## F-007 守猪待兔市场温度") == 1


def test_write_screen_section_rerun_replaces(tmp_path):
    """② 重跑以最新段替换旧段，不残留旧内容，且保留文件其它内容。"""
    mod = _load_extend()
    path = tmp_path / "factor-screen-results.md"
    path.write_text("# 因子评测协议报告\n\n已有内容 KEEP-ME\n", encoding="utf-8")

    mod.write_screen_section(str(path), _section(marker="RESULTS-A"))
    mod.write_screen_section(str(path), _section(date="2026-10-10", marker="RESULTS-B"))

    text = path.read_text(encoding="utf-8")
    assert "KEEP-ME" in text
    assert text.count(SECTION_TITLE) == 1
    assert "RESULTS-B" in text
    assert "RESULTS-A" not in text


def test_upsert_factor_rows_keeps_one_row_per_id(tmp_path):
    """③ 登记行按因子编号（幂等键）upsert：同一编号连续写两次只留一行。"""
    mod = _load_extend()
    path = tmp_path / "factors.md"
    header = (
        "# factors.md — 因子登记表（E4）\n\n"
        "| 编号 | 日期 | 因子(名称/公式) | 信号方向 | 检验方法 | 入库门槛 | 状态 | 备注 |\n"
        "|---|---|---|---|---|---|---|---|\n"
        "| F-001 | 2026-10-02 | 旧因子 | 逆向 | 同上 | 同上 | draft | KEEP-ME |\n"
    )
    path.write_text(header, encoding="utf-8")

    rows_a = {fid: "| %s | 2026-10-08 | 名称 %s | 正向 | 同 | 同 | draft | first |" % (fid, fid)
              for fid in ("F-007", "F-008", "F-009")}
    rows_b = {fid: "| %s | 2026-10-09 | 名称 %s | 正向 | 同 | 同 | draft | latest |" % (fid, fid)
              for fid in ("F-007", "F-008", "F-009")}

    mod.upsert_factor_rows(str(path), rows_a)
    mod.upsert_factor_rows(str(path), rows_b)

    text = path.read_text(encoding="utf-8")
    for fid in ("F-007", "F-008", "F-009"):
        assert text.count("| %s |" % fid) == 1, f"{fid} 重复：\n{text}"
    assert text.count("| F-001 |") == 1          # 既有因子未被破坏
    assert "KEEP-ME" in text
    assert "latest" in text
    assert "first" not in text                    # 旧登记行被最新替换
