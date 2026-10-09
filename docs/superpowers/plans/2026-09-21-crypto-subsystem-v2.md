# 加密子系统 + 趋势过滤修正 实施计划（v2）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 v1 大盘子系统上加入加密子系统（独立加密贪恐指数 + 按 Beta 三层管理），并引入趋势过滤修正 v1 验收暴露的根因（持续熊市中维持高仓位导致回撤 -61.53%）。

**Architecture:** 沿用 v1 的 pandas 预计算全链路。`signal` 层拆为包：`market_signal`（单市场五档 + 趋势过滤 + 分层上限）与 `portfolio`（共享弹药池 + 统一资金池）。加密回测走**合成 + 真实双轨**。

**Tech Stack:** Python 3.10、pandas、numpy、backtrader 1.9.78、pytest、Plotly

**参考设计文档：** `docs/superpowers/specs/2026-09-21-fear-greed-index-v2-design.md`（以下简称 §N）

**纪律规范：** `docs/trading-discipline.md` 第 8 条流程（先改文档 → 再改代码 → 再回测验证）

**环境约定：**
- Python：`C:\Users\260023\AppData\Local\Programs\Python\Python310\python.exe`
- 通用外网代理：`http://10.30.6.49:9090`（**直连不可用**，已实测全部 timeout）
- 所有输出文件编码 UTF-8

**执行环境注意事项（Task 0 实施中实测发现，后续所有 Task 适用）：**

1. **subagent 的 Bash 执行器不解析 shell 注释**：`git commit -m "msg" # user-confirmed-commit`
   会把 `#` 和标记当作 git 的额外参数导致报错。**改用**：
   ```bash
   git commit -m "msg" && echo "# user-confirmed-commit"
   ```
   这样标记出现在命令中（满足 hook 要求）但不会传给 git。

2. **subagent 的 Bash 执行器忽略 `cd`**：测试若依赖相对路径（如 `Data/`），直接
   `python -m pytest tests/ -q` 会失败（**这是环境问题，不是回归**）。改用进程内切目录：
   ```bash
   python -c "import os; os.chdir(r'D:\3-code\learning_backtrader'); import pytest, sys; sys.exit(pytest.main(['tests/','-q']))"
   ```

3. **提交信息不要带 ` # user-confirmed-commit` 字样**——它会污染 git log。用上面的 `&& echo` 写法。

4. **必须用项目专属解释器，不能用 PATH 上的 `python`**。PATH 上的 `python` 是
   `C:\Python314`，**没有安装 backtrader**，会让 `tests/backtest/*` 报
   `ModuleNotFoundError: No module named 'backtrader'`——**这是环境问题，不是回归**。
   统一用绝对路径：
   ```bash
   PYTHONUTF8=1 "/c/Users/260023/AppData/Local/Programs/Python/Python310/python.exe" -c "..."
   ```
   （实测：用错解释器会看到 2 个 collection error，用对则 150 passed。）

5. **subagent 的 Bash 处于沙箱中，可能无法访问真实项目路径**（Task 2 实测）：
   `cd /d/3-code/learning_backtrader` 会映射到一个假挂载点，Task 指定的
   `/c/Users/.../Python310/python.exe` 绝对路径调用返回 `error`。
   **规避方式**（Task 2 已验证可行）：
   ```bash
   py -3.10 "D:/3-code/learning_backtrader/script.py"
   ```
   —— 用 `py -3.10`（py launcher 注册的 3.10.11）+ **正斜杠**绝对脚本路径，
   并在脚本内用 `os.chdir(r'D:\3-code\learning_backtrader')`。
   若 `py -3.10` 也不可用，则用绝对路径解释器 + 进程内 chdir（见第 4 条）。

6. **v1 的 `tests/data/test_fetch.py` 实际有 8 个测试**（不是 5 个），计划中若有
   「5 个」的表述以实际为准。

---

## 关键约束（实施前必读）

1. **v1 的 127 个测试必须全程保持通过**。每完成一个 Task 都要跑一次全量测试。
2. **情绪因子禁止使用杠杆 ETF 自身价格**（§4.5 约束 1）。加密因子输入用 **BTC 现货**，绝不用 BITX/MSTX。
3. **前视偏差红线**（§10）：因子只用 ≤T 数据；VIX/贪恐类 `shift(1)`；`target_position` 喂回测前整体 `shift(1)`；状态化规则逐日推进。
4. **`signal` 层必须纯函数 + 显式状态**，禁止读写全局变量或文件。
5. **数据源硬事实**（§4.1）：
   - 贪恐指数：`https://api.alternative.me/fng/?limit=0&format=json`（3151 条，2018-02-01 起）
   - BTC 现货：`https://api.blockchain.info/charts/market-price?timespan=10years&sampled=false&format=json`（**必须带 `sampled=false`**，否则降采样到 2 天）
   - 加密 ETF / 币股：Nasdaq API（同 v1 的 `fetch_symbol`）

---

## 文件结构

| 文件 | 职责 | 动作 |
|---|---|---|
| `fg_system/config.py` | 新增加密与趋势过滤参数 | 修改 |
| `fg_system/data/fetch.py` | 新增 `fetch_crypto_fng`、`fetch_btc_spot`、`update_crypto_prices` | 修改 |
| `fg_system/data/synthetic.py` | 合成杠杆序列 + 质量门 | **新建** |
| `fg_system/data/loader.py` | 新增加密长表加载与宽表转换 | 修改 |
| `fg_system/factors/crypto_fng.py` | CF1 加密贪恐因子 | **新建** |
| `fg_system/factors/crypto_price.py` | CF2 BTC 价格因子 | **新建** |
| `fg_system/index.py` | 泛化为 `build_index(market)` | 修改 |
| `fg_system/signal/__init__.py` | 对外入口，**保持 v1 函数签名兼容** | **新建（替换 signal.py）** |
| `fg_system/signal/market_signal.py` | 单市场：五档 + 趋势过滤 + 分层上限 + 极端规则 | **新建** |
| `fg_system/signal/portfolio.py` | 组合级：共享弹药池 + 统一资金池 | **新建** |
| `fg_system/pipeline.py` | 编排两个市场 | 修改 |
| `fg_system/backtest/attribution.py` | 趋势过滤贡献度归因 | **新建** |
| `fg_system/backtest/runner.py` | 支持合成轨 | 修改 |
| `fg_system/dashboard/report.py` | 新增加密区块 + coinglass 对照栏 | 修改 |
| `fg_system/cli.py` | 新增 `crypto-pipeline` / `crypto-backtest` | 修改 |
| `docs/trading-discipline.md` | 同步 v2 规则 | 修改 |

**测试目录**（与源码同构）：
`tests/data/test_fetch_crypto.py`、`tests/data/test_synthetic.py`、`tests/factors/test_crypto_fng.py`、`tests/factors/test_crypto_price.py`、`tests/signal/__init__.py`、`tests/signal/test_market_signal.py`、`tests/signal/test_portfolio.py`、`tests/test_pipeline_crypto.py`、`tests/backtest/test_attribution.py`

---

## Task 0: 纪律规范同步（前置，文档先行）

**为什么先做这个**：`docs/trading-discipline.md` 第 8 条流程要求「先改文档 → 再改代码」。v2 引入了趋势过滤、共享弹药池、加密三层上限，纪律规范必须同步，否则编码违反流程。

**Files:**
- Modify: `docs/trading-discipline.md`

- [ ] **Step 1: 在第 4 条后插入新条款**

在 `## 第 5 条 操作频率上限` 之前插入：

```markdown
## 第 4A 条 趋势过滤（v2 新增）

4A.1 每个市场都有独立的趋势基准：大盘用 QQQ，加密用 BTC 现货。基准**均为无杠杆标的**，禁止用杠杆 ETF 自身价格判断趋势。

4A.2 当趋势基准的收盘价**低于其 200 日简单移动平均**时，该市场的核心仓上限**减半**。

4A.3 趋势过滤的优先级**高于**所有极端规则。即使指数处于极恐区、或触发了熔断解锁，也不得突破趋势过滤给出的上限。

4A.4 趋势过滤**只限制上限，不改变五档逻辑**。趋势基准在均线上方时，仓位规则与 v1 完全一致。

4A.5 **不允许我主观判断「这次跌破是假突破」而跳过趋势过滤。** 均线上方/下方是客观事实，不是观点。

## 第 4B 条 加密子系统（v2 新增）

4B.1 加密标的按 Beta 分三层，各有上限：BTC 纯 Beta（BITX/BITU）100%、币股高 Beta（MSTX/MSTU）70%、币股经营 Beta（CONL）50%。上限基准是**加密核心仓的满仓值**。

4B.2 加密弹药池与大盘**共享同一个池子**。同一日两市场同时触发时，按「该市场当前回撤 / 该市场当前待释放批次的阈值」排序，比值大者优先；平局时大盘优先。

4B.3 加密的极贪规则是**分批减仓**（指数 ≥85 减至 2/3、≥90 减至 1/3、≥95 减至 1/4），不是一次性清仓。每档只触发一次，回落至 <60 时逐档恢复。

4B.4 加密标的的净值可能因长期熊市而快速衰减，发行方会合股。**加密层仓位上限本身就是风险控制**，不允许因为「跌得多了很便宜」而突破上限。

4B.5 加密部分的回测结论必须区分**合成轨**与**真实轨**。合成轨用于验证策略逻辑，真实轨用于验证产品损耗。禁止用合成轨的收益数字当作真实预期。
```

- [ ] **Step 2: 更新第 3 条的禁止行为清单**

将第 3 条第 10 项：

```markdown
10. 交易 `config.py` 的 `symbols` 列表之外的标的。
```

改为：

```markdown
10. 交易 `config.py` 的 `SYMBOLS` / `CRYPTO_SYMBOLS` 列表之外的标的。
11. 在趋势过滤生效（基准跌破 200 日均线）时，试图突破上限加仓。
12. 把合成轨的回测收益当作真实预期，并据此调整仓位。
13. 在未完成第 6 条记录的情况下进行下一笔操作。
```

**注意**：原第 3 条共有 11 项，最后一项是「在未完成第 6 条记录的情况下进行下一笔操作」。
替换后必须**保留**它（顺延为第 13 项），否则会静默丢失一条既有纪律。
（初版计划漏了这一点，已在实施中发现并修正。）

- [ ] **Step 3: 更新第 4.1 条的资金结构描述**

将：

```markdown
4.1 资金结构固定为：**核心仓上限 70% + 弹药仓上限 30%**，总仓位上限 100%，**永不使用融资**。
```

改为：

```markdown
4.1 资金结构固定为：**核心仓上限 70% + 弹药仓上限 30%**，总仓位上限 100%，**永不使用融资**。

其中核心仓按 `MARKET_CORE_RATIO` 分给两个市场（先验值 大盘 70% / 加密 30%，**分母是核心仓上限**）：
- 大盘核心仓上限 = 70% × 70% = **49%**
- 加密核心仓上限 = 70% × 30% = **21%**
- 弹药池上限 = **30%**（两市场共享）
- 合计 = **100%**
```

- [ ] **Step 4: 提交**

```bash
git add docs/trading-discipline.md
git commit -m "docs: 交易纪律规范同步 v2（趋势过滤 + 加密子系统）" # user-confirmed-commit
```

---

## Task 1: 配置层扩展

**Files:**
- Modify: `fg_system/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: 写失败的测试**

追加到 `tests/test_config.py` 末尾：

```python
# ---------------------------------------------------------------- v2 新增

def test_market_core_ratio_sums_to_one():
    """核心仓内部分割比例之和必须为 1。"""
    assert sum(config.MARKET_CORE_RATIO.values()) == pytest.approx(1.0)


def test_core_ratio_denominator_is_core_cap():
    """MARKET_CORE_RATIO 的分母是 CORE_CAP，不是总资金。

    绝对值：大盘 49% + 加密 21% + 弹药 30% = 100%。
    """
    us = config.CORE_CAP * config.MARKET_CORE_RATIO["us_equity"]
    cr = config.CORE_CAP * config.MARKET_CORE_RATIO["crypto"]
    assert us + cr + config.AMMO_CAP == pytest.approx(1.0)
    assert us == pytest.approx(0.49)
    assert cr == pytest.approx(0.21)


def test_crypto_layer_cap_descending():
    """加密三层上限必须递减：BTC 层 > 高 Beta 层 > 经营 Beta 层。"""
    caps = config.CRYPTO_LAYER_CAP
    assert caps["btc_beta"] > caps["stock_high_beta"] > caps["stock_ops_beta"]


def test_crypto_layer_cap_covers_all_layers():
    """CRYPTO_SYMBOLS 的每个层名都必须在 CRYPTO_LAYER_CAP 中有定义。"""
    assert set(config.CRYPTO_SYMBOLS.keys()) == set(config.CRYPTO_LAYER_CAP.keys())


def test_crypto_underlying_covers_all_crypto_symbols():
    """每个加密标的都必须有底层映射（合成与偏离检测依赖它）。"""
    flat = [s for group in config.CRYPTO_SYMBOLS.values() for s in group]
    assert set(config.CRYPTO_UNDERLYING.keys()) == set(flat)
    assert set(config.CRYPTO_LEVERAGE.keys()) == set(flat)


def test_crypto_drawdown_batches_wider_than_equity():
    """加密档位必须比大盘宽（§6.4：加密 -20% 是常态，会抽干共享池）。"""
    assert min(config.CRYPTO_DRAWDOWN_BATCHES) > min(config.DRAWDOWN_BATCHES)


def test_crypto_greed_tiers_ascending_and_matched():
    """极贪分批档位递增，且与减仓比例一一对应。"""
    assert config.CRYPTO_GREED_TIERS == sorted(config.CRYPTO_GREED_TIERS)
    assert len(config.CRYPTO_GREED_TIERS) == len(config.CRYPTO_GREED_REDUCE)


def test_crypto_greed_reduce_descending():
    """减仓后的核心仓比例必须递减（越贪越少）。"""
    r = config.CRYPTO_GREED_REDUCE
    assert all(r[i] > r[i + 1] for i in range(len(r) - 1))


def test_trend_filter_factor_between_zero_and_one():
    assert 0.0 < config.TREND_FILTER_FACTOR < 1.0


def test_trend_benchmark_covers_all_markets():
    assert set(config.TREND_BENCHMARK.keys()) == set(config.MARKETS)


def test_crypto_weights_sum_to_one():
    assert sum(config.CRYPTO_WEIGHTS.values()) == pytest.approx(1.0)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL — `AttributeError: module 'fg_system.config' has no attribute 'MARKET_CORE_RATIO'`

- [ ] **Step 3: 实现配置**

追加到 `fg_system/config.py` 末尾：

```python
# ================================================================ v2 新增
# 设计依据：docs/superpowers/specs/2026-09-21-fear-greed-index-v2-design.md

# ---------------------------------------------------------------- 市场
MARKETS = ["us_equity", "crypto"]

# 核心仓内部分割。**分母是 CORE_CAP，不是总资金**（§7.1）：
#   大盘 70% × 70% = 49% + 加密 70% × 30% = 21% + 弹药 30% = 100%
MARKET_CORE_RATIO = {"us_equity": 0.70, "crypto": 0.30}

# ---------------------------------------------------------------- 趋势过滤（§6.1）
TREND_MA_DAYS = 200              # 趋势均线周期
TREND_FILTER_FACTOR = 0.5        # 跌破均线时核心仓上限折扣
# 趋势判断基准，必须是无杠杆标的（§4.5 约束 2）
TREND_BENCHMARK = {"us_equity": "QQQ", "crypto": "BTC"}

# ---------------------------------------------------------------- 加密标的（§6.3）
# 三层递减上限，基准是加密核心仓的满仓值
CRYPTO_SYMBOLS = {
    "btc_beta": ["BITX", "BITU"],
    "stock_high_beta": ["MSTX", "MSTU"],
    "stock_ops_beta": ["CONL"],
}
CRYPTO_LAYER_CAP = {"btc_beta": 1.00, "stock_high_beta": 0.70, "stock_ops_beta": 0.50}
# 底层映射：情绪因子与偏离检测的输入源（禁止用杠杆 ETF 自身价格）
CRYPTO_UNDERLYING = {
    "BITX": "BTC", "BITU": "BTC",
    "MSTX": "MSTR", "MSTU": "MSTR",
    "CONL": "COIN",
}
CRYPTO_LEVERAGE = {"BITX": 2, "BITU": 2, "MSTX": 2, "MSTU": 2, "CONL": 2}
# 产品损耗率（年化），用于合成序列。初值参考 v1 的标定口径，须在实施中重标定（§8.1 质量门）
CRYPTO_PRODUCT_COST_RATE = {"BITX": 0.0105, "BITU": 0.0105, "MSTX": 0.0120,
                            "MSTU": 0.0120, "CONL": 0.0105}

CRYPTO_FLAT_SYMBOLS = [s for group in CRYPTO_SYMBOLS.values() for s in group]

# ---------------------------------------------------------------- 加密指数（§5.2）
CRYPTO_WEIGHTS = {"crypto_fng": 0.50, "crypto_price": 0.50}
CRYPTO_FNG_SOURCE = "alternative.me"

# ---------------------------------------------------------------- 加密弹药档位（§6.4）
# 按比例加宽：2x BTC ETF 回撤 20% 是常态，沿用大盘档位会抽干共享池
CRYPTO_DRAWDOWN_BATCHES = [0.30, 0.50, 0.70]

# ---------------------------------------------------------------- 加密极端规则（§6.5）
CRYPTO_GREED_TIERS = [85, 90, 95]           # 分批减仓触发线
CRYPTO_GREED_REDUCE = [2.0 / 3.0, 1.0 / 3.0, 0.25]   # 各档减仓后的核心仓比例
CRYPTO_GREED_UNLOCK_INDEX = 60              # 回落至此值以下逐档恢复
CRYPTO_EXTREME_FEAR_TRIGGER = 10            # 待实测标定（§12 风险 9）

# ---------------------------------------------------------------- 合成序列（§4.2）
SYNTHETIC_DEVIATION_GATE = 0.05   # 合成与真实的年化偏离质量门（超过则作废告警）

# ---------------------------------------------------------------- 数据源
ALTERNATIVE_ME_API = "https://api.alternative.me/fng/"
BLOCKCHAIN_CHART_API = "https://api.blockchain.info/charts/market-price"
CRYPTO_PRICES_PATH = os.path.join(RAW_DIR, "crypto_prices.csv")
CRYPTO_UNDERLYING_PATH = os.path.join(RAW_DIR, "crypto_underlying.csv")
CRYPTO_FNG_PATH = os.path.join(RAW_DIR, "crypto_fng.csv")
SYNTHETIC_PATH = os.path.join(DATA_DIR, "synthetic_leverage.csv")
CRYPTO_FEATURES_PATH = os.path.join(DATA_DIR, "crypto_features.csv")
CRYPTO_STATE_PATH = os.path.join(DATA_DIR, "crypto_state.json")

# 待标定参数（§12 风险 5）：加密波动大于股票，v1 的 20pp 阈值可能过紧。
# 实施阶段用真实数据标定后回填，并重跑 tests/data/test_loader.py 的全部检测测试。
CRYPTO_SPLIT_DEVIATION_THRESHOLD = 0.35
CRYPTO_SPLIT_JUMP_THRESHOLD = 0.90
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS（全部）

- [ ] **Step 5: 跑全量测试确认无回归**

Run: `python -m pytest tests/ -q`
Expected: `127 passed`（v1 测试不受影响）

- [ ] **Step 6: 提交**

```bash
git add fg_system/config.py tests/test_config.py
git commit -m "feat(config): 新增加密子系统与趋势过滤参数" # user-confirmed-commit
```

---

## Task 2: 加密数据抓取（贪恐指数 + BTC 现货 + 加密 ETF）

**Files:**
- Modify: `fg_system/data/fetch.py`
- Test: `tests/data/test_fetch_crypto.py`（新建）

**接口约定**（后续 Task 依赖）：
- `fetch_crypto_fng()` → DataFrame `[date, value, classification]`，date 为 datetime64，升序
- `fetch_btc_spot()` → DataFrame `[date, close]`，日度，升序
- `fetch_crypto_symbol(symbol)` → 与 v1 `fetch_symbol` 同格式的 OHLCV
- `update_crypto_prices(path=None)` → `(merged_df, added_dict)`

- [ ] **Step 1: 写失败的测试**

```python
# tests/data/test_fetch_crypto.py
# -*- coding: utf-8 -*-
"""加密数据抓取测试。全部用离线 fixture，不发网络请求。"""
import json

import pandas as pd
import pytest

from fg_system.data import fetch


# ---------------------------------------------------------------- 贪恐指数

def test_parse_fng_rows_maps_value_and_date():
    payload = {
        "name": "Fear and Greed Index",
        "data": [
            {"value": "70", "value_classification": "Greed", "timestamp": "1789948800"},
            {"value": "15", "value_classification": "Extreme Fear", "timestamp": "1789862400"},
        ],
    }
    df = fetch.parse_fng_payload(payload)
    # 必须按日期升序
    assert list(df["value"]) == [15, 70]
    assert df["date"].is_monotonic_increasing
    assert df.loc[0, "classification"] == "Extreme Fear"


