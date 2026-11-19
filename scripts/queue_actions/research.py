# -*- coding: utf-8 -*-
"""研究 / 回测 / 假说验证 / 简报 action ✓ —— 拆出的第六个动作包。

【边界】
  · 只依赖 `queue_core`（`ROOT` / `run`）+ 标准库 ✓
  · **不碰队列状态** ✗ —— `QUEUE` / `run_once` / flock 在调度器里
  · `factor_probe` 的私有分派表（`_SYM_FACTORS` / `_COMPUTE` /
    `_compute_factor`）只被它用 ⇒ 一起搬 ✓
"""
import os
import re
import subprocess
import sys
import time

from queue_core import ROOT, run as _run


def _act_weekly_review(params):
    """**周度复盘**（在 Mac 上跑 ✓ 2026-11-03 用户裁定）。

    🔴 为什么必须在 Mac：
       `Data/raw/*.csv` 在 Windows 侧只是**旧快照** ✗
       （实测停在 2026-10-12 ✗ 而 Mac 上是新的 ✗）
       ⇒ 在 Windows 跑会得出「数据断流」的假警报 ✗

    参数：`days`（回顾最近 N 份简报，默认 7）✓
    """
    days = int(params.get("days") or 7)
    cmd = [sys.executable, os.path.join(ROOT, "scripts", "weekly_review.py"),
           "--days", str(days)]
    try:
        r = _run(cmd, 600)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "超过 600 秒"}
    return {"ok": r.returncode == 0, "days": days,
            "note": "⚠️ 样本很小 ✗ 单周胜率不能当因子有效性证据 ✓",
            "stdout": (r.stdout or "")[-4000:],
            "stderr": (r.stderr or "")[-400:]}


def _act_archive_briefs(params):
    """**立即归档简报并自动提交** ✓（2026-11-03 用户裁定）。

    🔴 为什么需要：Mac 端堆了 10+ 个未追踪的
       `Data/briefs/archive/2026-10/invest_brief_*.md` ✗
       （`archive_briefs.py` 原来只写文件不提交 ✗）
       2026-11-03 已加自动提交 ✓ 但 Mac 端要先拉代码 ✓
       ⇒ 拉完用本动作**立即清一次存量** ✓

    参数：`keep`（保留最近 N 天，默认 7）✓
    """
    keep = int(params.get("keep") or 7)
    cmd = [sys.executable, os.path.join(ROOT, "scripts", "archive_briefs.py"),
           "--keep", str(keep)]
    try:
        r = _run(cmd, 600)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "超过 600 秒"}
    return {"ok": r.returncode == 0, "keep": keep,
            "note": "归档后会自动 git commit ✓（只 add Data/briefs/ 路径 ✗）",
            "stdout": (r.stdout or "")[-2000:],
            "stderr": (r.stderr or "")[-400:]}


def _act_verify_hypotheses(params):
    """**跑 `verify_hypotheses.py` 推进假说验证** ✓（2026-11-05 用户要求）。

    🔴 为什么要推进 ✗：
       台账现状（`evolution/hypotheses.md` ✗ 共 85 条）：
         `verifying`  **3 条** —— H-006 / H-008 / H-009 ✗ **10-02 登记，一个月没推进**
         `open`       **15 条**
         `pending-revise` **1 条** —— H-085
       ⇒ 假说验证**停摆** ✗ 而 `verify_hypotheses.py` 就是执行器 ✓

    【脚本参数】
      `-H/--hypothesis H-006`（可重复 ✗ 不给则跑**全部 open** ✓）
      `--dry-run`（只算不写台账 ✗）
      `--out <path>`（结果另存 ✗）
      `--check-table`（校验台账列名 ✗）

    参数：
      - `hypotheses`：逗号分隔（默认空 ⇒ 全部 open ✓）
      - `dry_run`：`1` = 只算不写 ✓
    """
    hs = [x.strip() for x in str(params.get("hypotheses") or "").split(",")
          if x.strip()]
    dry = str(params.get("dry_run") or "").lower() in ("1", "true", "yes")

    # 🔴 2026-11-05：`write_notes=1` ⇒ **只写备注列** ✓（不跑假说 ✗）
    #    用户要求「备注列加等数据 x/y，且支持动态更新」✗
    #    实现放在 `verify_hypotheses.py --write-notes` ✓ 幂等 ✗
    notes = str(params.get("write_notes") or "").lower() in ("1", "true", "yes")

    cmd = [sys.executable, "scripts/verify_hypotheses.py"]
    for h in hs:
        cmd += ["-H", h]
    if notes:
        cmd.append("--write-notes")
    if dry:
        cmd.append("--dry-run")

    t0 = time.time()
    r = _run(cmd, 1800)
    secs = round(time.time() - t0, 1)
    so = (r.stdout or "").strip()
    se = (r.stderr or "").strip()

    # 🔴 逐条摘出结论行 ✓（脚本会打 `H-xxx` 开头的结果 ✗）
    #    只留「有判定」的行 ✓ 去掉噪声 ✓
    hits = []
    for ln in so.splitlines():
        s = ln.strip()
        if re.match(r"^H-\d+", s) or re.search(
                r"(通过|不通过|样本不足|跳过|无法|已验证|证伪)", s):
            if s and s not in hits:
                hits.append(s[:200])

    out = {"ok": r.returncode == 0, "rc": r.returncode, "seconds": secs,
           "hypotheses": hs or "全部 open",
           "dry_run": dry,
           "stdout_len": len(so), "stderr_len": len(se),
           "verdict_lines": hits[:40],
           "stdout_tail": so[-2500:] if so else "",
           "stderr_tail": se[-800:] if se else ""}
    # 简单判读 ✓
    if r.returncode != 0:
        out["verdict"] = "✗ 脚本失败 ✗ 见 stderr_tail"
    elif not hits:
        out["verdict"] = ("⚠️ 跑完了但**没有判定行** ✗ "
                          "可能全部「样本不足」✗ 见 stdout_tail")
    else:
        n_ok = sum(1 for h in hits if "通过" in h and "不通过" not in h)
        n_bad = sum(1 for h in hits if "不通过" in h)
        n_skip = sum(1 for h in hits if "样本不足" in h or "跳过" in h)
        out["verdict"] = ("✓ 有 %d 条判定：通过 %d / 不通过 %d / 样本不足 %d"
                          % (len(hits), n_ok, n_bad, n_skip))
    return out


