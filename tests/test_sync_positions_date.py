# -*- coding: utf-8 -*-
"""`scripts/sync_positions.py` 的日期口径（MT-47）：美东交易日。

背景（2026-10-20）：`features.csv` 的 `date` 是**美东交易日** ✓（只有周一~周五），
而旧版 `today()` 用 `dt.date.today()` = **Mac 本地日期** ✗ ⇒ 北京时间上午跑会把
「还没收盘的今天」写进快照 ✗ ⇒ 两表差一天 ✗。实测旧口径产物 `accounts.csv` 里
含 **10-10 / 10-11 / 10-17 / 10-18 四个周末日期** ✗。

本文件锁住四件事：
① 16:00 ET 收盘线（含端点）；② 周末 / 工作日回退；③ 结果永不为周末；
④ `note` 列的口径切换标注。
"""
import datetime as dt
import importlib.util
import os
from zoneinfo import ZoneInfo

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "sync_positions.py")
TZ_CN = ZoneInfo("Asia/Shanghai")


def _load():
    spec = importlib.util.spec_from_file_location("sync_positions", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sp = _load()


def _et(s):
    """北京本地时刻字符串 → 美东 tz-aware datetime（走真实时区换算，不硬编码偏移）。"""
    bj = dt.datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=TZ_CN)
    return bj.astimezone(sp.TZ_ET)


# ------------------------------------------- ① 16:00 ET 收盘线（MT-47 点名用例）
def test_beijing_0430_maps_to_same_et_trading_day():
    """北京 10-21 04:30 = 美东 10-20 16:30（已收盘）⇒ date = 2026-10-20 ✓"""
    now = _et("2026-10-21 04:30")
    assert now.strftime("%Y-%m-%d %H:%M") == "2026-10-20 16:30"
    assert sp.trading_date(now) == "2026-10-20"


def test_beijing_evening_before_close_keeps_prev_day():
    """北京 10-21 20:00 = 美东 10-21 08:00（未收盘）⇒ 仍取 2026-10-20 ✓"""
    now = _et("2026-10-21 20:00")
    assert now.strftime("%Y-%m-%d %H:%M") == "2026-10-21 08:00"
    assert sp.trading_date(now) == "2026-10-20"


def test_exactly_close_hour_uses_today():
    """恰好 16:00 ET 视为已收盘 ⇒ 当日 ✓（边界含端点）。"""
    now = dt.datetime(2026, 10, 20, 16, 0, tzinfo=sp.TZ_ET)
    assert sp.trading_date(now) == "2026-10-20"


def test_one_minute_before_close_uses_prev_day():
    """15:59 ET ⇒ 未收盘 ⇒ 上一工作日 ✓"""
    now = dt.datetime(2026, 10, 20, 15, 59, tzinfo=sp.TZ_ET)
    assert sp.trading_date(now) == "2026-10-19"


# ------------------------------------------- ② 周末 / 工作日回退
def test_weekend_before_close_falls_back_to_friday():
    """美东周六 12:00 ⇒ 周五 ✓"""
    now = dt.datetime(2026, 10, 24, 12, 0, tzinfo=sp.TZ_ET)
    assert sp.trading_date(now) == "2026-10-23"   # Fri


def test_weekend_after_close_still_falls_back():
    """美东周六 17:00（已过收盘线但当天非交易日）⇒ 仍回退到周五 ✓"""
    now = dt.datetime(2026, 10, 24, 17, 0, tzinfo=sp.TZ_ET)
    assert sp.trading_date(now) == "2026-10-23"


def test_monday_premarket_uses_friday():
    """美东周一 10:00（未收盘）⇒ 上周五 ✓"""
    now = dt.datetime(2026, 10, 26, 10, 0, tzinfo=sp.TZ_ET)
    assert sp.trading_date(now) == "2026-10-23"


def test_prev_business_day_rollback():
    assert sp._prev_business_day(dt.date(2026, 10, 25)).isoformat() == "2026-10-23"  # Sun→Fri
    assert sp._prev_business_day(dt.date(2026, 10, 26)).isoformat() == "2026-10-23"  # Mon→Fri
    assert sp._prev_business_day(dt.date(2026, 10, 20)).isoformat() == "2026-10-19"  # Tue→Mon


