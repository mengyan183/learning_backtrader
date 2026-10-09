# 守猪待兔「早清仓代价」实现计划（Step B · C 阶段）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 量化「守猪待兔 ≥ +60 即清仓」这条规则的代价（卖飞了多少），产出一个量级判断。

**Architecture:** 三层分离 —— ① `signal/portfolio.py` 新增 `next_position()` 纯函数，**并把 `FgStrategy` 改为调用它**（保证"分析里的规则 = 回测里的规则"）；② 新模块 `fg_system/shoutu_analysis.py` 放 `greed_episodes()` / `replay_exit_path()` 两个纯函数；③ `scripts/analyze_shoutu_greed.py` 只做 I/O 编排与出表。

**Tech Stack:** Python 3.10、pandas、numpy、pytest、backtrader（仅既有回测，不新增用法）

**设计依据:** `docs/superpowers/specs/2026-09-24-shoutu-greed-exit-cost-design.md`（已获用户批准）

**测试命令（本机）:** `py -3.10 -m pytest <path> -v`
**⚠️ 不要用裸 `python`** —— 系统 Python 3.14 缺 `backtrader`，会 3 个收集错误。

---

## 文件结构

| 文件 | 动作 | 职责 |
|---|---|---|
| `fg_system/signal/portfolio.py` | **改** | 新增 `next_position()`；`clip_adjustment` 保留不动 |
| `fg_system/backtest/strategy.py` | **改** | `FgStrategy.next()` 改为调用 `next_position()`（逻辑不变） |
| `fg_system/shoutu_analysis.py` | **新建** | `greed_episodes()` + `replay_exit_path()`，纯计算、无 I/O |
| `tests/test_shoutu_analysis.py` | **新建** | 上面两个纯函数的单测 + 与 `FgStrategy` 的一致性测试 |
| `scripts/analyze_shoutu_greed.py` | **新建** | 读数据 → 出表 → 交叉校验 |
| `docs/trading-discipline.md` | **改** | §14.5 回写结论 |

---

## Task 1: `next_position()` 纯函数 + 让 `FgStrategy` 调用它

**为什么先做这个**：它是整个分析的**正确性基石**。若分析与回测各写一套调仓逻辑，
测出来的"代价"就不是真实规则的代价（本仓库第 12.26 条⑤已有这类先例）。

**Files:**
- Modify: `fg_system/signal/portfolio.py`（在 `clip_adjustment` 之后新增）
- Modify: `fg_system/backtest/strategy.py:30-48`
- Test: `tests/test_shoutu_analysis.py`（新建）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_shoutu_analysis.py
# -*- coding: utf-8 -*-
"""守猪待兔「早清仓代价」分析的纯函数测试（Step B · C）。

设计：docs/superpowers/specs/2026-09-24-shoutu-greed-exit-cost-design.md
"""
import pytest

from fg_system import config
from fg_system.signal import portfolio


def test_next_position_clears_small_sleeve_in_one_day():
    """单标的 sleeve ≈12% ⇒ 一天清完（12pp < MAX_SINGLE_ADJUST 30pp）。"""
    assert portfolio.next_position(0.12, 0.0) == pytest.approx(0.0)


def test_next_position_needs_two_days_above_cap():
    """45% 仓位 ⇒ 单次最多 30pp ⇒ 第一天到 15%，第二天到 0%（两天清完）。

    ⚠️ 计划原文用 36%（断言第二天到 0%），与
    `test_next_position_leaves_last_ten_pp` **直接矛盾** —— 同一输入
    `next_position(0.06, 0.0)` 不可能同时等于 0.0 和 0.06；且 Task 2 的
    `replay_exit_path(t, p0=0.36) == [0.06, 0.06, 0.06]` 也证明 6% 会**留在** 6%。
    故改为 45%：它才真正体现"单日限幅 30pp ⇒ 需两天"（15% 仍 ≥ 10pp 阈值）。
    """
    p1 = portfolio.next_position(0.45, 0.0)
    assert p1 == pytest.approx(0.15)
    assert portfolio.next_position(p1, 0.0) == pytest.approx(0.0)


def test_next_position_leaves_last_ten_pp():
    """|目标 − 现状| < REBALANCE_THRESHOLD ⇒ 不动作（最后 10pp 被留下）。"""
    assert portfolio.next_position(0.06, 0.0) == pytest.approx(0.06)


def test_next_position_acts_when_diff_equals_threshold():
    """⚠️ 是 `<` 不是 `≤`：|差| 恰好等于阈值时**要动作**（与 FgStrategy 一致）。"""
    thr = config.REBALANCE_THRESHOLD
    assert portfolio.next_position(thr, 0.0) == pytest.approx(0.0)


def test_next_position_nan_target_holds():
    """目标 NaN（warmup）⇒ 不动，不得当成空仓。"""
    assert portfolio.next_position(0.30, float("nan")) == pytest.approx(0.30)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `py -3.10 -m pytest tests/test_shoutu_analysis.py -v`
Expected: FAIL —— `AttributeError: module 'fg_system.signal.portfolio' has no attribute 'next_position'`

- [ ] **Step 3: 实现**

在 `fg_system/signal/portfolio.py` 的 `clip_adjustment` **之后**追加：

