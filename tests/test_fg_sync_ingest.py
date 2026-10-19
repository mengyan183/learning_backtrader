# -*- coding: utf-8 -*-
"""fg_sync_ingest 白名单 / 冲突 / 安全解压逻辑单测（不联网、不改仓库）。"""

import io
import os
import sys
import tarfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from fg_sync_ingest import _allowed, _safe_extract


def test_whitelist_accepts_code_dirs():
    for p in ["fg_system/factors/symbol.py", "scripts/fetch_news.py",
              "tests/test_index.py", "evolution/hypotheses.md",
              "docs/roadmap.md", "AGENTS.md", "pyproject.toml"]:
        assert _allowed(p), p


def test_whitelist_rejects_data_git_and_secrets():
    for p in ["Data/newsapi_key", "Data/features.csv", "Data/raw/sentiment.csv",
              ".git/config", ".venv/bin/python", "fg_system/__pycache__/x.pyc",
              "scripts/foo.key", "scripts/.env", "docs/secret.token",
              "../evil.sh", "/etc/passwd", "a/../../b"]:
        assert not _allowed(p), p


def test_safe_extract_rejects_traversal():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        info = tarfile.TarInfo("../escape.txt")
        data = b"evil"
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    buf.seek(0)
    with tarfile.open(fileobj=buf, mode="r:") as tf:
        try:
            _safe_extract(tf, "/tmp/fg-sync-test-out")
            raise AssertionError("应拒绝穿越路径")
        except SystemExit:
            pass


def test_safe_extract_accepts_flat_files(tmp_path):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        info = tarfile.TarInfo("scripts/hello.py")
        data = b"print('hi')\n"
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    buf.seek(0)
    with tarfile.open(fileobj=buf, mode="r:") as tf:
        out = _safe_extract(tf, str(tmp_path))
    assert out == ["scripts/hello.py"]
    assert (tmp_path / "scripts" / "hello.py").read_text() == "print('hi')\n"


# ===== MT-38：patch 带 index 行 ⇒ git apply --3way 三方合并 =====

import subprocess

from fg_sync_ingest import _has_index_line, _to_git_patch

_INDEX = "index 1a2b3c4d..5e6f7a8b 100644"


def _blk(index_line=None):
    blk = ["--- docs/x.md@origin/main", "+++ docs/x.md"]
    if index_line:
        blk.append(index_line)
    blk += ["@@ -1,3 +1,3 @@", " l1", "-l2", "+L2", " l3"]
    return blk


def test_has_index_line_detects_index_header():
    """带 index 行 ⇒ 可三方合并；不带 ⇒ 退化为普通 apply。"""
    assert _has_index_line(
        "diff --git a/x b/x\n%s\n--- a/x\n+++ b/x\n" % _INDEX)
    assert not _has_index_line(
        "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n")


def test_to_git_patch_places_index_line_before_file_headers():
    """index 行必须落在 `diff --git` 之后、`---` 之前，git 才认（MT-38）。"""
    lines = _to_git_patch("docs/x.md", _blk(_INDEX)).splitlines()
    assert lines[0] == "diff --git a/docs/x.md b/docs/x.md"
    assert lines[1] == _INDEX
    assert lines[2] == "--- a/docs/x.md"
    assert lines[3] == "+++ b/docs/x.md"
    assert lines[4].startswith("@@")


def test_to_git_patch_without_index_keeps_plain_shape():
    """不引入 index 行时，输出结构与 MT-20 保持一致（向后兼容）。"""
    lines = _to_git_patch("docs/x.md", _blk()).splitlines()
    assert lines[0] == "diff --git a/docs/x.md b/docs/x.md"
    assert lines[1] == "--- a/docs/x.md"
    assert lines[2] == "+++ b/docs/x.md"
    assert not _has_index_line("\n".join(lines))


def test_3way_merges_when_base_drifted(tmp_path):
    """复刻 sync_1019e：patch 基于旧版，目标已被推进且改进已落地 ⇒ --3way 合上。

    base  : l1/l2/l3
    patch : 把 l2 → L2（基于 base 生成，带 index 行）
    当前  : l1/L2/l3（别人已做掉同一处改动）
    普通 apply 因上下文 l2 不存在而失败；--3way 用 blob 三方合并后应成功。
    """
    repo = tmp_path / "repo"
    repo.mkdir()

    def g(*args, **kw):
        return subprocess.run(["git", "-C", str(repo), *args],
                              capture_output=True, text=True, **kw)

    g("init", "-q")
    g("config", "user.email", "t@example.com")
    g("config", "user.name", "t")
    target = repo / "a.txt"
    target.write_text("l1\nl2\nl3\n")
    g("add", "a.txt")
    g("commit", "-q", "-m", "base")
    old_blob = g("hash-object", "a.txt").stdout.strip()
    # 当前版本：同一处已被改掉（模拟 1019d 先落地了 MT-36 的分隔符改动）
    target.write_text("l1\nL2\nl3\n")
    g("add", "a.txt")
    g("commit", "-q", "-m", "advance")
    new_blob = g("hash-object", "a.txt").stdout.strip()

    patch = ("diff --git a/a.txt b/a.txt\n"
             "index %s..%s 100644\n"
             "--- a/a.txt\n"
             "+++ b/a.txt\n"
             "@@ -1,3 +1,3 @@\n"
             " l1\n"
             "-l2\n"
             "+L2\n"
             " l3\n" % (old_blob, new_blob))

    assert _has_index_line(patch)
    plain = g("apply", "--whitespace=nowarn", "-", input=patch)
    assert plain.returncode != 0, "普通 apply 预期失败（基准漂移）"

    three = g("apply", "--3way", "--whitespace=nowarn", "-", input=patch)
    assert three.returncode == 0, three.stderr
    assert target.read_text() == "l1\nL2\nl3\n"
