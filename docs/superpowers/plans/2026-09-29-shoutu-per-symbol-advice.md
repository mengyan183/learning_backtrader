# 守猪待兔「逐标的建议」+ 行情自动化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让系统能**逐标的**输出最新建议（覆盖全部 8 个守猪待兔标的），并让行情数据跟着每日任务自动更新。

**Architecture:** 四件**互相独立**的事，按依赖排序：**P0** 把行情抓取加进每日任务（否则后面三件的输出都建立在旧数据上）；**A** 把 `status` 的逐标的表从 3 个生产标的扩到 8 个守猪待兔标的（需先把脚本里的 `_signal_wide` 上移到库层做单源）；**C** 把该表读的源从**本地 06:30 采样表**换成**服务端权威表**；**B**（逐标的**动作**）是**新机制**，本方案**只定设计与启动闸门，不实施** —— 第 8 条的「回测」这一步在数据长度上做不了（见 Task 5）。

**Tech Stack:** Python 3.10 / pandas 2.3.3 / numpy 2.2.6 / pytest 9.1.1

---

## 背景与证据（先看这个，否则会做错）

现状由 2026-09-29 的实测确定，三条：

| # | 事实 | 证据 |
|---|---|---|
| **P0** | `prices.csv`（OHLC 历史）**没有任何定时任务在更新** | `fetch.update_prices()` 的**唯一**调用方是 `scripts/bootstrap_data.py:168`（一次性数据重建）；`shoutu_daily.sh` / `shoutu_daily.cmd` 只抓守猪待兔；§14.5 的自动化清单**只有 E1**。实测：`prices.csv` 停在 **2026-09-25**，而 `shoutu_fng.csv` 是当天的 ⇒ `status` 自己打印「价格数据最后一日 2026-09-25」 |
| **A** | `status` 的逐标的表**只覆盖 3 个** | `fg_system/cli.py:120` 与 `:133` 都是 `for s in config.SYMBOLS`；`config.SYMBOLS` 只有 TQQQ/SOXL/UPRO，而 `config.SHOUTU_SYMBOLS` 有 **8** 个 |
| **C** | 该表读的是**本地采样表**，不是生产权威源 | `fg_system/cli.py:91` `sw = loader.load_shoutu_fng()`。`config.py:287-288` 明确：「这里是**服务端权威日值**，那边是**本地 06:30 采样**。**不要混用**（spec §5.4）」 |

**已知的拦路石（必须先解决，否则 A 会崩）**：`GDXU` 的 σ 必须用**合成列** `GDXU_UND`（= GDX+GDXJ 市值加权，见 `config.py:319-330`），而 `CONL` 的底层 `COIN` **不在** `prices.csv` 里（在 `crypto_prices.csv`）。生产宽表 `pipeline.load_wide()` **没有**这两列 ⇒ 直接用 `SHOUTU_SYMBOLS` 调 `risk_weight_series` 会 **KeyError**。现成的解法已经存在，但在**脚本**里（`scripts/analyze_shoutu_variants.py:296-315` 的 `_signal_wide`）⇒ 本方案把它**上移到库层**（Task 2）。

**第 8 条纪律**（本仓库 `docs/trading-discipline.md:281-311`）：顺序**不可颠倒** ——
1. 先改文档（本规范 + 技术设计文档）→ 2. 再改代码 → 3. 再回测 → 4. 再验证。

⇒ 因此 **Task 0 先落文档**，代码任务在其后。**一次只改一件事**，每件事单独提交。

---

## 文件结构

| 文件 | 动作 | 职责 |
|---|---|---|
| `docs/trading-discipline.md` | Modify（§12.28 + §14.5） | 登记本次变更与「行情纳入每日任务」这一新能力 |
| `scripts/shoutu_daily.sh` | Modify（在 history 块之后） | Mac：加一步行情增量抓取，**不改 RC** |
| `scripts/shoutu_daily.cmd` | Modify（在 history 块之后） | Windows：同上，**注释必须纯 ASCII** |
| `fg_system/pipeline.py` | Modify（新增 2 个函数） | `signal_wide()` + `_crypto_close()` —— 从脚本上移，成为**单源** |
| `scripts/analyze_shoutu_variants.py` | Modify（删 `_signal_wide`/`_crypto_close`，改调用） | 改为调库层，**守卫保持不变** |
| `fg_system/cli.py` | Modify（`_print_shoutu_cores`） | 表扩到 8 个标的 + 换权威源 |
| `tests/test_shoutu_variants.py` | Modify（新增） | `signal_wide` 的单源守卫 + 行为守卫 |
| `tests/test_cli_status.py` | Modify（新增） | 逐标的表覆盖 8 个标的的守卫 |

---

## Task 0: 先落文档（第 8 条要求）

**Files:**
- Modify: `docs/trading-discipline.md`（在 §12.27 之后追加 §12.28；在 §14.5 的表格里加一行）

- [ ] **Step 1: 在 §12.27 之后追加 §12.28**

在 `docs/trading-discipline.md` 里找到 `### 12.27（2026-09-28）：传输链路的三个教训` 这一节的**末尾**（即文件末尾那行 `> 诊断信息必须能区分「**输入不对**」与「**数据不对**」。`），在其后追加：

