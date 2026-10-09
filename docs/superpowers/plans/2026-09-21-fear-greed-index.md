# 贪婪恐惧指数交易纪律系统 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个自建多因子贪婪恐惧指数（0-100），并以其为唯一决策源输出仓位指令，配合交易纪律审计，把人的裁量权压缩到"只负责执行"。

**Architecture:** pandas 预计算全链路（数据 → 因子 → 指数 → 目标仓位）+ backtrader 只做执行与评估。`signal` 层是纯函数 + 显式状态，保证回测与日常运行逻辑完全一致。所有情绪因子的输入是**无杠杆标的**（QQQ/SOXX/SPY），杠杆 ETF 价格仅用于成交与损耗归因。

**Tech Stack:** Python 3.10、pandas、numpy、backtrader 1.9.78、pytest、Plotly（仪表盘）

**参考设计文档：** `docs/superpowers/specs/2026-09-21-fear-greed-index-design.md`（以下简称 §N）

**环境约定：**
- Python：`C:\Users\260023\AppData\Local\Programs\Python\Python310\python.exe`
- 通用外网代理：`http://10.30.6.49:9090`（pip 用 `10.1.82.22:3128`）
- 所有输出文件编码 UTF-8
- 所有 `.sh` 脚本换行符用 LF

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `fg_system/config.py` | 全部参数集中一处（§16） |
| `fg_system/data/fetch.py` | 抓取 Nasdaq/CBOE 并增量落盘（§4.1–4.2） |
| `fg_system/data/loader.py` | 读取、日期规范化、对齐、拆股异常检测（§4.2–4.4） |
| `fg_system/factors/base.py` | `Factor` 抽象基类 + 滚动分位归一化工具（§5.1、5.3） |
| `fg_system/factors/vix.py` | F1 VIX 水位与变化率（§5.2） |
| `fg_system/factors/term.py` | F2 波动率期限结构 VIX/VIX3M（§5.2） |
| `fg_system/factors/price.py` | F3 价格因子（动量/RSI/回撤/波动率，输入 QQQ）（§5.2） |
| `fg_system/factors/breadth.py` | F4 广度代理（RSP/SPY、QQQ/SPY、均线宽度）（§5.2） |
| `fg_system/index.py` | 因子加权合成 `fg_index`（§5.4） |
| `fg_system/signal.py` | 指数 + 回撤 → 目标仓位（五档 + 弹药池 + 极端规则 + 防抖动）（§7–9） |
| `fg_system/leverage.py` | 损耗归因与损耗速率（§4.5） |
| `fg_system/pipeline.py` | 编排全链路 → `Data/features.csv`（§3.3） |
| `fg_system/backtest/feed.py` | `FgPandasData` 扩展 line（§11.1） |
| `fg_system/backtest/strategy.py` | `FgStrategy` 只读目标仓位下单（§11.2） |
| `fg_system/backtest/runner.py` | cerebro 装配 + 基准 + 评估指标（§11.4–11.6） |
| `fg_system/dashboard/report.py` | 自包含 HTML 仪表盘（§12） |
| `fg_system/audit.py` | 交易记录 vs 指令 → 违规报告（§13.2） |
| `fg_system/cli.py` | `pipeline \| backtest \| report \| audit`（§3.2） |
| `tests/` | 与源码同构的测试目录 |

---

## Task 1: 项目骨架与配置层

**Files:**
- Create: `fg_system/__init__.py`
- Create: `fg_system/config.py`
- Create: `tests/__init__.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_config.py
# -*- coding: utf-8 -*-
"""配置层测试：参数完整性与内部一致性。"""
import pytest

from fg_system import config


def test_weights_sum_to_one():
    assert sum(config.WEIGHTS.values()) == pytest.approx(1.0)


def test_zone_saturation_length_matches_edges():
    # 5 档 = 4 个边界
    assert len(config.ZONE_SATURATION) == len(config.ZONE_EDGES) + 1


def test_core_and_ammo_caps_within_total():
    assert config.CORE_CAP + config.AMMO_CAP == pytest.approx(1.0)


def test_ammo_batches_descending():
    # 回撤触发点必须递增（20% < 40% < 60%）
    assert config.DRAWDOWN_BATCHES == sorted(config.DRAWDOWN_BATCHES)


def test_ammo_total_matches_cap():
    assert config.AMMO_PER_BATCH * len(config.DRAWDOWN_BATCHES) == pytest.approx(config.AMMO_CAP)


def test_underlying_map_covers_all_symbols():
    assert set(config.UNDERLYING_MAP.keys()) == set(config.SYMBOLS)


def test_leverage_ratio_covers_all_symbols():
    assert set(config.LEVERAGE_RATIO.keys()) == set(config.SYMBOLS)


def test_extreme_greed_thresholds_ordered():
    assert config.EXTREME_GREED_TRIGGER > config.EXTREME_GREED_UNLOCK_INDEX
    assert config.EXTREME_FEAR_TRIGGER < config.EXTREME_GREED_UNLOCK_INDEX


def test_sample_periods_not_overlapping():
    assert config.IS_END < config.OOS_START
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fg_system'`

- [ ] **Step 3: 实现配置层**

```python
# fg_system/__init__.py
# -*- coding: utf-8 -*-
"""贪婪恐惧指数交易纪律系统。"""
__version__ = "0.1.0"
```

```python
# fg_system/config.py
# -*- coding: utf-8 -*-
"""全部参数集中一处。修改任何参数前必须走 docs/trading-discipline.md 第 8 条流程。"""
import os

# ---------------------------------------------------------------- 路径
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "Data")
RAW_DIR = os.path.join(DATA_DIR, "raw")
FEATURES_PATH = os.path.join(DATA_DIR, "features.csv")
STATE_PATH = os.path.join(DATA_DIR, "state.json")
TRADE_LOG_PATH = os.path.join(DATA_DIR, "trade_log.csv")
REPORTS_DIR = os.path.join(ROOT, "reports")
EXTERNAL_INDEX_PATH = os.path.join(RAW_DIR, "external_index.csv")

# ---------------------------------------------------------------- 网络
# 通用外网代理（PAC 指定）。pip 用 10.1.82.22:3128，见设计文档 §4.1。
PROXY = os.environ.get("FG_PROXY", "http://10.30.6.49:9090")
NASDAQ_API = "https://api.nasdaq.com/api/quote/{symbol}/historical"
CBOE_CDN = "https://cdn.cboe.com/api/global/us_indices/daily_prices/{name}_History.csv"

# ---------------------------------------------------------------- 标的
SYMBOLS = ["TQQQ", "SOXL", "UPRO"]
UNDERLYING_MAP = {"TQQQ": "QQQ", "SOXL": "SOXX", "UPRO": "SPY"}
LEVERAGE_RATIO = {"TQQQ": 3, "SOXL": 3, "UPRO": 3}
BREADTH_SYMBOLS = ["SPY", "QQQ", "RSP", "IWM"]
FETCH_SYMBOLS = ["TQQQ", "SOXL", "UPRO", "QQQ", "SOXX", "SMH", "SPY", "RSP", "IWM"]

# 产品损耗率（费用+融资+跟踪误差），2016-2026 实测标定，须定期重标定（§17 风险 12）
PRODUCT_COST_RATE = {"TQQQ": 0.0822, "SOXL": 0.0895, "UPRO": 0.0395}

# ---------------------------------------------------------------- 因子
RANK_WINDOW = 756          # 滚动百分位窗口（3 年）
WARMUP_DAYS = 756          # 信号生效前预热期
WEIGHTS = {"vix": 0.30, "term": 0.20, "price": 0.30, "breadth": 0.20}
MIN_VALID_FACTORS = 2      # 有效因子数少于此值则当日不产生信号

# ---------------------------------------------------------------- 资金结构
CORE_CAP = 0.70            # 核心仓上限
AMMO_CAP = 0.30            # 弹药仓上限
ZONE_EDGES = [20, 40, 60, 80]
ZONE_SATURATION = [1.00, 0.75, 0.50, 0.25, 0.00]
DRAWDOWN_BATCHES = [0.20, 0.40, 0.60]
AMMO_PER_BATCH = 0.10
DRAWDOWN_LOOKBACK = 252    # 回撤基准滚动窗口（52 周）

# ---------------------------------------------------------------- 极端规则
EXTREME_GREED_TRIGGER = 85
EXTREME_GREED_FLOOR = 0.25
EXTREME_GREED_BLOCK_DAYS = 3
EXTREME_GREED_UNLOCK_INDEX = 60
EXTREME_GREED_UNLOCK_REBOUND = 0.10
EXTREME_GREED_UNLOCK_DROP = 15
EXTREME_FEAR_TRIGGER = 10
EXTREME_FEAR_COOLDOWN = 60

# ---------------------------------------------------------------- 防抖动
REBALANCE_THRESHOLD = 0.10
REBALANCE_COOLDOWN = 5
MAX_SINGLE_ADJUST = 0.30

# ---------------------------------------------------------------- 数据质量
SPLIT_DEVIATION_THRESHOLD = 0.15   # |杠杆ETF收益 − N×标的收益| 阈值（§4.4 主检测）
SPLIT_JUMP_THRESHOLD = 0.70        # 绝对兜底阈值（§4.4 辅助检测）
SPLIT_CONTINUITY_TOLERANCE = 0.05  # 拆股日前后连续性容差（§14.6）
STALE_MAX_DAYS = 5                 # 前向填充最大天数，超过则该因子置 NaN

# ---------------------------------------------------------------- 回测
COMMISSION = 0.0003
SLIPPAGE = 0.0005
INITIAL_CASH = 1_000_000.0
WEIGHTING = "equal"                # v1 等权；v2 可改 "factor"
IS_START = "2017-01-01"            # 样本内起点（warmup 756 交易日后）
IS_END = "2022-12-31"
OOS_START = "2023-01-01"           # 样本外起点（禁止调参）

SMOOTHING_DAYS = 1                 # v1 不平滑
VOL_GATE_OBSERVE = True            # v1 仅观测损耗速率，不参与仓位计算（§4.5 约束 4）
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_config.py -v`
Expected: 9 passed

- [ ] **Step 5: 提交**

```bash
git add fg_system/ tests/
git commit -m "feat: 项目骨架与配置层" # user-confirmed-commit
```

---

## Task 2: 数据加载与规范化

**Files:**
- Create: `fg_system/data/__init__.py`
- Create: `fg_system/data/loader.py`
- Create: `tests/data/__init__.py`
- Create: `tests/data/test_loader.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/data/test_loader.py
# -*- coding: utf-8 -*-
"""数据加载测试：日期规范化、升序、缺口检测、异常跳变检测。"""
import io
import os

import pandas as pd
import pytest

from fg_system.data import loader


def _write(tmp_path, text, name="prices.csv"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_normalize_dates_handles_mm_dd_yyyy_and_sorts_ascending(tmp_path):
    """Nasdaq 原始格式 MM/DD/YYYY 且降序，必须转成 YYYY-MM-DD 升序。"""
    csv = (
        "date,symbol,open,high,low,close,volume\n"
        "01/03/2024,QQQ,400,401,399,400.5,1000\n"
        "01/02/2024,QQQ,398,400,397,399.0,900\n"
    )
    df = loader.load_prices(_write(tmp_path, csv))
    assert df["date"].is_monotonic_increasing
    assert df["date"].iloc[0] == pd.Timestamp("2024-01-02")
    assert df["date"].iloc[1] == pd.Timestamp("2024-01-03")


def test_normalize_dates_parses_ambiguous_day_correctly(tmp_path):
    """01/02/2024 必须解析为 1 月 2 日（MM/DD），不是 2 月 1 日。"""
    csv = "date,symbol,open,high,low,close,volume\n01/02/2024,QQQ,398,400,397,399.0,900\n"
    df = loader.load_prices(_write(tmp_path, csv))
    assert df["date"].iloc[0] == pd.Timestamp("2024-01-02")
    assert df["date"].iloc[0].month == 1


def test_duplicate_rows_are_dropped(tmp_path):
    csv = (
        "date,symbol,open,high,low,close,volume\n"
        "01/02/2024,QQQ,398,400,397,399.0,900\n"
        "01/02/2024,QQQ,398,400,397,399.0,900\n"
    )
    df = loader.load_prices(_write(tmp_path, csv))
    assert len(df) == 1


def test_split_deviation_detects_unadjusted_split(tmp_path):
    """构造未复权的 2:1 拆股（杠杆 ETF −50%，标的 0%），必须被拦截。"""
    rows = ["date,symbol,open,high,low,close,volume"]
    for i in range(3):
        rows.append("01/0%d/2024,QQQ,100,101,99,100,1000" % (i + 2))
    rows += [
        "01/02/2024,TQQQ,300,301,299,300,1000",
        "01/03/2024,TQQQ,150,151,149,150,2000",  # 拆股未复权
        "01/04/2024,TQQQ,151,152,150,151,1000",
    ]
    with pytest.raises(loader.DataQualityError, match="异常跳变"):
        loader.check_split_anomalies(loader.load_prices(_write(tmp_path, "\n".join(rows) + "\n")))


def test_real_extreme_move_is_not_flagged(tmp_path):
    """SOXL 2025-04-09 真实 +54.79%（标的 SOXX +18.57%）必须放行。"""
    rows = [
        "date,symbol,open,high,low,close,volume",
        "04/08/2025,SOXX,180,181,179,180,1000",
        "04/09/2025,SOXX,213,214,212,213.4,1000",   # +18.57%
        "04/08/2025,SOXL,20,20.1,19.9,20,1000",
        "04/09/2025,SOXL,31,31.1,30.9,30.96,1000",  # +54.79%
    ]
    loader.check_split_anomalies(loader.load_prices(_write(tmp_path, "\n".join(rows) + "\n")))


def test_missing_symbol_raises(tmp_path):
    csv = "date,symbol,open,high,low,close,volume\n01/02/2024,QQQ,1,1,1,1,1\n"
    with pytest.raises(loader.DataQualityError, match="缺少标的"):
        loader.load_prices(_write(tmp_path, csv), required_symbols=["TQQQ"])


def test_wide_table_aligns_on_primary_calendar(tmp_path):
    """宽表以主日历（SPY 交易日）为基准，缺数据处为 NaN 而非前向填充。"""
    csv = (
        "date,symbol,open,high,low,close,volume\n"
        "01/02/2024,SPY,100,101,99,100,1000\n"
        "01/03/2024,SPY,101,102,100,101,1000\n"
        "01/02/2024,QQQ,400,401,399,400,1000\n"
    )
    wide = loader.to_wide(loader.load_prices(_write(tmp_path, csv)))
    assert list(wide.index) == [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03")]
    # QQQ 在 01-03 无数据，缺口必须是 NaN（禁止前向填充）
    assert pd.isna(wide.loc[pd.Timestamp("2024-01-03"), ("QQQ", "close")])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/data/test_loader.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fg_system.data'`

- [ ] **Step 3: 实现加载层**

```python
# fg_system/data/__init__.py
# -*- coding: utf-8 -*-
```

