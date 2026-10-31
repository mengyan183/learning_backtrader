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
    _no_preflight(m, monkeypatch)
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

    news, sent, attr = m._run_stages({"date": "2026-10-29"})

    assert (news, sent, attr) == ("news", "sent", "attr")
    # 只看**并发峰值**，不看墙钟 ✗ —— 墙钟断言（took<0.6）在负载高的机器上会假红，
    # 而「峰值==3」已经能确定性证明三个线程同时在跑 ✓
    assert peak["max"] == 3, "三个阶段没有真正并发（峰值 %d）✗" % peak["max"]


def _no_preflight(m, monkeypatch):
    """关掉端口预检 ✓ —— 测试机没有 Hermes/代理，否则阶段会被秒跳过 ✗。"""
    monkeypatch.setattr(m, "HERMES_ADDR", None)
    monkeypatch.setattr(m, "PROXY_ADDR", None)


def test_preflight_skips_dead_stage(monkeypatch):
    """服务端口不通 ⇒ **秒跳过**，不白等阶段超时 ✓（2026-10-29 实测教训）。

    代理恢复后 net_probe 全绿，但简报两个阶段仍 240s 超时 ✗
    ⇒ 「网络通」≠「服务在」✗ ⇒ 必须探端口。
    """
    import time as _t

    m = _load()
    monkeypatch.setattr(m, "HERMES_ADDR", ("127.0.0.1", 1))   # 必然连不上
    monkeypatch.setattr(m, "PROXY_ADDR", None)
    called = []
    monkeypatch.setattr(m, "fetch_news", lambda snap: "n")
    monkeypatch.setattr(m, "_read_hermes_key", lambda: "k")
    monkeypatch.setattr(m, "_read_nim_key", lambda: "k")
    monkeypatch.setattr(m, "stage_sentiment",
                        lambda k, snap: called.append(1) or "s")
    monkeypatch.setattr(m, "stage_attribution", lambda k, snap, kb=None: "a")

    t0 = _t.time()
    news, sent, attr = m._run_stages({"date": "2026-10-29"})
    took = _t.time() - t0

    assert not called, "端口不通却还去调 Hermes ✗"
    assert sent is None, "跳过的阶段应返回 None ✗"
    assert news == "n" and attr == "a", "正常阶段被连累了 ✗"
    assert took < 3, "预检没起作用（%.1fs）✗" % took


def test_llm_endpoints_are_env_configurable(monkeypatch):
    """LLM 地址 / 模型 / key 必须能从环境变量覆盖 ✓。

    2026-10-30：Mac 上三个 agent 已统一走 DeepSeek，而脚本里还硬编码 NIM ✗
    ⇒ 换供应商要改代码 ✗ ⇒ 改成读配置，且**不设 env 时行为不变** ✓。
    """
    monkeypatch.setenv("FG_LLM_URL", "https://api.deepseek.com/v1/chat/completions")
    monkeypatch.setenv("FG_LLM_MODEL", "deepseek/deepseek-flash")
    monkeypatch.setenv("FG_LLM_KEY", "sk-unit-test")

    m = _load()

    assert m.NIM_URL == "https://api.deepseek.com/v1/chat/completions"
    assert m.NIM_MODEL == "deepseek/deepseek-flash"
    assert m._read_nim_key() == "sk-unit-test", "FG_LLM_KEY 没被优先采用 ✗"
    assert m._read_hermes_key() == "sk-unit-test"


def test_llm_defaults_unchanged_without_env(monkeypatch):
    """不设环境变量时**行为完全不变** ✓ —— 不能静默改掉生产链路 ✗。"""
    for k in ("FG_LLM_URL", "FG_LLM_MODEL", "FG_LLM_KEY",
              "FG_HERMES_URL", "FG_HERMES_MODEL"):
        monkeypatch.delenv(k, raising=False)

    m = _load()

    assert "integrate.api.nvidia.com" in m.NIM_URL
    assert m.NIM_MODEL == "deepseek-ai/deepseek-v4.1-flash"
    assert "127.0.0.1:8642" in m.HERMES_URL