```markdown
---

### 12.28（2026-09-29）：逐标的建议的覆盖面与口径 + 行情纳入每日任务

**背景（实测）**：用户问「每个标的最新的投资建议」。查证发现三件事，
其中**前两件是能力缺失、第三件是口径不一致**。

**① 逐标的表只覆盖 3 个标的（覆盖面）**
`cli.py:120` / `:133` 用 `config.SYMBOLS`（TQQQ/SOXL/UPRO），
而 `config.SHOUTU_SYMBOLS` 有 **8** 个 ⇒ CONL / YINN / GDXU / AXTX / CRCG
**在表里完全不出现**，用户看不到它们的档位与饱和度。

**② 该表读的是本地采样表，不是生产权威源（口径）**
`cli.py:91` 读 `loader.load_shoutu_fng()`，而 `config.py:287-288` 明确
「不要混用（spec §5.4）」—— 这里是**服务端权威日值**，那边是**本地 06:30 采样**。
⇒ 表里显示的档位可能和生产实际用的**不是同一份数据**。

**③ 行情（`prices.csv`）没有任何定时任务在更新**
`fetch.update_prices()` 的唯一调用方是 `scripts/bootstrap_data.py`（一次性数据重建）
⇒ 实测 `prices.csv` 停在 **2026-09-25**，而守猪待兔数据是当天的 ⇒
**生产信号日卡住不动**（`status` 自己打印「价格数据最后一日 2026-09-25」）。
§14.5 的自动化清单里**只有 E1**，这一条**从未被排进任务**。

**本次改动范围（一次只改一件事，逐条提交）**：
- **P0**：把行情增量抓取加进 `shoutu_daily.sh` / `.cmd`（**不改 RC**，同 history 的约定）
- **A**：逐标的表扩到 `config.SHOUTU_SYMBOLS` 全 8 个（先把脚本里的
  `_signal_wide` 上移到库层做**单源**）；⚠️ **加权平均仍只用 3 个生产标的**
  ⇒ 生产口径**逐位不变**
- **C**：该表改用 `shoutu_history.csv`（权威源）
- **B（不实施）**：逐标的**动作**是新机制，且第 8 条的「回测」这一步
  因数据长度做不了（§12.26 Q4）⇒ 只登记设计与启动闸门

> **规则**：**「看不到」和「算错了」是两种缺陷，必须分开处理。**
> 覆盖面（①）是显示问题、改一行循环即可；口径（②）会**改变数字**，
> 属行为变更、必须单独提交并写明前后差异；能力缺失（③）要走第 8 条但
> **不改任何交易规则**。把三件事混成一次提交，会让"数字变了"无法归因。
```

- [ ] **Step 2: 在 §14.5 的自动化表格里加一行**

找到 `docs/trading-discipline.md` 里 `### 14.5 自动化的实现状态` 下的三行表格（`| **E1** | ...` / `| **E2** | ...` / `| **E3** | ...`），在 `| **E3** |` 那行**之前**插入：

```markdown
| **E1b** | **行情增量抓取**（`prices.csv`） | ✅ **已实现**（2026-09-29，并入 `shoutu_daily.sh` / `.cmd`，**不改 RC**） |
```

- [ ] **Step 3: 提交**

```bash
git add docs/trading-discipline.md
git commit -m "docs(discipline): §12.28 逐标的建议覆盖面/口径 + 行情纳入每日任务（第8条：先文档）"
```

---

## Task 1: 行情增量抓取并入 Mac 每日任务

**Files:**
- Modify: `scripts/shoutu_daily.sh`（在 `echo "===== shoutu_history exit=$RC2 =====" >> "$LOG"` 之后、`echo "===== end $(stamp) exit=$RC =====" >> "$LOG"` 之前）

- [ ] **Step 1: 在 `shoutu_daily.sh` 的 history 块之后插入行情块**

在 `scripts/shoutu_daily.sh` 里找到这一段（第 96-102 行附近）：

```bash
if command -v bsk >/dev/null 2>&1; then
    "$PY" scripts/fetch_shoutu_history.py >> "$LOG" 2>&1
    RC2=$?
    echo "===== shoutu_history exit=$RC2 =====" >> "$LOG"
else
    echo "===== shoutu_history SKIPPED (no bsk on PATH) =====" >> "$LOG"
fi
```

在 `fi` 之后、`echo "===== end $(stamp) exit=$RC =====" >> "$LOG"` **之前**插入：

```bash
# ---------------------------------------------------------------- 抓取（行情，**可选**）
# 2026-09-29 补（§12.28③）：`prices.csv` 此前**没有任何定时任务**在更新 ——
# 唯一调用方是 `scripts/bootstrap_data.py`（一次性数据重建）⇒ 生产信号日会**卡住不动**
# （实测 2026-09-29：守猪待兔是当天的，行情却停在 09-25）。
#
# ⚠️ **不改 RC** —— 任务成败仍由主路径 `fetch_shoutu_api.py` 决定
#    （同上面 history 块的约定，见本文件第 91-92 行）。
# ⚠️ 数据源有请求前节流，24 个标的约 1~3 分钟，属正常等待。
"$PY" -c "from fg_system.data import fetch; _, a = fetch.update_prices(); print('prices.csv 新增 %d 行' % sum(a.values()))" >> "$LOG" 2>&1
RC3=$?
echo "===== prices exit=$RC3 =====" >> "$LOG"
```

- [ ] **Step 2: 语法自检（不跑真抓取）**

Run:
```bash
bash -n scripts/shoutu_daily.sh && echo SYNTAX_OK
```
Expected: `SYNTAX_OK`

