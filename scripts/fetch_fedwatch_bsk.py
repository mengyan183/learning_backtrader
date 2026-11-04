# -*- coding: utf-8 -*-
"""用 **bsk（真实 Chromium）** 抓 CME FedWatch ✓（2026-11-04 用户裁定「CME 用 bsk」）。

【为什么改用 bsk】
  ① 旧方案 headless Chrome ✗ 拿不到数据 ✗
     实测 `--dump-dom` 得 287KB ✗ 有 `FedWatch` 字样、有 `ZQ` 合约代码 ✗
     但**零个百分比数字** ✗ ⇒ 数据是 JS 异步渲染的 ✗
  ② 直接调 API ✗ `CmeWS/mvc/quotes/v2/contracts-by-number` **403** ✗
  ③ bsk 用的是**用户真实浏览器** ✓ 已有登录态/cookie ✓ 能过 JS 挑战 ✓

【流程】（严格按 bsk 的 lifecycle ✗ 不遵守会报
        `shared page control or observation changed` ✗）
  `bsk session start`            → 拿 4 字母 session id ✓
  `bsk navigate <url> --session` → 打开页面 ✓
  `bsk wait-ms 8000 --session`   → **等 JS 渲染** ✓（关键 ✗ 不等就是空表）
  `bsk get-html --session`       → 拿**渲染后**的 HTML ✓
  `bsk session stop <id>`        → **必须停** ✓（成功/异常都要 ✗）

【⚠️ 已知限制】
  - 需要 Mac 上 **Chrome 常驻 + bsk daemon 在跑** ✗
  - 需要页面**已登录/无验证码** ✗（首次可能要人处理 ✗）
  - 与 **OpenClaw agent** 抢浏览器会失败 ✗（见 `--retries`）

用法：
    python scripts/fetch_fedwatch_bsk.py --dump-html /tmp/cme.html
    python scripts/fetch_fedwatch_bsk.py --write      # 解析并写 fedwatch.csv
"""
import argparse
import os
import re
import subprocess
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fg_system import config  # noqa: E402

def _find_bsk():
    """**自动探测 `bsk` 可执行文件** ✓（2026-11-04 修）。

    🔴 为什么不能直接 `["bsk", ...]` ✗：
       实测（Mac / launchd 环境）：
         `session_start rc=-1  **找不到 bsk** ✗`
       而 bsk **确实装着** ✓（`fetch_shoutu_history.py` 用过 ✓）
       ⇒ 因为 **launchd 的 PATH 不含 `~/.local/bin` / `/opt/homebrew/bin`** ✗
         （plist 里只加过 `/opt/homebrew/bin` ✗ 而 bsk 可能装在
          `~/.local/bin` 或 `~/Library/Python/*/bin` ✗）

    ⇒ 依次尝试：`FG_BSK` 环境变量 → `shutil.which` → 常见路径 ✓
    """
    env = os.environ.get("FG_BSK")
    if env and os.path.exists(env):
        return env
    import shutil
    w = shutil.which("bsk")
    if w:
        return w
    home = os.path.expanduser("~")
    cands = [
        os.path.join(home, ".local", "bin", "bsk"),
        "/opt/homebrew/bin/bsk",
        "/usr/local/bin/bsk",
        "/usr/bin/bsk",
        os.path.join(home, ".npm-global", "bin", "bsk"),
    ]
    # `~/Library/Python/3.x/bin/bsk`（pip --user 常见位置 ✗）
    import glob as _g
    cands += sorted(_g.glob(os.path.join(
        home, "Library", "Python", "*", "bin", "bsk")), reverse=True)
    for c in cands:
        if os.path.exists(c) and os.access(c, os.X_OK):
            return c
    return None


BSK = _find_bsk() or "bsk"      # 探测失败仍用 "bsk" ✓（至少报错更明确 ✗）
PAGE = config.FEDWATCH_PAGE_URL
#: 等 JS 渲染的毫秒数 ✗ —— 实测页面要 5~10 秒才出表格 ✓
WAIT_MS = int(os.environ.get("FG_CME_WAIT_MS") or 8000)


def _run(args, timeout=120):
    """跑一条 bsk 命令 ✓ 返回 `(rc, stdout, stderr)`。"""
    try:
        r = subprocess.run([BSK] + args, capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           timeout=timeout)
        return r.returncode, (r.stdout or ""), (r.stderr or "")
    except FileNotFoundError:
        # 探测结果给出来 ✓ 便于定位是「没装」还是「PATH 不含」✗
        import shutil as _sh
        where = _sh.which("bsk") or "(which 也找不到 ✗)"
        return -1, "", ("**找不到 bsk** ✗\n"
                        "   探测结果：BSK=%r  which=%s\n"
                        "   常见路径：~/.local/bin/bsk / /opt/homebrew/bin/bsk\n"
                        "   ⇒ 设 `FG_BSK=/完整/路径/bsk` 或 `pip install browser-skill` ✗"
                        % (BSK, where))
    except subprocess.TimeoutExpired:
        return -2, "", "bsk 命令超时（%ds ✗）" % timeout


