# -*- coding: utf-8 -*-
"""守猪待兔贪恐指数：**前向录入**（第 12.26 条）。

【为什么需要它】
**历史数据已可得**（2026-09-24 更新，见 `trading-discipline.md` 第 14.5 条
「E1 再补」）：网页端 `#/stock_detail?code=<CODE>` 的「历史贪恐指数」页背后是
`GET /api/invest/stock_emotion/history?code=<CODE>`，实测返回 543~625 个
交易日的逐日 `score` + `price`。
⇒ 抓取见 `scripts/fetch_shoutu_history.py`，落盘 `Data/raw/shoutu_history.csv`
（**服务端权威日值**）。

> 历史背景（第 12.26 条 Q4 的**原始**判定，**已被取代、不是被推翻** ——
> 当年那几条路确实都不通，第五条路是后来才找到的）：
>   - API 直连   ：token 绑单设备，从电脑调用会让用户手机掉线
>   - App 导出   ：结果是图片，不是 CSV
>   - 图片数字化 ：已证伪（列跨度中位 7px、42.5% 的列 >8px，原理上歧义）
>   - **网页端历史页**：✅ 见上（走登录会话，**零凭据**）

⇒ 丙方案（逐标的分位数）的阻塞**从"等历史"变为"等 756 日窗口"**
（`RANK_WINDOW`）—— 数据已可得（625 / 756），缺的只是**长度**。
⇒ `shoutu_fng.csv` 仍作为**前向 06:30 采样**保留（与历史文件**口径不同，不合并**）。

【职责边界】
本模块只做**存储层**，全部可离线测试：
    `append_records`   把新观测**幂等**并入 CSV
    `load_token`       从环境变量/本地文件取密钥（源码树里永不出现密钥）
    `mapping_to_frame` 手工录入的便捷转换
**读取**在 `loader.load_shoutu_fng`，此处不重复其 pivot 逻辑。

【不含 API 客户端】
接口契约（端点、鉴权方式、响应结构、限流规则）尚未确认。按第 8 条流程
（先文档 → 再代码）**不写投机代码**；待用户同步密钥与接口文档后，
在 `fetch.py` 新增抓取函数，复用其已有的 `_throttle` / `_backoff` / `_get`。
"""
import os

import pandas as pd

from fg_system import config
from fg_system.data import loader


class ShoutuError(Exception):
    """守猪待兔录入错误（越界、格式错误、缺密钥等）。"""


TOKEN_ENV = "SHOUTU_TOKEN"
# 前向录入的列。**`price` 是参考量，不是信号** —— 它不参与任何校验
# （量程 / 白名单都只管 `value`），且不可解析时**置 NaN 而不报错**。
# 目的：让「价格 × 贪恐指数」的对照能在同一张表里做（2026-09-24 用户要求）。
RECORD_COLUMNS = ["date", "symbol", "value", "price"]
# 服务端**历史**的列。用**源字段名** `score`（端点返回的就是 `score`），
# 与前向文件的 `value` 含义相同、**列名刻意不同** —— 各自对齐其数据源的字段名，
# 便于追溯。将来若要把两个文件合并，必须**显式改名**（spec §5.4）。
HISTORY_COLUMNS = ["date", "symbol", "score", "price"]


def load_token(path=None):
    """读取认证密钥：**环境变量优先，其次本地文件**。

    **为什么不在 config 里写死**：`config.py` 被 git 跟踪，密钥写进去必然入库。
    本函数只从「环境变量」或「`.gitignore` 覆盖的本地文件」取，
    **源码树里永远不出现密钥**（`.gitignore` 已有 `Data/*token*`）。

    **绝不回显密钥**：异常信息只含路径与变量名、不含内容 ——
    否则密钥会随报错进入终端记录与日志。
    """
    token = (os.environ.get(TOKEN_ENV) or "").strip()
    if token:
        return token
    path = path or config.SHOUTU_TOKEN_PATH
    if not os.path.exists(path):
        raise ShoutuError(
            "未找到守猪待兔认证密钥。二选一：\n"
            "  1. 设置环境变量 %s\n"
            "  2. 写入文件 %s（已被 .gitignore 的 `Data/*token*` 覆盖）"
            % (TOKEN_ENV, path))
    with open(path, "r", encoding="utf-8") as fh:
        token = fh.read().strip()
    if not token:
        raise ShoutuError("密钥文件为空：%s" % path)
    return token