def _act_rerun_brief(params):
    """**重算 features 并生成简报** ✓（2026-11-05 用户要求「重新测试输出的简报」）。

    🔴 为什么不能只跑 `invest_research.py` ✗：
       简报读的是 `features.csv` ✗ 而它由 `pipeline.run(write=True)` 产出 ✗
       ⇒ `fedwatch.csv` 更新了 ✗ 但 `features.csv` **还是旧的** ✗
       ⇒ 必须**先重算 pipeline** ✓ 才能看到 `FED` 因子的变化 ✓

    【两步】
      ① `pipeline.run(write=True)` —— 重算六因子 ✓
      ② `invest_research.py --dry-run` —— 生成简报 ✓ **不推送飞书** ✓

    参数：
      - `skip_pipeline`：1 = 跳过第①步 ✗ 只看现有 features ✗
      - `push`：1 = **推飞书** ✓（默认 `--dry-run` 不推 ✗）
        🔴 2026-11-09 用户要求「把这份简报推飞书」⇒ 加此开关 ✓
    """
    skip = str(params.get("skip_pipeline") or "").lower() in ("1", "true", "yes")
    push = str(params.get("push") or "").lower() in ("1", "true", "yes")
    out = {"steps": {}}

    # ① pipeline ✓
    if not skip:
        t0 = time.time()
        # 🔴 2026-11-05：**必须显式加 sys.path** ✗
        #    实测报 `[warn] 有效敞口计算失败：No module named 'fg_system'` ✗
        #    因为 `python -c` 的 `sys.path[0]` 是 `""`（cwd ✗）
        #    而 `cwd=ROOT` 下 `fg_system` **应该能找到** ✗ 但被别的
        #    路径顺序干扰 ✗ ⇒ 显式 insert ✓
        r = _run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, '.'); "
             "from fg_system import pipeline; pipeline.run(write=True)"],
            900)
        out["steps"]["pipeline"] = {
            "rc": r.returncode, "seconds": round(time.time() - t0, 1),
            "stdout": (r.stdout or "")[-800:],
            "stderr": (r.stderr or "")[-500:],
        }
        if r.returncode != 0:
            out["ok"] = False
            out["error"] = "pipeline 失败 ✗ 见 steps.pipeline.stderr"
            return out

    # ② 简报 ✓（`--dry-run` 不推送 ✓）
    t0 = time.time()
    cmd = [sys.executable, "scripts/invest_research.py"]
    if not push:
        cmd.append("--dry-run")        # 不加 --dry-run 才会推飞书 ✓
    r = _run(cmd, 1200)
    # 🔴 2026-11-05 **关键**：`--dry-run` 的 **stdout 只有运行日志** ✗
    #    实测 stdout 只有 1083 字（`[warn]` + `简报已写入: ...` ✗）
    #    而**完整简报写到了 `Data/invest_brief_<日期>.md`** ✓
    #    ⇒ 必须**读那个 md 文件** ✗ 不能只取 stdout ✗
    brief = ""
    md_path = ""
    import glob as _g2
    cands = sorted(_g2.glob(os.path.join(ROOT, "Data", "invest_brief_*.md")),
                   key=os.path.getmtime, reverse=True)
    if cands:
        md_path = cands[0]
        try:
            brief = open(md_path, encoding="utf-8",
                         errors="replace").read()
        except OSError:
            brief = ""
    if not brief:
        brief = (r.stdout or "").strip()

    out["steps"]["brief"] = {
        "rc": r.returncode, "seconds": round(time.time() - t0, 1),
        "len": len(brief), "md": os.path.relpath(md_path, ROOT) if md_path else "",
        "stdout_len": len(r.stdout or ""),
        "stderr": (r.stderr or "")[-500:],
    }
    out["ok"] = r.returncode == 0
    out["push"] = push
    m3 = re.search(r"飞书富文本推送[:：]\s*(.+)", r.stdout or "")
    out["push_result"] = m3.group(1).strip()[:120] if m3 else "(未见推送结果)"
    out["brief"] = brief[-12000:] if brief else "(空 ✗)"
    # 关键：把「美联储动态」那一段单独摘出来 ✓（用户最关心 ✗）
    m = re.search(r"美联储动态(.{0,1500})", brief, re.S)
    out["fed_section"] = (m.group(0)[:1500] if m else "(没找到美联储动态段 ✗)")
    # 顺带报数据日 ✓
    m2 = re.search(r"数据日[:：]\s*(\d{4}-\d{2}-\d{2})", brief)
    out["data_date"] = (m2.group(1) if m2 else "?")
    return out


def _act_verify_hyp(params):
    """跑 `verify_hypotheses.py` 验证**指定假说** ✓（2026-11-13 用户要求）

    🔴 背景：`hypotheses.md` 里有 **10 条「有 handler 但状态还是 open/verifying」** ✗
       （H-009/H-011/H-017/H-022/H-028/H-031/H-038/H-042/H-049/H-085）
       怀疑是 `evolve_review` 的 LLM 超时导致日更停摆 ⇒ 状态没落盘 ✗
       ⇒ 手动跑一次，看是「insufficient」还是「false」还是「根本没执行」✓

    用法：`--param ids=H-009,H-011,H-017`
    """
    ids = params.get("ids") or []
    if isinstance(ids, str):
        ids = [x.strip() for x in ids.replace("，", ",").split(",") if x.strip()]
    if not ids:
        return {"ok": False,
                "error": "缺 params.ids（如 `ids=H-009,H-011`）"}
    py = sys.executable or "python3"
    cmd = [py, os.path.join(ROOT, "scripts", "verify_hypotheses.py")]
    for h in ids:
        cmd += ["-H", h]
    try:
        r = _run(cmd, 900)
    except subprocess.TimeoutExpired:
        return {"ok": False, "ids": ids, "error": "verify_hypotheses 超时（900s）"}
    out = (r.stdout or "") + (("\n[stderr]\n" + r.stderr) if r.stderr else "")
    return {"ok": r.returncode == 0, "ids": ids, "rc": r.returncode,
            "stdout": out[-4000:]}


def _compute_gold_ratio(root, pd):
    """F-021：`GDX/GLD` 的 **120 日滚动分位** ✓（`factors/gold_ratio.py`）"""
    sys.path.insert(0, root)
    from fg_system.factors import gold_ratio as _gr
    prices = pd.read_csv(os.path.join(root, "Data", "raw", "prices.csv"))
    sdf = _gr.gold_ratio_pct(prices).to_frame(name="gold_ratio").reset_index()
    sdf.columns = ["date", "gold_ratio"][:len(sdf.columns)]
    sdf["date"] = sdf["date"].astype(str).str[:10]
    return sdf


