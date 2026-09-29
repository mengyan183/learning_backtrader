# -*- coding: utf-8 -*-
"""个股贪恐视图（`#/stock_scan`）的**成本闸门**与结果解析测试（第 14.5 条）。

只测**可离线复现**的部分：覆盖判定 + 面板字段解析。
真正驱动浏览器的编排在 `scripts/fetch_shoutu.py`（依赖 `bsk`，无法在 CI 里跑）。

**为什么这两块必须锁住**：

1. 覆盖判定是**成本闸门** —— 11 张分类表是**一次页面加载**（零逐标的请求），
   而个股贪恐视图的「查询」是**一标的一请求**。判错会让分类表已覆盖的标的
   也去发请求，白白消耗「剩余额度」。
2. 面板解析是**选择器约定** —— 页面改版时最容易**静默失效**的部分：
   读错元素**不会报错**，只会把别的数字当成贪恐值写进分布。
   （分布正是丙方案的唯一输入，错数据比没数据更糟。）
"""
import ast
import importlib
import os
import sys

import pandas as pd
import pytest

from fg_system import config
from fg_system.data import shoutu


def _universe(codes, date="2026-09-24"):
    """用**页面实际格式**构造全市场表（`分类~代码~名称~贪恐~市价~规模`）。"""
    lines = ["美股杠杆~%s~名称~33~1.0~1.0" % c for c in codes]
    return shoutu.parse_universe_rows(lines, date=date)


# ================================================================ 成本闸门

def test_covered_symbols_matches_code_suffix():
    """覆盖判定按**代码后缀**（`US.TQQQ` → `TQQQ`）。

    页面代码带市场前缀（`US.` / `HK.` / `SZ.`），而白名单只有标的本身 ——
    口径必须与 `fetch_shoutu.py` 既有写法一致，不能另造一套。
    """
    df = _universe(["US.TQQQ", "HK.07226", "SZ.159919"])
    assert shoutu.covered_symbols(df, ["TQQQ", "07226", "159919", "AXTX"]) == \
        ["TQQQ", "07226", "159919"]


def test_missing_symbols_returns_uncovered_only():
    """**成本闸门**：分类表已覆盖的标的**一律不查**。

    实测（2026-09-24）：11 张分类表覆盖 6 个标的，缺 `AXTX` / `CRCG` ——
    只有这两个该去 `#/stock_scan` 发查询。
    """
    df = _universe(["US.CONL", "US.YINN", "US.GDXU",
                    "US.TQQQ", "US.SOXL", "US.UPRO"])
    assert shoutu.missing_symbols(df) == ["AXTX", "CRCG"]


def test_missing_symbols_empty_when_all_covered():
    """**守卫**：全覆盖时返回空 —— 调用方据此**完全不打开**个股贪恐页。

    这条是"重复查询不消耗额度"的**第一道**保证（本地不发请求）；
    第二道在服务端（按标的去重计数，见 `test_scan_quota_*` 记录的实测）。
    """
    df = _universe(["US." + s for s in config.SHOUTU_SYMBOLS])
    assert shoutu.missing_symbols(df) == []


def test_missing_symbols_follow_whitelist_order():
    """顺序取自**白名单**而不是页面顺序 —— 请求顺序稳定，日志可逐日比对。"""
    df = _universe(["US.UPRO"])
    assert shoutu.missing_symbols(df) == [
        s for s in config.SHOUTU_SYMBOLS if s != "UPRO"]


def test_missing_symbols_on_empty_universe_is_the_whole_whitelist():
    """全市场表为空（sweep 失败）时，缺失集合就是整张白名单。

    **注意调用方**：`fetch_shoutu.py` 在全市场表零命中时**提前失败退出**，
    不拿这个结果去逐标的查询 —— 因为那 8 个里只有 2 个在页面的已查询列表里，
    逐个查会失败，而失败会触发 `.cmd` 的 API 兜底（那才是正确的恢复路径）。
    """
    assert shoutu.missing_symbols(pd.DataFrame()) == list(config.SHOUTU_SYMBOLS)
    assert shoutu.missing_symbols(None) == list(config.SHOUTU_SYMBOLS)