```python
def next_position(current, target):
    """`FgStrategy.next()` 的**纯函数版**：目标仓位 → 本次调仓后的实际仓位。

    **这是唯一实现** —— `FgStrategy.next()` 也调它。分析与回测共用同一段逻辑，
    否则"分析里的规则 ≠ 回测里的规则"，测出来的代价不是真规则的代价。

    ⚠️ 阈值判断是 `<` 不是 `≤`：`|target - current|` **恰好等于**
    `REBALANCE_THRESHOLD` 时**要动作**（与 `FgStrategy` 原实现逐字一致）。

    ⚠️ `target` 为 NaN（warmup / 无信号）时**保持不动** —— 不得当成"空仓"，
    那会被回测误读为"策略主动空仓"，污染净值（同 `pipeline` 的约定）。
    """
    if target != target:                       # NaN
        return current
    if abs(target - current) < config.REBALANCE_THRESHOLD:
        return current
    adjusted = current + max(
        -config.MAX_SINGLE_ADJUST,
        min(config.MAX_SINGLE_ADJUST, target - current))
    return max(0.0, min(1.0, adjusted))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `py -3.10 -m pytest tests/test_shoutu_analysis.py -v`
Expected: 5 passed

- [ ] **Step 5: 把 `FgStrategy.next()` 改为调用它（逻辑不变）**

`fg_system/backtest/strategy.py` —— 把 `next()` 体替换为：

```python
    def next(self):
        if self._pending:
            return
        target = self.datas[0].target_position[0]

        # **唯一实现**在 signal 层：`portfolio.next_position`。
        # 分析脚本（scripts/analyze_shoutu_greed.py）调的是**同一个函数** ⇒
        # "分析里的规则 = 回测里的规则"是**构造保证**，不靠测试去证明等价。
        adjusted = portfolio.next_position(self.current_position, target)
        if adjusted == self.current_position:
            return

        self.order_count += 1
        self._pending = True
        self.current_position = adjusted
        self.order_target_percent(target=adjusted)
```

并把顶部 import 改为：

```python
import backtrader as bt

from fg_system import config                     # noqa: F401  （config 仍被本模块其它处引用）
from fg_system.signal import portfolio
```

> ⚠️ 若 `config` 在本模块已无其它引用，**保留 import 会触发 lint 报未使用** ⇒
> 跑一遍 `py -3.10 -m pytest tests/backtest -q` 与 lint 确认；若无引用则删掉该行。

- [ ] **Step 6: 跑全量测试确认无回归**

Run: `py -3.10 -m pytest -q`
Expected: `682 passed`（数量不变 —— 本步只重构，不新增测试）

- [ ] **Step 7: 提交**

```bash
git add fg_system/signal/portfolio.py fg_system/backtest/strategy.py tests/test_shoutu_analysis.py
git commit -m "refactor(signal): 抽出 next_position() 纯函数，FgStrategy 改为调用它"
```

---

## Task 2: `greed_episodes()` —— 找贪婪 episode

**Files:**
- Create: `fg_system/shoutu_analysis.py`
- Test: `tests/test_shoutu_analysis.py`（追加）

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_shoutu_analysis.py`：

```python
import pandas as pd

from fg_system import shoutu_analysis


def _series(pairs):
    """`{"2024-01-01": 61, ...}` → 日期索引的 Series（升序）。"""
    s = pd.Series({pd.Timestamp(k): float(v) for k, v in pairs.items()})
    return s.sort_index()


def test_greed_episodes_single_day():
    s = _series({"2024-01-01": 10, "2024-01-02": 61, "2024-01-03": 10})
    ep = shoutu_analysis.greed_episodes(s)
    assert len(ep) == 1
    assert ep.iloc[0]["start"] == pd.Timestamp("2024-01-02")
    assert ep.iloc[0]["days"] == 1
    assert ep.iloc[0]["closed"] is True or bool(ep.iloc[0]["closed"]) is True


def test_greed_episodes_contiguous_run():
    s = _series({"2024-01-01": 60, "2024-01-02": 61,
                 "2024-01-03": 70, "2024-01-04": 59})
    ep = shoutu_analysis.greed_episodes(s)
    assert len(ep) == 1
    assert ep.iloc[0]["days"] == 3          # 60 恰好等于阈值 ⇒ 算在内
    assert ep.iloc[0]["peak"] == 70.0


def test_greed_episodes_open_at_tail_is_marked_unclosed():
    """数据末尾仍在贪婪档 ⇒ closed=False（不进"全程"统计）。"""
    s = _series({"2024-01-01": 10, "2024-01-02": 61, "2024-01-03": 70})
    ep = shoutu_analysis.greed_episodes(s)
    assert bool(ep.iloc[0]["closed"]) is False


def test_greed_episodes_none():
    s = _series({"2024-01-01": 10, "2024-01-02": 20})
    assert shoutu_analysis.greed_episodes(s).empty


def test_greed_episodes_two_separate_runs():
    s = _series({"2024-01-01": 61, "2024-01-02": 10, "2024-01-03": 62})
    assert len(shoutu_analysis.greed_episodes(s)) == 2
```

- [ ] **Step 2: 跑测试确认失败**

Run: `py -3.10 -m pytest tests/test_shoutu_analysis.py -v -k greed_episodes`
Expected: FAIL —— `ModuleNotFoundError: No module named 'fg_system.shoutu_analysis'`

- [ ] **Step 3: 实现**

新建 `fg_system/shoutu_analysis.py`：