- [ ] **Step 3: 手工验证这一步真的能抓到数据**

⚠️ 本步骤**会**改 `Data/raw/prices.csv`（追加新行）。在**开发机**上跑：

Run:
```bash
cd /d/3-code/learning_backtrader && PYTHONUTF8=1 py -3.10 -c "from fg_system.data import fetch; df, a = fetch.update_prices(); print('新增', sum(a.values()), '行；最后日期', df['date'].max())"
```
Expected: `新增 N 行；最后日期 2026-09-26`（或更晚）—— **N > 0**，
且最后日期**晚于**改动前的 `2026-09-25`。

- [ ] **Step 4: 提交**

```bash
git add scripts/shoutu_daily.sh
git commit -m "feat(daily): 行情增量抓取并入 Mac 每日任务（不改 RC，§12.28③）"
```

---

## Task 2: 行情增量抓取并入 Windows 每日任务

**Files:**
- Modify: `scripts/shoutu_daily.cmd`（在 `echo ===== shoutu_history exit=%RC2% ===== >> logs\shoutu_daily.log` 之后）

⚠️ **本文件是纯 ASCII 的**（文件头 16-26 行有明确禁令 + 2026-09-23 的实机事故记录）
⇒ 新增注释**只能用英文**。

- [ ] **Step 1: 插入行情块**

在 `scripts/shoutu_daily.cmd` 里找到：

```bat
"C:\Users\260023\AppData\Local\Programs\Python\Python310\python.exe" scripts\fetch_shoutu_history.py >> logs\shoutu_daily.log 2>&1
set RC2=%ERRORLEVEL%
echo ===== shoutu_history exit=%RC2% ===== >> logs\shoutu_daily.log
```

在其**之后**、`for /f %%i in ('powershell ... Get-Date -Format s') do set STAMP2=%%i` **之前**插入：

```bat
REM ---------------------------------------------------------------------------
REM MARKET DATA (2026-09-29, section 12.28 item 3): prices.csv had NO scheduled
REM task at all -- its only caller was scripts\bootstrap_data.py (one-time
REM rebuild). Result: the production signal date froze (measured 2026-09-29:
REM shoutu data was current, prices.csv was 4 days stale).
REM
REM Failure here does NOT change RC -- the main path decides the task result
REM (same convention as the history block above).
REM NOTE: keep this file ASCII-only (see the header of this file).
REM ---------------------------------------------------------------------------
"C:\Users\260023\AppData\Local\Programs\Python\Python310\python.exe" -c "from fg_system.data import fetch; df, a = fetch.update_prices(); print('prices.csv added %d rows' % sum(a.values()))" >> logs\shoutu_daily.log 2>&1
set RC3=%ERRORLEVEL%
echo ===== prices exit=%RC3% ===== >> logs\shoutu_daily.log
```

- [ ] **Step 2: 断言新增内容全是 ASCII**

Run:
```bash
cd /d/3-code/learning_backtrader && PYTHONUTF8=1 py -3.10 -c "d=open('scripts/shoutu_daily.cmd','rb').read(); bad=[b for b in d if b>127]; print('非 ASCII 字节数:', len(bad))"
```
Expected: `非 ASCII 字节数: 0`

- [ ] **Step 3: 提交**

```bash
git add scripts/shoutu_daily.cmd
git commit -m "feat(daily): 行情增量抓取并入 Windows 每日任务（纯ASCII，不改 RC）"
```

---

## Task 3: 把 `_signal_wide` 上移到库层（单源）

**为什么必须先做这一步**：Task 4 要按 `SHOUTU_SYMBOLS`（8 个）算 inv-vol 权重，
而 `GDXU` 的底层是**合成列** `GDXU_UND`、`CONL` 的底层 `COIN` 在 `crypto_prices.csv`
⇒ 直接用生产宽表会 `KeyError`。补齐逻辑**已经存在**，但在脚本里
（`scripts/analyze_shoutu_variants.py:296-315`）⇒ 现在有**两个**使用方，必须单源。

**Files:**
- Modify: `fg_system/pipeline.py`（在 `blend_close` 之后新增两个函数）
- Modify: `scripts/analyze_shoutu_variants.py`（删掉本地的 `_signal_wide` / `_crypto_close`，改调库层）
- Test: `tests/test_shoutu_variants.py`

- [ ] **Step 1: 写失败的测试**

在 `tests/test_shoutu_variants.py` **末尾**追加：

