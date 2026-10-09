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

## 追加（2026-10-09 09:34）：主模型切换 nvidia + 429 重试根因

### 新发现
9:24 同步实测：收到→回复 6 分钟，其中 **4 分钟浪费在 zai 429 后的同模型重试 9 次**（间隔指数退避 1s→30s），OpenClaw 硬编码"429 先重试 9 次再切 fallback"，无配置可跳过。
fallback 生效后 nvidia 实测 6s/11s 稳定完成，输出 4 行精简结论——**规则本身已完全生效**。

### 修复
主模型切换：`zai/glm-4.7-flash` → `nvidia/deepseek-ai/deepseek-v4.1-flash`（128k 上下文、工具调用、实测 6s 无 429）。
zai 降为第一 fallback。Gateway 重启后确认 `agent model: nvidia/... (thinking=medium)`。

### 预期
同步链路：nvidia 主模型 ~6s 决策 + 1.2s 执行 + 回传 = **10-15 秒**，不再受 zai 429 拖累。