# ================================================================ partner API（第 14.5 条）
# 官方文档：docs/查询实时贪恐.docx。**量程 −100~100，与页面表格同口径，不做转换。**

def api_params(symbol):
    """返回该标的的 `(lever, emo_area)`（第 14.5 条 §3 的**实测**值）。

    **未知标的必须报错，不得回退默认值** —— `emo_area` 填错**不报错、只给错值**，
    而默认值必然对某些标的是错的（八个标的用了四种不同的 area）。
    """
    sym = str(symbol).strip().upper()
    if sym not in config.SHOUTU_API_PARAMS:
        raise ShoutuError(
            "未知标的：%s。已知标的为 %s。\n"
            "若确需新增，请先改 config.SHOUTU_API_PARAMS（第 8 条流程）——"
            "并且 **lever 与 emo_area 都必须实测**，不得从名称或语义推断。"
            % (sym, sorted(config.SHOUTU_API_PARAMS)))
    return config.SHOUTU_API_PARAMS[sym]


def parse_score_payload(payload):
    """解析 partner API 响应，返回 `{score, name, price, time}`。

    **量程是 −100~100，不做任何转换**：实测确认与页面「贪恐」表格**同口径**
    （多个标的精确吻合）。文档示例 `score:71` 是正数，**不代表**量程是 0~100。

    三条硬约束，每条对应一个真实失败模式：

    1. `status != 1` 即报错，并**带上服务端 msg**（如「杠杆倍数错误」）——
       这是发现 `lever` / `emo_area` 填错的主要信号
    2. `data` 缺失即报错（账号未激活 / 接口变更）
    3. `score` 非数值即报错（页面未激活时显示 `**`）—— **不静默变 NaN**
    """
    payload = payload or {}
    if payload.get("status") != 1:
        raise ShoutuError("守猪待兔 API 返回错误：status=%s msg=%s"
                          % (payload.get("status"), payload.get("msg")))
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ShoutuError("守猪待兔 API 响应缺少 data：%s" % str(payload)[:200])
    try:
        score = float(data["score"])
    except (KeyError, TypeError, ValueError):
        raise ShoutuError("守猪待兔 API 的 score 无法解析：%r" % (data.get("score"),))
    return {
        "score": score,
        "name": data.get("name"),
        "price": pd.to_numeric(data.get("price"), errors="coerce"),
        "time": data.get("time"),
    }


def collect_score_records(symbols=None, fetch_one=None):
    """逐标的取分**并保留 price**，返回 `{symbol: {"score":…, "price":…}}`。

    `price` 是**参考量**（供「价格 × 贪恐指数」对照），不参与仓位计算。

    **每个标的用它自己的 `(lever, emo_area)`** —— 统一填 `us` 会拿到错误模型
    的数值（实测 CONL 差 43 点、YINN 差 23 点，第 14.5 条 §3）。

    **任一标的失败即抛错，不静默跳过**：跳过会让当天记录**悄悄缺标的**，
    而 `append_records` 是覆盖语义 ⇒ 序列出现空洞，且事后难以发现。
    （`_post_form` 已重试 5 次 + 指数退避，能走到这里说明是真故障。）

    `fetch_one(symbol, lever, emo_area) -> payload` 可注入，便于**离线**测试。
    """
    if fetch_one is None:
        from fg_system.data import fetch as fetch_mod
        fetch_one = fetch_mod.fetch_shoutu_score
    symbols = config.SHOUTU_SYMBOLS if symbols is None else list(symbols)

    out = {}
    for sym in symbols:
        lever, area = api_params(sym)
        try:
            rec = parse_score_payload(fetch_one(sym, lever, area))
        except ShoutuError as exc:
            raise ShoutuError("[%s] %s" % (sym, exc))
        except Exception as exc:       # 网络类异常也要指明是哪个标的
            raise RuntimeError("[%s] %s" % (sym, exc))
        out[sym] = {"score": rec["score"], "price": rec["price"]}
    return out


def collect_scores(symbols=None, fetch_one=None):
    """逐标的取分，返回 `{symbol: score}` —— **契约不变**。

    实现委托给 `collect_score_records`（它同时保留 `price`）；
    语义、报错、`fetch_one` 注入方式完全一致，见那边的说明。
    """
    return {s: r["score"]
            for s, r in collect_score_records(symbols, fetch_one).items()}


