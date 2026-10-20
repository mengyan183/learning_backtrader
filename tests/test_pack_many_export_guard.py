# -*- coding: utf-8 -*-
"""`pack_many._export_errors()` —— **外发安全闸门**（2026-10-20 团队审查 P0）。

背景：`pack_many x Data/accounts.csv` 或 `pack_many x ~/.okx_credentials.json`
原来**都会被打包发往飞书** ✗ —— `_safe_extract` 只在**接收端**拒绝绝对路径 ✓，
拦不住**已发出**的数据 ✗。项目纪律：「`Data/**` 与凭据一律不外发」✗。
"""
import importlib.util
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "pack_many.py")


def _load():
    spec = importlib.util.spec_from_file_location("pack_many", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pm = _load()


def test_normal_files_pass():
    """普通文档/代码 ⇒ 不报错 ✓。"""
    assert pm._export_errors(["AGENTS.md", "scripts/pack_many.py"]) == []


def test_data_dir_is_rejected():
    """`Data/**` ⇒ 必须拒绝 ✗（这是本项目最硬的一条纪律 ✓）。"""
    for rel in ("Data/accounts.csv", "Data/raw/prices.csv",
                "Data/features.csv", "data/features.csv"):
        errs = pm._export_errors([rel])
        assert errs, "%s 应被拒绝" % rel
        assert "拒绝目录" in errs[0] or "拒绝" in errs[0]


def test_credential_like_files_are_rejected():
    """凭据/密钥类 ⇒ 必须拒绝 ✗。"""
    for rel in (".okx_credentials.json", "scripts/feishu_token.txt",
                "deploy/id_rsa", "certs/server.pem", ".env"):
        assert pm._export_errors([rel]), "%s 应被拒绝" % rel


def test_path_outside_repo_is_rejected():
    """仓库外路径 ⇒ 必须拒绝 ✗（`..` 穿越也算 ✓）。"""
    for rel in ("../outside.txt", "../../etc/passwd",
                "C:/Users/me/secret.txt"):
        assert pm._export_errors([rel]), "%s 应被拒绝" % rel


def test_mixed_list_reports_only_bad_ones():
    """混合列表 ⇒ 只报违规项 ✓（不误伤正常文件 ✓）。"""
    errs = pm._export_errors(["AGENTS.md", "Data/accounts.csv"])
    assert len(errs) == 1
    assert "Data/accounts.csv" in errs[0]
