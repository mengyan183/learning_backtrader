# 双端分工表（Windows 开发端 / Mac 服务端）

> **更新**：2026-10-10 · **架构定位**（`docs/macos-deploy.md`）：公司电脑（Windows）= 开发主力；家里 Mac（macOS）= 服务运行。
> **用途**：开会/排期时照表执行——明确每类任务放哪一端，避免"该 Mac 抓的数据放到 Windows 跑"或"该 Windows 开发的任务积压在 Mac"。

---

## 分界原则（一句话）

- **凡是"抓外部数据 / 跑定时服务 / 接收消息 / 持有生产状态"→ 只能 Mac**（公司电脑无公网，走内网 Nexus + 代理，外部数据源只有 Mac 能拉）。
- **凡是"写代码 / 跑本地计算 / 全量回归测试 / 数据分析"→ Windows 可做**（Windows 是开发主力，Mac 也能做，但优先放 Windows 分流）。

---

## A. 仅 Mac 端（硬性依赖，Windows 替代不了）

| 类别 | 任务 | 依赖项 | 备注 |
|---|---|---|---|
| 数据抓取 | Nasdaq 行情（含 Referer 反爬修复后） | 公网 + `fg_system/data/fetch.py` | 2026-10-09 修复后每日链恢复 |
| 数据抓取 | CBOE VIX / VIX3M | 公网 | `update_indices()` |
| 数据抓取 | 守猪待兔系数（bsk 封装） | `Data/shoutu_token` + 公网 | 密钥仅在 Mac |
| 数据抓取 | NewsAPI 新闻情绪 | `Data/newsapi_key` + 公网 | 免费档 100 请求/天 |
| 数据抓取 | 资金费率（OKX） | 公网 + 代理 7890 | okx 走 `PROXY_HOSTS` |
| 数据抓取 | Put-Call 期权情绪（CBOE CSV） | 公网 | B-6 免 key 双层链路 |
| 定时服务 | 每日链 05:30（数据+指数+简报） | launchd | Mac 生产端 |
| 定时服务 | 假说重检 18:00 推飞书 | OpenClaw cron | Mac |
| 定时服务 | C-5 季度 walk-forward 自动重检 | launchd | Mac |
| 实时行情 | 富途 FutuOpenD 常驻 + 实时订阅 | 富途客户端 + OpenD（Mac 部署） | 持仓/行情 live |
| 看板服务 | `serve_dashboard.py` :8000 | Flask | Mac 常驻进程 |
| 消息接收 | OpenClaw 网关 + fg-sync 还原入库 | OpenClaw（Mac） | Windows 只能发，不能收 |
| 知识库 | YouTube 字幕抓取 + ChromaDB 入库 + 自动更新 | 公网 + chroma 库 | kb 集合在 Mac |
| 盘中监控 | 异动 → 新闻联动 → 飞书告警 | 富途订阅 + NewsAPI | 均在 Mac |
| 网页触发 | 刷新 freshness 检查 → live 同步 | 读 Mac 本地文件 | 依赖看板服务 |

## B. Windows 可做（可分流，开发/计算类）

| 优先级 | 任务 | 对应文档 | 说明 |
|---|---|---|---|
| 🟡 中 | 全量 pytest 回归（~900 用例） | NEXT-SESSION | Mac 只跑增量；Windows 全量更早暴露问题（阶段 1️⃣/2️⃣ 已由 Mac 完成 2026-10-09，不再列） |
| 🟡 中 | B 类观察点数据分析（H-001 满 20 点后验证等） | blocked-registry B 类 | 数据 Mac 积累，Windows 做分析/汇总 |
| 🟢 低 | 日常代码开发（dashboard/脚本/文档） | macos-deploy | **具体任务见 `docs/windows-tasks.md`**（WT 编号清单，Mac 端「同步待办」快照直接回传）；开发完走 fg-sync 打包回传 |

## C. 双端协作流程（公司 → Mac）

```
Windows 开发 → make_feishu_bundle.py 打包（≤8KB/片）
    → 飞书「海外投资助手」机器人
    → OpenClaw(Mac) fg-sync skill：聚合→解压→白名单→冲突→入库→pytest→回传
    → Mac 仓库自动 commit/push（有新变更时）
```

