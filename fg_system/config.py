# -*- coding: utf-8 -*-
"""全部参数集中一处。修改任何参数前必须走 docs/trading-discipline.md 第 8 条流程。"""
import os

# ---------------------------------------------------------------- 路径
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "Data")
RAW_DIR = os.path.join(DATA_DIR, "raw")
FEATURES_PATH = os.path.join(DATA_DIR, "features.csv")
STATE_PATH = os.path.join(DATA_DIR, "state.json")
TRADE_LOG_PATH = os.path.join(DATA_DIR, "trade_log.csv")
REPORTS_DIR = os.path.join(ROOT, "reports")
EXTERNAL_INDEX_PATH = os.path.join(RAW_DIR, "external_index.csv")
# 实盘快照（第 13.2 条「我是否按规则执行」的输入）。**只读**，系统不据此下单。
# accounts.csv：各账户净值/现金；positions.csv：持仓明细（notional = 名义敞口）。
ACCOUNTS_PATH = os.path.join(DATA_DIR, "accounts.csv")
POSITIONS_PATH = os.path.join(DATA_DIR, "positions.csv")
PORTFOLIO_FEATURES_PATH = os.path.join(DATA_DIR, "portfolio_features.csv")

# ---------------------------------------------------------------- 网络
# 通用外网代理（PAC 指定）。pip 用 10.1.82.22:3128，见设计文档 §4.1。
#
# ⚠️ **家里 Mac 上必须覆盖**：默认值是**公司代理**，Mac 访问不到它，会全部超时。
#     Mac 有公网，直连即可：
#         export FG_PROXY=""        # 空串 = 不用代理（见 data/fetch.py 的 _opener）
#     放在 ~/.zshrc 里，或写进 Mac 上的 .env。
PROXY = os.environ.get("FG_PROXY", "http://10.30.6.49:9090")
# 需要走代理的域名白名单（data/fetch._opener 按此分流）：
# 只有这里列出的 host 用 config.PROXY，其余（nasdaq.com/cboe.com/
# alternative.me）一律直连 —— 公司代理在家里不可达，曾导致 prices 停更。
PROXY_HOSTS = ("okx.com",)
NASDAQ_API = "https://api.nasdaq.com/api/quote/{symbol}/historical"
CBOE_CDN = "https://cdn.cboe.com/api/global/us_indices/daily_prices/{name}_History.csv"

# ---------------------------------------------------------------- 标的
SYMBOLS = ["TQQQ", "SOXL", "UPRO"]
UNDERLYING_MAP = {"TQQQ": "QQQ", "SOXL": "SOXX", "UPRO": "SPY"}
LEVERAGE_RATIO = {"TQQQ": 3, "SOXL": 3, "UPRO": 3}
BREADTH_SYMBOLS = ["SPY", "QQQ", "RSP", "IWM"]
# ---------------------------------------------------------------- 研究标的（第 13.4 条取证用）
# **不参与生产**：不在 SYMBOLS / UNDERLYING_MAP / 任何因子输入里。
# 用途：为候选新市场（`gold_miners` / `china_equity`）做**否证性取证**——
# 检验「情绪因子极值 → 未来收益反向」这一先验是否成立。见 factors/screening.py。
#   黄金线：GLD（黄金） / GDX（金矿） / GDXU（3×金矿，候选可交易标的） / SLV（白银）
#           ⚠️ **GDXU 的底层不是 GDX**（2026-09-28 修正）：GDXU =
#           **MicroSectors Gold Miners 3X Leveraged ETN**（BMO 发行，是 **ETN 非 ETF**），
#           跟踪 S-Network MicroSectors Gold Miners Index（CBOE 代码 `MINERS`）
#           = **GDX + GDXJ 市值加权**。故 GDXJ 必须一并抓取（否则 GDXU 的底层缺一只）。
#           （旧文档写的「GDXU = 3×GDX」不准确，见 trading-discipline.md 第 12.17 条。）
#   中国线：FXI（大盘） / MCHI（MSCI 中国） / KWEB（中概互联） / CQQQ（科技）
#           / ASHR（A 股） / YINN（3×FXI，候选可交易标的）
#   实盘线（第 12.20 条，用户选择 B「对齐系统到实盘」）：AXTX/CRCG 为实际持仓，
#   AXTI/CRCL 为其无杠杆底层（因子输入必须用底层，§4.5 约束 1）。
RESEARCH_SYMBOLS = ["GLD", "GDX", "GDXJ", "GDXU", "SLV",
                    "FXI", "MCHI", "KWEB", "CQQQ", "ASHR", "YINN",
                    "AXTI", "AXTX", "CRCL", "CRCG"]
FETCH_SYMBOLS = ["TQQQ", "SOXL", "UPRO", "QQQ", "SOXX", "SMH", "SPY", "RSP",
                 "IWM"] + RESEARCH_SYMBOLS

# ---------------------------------------------------------------- 观察池（扩池-数据侧，第 E 层）
# **不参与生产**：不进 SYMBOLS / UNDERLYING_MAP / 因子输入 / 仓位计算。
# 用途：为个股指数扩池（第三层迭代）做数据侧储备——候选标的先入库，
# 待有回测基准后经变体+审批才能纳入白名单。**无基准前禁止读入策略。**
OBSERVE_SYMBOLS = [
    "NVDL",   # 英伟达 2×
    "TSLL",   # 特斯拉 2×
    "FNGU",   # FANG 科技巨头 3×
    "FAS",    # 金融 3×
    "TNA",    # 罗素 2000 3×
    "SQQQ",   # 纳指 -3×（反向，情绪极端反向候选）
]

# 产品损耗率（费用+融资+跟踪误差），2016-2026 实测标定，须定期重标定（§17 风险 12）
PRODUCT_COST_RATE = {"TQQQ": 0.0822, "SOXL": 0.0895, "UPRO": 0.0395}

