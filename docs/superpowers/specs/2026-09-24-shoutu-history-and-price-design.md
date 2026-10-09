# 守猪待兔：历史数据回填 + 前向文件补 `price`（Step A）

- **日期**：2026-09-24
- **状态**：设计已获用户批准，待实施
- **关联**：第 8 条流程（先文档 → 再代码 → 再回测）、第 12.26 条 Q4（历史数据不可得）、第 14.5 条（守猪待兔自动化）
- **后续**：Step B（用本步落地的数据回测量化"早清仓代价"）**另立 spec**，不在本文范围

---

## 1. 背景

### 1.1 触发：用户自述的一个行为缺陷

> 我可以根据贪恐指数和下跌幅度控制加仓频率，且不会主动割肉；在低谷时可以苟住，
> 但是在上涨阶段**拿不住**，很容易贪恐指数**刚上 60**，就开始分批卖出了。

### 1.2 这个缺陷在系统里就是一条规则（不是执行偏差）

`loader.shoutu_to_system_scale` 把守猪待兔量程 `(x+100)/2` 映射到系统口径，而该映射
**刻意**与 `ZONE_EDGES = [20, 40, 60, 80]` 对齐（`loader.py:253` 原话：
「用户定义的贪婪线 60 → 80 …与 `ZONE_EDGES` 的 80 **边界精确重合**」）：

| 守猪待兔 | 系统口径 | 档位 | 核心仓饱和度 |
|---|---|---|---|
| −60（恐惧线） | 20 | 1 | 0.75 |
| −20 | 40 | 2 | 0.50 |
| **+20** | 60 | 3 | **0.25** |
| **+60（贪婪线）** | 80 | 4 | **0.00 ← 清仓** |
| +100 | 100 | 4 | 0.00 |

⇒ 守猪待兔一过 **+60**，目标仓位归零；而 `MAX_SINGLE_ADJUST = 0.30`
（单次调仓最多走完 30% 的差距）使其**分几天卖完** —— 正是用户感到的「分批卖出」。
（更早：`+20` 时已砍到 0.25。）

**对照**：**加密**路径的减仓线是 `CRYPTO_GREED_TIERS = [85, 90, 95]`
（减至 2/3、1/3、1/4）。**系统里本来就存在一个"拿得住"的对照组**，只是两个市场不对称。

`ZONE_EDGES` 在设计文档里只写了「**沿用 v1 §7.2**」，**没有标定依据** —— 是继承来的默认值。

### 1.3 用户裁决

**先量化，再决定是否改规则**（选 C）。而量化的前提是**历史数据**。

---

## 2. 关键发现（2026-09-24 实测）：历史数据**可得**

### 2.1 官方接口文档**没有**历史端点

`docs/查询实时贪恐.docx` 全文只有 **1 个端点**：
`POST /api/partner/invest/stock/scan`（`code` / `lever` / `emo_area` → 实时
`score` / `price` / `time`）。**无任何时间/区间/历史参数。**

### 2.2 网页端有「历史贪恐指数」页（此前只知 App 有）

- **路由**：`https://fe.szdt.tech/invest/#/stock_detail?code=<CODE>`
- **端点**：`GET https://szdt.tech/api/invest/stock_emotion/history?code=<CODE>`
- **载荷**：`{"status":1,"msg":"成功","data":[{"score":-75,"price":"35.220","date":"2024-08-16"}, …]}`
- 页面同时渲染**全量分位数分布**（11 个桶的天数 + 占比）、当前值、
  `近100天 / 近1年 / 全部` 切换、`导出`（png）

**发现路径**（可复用）：主 bundle 里枚举路由 → 27 条 → 定位 `/stock_detail` 的
懒加载 chunk → 从 chunk 里挖出端点字符串。
（`_historyX/_historyY/_historyTime` 是**滚动手势库**的变量，与图表无关，已排除。）

### 2.3 覆盖矩阵（实测）