def test_kb_threshold_is_060():
    """知识库相关度阈值 = **0.6** ✓（2026-10-29 用户裁定 0.7 → 0.6）。

    0.7 太严：实测当天命中全被过滤 ⇒ 整节变成空占位 ✗。
    """
    m = _load()
    assert m.KB_MIN_SCORE == 0.6

    def _hit(score):
        return {"channel": "C%d" % int(score * 100), "title": "t", "date": "NA",
                "score": score, "snippet": "x" * 60}

    txt = m._kb_brief_text([_hit(0.55), _hit(0.62)])
    assert "C62" in txt, "0.62 应该保留 ✓"
    assert "C55" not in txt, "0.55 应该被过滤 ✗"


def test_snapshot_lines_format_numbers():
    """简报里的数字必须**可读** ✓（2026-10-29 用户实测）。

    - 目标仓位原来直接打 float ⇒ 出现 `0.4708333333333333` ✗
    - 浮盈亏同一列里 1 位 / 2 位小数混用（`-1276.8` vs `-869.78`）✗
    """
    m = _load()
    snap = {
        "fg": {"fg_index": 36.4, "zone": "1.0",
               "target_position": 0.4708333333333333,
               "drawdown": 0.0633, "circuit_breaker": False},
        "shoutu": {}, "shoutu_date": "2026-10-29",
        "positions": [{"symbol": "YINN", "name": "x", "cost": 26.82,
                       "last_close": 21.28, "pnl": -1276.8, "pnl_pct": -27.34}],
        "accounts": {"stock": 11017.4},
    }
    txt = m.build_snapshot_lines(snap)

    assert "目标仓位 47.1%" in txt, txt
    assert "0.4708333333333333" not in txt, "目标仓位又打全精度了 ✗"
    assert "-1276.80 (-27.34%)" in txt, "浮盈亏没统一 2 位小数 ✗"


def test_reduce_suffix_is_stated_once():
    """「仅价格风控 / 只降敞口不追方向」只在**段首**说一次 ✓。

    2026-10-29 实测：6 条减仓各带一遍同样的后缀 ✗。
    """
    m = _load()
    snap = {"positions": [
        {"symbol": "YINN", "mv": 3341, "risk_limit": 1255, "risk_over": True,
         "sys_fg": 25.9, "sys_fg_note": "个股级"},
        {"symbol": "GDXU", "mv": 3393, "risk_limit": 487, "risk_over": True,
         "sys_fg": 32.8, "sys_fg_note": "个股级"},
    ], "shoutu": {}}

    txt = m.action_brief_text(snap)

    assert txt is not None
    assert txt.count("只降敞口") == 1, "后缀又被逐条重复了 ✗"


def test_hung_stage_degrades_instead_of_blocking(monkeypatch):
    """单阶段卡住必须**降级跳过** ✓ —— 不许拖死整条简报 ✗。

    2026-10-29 用户裁定：并发版仍破 600 秒 ⇒ 说明有阶段会长时间挂住 ✗
    ⇒ 每个阶段加 `STAGE_TIMEOUT`，超了就 None（简报照发 + 写「跳过：超时」）✓。
    """
    import time as _t

    m = _load()
    _no_preflight(m, monkeypatch)
    monkeypatch.setattr(m, "STAGE_TIMEOUT", 0.4)
    monkeypatch.setattr(m, "fetch_news", lambda snap: "news")
    monkeypatch.setattr(m, "_read_hermes_key", lambda: "k")
    monkeypatch.setattr(m, "_read_nim_key", lambda: "k")
    monkeypatch.setattr(m, "stage_sentiment", lambda k, snap: _t.sleep(30))
    monkeypatch.setattr(m, "stage_attribution", lambda k, snap, kb=None: "attr")

    t0 = _t.time()
    news, sent, attr = m._run_stages({"date": "2026-10-29"})
    took = _t.time() - t0

    assert took < 5, "卡住的阶段把整条简报拖住了（%.1fs）✗" % took
    assert sent is None, "卡住的阶段应降级为 None ✗"
    assert news == "news" and attr == "attr", "正常阶段被连累了 ✗"