```python
# fg_system/data/loader.py
# -*- coding: utf-8 -*-
"""数据加载、规范化与质量校验。

设计依据：§4.2 格式规则、§4.3 对齐与缺失、§4.4 拆股异常检测。
"""
import pandas as pd

from fg_system import config


class DataQualityError(Exception):
    """数据质量问题。pipeline 遇到此异常必须中止（fail fast）。"""


PRICE_COLUMNS = ["date", "symbol", "open", "high", "low", "close", "volume"]


def load_prices(path=None, required_symbols=None):
    """读取长表价格数据并规范化。

    - 日期解析：优先按 MM/DD/YYYY（Nasdaq 原始格式）解析，失败再按 ISO 解析
    - 排序：按 (symbol, date) 升序
    - 去重：同 (symbol, date) 只保留最后一条
    """
    path = path or f"{config.RAW_DIR}/prices.csv"
    df = pd.read_csv(path, dtype={"symbol": str})
    missing = [c for c in PRICE_COLUMNS if c not in df.columns]
    if missing:
        raise DataQualityError("价格文件缺少列: %s" % missing)

    df["date"] = _parse_dates(df["date"])
    df = (
        df.dropna(subset=["date"])
        .drop_duplicates(subset=["symbol", "date"], keep="last")
        .sort_values(["symbol", "date"])
        .reset_index(drop=True)
    )
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    required = required_symbols if required_symbols is not None else config.SYMBOLS
    absent = [s for s in required if s not in set(df["symbol"])]
    if absent:
        raise DataQualityError("缺少标的: %s" % absent)
    return df


def _parse_dates(series):
    """按 MM/DD/YYYY 解析（Nasdaq 口径），失败回退 ISO。"""
    out = pd.to_datetime(series, format="%m/%d/%Y", errors="coerce")
    fallback = out.isna()
    if fallback.any():
        out.loc[fallback] = pd.to_datetime(series[fallback], errors="coerce")
    return out


def to_wide(df, primary_symbol="SPY", value="close"):
    """转成以主日历为索引的宽表：index=交易日，columns=(symbol, field)。

    主日历取 primary_symbol 的交易日；其他标的左连接，缺数据处为 NaN（**不前向填充**，§4.3）。
    """
    wide = df.pivot_table(index="date", columns="symbol", values=value, aggfunc="last")
    if primary_symbol in wide.columns:
        calendar = wide[primary_symbol].dropna().index
        wide = wide.reindex(calendar)
    return wide.sort_index()


def to_wide_ohlcv(df, primary_symbol="SPY"):
    """多字段宽表：columns 为 MultiIndex (symbol, field)。"""
    frames = []
    for field in ["open", "high", "low", "close", "volume"]:
        w = df.pivot_table(index="date", columns="symbol", values=field, aggfunc="last")
        w.columns = pd.MultiIndex.from_product([w.columns, [field]], names=["symbol", "field"])
        frames.append(w)
    wide = pd.concat(frames, axis=1).sort_index()
    if (primary_symbol, "close") in wide.columns:
        wide = wide.reindex(wide[(primary_symbol, "close")].dropna().index)
    return wide.sort_index()


def check_split_anomalies(df):
    """拆股/合股异常检测（§4.4）。

    主检测：|杠杆ETF单日收益 − N×标的单日收益| > SPLIT_DEVIATION_THRESHOLD
    辅助检测：|N × 标的单日收益| > SPLIT_JUMP_THRESHOLD（兜底对象是"3×标的"一侧，不是杠杆 ETF 自身）
    """
    problems = []
    for lev, und in config.UNDERLYING_MAP.items():
        n = config.LEVERAGE_RATIO[lev]
        sub = df[df["symbol"].isin([lev, und])]
        lev_s = sub[sub["symbol"] == lev].set_index("date")["close"].sort_index()
        und_s = sub[sub["symbol"] == und].set_index("date")["close"].sort_index()
        lev_r = lev_s.pct_change()
        und_r = und_s.reindex(lev_r.index).pct_change()

        dev = (lev_r - n * und_r).abs()
        for dt, v in dev[dev > config.SPLIT_DEVIATION_THRESHOLD].items():
            problems.append(
                "%s %s: %s 收益 %+.2f%% 与 %d×%s 收益 %+.2f%% 偏离 %.2fpp"
                % (
                    lev, dt.date(), lev, lev_r.loc[dt] * 100, n, und,
                    (und_r.loc[dt] or 0) * 100, v * 100,
                )
            )
        for dt, v in lev_r[lev_r.abs() > config.SPLIT_JUMP_THRESHOLD].items():
            problems.append("%s %s: 单日收益 %+.2f%% 超绝对兜底阈值" % (lev, dt.date(), v * 100))

    if problems:
        raise DataQualityError(
            "异常跳变（疑似未复权或数据错误），pipeline 中止：\n  " + "\n  ".join(problems)
        )
    return True


def health_report(df):
    """数据健康检查报告（§4.4 第 8 条）。"""
    lines = []
    for sym in sorted(df["symbol"].unique()):
        s = df[df["symbol"] == sym].sort_values("date")
        r = s["close"].pct_change()
        worst = r.abs().idxmax() if r.notna().any() else None
        lines.append(
            {
                "symbol": sym,
                "rows": len(s),
                "start": s["date"].min().strftime("%Y-%m-%d"),
                "end": s["date"].max().strftime("%Y-%m-%d"),
                "max_abs_chg": float(r.loc[worst]) if worst is not None else float("nan"),
                "max_chg_date": s["date"].loc[worst].strftime("%Y-%m-%d") if worst is not None else "",
            }
        )
    return pd.DataFrame(lines)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/data/test_loader.py -v`
Expected: 7 passed

- [ ] **Step 5: 提交**

```bash
git add fg_system/data/ tests/data/
git commit -m "feat: 数据加载、日期规范化与拆股异常检测" # user-confirmed-commit
```

---

## Task 3: 拆股记录与连续性校验

**Files:**
- Create: `fg_system/data/splits.py`
- Create: `Data/raw/splits.csv`
- Create: `tests/data/test_splits.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/data/test_splits.py
# -*- coding: utf-8 -*-
"""拆股记录与连续性校验测试（§4.4、§14.6）。"""
import pandas as pd
import pytest

from fg_system.data import splits


def test_ratio_semantics_split_vs_reverse():
    assert splits.classify(2.0) == "split"
    assert splits.classify(0.2) == "reverse_split"
    assert splits.classify(1.0) == "none"


def test_continuity_passes_for_adjusted_series(tmp_path):
    """复权后拆股日前后应连续。"""
    csv = (
        "date,symbol,open,high,low,close,volume\n"
        "01/12/2021,TQQQ,22.7,23.0,22.0,22.635,146031440\n"
        "01/13/2021,TQQQ,22.6,23.2,22.5,23.075,108750000\n"
    )
    p = tmp_path / "prices.csv"
    p.write_text(csv, encoding="utf-8")
    sp = pd.DataFrame(
        [{"symbol": "TQQQ", "date": "2021-01-21", "ratio": 2.0, "source": "test", "verified": 1}]
    )
    assert splits.check_continuity(str(p), sp) is True


def test_continuity_fails_for_unadjusted_series(tmp_path):
    """未复权序列在拆股日会出现 ~-50% 跳空，必须报错。"""
    csv = (
        "date,symbol,open,high,low,close,volume\n"
        "01/12/2021,TQQQ,330,331,329,330,1000\n"
        "01/13/2021,TQQQ,165,166,164,165,2000\n"
    )
    p = tmp_path / "prices.csv"
    p.write_text(csv, encoding="utf-8")
    sp = pd.DataFrame(
        [{"symbol": "TQQQ", "date": "2021-01-21", "ratio": 2.0, "source": "test", "verified": 1}]
    )
    with pytest.raises(splits.SplitContinuityError):
        splits.check_continuity(str(p), sp)


def test_only_verified_events_are_checked(tmp_path):
    """verified=0 的事件不参与校验。"""
    csv = (
        "date,symbol,open,high,low,close,volume\n"
        "01/12/2021,TQQQ,330,331,329,330,1000\n"
        "01/13/2021,TQQQ,165,166,164,165,2000\n"
    )
    p = tmp_path / "prices.csv"
    p.write_text(csv, encoding="utf-8")
    sp = pd.DataFrame(
        [{"symbol": "TQQQ", "date": "2021-01-21", "ratio": 2.0, "source": "test", "verified": 0}]
    )
    assert splits.check_continuity(str(p), sp) is True
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/data/test_splits.py -v`
Expected: FAIL — `ImportError: cannot import name 'splits'`

- [ ] **Step 3: 实现拆股模块**

```python
# fg_system/data/splits.py
# -*- coding: utf-8 -*-
"""拆股/合股事件记录与连续性校验（§4.4）。"""
import pandas as pd

from fg_system import config

SPLIT_COLUMNS = ["symbol", "date", "ratio", "source", "verified"]


class SplitContinuityError(Exception):
    """拆股日前后价格不连续，说明复权失效。"""


def classify(ratio):
    """ratio 语义（§4.4 第 3 条）：>1 拆股，<1 合股，=1 无事件。"""
    if ratio > 1:
        return "split"
    if ratio < 1:
        return "reverse_split"
    return "none"


def load(path=None):
    path = path or f"{config.RAW_DIR}/splits.csv"
    try:
        df = pd.read_csv(path, dtype={"symbol": str})
    except FileNotFoundError:
        return pd.DataFrame(columns=SPLIT_COLUMNS)
    if df.empty:
        return pd.DataFrame(columns=SPLIT_COLUMNS)
    df["date"] = pd.to_datetime(df["date"])
    df["verified"] = pd.to_numeric(df["verified"], errors="coerce").fillna(0).astype(int)
    return df


def check_continuity(prices_path, split_df, tolerance=None):
    """校验每个 verified 事件的拆股日前后涨跌幅在容差内（§14.6 第 1 条）。"""
    tolerance = tolerance if tolerance is not None else config.SPLIT_CONTINUITY_TOLERANCE
    if split_df is None or split_df.empty:
        return True
    prices = pd.read_csv(prices_path)
    prices["date"] = pd.to_datetime(prices["date"], format="%m/%d/%Y", errors="coerce")
    prices.loc[prices["date"].isna(), "date"] = pd.to_datetime(
        prices.loc[prices["date"].isna(), "date"], errors="coerce"
    )

    bad = []
    for _, ev in split_df[split_df["verified"] == 1].iterrows():
        s = prices[prices["symbol"] == ev["symbol"]].sort_values("date")
        s = s.set_index("date")["close"]
        if ev["date"] not in s.index:
            continue
        pos = s.index.get_loc(ev["date"])
        if pos == 0:
            continue
        chg = abs(s.iloc[pos] / s.iloc[pos - 1] - 1)
        if chg > tolerance:
            bad.append(
                "%s %s: 拆股日涨跌 %.2f%% 超容差 %.2f%%（复权可能失效）"
                % (ev["symbol"], ev["date"].date(), chg * 100, tolerance * 100)
            )
    if bad:
        raise SplitContinuityError("拆股连续性校验失败：\n  " + "\n  ".join(bad))
    return True
```

- [ ] **Step 4: 生成真实的 `Data/raw/splits.csv`**

用 `scripts/fetch_market_data.py` 的 Nasdaq 拆股接口拉取 TQQQ/SOXL/UPRO/QQQ/SOXX/SPY 的拆股事件，落盘为 `symbol,date,ratio,source,verified`，其中 `source=nasdaq`，**`verified` 先全部置 0**。

然后人工核对（对照公开拆股记录），把确认无误的事件改为 `verified=1`。

**已知需核对的事件（经 OCC 官方 memo 与富途新闻核实）**：

| 标的 | 拆股日 | 比例 | 是否在数据区间内 | 依据 |
|---|---|---|---|---|
| TQQQ | **2021-01-21** | 2:1 | ✅ 在区间内（2016-09 起） | OCC memo 48190、富途新闻 |

**⚠️ 重要教训**：初版本文档曾把 TQQQ 拆股日误记为 **2021-01-13**，实际 ex-date 为 **2021-01-21**。**拆股日期必须来自官方记录（OCC memo / 交易所公告），禁止凭记忆填写。** 其余历史拆股事件（2011-02-25 等）均在数据区间之外，标注为"区间外"不参与校验。

**注意**：Nasdaq 全站不提供拆股事件数据（`/splits` 端点 404、`/dividends` 只返回 Cash 类型），因此该表**只能人工维护**。这决定了 §4.4 第 4 条的**数据驱动检测才是主防线**，本表是人工补充的精确校验。

- [ ] **Step 5: 跑测试 + 对真实数据校验**

Run: `python -m pytest tests/data/test_splits.py -v`
Expected: 3 passed

Run: `python -c "from fg_system.data import splits; print(splits.check_continuity('Data/raw/prices.csv', splits.load()))"`
Expected: `True`（真实数据已复权，应通过）

- [ ] **Step 6: 提交**

```bash
git add fg_system/data/splits.py tests/data/test_splits.py Data/raw/splits.csv
git commit -m "feat: 拆股事件记录与连续性校验" # user-confirmed-commit
```

---

## Task 4: 数据抓取与增量更新

**Files:**
- Create: `fg_system/data/fetch.py`
- Create: `tests/data/test_fetch.py`

- [ ] **Step 1: 写失败的测试（离线，不打网络）**

```python
# tests/data/test_fetch.py
# -*- coding: utf-8 -*-
"""抓取层测试：解析与增量合并逻辑（不依赖网络）。"""
import pandas as pd
import pytest

from fg_system.data import fetch


NASDAQ_ROW = {"date": "09/18/2026", "close": "72.64", "volume": "41,007,910",
              "open": "71.915", "high": "72.7777", "low": "70.8094"}


def test_parse_nasdaq_rows_handles_commas_and_mm_dd_yyyy():
    df = fetch.parse_nasdaq_rows([NASDAQ_ROW], "TQQQ")
    assert len(df) == 1
    assert df["date"].iloc[0] == pd.Timestamp("2026-09-18")
    assert df["close"].iloc[0] == pytest.approx(72.64)
    assert df["volume"].iloc[0] == pytest.approx(41007910)
    assert df["symbol"].iloc[0] == "TQQQ"


def test_parse_nasdaq_rows_skips_bad_rows():
    rows = [NASDAQ_ROW, {"date": "", "close": "", "volume": "", "open": "", "high": "", "low": ""}]
    df = fetch.parse_nasdaq_rows(rows, "TQQQ")
    assert len(df) == 1


def test_merge_incremental_is_idempotent():
    old = pd.DataFrame({"date": [pd.Timestamp("2026-09-17")], "symbol": ["TQQQ"],
                        "open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1.0]})
    new = pd.DataFrame({"date": [pd.Timestamp("2026-09-17"), pd.Timestamp("2026-09-18")],
                        "symbol": ["TQQQ", "TQQQ"], "open": [1.0, 2.0], "high": [1.0, 2.0],
                        "low": [1.0, 2.0], "close": [1.0, 2.0], "volume": [1.0, 2.0]})
    merged = fetch.merge_incremental(old, new)
    assert len(merged) == 2
    # 重复执行不产生重复行
    assert len(fetch.merge_incremental(merged, new)) == 2


def test_missing_ranges_returns_start_when_empty():
    assert fetch.missing_ranges(pd.DataFrame(), "TQQQ") == (None, None)


def test_missing_ranges_returns_last_date_plus_one():
    old = pd.DataFrame({"date": [pd.Timestamp("2026-09-17")], "symbol": ["TQQQ"]})
    start, _ = fetch.missing_ranges(old, "TQQQ")
    assert start == pd.Timestamp("2026-09-18")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/data/test_fetch.py -v`
Expected: FAIL — `ImportError: cannot import name 'fetch'`

- [ ] **Step 3: 实现抓取层**