# ---------------------------------------------------------------- 因子
RANK_WINDOW = 756          # 滚动百分位窗口（3 年）
COMPOSITE_WINDOW = RANK_WINDOW   # 保留位：v1 与 RANK_WINDOW 相同，v2 若需二次归一化再分离
WARMUP_DAYS = 756          # 信号生效前预热期
# 五因子权重（v2.2：fed 0.20→0.15，避免慢变量过度锚定指数）：
#   原四因子 0.30/0.20/0.30/0.20 → 五因子 0.25/0.15/0.25/0.15/0.20
#   → v2.2 释放 0.05 回补 vix（最高频情绪，回到四因子时代 0.30 水平）：
#   0.30/0.15/0.25/0.15/0.15。
#   2026-01-01 前 fed 无数据（NaN）→ combine 自动按剩余权重归一化，
#   历史指数比例 ≈ 0.3529/0.1765/0.2941/0.1765。
WEIGHTS = {"vix": 0.30, "term": 0.15, "price": 0.25, "breadth": 0.15, "fed": 0.15}
# 美联储政策时段（生效日, 政策方向, 目标区间上沿%）：官方事件驱动，人工随决议更新。
# 2026 上半年按兵不动（3.50-3.75%），2026-09-16 起加息周期（3.75-4.00%）。
FED_POLICY_PERIODS = [
    ("2026-01-01", "按兵不动", 3.75),
    ("2026-09-16", "加息周期", 4.00),
]
# 注意（v2）：加密指数只有 2 个因子（CF1 贪恐 + CF2 价格），因此该阈值等价于
# 「两个因子都必须有效」。后果是加密信号的有效起点 = max(CF1 warmup 756, CF2 warmup 1008)
# = **1008 个交易日**，而不是大盘的 756。这是「避免单因子主导」（§5.4）的必然代价。
MIN_VALID_FACTORS = 2      # 有效因子数少于此值则当日不产生信号

# ---------------------------------------------------------------- 资金结构
# v2.1（2026-09-22）：核心仓上限 70% → **45%**。
# 变更依据与完整流程记录见 docs/trading-discipline.md 第 12.1 条。
# **不要**在未走第 8 条流程（先改文档 → 再改代码 → 再回测）的情况下修改本值。
# 推导（不是全样本搜索出来的）：
#   目标最大暴露 = 变更前暴露 × (目标回撤 / 实测回撤) = 79% × (40 / 50.21) ≈ 62.9%
#   弹药固定 30% ⇒ 核心仓 ≤ 32.9% ⇒ CORE_CAP ≤ 0.47 ⇒ 取 0.45（留余量）
CORE_CAP = 0.45            # 核心仓上限（v2.4 复核确认，见 trading-discipline.md 第 12.7 条）
# v2.4（2026-09-22）：弹药仓上限 **12% → 20%**。
# v2.2 曾把它压到 12%，但那个推导基于**错误的回测口径**（逐标的独立，把整份
# target_position 压到单一标的，**不是实际组合**），且假设「最大暴露贯穿 -90% 崩盘」——
# 该极端情形历史上从未发生。修正口径后 v2.1（AMMO 30%）的组合回撤只有 **-42.52%**，
# 仅比 -40% 差 2.5pp，说明 12% 是对**误导性指标**的过度反应。
# 依据（第 12.7 条 CORE_CAP × AMMO_CAP **组合级 30 格矩阵**）：
#   实测「组合回撤 / 大盘最大暴露」比值稳定落在 **0.63 ~ 0.74**（均值 0.68）。
#   AMMO=20% 时，满足 -40% 的**最大** CORE_CAP 恰好是 **45%（当前值）**；
#     CORE 45% + AMMO 20% ⇒ 最大暴露 51.5% ⇒ 组合回撤 **-35.09%**（余量 4.91pp）
#     CORE 50%           ⇒ -40.25%（击穿）
#     CORE 45% + AMMO 25% ⇒ -38.84%（余量仅 1.16pp，**不取**）
# **不按矩阵挑 Calmar / 年化最高的格子**——那是对历史路径的拟合。
# **不把参数顶到约束边界**——须留约 5pp 余量以抗未来更深的崩盘。
AMMO_CAP = 0.20            # 弹药仓上限

# 总仓位上限 = CORE_CAP + AMMO_CAP = **65%**，其余 35% 为**永久现金缓冲**（不得动用）。
# 大盘最大暴露 = 31.5% + 20% = **51.5%**
#   （沿革：v2 79% → v2.1 61.5% → v2.2 43.5% → v2.4 **51.5%**）。
# 为什么不上调弹药仓以凑满 100%：那会把大盘最大暴露推到 31.5% + 55% = 86.5%，
# 比 v2 的 79% **更高**，与「降低回撤」的目标方向相反。
# 减仓必须是真减仓，不是把仓位从左口袋挪到右口袋。见 trading-discipline.md 第 4.1.1 条。
ZONE_EDGES = [20, 40, 60, 80]
ZONE_SATURATION = [1.00, 0.75, 0.50, 0.25, 0.00]
DRAWDOWN_BATCHES = [0.20, 0.40, 0.60]
# 每批释放额 = 池子上限 / 批数。**必须由 AMMO_CAP 派生**，避免手工算出不一致。
AMMO_PER_BATCH = AMMO_CAP / len(DRAWDOWN_BATCHES)   # v2.4：20% / 3 ≈ 6.67%
DRAWDOWN_LOOKBACK = 252    # 回撤基准滚动窗口（52 周）

# ---------------------------------------------------------------- 极端规则
EXTREME_GREED_TRIGGER = 85
EXTREME_GREED_FLOOR = 0.25
EXTREME_GREED_BLOCK_DAYS = 3
EXTREME_GREED_UNLOCK_INDEX = 60
EXTREME_GREED_UNLOCK_REBOUND = 0.10
EXTREME_GREED_UNLOCK_DROP = 15
EXTREME_FEAR_TRIGGER = 10
# 极恐提前释放的最小间隔。单位是**自然日**（signal 层只有日期字符串、无交易日历）。
# 设计文档 §8.2 的口径是 60 个交易日，按 7/5 折算 ≈ 84 自然日。
EXTREME_FEAR_COOLDOWN_DAYS = 84