def test_missing_symbols_ignores_codes_outside_whitelist():
    """页面里的非白名单代码**不参与**判定（否则会被当成"要查的标的"）。"""
    df = _universe(["US.AAPL", "US.TQQQ"])
    missing = shoutu.missing_symbols(df)
    assert "AAPL" not in missing
    assert "TQQQ" not in missing


# ================================================================ 面板解析

# 2026-09-24 实测 dump（`div.scan-result` 面板，全部字段都是**字符串**）
_SCAN = {"code": "US.AXTX", "score": "-21", "name": "2倍做多AXTI ETF-Tradr",
         "zone": "中性区间", "price": "30.53", "time": "2026-09-24 09:41:16"}


def test_parse_scan_result_extracts_value():
    """面板字段 → 录入所需的 `{symbol, value}`（其余字段供日志与审计）。"""
    out = shoutu.parse_scan_result(_SCAN)
    assert out["symbol"] == "AXTX"
    assert out["value"] == pytest.approx(-21.0)
    assert out["name"] == "2倍做多AXTI ETF-Tradr"
    assert out["zone"] == "中性区间"
    assert out["price"] == pytest.approx(30.53)
    assert out["time"] == "2026-09-24 09:41:16"


def test_parse_scan_result_preserves_negative_scale():
    """**关键**：量程 −100~100，**不做任何转换** —— 与分类表、partner API 同口径。

    若误按 0~100 处理，负数会被当异常值，或静默错判档位。
    """
    assert shoutu.parse_scan_result(dict(_SCAN, score="-67"))["value"] == pytest.approx(-67.0)
    assert shoutu.parse_scan_result(dict(_SCAN, score="100"))["value"] == pytest.approx(100.0)
    assert shoutu.parse_scan_result(dict(_SCAN, score="-100"))["value"] == pytest.approx(-100.0)


def test_parse_scan_result_raises_on_error_payload():
    """**守卫**：脚本用 `error` 表示「标的**不在**已查询列表」或「等面板超时」。

    必须报错，**不得**当成缺值跳过 —— 跳过会让当天记录**悄悄少一只**，
    而 `append_records` 是覆盖语义，事后极难发现（同 `collect_scores`）。
    """
    with pytest.raises(shoutu.ShoutuError, match="NOT_IN_LIST"):
        shoutu.parse_scan_result({"error": "NOT_IN_LIST", "code": "AXTX"})
    with pytest.raises(shoutu.ShoutuError, match="TIMEOUT"):
        shoutu.parse_scan_result({"error": "TIMEOUT", "code": "AXTX"})


def test_parse_scan_result_raises_on_non_numeric_score():
    """未激活时数值显示 `**` ⇒ 必须报错，**不能静默变 NaN**（同 `parse_score_payload`）。"""
    with pytest.raises(shoutu.ShoutuError):
        shoutu.parse_scan_result(dict(_SCAN, score="**"))
    with pytest.raises(shoutu.ShoutuError):
        shoutu.parse_scan_result({"code": "US.AXTX"})       # 缺 score


def test_parse_scan_result_rejects_symbol_outside_whitelist():
    """**守卫**：代码必须在白名单内。

    这是**选择器漂移**的兜底：若 `.result-code` 选错、读到了别的标的，
    这里会立刻报错，而不是把一个不相干的数字静默写进该标的的序列。
    """
    with pytest.raises(shoutu.ShoutuError, match="白名单"):
        shoutu.parse_scan_result(dict(_SCAN, code="US.AAPL"))


# ================================================================ 脚本层守卫（静态）
# 编排依赖 `bsk`（需要浏览器），无法在 CI 里真跑 ⇒ 只能读源码做静态断言，
# 同 `tests/test_shoutu_daily_cmd.py::test_daily_task_prefers_browser_path` 的做法。
#
# **⚠️ 这类守卫的固有局限（必须知道，别高估它们）**：
#   - 判据是**文本/AST 级**的，只证明"源码里有这个写法"，**不证明它在执行路径上**、
#     更不证明**取的是哪个元素的值**。JS 的取值正确性只能靠**实机跑**
#     （实测结果见 `docs/trading-discipline.md` 第 14.5 条「E1 补」）。
#   - 故凡涉及"函数**被调用**"的判据，一律走 `_called_names`（AST），不用字符串
#     包含 —— 后者对**注释**同样命中，是结构性假阳（2026-09-24 评审指出）。