| 标的 | 历史天数 | 起始日 | 备注 |
|---|---|---|---|
| **TQQQ** | **625** | 2024-04-23 | ✅ 系统在用 |
| **UPRO** | **625** | 2024-04-23 | ✅ 系统在用 |
| **SOXL** | **587** | 2024-06-17 | ✅ 系统在用 |
| CONL | **543** | 2024-08-16 | ✅（响应 `complete=true`，27,364 B） |
| AXTX | **0** | — | ❌ 服务端 `data: []` |
| CRCG | **0** | — | ❌ 服务端 `data: []` |
| YINN / GDXU | 待测 | — | 仓库已有分布记录（623 / 580 天） |

⇒ **系统自己在用的三个标的全都有 587~625 天逐日 `score` + `price`。**

### 2.4 直连**不可行** —— 前端用登录会话鉴权

| 方式 | 结果 |
|---|---|
| 无鉴权 `fetch` | `{"status":2,"msg":"参数校验失败，IP 已记录"}` |
| `X-Auth: <32 位会员激活码>`（partner 那套） | **同样** `参数校验失败，IP 已记录` ⇒ 前端端点**不认**激活码 |
| **浏览器路径**（挂钩页面自身 XHR） | ✅ **抓到完整响应体**（543 条，`complete=true`），**零凭据** |

### 2.5 这对 C（量化）意味着什么

原本要造代理（市场指数 / 加密情绪指数）或等前向积累。**现在都不需要**：
有 543~625 天逐日 `score + price` ⇒ 可**直接回测**守猪待兔驱动的仓位规则。

⚠️ 一个限制：`RANK_WINDOW = 756` 日，625 天**还不够**触发分位数口径
（差约 131 个交易日 ≈ 半年）⇒ 丙的 `percentile` 仍会回退 `fixed`。
但**量化"早清仓代价"这个 C 任务，543~625 天完全够**。

---

## 3. 目标 / 非目标

### 目标（Step A）

1. **A1**：把服务端全量历史落成 `Data/raw/shoutu_history.csv`
2. **A2**：给 `Data/raw/shoutu_fng.csv` 补 `price` 列（供后续 price × 贪恐指数对照）

### 非目标（明确不做）

- ❌ 不改 `pipeline` / `config` / 任何策略规则
- ❌ 不改每日抓取任务（`shoutu_daily.cmd` / `.sh`）
- ❌ **不把历史写进 `shoutu_fng.csv`** —— 那会让 `pipeline` 立刻看到 625 天守猪待兔数据
  ⇒ **改变回测结果** ⇒ 属于 **Step B**（策略改动），不是本步
- ❌ 不做回测、不做阈值对比（Step B）
- ❌ 不支持手动录入带 price 的语法（`CONL=24@6.79`，YAGNI）

---

## 4. 设计 A1：历史回填

### 4.1 抓取方式

新增 `scripts/fetch_shoutu_history.py`：

1. bsk 打开 `#/mine`（进入应用）
2. **挂钩 `XMLHttpRequest.prototype.open/send` 与 `window.fetch`**，
   **只记录** URL 含 `stock_emotion/history` 的响应体（其余一律丢弃）
3. 对每个标的一次 `location.hash = "#/stock_detail?code=<CODE>"`（SPA 内切路由，
   强制组件重挂载 ⇒ 触发一次请求）
4. 解析 → 落盘 → 下一个标的

**为什么不直连**：前端端点用**登录会话**鉴权（见 2.4）。会话凭据属**凭据**，
按 browser-skill 规则**不得提取**；挂钩页面自身请求则**完全不接触凭据**。

### 4.2 为什么是"挂钩"而不是"读 DOM"

页面 DOM 只暴露**分布**（11 个桶的天数与占比），**逐日时序只在图表 canvas 里**
⇒ 读 DOM 拿不到本步要的时序。挂钩是唯一能拿到完整数组的方式（已实测）。

### 4.3 落盘

`Data/raw/shoutu_history.csv`，长表：`date,symbol,score,price`

