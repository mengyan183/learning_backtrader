# Harness Engineering 学习笔记（论文 2609.00006）

> 来源：Wavestone AI Lab《Harness Engineering: Anatomy, Architecture, and Evolution of Coding Agents — A Source-Code Study of Eleven Systems》（arXiv:2609.00006, cs.SE, 2026-07）
> 学习日期：2026-10-06
> 关联：本仓库的 harness 栈 = OpenClaw（网关）+ Hermes（个人助手/编码混合）+ DeepSeek-Harness + 贪恐系统每日链；论文将 OpenClaw 与 Hermes 均列为源码研究对象

---

## 0. 一句话

**Agent = Model + Harness**。模型提供智能，harness 是"除模型之外的一切"——把智能变成工作的运行时：循环、工具、上下文、安全、编排、扩展面。Harness Engineering 是设计、演化这套运行时的学科。

论文对 11 个生产级 coding harness 做**源码级解剖**（非基准评测）：Claude Code、Codex CLI、Gemini CLI、Mistral Vibe、OpenHands、Aider、Mini-SWE-Agent、Hermes、Pi、OpenCode、OpenClaw，外加 meta-harness 对照点 Omnigent（Databricks）。跨度：Python/TypeScript/Rust 三种语言、约 5K~110 万行、从 100 行研究基线到百万行商业产品。

## 1. 什么是 harness

- **定义**：除模型外的运行时——loop、tools、context、safety、orchestration、extensibility。
- **不是**：不是 scaffold（scaffold=结构代码，harness=交付的运行制品）；不是 agentic framework（框架是你 import 去建 agent，harness 是你工作在其中的运行时）；不是评测 harness（方向相反）；不是 orchestrator（meta-harness 在 harness 之上，无自身编辑循环）。
- **最小 harness**：Mini-SWE-Agent 约 100 行实现全部七个子系统，SWE-bench Verified 成绩与大它三个数量级的系统同区间——**地板很低**。

## 2. 七大子系统（组件图）

| 子系统 | 作用 | 最小形式 | 最大形式 |
|---|---|---|---|
| Agent Loop | 推理与行动交替；停止条件、故障恢复 | Mini-SWE-Agent：线性 while + 1 个 bash 工具 | OpenHands：事件溯源会话引擎，并行行动批 |
| LLM Integration | 说 provider 协议；组装 prompt；缓存/思考/路由 | 一次 LiteLLM 调用 + 一个模板 | Hermes：5 个自有传输、29 个 provider 配置；Codex：服务端下发的模型目录 |
| Tools & Actions | 定义执行能力（文件编辑是核心） | 只有 bash | Claude Code：43 个类型化工具+延迟加载；Codex：工具调用=V8 执行代码 |
| Memory & Context | 配给上下文窗口；跨轮/跨会话持久化 | 无界线性历史 | Codex：agent 自主维护跨会话记忆管道；Gemini：图式上下文蒸馏 |
| Safety & Permissions | 决定什么能跑、什么要问、什么禁止 | 步数/成本上限 | Codex：策略规则+LLM 审批员+三平台 OS 沙箱 |
| Orchestration | 生成/协调子 agent | Aider：无（刻意单 agent） | Claude Code：递归组合；Omnigent：跨厂商 meta 层 |
| Extensibility | 让用户/生态加能力 | 结构类型（Python protocol） | Pi：一切皆扩展；Codex：市场分发插件 |

另有两个横切面：**界面层**（TUI/CLI flags/IDE protocol/HTTP server/SDK）与**会话基底**（transcripts、持久化、resume/fork）。

## 3. Agent Loop 三范式

