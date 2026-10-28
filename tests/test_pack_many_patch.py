# -*- coding: utf-8 -*-
"""`scripts/pack_many.py` 的 `--patch` 增量模式（2026-10-15）。

【为什么需要】
`docs/trading-discipline.md` 有 336 KB ⇒ 整份发要 118 片（116 片那次真挂在飞书会话上）。
⇒ 只发**统一 diff**。

【测试纪律】
⚠️ **本环境不许跑 git**（见 Task 说明），⇒ 把「读基准」抽成 `_base_text(rel, base_ref)`，
   测试用 `monkeypatch.setattr` 猴补它，**不真联网**。
⚠️ 输出目录重定向到 `tmp_path`，避免污染真的 `dist/feishu/text/`。
"""
import base64
import importlib.util
import io
import os
import sys
import tarfile

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SPEC = os.path.join(_REPO, "scripts", "pack_many.py")


def _load():
    spec = importlib.util.spec_from_file_location("pack_many", _SPEC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pm = _load()


# ---------------------------------------------------------------- 工具函数

def _run(monkeypatch, out_dir, argv):
    """以给定 argv 调用 main()，输出目录重定向到 out_dir；返回 (rc, stdout)。"""
    import contextlib
    monkeypatch.setattr(pm, "OUT_DIR", str(out_dir))
    monkeypatch.setattr(pm, "_fetch_origin", lambda: None)  # 测试不跑真 fetch ✓
    monkeypatch.setattr(sys, "argv", ["pack_many.py"] + argv)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = pm.main()
    return rc, buf.getvalue()


def _pieces(out_dir, pkg):
    """读回分片正文（去掉 ###FG 标记）。"""
    out = []
    n = 1
    while True:
        p = os.path.join(str(out_dir), "%s-t%03d.txt" % (pkg, n))
        if not os.path.exists(p):
            break
        txt = open(p, encoding="utf-8").read().strip()
        out.append(txt.split("###", 3)[2])
        n += 1
    return out


def _joined_b64(out_dir, pkg):
    return "".join(_pieces(out_dir, pkg))


def _untar(b64):
    raw = base64.b64decode(b64.replace("-", "+").replace("_", "/"))
    tf = tarfile.open(fileobj=io.BytesIO(raw), mode="r:xz")
    return {m.name: tf.extractfile(m).read() for m in tf.getmembers()}


# ---------------------------------------------------------------- fixture

@pytest.fixture
def repo_file():
    """在仓库里造一个临时文件（相对路径），测试后删除。"""
    created = []

    def _make(rel, text):
        path = os.path.join(_REPO, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        created.append(path)
        return rel

    yield _make

    for p in created:
        if os.path.exists(p):
            os.remove(p)


# ---------------------------------------------------------------- 1) 回归（最重要）

def test_no_patch_is_byte_identical_to_tar_path(monkeypatch, tmp_path, repo_file):
    """🔴 回归：**不加** `--patch` 时，产出的分片 == 走 tar 路径的期望值（逐字节）。"""
    rel = repo_file("dist/_tmp_packmany_regress.txt", "line1\nline2\nline3\n")
    rc, _ = _run(monkeypatch, tmp_path, ["regress1", rel])
    assert rc == 0

    # 期望值：用 pack_many 自身现有的 tar 流程构造（pack_one._b64url + tarfile w:xz）
    data = open(os.path.join(_REPO, rel.replace("/", os.sep)), "rb").read()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:xz") as tf:
        info = tarfile.TarInfo(rel)
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    want_b64 = pm._b64url(buf.getvalue())

    assert _joined_b64(tmp_path, "regress1") == want_b64
    assert _untar(_joined_b64(tmp_path, "regress1"))[rel] == data


def test_no_patch_stdout_has_no_mode_field(monkeypatch, tmp_path, repo_file):
    """回归：不加 --patch 的 stdout 首行格式与改动前一致（无「模式」字段）。"""
    rel = repo_file("dist/_tmp_packmany_stdout.txt", "x\n")
    _, out = _run(monkeypatch, tmp_path, ["regress2", rel])
    first = out.splitlines()[0]
    assert "模式" not in first
    assert first.startswith("包名 regress2：1 个文件 → ")


# ---------------------------------------------------------------- 2) patch 成功

def test_patch_uses_base_and_is_far_smaller(monkeypatch, tmp_path, repo_file):
    """--patch + 能拿到基准 ⇒ 产出统一 diff 文本，且片数**显著少于**整文件模式。"""
    # 造一个大文件：基准里只有一行不同（模拟 trading-discipline.md 改一行）。
    # ⚠️ 内容必须**不可被 xz 轻易压缩**，否则整文件模式下片数也很少、看不出对比 ⇒
    #    用每行都不同的伪随机串。
    import hashlib
    body = "\n".join(
        "第 %d 行：%s" % (i, hashlib.md5(str(i).encode()).hexdigest())
        for i in range(4000)) + "\n"
    rel_changed = repo_file("dist/_tmp_packmany_big.md", body + "新加的一行\n")

    def fake_base(r, ref):
        if r == rel_changed:
            return body          # 基准 = 缺最后一行
        return None

    monkeypatch.setattr(pm, "_base_text", fake_base)

    # full
    rc, _ = _run(monkeypatch, tmp_path, ["fullpkg", rel_changed])
    assert rc == 0
    full_pieces = _pieces(tmp_path, "fullpkg")

    # patch
    rc, out = _run(monkeypatch, tmp_path,
                   ["patchpkg", "--patch", rel_changed])
    assert rc == 0
    assert "模式 patch" in out
    patch_pieces = _pieces(tmp_path, "patchpkg")

    # 片数显著更少
    assert len(patch_pieces) < len(full_pieces)
    assert len(patch_pieces) <= 3                   # 个位数，远小于整文件
    assert len(patch_pieces) * 4 < len(full_pieces)  # 「显著」量化

    # 内容真是统一 diff，且落在 __patch__/ 前缀（不进白名单）
    files = _untar(_joined_b64(tmp_path, "patchpkg"))
    assert list(files) == [pm.PATCH_PREFIX + "patchpkg.diff"]
    diff = files[pm.PATCH_PREFIX + "patchpkg.diff"].decode("utf-8")
    assert "+新加的一行" in diff
    assert "@@" in diff
    # MT-38：改成 git 风格（`diff --git` + `--- a/` / `+++ b/`）⇒ 可被 `git apply` 识别 ✓
    assert diff.startswith("diff --git a/%s b/%s\n" % (rel_changed, rel_changed))
    assert "\n--- a/%s\n+++ b/%s\n" % (rel_changed, rel_changed) in diff


def test_patch_has_index_line_for_real_repo_file(monkeypatch, tmp_path):
    """能取到 blob SHA 时必须带 `index <old>..<new> 100644` 行 ✓
    —— Mac 端据此走 `git apply --3way`（MT-38 ✓）。"""
    rel = "AGENTS.md"
    # 改一行再打 patch（先备份，避免污染工作区）
    path = os.path.join(pm.REPO, rel)
    original = open(path, "rb").read()
    try:
        open(path, "wb").write(
            original + "\n<!-- packmany index 行测试 -->\n".encode("utf-8"))
        payload, reasons = pm._patch_payload([rel], "origin/main")
        assert reasons == []
        diff = payload.decode("utf-8")
        lines = diff.splitlines()
        assert lines[0] == "diff --git a/%s b/%s" % (rel, rel)
        assert lines[1].startswith("index ") and lines[1].endswith(" 100644")
        assert ".." in lines[1]
        # git 只认这个位置：index 必须在 diff --git 之后、--- 之前
        assert lines[2] == "--- a/%s" % rel
        assert lines[3] == "+++ b/%s" % rel
    finally:
        open(path, "wb").write(original)


def test_patch_index_new_sha_matches_crlf_payload(monkeypatch, repo_file):
    """🔴 回归（2026-10-28）：基准是 **CRLF** 时，`index` 的新 blob SHA 必须按
    **写进 diff 的那份字节（CRLF）** 算 ✓。

    原来按工作区的 LF 内容算 ✗ ⇒ 与 patch 实际产物不一致 ✗
    ⇒ Mac 端 `git apply --3way` 判「patch 不适用」✗
    （`sync_1028v` 的 `tests/test_feishu_send.py` 实测被拒 ✗）。
    """
    import subprocess
    rel = repo_file("dist/_tmp_packmany_crlf.py", "a = 1\nb = 3\n")
    monkeypatch.setattr(pm, "_base_text", lambda r, ref: "a = 1\r\nb = 2\r\n")
    monkeypatch.setattr(pm, "_in_base", lambda r, ref: True)
    monkeypatch.setattr(pm, "_git_blob_sha", lambda ref, r: "aaaaaaa")
    payload, reasons = pm._patch_payload([rel], "origin/main")
    assert reasons == []
    head = [l for l in payload.split(b"\n") if l.startswith(b"index ")][0]
    new_sha = head.split(b"..")[1].split(b" ")[0].decode()
    # patch 实际产物 = 基准行尾（CRLF）+ 工作区内容
    want = subprocess.run(["git", "-C", pm.REPO, "hash-object", "--stdin"],
                          input=b"a = 1\r\nb = 3\r\n",
                          capture_output=True).stdout.decode().strip()[:7]
    assert new_sha == want, \
        "index 的新 blob SHA 必须等于 patch 应用后的产物 ✗（否则 Mac 端 --3way 必失败）"


# ---------------------------------------------------------------- 3) 基准不存在 → 回落

def test_patch_falls_back_when_base_missing(monkeypatch, tmp_path, repo_file, capsys):
    """--patch 但拿不到基准（不存在的 ref）⇒ 回落整文件，且 stdout 说明原因。"""
    rel = repo_file("dist/_tmp_packmany_fallback.txt", "hello\n")
    monkeypatch.setattr(pm, "_base_text", lambda r, ref: None)  # 模拟 ref 不存在
    monkeypatch.setattr(pm, "_in_base", lambda r, ref: True)    # 文件在基准里、只是读不到

    rc, out = _run(monkeypatch, tmp_path,
                   ["fbpkg", "--patch", "--base-ref", "origin/nope", rel])
    assert rc == 0
    assert "回落" in out                       # 明确打印回落
    assert "拿不到基准" in out
    assert "origin/nope" in out                 # 带上失败原因细节

    # 仍是整文件 tar（条目名就是原相对路径，不是 __patch__/）
    files = _untar(_joined_b64(tmp_path, "fbpkg"))
    assert files == {rel: b"hello\n"}


# ------------------------------------------------- 4) 新增文件 → 走「新增文件 diff」（不回落）

def test_patch_new_file_in_mixed_package(monkeypatch, tmp_path, repo_file):
    """改一个文件 + 加一个文件 ⇒ **都是 patch**（新文件用 `new file mode` ✓），不回落 ✗。

    2026-10-19 修：原来「基准里没有 ⇒ 回落整文件」✗ ⇒ 只要带一个新文件，
    整包就退化成整文件（实测 40 片 ✗）⇒ 改为生成 git 的 `--- /dev/null` 形式 ✓。
    """
    rel_new = repo_file("dist/_tmp_packmany_new.txt", "brand new\n")
    rel_old = repo_file("dist/_tmp_packmany_old.txt", "old base\n")

    def fake_base(r, ref):
        if r == rel_old:
            return "old base（旧）\n"      # 与工作区内容不同 ⇒ 有真实 hunk ✓
        return None          # 新增文件：基准里没有

    monkeypatch.setattr(pm, "_base_text", fake_base)
    monkeypatch.setattr(pm, "_in_base", lambda r, ref: r == rel_old)

    # 直接断言 payload（不走 main：小文件会被「diff 是否更小」闸门回落 ✗，与本测无关 ✓）
    payload, reasons = pm._patch_payload([rel_old, rel_new], "origin/main")
    assert reasons == []
    diff = payload.decode("utf-8")
    assert "new file mode 100644" in diff
    assert "--- /dev/null" in diff and "+++ b/%s" % rel_new in diff
    assert "+brand new" in diff
    assert "--- a/%s" % rel_old in diff      # 改动的文件仍是普通 hunk ✓


# ---------------------------------------------------------------- 5) 回落时不得静默

def test_fallback_never_silent(monkeypatch, tmp_path, repo_file, capsys):
    """硬约束②：回落**绝不静默** —— 必须打印原因（此处断言 markers 齐全）。"""
    rel = repo_file("dist/_tmp_packmany_silent.txt", "z\n")
    monkeypatch.setattr(pm, "_base_text", lambda r, ref: None)
    # 文件**存在于基准**却拿不到内容 ⇒ 才是真故障 ✓（新文件走「新增文件 diff」✓，不回落 ✗）
    monkeypatch.setattr(pm, "_in_base", lambda r, ref: True)
    _, out = _run(monkeypatch, tmp_path, ["silentpkg", "--patch", rel])
    assert "⚠️" in out and "已回落为整文件打包" in out


def test_patch_new_file_uses_dev_null(tmp_path, repo_file):
    """基准里没有的文件 ⇒ 生成 `new file mode` + `--- /dev/null` ✓，且**不回落** ✗。"""
    rel = repo_file("dist/_tmp_packmany_new.md", "新文件第一行\n第二行\n")
    payload, reasons = pm._patch_payload([rel], "origin/main")
    assert reasons == []
    diff = payload.decode("utf-8")
    assert diff.startswith("diff --git a/%s b/%s\nnew file mode 100644\n"
                           % (rel, rel))
    assert "\n--- /dev/null\n+++ b/%s\n" % rel in diff
    assert "+新文件第一行" in diff


# ------------------- 6) `+N/-M` 统计 + 「删除行」告警（2026-10-19，护栏）

def test_patch_prints_add_del_counts(monkeypatch, capsys, repo_file):
    """护栏①：`--patch` 必须逐文件打印 `+N/-M`（打包前可核对本地是否旧于 origin）。

    纯追加时**不得**出现删除告警 —— 否则变成狼来了，真告警会被忽略。
    """
    rel = repo_file("dist/_tmp_packmany_counts.txt", "a\nb\nc\n")
    monkeypatch.setattr(pm, "_base_text", lambda r, ref: "a\nb\n")  # 基准缺最后一行

    payload, reasons = pm._patch_payload([rel], "origin/main")
    assert reasons == []
    out = capsys.readouterr().out
    assert "[patch] %s" % rel in out
    assert "+1/-0" in out
    assert "有删除行" not in out


def test_patch_warns_on_deleted_lines(monkeypatch, capsys, repo_file):
    """护栏②：diff 出现删除行 ⇒ 告警「本地可能旧于 origin」。

    `sync_1019q` 就是这样把 Mac 回写的 MT-39 ✅ **静默**冲回「待执行」
    （整文件包连 patch 失败那种响声都没有）⇒ 打包端必须能在本地先看到删除行。
    """
    rel = repo_file("dist/_tmp_packmany_del.txt", "keep\n")
    monkeypatch.setattr(pm, "_base_text", lambda r, ref: "keep\nremoved-line\n")

    payload, reasons = pm._patch_payload([rel], "origin/main")
    assert reasons == []
    assert "-removed-line" in payload.decode("utf-8")
    out = capsys.readouterr().out
    assert "[patch] %s" % rel in out
    assert "+0/-1" in out
    assert "有删除行" in out
    assert "本地可能旧于 origin" in out

# ------------------------------------------------ 5) CRLF 文件（2026-10-21 修）
def test_patch_crlf_file_diff_is_small_and_crlf(tmp_path, monkeypatch):
    """基准是 **CRLF** ⇒ diff 必须（a）**只含真实改动** ✓、（b）上下文是 **CRLF** ✓。

    2026-10-21 实测 ✗：`scripts/feishu_send.py` 只加 63 行，却出现两种错法 ——
    ① 两侧行尾不同 ⇒ `+368/-305`（整文件 ✗）；
    ② 强行把基准转 LF ⇒ diff 上下文是 LF ✗ ⇒ Mac 侧 `git apply` **失败** ✗
       （实际报「patch 应用失败 → scripts/feishu_send.py」✗）。
    ⇒ 正解：**以基准行尾为准**统一两侧 ✓。
    """
    rel = "scripts/_tmp_crlf_probe.py"
    d = tmp_path / "scripts"
    d.mkdir()
    # 工作区文件：LF（等价于 `open(..., encoding="utf-8")` 通用换行的结果 ✓）
    (d / "_tmp_crlf_probe.py").write_bytes(b"line1\nline2\nline2b\nline3\n")

    monkeypatch.setattr(pm, "REPO", str(tmp_path))
    monkeypatch.setattr(pm, "_base_text",
                        lambda r, ref: "line1\r\nline2\r\nline3\r\n")   # 基准：CRLF
    monkeypatch.setattr(pm, "_in_base", lambda r, ref: True)
    monkeypatch.setattr(pm, "_git_blob_sha", lambda ref, r: "aaaaaaa")
    monkeypatch.setattr(pm, "_git_hash_blob", lambda data: "bbbbbbb")

    payload, reasons = pm._patch_payload([rel], "origin/main")
    assert reasons == []
    diff = payload.decode("utf-8")
    adds = sum(1 for l in diff.splitlines()
               if l.startswith("+") and not l.startswith("+++"))
    dels = sum(1 for l in diff.splitlines()
               if l.startswith("-") and not l.startswith("---"))
    # 只插了 1 行 ⇒ +1/-0 ✓（若两侧行尾不一致会是 +4/-3 = 整文件 ✗）
    assert adds + dels <= 2, "diff 应只含真实改动，实际 +%d/-%d" % (adds, dels)
    assert adds >= 1
    # 上下文必须带 CRLF ✓（否则在 CRLF 文件上 apply 失败 ✗）
    assert "\r\n" in diff

# --------------------------------- 6) 无差异文件必须告警（2026-10-21 ✗）
def test_patch_warns_on_unchanged_file(monkeypatch, tmp_path, repo_file, capsys):
    """🔴 文件**与基准无差异**时必须**打印告警** ✗ —— 否则会静默漏发 ✗。

    2026-10-21 实测 ✗：`sync_1021k` 我传了 7 个文件，`docs/mac-tasks.md` 因刷新后
    忘了加回改动 ⇒ 无差异 ⇒ **只往 payload 塞标记、不打印** ✗ ⇒ 我以为发了 ✓
    ⇒ 实际只进包 6 个 ✗ ⇒ Mac 收不到 `MT-53` ✗。
    """
    rel = repo_file("dist/_tmp_packmany_same.md", "same content\n")
    monkeypatch.setattr(pm, "_base_text", lambda r, ref: "same content\n")
    monkeypatch.setattr(pm, "_in_base", lambda r, ref: True)

    pm._patch_payload([rel], "origin/main")
    out = capsys.readouterr().out
    assert "与基准无差异" in out and "已跳过" in out