```python
# -*- coding: utf-8 -*-
"""守猪待兔「早清仓代价」分析（Step B · C 阶段）。

设计：docs/superpowers/specs/2026-09-24-shoutu-greed-exit-cost-design.md

**本模块只做纯计算**（可离线测试）：不读文件、不打印、不做 I/O。
编排（读 CSV、出表、交叉校验）在 `scripts/analyze_shoutu_greed.py`。
"""
import pandas as pd

from fg_system import config
from fg_system.signal import portfolio


def greed_episodes(series, threshold=None):
    """找出 `series` 里**进入贪婪档**的 episode（连续区间）。

    `series`：index = 日期（**升序**），值 = 守猪待兔**原值**（−100 ~ 100）。
    `threshold`：贪婪线，默认 `config.SHOUTU_GREED_LINE`（+60）。

    返回 DataFrame（每 episode 一行）：

    | 列 | 含义 |
    |---|---|
    | `start` / `end` | 进入日 / 结束日 |
    | `days` | 区间内**交易日数**（含首尾） |
    | `peak` | 区间内最大值（原值） |
    | `closed` | 是否已结束。`False` = 数据末尾仍在贪婪档（**未完成**） |

    ⚠️ 判定是 `>= threshold`（**等于算在内**），与 `ZONE_EDGES` 的
    `searchsorted(side="right")` 语义一致 —— 若这里用 `>`，边界日的档位
    会与分析外的地方对不上。
    """
    thr = config.SHOUTU_GREED_LINE if threshold is None else float(threshold)
    s = series.dropna().sort_index()
    cols = ["start", "end", "days", "peak", "closed"]
    if s.empty:
        return pd.DataFrame(columns=cols)

    in_zone = (s >= thr).to_numpy()
    idx = s.index
    rows = []
    i = 0
    n = len(in_zone)
    while i < n:
        if not in_zone[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and in_zone[j + 1]:
            j += 1
        rows.append({
            "start": idx[i],
            "end": idx[j],
            "days": j - i + 1,
            "peak": float(s.iloc[i:j + 1].max()),
            "closed": bool(j < n - 1),
        })
        i = j + 1
    return pd.DataFrame(rows, columns=cols)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `py -3.10 -m pytest tests/test_shoutu_analysis.py -v -k greed_episodes`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add fg_system/shoutu_analysis.py tests/test_shoutu_analysis.py
git commit -m "feat(shoutu): 新增 greed_episodes() —— 找贪婪档 episode（含未完成标注）"
```

---

## Task 3: `replay_exit_path()` —— 逐日状态机回放

**Files:**
- Modify: `fg_system/shoutu_analysis.py`
- Test: `tests/test_shoutu_analysis.py`（追加）

- [ ] **Step 1: 写失败测试**

```python
def test_replay_exit_path_small_sleeve_one_day():
    """12% 仓位，目标 0 ⇒ 一天到 0。"""
    t = pd.Series([0.0, 0.0], index=pd.to_datetime(["2024-01-02", "2024-01-03"]))
    path = shoutu_analysis.replay_exit_path(t, p0=0.12)
    assert list(path) == pytest.approx([0.0, 0.0])


def test_replay_exit_path_leaves_last_ten_pp():
    """36% 仓位 ⇒ 第一天 6%，之后 |0−6%| < 10pp ⇒ 停在 6%（不归零）。"""
    t = pd.Series([0.0, 0.0, 0.0], index=pd.to_datetime(
        ["2024-01-02", "2024-01-03", "2024-01-04"]))
    path = shoutu_analysis.replay_exit_path(t, p0=0.36)
    assert list(path) == pytest.approx([0.06, 0.06, 0.06])


def test_replay_exit_path_rebuys_when_target_returns():
    """⚠️ 关键：值回落后**重新买回** —— 不得冻结在 0（冻结会高估卖飞）。"""
    t = pd.Series([0.0, 0.12, 0.12], index=pd.to_datetime(
        ["2024-01-02", "2024-01-03", "2024-01-04"]))
    path = shoutu_analysis.replay_exit_path(t, p0=0.12)
    assert list(path) == pytest.approx([0.0, 0.12, 0.12])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `py -3.10 -m pytest tests/test_shoutu_analysis.py -v -k replay`
Expected: FAIL —— `AttributeError: module 'fg_system.shoutu_analysis' has no attribute 'replay_exit_path'`

- [ ] **Step 3: 实现**

追加到 `fg_system/shoutu_analysis.py`：

```python
def replay_exit_path(targets, p0):
    """逐日回放规则侧仓位路径。返回与 `targets` 同索引的实际仓位 Series。

    `targets`：每日的**目标仓位**（由 `P0 × ZONE_SATURATION[zone(值)]` 得到）。
    `p0`：起点仓位。

    ⚠️ **必须走 `portfolio.next_position`**（与 `FgStrategy` 同一个函数）——
    不得在此另写阈值/限幅逻辑。
    ⚠️ 回放覆盖**整个窗口**：目标回到非零时会**重新买回**（`next_position` 天然
    支持），不得"冻结"在清仓后的 0 仓位 —— 冻结等于假设永不买回，会高估卖飞。
    """
    out = []
    cur = float(p0)
    for t in targets:
        cur = portfolio.next_position(cur, float(t))
        out.append(cur)
    return pd.Series(out, index=targets.index, dtype=float)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `py -3.10 -m pytest tests/test_shoutu_analysis.py -v`