def compare_page_vs_api(page_values, api_values, tol=3.0):
    """对照「页面表格值」与「API 值」，返回 `(rows, ok)`（第 14.5 条）。

    **为什么需要它**：用户决定**保留 bsk 通道**（`shoutu_daily.cmd` 不切 API），
    理由是"还需要 API 数据和浏览器页面数据进行对照"。本函数即该对照的判定逻辑，
    由 `scripts/compare_shoutu.py` 调用。

    `rows`：`[{"symbol", "page", "api", "diff", "status"}]`，按标的排序。
    `status` ∈ `ok` / `diff` / `page_missing`。

    `ok` 为真**当且仅当**：页面至少命中一个标的，**且**表内标的的最大差 ≤ `tol`。

    三点设计说明：

    1. **`tol` 不取 0** —— 该指数**实时更新**，而"读页面（sweep 约 38 秒）→ 调
       API"之间存在时间差，1~2 点波动属正常。实测**同一时刻**对照最大差为 **0.0**。
    2. **表外标的标为 `page_missing` 且不参与判定** —— 计入会**误报**"不一致"。
       注意（2026-09-24 起）：`scripts/compare_shoutu.py` 已对分类表未覆盖的标的
       补走个股贪恐视图，所以 AXTX / CRCG **不再**天然落在这一类里；
       真出现 `page_missing` 说明**页面侧确实没拿到**，该去查而不是当正常。
    3. **页面零命中判失败** —— 可能是页面改版、账号未登录，或 sweep 漏读
       （实测出现过 369 行 / 10 分类，而应为 379 行 / 11 分类）。
    """
    rows = []
    for sym in sorted(set(page_values) | set(api_values)):
        if sym not in page_values:
            rows.append({"symbol": sym, "page": None,
                         "api": api_values.get(sym), "diff": None,
                         "status": "page_missing"})
            continue
        page = float(page_values[sym])
        api = api_values.get(sym)
        if api is None:
            rows.append({"symbol": sym, "page": page, "api": None, "diff": None,
                         "status": "page_missing"})
            continue
        diff = abs(page - float(api))
        rows.append({"symbol": sym, "page": page, "api": float(api), "diff": diff,
                     "status": "ok" if diff <= tol else "diff"})
    covered = [r for r in rows if r["status"] in ("ok", "diff")]
    ok = bool(covered) and all(r["status"] == "ok" for r in covered)
    return rows, ok


def mapping_to_frame(mapping, date=None, prices=None):
    """`{symbol: value}` → 录入用的长表（列 `date,symbol,value,price`）。

    `date` 缺省为**今天**。为什么默认今天而不是"自动取最新交易日"：
    手工录入的语义是"我今天看到的当前值"，由录入者显式指定日期最不易错。

    `prices` 可选：`{symbol: price}`。缺省、或某个标的没给 ⇒ 该行 price 为 NaN
    （手动录入 `cli shoutu-record --values` 不带价格；price 是**参考量**，不校验）。
    """
    date = pd.Timestamp.today().normalize() if date is None else pd.Timestamp(date)
    prices = prices or {}
    recs = []
    for s, v in mapping.items():
        sym = str(s).strip().upper()
        recs.append({"date": date, "symbol": sym, "value": float(v),
                     "price": pd.to_numeric(prices.get(sym), errors="coerce")})
    return pd.DataFrame(recs, columns=RECORD_COLUMNS)