def fetch_html(wait_ms=WAIT_MS, retries=2, debug=False):
    """用 bsk 打开 CME FedWatch 并返回**渲染后**的 HTML ✓。

    :returns: `(html, info)` —— `html` 为 `None` 表示失败 ✓ `info` 带诊断 ✗
    """
    info = {"page": PAGE, "wait_ms": wait_ms, "attempts": []}
    for attempt in range(retries + 1):
        rc, out, err = _run(["session", "start"], timeout=60)
        sid = (out or "").strip().splitlines()[-1].strip() if out else ""
        if rc != 0 or not re.fullmatch(r"[a-z0-9]{3,12}", sid or ""):
            info["attempts"].append({"step": "session_start", "rc": rc,
                                     "out": out[-200:], "err": err[-300:]})
            time.sleep(3)
            continue
        info["session"] = sid
        try:
            rc, out, err = _run(["navigate", PAGE, "--session", sid],
                                timeout=180)
            info["attempts"].append({"step": "navigate", "rc": rc,
                                     "out": out[-200:], "err": err[-300:]})
            if rc != 0:
                continue
            # 🔴 **必须等 JS 渲染** ✗ 不等就是空表 ✗
            #    2026-11-04 踩坑：`bsk wait-ms` **没有 `--session` 参数** ✗
            #      实测 `bsk wait-ms --help`：
            #        Usage: bsk wait-ms [OPTIONS] <DURATION>
            #        （只接受时长 ✗ 且是 **daemon 侧 sleep** ✗ 与 session 无关 ✗）
            #      ⇒ 原来传 `--session sid` ⇒ **命令报错** ✗ 而返回值没检查 ✗
            #      ⇒ **等待从未生效** ✗ 5.1 秒就 get-html ✗ 页面没渲染完 ✗
            #      ⇒ 症状：HTML 217KB ✗ 但 `pct_total=0` ✗
            wrc, wout, werr = _run(["wait-ms", str(wait_ms)], timeout=90)
            info["attempts"].append({"step": "wait_ms", "rc": wrc,
                                     "ms": wait_ms, "err": werr[-200:]})
            rc, html, err = _run(["get-html", "--session", sid], timeout=120)
            info["attempts"].append({"step": "get_html", "rc": rc,
                                     "len": len(html or ""),
                                     "err": err[-300:]})
            if rc == 0 and html and len(html) > 10000:
                info["ok"] = True
                info["html_len"] = len(html)
                return html, info
        finally:
            # 🔴 **成功/异常都要停** ✓
            _run(["session", "stop", sid], timeout=60)
        time.sleep(2)
    info["ok"] = False
    return None, info