def _compute_f012(root, pd):
    """F-012：VIX 期限结构 `vix/vix3m` 的 **5 日变化率** ✓

    判据来源 `evolution/factors.md` 原文：
      「波动率结构（VIX 期限结构 term=vix3m/vix 的滚动变化率）」
      「2026-11-02 重测…**方向改为「正向」** ✓…统一用 `vix/vix3m` 的 N 日变化率」
      「N=5：+0.308/+0.403/+0.236/**+0.668**（5/10/20/40）…⇒ **定 N=5** ✓」

    ⚠️ 与 `features.csv` 的 `term` 列**不是一回事** ✗ ——
       `term` 是 `vix3m/vix` 的**水平** ✗；本因子要的是 `vix/vix3m` 的**变化率** ✓
    数据：`Data/raw/vix.csv` + `Data/raw/vix3m.csv`（都是 `date,open,high,low,close`）
    """
    def _close(name):
        d = pd.read_csv(os.path.join(root, "Data", "raw", name),
                        parse_dates=["date"])
        s = d.set_index("date")["close"].astype(float)
        return s[~s.index.duplicated(keep="last")].sort_index()

    v, v3 = _close("vix.csv"), _close("vix3m.csv")
    ratio = (v / v3).dropna()
    chg = ratio.pct_change(5).dropna()          # N=5（2026-11-02 定版）
    sdf = chg.rename("f012").reset_index()
    sdf.columns = ["date", "f012"]
    sdf["date"] = sdf["date"].astype(str).str[:10]
    return sdf


def _compute_erp(root, pd):
    """F-017：ERP 股权风险溢价 **滚动分位** ✓（`factors/erp.py`）

    判据来源 `evolution/factors.md`：
      「ERP 股权风险溢价（`1/PE − 月均10Y`，`fg_system/factors/erp.py`）」
      「**正向**（ERP 高=股票便宜=看多）」
    状态：`rejected`（日频 rank_ICIR +0.334/+0.244/+0.200/+0.242 未达 0.5 ✗，
          月频更差）—— **本次复核是用新判据（择时 alpha）重判** ✓

    ⚠️ `erp_pct()` 原生是**月频**（`available_date`）✗
       ⇒ 必须传 `target_index` 对齐到**日频** ✓
          （否则 join 日频价格后只剩每月一行 ✗ 样本不够）
       目标指数取 SPY（缺则退 TQQQ）✓
    """
    sys.path.insert(0, root)
    from fg_system.factors import erp as _erp
    px = pd.read_csv(os.path.join(root, "Data", "raw", "prices.csv"),
                     parse_dates=["date"])
    idx = None
    for sym in ("SPY", "TQQQ"):
        s = px[px["symbol"] == sym].set_index("date").sort_index()
        if not s.empty:
            idx = s.index
            break
    if idx is None:
        raise RuntimeError("prices.csv 缺 SPY/TQQQ，无法对齐 ERP 到日频")
    s = _erp.erp_pct(target_index=idx).dropna().rename("erp")
    sdf = s.reset_index()
    sdf.columns = ["date", "erp"]
    sdf["date"] = pd.to_datetime(sdf["date"]).dt.strftime("%Y-%m-%d")
    return sdf


def _compute_fg_base(root, pd):
    """基线：**现有 6 因子合成** ⇒ 仓位倾向 0~100 ✓（不加 ERP）"""
    return _fg_pos_tendency(pd, root, with_erp=False)


def _compute_fg_erp(root, pd):
    """增量：**6 因子 + ERP（10% 权重）** ⇒ 仓位倾向 0~100 ✓"""
    return _fg_pos_tendency(pd, root, with_erp=True)


def _compute_putcall(root, pd):
    """F-011：CBOE 总 Put/Call 比率的**逆向滚动分位** ✓（高分=贪婪）

    🔴 2026-11-12 实测：`Data/features.csv` **没有 `putcall` 列** ✗
       （`factor_probe --factor putcall` 报「features 无因子列」✗）
       ⇒ 只能从原始 `Data/raw/putcall.csv` 现算 ✓

    口径（照抄 `fg_system/factors/putcall.py:29-37`）：
      `total_ratio` → ffill → `rolling_pct(RANK_WINDOW)` → **`1 - pct`**（逆向）
      ⇒ 高分 = P/C 低 = 贪婪 ✓ ⇒ `direction = negative`（贪婪 ⇒ 仓位低）
    """
    sys.path.insert(0, root)
    from fg_system import config as _cfg
    from fg_system.factors.base import rolling_pct as _rp
    d = pd.read_csv(os.path.join(root, "Data", "raw", "putcall.csv"))
    d["date"] = pd.to_datetime(d["date"])
    s = d.set_index("date")["total_ratio"].astype(float).sort_index()
    s = s[~s.index.duplicated(keep="last")].ffill()
    out = (1.0 - _rp(s, _cfg.RANK_WINDOW)).dropna().rename("putcall").reset_index()
    out.columns = ["date", "putcall"]
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    return out
#: 需现算的因子（其余因子名若在 `features.csv` 里已存在 ⇒ 直接复用 ✓）


def _compute_ene(root, pd, symbol=None):
    """F-018：ENE 包络通道位置（0=触下轨超卖，1=触上轨超买）✓

    🔴 **这是「标的自身」因子** ⇒ 必须传 `symbol` ✗（不同标的值不同 ✗）
       与 `gold_ratio` / `erp` / `f012` 这些「市场级」因子不同 ✓
       ⇒ `_act_factor_probe` 对这类因子会**按 symbol 分别生成**研究 features ✓

    口径（`fg_system/factors/ene.py:126`）：`ene_pos(prices_df, sym)`
    方向：高分=触上轨=超买 ⇒ 该降仓 ⇒ `negative` ✓
    """
    if not symbol:
        raise RuntimeError("ENE 是标的自身因子，必须传 symbol ✗")
    sys.path.insert(0, root)
    from fg_system.factors import ene as _ene
    prices = pd.read_csv(os.path.join(root, "Data", "raw", "prices.csv"))
    s = _ene.ene_pos(prices, symbol)
    out = s.dropna().rename("ene").reset_index()
    out.columns = ["date", "ene"]
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    return out


def _compute_f020(root, pd):
    """F-020：**独立极恐标记** ✓（`putcall.csv` 的 `total_ratio > 1.2` ⇒ 1，否则 0）

    与 F-008（`zone==0` 二进制）的区别：
      F-008 的 `zone` 由 `fg_index` 分档而来 ⇒ **循环论证** ✗（已 rejected）
      F-020 用的是**独立的原始 P/C 比率** ⇒ 不依赖合成指数 ✓
    数据：`Data/raw/putcall.csv`（`date,total_ratio,...`）
    方向：`total_ratio > 1.2` = 极度恐慌 = 该加仓 ⇒ `positive` ✓
          （注意：与 F-011 的 `1-pct` 逆向分位**不同** ✗ —— 这是原始阈值的二进制）
    """
    d = pd.read_csv(os.path.join(root, "Data", "raw", "putcall.csv"))
    d["date"] = pd.to_datetime(d["date"])
    s = d.set_index("date")["total_ratio"].astype(float).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    out = (s > 1.2).astype(float).rename("f020").reset_index()
    out.columns = ["date", "f020"]
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    return out
#: 依赖 `symbol` 的因子（需按标的分别生成研究 features）✓