def _called_names(path):
    """该模块里**实际被调用**的函数/方法名（`a.b(...)` → `b`，`f(...)` → `f`）。

    只看真正构成 `ast.Call` 节点的名字：把调用注释掉、或在注释里写上函数名，
    都**不会**让它通过。
    """
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                names.add(func.attr)
            elif isinstance(func, ast.Name):
                names.add(func.id)
    return names


def test_script_queries_only_uncovered_symbols():
    """**守卫**：脚本必须**调用** `shoutu.missing_symbols` 决定查哪些标的。

    且**不得把标的写成字符串字面量**（写死就失去了成本闸门的意义：
    白名单一变，写死的那两个仍会被查询，而新缺的标的反而漏掉）。

    **判据是"带引号"而不是裸词**：脚本文档里**提到** AXTX / CRCG 是必要的
    （说明这个视图是为什么而加的），那是散文不是代码。裸词匹配会把说明文字
    误判成硬编码，逼着人删掉有用的文档 —— 故只查 `"AXTX"` / `'AXTX'` 这种
    **字面量**形式。
    """
    p = os.path.join(config.ROOT, "scripts", "fetch_shoutu.py")
    called = _called_names(p)
    assert "missing_symbols" in called, \
        "脚本没有**调用** shoutu.missing_symbols 做成本闸门（只写在注释里不算）"
    # 名字可以是 `fetch_scan_records`（保留 price 的主函数）或它的薄包装
    # `fetch_scan_scores` —— 两者任一在场，都说明"未覆盖的标的会去补查"。
    assert ("fetch_scan_records" in called) or ("fetch_scan_scores" in called), \
        "脚本没有去个股贪恐视图补查分类表未覆盖的标的"
    text = open(p, encoding="utf-8").read()
    for sym in ("AXTX", "CRCG"):
        for literal in ('"%s"' % sym, "'%s'" % sym):
            assert literal not in text, \
                "脚本把 %s 写死成了字面量 —— 应由分类表覆盖情况（missing_symbols）决定" % sym


def _script_module():
    """导入 `scripts/fetch_shoutu.py`（**不触发** bsk —— 它只在函数内被调用）。"""
    p = os.path.join(config.ROOT, "scripts")
    if p not in sys.path:
        sys.path.insert(0, p)
    return importlib.import_module("fetch_shoutu")


def test_query_one_js_embeds_symbol_as_a_single_string_literal():
    """**守卫**：标的必须**恰好**被包成**一层** JS 字符串字面量。

    模板里已经写了引号，若再套一层 `json.dumps` 就会生成
    `const CODE=""AXTX"";` —— **JS 语法错误**。表现是 `bsk evaluate` 返回的
    JSON 里没有 `value` 字段，抛 `KeyError: 'value'`：
    **看起来像页面改版，实际是拼接 bug**（2026-09-24 实机踩到，误判成本很高）。
    """
    js = _script_module().query_one_js("AXTX")
    assert 'const CODE="AXTX";' in js
    assert '""' not in js, "标的被套了两层引号 —— JS 语法错误"
    assert "__CODE__" not in js, "占位符没被替换"


def test_query_one_js_visibility_check_survives_fixed_positioning():
    """**守卫**：面板可见性必须用 `getClientRects()`，**不能**用 `offsetParent`。

    `.scan-result` 是 `position: fixed` —— 即使**完全可见**，`offsetParent`
    也返回 `null`（实测：可见时 `rects=1` 而 `offsetParent=false`）。
    用它做判据 ⇒ 查询**永远等不到结果**，最终报 TIMEOUT，
    **看起来像页面改版或账号失效，实际是判据选错**（2026-09-24 实机踩到）。
    """
    js = _script_module().query_one_js("AXTX")
    assert "getClientRects" in js
    assert "offsetParent" not in js, \
        "offsetParent 对 position:fixed 的元素恒为 null，不能用作可见性判据"


# ================================================================ 覆盖判定与取值必须**同口径**
# 2026-09-24 评审发现：`covered_symbols` 对代码做了 `.upper()` 归一化，而
# `fetch_shoutu.py` 的 `main()` 取值用**未归一化**的 `endswith`。
# 两者不一致时会出现「判定为已覆盖 ⇒ 不查询」**同时**「取不到值 ⇒ 不在 vals 里」
# ⇒ 该标的**当天静默缺失**（下游 `shoutu_symbol_index` 回退市场指数，不报错）。