```python
def test_signal_wide_adds_gdxu_blend_and_crypto_underlying():
    """`pipeline.signal_wide` 必须补齐**两个**非生产底层列。

    为什么需要它（第 12.28 条①）：按 `SHOUTU_SYMBOLS`（8 个）算 inv-vol 权重时，
    `GDXU` 的底层是**合成列** `GDXU_UND`（GDX+GDXJ 市值加权），
    `CONL` 的底层 `COIN` 在 `crypto_prices.csv`（**不在** `prices.csv`）
    ⇒ 直接用生产宽表会 `KeyError`。

    ⚠️ fixture 必须构造**生产同款**的宽表（含全部非币底层）：
    `signal_wide` 对「不在宽表里的底层」**一律**去 `crypto_prices.csv` 找，
    而那里只有币股。若只放 GDX/GDXJ，循环会去找 QQQ/SOXX/... ⇒ `ValueError`
    （实测踩到：最小 fixture 与本实现互斥）。
    """
    idx = pd.date_range("2024-01-01", periods=5, freq="B")
    cols = {("GDX", "close"): [10.0, 11.0, 12.0, 13.0, 14.0],
            ("GDXJ", "close"): [20.0, 21.0, 22.0, 23.0, 24.0]}
    # 非币底层：生产 `load_wide()` 里本来就有它们 ⇒ fixture 必须同款
    for und in ("QQQ", "SOXX", "SPY", "FXI", "AXTI", "CRCL"):
        cols[(und, "close")] = [100.0] * 5
    wide = pd.DataFrame(cols, index=idx)

    out = pipeline.signal_wide(wide)

    # ① GDXU 的合成底层列（GDX+GDXJ 市值加权）
    und = config.GDXU_UNDERLYING_COLUMN
    assert (und, "close") in out.columns, "没补上 GDXU 的合成底层列"
    w = config.GDXU_UNDERLYING_BLEND
    expect = (w["GDX"] * wide[("GDX", "close")]
              + w["GDXJ"] * wide[("GDXJ", "close")])
    assert out[(und, "close")].tolist() == pytest.approx(expect.tolist())

    # ② CONL 的底层 COIN 只能从 crypto_prices.csv 补
    assert ("COIN", "close") in out.columns, "没从 crypto_prices.csv 补上 COIN"

    # ③ 只增列，不改列
    assert ("GDX", "close") in out.columns
    assert len(out.columns) == len(wide.columns) + 2, "应该恰好补 2 列"


def test_signal_wide_is_single_source_with_the_script():
    """**守卫**：脚本不得再自己实现一份 `_signal_wide`（第 12.26 条⑤ 的教训）。

    同一份「补齐底层列」的逻辑若在脚本和库层各写一份，必然漂移 ——
    而漂移的后果是**研究口径与展示口径不一致**，且**不报错**。
    """
    src = open(os.path.join(config.ROOT, "scripts",
                            "analyze_shoutu_variants.py"),
               encoding="utf-8").read()
    assert "def _signal_wide" not in src, \
        "脚本里又出现了本地的 _signal_wide —— 必须改为调用 pipeline.signal_wide"
    assert "pipeline.signal_wide(" in src, "脚本没有调用库层的 signal_wide"
```

> ⚠️ **fixture 必须含全部非币底层**（2026-09-29 实施时踩到）：`signal_wide` 对
> 「不在宽表里的底层」一律去 `crypto_prices.csv` 找，而那里只有币股 ⇒
> 最小 fixture 会让它去找 QQQ ⇒ `ValueError`。实施者据此 BLOCKED 并纠正了本方案。

在 `tests/test_shoutu_variants.py` 顶部的 import 区确认有（没有就补）：

```python
import os
```

- [ ] **Step 2: 跑测试，确认失败**

Run:
```bash
cd /d/3-code/learning_backtrader && PYTHONUTF8=1 py -3.10 -m pytest tests/test_shoutu_variants.py -q -k "signal_wide" --tb=short
```
Expected: FAIL —— `AttributeError: module 'fg_system.pipeline' has no attribute 'signal_wide'`

- [ ] **Step 3: 在 `pipeline.py` 里实现**

在 `fg_system/pipeline.py` 的 `blend_close` 函数**之后**（即 `blend_close` 的
最后一行 `return ...` 之后、下一个 `def` 之前）插入：

```python
def _crypto_close(symbol):
    """从 `crypto_prices.csv` 取单标的 close（币股**不在** `prices.csv` 里）。"""
    df = pd.read_csv(config.CRYPTO_PRICES_PATH, dtype={"symbol": str},
                     parse_dates=["date"])
    sub = df[df["symbol"] == symbol].set_index("date")["close"].sort_index()
    if sub.empty:
        raise ValueError(
            "crypto_prices.csv 里没有 %s —— 它是某个守猪待兔标的的无杠杆底层，不得缺"
            % symbol)
    return sub


def signal_wide(wide):
    """研究用宽表：在 `wide` 上**只增列**，补齐守猪待兔标的的无杠杆底层。

    从 `scripts/analyze_shoutu_variants.py::_signal_wide` **上移**而来（2026-09-29）。
    为什么必须单源：同一份逻辑现在有**两个**使用方 ——
      1. `scripts/analyze_shoutu_variants.py` 的全样本稳健性对照；
      2. `fg_system/cli.py::_print_shoutu_cores` 的逐标的表（第 12.28 条①）。
    两边各写一份必然漂移（第 12.26 条⑤ 的教训）。

    - `config.GDXU_UNDERLYING_COLUMN`：按 `config.GDXU_UNDERLYING_BLEND` 合成
      （GDXU 的真底层是指数 `MINERS` = GDX+GDXJ 市值加权，**不是** GDX 单只）。
    - 其余底层：凡 `config.SIGNAL_UNDERLYING_MAP` 里出现、而 `wide` 没有的列，
      一律到 `crypto_prices.csv` 找（当前只有 CONL 的底层 COIN）。

    ⚠️ **不硬编码任何标的** —— 映射与合成列名都来自 `config`。
    """
    out = wide.copy()
    have = set(out.columns.get_level_values(0))
    for und in config.SIGNAL_UNDERLYING_MAP.values():
        if und in have or und == config.GDXU_UNDERLYING_COLUMN:
            continue
        out[(und, "close")] = _crypto_close(und).reindex(out.index)
    out[(config.GDXU_UNDERLYING_COLUMN, "close")] = blend_close(
        out, config.GDXU_UNDERLYING_BLEND).reindex(out.index)
    return out
```