1. **迭代式行动-观察**（9 系统）：OpenHands 事件溯源、Claude Code SSE+并发安全分批、Codex Tokio async 状态机、Mini-SWE-Agent 线性循环、Mistral Vibe 中间件管道、Gemini CLI async-generator+混合死循环检测、Hermes 预算循环+停止守卫、Pi 函数式核心+steer 队列、OpenCode 日志即队列。
2. **反射增强**（Aider）：编辑后 lint/测试失败 → 反射消息 → 重新调用（默认最多 3 次）；结构表亲：Gemini edit fixer 子调用、OpenCode LSP 反馈、Hermes verify-on-stop（把反射放到停止条件，成本低一个量级）。
3. **协调者-工人覆盖**（Claude Code/Codex 强约束；Hermes 配置门控）：Research→Synthesis→Implementation→Verification。

## 4. LLM 集成：provider 抽象光谱

- 单 provider 紧耦合：Claude Code（Claude 专属 thinking/cache/tool_use 格式）、Codex（Responses API+按代模型 prompt+服务端目录）、Gemini CLI（ModelRouterService 把模型选择当运行时调度）。
- Provider 优先+通用回退：Mistral Vibe。
- 经抽象层多 provider：OpenHands/Aider/Mini-SWE-Agent（LiteLLM）。
- **自有传输多 provider（本版新增）**：Hermes 5 传输/29 profile/3800+ 模型元数据；Pi 9 线协议/35 provider/约 20 个兼容怪癖 flag（含 10 种 thinkingFormat 方言）；OpenCode 用 Vercel AI SDK+per-vendor 转换矩阵。
- 混合插件：OpenClaw（认证轮换、last-good 故障转移、冷却过期 key）。

**观察 2**：Provider 原生优化（缓存边界/思考/推理力度/模型专属 prompt）不取决于紧耦合，而取决于**谁付每 provider 条件代码的成本**。Hermes 的 bit-perfect 前缀归一化连本地 llama.cpp KV cache 都能命中。

**观察 3**：Prompt 修辞随信任校准变薄。6 个系统有近同文的"别镀金"指令；2026-04 全员禁自动 commit → 07 Mistral 反转成教 commit（含 Co-Authored-By 尾标）、Codex 新代模型直接删规则；政策从 prompt 散文迁往配置/flag。三个修辞学派：修辞强调（大写标签）/结构契约（Mistral 七级指令层级）/示例驱动（Aider patch 样例）。11/11 的 prompt 中**没有任何有害请求拒绝语言**——对齐工作完全委托给底层模型。

## 5. 工具系统

- **工具数光谱**：1（Mini-SWE-Agent）→ 7（Pi，默认暴露 4）→ 12/13 → 17 → 25 → 27 → 35 → 43 → 69（Hermes，toolset 分层按平台裁剪）→ 109+（OpenClaw）。
- **延迟加载**：Claude Code shouldDefer → 现扩散为 Codex（BM25 tool_search）、Hermes（schema 超上下文 10% 时折叠为 tool_search/tool_describe/tool_call 三桥）、OpenCode（skills 目录只列名+描述）。
- **文件编辑 8 种策略**：精确串替换（Claude Code/Mistral 现）、统一 diff patch DSL（Codex）、13 格式多态（Aider）、模糊级联（OpenCode 9 级 Levenshtein 0.65 / Hermes 9 策略链，注释互认谱系）、规范化无阈值（Pi）、LLM 辅助修复（Gemini edit fixer）、sed/awk（Mini-SWE-Agent）、整文件写入。**观察 4**：编辑策略是代码修改准确性的头号决定因素；模型感知多态（按模型换编辑格式/工具面）已从 Aider 扩散到 OpenCode。
- **沙箱**：Codex 最重（Linux vendored Bubblewrap C FFI / macOS Seatbelt / Windows restricted-token）；Gemini 第二个跨平台沙箱（Docker/Bubblewrap/gVisor/LXC + Seatbelt + restricted-token + TOML per-mode 策略 + 凭据 scrubbing）；Hermes/OpenCode 零 OS 隔离（分别投安全预算在内容威胁/策略权限）。**观察 6**：OS 沙箱是"选择"而非规模后果。

