# 系统架构总览（贪恐系统）

> 目的：一张图看懂"数据从哪来、每天自动做什么、产出到哪去"。
> 关联：E1 每日链 / E2 漂移 / E4 因子 / E5 问答 / Web 看板。

## 1. 每日自动投研链（launchd `com.xingguo.fg-daily`，每日 05:30）

```mermaid
flowchart LR
    A[sync_positions<br/>同步持仓快照] --> B[evolve_h001<br/>指数演化]
    B --> C[evolve_review<br/>变更复核]
    C --> D[invest_research<br/>投研简报]
    D --> E[drift_monitor<br/>漂移监控]
    E --> F[fetch_sentiment<br/>情绪子信号]
    D --> G[飞书富文本简报<br/>海外投资助手]
    E -->|异常才推送| G
    F --> H[Data/raw/sentiment.csv]
    H --> B
```

## 2. 系统分层（运行时）

```mermaid
flowchart TB
    U[用户入口] --> W[Web 看板<br/>Flask + Jinja2 :8000]
    U --> F[飞书机器人<br/>OpenClaw Gateway :18789]
    U --> Q[问答脚本<br/>portfolio_qa.py]
    W --> P[pipeline.run<br/>纯计算 不抓取]
    F --> P
    Q --> P
    P --> D1[Data/features.csv<br/>指数/档位/仓位]
    P --> D2[Data/positions.csv<br/>持仓快照]
    P --> D3[Data/raw/prices.csv]
    P --> D4[Data/raw/shoutu_fng.csv<br/>守猪待兔]
    P --> D5[Data/raw/sentiment.csv<br/>情绪子信号]
    D4 -->|仅每日链抓取| API[守猪待兔 API<br/>06:30 独占]
    D3 -->|行情| OPEND[FutuOpenD :11111]
```

## 3. 关键约束

| 约束 | 原因 |
|---|---|
| Web 看板**绝不抓取**守猪待兔 API | 每次刷新会覆盖当天样本 + 消耗月度额度 |
| 每日链 05:30 是唯一抓取方 | 避免样本污染、额度可控 |
| 公司电脑只跑静态数据 | 不调用富途/OKX 动态接口 |
| 所有服务 launchd 托管 + KeepAlive | 重启自恢复（Hermes dashboard 带 --no-open） |
