# -*- coding: utf-8 -*-
"""守猪待兔页面编排（bsk）—— 历史抓取与个股贪恐视图查询的公共层。

背景：bsk 时代（2026-09-24 前）的历史抓取依赖本模块；该模块随 bsk 通道被
partner-API 通道替代时删除，导致 `fetch_shoutu_history.py`（全量历史）静默断更
（09-29 停更）。2026-10-07 重建时**只保留了薄封装**，又丢掉了页面编排契约
（missing_symbols 成本闸门 / fetch_universe / fetch_scan_records / main），
`tests/data/test_shoutu_page_query.py` 的三个守卫随之红灯。本次补回完整编排层。

本模块提供：
    bsk(args, session=None) / bsk_eval(js, session)  —— bsk CLI 封装（薄）
    fetch_universe(date=None)                        —— 全市场分类表（11 张表一次
                                                        页面加载，零逐标的请求）
    query_one_js(symbol)                             —— 个股贪恐视图「查询」的 JS
    fetch_scan_records(symbols)                      —— 未覆盖标的逐只查询
                                                        （一标的一请求，保留 price）
    fetch_scan_scores(symbols)                       —— 薄包装：只取 value（对照用）
    _warn_if_short(n)                                —— 行数告警（不全即提醒）
    run() / main()                                   —— 全量编排：先收齐、再落盘

安全约束（继承 fetch_shoutu_history.py）：
    挂钩 JS 只记录 URL 含 `stock_emotion/history` 的响应体；同会话的许可信息
    端点（含明文凭据）响应一律丢弃，不进日志不进文件。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fg_system import config                     # noqa: E402
from fg_system.data import shoutu                # noqa: E402

_BSK = "/Users/xingguo/.local/bin/bsk"
UNIVERSE_PAGE = "https://fe.szdt.tech/invest/#/etf"
SCAN_PAGE = "https://fe.szdt.tech/invest/#/stock_scan"


def bsk(args, session=None):
    cmd = [_BSK] + [str(a) for a in args]
    if session:
        cmd += ["--session", str(session)]
    r = __import__("subprocess").run(cmd, capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        raise RuntimeError(
            "bsk %s failed rc=%s: %s" % (args, r.returncode, (r.stderr or r.stdout or "")[:300])
        )
    return r.stdout


def bsk_eval(js, session):
    out = bsk(["evaluate", js], session)
    return out.strip()


def _session():
    """起一个 bsk 会话，返回 session id。"""
    out = bsk(["session", "start", "--no-focus"]).strip().splitlines()
    sid = out[-1].strip() if out else ""
    if not sid:
        raise RuntimeError("未取得 bsk session id")
    return sid


# ================================================================ 全市场分类表

# 从 `#/etf` 分类表页提取行：`分类~代码~名称~贪恐~市价~规模`。
# 与 `shoutu.parse_universe_rows` 的格式约定一致（名称含空格，故用 `~` 分隔）。
# 选择器以实机验证为准（bsk 运行时手工核）——解析与校验都在库内测试锁死。
_EXTRACT_JS = (
    "(()=>{const out=[];"
    "document.querySelectorAll('tr').forEach(tr=>{"
    "const tds=[...tr.querySelectorAll('td')].map(td=>td.textContent.trim());"
    "if(tds.length<4)return;"
    "const cat=(tr.closest('table')||{}).getAttribute&&"
    "(tr.closest('table').getAttribute('data-category')||'')||'';"
    "const code=tds[0],name=tds[1],fg=tds[2];"
    "if(!code||!fg||isNaN(parseFloat(fg)))return;"
    "out.push([cat||'分类',code,name,fg,tds[3]||'',tds[4]||''].join('~'));});"
    "return out.join('\\n');})()"
)


def fetch_universe(date=None):
    """抓全市场分类表，返回 `(df, 行数)`。

    11 张分类表是**一次页面加载**（零逐标的请求）——成本闸门的第一道：
    覆盖判定（missing_symbols）只在这里做，绝不去逐标的查询已覆盖标的。
    """
    session = _session()
    try:
        bsk(["navigate", UNIVERSE_PAGE], session)
        time.sleep(6)
        raw = bsk_eval(_EXTRACT_JS, session)
        df = shoutu.parse_universe_rows(raw.splitlines(), date=date)
        return df, len(df)
    finally:
        try:
            bsk(["session", "stop", session])
        except Exception:
            pass


# ================================================================ 个股贪恐视图

def query_one_js(symbol):
    """触发「查询」的 JS：输入标的、派发事件、点击查询。

    测试守卫（tests/data/test_shoutu_page_query.py）：
      - 标的恰好一层 JS 字符串字面量 `const CODE="<SYM>";`
        （再套一层 json.dumps 会生成双层引号的 JS 语法错误）
      - 面板可见性必须用 `getClientRects()`，不能 `offsetParent`
        （`.scan-result` 是 position:fixed，可见时 offsetParent 恒 null）
    """
    return (
        "(()=>{"
        "const CODE=\"" + symbol + "\";"
        "const input=document.querySelector('input[type=\"text\"]')"
        "||document.querySelector('input');"
        "if(input){const setter=Object.getOwnPropertyDescriptor("
        "window.HTMLInputElement.prototype,'value').set;"
        "setter.call(input,'US.'+CODE);"
        "input.dispatchEvent(new Event('input',{bubbles:true}));"
        "input.dispatchEvent(new Event('change',{bubbles:true}));}"
        "const btn=[...document.querySelectorAll('button')]"
        ".find(b=>/查询|搜/.test(b.textContent||''));"
        "if(btn)btn.click();"
        "const panel=document.querySelector('.scan-result');"
        "return panel&&panel.getClientRects().length?panel.textContent:'QUERY_SENT';"
        "})()"
    )


_READ_PANEL_JS = (
    "(()=>{const p=document.querySelector('.scan-result');"
    "if(!p||p.getClientRects().length===0)return 'TIMEOUT';"
    "const t=s=>{const el=p.querySelector(s);return el?el.textContent.trim():''};"
    "return JSON.stringify({code:t('[class*=\"code\"]'),"
    "score:t('[class*=\"score\"]'),name:t('[class*=\"name\"]'),"
    "zone:t('[class*=\"zone\"]'),price:t('[class*=\"price\"]'),"
    "time:t('[class*=\"time\"]')});})()"
)


def _wait_panel(session, timeout=30):
    """轮询查询结果面板，返回 `parse_scan_result` 可吃的 dict。

    超时抛错（不得静默跳过 —— 跳过会让当天记录悄悄少一只，
    而 append_records 是覆盖语义，事后极难发现）。
    """
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        raw = bsk_eval(_READ_PANEL_JS, session)
        if raw != "TIMEOUT":
            last = raw
            break
        time.sleep(1.5)
    if not last:
        raise shoutu.ShoutuError("TIMEOUT: 查询面板未出现（%ss）" % timeout)
    try:
        payload = json.loads(last)
    except ValueError as e:
        raise shoutu.ShoutuError("面板返回值不是 JSON: %s" % str(e))
    return shoutu.parse_scan_result(payload)


def fetch_scan_records(symbols):
    """对**未覆盖**标的逐只查询个股贪恐视图，返回 `{symbol: {value, price}}`。

    任一标的失败即抛错（与历史抓取同一约定）：静默跳过会让当天**悄悄缺标的**。
    """
    if not symbols:
        return {}
    session = _session()
    try:
        bsk(["navigate", SCAN_PAGE], session)
        time.sleep(6)
        out = {}
        for sym in symbols:
            bsk_eval(query_one_js(sym), session)
            rec = _wait_panel(session)
            out[rec["symbol"]] = {"value": rec["value"], "price": rec["price"]}
        return out
    finally:
        try:
            bsk(["session", "stop", session])
        except Exception:
            pass


def fetch_scan_scores(symbols):
    """薄包装：只取 value（`scripts/compare_shoutu.py` 对照用）。"""
    return {s: r["value"] for s, r in fetch_scan_records(symbols).items()}


# ================================================================ 编排

def _warn_if_short(n, symbols=None):
    symbols = symbols or config.SHOUTU_SYMBOLS
    if n < len(symbols):
        print("警告：本次仅收集到 %d/%d 个标的" % (n, len(symbols)),
              file=sys.stderr)


def main():
    """全量编排：先收齐、再落盘（当天数据不会写一半）。

    - 全市场表零命中 → **提前失败退出**（不拿白名单去逐标的查询——
      失败会触发 `.cmd` 的 API 兜底，那才是正确的恢复路径）。
    - 未覆盖标的（missing_symbols）才去 `#/stock_scan` 逐只查询（成本闸门）。
    - 价格双来源：分类表（universe_prices）+ 查询面板（fetch_scan_records）都落盘。
    """
    df, n = fetch_universe()
    if n == 0 or df is None or len(df) == 0:
        print("全市场表零命中，提前退出（不拿白名单去逐标的查询）",
              file=sys.stderr)
        return 1

    vals = shoutu.universe_values(df)
    prices = shoutu.universe_prices(df)
    shoutu.record_universe(df)

    missing = shoutu.missing_symbols(df)
    scans = {}
    if missing:
        scans = fetch_scan_records(missing)     # 任一失败抛错 ⇒ 不落盘

    merged = dict(vals)
    for s, rec in scans.items():
        merged[s] = rec["value"]
        prices[s] = rec["price"]

    recs = shoutu.mapping_to_frame(merged, prices=prices)
    shoutu.append_records(recs)
    _warn_if_short(len(merged))
    return 0


def run():
    sys.exit(main())


if __name__ == "__main__":
    run()
