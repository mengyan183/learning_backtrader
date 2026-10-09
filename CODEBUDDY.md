> 本工程短名：`fg`（调用 codegraph_* 工具时带 `project="fg"`）

## 双层知识引擎 (CodeGraph + Graphify)

MCP server：`codegraph-multi`（多工程共用 1 个进程，用 `project` 参数选择工程；
`codegraph_projects` 可列出全部已登记工程）。

| 层 | 工具 | 用途 |
|----|------|------|
| L1 CodeGraph | `codegraph_search` / `codegraph_context` / `codegraph_impact` / `codegraph_stats` | 代码结构查询（符号/调用链/影响面） |
| L2 Graphify | `python .codegraph/build/graphify_ingest.py query/path/stats` | 背景知识追溯（概念关系/路径） |

代码搜索规则：符号/调用/引用查询优先 `codegraph_*` 工具，禁止先 grep；纯文本匹配才用 grep；
三方 jar 不在索引内需反编译。详细规则见 `.codebuddy/WORK-CONVENTIONS.md`。

## 本工程简介

恐惧贪婪指数交易系统（`fg_system` 包）：因子 → 情绪指数 → 信号 → 分层仓位组合 → 回测。
交易规则见 `docs/trading-discipline.md`（**第 8 条流程**：先文档 → 再代码 → 再回测 → 再验证）。