def append_records(records, path=None):
    """把新观测**幂等**并入 CSV，返回 `(合并后宽表, 本次录入行数)`。

    四条硬约束，每条都对应一个真实的失败模式：

    1. **越界即报错**（量程 −100~100）。静默截断会把「口径变了」伪装成
       「极值信号」—— 同 `loader.shoutu_to_system_scale` 的原则。
       **只管 `value`** —— `price` 是参考量，不参与（否则正常股价 300 会被误判越界）。
    2. **幂等**：同 `(date, symbol)` 重复录入**覆盖**而非追加。手工录入必然
       需要补录/更正，追加会污染分布 —— 而分布正是丙方案的唯一输入。
    3. **排序落盘**：按 `(date, symbol)` 排序，使文件 diff 稳定、可 review。
    4. **失败不落盘**：任何校验不过就抛异常、**不碰文件**。
       宁可没有数据，不可有错数据（第 13.0 条）。

    **标的白名单**：`symbol` 必须在 `config.SHOUTU_SYMBOLS` 内。
    这是**录入错误**的主要防线（`CONL` 敲成 `CONLL` 会静默多出一个标的、
    且永远只有一天数据，极难发现）。新增标的须先改 `config`（第 8 条流程）。
    """
    path = path or config.SHOUTU_FNG_PATH
    new = pd.DataFrame(records)
    # `price` 是**可选**列（参考量）：只传 3 列的旧调用方**照常可用**（补 NaN），
    # 而不是报"缺列" —— 否则这次改动会打断所有既有调用方与测试。
    missing = [c for c in RECORD_COLUMNS if c not in new.columns and c != "price"]
    if missing:
        raise ShoutuError("录入数据缺少列：%s（应为 %s）" % (missing, RECORD_COLUMNS))
    if "price" not in new.columns:
        new["price"] = pd.NA

    new = new[RECORD_COLUMNS].copy()
    new["date"] = pd.to_datetime(new["date"], errors="coerce").dt.normalize()
    new["symbol"] = new["symbol"].astype(str).str.strip().str.upper()
    new["value"] = pd.to_numeric(new["value"], errors="coerce")
    # **price 不可解析 ⇒ 置 NaN，不报错**：它是参考量，价格源抖动不该把整次抓取搞挂。
    new["price"] = pd.to_numeric(new["price"], errors="coerce")

    bad = new[new["date"].isna() | new["value"].isna() | (new["symbol"] == "")]
    if len(bad):
        raise ShoutuError(
            "录入数据含无法解析的行（日期/数值/标的为空）：\n%s"
            % bad.to_string(index=False))

    unknown = sorted(set(new["symbol"]) - set(config.SHOUTU_SYMBOLS))
    if unknown:
        raise ShoutuError(
            "未知标的：%s。已知标的为 %s。\n"
            "若确需新增，请先改 config.SHOUTU_SYMBOLS（第 8 条流程），"
            "否则很可能是录入笔误（如 CONL → CONLL）。"
            % (unknown, config.SHOUTU_SYMBOLS))

    lo, hi = config.SHOUTU_FNG_MIN, config.SHOUTU_FNG_MAX
    out_of_range = new[(new["value"] < lo) | (new["value"] > hi)]
    if len(out_of_range):
        raise ShoutuError(
            "守猪待兔指数越界（量程 %g ~ %g）：\n%s\n"
            "请确认数据源口径是否变化，不要静默截断。"
            % (lo, hi, out_of_range.to_string(index=False)))

    # **必须读长表**（`load_shoutu_records`），不能读宽表（`load_shoutu_fng`）：
    # 宽表只有 `value`，用它重读旧数据会把旧行的 `price` **静默丢掉**
    # —— 2026-09-24 实机踩到，回归红线见
    # `test_append_records_preserves_existing_price`。
    old_long = loader.load_shoutu_records(path)
    if not old_long.empty:
        old_long = old_long.dropna(subset=["value"])

    # 空表不参与 concat：pandas 对「含全 NA 列的空表」参与 concat 会告警，
    # 且未来版本会改变 dtype 推断规则。
    parts = [f for f in (old_long, new) if not f.empty]
    merged = (pd.concat(parts, ignore_index=True) if parts
              else pd.DataFrame(columns=RECORD_COLUMNS))
    merged = (merged.drop_duplicates(subset=["date", "symbol"], keep="last")
              .sort_values(["date", "symbol"])
              .reset_index(drop=True))

    os.makedirs(os.path.dirname(path), exist_ok=True)
    merged.to_csv(path, index=False, encoding="utf-8")
    return loader.load_shoutu_fng(path), len(new)


UNIVERSE_COLUMNS = ["date", "category", "code", "name", "fg_index", "price", "scale"]


