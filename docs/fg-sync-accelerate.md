# fg-sync 同步加速：根因与修复记录（2026-10-09）

## 现象
公司端发同步包到飞书 → 返回「同步完成」耗时从 10 分钟 → 3 分钟，且回传仍为长文本、pytest 仍全量 100s。

## 根因（两层）
1. **部署版 SKILL.md 是旧版**（fg_sync_ingest.py 全量 pytest），加速改动只改了仓库没同步部署目录 → 模型读旧流程跑全量 pytest ~100s。
2. **模型不读 SKILL.md，凭会话历史惯性执行旧命令**：`fg_sync_ingest.py`（无 --quick）+ 后台 process 运行 + 反复 poll 8 次（每次 poll 烧一次 zai 模型请求）+ 把输出加工成长文本回传。

## 修复
1. 部署版 SKILL.md 同步为加速版（--quick --brief 单命令），三处 md5 一致。
2. **AGENTS.md 强制规则注入**（~/.openclaw/workspace/AGENTS.md，每轮强制注入，不依赖模型主动加载 skill）：
   - 收到 ###FG: 必走 4 步：先回确认 → 原样存文件 → 跑 fg_sync_tool.py --quick --brief → 原样回传
   - 禁止 fg_sync_ingest.py / 禁止后台轮询 / 禁止手动解码 / 禁止加工输出
3. fg_sync_tool.py 新增 --brief（回传精简为结论行）。
4. compaction 收紧（keepRecentTokens=12000，减少模型输入）。
5. Gateway 重启生效。

## 验证
- `--quick --brief` 实测：**1.2s**（全量 100.98s 的 1/84），输出 4 行结论。
- 三处 SKILL.md md5 一致；AGENTS.md 含强制规则；Gateway 新进程正常。

## 预期
下次同步 ~10-20s 完成，回传 4 行精简结论。