def test_universe_values_extracts_one_value_per_symbol():
    """全市场表 → `{symbol: fg_index}`，只含表里出现过的标的。"""
    df = _universe(["US.CONL", "US.TQQQ"])
    assert shoutu.universe_values(df, ["TQQQ", "CONL"]) == {"TQQQ": 33.0, "CONL": 33.0}
    assert shoutu.universe_values(df, ["AXTX"]) == {}


def test_universe_values_takes_first_hit_when_categories_overlap():
    """同一标的多张分类表都出现时取**第一条**。

    页面分类是**重叠**的（`我的自选` ⊂ `美股杠杆`），实测同一标的在各表里值相同
    ⇒ 取第一条即可，且必须与 `record_universe` 的 `keep=last` 去重不冲突。
    """
    df = shoutu.parse_universe_rows([
        "我的自选~US.CONL~两倍Coin~27~6.79~6.14",
        "美股杠杆~US.CONL~两倍Coin~27~6.79~6.14",
    ])
    assert shoutu.universe_values(df, ["CONL"]) == {"CONL": 27.0}


def test_coverage_and_values_partition_the_whitelist():
    """**不变量**：`universe_values` 的键 ∪ `missing_symbols` **必须恰好**等于白名单。

    任何标的一旦掉进两者的**缝**里，当天就静默缺失 —— 而且没有任何告警：
    `_warn_if_short` 比的是**行数**，不是**标的是否齐全**。

    这条不变量就是「覆盖判定与取值同口径」的可执行定义，比逐个断言强得多：
    它同时挡住"归一化不一致""某一侧漏写"这两类改法。
    """
    cases = [
        ["US.CONL", "US.YINN"],                       # 部分覆盖
        ["US." + s for s in config.SHOUTU_SYMBOLS],   # 全覆盖
        ["US.AAPL", "US.GDP"],                        # 全是白名单外的代码
        [],                                           # 空表
    ]
    for codes in cases:
        df = _universe(codes)
        covered = set(shoutu.universe_values(df))
        missing = set(shoutu.missing_symbols(df))
        assert covered | missing == set(config.SHOUTU_SYMBOLS), codes
        assert not (covered & missing), codes


def test_lowercase_codes_are_covered_and_valued_consistently():
    """**守卫**：页面若返回**小写**代码，覆盖判定与取值必须给出**一致**的结论。

    2026-09-24 实机：页面返回大写（`US.AXTX`），所以这条当时不会暴露。
    但库函数归一化了、取值路径没归一化 ⇒ 一旦页面改成小写，TQQQ 会被判为
    「已覆盖」（不去查询）**同时**取不到值 ⇒ 当天静默缺失。
    """
    df = _universe(["us.tqqq", "us.axTx"])
    assert shoutu.universe_values(df, ["TQQQ"]) == {"TQQQ": 33.0}
    assert shoutu.missing_symbols(df, ["TQQQ"]) == []
    assert shoutu.universe_values(df, ["AXTX"]) == {"AXTX": 33.0}
    assert shoutu.missing_symbols(df, ["AXTX"]) == []


def test_covered_symbols_is_the_key_set_of_universe_values():
    """**守卫**：`covered_symbols` 必须就是 `universe_values` 的键集（顺序按白名单）。

    两个函数不许各写一套后缀匹配 —— 那正是本次不一致的成因。
    """
    df = _universe(["US.TQQQ", "US.CONL"])
    for symbols in (None, ["CONL", "TQQQ", "AXTX"], ["AXTX"]):
        assert shoutu.covered_symbols(df, symbols) == \
            list(shoutu.universe_values(df, symbols))


# ================================================================ 对照脚本也要纳入本视图
# 编排依赖 bsk（需浏览器），无法在 CI 里真跑 ⇒ 静态守卫，同上面的做法。