- 白名单：`fg_system/** scripts/** tests/** evolution/** docs/**` + 根级文档；`Data/**`、密钥、`.git` 一律拒。
- 自动清理：2026-10-09 起入库成功后自动删除分片原文（失败保留便于排查）。

### C.1 同步通道：读走 git+代理，写走飞书，不做 merge（2026-10-10 定案）

**决策**：**读** Mac 最新走 git（**必须带公司代理**）；**写**回 Mac 走飞书分片；
**不做 `git merge`**（历史无关）。

**根因（2026-10-10 实测，经两轮修正）**：

1. **直连不通，但公司通用代理可通** —— 直连 curl 报
   `curl: (28) Failed to connect to gitee.com port 443 after 5010 ms: Timeout was reached`；
   改用公司代理后立刻成功：

       PROXY=http://10.30.6.49:9090
       git -c http.proxy=$PROXY -c https.proxy=$PROXY ls-remote --heads origin
         → 6bb61b28b391e19f6d7632a53022548f617307fa  refs/heads/main   (rc=0)
       git -c http.proxy=$PROXY -c https.proxy=$PROXY fetch origin
         → ok fetched (1 new refs)

   - **代理地址**：`http://10.30.6.49:9090`（通用外网代理，见 `docs/trading-discipline.md`）。
   - ⚠️ `http://10.1.82.22:3128` **只放行 pypi**，拿它上网报 403。
   - ⚠️ **不要写进 git config**（本仓库纪律：不改 git config）⇒ 每次用 `-c` 显式传参。

2. **部分克隆 ⇒ 读文件也必须带代理** —— 本仓库是 `blob:none` 部分克隆，
   `git show origin/main:<path>` 会**按需拉 blob**；不带代理时走直连 ⇒ **静默挂死**
   （输出为空、无报错、进程被清）。必须同样加 `-c http.proxy=...`：

       git -c http.proxy=$PROXY -c https.proxy=$PROXY show origin/main:docs/windows-tasks.md

3. **别把「fetch 静默失败」当成「远端没前进」（2026-10-10 实际踩过）** ——
   `git fetch` 无输出被当成"已是最新" ⇒ 误判"Gitee 没有新记录"✗（实际已有 `6bb61b2`）。
   **判据**：判断远端是否前进，必须看 `git fetch` 的**退出码**，或先做连通性探针。

4. **合并仍然不可行（与网络无关，已核实）** —— `git merge-base HEAD origin/main` **为空**
   ⇒ 两条历史**确实没有共同祖先**，`git merge` 报 `refusing to merge unrelated histories`；
   强合只能 `--allow-unrelated-histories`，后果是全库冲突。⇒ **不做 merge**。

**做法（保持现状）**：

```
Windows 完成一项 → scripts/pack_many.py 打包（URL-safe base64 分片）
    → scripts/send_pkg.bat 发送（cmd start 脱离会话，见 AGENTS.md §6.1）
    → Mac 入库 → Mac 更新 docs/windows-tasks.md 状态并提交
```

- 打包/校验/发送工具：`scripts/pack_many.py`、`scripts/verify_pkg.py`、`scripts/send_pkg.py|bat`。
- 发送后**必须**跑 `verify_pkg.py` 做往返 md5 比对 —— 只报"已发出"不算证据。

## 当前排期建议（2026-10-09 晚更新）

> 状态更正：阶段 1️⃣/2️⃣ 已由 Mac 于 2026-10-09 完成（`evolution/sensitivity/` 四组表 + variants V-H7/V-ATR/V-VOL/V-CORR/V-MA，V-ATR/V-VOL 归档）——roadmap 原"Windows 端可执行"标注已过时，不再重复劳动。

1. **Windows 端**：全量 pytest 回归（~900 用例，Mac 只跑增量 --quick）；B 类观察点满点后的数据分析（H-001 满 20 点等）；日常代码开发（dashboard/脚本/文档）。
2. **Mac 端**：维持每日链/定时服务/数据积累（B 类观察点自动累积中）。
3. **两边共同**：季度 walk-forward（C-5）已设自动重检，人工只做最后审批。
