# -*- coding: utf-8 -*-
"""账户/持仓快照同步 —— 实盘数据运行时生成，不入库（数据层改造）。

模式（环境变量 FG_SYNC_MODE，**默认 static**）：
  static : 不调用任何外部 API。**公司电脑安全默认**：仅检查现有快照并打印状态，
           绝不触碰 Data/accounts.csv 与 Data/positions.csv。
  live   : 从富途(FutuOpenD)与 OKX(REST)动态拉取，**追加当日快照行**（保留历史行）。

日期口径（MT-47，2026-10-20 起）：
  写入的 `date` = **最近已收盘的美东交易日**（16:00 ET 为收盘线）✓，与
  `features.csv` 的 `date` 同为美东口径 ✓。旧版写的是 Mac 本地日期 ✗ ⇒ 两表会
  差一天 ✗。切换点在 `note` 列标注 ✓。

依赖：
  富途 : 本机已运行 FutuOpenD（默认 127.0.0.1:11111）+ 已开通 API 交易权限。
   OKX : ~/.okx_credentials.json（chmod 600，绝不入库）：
         {"api_key": "...", "secret": "...", "passphrase": "...",
          "proxy": "http://127.0.0.1:7890"}   # 国际站被墙时需要

用法：
  python scripts/sync_positions.py --check      # 查看当前快照状态（任何模式安全）
  FG_SYNC_MODE=static python scripts/sync_positions.py   # 公司电脑 / 离线
  FG_SYNC_MODE=live   python scripts/sync_positions.py   # 家里 Mac 动态同步
"""
import argparse
import datetime as dt
import json
import os
import sys
from zoneinfo import ZoneInfo

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # 同目录模块 ✓
from fg_system import config  # noqa: E402
import futu_health  # noqa: E402  —— 预检/硬超时/状态落盘 ✓

ACCOUNTS_HEADER = ["date", "account", "net_value", "securities_mv", "cash",
                   "unrealized_pnl", "day_pnl", "currency", "note"]
POSITIONS_HEADER = ["date", "account", "symbol", "name", "qty", "price",
                    "cost", "market_value", "notional", "margin", "bucket", "currency"]

OKX_CRED_PATH = os.path.expanduser("~/.okx_credentials.json")

# ------------------------------------------------- 日期口径 = 美东交易日（MT-47）
# `features.csv` 的 `date` 是**美东交易日** ✓（实测只有周一~周五 ✓），而旧版
# `today()` 用 `dt.date.today()` = **Mac 本地日期** ✗ ⇒ 北京时间上午跑，会把「还没
# 收盘的今天」写进快照 ✗ ⇒ `accounts.csv` / `positions.csv` 比 `features.csv`
# **领先一天** ✗。实测（2026-10-20）：`accounts.csv` 里存在 **10-10 / 10-11 /
# 10-17 / 10-18 四个周末日期** ✗，进一步证明旧口径不是交易日 ✓。凡按 `date` 关联
# 两表的假说（H-072 / H-076 / H-077 / H-006 / H-008 / H-009）都带**系统性一天偏移** ✗。
TZ_ET = ZoneInfo("America/New_York")
MARKET_CLOSE_HOUR_ET = 16           # 美股常规收盘 16:00 ET
DATE_BASIS_SWITCH = "2026-10-20"    # 该日（含）起写入的快照用美东交易日口径
DATE_BASIS_NOTE = "日期口径=美东交易日"


def _prev_business_day(d):
    """上一个工作日：仅跳过周末。

    ⚠️ 美股**节假日未**处理（不引入 exchange_calendars 依赖）—— 节假日的边界情形
    见 `docs/mac-tasks.md` MT-47 备注 ✓。
    """
    d = d - dt.timedelta(days=1)
    while d.weekday() >= 5:         # 5=Sat, 6=Sun
        d -= dt.timedelta(days=1)
    return d


