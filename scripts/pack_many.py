#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多文件打包 → 飞书分片（写入 dist/feishu/text/<包名>-tNNN.txt，供 feishu_send.py 发送）。

与 pack_one.py 的分工：
    pack_one.py  单文件 → sync_pieces.txt（手工逐条复制的老流程）
    pack_many.py 多文件 → dist/feishu/text/（可直接被 feishu_send.py --pkg 发送）

用法（Windows）：
    py -3.10 scripts/pack_many.py sync_1010c AGENTS.md
    py -3.10 scripts/pack_many.py sync_1010d docs/windows-tasks.md scripts/foo.py

    # 增量模式（只发统一 diff，用于大文件如 docs/trading-discipline.md）：
    py -3.10 scripts/pack_many.py sync_1015a --patch docs/trading-discipline.md
    py -3.10 scripts/pack_many.py sync_1015b --patch --base-ref origin/main a.md b.py

约定（与 pack_one.py 一致）：
    · 包名只允许 [A-Za-z0-9_]（Mac 端标记正则是 ###FG:([A-Za-z0-9_]+):(\\d+)/(\\d+)###）。
    · 同一包名重复发送是**幂等**的：Mac 端按 <包>_<序号> 逐片覆盖，总数一致即可。
    · 路径必须是仓库内相对路径（tar 内路径决定 Mac 端白名单）。

【--patch 增量模式（2026-10-15 新增）】
背景：docs/trading-discipline.md 有 336 KB ⇒ 整份发要 118 片（且 116 片那次真的挂在
飞书会话上）。本模式只发**统一 diff**（difflib.unified_diff），片数降到个位数。

🔴 回落规则（任一满足 ⇒ 走原来的整文件 tar 路径，并在 stdout 明确打印原因，绝不静默）：
    · 拿不到基准（git show 失败：非 git 仓库 / ref 不存在 / 无代理致超时）
    · 某文件在基准里不存在（新增文件）
    · diff 字节数 ≥ 整文件 tar 字节数（不值得）