def test_stage_progress_is_logged(tmp_path, monkeypatch):
    """阶段级进度必须**落盘** ✓。

    2026-10-29 实测：队列动作 600 秒超时，`subprocess` 杀掉进程 ⇒ stdout 全丢 ✗
    ⇒ 只知道「超时」，不知道卡在新闻还是某个 LLM 阶段 ✗。
    """
    m = _load()
    _no_preflight(m, monkeypatch)
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
    _no_preflight(m, monkeypatch)

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


def test_prev_factor_value_falls_back_to_last_valid():
    """vix/term 缺失时回退到**最近一个非空值**并给出 T-n ✓。

    2026-10-31 实测：VIX 缺失是**数据源时滞**（CBOE 的 T 日数据在每日链
    05:30 跑时还没发布 ✗，10:22 补抓就有 ✓）
    ⇒ 简报显示 `T-1` 的值并标注，比「数据缺失」有用且不编造 ✓。
    """
    import pandas as pd

    m = _load()
    df = pd.DataFrame({
        "date": ["2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30"],
        "vix": [40.0, 42.0, 41.0, None],
        "term": [None, None, None, None],
    })

    assert m._prev_factor_value(df, "vix") == (41.0, 1)
    assert m._prev_factor_value(df, "term") == (None, 0), \
        "全空时不能瞎给值 ✗"
    assert m._prev_factor_value(df, "不存在") == (None, 0)


def test_every_symbol_term_has_entity_filter():
    """每个标的检索词都必须配**实体词** ✓。

    2026-10-31 实测：0.602 的 RaynerTeo《Trading Results》讲比特币减半，
    分数过了 0.6 但与当天持仓无关 ✗ —— 语义相似 ≠ 讲的是同一个东西 ✗
    ⇒ 靠 `KB_QUERY_ENTITIES` 要求片段提到核心实体 ✓。
    漏配的检索词会**静默不过滤** ✗ ⇒ 这里锁住覆盖完整 ✓。
    """
    m = _load()
    missing = [t for t in m.KB_SYMBOL_TERMS.values()
               if t not in m.KB_QUERY_ENTITIES]
    assert not missing, "这些检索词没配实体词 ✗：%s" % missing
    for term, ents in m.KB_QUERY_ENTITIES.items():
        assert ents, "%r 的实体词列表为空 ✗" % term


def test_btc_term_is_thesis_specific():
    """BTC 的检索词不能是「halving」这种话题词 ✗。

    「比特币减半」是科普话题，会命中一堆讲原理的视频 ✗；
    仓位逻辑是「借 USDT 买入」⇒ 该看 ETF 资金流 / 机构需求 ✓。
    """
    m = _load()
    t = m.KB_SYMBOL_TERMS["BTC"]
    assert "halving" not in t, "又退回话题词了 ✗"
    assert "etf" in t or "institutional" in t


def test_llm_tag_follows_runtime_config():
    """简报小节标题必须**跟着运行时配置走** ✓ —— 硬编码会过期 ✗。

    2026-10-31 实测：三个通道全部切到 DeepSeek 后，简报标题仍写着
    「Hermes(GLM)」「DeepSeek(NVIDIA NIM)」「OpenClaw云端(NVIDIA NIM)」✗
    ⇒ 读者会以为还在用 GLM / NIM ✗。
    """
    m = _load()

    assert "DeepSeek" in m._llm_tag(
        "https://api.deepseek.com/v1/chat/completions", "deepseek/deepseek-flash")
    assert "deepseek-flash" in m._llm_tag(
        "https://api.deepseek.com/v1/chat/completions", "deepseek/deepseek-flash")
    assert "NVIDIA" in m._llm_tag(
        "https://integrate.api.nvidia.com/v1/chat/completions",
        "deepseek-ai/deepseek-v4.1-flash")
    assert "本地" in m._llm_tag("http://127.0.0.1:8642/v1/chat/completions",
                                "hermes-agent")
    assert m._llm_tag("", "") == "未知模型"