## 6. 记忆与上下文

- 四策略谱：线性（Mini-SWE-Agent）→ 递归摘要（Aider 1024 token 对半砍）→ 可插拔冷凝（OpenHands 三实现，事件溯源化+兼做错误恢复）→ **阈值压缩（7 系统=事实标准）**。
- 阈值压缩细节：Claude Code 缓冲 13K/图片→[image]→按 API 轮分组→LLM 摘要+SystemCompactBoundaryMessage；Hermes **lineage compaction**（压缩=结束会话、轮转到 child 会话、祖先链可查、历史永不销毁）；Pi 会话树（append-only JSONL tree、fork/clone、分支摘要）；OpenCode 锚定增量摘要（<previous-summary> 合并+强制 Markdown 结构+verbatim 尾部）。
- **持久记忆（新前沿）**：4 种治理——agent 自主（Codex 后台双阶段提取+git-baselined ~/.codex/memories/，沙箱内子 agent 合稿）/ 人工门控（Gemini 提取子 agent→.inbox/ 用户 /memory 应用）/ 模型直写但有界（Hermes MEMORY.md 2200 字符+USER.md 1375，冻结快照保缓存；OpenHands/Claude 写 AGENTS.md/CLAUDE.md）/ 轮前 agentic 召回（**OpenClaw Active Memory 子 agent**，每次主回复前跑）。
- **仓库上下文**：Aider RepoMap（tree-sitter 符号索引+排名，语料唯一）；Hermes 层级上下文文件+**prompt 注入威胁扫描整块拦截**；JIT 子目录上下文（Mistral/OpenCode 读文件时懒挂载）。

## 7. 安全与权限

- Claude Code 三层：静态 hook 规则 → LLM 权限分类器 → 交互对话框；后台/分叉子 agent 只有前两层。
- Codex 四层：Starlark 执行策略（非 TOML，规则带内联可执行测试用例）→ 生命周期 hooks（词汇近 Claude Code 原文）→ **Guardian LLM 审批员**（超时/畸形输出 fail-closed）→ 原生 OS 沙箱。
- Hermes：config.yaml 即安全策略；3200 行批准模块；12 模式硬底（rm -rf / 等）**连 --yolo 都存活**（YOLO env 在 import 时冻结防注入）；47 危险命令反混淆匹配；外部 Rust 扫描器 Tirith；promptware 扫描（上下文文件/记忆/MCP 描述/skill 安装四路）+ <untrusted_tool_result> 分隔+伪装去毒。
- OpenCode：语法感知命令授权（web-tree-sitter 解析 bash/PowerShell，按命令元数 scope 授权如 git→2、npm run→3），"*": allow 项目内；工具可见性本身由权限派生。
- Pi：**文档化缺席作为安全论证**（"部分进程内沙箱容易被误解为安全边界"）；项目信任门控。
- OpenHands：ensemble 防御（LLMSecurityAnalyzer 自评分 + GraySwan + 确定性 Pattern/PolicyRail + worst-case-wins 融合 + <UNTRUSTED_CONTENT> 包裹）。

## 8. 多 agent 编排（6 模式）

单 agent（Mini/Aider/Pi 核心）| 顺序委托（Mistral）| 并行子会话（OpenHands/OpenCode）| 层级线程树+扇出（Codex：SpawnAgentForkMode 全史/尾 N 轮、typed InterAgentCommunication、CSV map-reduce 扇出、声明式 TOML 角色）| 递归组合（Claude Code：六维上下文 fork+prompt 缓存共享）| 注册表+跨进程协议（Gemini A2A 服务端、OpenClaw ACP spawn、Hermes Kanban swarm 子进程+SQLite 黑板）。

