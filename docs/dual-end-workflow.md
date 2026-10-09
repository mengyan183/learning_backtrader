# 双端分工表（Windows 开发端 / Mac 服务端）

> **更新**：2026-10-09 · **架构定位**（`docs/macos-deploy.md`）：公司电脑（Windows）= 开发主力；家里 Mac（macOS）= 服务运行。
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
| 🟢 低 | 日常代码开发（dashboard/脚本/文档） | macos-deploy | 开发完走 fg-sync 打包回传 |

## C. 双端协作流程（公司 → Mac）

```
Windows 开发 → make_feishu_bundle.py 打包（≤8KB/片）
    → 飞书「海外投资助手」机器人
    → OpenClaw(Mac) fg-sync skill：聚合→解压→白名单→冲突→入库→pytest→回传
    → Mac 仓库自动 commit/push（有新变更时）
```

- 白名单：`fg_system/** scripts/** tests/** evolution/** docs/**` + 根级文档；`Data/**`、密钥、`.git` 一律拒。
- 自动清理：2026-10-09 起入库成功后自动删除分片原文（失败保留便于排查）。

## 当前排期建议（2026-10-09 晚更新）

> 状态更正：阶段 1️⃣/2️⃣ 已由 Mac 于 2026-10-09 完成（`evolution/sensitivity/` 四组表 + variants V-H7/V-ATR/V-VOL/V-CORR/V-MA，V-ATR/V-VOL 归档）——roadmap 原"Windows 端可执行"标注已过时，不再重复劳动。

1. **Windows 端**：全量 pytest 回归（~900 用例，Mac 只跑增量 --quick）；B 类观察点满点后的数据分析（H-001 满 20 点等）；日常代码开发（dashboard/脚本/文档）。
2. **Mac 端**：维持每日链/定时服务/数据积累（B 类观察点自动累积中）。
3. **两边共同**：季度 walk-forward（C-5）已设自动重检，人工只做最后审批。
