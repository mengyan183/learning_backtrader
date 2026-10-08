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