# ---------------------------------------------------------------- 防抖动
REBALANCE_THRESHOLD = 0.10
REBALANCE_COOLDOWN = 5
MAX_SINGLE_ADJUST = 0.30

# ---------------------------------------------------------------- 数据质量
# |杠杆ETF收益 − N×标的收益| 阈值（§4.4 主检测）。
# 标定依据（2026-09-21 实测 Data/raw/prices.csv 全区间 2016-09 ~ 2026-09）：
#   真实市场最大偏离 = 16.46pp（SOXL 2020-03-17，杠杆ETF +9.94% vs 3×SOXX +26.40%，
#   同期 SOXL 日内振幅 4.38~5.99 ≈ 37%，是真实崩盘日而非数据错误；TQQQ/UPRO 同日
#   最大偏离仅 6.46pp/2.46pp，2025-04-09 关税暂缓日偏离 0.88pp）。
#   设计初值 0.15 会被该日击穿 → 全区间运行必报错，故上调至 0.20（留 ~3.5pp 余量）。
#   拆股误判空间仍充足：2:1 拆股偏离 50pp、1:5 合股偏离 150pp，均远超 0.20。
# 若将来换数据源或重标定，必须重跑 §14.6 全部测试并在设计文档 §4.4 记录新标定。
SPLIT_DEVIATION_THRESHOLD = 0.20
SPLIT_JUMP_THRESHOLD = 0.70        # 绝对兜底阈值（§4.4 辅助检测）
SPLIT_CONTINUITY_TOLERANCE = 0.05  # 拆股日前后连续性容差（§14.6）
STALE_MAX_DAYS = 5                 # 前向填充最大天数，超过则该因子置 NaN

# ---------------------------------------------------------------- 回测
# ---------------------------------------------------------------- 抓取节流与重试（第 12.14 条）
# 实测：连续抓 12 个标的时从第 8 个起**全部失败**（连 SPY 都失败，而 SPY 显然有数据）
# —— 这是数据源**限流**，不是无数据。
# 原实现的缺陷：只在**失败后**固定 sleep 2 秒，对「成功但过于密集」的请求毫无作用，
# 而限流恰恰是由密集的**成功**请求触发的。故必须加**请求前节流**。
FETCH_MIN_INTERVAL = 1.0     # 两次请求之间的最小间隔（秒）；模块级状态，跨调用生效
FETCH_RETRIES = 5            # 总尝试次数（原为 3）
FETCH_BACKOFF_BASE = 2.0     # 指数退避基数（秒）：2, 4, 8, 16, ...
FETCH_BACKOFF_MAX = 60.0     # 单次退避上限（秒）

COMMISSION = 0.0003
SLIPPAGE = 0.0005
INITIAL_CASH = 1_000_000.0
# ---------------------------------------------------------------- 标的权重（§7.2 / 第 4C 条）
# v2.3：由**等权**改为**反比波动率（风险平价）**：w_i ∝ 1/σ_i。
# 等权的隐含假设是「三个标的风险相同」，被实测否定：
#   买入持有年化波动率  SOXL 1.03 / TQQQ 0.67 / UPRO 0.54
# 等权下 SOXL 的风险贡献达 46%（权重仅 33%），**超配 13pp**，
# 它单独主导了整个 us_equity 的回撤（-51.32% vs TQQQ -28.19% / UPRO -29.17%）。
# σ 必须用**无杠杆底层**（UNDERLYING_MAP）计算，不用 ETF 自身——
# 杠杆 ETF 的自身波动含损耗噪声（费用+融资+跟踪误差），会污染风险估计（§4C.4）。
WEIGHTING = "inv_vol"              # "inv_vol"（风险平价）| "equal"
# 波动率窗口。**先验值，禁止优化**（第 4C.5 条）；与 DRAWDOWN_LOOKBACK 一致。
VOL_WEIGHT_WINDOW = 252
# 样本划分。注意：数据起点 2016-09-19 + warmup 756 交易日 ≈ 2019-09-20，
# 因此样本内起点必须晚于该日期，否则区间前段无信号（§11.5）。
IS_START = "2019-09-20"
IS_END = "2022-12-31"
OOS_START = "2023-01-01"           # 样本外起点（禁止调参）

SMOOTHING_DAYS = 1                 # v1 不平滑
VOL_GATE_OBSERVE = True            # v1 仅观测损耗速率，不参与仓位计算（§4.5 约束 4）

# ================================================================ v2 新增
# 设计依据：docs/superpowers/specs/2026-09-21-fear-greed-index-v2-design.md

# ---------------------------------------------------------------- 市场
MARKETS = ["us_equity", "crypto"]

# 核心仓内部分割。**分母是 CORE_CAP，不是总资金**（§7.1）：
# v2.6 由 70/30 改为 **80/20**。依据（第 12.12 条）：
#   加密 sleeve 对总资金的回撤贡献（-35.47pp）**大于**大盘（-24.81pp），
#   而加密年化≈0（合成轨 +0.49%）、跨市场相关性仅 -0.02（分散化收益弱）。
#   按「**两市场回撤贡献尽量均衡**」这一原则，把核心仓预算向大盘倾斜。
# v2.6 绝对值：大盘 45% × 80% = 36% + 加密 45% × 20% = 9% + 弹药 20% = 65%
MARKET_CORE_RATIO = {"us_equity": 0.80, "crypto": 0.20}

# ---------------------------------------------------------------- 趋势过滤（§6.1）
TREND_MA_DAYS = 200              # 趋势均线周期
TREND_FILTER_FACTOR = 0.5        # 跌破均线时核心仓上限折扣
# 趋势判断基准，必须是无杠杆标的（§4.5 约束 2）
TREND_BENCHMARK = {"us_equity": "QQQ", "crypto": "BTC"}