Expected: 13 passed

- [ ] **Step 5: 提交**

```bash
git add fg_system/shoutu_analysis.py tests/test_shoutu_analysis.py
git commit -m "feat(shoutu): 新增 replay_exit_path() —— 逐日状态机回放（含买回，不冻结）"
```

---

## Task 4: 编排脚本 `scripts/analyze_shoutu_greed.py`

**Files:**
- Create: `scripts/analyze_shoutu_greed.py`
- Test: `tests/test_analyze_shoutu_greed.py`（新建，静态守卫）

- [ ] **Step 0: 先把 `pipeline._saturation_of` 提升为公开名（分析要用它）**

`fg_system/pipeline.py` 里 `_saturation_of(values)` 是**私有**的，但它是
"值 → 档位饱和度"的**唯一实现**。分析脚本必须复用它（重写 zone 查找就是
第 12.26 条⑤那类静默分歧）。⇒ 重命名为 `saturation_of`：

```bash
# 1) 定义处与所有调用处一起改名（pipeline.py 内部 + 引用它的测试）
grep -rn "_saturation_of" fg_system tests
```

把每一处 `_saturation_of` 改为 `saturation_of`（**定义处**去掉下划线前缀，
调用处同步改）。**不要**留兼容别名 —— 两套名字正是要避免的东西。

Run: `py -3.10 -m pytest -q`
Expected: 全过（纯改名，行为不变）

```bash
git add -A && git commit -m "refactor(pipeline): _saturation_of → saturation_of（分析模块要复用它）"
```

- [ ] **Step 1: 写静态守卫测试（失败）**

> ⚠️ **本节代码已被取代，以 `tests/test_analyze_shoutu_greed.py` 为准。** 计划原稿的守卫有两处问题：
> 1. **对任意 AST 节点调 `ast.get_docstring`**（`for node in ast.walk(...)`）—— 3.10 上
>    对非 `FunctionDef`/`ClassDef`/`Module` 节点会抛 `TypeError`（实际实现已改为按节点类型过滤）。
> 2. 旧守卫把 docstring 从待检常量里**剔除**（`[s for s in lits if s not in docs]`），
>    使"把标的写进 docstring"可**绕过**守卫。
>
> 实际实现（D4a 加固后）改为**扫描全部字符串常量（含 docstring）** + **遍历 `config.SHOUTU_SYMBOLS`**，
> 并新增两条**变异验证常驻测试**（docstring 里藏标的必须被抓到）+ 一条**不误报裸词提及**的测试。
> 关键差异（实际 `tests/test_analyze_shoutu_greed.py`，行号为实测）：

```python
def _hardcoded_symbols(src):
    """返回 `src` 里**以精确相等**出现的标的名（扫描**全部** `ast.Constant` 字符串）。

    ⚠️ **不排除 docstring** —— 早期版本把 docstring 内容从待检常量里剔除
    （`[s for s in lits if s not in docs]`），使"把标的写进 docstring"可**绕过**守卫。
    现在扫描全部字符串常量（含 docstring）。

    ⚠️ 判定是**精确相等**（`s == sym`），**不是**子串匹配 —— 子串匹配会把说明文字里
    的提及（如 "TQQQ/SOXL/UPRO 作旁证"）误判成硬编码。
    """
    lits = [n.value for n in ast.walk(ast.parse(src))
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    return [sym for sym in config.SHOUTU_SYMBOLS if any(s == sym for s in lits)]


def test_script_does_not_hardcode_symbols():
    bad = _hardcoded_symbols(_src())
    assert not bad, "脚本里硬编码了标的 %s（应走 config）" % "/".join(bad)
```

（另含 `test_guard_detects_symbol_hidden_in_docstring` / `..._in_nested_docstring` /
`test_guard_does_not_flag_plaintext_mentions` 三条，见该文件。）

- [ ] **Step 2: 跑测试确认失败**

Run: `py -3.10 -m pytest tests/test_analyze_shoutu_greed.py -v`
Expected: FAIL —— `FileNotFoundError`

- [ ] **Step 3: 实现脚本**

> ⚠️ **本节代码已被取代，以 `scripts/analyze_shoutu_greed.py` 为准**（该文件已是实际实现，
> **不要**把计划里的旧稿当模板；这里也不再整段复制，以免出现"两份会漂移的副本"）。
> 计划原稿与实际实现的关键差异（实际行号为 2026-09-24 实测）：

1. **`full` 的 horizon = `days - 1`（不是 `days`）**，且 `full` = **spec §5.1 的 episode 全程**
   （不是计划的 `max(days, 120)`）。实际：

   ```python
   # spec §5.1「episode 全程」= 从进入 ≥+60 到回落 <+60；规则在事件日当天清仓、
   # 在回落日买回，且 rets[0] 被 fillna(0.0) 丢弃（两侧同丢）⇒ 离场收益只有 days-1 个。
   path, full = _pair(max(int(ep["days"]) - 1, 0))
   ```

   计划原文 `horizon = max(int(ep["days"]), max(WINDOWS))` 会让**每个** episode 至少回放 120 天
   ⇒ 列名 "full" 装的是 120 日窗口值，与按 `days` 分段（≤5/6~20/>20）**错位**。

