"""一次性入库：7 篇微信文章要点 → ChromaDB yt_trading 集合（channel=wechat_article）。
与既有 wechat_article 文章（COIN/HOOD/CRCL）同频道，kb_search 可检索。"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
DB_DIR = REPO / "Data" / "kb" / "chroma"
COLLECTION = "yt_trading"
OLLAMA_URL = "http://127.0.0.1:11434"
EMBED_MODEL = "bge-m3"

ARTICLES = [
    ("wechat_ubs_digital_assets_20260928", "UBS：数字资产走向主流——稳定币支付/RWA代币化/AI Agent支付", "20260928",
     """过去几年数字资产定价核心围绕 BTC/ETH 与全球流动性周期；进入 2026 机构重心变化：ETF 解决配置入口、稳定币切入支付结算、RWA 触碰抵押品管理、AI Agent 带来机器支付。
美国数字资产 ETF 管理规模超 1000 亿美元，日交易量约 100 亿美元；CME 数字资产期货未平仓约 100 亿美元。
2026 年稳定币真实经济支付年化规模接近 5000 亿美元；瑞银预计 2031 年约 3 万亿美元（跨境 B2B、汇款、新兴市场支付走廊）。
「流通速度悖论（Velocity Paradox）」：支付规模增长不要求稳定币市值同步增长——同一美元稳定币可支持更多交易量；预计 2031 年稳定币总市值约 1.2 万亿美元。
稳定币发行商持有超 1750 亿美元美国国债相关资产——相当于全球美元需求新增一条短久期资产渠道。
RWA 链上代币化资产从 2022 不足 10 亿美元增至接近 400 亿美元；相对全球 350 万亿美元渗透率仅 0.01%。
代币化核心价值不在"把股票搬上链"，而在证券更快交割、抵押、再质押：假设缓冲下降，对应约 25 万亿美元新增年交易量或 8000 亿美元资本占用减少。
全球证券回购日均约 8 万亿美元，Broadridge DLR 平台处理超 3500 亿美元日交易量。
AI Agent 预计 2030 年参与约 2 万亿美元 C2B 电商交易；稳定币完成约 600 亿美元（占 3%）；卡网络在普通消费场景优势难替代。
稳定币适合：API 调用、Token 消耗、数据/算力采购、按量计费、Agent 间自主交易——高频小额实时。
价值捕获路径：通用区块空间→专业化执行→流动性→支付与交易编排→客户分发；越靠近客户、资金入口和流动性壁垒越高。
Circle 对应稳定币发行及储备资产经济性；Coinbase 覆盖交易托管分发；Visa/Mastercard 掌握消费者支付；银行占据机构客户。
竞争焦点已从"谁拥有一条链"转向谁控制资金入口、客户关系和流动性。
资料来源：UBS Global Research《Digital Assets go mainstream》2026-09-28。"""),
    ("wechat_bernstein_digitalassets_20260916", "伯恩斯坦：CLARITY受阻+FOMC加息——币股重新分层", "20260916",
     """9月15日 CLARITY 法案参议院程序性投票未获推进（49赞成/50反对）；9月16日美联储加息25bp至 3.75%-4.00%。
监管风险溢价与资金成本同时抬升 → 数字资产进入重新定价；BTC 相对防御性更高；币股开始摆脱统一 Crypto Beta。
CLARITY 延后：先压远期估值，不必然同步压低 EPS；监管确定性下降→远期可见度下降→风险溢价上升→估值倍数收缩。
9月15日美国现货 BTC ETF 单日净流出约 4.50 亿美元（FBTC -2.15亿/IBIT -1.62亿/GBTC -0.44亿），前一交易日仍 +1.60亿——事件窗口机构风险偏好降温。
9月FOMC 12:0 加息25bp；2026年底利率中位预测由 3.8% 升至 4.1%，2027E/2028E 均上调 50bp——快速降息路径明显后移。
利率压力三渠道：实际利率上行提高无现金流资产机会成本；无风险利率抬升压低高久期资产；美债收益率高位增强美元吸引力。
币股拆解——CRCL：高利率压估值但储备收益受益（USDC 规模韧性存在对冲）；HOOD：依赖交易量与产品活跃度；COIN：同时承担价格/成交量/监管三重 Beta；FIGR：信贷资产代币化、对币价直接敞口近零；MSTR：BTC 资产负债表 Beta。
币股分三套估值模型：CRCL/HOOD/FIGR 现实经营现金流；COIN 经营现金流+Crypto Beta；MSTR 更接近 BTC 资产负债表。
交易机会分层：BTC 不需要证明商业模式——宏观未恶化时更接近基准资产；币股看"股价被板块拖下去、盈利却没有同步变差"的公司。
判断：BTC 相对占优、ETH 居中、高 Beta 资产弹性下降；估值要回到现金流、交易量、资产规模和资产负债表。
资料来源：Bernstein《Crypto: Clarity fails - what next?》2026-09-16。"""),
    ("wechat_robinhood_chain_20260831", "Robinhood Chain 冷启动拆解：Base vs Robinhood Chain", "20260831",
     """7月1日上线后两个月：Robinhood Chain DeFi TVL 约 7.18 亿美元、稳定币约 7.75 亿；Base 分别约 54.76 亿和 50.09 亿——资金沉淀只有 Base 的 13%-15%。
