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

## 验证（2026-10-09 09:40）：主模型切换后首次实测

- 09:40:06 收到同步包 → 09:40:53 完成回传，**总耗时 47 秒**（此前 6 分钟）。
- nvidia 主模型两轮请求：17.7s 决策 + 9.2s 输出，**全程无 fallback、无 429 重试**。
- 输出 4 行精简结论，`--quick` 增量 pytest 通过。
- 链路目标达成：规则生效 ✓ 输出精简 ✓ 主模型稳定 ✓ 不再受 zai 429 拖累 ✓

## 追加（2026-10-09 09:54）：关闭 nvidia 思考 + 开启 fast 模式

### 新发现
47 秒中 nvidia 决策占 17.7s（reasoning 模型思考时间）。日志 `agent model: nvidia/... (thinking=medium, fast=off)`。
同步是确定性任务（保存→跑脚本→回传），不需要深度推理。

### 修复
main agent 配置：`thinkingDefault=off` + `fastModeDefault=true`。
重启后确认 `agent model: nvidia/deepseek-v4.1-flash (thinking=off, fast=on)`。

### 预期
决策 17.7s → 3-5s，同步链路总耗时 47s → 15-20s。

## 验证（2026-10-09 09:55）：thinking=off + fast 模式首测

- 09:55:30 收到 → 09:56:22 回传，总 52s（nvidia 首轮 12.3s 决策 + 次轮 17s 输出）。
- 全程无 fallback、无 429、无模型异常。
- 用户感知"9:56 就响应"，链路从 6 分钟 → 稳定 1 分钟内达标。
- 剩余小优化点：streaming card 渲染每次 HTTP 400 走兜底（约 +7s），可后续修卡片格式。

## 追加（2026-10-09 10:02）：修复 streaming card HTTP 400

### 根因
每次回传日志 `streaming start failed ... Create card request failed with HTTP 400`，实测复现 CardKit create 请求：
`code 99991672 - Access denied. One of the following scopes is required: [cardkit:card:write]`
→ **飞书应用缺 `cardkit:card:write` 权限**，OpenClaw 每次尝试创建流式卡片都失败，回退普通消息（+~7s）。

### 修复
`channels.feishu.streaming.mode = off`：关闭流式渲染，回复直发普通消息（im.message.create），不再触发 CardKit API，无 400、无 7s 兜底。
（替代方案：在飞书开放平台给应用开通 cardkit:card:write 权限，可恢复流式打字效果。）

### 备注
本地 bot 自发的测试消息被 OpenClaw 按设计丢弃（dropping self-authored bot message），需用户从公司端发真实消息验证。

## 验证（2026-10-09 10:05）：card 400 修复生效

- 10:05:23 收到 → 10:06:12 回传，总 49s。
- **日志中 streaming start failed / HTTP 400 完全消失** —— 关闭流式卡片修复生效，回复直发普通消息。
- nvidia 首轮 19s（决策）+ 次轮 12.3s（输出），无 fallback/429。
- 剩余瓶颈：deepseek-v4.1-flash 是推理型模型，API 层响应本身 ~12-19s/轮，agent 层 thinking=off 无法再压缩。

## 追加（2026-10-09 11:20）：ClashX 代理故障导致链路卡死 + 修复

### 现象
11:12 预告消息 10 分钟无响应；日志 nvidia 连续 7 次 ConnectTimeout，任务超 5 分钟被逐出队列。

### 根因（实测定位）
1. OpenClaw 检测系统代理后自动注入 `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY=http://127.0.0.1:7890`（在 `~/.openclaw/service-env/ai.openclaw.gateway.env`）。
2. 本机运行 **ClashX**（PID 36274）监听 7890，但**其出口节点当前不可用** → 所有走代理的模型请求全部超时（nvidia、zai 双双超时）。
3. 直连验证：`TCP 0.1s` / `curl nvidia API 200 0.5s` —— 网络本身正常，问题只在代理一跳。
4. 仅本地 ollama（11434，NO_PROXY 白名单内）正常。

### 修复
`ai.openclaw.gateway.env` 的 NO_PROXY 追加模型域名：
`integrate.api.nvidia.com,open.bigmodel.cn` → nvidia/zai 直连，绕过失效代理。
重启 gateway（PID 40434），nvidia API 直连 0.5s 200。等用户实测。

### 备注
- ClashX 本身节点不可用，用户其他走代理的流量（如 Google）可能也受影响，需自行恢复/切换节点。
- 若 OpenClaw 更新后重写 env 文件，此 NO_PROXY 追加会被覆盖，需复查。

## 追加（2026-10-09 11:40）：路线 B 实施——feishu 插件 ###FG: 旁路绕过 LLM

### 背景
855 片分片协议在 OpenClaw 架构下走不通：每条分片消息 = 一次完整 LLM 决策（10-25s/条，不可并行）+ 上下文膨胀 → 371s 无进展被判定 stalled 中止，分片一条都没落盘（sync_in.md 0 字节）。

### 补丁（改编译产物，升级会被覆盖）
`~/.openclaw/npm/projects/openclaw-feishu-*/node_modules/@openclaw/feishu/dist/.setup/monitor.account-*.mjs`
在 `dispatchFeishuMessage` 的 task 里、`handleMessage` 前插入分支：检测 `preparedContent` 含 `###FG:` → 落盘到 `~/.openclaw/tmp/fg-sync-bypass-in/` → 调 `fg-sync-bypass.py` → return（绕过 LLM）。备份：同目录 `.bak_fgbypass`。

### 旁路脚本（入库：skills/fg-sync/scripts/fg-sync-bypass.py）
- 解析 `###FG:包名:序号/总数###...###FG:end###` 全部分片
- 逐片落盘 `~/.openclaw/tmp/fg-sync-in/<包>_<序号>.md`（幂等，同序号覆盖）
- 收齐（已收 == 总数）→ 聚合到 sync_in.md → 调 fg_sync_tool.py 入库 → 回传飞书
- 未收齐静默；每 100 片回传一次进度

### 风险与防护
- OpenClaw 升级会覆盖 .mjs → 需在升级后重打补丁（备份 .bak_fgbypass 在手）
- 补丁语法已 node --check 验证；gateway 重启正常（PID 45290）
- 待用户重发 855 片实测