```python
# fg_system/data/fetch.py
# -*- coding: utf-8 -*-
"""数据抓取：Nasdaq 官方 API（价格）+ CBOE cdn（VIX/VIX3M）。

数据源实测结论见设计文档 §4.1。请求逻辑可直接复用 scripts/fetch_market_data.py。
"""
import json
import os
import ssl
import time
import urllib.parse
import urllib.request

import pandas as pd

from fg_system import config

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def _opener():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": config.PROXY, "https": config.PROXY}),
        urllib.request.HTTPSHandler(context=ctx),
    )


def _get(url, retries=3):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            with _opener().open(req, timeout=35) as r:
                return r.read()
        except Exception as exc:      # 网络类异常统一重试
            last = exc
            time.sleep(2)
    raise RuntimeError("请求失败 %s: %s" % (url, last))


def parse_nasdaq_rows(rows, symbol):
    """解析 Nasdaq tradesTable.rows。字段顺序：date,close,volume,open,high,low。"""
    recs = []
    for r in rows:
        try:
            recs.append({
                "date": pd.to_datetime(r["date"], format="%m/%d/%Y"),
                "symbol": symbol,
                "open": float(str(r["open"]).replace(",", "")),
                "high": float(str(r["high"]).replace(",", "")),
                "low": float(str(r["low"]).replace(",", "")),
                "close": float(str(r["close"]).replace(",", "").replace("$", "")),
                "volume": float(str(r["volume"]).replace(",", "") or 0),
            })
        except (ValueError, KeyError, TypeError):
            continue
    return pd.DataFrame(recs).sort_values("date").reset_index(drop=True)


def fetch_symbol(symbol, limit=9999):
    url = "%s?assetclass=etf&fromdate=2010-01-01&limit=%d" % (
        config.NASDAQ_API.format(symbol=urllib.parse.quote(symbol)), limit)
    data = json.loads(_get(url).decode("utf-8"))
    rows = ((data.get("data") or {}).get("tradesTable") or {}).get("rows") or []
    return parse_nasdaq_rows(rows, symbol)


def fetch_cboe_index(name):
    """下载 CBOE 指数历史 CSV（VIX / VIX3M），返回 date,open,high,low,close。"""
    url = config.CBOE_CDN.format(name=name)
    text = _get(url).decode("utf-8", errors="replace")
    lines = [l for l in text.splitlines() if l.strip()]
    start = next((i for i, l in enumerate(lines) if l.upper().startswith("DATE,")), 0)
    rows = [l.split(",") for l in lines[start + 1:]]
    recs = []
    for r in rows:
        try:
            recs.append({
                "date": pd.to_datetime(r[0].strip(), format="%m/%d/%Y"),
                "open": float(r[1]), "high": float(r[2]),
                "low": float(r[3]), "close": float(r[4]),
            })
        except (ValueError, IndexError):
            continue
    return pd.DataFrame(recs).sort_values("date").reset_index(drop=True)


def missing_ranges(existing, symbol):
    """返回该标的需要抓取的起始日期（本地最大日期的下一天）。"""
    if existing is None or existing.empty:
        return None, None
    sub = existing[existing["symbol"] == symbol]
    if sub.empty:
        return None, None
    return sub["date"].max() + pd.Timedelta(days=1), None


def merge_incremental(old, new):
    """追加去重排序，保证幂等（§4.2）。"""
    if old is None or old.empty:
        return new.sort_values(["symbol", "date"]).reset_index(drop=True)
    if new is None or new.empty:
        return old.sort_values(["symbol", "date"]).reset_index(drop=True)
    merged = pd.concat([old, new], ignore_index=True)
    return (merged.drop_duplicates(subset=["symbol", "date"], keep="last")
            .sort_values(["symbol", "date"]).reset_index(drop=True))


def update_prices(path=None, symbols=None, sleep=1.0):
    """增量更新价格文件。返回 (合并后 DataFrame, 各标的本次新增行数)。"""
    path = path or os.path.join(config.RAW_DIR, "prices.csv")
    symbols = symbols or config.FETCH_SYMBOLS
    old = pd.DataFrame()
    if os.path.exists(path):
        old = pd.read_csv(path, dtype={"symbol": str}, parse_dates=["date"])

    added, frames = {}, []
    for sym in symbols:
        fresh = fetch_symbol(sym)
        before = len(old[old["symbol"] == sym]) if not old.empty else 0
        frames.append(fresh)
        added[sym] = len(fresh) - before
        time.sleep(sleep)

    merged = merge_incremental(old, pd.concat(frames, ignore_index=True) if frames else pd.DataFrame())
    os.makedirs(os.path.dirname(path), exist_ok=True)
    merged.to_csv(path, index=False, encoding="utf-8")
    return merged, added


def update_indices(raw_dir=None):
    """增量更新 vix.csv / vix3m.csv。"""
    raw_dir = raw_dir or config.RAW_DIR
    os.makedirs(raw_dir, exist_ok=True)
    out = {}
    for name, fname in [("VIX", "vix.csv"), ("VIX3M", "vix3m.csv")]:
        df = fetch_cboe_index(name)
        df.to_csv(os.path.join(raw_dir, fname), index=False, encoding="utf-8")
        out[name] = len(df)
    return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/data/test_fetch.py -v`
Expected: 5 passed

- [ ] **Step 5: 对真实网络做一次端到端验证（人工确认）**

Run: `python -c "from fg_system.data import fetch; df,added=fetch.update_prices(); print(added)"`
Expected: 打印各标的本次新增行数（数据已是 2026-09-18 最新，新增应为 0 或个位数）

- [ ] **Step 6: 提交**

```bash
git add fg_system/data/fetch.py tests/data/test_fetch.py
git commit -m "feat: 数据抓取与增量更新（Nasdaq + CBOE）" # user-confirmed-commit
```

---

## Task 5: 因子基类与 F1 VIX

**Files:**
- Modify: `fg_system/config.py`（追加 `COMPOSITE_WINDOW`，见 Step 3 说明）
- Create: `fg_system/factors/__init__.py`
- Create: `fg_system/factors/base.py`
- Create: `fg_system/factors/vix.py`
- Create: `tests/factors/__init__.py`
- Create: `tests/factors/test_base.py`
- Create: `tests/factors/test_vix.py`

**归一化口径说明（重要，与 §5.3 的对应关系）：**

设计文档 §5.3 要求"滚动分位数而非固定阈值"。本计划统一实现为**单层滚动百分位**：多子项因子先对每个子项取滚动百分位（窗口 `RANK_WINDOW`），再加权平均得到 `raw ∈ [0,1]`，最后按方向映射为 `score ∈ [0,100]`。

**为什么不做第二层百分位**：4 个因子的 score 各自近似均匀分布时，加权平均后的 `fg_index` 标准差约为 `100×0.289×sqrt(Σwᵢ²) ≈ 14.7`，落在 [0,20] 与 [80,100] 的概率各约 2%。对 10 年 2514 个交易日而言约各 50 天——**极端档位稀有但确实会发生**，无需二次拉伸。这样 `warmup` 只需 756 交易日（3 年），回测区间得以保留 7 年长度。

- [ ] **Step 1: 写失败的测试**

```python
# tests/factors/test_base.py
# -*- coding: utf-8 -*-
"""因子基类工具测试。"""
import numpy as np
import pandas as pd
import pytest

from fg_system.factors import base


def test_rolling_pct_returns_uniform_between_0_and_1():
    s = pd.Series(np.arange(100, dtype=float))
    out = base.rolling_pct(s, 20)
    assert out.dropna().between(0, 1).all()
    assert out.iloc[:19].isna().all()      # 窗口不足返回 NaN
    assert out.iloc[-1] == pytest.approx(1.0)


def test_rolling_pct_min_periods_enforced():
    s = pd.Series(np.arange(50, dtype=float))
    out = base.rolling_pct(s, 20)
    assert out.notna().sum() == 50 - 20 + 1


def test_pct_score_reverse_direction():
    """反转方向：同一位置 normal 与 reverse 之和恒为 100。

    注意：不能用「原始值上升 → 分数上升」来断言。对单调递增序列，滚动百分位
    在每个窗口的末尾元素恒为最大值，normal 与 reverse 在所有位置分别恒为
    100 与 0，原写法 `normal.iloc[-1] > normal.iloc[-20]` 必然失败。
    """
    s = pd.Series(np.arange(100, dtype=float))
    normal = base.pct_score(s, 20, reverse=False)
    reverse = base.pct_score(s, 20, reverse=True)
    valid = normal.dropna().index.intersection(reverse.dropna().index)
    assert len(valid) > 0
    assert (normal.loc[valid] + reverse.loc[valid] - 100.0).abs().max() < 1e-9


def test_factor_is_abstract():
    with pytest.raises(TypeError):
        base.Factor()
```

```python
# tests/factors/test_vix.py
# -*- coding: utf-8 -*-
"""F1 VIX 因子测试（§5.2 F1）。"""
import numpy as np
import pandas as pd
import pytest

from fg_system.factors.vix import VixFactor


def _wide(vix_values):
    idx = pd.date_range("2020-01-01", periods=len(vix_values), freq="B")
    cols = pd.MultiIndex.from_tuples([("VIX", "close")], names=["symbol", "field"])
    return pd.DataFrame(np.array(vix_values, dtype=float).reshape(-1, 1), index=idx, columns=cols)


def test_score_range_is_0_to_100():
    vix = 15 + 5 * np.sin(np.arange(1200) / 30.0)
    score = VixFactor().score(_wide(vix))
    valid = score.dropna()
    assert not valid.empty
    assert valid.between(0, 100).all()


def test_reverse_direction_vix_high_lowers_score():
    """VIX 水平高 → 分数低（§14.1 反转方向正确）。

    注意：不要用「线性 ramp 下末尾分数低于 30 天前」来断言——该写法依赖滚动
    排名的边界细节，不稳定（实测会得到相反结果）。改用相关性 + 分段均值。
    """
    rng = np.random.RandomState(0)
    low = 12 + 0.5 * rng.randn(800)
    high = 60 + 0.5 * rng.randn(400)
    vix = np.concatenate([low, high])
    score = VixFactor().score(_wide(vix))
    valid = score.dropna()
    assert not valid.empty
    aligned = vix[score.notna()]
    assert np.corrcoef(aligned, valid.values)[0, 1] < -0.5
    assert valid.iloc[-50:].mean() < valid.iloc[750:800].mean()


def test_nan_when_warmup_insufficient():
    score = VixFactor().score(_wide(np.full(100, 15.0)))
    assert score.isna().all()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/factors -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fg_system.factors'`

- [ ] **Step 3: 实现因子基类与 F1**

先在 `fg_system/config.py` 的「因子」段追加一行：

```python
COMPOSITE_WINDOW = RANK_WINDOW   # 保留位：v1 与 RANK_WINDOW 相同，v2 若需二次归一化再分离
```

```python
# fg_system/factors/__init__.py
# -*- coding: utf-8 -*-
from fg_system.factors.base import Factor, pct_score, rolling_pct  # noqa: F401
```

```python
# fg_system/factors/base.py
# -*- coding: utf-8 -*-
"""因子抽象基类与滚动分位归一化工具（§5.1、§5.3）。

硬约束（§4.5 约束 1）：因子输入必须是**无杠杆标的**（QQQ/SOXX/SPY/VIX 等），
禁止使用 TQQQ/SOXL/UPRO 自身价格——杠杆 ETF 含年化 12%~38% 的波动率拖累，
会把损耗系统性误读为恐惧。
"""
from abc import ABC, abstractmethod

import pandas as pd

from fg_system import config


def rolling_pct(series, window=None, min_periods=None):
    """滚动百分位，返回 [0, 1]。窗口不足处为 NaN（禁止用不足窗口的数据凑值）。"""
    window = window or config.RANK_WINDOW
    min_periods = window if min_periods is None else min_periods
    return series.rolling(window, min_periods=min_periods).rank(pct=True)


def pct_score(series, window=None, reverse=False):
    """滚动百分位映射为 0-100 分数。reverse=True 时高分代表低原始值。"""
    pct = rolling_pct(series, window)
    return 100.0 * (1.0 - pct) if reverse else 100.0 * pct


class Factor(ABC):
    """单一因子 → 0-100 情绪分（高分 = 贪婪）。纯函数，无副作用。"""

    name = ""

    @abstractmethod
    def raw(self, wide):
        """原始合成值（通常为 [0,1] 的百分位加权平均，高分 = 贪婪）。"""

    def score(self, wide):
        """0-100 情绪分。默认把 raw（[0,1]）线性映射到 [0,100]。"""
        raw = self.raw(wide)
        return 100.0 * raw
```

```python
# fg_system/factors/vix.py
# -*- coding: utf-8 -*-
"""F1 VIX 水位与变化率（先验权重 30%，§5.2）。

反转因子：VIX 高 = 恐惧 = 低分。
数据源：Data/raw/vix.csv（CBOE，1990 起）。
"""
from fg_system import config
from fg_system.factors.base import Factor, rolling_pct


class VixFactor(Factor):
    name = "vix"

    def raw(self, wide):
        vix = wide[("VIX", "close")]
        chg5 = vix.pct_change(5)
        level_pct = rolling_pct(vix, config.RANK_WINDOW)
        chg_pct = rolling_pct(chg5, config.RANK_WINDOW)
        composite = 0.7 * level_pct + 0.3 * chg_pct
        return 1.0 - composite          # 反转：VIX 高 → raw 低 → score 低
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/factors -v`
Expected: 7 passed

- [ ] **Step 5: 提交**

```bash
git add fg_system/config.py fg_system/factors/ tests/factors/
git commit -m "feat: 因子基类与 F1 VIX 因子" # user-confirmed-commit
```

---

## Task 6: F2 波动率期限结构

**Files:**
- Create: `fg_system/factors/term.py`
- Create: `tests/factors/test_term.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/factors/test_term.py
# -*- coding: utf-8 -*-
"""F2 波动率期限结构测试（§5.2 F2）。

原设计为 CBOE Put/Call，因官方文件停更于 2019-10 而改用 VIX/VIX3M 比值。
"""
import numpy as np
import pandas as pd
import pytest

from fg_system.factors.term import TermStructureFactor


def _wide(vix, vix3m):
    idx = pd.date_range("2020-01-01", periods=len(vix), freq="B")
    cols = pd.MultiIndex.from_tuples(
        [("VIX", "close"), ("VIX3M", "close")], names=["symbol", "field"]
    )
    return pd.DataFrame(np.c_[vix, vix3m], index=idx, columns=cols)


def test_score_range():
    rng = np.random.RandomState(1)
    vix = 15 + 5 * rng.randn(1200)
    vix3m = 18 + 4 * rng.randn(1200)
    score = TermStructureFactor().score(_wide(vix, vix3m)).dropna()
    assert not score.empty
    assert score.between(0, 100).all()


def test_inverted_term_structure_lowers_score():
    """期限结构倒挂（VIX > VIX3M）表示短期恐慌，分数必须下降。"""
    rng = np.random.RandomState(2)
    n = 900
    normal_vix = 14 + 1.0 * rng.randn(n)
    normal_3m = normal_vix + 3.0          # 正常：远期高于近期
    inverted = np.concatenate([normal_vix, np.full(300, 60.0)])
    inverted_3m = np.concatenate([normal_3m, np.full(300, 45.0)])   # 倒挂
    score = TermStructureFactor().score(_wide(inverted, inverted_3m))
    assert score.iloc[-1] < score.iloc[n - 30]


def test_nan_when_insufficient_warmup():
    score = TermStructureFactor().score(_wide(np.full(50, 15.0), np.full(50, 18.0)))
    assert score.isna().all()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/factors/test_term.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fg_system.factors.term'`

- [ ] **Step 3: 实现 F2**