_SYM_FACTORS = {"ene"}


_COMPUTE = {
    "gold_ratio": _compute_gold_ratio,
    "f012": _compute_f012,
    "erp": _compute_erp,
    # 🔴 2026-11-12 用户要求「6 因子 vs 6 因子+ERP 增量评测」✓
    #    两个都用 `direction=positive`（高=该加仓）⇒ 口径一致可比 ✓
    "fg_base": _compute_fg_base,     # 基线：6 因子合成
    "fg_erp": _compute_fg_erp,       # 增量：6 因子 + ERP 10%
    "putcall": _compute_putcall,     # F-011（features.csv 无此列，须现算）
    "ene": _compute_ene,             # F-018（**标的自身**因子，需 symbol）
    "f020": _compute_f020,           # F-020（独立极恐标记，P/C > 1.2 二进制）
}


def _compute_factor(root, factor, pd, symbol=None):
    """按名算因子列 ⇒ 返回 `DataFrame(date, <factor>)`，未知返回 `None` ✓"""
    fn = _COMPUTE.get(factor)
    if fn is None:
        return None
    if factor in _SYM_FACTORS:
        return fn(root, pd, symbol=symbol)
    return fn(root, pd)


def _act_factor_probe(params):
    """**算 gold_ratio 列 → 跑回测裁判** ✓（2026-11-12 用户要求推进 F-021）。

    🔴 为什么需要这个动作：
       `factor_backtest_probe.py --factor <name>` 只从 **features 文件**取因子列 ✗
       而 `gold_ratio` 从没写进 `Data/features.csv`（只有 vix/term/price/breadth）✗
       ⇒ 无法直接跑裁判 ✗

    ✅ 做法（**不动生产 features.csv** ✗）：
      ① `factors/gold_ratio.gold_ratio_pct(prices)` 算信号 ✓
      ② 写成研究专用特征文件
         `evolution/experiments/factor-adoption/features_gold_ratio.csv` ✓
      ③ `factor_backtest_probe.py --factor gold_ratio --features <上一步文件>` ✓
         **同时跑 TQQQ 与 GDXU 两个标的** ✓（GDXU 才是直接持仓 ✓）
      ④ 回执带上裁判产出的 md 路径 + 关键指标行 ✓

    方向：`gold_ratio.py` docstring 明写「方向待测，由 eval_gold_ratio 的实测 IC 决定」✗
       实测 `rank_ic_mean = -0.53`（负）⇒ 默认 `--direction negative` ✓
       （可用 `params.direction` 覆盖 ✓）
    """
    import glob as _glob

    out = {"steps": {}}
    root = ROOT
    py = os.path.join(root, ".venv", "bin", "python")
    if not os.path.exists(py):
        py = sys.executable

    # ① 算信号 —— 🔴 2026-11-12 用户要求：**支持任意因子列** ✓
    #    两条路径：
    #      A. `features.csv` **已有该列**（vix/term/price/breadth/fed/putcall）
    #         ⇒ 直接复制到研究文件 ✓（不重算，与生产同源 ✓）
    #      B. 需现算（`gold_ratio` / `f012`）⇒ 走 `_COMPUTE` 分派 ✓
    factor = str(params.get("factor") or "gold_ratio").strip()
    out["factor"] = factor
    try:
        import pandas as _pd
        sys.path.insert(0, root)
        base = _pd.read_csv(os.path.join(root, "Data", "features.csv"))
        base["date"] = base["date"].astype(str).str[:10]

        # 🔴 2026-11-13 修：**标的自身因子**在 ① 段不能算 ✗（这里还没拿到 symbol）
        #    实测 `factor_probe --factor ene` 报
        #    `RuntimeError: ENE 是标的自身因子，必须传 symbol` ✗
        #    ⇒ 跳过 ①，由 ③ 段逐 symbol 算 ✓
        if factor in _SYM_FACTORS:
            out["steps"]["signal_from"] = "per-symbol（见 ③）"
            sdf = None
        elif factor in base.columns:
            sdf = base[["date", factor]].copy()
            out["steps"]["signal_from"] = "features.csv（已有列，直接复用）"
        else:
            sdf = _compute_factor(root, factor, _pd)
            if sdf is None:
                return {"ok": False,
                        "error": "未知因子 `%s` ✗ —— features.csv 无此列，"
                                 "且 `_COMPUTE` 里没有对应算列逻辑（支持：%s）"
                                 % (factor, "、".join(sorted(_COMPUTE)) +
                                    " + features 已有列")}
            out["steps"]["signal_from"] = "_COMPUTE[%s]（现算）" % factor
        if sdf is not None:
            out["steps"]["signal"] = {"n": int(len(sdf)),
                                      "head": sdf.head(2).to_dict("records"),
                                      "tail": sdf.tail(2).to_dict("records")}
    except Exception as exc:              # noqa: BLE001
        return {"ok": False,
                "error": "算 %s 失败：%s: %s"
                         % (factor, type(exc).__name__, str(exc)[:250])}

    # ② 写研究专用特征文件（合并原 features 的非因子列）
    feat_out = os.path.join(root, "evolution", "experiments",
                            "factor-adoption", "features_%s.csv" % factor)
    if factor in _SYM_FACTORS:
        # 🔴 2026-11-13：**标的自身**因子（ENE）不能在这里生成 ✗
        #    每个 symbol 的因子值不同 ⇒ 必须按 symbol 分别生成 ✓
        #    ⇒ 跳过这里，在 ③ 循环内逐 symbol 生成 ✓
        out["steps"]["features_file"] = ("per-symbol（%s 依赖 symbol，见 ③）"
                                         % factor)
    else:
        try:
            os.makedirs(os.path.dirname(feat_out), exist_ok=True)
            base = _pd.read_csv(os.path.join(root, "Data", "features.csv"))
            base["date"] = base["date"].astype(str).str[:10]
            # 🔴 2026-11-13 修真 bug：**因子已存在于 features.csv 时不能 merge** ✗
            #    `sdf` 本来就是从 `base` 取的（`base[["date", factor]]`）✗
            #    ⇒ `base.merge(sdf)` = **自己和自己 merge** ✗
            #    ⇒ pandas 产生 `baa10y_pct_x` / `baa10y_pct_y` ✗
            #    ⇒ 子进程 `factor_probe --factor baa10y_pct` 报「无因子列」✗
            #    （实测 F-016 / F-011 都栽在这里 ✗）
            if factor in base.columns:
                merged = base
            else:
                merged = base.merge(sdf, on="date", how="left")
            merged.to_csv(feat_out, index=False)
            out["steps"]["features_file"] = feat_out
            out["steps"]["features_cols"] = list(merged.columns)[-6:]
        except Exception as exc:          # noqa: BLE001
            return {"ok": False,
                    "error": "写研究特征文件失败：%s: %s"
                             % (type(exc).__name__, str(exc)[:250])}

    # ③ 跑裁判（TQQQ + GDXU）
    # 方向默认按因子定 ✓（`gold_ratio` 实测 rank_ic -0.53 ⇒ 逆向；F-012 定「正向」）
    _DIR_DEFAULT = {"gold_ratio": "negative", "f012": "positive",
                    "erp": "positive",   # F-017 登记为「正向」（ERP 高=便宜=看多）
                    # 下面两个已转成「仓位倾向」（高=该加仓）⇒ positive ✓
                    "fg_base": "positive", "fg_erp": "positive",
                    # F-011：因子值 = 1-P/C分位（高分=贪婪）⇒ 贪婪该减仓 ⇒ negative
                    "putcall": "negative",
                    # F-018：因子值 = 通道位置（高=触上轨=超买）⇒ 超买该降仓 ⇒ negative
                    "ene": "negative",
                    # F-020：因子值 = 极恐标记（1=极恐）⇒ 极恐该加仓 ⇒ positive
                    "f020": "positive"}
    direction = str(params.get("direction")
                    or _DIR_DEFAULT.get(factor, "positive")).strip().lower()
    if direction not in ("positive", "negative"):
        direction = "negative"
    out["direction"] = direction
    runs = {}
    # 🔴 2026-11-12 用户要求：**标的可参数化** ✓
    #    背景：F-012/F-017 在 TQQQ PASS 但 GDXU FAIL ⇒ 疑似「只在宽基有效」✗
    #    ⇒ 需要扩到 SPY/QQQ/YINN/CONL 交叉验证 ✓
    #    用法：`--param symbols=SPY,QQQ,YINN,CONL`（不传则用默认两个 ✓）
    _syms = [s.strip().upper() for s in
             str(params.get("symbols") or "TQQQ,GDXU").split(",") if s.strip()]
    for sym in _syms:
        # 🔴 2026-11-13：**标的自身**因子（ENE）逐 symbol 生成研究 features ✓
        _feat = feat_out
        if factor in _SYM_FACTORS:
            try:
                _sdf = _compute_factor(root, factor, _pd, symbol=sym)
                _feat = os.path.join(root, "evolution", "experiments",
                                     "factor-adoption",
                                     "features_%s-%s.csv" % (factor, sym))
                os.makedirs(os.path.dirname(_feat), exist_ok=True)
                _b = _pd.read_csv(os.path.join(root, "Data", "features.csv"))
                _b["date"] = _b["date"].astype(str).str[:10]
                _b.merge(_sdf, on="date", how="left").to_csv(_feat, index=False)
            except Exception as exc:      # noqa: BLE001
                runs[sym] = {"rc": -1,
                             "tail": "生成 %s 的 %s 列失败：%s: %s"
                                     % (sym, factor, type(exc).__name__,
                                        str(exc)[:150])}
                continue
        try:
            r = _run([py, os.path.join(root, "scripts",
                                       "factor_backtest_probe.py"),
                      "--factor", factor, "--symbol", sym,
                      "--direction", direction, "--features", _feat],
                     300, cwd=root)
            tail = ((r.stdout or "") + (r.stderr or "")).strip()[-500:]
            runs[sym] = {"rc": r.returncode, "tail": tail}
        except Exception as exc:          # noqa: BLE001
            runs[sym] = {"rc": -1, "tail": "%s: %s"
                                          % (type(exc).__name__, str(exc)[:150])}
    out["steps"]["probe"] = runs

    # ④ 收集产出
    arts = sorted(_glob.glob(os.path.join(
        root, "evolution", "experiments", "factor-adoption",
        "%s-*-oos.md" % factor)))
    out["steps"]["artifacts"] = [os.path.basename(a) for a in arts[-4:]]
    # 🔴 2026-11-12 实测修正：**`rc=1` 不代表执行失败** ✗
    #    `factor_backtest_probe.py` 在「因子未通过裁判」时也返回 1 ✗
    #    （首次跑 F-021 时两个标的都 rc=1，但 md/json 都正常产出 ✓
    #      回执却被判成 failed，白排查一轮 ✗）
    #    ⇒ 判据改成「**有没有产出 artifacts**」✓（产出即跑通 ✓）
    out["ok"] = bool(arts)
    if not out["ok"]:
        out["hint"] = ("两个标的都没产出 md ✗ ⇒ 看 `steps.probe.*.tail`；"
                       "常见原因：prices.csv 缺 GDX/GLD、或 features 日期对不上")
    else:
        # rc=1 时把语义写清楚，避免下次又误读成「执行失败」✗
        _rcs = {s: v.get("rc") for s, v in runs.items()}
        if any(rc != 0 for rc in _rcs.values()):
            out["note"] = ("rc=%s 表示**因子未通过裁判**（不是执行失败 ✓）—— "
                           "产出已生成，结论见 artifacts" % _rcs)
    return out


