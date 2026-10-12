# Windows 端回传 · 2026-10-12（二）工具同步 + 守卫修复

> 本文件同样放在 `docs/notes/` ⇒ 走白名单自动入库（约定见 `docs/dual-end-workflow.md` §C）。

## 1. 修复：`send_pkg_guarded.sh` 的**假成功**

**现象**（今日实测）：`sync_1012a` 5 片只发出 **3 片**，第 4 片崩：

```
RuntimeError: bsk press Enter --ref @e75 失败：browser rejected the underlying CDP call
  hint: … reloading the tab usually resets a stuck DevTools session
  details: {"code":-32000,"message":"Element is not focusable"}
DONE_RC=1
```

而守卫**照样打印「[脱离] 已启动」并 exit 0** ✗ ⇒ 假成功。

**根因**：守卫的判据是「15s 内日志非空」—— 但 `feishu_send` **一启动就打印「共 N 条」**，
那一刻日志就非空，与"发送是否成功"无关。

**修法**：先看有没有**终态**（`DONE_RC=`）——有则报真实结果（`DONE_RC=0` ⇒ 成功，
否则 ⇒ 失败并打印 `--start` 续发命令）；没有则只报「**已启动·结果未定**」并给出回读命令。
**验证**：拿今天那份**真实失败日志**跑新逻辑 ⇒ `DONE_RC=1` ⇒ 判失败 ✓ 与事实一致
（`bash -n` 语法检查通过）。

**教训**：**「启动了」≠「成功了」**；脱离执行的守卫必须回读**终态标记**，
不能停在"进程起来了"。这是本项第三次印证（前两次只是记录，这次真咬到）。

## 2. 恢复手段（已实测可用，留档）

| 场景 | 命令 |
|---|---|
| 中途崩，续发剩余片 | `py -3.10 scripts/feishu_send.py --pkg <包> --chat 海外投资助手 --start <下一片>` |
| 页面卡住（CDP `Element is not focusable`） | `feishu_send` **自带**「外壳没渲染，重载页面（第 N/4 次）」⇒ 通常自愈，**无需人工介入**（实测本轮 5/5 最终发齐） |
| 幂等性 | Mac 端 ingest 有 `.done` 内容 hash 标记 ⇒ **重发整包也安全** |

## 3. 补齐：文档写了、Mac 仓库里却没有的工具

`docs/dual-end-workflow.md:98` 明写「打包/校验/发送工具：`scripts/pack_many.py`、
`scripts/verify_pkg.py`、`scripts/send_pkg.py|bat`」，但实测：

```
scripts/send_pkg_guarded.sh : Mac 仓库 EXISTS（本次已更新 ⇒ 旧版需覆盖）
scripts/pack_many.py        : Mac 仓库 MISSING
scripts/verify_pkg.py       : Mac 仓库 MISSING
```

⇒ 本包一并补齐 4 个工具（`pack_many.py` / `verify_pkg.py` / `send_pkg.py` /
`send_pkg.bat`）+ 更新后的 `send_pkg_guarded.sh`，使**文档与仓库一致**。

## 4. 本轮总结（对应 `windows-tasks.md` 第 29 行「自查」授权）

- **无待做任务**：WT-01~13 全 ✅；blocked-registry 非等待型全完成；roadmap 规划 17 项
  只剩 R1.1（Mac 进行中）与 R1.4/R1.6/M2.1/M2.2（均需 Data）。
- **上轮自查缺口 #3 已由 Mac 闭环**（`585ab27`：`config.BACKTEST_BASELINE` 单一事实源
  + `tests/test_cli_baseline_guard.py`）。
- **note 路径约定已落实**（用户 2026-10-12 定案）：note 类内容放 `docs/notes/` ⇒ 命中
  `fg_sync_ingest.py:39` 的 `ALLOWED_DIRS`（含 `docs`）⇒ 自动入库，无需 Mac 人工归档。
- **遗留**：本地 `scripts/push_todo.py`、`docs/windows-agent-prompt.md` 实测**本地落后**
  （Mac 版 `push_todo.py` 已含"说明摘要"）⇒ 建议以 Mac 版覆盖本地，请指示。