```python
# fg_system/factors/term.py
# -*- coding: utf-8 -*-
"""F2 波动率期限结构 VIX/VIX3M（先验权重 20%，§5.2）。

比值 > 1 表示短期恐慌高于中期（倒挂），是市场承压信号。
反转因子：比值高 = 恐惧 = 低分。
已知代价：与 F1 同属波动率族，存在共线性（§17 风险 3），实现时须做相关性检查。
"""
from fg_system import config
from fg_system.factors.base import Factor, rolling_pct


class TermStructureFactor(Factor):
    name = "term"

    def raw(self, wide):
        vix = wide[("VIX", "close")]
        vix3m = wide[("VIX3M", "close")]
        ratio = (vix / vix3m).rolling(5).mean()      # 5 日均值消噪
        pct = rolling_pct(ratio, config.RANK_WINDOW)
        return 1.0 - pct                             # 反转：倒挂 → 低分
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/factors/test_term.py -v`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add fg_system/factors/term.py tests/factors/test_term.py
git commit -m "feat: F2 波动率期限结构因子" # user-confirmed-commit
```

---

## Task 7: F3 价格因子

**Files:**
- Create: `fg_system/factors/price.py`
- Create: `tests/factors/test_price.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/factors/test_price.py
# -*- coding: utf-8 -*-
"""F3 价格因子测试（§5.2 F3）。输入必须是 QQQ 等无杠杆标的。"""
import numpy as np
import pandas as pd
import pytest

from fg_system.factors.price import PriceFactor


def _wide(close):
    idx = pd.date_range("2020-01-01", periods=len(close), freq="B")
    cols = pd.MultiIndex.from_tuples([("QQQ", "close")], names=["symbol", "field"])
    return pd.DataFrame(np.array(close, dtype=float).reshape(-1, 1), index=idx, columns=cols)


def test_score_range():
    rng = np.random.RandomState(3)
    close = 300 * np.exp(np.cumsum(0.0004 + 0.01 * rng.randn(1300)))
    score = PriceFactor().score(_wide(close)).dropna()
    assert not score.empty
    assert score.between(0, 100).all()


def test_deep_drawdown_lowers_score():
    """深度回撤应给出低分（恐惧）。"""
    up = 300 * np.exp(np.cumsum(np.full(900, 0.0008)))
    crash = up[-1] * np.exp(np.cumsum(np.full(300, -0.004)))
    score = PriceFactor().score(_wide(np.concatenate([up, crash])))
    assert score.iloc[-1] < 30


def test_strong_uptrend_raises_score():
    up = 300 * np.exp(np.cumsum(np.full(1200, 0.0012)))
    score = PriceFactor().score(_wide(up))
    assert score.iloc[-1] > 70


def test_requires_underlying_not_leveraged():
    """传入 TQQQ 列应报错——强制使用无杠杆标的（§4.5 约束 1）。"""
    idx = pd.date_range("2020-01-01", periods=900, freq="B")
    cols = pd.MultiIndex.from_tuples([("TQQQ", "close")], names=["symbol", "field"])
    wide = pd.DataFrame(np.full((900, 1), 50.0), index=idx, columns=cols)
    with pytest.raises(ValueError, match="无杠杆标的"):
        PriceFactor().score(wide)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/factors/test_price.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fg_system.factors.price'`

- [ ] **Step 3: 实现 F3**

```python
# fg_system/factors/price.py
# -*- coding: utf-8 -*-
"""F3 价格因子（先验权重 30%，§5.2）。

四个子项（等权）：动量、RSI(14)、距 52 周高点回撤（反转）、20 日已实现波动率（反转）。
输入：QQQ（标的指数代理）。**禁止使用杠杆 ETF 自身价格**（§4.5 约束 1）。
"""
import numpy as np

from fg_system import config
from fg_system.factors.base import Factor, rolling_pct


def rsi(series, period=14):
    """Wilder RSI。"""
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    return 100.0 - 100.0 / (1.0 + rs)


def drawdown_52w(series, lookback=252):
    """距滚动 52 周最高收盘价的回撤（正数表示回撤幅度）。"""
    peak = series.rolling(lookback, min_periods=lookback).max()
    return 1.0 - series / peak


class PriceFactor(Factor):
    name = "price"
    underlying = "QQQ"

    def raw(self, wide):
        if (self.underlying, "close") not in wide.columns:
            raise ValueError(
                "F3 必须使用无杠杆标的 %s，当前列: %s" % (self.underlying, list(wide.columns))
            )
        for lev in config.SYMBOLS:
            if (lev, "close") in wide.columns and self.underlying not in (lev,):
                pass  # 允许同表存在杠杆列，但本因子只读 underlying
        qqq = wide[(self.underlying, "close")]
        w = config.RANK_WINDOW

        mom = rolling_pct(qqq.pct_change(60), w)                       # 正向
        strength = rolling_pct(rsi(qqq), w)                            # 正向
        dd = 1.0 - rolling_pct(drawdown_52w(qqq), w)                   # 反转
        vol = qqq.pct_change().rolling(20).std() * np.sqrt(252)
        calm = 1.0 - rolling_pct(vol, w)                               # 反转
        return (mom + strength + dd + calm) / 4.0
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/factors/test_price.py -v`
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add fg_system/factors/price.py tests/factors/test_price.py
git commit -m "feat: F3 价格因子（动量/RSI/回撤/波动率）" # user-confirmed-commit
```

---

## Task 8: F4 广度代理

**Files:**
- Create: `fg_system/factors/breadth.py`
- Create: `tests/factors/test_breadth.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/factors/test_breadth.py
# -*- coding: utf-8 -*-
"""F4 广度代理测试（§5.2 F4）。"""
import numpy as np
import pandas as pd
import pytest

from fg_system.factors.breadth import BreadthFactor


def _wide(series_map):
    n = len(next(iter(series_map.values())))
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    cols = pd.MultiIndex.from_tuples([(s, "close") for s in series_map], names=["symbol", "field"])
    return pd.DataFrame(np.c_[*series_map.values()], index=idx, columns=cols)


def test_score_range():
    rng = np.random.RandomState(4)
    n = 1300
    base = 100 * np.exp(np.cumsum(0.0003 + 0.008 * rng.randn(n)))
    wide = _wide({"SPY": base, "QQQ": base * 1.1, "RSP": base * 0.98, "IWM": base * 0.9})
    score = BreadthFactor().score(wide).dropna()
    assert not score.empty
    assert score.between(0, 100).all()


def test_narrowing_breadth_lowers_score():
    """RSP/SPY 持续走弱（广度恶化）应给出低分。"""
    n = 900
    spy = 100 * np.exp(np.cumsum(np.full(n, 0.0010)))
    rsp = 100 * np.exp(np.cumsum(np.full(n, -0.0005)))    # 等权持续弱于市值权
    wide = _wide({"SPY": spy, "QQQ": spy, "RSP": rsp, "IWM": spy * 0.9})
    score = BreadthFactor().score(wide)
    assert score.iloc[-1] < 40


def test_missing_breadth_symbol_raises():
    n = 900
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    cols = pd.MultiIndex.from_tuples([("SPY", "close")], names=["symbol", "field"])
    wide = pd.DataFrame(np.full((n, 1), 100.0), index=idx, columns=cols)
    with pytest.raises(ValueError, match="广度标的缺失"):
        BreadthFactor().score(wide)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/factors/test_breadth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fg_system.factors.breadth'`

- [ ] **Step 3: 实现 F4**

```python
# fg_system/factors/breadth.py
# -*- coding: utf-8 -*-
"""F4 广度代理（先验权重 20%，§5.2）。

三个子项（等权）：RSP/SPY 相对强弱、QQQ/SPY 相对强弱、均线宽度。
输入全部为无杠杆标的。均线宽度本身已是有界值，直接使用不再做百分位。
"""
from fg_system import config
from fg_system.factors.base import Factor, rolling_pct


class BreadthFactor(Factor):
    name = "breadth"

    def raw(self, wide):
        missing = [s for s in config.BREADTH_SYMBOLS if (s, "close") not in wide.columns]
        if missing:
            raise ValueError("广度标的缺失: %s" % missing)

        spy = wide[("SPY", "close")]
        rsp = wide[("RSP", "close")]
        qqq = wide[("QQQ", "close")]
        w = config.RANK_WINDOW

        equal_vs_cap = rolling_pct((rsp / spy).pct_change(60), w)
        growth_vs_cap = rolling_pct((qqq / spy).pct_change(60), w)

        above = None
        for sym in config.BREADTH_SYMBOLS:
            s = wide[(sym, "close")]
            flag = (s > s.rolling(200, min_periods=200).mean()).astype(float)
            flag = flag.where(s.rolling(200, min_periods=200).mean().notna())
            above = flag if above is None else above + flag
        above = above / len(config.BREADTH_SYMBOLS)      # 0 ~ 1

        return (equal_vs_cap + growth_vs_cap + above) / 3.0
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/factors/test_breadth.py -v`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add fg_system/factors/breadth.py tests/factors/test_breadth.py
git commit -m "feat: F4 广度代理因子" # user-confirmed-commit
```

---

## Task 9: 指数合成

**Files:**
- Create: `fg_system/index.py`
- Create: `tests/test_index.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_index.py
# -*- coding: utf-8 -*-
"""指数合成测试（§5.4）。"""
import numpy as np
import pandas as pd
import pytest

from fg_system import config
from fg_system import index as idx


class FakeFactor:
    def __init__(self, name, values):
        self.name = name
        self._values = values

    def score(self, wide):
        return self._values


def _scores(**kwargs):
    n = len(next(iter(kwargs.values())))
    return pd.DataFrame(kwargs, index=pd.date_range("2020-01-01", periods=n, freq="B"))


def test_weighted_average_of_all_factors():
    s = _scores(vix=[100.0] * 3, term=[100.0] * 3, price=[0.0] * 3, breadth=[0.0] * 3)
    factors = [FakeFactor(k, s[k]) for k in s.columns]
    out = idx.combine(s, factors)
    assert out.iloc[0] == pytest.approx(50.0)


def test_missing_factor_renormalizes_weights():
    """F2 全 NaN 时，剩余三个因子按各自权重重新归一化。"""
    s = _scores(vix=[100.0] * 3, term=[np.nan] * 3, price=[100.0] * 3, breadth=[100.0] * 3)
    factors = [FakeFactor(k, s[k]) for k in s.columns]
    out = idx.combine(s, factors)
    assert out.iloc[0] == pytest.approx(100.0)


def test_insufficient_factors_returns_nan():
    """有效因子少于 MIN_VALID_FACTORS 时当日不产生信号。"""
    s = _scores(vix=[50.0] * 3, term=[np.nan] * 3, price=[np.nan] * 3, breadth=[np.nan] * 3)
    factors = [FakeFactor(k, s[k]) for k in s.columns]
    out = idx.combine(s, factors)
    assert out.isna().all()


def test_output_range_is_0_to_100():
    rng = np.random.RandomState(5)
    s = pd.DataFrame(
        {k: rng.uniform(0, 100, 500) for k in config.WEIGHTS},
        index=pd.date_range("2020-01-01", periods=500, freq="B"),
    )
    factors = [FakeFactor(k, s[k]) for k in s.columns]
    out = idx.combine(s, factors).dropna()
    assert out.between(0, 100).all()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_index.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fg_system.index'`

- [ ] **Step 3: 实现指数合成**

```python
# fg_system/index.py
# -*- coding: utf-8 -*-
"""因子加权合成 fg_index（§5.4）。

fg_index = Σ(wᵢ × scoreᵢ) / Σwᵢ   —— 仅对当日有效的因子求和。
有效因子数 < MIN_VALID_FACTORS 时返回 NaN（避免单因子主导）。
禁止使用任何全样本统计量。
"""
import numpy as np
import pandas as pd

from fg_system import config


def build_factors():
    """按配置构造四个因子实例。"""
    from fg_system.factors.breadth import BreadthFactor
    from fg_system.factors.price import PriceFactor
    from fg_system.factors.term import TermStructureFactor
    from fg_system.factors.vix import VixFactor

    return [VixFactor(), TermStructureFactor(), PriceFactor(), BreadthFactor()]


def factor_scores(wide, factors=None):
    """各因子 0-100 分数矩阵（列 = 因子名）。"""
    factors = factors or build_factors()
    return pd.DataFrame({f.name: f.score(wide) for f in factors})


def combine(scores, factors=None):
    """加权合成 fg_index，缺失因子按剩余权重重新归一化。"""
    factors = factors or build_factors()
    weight = pd.Series({f.name: config.WEIGHTS[f.name] for f in factors}, dtype=float)

    valid = scores.notna()
    weights = valid.mul(weight, axis=1)
    weight_sum = weights.sum(axis=1)

    weighted = (scores.fillna(0.0) * weights).sum(axis=1)
    out = weighted / weight_sum.replace(0.0, np.nan)

    too_few = valid.sum(axis=1) < config.MIN_VALID_FACTORS
    out[too_few] = np.nan
    return out.clip(lower=0.0, upper=100.0)


def smooth(fg_index, days=None):
    """可选平滑（v1 默认 SMOOTHING_DAYS = 1，即不平滑）。"""
    days = days or config.SMOOTHING_DAYS
    if days <= 1:
        return fg_index
    return fg_index.rolling(days, min_periods=days).mean()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_index.py -v`
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add fg_system/index.py tests/test_index.py
git commit -m "feat: 指数加权合成与缺因子权重重归一化" # user-confirmed-commit
```

---

## Task 10: 信号层 — 核心仓与弹药池

**Files:**
- Create: `fg_system/signal.py`
- Create: `tests/test_signal.py`

**设计要点（§7、§3.4）：** `signal` 层必须是**纯函数 + 显式状态**，禁止读写全局变量或文件。状态由调用方持久化，这是保证"回测逻辑 = 日常运行逻辑"的关键。

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_signal.py
# -*- coding: utf-8 -*-
"""信号层测试（§7、§8、§9）。"""
import pandas as pd
import pytest

from fg_system import config
from fg_system import signal


def test_core_position_five_zones():
    """五档映射：饱和度 × CORE_CAP（§7.2）。"""
    assert signal.core_position(10) == pytest.approx(0.70)
    assert signal.core_position(30) == pytest.approx(0.70 * 0.75)
    assert signal.core_position(50) == pytest.approx(0.70 * 0.50)
    assert signal.core_position(70) == pytest.approx(0.70 * 0.25)
    assert signal.core_position(90) == pytest.approx(0.0)


def test_core_position_boundaries_are_lower_inclusive():
    assert signal.core_position(20) == pytest.approx(0.70 * 0.75)   # 20 属于恐惧档
    assert signal.core_position(80) == pytest.approx(0.0)          # 80 属于极贪档


def test_core_position_nan_returns_none():
    assert signal.core_position(float("nan")) is None


def test_ammo_released_progressively():
    """回撤穿越 20/40/60% 依次释放三批，各批只释放一次（§7.3）。"""
    st = signal.SignalState()
    st, ammo, _ = signal.update_ammo(st, drawdown=0.25)
    assert ammo == pytest.approx(0.10)
    st, ammo, _ = signal.update_ammo(st, drawdown=0.45)
    assert ammo == pytest.approx(0.20)
    st, ammo, _ = signal.update_ammo(st, drawdown=0.65)
    assert ammo == pytest.approx(0.30)
    # 再次穿越不重复释放
    st, ammo, _ = signal.update_ammo(st, drawdown=0.70)
    assert ammo == pytest.approx(0.30)


def test_ammo_not_released_when_drawdown_shallow():
    st = signal.SignalState()
    st, ammo, _ = signal.update_ammo(st, drawdown=0.05)
    assert ammo == pytest.approx(0.0)


def test_target_position_sums_core_and_ammo():
    st = signal.SignalState()
    st, _, _ = signal.update_ammo(st, drawdown=0.25)
    target = signal.target_position(10, st)
    assert target == pytest.approx(0.70 + 0.10)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_signal.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fg_system.signal'`