# ---------------------------------------------------------------- 加密标的（§6.3）
# 三层递减上限，基准是加密核心仓的满仓值
CRYPTO_SYMBOLS = {
    # v2.8（第 12.23 条）：`btc_beta` 加入 **BTC 现货杠杆**（借 USDT 买真实 BTC）。
    # 层内等权（第 4B.6 条）⇒ 三个标各 16.67% of 加密核心仓，
    # 层实际杠杆由 2.0x 降到 (2/3×2 + 1/3×1.10) = **1.70x**（保守方向）。
    # **成本优势**：BITX/BITU 实测年化损耗 30.17%/22.85%，而 BTC 现货杠杆
    # 在 L=1.10 时仅 9.09%×3.5% = **0.32%**（第 12.23 条先验推导①）。
    "btc_beta": ["BITX", "BITU", "BTC"],
    "stock_high_beta": ["MSTX", "MSTU"],
    "stock_ops_beta": ["CONL"],
}
# v2.1（2026-09-22）：三层上限由 100% / 70% / 50% 收紧至 **80% / 50% / 30%**。
# 依据：真实轨实测各标的**最大回撤 -85% ~ -99.6%**（MSTX -99.61%、CONL -95.39%，
# 均接近净值归零，比 TQQQ 的 -81.75% 更惨烈）。见验收报告 v2 §4.2 与设计文档 §12 风险 11。
# BTC 层设 80% 上限 ⇒ **强制至少 20% 的加密核心仓配置在 BTC 层之外**，
# 使单一标的归零不得吞噬整个加密仓。这是**先验风险预算**，不是回测优化结果。
# 绝对上限（加密核心仓满仓值 13.5%）：BTC 层 10.8% / 高 Beta 层 6.75% / 经营 Beta 层 4.05%。
CRYPTO_LAYER_CAP = {"btc_beta": 0.80, "stock_high_beta": 0.50, "stock_ops_beta": 0.30}

# 层间实际配置（第 4B.6 条，v2.5 补齐设计缺口）。
# v2 设计只给了三层**上限**，未定义层间配置。规则：**层权重 = 层上限归一化**，
# **层内等权**。这样「风险越靠间接的一端、配置越少」（§6.3）真正生效，
# 而不是只当一个可能永不触发的上限。
#   80/50/30 ⇒ 层权重 50% / 31.25% / 18.75%
#   ⇒ BITX 25% / BITU 25% / MSTX 15.625% / MSTU 15.625% / CONL 18.75%
# **禁止**另行发明层间权重（如按波动率反比）——那会引入未经验证的第二个自由度。
_CRYPTO_LAYER_CAP_SUM = sum(CRYPTO_LAYER_CAP.values())
CRYPTO_LAYER_WEIGHT = {layer: cap / _CRYPTO_LAYER_CAP_SUM
                       for layer, cap in CRYPTO_LAYER_CAP.items()}
# 底层映射：情绪因子与偏离检测的输入源（禁止用杠杆 ETF 自身价格）
CRYPTO_UNDERLYING = {
    "BITX": "BTC", "BITU": "BTC",
    # BTC 现货杠杆的底层就是 BTC 自身（**不是**杠杆 ETF，无跟踪误差）。
    "BTC": "BTC",
    "MSTX": "MSTR", "MSTU": "MSTR",
    "CONL": "COIN",
}
# v2.8（第 12.23 条）：BTC 现货杠杆的杠杆上限 **1.10x**。
# **由抗压反推，不是搜索**：强平回撤 x=(1/L−mmr)/(1−mmr)；
# BTC 历史最大回撤 −83.2%，按第 12.13 条留 5pp 余量 ⇒ 要能扛 −89%
# ⇒ 1/L ≥ 0.89×0.995+0.005 = 0.8906 ⇒ L ≤ 1.123 ⇒ 取 1.10（实测强平回撤 −90.9%）。
# 实测（3650 天，逐建仓日）：L=1.10 的 1 年内强平率 **0.0%** ⇒ 回测无需建强平模型；
# 对照 L=3.0 强平率 39.7%（**不纳入**：强平＝在最恐慌时被迫卖出，与 §1.3 冲突）。
CRYPTO_LEVERAGE = {"BITX": 2, "BITU": 2, "BTC": 1.10, "MSTX": 2, "MSTU": 2, "CONL": 2}
# 借 USDT 年化利率 3.5%（实盘）⇒ 持有成本 = (1 − 1/1.10) × 3.5% = 0.32%。
CRYPTO_SPOT_SYMBOLS = {"BTC"}
# 手动价格目标（用户策略偏好，覆盖系统指数档位信号）：
# 键用 config 侧符号（如 "BTC"），positions.csv 里的 "BTC-USDT" 做前缀归一。
# 现价未达目标 → 观望（持有至目标价）；达到目标 → 卖出。
# BTC：到 10 万美元才卖出（2026-10-05 用户明确），不跟随系统贪婪止盈。
MANUAL_PRICE_TARGETS = {"BTC": 100000.0}
# ── 美联储政策环境（FOMC）──────────────────────────────
# 2026 官方日历来源：federalreserve.gov FOMC Calendar（2026-09-16 发布）。
# 现状：2026-09-16 会议 12:0 全票加息 25bp → 3.75%-4.00%（2023-07 以来首次加息，
# 加息周期重启，通胀仍高、主席 Warsh 强调价格稳定优先）；7/29 曾 9:3 维持 3.5-3.75%。
# 市场预期：10 月维持（0bp）、12 月再 +25bp → 4.00-4.25%。
FED_RANGE_TXT = "3.75%-4.00%"          # 当前联邦基金目标区间
FED_STANCE = "加息周期"                 # 加息周期 / 按兵不动 / 降息周期
FED_LAST_DECISION = "2026-09-16"       # 最近决议日（+25bp）
FED_LAST_DECISION_TXT = "9月会议 12:0 加息 25bp → 3.75%-4.00%"
FED_OUTLOOK_TXT = "10月预计维持 · 12月预计再 +25bp → 4.00%-4.25%"
FED_EVENT_WINDOW_DAYS = 7              # FOMC 前 N 天进入事件窗口（谨慎/减仓提醒）
# 会议日 (开始, 结束)；纪要发布日 (发布日, 对应会议开始日)
FOMC_MEETINGS_2026 = [
    ("2026-01-27", "2026-01-28"), ("2026-03-17", "2026-03-18"),
    ("2026-04-28", "2026-04-29"), ("2026-06-16", "2026-06-17"),
    ("2026-07-28", "2026-07-29"), ("2026-09-15", "2026-09-16"),
    ("2026-10-27", "2026-10-28"), ("2026-12-08", "2026-12-09"),
]
FOMC_MINUTES_2026 = [
    ("2026-10-07", "2026-09-15"), ("2026-11-18", "2026-10-27"),
]
# ── 宏观事件日历（CPI/非农，2026-10-06 查证 FRED 官方 Release Calendar）──
# CPI：10-14(9月) / 11-10(10月) / 12-10(11月)，美东 8:30；
# 非农(Employment Situation)：11-06(10月) / 12-04(11月)，美东 8:30。
# 10-02 非农已发布不列入。事件前 MACRO_EVENT_WINDOW_DAYS 天进入事件窗口，
# 简报/看板提示：数据发布前避免重仓押注方向（知识库：宏观政策 50 条沉淀）。
MACRO_EVENTS_2026 = [
    ("2026-10-14", "CPI(9月)"), ("2026-11-10", "CPI(10月)"), ("2026-12-10", "CPI(11月)"),
    ("2026-11-06", "非农(10月)"), ("2026-12-04", "非农(11月)"),
]
MACRO_EVENT_WINDOW_DAYS = 2   # 宏观数据发布前 N 天进入事件窗口
# ── CME FedWatch 市场预期（QuikStrike 会话，全自动刷新）──────────────────
# QuikStrike 数据页（服务端渲染 .aspx）：insid(工具实例) + qsid(会话) 均
# 由 CME 宿主页面每次动态生成。scripts/fetch_fedwatch.py 抓取前先用
# headless Chrome 打开 CME 页面并从网络日志提取最新 insid/qsid（无人工）。
# 以下为默认值（首次回退），实际会话持久化在 FEDWATCH_SESSION_FILE。
FEDWATCH_PAGE_URL = "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html"
FEDWATCH_VIEW_URL = ("https://cmegroup-tools.quikstrike.net/User/QuikStrikeView.aspx"
                     "?viewitemid=IntegratedFedWatchTool&insid=%s&qsid=%s")