2. **`full120` 双列**：把计划的 120 日长窗口口径另存一列以保留对照：

   ```python
   _, full120 = _pair(max(int(ep["days"]) - 1, max(WINDOWS)))
   ```

3. **`noact` 过滤**（计划没有）：`exit_ratio == 0` ⇒ 规则**从未动作**（`p0 < REBALANCE_THRESHOLD`）
   ⇒ `full` 恒为 0，混入会稀释结论。实际用 `view = ev[ev["exit_ratio"] > 0.0]` 过滤后汇总。

4. **`unclosed` 按 `closed` 过滤**（计划没有）：未完成 episode（数据末尾仍在档位 4）**不进入**
   「全程」统计。实际：

   ```python
   unclosed = ev[~ev["closed"].astype(bool)]
   ev = ev[ev["closed"].astype(bool)]
   ```

5. **`view` 主样本判据 + `_verdict` 具名常量**：判据**用主样本**（裁决③），旁证并入的全样本
   另算作**稳健性对照**。阈值提为具名常量 `GO_LONG_AVG_MIN = 0.10` / `GO_MAX_LOSS_MIN = 0.20`：

   ```python
   def _verdict(g, col="full"):
       if g.empty:
           return float("nan"), float("nan"), False
       long_avg = float(g[g["bucket"] == ">20 天"][col].mean())
       mx = float(g[col].max())
       ok = ((long_avg == long_avg and long_avg >= GO_LONG_AVG_MIN)
             or mx >= GO_MAX_LOSS_MIN)
       return long_avg, mx, ok
   ```

   （`col` 参数见下条 8：判据**两窗口并列**，`full` = 主判据、`full120` = 补充判据。）

6. **权重取「事件日」而非样本首日**（计划原稿取 `s.index[0]` 是笔误）：

   ```python
   w = float(weights.reindex([start]).ffill().bfill().iloc[0].get(sym, 1.0 / 3.0))
   ```

7. **`wide` 单次读盘复用**：`pipeline.load_wide()` 在取权重处调一次，price 交叉校验复用
   （见 Step 5）。

8. **`_forward_return` 按 `p0` 缩放（D8 bug 修复）**：持有端**必须与规则侧同规模**
   （spec §4「每 1 元持仓」）。计划/初版实现让 `d20/d60/d120` 用**原始价格收益**
   （= 100% 持仓）而规则侧是 `p0` 规模 ⇒ 差值被 `1/p0` 倍放大（`p0 ≈ 0.12` 时实测高估
   ~2.8 倍，如 TQQQ 2025-05-13 `d120 = 0.7289` vs 正确 `0.3433`）。实际：

   ```python
   def _forward_return(prices, start, days, p0):
       ...
       seg = prices.iloc[i:j + 1]
       rets = seg.pct_change().fillna(0.0)
       return float((1.0 + p0 * rets).prod() - 1.0)
   ```

   ⇒ **强不变量**：`days <= 120` 时 `d120 == full120`（同窗口、同 `p0` 规模、同
   `pct_change().fillna(0)` 约定）。守卫 = `tests/test_analyze_shoutu_greed.py`
   （`test_fixed_window_matches_full120_scale`、`test_hold_return_scales_with_p0`、
   常驻变异验证 `test_mutation_old_forward_return_breaks_invariant`）。

9. **判据两窗口并列（D7）**：`_verdict(g, col)` 带列名参数；`main()` 里对
   **主判据 `full`** 与**补充判据 `full120`** 各出一行，末尾结论为
   「主判据不建议做 A；补充判据的『单次最大卖飞 ≥ 20%』成立 ⇒ 是否做 A 交人工裁决」。
   为什么两个窗口差这么多：规则一旦清仓，120 日窗口内平均 **97.4 / 121 天（80%）仓位为 0**
   （只在档位 0 才买回）⇒ `full` 只覆盖离场期的很小一段，**结构性低估**。

- [ ] **Step 4: 跑测试确认通过**

Run: `py -3.10 -m pytest tests/test_analyze_shoutu_greed.py -v`
Expected: 5 passed（实际 `tests/test_analyze_shoutu_greed.py` 共 5 个用例：2 个基本守卫 +
2 个 docstring 变异验证 + 1 个不误报 —— 见该文件）。

- [ ] **Step 5: 跑脚本，先看数字是否合理**

Run: `py -3.10 scripts/analyze_shoutu_greed.py --main-only`
Expected: 打出事件表（TQQQ 25 / UPRO 21 / SOXL 10 行左右）+ 汇总 + 判据结论。
**人工核对**：`days` 应与 spec §2 的数一致（TQQQ 最长 37、UPRO 34、SOXL 37）。

- [ ] **Step 6: 提交**

```bash
git add scripts/analyze_shoutu_greed.py tests/test_analyze_shoutu_greed.py
git commit -m "feat(scripts): 守猪待兔早清仓代价分析脚本（事件表 + 分段汇总 + 判据）"
```

---

## Task 5: 交叉校验 `price` 列

**为什么**：A2 新增的 `price` 列此前**从未被实质使用**。这一步既校验本次结论的可信度，
也给 A2 补上端到端证据。

**Files:**
- Modify: `fg_system/shoutu_analysis.py`（新增 `price_divergence()`）
- Test: `tests/test_shoutu_analysis.py`（追加）

- [ ] **Step 1: 写失败测试**