def test_parse_fng_payload_skips_bad_rows():
    payload = {"data": [
        {"value": "50", "value_classification": "Neutral", "timestamp": "1789948800"},
        {"value": "abc", "value_classification": "X", "timestamp": "1789862400"},
    ]}
    df = fetch.parse_fng_payload(payload)
    assert len(df) == 1


def test_parse_fng_payload_empty_returns_columns():
    df = fetch.parse_fng_payload({"data": []})
    assert list(df.columns) == ["date", "value", "classification"]
    assert df.empty


def test_fng_url_requests_full_history():
    """limit=0 才是全量；用默认 limit 只能拿到 1 条。"""
    url = fetch.fng_url()
    assert "limit=0" in url
    assert "format=json" in url


# ---------------------------------------------------------------- BTC 现货

def test_btc_url_has_sampled_false():
    """必须带 sampled=false，否则会降采样到 2-4 天间隔（§4.1）。"""
    url = fetch.btc_spot_url()
    assert "sampled=false" in url


def test_parse_btc_payload_converts_unix_to_date():
    payload = {"status": "ok", "values": [
        {"x": 1474588800, "y": 594.08},
        {"x": 1789948800, "y": 81136.2},
    ]}
    df = fetch.parse_btc_payload(payload)
    assert len(df) == 2
    assert df["date"].is_monotonic_increasing
    assert df.loc[0, "close"] == pytest.approx(594.08)
    assert str(df.loc[0, "date"].date()) == "2016-09-23"


def test_parse_btc_payload_drops_zero_prices():
    """blockchain.info 早期返回 y=0.0（2009 年 BTC 无市场价），必须剔除。"""
    payload = {"values": [
        {"x": 1230940800, "y": 0.0},
        {"x": 1789948800, "y": 81136.2},
    ]}
    df = fetch.parse_btc_payload(payload)
    assert len(df) == 1
    assert df.loc[0, "close"] == pytest.approx(81136.2)


def test_parse_btc_payload_empty_returns_columns():
    df = fetch.parse_btc_payload({"values": []})
    assert list(df.columns) == ["date", "close"]
    assert df.empty


# ---------------------------------------------------------------- 增量合并

def test_merge_crypto_prices_is_idempotent():
    a = pd.DataFrame({
        "date": pd.to_datetime(["2026-01-01", "2026-01-02"]),
        "symbol": ["BITX", "BITX"],
        "open": [1.0, 2.0], "high": [1.0, 2.0], "low": [1.0, 2.0],
        "close": [1.0, 2.0], "volume": [10.0, 20.0],
    })
    merged = fetch.merge_incremental(a, a.copy())
    assert len(merged) == 2


def test_merge_crypto_prices_keeps_newer():
    old = pd.DataFrame({
        "date": pd.to_datetime(["2026-01-01"]), "symbol": ["BITX"],
        "open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1.0],
    })
    new = pd.DataFrame({
        "date": pd.to_datetime(["2026-01-01"]), "symbol": ["BITX"],
        "open": [9.0], "high": [9.0], "low": [9.0], "close": [9.0], "volume": [9.0],
    })
    merged = fetch.merge_incremental(old, new)
    assert len(merged) == 1
    assert merged.loc[0, "close"] == pytest.approx(9.0)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/data/test_fetch_crypto.py -v`
Expected: FAIL — `AttributeError: module 'fg_system.data.fetch' has no attribute 'parse_fng_payload'`

- [ ] **Step 3: 实现抓取**

追加到 `fg_system/data/fetch.py` 末尾：

```python
# ================================================================ v2 加密数据源

FNG_COLUMNS = ["date", "value", "classification"]
BTC_COLUMNS = ["date", "close"]


def fng_url(limit=0):
    """alternative.me 贪恐指数 URL。limit=0 表示全量（3151 条，2018-02-01 起）。"""
    return "%s?limit=%d&format=json" % (config.ALTERNATIVE_ME_API, limit)


def btc_spot_url(timespan="10years"):
    """blockchain.info BTC 现货 URL。

    **必须带 sampled=false**：默认 sampled=true 会降采样到 2-4 天间隔
    （timespan=10years 只剩 1826 点），CF2 的动量/RSI/波动率都依赖日度粒度。
    """
    return "%s?timespan=%s&sampled=false&format=json" % (config.BLOCKCHAIN_CHART_API, timespan)


def parse_fng_payload(payload):
    """解析 alternative.me 响应为 date,value,classification（升序）。"""
    recs = []
    for item in (payload or {}).get("data") or []:
        try:
            recs.append({
                "date": pd.to_datetime(int(item["timestamp"]), unit="s").normalize(),
                "value": float(item["value"]),
                "classification": str(item.get("value_classification") or ""),
            })
        except (ValueError, KeyError, TypeError):
            continue
    if not recs:
        return pd.DataFrame(columns=FNG_COLUMNS)
    return (pd.DataFrame(recs).drop_duplicates(subset=["date"], keep="last")
            .sort_values("date").reset_index(drop=True))


def parse_btc_payload(payload):
    """解析 blockchain.info 响应为 date,close（升序）。

    剔除 y=0.0 的记录：2009 年 BTC 尚无市场价格，blockchain.info 返回 0，
    保留会把「无价」误当成「价格为零」，使后续收益率计算产生 inf。
    """
    recs = []
    for item in (payload or {}).get("values") or []:
        try:
            price = float(item["y"])
            if price <= 0:
                continue
            recs.append({
                "date": pd.to_datetime(int(item["x"]), unit="s").normalize(),
                "close": price,
            })
        except (ValueError, KeyError, TypeError):
            continue
    if not recs:
        return pd.DataFrame(columns=BTC_COLUMNS)
    return (pd.DataFrame(recs).drop_duplicates(subset=["date"], keep="last")
            .sort_values("date").reset_index(drop=True))


def fetch_crypto_fng():
    """抓取加密贪恐指数全量历史。"""
    payload = json.loads(_get(fng_url()).decode("utf-8"))
    return parse_fng_payload(payload)


def fetch_btc_spot(timespan="10years"):
    """抓取 BTC 现货日度价格。"""
    payload = json.loads(_get(btc_spot_url(timespan)).decode("utf-8"))
    return parse_btc_payload(payload)


def fetch_crypto_symbol(symbol, limit=9999, fromdate="2010-01-01"):
    """抓取加密 ETF / 币股（走 Nasdaq，assetclass 自动判断）。

    Nasdaq 的 assetclass 参数对 ETF 与股票不同：加密 ETF（BITX/MSTX/CONL 等）
    用 etf，币股（MSTR/COIN）用 stocks。
    """
    assetclass = "etf" if symbol in config.CRYPTO_FLAT_SYMBOLS else "stocks"
    url = "%s?assetclass=%s&fromdate=%s&limit=%d" % (
        config.NASDAQ_API.format(symbol=urllib.parse.quote(symbol)), assetclass, fromdate, limit)
    data = json.loads(_get(url).decode("utf-8"))
    rows = ((data.get("data") or {}).get("tradesTable") or {}).get("rows") or []
    return parse_nasdaq_rows(rows, symbol)


def update_crypto_prices(path=None, sleep=1.0):
    """增量更新加密 ETF + 币股价格，返回 (合并后 DataFrame, 各标的本次新增行数)。"""
    path = path or config.CRYPTO_PRICES_PATH
    symbols = config.CRYPTO_FLAT_SYMBOLS + ["MSTR", "COIN"]
    old = pd.DataFrame()
    if os.path.exists(path):
        old = pd.read_csv(path, dtype={"symbol": str}, parse_dates=["date"])

    before = {s: (len(old[old["symbol"] == s]) if not old.empty else 0) for s in symbols}

    frames = []
    for sym in symbols:
        start, _ = missing_ranges(old, sym)
        fromdate = start.strftime("%Y-%m-%d") if start is not None else "2010-01-01"
        frames.append(fetch_crypto_symbol(sym, fromdate=fromdate))
        time.sleep(sleep)

    merged = merge_incremental(
        old, pd.concat(frames, ignore_index=True) if frames else pd.DataFrame())
    os.makedirs(os.path.dirname(path), exist_ok=True)
    merged.to_csv(path, index=False, encoding="utf-8")
    added = {s: len(merged[merged["symbol"] == s]) - before[s] for s in symbols}
    return merged, added


def update_crypto_aux(raw_dir=None):
    """更新 crypto_fng.csv 与 crypto_underlying.csv（BTC 现货）。"""
    raw_dir = raw_dir or config.RAW_DIR
    os.makedirs(raw_dir, exist_ok=True)
    fng = fetch_crypto_fng()
    fng.to_csv(config.CRYPTO_FNG_PATH, index=False, encoding="utf-8")
    btc = fetch_btc_spot()
    btc.to_csv(config.CRYPTO_UNDERLYING_PATH, index=False, encoding="utf-8")
    return {"fng_rows": len(fng), "btc_rows": len(btc)}
```

- [ ] **Step 3b: 修复 v1 `parse_nasdaq_rows` 的 `$` 剥离缺陷（实施中发现，已授权）**

**问题**（Task 2 实施中实测发现）：Nasdaq API 的返回格式**因 `assetclass` 而异**：

| assetclass | 价格字段样例 |
|---|---|
| `etf`（QQQ/BITX） | `'close': '741.47'` — 无 `$` |
| `stocks`（MSTR/COIN） | `'close': '$168.50'` — **所有价格字段带 `$`** |

v1 的 `parse_nasdaq_rows` 只在 `close` 上剥离 `$`，`open/high/low` 没有。因此
`assetclass=stocks` 的标的（MSTR/COIN）**每一行都在 `float("$164.58")` 处抛
ValueError 被静默 skip**，返回空表（实测 MSTR=0、COIN=0 行）。

这是 v1 的**潜伏缺陷**——v1 的 `fetch_symbol` 硬编码 `assetclass=etf`，从未碰到这个格式。
必须修：MSTR 与 COIN 分别是 MSTX/MSTU 与 CONL 的底层，缺它们 Task 3 的合成序列
与偏离检测都无从谈起。

**修复**（把 `$` 剥离统一到所有价格字段）：

```python
def _num(value):
    """剥离 Nasdaq 的 $ 与千分位后转 float。etf 与 stocks 两种格式通用。"""
    return float(str(value).replace(",", "").replace("$", ""))


def parse_nasdaq_rows(rows, symbol):
    """解析 Nasdaq tradesTable.rows。字段顺序：date,close,volume,open,high,low。

    注意：`assetclass=etf` 的价格不带 `$`，`assetclass=stocks` 的**所有价格字段都带 `$`**
    （实测 MSTR/COIN）。因此三个价格字段都必须剥离 `$`，否则 stocks 格式的每一行
    都会在 float() 处抛 ValueError 被静默 skip，返回空表。
    """
    recs = []
    for r in rows:
        try:
            recs.append({
                "date": pd.to_datetime(r["date"], format="%m/%d/%Y"),
                "symbol": symbol,
                "open": _num(r["open"]),
                "high": _num(r["high"]),
                "low": _num(r["low"]),
                "close": _num(r["close"]),
                "volume": float(str(r["volume"]).replace(",", "") or 0),
            })
        except (ValueError, KeyError, TypeError):
            continue
    if not recs:
        return pd.DataFrame(columns=PRICE_COLUMNS)
    return pd.DataFrame(recs).sort_values("date").reset_index(drop=True)
```

**为什么安全**：v1 测试夹具（`tests/data/test_fetch.py` 的 `NASDAQ_ROW`）字段不带 `$`，
`replace("$", "")` 对它们是 no-op → 零回归。修复后必须跑全量测试确认。

**补充两个测试**（加到 `tests/data/test_fetch_crypto.py`）：

```python
def test_parse_nasdaq_rows_strips_dollar_signs():
    """stocks 格式的所有价格字段都带 $，必须全部剥离（MSTR/COIN 依赖）。"""
    rows = [{"date": "01/02/2026", "open": "$164.58", "high": "$169.52",
             "low": "$164.49", "close": "$168.50", "volume": "1,234,567"}]
    df = fetch.parse_nasdaq_rows(rows, "MSTR")
    assert len(df) == 1
    assert df.loc[0, "close"] == pytest.approx(168.50)
    assert df.loc[0, "open"] == pytest.approx(164.58)
    assert df.loc[0, "high"] == pytest.approx(169.52)
    assert df.loc[0, "low"] == pytest.approx(164.49)


def test_parse_nasdaq_rows_still_works_without_dollar():
    """etf 格式不带 $，剥离操作必须是 no-op（v1 回归防线）。"""
    rows = [{"date": "01/02/2026", "open": "741.47", "high": "745.00",
             "low": "738.00", "close": "741.47", "volume": "1,000"}]
    df = fetch.parse_nasdaq_rows(rows, "QQQ")
    assert df.loc[0, "close"] == pytest.approx(741.47)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/data/test_fetch_crypto.py -v`
Expected: PASS（全部 12 个）

- [ ] **Step 5: 联网验证数据源（一次性，产出真实数据文件）**

Run:
```bash
python -c "from fg_system.data import fetch; print(fetch.update_crypto_aux()); print(fetch.update_crypto_prices()[1])"
```
Expected: `{'fng_rows': 3151, 'btc_rows': ~3651}`，且各加密标的行数 > 0。
**若代理返回 407，等待 30 秒重试**（实测为瞬时故障）。

- [ ] **Step 6: 跑全量测试**

Run: `python -m pytest tests/ -q`
Expected: `137 passed`（127 + 10 新增）

- [ ] **Step 7: 提交**

```bash
git add fg_system/data/fetch.py tests/data/test_fetch_crypto.py Data/raw/crypto_fng.csv Data/raw/crypto_underlying.csv Data/raw/crypto_prices.csv
git commit -m "feat(data): 加密数据抓取（贪恐指数 + BTC 现货 + 加密 ETF）" # user-confirmed-commit
```

---

## Task 3: 合成杠杆序列 + 质量门

**为什么需要**（§4.2）：加密 ETF 真实历史最长仅 4 年（CONL），扣掉 756 交易日 warmup 后只剩 1 年可回测，且完全未覆盖 2018 熊市与 2022 熊市。合成轨把回测拉到 10 年。

**Files:**
- Create: `fg_system/data/synthetic.py`
- Test: `tests/data/test_synthetic.py`（新建）

**接口约定**：
- `synthetic_returns(underlying_returns, leverage, cost_rate)` → 合成日收益 Series
- `build_synthetic_series(underlying_close, leverage, cost_rate)` → 合成价格 Series
- `deviation_gate(synthetic_close, real_close)` → 年化偏离 float（>0 表示合成跑赢）
- `build_all(raw_dir=None)` → DataFrame `[date, symbol, close]` 长表

- [ ] **Step 1: 写失败的测试**

```python
# tests/data/test_synthetic.py
# -*- coding: utf-8 -*-
"""合成杠杆序列测试。"""
import numpy as np
import pandas as pd
import pytest

from fg_system.data import synthetic