"""
import argparse
import glob
import difflib
import io
import os
import subprocess
import sys
import tarfile

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)

from pack_one import _b64url  # noqa: E402 —— 复用已验证编码器，避免两套实现分叉

# 自设输出编码：Windows 默认 GBK，print 非 ASCII 会直接崩（见 AGENTS.md §6.2）
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

OUT_DIR = os.path.join(REPO, "dist", "feishu", "text")
MAX_CHARS = 1500
DEFAULT_BASE_REF = "origin/main"

# 🔴 patch 模式的 tar 条目前缀 —— **不得**命中 Mac 白名单目录
# （ALLOWED_DIRS = fg_system/ scripts/ tests/ evolution/ docs/，见 scripts/fg_sync_ingest.py:39）
# ⇒ Mac 端不会误当普通文件入库，需人工/新流程 apply。
PATCH_PREFIX = "__patch__/"


#: 🔴 **拒绝外发的目录段**（项目纪律：「`Data/**` 与凭据一律不外发」✗）。
#: 动机（2026-10-20 团队审查 P0）：`pack_many x Data/accounts.csv` 或
#: `pack_many x C:/Users/me/.okx_credentials.json` 原来**都会被打包发往飞书** ✗ ——
#: `_safe_extract` 只在接收端拒绝绝对路径 ✓，拦不住**已发出**的数据 ✗。
#: 🔴 只在**仓库根目录**出现才拒的目录名（2026-10-21 修 ✗）——
#: 不能放进 `DENY_DIR_SEGMENTS` ✗：那样会误伤 `fg_system/data/`（**代码包内的同名子目录** ✓）。
DENY_ROOT_DIRS = ("Data", "data", "logs")

#: 任何位置都拒的目录段 ✓
DENY_DIR_SEGMENTS = (".git", ".venv", "__pycache__", "node_modules")

#: 🔴 文件名里出现这些片段 ⇒ 视为凭据/密钥 ✗
DENY_FILE_FRAGMENTS = ("credential", "credentials", ".pem", ".p12", "id_rsa",
                       "id_ed25519", "token", "secret", ".env", "fred_key")

#: 🔴 精确拒绝的文件名（小写比对）
DENY_FILE_NAMES = (".okx_credentials.json", "fred_key", "feishu_token",
                   "credentials.json")


def _export_errors(srcs):
    """校验待打包文件：**必须在仓库内** ✓、**不在拒绝表** ✓。返回错误列表。

    :returns: 错误字符串列表（空 ⇒ 可打包）。调用方应 `sys.exit` 而非继续 ✓。
    """
    errors = []
    root = os.path.realpath(REPO)
    for rel in srcs:
        real = os.path.realpath(os.path.join(root, rel.replace("/", os.sep)))
        if real != root and not real.startswith(root + os.sep):
            errors.append("%s：**不在仓库内** ✗（realpath=%s）⇒ 拒绝外发" % (rel, real))
            continue
        norm = rel.replace("\\", "/")
        parts = [p for p in norm.split("/") if p]
        # 🔴 **大小写不敏感**比对 ✗ —— Windows/macOS 文件系统大小写不敏感 ✓，
        # `data/features.csv` 与 `Data/features.csv` 是**同一个文件** ✗
        # （2026-10-20 实测：原实现漏掉小写变体 ✓）
        deny_lower = {d.lower() for d in DENY_DIR_SEGMENTS}
        bad_dir = [p for p in parts[:-1] if p.lower() in deny_lower]
        # 🔴 `Data` / `data` / `logs` 只在**根目录**才拒 ✗（否则误伤 `fg_system/data/` ✓）
        if not bad_dir and len(parts) > 1 and parts[0].lower() in {
                d.lower() for d in DENY_ROOT_DIRS}:
            bad_dir = [parts[0]]
        if bad_dir:
            errors.append("%s：命中**拒绝目录** `%s` ✗（`Data/**`、`.git`、`.venv` 一律不外发）"
                          % (rel, bad_dir[0]))
            continue
        low = norm.lower()
        hit = [f for f in DENY_FILE_FRAGMENTS if f in low]
        if hit or (parts and parts[-1].lower() in DENY_FILE_NAMES):
            errors.append("%s：疑似**凭据/密钥** ✗（命中 `%s`）⇒ 拒绝外发"
                          % (rel, (hit or [parts[-1]])[0]))
    return errors


def _base_text(rel, base_ref):
    """读基准内容：git -C <REPO> show <base_ref>:<rel>（失败返回 None）。

    ⚠️ 必须带代理：本仓库是 blob:none 部分克隆，`git show` 会按需拉 blob，
       不带代理走直连 ⇒ **静默挂死**（见 docs/dual-end-workflow.md §C.1 / §2）。
       `FG_PROXY` 非空时用 `-c http.proxy=$FG_PROXY -c https.proxy=$FG_PROXY`。
    ⚠️ 抽成独立函数以便测试猴补（本环境不许跑 git），见 tests/test_pack_many_patch.py。
    """
    cmd = ["git", "-C", REPO]
    proxy = os.environ.get("FG_PROXY", "")
    if proxy:
        cmd += ["-c", "http.proxy=%s" % proxy, "-c", "https.proxy=%s" % proxy]
    cmd += ["show", "%s:%s" % (base_ref, rel)]
    try:
        out = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    # ⚠️ **保留原始行尾** ✓ —— 由 `_patch_payload` 按基准行尾统一两侧 ✓。
    # （2026-10-21 教训 ✗：这里无条件转 LF ✗ ⇒ 对 **CRLF 文件**生成的 diff
    #  上下文是 LF ✗ ⇒ Mac 侧 `git apply` **失败** ✗。要统一就**两侧一起**统一 ✓。）
    return out.stdout.decode("utf-8", "replace")


def _fetch_origin():
    """`--patch` 前先 `git fetch origin` ✓（失败不致命 ✓，只打印）。

    ⚠️ 这只能让基准尽量新 ✓，**不能**防「上一包还在途、origin 尚未推进」✗
    —— 那种漂移只能靠**串行发送**（`docs/dual-end-workflow.md` 教训 **8b** ✓）。
    """
    cmd = ["git", "-C", REPO]
    proxy = os.environ.get("FG_PROXY", "")
    if proxy:
        cmd += ["-c", "http.proxy=%s" % proxy, "-c", "https.proxy=%s" % proxy]
    cmd += ["fetch", "origin"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=180)
        ok = r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        ok = False
    print("[patch] fetch origin：%s" % ("ok ✓" if ok else "失败（沿用旧 ref ✗）"))


def _in_base(rel, base_ref):
    """`<rel>` 是否存在于 `<base_ref>` 的树里（用 `ls-tree` ✓ 不拉 blob ✓）。"""
    cmd = ["git", "-C", REPO]
    proxy = os.environ.get("FG_PROXY", "")
    if proxy:
        cmd += ["-c", "http.proxy=%s" % proxy, "-c", "https.proxy=%s" % proxy]
    cmd += ["ls-tree", "--name-only", base_ref, "--", rel]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return True          # 查不了 ⇒ 保守当作「存在」✓（走回落，不冒险 ✗）
    return bool(out.stdout.strip())


def _git_blob_sha(ref, rel):
    """取 `<ref>:<rel>` 的 blob SHA（7 位）；失败返回 None。"""
    cmd = ["git", "-C", REPO]
    proxy = os.environ.get("FG_PROXY", "")
    if proxy:
        cmd += ["-c", "http.proxy=%s" % proxy, "-c", "https.proxy=%s" % proxy]
    cmd += ["rev-parse", "--short=7", "%s:%s" % (ref, rel)]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.decode("utf-8", "replace").strip() or None


def _git_hash_blob(data):
    """对内存内容算 blob SHA（7 位，**不写入**对象库）；失败返回 None。

    shortcut: 不套 `core.autocrlf` 过滤 ⇒ 换行不一致时 new 侧 SHA 与 git 存的可能不同；
    `--3way` 只用 **old**（preimage）✓，故不影响合并；若要严格一致，改成
    `git hash-object -w --path=<rel> --stdin`。
    """
    try:
        out = subprocess.run(["git", "-C", REPO, "hash-object", "--stdin"],
                             input=data, capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.decode("utf-8", "replace").strip()[:7] or None


def _patch_payload(srcs, base_ref):
    """生成**git 风格**统一 diff。返回 (payload_bytes, 回落原因列表)。

    MT-38（2026-10-19）：加 `diff --git` + `index <old>..<new> <mode>` 行 ✓ ——
    有 `index` 行时 Mac 端才会走 `git apply --3way` ✓，基准漂移可自动三方合并 ✓；
    取不到 blob SHA 时**不回落** ✓，只是退化成无 `index` 行（Mac 端走普通 apply ✓）。

    只要有**任一**回落条件成立 ⇒ 返回 (None, [原因...])，由调用方走整文件路径。
    """
    reasons = []
    chunks = []
    for rel in srcs:
        cur = open(os.path.join(REPO, rel.replace("/", os.sep)),
                   encoding="utf-8", errors="replace").read()
        base = _base_text(rel, base_ref)
        if base is None and not _in_base(rel, base_ref):
            # **新文件**（基准里没有）⇒ 生成 git 的「新增文件」diff ✓
            # 不回落 ✗：新文件本来就无基准 ✓，回落会让整包退化成整文件（片数暴涨 ✗）
            diff = "".join(difflib.unified_diff(
                [], cur.splitlines(True), fromfile="/dev/null", tofile="b/" + rel))
            header = "diff --git a/%s b/%s\nnew file mode 100644\n" % (rel, rel)
            new = _git_hash_blob(cur.encode("utf-8"))
            if new:
                header += "index 0000000..%s\n" % new
            chunks.append(header + diff)
            continue
        if base is None:
            reasons.append("%s：拿不到基准（%s 不存在 / 非 git 仓库 / 无代理）"
                           % (rel, base_ref))
            continue
        # 🔴 **按基准文件的行尾统一两侧** ✓（2026-10-21）：
        # `cur` 是 `open(..., encoding="utf-8")` 读的 ⇒ Python 通用换行 ⇒ **恒为 LF** ✗；
        # 若基准是 CRLF ✗ ⇒ 不统一就会「每行都算改动」✗（`+368/-305` ✗）；
        # 若强行把基准转 LF ✗ ⇒ diff 上下文是 LF ✗ ⇒ 在 CRLF 文件上 apply 失败 ✗。
        # ⇒ 以**基准**为准：基准 CRLF ⇒ 把 cur 也转 CRLF ✓；基准 LF ⇒ 把 base 转 LF ✓。
        if "\r\n" in base:
            base_txt = base
            cur_txt = cur.replace("\r\n", "\n").replace("\n", "\r\n")
            # 🔴 2026-10-29：**纯行尾变更**（内容逐字相同、只有 EOL 不同）✗ ——
            # 上面那步把两边都归一成 CRLF ⇒ diff 变空 ⇒ 文件被**静默跳过** ✗。
            # 实测：8 个 CRLF blob 归一的包，13 个文件只带出 5 个文件块 ✗。
            # ⇒ 此时改用**原始字节**做 diff（要改的就是行尾）✓，
            #   新 blob SHA 也随之取 `cur`（LF）✓ —— 两处口径一致 ✓。
            if cur_txt == base_txt and cur != base:
                base_txt, cur_txt = base, cur
        else:
            base_txt = base.replace("\r\n", "\n")
            cur_txt = cur
        diff = "".join(difflib.unified_diff(
            base_txt.splitlines(True), cur_txt.splitlines(True),
            fromfile="a/" + rel, tofile="b/" + rel))
        if not diff:
            # 无差异：不回落，但也没东西可发 —— 视为空 diff（继续，允许所有文件都空）
            # 🔴 **必须打印** ✗（2026-10-21 实测）：原来只往 payload 塞标记 ✗
            # ⇒ 我传了 7 个文件、实际进包 6 个 ✗，**双方都以为发了** ✗。
            print("[patch] %s  ⚠️ **与基准无差异，已跳过** ✗"
                  "（确认它本该有改动？）" % rel)
            chunks.append("--- %s ---\n（与基准无差异）\n" % rel)
            continue
        header = "diff --git a/%s b/%s\n" % (rel, rel)
        # 🔴 必须对**写进 diff 的那份字节**算 SHA ✗ —— 基准是 CRLF 时 `cur_txt` 已被
        # 转成 CRLF ✓，而 `cur` 是 LF ✗ ⇒ 新 blob SHA 对不上 patch 实际产物 ✗
        # ⇒ Mac 端 `git apply --3way` 判「patch 不适用」（2026-10-28 实测：
        # `sync_1028v` 的 tests/test_feishu_send.py 就是这样被拒 ✗）。
        old, new = _git_blob_sha(base_ref, rel), _git_hash_blob(cur_txt.encode("utf-8"))
        if old and new:
            header += "index %s..%s 100644\n" % (old, new)
        # 🔴 删除行告警（2026-10-19）：本项目 Windows 侧**只追加** ✓ ⇒ 出现删除行通常意味着
        # **本地旧于 origin** ✗（`sync_1019q` 就是这样把 Mac 回写的 ✅ 冲回「待执行」✗）。
        dels = sum(1 for l in diff.splitlines()
                   if l.startswith("-") and not l.startswith("---"))
        adds = sum(1 for l in diff.splitlines()
                   if l.startswith("+") and not l.startswith("+++"))
        print("[patch] %s  +%d/-%d%s"
              % (rel, adds, dels,
                 "  ⚠️ 有删除行 ⇒ 本地可能旧于 origin ✗（任务表请先刷新 ✓）" if dels else ""))
        chunks.append(header + diff)
    if reasons:
        return None, reasons
    return "".join(chunks).encode("utf-8"), []


def _tar_bytes(entries):
    """entries: [(name, data_bytes)] → xz tar 字节（mtime=0，可复现）。"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:xz") as tf:
        for name, data in entries:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("pkg")
    ap.add_argument("srcs", nargs="+")
    ap.add_argument("--no-check", action="store_true",
                    help="跳过「表格强制校验」✗（应急用 ✓，默认**必跑** ✗）")
    ap.add_argument("--patch", action="store_true",
                    help="增量模式：只发统一 diff")
    ap.add_argument("--base-ref", default=DEFAULT_BASE_REF,
                    help="patch 基准 ref（默认 origin/main）")
    args = ap.parse_args()
    pkg = args.pkg
    srcs = args.srcs

    # 校验文件存在（两种模式都要，保持原有报错行为）
    for rel in srcs:
        full = os.path.join(REPO, rel.replace("/", os.sep))
        if not os.path.isfile(full):
            sys.exit("❌ 找不到：%s" % rel)
        # 🔴 **0 字节文件必须拒绝** ✗（2026-10-21 实测）：我的脚本 bug 曾把
        # `docs/windows-tasks.md` 写成 **0 字节** ✗，`pack_many` 只报「整文件回落」
        # 并生成了 **164 字节的空包** ✗ —— 若发出去，对端会把整张表**清空** ✗。
        if os.path.getsize(full) == 0:
            sys.exit("❌ %s **文件为 0 字节** ✗ ⇒ 拒绝打包"
                     "（很可能是脚本把它清空了，先 `git show origin/main:%s` 恢复）"
                     % (rel, rel))

    # 🔴 **外发安全闸门**（2026-10-20 团队审查 P0）：仓库边界 + 数据/凭据拒绝表 ✗
    # 🔴 **表格强制校验闸门** ✗（2026-10-23）：裸 `|` 串格已犯 **7 次** ✗
    # （WT-62/66/67/73/76/78 / MT-51/58 / H-082/085 ✓）—— 每次都是人工写备注漏转义 ✓，
    # 靠 `--check-table` **事后**抓 ✗，而打包前常忘了跑 ✗ ⇒ 「发出去 → 对端自检失败 → 重发」✗。
    # ⇒ 只要包里有 `docs/*.md` 或 `evolution/*.md` ✓，就**强制**校验 ✗，不通过即中止 ✗。
    if not getattr(args, "no_check", False):
        tables = [s for s in srcs
                  if s.startswith(("docs/", "evolution/")) and s.endswith(".md")]
        if tables:
            import subprocess as _sp
            _chk = os.path.join(REPO, "scripts", "verify_hypotheses.py")
            if os.path.exists(_chk):
                print("[check] 包内含表格文件 %d 个 ⇒ 强制校验 ✗" % len(tables))
                _r = _sp.run([sys.executable, _chk, "--check-table"],
                             capture_output=True, timeout=180,
                             env=dict(os.environ, PYTHONIOENCODING="utf-8"))
                _out = (_r.stdout or b"").decode("utf-8", "replace")
                if _r.returncode != 0:
                    for _ln in _out.splitlines():
                        if "❌" in _ln:
                            print("  " + _ln.strip())
                    sys.exit("❌ 表格校验未通过 ✗ ⇒ 拒绝打包"
                             "（裸 `|` 会串格 ✓；修好后重试，应急可加 --no-check ✗）")
                print("[check] ✅ 通过 ✓")
    export_errors = _export_errors(srcs)
    if export_errors:
        for e in export_errors:
            print("  ❌ %s" % e)
        sys.exit("❌ 拒绝打包：以上文件**不得外发** ✗"
                 "（项目纪律：`Data/**` 与凭据一律不外发 ✓）")

    os.makedirs(OUT_DIR, exist_ok=True)

    # 🔴 **清理同名包的旧分片** ✗（2026-10-21 修团队审查 P1 ✓）：
    # 原来只**写**不清理 ✗ ⇒ 包从 12 片缩到 8 片时 ✓，旧 `t009..t012` **残留** ✗
    # ⇒ `send_pkg` 会把它们**一起发出去** ✗ ⇒ 对端收到**上一版内容** ✗（静默错版 ✗）。
    _old = glob.glob(os.path.join(OUT_DIR, "%s-t*.txt" % pkg))
    for _f in _old:
        os.remove(_f)
    if _old:
        print("[pack] 清理同名包旧分片：%d 个 ✓" % len(_old))

    mode = "full"
    fallback_reasons = []

    if args.patch:
        _fetch_origin()
        payload, reasons = _patch_payload(srcs, args.base_ref)
        if payload is not None:
            # 整文件 tar 字节数（用于「diff 是否更小」的比较）
            full_entries = [(rel, open(os.path.join(REPO, rel.replace("/", os.sep)),
                                       "rb").read()) for rel in srcs]
            full_blob = _tar_bytes(full_entries)
            patch_blob = _tar_bytes([(PATCH_PREFIX + pkg + ".diff", payload)])
            if len(patch_blob) >= len(full_blob):
                fallback_reasons.append(
                    "diff 打包 %d 字节 ≥ 整文件 tar %d 字节（不值得）"
                    % (len(patch_blob), len(full_blob)))
            else:
                mode = "patch"
                blob = patch_blob
        if mode == "full":
            if reasons:
                fallback_reasons.extend(reasons)

    if mode == "full":
        entries = [(rel, open(os.path.join(REPO, rel.replace("/", os.sep)),
                              "rb").read()) for rel in srcs]
        blob = _tar_bytes(entries)

    b64 = _b64url(blob)
    pieces = [b64[i:i + MAX_CHARS] for i in range(0, len(b64), MAX_CHARS)]

    for n, piece in enumerate(pieces, 1):
        dst = os.path.join(OUT_DIR, "%s-t%03d.txt" % (pkg, n))
        with open(dst, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("###FG:%s:%d/%d###%s###FG:end###\n" % (pkg, n, len(pieces), piece))

    if args.patch and mode == "full":
        print("⚠️ --patch 已回落为整文件打包：")
        for r in fallback_reasons:
            print("    · %s" % r)

    # ⚠️ 不加 --patch 时，stdout 必须与改动前**逐字节一致** ⇒ 不带「模式」字段。
    if args.patch:
        print("包名 %s：模式 %s：%d 个文件 → %d 字节(xz) → %d 片（每片 ≤%d 字符）"
              % (pkg, mode, len(srcs), len(blob), len(pieces), MAX_CHARS))
    else:
        print("包名 %s：%d 个文件 → %d 字节(xz) → %d 片（每片 ≤%d 字符）"
              % (pkg, len(srcs), len(blob), len(pieces), MAX_CHARS))
    for rel in srcs:
        print("    %s  (%d 字节)"
              % (rel, os.path.getsize(os.path.join(REPO, rel.replace("/", os.sep)))))
    print("下一步：py -3.10 scripts/send_pkg.bat %s" % pkg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
