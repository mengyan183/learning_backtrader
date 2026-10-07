# -*- coding: utf-8 -*-
"""看板数据新鲜度检查与按需后台刷新（2026-10-07 落地）。

需求（用户）：网页每次刷新时，若底层文件「最新时间」与「刷新时间」不匹配
（文件明显过期），触发系统更新底层文件，避免用户一直看到陈旧数据。

纪律（既有，必须维持，见 server.py docstring / tests 守卫）：
1. 守猪待兔**绝不无条件抓取**：`append_records` 对同一 `(date, symbol)` 是
   覆盖语义 ⇒ 每次刷新都抓 = 污染当天样本（§14.5 实际发生过）；`query_api`
   额度 5000/月。⇒ 仅当**当天快照缺失** 且数据过期时才补抓**一次**，
   当天已有记录则跳过（不覆盖）。
2. 默认静态模式（FG_SYNC_MODE 默认 static）：sync_positions 不调用外部 API
   （公司电脑只跑静态数据）。
3. 触发必须**后台异步 + 节流**（默认 10 分钟）；失败只写日志，不影响页面。
"""
import os
import subprocess
import threading
import time
from datetime import datetime

import pandas as pd

from fg_system import config

_LOG = "/tmp/fg_dashboard_fresh.log"
_THROTTLE_SEC = 600          # 两次触发的间隔下限（10 分钟）
_REFRESH_GRACE_DAYS = 3      # features/行情允许的最大滞后（跳过周末/节假日宽限）

_state = {"last_trigger": 0.0, "running": False}
_lock = threading.Lock()


def _log(msg):
    try:
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


# ---------------------------------------------------------------- 新鲜度判定
def _last_date(path, col="date"):
    """CSV 的 max(date)；文件缺失/解析失败返回 None。"""
    try:
        if not os.path.isfile(path):
            return None
        d = pd.read_csv(path, usecols=[col], parse_dates=[col])
        return d[col].max() if len(d) else None
    except Exception:
        return None


def _today():
    return pd.Timestamp.now().normalize()


def _recent_trading_day(days_ago=0):
    """今天（或往前第 days_ago 个）**最近交易日**（跳过周末；节假日由宽限期兜底）。"""
    d = _today() - pd.Timedelta(days=days_ago)
    while d.weekday() >= 5:
        d -= pd.Timedelta(days=1)
    return d


def _is_stale(csv_date, reference):
    """csv_date 是否明显落后于 reference（reference 为最近交易日/今天）。"""
    if csv_date is None:
        return True
    return (reference - csv_date) > pd.Timedelta(days=_REFRESH_GRACE_DAYS)


# ---------------------------------------------------------------- 触发更新
def _run_refresh():
    """后台线程：按过期情况触发底层文件更新。只写日志，异常不抛出。"""
    global _state
    try:
        _log("刷新触发开始")
        # 1) 行情价格 + 指数（增量/幂等，安全）
        from fg_system.data import fetch
        px, added = fetch.update_prices()
        fetch.update_indices()
        _log("行情更新完成，新增行数=%s" % {k: v for k, v in added.items() if v})
        # 2) 持仓快照（默认 static 模式：不调外部 API；live 环境由每日链负责）
        subprocess.run(
            [sys_python(), str(config.ROOT) + "/scripts/sync_positions.py"],
            env={**os.environ, "FG_SYNC_MODE": "static"},
            timeout=180)
        _log("持仓快照同步(static)完成")
        # 3) 守猪待兔：仅当天快照缺失时补抓一次（绝不覆盖已有当天记录）
        st = _last_date(os.path.join(config.DATA_DIR, "raw", "shoutu_fng.csv"))
        if st is None or st.date() < _today().date():
            subprocess.run(
                [sys_python(), str(config.ROOT) + "/scripts/fetch_shoutu_api.py",
                 "--date", _today().strftime("%Y-%m-%d")],
                timeout=180)
            _log("守猪待兔补抓 %s 完成" % _today().strftime("%Y-%m-%d"))
        else:
            _log("守猪待兔当天快照已存在(%s)，跳过（防覆盖/耗额度）" % st.date())
        _log("刷新触发完成")
    except Exception as e:
        _log("刷新触发失败: %r" % e)


def sys_python():
    """优先仓库 venv 的 python，其次系统 python。"""
    venv = os.path.join(config.ROOT, ".venv", "bin", "python")
    return venv if os.path.isfile(venv) else sys.executable


def check_and_refresh():
    """入口（GET 请求时调用）：过期则后台触发更新，节流 + 防重入。

    返回本次是否触发了刷新（供页面提示用）。
    """
    with _lock:
        now = time.time()
        if _state["running"] or (now - _state["last_trigger"]) < _THROTTLE_SEC:
            return False
        # 只检查**需要写盘类**数据的新鲜度：
        #   - 行情/指数（prices.csv、features.csv 的输入）
        px = _last_date(os.path.join(config.RAW_DIR, "prices.csv"))
        if not _is_stale(px, _recent_trading_day()):
            # 行情新鲜 → 底层无需刷新（持仓/守猪待兔由每日链与常驻服务负责）
            return False
        _state["running"] = True
        threading.Thread(target=_run_refresh, daemon=True).start()
        _log("已触发后台刷新（prices 最后日期=%s）" % px)
        return True