- [ ] **Step 4: 改脚本去调用库层**

在 `scripts/analyze_shoutu_variants.py` 里：

1. **删除**本地的 `def _crypto_close(symbol):` 与其整个函数体（第 284-293 行）。
2. **删除**本地的 `def _signal_wide(wide):` 与其整个函数体（第 296-315 行）。
3. 找到脚本里唯一调用它的地方（形如 `sig_wide = _signal_wide(wide)`），改为：

```python
    sig_wide = pipeline.signal_wide(wide)
```

> 若 `pipeline` 尚未在脚本里导入，在文件顶部已有的
> `from fg_system import config, pipeline, shoutu_variants` 一行里确认包含 `pipeline`。

- [ ] **Step 5: 跑测试，确认通过**

Run:
```bash
cd /d/3-code/learning_backtrader && PYTHONUTF8=1 py -3.10 -m pytest tests/test_shoutu_variants.py -q --tb=short
```
Expected: PASS（全绿，含原有的「脚本不得硬编码 SHOUTU_SYMBOLS」守卫）

- [ ] **Step 6: 提交**

```bash
git add fg_system/pipeline.py scripts/analyze_shoutu_variants.py tests/test_shoutu_variants.py
git commit -m "refactor(pipeline): _signal_wide 上移到库层单源（为逐标的表扩到8个标的铺路）"
```

---

## Task 4: 逐标的表扩到全部 8 个标的（覆盖面）

**Files:**
- Modify: `fg_system/cli.py:77-139`（`_print_shoutu_cores`）
- Test: `tests/test_cli_status.py`

⚠️ **本任务只改「显示什么」，不改「怎么算」** —— 加权平均**仍只用 3 个生产标的**，
所以生产口径（核心仓 %）**逐位不变**。这是第 8 条「一次只改一件事」的要求。

- [ ] **Step 1: 写失败的测试**

在 `tests/test_cli_status.py` **末尾**追加：

```python
def test_status_shoutu_table_covers_all_shoutu_symbols(capsys):
    """**守卫**：逐标的表必须覆盖 `config.SHOUTU_SYMBOLS` 的**全部**标的。

    第 12.28 条①：原来只遍历 `config.SYMBOLS`（3 个）⇒
    CONL / YINN / GDXU / AXTX / CRCG **在表里完全不出现**，
    用户看不到它们的档位与饱和度。
    """
    from fg_system import cli, config
    rc = cli.main(["status"])
    # ⚠️ `cli.main()` 对成功命令返回 `None`（`_cmd_status` 无 return；
    #    退出码归一化 `_exit_code()` 只在 `__main__` 里用）。
    #    仓库既有测试也都不断言返回值 ⇒ 这里只断言「没崩」。
    assert rc is None
    out = capsys.readouterr().out
    # 每个标的名字必须出现在输出里（该表每标的打一行）
    missing = [s for s in config.SHOUTU_SYMBOLS if s not in out]
    assert not missing, "逐标的表漏了这些标的：%s" % missing


def test_shoutu_avg_covers_only_production_symbols(monkeypatch):
    """**守卫**：加权平均**只用生产标的**（第 8 条「一次只改一件事」）。

    ⚠️ 用**行为**断言，**不用** `inspect.getsource` + 字符串匹配 ——
    那正是 §12.27-① 抓到的弱守卫形态（把 `if False and ...` 塞进去也照样通过）。

    做法：造一份**只有研究标的有值**、生产标的（TQQQ/SOXL/UPRO）**全缺**的守猪待兔表。
    ⇒ 若加权平均把研究标的算进去，`avg` 会偏离市场指数系数；
    ⇒ 只算生产标的时，生产标的全部缺值 ⇒ 每个都回退 `mkt_sat`
      ⇒ `avg` 必须**恰好等于** `mkt_sat`。
    """
    from fg_system import cli
    from fg_system.data import loader

    idx = pd.date_range("2026-09-22", periods=2, freq="D")
    fake = pd.DataFrame({"CONL": [50.0, 50.0], "YINN": [-50.0, -50.0]}, index=idx)
    monkeypatch.setattr(loader, "load_shoutu_fng", lambda *a, **k: fake)

    us = pd.DataFrame({"fg_index": [58.3]}, index=idx[-1:])
    ret = cli._print_shoutu_cores(us)
    assert ret is not None, "没有返回值 —— 无法做行为断言（见 Step 3 的 return）"
    assert ret["avg"] == pytest.approx(ret["mkt_sat"]), \
        "生产标的全缺值时 avg 必须恰好等于市场指数系数 ⇒ 说明把研究标的算进去了"
```

> ⚠️ **`cli.main()` 对成功命令返回 `None`**（2026-09-29 实施时踩到）：
> `_cmd_status` 无 return，退出码归一化 `_exit_code()` 只在 `__main__` 里用
> ⇒ 方案初稿写的 `assert rc == 0` 恒为 False。实施者据此 BLOCKED 并纠正了本方案。
> 仓库既有测试也都不断言 `cli.main()` 的返回值。

- [ ] **Step 2: 跑测试，确认失败**