def parse_universe_rows(lines, date=None):
    """把页面提取的行解析成全市场长表（E1，第 14.5 条）。

    输入是 `scripts/fetch_shoutu.py` 从页面读出的行，格式：

        `分类~代码~名称~贪恐~市价~规模`

    **为什么用 `~` 分隔而不是空格/逗号**：标的名称里含**空格**
    （如 `2倍做多AXTI ETF-Tradr`），用空格或逗号分隔会错列。
    `~` 在名称中出现的概率极低。

    **为什么解析放在库里而不是脚本里**：脚本要调 `bsk`（需要浏览器），
    无法在 CI 里测；把**纯解析**拆出来，就能用测试锁住格式约定 ——
    而格式约定恰恰是最容易因页面改版而静默失效的部分。

    无法解析的行**跳过而不是报错**：页面改版时宁可少收几行，
    也不能让整个抓取失败（抓取失败意味着当天没有数据）。
    """
    date = pd.Timestamp.today().normalize() if date is None else pd.Timestamp(date)
    recs = []
    for line in lines or []:
        parts = str(line).split("~")
        if len(parts) < 4:
            continue
        cat, code, name = (p.strip() for p in parts[:3])
        if not code:
            continue
        fg = pd.to_numeric(parts[3], errors="coerce")
        if pd.isna(fg):
            # 贪恐值缺失（如未激活时的 `**`）⇒ 该行无意义，跳过
            continue
        recs.append({
            "date": date, "category": cat, "code": code, "name": name,
            "fg_index": float(fg),
            "price": pd.to_numeric(parts[4], errors="coerce") if len(parts) > 4 else None,
            "scale": pd.to_numeric(parts[5], errors="coerce") if len(parts) > 5 else None,
        })
    return pd.DataFrame(recs, columns=UNIVERSE_COLUMNS)


def record_universe(df, path=None):
    """把全市场快照落盘到 `Data/raw/shoutu_etf_universe.csv`（覆盖同日）。

    与 `append_records` 的分工：本函数写的是**全市场快照**（用于回答
    "某标的是否被覆盖"这类问题），`append_records` 写的是**逐标的时序**
    （用于丙方案的仓位系数）。两者的消费者不同，故分开存。
    """
    path = path or os.path.join(config.RAW_DIR, "shoutu_etf_universe.csv")
    new = pd.DataFrame(df, columns=UNIVERSE_COLUMNS)
    old = pd.DataFrame(columns=UNIVERSE_COLUMNS)
    if os.path.exists(path):
        old = pd.read_csv(path, parse_dates=["date"])
    # 空表不参与 concat（同 append_records 的理由：pandas 对含全 NA 列的空表
    # 参与 concat 会告警，且未来版本会改变 dtype 推断规则）
    parts = [f for f in (old, new) if not f.empty]
    merged = (pd.concat(parts, ignore_index=True) if parts
              else pd.DataFrame(columns=UNIVERSE_COLUMNS))
    # **去重键必须含 category**：页面的分类是**重叠**的
    # （`我的自选` 是 `美股杠杆` 等的子集，`US.CONL` 会同时出现在两处）。
    # 只按 (date, code) 去重会**丢掉分类信息**（实测 379 → 361 行），
    # 而分类对系统有意义（"美股杠杆"才是需要的那张表）。
    merged = (merged.drop_duplicates(subset=["date", "category", "code"],
                                     keep="last")
              .sort_values(["date", "category", "code"]).reset_index(drop=True))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    merged.to_csv(path, index=False, encoding="utf-8")
    return merged, len(new)


# ================================================================ 个股贪恐视图（第 14.5 条）
# 页面：`https://fe.szdt.tech/invest/#/stock_scan`。
# **为什么需要它**：11 张分类表**不含** AXTX / CRCG（实测 379 行全表零命中），
# 这两个实盘持仓标的只能从本视图的「查询」取。详见 docs/trading-discipline.md 14.5。

def universe_values(universe_df, symbols=None):
    """全市场表 → `{symbol: fg_index}`，**只含表里出现过**的标的。

    **这是"覆盖判定"与"取值"的唯一口径**（第 14.5 条）：`covered_symbols` /
    `missing_symbols` 都从它派生，`fetch_shoutu.py` 的 `main()` 也用它取值。
    三者**必须**同口径 —— 否则会出现「判定为已覆盖 ⇒ 不去查询」**同时**
    「取不到值 ⇒ 不在 vals 里」⇒ 该标的**当天静默缺失**：下游
    `shoutu_symbol_index` 会把它回退成市场指数（不报错），序列出现空洞而无人察觉，
    且 `_warn_if_short` 比的是**行数**不是**标的是否齐全**，同样抓不到。

    **为什么用后缀而不是等值**：页面代码带市场前缀（`US.` / `HK.` / `SZ.`），
    而白名单只写标的本身。代码做 `strip().upper()` 归一化（页面实测是大写，
    归一化是防御性的；关键是**取值侧也走这里**，不会两边不一致）。

    同一标的多张分类表都出现时取**第一条**：页面分类是**重叠**的
    （`我的自选` ⊂ `美股杠杆`），实测同一标的在各表里值相同。

    不变量由 `tests/data/test_shoutu_page_query.py` 的
    `test_coverage_and_values_partition_the_whitelist` 钉死：
    `universe_values` 的键 ∪ `missing_symbols` == 白名单。
    """
    symbols = config.SHOUTU_SYMBOLS if symbols is None else list(symbols)
    if universe_df is None or len(universe_df) == 0:
        return {}
    return _universe_by(universe_df, "fg_index", symbols)


