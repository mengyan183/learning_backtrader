# -*- coding: utf-8 -*-
"""R-6：NewsAPI key 的来源（env 优先，文件兜底）。

背景（WT-12 代码审查 R-6）：key 进 URL query string 是 NewsAPI 官方约束
（改不了 header），但**来源**不该只有 `Data/newsapi_key` 一个 —— env 注入
便于临时/CI 运行，且与 `shoutu.load_token` 的既有约定一致（env 优先）。
"""
import importlib.util
import os

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "fetch_news.py")


def _load():
    spec = importlib.util.spec_from_file_location("fetch_news", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fn = _load()


def test_env_takes_precedence(tmp_path, monkeypatch):
    key_file = tmp_path / "newsapi_key"
    key_file.write_text("from-file", encoding="utf-8")
    monkeypatch.setattr(fn, "KEY_FILE", str(key_file))
    monkeypatch.setenv("NEWSAPI_KEY", "from-env")
    assert fn.read_key() == "from-env"


def test_falls_back_to_file(tmp_path, monkeypatch):
    key_file = tmp_path / "newsapi_key"
    key_file.write_text("  from-file\n", encoding="utf-8")
    monkeypatch.setattr(fn, "KEY_FILE", str(key_file))
    monkeypatch.delenv("NEWSAPI_KEY", raising=False)
    assert fn.read_key() == "from-file"


def test_missing_everywhere_exits_with_both_hints(tmp_path, monkeypatch):
    """两处都没有 ⇒ 报错信息必须**同时**给出 env 名与文件路径（否则用户不知道去哪配）。"""
    monkeypatch.setattr(fn, "KEY_FILE", str(tmp_path / "nope_key"))
    monkeypatch.delenv("NEWSAPI_KEY", raising=False)
    with pytest.raises(SystemExit) as exc:
        fn.read_key()
    msg = str(exc.value)
    assert "NEWSAPI_KEY" in msg
    assert "newsapi_key" in msg
