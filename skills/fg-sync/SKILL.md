---
name: fg-sync
description: 收到含 ###FG: 标记的飞书消息时立即执行：先回"已收到"，把消息原文存文件，跑单命令 fg_sync_tool.py --quick 还原入库，把脚本输出原样回传。触发词：同步、还原、补传、backfill、base64、分片、公司端、###FG:。
---

# fg-sync：同步分片 → Mac 仓库（唯一动作，顺序不可改）

收到含 `###FG:` 标记或「同步/还原/补传」的消息，**只做以下 4 步**：

1. **先回一条短确认**：`✅ 已收到，正在还原入库，请稍候…`（不等结果）
2. **原样保存消息**到 `~/.openclaw/tmp/fg-sync-in/sync_in.md`（保留全部字符与标记，一个字不改）
3. **运行单命令**（禁止自行解码 base64、禁止分步解析）：

```bash
cd /Users/xingguo/learning_backtrader
.venv/bin/python scripts/fg_sync_tool.py -f ~/.openclaw/tmp/fg-sync-in/sync_in.md --commit "fg-sync: 公司端同步 <YYYY-MM-DD>" --quick --brief
```

4. **把脚本输出原样回传飞书**（成功/失败都原样回，不改写、不补充解释）

**关键纪律**：
- `fg_sync_tool.py` 是唯一入口（内部完成聚合→解压→白名单→冲突→入库→pytest→回传）
- `--quick` 增量测试 <10s；退出码 0=成功 / 2=可解释失败 / 3=内部错误
- 分片不齐：直接回传 `还缺第 X/N 片，请补发`，不跑还原
- 白名单拒绝/冲突/校验失败：**原样回传脚本报错**，不改判
- **禁止** `tool_call {"id":"fg-sync"}`（这是 skill 不是工具）；禁止手动 base64 解码（URL-safe 含 `-`/`_`，手动必错）；禁止只回"检查打包脚本"而不跑命令

## 链路参考（供理解，不执行）

- 打包端（公司电脑）：`scripts/make_feishu_bundle.py`（分片 ≤8KB/条）
- 解析核心：`scripts/restore_from_base64.py`（标记聚合/缺片检测/base64 解码）
- 编排入口：`scripts/fg_sync_tool.py --quick`（加速版，增量 pytest <10s）