Run:
```bash
cd /d/3-code/learning_backtrader && PYTHONUTF8=1 py -3.10 -m pytest tests/test_cli_status.py -q -k "shoutu" --tb=short
```
Expected: `test_status_shoutu_table_covers_all_shoutu_symbols` FAIL ——
`逐标的表漏了这些标的：['CONL', 'YINN', 'GDXU', 'AXTX', 'CRCG']`

- [ ] **Step 3: 改 `_print_shoutu_cores`**

在 `fg_system/cli.py` 里，把 `_print_shoutu_cores` 的这三处改掉：

**(a) 权重：保持生产口径权重不变**（原第 94-95 行，**不改**）：

```python
    # ⚠️ 2026-09-29（第 12.28 条①）：**权重仍按生产口径（3 个标的，Σ=1）算**。
    #    不要改成 `symbols=config.SHOUTU_SYMBOLS` —— 那会把归一化基数从 3 换成 8，
    #    于是「只对生产标的求和的加权平均」会变成旧值的 0.375 倍
    #    ⇒ **生产口径被改**（实测 0.286→0.125、核心仓 10.31%→4.50%）。
    #    本任务只改「显示什么」，改数字是 Task 5 的事（第 8 条「一次只改一件事」）。
    weights = (pipeline.risk_weight_series(pipeline.load_wide())
               .reindex(us.index).ffill())
```

**(b) 循环：遍历全部 8 个，并标出是否生产标的**（原第 120-128 行）：

```python
    for s in config.SHOUTU_SYMBOLS:
        if s not in row.index or pd.isna(row[s]):
            continue
        v = float(row[s])
        scaled = (v + 100.0) / 2.0
        z = ms_mod.zone_of(scaled)
        sats[s] = config.ZONE_SATURATION[z]
        # ⚠️ `last_w` 只含 3 个**生产**标的 ⇒ 研究标的**不可索引**
        #    （它们不可交易、没有生产权重）。给它们显示一个归一化出来的百分比
        #    会**误导**（让人以为占了组合 12.5%）⇒ 研究标的显示 `—`。
        w_txt = ("%7.1f%%" % (last_w[s] * 100)) if s in config.SYMBOLS else "      —"
        print("%-6s %+10.0f %10.1f %6d %8.2f %8s  %s"
              % (s, v, scaled, z, config.ZONE_SATURATION[z], w_txt,
                 "生产" if s in config.SYMBOLS else "研究"))
```

并把表头（原第 117-118 行）改为：

```python
    print("%-6s %10s %12s %6s %8s %8s  %s"
          % ("标的", "守猪待兔", "固定阈值口径", "档位", "饱和度", "权重", "类别"))
```

**(c) 加权平均：显式限定生产标的，并**返回结果**（供行为断言）**（原第 133-139 行）：

```python
    # ⚠️ 加权平均**仍只用生产标的** —— 核心仓是生产量，研究标的**不可交易**。
    #    这样本次改动对生产口径**逐位不变**（第 8 条「一次只改一件事」）。
    prod = [s for s in config.SYMBOLS if s in last_w.index]
    avg = sum(sats.get(s, mkt_sat) * last_w[s] for s in prod)
    print("加权平均系数 %.3f  ←  市场指数系数 %.3f（指数 %.1f，档 %d）"
          % (avg, mkt_sat, mkt_idx, ms_mod.zone_of(mkt_idx)))
    print("核心仓（不含趋势）%.2f%%  ←  原市场级 %.2f%%"
          % (base * avg * 100, base * mkt_sat * 100))
    print("注：历史区间无守猪待兔数据 ⇒ 逐标的系数**回退市场指数**，"
          "回测结果不变（第 12.26 条）。")
    # ⚠️ **返回结果**：测试要用**行为**断言「加权平均只用生产标的」，
    #    而不是去匹配源码字符串（那正是 §12.27-① 的弱守卫形态）。
    return {"avg": avg, "mkt_sat": mkt_sat, "base": base,
            "sats": sats, "weights": last_w}
```

> 注意：函数里那两处**提前 return**（`sw.empty` 与「该日无任何标的的守猪待兔值」）
> 保持原样返回 `None` —— 新增的 `return` 只走「正常算完」这条路径。

- [ ] **Step 4: 跑测试，确认通过**

Run:
```bash
cd /d/3-code/learning_backtrader && PYTHONUTF8=1 py -3.10 -m pytest tests/test_cli_status.py -q --tb=short
```
Expected: PASS

- [ ] **Step 5: 肉眼核对生产口径没变**

Run:
```bash
cd /d/3-code/learning_backtrader && PYTHONUTF8=1 py -3.10 -m fg_system.cli status 2>/dev/null | sed -n '/守猪待兔逐标的系数/,/回测结果不变/p'
```
Expected: 表里出现 **8 行**；且最后两行的
`加权平均系数` 与 `核心仓（不含趋势）` 的数值与**改动前一致**
（改动前是 `加权平均系数 0.286` / `核心仓（不含趋势）10.31%`）。
⚠️ 若数值变了 ⇒ **说明加权平均被误改**，回退 Step 3(c)。