但换指标差距没那么大：RWA 活跃市值 1.51 亿（Base 1.96 亿的 77%）；过去 7 日 DEX 成交 61.6 亿 vs Base 67.5 亿（91%）。
用户侧追赶更快：日活 40.7 万 vs Base 35.2 万、周活 168 万 vs 115 万（+46%）已反超；月活 270 万 vs 354 万仍差 24%。
TVL 增速：7月中 1.6 亿→7月底 3.25 亿→8/17 破 5.4 亿→8月底 7.18 亿（一个半月 3.5 倍）；稳定币 +138%。
"Robinhood 日活超 Base" 和 "Robinhood 生态超 Base" 是两件事：已证明用户获取能力，留存与单用户金融价值待验证。
高成交量构成：Memecoin 一度贡献 79.2% DEX 成交量；RWA 第一周仅 0.39% 交易活动；Robinhood 为 Wallet 用户承担上线后前 90 天交易成本。
Base 最深护城河：Coinbase 账户→法币/USDC→Base→交易借贷支付→代币化/x402/AI代理；AI 代理交易超 7500 万笔、活跃 1.2 万+、x402 API 2.2 万+。
Robinhood 特殊资产：2850 万已入金客户、平台资产 3550 亿美元；股票代币链上 AUM 5193 万美元（Coinbase 867 万的 6 倍）；覆盖 120+ 国家地区。
Base 从 Crypto 和稳定币向金融基础设施延伸；Robinhood 从证券账户向链上金融延伸。
后续跟踪五项：TVL 沉淀、稳定币增长、RWA 占比、股票代币 AUM 与成交、补贴结束后的 DAU/WAU。
情景：Robinhood Chain TVL Bear $1-2B / Base $3-5B / Bull $8-12B+；关键在交易流量能否转换成证券资产沉淀。
结论：Base 现在更强（基础设施厚度）；未来两年 Robinhood Chain 增长弹性更高；对母公司边际影响 HOOD > COIN（COIN 已计入 Base 叙事，HOOD 是兑现条件严格的长期期权）。"""),
    ("wechat_market_week_20260428", "市场周报：FOMC交接+超级财报周+BTC底部抬高", "20260428",
     """上周美股"冰火两重天"：QQQ +1.6% 全年 +6.7%，SPY 双双创新高；道指在 50000 下方承压。
INTC 单日飙升近 26.7%（1987 年以来最大单日涨幅）带动科技板块做多情绪；地缘（霍尔木兹）推高油价但市场"审美疲劳"。
FOMC 议息（4/28-29）：CME 显示 99.5% 概率按兵不动（维持 3.50%-3.75%）；看点：鲍威尔最后一次发布会→5 月中旬沃什（Kevin Warsh）接任后政策框架信号。
操作提示：FOMC 决议前后大盘易剧烈洗盘；鹰派表态可能触发高位获利盘集中抛压；保持适当现金、避免单边押注。
超级财报周：MSFT/AMZN/META/GOOG 同日 + AAPL/CRWV/NET/QCOM/ARM；交易逻辑从"谁在狂买AI芯片"转向"AI如何创造营收利润"。
BTC：未能攻克 80000 收于 78000 附近；除非美股加息大跌或币圈重大黑天鹅，底部逐渐抬高；上次 6 万附近大概率本轮低点。
预计 Q4 看空看多形成一致性预期；币股联动标的（IBIT/MSTR/COIN/CRCL/BMNR）若大跌是较好建仓时机。
作者曾预判关键支撑位：MSTR 100/CRCL 50/COIN 150/HOOD 70。
本周核心原则：重仓持有但不盲目追高，保持子弹，等待波动率爆炸后的机会。"""),
    ("wechat_market_week_20260508", "市场周报：AI行情+BTC区间分析+ETF流入", "20260508",
     """美股震荡上行，QQQ 首次站上 25000，上周 +1.5% 全年 +9.8%；科技/AI 板块推动明显。