- [ ] **Step 3: 实现核心仓与弹药池**

```python
# fg_system/signal.py
# -*- coding: utf-8 -*-
"""信号层：指数 + 回撤 → 目标仓位（§7、§8、§9）。

硬性约定（§3.4）：本模块是唯一产生仓位的层，且必须是**纯函数 + 显式状态**。
禁止读写全局变量或文件；状态由调用方（pipeline / backtest runner）持久化。
"""
import math
from dataclasses import dataclass, field

import pandas as pd

from fg_system import config


@dataclass
class SignalState:
    """信号状态机。所有字段均可 JSON 序列化，用于 state.json 持久化。"""

    ammo_released: list = field(default_factory=list)     # 已释放批次索引 [0,1,2]
    last_rebalance_date: str = None                       # ISO 日期字符串
    circuit_breaker: bool = False
    cb_trigger_index: float = None                        # 熔断时的指数峰值
    cb_trigger_date: str = None
    cb_low_price: dict = field(default_factory=dict)      # symbol -> 熔断后最低价
    last_extreme_fear_date: str = None

    def to_dict(self):
        return {
            "ammo_released": sorted(self.ammo_released),
            "last_rebalance_date": self.last_rebalance_date,
            "circuit_breaker": self.circuit_breaker,
            "cb_trigger_index": self.cb_trigger_index,
            "cb_trigger_date": self.cb_trigger_date,
            "cb_low_price": dict(self.cb_low_price),
            "last_extreme_fear_date": self.last_extreme_fear_date,
        }

    @classmethod
    def from_dict(cls, data):
        if not data:
            return cls()
        return cls(
            ammo_released=list(data.get("ammo_released") or []),
            last_rebalance_date=data.get("last_rebalance_date"),
            circuit_breaker=bool(data.get("circuit_breaker", False)),
            cb_trigger_index=data.get("cb_trigger_index"),
            cb_trigger_date=data.get("cb_trigger_date"),
            cb_low_price=dict(data.get("cb_low_price") or {}),
            last_extreme_fear_date=data.get("last_extreme_fear_date"),
        )


# ---------------------------------------------------------------- 核心仓（§7.2）
def zone_of(fg_index):
    """返回档位索引 0-4。边界为下闭区间：20 属于档 1。"""
    for i, edge in enumerate(config.ZONE_EDGES):
        if fg_index < edge:
            return i
    return len(config.ZONE_EDGES)


def core_position(fg_index):
    """核心仓仓位 = 饱和度 × CORE_CAP。指数无效时返回 None。"""
    if fg_index is None or (isinstance(fg_index, float) and math.isnan(fg_index)):
        return None
    return config.CORE_CAP * config.ZONE_SATURATION[zone_of(fg_index)]


# ---------------------------------------------------------------- 弹药池（§7.3）
def update_ammo(state, drawdown):
    """按标的指数回撤释放弹药。每批只释放一次。返回 (新状态, 弹药仓位, 新释放批次列表)。"""
    if drawdown is None or (isinstance(drawdown, float) and math.isnan(drawdown)):
        return state, config.AMMO_PER_BATCH * len(state.ammo_released), []

    newly = []
    for i, trigger in enumerate(config.DRAWDOWN_BATCHES):
        if drawdown >= trigger and i not in state.ammo_released:
            state.ammo_released.append(i)
            newly.append(i)
    return state, config.AMMO_PER_BATCH * len(state.ammo_released), newly


def ammo_position(state):
    return config.AMMO_PER_BATCH * len(state.ammo_released)


def target_position(fg_index, state):
    """目标总仓位 = 核心仓 + 弹药仓（§7.4）。"""
    core = core_position(fg_index)
    if core is None:
        return None
    return core + ammo_position(state)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_signal.py -v`
Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
git add fg_system/signal.py tests/test_signal.py
git commit -m "feat: 信号层核心仓五档映射与弹药池释放" # user-confirmed-commit
```

---

## Task 11: 信号层 — 极端规则与防抖动

**Files:**
- Modify: `fg_system/signal.py`
- Modify: `tests/test_signal.py`

- [ ] **Step 1: 追加失败的测试**

在 `tests/test_signal.py` 末尾追加：

```python
# ---------------------------------------------------------------- 极端规则（§8）
def test_circuit_breaker_triggers_at_threshold():
    st = signal.SignalState()
    st, target, reason = signal.apply_extremes(st, fg_index=90.0, date="2024-01-02",
                                                prices={"TQQQ": 100.0}, target=0.7)
    assert st.circuit_breaker is True
    assert target == pytest.approx(config.EXTREME_GREED_FLOOR)
    assert "熔断" in reason


def test_circuit_breaker_unlocks_when_index_falls():
    st = signal.SignalState(circuit_breaker=True, cb_trigger_index=90.0,
                            cb_trigger_date="2024-01-02", cb_low_price={"TQQQ": 90.0})
    st, target, reason = signal.apply_extremes(st, fg_index=55.0, date="2024-01-20",
                                                prices={"TQQQ": 95.0}, target=0.7)
    assert st.circuit_breaker is False
    assert target == pytest.approx(0.7)


def test_circuit_breaker_unlocks_on_rebound():
    """标的自熔断后低点反弹 >= 10% 解锁（§8.1 条件 2）。"""
    st = signal.SignalState(circuit_breaker=True, cb_trigger_index=90.0,
                            cb_trigger_date="2024-01-02", cb_low_price={"TQQQ": 100.0})
    st, target, reason = signal.apply_extremes(st, fg_index=80.0, date="2024-01-20",
                                                prices={"TQQQ": 111.0}, target=0.7)
    assert st.circuit_breaker is False
    assert "反弹" in reason


def test_circuit_breaker_unlocks_on_index_drop():
    """指数自峰值回落 >= 15 点解锁（§8.1 条件 3）。"""
    st = signal.SignalState(circuit_breaker=True, cb_trigger_index=90.0,
                            cb_trigger_date="2024-01-02", cb_low_price={"TQQQ": 100.0})
    st, target, reason = signal.apply_extremes(st, fg_index=74.0, date="2024-01-20",
                                                prices={"TQQQ": 101.0}, target=0.7)
    assert st.circuit_breaker is False
    assert "回落" in reason


def test_circuit_breaker_stays_locked_when_nothing_unlocks():
    st = signal.SignalState(circuit_breaker=True, cb_trigger_index=90.0,
                            cb_trigger_date="2024-01-02", cb_low_price={"TQQQ": 100.0})
    st, target, reason = signal.apply_extremes(st, fg_index=88.0, date="2024-01-20",
                                                prices={"TQQQ": 101.0}, target=0.7)
    assert st.circuit_breaker is True
    assert target == pytest.approx(config.EXTREME_GREED_FLOOR)


def test_circuit_breaker_updates_low_price():
    st = signal.SignalState(circuit_breaker=True, cb_trigger_index=90.0,
                            cb_trigger_date="2024-01-02", cb_low_price={"TQQQ": 100.0})
    st, _, _ = signal.apply_extremes(st, fg_index=88.0, date="2024-01-20",
                                      prices={"TQQQ": 92.0}, target=0.7)
    assert st.cb_low_price["TQQQ"] == pytest.approx(92.0)


def test_extreme_fear_releases_extra_ammo():
    """指数 <= 10 允许提前释放下一批弹药（§8.2）。"""
    st = signal.SignalState()
    st, released, reason = signal.apply_extreme_fear(st, fg_index=8.0, date="2024-01-02")
    assert released == 1
    assert len(st.ammo_released) == 1
    assert "极恐" in reason


def test_extreme_fear_cooldown_blocks_repeat():
    st = signal.SignalState(ammo_released=[0], last_extreme_fear_date="2024-01-02")
    st, released, reason = signal.apply_extreme_fear(st, fg_index=8.0, date="2024-02-01")
    assert released == 0


def test_extreme_fear_cannot_release_beyond_cap():
    st = signal.SignalState(ammo_released=[0, 1, 2])
    st, released, reason = signal.apply_extreme_fear(st, fg_index=5.0, date="2024-01-02")
    assert released == 0


# ---------------------------------------------------------------- 防抖动（§9）
def test_throttle_blocks_small_adjustment():
    st = signal.SignalState(last_rebalance_date="2024-01-02")
    ok, reason = signal.throttle_ok(st, current=0.50, target=0.55, date="2024-01-03",
                                    extreme=False)
    assert ok is False
    assert "阈值" in reason


def test_throttle_blocks_within_cooldown():
    st = signal.SignalState(last_rebalance_date="2024-01-02")
    ok, reason = signal.throttle_ok(st, current=0.50, target=0.70, date="2024-01-04",
                                    extreme=False)
    assert ok is False
    assert "冷却" in reason


def test_throttle_allows_after_cooldown():
    st = signal.SignalState(last_rebalance_date="2024-01-02")
    ok, reason = signal.throttle_ok(st, current=0.50, target=0.70, date="2024-01-10",
                                    extreme=False)
    assert ok is True


def test_throttle_extreme_bypasses_all():
    st = signal.SignalState(last_rebalance_date="2024-01-02")
    ok, reason = signal.throttle_ok(st, current=0.50, target=0.55, date="2024-01-03",
                                    extreme=True)
    assert ok is True


def test_clip_single_adjustment():
    assert signal.clip_adjustment(0.0, 0.70) == pytest.approx(config.MAX_SINGLE_ADJUST)
    assert signal.clip_adjustment(0.50, 0.60) == pytest.approx(0.60)
    assert signal.clip_adjustment(0.60, 0.00) == pytest.approx(0.30)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_signal.py -v`
Expected: FAIL — `AttributeError: module 'fg_system.signal' has no attribute 'apply_extremes'`

- [ ] **Step 3: 在 `fg_system/signal.py` 末尾追加实现**

```python
# ---------------------------------------------------------------- 极端规则（§8）
def apply_extremes(state, fg_index, date, prices, target):
    """应用极端规则，返回 (新状态, 修正后的目标仓位, 说明)。

    优先级：极贪熔断 > 极恐加仓 > 五档映射（§8.3）。
    prices: {symbol: 当日收盘价}，用于熔断的标的级反弹判断。
    """
    if fg_index is None or (isinstance(fg_index, float) and math.isnan(fg_index)):
        return state, target, "指数无效"

    # --- 极贪熔断（§8.1）
    if not state.circuit_breaker and fg_index >= config.EXTREME_GREED_TRIGGER:
        state.circuit_breaker = True
        state.cb_trigger_index = fg_index
        state.cb_trigger_date = date
        state.cb_low_price = dict(prices or {})
        return state, config.EXTREME_GREED_FLOOR, "极贪熔断触发（指数 %.1f）" % fg_index

    if state.circuit_breaker:
        # 更新熔断后低点
        for sym, px in (prices or {}).items():
            low = state.cb_low_price.get(sym)
            if low is None or px < low:
                state.cb_low_price[sym] = px

        if fg_index < config.EXTREME_GREED_UNLOCK_INDEX:
            state.circuit_breaker = False
            return state, target, "熔断解锁（指数回落至 %.1f）" % fg_index

        if (state.cb_trigger_index is not None
                and state.cb_trigger_index - fg_index >= config.EXTREME_GREED_UNLOCK_DROP):
            state.circuit_breaker = False
            return state, target, "熔断解锁（指数自峰值回落 %.1f 点）" % (
                state.cb_trigger_index - fg_index)

        for sym, px in (prices or {}).items():
            low = state.cb_low_price.get(sym)
            if low and low > 0 and px / low - 1.0 >= config.EXTREME_GREED_UNLOCK_REBOUND:
                state.circuit_breaker = False
                return state, target, "熔断解锁（%s 自低点反弹 %.1f%%）" % (
                    sym, (px / low - 1.0) * 100)

        return state, config.EXTREME_GREED_FLOOR, "熔断维持中"

    return state, target, ""


def apply_extreme_fear(state, fg_index, date):
    """极恐提前释放弹药（§8.2）。返回 (新状态, 本次释放批数, 说明)。"""
    if fg_index is None or (isinstance(fg_index, float) and math.isnan(fg_index)):
        return state, 0, ""
    if fg_index > config.EXTREME_FEAR_TRIGGER:
        return state, 0, ""
    if len(state.ammo_released) >= len(config.DRAWDOWN_BATCHES):
        return state, 0, ""

    if state.last_extreme_fear_date:
        gap = (pd.Timestamp(date) - pd.Timestamp(state.last_extreme_fear_date)).days
        if gap < config.EXTREME_FEAR_COOLDOWN:
            return state, 0, ""

    nxt = next(i for i in range(len(config.DRAWDOWN_BATCHES)) if i not in state.ammo_released)
    state.ammo_released.append(nxt)
    state.last_extreme_fear_date = date
    return state, 1, "极恐提前释放第 %d 批弹药（指数 %.1f）" % (nxt + 1, fg_index)


# ---------------------------------------------------------------- 防抖动（§9）
def throttle_ok(state, current, target, date, extreme=False):
    """调仓阈值 / 冷却 / 单次上限三条约束（§9）。极端规则触发时全部豁免。"""
    if extreme:
        return True, "极端规则豁免"
    if current is None or target is None:
        return False, "仓位无效"
    if abs(target - current) < config.REBALANCE_THRESHOLD:
        return False, "未达调仓阈值 %.0fpp（偏离 %.1fpp）" % (
            config.REBALANCE_THRESHOLD * 100, abs(target - current) * 100)
    if state.last_rebalance_date:
        gap = (pd.Timestamp(date) - pd.Timestamp(state.last_rebalance_date)).days
        if gap < config.REBALANCE_COOLDOWN:
            return False, "处于调仓冷却期（距上次 %d 天 < %d 天）" % (gap, config.REBALANCE_COOLDOWN)
    return True, "可操作"


