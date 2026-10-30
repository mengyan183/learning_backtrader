# -*- coding: utf-8 -*-
"""守猪待兔**全量历史**抓取（spec: docs/superpowers/specs/2026-09-24-shoutu-history-and-price-design.md 的 Step A / A1）。

【为什么需要它】官方接口文档（`docs/查询实时贪恐.docx`）只有**实时**端点
`POST /api/partner/invest/stock/scan`，**没有历史**。而网页端
`#/stock_detail?code=<CODE>` 有一个「历史贪恐指数」页，其数据来自
`GET https://szdt.tech/api/invest/stock_emotion/history?code=<CODE>`
—— 实测返回 **543~625 个交易日**的逐日 `score` + `price`。

【为什么走浏览器而不是直连】该端点用**登录会话**鉴权：无鉴权、以及带 partner
那套 `X-Auth`（会员激活码）**都**返回
`{"status":2,"msg":"参数校验失败，IP 已记录"}` ⇒ 直连需要**提取登录凭据**，
而凭据不得从页面提取（browser-skill 规则）。
⇒ 改为**旁观页面自身的请求**：页面本来就是登录态，我们只读它的响应。

【⚠️ 安全约束（硬）】**只记录 URL 含 `stock_emotion/history` 的响应体**。
同一次挂钩会经过**许可信息**端点，而它的响应里含**明文凭据**
（会员令牌、钉钉机器人密钥）—— 不过滤就会把凭据写进日志或文件。
`tests/data/test_shoutu_history.py::test_script_only_records_the_history_endpoint`
把这条钉死。

【用法】
    python scripts/fetch_shoutu_history.py                    # 白名单全部
    python scripts/fetch_shoutu_history.py --symbols TQQQ,SOXL
"""
import argparse
import datetime
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fg_system import config                     # noqa: E402
from fg_system.data import shoutu                # noqa: E402

import fetch_shoutu as fs                        # noqa: E402  复用 bsk 封装（同 compare_shoutu）

APP_PAGE = "https://fe.szdt.tech/invest/#/mine"
HISTORY_MARK = "stock_emotion/history"

# 挂钩：**只**记录 URL 含 HISTORY_MARK 的响应体，其余一律丢弃（安全约束）。
# 顺带把缓冲清空。`__shoutu_hooked` 保证**只装一次** —— 重复包装会让同一次
# 响应被记录多份（而且层数会随调用次数增长）。
HOOK = (
    "(()=>{"
    "const MARK='" + HISTORY_MARK + "';"
    "window.__shoutu_cap=[];window.__shoutu_all=[];"
    "const rec=(u,b)=>{const s=String(u);"
    # 2026-10-30：**所有** URL 都记一份（只 URL，不含响应体 ✓）——
    # 用来确认「页面到底用哪个端点取历史」✗（实测只发一次 `?code=US.X` 且返回空 ✗）
    "try{window.__shoutu_all.push(s)}catch(e){}"
    "if(s.indexOf(MARK)<0)return;"
    "try{window.__shoutu_cap.push({u:s,b:String(b||'')})}catch(e){}};"
    "if(!window.__shoutu_hooked){window.__shoutu_hooked=1;"
    "const OO=XMLHttpRequest.prototype.open,OS=XMLHttpRequest.prototype.send;"
    "XMLHttpRequest.prototype.open=function(m,u){this.__u=u;"
    "return OO.apply(this,arguments)};"
    "XMLHttpRequest.prototype.send=function(){"
    "this.addEventListener('load',()=>rec(this.__u,this.responseText));"
    "return OS.apply(this,arguments)};"
    "const OF=window.fetch;window.fetch=async function(){"
    "const r=await OF.apply(this,arguments);"
    "try{const c=r.clone();"
    "c.text().then(t=>rec(arguments[0]&&arguments[0].url||arguments[0],t))}catch(e){}"
    "return r};}"
    "return 'OK';})()"
)


def _goto(symbol, stock_id=None):
    """SPA 内切路由到该标的的详情页（**不整页重载** ⇒ 挂钩不会被冲掉）。

    必须**先离开再回来**：直接改 hash 到同一路由（只换 query）不会让组件重挂载，
    也就不会触发新请求（实测）。

    🔴 2026-10-30 修正：补 `tab=-1` ✗ —— 用户给的真实详情页 URL 是
    `#/stock_detail?id=875&tab=-1&name=三倍中国&code=US.YINN` ✗，
    而原来只带 `code` ✗ ⇒ 实测 8 个标的全部 `data: []` ✗，
    很可能是页面**没切到历史 tab** ⇒ 压根没请求 `stock_emotion/history` ✗。
    """
    # 🔴 2026-10-30 实测（记录所有 URL 后）：
    #   页面发出 `license_like?stock_id=undefined` ✗ ⇒ **组件拿不到 stock_id** ✗
    #   ⇒ 只发了一个降级的 `?code=US.YINN`（返回 data:[]）✗
    # 用户给的真实 URL 是 `#/stock_detail?id=875&tab=-1&name=...&code=US.YINN`
    # ⇒ **`id` 才是主键**，`code` 只是附加 ✗
    q = "tab=-1&code=US.%s" % symbol
    if stock_id not in (None, ""):
        q = "id=%s&%s" % (stock_id, q)
    return ("(async()=>{const w=ms=>new Promise(r=>setTimeout(r,ms));"
            "location.hash='#/mine';await w(1200);"
            "location.hash='#/stock_detail?%s';"
            "return 'OK';})()" % q)