def _act_c5_backtest(params):
    """C5 ENE 回测裁判 ✓ —— 两步：dump `ene_pos` 进研究 features → 跑 probe。

    2026-10-31 用户裁定：**C5b（自身 ENE）进裁判** ✓
    理由：三变体 ICIR 差距在噪声内（YINN 差 0.044、GDXU 杠杆反而更好 ✗）
    ⇒ 选**最简**的（不需要正股映射表维护 ✓）。
    ⚠️ 且 ICIR 已证实**结构性虚高**（IC 自相关 0.99 ⇒ n_eff 仅 5~15）
    ⇒ **只有裁判结果算数** ✗
    """
    base = str(params.get("features")
               or "evolution/experiments/factor-adoption/features_c5.csv")
    # 2026-10-31 用户裁定：**跑多个标的** ✓（单标的不够代表性）
    # 每个标的必须**各自 dump 一份 features** ✗ —— `ene_pos` 是单列，
    # 不同标的的信号不能塞进同一份文件（会互相覆盖 ✗）
    syms = [x.strip() for x in str(
        params.get("symbols") or params.get("symbol") or "YINN").split(",")
        if x.strip()]
    mode = str(params.get("mode") or "self_ene")
    # `ene_pos` 高 = 超买 ⇒ 未来收益低 ⇒ direction=**negative** ✓
    direc = str(params.get("direction") or "negative")
    steps, feat_of = [], {}
    for s in syms:
        f = base[:-4] + "_%s.csv" % s if base.endswith(".csv") else base + "_" + s
        feat_of[s] = f
        steps.append([sys.executable, os.path.join(ROOT, "scripts", "eval_ene.py"),
                      "--dump-features", f, "--dump-symbol", s,
                      "--dump-mode", mode])
        steps.append([sys.executable,
                      os.path.join(ROOT, "scripts", "factor_backtest_probe.py"),
                      "--factor", "ene_pos", "--symbol", s,
                      "--direction", direc, "--features", f])
    out = []
    for cmd in steps:
        try:
            r = _run(cmd, 1800)
        except subprocess.TimeoutExpired:
            out.append({"cmd": " ".join(cmd[1:]), "rc": -1,
                        "stdout": "", "stderr": "超过 1800 秒"})
            continue
        # 🔴 probe 判 FAIL 时 **exit 1** ✗ —— 那是**结论**不是崩溃 ✓
        # ⇒ 不能 break，否则后面的标的全被跳过 ✗
        out.append({"cmd": " ".join(cmd[1:]), "rc": r.returncode,
                    "stdout": (r.stdout or "")[-2000:],
                    "stderr": (r.stderr or "")[-400:]})
    # 🔴 2026-10-31 实测：`ok` 用 `rc == 0` 判会让**整个任务显示 failed** ✗
    # 而 probe 判 FAIL 时 `exit 1` 是**结论**不是崩溃 ✗
    # ⇒ 只把「执行异常」（rc not in 0/1）算失败 ✓
    # 并从 stdout 里抽出每个标的的判定，避免被 2000 字截断看不到 ✓
    import re as _re
    verdicts = {}
    for st in out:
        m = _re.search(r"symbol (\w+) --direction", str(st.get("cmd")))
        if not m:
            continue
        v = _re.search(r"判定：\*\*(PASS|FAIL)", str(st.get("stdout") or ""))
        verdicts[m.group(1)] = v.group(1) if v else "?"
    bad = [x for x in out if x.get("rc") not in (0, 1)]
    return {"ok": not bad,
            "symbols": syms, "features": feat_of, "verdicts": verdicts,
            "n_pass": sum(1 for v in verdicts.values() if v == "PASS"),
            "n_fail": sum(1 for v in verdicts.values() if v == "FAIL"),
            "note": "⚠️ 裁判 FAIL 时 probe 会 exit 1 —— 那是**结论**不是崩溃 ✓",
            "errors": bad}


