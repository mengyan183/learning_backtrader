# Windows 端回传 · 2026-10-12

> 本文件**故意**放在 `docs/notes/` —— 用于验证 2026-10-12 用户定案的约定：
> note 类内容走**仓库内 `docs/` 路径**即可命中白名单
> （`scripts/fg_sync_ingest.py:39` `ALLOWED_DIRS = {fg_system, scripts, tests, evolution, docs}`）
> ⇒ Mac 端自动入库，无需人工归档。约定已写入 `docs/dual-end-workflow.md` §C 打包段。

## 1. 本轮状态：无待做任务

| 来源 | 结论 |
|---|---|
| `docs/windows-tasks.md` | WT-01~**WT-13** 全部 ✅（文件 10293 字节，与本轮前完全一致 ⇒ 未新增） |
| `docs/blocked-registry.md` | 非等待型条目全部完成（C-1~C-11 ✅ / D-1~D-3 ✅）；B 系列只剩数据积累等待型 |
| `docs/roadmap.md` 规划 17 项 | 除 R1.1（Mac 进行中）、R1.4/R1.6/M2.1/M2.2（均需 Data）外全部 ✅ |

⇒ Windows 端**无待做项**，本轮未产生代码改动。

## 2. 上轮自查缺口 #3 已闭环 ✓

- **发现**（Windows 自查 2026-10-12）：`fg_system/cli.py:281-283` 硬编码回测基准数字，
  源码自带注释「改动加密层配置时**必须同步更新此字符串**」⇒ 人工同步耦合。
- **Mac 处置**：`585ab27 fix(cli): 回测基准收口 config.BACKTEST_BASELINE 单一事实源`
  —— 新增 `config.BACKTEST_BASELINE` + `tests/test_cli_baseline_guard.py`（守卫测试强制校验）
  + `docs/windows-selfcheck-2026-10-12.md` 留痕。**采纳并落地 ✓**
- 同批 `7244502`：15 份变体提案批量 **Z（观察）** 归档，生产权重不变。

## 3. 同轮撤回的 2 个**伪缺口**（留证，避免后人重复误报）

| 位置 | 为何**不是**缺口 |
|---|---|
| `scripts/futu_realtime.py:327` `"/tmp/fg_realtime.lock"` | 该函数 `import fcntl`（**Unix-only**）+ docstring「防 **launchd** 多实例」⇒ **纯 Mac 守护脚本**；`/tmp` 是合法绝对路径，符合 `AGENTS.md` §6.4（该条只要求「绝对路径或 `$TEMP/`」，未禁止 `/tmp`） |
| `scripts/_kb_add_wechat.py:28` `Path("/tmp/wx_article.txt")` | docstring 自述「**一次性入库**」+ 依赖 Mac 本机 ChromaDB/Ollama ⇒ Mac 侧脚本 |

⇒ **判据**：判断"是不是跨端 bug"要看**运行环境**，不是看写法。

## 4. 遗留（待 Mac 指示）

本地 `scripts/push_todo.py` 与 `docs/windows-agent-prompt.md` 经
`git show origin/main:<path>` + `diff` 实测为**本地落后**（Mac 版 `push_todo.py`
已含"说明摘要"，正是待办快照里 WT 行说明的来源）⇒ 建议**以 Mac 版覆盖本地**，
避免双端漂移（本地改动已被 Mac 版取代）。