- **幂等**：同 `(date, symbol)` 覆盖（同 `record_universe` 的模式）
- 排序：按 `(date, symbol)` 落盘，使 diff 稳定

---

## 5. 设计 A2：`shoutu_fng.csv` 加 `price`

### 5.1 price 从哪来：三条路径**都已经拿到，只是丢掉了**

| 路径 | 已有字段 | 现状 |
|---|---|---|
| 分类表（`#/mine`） | `parse_universe_rows` 产出 `price` 列 | 只取了 `fg_index` |
| 个股贪恐查询面板 | `parse_scan_result` 返回 `price` | 只取了 `value` |
| partner API | `parse_score_payload` 返回 `price` | `collect_scores` 只留 `score` |

⇒ **不需要新数据源**，只需把已有的传下去。

### 5.2 ⚠️ 一个必须改的关键实现点（否则 price 会被**静默**丢掉）

`append_records` 现在**从宽表重读旧数据**再 melt：

```python
old = loader.load_shoutu_fng(path)          # 宽表，只有 value
old_long = old.reset_index().melt(...)      # ⇒ 旧行的 price 在这里丢失
```

⇒ 必须改成读**长表**（保留全部列）：

- 新增 `loader.load_shoutu_records(path)` → 长表；**缺 `price` 列时补 NaN**（兼容现有 3 列文件）
- `append_records` 改用它做合并；**返回值仍是宽表**（契约不变）
- **`load_shoutu_fng` 完全不动** ⇒ `pipeline` / `evolution` / `recorded_symbols` **零改动**

> 依据：`loader.py:245` 的 `pivot_table(..., values="value")` 显式只取 `value` 列，
> 所以加列不影响它的输出。这是本设计"pipeline 零改动"的**证明**。

### 5.3 列与语义

```python
RECORD_COLUMNS = ["date", "symbol", "value", "price"]
```

| 项 | 设计 |
|---|---|
| 幂等键 | 仍是 `(date, symbol)`；`price` 随 `value` 一起覆盖 |
| 兼容 | 旧 3 列文件读进来 `price = NaN`，**不报错**；已有 3 行自然为 NaN |
| 校验 | **price 不参与**量程/白名单校验 —— 它是**参考量，不是信号** |
| price 不可解析 | **置 NaN，不报错**（避免价格源抖动把整次抓取搞挂） |
| 手动录入 | `cli shoutu-record --values "CONL=24"` 的 price 保持 **NaN** |
| 自动路径 | 分类表 → 新增 `universe_prices(df)`；查询面板 → 用 `parse_scan_result` 的 `price`；API → 新增 `collect_score_records()` 保留 price（**`collect_scores` 契约不动**） |

### 5.4 与 `shoutu_history.csv` 的分工（口径必须可追溯）

| 文件 | 含义 | 来源 |
|---|---|---|
| `shoutu_history.csv`（新） | **服务端权威日值**（带 price） | `stock_emotion/history` |
| `shoutu_fng.csv`（改） | **前向 06:30 采样**（本地约定，带 price） | 每日抓取 / 手动录入 |

两者**采样口径不同**（服务端日值 vs 本地固定时刻快照）。混进一张表，
"某天的值到底是哪个口径"就再也答不上来 —— 而本仓库的原则是**口径必须可追溯**。
⇒ **是否合并/替换 `shoutu_fng.csv` 的角色属于后续决策**（Step B 或独立 spec）。

---

## 6. 失败语义

| 场景 | 处理 | 理由 |
|---|---|---|
| 某标的返回 `data: []`（AXTX/CRCG） | **打印告警，不算失败**，该标的不写入 | 服务端确实没有它们的历史；失败会掩盖"其余标的是好的"这一事实 |
| 某标的请求超时/未捕获到响应 | **抛错**（非零退出） | 与 `fetch_scan_scores` 一致：静默跳过会让数据悄悄缺失 |
| `score` 越界 | **抛错** | 复用 `shoutu_to_system_scale` 的既有口径：越界说明口径变了，不静默截断 |
| `score` 非数值 | **抛错** | 不静默变 NaN |
| `price` 非数值 | **置 NaN** | price 是参考量（见 5.3） |
| 落盘路径不存在 | 创建目录（同 `append_records`） | — |