def trading_date(now_et=None):
    """返回**最近已收盘**的美东交易日（ISO 字符串）。

    规则（MT-47）：
    - 美东 >= 16:00 ⇒ 当日（当日为周末则回退）；
    - 美东 < 16:00 ⇒ **上一个**工作日 ⇒ 绝不写到「还没收盘的今天」✗。

    实测对照（2026-10-21）：
    - 北京 04:30 = 美东 10-20 16:30 ⇒ `2026-10-20` ✓
    - 北京 20:00 = 美东 10-21 08:00（未收盘）⇒ 仍 `2026-10-20` ✓

    `now_et` 可注入（测试用），须为 tz-aware 的美东时间。
    """
    if now_et is None:
        now_et = dt.datetime.now(TZ_ET)
    d = now_et.date()
    if now_et.hour < MARKET_CLOSE_HOUR_ET or d.weekday() >= 5:
        d = _prev_business_day(d)
    return d.isoformat()


def _tag_date_basis(note, date):
    """在 `note` 标注日期口径（MT-47）—— 便于将来区分切换点前后的行 ✓。

    历史行 = Mac 本地日期（note 无标注，且运行时数据不入库 ✓）；
    切换日及之后 = 美东交易日（note 带标注 ✓）。
    """
    if date >= DATE_BASIS_SWITCH:
        return f"{note}；{DATE_BASIS_NOTE}"
    return note


def _f(x, default=0.0):
    """安全转 float：'N/A'/空/None 等异常值 → default。"""
    try:
        v = float(x)
        return v
    except (TypeError, ValueError):
        return default


# MT-48（2026-10-20 P0）：硬错误收集 —— 必需字段缺失时不默认 0、而是记录并中止写盘。
# 旧版 _f(x, default=0.0) 遍布金额/价格字段 ⇒ OKX /account/balance 无顶层 cash ⇒
# cash 恒 0、net_value 恒等式不成立 ⇒ 静默假数据 ✗。
_SYNC_ERRORS = []


def _req_f(x, field, source):
    """MT-48：必需字段转 float；缺失/空/非数值 ⇒ 记录错误并返回 None（不默认 0）。"""
    if x is None or x == "":
        _SYNC_ERRORS.append(f"{source}: 必需字段 {field} 缺失/空（不默认 0）")
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        _SYNC_ERRORS.append(f"{source}: 必需字段 {field} 非数值（{x!r}，不默认 0）")
        return None


def _sum_unrealized(pos_rows):
    """未实现盈亏 = Σ `qty × (price − cost)` ✓。

    ⚠️ **不**取 `accinfo_query` 的 `unrealized_pl` ✗：该字段在部分 FutuOpenD 版本
    **不存在** ✗ ⇒ `r.get(..., 0)` 会**静默写 0.0** ✗ —— 2026-10-19 实测
    `accounts.csv` 10-16 快照 `unrealized_pnl=0.0` ✗，而持仓（AXTX/YINN/GDXU/…）
    全在浮亏 ✓ ⇒ 假说分析（H-004 / H-072）据此得出的结论全不可信 ✗。
    改由**持仓行自算** ✓：可验证 ✓、不依赖 API 字段名 ✓。
    """
    total = 0.0
    for r in pos_rows:
        qty, price, cost = _f(r[4]), _f(r[5]), _f(r[6])
        if qty and cost:
            total += qty * (price - cost)
    return round(total, 2)


def load_existing():
    """读取现有快照；文件缺失时返回空 DataFrame（带表头）。"""
    a = pd.read_csv(config.ACCOUNTS_PATH) if os.path.exists(config.ACCOUNTS_PATH) \
        else pd.DataFrame(columns=ACCOUNTS_HEADER)
    p = pd.read_csv(config.POSITIONS_PATH) if os.path.exists(config.POSITIONS_PATH) \
        else pd.DataFrame(columns=POSITIONS_HEADER)
    return a, p