```python
def test_price_divergence_detects_mismatch():
    a = pd.Series([10.0, 11.0], index=pd.to_datetime(["2024-01-01", "2024-01-02"]))
    b = pd.Series([10.0, 12.0], index=a.index)
    d = shoutu_analysis.price_divergence(a, b)
    assert d["n"] == 2
    assert d["max_rel"] == pytest.approx(1.0 / 12.0, rel=1e-6) or d["max_rel"] > 0.08


def test_price_divergence_identical_is_zero():
    a = pd.Series([10.0, 11.0], index=pd.to_datetime(["2024-01-01", "2024-01-02"]))
    d = shoutu_analysis.price_divergence(a, a.copy())
    assert d["max_rel"] == pytest.approx(0.0)


# ⚠️ 以下 4 条为**实施时按实际公式补充**（计划原稿只列了上面 2 条）。
# 其中 `test_price_divergence_reports_return_consistency` 的分母是
# `max(|a|,|b|)` ⇒ 恒定 2% 水平差的最大相对偏差是 **2.0/102.0**，**不是** 0.02
# （0.02 = 2/100 是手算按分母 100，与本模块公式不符）。
def test_price_divergence_reports_return_consistency():
    """⚠️ 关键：**恒定级差**（复权口径差的形态）不影响日收益。"""
    idx = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"])
    a = pd.Series([100.0, 110.0, 99.0, 108.9], index=idx)
    d = shoutu_analysis.price_divergence(a, a * 1.02)     # 恒定 2% 水平差
    assert d["max_rel"] == pytest.approx(2.0 / 102.0)
    assert d["corr_dret"] == pytest.approx(1.0)
    assert d["max_abs_dret"] == pytest.approx(0.0, abs=1e-12)


def test_price_consistency_ok_ignores_level_gap():
    """⚠️ 关键：2% 的**级差**（复权口径差）不得判失败 —— 分析只用日收益。"""
    idx = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"])
    a = pd.Series([100.0, 110.0, 99.0, 108.9], index=idx)
    assert shoutu_analysis.price_consistency_ok(
        shoutu_analysis.price_divergence(a, a * 1.02)) is True


def test_price_consistency_ok_thresholds():
    """corr 或单日收益差任一越界 ⇒ 判失败。"""
    good = {"n": 100, "corr_dret": 0.99995, "max_abs_dret": 0.0038}
    assert shoutu_analysis.price_consistency_ok(good) is True
    assert shoutu_analysis.price_consistency_ok(
        dict(good, corr_dret=0.99)) is False
    assert shoutu_analysis.price_consistency_ok(
        dict(good, max_abs_dret=0.05)) is False


def test_price_consistency_ok_insufficient_sample_is_failure():
    """⚠️ 样本不足 / NaN ⇒ **判失败**（"没查过"不等于"查过通过"）。"""
    assert shoutu_analysis.price_consistency_ok(
        {"n": 0, "corr_dret": float("nan"), "max_abs_dret": float("nan")}) is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `py -3.10 -m pytest tests/test_shoutu_analysis.py -v -k divergence`
Expected: FAIL —— `AttributeError`

- [ ] **Step 3: 实现**

追加到 `fg_system/shoutu_analysis.py`（**实际含日收益一致性键** `corr_dret` /
`max_abs_dret` / `mean_abs_dret`，以及 go 门函数 `price_consistency_ok`，见 spec 附 B）：

```python
def price_divergence(hist_price, ref_price):
    a, b = hist_price.align(ref_price, join="inner")
    ok = a.notna() & b.notna() & (a != 0) & (b != 0)
    a, b = a[ok], b[ok]
    nan = float("nan")
    if a.empty:
        return {"n": 0, "max_rel": nan, "mean_rel": nan,
                "corr_dret": nan, "max_abs_dret": nan, "mean_abs_dret": nan}
    rel = (a - b).abs() / pd.concat([a.abs(), b.abs()], axis=1).max(axis=1)
    ra = a.pct_change().dropna()
    rb = b.pct_change().dropna()
    ra, rb = ra.align(rb, join="inner")
    dr = (ra - rb).abs()
    corr = float(ra.corr(rb)) if len(dr) >= 2 else nan
    return {"n": int(len(a)),
            "max_rel": float(rel.max()), "mean_rel": float(rel.mean()),
            "corr_dret": corr,
            "max_abs_dret": float(dr.max()) if len(dr) else nan,
            "mean_abs_dret": float(dr.mean()) if len(dr) else nan}


def price_consistency_ok(d, corr_min=None, max_abs_dret=None):
    """go/no-go：**日收益一致性**（判据不含 `max_rel`，见 spec 附 B）。"""
    corr_min = PRICE_CORR_MIN if corr_min is None else float(corr_min)
    max_abs = PRICE_MAX_ABS_DRET if max_abs_dret is None else float(max_abs_dret)
    corr = d.get("corr_dret", float("nan"))
    dr = d.get("max_abs_dret", float("nan"))
    if corr != corr or dr != dr:                     # NaN
        return False
    return corr >= corr_min and dr <= max_abs