> ⚠️ **方案初稿在 Step 3(a) 与 Step 3(d) 之间自相矛盾**（2026-09-29 实施时踩到）：
> 把权重基数从 3 个换成 8 个（`symbols=SHOUTU_SYMBOLS`）会让「只对生产标的求和」的
> 加权平均变成旧值的 **0.375 倍**（实测 `0.286 → 0.125`、核心仓 `10.31% → 4.50%`）
> ⇒ 与「生产口径逐位不变」的硬约束冲突。**裁决：权重仍按生产口径（3 标的，Σ=1）算**，
> 研究标的的「权重」列显示 `—`（它们**不可交易、没有生产权重**）。
> 实施者据此 BLOCKED 并逐位复现了基线值。

- [ ] **Step 6: 提交**

```bash
git add fg_system/cli.py tests/test_cli_status.py
git commit -m "feat(cli): 逐标的表扩到全部8个守猪待兔标的（生产口径逐位不变，§12.28①）"
```

---

## Task 5: 口径换成服务端权威源（**行为变更，必须单独提交**）

**Files:**
- Modify: `fg_system/cli.py:91`（`_print_shoutu_cores` 的取数）
- Test: `tests/test_cli_status.py`

⚠️ **本任务会改变表里的数字**（本地 06:30 采样 → 服务端权威日值）。
这是**有意**的（`config.py:287-288` 明确「不要混用」），但必须：
1. **单独提交**，commit message 写明「行为变更」；
2. 在 §12.28 里补记**前后差异**（Step 5 的输出贴进去）。

- [ ] **Step 1: 写失败的测试**

在 `tests/test_cli_status.py` **末尾**追加：

```python
def test_shoutu_table_reads_authoritative_history_not_local_sample():
    """**守卫**：逐标的表必须读**服务端权威源**，不是本地 06:30 采样表。

    第 12.28 条②：`config.py:287-288` 明确两者口径不同、**不要混用**
    （spec §5.4）。原实现读 `load_shoutu_fng()`（本地采样）⇒
    表里显示的档位可能和生产实际用的**不是同一份数据**。
    """
    import inspect

    from fg_system import cli
    src = inspect.getsource(cli._print_shoutu_cores)
    assert "load_shoutu_history()" in src, "没有读服务端权威源"
    assert "load_shoutu_fng()" not in src, \
        "仍在读本地 06:30 采样表 —— 与生产信号源不是同一份数据"
```

- [ ] **Step 2: 跑测试，确认失败**

Run:
```bash
cd /d/3-code/learning_backtrader && PYTHONUTF8=1 py -3.10 -m pytest tests/test_cli_status.py -q -k "authoritative" --tb=short
```
Expected: FAIL —— `没有读服务端权威源`

- [ ] **Step 3: 改取数**

在 `fg_system/cli.py` 的 `_print_shoutu_cores` 里，把原来的：

```python
    sw = loader.load_shoutu_fng()
    if sw.empty:
        return
```

改为：

```python
    # ⚠️ 2026-09-29（第 12.28 条②）：改用**服务端权威源** `shoutu_history.csv`。
    #    `config.py:287-288` 明确：`shoutu_history.csv` 是**服务端权威日值**，
    #    `shoutu_fng.csv` 是**本地 06:30 采样**，两者**口径不同、不要混用**（spec §5.4）。
    #    原来读后者 ⇒ 表里显示的档位可能和生产实际用的**不是同一份数据**。
    # ⚠️ **这是行为变更**：显示的数字会变。已单独提交并记录前后差异。
    hist = loader.load_shoutu_history()
    if hist.empty:
        print()
        print("=== 守猪待兔逐标的系数（第 12.26 条 丙）===")
        print("（服务端权威源 shoutu_history.csv 为空 —— 请先跑 fetch_shoutu_history.py）")
        return
    try:
        sw = shoutu_variants.shoutu_wide_from_long(hist, config.SHOUTU_SYMBOLS)
    except ValueError as exc:
        print()
        print("=== 守猪待兔逐标的系数（第 12.26 条 丙）===")
        print("（权威源不可用：%s）" % exc)
        return
```

并在 `_print_shoutu_cores` 的局部 import 区（原第 85-89 行）补一行：

```python
    from fg_system import shoutu_variants
```

- [ ] **Step 4: 跑测试，确认通过**

Run:
```bash
cd /d/3-code/learning_backtrader && PYTHONUTF8=1 py -3.10 -m pytest tests/test_cli_status.py -q --tb=short
```
Expected: PASS

- [ ] **Step 5: 记录前后差异（必须）**

Run:
```bash
cd /d/3-code/learning_backtrader && PYTHONUTF8=1 py -3.10 -m fg_system.cli status 2>/dev/null | sed -n '/守猪待兔逐标的系数/,/回测结果不变/p'
```
Expected: 能跑出表。**把这一整段输出贴进 `docs/trading-discipline.md` §12.28**，
并写明与 Task 4 Step 5 那次的差异（尤其：哪些标的的档位变了、
`AXTX` / `CRCG` 是否显示为缺值 —— 服务端对这两只**无历史**，见 `logs/shoutu_daily.log`
的「服务端无历史的标的：AXTX / CRCG」）。

- [ ] **Step 6: 提交**

```bash
git add fg_system/cli.py tests/test_cli_status.py docs/trading-discipline.md
git commit -m "change(cli): 逐标的表改用服务端权威源 shoutu_history（行为变更：显示数字会变，§12.28②）"
```

---

## Task 6: 逐标的**动作** —— 只登记设计与启动闸门，**不实施**

**Files:**
- Modify: `docs/trading-discipline.md`（在 §12.28 末尾追加一小节）
- 无代码改动。