驱动：AI 与半导体乐观延续（AMD/QCOM/INTC 强、巨头财报提振）；地缘推高油价（WTI 一度超 105）但市场"无视"；4 月 Nasdaq +15%、SPY +10%、Dow +7% 创近年最佳单月。
BTC 在 78,000-79,900 区间震荡，5月4日盘中一度破 80,000（2026年1月以来新高）；4 月全月 +12%-16% 为 2026 最佳单月，从 2 月低点 60,000 反弹超 30%。
核心驱动：机构资金主导——美国现货 BTC ETF 4月净流入约 19.7-24.4 亿美元（创 2026 最佳，接近翻倍 3 月）；IBIT 等持仓激增。
周期背景：2025年10月历史新高超 118,000-126,000；2026 年初熊市修正 YTD 一度 -20%+；ETF 时代"四年周期"影响力减弱。
技术面：BTC 从下降通道突破，75,000-80,000 区间筑底；200日均线约 82,000 为关键阻力；恐惧与贪婪指数 40-50（恐惧到中性）情绪逐步改善。
判断：温和震荡上行或区间整理（+10-20% 概率），波动剧烈，不排除回调测 70,000-75,000；机构共识（Franklin Templeton/Standard Chartered/Bernstein）预测年内回 100,000 以上，Q3 或成转折点。
相关标的：首选 MSTR、CRCL；次选 COIN、BMNR、MARA。"""),
    ("wechat_circle_deep_20260512", "Circle 商业模式深度：从稳定币发行商到数字美元基础设施", "20260512",
     """Q1 财报后股价单日 +16% 至 135 美元，总市值破 325 亿美元。
商业模式本质：USDC 全额准备金稳定币——用户存 1 美元发行 1 枚，美元投入短债/隔夜存款，利息归 Circle；不承担信贷风险、不做期限错配。
Q1 末 USDC 流通 770 亿美元（同比 +28%）；储备收益占营收 90% 以上。飞轮：流通规模↑→准备金池↑→利息↑→生态建设→场景↑→流通↑。
软肋：高度依赖利率环境——降息周期同样规模准备金产生更少利息；必须在利率高位期间建立不依赖利率的收入护城河。
Q1 数字：收入 6.94 亿（+20%）、调整后 EBITDA 1.51 亿（+24%）、RLDC 利润率 53%。
USDC 真实地位：流通占比约 25-28%（第二），但贡献稳定币总交易量 63%——使用效率约为流通占比两倍以上；是支付工具而非投机资产。
机构落地：Meta、Kyriba、Ramp 采用 USDC 支付结算；一旦嵌入资金流动链条黏性极高。
两条护城河：CPN（年化交易量 83 亿美元）+ ManagedPayments（稳定币支付即服务，金融机构无需自持数字资产）；USYC 代币化货币市场基金（全球最大）——从支付延伸到资产管理。
Arc：30 亿美元完全摊薄估值完成 2.22 亿美元 Arc Token 预售（a16z 领投、Apollo/ARK/BLACKROCK 跟投）；Layer-1 区块链专为支付金融设计；现有指引不含 Arc 收入=额外弹性。
AI 智能体支付栈：CircleCLI + AgentWallets + AgentMarketplace；判断 AI 智能体自主交易产生巨大机器支付需求，USDC 天然适合（24/7/可编程/跨链/即时结算）。
风险三软肋：①利率风险——降息 100bp 非线性冲击（收入可能缩水数亿美元）；②竞争风险——GENIUS 法案降合规门槛、Visa/JPMorgan/亚马逊可发自有稳定币；③脱锚风险——2023年3月硅谷银行事件（已优化准备金结构，99% 存放货币基金或 G-SIB）。
估值（ClearStreet EV/EBITDA 34x 2028E）：2028E EBITDA 11.16 亿→EV 379 亿+净现金 23.49 亿→股权 403 亿→目标价约 152（较 $135 有 +13%）；动态 PE 147x 已计入生态预期。
核心财务预测：2026E 营收 31.30 亿/2027E 36.57/2028E 43.24；EBITDA 7.48/9.26/11.16。
长期主线：让 Circle 成为数字美元时代不可绕过的基础设施层；Arc/AgentStack 是利率对冲。"""),
    ("wechat_circle_value_20260414", "Circle 长期估值 1000 亿美元：底线账与四个增量", "20260414",
     """从 2 月底 50 美元附近持续买入；核心逻辑：USDC 是 AI Agent 时代的原生货币、数字金融基础设施、稀缺标的。