```

（模块常量：`PRICE_CORR_MIN = 0.9999` / `PRICE_MAX_ABS_DRET = 0.005`。
`max_rel` 分母取 `max(|a|,|b|)` —— 0.02 手算按 2/100 **不符公式**，实际是 `2.0/102.0`。）

- [ ] **Step 4: 跑测试确认通过**

Run: `py -3.10 -m pytest tests/test_shoutu_analysis.py -v`
Expected: **24 passed**（计划原稿写 15，是写作时的快照；本文件最终 24 个用例 —— 见 Task 5 Step 1 补入的返回一致性 4 条 + Task 1 的钳位/NaN 等）。

- [ ] **Step 5: 在脚本里接上校验**

> ⚠️ **本节代码已被取代，以 `scripts/analyze_shoutu_greed.py` 为准。** 计划原稿与实际实现的差异：
> ① 计划把 `wide = pipeline.load_wide()` 放在 **try 内**；实际在**取权重处**读一次，
> 交叉校验**复用**（`if wide is None: wide = pipeline.load_wide()`）。
> ② 计划**只打印级差**；实际**两层打印**：级差为**观察项** +
> **日收益一致性为 go 门**，并加 `price_ok` 汇总行。
>
> 实际（`scripts/analyze_shoutu_greed.py`）：

```python
    # 权重：用**事件日**的实际权重；⚠️ `wide` 只读一次盘，下面的 price 交叉校验复用它。
    weights = None
    wide = None
    try:
        wide = pipeline.load_wide()
        weights = pipeline.risk_weight_series(wide)
    except Exception as e:                                  # noqa: BLE001
        print("⚠️ 取权重失败（%s）⇒ 退化为等权 1/3" % e)

    # 交叉校验：`shoutu_history.csv` 的 price 列 vs `prices.csv`（A2 的第一次实质使用）
    # ⚠️ 门槛分两层：① `max_rel`（级差）**只作观察项**（前复权 vs 未复权，差异落在除息日）；
    #   ② 真正的 go 门是**日收益一致性**（corr_dret ≥ PRICE_CORR_MIN 且 max_abs_dret ≤ ...）。
    price_ok = []
    try:
        if wide is None:
            wide = pipeline.load_wide()
        for s in MAIN_SYMBOLS:
            hp = hist[hist["symbol"] == s].set_index("date")["price"].astype(float)
            rp = wide[(s, "close")].dropna()
            d = shoutu_analysis.price_divergence(hp, rp)
            ok = shoutu_analysis.price_consistency_ok(d)
            price_ok.append(ok)
            print("price 交叉校验 %-5s 交集 %4d 天 | 级差(观察) 最大 %.4f%% 平均 %.4f%%"
                  " | 日收益 corr %.6f 最大差 %.4f%% 平均 %.4f%% | %s"
                  % (s, d["n"], 100 * d["max_rel"], 100 * d["mean_rel"],
                     d["corr_dret"], 100 * d["max_abs_dret"], 100 * d["mean_abs_dret"],
                     "通过" if ok else "**未通过**"))
    except Exception as e:                                  # noqa: BLE001
        print("⚠️ price 交叉校验跳过（%s）" % e)
    if price_ok:
        print("⇒ price 列一致性校验：%s（判据 = 日收益 corr ≥ %.4f 且 单日收益差 ≤ %.2f%%；"
              "级差为复权口径差，不作判据）"
              % ("**通过**" if all(price_ok) else "**未通过，本次结论需复核**",
                 shoutu_analysis.PRICE_CORR_MIN,
                 100 * shoutu_analysis.PRICE_MAX_ABS_DRET))
    print()
```

- [ ] **Step 6: 跑脚本确认校验通过**

Run: `py -3.10 scripts/analyze_shoutu_greed.py --main-only`
Expected: 三个标的的最大相对偏差**都远小于 1%**（同一标的的收盘价，应几乎相同）。
若某个 > 1% ⇒ **停下来查**，不要继续（说明 price 列口径不对，本次结论不可信）。

> ⚠️ **实施修正（2026-09-24 用户裁决）**：本步「最大相对偏差**远小于 1%**」的期望被实测
> 打破（实测 1.38%~2.22%），根因 = **复权口径差**（`hist.price` 前复权含分红 /
> `prices.csv.close` 未含分红，差异全部落在除息日）——**不是**数据错误。
> 门槛已改为**日收益一致性**（`corr_dret ≥ 0.9999` 且 `max_abs_dret ≤ 0.5%`），实测通过。
> **不要再按本步的 1% 判失败。** 详见 spec 附 B。

- [ ] **Step 7: 提交**

```bash
git add fg_system/shoutu_analysis.py scripts/analyze_shoutu_greed.py tests/test_shoutu_analysis.py
git commit -m "feat(shoutu): price 列交叉校验（vs prices.csv）—— 兼作 A2 的端到端证据"
```

---

## Task 6: 出数、回写文档、收尾

- [ ] **Step 1: 跑全量测试**

Run: `py -3.10 -m pytest -q`
Expected: **713 passed**（计划原稿写「预计 699 左右」，是写作时快照；最终实测 **713 passed**，
见文末「实施结果」一节）。

- [ ] **Step 2: 跑完整分析（含旁证）**

Run: `py -3.10 scripts/analyze_shoutu_greed.py`
Expected: 事件表 + 汇总 + 判据结论。**把完整输出留档**（回写文档要用）。

- [ ] **Step 3: 回写 `docs/trading-discipline.md` §14.5**

在「本步之后的裁决」表**之后**新增小节，内容（数字以 Step 2 的实际输出为准）：

```markdown
**Step B（C 阶段）结论：守猪待兔「早清仓代价」（2026-09-24）**