def test_no_hardcoded_vendor_labels_left():
    """源码里不能再有硬编码的供应商标题 ✗（会随切换过期 ✗）。"""
    import io
    import os

    from fg_system import config
    p = os.path.join(config.ROOT, "scripts", "invest_research.py")
    src = io.open(p, encoding="utf-8").read()
    # 只查**会被渲染出去**的完整标签 ✗ —— 别误伤解释性注释 ✓
    for bad in ('("📰 情绪面 · Hermes(GLM)"',
                '("🔍 深度归因 · DeepSeek(NVIDIA NIM)"',
                '"## 情绪面分析（Hermes / GLM）"',
                '"## 深度归因（Harness 后端'):
        assert bad not in src, "硬编码标题又回来了 ✗：%r" % bad


def test_llm_key_follows_url_not_vendor(monkeypatch):
    """归因/裁判的 key 按 **URL** 选，不是按供应商 ✗（2026-10-31）。

    实测教训：plist 把 URL 指到 `api.deepseek.com` 后，
    情绪面（本地 Hermes）**从成功变失败** ✗、归因/裁判 401 ✗
    ⇒ 本地 Hermes 内部已配好 DeepSeek，脚本不该自己拿 key 直连 ✗
    ⇒ URL 是本机时用 Hermes 的 key ✓。
    """
    m = _load()
    monkeypatch.delenv("FG_LLM_KEY", raising=False)
    monkeypatch.setattr(m, "_read_hermes_key", lambda: "hermes-key")
    monkeypatch.setattr(m, "_read_nim_key", lambda: "nim-key")

    monkeypatch.setattr(m, "NIM_URL", "http://127.0.0.1:8642/v1/chat/completions")
    assert m._read_llm_key() == "hermes-key", "本地 URL 应该用 Hermes 的 key ✗"

    monkeypatch.setattr(m, "NIM_URL",
                        "https://integrate.api.nvidia.com/v1/chat/completions")
    assert m._read_llm_key() == "nim-key", "远端 URL 应该用 NIM 的 key ✗"

    monkeypatch.setenv("FG_LLM_KEY", "explicit-key")
    assert m._read_llm_key() == "explicit-key", "显式环境变量优先级最高 ✗"


def test_judge_error_message_is_not_hardcoded():
    """裁判失败文案不能写死「NIM」✗（通道可能已换 ✗）。"""
    import io
    import os

    from fg_system import config
    src = io.open(os.path.join(config.ROOT, "scripts", "invest_research.py"),
                  encoding="utf-8").read()
    assert "裁判调用失败（NIM）" not in src
    assert "（跳过：NIM 不可用）" not in src