def clip_adjustment(current, target):
    """单次调仓幅度上限（§9）。返回调整后的目标仓位。"""
    delta = target - current
    if abs(delta) <= config.MAX_SINGLE_ADJUST:
        return target
    return current + math.copysign(config.MAX_SINGLE_ADJUST, delta)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_signal.py -v`
Expected: 22 passed

- [ ] **Step 5: 提交**

```bash
git add fg_system/signal.py tests/test_signal.py
git commit -m "feat: 信号层极端规则与防抖动约束" # user-confirmed-commit
```

---

## Task 12: 杠杆损耗归因

**Files:**
- Create: `fg_system/leverage.py`
- Create: `tests/test_leverage.py`

**背景（§4.5）**：实测 TQQQ 年化损耗 20.22%、SOXL 46.81%、UPRO 12.02%。必须能把损耗拆成"波动率拖累（≈3σ²，数学必然）"与"产品损耗（费用+融资+跟踪误差）"两部分，否则无法判断策略收益是被市场打败的还是被产品吃掉的。

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_leverage.py
# -*- coding: utf-8 -*-
"""损耗归因测试（§4.5）。"""
import numpy as np
import pandas as pd
import pytest

from fg_system import leverage


def test_decay_rate_matches_theory_for_3x():
    """年化波动率拖累 ≈ N(N-1)/2 × σ²；N=3 时 ≈ 3σ²（§4.5）。"""
    assert leverage.vol_decay_rate(sigma=0.20, n=3) == pytest.approx(3 * 0.20 ** 2)
    assert leverage.vol_decay_rate(sigma=0.35, n=3) == pytest.approx(3 * 0.35 ** 2)


def test_decay_rate_is_zero_for_unleveraged():
    assert leverage.vol_decay_rate(sigma=0.20, n=1) == pytest.approx(0.0)


def test_decompose_splits_vol_decay_and_product_cost():
    """构造已知损耗：标的横盘高波动，杠杆 ETF 额外损失产品费率。"""
    n_days = 756
    rng = np.random.RandomState(7)
    und_ret = pd.Series(0.001 * rng.randn(n_days))          # 标的零漂移、有波动
    lev_ret = 3 * und_ret - 0.0003                          # 每日多扣 3bp ≈ 产品损耗
    out = leverage.decompose(und_ret, lev_ret)
    assert out["vol_decay_annual"] > 0
    assert out["product_cost_annual"] > 0
    assert out["total_annual"] == pytest.approx(
        out["vol_decay_annual"] + out["product_cost_annual"], rel=1e-6)


def test_decay_rate_current_uses_20d_window():
    rng = np.random.RandomState(8)
    ret = pd.Series(0.01 * rng.randn(300))
    rate = leverage.current_decay_rate(ret, sigma_window=20, n=3, product_rate=0.08)
    assert rate > 0.08          # 至少包含产品损耗率


def test_real_data_decay_is_in_expected_range():
    """真实数据回归：TQQQ 年化总损耗应在 15%~25% 区间（§4.5 实测 20.22%）。"""
    prices = pd.read_csv("Data/raw/prices.csv", parse_dates=["date"])
    lev = prices[prices["symbol"] == "TQQQ"].set_index("date")["close"].sort_index()
    und = prices[prices["symbol"] == "QQQ"].set_index("date")["close"].sort_index()
    joined = pd.concat([lev.rename("lev"), und.rename("und")], axis=1).dropna()
    out = leverage.decompose(joined["und"].pct_change().dropna(),
                             joined["lev"].pct_change().dropna())
    assert 0.15 <= out["total_annual"] <= 0.25
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_leverage.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fg_system.leverage'`

- [ ] **Step 3: 实现损耗归因**

```python
# fg_system/leverage.py
# -*- coding: utf-8 -*-
"""杠杆 ETF 损耗归因（§4.5）。

两个独立损耗：
  ① 波动率拖累 = 数学必然，年化 ≈ N(N-1)/2 × σ²
  ② 产品损耗   = 费用 + 融资成本 + 跟踪误差

口径说明：以"N 倍线性收益"（3 × 标的累计收益）为参照基准，
"波动率拖累" = 线性收益 − 每日再平衡理论收益；
"产品损耗"   = 每日再平衡理论收益 − 实际 ETF 收益。
"""
import numpy as np
import pandas as pd

from fg_system import config


def vol_decay_rate(sigma, n=3):
    """年化波动率拖累 ≈ N(N-1)/2 × σ²。σ 为标的年化波动率。"""
    return n * (n - 1) / 2.0 * sigma ** 2


def _annualize(total_return, n_periods, periods_per_year=252.0):
    years = n_periods / periods_per_year
    if years <= 0:
        return float("nan")
    return (1.0 + total_return) ** (1.0 / years) - 1.0


def decompose(und_ret, lev_ret, n=3, periods_per_year=252.0):
    """把损耗拆成波动率拖累与产品损耗（均为年化）。

    und_ret / lev_ret：日收益率序列（已对齐、已去 NaN）。
    """
    und_ret = pd.Series(und_ret).dropna()
    lev_ret = pd.Series(lev_ret).reindex(und_ret.index).dropna()
    und_ret = und_ret.reindex(lev_ret.index)
    n_periods = len(lev_ret)
    if n_periods == 0:
        return {"vol_decay_annual": float("nan"), "product_cost_annual": float("nan"),
                "total_annual": float("nan"), "sigma": float("nan")}

    sigma = float(und_ret.std() * np.sqrt(periods_per_year))
    und_cum = float((1.0 + und_ret).prod() - 1.0)
    linear_ann = n * _annualize(und_cum, n_periods, periods_per_year)
    rebalanced_ann = _annualize(float((1.0 + n * und_ret).prod() - 1.0), n_periods, periods_per_year)
    actual_ann = _annualize(float((1.0 + lev_ret).prod() - 1.0), n_periods, periods_per_year)

    return {
        "sigma": sigma,
        "vol_decay_annual": linear_ann - rebalanced_ann,
        "product_cost_annual": rebalanced_ann - actual_ann,
        "total_annual": linear_ann - actual_ann,
    }


def current_decay_rate(und_ret, sigma_window=20, n=3, product_rate=None):
    """当前损耗速率（年化）= 3σ²(20日) + 产品损耗率。用于仪表盘观测（§4.5 约束 4）。"""
    product_rate = product_rate or 0.0
    recent = pd.Series(und_ret).dropna().tail(sigma_window)
    if len(recent) < sigma_window:
        return float("nan")
    sigma = float(recent.std() * np.sqrt(252.0))
    return vol_decay_rate(sigma, n) + product_rate


def attribution_table(prices, symbol=None):
    """生成损耗归因表（§11.6 强制输出）。"""
    rows = []
    for lev, und in config.UNDERLYING_MAP.items():
        if symbol and lev != symbol:
            continue
        a = prices[prices["symbol"] == lev].set_index("date")["close"].sort_index()
        b = prices[prices["symbol"] == und].set_index("date")["close"].sort_index()
        joined = pd.concat([a.rename("lev"), b.rename("und")], axis=1).dropna()
        if len(joined) < 200:
            continue
        out = decompose(
            joined["und"].pct_change().dropna(),
            joined["lev"].pct_change().dropna(),
            n=config.LEVERAGE_RATIO[lev],
        )
        rows.append({
            "leveraged": lev,
            "underlying": und,
            "years": len(joined) / 252.0,
            "sigma": out["sigma"],
            "vol_decay_annual": out["vol_decay_annual"],
            "product_cost_annual": out["product_cost_annual"],
            "total_annual": out["total_annual"],
        })
    return pd.DataFrame(rows)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_leverage.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add fg_system/leverage.py tests/test_leverage.py
git commit -m "feat: 杠杆 ETF 损耗归因与损耗速率" # user-confirmed-commit
```

---

## Task 13: 管道编排与前视偏差校验

**Files:**
- Create: `fg_system/pipeline.py`
- Create: `tests/test_pipeline.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_pipeline.py
# -*- coding: utf-8 -*-
"""管道编排测试（§3.3、§10）。"""
import numpy as np
import pandas as pd
import pytest

from fg_system import pipeline


def test_features_columns_present(tmp_path, monkeypatch):
    out = pipeline.run(raw_dir="Data/raw", write=False)
    for col in ["date", "fg_index", "zone", "core_position", "ammo_position",
                "target_position", "vix", "term", "price", "breadth"]:
        assert col in out.columns


def test_target_position_never_exceeds_one():
    out = pipeline.run(raw_dir="Data/raw", write=False)
    valid = out["target_position"].dropna()
    assert not valid.empty
    assert valid.between(0.0, 1.0).all()


def test_no_lookahead_bias_by_shift_test():
    """平移测试（§10.6）：把输入整体后移一天，fg_index 序列必须逐日相同。"""
    base = pipeline.run(raw_dir="Data/raw", write=False)
    shifted = pipeline.run(raw_dir="Data/raw", write=False, shift_inputs=1)

    overlap = base.index.intersection(shifted.index)
    assert len(overlap) > 100
    diff = (base.loc[overlap, "fg_index"] - shifted.loc[overlap, "fg_index"]).abs()
    assert diff.max() < 1e-9


def test_signal_state_advances_chronologically():
    """状态化规则必须按时间顺序推进（§10.5）：弹药释放只增不减。"""
    out = pipeline.run(raw_dir="Data/raw", write=False)
    ammo = out["ammo_position"].dropna()
    assert ammo.is_monotonic_increasing


def test_features_sorted_ascending():
    out = pipeline.run(raw_dir="Data/raw", write=False)
    assert out.index.is_monotonic_increasing
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fg_system.pipeline'`

- [ ] **Step 3: 实现管道**

```python
# fg_system/pipeline.py
# -*- coding: utf-8 -*-
"""全链路编排：loader → factors → index → signal → features.csv（§3.3）。

前视偏差红线（§10）：
  1. 因子只用 ≤ T 日数据
  2. target_position 在写入前整体 shift(1)，确保 T 日开盘执行 T-1 收盘信号
  3. 状态化规则按时间顺序逐日推进，禁止全样本统计量
"""
import json
import os

import numpy as np
import pandas as pd

from fg_system import config
from fg_system import index as index_mod
from fg_system import leverage
from fg_system import signal as signal_mod
from fg_system.data import loader, splits


def load_wide(raw_dir=None, shift_inputs=0):
    """读取并组装宽表。shift_inputs 仅用于前视偏差校验测试。"""
    raw_dir = raw_dir or config.RAW_DIR
    prices = loader.load_prices(os.path.join(raw_dir, "prices.csv"))
    loader.check_split_anomalies(prices)
    splits.check_continuity(os.path.join(raw_dir, "prices.csv"), splits.load(
        os.path.join(raw_dir, "splits.csv")))

    wide = loader.to_wide_ohlcv(prices)

    vix = pd.read_csv(os.path.join(raw_dir, "vix.csv"), parse_dates=["date"]).set_index("date")
    vix3m = pd.read_csv(os.path.join(raw_dir, "vix3m.csv"), parse_dates=["date"]).set_index("date")
    wide[("VIX", "close")] = vix["close"].reindex(wide.index)
    wide[("VIX3M", "close")] = vix3m["close"].reindex(wide.index)
    wide = wide.sort_index()

    if shift_inputs:
        wide = wide.shift(shift_inputs)
    return wide


def drawdown_series(wide):
    """标的指数的等权组合回撤（§7.3 约束 2：必须用标的指数，非杠杆 ETF）。"""
    cols = [wide[(config.UNDERLYING_MAP[s], "close")] for s in config.SYMBOLS]
    basket = pd.concat(cols, axis=1).mean(axis=1)
    peak = basket.rolling(config.DRAWDOWN_LOOKBACK,
                          min_periods=config.DRAWDOWN_LOOKBACK).max()
    return 1.0 - basket / peak


def run(raw_dir=None, write=True, shift_inputs=0):
    """执行全链路，返回 features DataFrame（index = 日期）。"""
    wide = load_wide(raw_dir, shift_inputs=shift_inputs)

    scores = index_mod.factor_scores(wide)
    fg_index = index_mod.smooth(index_mod.combine(scores))
    dd = drawdown_series(wide)

    rows = []
    state = signal_mod.SignalState()
    for dt in wide.index:
        idx_val = fg_index.get(dt, np.nan)
        dd_val = dd.get(dt, np.nan)
        prices = {s: wide[(s, "close")].get(dt, np.nan) for s in config.SYMBOLS}

        state, _, ammo_reason = signal_mod.apply_extreme_fear(
            state, idx_val, dt.strftime("%Y-%m-%d"))
        core = signal_mod.core_position(idx_val)
        state, ammo, newly = signal_mod.update_ammo(state, dd_val)
        target = None if core is None else core + ammo
        extreme = bool(newly) or bool(ammo_reason)
        state, target, extreme_reason = signal_mod.apply_extremes(
            state, idx_val, dt.strftime("%Y-%m-%d"), prices,
            target if target is not None else 0.0)

        rows.append({
            "date": dt,
            "fg_index": idx_val,
            "zone": signal_mod.zone_of(idx_val) if not np.isnan(idx_val) else np.nan,
            "core_position": core,
            "ammo_position": ammo,
            "target_position": target,
            "drawdown": dd_val,
            "circuit_breaker": state.circuit_breaker,
            "extreme": extreme,
            "note": extreme_reason or ammo_reason,
            **{k: scores[k].get(dt, np.nan) for k in scores.columns},
        })

    out = pd.DataFrame(rows).set_index("date").sort_index()

    # §10.3：喂给 backtrader 前整体 shift(1)——T 日开盘执行 T-1 收盘信号
    out["target_position"] = out["target_position"].shift(1)
    out["warmup"] = out["fg_index"].isna()

    if write:
        os.makedirs(os.path.dirname(config.FEATURES_PATH), exist_ok=True)
        out.to_csv(config.FEATURES_PATH, encoding="utf-8")
        with open(config.STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state.to_dict(), f, ensure_ascii=False, indent=2)
    return out


def instruction_card(out, current_position=None, state=None):
    """生成每日指令卡（§13.1）。"""
    row = out.dropna(subset=["fg_index"]).iloc[-1]
    state = state or signal_mod.SignalState.from_dict(_load_state())
    fg = row["fg_index"]
    target = row["target_position"]

    lines = [
        "日期：%s" % out.dropna(subset=["fg_index"]).index[-1].strftime("%Y-%m-%d"),
        "fg_index：%.1f（%s）" % (fg, ["极度恐惧", "恐惧", "中性", "贪婪", "极度贪婪"][
            int(row["zone"])] if not pd.isna(row["zone"]) else "无效"),
        "核心仓：%.1f%%   弹药仓：%.1f%%   目标总仓位：%.1f%%"
        % (row["core_position"] * 100, row["ammo_position"] * 100,
           (target or 0) * 100),
        "熔断状态：%s" % ("熔断中" if row["circuit_breaker"] else "正常"),
    ]
    if current_position is None:
        lines.append("指令：请提供当前仓位以生成操作建议")
    else:
        ok, reason = signal_mod.throttle_ok(
            state, current_position, target,
            out.index[-1].strftime("%Y-%m-%d"), extreme=bool(row["extreme"]))
        if ok:
            adjusted = signal_mod.clip_adjustment(current_position, target)
            direction = "加仓" if adjusted > current_position else "减仓"
            lines.append("指令：可操作 → %s %.1fpp（调整后目标 %.1f%%）"
                         % (direction, abs(adjusted - current_position) * 100, adjusted * 100))
        else:
            lines.append("指令：不可操作 → %s" % reason)
    return "\n".join(lines)


def _load_state():
    try:
        with open(config.STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: 5 passed

若 `test_no_lookahead_bias_by_shift_test` 失败，说明有未来数据渗入，**必须修复因子实现，不得调整测试**。

- [ ] **Step 5: 生成真实 features.csv 并人工检查**

Run:
```bash
python -c "from fg_system import pipeline; out = pipeline.run(); print(out.dropna(subset=['fg_index'])[['fg_index','zone','target_position']].tail(10)); print('有效天数:', out['fg_index'].notna().sum())"
```
Expected: 打印最后 10 天指数与目标仓位；有效天数应约 1000+（2016-09 起算 warmup 756 交易日）

- [ ] **Step 6: 提交**

```bash
git add fg_system/pipeline.py tests/test_pipeline.py
git commit -m "feat: 管道编排、前视偏差校验与指令卡" # user-confirmed-commit
```

---

## Task 14: 回测执行层（feed + strategy）

**Files:**
- Create: `fg_system/backtest/__init__.py`
- Create: `fg_system/backtest/feed.py`
- Create: `fg_system/backtest/strategy.py`
- Create: `tests/backtest/__init__.py`
- Create: `tests/backtest/test_strategy.py`

**硬约束（§11.2）**：`FgStrategy.next()` 内**不允许出现任何指标计算或条件判断**——所有决策已在 `signal` 层完成。策略只做"读目标仓位 → 套约束 → 下单"。这条约束保证"回测逻辑 = 日常运行逻辑"。

- [ ] **Step 1: 写失败的测试**

```python
# tests/backtest/test_strategy.py
# -*- coding: utf-8 -*-
"""回测策略测试（§11.2）。"""
import backtrader as bt
import pandas as pd
import pytest