最新基本面（富国银行研报，截至 4/14）：1Q26 全球稳定币总市值 3150 亿美元环比持平；USDT 份额 58%（+0.9%）、USDC 24%（-1.2%）、PYUSD 1%（+20%）；富国预测 2026 营收 12.47 亿/2027 16.28 亿，Overweight，目标价 111。
USDC 份额短期波动验证"合规是稳定币行业核心趋势"：Tether 首次聘四大审计、试图入美市场；Circle 是唯一获美国 OCC 有条件信托牌照的稳定币发行商。
底线账：五年内 USDC 3000 亿美元发行量×3.5% 利率=毛收入 105 亿；给 Coinbase 分成降至 35%→实际收入 68 亿；净利率 45%→净利 30.6 亿；35x PE→市值 1071 亿美元。
交叉验证：富国 30x 2026E EV/RLDC 与 35x PE 逻辑吻合；万事达卡 18 亿美元收购 BVNK 对应 26x 2026 PS（按 Circle 2026 营收 12.47 亿=市值 832 亿）；富国预测 2028 EBITDA 率 62% 与 45% 净利率匹配。
四个未充分定价增量：①RWA 默认结算层——代币化 AUM 从 2023Q1 15 亿增至 2026Q1 265 亿（三年 17 倍），与加密市场相关度 55%、与 USDC 相关度 95%，BUIDL/富兰克林都用 USDC 结算；②AI Agent 原生货币——过去 9 个月 40 万 AI Agent 产生 1.4 亿笔支付，98.6% 用 USDC；SDK 2.0 支持免授权小额流转；ARC 链主网上线交易确认 0.5 秒；③CPN 发行网络——合作银行通过标准协议直接铸造/销毁合规稳定币，Circle 从赚利息变赚网络交易费；④香港牌照——亚洲唯一合规美元稳定币，若落地 USDC 流通量再上台阶。
合规是最大护城河：USDT 非美债高风险资产比例比 USDC 高 10 个百分点；Circle 是纯数字资产基础设施赛道里合规性最强的标的。
风险：监管政策变化（CLARITY Act 因"稳定币奖励禁令"争议延迟）；利率下行（美债收益率降到 2% 以下直接冲击利息收入，系统性风险）；银行系稳定币竞争（汇丰/渣打发港币稳定币，更多是补充而非替代）。
机构目标价分歧：Bernstein/Needham/BTIG 250-280（看涨）；JPMorgan 220；共识 165-185（MarketBeat/富国/ClearStreet，30-35x PE）；看跌 65-110；深度看跌 50-90。
后续跟踪：2026Q3 Circle 正向净利润；2026Q2 香港金管局第二批稳定币牌照；2026H2 ARC 链主网上线及发币；CLARITY Act 最终落地。"""),
]

VID_PREFIX = "wechat_article_20261009_"


def chunk_text(text, size=450, overlap=60):
    chunks = []
    for i in range(0, len(text), size - overlap):
        chunks.append(text[i:i + size].strip())
    return [c for c in chunks if len(c) > 60]


def main():
    import chromadb
    from chromadb.utils.embedding_functions import OllamaEmbeddingFunction
    client = chromadb.PersistentClient(path=str(DB_DIR))
    emb = OllamaEmbeddingFunction(url=OLLAMA_URL, model_name=EMBED_MODEL)
    col = client.get_or_create_collection(COLLECTION, embedding_function=emb)
    existing = set(col.get()["ids"]) if col.count() else set()
    added = 0
    for vid, title, date, text in ARTICLES:
        full_vid = VID_PREFIX + vid
        for i, ch in enumerate(chunk_text(text)):
            id_ = f"{full_vid}_{i}"
            if id_ in existing:
                continue
            col.add(ids=[id_], documents=[ch],
                    metadatas=[{"video_id": full_vid, "channel": "wechat_article",
                                "title": title, "date": date, "chunk": i}])
            added += 1
    print(f"7 篇文章入库完成: 新增 {added} 块, 集合共 {col.count()} 块")
    # 验证
    res = col.query(query_texts=["稳定币 储备收益 利率敏感 币股分层"], n_results=3)
    for doc, meta in zip(res["documents"][0], res["metadatas"][0]):
        print("  ->", meta.get("channel"), "|", meta.get("title"), "|", doc[:50])


if __name__ == "__main__":
    main()