def _urls():
    """取回页面发过的**所有** XHR/fetch URL ✓（只 URL，不含响应体 —— 安全 ✓）。"""
    return "(()=>{const a=window.__shoutu_all||[];return a.join('\\n');})()"


def _click_tab():
    """点一下页面上的「历史」页签 ✓ —— 返回 'OK' / 'NO'。

    🔴 2026-10-30 实测：`--ids YINN=875` 后 `license_like?stock_id=875` 说明
    **id 已经生效** ✓，但 `stock_emotion/history?code=US.YINN` **仍返回 `data: []`** ✗
    ⇒ 不是 id 的问题 ✗ ⇒ 怀疑 SPA 的 `tab=-1` 只是路由参数，
    **历史 tab 需要真实点击**才会触发取数 ✗。
    """
    return (
        "(()=>{"
        "const hit=(e)=>{const t=(e.textContent||'').trim();"
        "return t && t.length<=8 && /^(历史|历史数据|走势|History)$/i.test(t)};"
        "const cands=[...document.querySelectorAll('a,button,li,span,div')]"
        ".filter(e=>e.children.length===0 && hit(e));"
        "if(!cands.length) return 'NO';"
        "cands[0].click(); return 'OK';})()")


def _take(symbol):
    """取回缓冲里**所有** history 响应体（JSON 数组字符串，没有则返回空串）。

    🔴 2026-10-30 实测：页面会发**不止一次** `stock_emotion/history` ——
    其中 `?code=US.YINN`（不带 id）返回 **`data: []`** ✗，而带 `id` 的那次才有数据 ✓。
    原来只按 `code=US.<sym>` 过滤并取最后一个 ✗ ⇒ 正好拿到空的那次 ✗
    ⇒ 8 个标的全部「服务端无历史」✗。现在改成**全收 + 由调用方挑非空的** ✓。
    """
    return ("(()=>{const a=window.__shoutu_cap||[];"
            "const m=a.filter(x=>String(x.u).indexOf('stock_emotion/history')>=0);"
            "window.__shoutu_cap=[];"
            "return JSON.stringify(m.map(x=>x.b));})()")


def _now_stamp(now=None):
    """抓取时刻的**可审计**戳（spec §12 风险 6 / §10.2）。

    **为什么必须打印**：定时任务在 **06:30** 跑，而「**美股收盘前**抓会写入
    **未完成的最后一行**」—— 实测服务端后来修正了 6 行（TQQQ `78.17 → 77.095`、
    GDXU `130.71 → 120.85`）。日志里没有时刻，就无法事后判断某天的数据是在收盘前
    还是收盘后落的盘（**冬令时 / 夏令时会让 06:30 落错边**）。

    `now`：仅测试注入用（默认取本机当前时间）。返回**本机时区**的可读时刻 ——
    定时任务日志与人读日志都在本机时区，换算成 UTC 只会增加误读风险。
    """
    ts = datetime.datetime.now() if now is None else now
    return "抓取时刻：%s（本机 %s）" % (
        ts.strftime("%Y-%m-%d %H:%M:%S"), ts.astimezone().strftime("%z"))