def write_snapshot(accounts, positions):
    """原子写（tmp + rename），追加当日行。"""
    tmp_a, tmp_p = config.ACCOUNTS_PATH + ".tmp", config.POSITIONS_PATH + ".tmp"
    accounts.to_csv(tmp_a, index=False)
    positions.to_csv(tmp_p, index=False)
    os.replace(tmp_a, config.ACCOUNTS_PATH)
    os.replace(tmp_p, config.POSITIONS_PATH)


# ---------------------------------------------------------------- 富途
def _opend_alive(host="127.0.0.1", port=11111, timeout=2.0):
    """快速探测 FutuOpenD 是否可达（避免无 OpenD 时连接挂起数十秒）。"""
    import socket
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def sync_futu(accounts, positions, date):
    """富途(FutuOpenD) → 股票账户快照行。OpenD 不可达时打印提示并跳过（不崩溃）。"""
    if not _opend_alive():
        print("[futu] FutuOpenD 未运行（127.0.0.1:11111 不可达），跳过股票账户。\n"
              "       家里 Mac 首次使用：下载 FutuOpenD 并开通 API 权限后重试；"
              "公司电脑用 static 模式")
        return accounts, positions
    try:
        import futu
    except ImportError:
        print("[futu] 未安装 futu-api，跳过股票账户（pip install futu-api）")
        return accounts, positions
    try:
        ctx = futu.OpenSecTradeContext(filter_trdmarket=futu.TrdMarket.US,
                                       host="127.0.0.1", port=11111,
                                       security_firm=futu.SecurityFirm.FUTUSECURITIES)
    except Exception as e:
        print(f"[futu] 无法连接 FutuOpenD（127.0.0.1:11111）：{e}\n"
              f"       请先启动 FutuOpenD 并开通 API 权限，或忽略此项（公司电脑用 static 模式）")
        return accounts, positions

    ret, accs = ctx.get_acc_list()
    if ret != futu.RET_OK or (hasattr(accs, "empty") and accs.empty):
        print(f"[futu] get_acc_list 失败: {accs}")
        return accounts, positions
    # futu 10.x 返回 DataFrame；优先取 REAL + ACTIVE 的保证金账户
    if hasattr(accs, "iloc"):
        df = accs
        if "trd_env" in df.columns and "acc_status" in df.columns:
            df = df[(df["trd_env"] == "REAL") & (df["acc_status"] == "ACTIVE")]
            if df.empty:
                df = accs[accs["trd_env"] == "REAL"]
        if df.empty:
            print(f"[futu] 无可用真实账户: {accs}")
            return accounts, positions
        acc_id = int(df.iloc[0]["acc_id"])
    else:
        acc_id = int(accs[0]["acc_id"])
    print(f"[futu] 使用账户 acc_id={acc_id}")

    # 资产（净值/现金/市值）——DataFrame 单行
    ret, info = ctx.accinfo_query(acc_id=acc_id, currency="USD")
    if ret != futu.RET_OK:
        print(f"[futu] accinfo_query 失败: {info}")
        return accounts, positions
    if hasattr(info, "iloc") and not info.empty:
        r = info.iloc[0]
        # MT-48：必需字段缺失 ⇒ 记录错误并 return（不默认 0，避免假数据）
        net = _req_f(r.get("total_assets"), "total_assets", "futu")
        cash = _req_f(r.get("cash"), "cash", "futu")
        mv = _req_f(r.get("market_val"), "market_val", "futu")
        if net is None or cash is None or mv is None:
            return accounts, positions
        note = "富途动态同步"
        if "net_cash_power" in info.columns:
            note += f"；净购买力={r.get('net_cash_power')}"
        # ⚠️ 账户行**延后到持仓之后**写 —— 未实现盈亏要由持仓自算 ✓（见 `_sum_unrealized`）
    else:
        print(f"[futu] accinfo 返回异常: {info}")
        return accounts, positions

    # 持仓——DataFrame 多行；code 去除 "US." 前缀
    ret, poss = ctx.position_list_query(acc_id=acc_id, currency="USD")
    if ret != futu.RET_OK:
        print(f"[futu] position_list_query 失败: {poss}")
        return accounts, positions
    pos_rows = []
    if hasattr(poss, "iterrows"):
        for _, pos in poss.iterrows():
            code = str(pos.get("code", "") or "").replace("US.", "", 1)
            qty = _f(pos.get("qty", 0))
            if qty == 0:
                continue
            cost = _f(pos.get("cost_price", 0))
            price = _f(pos.get("nominal_price", 0))
            notional = _f(pos.get("market_val", 0)) or round(qty * price, 2)
            name = str(pos.get("stock_name", "") or "") or code
            row = [date, "stock", code, name, qty, round(price, 4), round(cost, 4),
                   round(notional, 2), round(notional, 2), "", "system", "USD"]
            pos_rows.append(row)
            positions.loc[len(positions)] = row
    # 账户行延后写：未实现盈亏由持仓自算 ✓（不取可能缺失的 `unrealized_pl` ✗）
    accounts.loc[len(accounts)] = [date, "stock", round(net, 2), round(mv, 2),
                                   round(cash, 2), _sum_unrealized(pos_rows), "",
                                   "USD", _tag_date_basis(note, date)]
    ctx.close()
    return accounts, positions


