# Windows 端回传 · 2026-10-12（十）WT-26 完成 —— sensitivity_scan 产物带 OOS 红线显式警示

> 用户裁决（2026-10-12）：**方案②** —— 不改扫描逻辑，改为在**输出物**上显式声明
> 「本产物**不得作为调参依据**」+ OOS 红线提示。理由：改动小、当天可闭环。
> 本说明即该任务的**文档登记**（验收要求「② 输出物含显式警示且**文档登记**」）。

## 1. 为什么不是方案①

`scripts/sensitivity_scan.py::main()` 用**整段** `features` 跑 `pipeline.run()` 与
`runner.run_single`，**没有任何 train/OOS 切分** ⇒ 「只测量不改参」此前**只写在 docstring 里**，
产物本身看不出来，容易被当成调参依据。

方案①（显式切分：扫描只用 IS、OOS 仅终验一次）需要先裁决用哪个 OOS 口径
（纪律声明口径 `config.IS_START/IS_END` vs 研究产物口径 `evo_meta.oos_start()`，
WT-18 明令二者不得混用）⇒ 属**新功能**、改动大。
**用户裁定走方案②**：不改扫描逻辑，只在产物上把红线讲清楚。

## 2. 方案②落地位置

| # | 位置 | 内容 |
|---|---|---|
| 1 | `scripts/sensitivity_scan.py::oos_warning(split)` | 按 `split` 生成红线警示文本（唯一来源） |
| 2 | 每张表 `evolution/sensitivity/sensitivity_<组>_<标的>.md` | **文件头**写入警示（`write_report()` 内，标题/评估区间下方、表格上方） |
| 3 | 汇总 `evolution/sensitivity/README.md` | **文件头**写入警示（`main()` 汇总段） |
| 4 | 模块 docstring | 增「⚠️ OOS 红线」段，指向 `oos_warning()` |
| 5 | `stdout` | 扫描时逐表打印 `⏳ 扫描 …（split=…）`，并在 `--split oos` 时打印终验产物路径 |

> ⚠️ 本脚本**没有独立产物文件**（表是 `.md`、汇总是 `README.md`），警示直接写进
> **这两个产物文件的头部**，人打开就第一眼看到，**无法被忽略** ✓。

### 警示文字原文（`--split is`，扫描默认口径）

```
> ⚠️ **OOS 红线：本表只覆盖 IS（样本内），不得据此直接调参**
> 评估区间 = IS（纪律声明口径 `config.IS_START ~ IS_END`）：<IS_START> ~ <IS_END>
> IS 上的敏感性只说明「参数在样本内怎么变」，**不含**任何样本外证据。
> 参数变更必须走阶段 2 变体 → **OOS 终验一次**（`--split oos`）→ 人工审批（`docs/trading-discipline.md` 第 8 条）。
```

### 警示文字原文（`--split oos`，定稿参数终验口径）

```
> ⚠️ **OOS 终验产物 —— 只允许验收一次，禁止据此反复调参**
> 评估区间 = OOS（研究产物口径 `baseline.json` 的 `meta.is_oos.oos_start`）：<oos_start> ~ 数据末尾
> 本表用于**已定稿参数的终验**；一旦反复扫参再挑结果，OOS 即被污染、失去证据力。
> 终验通过后走人工审批（`docs/trading-discipline.md` 第 8 条）。
```

⚠️ 文案里**不写任何字面日期**（IS 读 `config`、OOS 读 `evo_meta`）——
`tests/test_oos_single_source.py` 会全仓扫描源码（**注释也算** ✗），写字面日期会立刻红。

## 3. 守卫测试（后人删掉警示会立刻红）

| 测试 | 断言 |
|---|---|
| `test_outputs_carry_oos_warning` | 表 + README **都**含 `OOS` / `调参` / (`禁止`\|`不得`) |
| `test_warning_states_the_split_in_use` | is / oos 两套文案**不同**，且 is 文案含 `config.IS_END` |

## 4. WT-17 补测试（同一入口）

`tests/test_sensitivity_scan.py` 覆盖：`--help`/参数解析、**无数据路径退出 2**、
mock 扫描输出格式，外加「只测量不改参」不变量（不写回 `config.py`、不往 `Data/` 写产出、
`finally` 还原 config）。

**本轮新增 2 条**无数据路径用例（WT-17 验收「无数据路径实测退出 2」）：

| 测试 | 场景 |
|---|---|
| `test_missing_prices_file_exits_2` | `raw/prices.csv` 缺 ⇒ 退出 2（原为裸 `FileNotFoundError`） |
| `test_pipeline_data_missing_exits_2` | 扫描期 `pipeline.run` 读 raw 失败（如缺 `raw/putcall.csv`）⇒ 退出 2 |

## 5. 实测（Windows 本地 Python 3.10）

```
$ py -3.10 -m pytest tests/test_sensitivity_scan.py -q
29 passed
```

**无数据路径实测（真实环境，`Data/raw/putcall.csv` 缺失）**：

```
$ py -3.10 scripts/sensitivity_scan.py
……
❌ 缺少扫描所需数据文件：[Errno 2] No such file or directory:
   '…\Data\raw\putcall.csv'（先跑 pipeline 生成 raw 数据）
EXITCODE= 2          ← 修复前是 1 + 裸 traceback
```

## 6. 请 Mac 执行

1. 复核本说明 + `scripts/sensitivity_scan.py` 第 132-149（`oos_warning`）/ 249-266
   （`write_report` 写表头警示）/ 326-345（扫描 + 无数据退出 2）/ 359-366（README 警示）行 ⇒ 若通过，
   把 `docs/windows-tasks.md` 的 `WT-26` 状态列改为 ✅
2. 确认警示是否还需写进其它产物（如 OOS 终验 CSV 是否需要同款表头注释）
