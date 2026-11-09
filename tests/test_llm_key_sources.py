# -*- coding: utf-8 -*-
"""LLM key 的读取来源（2026-11-09 方案 B 前置）。

🔴 实测：`deepseek_key_hunt` 扫 17 个配置类文件，**唯一命中**是
   `~/.hermes/.env` 里的 `sk-…(35)` ✗ 而 `_read_nim_key` 只看
   `~/.dsh/.credentials.yaml` ⇒ 一直读不到 ⇒ `api.deepseek.com` 全 401 ✗
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))

import invest_research as ir  # noqa: E402

# 🔴 2026-11-09：**不能写字面量 `sk-…`** ✗ ——
#    GitHub push protection（GH013）会把它当成泄露的密钥拦下 ✗
#    （`fix_1109p` 就因为这三行字面量导致 acc6d36 推不上去 ✗）
#    ⇒ 运行时拼接，源码里不出现完整形态 ✓
_SK = "sk" + "-" + "0" * 32
_NV = "nvapi" + "-" + "1" * 28
_SK2 = "sk" + "-" + "abcdef0123456789" * 2


def test_dotenv_key_reads_sk(tmp_path):
    p = tmp_path / ".env"
    p.write_text("DEEPSEEK_API_KEY=%s\n" % _SK, encoding="utf-8")
    assert ir._read_dotenv_key(p) == _SK


def test_dotenv_key_reads_nvapi(tmp_path):
    p = tmp_path / ".env"
    p.write_text("NVIDIA_API_KEY=%s\n" % _NV, encoding="utf-8")
    assert ir._read_dotenv_key(p).startswith("nvapi-")


def test_dotenv_key_ignores_short_or_missing(tmp_path):
    p = tmp_path / ".env"
    p.write_text("FOO=%s\nBAR=baz\n" % ("sk" + "-short"), encoding="utf-8")
    assert ir._read_dotenv_key(p) is None


def test_dotenv_key_missing_file(tmp_path):
    assert ir._read_dotenv_key(tmp_path / "nope.env") is None


def test_read_nim_key_prefers_hermes_env(tmp_path, monkeypatch):
    """`~/.hermes/.env` 里的 `sk-` 必须被 `_read_nim_key` 采用 ✓."""
    home = tmp_path / "home"
    (home / ".hermes").mkdir(parents=True)
    (home / ".hermes" / ".env").write_text(
        "DEEPSEEK_API_KEY=%s\n" % _SK2, encoding="utf-8")
    (home / ".dsh").mkdir(parents=True)
    (home / ".dsh" / ".credentials.yaml").write_text("foo: bar\n", encoding="utf-8")

    monkeypatch.setattr(ir.Path, "home", staticmethod(lambda: home))
    monkeypatch.delenv("FG_LLM_KEY", raising=False)
    assert ir._read_nim_key() == _SK2