def universe_prices(universe_df, symbols=None):
    """全市场表 → `{symbol: price}`（只含表里出现过、且价格可解析的标的）。

    与 `universe_values` **共用同一处后缀口径**（`_universe_by`）—— 这是硬要求：
    取值与覆盖判定若用两套写法，就会出现「判定为已覆盖、却取不到值」的静默缺口。
    用途：把价格与贪恐指数**并列留存**，供「价格 × 情绪」对照。
    """
    return _universe_by(universe_df, "price", symbols)


def _universe_by(universe_df, field, symbols=None):
    """按**同一处**后缀口径，把全市场表的某一列取成 `{symbol: value}`。

    `field` 取 `fg_index`（贪恐值）或 `price`（市价）。**不可解析的值跳过** ——
    对 `fg_index` 而言 `parse_universe_rows` 已保证非 NaN；对 `price` 而言
    跳过即"这个标的没拿到价"，与给 NaN 在下游等价。
    """
    symbols = config.SHOUTU_SYMBOLS if symbols is None else list(symbols)
    if universe_df is None or len(universe_df) == 0:
        return {}
    codes = universe_df["code"].dropna().astype(str).str.strip().str.upper()
    vals = pd.to_numeric(universe_df[field], errors="coerce")
    out = {}
    for s in symbols:
        hit = vals[codes.str.endswith("." + s)].dropna()
        if len(hit):
            out[s] = float(hit.iloc[0])
    return out


def covered_symbols(universe_df, symbols=None):
    """全市场表**覆盖到**的标的（按代码后缀匹配：`US.TQQQ` → `TQQQ`）。

    就是 `universe_values` 的**键集**（顺序按白名单）—— 刻意不另写一套后缀匹配：
    两套写法正是 2026-09-24 那次「判定与取值不一致」的成因。
    """
    return list(universe_values(universe_df, symbols))


def missing_symbols(universe_df, symbols=None):
    """全市场表**未覆盖**的标的，按 `symbols` 顺序返回。

    **这是成本闸门**（第 14.5 条）：11 张分类表是**一次页面加载**
    （零逐标的请求），而个股贪恐视图的「查询」是**一标的一请求**。
    故只对这里返回的标的去查询，分类表已覆盖的**一律不查**。

    这是"重复查询不消耗剩余额度"的**第一道**保证（本地根本不发请求）；
    第二道在服务端 —— 按标的**去重计数**，实测：连查两次 AXTX，
    页面「已查询股票个数 2，剩余额度 28」**两次读数相同**（2026-09-24）。
    """
    symbols = config.SHOUTU_SYMBOLS if symbols is None else list(symbols)
    covered = set(covered_symbols(universe_df, symbols))
    return [s for s in symbols if s not in covered]