FEDWATCH_INSID = "249313867"
FEDWATCH_QSID = "9495ec2d-638b-4e16-a1c5-a1bca7691d2a"
FEDWATCH_SESSION_FILE = os.path.join(RAW_DIR, "fedwatch_session.json")
# 产品损耗率（年化），用于合成序列。**这是实测校准值，不是费率**（§4.2）：
# 用真实产品在重叠区间的已实现表现反推、使合成序列复现其已实现拖累。
#   - BITX/BITU 隐含 BTC **期货展期升水**成本（模型用现货 BTC 无法捕捉）
#   - MSTX/MSTU 隐含 2x **单股互换融资价差**（超高波动标的上极宽）+ 跟踪误差
#   - CONL 仅 ~2%，符合合理费用（费用+融资），说明模型原理正确
# 校准证据：见 modules docstring 与设计文档 §4.2；校准后残留年化偏离 ≈ 0。
# 校准基于 2022-2026 的利率与升水环境，外推存在不确定性，不得当作费率使用。
CRYPTO_PRODUCT_COST_RATE = {"BITX": 0.3017, "BITU": 0.2285, "MSTX": 0.5790,
                            "MSTU": 0.3529, "CONL": 0.0216,
                            # v2.8：BTC 现货杠杆无波动率拖累、无展期、无资金费，
                            # 成本 = 借款比例 × 借 U 利率 = (1 − 1/1.10) × 3.5% = 0.32%。
                            "BTC": 0.0032}

CRYPTO_FLAT_SYMBOLS = [s for group in CRYPTO_SYMBOLS.values() for s in group]
# **抓取清单必须排除现货标的**：BTC 不是 Nasdaq 标的，若混进 `update_crypto_prices`
# 会按 `assetclass=stocks` 去抓，必然失败。价格来自 `crypto_underlying.csv`。
CRYPTO_FETCH_SYMBOLS = [s for s in CRYPTO_FLAT_SYMBOLS if s not in CRYPTO_SPOT_SYMBOLS]

# ---------------------------------------------------------------- 加密指数（§5.2）
CRYPTO_WEIGHTS = {"crypto_fng": 0.50, "crypto_price": 0.50}
CRYPTO_FNG_SOURCE = "alternative.me"

# ---------------------------------------------------------------- 加密弹药档位（§6.4）
# 按比例加宽：2x BTC ETF 回撤 20% 是常态，沿用大盘档位会抽干共享池
CRYPTO_DRAWDOWN_BATCHES = [0.30, 0.50, 0.70]

# ---------------------------------------------------------------- 加密极端规则（§6.5）
CRYPTO_GREED_TIERS = [85, 90, 95]           # 分批减仓触发线
CRYPTO_GREED_REDUCE = [2.0 / 3.0, 1.0 / 3.0, 0.25]   # 各档减仓后的核心仓比例
CRYPTO_GREED_UNLOCK_INDEX = 60              # 回落至此值以下逐档恢复
CRYPTO_EXTREME_FEAR_TRIGGER = 10            # 待实测标定（§12 风险 9）

# ---------------------------------------------------------------- 合成序列（§4.2）
SYNTHETIC_DEVIATION_GATE = 0.05   # 合成与真实的年化偏离质量门（超过则作废告警）
# 校准值超过此阈值时告警：表示实际拖累远超合理费用，合成轨属经验校准而非机制建模
CRYPTO_IMPLAUSIBLE_COST_RATE = 0.15

