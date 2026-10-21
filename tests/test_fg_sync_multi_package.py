# -*- coding: utf-8 -*-
"""MT-55：单消息多包必须全部入库，不得只处理最后一个。

Bug（2026-10-21 盘点）：fg_sync_ingest main() 里
    for name, parts in groups.items():
        ...
        members = _safe_extract(tf, tmp)   # ← 每次覆盖，不是 extend
⇒ 单消息多包时只剩最后一个包的文件，前面的包被丢弃，
   而脚本仍打印 ✅ pytest 通过（假成功）。
"""
import importlib.util
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "fg_sync_ingest.py")


def _load():
    spec = importlib.util.spec_from_file_location("fg_ingest_mt55", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_extract_marked_returns_multiple_packages():
    """extract_marked 必须从单条消息里认出所有包（不是只取最后一个）。"""
    import sys
    sys.path.insert(0, os.path.join(REPO, "scripts"))
    from restore_from_base64 import extract_marked
    # 两个包各 1 片（body 是任意 base64 字符，不必真能解码——这里只测分组）
    text = (
        "###FG:sync_A:1/1###QUJD###FG:end###\n"
        "###FG:sync_B:1/1###REVG###FG:end###"
    )
    groups, problems = extract_marked(text)
    assert set(groups.keys()) == {"sync_A", "sync_B"}, \
        "两个包都应被认出，实际：%s" % list(groups.keys())
    assert groups["sync_A"] == ["QUJD"]
    assert groups["sync_B"] == ["REVG"]


def test_ingest_accumulates_members_across_packages():
    """fg_sync_ingest main() 的循环必须 members.extend() 而非 =。

    通过源码检查锁住这个行为，防止回归。
    """
    src = open(SCRIPT, encoding="utf-8").read()
    # 关键修复行：循环内必须是 members.extend(...)，不能是 members = ...
    assert "members.extend(_safe_extract" in src, \
        "必须用 members.extend() 累加多包文件，不得 members = ... 覆盖"
    # 同时确保 members 在循环外初始化为 []
    assert "members = []" in src