def parse_scan_result(payload):
    """解析**个股贪恐视图**的查询结果面板（`.scan-result`）。

    入参是 `scripts/fetch_shoutu.py` 从页面读出的**原始字段**（全是字符串）：

        {"code": "US.AXTX", "score": "-21", "name": "2倍做多AXTI ETF-Tradr",
         "zone": "中性区间", "price": "30.53", "time": "2026-09-24 09:41:16"}

    返回 `{"symbol", "value", "name", "zone", "price", "time"}`。
    **量程 −100~100，不做任何转换** —— 与分类表、partner API **同口径**
    （实测：同一标的在分类表与查询面板上的值一致）。

    **⚠️ 量程校验只是兜底，不是防串档的主力。** 面板里同时有价格（`30.53`）、
    杠杆（`2x`）、刻度标签（`100` / `-100`）三种数字，它们**都落在量程内**
    ⇒ 下游 `append_records` 的越界断言（`shoutu.py` 的 `out_of_range`）**拦不住**
    「读错元素但值恰好合法」。真正防串档的是**读取侧的三重锚定**（见
    `scripts/fetch_shoutu.py` 的 `QUERY_ONE`）：`.score-label` 的**固定文本**
    「实时贪恐指数」、面板**可见**、`.result-code` 与所查标的**吻合**。
    本函数的 `code` 白名单是这三重之外的最后一道，不是第一道。
    （若页面改版导致锚点失效，`copy` 为 undefined ⇒ `strong` 为 null ⇒
    这里立刻报「score 无法解析」，**不会静默取到别的数字**。）

    三条硬约束，每条对应一个真实失败模式：

    1. `error` 字段存在即报错 —— 脚本用它表示「标的**不在**页面的已查询列表里」
       （此时只能走表单查询，会**消耗额度**）或「等面板超时」。静默当成缺值会让
       当天记录**悄悄少一只**，而 `append_records` 是覆盖语义，事后极难发现。
    2. `code` 必须在白名单内 —— 这是**选择器漂移**的兜底：读错元素时
       立刻报错，而不是把不相干的数字静默写进某个标的的序列。
    3. `score` 非数值即报错（未激活显示 `**`）—— **不静默变 NaN**，
       同 `parse_score_payload`。
    """
    payload = payload or {}
    if payload.get("error"):
        raise ShoutuError("个股贪恐查询失败：%s（code=%s）"
                          % (payload["error"], payload.get("code")))
    code = str(payload.get("code") or "").strip().upper()
    sym = code.rsplit(".", 1)[-1]
    if sym not in config.SHOUTU_SYMBOLS:
        raise ShoutuError(
            "个股贪恐查询返回了白名单外的代码：%r（解析为 %r）。\n"
            "若确需新增，请先改 config.SHOUTU_SYMBOLS（第 8 条流程）；"
            "否则多半是页面选择器漂移，读到了**别的标的**。"
            % (code, sym))
    try:
        value = float(payload["score"])
    except (KeyError, TypeError, ValueError):
        raise ShoutuError("个股贪恐查询的 score 无法解析：%r"
                          % (payload.get("score"),))
    return {
        "symbol": sym,
        "value": value,
        "name": payload.get("name"),
        "zone": payload.get("zone"),
        "price": pd.to_numeric(payload.get("price"), errors="coerce"),
        "time": payload.get("time"),
    }


def parse_history_payload(payload, symbol):
    """解析服务端**历史**端点（`stock_emotion/history`）的响应 → 长表。

    载荷（2026-09-24 实测）::

        {"status":1,"msg":"成功",
         "data":[{"score":-75,"price":"35.220","date":"2024-08-16"}, …]}

    返回列 `HISTORY_COLUMNS`（`date,symbol,score,price`）。

    **`data: []` 不是错误**：它表示服务端**对该标的没有历史**
    （实测 AXTX / CRCG 如此）⇒ 返回**空表**，由调用方打印告警。
    抛错会让整次抓取失败，掩盖「其余标的是好的」这一事实。

    校验分工：
      - `status != 1` / `data` 不是列表 ⇒ 报错（带上服务端 msg）
      - `score` 非数值或**越界** ⇒ 报错（口径变了必须响，不静默截断）
      - `date` 不可解析 ⇒ 报错（历史按日期索引，日期坏了整段不可用）
      - **`price` 不可解析 ⇒ 置 NaN，不报错**（参考量，不是信号）
    """
    payload = payload or {}
    if payload.get("status") != 1:
        raise ShoutuError("守猪待兔历史接口返回错误：status=%s msg=%s"
                          % (payload.get("status"), payload.get("msg")))
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise ShoutuError("守猪待兔历史响应缺少 data 列表：%s" % str(payload)[:200])

    sym = str(symbol).strip().upper()
    if sym not in config.SHOUTU_SYMBOLS:
        raise ShoutuError(
            "未知标的：%s。已知标的为 %s。\n"
            "新增标的须先改 config.SHOUTU_SYMBOLS（第 8 条流程）。"
            % (sym, config.SHOUTU_SYMBOLS))
    if not rows:
        return pd.DataFrame(columns=HISTORY_COLUMNS)

    recs = []
    for row in rows:
        row = row or {}
        try:
            score = float(row["score"])
        except (KeyError, TypeError, ValueError):
            raise ShoutuError("守猪待兔历史的 score 无法解析：%r（date=%r）"
                              % (row.get("score"), row.get("date")))
        date = pd.to_datetime(row.get("date"), errors="coerce")
        if pd.isna(date):
            raise ShoutuError("守猪待兔历史的 date 无法解析：%r" % (row.get("date"),))
        recs.append({"date": date, "symbol": sym, "score": score,
                     "price": pd.to_numeric(row.get("price"), errors="coerce")})

    out = pd.DataFrame(recs, columns=HISTORY_COLUMNS)
    lo, hi = config.SHOUTU_FNG_MIN, config.SHOUTU_FNG_MAX
    oor = out[(out["score"] < lo) | (out["score"] > hi)]
    if len(oor):
        raise ShoutuError(
            "守猪待兔历史越界（量程 %g ~ %g）：%d 行，例：\n%s\n"
            "请确认数据源口径是否变化，不要静默截断。"
            % (lo, hi, len(oor), oor.head(3).to_string(index=False)))
    return out