# ---------------------------------------------------------------- 数据源
ALTERNATIVE_ME_API = "https://api.alternative.me/fng/"
BLOCKCHAIN_CHART_API = "https://api.blockchain.info/charts/market-price"
CRYPTO_PRICES_PATH = os.path.join(RAW_DIR, "crypto_prices.csv")
# ---------------------------------------------------------------- 守猪待兔贪恐指数（第 12.26 条）
# 用户提供的外部信号源，**逐标的**给值（不是逐市场）。
# 量程 −100 ~ 100；≥60 贪婪，≤−60 恐惧。
# **数据入口先用文件**：该服务的 token **限制单一设备使用**，从开发机直连
# 可能挤掉用户手机，故 API 直连待确认（第 12.26 条 Q1 的答复）。
SHOUTU_FNG_PATH = os.path.join(RAW_DIR, "shoutu_fng.csv")
# 服务端**全量历史**（2026-09-24 新增，见 docs/superpowers/specs/2026-09-24-shoutu-history-and-price-design.md）。
# 来源：网页端 `#/stock_detail?code=<CODE>` 背后的
# `GET https://szdt.tech/api/invest/stock_emotion/history?code=<CODE>`。
# ⚠️ **与 `SHOUTU_FNG_PATH` 的口径不同**：这里是**服务端权威日值**，
# 那边是**本地 06:30 采样**。**不要混用**（spec §5.4）。
SHOUTU_HISTORY_PATH = os.path.join(RAW_DIR, "shoutu_history.csv")
SHOUTU_FNG_MIN, SHOUTU_FNG_MAX = -100.0, 100.0
# 用户定义的贪婪/恐惧线，**必须与 ZONE_EDGES 的两端边界对应**（见 loader 的映射函数）。
SHOUTU_GREED_LINE, SHOUTU_FEAR_LINE = 60.0, -60.0
# ── 守猪待兔个性化买卖线（buy_line, sell_line）：该标的的恐慌/贪婪分界 ──
# 全标的共用 ±60 一刀切不合理：3x 杠杆 ETF 下跌杀伤大数倍，
# 买入应更苛刻（更负才买）、卖出应更敏感（更早减仓）；
# 1x/现货可承受更深恐慌，无需过早止盈。按杠杆/风险分层：
#   3x 组（TQQQ/SOXL/UPRO/YINN/GDXU）  ：买入 ≤-70 / 卖出 ≥+50
#   2x 组（CONL/BITX/BITU/MSTX/MSTU）  ：买入 ≤-65 / 卖出 ≥+55
#   1x/现货组（AXTX/CRCG/BTC）         ：买入 ≤-50 / 卖出 ≥+70
# 未配置标的回退全局 ±60。60 交易日后可升级为标的自身历史分位数（<20%=恐慌、>80%=贪婪）。
SHOUTU_LINES_3X = {"TQQQ", "SOXL", "UPRO", "YINN", "GDXU"}
SHOUTU_LINES_2X = {"CONL", "BITX", "BITU", "MSTX", "MSTU"}
SHOUTU_LINES_1X = {"AXTX", "CRCG", "BTC"}

def shoutu_lines(sym):
    """标的的守猪待兔个性化 (buy_line, sell_line)；未配置回退全局 ±60。"""
    if sym in SHOUTU_LINES_3X:
        return -70.0, 50.0
    if sym in SHOUTU_LINES_2X:
        return -65.0, 55.0
    if sym in SHOUTU_LINES_1X:
        return -50.0, 70.0
    return SHOUTU_FEAR_LINE, SHOUTU_GREED_LINE
# ── 守猪待兔官方档位表（2026-10-02 官网 fe.szdt.tech/invest/#/etf 页面实测，见 docs/shoutu-zones.md）──
# 官方**三档**，锚点刻度 -100 / -60 / 60 / 100：
#   恐慌  ≈ [-100, -60]      （页面锚点 -100 标"恐慌"、-60 标"中性"）
#   中性  ≈ (-60, 60)        （页面锚点 -60/60 标"中性"，当前计数"中性 54 个"落在该段）
#   贪婪  ≈ [60, 100]        （页面锚点 60 标"贪婪"、100 标"极贪婪端"）
# 与服务端 zone 文本（如"中性区间"）同源；边界归属以服务端下发为准。
# 官方三档 → 系统刻度映射（(x+100)/2）：恐慌→[0,20) 极度恐惧、中性→[20,80) 恐惧~贪婪、贪婪→[80,100] 极度贪婪。
# 已知标的白名单（第 12.26 条）。录入时校验，**防录入笔误**
# （`CONL` 敲成 `CONLL` 会静默多出一个只有一天数据的标的，极难发现）。
# 新增标的（如 Q7 若把 TQQQ/SOXL/UPRO 也纳入）须**先改此处**，走第 8 条流程。
# 2026-09-23 扩表：加入系统自身的三个大盘标的。依据是第 12.26 条 Q7 关闭 ——
# 该服务**本就覆盖**它们（实测 TQQQ +33 / SOXL +3 / UPRO +24），
# 此前只是用户未导出。用户决定「TQQQ/SOXL/UPRO 改用守猪待兔」。
SHOUTU_SYMBOLS = ["CONL", "YINN", "GDXU", "AXTX", "CRCG",
                  "TQQQ", "SOXL", "UPRO"]