def _act_factor_reduce_probe(params):
    """**风控型因子专用裁判**：减仓触发回测 ✓（2026-11-02 用户裁定接进队列）。

    为什么需要独立动作 ✗：`factor_backtest_probe` 的口径是「因子 → 仓位 0.2~1.0
    线性映射」✗ 它要求因子能**决定仓位比例** ✗ 但 F-016/F-018/F-020 的能力只是
    「识别危险时刻」✗ ⇒ 用满仓吃 beta 的口径去测必然「跑输 B0」✗ 是口径错配 ✗

    参数：
      - `factor`：`ene` / `f020` / `f020_pct`（默认 `ene`）
      - `symbols`：逗号分隔（默认 SPY,YINN,GDXU,CONL,QQQ）
      - `trend_filter`：`1` 开启 MA200 趋势过滤 ✓
        ⚠️ **位置型因子（ENE）不要开** ✗ —— 实测 GDXU 从 +0.05 掉到 -0.04 ✗
           **状态型因子（f020_pct）要开** ✓ —— 有效数 2/5→4/5 ✓
      - `json`：结果落盘路径
    """
    factor = str(params.get("factor") or "ene")
    syms = str(params.get("symbols") or "SPY,YINN,GDXU,CONL,QQQ")
    tf = str(params.get("trend_filter") or "").lower() in ("1", "true", "yes", "on")
    js = params.get("json") or (
        "evolution/experiments/factor-adoption/reduce-%s.json" % factor)

    cmd = [sys.executable,
           os.path.join(ROOT, "scripts", "factor_reduce_probe.py"),
           "--factor", factor, "--symbols", syms, "--json", js]
    if tf:
        cmd.append("--trend-filter")
    try:
        r = _run(cmd, 1800)
    except subprocess.TimeoutExpired:
        return {"ok": False, "factor": factor, "trend_filter": tf,
                "error": "超过 1800 秒"}
    return {"ok": r.returncode == 0, "factor": factor,
            "trend_filter": tf, "symbols": syms, "json": js,
            "note": "判据是 **Calmar**（不是「跑赢 B0」✗）—— "
                    "风控型因子的价值是「同样收益下更少回撤」✓",
            "stdout": (r.stdout or "")[-3000:],
            "stderr": (r.stderr or "")[-400:]}


def _act_f_factor_backtest(params):
    """F-012 / F-020 通用回测裁判 ✓（2026-11-02）。

    两步：`eval_f020.py --dump-features`（写出 `f012_term` / `f020_pc`）
    → `factor_backtest_probe.py --factor <列> --direction <方向>` ✓

    ⚠️ **一个动作跑一个因子** ✗ —— 用户裁定 F-012 / F-020 是**两个独立裁判** ✓
    （两者信号来源不同、经济含义不同，合在一起会混淆结论 ✗）

    方向：
      - `f012_term`（term 变化率）：高=恐慌缓和 ⇒ **positive** ✓
      - `f020_pc`（P/C>1.2 触发）：高=极恐 ⇒ **negative** ✓（逆向：触发时应看多）
    """
    feat = str(params.get("features")
               or "evolution/experiments/factor-adoption/features_f012f020.csv")
    factor = str(params.get("factor") or "f012_term")
    direc = str(params.get("direction") or "positive")
    sym = str(params.get("symbol") or "SPY")
    steps = [
        [sys.executable, os.path.join(ROOT, "scripts", "eval_f020.py"),
         "--dump-features", feat],
        [sys.executable, os.path.join(ROOT, "scripts", "factor_backtest_probe.py"),
         "--factor", factor, "--symbol", sym,
         "--direction", direc, "--features", feat],
    ]
    out = []
    for cmd in steps:
        try:
            r = _run(cmd, 1800)
        except subprocess.TimeoutExpired:
            out.append({"cmd": " ".join(cmd[1:]), "rc": -1,
                        "stdout": "", "stderr": "超过 1800 秒"})
            continue
        # 🔴 probe 判 FAIL 时 exit 1 是**结论**不是崩溃 ✗ ⇒ 不 break ✓
        out.append({"cmd": " ".join(cmd[1:]), "rc": r.returncode,
                    "stdout": (r.stdout or "")[-2000:],
                    "stderr": (r.stderr or "")[-400:]})
    return {"ok": all(x["rc"] in (0, 1) for x in out),
            "factor": factor, "direction": direc, "symbol": sym,
            "note": "⚠️ 裁判 FAIL 时 probe 会 exit 1 —— 那是**结论**不是崩溃 ✓",
            "steps": out}