**为什么不做**：第 8 条要求「再回测」。而逐标的动作的输入是守猪待兔信号，
它**只有 6 天历史** ⇒ **无法回测**（§12.26 Q4 的原始判定：
「该信号无法回测 ⇒ 第 8 条流程的『回测』这一步**做不了**」）。
强行实施 = 接入一个**未经验证**的信号，且违反「一次只改一件事」与「不凭回测挑参数」。

- [ ] **Step 1: 在 §12.28 末尾追加设计与闸门**

```markdown
#### 12.28-B：逐标的**动作** —— 设计已定，**启动闸门未满足**（不实施）

**需求**：现在只有「市场级一个总仓位」+「逐标的静态权重」，
没有「相对**你当前持仓**，每个标该买/卖多少」。

**已具备的零件**（不用新写）：
- `pipeline.weighted_targets()`（`pipeline.py:405-413`）已能把市场级目标按权重
  拆成**逐标的 target** —— 但**全库无生产调用方**（只在测试里出现）。
- `pipeline.risk_weight_series()` 给逐标的权重；
  `pipeline.shoutu_symbol_index()` / `saturation_of()` 给逐标的档位与饱和度。
- 持仓明细在 `Data/trade_log.csv`（`loader` 已能读）。

**缺的三样**（这才是真正的工作量）：
1. **持仓快照**：需要一个「当前持仓」的权威来源。`trade_log.csv` 是**人工记录**的
   交易流水（第 12.19 条实测有缺口：YINN 缺 107 股等），**不足以**作为持仓真相。
   ⇒ 需先定义「持仓从哪来」（券商导出？手工快照？）—— 这是**用户决策**。
2. **动作口径**：`weighted_targets` 只给 target，不给「现在动多少」。
   需要定义：按 target 与当前持仓的差额、还是按档位变化触发？两者结果不同。
3. **最小变动阈值**：避免每天产生微小调仓（§7.1 的换手纪律）。

**启动闸门（两条**同时**满足才启动）**：
1. 守猪待兔历史 ≥ `RANK_WINDOW`（756 个交易日）⇒ 分位数口径生效、
   且**首次**具备回测条件；
2. 用户明确「持仓快照从哪来」。

**在此之前**：不改任何代码。理由同 §12.26 Q4 与 §8 ——
**接入一个无法回测的信号，不是改进，是把不确定性搬进生产。**
```

- [ ] **Step 2: 提交**

```bash
git add docs/trading-discipline.md
git commit -m "docs(discipline): §12.28-B 逐标的动作的设计与启动闸门（数据不足，不实施）"
```

---

## 自审（Self-Review）

**1. 需求覆盖**

| 用户提出的 | 对应任务 |
|---|---|
| 「确认行情历史没在跟每日任务更新」 | Task 1 / Task 2（并已在 §12.28③ 记录确认结论） |
| 「每个标的最新的投资建议」（覆盖面） | Task 4 |
| 口径不一致（读采样表而非权威源） | Task 5 |
| 逐标的**动作** | Task 6（**只登记，不实施** —— 数据不足，已写明闸门） |
| 第 8 条「先文档」 | Task 0 |

**2. 占位符扫描**：无 `TBD` / `TODO` / 「类似 Task N」；每个代码步骤都给了**完整代码**。

**3. 类型与命名一致性**：
- `pipeline.signal_wide(wide)` —— Task 3 定义、Task 4 调用，**同名同参**。
- `pipeline._crypto_close(symbol)` —— Task 3 定义，仅在 `signal_wide` 内使用。
- `config.GDXU_UNDERLYING_COLUMN` / `config.SIGNAL_UNDERLYING_MAP` /
  `config.SHOUTU_SYMBOLS` / `config.ZONE_SATURATION` —— 全部为 `config` 里**已存在**的名字。
- `shoutu_variants.shoutu_wide_from_long(hist, symbols)` —— Task 5 调用，
  签名与 `fg_system/shoutu_variants.py:45` **一致**。

**4. 已知风险（实施者必须知道）**
- Task 4 Step 5 与 Task 5 Step 5 的**数值必须比对**：前者要求「不变」，
  后者要求「变了并记录」。若 Task 4 的数值变了 ⇒ 是 bug，必须回退。
- `AXTX` / `CRCG` 在服务端**无历史**（`logs/shoutu_daily.log` 实测）
  ⇒ Task 5 之后这两只在表里**会缺行**，这是**预期**，不是 bug。
- Task 1 Step 3 与 Task 2 会**写 `Data/raw/prices.csv`**（追加真实行情行）
  ⇒ 跑之前确认这是允许的（它会改变 `keep` 包的内容）。

---

## 执行交接（Execution Handoff）

**Plan complete and saved to `docs/superpowers/plans/2026-09-29-shoutu-per-symbol-advice.md`. Two execution options:**

**1. Subagent-Driven（推荐）** —— 每个 Task 派一个全新的子代理，任务之间我来评审，迭代快。

**2. Inline Execution** —— 在当前会话里按 `executing-plans` 批量执行，带检查点。

**选哪种？**

> 另外：**Task 1 / 2 / 3 / 4 / 5 各自独立**，可以只做其中几件。
> 最小可交付是 **Task 4**（覆盖面，改一行循环 + 两个守卫），但它**依赖 Task 3**（单源上移）。
> **Task 6 不需要执行**（它是"不实施"的记录）。