# ---------------------------------------------------------------- OKX
def _okx_creds():
    if not os.path.exists(OKX_CRED_PATH):
        return None
    with open(OKX_CRED_PATH) as f:
        return json.load(f)


def _okx_request(creds, path):
    """OKX V5 REST 请求（curl 签名，与 scripts/okx_monitor.py 同法；走代理）。"""
    import base64
    import hashlib
    import hmac
    import subprocess
    import tempfile
    import datetime

    ts = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    sig = base64.b64encode(
        hmac.new(creds["secret"].encode(),
                 (ts + "GET" + path).encode(), hashlib.sha256).digest()
    ).decode()
    # G-5（WT-12 审查）：凭据**不得**出现在 curl 的 argv 里 —— 同机任意进程
    # （`ps aux` / 任务管理器）都能读到 api_key / 签名 / passphrase，等于把
    # 密钥文件 0600 的保护整个绕开。改用 `--config` 临时文件（0600，用完即删）；
    # argv 里只留 `-x` 代理（无凭据）。
    def _q(v):
        return str(v).replace("\\", "\\\\").replace('"', '\\"')

    cfg_lines = ['header = "OK-ACCESS-KEY: %s"' % _q(creds["api_key"]),
                 'header = "OK-ACCESS-SIGN: %s"' % _q(sig),
                 'header = "OK-ACCESS-TIMESTAMP: %s"' % _q(ts),
                 'header = "OK-ACCESS-PASSPHRASE: %s"' % _q(creds["passphrase"]),
                 'header = "Content-Type: application/json"']
    fd, cfg = tempfile.mkstemp(prefix="okx_curl_", suffix=".cfg")
    try:
        os.chmod(cfg, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(cfg_lines) + "\n")
        cmd = ["curl", "-s", "-m", "30", "--config", cfg,
               "https://www.okx.com" + path]
        if creds.get("proxy"):
            cmd[1:1] = ["-x", creds["proxy"]]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=35)
    finally:
        os.remove(cfg)
    if r.returncode != 0:
        raise RuntimeError(f"curl 失败: {r.stderr[:150]}")
    return json.loads(r.stdout or "{}")