def fetch_history(symbols, debug=False, ids=None, click_tab=False):
    """`ids`：`{symbol: stock_id}` ✓ —— 页面详情页以 `id` 为主键 ✗（2026-10-30 实测）。

    `click_tab`：导航后再点一下「历史」页签 ✓（只改 hash 不触发取数 ✗）。
    """
    ids = ids or {}
    """逐个标的取历史并落盘，返回 `{symbol: 写入行数}`（0 = 服务端无该标的的历史）。

    **任一标的失败即抛错，不静默跳过**（与 `fetch_scan_scores` 同一约定）：
    静默跳过会让历史**悄悄缺标的**，而 Step B 的量化结论全部建立在它上面。
    """
    session = fs.bsk(["session", "start", "--no-focus"]).strip().splitlines()[-1].strip()
    if not session:
        raise RuntimeError("未取得 bsk session id")
    counts = {}
    try:
        fs.bsk(["navigate", APP_PAGE], session)
        time.sleep(6)
        if fs.bsk_eval(HOOK, session) != "OK":
            raise RuntimeError("挂钩未装成功 —— 页面结构可能已变")
        for sym in symbols:
            # ⚠️ 每轮**先清空缓冲** —— 这是"导航失败"能被发现的关键，别删。
            # 安全性链条（独立评审确认，改动前先读懂）：
            #   1. 清空 ⇒ 本轮缓冲里只可能有**本次**导航产生的响应；
            #   2. `_take(sym)` 按 `code=US.<sym>` 过滤 ⇒ **取不到别的标的**；
            #   3. 导航失败 ⇒ 过滤后为空 ⇒ 下面 `if not raw` **抛错**（不是静默跳过）。
            # ⚠️ 因此 `_goto` 的返回值**故意不检查**：它是 `(async()=>{…})()`
            #    （返回 Promise），而 `bsk_eval` 只对**同步** IIFE 返回字符串 ——
            #    上面 HOOK 的 `!= "OK"` 能生效正因为它同步。给 `_goto` 照抄那个检查
            #    会**每次都误抛**。要真校验导航，先实测 bsk 对 Promise 的取值。
            fs.bsk_eval(HOOK, session)            # 清空缓冲（挂钩只装一次）
            fs.bsk_eval(_goto(sym, ids.get(sym)), session)
            time.sleep(5)
            if click_tab:
                # 点「历史」页签 ⇒ 触发取数 ✓（只改 hash 不够 ✗，2026-10-30 实测）
                hit = fs.bsk_eval(_click_tab(), session)
                print("    [click] 历史页签：%s" % hit)
                time.sleep(4)
            if debug:
                # 只打 URL（不含响应体）✓ —— 用来确认页面到底请求了哪个端点 ✗
                got = fs.bsk_eval(_urls(), session) or ""
                print("    [debug] 捕获 URL：\n%s" % (got.strip() or "（空）"))
            raw = fs.bsk_eval(_take(sym), session)
            if not raw:
                raise RuntimeError(
                    "[%s] 未捕获到历史响应 —— 页面可能改版、未登录，或该标的详情页打不开" % sym)
            # 2026-10-30：可能有多条 history 响应 ⇒ **挑第一条非空的** ✓
            bodies = json.loads(raw)
            df = None
            for b in bodies:
                try:
                    cand = shoutu.parse_history_payload(json.loads(b), sym)
                except Exception:              # noqa: BLE001 —— 坏的那条跳过 ✓
                    continue
                if not cand.empty:
                    df = cand
                    break
            if df is None:
                # 全部为空 ⇒ 服务端确实没有该标的的历史（保留原语义 ✓）
                df = shoutu.parse_history_payload(
                    json.loads(bodies[-1] if bodies else "{}"), sym)
            if df.empty:
                # `data: []` ⇒ 服务端**确实没有**该标的的历史（实测 AXTX / CRCG）
                print("  %-5s ⚠️ 服务端无历史（data: []）—— 跳过" % sym)
                counts[sym] = 0
                continue
            shoutu.record_history(df)
            counts[sym] = len(df)
            print("  %-5s %d 天（%s ~ %s）"
                  % (sym, len(df), df["date"].min().date(), df["date"].max().date()))
        return counts
    finally:
        # **必须显式停**：不依赖空闲超时（browser-skill 的要求）
        fs.bsk(["session", "stop", session])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default=None,
                    help="逗号分隔；省略则取 config.SHOUTU_SYMBOLS 全部")
    ap.add_argument("--debug", action="store_true",
                    help="打印每个标的捕获到的 URL（不含响应体 ✓）—— 端点改版时用")
    ap.add_argument("--ids", default=None,
                    help="symbol=stock_id 逗号分隔（如 YINN=875）—— 详情页以 id 为主键")
    ap.add_argument("--click-tab", action="store_true",
                    help="导航后点一下「历史」页签（只改 hash 不触发取数）")
    args = ap.parse_args()

    ids = {}
    for kv in (args.ids or "").split(","):
        if "=" in kv:
            k, v = kv.split("=", 1)
            ids[k.strip().upper()] = v.strip()

    symbols = ([s.strip().upper() for s in args.symbols.split(",") if s.strip()]
               if args.symbols else list(config.SHOUTU_SYMBOLS))
    print(_now_stamp())                      # 抓取时刻（spec §12 风险 6）
    print("抓取守猪待兔历史：%s" % " / ".join(symbols))
    counts = fetch_history(symbols, debug=args.debug, ids=ids,
                           click_tab=args.click_tab)
    print("已写入：%s" % config.SHOUTU_HISTORY_PATH)
    missing = [s for s, n in counts.items() if not n]
    if missing:
        print("⚠️ 服务端无历史的标的：%s" % " / ".join(missing))
    print("合计：%s" % " / ".join("%s %d" % (s, n) for s, n in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