---

## 7. 测试策略

沿用 E1 的分工原则：**纯解析/落盘放库里（离线可测），bsk 编排放脚本里**。

新增 `tests/data/test_shoutu_history.py`（实测 **16 条**）：

- 解析：正常载荷 / `data: []` / `status != 1` / 缺 `score` / `score` 非数值 /
  `score` 越界 / **`date` 不可解析** / **`price` 非数值 ⇒ NaN** / **未知标的 ⇒ 抛错**
- 落盘：创建并排序 / **幂等**（同日同标的重复不产生重复行）/ 服务端修订时**覆盖** /
  多标的共存 / **空表 no-op（不创建文件）**
- 读：文件不存在返回空 / roundtrip
- 脚本层：**静态 AST 守卫**（只记录 `stock_emotion/history`，见 §9.2）

> ⚠️ **未自动化**：本表原第 4 行「AXTX 空历史由**脚本打印告警**」—— 库层的空表 no-op
> **已测**（`test_record_history_empty_is_noop`），但**脚本层的打印**要跑 `bsk`
> 才能验证 ⇒ 当前**无自动化覆盖**，只有 §14.5 的一次实机运行作为证据。

> **列名约定**：历史文件用**源字段名** `score`（`date,symbol,score,price`），
> 前向文件用 `value`（`date,symbol,value,price`）。两者含义相同、列名不同 ——
> 这是**刻意的**：各自对齐其数据源的字段名，便于追溯。
> 将来若要在 Step B 合并，必须**显式改名**，不要靠"看起来一样"。

`tests/data/test_shoutu_record.py` 补 A2：

- `mapping_to_frame` 产出 4 列，未给 price 时为 NaN
- `append_records` **保留旧行的 price**（回归红线：防止 5.2 那个静默丢失）
- 读**旧 3 列文件**不报错、price 为 NaN
- price 非数值置 NaN 而不报错

脚本层：**静态守卫**（读源码 AST 断言必须走库函数、不得把标的写成字面量），
同 `test_shoutu_page_query.py` 的做法。

---

## 8. 向后兼容

| 对象 | 影响 |
|---|---|
| `loader.load_shoutu_fng` 输出 | **不变**（仍 `date × symbol` 的 value 宽表） |
| `pipeline.shoutu_symbol_index` / `evolution` / `recorded_symbols` | **零改动** |
| 现有 `shoutu_fng.csv`（3 列） | 可读，price = NaN |
| `cli shoutu-record` 输出 | 多一列（宽表不变，`wide.to_string()` 不受影响） |
| `collect_scores` 契约 | **不变**（新增 `collect_score_records` 作为带 price 的兄弟函数） |

---

## 9. 风险、未知与教训

### 9.1 未知（本步顺带记录，不阻塞）

- **历史端点是否消耗额度**：未知。抓完后可用页面 `#/stock_scan_history`（额度使用明细）
  核对前后差值
- **YINN / GDXU 覆盖**：顺带测，补齐矩阵

### 9.2 ⚠️ 安全发现（务必遵守）

- `/api/invest/license/info` 的响应里含**明文凭据**（会员 `token`、钉钉机器人 `dd_token`、
  `code` 等）。**抓包内容不得外贴、不得入库**。
  本设计的所有代码**只读 `stock_emotion/history`**，对其它端点**不记录、不保存**。

### 9.3 过程教训（本轮实际踩到，记下来防复发）

调查鉴权方式时，我触发了若干次 `参数校验失败，IP 已记录`
（3 次浏览器内无鉴权 + 4 次用激活码试前端端点）。
这**违反**了第 14.5 条「不要盲试接口」的纪律 —— **第一次看到该提示时就该停手**。
后果：服务端可能记录了开发机 IP（额度未消耗，仍为 28）。
⇒ **规则：任何返回「参数校验失败，IP 已记录」的调用，出现一次即停止该方向的探测。**