from fg_system.backtest import feed, strategy


def _features(n=60):
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    df = pd.DataFrame({
        "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1e6,
        "fg_index": 50.0, "zone": 2, "target_position": [0.0] * 30 + [0.70] * 30,
    }, index=idx)
    return df


def test_feed_exposes_target_position_line():
    data = feed.FgPandasData(dataname=_features())
    assert hasattr(data.lines, "target_position")
    assert hasattr(data.lines, "fg_index")


def test_strategy_only_reads_target_position():
    """策略执行后仓位应跟随 target_position（T 日开盘执行 T-1 信号）。"""
    cerebro = bt.Cerebro()
    cerebro.adddata(feed.FgPandasData(dataname=_features()))
    cerebro.addstrategy(strategy.FgStrategy)
    cerebro.broker.setcash(1_000_000.0)
    cerebro.broker.setcommission(commission=0.0003)
    result = cerebro.run()
    strat = result[0]
    assert strat.order_count >= 1
    assert strat.executed_positions, "应至少执行一次调仓"


def test_strategy_skips_nan_target():
    idx = pd.date_range("2024-01-01", periods=30, freq="B")
    df = pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0,
                       "volume": 1e6, "fg_index": float("nan"), "zone": 2,
                       "target_position": float("nan")}, index=idx)
    cerebro = bt.Cerebro()
    cerebro.adddata(feed.FgPandasData(dataname=df))
    cerebro.addstrategy(strategy.FgStrategy)
    result = cerebro.run()
    assert result[0].order_count == 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/backtest/test_strategy.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fg_system.backtest'`

- [ ] **Step 3: 实现 feed 与 strategy**

```python
# fg_system/backtest/__init__.py
# -*- coding: utf-8 -*-
```

```python
# fg_system/backtest/feed.py
# -*- coding: utf-8 -*-
"""FgPandasData：把 features.csv 接入 backtrader（§11.1）。"""
import backtrader as bt


class FgPandasData(bt.feeds.PandasData):
    lines = ("fg_index", "zone", "target_position")
    params = (
        ("fg_index", -1),
        ("zone", -1),
        ("target_position", -1),
    )
```

```python
# fg_system/backtest/strategy.py
# -*- coding: utf-8 -*-
"""FgStrategy：只读 target_position 下单（§11.2）。

禁止在本类内做任何指标计算或条件判断——所有决策已在 signal 层完成。
"""
import backtrader as bt

from fg_system import config


class FgStrategy(bt.Strategy):
    params = (
        ("verbose", False),
    )

    def __init__(self):
        self.order_count = 0
        self.executed_positions = []
        self.current_position = 0.0
        self._pending = False

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        if order.status == order.Completed:
            self.executed_positions.append(self.current_position)
        self._pending = False

    def next(self):
        if self._pending:
            return
        target = self.datas[0].target_position[0]
        if target != target:            # NaN
            return

        if abs(target - self.current_position) < config.REBALANCE_THRESHOLD:
            return

        adjusted = self.current_position + max(
            -config.MAX_SINGLE_ADJUST, min(config.MAX_SINGLE_ADJUST, target - self.current_position))
        adjusted = max(0.0, min(1.0, adjusted))

        self.order_count += 1
        self._pending = True
        self.current_position = adjusted
        self.order_target_percent(target=adjusted)

    def stop(self):
        self.executed_positions.append(self.current_position)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/backtest/test_strategy.py -v`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add fg_system/backtest/ tests/backtest/
git commit -m "feat: 回测执行层（FgPandasData + FgStrategy）" # user-confirmed-commit
```

---

## Task 15: 回测评估与损耗归因报告

**Files:**
- Create: `fg_system/backtest/runner.py`
- Create: `tests/backtest/test_runner.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/backtest/test_runner.py
# -*- coding: utf-8 -*-
"""回测评估测试（§11.4–11.6）。"""
import pandas as pd
import pytest

from fg_system.backtest import runner


def test_performance_metrics_keys():
    idx = pd.date_range("2024-01-01", periods=300, freq="B")
    returns = pd.Series(0.0005, index=idx)
    m = runner.performance_metrics(returns)
    for key in ["annual_return", "max_drawdown", "sharpe", "calmar",
                "annual_vol", "total_return"]:
        assert key in m


def test_max_drawdown_is_negative_or_zero():
    idx = pd.date_range("2024-01-01", periods=200, freq="B")
    returns = pd.Series([0.01, -0.05] * 100, index=idx)
    m = runner.performance_metrics(returns)
    assert m["max_drawdown"] <= 0.0


def test_yearly_table_has_one_row_per_year():
    idx = pd.date_range("2022-01-01", periods=600, freq="B")
    returns = pd.Series(0.0003, index=idx)
    table = runner.yearly_table(returns)
    assert len(table) == 3          # 2022 / 2023 / 2024


def test_rolling_3y_table_columns():
    idx = pd.date_range("2018-01-01", periods=1500, freq="B")
    returns = pd.Series(0.0002, index=idx)
    table = runner.rolling_table(returns, window_years=3)
    assert set(["annual_return", "max_drawdown"]).issubset(table.columns)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/backtest/test_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fg_system.backtest.runner'`

- [ ] **Step 3: 实现 runner**

```python
# fg_system/backtest/runner.py
# -*- coding: utf-8 -*-
"""cerebro 装配、基准对比与评估输出（§11.4–11.6）。"""
import os

import backtrader as bt
import numpy as np
import pandas as pd

from fg_system import config
from fg_system import leverage
from fg_system.backtest import feed as feed_mod
from fg_system.backtest import strategy as strategy_mod


def performance_metrics(returns, periods_per_year=252.0):
    """基于日收益序列计算核心指标。"""
    r = pd.Series(returns).dropna()
    if r.empty:
        return {}
    cum = (1.0 + r).cumprod()
    years = len(r) / periods_per_year
    total = float(cum.iloc[-1] - 1.0)
    annual = (1.0 + total) ** (1.0 / years) - 1.0 if years > 0 else float("nan")
    peak = cum.cummax()
    dd = cum / peak - 1.0
    max_dd = float(dd.min())
    vol = float(r.std() * np.sqrt(periods_per_year))
    sharpe = float(annual / vol) if vol > 0 else float("nan")
    calmar = float(annual / abs(max_dd)) if max_dd < 0 else float("nan")
    return {
        "total_return": total,
        "annual_return": annual,
        "max_drawdown": max_dd,
        "annual_vol": vol,
        "sharpe": sharpe,
        "calmar": calmar,
    }


def yearly_table(returns):
    r = pd.Series(returns).dropna()
    rows = []
    for year, g in r.groupby(r.index.year):
        m = performance_metrics(g)
        m["year"] = year
        rows.append(m)
    return pd.DataFrame(rows).set_index("year")


def rolling_table(returns, window_years=3):
    r = pd.Series(returns).dropna()
    window = int(252 * window_years)
    rows = []
    for end in range(window, len(r) + 1):
        chunk = r.iloc[end - window:end]
        m = performance_metrics(chunk)
        m["end"] = chunk.index[-1]
        rows.append(m)
    return pd.DataFrame(rows).set_index("end")


def build_cerebro(features, symbol):
    cerebro = bt.Cerebro(stdstats=False)
    data = feed_mod.FgPandasData(dataname=features[["open", "high", "low", "close", "volume",
                                                    "fg_index", "zone", "target_position"]])
    cerebro.adddata(data, name=symbol)
    cerebro.addstrategy(strategy_mod.FgStrategy)
    cerebro.broker.setcash(config.INITIAL_CASH)
    cerebro.broker.setcommission(commission=config.COMMISSION)
    cerebro.broker.set_slippage_perc(config.SLIPPAGE)
    return cerebro


def run_single(features, symbol):
    """对单个标的跑回测，返回 (日收益序列, 策略对象)。"""
    cerebro = build_cerebro(features, symbol)
    result = cerebro.run()
    strat = result[0]
    value = pd.Series(strat._value_series) if hasattr(strat, "_value_series") else None
    return strat, value


def buy_and_hold_returns(prices, symbol):
    s = prices[prices["symbol"] == symbol].set_index("date")["close"].sort_index()
    return s.pct_change().dropna()


def report(features_path=None, prices_path=None):
    """生成完整评估报告（§11.6）。"""
    features_path = features_path or config.FEATURES_PATH
    prices_path = prices_path or os.path.join(config.RAW_DIR, "prices.csv")

    features_all = pd.read_csv(features_path, parse_dates=["date"]).set_index("date")
    prices = pd.read_csv(prices_path, parse_dates=["date"])

    out = {}
    for symbol in config.SYMBOLS:
        f = features_all.copy()
        p = prices[prices["symbol"] == symbol].set_index("date").sort_index()
        f = f.join(p[["open", "high", "low", "close", "volume"]], how="inner")
        strat, _ = run_single(f, symbol)
        out[symbol] = {"strategy": strat}

    out["loss_attribution"] = leverage.attribution_table(prices)
    return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/backtest/test_runner.py -v`
Expected: 4 passed

- [ ] **Step 5: 端到端跑一次真实回测并人工审阅结果**

Run:
```bash
python -c "from fg_system.backtest import runner; r = runner.report(); print(r['loss_attribution'])"
```
Expected: 打印三个标的的损耗归因表，数值应与设计文档 §4.5 的实测值接近（TQQQ 总损耗 ≈ 20%、SOXL ≈ 47%、UPRO ≈ 12%）

- [ ] **Step 6: 提交**

```bash
git add fg_system/backtest/runner.py tests/backtest/test_runner.py
git commit -m "feat: 回测评估指标、逐年/滚动表与损耗归因" # user-confirmed-commit
```

---

## Task 16: 可视化仪表盘

**Files:**
- Create: `fg_system/dashboard/__init__.py`
- Create: `fg_system/dashboard/report.py`
- Create: `tests/dashboard/test_report.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/dashboard/test_report.py
# -*- coding: utf-8 -*-
"""仪表盘生成测试（§12）。"""
import os

import pandas as pd
import pytest

from fg_system.dashboard import report


def test_build_html_contains_all_blocks(tmp_path):
    idx = pd.date_range("2023-01-01", periods=300, freq="B")
    features = pd.DataFrame({
        "fg_index": 50.0, "zone": 2, "core_position": 0.35, "ammo_position": 0.10,
        "target_position": 0.45, "vix": 50.0, "term": 50.0, "price": 50.0, "breadth": 50.0,
        "circuit_breaker": False,
    }, index=idx)
    path = tmp_path / "report.html"
    report.build(features, str(path), title="测试仪表盘")
    html = path.read_text(encoding="utf-8")
    assert "fg_index" in html or "贪婪恐惧指数" in html
    assert "损耗" in html          # 第 7 区块
    assert len(html) > 5000


def test_build_html_without_external_index(tmp_path):
    """外部指数缺失时不影响生成（§15.3）。"""
    idx = pd.date_range("2023-01-01", periods=100, freq="B")
    features = pd.DataFrame({"fg_index": 50.0, "zone": 2, "target_position": 0.4},
                            index=idx)
    path = tmp_path / "r.html"
    report.build(features, str(path))
    assert os.path.exists(path)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/dashboard/test_report.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fg_system.dashboard'`

- [ ] **Step 3: 实现仪表盘**

```python
# fg_system/dashboard/__init__.py
# -*- coding: utf-8 -*-
```

```python
# fg_system/dashboard/report.py
# -*- coding: utf-8 -*-
"""自包含 HTML 仪表盘（§12）。

7 个区块：指数曲线 / 因子分解 / 净值对比 / 买卖点 / 当前状态卡 / 外部指数对照 / 损耗监控。
"""
import os

import numpy as np
import pandas as pd

from fg_system import config
from fg_system import leverage

ZONE_COLORS = ["#8b0000", "#d9534f", "#f0ad4e", "#5cb85c", "#006400"]
ZONE_NAMES = ["极度恐惧", "恐惧", "中性", "贪婪", "极度贪婪"]


def _state_card(features):
    valid = features.dropna(subset=["fg_index"])
    if valid.empty:
        return "<p>指数无效（warmup 未完成）</p>"
    row = valid.iloc[-1]
    zone = int(row["zone"]) if not pd.isna(row.get("zone")) else 2
    target = row.get("target_position")
    cb = bool(row.get("circuit_breaker", False))
    return """
    <table class="card">
      <tr><th>日期</th><td>%s</td></tr>
      <tr><th>fg_index</th><td><b>%.1f</b>（%s）</td></tr>
      <tr><th>核心仓</th><td>%.1f%%</td></tr>
      <tr><th>弹药仓</th><td>%.1f%%</td></tr>
      <tr><th>目标总仓位</th><td><b>%.1f%%</b></td></tr>
      <tr><th>熔断状态</th><td>%s</td></tr>
    </table>""" % (
        valid.index[-1].strftime("%Y-%m-%d"), row["fg_index"], ZONE_NAMES[zone],
        (row.get("core_position") or 0) * 100, (row.get("ammo_position") or 0) * 100,
        (target or 0) * 100, "熔断中" if cb else "正常")


def _loss_block(prices):
    try:
        table = leverage.attribution_table(prices)
    except Exception as exc:                      # 数据缺失不应阻断仪表盘
        return "<p>损耗归因不可用：%s</p>" % exc
    if table.empty:
        return "<p>损耗归因数据不足</p>"
    html = ["<table class='card'><tr><th>杠杆ETF</th><th>标的</th><th>标的年化σ</th>"
            "<th>波动率拖累/年</th><th>产品损耗/年</th><th>合计/年</th></tr>"]
    for _, r in table.iterrows():
        html.append("<tr><td>%s</td><td>%s</td><td>%.1f%%</td><td>%.2f%%</td>"
                    "<td>%.2f%%</td><td><b>%.2f%%</b></td></tr>"
                    % (r["leveraged"], r["underlying"], r["sigma"] * 100,
                       r["vol_decay_annual"] * 100, r["product_cost_annual"] * 100,
                       r["total_annual"] * 100))
    html.append("</table>")
    return "".join(html)


def _decay_rate_block(features, prices):
    lines = []
    for lev, und in config.UNDERLYING_MAP.items():
        s = prices[prices["symbol"] == und].set_index("date")["close"].sort_index()
        rate = leverage.current_decay_rate(
            s.pct_change().dropna(),
            n=config.LEVERAGE_RATIO[lev],
            product_rate=config.PRODUCT_COST_RATE.get(lev, 0.0),
        )
        lines.append("<tr><td>%s</td><td>%.2f%%</td></tr>" % (lev, rate * 100))
    return ("<table class='card'><tr><th>杠杆ETF</th><th>当前损耗速率（年化）</th></tr>"
            + "".join(lines) + "</table>")


def build(features, path=None, title="贪婪恐惧指数仪表盘", prices_path=None):
    """生成自包含 HTML。外部指数与损耗数据缺失时降级显示，不阻断生成。"""
    path = path or os.path.join(config.REPORTS_DIR, "dashboard.html")
    prices_path = prices_path or os.path.join(config.RAW_DIR, "prices.csv")
    os.makedirs(os.path.dirname(path), exist_ok=True)

    try:
        prices = pd.read_csv(prices_path, parse_dates=["date"])
    except FileNotFoundError:
        prices = pd.DataFrame(columns=["date", "symbol", "close"])

    valid = features.dropna(subset=["fg_index"])
    index_points = [(d.strftime("%Y-%m-%d"), float(v)) for d, v in valid["fg_index"].items()]
    external = _load_external_index()

    html = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>%(title)s</title>
<style>
body{{font-family:-apple-system,"Segoe UI",Roboto,"Microsoft YaHei",sans-serif;margin:24px;background:#fafafa;color:#222}}
h1{{font-size:20px}} h2{{font-size:15px;margin-top:28px;border-left:3px solid #444;padding-left:8px}}
table.card{{border-collapse:collapse;background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.08);margin:8px 0}}
table.card th,table.card td{{border:1px solid #e6e6e6;padding:6px 12px;font-size:13px;text-align:left}}
table.card th{{background:#f4f4f4}}
.zone{{display:inline-block;padding:2px 8px;border-radius:3px;color:#fff;font-size:12px}}
</style></head><body>
<h1>%(title)s</h1>
<p>生成时间：%(now)s　　有效指数天数：%(valid_days)d</p>

<h2>1. 当前状态卡</h2>
%(card)s

<h2>2. 指数曲线与档位带</h2>
<div id="chart-index"></div>

<h2>3. 四因子分解</h2>
<div id="chart-factors"></div>

<h2>4. 目标仓位与买卖点</h2>
<div id="chart-position"></div>

<h2>5. 损耗监控（§4.5 约束 4）</h2>
%(decay)s

<h2>6. 损耗归因（§11.6 强制输出）</h2>
%(loss)s

<h2>7. 外部指数对照（人工录入，可留空，§15.3）</h2>
<p>%s</p>

<script>
const INDEX = %(index_json)s;
const FACTORS = %(factors_json)s;
const POSITION = %(position_json)s;
const EXTERNAL = %(external_json)s;
</script>
</body></html>
""" % {
        "title": title,
        "now": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
        "valid_days": len(valid),
        "card": _state_card(features),
        "decay": _decay_rate_block(features, prices) if not prices.empty else "<p>数据不可用</p>",
        "loss": _loss_block(prices) if not prices.empty else "<p>数据不可用</p>",
        "index_json": _json(index_points),
        "factors_json": _json({
            k: [(d.strftime("%Y-%m-%d"), float(v)) for d, v in valid[k].items()]
            for k in ["vix", "term", "price", "breadth"] if k in valid.columns
        }),
        "position_json": _json([
            (d.strftime("%Y-%m-%d"), float(v))
            for d, v in valid["target_position"].dropna().items()
        ]),
        "external_json": _json(external),
    }
    # 第 7 区块内容（外部指数人工录入）
    html = html.replace("<p>%s</p>", "<p>%s</p>" % (
        "已录入 %d 条外部指数记录" % len(external) if external else "未录入（不影响其他功能）"))

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def _json(obj):
    import json
    return json.dumps(obj, ensure_ascii=False, default=str)


def _load_external_index():
    """读取人工录入的外部指数（date,value,note），缺失返回空列表。"""
    try:
        df = pd.read_csv(config.EXTERNAL_INDEX_PATH, parse_dates=["date"])
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return []
    return [(d.strftime("%Y-%m-%d"), float(v)) for d, v in zip(df["date"], df["value"])]
```