# ---------------------------------------------------------------- 研究用底层映射
# 守猪待兔标的的**无杠杆底层**（与 `UNDERLYING_MAP` 同一纪律：§4.5 约束 1）。
#
# **只服务研究**：`scripts/analyze_shoutu_variants.py` 的「全样本」稳健性对照要按
# inv-vol 算**信号聚合**权重，而生产 `UNDERLYING_MAP` 只覆盖系统自身的三个标的。
# ⚠️ **禁止**用它替换 `UNDERLYING_MAP`（那会改变生产权重 / 拆股检测 / 损耗归因）。
#
# 为什么放在 config 而不是脚本里：`tests/test_shoutu_variants.py` 有守卫
# 「脚本不得硬编码 `SHOUTU_SYMBOLS` 里的任何标的」（精确相等、扫描全部字符串常量）
# ⇒ 映射只能来自 config（同 `RESEARCH_SYMBOLS` 的做法）。
SIGNAL_UNDERLYING_MAP = {
    "TQQQ": "QQQ", "SOXL": "SOXX", "UPRO": "SPY",   # 与生产 UNDERLYING_MAP 逐字一致
    "YINN": "FXI",                                  # 3× 富时中国 50
    "AXTX": "AXTI", "CRCG": "CRCL",                 # 第 12.20 条已记录
    "CONL": "COIN",                                 # 同 CRYPTO_UNDERLYING["CONL"]
    "GDXU": "GDXU_UND",                             # **合成列**，见下
    # C-9 观察池扩池-策略侧（2026-10-08，白名单未动）：
    #   底层精确映射：NVDL→NVDA、TSLL→TSLA、FAS→XLF、TNA→IWM（Nasdaq 已补抓入库）
    #   FNGU→QQQ：FANG 指数无现货 ETF 数据，QQQ 作大盘科技**近似底层**（已声明，非精确）
    #   SQQQ→QQQ：反向 -3× 纳指 ⇒ 指数表达**纳指情绪**（QQQ 动量高=SQQQ 该跌），动作反向
    "NVDL": "NVDA", "TSLL": "TSLA", "FNGU": "QQQ",
    "FAS": "XLF", "TNA": "IWM", "SQQQ": "QQQ",
}
# GDXU 的底层 = 指数 `MINERS` = **GDX + GDXJ 市值加权**（**不是** GDX 单只）。
# 权重取自 investing.com 的 GDXU 持仓页（2026-09-28 查得：GDX 76.07%）⇒ 固定先验。
# ⚠️ 指数**定期再平衡** ⇒ 真实权重会漂移；此处固定值只作 inv-vol 的 σ 代理，
#    **禁止优化**（同 §4C.5 对 VOL_WEIGHT_WINDOW 的纪律）。
#
# ⚠️ **「直接取指数」这条路已实测不可用（2026-09-28）**：该指数在 CBOE 有公开
#    代码 `MINERS`，但 `CBOE_CDN.format(name="MINERS")` 返回 **HTTP 403**
#    （同一个 `_get` 取 VIX 正常 ⇒ 不是代理/UA 问题，是该 CDN 没有这个文件）
#    ⇒ 无法用真指数替代本 blend，**不要**再照这条思路重试。
GDXU_UNDERLYING_BLEND = {"GDX": 0.7607, "GDXJ": 0.2393}
# 合成列名（由 `pipeline.blend_close` 写入研究用宽表；**不是**真实标的）。
GDXU_UNDERLYING_COLUMN = "GDXU_UND"

# 档位口径（第 12.26 条 Q8，2026-09-23 用户选定）：
#   "percentile" —— **逐标的分位数**：idx_i 在**自身**历史中的滚动百分位 → zone。
#                   跨标的**可比**（同一个"恐惧"在不同标的上代表同一稀有度）。
#                   窗口复用 `RANK_WINDOW`（756 日），**不新造参数**（第 4B.6 条）。
#   "fixed"      —— 固定阈值：`(x+100)/2` → zone。口径统一、可解释，
#                   但**跨标的不可比**（CONL 的 −60 出现在 38.4% 的交易日，
#                   YINN 只有 5.1%）。
# **历史不足 756 日时自动回退 `"fixed"`**（见 pipeline.shoutu_symbol_index）——
# 守猪待兔当前只有 2 天数据，故实际生效的是 fixed，直到积累满窗口。
SHOUTU_INDEX_MODE = "percentile"
# 信号源**陈旧**容忍度（交易日）。三级回退会把「停更」变成「用 fg_index」而**不产生 NaN**
# ⇒ 必须显式检测（spec §7.3）。正常抓取滞后约 1 个交易日，3 个交易日足以吸收周末与节日。
# ⚠️ 这是**安全阈值**，不是可优化参数（第 4B.6 条：禁止用回测调它）。
SHOUTU_SIGNAL_MAX_LAG_DAYS = 3
# 认证密钥路径。**必须在 .gitignore 覆盖范围内**（`Data/*token*`）。
# 只允许从环境变量 `SHOUTU_TOKEN` 或此文件读取；**严禁**把密钥写进源码。
# 用法见 fg_system/data/shoutu.py 的 load_token。
SHOUTU_TOKEN_PATH = os.path.join(DATA_DIR, "shoutu_token")

# ---------------------------------------------------------------- partner API（第 14.5 条）
# 官方开发文档：docs/查询实时贪恐.docx。契约：
#   POST /api/partner/invest/stock/scan
#   Header:    X-Auth <会员激活码>（即 SHOUTU_TOKEN_PATH 的内容）
#   form-data: code / lever / emo_area
# 额度：`query` 30 个标的 / 30 天（**去重**计数 —— 重复查同一只不再扣），
#       `query_api` 5000 次 / 自然月。八个标的全部注册后，日常抓取只耗 query_api。
SHOUTU_API_URL = "https://szdt.tech/api/partner/invest/stock/scan"

# `emo_area` 的**合法取值**。⚠️ 官方文档只列了 4 个，**漏了 `sk`（韩概）**；
# 以下 5 个来自**页面表单实测**（第 14.5 条 §5）。**以页面为准。**
SHOUTU_EMO_AREAS = ("a", "us", "sk", "coin", "other")