def sync_okx(accounts, positions, date):
    """OKX REST → 加密账户快照行。凭据缺失/网络失败时打印提示并跳过。"""
    creds = _okx_creds()
    if not creds:
        print(f"[okx] 缺少凭据文件 {OKX_CRED_PATH}，跳过加密账户。\n"
              f"       格式: {{\"api_key\":\"..\",\"secret\":\"..\",\"passphrase\":\"..\","
              f"\"proxy\":\"http://127.0.0.1:7890\"(可选)}}，chmod 600")
        return accounts, positions

    try:
        bal = _okx_request(creds, "/api/v5/account/balance")
    except Exception as e:
        print(f"[okx] get_balance 失败: {e}")
        return accounts, positions
    if bal.get("code") != "0":
        print(f"[okx] get_balance 错误: code={bal.get('code')} msg={bal.get('msg')}")
        return accounts, positions
    data = (bal.get("data") or [{}])[0]
    # MT-48：totalEq 必需（缺失 ⇒ 记录错误并 return）；cash 顶层字段 OKX 确实没有
    # ⇒ 写 NaN（不默认 0，避免 cash 恒 0 导致净值恒等式假成立）
    total_eq = _req_f(data.get("totalEq"), "totalEq", "okx")
    if total_eq is None:
        return accounts, positions
    cash_raw = data.get("cash")
    cash = _f(cash_raw, None) if cash_raw not in (None, "") else float("nan")
    accounts.loc[len(accounts)] = [date, "crypto", round(total_eq, 2), "", round(cash, 2),
                                   "", "", "USDT", _tag_date_basis("OKX 动态同步", date)]

    try:
        poss = _okx_request(creds, "/api/v5/account/positions")
    except Exception as e:
        print(f"[okx] get_positions 失败: {e}")
        return accounts, positions
    if poss.get("code") != "0":
        print(f"[okx] get_positions 错误: code={poss.get('code')} msg={poss.get('msg')}")
        return accounts, positions
    for pos in poss.get("data") or []:
        inst = pos.get("instId", "")
        inst_type = pos.get("instType", "") or ""
        qty_raw = _f(pos.get("pos", 0))
        if qty_raw == 0:
            continue
        cost = _f(pos.get("avgPx", 0))
        price = _f(pos.get("markPx", 0))
        # MT-53：SWAP 的 pos 单位是「张」，ctVal 是每张对应币数（BTC-USDT-SWAP=0.01）
        # ⇒ qty 列必须写币数（= 张数 × ctVal），否则 notional 差 ctVal 倍。
        ct_val = _f(pos.get("ctVal", 0))
        contracts_note = ""
        if inst_type.upper() == "SWAP" and ct_val > 0:
            qty = qty_raw * ct_val
            contracts_note = "（%g张×ctVal=%g=%g币）" % (qty_raw, ct_val, qty)
        else:
            qty = qty_raw
        notional = _f(pos.get("notionalUsd", 0)) or round(qty * price, 2)
        name = {"BTC-USDT": "BTC现货杠杆(借USDT买入)",
                "BTC-USDT-SWAP": "BTC永续"}.get(inst, inst) + contracts_note
        positions.loc[len(positions)] = [date, "crypto", inst, name, round(qty, 8),
                                         round(price, 4),
                                         round(cost, 4), round(notional, 2), round(notional, 2),
                                         "", "system", "USDT"]
    return accounts, positions


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser(description="账户/持仓快照同步（实盘数据运行时生成）")
    ap.add_argument("--check", action="store_true", help="仅查看当前快照状态，不执行任何同步")
    args = ap.parse_args()

    mode = os.environ.get("FG_SYNC_MODE", "static").strip().lower()

    if args.check:
        a, p = load_existing()
        print(f"当前日期口径（MT-47）：最近已收盘美东交易日 = {trading_date()}"
              f"（收盘线 {MARKET_CLOSE_HOUR_ET}:00 ET）")
        print("当前快照状态：")
        if a.empty:
            print("  accounts.csv 为空或不存在")
        else:
            print("  accounts.csv 最新日期:", a["date"].max(), "| 行数:", len(a))
            print(a.tail(3).to_string(index=False))
        if p.empty:
            print("  positions.csv 为空或不存在")
        else:
            print("  positions.csv 最新日期:", p["date"].max(), "| 行数:", len(p))
        return

    if mode == "static":
        a, p = load_existing()
        print("[sync] FG_SYNC_MODE=static：不调用任何外部 API（公司电脑模式）。")
        print(f"[sync] 现有快照保持原样：accounts {len(a)} 行 / positions {len(p)} 行。")
        print("[sync] 如需在家动态同步：FG_SYNC_MODE=live python scripts/sync_positions.py")
        return

    if mode != "live":
        print(f"[sync] 未知 FG_SYNC_MODE={mode!r}，取 static 行为（安全默认）。")
        return

    date = trading_date()   # MT-47：只算一次，避免跨午夜 / 跨收盘线时前后不一致
    print(f"[sync] FG_SYNC_MODE=live：动态同步 {date}"
          f"（美东交易日口径，{MARKET_CLOSE_HOUR_ET}:00 ET 为收盘线）")
    accounts, positions = load_existing()
    # 当日覆盖写：同一交易日已有快照行时先剔除，避免重复追加导致下游重复计入
    accounts = accounts[accounts["date"] != date].reset_index(drop=True)
    positions = positions[positions["date"] != date].reset_index(drop=True)
    a_before = len(accounts)
    p_before = len(positions)
    # 🔴 2026-10-29：富途**先预检端口** ✗ —— OpenD 没开时绝不能进 SDK ✗
    # （SDK 进 `_init_connect_sync` 就是无界重连 ✗，2026-10-28 连刷 3 小时把整条
    #   每日链拖死 ✗）。连不上就跳过富途、只用 OKX ✓，并把状态落盘给简报 ✓。
    futu_ok, futu_why = futu_health.preflight()
    if futu_ok:
        futu_health.guard(step="sync_positions")
        try:
            accounts, positions = sync_futu(accounts, positions, date)
        finally:
            futu_health.done()
        futu_health.write_status(True, "富途同步完成", "sync_positions")
    else:
        futu_health.write_status(False, futu_why, "sync_positions")
        print("[sync] %s ⇒ 跳过富途，仅用 OKX（状态已记入简报）" % futu_why)
    accounts, positions = sync_okx(accounts, positions, date)
    new_a = len(accounts) - a_before
    new_p = len(positions) - p_before

    # MT-48 ①：硬错误（必需字段缺失）⇒ 中止写盘（不默认 0）
    if _SYNC_ERRORS:
        print("⛔ 以下数据源硬错误，当日写入已中止（不写盘，避免静默假数据）：")
        for e in _SYNC_ERRORS:
            print("   - " + e)
        return 1
    # MT-48 ①：至少一源成功且有新增账户行才写盘；两源全失败 ⇒ 当日旧行已剔除
    # 却仍写盘 ⇒ 当日快照被删掉且 rc=0（静默丢金融数据 ✗）
    if new_a == 0:
        print("⛔ 两个数据源都未产出账户行（当日旧行已剔除），不写盘以避免静默丢数据。")
        return 1
    # MT-48 ④：写盘前断言 net_value = securities_mv + cash 且 net > 0
    for i in range(a_before, len(accounts)):
        r = accounts.iloc[i]
        net = _f(r["net_value"])
        mv = r["securities_mv"]
        cash = r["cash"]
        if net <= 0:
            print(f"⛔ net_value={net} <= 0 可疑（account={r['account']}），中止写盘。")
            return 1
        # OKX 行 securities_mv 为空（NaN）⇒ 跳过恒等式校验
        if pd.notna(mv) and abs(net - (_f(mv) + _f(cash))) > 1.0:
            print(f"⛔ 恒等式不成立：net={net} != mv({_f(mv)})+cash({_f(cash)})"
                  f"（account={r['account']}），中止写盘。")
            return 1

    write_snapshot(accounts, positions)
    print(f"[sync] 已写入：accounts {len(accounts)} 行（新增 {new_a}）"
          f"/ positions {len(positions)} 行（新增 {new_p}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
