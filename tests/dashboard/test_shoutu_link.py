# -*- coding: utf-8 -*-
"""MT-67：看板「跳转守猪待兔」按钮 + 激活码安全（方案A：纯跳转零泄露）。

硬约束：
- 页面源码**绝不出现** SHOUTU_TOKEN / 激活码字面量 ✗；
- 页面源码**不出现** 40+ 位十六进制串（激活码形态）✗；
- 按钮纯跳转 `https://fe.szdt.tech/invest/#/etf`，URL 不带凭证 ✗。
"""
import os
import re

from fg_system.dashboard import server

TPL = os.path.join(os.path.dirname(os.path.dirname(server.__file__)),
                   "dashboard", "templates", "index.html")


def _html():
    return open(TPL, encoding="utf-8").read()


def test_link_points_to_official_etf_page():
    t = _html()
    assert "https://fe.szdt.tech/invest/#/etf" in t
    # 新窗口打开 + 不泄露 referrer / opener ✓
    assert 'target="_blank"' in t
    assert "noopener" in t


def test_no_token_literal_in_page():
    t = _html()
    assert "SHOUTU_TOKEN" not in t
    assert "X-Auth" not in t
    # 激活码变量名 / 注释里也不许出现明文凭证字样
    assert "load_token" not in t


def test_no_long_hex_secret_in_page():
    """40+ 位连续十六进制 = 激活码/密钥形态 ✗，页面源码不得出现 ✓。"""
    t = _html()
    hits = re.findall(r"[0-9a-fA-F]{40,}", t)
    assert not hits, "页面源码出现 40+ 位十六进制串（疑似激活码泄露）✗：%s" % hits[:2]


def test_link_url_carries_no_credential():
    """跳转 URL 本身不得拼 token / auth / key 参数 ✗。"""
    t = _html()
    for m in re.finditer(r'href="([^"]*fe\.szdt\.tech[^"]*)"', t):
        url = m.group(1)
        for kw in ("token", "auth", "key", "code=", "secret"):
            assert kw not in url.lower(), "跳转 URL 携带凭证参数 ✗：%s" % url