**观察 7**：Coordinator-worker 在语料中独立趋同（4 厂商+OpenHands+Hermes+OpenCode+OpenClaw）；实现差异在优化目标：Claude 缓存共享（成本）、Codex 深度线程树+类型化记录（隔离/规模）、Mistral 进程内顺序（简单）、Hermes 工具集交集+默认禁递归（遏制）。

## 9. 可扩展性

- Skills（SKILL.md+frontmatter）**9/11 > MCP 8/11**；`.agents/skills/` 路径被 6 系统接受；OpenCode 甚至搜竞争者的 `~/.claude/skills`。
- 延迟加载成为主导（8/9 采用者：先元数据后正文）。
- **条件激活**：OpenClaw requires（bin/env/OS 过滤）、Claude paths frontmatter、OpenHands PathTrigger。
- **供应链**：4 个远程注册表（Mistral catalog/OpenCode URL registry/Hermes Skills Hub/OpenHands marketplace）；Hermes 信任层级+预装扫描+隔离区；OpenClaw 批准流+来源验证；**首个 agent 作者**（Hermes 后台评审 agent 从完成任务创建/修补 skill、Gemini 提取收件箱）。
- 插件：OpenClaw 最成熟（manifest 驱动、npm 外部化、严格 import 边界）；Codex marketplace+in-conversation 审批+兼容 .claude-plugin；OpenHands 直接读 Claude 插件格式。

## 10. 横切观察 13 条（速查）

1. 复杂度不预测分数；大系统的代码大多花在安全/UX/扩展/传输。
2. Provider 原生优化看谁付条件代码成本，不看耦合。
3. Prompt 修辞随信任校准变薄；政策从散文迁配置；11/11 无拒绝语言。
4. 编辑策略决定准确性；模糊级联有可见谱系；模型感知多态扩散。
5. 持久记忆取代压缩成前沿；4 种治理模型；无 embedding 主记忆。
6. OS 沙箱是选择不是规模后果。
7. Coordinator-worker 独立趋同。
8. Skills > MCP；供应链与 agent 作者出现。
9. **双缺失**：无 agentic 框架（4M 行 Python/TS/Rust 零 import）、无 code RAG（全用 ripgrep/tree-sitter/glob/Markdown 上下文文件）；OpenClaw 是唯一默认开 embedding 的（仅对话记忆，非代码）。
10. Anthropic Effective Agents 系列与实际架构吻合。
11. ACP 三角色：编辑器边界/harness hosting/跨厂商 mesh；自家子 agent 仍进程内原语为主。
12. Policy-as-Code 扩散（Starlark/config.yaml/语法感知）。
13. 无框架、无 code RAG 的成因：可调试性优先、代码结构元数据稠密、代码分钟级变化、ripgrep 已近最优。

## 11. 29 个设计模式（新增 12 个，2026-07 版）

Agent-Maintained Memory（Codex）、Outer Verification Loop（OpenHands /goal judge + Hermes verify-on-stop）、Self-Improving Skill Loop（Hermes）、Lineage Compaction（Hermes）、Session-Tree Version Control（Pi/OpenHands）、Minimal-Core/Extension-Host（Pi）、Client/Server Harness（OpenCode）、Model-Family Prompt Matrix（Codex/OpenCode/Hermes）、Cache-Dialect Fanout（OpenCode）、Syntax-Aware Command Permissioning（OpenCode/Mistral/Hermes）、Untrusted-Content Delimiting（Hermes/OpenHands）、Harness Mimicry（Pi 冒 Claude Code 身份骑订阅）。

## 12. 平台转向（thesis）

