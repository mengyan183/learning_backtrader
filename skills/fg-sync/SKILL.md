---
name: fg-sync
description: 接收并还原飞书 base64 分片，把公司电脑/Windows 端同步来的文件安全追加到 Mac 本地贪恐仓库，白名单过滤 + 冲突中止，入库后自动跑 pytest 并回传结果。触发词：同步、还原、补传、backfill、base64、分片、公司端。
---

# fg-sync：飞书分片 → Mac 仓库安全同步

## ⚠️ 收到分片后的唯一正确动作（必须先读）

1. **禁止自行解码 base64**、禁止自己判断"是不是 xz"。分片是 URL-safe base64
   （含 `-`/`_` 字符），手动解码必错。
2. **把用户消息原文原样保存**到 `~/.openclaw/tmp/fg-sync-in/sync_in.md`（保留
   `###FG:…###` 标记和全部字符，一个字都不要改）。
3. **运行单命令**（不要分步、不要自己解析）：

```bash
cd /Users/xingguo/learning_backtrader
.venv/bin/python scripts/fg_sync_tool.py -f ~/.openclaw/tmp/fg-sync-in/sync_in.md \
  --commit "fg-sync: 公司端同步 <YYYY-MM-DD>"
```

4. **把脚本输出原样回传飞书**（成功/失败都回传，不要改写、不要补充解释）。

> 常见错误示范（都是错的，别这么做）：
> - 试图 `tool_call {"id":"fg-sync"}` —— fg-sync 是 skill 不是可调用工具。
> - 用标准 base64 解码 URL-safe 串（`-`/`_` 会被丢）→ 必然报"不是 xz"。
> - 只回"检查打包脚本"而不跑命令 —— 必须先跑命令看真实输出。

## 这个 skill 干什么

公司电脑把文件打成 base64 分片（`###FG:包名:序号/总数###…###FG:end###`）发到飞书
「海外投资助手」机器人；OpenClaw 收到这些消息后，把分片**全部存入一个目录**，
运行本 skill 的编排脚本完成：聚合校验 → 暂存解压 → 白名单过滤 → 冲突检查 →
入库（git add/commit/push）→ Mac pytest 验证 → 结果回传飞书会话。

**核心纪律：宁可中止，不可乱覆盖。** 白名单外的文件、与 Mac 本地未提交修改冲突的
文件，一律不碰；缺片、校验失败、路径穿越，一律报错中止。

## 第 1 步：收齐分片

- 用户消息含 `###FG:…###` 标记，或明确说「同步/还原/补传/backfill」+ 一段 base64 文本。
- **把所有分片消息原样合并**（不要过滤任何字符，昵称/时间戳由解析脚本按标记精确切，
  只有标记之间的 base64 才算内容），存成文件：
  - 多条消息 → 每消息一个文件，或全部拼进一个 `sync_in.md`；
  - 存放目录：`~/.openclaw/tmp/fg-sync-in/`（没有就建）。
- 分片不齐时**不要跑还原**，直接回传：`还缺第 X/N 片，请补发`。

## 第 2 步：运行编排脚本

```bash
cd /Users/xingguo/learning_backtrader
.venv/bin/python scripts/fg_sync_ingest.py ~/.openclaw/tmp/fg-sync-in \
  --commit "fg-sync: 公司端同步 <YYYY-MM-DD>"
```

退出码约定：
- `0`：全流程成功（文件已入库、pytest 通过或已说明跳过）。
- `2`：可解释失败（缺片/白名单拒绝/冲突/测试失败）——**按输出原样回传**，不要改判。
- `3`：内部错误——如实报告脚本报错。

## 第 3 步：按输出回传飞书

- 成功：回传
  `✅ 同步完成：N 个文件已入库并推送（<commit 前 7 位>），Mac pytest <结果>。`
- 白名单拒绝：回传被拒文件清单（`⛔ 不在白名单，未入库：…`），提醒只发代码/测试/文档。
- 冲突：回传冲突清单，并说明 `先在 Mac 提交/丢弃本地改动后再同步`。
- 缺片/校验失败：回传解析脚本的具体报错。

## 边界（必须遵守）

- **白名单**：只接受 `fg_system/**`、`scripts/**`、`tests/**`、`evolution/**`、
  `docs/**` 及根级 `README.md`/`AGENTS.md`/`pyproject.toml`/`requirements*.txt`/`Makefile`。
  拒绝：`Data/**`（密钥+运行态，含 newsapi_key）、`.git/**`、`.venv/**`、`__pycache__/**`、
  `*.pyc`、`*.key`、`*.secret`、`.env*`。
- **冲突即中止**：与 Mac 本地未提交修改交集 > 0 时绝不覆盖，列清单等确认。
- **不主动扩展**：只处理明确发来的同步内容；不顺手改其他文件、不跑其他任务。
- **密钥纪律**：任何 `key`/`secret`/`token` 文件一律拒绝入库；Data 下文件不经本 skill 同步。
- 还原脚本同时支持「云文档 .md 下载」形态（`restore_from_base64.py` 会去掉
  `\#`/`\+` 转义）——同一编排脚本可直接处理。

## 常用链路（供参考）

- 打包端（公司电脑）：`scripts/make_feishu_bundle.py`（分片 ≤8KB/条，含 52 片投递先例）。
- 解析核心：`scripts/restore_from_base64.py`（标记聚合/缺片检测/base64 解码）。
- 本 skill 编排：`scripts/fg_sync_ingest.py`（暂存解压→白名单→冲突→入库→pytest→回传）。