def _act_c1_backtest(params):
    """C1 回测裁判（M2.2）✓ —— 两步：把 `baa10y_z` 并入研究 features → 跑 probe。

    2026-10-30：相关性复核**通过**（无 `|ρ|>0.5 且 n≥250` 的列 ⇒ 跳过正交化）✓
    ⇒ 直接进回测裁判 ✓。
    `factor_backtest_probe.py` 只认 features 里的**列** ✗，而 baa10y 在
    `Data/raw/fred_baa10y_avail.csv` ⇒ 先 dump 一份研究专用 features ✓。
    """
    feat = str(params.get("features")
               or "evolution/experiments/factor-adoption/features_c1.csv")
    # 2026-10-30：支持**多组合扫描** ✓（`symbols`/`directions` 逗号分隔）——
    # ⚠️ 这是**多重检验** ✗：同一份数据反复试直到通过 = 过拟合 ✓
    # ⇒ 结果只作**探索性分析**，**不作为采纳依据** ✗（提案里必须写明）
    syms = [x.strip() for x in str(params.get("symbols")
                                   or params.get("symbol") or "TQQQ").split(",")
            if x.strip()]
    dirs = [x.strip() for x in str(params.get("directions")
                                   or params.get("direction") or "positive").split(",")
            if x.strip()]
    sym = syms[0]
    # C1 是**逆向**因子：信用利差高（z 高）= 恐慌 = 看多 ⇒ direction=positive ✓
    direc = dirs[0]
    steps = [[sys.executable, os.path.join(ROOT, "scripts", "eval_baa10y.py"),
              "--dump-features", feat]]
    for s in syms:
        for d in dirs:
            steps.append(
                [sys.executable,
                 os.path.join(ROOT, "scripts", "factor_backtest_probe.py"),
                 "--factor", "baa10y_z", "--symbol", s,
                 "--direction", d, "--features", feat])
    out = []
    for cmd in steps:
        try:
            r = _run(cmd, 1800)
        except subprocess.TimeoutExpired:
            out.append({"cmd": " ".join(cmd[1:]), "rc": -1,
                        "stdout": "", "stderr": "超过 1800 秒"})
            continue
        # 🔴 probe 判 FAIL 时 **exit 1** ✗ —— 那是**结论**不是崩溃 ✓
        # ⇒ 不能因为 rc!=0 就 break，否则后面的组合全被跳过 ✗
        out.append({"cmd": " ".join(cmd[1:]), "rc": r.returncode,
                    "stdout": (r.stdout or "")[-1800:],
                    "stderr": (r.stderr or "")[-400:]})
    return {"ok": all(x["rc"] == 0 for x in out),
            "combos": len(syms) * len(dirs),
            "warning": "⚠️ 多组合扫描 = 多重检验 ⇒ 仅作探索，不作为采纳依据 ✗",
            "steps": out}


def _act_backtest_plan(params):
    """在 Mac 上跑**建仓/加仓计划回测** ✓（`shoutu_fng.csv` 只在 Mac 本地 ✗）。

    `symbols` 非空 ⇒ 覆盖默认 6 个标的 ✓；`json` 非空 ⇒ 完整结果落盘 ✓。
    """
    cmd = [sys.executable,
           os.path.join(ROOT, "scripts", "backtest_position_plan.py")]
    syms = str(params.get("symbols") or "").strip()
    if syms:
        cmd += ["--symbols", syms]
    out = str(params.get("json") or "").strip()
    if out:
        cmd += ["--json", out if os.path.isabs(out) else os.path.join(ROOT, out)]
    try:
        r = _run(cmd, 900)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "超过 900 秒未完成"}
    except (subprocess.SubprocessError, OSError) as exc:
        return {"ok": False, "reason": "执行失败：%s" % exc}
    return {"ok": r.returncode == 0, "rc": r.returncode,
            "stdout": (r.stdout or "")[-3000:], "stderr": (r.stderr or "")[-500:]}


def _act_run_pipeline(params):
    """重算 `features.csv`（与每日链**同一条**调用序列 ✓）。

    动机（2026-10-29 实测）：`features.csv` 尾行的 `vix`/`term` 是空 ✗，
    而 `raw/vix.csv`、`raw/prices.csv` 都已到新日期 ✓ ⇒ 说明 pipeline 当时
    **在 vix 数据补齐之前**就跑了，尾行因子只能留空，之后没人重算 ✗。

    🔴 会**覆写** `features.csv` / `portfolio_features.csv` ✗ —— 所以只跑
    与每日链完全相同的三步（不多做、不少做），避免两条口径打架 ✓。
    """
    code = ("from fg_system import pipeline;"
            "pipeline.run(write=True);"
            "us=pipeline.run_equity_v2();"
            "cr=pipeline.run_crypto(write=True);"
            "pipeline.run_portfolio(us, cr, write=True)")
    try:
        r = _run([sys.executable, "-c", code], 1800)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "超过 1800 秒未完成"}
    except (subprocess.SubprocessError, OSError) as exc:
        return {"ok": False, "reason": "执行失败：%s" % exc}
    return {"ok": r.returncode == 0, "rc": r.returncode,
            "stdout": (r.stdout or "")[-1200:],
            "stderr": (r.stderr or "")[-500:]}