#: CME 的月份缩写 ✓
_MONTHS = {m: i + 1 for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"))}


def parse(html):
    """从**渲染后**的 HTML 解析 FedWatch 数据 ✓。

    🔴 2026-11-04：**旧正则全部作废** ✗
       旧代码找 `<td class="number">78.4%</td>` ✗
       而实测新页面 `has_number_td: False` ✗ ⇒ 结构完全不同 ✗
       ⇒ 本函数**多套正则并试** ✓ 哪个出结果用哪个 ✓
       ⇒ 并在 `raw_hits` 里回传命中的样本 ✓ 便于下次调 ✗
    """
    out = {"meetings": [], "prob_rows": [], "zones": [],
           "raw_hits": {}, "source_len": len(html or "")}
    if not html:
        return out

    # ① 会议日期 + 合约代码（ZQ 系列 ✗ 这个在实测里存在 ✓）
    for d, mon, y, con in re.findall(
            r'(\d{1,2})\s+([A-Za-z]{3})[a-z]*\s+(\d{4})[^A-Za-z]{0,80}(ZQ\w+)',
            html):
        m = _MONTHS.get(mon[:3].lower())
        if not m:
            continue
        key = "%04d-%02d-%02d" % (int(y), m, int(d))
        if key not in out["meetings"]:
            out["meetings"].append(key)
    out["raw_hits"]["meeting_con"] = len(out["meetings"])

    # ② 概率三元组（宽松版 ✗ 不依赖 td class ✗）
    #    匹配「78.4%」这种，且同一段里连着出现 3 个 ✓
    pcts = re.findall(r'(\d{1,3}\.\d)\s*%', html)
    out["raw_hits"]["pct_total"] = len(pcts)
    if len(pcts) >= 3:
        # 按 3 个一组切 ✓（FedWatch 每行是 ease/hold/hike ✗）
        for i in range(0, len(pcts) - 2, 3):
            out["prob_rows"].append(tuple(pcts[i:i + 3]))
    out["raw_hits"]["prob_rows"] = len(out["prob_rows"])

    # ③ 目标区间（`375-400` / `400-425` 这类 ✗）
    zones = re.findall(r'(\d{3})\s*[-–]\s*(\d{3})', html)
    out["zones"] = sorted(set("%s-%s" % (a, b) for a, b in zones))[:12]
    out["raw_hits"]["zones"] = len(out["zones"])

    return out


def main():
    ap = argparse.ArgumentParser(
        description="用 bsk 抓 CME FedWatch（真实浏览器 ✗ 能过 JS 渲染 ✓）")
    ap.add_argument("--dump-html", metavar="PATH",
                    help="把渲染后的 HTML 存到 PATH（用于**先看结构** ✗）")
    ap.add_argument("--write", action="store_true",
                    help="解析并写 `Data/raw/fedwatch.csv` ✓")
    ap.add_argument("--wait-ms", type=int, default=WAIT_MS,
                    help="等 JS 渲染的毫秒数（默认 %d ✗）" % WAIT_MS)
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    html, info = fetch_html(wait_ms=args.wait_ms, retries=args.retries,
                            debug=args.debug)
    if args.dump_html and html:
        # 🔴 相对路径按 ROOT 解析 ✓（`run_fetch_step` 的 cwd 是仓库根 ✗）
        out_path = args.dump_html
        if not os.path.isabs(out_path):
            out_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                out_path)
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)
        print("HTML 已存：%s（%.1f KB ✗）"
              % (out_path, len(html) / 1024.0))

    # 🔴 2026-11-04：**把 HTML 里的关键片段打出来** ✓
    #    因为 217KB 的文件没法直接看 ✗ 而 `pct_total=0` 需要知道
    #    「页面里到底有什么」✗ 才能判断是「没渲染」还是「结构变了」✗
    if html:
        import re as _re2
        print("\n--- HTML 特征 ---")
        for key in ("FedWatch", "ZQ", "probability", "Probability",
                    "target rate", "Target Rate", "table", "quikstrike",
                    "QuikStrike", "CmeWS"):
            print("  %-14s %s" % (key, html.count(key)))
        # 任何数字+% 的样本 ✓（不限于 `>78.4%<` ✗）
        pcts = _re2.findall(r"(\d{1,3}\.\d)\s*%", html)[:15]
        print("  百分比样本:", pcts if pcts else "(零个 ✗)")
        # 找最大的 `<table>` 片段 ✓
        tbls = _re2.findall(r"<table.{0,4000}?</table>", html, _re2.S)
        print("  table 数量:", len(tbls))
        if tbls:
            print("  最大 table 前 600 字：")
            print("  " + max(tbls, key=len)[:600].replace("\n", " "))

    if not html:
        print("✗ bsk 抓取失败 ✗", file=sys.stderr)
        for a in info.get("attempts", []):
            print("   %s rc=%s %s %s" % (a.get("step"), a.get("rc"),
                                         str(a.get("out") or "")[:120],
                                         str(a.get("err") or "")[:200]),
                  file=sys.stderr)
        return 2

    data = parse(html)
    print("meetings=%d prob_rows=%d zones=%d pct_total=%d"
          % (len(data["meetings"]), len(data["prob_rows"]),
             len(data["zones"]), data["raw_hits"].get("pct_total", 0)))
    if args.debug:
        print("meetings:", data["meetings"][:6])
        print("prob_rows:", data["prob_rows"][:6])
        print("zones:", data["zones"][:6])

    if not args.write:
        return 0

    # ---- 写盘 ✓ ----
    # ⚠️ **字段映射待确认** ✗ —— 必须先看 `--dump-html` 的真实结构 ✗
    #    现在按「meeting + 第一个 prob_row」尽力而为 ✓
    if not data["meetings"] or not data["prob_rows"]:
        print("✗ 解析不到 meetings / prob_rows ⇒ **不能写盘** ✗"
              "（先跑 --dump-html 看结构 ✗）", file=sys.stderr)
        return 3

    rows = []
    for i, mt in enumerate(data["meetings"]):
        if i >= len(data["prob_rows"]):
            break
        e, h, k = data["prob_rows"][i]
        rows.append({"date": datetime.now().strftime("%Y-%m-%d"),
                     "meeting": mt, "ease_pct": e, "hold_pct": h,
                     "hike_pct": k, "src": "cme-bsk"})
    if not rows:
        print("✗ 无有效行 ✗", file=sys.stderr)
        return 3

    import csv
    path = os.path.join(config.RAW_DIR, "fedwatch.csv")
    os.makedirs(config.RAW_DIR, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("✓ 已写 %s（%d 行 ✗）" % (path, len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