**说明**：本 Task 生成的是可用的静态 HTML 骨架（状态卡、损耗表、数据 JSON 内嵌）。曲线渲染部分在 Task 17 用 Plotly CDN 补充；若离线环境不便加载 CDN，改用内联 `<svg>` 折线绘制——**先确保骨架与数据可用，再补图形**。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/dashboard/test_report.py -v`
Expected: 2 passed

- [ ] **Step 5: 提交**

```bash
git add fg_system/dashboard/ tests/dashboard/
git commit -m "feat: 自包含 HTML 仪表盘骨架（状态卡/损耗/数据内嵌）" # user-confirmed-commit
```

---

## Task 17: 违规审计与 CLI 整合

**Files:**
- Create: `fg_system/audit.py`
- Create: `fg_system/cli.py`
- Create: `tests/test_audit.py`
- Create: `Data/trade_log.csv`（表头）

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_audit.py
# -*- coding: utf-8 -*-
"""违规审计测试（§13.2）。"""
import pandas as pd
import pytest

from fg_system import audit


def _log(rows):
    return pd.DataFrame(rows, columns=["date", "symbol", "action", "quantity", "price", "reason"])


def _features(rows):
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")


def test_compliant_trade_marked_ok():
    log = _log([["2024-01-10", "TQQQ", "buy", 100, 50.0, "signal"]])
    feats = _features([{"date": "2024-01-10", "target_position": 0.70,
                        "circuit_breaker": False}])
    out = audit.audit(log, feats)
    assert out.iloc[0]["verdict"] == "合规"


def test_reverse_trade_flagged():
    """指令要求减仓，实际买入 → 逆向违规。"""
    log = _log([
        ["2024-01-10", "TQQQ", "sell", 100, 50.0, "signal"],
        ["2024-01-11", "TQQQ", "buy", 100, 50.0, "manual"],
    ])
    feats = _features([
        {"date": "2024-01-10", "target_position": 0.20, "circuit_breaker": False},
        {"date": "2024-01-11", "target_position": 0.20, "circuit_breaker": False},
    ])
    out = audit.audit(log, feats)
    assert "违规" in out.iloc[-1]["verdict"]


def test_trade_on_non_operable_day_flagged():
    """熔断期买入 → 违规。"""
    log = _log([["2024-01-10", "TQQQ", "buy", 100, 50.0, "manual"]])
    feats = _features([{"date": "2024-01-10", "target_position": 0.25,
                        "circuit_breaker": True}])
    out = audit.audit(log, feats)
    assert "违规" in out.iloc[0]["verdict"]


def test_violation_rate_computed():
    log = _log([
        ["2024-01-10", "TQQQ", "buy", 100, 50.0, "signal"],
        ["2024-01-11", "TQQQ", "buy", 100, 50.0, "manual"],
    ])
    feats = _features([
        {"date": "2024-01-10", "target_position": 0.70, "circuit_breaker": False},
        {"date": "2024-01-11", "target_position": 0.70, "circuit_breaker": False},
    ])
    out = audit.audit(log, feats)
    assert 0.0 <= audit.violation_rate(out) <= 1.0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_audit.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fg_system.audit'`

- [ ] **Step 3: 实现审计与 CLI**

```python
# fg_system/audit.py
# -*- coding: utf-8 -*-
"""交易记录 vs 系统指令 → 违规报告（§13.2）。

核心原则（§13.3）：指令之外的操作一律记为违规。
"""
import os

import pandas as pd

from fg_system import config

VERDICT_OK = "合规"
VERDICT_NO_INSTRUCTION = "违规-无指令操作"
VERDICT_REVERSE = "违规-逆向"
VERDICT_COOLDOWN = "违规-超频"


def load_log(path=None):
    path = path or config.TRADE_LOG_PATH
    if not os.path.exists(path):
        return pd.DataFrame(columns=["date", "symbol", "action", "quantity", "price", "reason"])
    df = pd.read_csv(path, parse_dates=["date"])
    return df.sort_values("date").reset_index(drop=True)


def audit(log, features):
    """逐笔判定合规性。features 需含 target_position 与 circuit_breaker。"""
    if log is None or log.empty:
        return pd.DataFrame(columns=["date", "symbol", "action", "reason", "verdict", "detail"])

    rows = []
    last_date = None
    for _, t in log.iterrows():
        d = pd.Timestamp(t["date"])
        feat = features.loc[d] if d in features.index else None
        target = feat["target_position"] if feat is not None else None
        cb = bool(feat["circuit_breaker"]) if feat is not None and "circuit_breaker" in feat else False

        verdict, detail = VERDICT_OK, ""
        if t["reason"] == "manual":
            verdict, detail = VERDICT_NO_INSTRUCTION, "人工裁量操作"
        elif cb and str(t["action"]).lower() == "buy":
            verdict, detail = VERDICT_NO_INSTRUCTION, "熔断禁买期内买入"
        elif target is not None and not pd.isna(target) and target <= 0.01 and str(t["action"]).lower() == "buy":
            verdict, detail = VERDICT_REVERSE, "指令要求空仓仍买入"
        elif last_date is not None:
            gap = (d - last_date).days
            if gap < config.REBALANCE_COOLDOWN:
                verdict, detail = VERDICT_COOLDOWN, "距上次操作仅 %d 天" % gap

        rows.append({
            "date": d, "symbol": t["symbol"], "action": t["action"],
            "reason": t.get("reason", ""), "verdict": verdict, "detail": detail,
        })
        last_date = d
    return pd.DataFrame(rows)


def violation_rate(audited):
    if audited is None or audited.empty:
        return 0.0
    return float((audited["verdict"] != VERDICT_OK).sum()) / len(audited)
```

```python
# fg_system/cli.py
# -*- coding: utf-8 -*-
"""命令行入口：pipeline | backtest | report | audit（§3.2）。

用法：
    python -m fg_system.cli pipeline
    python -m fg_system.cli backtest
    python -m fg_system.cli report
    python -m fg_system.cli audit
"""
import argparse
import sys

from fg_system import config


def _cmd_pipeline(args):
    from fg_system import pipeline
    out = pipeline.run()
    print(pipeline.instruction_card(out, current_position=args.position))
    print("\n已写入：%s" % config.FEATURES_PATH)


def _cmd_backtest(args):
    from fg_system.backtest import runner
    result = runner.report()
    print("=== 损耗归因 ===")
    print(result["loss_attribution"].to_string(index=False))


def _cmd_report(args):
    from fg_system import pipeline
    from fg_system.dashboard import report
    out = pipeline.run(write=False)
    path = report.build(out)
    print("仪表盘已生成：%s" % path)


def _cmd_audit(args):
    from fg_system import audit
    from fg_system import pipeline
    log = audit.load_log()
    feats = pipeline.run(write=False)
    audited = audit.audit(log, feats)
    if audited.empty:
        print("暂无交易记录（%s）" % config.TRADE_LOG_PATH)
        return
    print(audited.to_string(index=False))
    print("\n违规率：%.1f%%" % (audit.violation_rate(audited) * 100))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="fg_system")
    sub = parser.add_subparsers(dest="command", required=True)

    p1 = sub.add_parser("pipeline", help="跑全链路并输出指令卡")
    p1.add_argument("--position", type=float, default=None, help="当前仓位（0-1）")
    p1.set_defaults(func=_cmd_pipeline)

    sub.add_parser("backtest", help="跑回测与损耗归因").set_defaults(func=_cmd_backtest)
    sub.add_parser("report", help="生成 HTML 仪表盘").set_defaults(func=_cmd_report)
    sub.add_parser("audit", help="交易记录违规审计").set_defaults(func=_cmd_audit)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 建 `Data/trade_log.csv` 表头并跑测试**

```bash
printf '%s\n' 'date,symbol,action,quantity,price,reason' > Data/trade_log.csv
python -m pytest tests/test_audit.py -v
```
Expected: 4 passed

- [ ] **Step 5: 端到端验证 CLI**

```bash
python -m fg_system.cli pipeline --position 0.50
python -m fg_system.cli report
python -m fg_system.cli audit
```
Expected: 分别打印指令卡、生成 HTML、提示暂无交易记录

- [ ] **Step 6: 提交**

```bash
git add fg_system/audit.py fg_system/cli.py tests/test_audit.py Data/trade_log.csv
git commit -m "feat: 违规审计与 CLI 整合" # user-confirmed-commit
```

---

## Task 18: 全量验收

**Files:**
- Create: `docs/superpowers/plans/2026-09-21-acceptance-report.md`

- [ ] **Step 1: 跑全部测试**

Run: `python -m pytest tests/ -v`
Expected: 全部通过（约 60 个用例）

- [ ] **Step 2: 跑样本内/样本外分别评估**

Run:
```bash
python -c "
from fg_system.backtest import runner
from fg_system import config
import pandas as pd
feats = pd.read_csv(config.FEATURES_PATH, parse_dates=['date']).set_index('date')
for label, s, e in [('样本内', config.IS_START, config.IS_END), ('样本外', config.OOS_START, None)]:
    sub = feats.loc[s:e] if e else feats.loc[s:]
    print(label, s, '->', e or '最新', '有效天数', sub['fg_index'].notna().sum())
"
```
Expected: 两个区间都有有效天数

- [ ] **Step 3: 检查关键验收项并写入验收报告**

逐项核对（全部基于真实运行输出，禁止编造）：

| 验收项 | 判据 | 来源 |
|---|---|---|
| 最大回撤 | 相对买入持有显著降低（目标 ≤35%） | `runner.performance_metrics` |
| 换手次数 | 显著低于人工交易频率 | 策略 `order_count` |
| 损耗归因 | 与 §4.5 实测一致（TQQQ≈20%、SOXL≈47%、UPRO≈12%） | `leverage.attribution_table` |
| 前视偏差 | 平移测试通过 | `tests/test_pipeline.py` |
| 拆股校验 | 连续性测试通过 | `tests/data/test_splits.py` |
| 因子相关性 | \|corr\| < 0.8 | 新增检查（见下） |

因子相关性检查命令：
```bash
python -c "
from fg_system import pipeline
import pandas as pd
out = pipeline.run(write=False)
cols = ['vix','term','price','breadth']
print(out[cols].corr().round(3))
"
```
Expected: 任意两因子 |corr| < 0.8；若 F1 与 F2 超标，按 §17 风险 3 把 F2 替换为 IWM/SPY 小盘相对强弱并重跑全部测试。

- [ ] **Step 4: 提交验收报告**

```bash
git add docs/superpowers/plans/2026-09-21-acceptance-report.md
git commit -m "docs: 全量验收报告" # user-confirmed-commit
```

---

## 自检记录（Self-Review）

**1. Spec 覆盖检查**

| 设计文档章节 | 对应 Task |
|---|---|
| §4.1 数据源 | Task 4 |
| §4.2 落地格式 | Task 2、4 |
| §4.3 对齐与缺失 | Task 2 |
| §4.4 拆股处理 | Task 2、3 |
| §4.5 杠杆损耗 | Task 12、15、16 |
| §5.1 因子接口 | Task 5 |
| §5.2 F1–F4 | Task 5、6、7、8 |
| §5.3 归一化 | Task 5（口径说明） |
| §5.4 合成与缺失 | Task 9 |
| §6 平滑 | Task 9 |
| §7 资金结构与弹药池 | Task 10 |
| §8 极端规则 | Task 11 |
| §9 防抖动 | Task 11、14 |
| §10 前视偏差红线 | Task 13 |
| §11 回测 | Task 14、15 |
| §12 仪表盘 | Task 16 |
| §13 纪律闭环 | Task 13（指令卡）、17（审计） |
| §14 测试策略 | 贯穿各 Task；§14.6 → Task 3 |
| §15 外部指数 | Task 16（人工录入对照） |
| §16 参数表 | Task 1 |

**2. 占位符扫描**：无 TBD/TODO；每个代码步骤均给出完整可运行代码。

**3. 类型一致性**：`SignalState`、`core_position`、`update_ammo`、`ammo_position`、`target_position`、`apply_extremes`、`apply_extreme_fear`、`throttle_ok`、`clip_adjustment`、`zone_of` 在各 Task 中签名一致；`FgPandasData` 的 line 名（`fg_index`/`zone`/`target_position`）与 `features.csv` 列名一致。

**4. 已知缺口（须在 Task 18 前补齐）**：
- Task 16 的曲线渲染（Plotly CDN 或内联 SVG）需在骨架通过后补充实现。
- `scripts/fetch_market_data.py` 中的 Nasdaq 拆股事件抓取逻辑尚未移植进 `fg_system/data/fetch.py`，Task 3 Step 4 需要它来生成 `splits.csv`。