def _act_factor_diag(params):
    """查六因子为什么缺 ✓ —— 只读，报各数据源的尾行日期与近 30 行非空数。

    动机（2026-10-29）：简报里 `VIX — 数据缺失` / `TERM — 数据缺失` ✗，
    但没人知道是 features 没算、还是原始 csv 没更新 ✗ ⇒ 只能上 Mac 查 ✓。
    """
    import pandas as pd

    data = os.path.join(ROOT, "Data")
    out = {}

    def _tail(path):
        try:
            d = pd.read_csv(path, parse_dates=["date"])
            if d.empty:
                return "空文件"
            return "%s（%d 行）" % (d["date"].iloc[-1].date(), len(d))
        except Exception as exc:                   # noqa: BLE001
            return "读不出：%s" % exc

    out["raw/vix.csv"] = _tail(os.path.join(data, "raw", "vix.csv"))
    out["raw/prices.csv"] = _tail(os.path.join(data, "raw", "prices.csv"))
    out["features.csv"] = _tail(os.path.join(data, "features.csv"))

    try:
        f = pd.read_csv(os.path.join(data, "features.csv"), parse_dates=["date"])
        last = f.iloc[-1]
        out["features 尾行"] = {
            c: (None if pd.isna(last.get(c)) else float(last[c]))
            for c in ("fg_index", "vix", "term") if c in f.columns}
        out["features 尾行"]["date"] = str(last["date"].date())
        # 从哪一天开始断的：倒着数连续为空的长度
        for c in ("vix", "term"):
            if c not in f.columns:
                continue
            s = f[c]
            n = 0
            for v in reversed(list(s)):
                if pd.isna(v):
                    n += 1
                else:
                    break
            out["%s 连续缺失" % c] = "%d 行" % n
        out["近30行非空"] = {c: int(f[c].tail(30).notna().sum())
                          for c in ("vix", "term") if c in f.columns}
    except Exception as exc:                       # noqa: BLE001
        out["features 尾行"] = "读不出：%s" % exc

    try:
        r = _run(
            [sys.executable, os.path.join(ROOT, "scripts", "check_freshness.py")],
            180)
        out["check_freshness"] = {"rc": r.returncode,
                                  "out": (r.stdout or "")[-800:]}
    except (subprocess.SubprocessError, OSError) as exc:
        out["check_freshness"] = "执行失败：%s" % exc
    return {"ok": True, "result": out}


def _act_eval_baa10y(params):
    """在 Mac 上跑 **C1 信用利差评测** ✓（`fred_baa10y_avail.csv` 只在 Mac 本地 ✗）。

    `orth` 非空 ⇒ 先剔除该列（如 `fed`）再评测 ✓（用户裁定：先正交化再进裁判 ✓）；
    `json` 非空 ⇒ 把完整报告写到该路径（相对路径按仓库根解析 ✓）。
    """
    cmd = [sys.executable, os.path.join(ROOT, "scripts", "eval_baa10y.py")]
    orth = str(params.get("orth") or "").strip()
    if orth:
        cmd += ["--orthogonalize", orth]
    out = str(params.get("json") or "").strip()
    if out:
        cmd += ["--json", out if os.path.isabs(out) else os.path.join(ROOT, out)]
    try:
        r = _run(cmd, 900)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "超过 900 秒未完成"}
    except (subprocess.SubprocessError, OSError) as exc:
        return {"ok": False, "reason": "执行失败：%s" % exc}
    return {"ok": r.returncode == 0, "rc": r.returncode,
            "orth": orth or None,
            "stdout": (r.stdout or "")[-2500:], "stderr": (r.stderr or "")[-500:]}


def _act_run_invest_research(params):
    """跑一次投研简报 ✓ —— 默认 `--dry-run`（不推飞书）✓。

    动机（2026-10-29）：简报连停两天，改完需要**今天就能验证** ✗，
    而不是干等明天 05:30 ✗。`--dry-run` 只写文件 + 打印开头 ⇒ 从结果里
    就能确认「🔌 数据源健康」这节在不在 ✓。要真发：`--param push=1` ✓。
    """
    push = str(params.get("push") or "") in ("1", "true", "yes")
    cmd = [sys.executable, os.path.join(ROOT, "scripts", "invest_research.py")]
    if not push:
        cmd.append("--dry-run")
    try:
        # 🔴 2026-10-29：600 → **900** 秒 ✗ —— 实测一次 dry-run 到 600 秒被杀，
        # 而串行版历史耗时 478 秒（并发版不该更慢）⇒ 说明阶段耗时波动很大 ✗。
        # 与每日链 `run_guarded` 给这步的 900 秒对齐 ✓。
        r = _run(cmd, 900)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "超过 900 秒未完成"
                "（阶段级进度见 daily_log_tail --which invest）"}
    except (subprocess.SubprocessError, OSError) as exc:
        return {"ok": False, "reason": "执行失败：%s" % exc}
    return {"ok": r.returncode == 0, "rc": r.returncode, "push": push,
            "stdout": (r.stdout or "")[-1500:], "stderr": (r.stderr or "")[-500:]}



def _fg_pos_tendency(pd, root, with_erp):
    """把「6 因子合成」转成**仓位倾向** 0~100（高=该加仓）✓

    🔴 为什么必须转：`fg_index` 是**贪婪度**（高=贪婪=该减仓）✗
       而 `factor_backtest_probe` 的 `positive` 方向是「因子高 ⇒ 仓位高」✗
       ⇒ 直接把 `fg_index` 丢进去会**方向反了** ✗
       ⇒ 统一转成 `100 - fg_index`（恐惧度，高=该加仓）✓

    `with_erp=True` 时：`0.9 × (100-fg_index) + 0.1 × (erp×100)` ✓
       - ERP 是 0~1 分位（高=便宜=该加仓 ✓，与「恐惧度」同向 ✓）
       - 权重 10%：参照 `config.WEIGHTS` 里 putcall 的 0.10 ✓
         其余 6 项按比例缩到 0.90 ✓（不新增权重总量，只做再分配 ✓）
    """
    base = pd.read_csv(os.path.join(root, "Data", "features.csv"))
    base["date"] = base["date"].astype(str).str[:10]
    base["fg_index"] = pd.to_numeric(base["fg_index"], errors="coerce")
    df = base[["date", "fg_index"]].dropna()
    df["fg_base"] = 100.0 - df["fg_index"]
    if not with_erp:
        return df[["date", "fg_base"]]

    erp = _compute_erp(root, pd)
    m = df.merge(erp, on="date", how="inner").dropna()
    m["fg_erp"] = 0.90 * m["fg_base"] + 0.10 * (m["erp"] * 100.0)
    return m[["date", "fg_erp"]]


#: `read_tail` 允许读的路径前缀 ✓ —— 定义已上移 `queue_core.READ_ALLOW`
#: （`data` 包也要用）⇒ 这里只留别名 ✓


#: 需要「从仓库副本装到 LaunchAgents」的 plist ✓

ACTIONS = {
    "c1_backtest": _act_c1_backtest,
    "c5_backtest": _act_c5_backtest,
    "f_factor_backtest": _act_f_factor_backtest,
    "factor_reduce_probe": _act_factor_reduce_probe,
    "factor_probe": _act_factor_probe,
    "factor_diag": _act_factor_diag,
    "backtest_plan": _act_backtest_plan,
    "run_pipeline": _act_run_pipeline,
    "eval_baa10y": _act_eval_baa10y,
    "verify_hypotheses": _act_verify_hypotheses,
    "verify_hyp": _act_verify_hyp,
    "archive_briefs": _act_archive_briefs,
    "weekly_review": _act_weekly_review,
    "rerun_brief": _act_rerun_brief,
    "run_invest_research": _act_run_invest_research,
}