harness 从工具变成平台，四个信号：Skills 作为声明式程序；hooks/事件总线成为扩展基底（9/11）；工具与工作流边界消失（loop 即工作流引擎）；harness 作为服务面（OpenCode 内嵌 HTTP server+OpenAPI SDK、OpenHands OpenAI 兼容网关=agent 即 model）。harness-框架合流双向发生（Claude Agent SDK、openai-codex SDK、OpenHands SDK；反向 LangChain Deep Agents、Pydantic AI Harness、Strands harness-sdk）。平台经济学：市场（插件市场/技能注册表）、切换成本（Codex 导入 Claude 会话与设置；OpenCode 读 Claude skills；OpenHands 读 Claude 插件）、企业治理（Codex MDM 层+约束引擎）。**Meta-harness**：Omnigent（Databricks，Apache-2.0，23 适配器 5 集成模式，跨 harness 策略经各家扩展机制强制、统一沙箱+secretless 凭据代理、共享会话），不做编辑循环——证据：harness 已成商品组件。

## 13. 与本栈的对照与可落地模式

论文定位：**OpenClaw** = 多通道网关（非 SWE 对照点，无原生编辑工具，把编码委托给专用 SWE agent，Active Memory 轮前子 agent）；**Hermes** = 最快增长、混合个人/SWE、自进化 skill 回路、lineage compaction、verify-on-stop。

### 高价值可落地模式（按性价比排序）

1. **Outer Verification Loop（外验证循环）**——OpenHands /goal LLM 裁判 + Hermes verify-on-stop。直接对应贪恐系统每日链：简报生成后加一道确定性校验器+（可选）LLM 裁判，裁决通过才推送飞书。已有雏形：check_freshness.py、_zone_int 断言。**结构性解决"简报被截断/幻觉"**。
2. **Policy-as-Code 迁移**——把系统提示中的散文规则（"禁止编造数字""必须注明日期""查不到直说"）迁到可执行校验器/配置：fg-qa skill 的 SKILL.md 规则逐步转成脚本断言（数字可追溯检查器）。
3. **Deferred Loading + 检索**——OpenClaw/Hermes 工具/skill 多时，先只暴露元数据，按需 BM25 加载（OpenClaw 的 tool_describe 已是此思路）；贪恐系统 skill 目录可借鉴 gating（requires 环境/平台）。
4. **Self-Improving Skill Loop（Hermes 自进化回路）**——让 Hermes 从每次简报/问答任务沉淀 skill 到 fg-qa，自动修补（背景评审 agent）；对应"贪恐系统自我进化"主线，是最直接的 harness 层进化机制。
5. **Lineage Compaction（Hermes）**——上下文压缩=会话轮转+祖先链，历史永不销毁；可借鉴到 OpenClaw 长会话治理。
6. **Untrusted-Content Delimiting**——外部数据（新闻/知识库/YouTube 转录）进 prompt 前包裹 taint 标记+威胁扫描，防注入；对应知识库自动更新的安全加固。
7. **Agent-Maintained Memory（Codex，人工门控变体）**——贪恐系统让 agent 定期把"决策理由/档位判断/教训"沉淀进仓库 docs，再由人审；比纯知识库问答更接近"系统在进化"。
8. **Harness-as-Service（服务面）**——OpenClaw 已开 HTTP/飞书通道；后续可加 OpenAI 兼容端点把贪恐 agent 暴露成"model"，供其它工具调用。

### 不建议照搬

- 原生 OS 沙箱（Codex/Gemini）：工程量大，本地个人部署收益低；用 Hermes 式策略底+内容扫描代替。
- 跨厂商 A2A mesh：需求未证，保持观望。
- 代码编辑模糊级联（OpenCode/Hermes 9 级链）：贪恐系统无 SWE 编辑场景。
- Harness Mimicry（Pi）：伦理/合规风险，不采用。

## 14. 附：设计建议（论文 §16 主旨）

循环架构手写 async 而非框架；provider 抽象按"谁付条件代码成本"决策；工具少而精（few thoughtful high-signal）；编辑用精确匹配为主、模糊为降级；上下文阈值压缩+持久记忆分离；安全按部署场景分级（个人用策略底，企业用沙箱）；子 agent 进程内原语+ACP server 面向外；扩展优先 SKILL.md+延迟加载；90 行 minimum-viable-harness 可实现其中 10 条。
