# 2026-10-08 B-7：NewsAPI 免费 key 申请 + 新闻情绪信号落地

## 背景
- blocked-registry B-7（新闻/社媒情绪 Market Mood）原阻塞于「需 API key」。
- 用户指示：申请免费 key（不接受付费档）。

## Key 申请（2026-10-08 实测）
- 注册 NewsAPI（newsapi.org/register）：免费 Developer 档，**100 请求/天**，足够每日简报。
- 表单含 Google reCAPTCHA + 邮箱验证，必须人工完成（用户接管浏览器完成，遵守登录交接纪律）。
- key：存 `Data/newsapi_key`（chmod 600，`.gitignore` 已排除，**不入库**）。
- 可用性实测：`everything?q=bitcoin` 返回 4205 条、status=ok。

## 落地
- `scripts/fetch_news.py`：
  - 三类查询：大盘（"stock market"/"wall street"/"s&p 500"）、加密（bitcoin/ethereum/crypto）、
    持仓标的（positions.csv 最新快照 symbols → 关键词映射，如 BTC-USDT→bitcoin）。
  - 确定性英文正负词表打分（标题+描述匹配计数，无 LLM、可审计）。
  - 网络容错：直连失败自动走本地代理 127.0.0.1:7890，单请求重试 2 次，单标的失败不中断整体。
  - 输出 `Data/raw/news_sentiment.csv`：date, mkt_total/pos/neg/score, crypto_total/pos/neg/score, syms_hit。
- 每日链 `shoutu_daily.sh` 新增 news 块（可选，不改主路径 RC）。
- 首跑（2026-10-08）：mkt_score=0.625（大盘偏正）、crypto_score=-0.125（加密偏负）、
  标的有新闻 CRCG/BTC/BTC-USDT。

## 信号分级
🟡 研究参考：新闻情绪为 E1 情绪子信号候选，词表打分未经回测裁判，不直接进合成权重；
后续可走 IC/IR 检验 + 变体审批（回测裁判），再决定是否入合成。