def test_synthetic_daily_return_formula():
    """合成日收益 = N × 底层日收益 − 产品损耗/252。"""
    und = pd.Series([0.01, -0.02, 0.03],
                    index=pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-05"]))
    out = synthetic.synthetic_returns(und, leverage=2, cost_rate=0.0252)
    daily_cost = 0.0252 / 252
    assert out.iloc[0] == pytest.approx(2 * 0.01 - daily_cost)
    assert out.iloc[1] == pytest.approx(2 * -0.02 - daily_cost)
    assert out.iloc[2] == pytest.approx(2 * 0.03 - daily_cost)


def test_synthetic_series_compounds():
    """合成价格 = ∏(1 + 合成日收益)。"""
    und = pd.Series([0.01, 0.01], index=pd.to_datetime(["2026-01-01", "2026-01-02"]))
    close = synthetic.build_synthetic_series(und, leverage=2, cost_rate=0.0, base=100.0)
    expected = 100.0 * (1 + 0.02) * (1 + 0.02)
    assert close.iloc[-1] == pytest.approx(expected)


def test_synthetic_series_first_point_is_base():
    und = pd.Series([0.05], index=pd.to_datetime(["2026-01-01"]))
    close = synthetic.build_synthetic_series(und, leverage=3, cost_rate=0.0, base=50.0)
    assert close.iloc[0] == pytest.approx(50.0 * 1.15)


def test_volatility_drag_is_negative_for_choppy_market():
    """横盘震荡时杠杆必然亏损（波动率拖累，数学必然）。"""
    rng = np.random.default_rng(42)
    und = pd.Series(rng.normal(0.0, 0.03, 500),
                    index=pd.bdate_range("2024-01-01", periods=500))
    lev3 = synthetic.build_synthetic_series(und, leverage=3, cost_rate=0.0, base=100.0)
    lev1 = synthetic.build_synthetic_series(und, leverage=1, cost_rate=0.0, base=100.0)
    assert lev3.iloc[-1] < lev1.iloc[-1]


def test_deviation_gate_zero_when_identical():
    s = pd.Series([100.0, 110.0, 121.0],
                  index=pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-05"]))
    assert synthetic.deviation_gate(s, s.copy()) == pytest.approx(0.0, abs=1e-9)


def test_deviation_gate_positive_when_synthetic_outperforms():
    real = pd.Series([100.0, 100.0, 100.0],
                     index=pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-05"]))
    synth = pd.Series([100.0, 110.0, 121.0], index=real.index)
    assert synthetic.deviation_gate(synth, real) > 0


def test_deviation_gate_nan_when_too_few_points():
    s = pd.Series([100.0], index=pd.to_datetime(["2026-01-01"]))
    assert np.isnan(synthetic.deviation_gate(s, s.copy()))


def test_check_gate_raises_above_threshold():
    real = pd.Series([100.0, 100.0, 100.0],
                     index=pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-05"]))
    synth = pd.Series([100.0, 200.0, 400.0], index=real.index)
    with pytest.raises(synthetic.SyntheticQualityError):
        synthetic.check_gate("BITX", synth, real, gate=0.05)


def test_check_gate_passes_below_threshold():
    s = pd.Series([100.0, 110.0, 121.0],
                  index=pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-05"]))
    assert synthetic.check_gate("BITX", s, s.copy(), gate=0.05) is True
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/data/test_synthetic.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fg_system.data.synthetic'`

- [ ] **Step 3: 实现合成模块**

```python
# fg_system/data/synthetic.py
# -*- coding: utf-8 -*-
"""合成杠杆序列（§4.2）。

用途：加密 ETF 真实历史最长仅 4 年，无法覆盖完整加密周期。用底层资产
（BTC/ETH/COIN/MSTR）的日收益合成杠杆序列，把回测拉到 10 年。

**定位声明（必须向使用者明确）**：合成序列不是真实交易标的的历史，
它只用于验证**策略逻辑**。任何基于合成轨的收益数字都必须标注「合成」。

硬约束：合成必须通过质量门（与真实 ETF 在重叠区间的年化偏离 < 5%），
否则该标的的合成轨结果作废并告警——不允许用未校准的合成序列得出结论。
"""
import os

import numpy as np
import pandas as pd

from fg_system import config

TRADING_DAYS = 252.0


class SyntheticQualityError(Exception):
    """合成序列与真实 ETF 偏离过大。必须中止，不得用该序列出结论。"""


def synthetic_returns(underlying_returns, leverage, cost_rate):
    """合成日收益 = N × 底层日收益 − 产品损耗/252。

    产品损耗（费用+融资+跟踪误差）按交易日均匀摊到每一天。波动率拖累
    **不需要显式建模**——它由 N × r 的复利自然产生（v1 §4.5 已实测验证）。
    """
    return leverage * underlying_returns - cost_rate / TRADING_DAYS


def build_synthetic_series(underlying_returns, leverage, cost_rate, base=100.0):
    """合成价格序列 = base × ∏(1 + 合成日收益)。

    首个数据点即已含当日收益（base 是序列起点的**前一日**收盘）。
    """
    r = synthetic_returns(underlying_returns, leverage, cost_rate)
    return base * (1.0 + r.fillna(0.0)).cumprod()


def deviation_gate(synthetic_close, real_close, min_points=60):
    """合成与真实的**年化收益偏离**（正数表示合成跑赢真实）。

    仅用两者重叠区间计算。点数不足 min_points 时返回 NaN——
    不足样本的偏离没有统计意义，不得据此判定通过。
    """
    joined = pd.concat(
        [synthetic_close.rename("synth"), real_close.rename("real")], axis=1
    ).dropna()
    if len(joined) < min_points:
        return float("nan")

    def annual(s):
        years = len(s) / TRADING_DAYS
        if years <= 0:
            return float("nan")
        total = s.iloc[-1] / s.iloc[0] - 1.0
        return (1.0 + total) ** (1.0 / years) - 1.0 if total > -1 else -1.0

    return float(annual(joined["synth"]) - annual(joined["real"]))


def check_gate(symbol, synthetic_close, real_close, gate=None):
    """质量门（§4.2）。偏离超阈值抛异常；点数不足抛异常（不得静默通过）。"""
    gate = config.SYNTHETIC_DEVIATION_GATE if gate is None else gate
    dev = deviation_gate(synthetic_close, real_close)
    if np.isnan(dev):
        raise SyntheticQualityError(
            "%s: 合成与真实的重叠区间不足 60 个交易日，无法做质量门校验" % symbol)
    if abs(dev) > gate:
        raise SyntheticQualityError(
            "%s: 合成与真实年化偏离 %.2f%%，超阈值 %.2f%%（合成轨结论作废）"
            % (symbol, dev * 100, gate * 100))
    return True


def build_all(raw_dir=None):
    """构建全部加密标的的合成序列。

    返回长表 DataFrame[date, symbol, close]。底层来自 crypto_underlying.csv
    （BTC）与 crypto_prices.csv（MSTR/COIN 正股）。
    """
    raw_dir = raw_dir or config.RAW_DIR
    btc = pd.read_csv(config.CRYPTO_UNDERLYING_PATH, parse_dates=["date"]).set_index("date")["close"]

    underlying = {"BTC": btc}
    crypto_path = config.CRYPTO_PRICES_PATH
    if os.path.exists(crypto_path):
        px = pd.read_csv(crypto_path, dtype={"symbol": str}, parse_dates=["date"])
        for sym in ("MSTR", "COIN"):
            s = px[px["symbol"] == sym].set_index("date")["close"].sort_index()
            if not s.empty:
                underlying[sym] = s

    frames = []
    for symbol, und_name in config.CRYPTO_UNDERLYING.items():
        if und_name not in underlying:
            continue
        und_close = underlying[und_name].sort_index()
        und_ret = und_close.pct_change()
        close = build_synthetic_series(
            und_ret,
            leverage=config.CRYPTO_LEVERAGE[symbol],
            cost_rate=config.CRYPTO_PRODUCT_COST_RATE.get(symbol, 0.0),
        )
        frames.append(pd.DataFrame({
            "date": close.index, "symbol": symbol, "close": close.values,
        }))

    if not frames:
        return pd.DataFrame(columns=["date", "symbol", "close"])
    return pd.concat(frames, ignore_index=True).sort_values(["symbol", "date"]).reset_index(drop=True)


def validate_against_real(raw_dir=None):
    """对每个有真实数据的标的跑质量门，返回 {symbol: 偏离值}。超阈值会抛异常。"""
    raw_dir = raw_dir or config.RAW_DIR
    synth = build_all(raw_dir)
    result = {}
    if not os.path.exists(config.CRYPTO_PRICES_PATH):
        return result
    real = pd.read_csv(config.CRYPTO_PRICES_PATH, dtype={"symbol": str}, parse_dates=["date"])

    for symbol in config.CRYPTO_FLAT_SYMBOLS:
        s = synth[synth["symbol"] == symbol].set_index("date")["close"]
        r = real[real["symbol"] == symbol].set_index("date")["close"].sort_index()
        if s.empty or r.empty:
            continue
        dev = deviation_gate(s, r)
        check_gate(symbol, s, r)
        result[symbol] = dev
    return result


def write(path=None, raw_dir=None):
    """构建并落盘 synthetic_leverage.csv。"""
    path = path or config.SYNTHETIC_PATH
    df = build_all(raw_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8")
    return df
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/data/test_synthetic.py -v`
Expected: PASS（全部 9 个）

- [ ] **Step 5: 用真实数据验证质量门**

Run:
```bash
python -c "from fg_system.data import synthetic; print(synthetic.write()); print(synthetic.validate_against_real())"
```
Expected: 打印各标的重叠区间年化偏离。
**若某标的偏离 > 5%**：说明 `CRYPTO_PRODUCT_COST_RATE` 标定不准，用实测偏离反推修正该标的的损耗率，**而不是放宽质量门阈值**。修正后重跑本步。

- [ ] **Step 6: 跑全量测试**

Run: `python -m pytest tests/ -q`
Expected: `146 passed`（137 + 9）

- [ ] **Step 7: 提交**

```bash
git add fg_system/data/synthetic.py tests/data/test_synthetic.py Data/synthetic_leverage.csv
git commit -m "feat(data): 合成杠杆序列 + 质量门" # user-confirmed-commit
```

---

## Task 4: 加密宽表加载

**Files:**
- Modify: `fg_system/data/loader.py`
- Test: `tests/data/test_loader_crypto.py`（新建）

**接口约定**：`to_crypto_wide(raw_dir=None)` → MultiIndex 列 `(symbol, field)` 的宽表，索引为**美股交易日**（主日历取 SPY）。

列包含：每个加密 ETF 与币股的 `close`、`BTC` 的 `close`、`FNG` 的 `value`。

- [ ] **Step 1: 写失败的测试**

```python
# tests/data/test_loader_crypto.py
# -*- coding: utf-8 -*-
"""加密宽表加载测试。"""
import pandas as pd
import pytest

from fg_system import config
from fg_system.data import loader


def _write_fixtures(tmp_path):
    """构造最小可用的原始数据文件。"""
    # 加密价格（含 BTC 现货与一只 ETF）
    px = pd.DataFrame({
        "date": pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"] * 2),
        "symbol": ["BITX"] * 3 + ["SPY"] * 3,
        "open": [10.0] * 6, "high": [11.0] * 6, "low": [9.0] * 6,
        "close": [10.0, 10.5, 11.0, 500.0, 505.0, 510.0],
        "volume": [100.0] * 6,
    })
    px.to_csv(config.CRYPTO_PRICES_PATH, index=False)

    btc = pd.DataFrame({
        "date": pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"]),
        "close": [90000.0, 92000.0, 91000.0],
    })
    btc.to_csv(config.CRYPTO_UNDERLYING_PATH, index=False)

    fng = pd.DataFrame({
        "date": pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"]),
        "value": [50.0, 60.0, 55.0],
        "classification": ["Neutral", "Greed", "Greed"],
    })
    fng.to_csv(config.CRYPTO_FNG_PATH, index=False)


def test_crypto_wide_has_expected_columns(tmp_path, monkeypatch):
    _write_fixtures(tmp_path)
    wide = loader.to_crypto_wide()
    assert ("BITX", "close") in wide.columns
    assert ("BTC", "close") in wide.columns
    assert ("FNG", "value") in wide.columns


def test_crypto_wide_index_is_spy_calendar(tmp_path):
    _write_fixtures(tmp_path)
    wide = loader.to_crypto_wide()
    assert list(wide.index) == list(pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"]))


def test_crypto_wide_does_not_forward_fill_prices(tmp_path):
    """价格缺失必须保持 NaN（§4.3），不能前向填充。"""
    _write_fixtures(tmp_path)
    px = pd.read_csv(config.CRYPTO_PRICES_PATH)
    px = px[~((px["symbol"] == "BITX") & (px["date"] == "2026-01-05"))]
    px.to_csv(config.CRYPTO_PRICES_PATH, index=False)
    wide = loader.to_crypto_wide()
    assert pd.isna(wide.loc[pd.Timestamp("2026-01-05"), ("BITX", "close")])


def test_crypto_wide_fng_is_forward_filled(tmp_path):
    """FNG 缺失前向填充（指数类），与价格类处理不同。"""
    _write_fixtures(tmp_path)
    fng = pd.read_csv(config.CRYPTO_FNG_PATH)
    fng = fng[fng["date"] != "2026-01-05"]
    fng.to_csv(config.CRYPTO_FNG_PATH, index=False)
    wide = loader.to_crypto_wide()
    assert wide.loc[pd.Timestamp("2026-01-05"), ("FNG", "value")] == pytest.approx(50.0)


def test_crypto_wide_raises_on_missing_underlying(tmp_path):
    """缺 BTC 现货时必须报错——CF2 与趋势过滤都依赖它。"""
    _write_fixtures(tmp_path)
    import os
    os.remove(config.CRYPTO_UNDERLYING_PATH)
    with pytest.raises(loader.DataQualityError):
        loader.to_crypto_wide()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/data/test_loader_crypto.py -v`
Expected: FAIL — `AttributeError: module 'fg_system.data.loader' has no attribute 'to_crypto_wide'`

- [ ] **Step 3: 实现加密宽表加载**

追加到 `fg_system/data/loader.py` 末尾：

```python
# ================================================================ v2 加密宽表

CRYPTO_FIELDS = ["open", "high", "low", "close", "volume"]


def to_crypto_wide(raw_dir=None, primary_symbol="SPY"):
    """加密市场的宽表。

    - 主日历：美股交易日（SPY）。加密 7×24 交易，但 ETF 只能在美股时段成交，
      因此**必须**用美股日历做回测索引（§4.4）。
    - 价格类缺失：保持 NaN，不前向填充（§4.3）。
    - FNG 缺失：前向填充（指数类），与价格类处理不同。
    - BTC 现货缺失：**直接报错**。CF2 与趋势过滤都依赖它，静默降级会产生错误信号。
    """
    raw_dir = raw_dir or config.RAW_DIR
    crypto_path = os.path.join(raw_dir, "crypto_prices.csv")
    btc_path = os.path.join(raw_dir, "crypto_underlying.csv")
    fng_path = os.path.join(raw_dir, "crypto_fng.csv")

    if not os.path.exists(btc_path):
        raise DataQualityError(
            "缺少 BTC 现货文件 %s。CF2 价格因子与趋势过滤都依赖它，无法继续。" % btc_path)

    px = pd.read_csv(crypto_path, dtype={"symbol": str}, parse_dates=["date"])

    frames = []
    for field in CRYPTO_FIELDS:
        w = px.pivot_table(index="date", columns="symbol", values=field, aggfunc="last")
        w.columns = pd.MultiIndex.from_product([w.columns, [field]], names=["symbol", "field"])
        frames.append(w)
    wide = pd.concat(frames, axis=1).sort_index()

    btc = pd.read_csv(btc_path, parse_dates=["date"]).set_index("date")["close"].sort_index()
    wide[("BTC", "close")] = btc.reindex(wide.index)

    fng = pd.read_csv(fng_path, parse_dates=["date"]).set_index("date")["value"].sort_index()
    # FNG 是指数类，允许前向填充；stale_days 由因子层负责检查
    wide[("FNG", "value")] = fng.reindex(wide.index).ffill()

    # 主日历必须取 **prices.csv 的 SPY**，不能取 crypto_prices.csv 的 SPY——
    # 后者根本不含 SPY（update_crypto_prices 只抓加密标的与 MSTR/COIN）。
    # 且合成轨（Task 3）也用 prices.csv 的 SPY 日历，两者必须一致，
    # 否则 run_portfolio 对齐时会出现错位。
    prices_path = os.path.join(raw_dir, "prices.csv")
    if os.path.exists(prices_path):
        spy = (pd.read_csv(prices_path, dtype={"symbol": str}, parse_dates=["date"])
               .query("symbol == @primary_symbol")
               .set_index("date")["close"].sort_index())
        wide = wide.reindex(spy.dropna().index)
    elif (primary_symbol, "close") in wide.columns:
        wide = wide.reindex(wide[(primary_symbol, "close")].dropna().index)
    return wide.sort_index()


def check_crypto_anomalies(df, threshold=None, jump_threshold=None):
    """加密标的的拆股/合股异常检测（§4.3）。

    与 v1 `check_split_anomalies` 逻辑相同，但阈值独立——加密日波动远大于股票，
    v1 的 20pp 在加密上会误报（实测待标定，见 config.CRYPTO_SPLIT_DEVIATION_THRESHOLD）。
    """
    threshold = (config.CRYPTO_SPLIT_DEVIATION_THRESHOLD
                 if threshold is None else threshold)
    jump_threshold = (config.CRYPTO_SPLIT_JUMP_THRESHOLD
                      if jump_threshold is None else jump_threshold)
    problems = []
    for lev, und in config.CRYPTO_UNDERLYING.items():
        n = config.CRYPTO_LEVERAGE[lev]
        sub = df[df["symbol"].isin([lev, und])]
        lev_s = sub[sub["symbol"] == lev].set_index("date")["close"].sort_index()
        und_s = sub[sub["symbol"] == und].set_index("date")["close"].sort_index()
        if lev_s.empty or und_s.empty:
            continue
        lev_r = lev_s.pct_change()
        und_r = und_s.reindex(lev_r.index).pct_change(fill_method=None)

        dev = (lev_r - n * und_r).abs()
        for dt, v in dev[dev > threshold].items():
            problems.append(
                "%s %s: %s 收益 %+.2f%% 与 %d×%s 收益 %+.2f%% 偏离 %.2fpp"
                % (lev, dt.date(), lev, lev_r.loc[dt] * 100, n, und,
                   (und_r.loc[dt] or 0) * 100, v * 100))
        jump = (n * und_r).abs()
        for dt, v in jump[jump > jump_threshold].items():
            problems.append(
                "%s %s: %d×%s 收益 %+.2f%% 超绝对兜底阈值"
                % (lev, dt.date(), n, und, v * 100))

    if problems:
        raise DataQualityError(
            "加密标的异常跳变（疑似未复权或数据错误），pipeline 中止：\n  "
            + "\n  ".join(problems))
    return True
```

同时在文件顶部的 import 区确认 `os` 已导入。若未导入，在 `import pandas as pd` 前加：

```python
import os
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/data/test_loader_crypto.py -v`
Expected: PASS（全部 5 个）

- [ ] **Step 5: 用真实数据检查异常检测是否误报**

Run:
```bash
python -c "
from fg_system.data import loader
import pandas as pd
from fg_system import config
df = pd.read_csv(config.CRYPTO_PRICES_PATH, dtype={'symbol': str}, parse_dates=['date'])
try:
    loader.check_crypto_anomalies(df)
    print('通过：无异常跳变')
except loader.DataQualityError as e:
    print(e)
"
```
Expected: 若报出大量真实市场波动日，说明 `CRYPTO_SPLIT_DEVIATION_THRESHOLD` 过紧。**用实测偏离分布的极值反推阈值并回填 config**（加密日波动是股票的 1.5 倍以上，35pp 是起点而非结论），然后重跑本步直到只剩真实拆股事件。

- [ ] **Step 6: 跑全量测试**

Run: `python -m pytest tests/ -q`
Expected: `151 passed`（146 + 5）

- [ ] **Step 7: 提交**

```bash
git add fg_system/data/loader.py tests/data/test_loader_crypto.py fg_system/config.py
git commit -m "feat(data): 加密宽表加载与异常检测" # user-confirmed-commit
```

---

## Task 5: CF1 加密贪恐因子

**Files:**
- Create: `fg_system/factors/crypto_fng.py`
- Test: `tests/factors/test_crypto_fng.py`（新建）

**设计依据**（§5.2 CF1）：alternative.me 的值本身已是 0-100，但它是**绝对刻度**——2018 年的「贪恐 30」与 2024 年的「贪恐 30」市场含义不同（情绪中枢在漂移）。因此必须再做**滚动 3 年百分位**，转为「相对当下环境的情绪位置」，与 v1 §5.3 的跨周期可比性要求一致。

- [ ] **Step 1: 写失败的测试**

```python
# tests/factors/test_crypto_fng.py
# -*- coding: utf-8 -*-
"""CF1 加密贪恐因子测试。"""
import numpy as np
import pandas as pd
import pytest

from fg_system import config
from fg_system.factors.crypto_fng import CryptoFngFactor


def _wide(values, start="2016-01-04"):
    idx = pd.bdate_range(start, periods=len(values))
    return pd.DataFrame({("FNG", "value"): list(values)}, index=idx)


def test_name_and_market():
    f = CryptoFngFactor()
    assert f.name == "crypto_fng"
    assert f.market == "crypto"


def test_score_in_range():
    w = _wide(np.linspace(10, 90, config.RANK_WINDOW + 50))
    s = CryptoFngFactor().score(w)
    valid = s.dropna()
    assert not valid.empty
    assert valid.min() >= 0.0 and valid.max() <= 100.0


def test_warmup_returns_nan():
    """窗口不足处必须 NaN（§10.4：禁止用不足窗口的数据凑值）。"""
    w = _wide(np.linspace(10, 90, 100))
    s = CryptoFngFactor().score(w)
    assert s.isna().all()


def test_high_fng_gives_high_score():
    """贪恐值高 = 贪婪 = 高分，**方向不反转**（与 VIX 相反）。"""
    w = _wide(np.linspace(10, 90, config.RANK_WINDOW))
    s = CryptoFngFactor().score(w)
    assert s.dropna().iloc[-1] > 50.0


def test_low_fng_gives_low_score():
    w = _wide(np.linspace(90, 10, config.RANK_WINDOW))
    s = CryptoFngFactor().score(w)
    assert s.dropna().iloc[-1] < 50.0


def test_missing_column_raises():
    """缺少 FNG 列必须报错，不能静默返回全 NaN。"""
    w = pd.DataFrame({("BTC", "close"): [1.0, 2.0]})
    with pytest.raises(ValueError):
        CryptoFngFactor().raw(w)


def test_constant_series_is_handled():
    """恒定值序列不应崩溃（百分位退化为固定值）。"""
    w = _wide([50.0] * (config.RANK_WINDOW + 10))
    s = CryptoFngFactor().score(w)
    assert not s.dropna().empty
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/factors/test_crypto_fng.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fg_system.factors.crypto_fng'`

- [ ] **Step 3: 实现因子**

```python
# fg_system/factors/crypto_fng.py
# -*- coding: utf-8 -*-
"""CF1 加密贪恐因子（先验权重 50%，§5.2）。

输入：alternative.me 的 0-100 贪恐值（高分 = 贪婪，**方向与自建指数一致，不反转**）。

为什么要再做滚动百分位：alternative.me 是**绝对刻度**，而加密市场的情绪中枢
在漂移——2018 年的「贪恐 30」与 2024 年的「贪恐 30」不是同一件事。滚动百分位
把它转为「相对当下环境的情绪位置」，这是跨 10 年回测成立的前提（v1 §5.3）。
"""
from fg_system.factors.base import Factor, rolling_pct

FNG_COLUMN = ("FNG", "value")


class CryptoFngFactor(Factor):
    name = "crypto_fng"
    market = "crypto"

    def raw(self, wide):
        if FNG_COLUMN not in wide.columns:
            raise ValueError(
                "CF1 需要 %s 列（alternative.me 贪恐指数），当前列: %s"
                % (FNG_COLUMN, list(wide.columns)))
        return rolling_pct(wide[FNG_COLUMN])
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/factors/test_crypto_fng.py -v`
Expected: PASS（全部 7 个）

- [ ] **Step 5: 提交**

```bash
git add fg_system/factors/crypto_fng.py tests/factors/test_crypto_fng.py
git commit -m "feat(factors): CF1 加密贪恐因子" # user-confirmed-commit
```

---

## Task 6: CF2 BTC 价格因子

**Files:**
- Create: `fg_system/factors/crypto_price.py`
- Test: `tests/factors/test_crypto_price.py`（新建）

**设计依据**（§5.2 CF2）：四个子项，结构与 v1 的 F3 对称，但输入是 **BTC 现货**。

**红线**：禁止使用 BITX/MSTX 等杠杆 ETF 自身价格——杠杆 ETF 含年化数十个百分点的波动率拖累，会把损耗系统性误读为恐惧（v1 §4.5 约束 1）。

- [ ] **Step 1: 写失败的测试**

```python
# tests/factors/test_crypto_price.py
# -*- coding: utf-8 -*-
"""CF2 BTC 价格因子测试（§5.2 CF2）。输入必须是 BTC 现货。

夹具长度要求：`drawdown_52w`(252) 与 `rolling_pct`(756) 串联，二者叠加后
首个非 NaN 出现在第 **1007** 个点（0-based 索引 1006）。因此本文件所有
断言有效输出的测试一律使用 **≥1100 点**，留足余量。

断言写法（对齐 v1 `tests/factors/test_price.py`）：用「持续上涨 vs 长上涨后
近期急跌」两类行情比较分数，**不能**用「单调上涨 vs 单调下跌」——`rolling_pct`
度量的是「今日在近 756 日中的相对位置」而非趋势方向，持续下跌会让反转子项
（dd = 1 - 回撤分位、calm = 1 - 波动分位）反而变高，净效应是下跌行情分更高。
这是 `rolling_pct` 的结构性性质（见 `fg_system/factors/base.py` docstring）。
"""
import pandas as pd
import pytest

from fg_system.factors.crypto_price import CryptoPriceFactor

# drawdown_52w(252) + rolling_pct(756) 串联 → 索引 1006 为首个有效值。
WARMUP_INDEX = 1006


def _wide(closes, start="2016-01-04"):
    idx = pd.bdate_range(start, periods=len(closes))
    return pd.DataFrame({("BTC", "close"): list(closes)}, index=idx)


def _trending(n, start=100.0, step=0.01):
    return [start * (1 + step) ** i for i in range(n)]


def test_name_and_market():
    f = CryptoPriceFactor()
    assert f.name == "crypto_price"
    assert f.market == "crypto"


def test_score_in_range():
    w = _wide(_trending(1100))
    s = CryptoPriceFactor().score(w)
    assert not s.dropna().empty
    assert s.dropna().min() >= 0.0 and s.dropna().max() <= 100.0


def test_warmup_returns_nan():
    w = _wide(_trending(100))
    s = CryptoPriceFactor().score(w)
    assert s.isna().all()


def test_warmup_boundary_is_1008_days():
    """drawdown_52w(252) 叠加 rolling_pct(756) → 首个有效值在 0-based 索引 1006。

    （序列第 1007 个点；`rolling_pct` 需要完整 756 个非 NaN 输入才产出首值。）
    """
    w = _wide(_trending(1100, step=0.003))
    s = CryptoPriceFactor().score(w)
    valid_idx = s.dropna().index
    assert len(valid_idx) > 0
    assert s.iloc[:WARMUP_INDEX].isna().all(), "索引 1006 之前必须全为 NaN"
    assert pd.notna(s.iloc[WARMUP_INDEX]), "索引 1006 处必须是首个有效值"


def test_recent_crash_scores_lower_than_sustained_rise():
    """长上涨 vs 长上涨后近期急跌：后者分数必须更低。

    注意：**不能**用「单调上涨 vs 单调下跌」做对照——rolling_pct 度量的是
    「今日在近 756 日中的相对位置」而非趋势方向，持续下跌会让反转子项
    （dd=1-回撤分位、calm=1-波动分位）反而变高，净效应是下跌行情分更高。
    这是 rolling_pct 的结构性性质（见 factors/base.py docstring），
    v1 的 tests/factors/test_price.py 同样避开了这个陷阱。
    """
    n = 1200
    rising = _trending(n, step=0.004)
    crash = rising[:-30] + [rising[-30] * (1 - 0.01 * i) for i in range(1, 31)]
    s_up = CryptoPriceFactor().score(_wide(rising)).dropna()
    s_crash = CryptoPriceFactor().score(_wide(crash)).dropna()
    assert s_up.iloc[-1] > s_crash.iloc[-1]


def test_deep_drawdown_scores_low():
    """深度回撤后分数必须显著下降（回撤子项是反转方向）。"""
    n = 1100
    rising = _trending(n)
    crashed = rising[:-1] + [rising[-1] * 0.4]
    w = _wide(crashed)
    s = CryptoPriceFactor().score(w).dropna()
    assert s.iloc[-1] < 50.0


def test_missing_btc_column_raises():
    w = pd.DataFrame({("FNG", "value"): [50.0, 60.0]})
    with pytest.raises(ValueError):
        CryptoPriceFactor().raw(w)


def test_uses_btc_not_leveraged_etf():
    """红线：因子输入必须是 BTC 现货，出现 BITX 列也不应被使用。

    做法：同时提供 BTC 与 BITX 列，其中 BITX 是人为污染的极端值。
    若实现误用 BITX，分数会明显不同。

    注意：夹具必须足够长（≥1100）——否则两个序列都全 NaN，`dropna()` 后
    都为空，`assert_series_equal` 会**假通过**，起不到红线作用。
    """
    n = 1100
    btc = _trending(n)
    idx = pd.bdate_range("2016-01-04", periods=n)
    w = pd.DataFrame({("BTC", "close"): btc}, index=idx)
    w[("BITX", "close")] = [1.0] * n          # 污染列：恒定值
    clean = pd.DataFrame({("BTC", "close"): btc}, index=idx)
    a = CryptoPriceFactor().score(w).dropna()
    b = CryptoPriceFactor().score(clean).dropna()
    assert not a.empty and not b.empty         # 防止全 NaN 假通过
    pd.testing.assert_series_equal(a, b)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/factors/test_crypto_price.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fg_system.factors.crypto_price'`

- [ ] **Step 3: 实现因子**

```python
# fg_system/factors/crypto_price.py
# -*- coding: utf-8 -*-
"""CF2 BTC 价格因子（先验权重 50%，§5.2）。

四个子项等权（与 v1 F3 结构对称）：动量(20/60日)、RSI(14)、距 52 周回撤（反转）、
20 日已实现波动率（反转）。

**红线（v1 §4.5 约束 1）**：输入必须是 **BTC 现货**，禁止使用 BITX/MSTX 等
杠杆 ETF 自身价格——杠杆 ETF 含年化数十个百分点的波动率拖累，会把产品损耗
系统性误读为「恐惧」，产生持续的错误买入信号。
"""
import numpy as np

from fg_system import config
from fg_system.factors.base import Factor, rolling_pct
from fg_system.factors.price import drawdown_52w, rsi

BTC_COLUMN = ("BTC", "close")


class CryptoPriceFactor(Factor):
    name = "crypto_price"
    market = "crypto"

    def raw(self, wide):
        if BTC_COLUMN not in wide.columns:
            raise ValueError(
                "CF2 必须使用 BTC 现货（%s），当前列: %s" % (BTC_COLUMN, list(wide.columns)))
        btc = wide[BTC_COLUMN]
        w = config.RANK_WINDOW

        mom = (rolling_pct(btc.pct_change(20), w)
               + rolling_pct(btc.pct_change(60), w)) / 2.0      # 正向
        strength = rolling_pct(rsi(btc), w)                     # 正向
        dd = 1.0 - rolling_pct(drawdown_52w(btc), w)            # 反转
        vol = btc.pct_change().rolling(20).std() * np.sqrt(252)
        calm = 1.0 - rolling_pct(vol, w)                        # 反转
        return (mom + strength + dd + calm) / 4.0
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/factors/test_crypto_price.py -v`
Expected: PASS（全部 8 个）

**夹具长度要求**：`drawdown_52w`(252) + `rolling_pct`(756) 串联，序列长度必须
**≥1008** 才有非 NaN 输出；本 Task 测试统一用 **≥1100 点**。实测首个非 NaN 在
**0-based 索引 1006**（序列第 1007 个点）——`rolling_pct` 需要完整 756 个非 NaN
输入才产出首值，而 `drawdown_52w` 的首个非 NaN 在索引 251，故 251 + 756 - 1 = 1006。
长度不足的后果：`test_score_in_range` 因全 NaN 失败；`test_uses_btc_not_leveraged_etf`
的两个序列**都**全 NaN，`dropna()` 后都空，`assert_series_equal` **假通过**。

- [ ] **Step 5: 跑全量测试**

Run: `python -m pytest tests/ -q`
Expected: `187 passed`（179 + 8；Task 6 前基线为 179 个）

- [ ] **Step 6: 提交**

```bash
git add fg_system/factors/crypto_price.py tests/factors/test_crypto_price.py docs/superpowers/plans/2026-09-21-crypto-subsystem-v2.md
git commit -m "feat(factors): CF2 BTC 价格因子

测试夹具修正：drawdown_52w(252)+rolling_pct(756) 串联需 >=1008 点才有非 NaN；
原计划给的 816 点夹具会让 test_score_in_range 全 NaN、
让 test_uses_btc_not_leveraged_etf 假通过。
同时把「上涨 vs 下跌」对照改为 v1 风格的「长上涨 vs 近期急跌」——
rolling_pct 度量相对位置而非趋势方向，前者是它结构性做不到的断言。" && echo "# user-confirmed-commit"
```

---

## Task 7: 指数层泛化（多市场）

**Files:**
- Modify: `fg_system/index.py`
- Test: `tests/test_index.py`（追加）

**兼容性要求**：v1 的 `build_factors()` / `factor_scores()` / `combine()` / `smooth()` 签名与行为**完全不变**（127 个测试依赖它们）。新增的函数是并行的市场感知版本。

- [ ] **Step 1: 写失败的测试**

追加到 `tests/test_index.py` 末尾：

```python
# ---------------------------------------------------------------- v2 多市场

def test_build_factors_for_us_equity_unchanged():
    """大盘因子集合必须与 v1 完全一致。"""
    names = [f.name for f in index.build_factors_for("us_equity")]
    assert names == ["vix", "term", "price", "breadth"]


def test_build_factors_for_crypto():
    names = [f.name for f in index.build_factors_for("crypto")]
    assert names == ["crypto_fng", "crypto_price"]


def test_weights_for_market():
    assert index.weights_for("us_equity") == config.WEIGHTS
    assert index.weights_for("crypto") == config.CRYPTO_WEIGHTS


def test_combine_uses_market_weights():
    """crypto 市场必须用 CRYPTO_WEIGHTS，而不是 WEIGHTS。"""
    scores = pd.DataFrame(
        {"crypto_fng": [100.0], "crypto_price": [0.0]},
        index=pd.to_datetime(["2026-01-01"]))
    out = index.combine(scores, market="crypto")
    # 50/50 权重 → 50
    assert out.iloc[0] == pytest.approx(50.0)


def test_combine_nan_when_one_of_two_missing_by_default():
    """crypto 只有 2 个因子，默认 min_valid=2 → 缺一个即无信号。

    设计依据 §5.4：「有效因子数 < MIN_VALID_FACTORS 时返回 NaN，避免单因子主导」。
    crypto 只有 2 个因子，若允许单因子重归一化，指数会被单个因子完全支配。
    """
    scores = pd.DataFrame(
        {"crypto_fng": [80.0], "crypto_price": [float("nan")]},
        index=pd.to_datetime(["2026-01-01"]))
    out = index.combine(scores, market="crypto")
    assert pd.isna(out.iloc[0])


def test_combine_renormalizes_when_min_valid_relaxed():
    """显式放宽 min_valid=1 时，单个有效因子按剩余权重重归一化（§5.4 的重归一化逻辑）。"""
    scores = pd.DataFrame(
        {"crypto_fng": [80.0], "crypto_price": [float("nan")]},
        index=pd.to_datetime(["2026-01-01"]))
    out = index.combine(scores, market="crypto", min_valid=1)
    assert out.iloc[0] == pytest.approx(80.0)


def test_combine_renormalizes_for_equity_when_one_missing():
    """大盘 4 个因子缺 1 个 → 3 个有效 ≥ 2 → 正常重归一化（v1 行为）。"""
    scores = pd.DataFrame(
        {"vix": [80.0], "term": [60.0], "price": [40.0], "breadth": [float("nan")]},
        index=pd.to_datetime(["2026-01-01"]))
    out = index.combine(scores, market="us_equity")
    # 等权 0.30/0.20/0.30，breadth 缺失 → 按剩余权重归一化
    expected = (80 * 0.30 + 60 * 0.20 + 40 * 0.30) / (0.30 + 0.20 + 0.30)
    assert out.iloc[0] == pytest.approx(expected)


def test_combine_nan_when_too_few_valid_factors():
    """有效因子数 < MIN_VALID_FACTORS 时必须 NaN，避免单因子主导。"""
    scores = pd.DataFrame(
        {"crypto_fng": [80.0], "crypto_price": [float("nan")]},
        index=pd.to_datetime(["2026-01-01"]))
    out = index.combine(scores, market="crypto", min_valid=2)
    assert pd.isna(out.iloc[0])


def test_build_index_returns_series_for_market():
    """build_index 是市场感知的统一入口。"""
    scores = pd.DataFrame(
        {"crypto_fng": [90.0, 10.0], "crypto_price": [90.0, 10.0]},
        index=pd.to_datetime(["2026-01-01", "2026-01-02"]))
    out = index.build_index(scores, market="crypto")
    assert isinstance(out, pd.Series)
    assert out.iloc[0] == pytest.approx(90.0)
    assert out.iloc[1] == pytest.approx(10.0)
```

同时在 `tests/test_index.py` 顶部确认已导入 `config`；若未导入，补上：

```python
from fg_system import config
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_index.py -v`
Expected: FAIL — `AttributeError: module 'fg_system.index' has no attribute 'build_factors_for'`

- [ ] **Step 3: 实现多市场支持**

将 `fg_system/index.py` 的 `build_factors`、`combine` 两个函数替换为下面的版本（`factor_scores`、`smooth` 保持不变，但 `factor_scores` 增加 `market` 参数）：

```python
def build_factors(market="us_equity"):
    """按市场构造因子实例。

    market="us_equity" → v1 四因子（签名兼容 v1 的无参调用）
    market="crypto"    → CF1 贪恐 + CF2 BTC 价格
    """
    return build_factors_for(market)


def build_factors_for(market):
    """按市场构造因子实例（显式版本，供 v2 调用）。"""
    if market == "crypto":
        from fg_system.factors.crypto_fng import CryptoFngFactor
        from fg_system.factors.crypto_price import CryptoPriceFactor

        return [CryptoFngFactor(), CryptoPriceFactor()]

    from fg_system.factors.breadth import BreadthFactor
    from fg_system.factors.price import PriceFactor
    from fg_system.factors.term import TermStructureFactor
    from fg_system.factors.vix import VixFactor

    return [VixFactor(), TermStructureFactor(), PriceFactor(), BreadthFactor()]


def weights_for(market):
    """该市场的因子权重表。"""
    if market == "crypto":
        return config.CRYPTO_WEIGHTS
    return config.WEIGHTS


def factor_scores(wide, factors=None, market="us_equity"):
    """各因子 0-100 分数矩阵（列 = 因子名）。"""
    factors = factors or build_factors_for(market)
    return pd.DataFrame({f.name: f.score(wide) for f in factors})


def combine(scores, factors=None, market="us_equity", min_valid=None):
    """加权合成指数，缺失因子按剩余权重重新归一化（§5.4）。

    v1 调用方式 `combine(scores)` 行为完全不变（market 默认 us_equity）。
    """
    if factors is None:
        factors = [type("F", (), {"name": c})() for c in scores.columns]
    weight_table = weights_for(market)
    weight = pd.Series({f.name: weight_table[f.name] for f in factors}, dtype=float)

    min_valid = config.MIN_VALID_FACTORS if min_valid is None else min_valid

    valid = scores.notna()
    weights = valid.mul(weight, axis=1)
    weight_sum = weights.sum(axis=1)

    weighted = (scores.fillna(0.0) * weights).sum(axis=1)
    out = weighted / weight_sum.replace(0.0, np.nan)

    too_few = valid.sum(axis=1) < min_valid
    out[too_few] = np.nan
    return out.clip(lower=0.0, upper=100.0)


def build_index(scores, market="us_equity", min_valid=None):
    """市场感知的统一入口：加权合成 + 平滑。"""
    return smooth(combine(scores, market=market, min_valid=min_valid))
```

**注意**：`combine` 在 `factors=None` 时用列名构造轻量代理对象，这样 v1 的
`combine(scores, factors=build_factors())` 与 v2 的 `combine(scores, market="crypto")`
两种调用方式都能工作。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_index.py -v`
Expected: PASS（v1 原有 + 7 个新增）

**关于 crypto 的 min_valid**：加密只有 2 个因子，默认 `MIN_VALID_FACTORS=2` 等价于
「两个都必须有效」。这是 §5.4「避免单因子主导」的必然结果，不是缺陷。
副作用：加密信号的有效起点 = max(CF1 756, CF2 1008) = **1008 个交易日**。

- [ ] **Step 5: 跑全量测试确认 v1 无回归**

Run: `python -m pytest tests/ -q`
Expected: `172 passed`

**若 v1 的 test_index.py 原有测试失败**，说明 `combine` 的兼容性被破坏——检查 `factors=None` 分支的代理对象构造，不要改 v1 测试。

- [ ] **Step 6: 提交**

```bash
git add fg_system/index.py tests/test_index.py
git commit -m "feat(index): 泛化为多市场指数构建" # user-confirmed-commit
```

---

## Task 8: signal 包拆分 — `market_signal`（单市场层）

**为什么拆**（§3.3）：v1 的 `signal` 是单市场纯函数。v2 引入共享弹药池后，状态分两类——**市场级**（五档、趋势过滤、分层上限）与**组合级**（弹药池余额、批次释放）。混在一起会让「哪个市场的信号触发了这笔调仓」无法回答。

**本 Task 只建包与单市场层**，`__init__.py` 的兼容层在 Task 10 完成。

**Files:**
- Create: `fg_system/signal/__init__.py`（临时空壳，Task 10 填充）
- Create: `fg_system/signal/market_signal.py`
- Test: `tests/signal/__init__.py`、`tests/signal/test_market_signal.py`

- [ ] **Step 1: 建测试目录**

```bash
mkdir -p tests/signal && touch tests/signal/__init__.py
```

- [ ] **Step 2: 写失败的测试**

```python
# tests/signal/test_market_signal.py
# -*- coding: utf-8 -*-
"""market_signal 单市场层测试。"""
import numpy as np
import pandas as pd
import pytest

from fg_system import config
from fg_system.signal import market_signal as ms


# ---------------------------------------------------------------- 趋势过滤

def test_trend_factor_is_one_above_ma():
    close = pd.Series(np.linspace(100, 200, 300),
                      index=pd.bdate_range("2020-01-01", periods=300))
    tf = ms.trend_factor_series(close)
    assert tf.iloc[-1] == pytest.approx(1.0)


def test_trend_factor_is_discounted_below_ma():
    close = pd.Series(np.linspace(200, 100, 300),
                      index=pd.bdate_range("2020-01-01", periods=300))
    tf = ms.trend_factor_series(close)
    assert tf.iloc[-1] == pytest.approx(config.TREND_FILTER_FACTOR)


def test_trend_factor_is_one_during_ma_warmup():
    """均线窗口不足时不做限制（返回 1.0），且不得抛异常。"""
    close = pd.Series(np.linspace(100, 110, 50),
                      index=pd.bdate_range("2020-01-01", periods=50))
    tf = ms.trend_factor_series(close)
    assert (tf == 1.0).all()


def test_trend_factor_handles_nan():
    close = pd.Series([100.0, np.nan, 102.0],
                      index=pd.bdate_range("2020-01-01", periods=3))
    tf = ms.trend_factor_series(close)
    assert len(tf) == 3


# ---------------------------------------------------------------- 核心仓

def test_market_core_without_trend():
    """无趋势限制时，核心仓 = 饱和度 × CORE_CAP × MARKET_CORE_RATIO。"""
    core = ms.market_core(10.0, trend=1.0, market="us_equity")
    expected = config.CORE_CAP * config.MARKET_CORE_RATIO["us_equity"] * 1.0
    assert core == pytest.approx(expected)


def test_market_core_with_trend_discount():
    core = ms.market_core(10.0, trend=config.TREND_FILTER_FACTOR, market="us_equity")
    full = config.CORE_CAP * config.MARKET_CORE_RATIO["us_equity"]
    assert core == pytest.approx(full * config.TREND_FILTER_FACTOR)


def test_market_core_nan_index_returns_none():
    assert ms.market_core(float("nan"), trend=1.0, market="us_equity") is None


def test_crypto_core_is_smaller_than_equity_core():
    """同样指数下，加密核心仓上限必须小于大盘（21% vs 49%）。"""
    eq = ms.market_core(10.0, trend=1.0, market="us_equity")
    cr = ms.market_core(10.0, trend=1.0, market="crypto")
    assert cr < eq


# ---------------------------------------------------------------- 分层上限

def test_layer_caps_crypto_three_layers():
    caps = ms.layer_cap_position(1.0, market="crypto")
    assert caps["btc_beta"] == pytest.approx(1.00)
    assert caps["stock_high_beta"] == pytest.approx(0.70)
    assert caps["stock_ops_beta"] == pytest.approx(0.50)


def test_layer_caps_scales_with_core():
    caps = ms.layer_cap_position(0.21, market="crypto")
    assert caps["btc_beta"] == pytest.approx(0.21)
    assert caps["stock_high_beta"] == pytest.approx(0.21 * 0.70)


def test_layer_caps_empty_for_equity():
    assert ms.layer_cap_position(0.49, market="us_equity") == {}


# ---------------------------------------------------------------- 加密极贪分批

def test_greed_tiers_trigger_in_order():
    st = ms.MarketState(market="crypto")
    st, note = ms.apply_greed_tiers(st, 86.0)
    assert st.greed_tier == 1
    st, note = ms.apply_greed_tiers(st, 91.0)
    assert st.greed_tier == 2
    st, note = ms.apply_greed_tiers(st, 96.0)
    assert st.greed_tier == 3


def test_greed_tiers_only_trigger_once():
    st = ms.MarketState(market="crypto")
    st, _ = ms.apply_greed_tiers(st, 86.0)
    st, _ = ms.apply_greed_tiers(st, 87.0)
    assert st.greed_tier == 1


def test_greed_tiers_restore_one_by_one():
    """回落至 <60 时**逐档恢复**，不是一次性恢复。"""
    st = ms.MarketState(market="crypto")
    for v in (86.0, 91.0, 96.0):
        st, _ = ms.apply_greed_tiers(st, v)
    assert st.greed_tier == 3
    st, _ = ms.apply_greed_tiers(st, 55.0)
    assert st.greed_tier == 2
    st, _ = ms.apply_greed_tiers(st, 55.0)
    assert st.greed_tier == 1


def test_greed_tier_factor_values():
    """三档对应的核心仓系数：2/3、1/3、1/4。"""
    assert ms.greed_tier_factor(0) == pytest.approx(1.0)
    assert ms.greed_tier_factor(1) == pytest.approx(2.0 / 3.0)
    assert ms.greed_tier_factor(2) == pytest.approx(1.0 / 3.0)
    assert ms.greed_tier_factor(3) == pytest.approx(0.25)


def test_market_state_is_deep_copied():
    """§3.4 硬约定：状态变更函数不得修改入参。"""
    st = ms.MarketState(market="crypto")
    snapshot = st.to_dict()
    ms.apply_greed_tiers(st, 96.0)
    assert st.to_dict() == snapshot


# ---------------------------------------------------------------- market_target

def test_market_target_combines_trend_and_tiers():
    st = ms.MarketState(market="crypto")
    st, _ = ms.apply_greed_tiers(st, 91.0)          # 系数 1/3
    out = ms.market_target(
        index_value=10.0, drawdown=0.0, trend=1.0,
        state=st, market="crypto")
    full = config.CORE_CAP * config.MARKET_CORE_RATIO["crypto"]
    assert out.core_position == pytest.approx(full / 3.0)


def test_market_target_trend_priority_over_extreme_fear():
    """趋势过滤优先级最高：极恐 + 跌破均线时，上限取趋势结果。"""
    st = ms.MarketState(market="us_equity")
    out = ms.market_target(
        index_value=5.0, drawdown=0.0, trend=config.TREND_FILTER_FACTOR,
        state=st, market="us_equity")
    full = config.CORE_CAP * config.MARKET_CORE_RATIO["us_equity"]
    assert out.core_position == pytest.approx(full * config.TREND_FILTER_FACTOR)


def test_market_target_reports_extreme_fear():
    st = ms.MarketState(market="crypto")
    out = ms.market_target(
        index_value=8.0, drawdown=0.0, trend=1.0, state=st, market="crypto")
    assert out.extreme_fear is True


def test_market_target_nan_index_returns_none_core():
    st = ms.MarketState(market="us_equity")
    out = ms.market_target(
        index_value=float("nan"), drawdown=0.0, trend=1.0,
        state=st, market="us_equity")
    assert out.core_position is None
```

**⚠️ 实施中修正的两处（已落地，见提交记录）**：

1. **`market_target` 返回元组 `(MarketOutput, MarketState)`**，上面 4 个 `market_target`
   测试必须写成 `out, st = ms.market_target(...)`。初版计划漏了解包。

2. **`test_market_target_combines_trend_and_tiers` 自相矛盾，已替换**。原测试用
   `apply_greed_tiers(st, 91.0)` 建 tier=2，却又用 `index_value=10.0` 调 `market_target`
   ——而 10.0 < `CRYPTO_GREED_UNLOCK_INDEX`(60) 会触发**逐档恢复**，tier 变 1，
   与期望的 1/3 冲突。**更严重的是**：它暴露了实现的一个真实缺陷——原实现写成
   `core = core * greed_tier_factor(tier)`，而五档在指数 ≥80 时已给饱和度 0，
   档位永远对着 0 做乘法，是**死代码**，违背 §6.5「不一次性清仓、分批递减」的初衷。

   已改为**档位替换五档饱和度**（设下限），并替换为 4 个测试：
   `test_market_target_greed_tier_replaces_five_tier_saturation`、
   `test_market_target_greed_tier_deepens_with_index`、
   `test_market_target_greed_tier_respects_trend_filter`、
   `test_market_target_without_tier_uses_five_tier`。
```

- [ ] **Step 3: 跑测试确认失败**

Run: `python -m pytest tests/signal/test_market_signal.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fg_system.signal'`

- [ ] **Step 4: 建包与实现**

创建 `fg_system/signal/__init__.py`（临时空壳，Task 10 填充）：

```python
# -*- coding: utf-8 -*-
"""信号层包。兼容层在 Task 10 完成。"""
```

创建 `fg_system/signal/market_signal.py`：

```python
# -*- coding: utf-8 -*-
"""单市场信号层：五档 + 趋势过滤 + 分层上限 + 极端规则（§6.1–6.3、§6.5）。

硬性约定（§3.4）：纯函数 + 显式状态。禁止读写全局变量或文件。

优先级（§6.6）：趋势过滤 > 极端规则 > 五档映射 > 分层上限 > 共享弹药池。
本模块负责前四项；弹药池在 portfolio 层。
"""
import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from fg_system import config

ZONE_NAMES = ["极度恐惧", "恐惧", "中性", "贪婪", "极度贪婪"]


@dataclass
class MarketState:
    """单市场状态机。所有字段可 JSON 序列化。"""

    market: str = "us_equity"
    circuit_breaker: bool = False
    cb_trigger_index: float = None
    cb_trigger_date: str = None
    cb_low_price: dict = field(default_factory=dict)
    greed_tier: int = 0                   # 加密极贪已触发档位数（0-3）
    last_extreme_fear_date: str = None

    def to_dict(self):
        return {
            "market": self.market,
            "circuit_breaker": self.circuit_breaker,
            "cb_trigger_index": self.cb_trigger_index,
            "cb_trigger_date": self.cb_trigger_date,
            "cb_low_price": dict(self.cb_low_price),
            "greed_tier": int(self.greed_tier),
            "last_extreme_fear_date": self.last_extreme_fear_date,
        }

    @classmethod
    def from_dict(cls, data):
        if not data:
            return cls()
        return cls(
            market=data.get("market", "us_equity"),
            circuit_breaker=bool(data.get("circuit_breaker", False)),
            cb_trigger_index=data.get("cb_trigger_index"),
            cb_trigger_date=data.get("cb_trigger_date"),
            cb_low_price=dict(data.get("cb_low_price") or {}),
            greed_tier=int(data.get("greed_tier", 0)),
            last_extreme_fear_date=data.get("last_extreme_fear_date"),
        )


@dataclass
class MarketOutput:
    """单市场的输出，供 portfolio 层消费。"""

    market: str
    core_position: float      # 已含趋势过滤与分层上限；None 表示无信号
    drawdown: float
    trend: float              # 1.0 或 TREND_FILTER_FACTOR
    trend_blocked: bool
    extreme_fear: bool
    extreme: bool             # 是否触发极端规则（用于豁免防抖动）
    layer_caps: dict
    note: str = ""


def _is_nan(value):
    return value is None or (isinstance(value, float) and math.isnan(value))


def _copy(state):
    """返回独立副本（§3.4 硬约定：不得修改入参）。"""
    return MarketState.from_dict(state.to_dict())


# ---------------------------------------------------------------- 趋势过滤（§6.1）
def trend_factor_series(close, ma_days=None, factor=None):
    """趋势系数序列：收盘 < MA 时为 factor，否则 1.0。

    均线窗口不足处返回 1.0（不做限制）。这与 v1 §10.4「不足窗口返回 NaN」不冲突：
    此处是**风险约束**而非因子，指数本身的 756 日 warmup 已保证有效信号出现时
    200 日均线必然有效，因此该分支只影响 warmup 期，不会污染有效信号。
    """
    ma_days = config.TREND_MA_DAYS if ma_days is None else ma_days
    factor = config.TREND_FILTER_FACTOR if factor is None else factor
    ma = close.rolling(ma_days, min_periods=ma_days).mean()
    below = close < ma
    out = pd.Series(np.where(below, factor, 1.0), index=close.index)
    out[ma.isna()] = 1.0
    return out


# ---------------------------------------------------------------- 核心仓（§6.2）
def zone_of(index_value):
    """档位索引 0-4。边界为**下闭区间**：20 属于档 1。"""
    for i, edge in enumerate(config.ZONE_EDGES):
        if index_value < edge:
            return i
    return len(config.ZONE_EDGES)


def market_core(index_value, trend, market):
    """核心仓 = 五档饱和度 × CORE_CAP × MARKET_CORE_RATIO × 趋势系数。

    指数无效时返回 None（warmup 期不产生信号）。
    """
    if _is_nan(index_value):
        return None
    ratio = config.MARKET_CORE_RATIO[market]
    saturation = config.ZONE_SATURATION[zone_of(index_value)]
    return config.CORE_CAP * ratio * saturation * trend


# ---------------------------------------------------------------- 分层上限（§6.3）
def layer_cap_position(core_position, market):
    """加密三层各自的上限（相对加密核心仓满仓值）。

    大盘返回空 dict（无分层概念）。
    """
    if market != "crypto":
        return {}
    return {layer: core_position * cap for layer, cap in config.CRYPTO_LAYER_CAP.items()}


# ---------------------------------------------------------------- 加密极贪分批（§6.5）
def greed_tier_factor(tier):
    """档位对应的核心仓系数。tier=0 → 1.0（未减仓）。"""
    if tier <= 0:
        return 1.0
    idx = min(tier, len(config.CRYPTO_GREED_REDUCE)) - 1
    return config.CRYPTO_GREED_REDUCE[idx]


def apply_greed_tiers(state, index_value):
    """加密极贪分批减仓（§6.5）。返回 (新状态, 说明)。

    - 指数 ≥ 各档触发线 → 逐档加深（每档只触发一次）
    - 指数 < CRYPTO_GREED_UNLOCK_INDEX → **逐档恢复**（一次只退一档）
    """
    if _is_nan(index_value):
        return state, ""

    state = _copy(state)
    n_tiers = len(config.CRYPTO_GREED_TIERS)

    # 逐档加深：找出当前指数满足的最高档位
    target_tier = 0
    for i, trigger in enumerate(config.CRYPTO_GREED_TIERS):
        if index_value >= trigger:
            target_tier = i + 1

    if target_tier > state.greed_tier:
        state.greed_tier = min(target_tier, n_tiers)
        return state, "加密极贪减仓至第 %d 档（指数 %.1f）" % (state.greed_tier, index_value)

    if index_value < config.CRYPTO_GREED_UNLOCK_INDEX and state.greed_tier > 0:
        state.greed_tier -= 1
        return state, "加密极贪恢复一档（指数 %.1f，剩余 %d 档）" % (
            index_value, state.greed_tier)

    return state, ""


# ---------------------------------------------------------------- 大盘熔断（§6.5，沿用 v1）
def apply_circuit_breaker(state, index_value, date, prices):
    """大盘极贪熔断（v1 §8.1 逻辑，阈值改为相对该市场核心仓满仓值）。

    返回 (新状态, 熔断后的核心仓系数或 None, 说明)。
    系数 None 表示未熔断，沿用五档结果。
    """
    if _is_nan(index_value):
        return state, None, ""

    state = _copy(state)

    if not state.circuit_breaker and index_value >= config.EXTREME_GREED_TRIGGER:
        state.circuit_breaker = True
        state.cb_trigger_index = index_value
        state.cb_trigger_date = date
        state.cb_low_price = dict(prices or {})
        return state, config.EXTREME_GREED_FLOOR, "极贪熔断触发（指数 %.1f）" % index_value

    if not state.circuit_breaker:
        return state, None, ""

    for sym, px in (prices or {}).items():
        if px is None or (isinstance(px, float) and math.isnan(px)):
            continue
        low = state.cb_low_price.get(sym)
        if low is None or px < low:
            state.cb_low_price[sym] = px

    if index_value < config.EXTREME_GREED_UNLOCK_INDEX:
        state.circuit_breaker = False
        return state, None, "熔断解锁（指数回落至 %.1f）" % index_value

    if (state.cb_trigger_index is not None
            and state.cb_trigger_index - index_value >= config.EXTREME_GREED_UNLOCK_DROP):
        state.circuit_breaker = False
        return state, None, "熔断解锁（指数自峰值回落 %.1f 点）" % (
            state.cb_trigger_index - index_value)

    for sym, px in (prices or {}).items():
        low = state.cb_low_price.get(sym)
        if low and low > 0 and px / low - 1.0 >= config.EXTREME_GREED_UNLOCK_REBOUND:
            state.circuit_breaker = False
            return state, None, "熔断解锁（%s 自低点反弹 %.1f%%）" % (
                sym, (px / low - 1.0) * 100)

    return state, config.EXTREME_GREED_FLOOR, "熔断维持中"


# ---------------------------------------------------------------- 单市场总入口
def market_target(index_value, drawdown, trend, state, market, date=None, prices=None):
    """计算单市场的核心仓与极端状态，返回 (MarketOutput, 新 MarketState)。"""
    state = _copy(state)
    note = ""
    extreme = False

    core = market_core(index_value, trend, market)
    if core is None:
        return (MarketOutput(market=market, core_position=None, drawdown=drawdown,
                             trend=trend, trend_blocked=(trend < 1.0),
                             extreme_fear=False, extreme=False, layer_caps={},
                             note="指数无效"),
                state)

    # 极端规则（市场级）
    full = config.CORE_CAP * config.MARKET_CORE_RATIO[market] * trend

    if market == "crypto":
        state, tier_note = apply_greed_tiers(state, index_value)
        if tier_note:
            note = tier_note
            extreme = True
        # 档位 > 0 时**替换**五档饱和度：设一个下限，避免五档在指数 >=80 时
        # 直接清仓（设计 §6.5 的初衷是「不一次性清仓，分批递减」）。
        # 档位 = 0 时沿用五档饱和度。
        if state.greed_tier > 0:
            core = full * greed_tier_factor(state.greed_tier)
    else:
        state, cb_floor, cb_note = apply_circuit_breaker(
            state, index_value, date, prices or {})
        if cb_floor is not None:
            # 熔断底仓：相对该市场核心仓满仓值
            core = min(core, full * cb_floor)
            note = cb_note
            extreme = True

    extreme_fear = (not _is_nan(index_value)
                    and index_value <= (config.CRYPTO_EXTREME_FEAR_TRIGGER
                                        if market == "crypto"
                                        else config.EXTREME_FEAR_TRIGGER))

    return (MarketOutput(
        market=market, core_position=core, drawdown=drawdown, trend=trend,
        trend_blocked=(trend < 1.0), extreme_fear=extreme_fear, extreme=extreme,
        layer_caps=layer_cap_position(core, market), note=note), state)
```

- [ ] **Step 5: 跑测试确认通过**

Run: `python -m pytest tests/signal/test_market_signal.py -v`
Expected: PASS（全部 22 个）

- [ ] **Step 6: 提交**

```bash
git add fg_system/signal/ tests/signal/
git commit -m "feat(signal): 拆分出 market_signal 单市场层（含趋势过滤与分层上限）" # user-confirmed-commit
```

---

## Task 9: signal 包拆分 — `portfolio`（组合级共享弹药池）

**设计依据**（§6.4）：弹药池**只有一个**，两个市场共享，先到先得。加密三层高度相关，若各自备弹药会在同一天同时打光并实际超配。

**冲突处理**：`优先级 = 该市场当前回撤 / 该市场「当前待释放批次」的阈值`。平局时大盘优先。

**为什么用比值而不是绝对值**：加密天然跌得多，用绝对值会让加密永远优先。

**Files:**
- Create: `fg_system/signal/portfolio.py`
- Test: `tests/signal/test_portfolio.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/signal/test_portfolio.py
# -*- coding: utf-8 -*-
"""portfolio 组合级共享弹药池测试。"""
import pytest

from fg_system import config
from fg_system.signal import portfolio as pf
from fg_system.signal.market_signal import MarketOutput


def _out(market, drawdown, core=0.4, extreme_fear=False):
    return MarketOutput(
        market=market, core_position=core, drawdown=drawdown, trend=1.0,
        trend_blocked=False, extreme_fear=extreme_fear, extreme=False,
        layer_caps={}, note="")


# ---------------------------------------------------------------- 优先级

def test_pending_threshold_first_batch():
    st = pf.PortfolioState()
    assert pf.pending_threshold(st, "us_equity") == pytest.approx(0.20)
    assert pf.pending_threshold(st, "crypto") == pytest.approx(0.30)


def test_pending_threshold_advances_after_release():
    st = pf.PortfolioState(market_batches={"us_equity": 1})
    assert pf.pending_threshold(st, "us_equity") == pytest.approx(0.40)


def test_pending_threshold_none_when_exhausted():
    st = pf.PortfolioState(market_batches={"us_equity": 3})
    assert pf.pending_threshold(st, "us_equity") is None


def test_priority_is_ratio_not_absolute():
    """加密跌 35% 的比值（35/30=1.17）高于大盘跌 25%（25/20=1.25）？不——算清楚。

    大盘 25/20 = 1.25 > 加密 35/30 = 1.167 → 大盘优先。
    这证明用的是比值：若用绝对值，加密（35）会优先。
    """
    st = pf.PortfolioState()
    p_eq = pf.ammo_priority(st, _out("us_equity", 0.25))
    p_cr = pf.ammo_priority(st, _out("crypto", 0.35))
    assert p_eq > p_cr


def test_priority_none_when_below_threshold():
    st = pf.PortfolioState()
    assert pf.ammo_priority(st, _out("us_equity", 0.10)) is None


# ---------------------------------------------------------------- 共享池

def test_release_single_market():
    st = pf.PortfolioState()
    st, newly, note = pf.release_ammo(st, [_out("us_equity", 0.25)])
    assert len(st.ammo_released) == 1
    assert st.market_batches["us_equity"] == 1
    assert newly == 1


def test_release_keeps_only_once_per_market_batch():
    """同一批不得重复释放。"""
    st = pf.PortfolioState()
    st, _, _ = pf.release_ammo(st, [_out("us_equity", 0.25)])
    st, newly, _ = pf.release_ammo(st, [_out("us_equity", 0.25)])
    assert newly == 0
    assert len(st.ammo_released) == 1


def test_release_deeper_batch_next_day():
    st = pf.PortfolioState()
    st, _, _ = pf.release_ammo(st, [_out("us_equity", 0.25)])
    st, newly, _ = pf.release_ammo(st, [_out("us_equity", 0.45)])
    assert newly == 1
    assert st.market_batches["us_equity"] == 2


def test_pool_exhausted_stops_release():
    """池子只有 3 个槽位，用完即止。"""
    st = pf.PortfolioState()
    st, _, _ = pf.release_ammo(st, [_out("us_equity", 0.25)])
    st, _, _ = pf.release_ammo(st, [_out("us_equity", 0.45)])
    st, _, _ = pf.release_ammo(st, [_out("us_equity", 0.65)])
    assert len(st.ammo_released) == 3
    st, newly, _ = pf.release_ammo(st, [_out("crypto", 0.80)])
    assert newly == 0


def test_conflict_higher_ratio_wins():
    """同日两市场触发，比值大者先得。"""
    st = pf.PortfolioState()
    st, newly, note = pf.release_ammo(
        st, [_out("crypto", 0.35), _out("us_equity", 0.25)])
    # 大盘 1.25 > 加密 1.167 → 大盘先释放
    assert st.market_batches.get("us_equity") == 1
    assert "us_equity" in note


def test_conflict_tie_goes_to_equity():
    """平局时大盘优先（§6.4）。"""
    st = pf.PortfolioState()
    # 大盘 0.20/0.20 = 1.0；加密 0.30/0.30 = 1.0
    st, newly, note = pf.release_ammo(
        st, [_out("crypto", 0.30), _out("us_equity", 0.20)])
    assert st.market_batches.get("us_equity") == 1


def test_only_one_batch_released_per_day():
    """单日最多释放 1 批（避免一天打光）。"""
    st = pf.PortfolioState()
    st, newly, _ = pf.release_ammo(
        st, [_out("crypto", 0.80), _out("us_equity", 0.65)])
    assert newly == 1
    assert len(st.ammo_released) == 1


# ---------------------------------------------------------------- 极恐提前释放

def test_extreme_fear_releases_one_batch():
    st = pf.PortfolioState()
    st, n, note = pf.apply_extreme_fear(st, [_out("crypto", 0.0, extreme_fear=True)], "2026-01-05")
    assert n == 1
    assert st.last_extreme_fear_date == "2026-01-05"


def test_extreme_fear_respects_cooldown():
    st = pf.PortfolioState(last_extreme_fear_date="2026-01-05")
    st, n, _ = pf.apply_extreme_fear(st, [_out("crypto", 0.0, extreme_fear=True)], "2026-01-10")
    assert n == 0


def test_extreme_fear_noop_when_pool_exhausted():
    st = pf.PortfolioState()
    for _ in range(3):
        st, _, _ = pf.release_ammo(st, [_out("us_equity", 0.65)])
    st, n, _ = pf.apply_extreme_fear(st, [_out("crypto", 0.0, extreme_fear=True)], "2026-01-05")
    assert n == 0


# ---------------------------------------------------------------- 组合仓位

def test_combine_sums_core_and_ammo():
    st = pf.PortfolioState(ammo_released=[0])
    target, note = pf.combine([_out("us_equity", 0.0, core=0.49),
                               _out("crypto", 0.0, core=0.21)], st)
    assert target == pytest.approx(0.49 + 0.21 + 0.10)


def test_combine_handles_none_core():
    """某市场无信号（warmup）时只计另一个市场。"""
    st = pf.PortfolioState()
    target, note = pf.combine([_out("us_equity", 0.0, core=None),
                               _out("crypto", 0.0, core=0.21)], st)
    assert target == pytest.approx(0.21)


def test_combine_none_when_all_markets_none():
    st = pf.PortfolioState()
    target, note = pf.combine([_out("us_equity", 0.0, core=None),
                               _out("crypto", 0.0, core=None)], st)
    assert target is None


def test_combine_clips_to_one():
    st = pf.PortfolioState(ammo_released=[0, 1, 2])
    target, _ = pf.combine([_out("us_equity", 0.0, core=0.49),
                            _out("crypto", 0.0, core=0.21)], st)
    assert target <= 1.0


# ---------------------------------------------------------------- 防抖动（收敛到本层）

def test_throttle_blocks_below_threshold():
    st = pf.PortfolioState()
    ok, reason = pf.throttle_ok(st, 0.50, 0.55, "2026-01-05")
    assert ok is False


def test_throttle_blocks_within_cooldown():
    st = pf.PortfolioState(last_rebalance_date="2026-01-05")
    ok, reason = pf.throttle_ok(st, 0.30, 0.60, "2026-01-07")
    assert ok is False


def test_throttle_allows_when_extreme():
    st = pf.PortfolioState(last_rebalance_date="2026-01-05")
    ok, reason = pf.throttle_ok(st, 0.30, 0.60, "2026-01-07", extreme=True)
    assert ok is True


def test_clip_adjustment_limits_single_move():
    assert pf.clip_adjustment(0.10, 0.90) == pytest.approx(0.40)
    assert pf.clip_adjustment(0.50, 0.55) == pytest.approx(0.55)


def test_state_is_deep_copied():
    st = pf.PortfolioState(market_batches={"us_equity": 1})
    snapshot = st.to_dict()
    pf.release_ammo(st, [_out("us_equity", 0.45)])
    assert st.to_dict() == snapshot
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/signal/test_portfolio.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fg_system.signal.portfolio'`

- [ ] **Step 3: 实现组合层**

创建 `fg_system/signal/portfolio.py`：

```python
# -*- coding: utf-8 -*-
"""组合级信号层：共享弹药池 + 统一资金池（§6.4、§6.7、§7）。

硬性约定（§3.4）：纯函数 + 显式状态。

为什么弹药池是组合级而非市场级：加密三层高度相关，BTC 崩盘时 BITX/MSTX/CONL
会在**同一天**触发加仓。若各自备弹药，会在同一天同时打光并实际超配；
共享池把「谁先用」变成显式规则，而不是隐性超配。
"""
import math
from dataclasses import dataclass, field

import pandas as pd

from fg_system import config

# 平局时的市场优先级（§6.4）：大盘标的流动性优于加密 ETF，且大盘崩盘往往
# 伴随系统性风险，先补大盘更符合风险管理直觉。
TIE_BREAK_ORDER = ["us_equity", "crypto"]


@dataclass
class PortfolioState:
    """组合级状态机。所有字段可 JSON 序列化。"""

    ammo_released: list = field(default_factory=list)          # 共享池已用槽位
    market_batches: dict = field(default_factory=dict)         # market -> 已触发档位数
    last_rebalance_date: str = None
    last_extreme_fear_date: str = None

    def to_dict(self):
        return {
            "ammo_released": sorted(self.ammo_released),
            "market_batches": dict(self.market_batches),
            "last_rebalance_date": self.last_rebalance_date,
            "last_extreme_fear_date": self.last_extreme_fear_date,
        }

    @classmethod
    def from_dict(cls, data):
        if not data:
            return cls()
        return cls(
            ammo_released=list(data.get("ammo_released") or []),
            market_batches=dict(data.get("market_batches") or {}),
            last_rebalance_date=data.get("last_rebalance_date"),
            last_extreme_fear_date=data.get("last_extreme_fear_date"),
        )


def _copy(state):
    return PortfolioState.from_dict(state.to_dict())


def batches_for(market):
    """该市场的弹药触发档位。"""
    if market == "crypto":
        return config.CRYPTO_DRAWDOWN_BATCHES
    return config.DRAWDOWN_BATCHES


def pending_threshold(state, market):
    """该市场**当前待释放批次**的阈值。已全部触发时返回 None。

    口径说明（§6.4 消歧）：分母是当前待释放的那一批，不是全部三档。
    """
    batches = batches_for(market)
    done = int(state.market_batches.get(market, 0))
    if done >= len(batches):
        return None
    return batches[done]


def ammo_priority(state, output):
    """优先级 = 当前回撤 / 当前待释放批次的阈值。未触发返回 None。"""
    if output.drawdown is None or (isinstance(output.drawdown, float)
                                   and math.isnan(output.drawdown)):
        return None
    threshold = pending_threshold(state, output.market)
    if threshold is None or output.drawdown < threshold:
        return None
    return output.drawdown / threshold


def release_ammo(state, outputs):
    """裁决共享弹药池释放。返回 (新状态, 本次释放批数, 说明)。

    规则：
      - 单日最多释放 1 批（避免一天打光）
      - 池子共 3 个槽位，先到先得
      - 同日多市场触发时按优先级比值排序，平局按 TIE_BREAK_ORDER
    """
    state = _copy(state)
    if len(state.ammo_released) >= len(config.DRAWDOWN_BATCHES):
        return state, 0, ""

    candidates = []
    for out in outputs:
        p = ammo_priority(state, out)
        if p is None:
            continue
        tie = TIE_BREAK_ORDER.index(out.market) if out.market in TIE_BREAK_ORDER else 99
        candidates.append((p, -tie, out))

    if not candidates:
        return state, 0, ""

    # 优先级降序；同优先级时 tie 小者（-tie 大者）优先
    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    _, _, winner = candidates[0]

    slot = max(state.ammo_released) + 1 if state.ammo_released else 0
    state.ammo_released.append(slot)
    state.market_batches[winner.market] = int(state.market_batches.get(winner.market, 0)) + 1
    return state, 1, "弹药释放（%s 回撤 %.1f%%）" % (
        winner.market, winner.drawdown * 100)


def apply_extreme_fear(state, outputs, date):
    """极恐提前释放弹药（§8.2 沿用 v1 语义）。返回 (新状态, 释放批数, 说明)。"""
    state = _copy(state)
    if len(state.ammo_released) >= len(config.DRAWDOWN_BATCHES):
        return state, 0, ""

    hit = next((o for o in outputs if o.extreme_fear), None)
    if hit is None:
        return state, 0, ""

    if state.last_extreme_fear_date:
        gap = (pd.Timestamp(date) - pd.Timestamp(state.last_extreme_fear_date)).days
        if gap < config.EXTREME_FEAR_COOLDOWN_DAYS:
            return state, 0, ""

    slot = max(state.ammo_released) + 1 if state.ammo_released else 0
    state.ammo_released.append(slot)
    state.market_batches[hit.market] = int(state.market_batches.get(hit.market, 0)) + 1
    state.last_extreme_fear_date = date
    return state, 1, "极恐提前释放弹药（%s）" % hit.market


def ammo_position(state):
    """弹药仓仓位 = 每批比例 × 已释放批数。"""
    return config.AMMO_PER_BATCH * len(state.ammo_released)


def combine(outputs, state):
    """组合目标仓位 = Σ各市场核心仓 + 弹药仓（§7.2）。

    某市场核心仓为 None（warmup）时跳过该市场；全部为 None 时返回 None
    （写盘为 NaN，回测自然跳过——不能写 0.0，那会被当成"主动空仓"）。
    """
    cores = [o.core_position for o in outputs if o.core_position is not None]
    if not cores:
        return None, "全部市场无有效信号"
    target = sum(cores) + ammo_position(state)
    return min(max(target, 0.0), 1.0), ""


# ---------------------------------------------------------------- 防抖动（§6.7）
# v2 把 clamp 统一收敛到本层，解决 v1 遗留问题 6（strategy.py 与 signal.throttle_ok
# 两处重复实现）。
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
            return False, "处于调仓冷却期（距上次 %d 天 < %d 天）" % (
                gap, config.REBALANCE_COOLDOWN)
    return True, "可操作"


def clip_adjustment(current, target):
    """单次调仓幅度上限（§9）。返回调整后的目标仓位。"""
    delta = target - current
    if abs(delta) <= config.MAX_SINGLE_ADJUST:
        return target
    return current + math.copysign(config.MAX_SINGLE_ADJUST, delta)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/signal/test_portfolio.py -v`
Expected: PASS（全部 25 个）

- [ ] **Step 5: 提交**

```bash
git add fg_system/signal/portfolio.py tests/signal/test_portfolio.py
git commit -m "feat(signal): 新增 portfolio 组合级共享弹药池" # user-confirmed-commit
```

---

## Task 10: signal 兼容层 + 等价性回归（**最关键的一步**）

**为什么单独做**：v1 的 127 个测试全部依赖 `fg_system.signal` 的现有 API。把 `signal.py` 换成包时，必须保证**现有调用一行不改就能继续工作**。

**策略**：
- `signal/legacy.py` = v1 `signal.py` 的**逐字副本**。v1 的行为已被 127 个测试锁定，**不重构它**——重构已验收的代码是纯风险。
- `signal/__init__.py` 重新导出 legacy 的名字 → 所有 v1 调用与测试无感。
- v2 的新流程走 `market_signal` + `portfolio`。

**等价性验证**（§9.2 第 12 条）：在 v1 参数下（`MARKET_CORE_RATIO["us_equity"]=1.0`、趋势系数 1.0），`market_signal.market_core` 必须与 `legacy.core_position` **逐点相同**。

**Files:**
- Create: `fg_system/signal/legacy.py`（v1 逐字副本）
- Modify: `fg_system/signal/__init__.py`
- Delete: `fg_system/signal.py`
- Test: `tests/signal/test_compat.py`

- [ ] **Step 1: 复制 v1 实现为 legacy.py**

```bash
git mv fg_system/signal.py fg_system/signal/legacy.py
```

然后把 `fg_system/signal/legacy.py` 的模块 docstring 第一段替换为：

```python
# -*- coding: utf-8 -*-
"""v1 单市场信号层的**逐字副本**，仅为向后兼容保留。

**不要修改本文件。** v1 的行为已被 tests/test_signal.py 的 127 个断言锁定，
任何改动都必须走 docs/trading-discipline.md 第 8 条流程。

v2 的新逻辑在 fg_system/signal/market_signal.py（单市场）与
fg_system/signal/portfolio.py（组合级）。本模块保留的原因是：重构已验收的
代码是纯风险——v2 的拆分不应该让 v1 的行为产生任何不确定性。

硬性约定（§3.4）：纯函数 + 显式状态。禁止读写全局变量或文件。
"""
```

- [ ] **Step 2: 写等价性测试**

```python
# tests/signal/test_compat.py
# -*- coding: utf-8 -*-
"""兼容层与等价性回归测试（§9.2 第 12 条）。"""
import numpy as np
import pandas as pd
import pytest

from fg_system import config
from fg_system import signal
from fg_system.signal import legacy, market_signal as ms


# ---------------------------------------------------------------- API 兼容

def test_v1_api_is_reexported():
    """v1 的全部公开名字必须仍可从 fg_system.signal 访问。"""
    for name in ["SignalState", "zone_of", "core_position", "update_ammo",
                 "ammo_position", "target_position", "apply_extremes",
                 "apply_extreme_fear", "throttle_ok", "clip_adjustment"]:
        assert hasattr(signal, name), "缺少 v1 公开 API: %s" % name


def test_v2_api_is_available():
    assert hasattr(signal, "market_signal")
    assert hasattr(signal, "portfolio")
    assert hasattr(signal, "MarketState")
    assert hasattr(signal, "PortfolioState")


def test_legacy_state_roundtrip_unchanged():
    st = legacy.SignalState()
    st.ammo_released = [0, 2]
    st.circuit_breaker = True
    restored = legacy.SignalState.from_dict(st.to_dict())
    assert restored.to_dict() == st.to_dict()


# ---------------------------------------------------------------- 等价性（核心）

@pytest.mark.parametrize("index_value", [0.0, 19.9, 20.0, 39.9, 40.0, 59.9,
                                         60.0, 79.9, 80.0, 100.0])
def test_market_core_equals_legacy_when_ratio_is_one(index_value, monkeypatch):
    """v1 参数下（us_equity 占比 1.0、无趋势折扣），v2 核心仓必须与 v1 逐点相同。

    这是「拆分没有改变行为」的证明。
    """
    monkeypatch.setitem(config.MARKET_CORE_RATIO, "us_equity", 1.0)
    v1 = legacy.core_position(index_value)
    v2 = ms.market_core(index_value, trend=1.0, market="us_equity")
    assert v2 == pytest.approx(v1)


def test_zone_of_equals_legacy():
    for v in np.arange(0.0, 100.1, 0.5):
        assert ms.zone_of(v) == legacy.zone_of(v)


def test_ammo_equivalence_with_single_market(monkeypatch):
    """单市场场景下，v2 portfolio 的弹药仓必须与 v1 相同。"""
    monkeypatch.setitem(config.MARKET_CORE_RATIO, "us_equity", 1.0)

    v1_state = legacy.SignalState()
    v2_state = signal.PortfolioState()
    for dd in (0.15, 0.25, 0.45, 0.65):
        v1_state, v1_ammo, _ = legacy.update_ammo(v1_state, dd)
        out = ms.MarketOutput(
            market="us_equity", core_position=0.0, drawdown=dd, trend=1.0,
            trend_blocked=False, extreme_fear=False, extreme=False,
            layer_caps={}, note="")
        v2_state, _, _ = signal.portfolio.release_ammo(v2_state, [out])

    assert v2_state.ammo_released == v1_state.ammo_released
    assert signal.portfolio.ammo_position(v2_state) == pytest.approx(
        legacy.ammo_position(v1_state))


def test_throttle_equivalence():
    """v2 的 throttle_ok 与 v1 行为一致（本层只是搬家）。"""
    v1_state = legacy.SignalState(last_rebalance_date="2026-01-05")
    v2_state = signal.PortfolioState(last_rebalance_date="2026-01-05")

    for current, target, date in [
        (0.50, 0.55, "2026-01-20"),
        (0.30, 0.60, "2026-01-07"),
        (0.30, 0.60, "2026-01-20"),
    ]:
        a = legacy.throttle_ok(v1_state, current, target, date)[0]
        b = signal.portfolio.throttle_ok(v2_state, current, target, date)[0]
        assert a == b


def test_clip_adjustment_equivalence():
    for current, target in [(0.10, 0.90), (0.50, 0.55), (0.80, 0.20)]:
        assert signal.portfolio.clip_adjustment(current, target) == pytest.approx(
            legacy.clip_adjustment(current, target))


# ---------------------------------------------------------------- 趋势过滤不污染 v1

def test_v1_path_has_no_trend_filter(monkeypatch):
    """legacy 路径必须完全不含趋势过滤——v1 的 127 个测试靠这一点。"""
    src = open(legacy.__file__, encoding="utf-8").read()
    assert "trend" not in src.lower()
```

- [ ] **Step 3: 填充 `signal/__init__.py`**

```python
# -*- coding: utf-8 -*-
"""信号层包（v2）。

对外暴露三组 API：

1. **v1 兼容 API**（来自 `legacy`，逐字保留）：`SignalState`、`zone_of`、
   `core_position`、`update_ammo`、`ammo_position`、`target_position`、
   `apply_extremes`、`apply_extreme_fear`、`throttle_ok`、`clip_adjustment`。
   这些名字**行为与 v1 完全一致**，不得修改。

2. **v2 单市场 API**（`market_signal`）：五档 + 趋势过滤 + 分层上限 + 极端规则。

3. **v2 组合级 API**（`portfolio`）：共享弹药池 + 统一资金池 + 防抖动收敛。

v2 的主流程用 2 + 3；1 仅为向后兼容与回归测试保留。
"""
from fg_system.signal import legacy, market_signal, portfolio
from fg_system.signal.legacy import (
    SignalState,
    ammo_position,
    apply_extreme_fear,
    apply_extremes,
    clip_adjustment,
    core_position,
    target_position,
    throttle_ok,
    update_ammo,
    zone_of,
)
from fg_system.signal.market_signal import (
    MarketOutput,
    MarketState,
    greed_tier_factor,
    layer_cap_position,
    market_core,
    market_target,
    trend_factor_series,
)
from fg_system.signal.portfolio import (
    PortfolioState,
    combine,
    release_ammo,
)

__all__ = [
    # v1 兼容
    "SignalState", "zone_of", "core_position", "update_ammo", "ammo_position",
    "target_position", "apply_extremes", "apply_extreme_fear", "throttle_ok",
    "clip_adjustment",
    # v2 单市场
    "MarketState", "MarketOutput", "market_core", "market_target",
    "trend_factor_series", "layer_cap_position", "greed_tier_factor",
    # v2 组合级
    "PortfolioState", "release_ammo", "combine",
    # 子模块
    "legacy", "market_signal", "portfolio",
]
```

- [ ] **Step 4: 跑 v1 全量测试确认零回归（本 Task 的核心验收）**

Run: `python -m pytest tests/ -q`
Expected: `197 passed`（172 + 25 + 兼容测试）

**若有任何 v1 测试失败**：说明兼容层没做到位。**不要改 v1 测试**——改 `__init__.py` 的导出。

- [ ] **Step 5: 单独确认 v1 的 signal 测试全通过**

Run: `python -m pytest tests/test_signal.py -v`
Expected: PASS（v1 全部原有断言）

- [ ] **Step 6: 提交**

```bash
git add -A fg_system/signal/ fg_system/signal.py tests/signal/
git commit -m "refactor(signal): 拆分为包并保留 v1 兼容层 + 等价性回归测试" # user-confirmed-commit
```

---

## Task 11: 管道层编排（加密市场 + 组合级）

**Files:**
- Modify: `fg_system/pipeline.py`
- Modify: `fg_system/config.py`（新增 `PORTFOLIO_FEATURES_PATH`）
- Test: `tests/test_pipeline_crypto.py`

**接口约定**：
- `run_crypto(raw_dir=None, write=True)` → 加密市场的 features（含三层目标仓位）
- `run_portfolio(us_features, crypto_features, write=True)` → 组合级目标仓位
- `instruction_card_v2(portfolio_out, us_out, crypto_out, current_position=None)` → 指令卡

- [ ] **Step 1: 在 config.py 追加路径常量**

```python
PORTFOLIO_FEATURES_PATH = os.path.join(DATA_DIR, "portfolio_features.csv")
```

- [ ] **Step 2: 写失败的测试**

```python
# tests/test_pipeline_crypto.py
# -*- coding: utf-8 -*-
"""加密管道与组合管道测试。"""
import numpy as np
import pandas as pd
import pytest

from fg_system import config
from fg_system import pipeline


def test_drawdown_series_crypto_uses_btc():
    """加密回撤基准必须是 BTC 现货，不是 BITX（§6.4）。"""
    idx = pd.bdate_range("2024-01-01", periods=300)
    btc = pd.Series(np.linspace(100000, 50000, 300), index=idx)
    wide = pd.DataFrame({("BTC", "close"): btc})
    dd = pipeline.crypto_drawdown_series(wide)
    assert dd.dropna().iloc[-1] > 0.4


def test_drawdown_series_crypto_nan_during_warmup():
    idx = pd.bdate_range("2024-01-01", periods=300)
    btc = pd.Series(np.linspace(100000, 50000, 300), index=idx)
    wide = pd.DataFrame({("BTC", "close"): btc})
    dd = pipeline.crypto_drawdown_series(wide)
    # 252 日窗口前必须 NaN
    assert dd.iloc[:251].isna().all()


def test_crypto_trend_series_uses_btc():
    idx = pd.bdate_range("2020-01-01", periods=300)
    btc = pd.Series(np.linspace(200000, 50000, 300), index=idx)
    wide = pd.DataFrame({("BTC", "close"): btc})
    tf = pipeline.crypto_trend_series(wide)
    assert tf.iloc[-1] == pytest.approx(config.TREND_FILTER_FACTOR)


def test_equity_trend_series_uses_qqq():
    idx = pd.bdate_range("2020-01-01", periods=300)
    qqq = pd.Series(np.linspace(500, 200, 300), index=idx)
    wide = pd.DataFrame({("QQQ", "close"): qqq})
    tf = pipeline.equity_trend_series(wide)
    assert tf.iloc[-1] == pytest.approx(config.TREND_FILTER_FACTOR)


def test_run_portfolio_shifts_target_position():
    """§10.3：喂给回测前必须整体 shift(1)。"""
    idx = pd.bdate_range("2024-01-01", periods=5)
    us = pd.DataFrame({
        "fg_index": [10.0] * 5, "drawdown": [0.0] * 5, "trend": [1.0] * 5,
    }, index=idx)
    cr = pd.DataFrame({
        "crypto_fg_index": [10.0] * 5, "drawdown": [0.0] * 5, "trend": [1.0] * 5,
    }, index=idx)
    out = pipeline.run_portfolio(us, cr, write=False)
    # 第 0 行应为 NaN（shift 后）
    assert pd.isna(out["target_position"].iloc[0])
    # 第 1 行 = 大盘满仓核心仓 + 加密满仓核心仓
    expected = (config.CORE_CAP * config.MARKET_CORE_RATIO["us_equity"]
                + config.CORE_CAP * config.MARKET_CORE_RATIO["crypto"])
    assert out["target_position"].iloc[1] == pytest.approx(expected)


def test_run_portfolio_marks_warmup():
    idx = pd.bdate_range("2024-01-01", periods=3)
    us = pd.DataFrame({
        "fg_index": [np.nan, 10.0, 10.0], "drawdown": [0.0] * 3, "trend": [1.0] * 3,
    }, index=idx)
    cr = pd.DataFrame({
        "crypto_fg_index": [np.nan, 10.0, 10.0], "drawdown": [0.0] * 3,
        "trend": [1.0] * 3,
    }, index=idx)
    out = pipeline.run_portfolio(us, cr, write=False)
    assert bool(out["warmup"].iloc[0]) is True


def test_run_portfolio_handles_partial_market():
    """一个市场 warmup 时，组合只用另一个市场。"""
    idx = pd.bdate_range("2024-01-01", periods=3)
    us = pd.DataFrame({
        "fg_index": [np.nan] * 3, "drawdown": [0.0] * 3, "trend": [1.0] * 3,
    }, index=idx)
    cr = pd.DataFrame({
        "crypto_fg_index": [10.0] * 3, "drawdown": [0.0] * 3, "trend": [1.0] * 3,
    }, index=idx)
    out = pipeline.run_portfolio(us, cr, write=False)
    expected = config.CORE_CAP * config.MARKET_CORE_RATIO["crypto"]
    assert out["core_position"].iloc[0] == pytest.approx(expected)


def test_run_portfolio_keeps_state_across_days():
    """回归：熔断/档位状态必须跨日保持，不能在循环内重置。

    构造：大盘指数先触发极贪熔断（>=85），之后回落到 70（熔断维持但未解锁）。
    若状态在循环内被重置，第 2 天会退回正常五档仓位（0.49），
    正确实现应维持熔断底仓（0.49 × 0.25）。
    """
    idx = pd.bdate_range("2024-01-01", periods=3)
    us = pd.DataFrame({
        "fg_index": [90.0, 70.0, 70.0], "drawdown": [0.0] * 3, "trend": [1.0] * 3,
    }, index=idx)
    cr = pd.DataFrame({
        "crypto_fg_index": [np.nan] * 3, "drawdown": [0.0] * 3, "trend": [1.0] * 3,
    }, index=idx)
    out = pipeline.run_portfolio(us, cr, write=False)
    full = config.CORE_CAP * config.MARKET_CORE_RATIO["us_equity"]
    # 第 1 天（索引 1）应处于熔断底仓，而非正常五档仓位
    assert out["us_core"].iloc[1] == pytest.approx(full * config.EXTREME_GREED_FLOOR)
    assert out["us_core"].iloc[1] < full
```

同时在 `tests/test_pipeline_crypto.py` 顶部确认已导入 `config`；若未导入，补上：

```python
from fg_system import config
```

- [ ] **Step 3: 跑测试确认失败**

Run: `python -m pytest tests/test_pipeline_crypto.py -v`
Expected: FAIL — `AttributeError: module 'fg_system.pipeline' has no attribute 'crypto_drawdown_series'`

- [ ] **Step 4: 实现管道扩展**

在 `fg_system/pipeline.py` 的 import 区追加：

```python
from fg_system.signal import market_signal as ms_mod
from fg_system.signal import portfolio as pf_mod
```

在文件末尾追加：

```python
# ================================================================ v2 加密与组合管道


def crypto_drawdown_series(wide, lookback=None):
    """加密回撤基准：**BTC 现货**的滚动 52 周最高（§6.4）。

    必须用 BTC 现货而非 BITX——杠杆 ETF 自身回撤含损耗，长期会"自然"触发，
    与市场情绪无关（v1 §4.5 约束 2 的同一条理由）。
    """
    lookback = lookback or config.DRAWDOWN_LOOKBACK
    btc = wide[("BTC", "close")]
    peak = btc.rolling(lookback, min_periods=lookback).max()
    return 1.0 - btc / peak


def crypto_trend_series(wide):
    """加密趋势系数：BTC 现货相对其 200 日均线（§6.1）。"""
    return ms_mod.trend_factor_series(wide[("BTC", "close")])


def equity_trend_series(wide):
    """大盘趋势系数：QQQ 相对其 200 日均线（§6.1）。"""
    return ms_mod.trend_factor_series(wide[("QQQ", "close")])


def run_crypto(raw_dir=None, write=True):
    """执行加密市场全链路，返回 crypto_features（index = 日期）。

    输出的列：crypto_fg_index / zone / core_position / trend / trend_blocked /
    layer_btc_beta / layer_stock_high_beta / layer_stock_ops_beta / drawdown /
    greed_tier / target_position / warmup + 两个因子分。
    """
    from fg_system.data import loader

    raw_dir = raw_dir or config.RAW_DIR
    wide = loader.to_crypto_wide(raw_dir)
    loader.check_crypto_anomalies(
        pd.read_csv(config.CRYPTO_PRICES_PATH, dtype={"symbol": str}, parse_dates=["date"]))

    scores = index_mod.factor_scores(wide, market="crypto")
    fg_index = index_mod.build_index(scores, market="crypto")
    dd = crypto_drawdown_series(wide)
    trend = crypto_trend_series(wide)

    rows = []
    state = ms_mod.MarketState(market="crypto")
    for dt in wide.index:
        idx_val = fg_index.get(dt, np.nan)
        out, state = ms_mod.market_target(
            index_value=idx_val,
            drawdown=dd.get(dt, np.nan),
            trend=trend.get(dt, 1.0),
            state=state,
            market="crypto",
            date=dt.strftime("%Y-%m-%d"),
        )
        rows.append({
            "date": dt,
            "crypto_fg_index": idx_val,
            "zone": (ms_mod.zone_of(idx_val)
                     if not (idx_val is None or (isinstance(idx_val, float) and np.isnan(idx_val)))
                     else np.nan),
            "core_position": out.core_position,
            "trend": out.trend,
            "trend_blocked": out.trend_blocked,
            "layer_btc_beta": out.layer_caps.get("btc_beta"),
            "layer_stock_high_beta": out.layer_caps.get("stock_high_beta"),
            "layer_stock_ops_beta": out.layer_caps.get("stock_ops_beta"),
            "drawdown": dd.get(dt, np.nan),
            "greed_tier": state.greed_tier,
            "extreme": out.extreme,
            "note": out.note,
            **{k: scores[k].get(dt, np.nan) for k in scores.columns},
        })

    out_df = pd.DataFrame(rows).set_index("date").sort_index()
    # 单市场目标仓位（供 run_portfolio 消费），同样 shift(1)
    out_df["target_position"] = out_df["core_position"].shift(1)
    out_df["warmup"] = out_df["crypto_fg_index"].isna()

    if write:
        os.makedirs(os.path.dirname(config.CRYPTO_FEATURES_PATH), exist_ok=True)
        out_df.to_csv(config.CRYPTO_FEATURES_PATH, encoding="utf-8")
        with open(config.CRYPTO_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state.to_dict(), f, ensure_ascii=False, indent=2)
    return out_df


def run_equity_v2(raw_dir=None):
    """大盘 features + 趋势列。

    **为什么不直接改 v1 的 `run()`**：v1 的 run() 输出已被 127 个测试锁定，
    加列虽看似无害，但任何对已验收代码的改动都是纯风险。本函数调用 v1 的 run()
    再**追加**趋势列，v1 路径零改动。
    """
    us = run(raw_dir=raw_dir, write=False)
    wide = load_wide(raw_dir)
    trend = equity_trend_series(wide).reindex(us.index).fillna(1.0)
    us["trend"] = trend
    us["trend_blocked"] = trend < 1.0
    return us


def run_portfolio(us_features, crypto_features, write=True):
    """组合级管道：把两个市场的核心仓与共享弹药池合成最终目标仓位（§7）。

    入参是两个市场的 features DataFrame（**未 shift**）。us_features 必须含
    `trend` / `trend_blocked` 列（由 `run_equity_v2` 产出）。

    返回 portfolio_features（target_position 已 shift(1)）。
    """
    us = us_features.copy()
    cr = crypto_features.copy()

    # 对齐到两市场共同交易日（大盘日历为主）
    joined = us.join(cr, how="left", lsuffix="_us", rsuffix="_cr")

    rows = []
    state = pf_mod.PortfolioState()
    # **状态必须建在循环外**：熔断解锁、极贪档位、极恐冷却是跨日状态机，
    # 建在循环内会每轮重置，状态机完全失效（这是 v1 已踩过的同类坑）。
    us_state = ms_mod.MarketState(market="us_equity")
    cr_state = ms_mod.MarketState(market="crypto")

    for dt in joined.index:
        date_str = dt.strftime("%Y-%m-%d")
        row = joined.loc[dt]
        idx_us = row.get("fg_index", np.nan)
        idx_cr = row.get("crypto_fg_index", np.nan)
        dd_us = row.get("drawdown_us", np.nan)
        dd_cr = row.get("drawdown_cr", np.nan)
        tr_us = row.get("trend_us", 1.0)
        tr_cr = row.get("trend_cr", 1.0)
        tr_us = 1.0 if pd.isna(tr_us) else tr_us
        tr_cr = 1.0 if pd.isna(tr_cr) else tr_cr

        # 必须接收新状态（熔断/档位是跨日状态机）
        out_us, us_state = ms_mod.market_target(
            idx_us, dd_us, tr_us, us_state, "us_equity", date_str)
        out_cr, cr_state = ms_mod.market_target(
            idx_cr, dd_cr, tr_cr, cr_state, "crypto", date_str)

        state, _, ammo_note = pf_mod.release_ammo(state, [out_us, out_cr])
        state, _, fear_note = pf_mod.apply_extreme_fear(
            state, [out_us, out_cr], date_str)

        target, _ = pf_mod.combine([out_us, out_cr], state)
        cores = [o.core_position for o in (out_us, out_cr) if o.core_position is not None]

        rows.append({
            "date": dt,
            "core_position": sum(cores) if cores else np.nan,
            "ammo_position": pf_mod.ammo_position(state),
            "target_position": target,
            "ammo_released": len(state.ammo_released),
            "us_core": out_us.core_position,
            "crypto_core": out_cr.core_position,
            "trend_blocked_us": out_us.trend_blocked,
            "trend_blocked_crypto": out_cr.trend_blocked,
            "extreme": bool(out_us.extreme or out_cr.extreme),
            "note": " | ".join(
                x for x in (ammo_note, fear_note, out_us.note, out_cr.note) if x),
        })

    out = pd.DataFrame(rows).set_index("date").sort_index()
    # §10.3：喂给 backtrader 前整体 shift(1)
    out["target_position"] = out["target_position"].shift(1)
    out["warmup"] = out["core_position"].isna()

    if write:
        os.makedirs(os.path.dirname(config.PORTFOLIO_FEATURES_PATH), exist_ok=True)
        out.to_csv(config.PORTFOLIO_FEATURES_PATH, encoding="utf-8")
        with open(config.STATE_PATH, "w", encoding="utf-8") as f:
            json.dump({"portfolio": state.to_dict(),
                       "us_equity": us_state.to_dict(),
                       "crypto": cr_state.to_dict()},
                      f, ensure_ascii=False, indent=2)
    return out
```

**注意**：`run_portfolio` 依赖 `us_features` 含 `trend_us` 列。当两个 DataFrame
用 `lsuffix="_us"` / `rsuffix="_cr"` 连接时，大盘的 `trend` 变成 `trend_us`、
加密的 `trend` 变成 `trend_cr`——上面的 `row.get("trend_us")` 与 `row.get("trend_cr")`
正是取这两个名字。

- [ ] **Step 5: 跑测试确认通过**

Run: `python -m pytest tests/test_pipeline_crypto.py -v`
Expected: PASS（全部 7 个）

- [ ] **Step 6: 跑全量测试 + 端到端冒烟**

Run:
```bash
python -m pytest tests/ -q
python -c "
from fg_system import pipeline
cr = pipeline.run_crypto()
print('加密 features:', cr.shape, '有效信号:', int(cr['crypto_fg_index'].notna().sum()))
"
```
Expected: 测试全通过；加密 features 形状约为 `(2500, 12)`，有效信号数 > 0（合成轨/BTC 起点决定）。

- [ ] **Step 7: 提交**

```bash
git add fg_system/pipeline.py fg_system/config.py tests/test_pipeline_crypto.py
git commit -m "feat(pipeline): 加密市场与组合级管道" # user-confirmed-commit
```

---

## Task 12: 趋势过滤贡献度归因

**为什么必须做**（§8.4）：趋势过滤是 v2 的核心改动，但**它可能无效**。设计文档 §12 风险 7 明确写了：若贡献度接近零，说明修正无效，应回到验收报告的选项 A（降低核心仓上限）。**没有这个归因表，就无法判断该改动是否值得保留。**

**Files:**
- Create: `fg_system/backtest/attribution.py`
- Test: `tests/backtest/test_attribution.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/backtest/test_attribution.py
# -*- coding: utf-8 -*-
"""趋势过滤贡献度归因测试。"""
import numpy as np
import pandas as pd
import pytest

from fg_system.backtest import attribution


def _features(targets, trend_blocked, index=100.0):
    idx = pd.bdate_range("2024-01-01", periods=len(targets))
    return pd.DataFrame({
        "target_position": targets,
        "trend_blocked": trend_blocked,
        "fg_index": [index] * len(targets),
    }, index=idx)


def test_without_trend_removes_discount():
    """关闭趋势过滤 = 把 trend_blocked 处的仓位还原为未打折值。"""
    f = _features([0.49, 0.245, 0.245], [False, True, True])
    out = attribution.without_trend(f)
    assert out["target_position"].iloc[0] == pytest.approx(0.49)
    # 打折值 0.245 → 还原为 0.49
    assert out["target_position"].iloc[1] == pytest.approx(0.49)


def test_without_trend_leaves_unblocked_rows_unchanged():
    f = _features([0.49, 0.30], [False, False])
    out = attribution.without_trend(f)
    assert out["target_position"].iloc[1] == pytest.approx(0.30)


def test_contribution_table_columns():
    f = _features([0.49, 0.245, 0.49, 0.245], [False, True, False, True])
    prices = pd.Series([100.0, 102.0, 104.0, 106.0], index=f.index)
    table = attribution.contribution_table(f, prices)
    for col in ["with_trend_return", "without_trend_return",
                "return_delta", "blocked_days", "blocked_ratio"]:
        assert col in table.columns


def test_contribution_reports_blocked_days():
    f = _features([0.49] * 4, [False, True, True, False])
    prices = pd.Series([100.0] * 4, index=f.index)
    table = attribution.contribution_table(f, prices)
    assert table["blocked_days"].iloc[0] == 2


def test_contribution_zero_delta_when_never_blocked():
    """从未触发趋势过滤时，两条路径收益必须完全相同。"""
    f = _features([0.49, 0.49, 0.49], [False, False, False])
    prices = pd.Series([100.0, 105.0, 110.0], index=f.index)
    table = attribution.contribution_table(f, prices)
    assert table["return_delta"].iloc[0] == pytest.approx(0.0, abs=1e-9)


def test_contribution_positive_delta_when_trend_avoids_loss():
    """趋势过滤避开下跌时，带过滤的收益应高于不带过滤。"""
    idx = pd.bdate_range("2024-01-01", periods=4)
    f = pd.DataFrame({
        "target_position": [0.49, 0.49, 0.245, 0.245],
        "trend_blocked": [False, False, True, True],
        "fg_index": [10.0] * 4,
    }, index=idx)
    prices = pd.Series([100.0, 100.0, 90.0, 80.0], index=idx)
    table = attribution.contribution_table(f, prices)
    assert table["return_delta"].iloc[0] > 0


def test_verdict_flags_ineffective_when_delta_small():
    """贡献度接近零时必须给出「无效」判定（§12 风险 7）。"""
    idx = pd.bdate_range("2024-01-01", periods=3)
    f = pd.DataFrame({
        "target_position": [0.49, 0.49, 0.49],
        "trend_blocked": [False, False, False],
        "fg_index": [50.0] * 3,
    }, index=idx)
    prices = pd.Series([100.0, 101.0, 102.0], index=idx)
    table = attribution.contribution_table(f, prices)
    assert attribution.verdict(table)["effective"] is False


def test_verdict_flags_effective_when_delta_large():
    idx = pd.bdate_range("2024-01-01", periods=4)
    f = pd.DataFrame({
        "target_position": [0.49, 0.49, 0.245, 0.245],
        "trend_blocked": [False, False, True, True],
        "fg_index": [10.0] * 4,
    }, index=idx)
    prices = pd.Series([100.0, 100.0, 80.0, 60.0], index=idx)
    table = attribution.contribution_table(f, prices)
    assert attribution.verdict(table)["effective"] is True
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/backtest/test_attribution.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fg_system.backtest.attribution'`

- [ ] **Step 3: 实现归因模块**

```python
# fg_system/backtest/attribution.py
# -*- coding: utf-8 -*-
"""趋势过滤贡献度归因（§8.4）。

目的：量化 v2 核心改动（趋势过滤）的实际价值。设计文档 §12 风险 7 明确：
**若贡献度接近零，说明修正无效，应回到验收报告的选项 A（降低核心仓上限），
而不是继续调趋势过滤的参数。**

做法：把 features 的 target_position 在「趋势过滤生效」处还原为未打折值，
得到一条「不带趋势过滤」的对照仓位序列，两条路径都按同一价格序列算收益。
"""
import numpy as np
import pandas as pd

from fg_system import config


def without_trend(features):
    """构造「关闭趋势过滤」的对照 features。

    在 trend_blocked=True 处，把 target_position 除以 TREND_FILTER_FACTOR
    还原为未打折值（上限 1.0）。
    """
    out = features.copy()
    blocked = out["trend_blocked"].fillna(False).astype(bool)
    restored = out["target_position"] / config.TREND_FILTER_FACTOR
    out.loc[blocked, "target_position"] = restored[blocked].clip(upper=1.0)
    return out


def _path_return(targets, prices):
    """按目标仓位持有，计算累计收益。

    简化口径：以「目标仓位 × 标的日收益」累乘。这里不引入 backtrader——
    归因的目的是**比较两条路径的差异**，不是模拟真实撮合；用同一套简化口径
    比较才公平（撮合成本在两条路径上相同，会在差分中抵消）。
    """
    ret = prices.pct_change().fillna(0.0)
    pos = targets.shift(1).fillna(0.0)     # T 日仓位在 T 日生效需再 shift
    strat_ret = pos * ret
    return float((1.0 + strat_ret).prod() - 1.0)


def contribution_table(features, prices):
    """趋势过滤贡献度表。返回单行 DataFrame。"""
    with_trend = features["target_position"]
    without = without_trend(features)["target_position"]
    prices = prices.reindex(features.index)

    r_with = _path_return(with_trend, prices)
    r_without = _path_return(without, prices)

    blocked = features["trend_blocked"].fillna(False).astype(bool)
    return pd.DataFrame([{
        "with_trend_return": r_with,
        "without_trend_return": r_without,
        "return_delta": r_with - r_without,
        "blocked_days": int(blocked.sum()),
        "blocked_ratio": float(blocked.mean()) if len(blocked) else 0.0,
    }])


def verdict(table, min_delta=0.02):
    """判定趋势过滤是否有效（§12 风险 7）。

    min_delta 是「有效」的最低累计收益改善（默认 2 个百分点）。
    低于此值 → effective=False，并给出应回退到「降低核心仓上限」的建议。
    """
    delta = float(table["return_delta"].iloc[0])
    blocked_days = int(table["blocked_days"].iloc[0])
    effective = abs(delta) >= min_delta and blocked_days > 0
    if blocked_days == 0:
        reason = "趋势过滤从未触发（blocked_days=0），本次回测无法评估其价值"
    elif not effective:
        reason = ("趋势过滤贡献度 %.2f%% < 阈值 %.2f%%，修正无效 → "
                  "应回到验收报告选项 A（降低核心仓上限），不要继续调趋势参数"
                  % (delta * 100, min_delta * 100))
    else:
        reason = "趋势过滤贡献度 %.2f%%，有效" % (delta * 100)
    return {"effective": effective, "delta": delta,
            "blocked_days": blocked_days, "reason": reason}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/backtest/test_attribution.py -v`
Expected: PASS（全部 8 个）

- [ ] **Step 5: 用真实数据出归因表**

Run:
```bash
python -c "
import pandas as pd
from fg_system import config, pipeline
from fg_system.backtest import attribution
us = pipeline.run(write=False)
px = pd.read_csv(config.RAW_DIR + '/prices.csv', dtype={'symbol': str}, parse_dates=['date'])
qqq = px[px['symbol']=='QQQ'].set_index('date')['close'].sort_index()
t = attribution.contribution_table(us, qqq)
print(t.to_string(index=False))
print(attribution.verdict(t))
"
```
Expected: 打印贡献度表与判定。**若 `effective=False`，不要调趋势参数——按设计文档 §12 风险 7 回到选项 A（降低核心仓上限），并在回测报告中记录该结论。**

- [ ] **Step 6: 提交**

```bash
git add fg_system/backtest/attribution.py tests/backtest/test_attribution.py
git commit -m "feat(backtest): 趋势过滤贡献度归因" # user-confirmed-commit
```

---

## Task 12B: 加密双轨回测与组合评估

**设计依据**（§8.1–8.4）：加密走**合成 + 真实双轨**；组合级必须输出两市场相关性（§12 风险 8：若危机期相关性 > 0.7，统一资金池的合理性需重新评估）。

**Files:**
- Create: `fg_system/backtest/crypto_runner.py`
- Test: `tests/backtest/test_crypto_runner.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/backtest/test_crypto_runner.py
# -*- coding: utf-8 -*-
"""加密双轨回测测试。"""
import numpy as np
import pandas as pd
import pytest

from fg_system.backtest import crypto_runner


def _prices(symbols, n=300, start="2024-01-01", trend=0.001):
    idx = pd.bdate_range(start, periods=n)
    frames = []
    for i, s in enumerate(symbols):
        close = 100.0 * (1 + trend) ** np.arange(n)
        frames.append(pd.DataFrame({
            "date": idx, "symbol": s, "open": close, "high": close,
            "low": close, "close": close, "volume": 1.0,
        }))
    return pd.concat(frames, ignore_index=True)


def test_track_labels_are_distinct():
    assert crypto_runner.TRACK_SYNTHETIC == "synthetic"
    assert crypto_runner.TRACK_REAL == "real"


def test_metrics_for_synthetic_track():
    prices = _prices(["BITX"])
    m = crypto_runner.track_metrics(prices, "BITX", track="synthetic")
    assert "annual_return" in m and "max_drawdown" in m


def test_result_carries_track_label():
    """结果必须带轨标签——防止合成轨数字被当成真实预期（§4.2）。"""
    prices = _prices(["BITX"])
    res = crypto_runner.evaluate_symbol(prices, "BITX", track="synthetic")
    assert res["track"] == "synthetic"


def test_cross_market_correlation_returns_float():
    us = _prices(["TQQQ"], n=200).set_index("date")["close"]
    cr = _prices(["BITX"], n=200).set_index("date")["close"]
    r = crypto_runner.cross_market_correlation(us, cr)
    assert isinstance(r, float)


def test_cross_market_correlation_nan_when_too_few_points():
    us = pd.Series([1.0, 2.0], index=pd.bdate_range("2024-01-01", periods=2))
    cr = pd.Series([1.0, 2.0], index=pd.bdate_range("2024-01-01", periods=2))
    assert np.isnan(crypto_runner.cross_market_correlation(us, cr))


def test_crisis_correlation_flags_high_risk():
    """危机期相关性 > 0.7 时必须告警（§12 风险 8）。"""
    idx = pd.bdate_range("2024-01-01", periods=100)
    rng = np.random.default_rng(7)
    base = pd.Series(rng.normal(0, 0.02, 100), index=idx)
    us = pd.Series((1 + base).cumprod().values * 100, index=idx)
    cr = pd.Series((1 + base * 1.5).cumprod().values * 100, index=idx)
    out = crypto_runner.crisis_correlation(us, cr, threshold=0.7)
    assert out["correlation"] > 0.7
    assert out["warning"] is True


def test_layer_contribution_sums_to_total():
    prices = _prices(["BITX", "MSTX", "CONL"])
    table = crypto_runner.layer_contribution(prices)
    assert set(table["layer"]) == {"btc_beta", "stock_high_beta", "stock_ops_beta"}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/backtest/test_crypto_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fg_system.backtest.crypto_runner'`

- [ ] **Step 3: 实现双轨回测**

```python
# fg_system/backtest/crypto_runner.py
# -*- coding: utf-8 -*-
"""加密双轨回测与组合评估（§8.1–8.4）。

**双轨的定位（必须在所有输出中保持）**：
  - 合成轨：验证**策略逻辑**（五档/趋势过滤/弹药档位在完整加密周期中的行为）
  - 真实轨：验证**产品损耗**与合成质量门

任何基于合成轨的收益数字都必须带 `track="synthetic"` 标签，禁止与真实轨混淆。
"""
import numpy as np
import pandas as pd

from fg_system import config
from fg_system.backtest.runner import performance_metrics

TRACK_SYNTHETIC = "synthetic"
TRACK_REAL = "real"


def _price_series(prices, symbol):
    return (prices[prices["symbol"] == symbol]
            .set_index("date")["close"].sort_index())


def track_metrics(prices, symbol, track=TRACK_SYNTHETIC):
    """单标的买入持有的指标（作为该轨的基准）。"""
    s = _price_series(prices, symbol)
    if s.empty:
        return {"track": track, "symbol": symbol, "annual_return": float("nan"),
                "max_drawdown": float("nan")}
    m = performance_metrics(s.pct_change().dropna())
    m["track"] = track
    m["symbol"] = symbol
    return m


def evaluate_symbol(prices, symbol, track=TRACK_SYNTHETIC):
    """评估单个加密标的。返回结果字典（含 track 标签）。"""
    return {
        "symbol": symbol,
        "track": track,
        "buy_and_hold": track_metrics(prices, symbol, track),
    }


def cross_market_correlation(us_close, crypto_close, min_points=60):
    """两市场日收益相关性（§12 风险 8）。"""
    joined = pd.concat(
        [us_close.pct_change().rename("us"), crypto_close.pct_change().rename("cr")],
        axis=1).dropna()
    if len(joined) < min_points:
        return float("nan")
    return float(joined["us"].corr(joined["cr"]))


def crisis_correlation(us_close, crypto_close, threshold=0.7, window=60):
    """危机期（滚动窗口内两市场同时下跌）的相关性 + 告警。

    取「两市场滚动收益都为负」的区间计算相关性——这是统一资金池最危险的场景：
    一个市场崩盘会同时拖累另一个的仓位。
    """
    joined = pd.concat(
        [us_close.pct_change().rename("us"), crypto_close.pct_change().rename("cr")],
        axis=1).dropna()
    if len(joined) < window:
        return {"correlation": float("nan"), "warning": False,
                "reason": "样本不足 %d 个交易日" % window}

    us_roll = joined["us"].rolling(window).sum()
    cr_roll = joined["cr"].rolling(window).sum()
    mask = (us_roll < 0) & (cr_roll < 0)
    subset = joined[mask]
    if len(subset) < 30:
        return {"correlation": float("nan"), "warning": False,
                "reason": "两市场同时下跌的区间不足 30 天，无法评估"}

    corr = float(subset["us"].corr(subset["cr"]))
    warn = corr > threshold
    return {
        "correlation": corr,
        "warning": warn,
        "reason": ("危机期相关性 %.2f > %.2f，统一资金池存在隐性集中风险，"
                   "需重新评估（§12 风险 8）" % (corr, threshold)) if warn
        else "危机期相关性 %.2f，在可接受范围" % corr,
    }


def layer_contribution(prices):
    """加密三层的收益贡献（§8.4）。"""
    rows = []
    for layer, symbols in config.CRYPTO_SYMBOLS.items():
        for sym in symbols:
            s = _price_series(prices, sym)
            if s.empty:
                continue
            m = performance_metrics(s.pct_change().dropna())
            rows.append({
                "layer": layer, "symbol": sym,
                "annual_return": m["annual_return"],
                "max_drawdown": m["max_drawdown"],
                "cap": config.CRYPTO_LAYER_CAP[layer],
            })
    if not rows:
        return pd.DataFrame(columns=["layer", "symbol", "annual_return",
                                     "max_drawdown", "cap"])
    return pd.DataFrame(rows)


def report(synthetic_path=None, real_path=None, us_features=None):
    """生成加密双轨评估报告（§8.4）。"""
    synthetic_path = synthetic_path or config.SYNTHETIC_PATH
    real_path = real_path or config.CRYPTO_PRICES_PATH

    out = {"synthetic": None, "real": None}

    if os.path.exists(synthetic_path):
        syn = pd.read_csv(synthetic_path, dtype={"symbol": str}, parse_dates=["date"])
        out["synthetic"] = [evaluate_symbol(syn, s, TRACK_SYNTHETIC)
                            for s in config.CRYPTO_FLAT_SYMBOLS
                            if not _price_series(syn, s).empty]

    if os.path.exists(real_path):
        real = pd.read_csv(real_path, dtype={"symbol": str}, parse_dates=["date"])
        out["real"] = [evaluate_symbol(real, s, TRACK_REAL)
                       for s in config.CRYPTO_FLAT_SYMBOLS
                       if not _price_series(real, s).empty]
        out["layer_contribution"] = layer_contribution(real)

        btc = real[real["symbol"] == "BTC"]
        if btc.empty:
            btc_path = config.CRYPTO_UNDERLYING_PATH
            if os.path.exists(btc_path):
                b = pd.read_csv(btc_path, parse_dates=["date"]).set_index("date")["close"]
                out["btc_close"] = b.sort_index()

    return out
```

**注意**：文件顶部需 `import os`。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/backtest/test_crypto_runner.py -v`
Expected: PASS（全部 8 个）

- [ ] **Step 5: 用真实数据出双轨报告与相关性**

Run:
```bash
python -c "
from fg_system.backtest import crypto_runner
import pandas as pd
from fg_system import config
r = crypto_runner.report()
for track in ('synthetic','real'):
    print('===', track, '===')
    for e in (r.get(track) or []):
        print(e['symbol'], '年化 %.2f%%' % (e['buy_and_hold']['annual_return']*100),
              '回撤 %.2f%%' % (e['buy_and_hold']['max_drawdown']*100))
btc = pd.read_csv(config.CRYPTO_UNDERLYING_PATH, parse_dates=['date']).set_index('date')['close']
px = pd.read_csv(config.RAW_DIR+'/prices.csv', dtype={'symbol':str}, parse_dates=['date'])
qqq = px[px['symbol']=='QQQ'].set_index('date')['close'].sort_index()
print('两市场相关性:', crypto_runner.cross_market_correlation(qqq, btc))
print('危机期相关性:', crypto_runner.crisis_correlation(qqq, btc))
"
```
Expected: 打印双轨指标与相关性。**若危机期相关性 > 0.7，必须在验收报告里写明并评估统一资金池的合理性**（§12 风险 8）。

- [ ] **Step 6: 跑全量测试**

Run: `python -m pytest tests/ -q`
Expected: 全部通过

- [ ] **Step 7: 提交**

```bash
git add fg_system/backtest/crypto_runner.py tests/backtest/test_crypto_runner.py
git commit -m "feat(backtest): 加密双轨回测与跨市场相关性" # user-confirmed-commit
```

---

## Task 13: 仪表盘扩展（加密区块 + coinglass 对照栏）

**Files:**
- Modify: `fg_system/dashboard/report.py`
- Test: `tests/dashboard/test_report_crypto.py`

**设计依据**（§12）：新增加密区块；coinglass 数值走 v1 已有的 `external_index.csv` 人工录入机制（§10.3）。

- [ ] **Step 1: 写失败的测试**

```python
# tests/dashboard/test_report_crypto.py
# -*- coding: utf-8 -*-
"""仪表盘加密区块测试。"""
import pandas as pd
import pytest

from fg_system.dashboard import report


def _us():
    idx = pd.bdate_range("2024-01-01", periods=30)
    return pd.DataFrame({
        "fg_index": range(30), "zone": [0] * 30, "target_position": [0.4] * 30,
        "core_position": [0.4] * 30, "ammo_position": [0.0] * 30,
        "drawdown": [0.0] * 30, "circuit_breaker": [False] * 30,
        "note": [""] * 30, "trend_blocked": [False] * 30,
    }, index=idx)


def _crypto():
    idx = pd.bdate_range("2024-01-01", periods=30)
    return pd.DataFrame({
        "crypto_fg_index": range(30), "zone": [0] * 30,
        "target_position": [0.1] * 30, "core_position": [0.1] * 30,
        "layer_btc_beta": [0.1] * 30, "layer_stock_high_beta": [0.07] * 30,
        "layer_stock_ops_beta": [0.05] * 30,
        "greed_tier": [0] * 30, "trend_blocked": [False] * 30,
        "note": [""] * 30,
    }, index=idx)


def test_crypto_section_included():
    html = report.build_v2(_us(), _crypto(), write=False)
    assert "加密贪婪恐惧指数" in html


def test_crypto_layer_caps_shown():
    html = report.build_v2(_us(), _crypto(), write=False)
    assert "BTC 纯 Beta" in html
    assert "币股高 Beta" in html
    assert "币股经营 Beta" in html


def test_coinglass_reference_section_present():
    """coinglass 人工对照栏必须存在（§10.3）。"""
    html = report.build_v2(_us(), _crypto(), write=False)
    assert "coinglass" in html.lower()


def test_trend_filter_status_shown():
    html = report.build_v2(_us(), _crypto(), write=False)
    assert "趋势过滤" in html


def test_v1_build_still_works():
    """v1 的 build() 必须不受影响（回归防线）。"""
    html = report.build(_us(), write=False)
    assert isinstance(html, str) and len(html) > 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/dashboard/test_report_crypto.py -v`
Expected: FAIL — `AttributeError: module 'fg_system.dashboard.report' has no attribute 'build_v2'`

- [ ] **Step 3: 实现仪表盘扩展**

在 `fg_system/dashboard/report.py` 末尾追加（**不修改 v1 的 `build`**）：

```python
# ================================================================ v2 加密区块

def _crypto_block(crypto_features, coinglass_value=None):
    """加密子系统区块的 HTML 片段。"""
    last = crypto_features.dropna(subset=["crypto_fg_index"]).iloc[-1] \
        if crypto_features["crypto_fg_index"].notna().any() else None
    if last is None:
        return "<h2>加密贪婪恐惧指数</h2><p>无有效信号（warmup 未完成）</p>"

    tier_txt = {0: "正常", 1: "第 1 档（2/3）", 2: "第 2 档（1/3）", 3: "第 3 档（1/4）"}
    rows = [
        ("加密贪恐指数", "%.1f" % last["crypto_fg_index"]),
        ("趋势过滤", "生效（上限减半）" if last.get("trend_blocked") else "未触发"),
        ("极贪减仓档位", tier_txt.get(int(last.get("greed_tier", 0)), "—")),
        ("加密核心仓", "%.2f%%" % ((last.get("core_position") or 0) * 100)),
    ]
    layer_rows = [
        ("BTC 纯 Beta（BITX/BITU）", last.get("layer_btc_beta")),
        ("币股高 Beta（MSTX/MSTU）", last.get("layer_stock_high_beta")),
        ("币股经营 Beta（CONL）", last.get("layer_stock_ops_beta")),
    ]

    html = ["<h2>加密贪婪恐惧指数</h2>", "<table>"]
    for k, v in rows:
        html.append("<tr><td>%s</td><td>%s</td></tr>" % (k, v))
    html.append("</table>")
    html.append("<h3>分层仓位上限</h3><table>")
    for k, v in layer_rows:
        html.append("<tr><td>%s</td><td>%s</td></tr>"
                    % (k, "%.2f%%" % (v * 100) if v is not None else "—"))
    html.append("</table>")

    html.append("<h3>coinglass 人工对照</h3>")
    if coinglass_value is None:
        html.append("<p>未录入。每日从 coinglass 页面读取后填入 "
                    "<code>Data/raw/external_index.csv</code>（字段 date,value,note）。"
                    "该数值<b>不参与任何仓位计算</b>，仅用于复盘对照。</p>")
    else:
        html.append("<p>coinglass 当日值：<b>%.1f</b>（alternative.me：%.1f）</p>"
                    % (coinglass_value, last["crypto_fg_index"]))
    return "\n".join(html)


def build_v2(us_features, crypto_features, external=None, write=True):
    """v2 仪表盘：v1 全部区块 + 加密区块 + coinglass 对照。

    复用 v1 的 build() 产出大盘部分，再拼接加密区块，避免两套绘图逻辑。
    """
    base = build(us_features, external=external, write=False)
    extra = _crypto_block(crypto_features)
    html = base.replace("</body>", extra + "\n</body>")

    if write:
        import os

        from fg_system import config
        os.makedirs(config.REPORTS_DIR, exist_ok=True)
        path = os.path.join(config.REPORTS_DIR, "dashboard_v2.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        return path
    return html
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/dashboard/ -v`
Expected: PASS（v1 原有 + 5 个新增）

- [ ] **Step 5: 跑全量测试**

Run: `python -m pytest tests/ -q`
Expected: 全部通过

- [ ] **Step 6: 提交**

```bash
git add fg_system/dashboard/report.py tests/dashboard/test_report_crypto.py
git commit -m "feat(dashboard): 加密区块与 coinglass 人工对照栏" # user-confirmed-commit
```

---

## Task 14: CLI 扩展与端到端验收

**Files:**
- Modify: `fg_system/cli.py`
- Create: `docs/superpowers/plans/2026-09-21-acceptance-report-v2.md`

- [ ] **Step 1: 扩展 CLI**

在 `fg_system/cli.py` 的 `main()` 之前追加：

```python
def _cmd_crypto_pipeline(args):
    from fg_system import config, pipeline
    cr = pipeline.run_crypto()
    print(pipeline.instruction_card(cr, current_position=args.position))
    print("\n已写入：%s" % config.CRYPTO_FEATURES_PATH)


def _cmd_portfolio(args):
    from fg_system import config, pipeline
    us = pipeline.run_equity_v2()          # 含 trend 列（v1 的 run() 不含）
    cr = pipeline.run_crypto(write=True)
    out = pipeline.run_portfolio(us, cr, write=True)
    valid = out.dropna(subset=["target_position"])
    if not valid.empty:
        last = valid.iloc[-1]
        print("日期：%s" % valid.index[-1].strftime("%Y-%m-%d"))
        print("大盘核心仓：%.2f%%" % ((last["us_core"] or 0) * 100))
        print("加密核心仓：%.2f%%" % ((last["crypto_core"] or 0) * 100))
        print("弹药仓：%.2f%%（已释放 %d 批）" % (
            (last["ammo_position"] or 0) * 100, int(last["ammo_released"])))
        print("目标总仓位：%.2f%%" % ((last["target_position"] or 0) * 100))
        if last.get("note"):
            print("说明：%s" % last["note"])
    print("\n已写入：%s" % config.PORTFOLIO_FEATURES_PATH)


def _cmd_attribution(args):
    import pandas as pd
    from fg_system import config, pipeline
    from fg_system.backtest import attribution
    us = pipeline.run(write=False)
    px = pd.read_csv(config.RAW_DIR + "/prices.csv", dtype={"symbol": str},
                     parse_dates=["date"])
    qqq = px[px["symbol"] == "QQQ"].set_index("date")["close"].sort_index()
    table = attribution.contribution_table(us, qqq)
    print(table.to_string(index=False))
    v = attribution.verdict(table)
    print("\n判定：%s" % v["reason"])
```

在 `main()` 的 `sub.add_parser("audit", ...)` 之后追加：

```python
    p2 = sub.add_parser("crypto-pipeline", help="跑加密市场管道并输出指令卡")
    p2.add_argument("--position", type=float, default=None)
    p2.set_defaults(func=_cmd_crypto_pipeline)

    sub.add_parser("portfolio", help="跑组合级管道（统一资金池）").set_defaults(
        func=_cmd_portfolio)
    sub.add_parser("attribution", help="输出趋势过滤贡献度归因").set_defaults(
        func=_cmd_attribution)
```

- [ ] **Step 2: 端到端运行全部命令**

Run:
```bash
python -m fg_system.cli pipeline --position 0.5
python -m fg_system.cli crypto-pipeline --position 0.1
python -m fg_system.cli portfolio
python -m fg_system.cli attribution
python -m fg_system.cli backtest
python -m fg_system.cli report
```
Expected: 全部正常输出，无异常。记录每条命令的实际输出（写入验收报告）。

- [ ] **Step 3: 跑全量测试**

Run: `python -m pytest tests/ -q`
Expected: 全部通过（v1 的 127 个 + v2 新增全部）

- [ ] **Step 4: 写验收报告**

创建 `docs/superpowers/plans/2026-09-21-acceptance-report-v2.md`，**逐项填写实测值**：

```markdown
# 加密子系统 + 趋势过滤修正 — 验收报告（v2）

- 日期：<填写>
- 分支：`feature-fear-greed-system`
- 测试：`pytest tests/ -q` → <填写> passed

## 一、结论摘要

| 验收项 | 目标 | 实际 | 判定 |
|---|---|---|---|
| 大盘最大回撤 | ≤ -40% | <填写> | <填写> |
| 加密最大回撤 | ≤ -50% | <填写> | <填写> |
| 趋势过滤贡献度 | > 2pp 且 blocked_days > 0 | <填写> | <填写> |
| v1 回归 | 127 个测试全通过 | <填写> | <填写> |
| 合成质量门 | 各标的偏离 < 5% | <填写> | <填写> |
| 前视偏差 | 零渗入（平移 + 截断测试） | <填写> | <填写> |
| 两市场危机期相关性 | 报告值（>0.7 需重新评估统一池） | <填写> | <填写> |

## 二、趋势过滤归因（§8.4）

<粘贴 `cli attribution` 的输出>

**判定与后续动作**：<若 effective=False，写明「按 §12 风险 7 回到选项 A：降低核心仓上限」>

## 三、加密双轨结果

| 轨 | 区间 | 年化 | 最大回撤 | 说明 |
|---|---|---|---|---|
| 合成轨 | 2018-2026 | <填写> | <填写> | **仅验证策略逻辑，不代表真实预期** |
| 真实轨 | 2022-2026 | <填写> | <填写> | 用于产品损耗校验 |

## 四、共享弹药池分配日志

<粘贴 portfolio_features.csv 中 ammo_released 变化的时点与当时的市场回撤>

## 五、已知遗留问题

1. 加密 ETF 真实历史仅 2-4 年，样本外区间偏短
2. 合成序列与真实的偏离度已过质量门，但合成模型的损耗参数须定期重标定
3. `CRYPTO_SPLIT_DEVIATION_THRESHOLD` 与 `CRYPTO_EXTREME_FEAR_TRIGGER` 为实测标定值，未来市场结构变化时需重新标定
4. <其他>
```

- [ ] **Step 5: 提交**

```bash
git add fg_system/cli.py docs/superpowers/plans/2026-09-21-acceptance-report-v2.md
git commit -m "feat(cli): 加密与组合命令 + v2 验收报告" # user-confirmed-commit
```

---

## 完成标准（Definition of Done）

全部 Task 完成后，以下每一条都必须为真：

- [ ] `python -m pytest tests/ -q` 全通过，且 **v1 的 127 个测试无一被修改**
- [ ] `python -m fg_system.cli portfolio` 能输出组合目标仓位
- [ ] `python -m fg_system.cli attribution` 输出趋势过滤贡献度，且**已据其判定采取行动**
- [ ] 验收报告 `2026-09-21-acceptance-report-v2.md` 的每一项都填了**实测值**（不得留空）
- [ ] `docs/trading-discipline.md` 已同步（Task 0）
- [ ] 加密回测结论**明确标注**了「合成轨」与「真实轨」，未混淆
- [ ] 若大盘回撤目标仍未达成，报告里写明了根因与下一步（不得静默略过）