def test_reduce_order_is_written():
    """「减仓操作」必须给出**减仓顺序** ✓（2026-10-31 用户裁定）。

    排序 = 浮亏深度 × 杠杆倍数（越大越先减）✓ 依据：
      ① 浮亏深 ⇒ 回本数学指数级恶化（-83% 要 +488%）
      ② 杠杆高 ⇒ 日重置损耗更快
      ③ 盈利仓 ⇒ 不减 ✓

    ⚠️ 不排序的话，照「逐标的减到上限」平均减会先砍 YINN
    （方向最对、亏得最少）而留着 AXTX（已废）⇒ **减反了** ✗
    """
    m = _load()
    snap = {
        "accounts": {"stock": 9584.6},
        "positions": [
            {"symbol": "YINN", "mv": 3531, "pnl_pct": -16.14,
             "risk_limit": 1065, "risk_over": True},
            {"symbol": "GDXU", "mv": 2692, "pnl_pct": -42.35,
             "risk_limit": 315, "risk_over": True},
            {"symbol": "CRCG", "mv": 1570, "pnl_pct": -53.67,
             "risk_limit": 331, "risk_over": True},
            {"symbol": "CONL", "mv": 1939, "pnl_pct": -40.78,
             "risk_limit": 350, "risk_over": True},
            {"symbol": "AXTX", "mv": 733, "pnl_pct": -82.75,
             "risk_limit": 209, "risk_over": True},
            {"symbol": "BTC-USDT", "mv": 2319, "pnl_pct": 23.78,
             "risk_limit": 1597, "risk_over": True},
        ],
        "shoutu": {"YINN": -81, "GDXU": -100, "CRCG": -96,
                   "CONL": -89, "AXTX": -90},
    }

    txt = m.action_brief_text(snap)

    assert "减仓顺序" in txt, "没写减仓顺序 ✗"
    # AXTX（83%×2x=166）必须排第一；YINN（16%×3x=48）排最后
    order_line = [ln for ln in txt.splitlines() if "减仓顺序" in ln][0]
    assert order_line.index("AXTX") < order_line.index("YINN"), \
        "AXTX 应该排在 YINN 前面 ✗（实际顺序反了）"
    assert "BTC" not in order_line, "盈利仓不该进减仓顺序 ✗"


def test_snapshot_gives_explicit_position_ratio():
    """快照必须**显式给出仓位口径** ✓ —— 否则 AI 自己挑分母 ✗。

    2026-10-31 实测：同一份持仓，两份简报一个算「名义仓位 103.7%」
    （分母=股票净值）、一个算「84.9%」（分母=总净值）✗ 数字对不上 ✗
    """
    m = _load()
    snap = {
        "positions": [
            {"symbol": "YINN", "account": "stock", "mv": 3531.0,
             "name": "x", "qty": 1, "cost": 26.82, "last_close": 22.49,
             "pnl": -679.81, "pnl_pct": -16.14},
        ],
        "accounts": {"stock": 9584.6, "crypto": 2742.3},
    }

    txt = m.snapshot_text(snap)

    assert "仓位口径" in txt, "没给仓位口径 ✗"
    # 名义仓位 = 3531 / (9584.6+2742.3) = 28.6%
    assert "28.6%" in txt, txt
    # 股票端 = 3531 / 9584.6 = 36.8%
    assert "36.8%" in txt, txt


def test_snapshot_shows_cash_detail():
    """快照要给出**现金明细** ✓ —— 解释「净值比币值多出来的钱」✗。

    2026-10-31：加密净值 2,742 vs BTC 市值 2,318，差 425 一直没人能解释 ✗
    `accounts.csv` 本来就有 `securities_mv` / `cash` 两列 ✓。
    """
    m = _load()
    snap = {
        "positions": [],
        "accounts": {"stock": 9584.6, "crypto": 2742.3},
        "accounts_detail": {
            "crypto": {"net_value": 2742.3, "securities_mv": 2318.0,
                       "cash": 424.3, "date": "2026-10-30"},
        },
    }

    txt = m.snapshot_text(snap)

    assert "账户明细" in txt
    assert "现金424" in txt, txt
    assert "证券2318" in txt, txt


def test_attribution_prompt_forbids_linear_scaling():
    """归因 prompt 必须**禁止线性折算** ✓（2026-10-31 用户裁定）。

    杠杆 ETF 是逐日复利：ETF累计 = ∏(1+L×r_i) ≠ 1 + L×Σr_i
    震荡市有 volatility decay ⇒ 「ETF跌幅÷杠杆」会**系统性低估**标的跌幅 ✗
    （实测：AXTX -82.75% 被折算成「标的仅跌41.4%」✗）
    """
    import io
    import os

    from fg_system import config
    src = io.open(os.path.join(config.ROOT, "scripts", "invest_research.py"),
                  encoding="utf-8").read()
    assert "禁止用「ETF 跌幅 ÷ 杠杆倍数」反推标的跌幅" in src
    assert "系统性低估" in src