# ------------------------------------------- ③ 结果永不为周末（旧口径的核心缺陷）
def test_never_weekend_across_a_full_week():
    """连续 7 天 × 4 个时刻运行，结果必须落在周一~周五 ✓。

    旧口径（`dt.date.today()`）会把周六 / 周日原样写成快照日期 ✗ ——
    实测 `accounts.csv` 就有 10-10 / 10-11 / 10-17 / 10-18 ✗。
    """
    for day in range(18, 25):                     # 2026-10-18(Sun) ~ 10-24(Sat)
        for hour in (3, 10, 16, 22):
            now = dt.datetime(2026, 10, day, hour, 0, tzinfo=sp.TZ_ET)
            d = dt.date.fromisoformat(sp.trading_date(now))
            assert d.weekday() < 5, f"{now} → {d} 落在周末"


def test_matches_features_csv_basis_on_real_boundaries():
    """真实边界：北京时间凌晨跑（本地日期已 +1）不得领先 => 与美东交易日一致 ✓。"""
    # 北京 10-21 00:30 = 美东 10-20 12:30（未收盘）⇒ 10-19（10-20 尚未收盘）
    assert sp.trading_date(_et("2026-10-21 00:30")) == "2026-10-19"
    # 北京 10-21 05:30 = 美东 10-20 17:30（已收盘）⇒ 10-20 ✓
    assert sp.trading_date(_et("2026-10-21 05:30")) == "2026-10-20"


# ------------------------------------------- ④ note 口径标注
def test_note_tagged_from_switch_date():
    assert sp._tag_date_basis("富途动态同步", "2026-10-20").endswith(sp.DATE_BASIS_NOTE)
    assert sp._tag_date_basis("OKX 动态同步", "2026-10-21").endswith(sp.DATE_BASIS_NOTE)


def test_note_untouched_before_switch_date():
    """切换点之前的行不加标注（保留历史原貌 ✓）。"""
    assert sp._tag_date_basis("富途动态同步", "2026-10-19") == "富途动态同步"


def test_today_alias_removed():
    """旧名 `today()` 必须已移除 —— 保留它会让人误用本地日期 ✗。"""
    assert not hasattr(sp, "today"), "`today()` 应已改名为 `trading_date()`"


# ===== MT-48（2026-10-20 P0）：失败仍写盘 + 缺字段静默写 0 =====
def test_req_f_missing_records_error_and_returns_none():
    """必需字段缺失 ⇒ 不默认 0、而是返回 None 并记录错误（main 据此中止写盘）。"""
    sp._SYNC_ERRORS.clear()
    assert sp._req_f(None, "total_assets", "futu") is None
    assert sp._req_f("", "cash", "okx") is None
    assert any("total_assets" in e for e in sp._SYNC_ERRORS)
    assert any("cash" in e for e in sp._SYNC_ERRORS)


def test_req_f_normal_value_returns_float():
    """正常值仍转 float 返回（不污染错误列表）。"""
    sp._SYNC_ERRORS.clear()
    assert sp._req_f("123.45", "totalEq", "okx") == 123.45
    assert sp._req_f(100, "cash", "futu") == 100.0
    assert sp._SYNC_ERRORS == []


def test_req_f_non_numeric_records_error():
    """非数值字符串 ⇒ 记录错误并返回 None（不静默转 0）。"""
    sp._SYNC_ERRORS.clear()
    assert sp._req_f("N/A", "market_val", "futu") is None
    assert sp._SYNC_ERRORS, "应记录 market_val 非数值错误"


def test_futu_required_fields_no_longer_default_zero():
    """回归保护：futu 的 total_assets/cash/market_val 不再用 `_f(x, 0.0)` 默认 0。

    MT-48 根因：旧版 `_f(r.get("total_assets", 0))` 把缺失字段写成 0 ⇒
    net_value=0、恒等式恒不成立。现在用 `_req_f`，缺失即中止。
    """
    import inspect
    src = inspect.getsource(sp.sync_futu)
    # 不应再出现 _f(r.get("total_assets", 0)) 这种默认 0 写法
    assert '_f(r.get("total_assets", 0))' not in src
    assert '_f(r.get("cash", 0))' not in src
    assert '_f(r.get("market_val", 0))' not in src


def test_main_uses_sys_exit():
    """main() 必须返回 int 退出码（sys.exit(main()) 让失败 rc=1）。"""
    import inspect
    src = inspect.getsource(sp)
    assert "sys.exit(main())" in src
    # main 内部必须 return 1（硬错误/无新行/恒等式失败）和 return 0（成功）
    assert "return 1" in inspect.getsource(sp.main)
    assert "return 0" in inspect.getsource(sp.main)