### 9.4 ⚠️ Step B 的**输入缺口**（免得后来人以为"数据已齐，直接回测即可"）

Step A 产出的是**逐日 `score` + `price`**。这**足以**回答"守猪待兔在 +60 以上清仓、
后来涨了多少"这一个问题，但**不足以**做完整回测：

1. **成本假设**（佣金 / 滑点 / 汇率）—— 量化"分几天卖完 vs 一次卖完"的价差会被
   成本吃掉多少。没有成本口径，结论不可比。
2. **基准** —— buy & hold 同标的的收益。没有基准就无法说"早清仓**付出了**多少"。
3. **`MAX_SINGLE_ADJUST=0.30` 的路径依赖** —— 每天实际卖多少取决于**前一天的
   实际仓位** ⇒ Step B 需要**逐日状态机回放**，不能只做 `score → 目标仓位` 的
   静态对照。
4. **`RANK_WINDOW=756` 未满足**（见 §2.5）—— 625 天不足以触发分位数口径 ⇒
   丙仍回退 `fixed`。这不是缺口而是**已知约束**：Step B 用 `fixed` 口径即可，
   与 percentile 无关。

### 9.5 未验证项（汇总，供后来人别当既成事实）

| 项 | 状态 |
|---|---|
| 历史端点**是否消耗额度** | **未验证**（§9.1；抓取期间额度读数仍 28，但两套额度未必同源） |
| **前向 06:30 采样 vs 服务端日值**口径是否相同 | ✅ **已结案（2026-09-24）：不相同** —— 实测最大差 **8 点**，GDXU 两天方向相反 ⇒ 两套文件并存是**必要的**，Step B 必须用服务端日值 |
| 端点逐日数组 与 App 分布桶「历史天数」**口径是否相同** | **未验证**（只观察到三个标的一律 +2 天，属弱旁证） |
| 脚本层"AXTX 空历史打印告警" | **无自动化覆盖**（需跑 bsk） |

---

## 10. 实施任务清单

1. **A1 库层**：`fg_system/data/shoutu.py` 新增 `parse_history_payload()` +
   `record_history()`（+ 测试，TDD）
2. **A1 loader**：`loader.load_shoutu_records()`（长表，兼容缺列）（+ 测试）
3. **A1 脚本**：`scripts/fetch_shoutu_history.py`（bsk + XHR 挂钩编排）+ 静态守卫测试
4. **A2 库层**：`RECORD_COLUMNS` 加 `price`；`mapping_to_frame(prices=...)`；
   `append_records` 改用 `load_shoutu_records`（+ 测试，含"保留旧 price"回归）
5. **A2 取价**：`shoutu.universe_prices()`；`collect_score_records()`
6. **A2 接线**：`fetch_shoutu.py` 与 `fetch_shoutu_api.py` 把 price 传下去
7. **文档回写**：`docs/trading-discipline.md` 第 12.26 / 14.5 条记录本步结论
8. **验证**：全量 `pytest` + 真机跑一次 `fetch_shoutu_history.py`（只读页面）

---

## 11. 实施后需回写 `trading-discipline.md` 的事项

1. **历史数据从"不可得"改为"可得"** —— 第 12.26 条 Q4 的判定被**取代**（不是推翻：
   当年三条路确实不通，现在是**第四条路**：网页端历史页 + 挂钩抓取）
2. 端点与选择器、覆盖矩阵（625/625/587/543/0/0）
3. `shoutu_history.csv` 与 `shoutu_fng.csv` 的**口径分工**
4. 9.2 的安全提醒、9.3 的探测纪律
5. 丙（逐标的分位数）的阻塞**从"等历史"变为"等 756 日窗口"** —— 数据已可得，
   缺的只是长度（625 / 756）