- **事件样本**：档位 4（守猪待兔 ≥ +60）共 105 个 episode
  （主样本 TQQQ/SOXL/UPRO 56 个）—— 详见 spec §2 的分布表。
- **⚠️ 结构性事实**：大量 episode 只有 1~2 天，而代价 ∝ **离场天数 × 该期间涨幅**
  ⇒ "26.4% 的天数在档位 4"**严重高估**实际暴露面。故结论按 episode 长度分段。
- **收益差（不卖 − 规则）**：<填 Step 2 的实际数字，含均值与中位数>
- **判据比对**（判据在跑数**之前**写死，见 spec §6）：
  - 长 episode（>20 天）平均收益差 <填>（门槛 ≥ 10%）
  - 单次最大卖飞 <填>（门槛 ≥ 20%）
  - ⇒ **<建议 / 不建议>做 A（全系统回放）**
- **未建模**（结论偏保守）：佣金 / 滑点 / 汇率 / 趋势系数 / 弹药池；
  `REBALANCE_COOLDOWN` 只在实盘侧，**回测里没有**（spec §2.1 校正）。
- **不做显著性检验**：事件在时间上重叠、非独立样本 ⇒ 本结论是**量级估计**，
  不是统计推断。
- 脚本：`scripts/analyze_shoutu_greed.py`（可重跑）
```

- [ ] **Step 4: 提交**

```bash
git add docs/trading-discipline.md
git commit -m "docs(shoutu): Step B（C 阶段）结论 —— 早清仓代价量化与判据比对"
```

---

## 自审（spec 覆盖检查）

| spec 要求 | 落在哪个 Task |
|---|---|
| §2 事件定义（含未完成标注） | Task 2 |
| §4.1 逐日回放（含买回、不冻结） | Task 1 + Task 3 |
| §4.2 P0 = CORE_CAP × RATIO × w_i | Task 4（`analyze_symbol`） |
| §5.1 窗口 20/60/120 + 全程 | Task 4 |
| §5.2 按 episode 长度分三段 | Task 4（`_bucket`） |
| §5.3 均值 + 中位数并列 | Task 4（汇总打印） |
| §5.4 价格用 price 列 + 交叉校验 | Task 4 + Task 5 |
| §5.5 未建模项随结果标注 | Task 6（回写块） |
| §6 判据事先写死 + 比对 | Task 4（打印）+ Task 6（记录） |
| §7 复用 `FgStrategy` 口径 + 一致性 | Task 1（**构造保证**：同一函数） |
| §9 任务清单 1~7 | Task 1~6 全覆盖 |
| §10 回写事项 | Task 6 |

**无占位符残留**（Task 6 的 `<填>` 是**运行时才存在的数字**，且已注明来源步骤 ——
不是"待设计"）。

---

## 实施结果（2026-09-24 实测）

> ⚠️ **本计划的 `Expected` 计数为写作时快照，最终以本节为准。**

- **最终全量测试**：`py -3.10 -m pytest tests -q` ⇒ **716 passed**（cwd = 仓库根）。
  - 713 = Step B 交付时的基线；**716 = 713 + 本次新增 3 条**（`tests/test_analyze_shoutu_greed.py`
    的 `test_fixed_window_matches_full120_scale`、`test_hold_return_scales_with_p0`、
    常驻变异验证 `test_mutation_old_forward_return_breaks_invariant`）。
  - 本计划各 Step 的 `Expected` 计数（5 / 15 / 2 / 699 …）为写作时快照，
    与最终实现有出入（如 Task 5 Step 4 实为 **24 passed**、Task 4 Step 4 实为 **5 passed**）。
- **最终判据结论**（判据见 spec §6，样本 = 主样本，见裁决③；**两窗口并列**，见 2026-09-24 裁决）：
  - **主判据**（窗口 `full` = episode 全程）：长 episode（>20 天）平均收益差 **+3.43pp** ❌、
    单次最大卖飞 **+7.56%** ❌ ⇒ **不建议**做 A。
  - **补充判据**（窗口 `full120` = 120 日固定窗口）：长 episode 均值 **+5.15pp** ❌、
    单次最大卖飞 **+34.33%** ✅（TQQQ 2025-05-13）⇒ **「单次最大卖飞 ≥ 20%」成立**。
  - 稳健性对照（含旁证的过滤后全样本 95 个，窗口 = `full`）：**+4.50pp / +15.29%** ⇒ 仍不满足。
  - ⇒ **主判据（`full`）不建议做 A；补充判据（`full120`）的「单次最大卖飞 ≥ 20%」成立
    ⇒ 是否做 A 交人工裁决**；**不改规则**、**议题不关闭**，立为追踪项
    （`docs/trading-discipline.md` §13.6 **O4**）。
- **与计划的实现差异**（均已同步或标注取代，见 Task 1 / Task 4 / Task 5 各 Step）：
  `full` 的 horizon = `days - 1` 且 `full` = episode 全程（非 `max(days, 120)`）、
  `full120` 对照列、`noact` / `unclosed` 过滤、`view` 主样本判据 + `_verdict` 具名常量、
  权重取事件日、静态守卫扫描全部字符串常量（含 docstring）、
  **`_forward_return` 按 `p0` 缩放（D8 bug 修复）**、**判据两窗口并列 `_verdict(g, col)`（D7）**。
