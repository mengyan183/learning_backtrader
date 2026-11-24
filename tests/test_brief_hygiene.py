# -*- coding: utf-8 -*-
"""简报卫生：剥 LLM 噪音行 + 模块→agent 路由（2026-11-09 用户要求）。"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))

import invest_research as ir  # noqa: E402


def test_conflict_note_only_when_both(monkeypatch):
    """「恐惧档 + 机械减仓」同时出现才解释 —— 否则是噪音 ✓。

    🔴 2026-11-23 事故：简报一边说「没恐慌割肉 ⇒ 不动是对的」，
       一边要求「YINN 2925 → 643（减仓至上限）」✗ 读者只看到矛盾 ✗
       ⇒ 必须由文案自己解释「情绪」与「敞口」是两个判据 ✓
    """
    monkeypatch.setattr(ir, "action_brief_text",
                        lambda snap: "· YINN 市值2925/上限643 → 减仓至上限643")
    note = ir._conflict_note({}, 0)
    assert "不冲突" in note and "1% 硬上限" in note

    # 贪婪档不需要解释（那时减仓与情绪方向一致，不矛盾）
    assert ir._conflict_note({}, 3) == ""

    # 没有机械减仓 ⇒ 不需要解释
    monkeypatch.setattr(ir, "action_brief_text",
                        lambda snap: "· 全部**无减仓触发** ⇒ 持有观望")
    assert ir._conflict_note({}, 0) == ""


def test_futu_probe_never_raises(monkeypatch):
    """实时探测失败必须**返回**而不是抛 ✓ —— 简报不能因为 OpenD 挂了而崩。

    🔴 2026-11-23 事故：健康块读的是 `futu_preflight` 在 05:42 写的状态文件 ✗
       13:48 的简报仍报「不可用」，而 OpenD 10:16 就恢复了 ⇒ 误导 3.5 小时 ✗
    """
    monkeypatch.setattr(ir, "_FUTU_PROBE", {})
    ok, why, at = ir._futu_probe_now(timeout=1)
    assert isinstance(ok, bool)
    assert isinstance(why, str)
    assert at, "必须带回探测时刻 ✗"


def test_brief_title_carries_generation_date():
    """标题（**飞书与 markdown 共用**）必须带「（生成 MM-DD）」✓。

    🔴 2026-11-23 事故：`_gen_suffix` 只加在 markdown 路径 ✗
       飞书富文本另有一处拼标题 ⇒ 用户看到的推送里没有生成日 ✗
    """
    import datetime as _dt

    old = (_dt.date.today() - _dt.timedelta(days=3)).isoformat()
    t = ir._brief_title({"index_date": old})
    assert "生成" in t and old in t

    # 续篇同样要带（否则第 2 条消息看不出是哪天生成的）
    t2 = ir._brief_title({"index_date": old}, cont=True)
    assert "续" in t2 and "生成" in t2

    today = _dt.date.today().isoformat()
    assert "生成" not in ir._brief_title({"index_date": today})


def test_index_lag_uses_trading_days():
    """周五数据在周一早上 = **0 个交易日**滞后 ✓（不能用自然日）。

    🔴 2026-11-23 事故：用自然日算会把每个周一都误报成「停更 3 天」✗
       2026-11-20 是周五、11-23 是周一 ⇒ 最新可得数据就是 11-20 ✓
    """
    import datetime as _dt

    mon = _dt.date(2026, 11, 23)
    assert ir._index_lag_days("2026-11-20", today=mon) == 0
    assert ir._index_lag_days("2026-11-19", today=mon) == 1
    assert ir._index_lag_days("2026-11-17", today=mon) == 3
    # 未来日期/脏值不得炸
    assert ir._index_lag_days("2026-12-01", today=mon) == 0
    assert ir._index_lag_days("not-a-date", today=mon) is None


def test_freshness_block_warns_when_file_missing(monkeypatch, tmp_path):
    """护栏产物缺失 ⇒ 必须说「未知」，**沉默不能等于正常** ✓。

    🔴 2026-11-23 事故：四份简报都没有「数据新鲜度」段，
       因为 `freshness_warning.txt` 不存在，而旧实现对此返回 None ✗
    """
    monkeypatch.setattr(ir, "REPO", tmp_path)
    txt = ir._freshness_block({"index_date": "2026-11-20"})
    assert txt and "新鲜度未知" in txt


def test_conflict_note_covers_not_operable(monkeypatch):
    """「不可操作 + 减仓至上限」也要解释 —— 措辞不能只适配恐惧档 ✓。

    🔴 2026-11-24 实测：风控段写「**不可操作** → 未达调仓阈值 10pp」，
       而减仓段仍写「YINN 3045/上限 656 → 减仓至上限 656」✗
       原文案「上面说**不动是对的**」对不上场景 ⇒ 读者以为文案串了 ✗
    """
    monkeypatch.setattr(
        ir, "action_brief_text",
        lambda snap: ("· 指令：**不可操作** → 未达调仓阈值 10pp（偏离 8.0pp）\n"
                      "· YINN 市值3045/上限656 → 减仓至上限656"))
    note = ir._conflict_note({}, 0)
    assert "不可操作" in note, note
    assert "硬上限" in note, note
    assert "不动是对的" not in note, "不可操作场景不该沿用恐惧档措辞 ✗"


def test_gen_suffix_marks_generation_date():
    """数据日 ≠ 生成日 ⇒ 标题必须标出生成日 ✓。

    🔴 四份简报（11-20~11-23）标题全是「2026-11-20」✗
       读者在 11-23 打开会以为是最新读数 ✗
    """
    import datetime as _dt

    old = (_dt.date.today() - _dt.timedelta(days=3)).isoformat()
    assert "生成" in ir._gen_suffix({"index_date": old})

    today = _dt.date.today().isoformat()
    assert ir._gen_suffix({"index_date": today}) == ""
    assert ir._gen_suffix({}) == ""


def test_strip_removes_pseudo_keys_and_selfcheck():
    """伪键名占位符 + 字数自检行必须剥掉，正文不动。"""
    raw = ("一、逐标的归因\n"
           "AXTX -92.5%，亏3930。\n"
           "explainer.file_mutation.header\n"
           "explainer.file_mutation.entry\n"
           "495字，符合上限。\n"
           "（498字，已按去空白字符核验）\n"
           "二、组合风险点\n")
    out = ir._strip_llm_artifacts(raw)
    assert "explainer.file_mutation" not in out
    assert "符合上限" not in out
    assert "已按去空白字符核验" not in out
    assert "AXTX -92.5%" in out
    assert "二、组合风险点" in out


def test_strip_keeps_legit_text_with_zi():
    """正常含「字」的正文不得被误删（只删 ≤30 字且带自检词的短行）。"""
    raw = "这一段的字面意思是杠杆损耗会累积，需要按逐日复利理解。"
    assert ir._strip_llm_artifacts(raw) == raw


def test_strip_removes_trailing_zi_suffix():
    """行尾的「（48字）」只削后缀，正文保留 ✓（2026-11-09 18:49 实测）。"""
    raw = "建议：每天固定20分钟写意义笔记，两周后对照精神分值。（48字）"
    out = ir._strip_llm_artifacts(raw)
    assert out.endswith("分值。")
    assert "48字" not in out


def test_strip_handles_none():
    assert ir._strip_llm_artifacts(None) is None


def test_agent_route_defaults_and_override(monkeypatch):
    """模块→agent 路由：默认回落现状，环境变量可覆盖。"""
    for k in ("FG_AGENT_SENTIMENT_URL", "FG_AGENT_SENTIMENT_MODEL"):
        monkeypatch.delenv(k, raising=False)
    url, model = ir.agent_route("sentiment")
    assert url == ir.HERMES_URL and model == ir.HERMES_MODEL

    monkeypatch.setenv("FG_AGENT_SENTIMENT_URL", "http://127.0.0.1:9999/v1")
    monkeypatch.setenv("FG_AGENT_SENTIMENT_MODEL", "other-agent")
    url, model = ir.agent_route("sentiment")
    assert url == "http://127.0.0.1:9999/v1" and model == "other-agent"


def test_agent_route_covers_three_modules():
    assert set(ir.AGENT_ROUTES) == {"sentiment", "attribution", "judge"}


def test_clip_at_sentence_cuts_at_period():
    """超长文本必须在**句号处**收尾，不能砍半句（2026-11-10 实测）。"""
    body = "第一句讲归因。" * 30
    out = ir._clip_at_sentence(body, 1200)
    assert len(out) <= 1200
    assert out.endswith("。"), "截断点不在句号处"


def test_clip_at_sentence_keeps_short_text():
    assert ir._clip_at_sentence("很短的一句。", 1200) == "很短的一句。"


def test_clip_at_sentence_falls_back_when_no_period():
    """全篇没有句号 ⇒ 退化为 `…` 收尾，不硬切出半句感。"""
    out = ir._clip_at_sentence("啊" * 2000, 1200)
    assert len(out) <= 1201
    assert out.endswith("…")


def test_strip_removes_markdown_heading():
    """模型吐的 `## 一、逐标的归因` 必须去掉 `##`（飞书不解析 markdown）。"""
    raw = "## 一、逐标的归因\nAXTX 亏 92.5%。\n### 二、组合风险点\n现金 -884。"
    out = ir._strip_llm_artifacts(raw)
    assert "##" not in out
    assert "一、逐标的归因" in out
    assert "二、组合风险点" in out


def test_repo_root_on_sys_path_so_fg_system_importable():
    """脚本上下文（`sys.path` 无 cwd）下必须能 `from fg_system import ...` ✓。

    🔴 2026-11-20 实测（每日链日志里一直有）✗：
       `[warn] 有效敞口计算失败：No module named 'fg_system'` ✗
       根因：本脚本以 `python scripts/invest_research.py` 运行 ⇒
       `sys.path[0]` 是 `scripts/`，**仓库根不在其中** ✗
       ⇒ `build_snapshot()` 里那句 `from fg_system import position_plan`
         每轮都抛 ModuleNotFoundError ⇒ 简报的「有效敞口」**一直是回退值** ✗
       （不崩、不报警，只是悄悄少一行 ⇒ 谁也没发现 ✗）

    这条测试用**子进程**模拟脚本上下文：先把 `''`/`'.'`（cwd）从 sys.path
    剔掉，再只放 `scripts/` —— 与真实运行方式一致 ✓
    """
    import subprocess

    code = (
        "import sys\n"
        "sys.path = [p for p in sys.path if p not in ('', '.')]\n"
        "sys.path.insert(0, 'scripts')\n"
        "import invest_research as ir\n"
        "assert str(ir.REPO) in sys.path, 'REPO 不在 sys.path ✗'\n"
        "from fg_system import position_plan as pp\n"
        "print(pp.leverage_of('YINN'))\n"
    )
    r = subprocess.run([sys.executable, "-c", code], cwd=REPO,
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    assert r.returncode == 0, "脚本上下文导不进 fg_system ✗：%s" % (r.stderr or "")[-400:]
    assert "3" in (r.stdout or ""), "leverage_of('YINN') 应为 3"


def test_stock_day_pnl_ignores_crypto_row():
    """连亏保护的分子只能取 **stock 账户** ✓ —— 不许跨账户 ✗。

    🔴 2026-11-20 线上实测：简报写「当日亏损 -1072.79 (-18.3% 股票净值)」，
       但同一份简报里股票净值 6202.5 → 5876.4 只差 **-326.1** ✗
       根因：`acc_latest` 同时含 stock + crypto 两行，代码 `.iloc[-1]`
       取到了 **crypto** 那行（本地实测 iloc[-1] 就是 crypto）✗，
       而分母是 `stock_net` ⇒ 跨账户混算 ✗
       （-1072.79 / 5876.4 = -18.26%，与显示的 -18.3% 完全吻合）
    """
    import pandas as pd
    df = pd.DataFrame([
        {"account": "stock", "net_value": 5876.4, "day_pnl": -326.1},
        {"account": "crypto", "net_value": 2302.48, "day_pnl": -1072.79},
    ])
    assert ir._stock_day_pnl(df) == -326.1, "取到 crypto 的数了 ✗"


def test_stock_day_pnl_returns_none_without_stock_row():
    """没有 stock 行 ⇒ 返回 None ✓（不给结论，而不是拿别的账户凑数 ✗）。"""
    import pandas as pd
    df = pd.DataFrame([{"account": "crypto", "net_value": 2302.48,
                        "day_pnl": -1072.79}])
    assert ir._stock_day_pnl(df) is None


def test_stock_day_pnl_tolerates_legacy_file_without_account_column():
    """老 `accounts.csv` 没有 `account` 列时退回原行为 ✓（向后兼容）。"""
    import pandas as pd
    df = pd.DataFrame([{"net_value": 5876.4, "day_pnl": -326.1}])
    assert ir._stock_day_pnl(df) == -326.1


def _acc_frame(stock_nv, stock_pnl, prev_mv, cur_mv, crypto_pnl=-51.98):
    """构造两日 accounts.csv 形态（stock + crypto）。"""
    import pandas as pd
    return pd.DataFrame([
        {"date": "2026-11-18", "account": "stock", "net_value": stock_nv - stock_pnl,
         "securities_mv": prev_mv, "day_pnl": -715.22},
        {"date": "2026-11-18", "account": "crypto", "net_value": 2354.46,
         "securities_mv": 0.0, "day_pnl": -16.28},
        {"date": "2026-11-19", "account": "stock", "net_value": stock_nv,
         "securities_mv": cur_mv, "day_pnl": stock_pnl},
        {"date": "2026-11-19", "account": "crypto", "net_value": 2302.48,
         "securities_mv": 0.0, "day_pnl": crypto_pnl},
    ])


def test_kill_switch_uses_opening_nav_as_denominator():
    """分母必须是**期初净值** ✓（第 12.46 条）。

    🔴 2026-11-19 实测：-1072.79 / 5876.40 = **-18.3%**（期末，被放大）
       正确：           -1072.79 / 6949.19 = **-15.4%**（期初）
    """
    import pandas as pd
    acc = _acc_frame(5876.40, -1072.79, prev_mv=7086.0, cur_mv=3014.0)
    latest = acc[acc["date"] == pd.Timestamp("2026-11-19").strftime("%Y-%m-%d")]
    if latest.empty:
        latest = acc[acc["date"] == "2026-11-19"]
    ks = ir._kill_switch(latest, acc, 5876.40)
    assert ks is not None, "该触发却没触发 ✗"
    assert ks["prev_net"] == 6949.19
    assert ks["pct"] == -15.44, "分母不是期初净值 ✗：%s" % ks["pct"]
    assert ks["pct"] != -18.26, "还在用期末净值 ✗"


def test_kill_switch_flags_liquidation_slippage():
    """证券市值大幅下降 ⇒ `sold=True`（文案要标注「含减仓滑点」）✓。"""
    import pandas as pd
    acc = _acc_frame(5876.40, -1072.79, prev_mv=7086.0, cur_mv=3014.0)
    latest = acc[acc["date"] == "2026-11-19"]
    ks = ir._kill_switch(latest, acc, 5876.40)
    assert ks["sold"] is True
    assert ks["sell_ratio"] and ks["sell_ratio"] > 0.5


def test_kill_switch_no_sell_flag_on_normal_day():
    """正常波动（证券市值只小幅变化）⇒ `sold=False`，不误标 ✓。"""
    import pandas as pd
    acc = _acc_frame(6000.0, -300.0, prev_mv=6300.0, cur_mv=6100.0)
    latest = acc[acc["date"] == "2026-11-19"]
    ks = ir._kill_switch(latest, acc, 6000.0)
    assert ks is not None
    assert ks["sold"] is False


def test_kill_switch_not_triggered_below_threshold():
    """亏损不到 2% 期初净值 ⇒ 不触发 ✓。"""
    import pandas as pd
    acc = _acc_frame(6000.0, -50.0, prev_mv=6100.0, cur_mv=6050.0)
    latest = acc[acc["date"] == "2026-11-19"]
    assert ir._kill_switch(latest, acc, 6000.0) is None


# ---------------------------------------------------------------- 防抖进简报（12.49）
def _instr_snap(mv=5000.0, net=10000.0, target=0.45):
    return {
        "fg": {"date": "2026-11-19", "target_position": target,
               "extreme": False},
        "positions": [{"symbol": "YINN", "mv": mv}],
        "accounts": {"stock": net},
    }


def test_instruction_line_shows_not_actionable_below_threshold():
    """偏离不足 10pp ⇒ 简报必须写「**不可操作**」✓，而不是只给目标仓位 ✗。

    🔴 2026-11-20（第 12.49 条）：防抖只在 `instruction_card()`（CLI）里生效，
       简报展示的是**未防抖**的原始目标 ⇒ 读者以为「目标 45%」就是该调的 ✗
    """
    from fg_system import signal as sig

    snap = _instr_snap(mv=5000.0, net=10000.0, target=0.45)   # 当前 50%，目标 45%
    txt = ir._instruction_line(snap, state=sig.SignalState())
    assert "不可操作" in txt
    assert "阈值" in txt
    assert "50.0%" in txt and "45.0%" in txt


def test_instruction_line_shows_actionable_above_threshold():
    """偏离 ≥10pp ⇒ 写「可操作 → 减仓 Xpp（调整后目标 Y%）」✓。"""
    from fg_system import signal as sig

    snap = _instr_snap(mv=8000.0, net=10000.0, target=0.45)   # 当前 80%
    txt = ir._instruction_line(snap, state=sig.SignalState())
    assert "可操作" in txt
    assert "减仓" in txt
    assert "pp" in txt
    # 单次调仓上限 30pp ⇒ 80% 只能减到 50%，不是直接到 45%
    assert "50.0%" in txt


def test_instruction_line_empty_without_positions():
    """没有持仓 / 净值 ⇒ 返回空串（不猜）✓。"""
    from fg_system import signal as sig

    snap = {"fg": {"target_position": 0.45}, "positions": [],
            "accounts": {"stock": 10000.0}}
    assert ir._instruction_line(snap, state=sig.SignalState()) == ""