# 逐标的参数 {symbol: (lever, emo_area)}。**全部为 2026-09-23 实测确定，
# 无一靠推断**（第 14.5 条 §3）。判据是「与页面「贪恐」表格**精确吻合（差 0）**」。
#
# ⚠️ **必须逐一对应，禁止统一为任何单一值。** 填错会与历史序列（由页面表格写入）
#    断裂：YINN 23 点 / CONL 43 点 / GDXU 12 点 —— 而丙方案（逐标的分位数）
#    **依赖历史分布**，断裂会直接污染分布。
#
# ⚠️ 下面三处都曾因**推断**出错、被**实测**纠正。**勿凭语义改回**：
#      GDXU  曾定为 us      -> other（黄金，按表单提示语属"其他"）
#      AXTX  曾推断为 coin  -> us（AXTI 是半导体公司，美概）
#      CRCG  曾语义推断 coin -> other（页面「已查询」存储 + 数值证据）
SHOUTU_API_PARAMS = {
    "TQQQ": (3, "us"),      # 三倍纳指
    "SOXL": (3, "us"),      # 三倍半导体
    "UPRO": (3, "us"),      # 三倍标普
    "GDXU": (3, "other"),   # 三倍金矿 —— 黄金 => 其他
    "YINN": (3, "a"),       # 三倍中国 => 中概
    "CONL": (2, "coin"),    # 两倍Coin => 币股
    "AXTX": (2, "us"),      # 两倍做多AXTI（半导体）=> 美概
    "CRCG": (2, "other"),   # 两倍做多CRCL => 其他
}

# ---------------------------------------------------------------- 系统阶段（第 13.0 条）
# **默认 development**：用户明确「现在还处于开发验证阶段」。
# 只有**用户明确宣布**"开始按系统执行"后才能改为 STAGE_USAGE ——
# **不得**由代码自动推断（如"有交易记录就算上线"），那会把用户的探索性操作
# 误判为承诺。
#
# 影响：`status` / `audit` 是否把「无指令操作」计为**违规**（第 6.4 / 10.2 条）。
# 开发阶段那些操作是用户在**系统之外**的，**不构成违规** ——
# 无条件套用使用阶段口径会把「系统从未被使用」误报成「用户严重违纪」，
# 并误触发第 10.2 条的"系统降级"（第 13.0 条已明确否定该结论）。
STAGE_DEVELOPMENT = "development"
STAGE_USAGE = "usage"
STAGE = STAGE_DEVELOPMENT

CRYPTO_UNDERLYING_PATH = os.path.join(RAW_DIR, "crypto_underlying.csv")
CRYPTO_FNG_PATH = os.path.join(RAW_DIR, "crypto_fng.csv")
SYNTHETIC_PATH = os.path.join(DATA_DIR, "synthetic_leverage.csv")
CRYPTO_FEATURES_PATH = os.path.join(DATA_DIR, "crypto_features.csv")
CRYPTO_STATE_PATH = os.path.join(DATA_DIR, "crypto_state.json")

# 加密拆股偏离阈值（§12 风险 5 标定回填）。检测口径为 5 日累计收益（见 CRYPTO_ANOMALY_WINDOW）。
# 标定依据（2026-09-21 实测 Data/raw/crypto_prices.csv + crypto_underlying.csv 全区间）：
#   各标的 5 日累计最大偏离：BITX 39.14pp(2024-03-05)、MSTX 38.05pp(2025-01-06)、
#   MSTU 14.91pp(2024-11-12)、CONL 27.62pp(2024-11-11)、BITU 29.58pp(2024-11-11)。
#   全样本最大 = 39.14pp（BITX 2024-03-05，ETF +11.66% vs 2×BTC +50.79%——BTC 期货
#   展期拖累叠加残余相位伪影，是真实市场日而非数据错误）。
#   → 取 0.45（45pp）：高出实测最大值 6pp 余量，且低于 2:1 拆股信号 50pp。
#   注意：5 日窗口下噪声与拆股信号的间距（39→50pp）比 v1 单日口径窄，这是稀释
#   相位伪影的代价；若将来拆股信号被漏检，说明窗口需进一步加宽而非上调本阈值。
#   拆股仍可判别：2:1 拆股（ETF 相对 2×标的 −50pp）→ 触发；1:5 合股（−150pp）→ 强触发。
CRYPTO_SPLIT_DEVIATION_THRESHOLD = 0.45
# 绝对兜底阈值（标的自身 5 日累计 2× 收益）。同为 5 日口径，需比 v1 的单日口径放宽：
#   实测最大 = 148.14pp（2×COIN 2024-11-11，加密真实暴涨日），90pp 会误杀。
#   → 取 2.0（200pp）：高出实测最大值 52pp 余量，仍可拦截标的自身数据损坏
#   （>100% 的 5 日标的涨幅在正常市场不会出现）。
CRYPTO_SPLIT_JUMP_THRESHOLD = 2.0

# ---------------------------------------------------------------- Android 客户端产物
# 由 `mobile/build_apk.sh` 生成，**不入库**（见 .gitignore 的 `*.apk`）。
# 仪表盘服务顺带把它分发出去 —— 公司有安全下载限制，APK 传不出公司网络，
# 而手机与 Mac 本就要在同一 Wi-Fi，故让 Mac 当分发点（第 14.5 条）。
APK_PATH = os.path.join(ROOT, "mobile", "android", "app", "build", "outputs",
                        "apk", "debug", "app-debug.apk")

# 加密异常检测的累计收益窗口（交易日）。
# 原因：BTC 现货来自 blockchain.info，是 7×24 日均价，其统计窗口跨越美股会话，
# 与 ETF 单日收益存在约 1 个交易日的相位差（实测 corr lag=0 仅 0.17、lag=+1 达 0.77）。
# 用单日收益比对会产生 47pp 的**假偏离**。改用 5 日累计后相位伪影被稀释约 5 倍，
# 而拆股仍表现为 50pp/150pp 跳变，判别力不受影响。
# **不做相位 shift**：把 BTC 后移一天会构成前视偏差（§10 红线）。
CRYPTO_ANOMALY_WINDOW = 5