def test_compare_script_also_reads_the_scan_view():
    """**守卫**：对照脚本必须把**分类表未覆盖**的标的也纳入**页面侧**。

    否则 AXTX / CRCG 恒为 `page_missing` ⇒ 那两个标的**从不参与对照**，
    等于放弃了「API 与页面同口径」的验证 —— 而 `emo_area` 填错（唯一会
    **静默给出错误数值**的字段）正是靠这个对照发现的。
    """
    p = os.path.join(config.ROOT, "scripts", "compare_shoutu.py")
    called = _called_names(p)
    assert "missing_symbols" in called, \
        "对照脚本没**调用** missing_symbols —— AXTX/CRCG 会恒为 page_missing"
    assert "fetch_scan_scores" in called, \
        "对照脚本没去个股贪恐视图补取 —— 那两个标的等于没对照"


# ================================================================ 落盘顺序不变量
# "当天数据不会写一半"目前来自 `main()` 的**语句顺序**（先收齐 vals、再落盘），
# 不是来自 try/except。没有任何东西阻止后来的人把它改成"边查边写" ⇒ 用测试表达它。

def test_main_writes_no_series_when_scan_query_fails(monkeypatch):
    """**守卫**：个股贪恐查询失败时，`main()` **不得**写逐标的时序。

    构造：6 个标的由分类表覆盖（`vals` 非空 ⇒ 不会提前 return），
    第 7/8 个（AXTX / CRCG）由 `fetch_scan_scores` 负责，让它抛错。

    期望：异常冒泡出去（⇒ `.cmd` 非零退出 ⇒ API 兜底），
    而 `append_records` **一次都没被调用** —— 磁盘上不会出现"写一半"。
    """
    fs = _script_module()
    df = _universe(["US." + s for s in config.SHOUTU_SYMBOLS
                    if s not in ("AXTX", "CRCG")])
    appended = []

    def boom(*_a, **_k):
        raise RuntimeError("查询失败")

    monkeypatch.setattr(fs, "fetch_universe", lambda date=None: (df, len(df)))
    monkeypatch.setattr(fs, "_warn_if_short", lambda *a, **k: None)
    monkeypatch.setattr(fs.shoutu, "record_universe",
                        lambda *a, **k: (df, len(df)))
    monkeypatch.setattr(fs.shoutu, "append_records",
                        lambda *a, **k: appended.append(a))
    monkeypatch.setattr(fs, "fetch_scan_records", boom)
    monkeypatch.setattr(sys, "argv", ["fetch_shoutu.py"])

    with pytest.raises(RuntimeError, match="查询失败"):
        fs.main()

    assert appended == [], \
        "查询失败却仍调用了 append_records —— 当天逐标的时序会写一半"


def test_main_writes_prices_from_both_sources(monkeypatch, tmp_path):
    """**端到端（离线）**：`main()` 必须把**两条来源**的 price 都落盘。

    - 分类表 → `shoutu.universe_prices(df)`
    - 个股贪恐视图 → `fetch_scan_records` 的 `price`

    这是 Step A2 的**交付物**：让「价格 × 贪恐指数」能在同一张表里对照
    （2026-09-24 用户要求）。缺任何一条，对照就会有一半标的是空的。
    """
    fs = _script_module()
    df = _universe(["US." + s for s in config.SHOUTU_SYMBOLS
                    if s not in ("AXTX", "CRCG")])
    out = tmp_path / "shoutu_fng.csv"
    monkeypatch.setattr(config, "SHOUTU_FNG_PATH", str(out))
    monkeypatch.setattr(fs, "fetch_universe", lambda date=None: (df, len(df)))
    monkeypatch.setattr(fs, "_warn_if_short", lambda *a, **k: None)
    monkeypatch.setattr(fs.shoutu, "record_universe", lambda *a, **k: (df, len(df)))
    monkeypatch.setattr(fs, "fetch_scan_records",
                        lambda syms: {"AXTX": {"value": -21.0, "price": 30.4},
                                      "CRCG": {"value": -70.0, "price": 15.0}})
    monkeypatch.setattr(sys, "argv", ["fetch_shoutu.py"])

    assert fs.main() == 0
    raw = pd.read_csv(out)
    got = dict(zip(raw["symbol"], raw["price"]))
    assert got["TQQQ"] == pytest.approx(1.0), "分类表来源的 price 没落盘"
    assert got["AXTX"] == pytest.approx(30.4), "查询面板来源的 price 没落盘"
    assert got["CRCG"] == pytest.approx(15.0)