def record_history(df, path=None):
    """把服务端历史**幂等**并入 `Data/raw/shoutu_history.csv`，返回合并后的长表。

    三条硬约束：

    1. **空表是 no-op** —— 服务端对某些标的（实测 AXTX / CRCG）返回 `data: []`，
       此时**不创建文件、不报错**（调用方打印告警即可）。
       ⚠️ **返回值语义要小心**：空表分支返回 `load_shoutu_history(path)`，
       即**文件现有内容**、**不是空表** —— 若文件里已有**别的**标的，返回值**非空**。
       ⇒ **不要用返回值判断"本次写了多少行"**（要那个数请自己 `len(df)`）。
    2. **幂等**：同 `(date, symbol)` **覆盖**（服务端修订历史时应生效）。
    3. **排序落盘**：按 `(date, symbol)`，使 diff 稳定、可 review。

    ⚠️ 与 `append_records` 的**口径不同**：那个写**本地 06:30 采样**，
    这个写**服务端权威日值**。**不要混用**（spec §5.4）。
    """
    path = path or config.SHOUTU_HISTORY_PATH
    new = pd.DataFrame(df, columns=HISTORY_COLUMNS)
    if new.empty:
        return loader.load_shoutu_history(path)

    new["date"] = pd.to_datetime(new["date"], errors="coerce").dt.normalize()
    new["symbol"] = new["symbol"].astype(str).str.strip().str.upper()
    new["score"] = pd.to_numeric(new["score"], errors="coerce")
    new["price"] = pd.to_numeric(new["price"], errors="coerce")

    bad = new[new["date"].isna() | new["score"].isna() | (new["symbol"] == "")]
    if len(bad):
        raise ShoutuError("历史数据含无法解析的行：\n%s"
                          % bad.head(5).to_string(index=False))
    unknown = sorted(set(new["symbol"]) - set(config.SHOUTU_SYMBOLS))
    if unknown:
        raise ShoutuError("未知标的：%s。已知标的为 %s。"
                          % (unknown, config.SHOUTU_SYMBOLS))
    lo, hi = config.SHOUTU_FNG_MIN, config.SHOUTU_FNG_MAX
    oor = new[(new["score"] < lo) | (new["score"] > hi)]
    if len(oor):
        raise ShoutuError("守猪待兔历史越界（量程 %g ~ %g）：\n%s"
                          % (lo, hi, oor.head(5).to_string(index=False)))

    old = loader.load_shoutu_history(path)
    parts = [f for f in (old, new) if not f.empty]
    merged = (pd.concat(parts, ignore_index=True) if parts
              else pd.DataFrame(columns=HISTORY_COLUMNS))
    merged = (merged.drop_duplicates(subset=["date", "symbol"], keep="last")
              .sort_values(["date", "symbol"]).reset_index(drop=True))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    merged.to_csv(path, index=False, encoding="utf-8")
    return loader.load_shoutu_history(path)


def recorded_symbols(path=None):
    """已录入的标的与天数（供 CLI 显示与"还缺什么"判断）。"""
    wide = loader.load_shoutu_fng(path)
    if wide.empty:
        return {}
    return {c: int(wide[c].notna().sum()) for c in wide.columns}
