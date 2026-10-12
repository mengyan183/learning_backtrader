# -*- coding: utf-8 -*-
"""restore_from_base64 解压的安全校验单测（WT-20）。

`restore_from_base64.py` 原用 `tar.extractall`（无任何路径穿越校验）⇒
恶意 tar 可写任意路径（绝对路径 / `..` / symlink 逃逸）。
现改用 `fg_sync_ingest._safe_extract`。

测试全部用 `tmp_path` 构造 tar，**不碰真实 Data/**、不联网。

【为什么断言的是"行为"而非 import 细节】
`restore_from_base64` 里**不应**存在裸 `extractall` 调用；安全解压必须来自
`fg_sync_ingest._safe_extract`（复用，不另写一套）。
"""

import io
import os
import sys
import tarfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import restore_from_base64
from fg_sync_ingest import _safe_extract


def _tar_bytes(entries):
    """把 `[(TarInfo, bytes|None)]` 打包成 tar 字节流。"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for info, data in entries:
            tf.addfile(info, io.BytesIO(data) if data is not None else None)
    return buf.getvalue()


def _file_info(name, data=b"x"):
    info = tarfile.TarInfo(name)
    info.size = len(data)
    return info, data


def _sym_info(name, target):
    info = tarfile.TarInfo(name)
    info.type = tarfile.SYMTYPE
    info.linkname = target
    return info, None


def _open_tar(path):
    return tarfile.open(path, "r:")


# ── ① 正常包：合法 tar 能正常还原（回归） ────────────────────────────────

def test_normal_package_extracts(tmp_path):
    blob = _tar_bytes([
        _file_info("scripts/hello.py", b"print('hi')\n"),
        _file_info("fg_system/engine.py", b"x = 1\n"),
    ])
    tarpath = tmp_path / "pkg.tar"
    tarpath.write_bytes(blob)

    out = tmp_path / "out"
    out.mkdir()
    with _open_tar(str(tarpath)) as tf:
        members = _safe_extract(tf, str(out))

    assert members == ["scripts/hello.py", "fg_system/engine.py"]
    assert (out / "scripts" / "hello.py").read_text() == "print('hi')\n"
    assert (out / "fg_system" / "engine.py").read_text() == "x = 1\n"


# ── ② 恶意成员被拒：绝对路径 / `..` / symlink 逃逸 ──────────────────────

def test_absolute_path_member_rejected(tmp_path):
    blob = _tar_bytes([_file_info("/tmp/evil.txt", b"evil")])
    tarpath = tmp_path / "evil.tar"
    tarpath.write_bytes(blob)

    out = tmp_path / "out"
    out.mkdir()
    with _open_tar(str(tarpath)) as tf:
        try:
            _safe_extract(tf, str(out))
            raise AssertionError("绝对路径成员应被拒绝")
        except SystemExit:
            pass
    assert not (out / "tmp").exists()


def test_parent_traversal_member_rejected(tmp_path):
    blob = _tar_bytes([_file_info("../escape.txt", b"evil")])
    tarpath = tmp_path / "evil.tar"
    tarpath.write_bytes(blob)

    out = tmp_path / "out"
    out.mkdir()
    with _open_tar(str(tarpath)) as tf:
        try:
            _safe_extract(tf, str(out))
            raise AssertionError("含 .. 的成员应被拒绝")
        except SystemExit:
            pass
    assert not (tmp_path / "escape.txt").exists()


def test_nested_traversal_member_rejected(tmp_path):
    blob = _tar_bytes([_file_info("a/../../escape.txt", b"evil")])
    tarpath = tmp_path / "evil.tar"
    tarpath.write_bytes(blob)

    out = tmp_path / "out"
    out.mkdir()
    with _open_tar(str(tarpath)) as tf:
        try:
            _safe_extract(tf, str(out))
            raise AssertionError("嵌套 .. 的成员应被拒绝")
        except SystemExit:
            pass
    assert not (tmp_path / "escape.txt").exists()


def test_symlink_escape_member_rejected(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("secret\n")

    blob = _tar_bytes([_sym_info("link", str(secret))])
    tarpath = tmp_path / "evil.tar"
    tarpath.write_bytes(blob)

    out = tmp_path / "out"
    out.mkdir()
    with _open_tar(str(tarpath)) as tf:
        try:
            _safe_extract(tf, str(out))
            raise AssertionError("符号链接成员应被拒绝")
        except SystemExit:
            pass
    assert not (out / "link").exists()


# ── ③ restore_from_base64 必须复用安全解压（不得再有裸 extractall） ──────

def test_restore_reuses_safe_extract():
    """确认 restore_from_base64 复用 fg_sync_ingest._safe_extract。"""
    assert getattr(restore_from_base64, "_safe_extract", None) is _safe_extract
