# -*- coding: utf-8 -*-
"""MT-04 守卫：A3c 尝试台账（attempts-ledger.jsonl）追加与幂等。"""
import json
import os

import pytest

from fg_system import attempts

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def ledger(tmp_path):
    return os.path.join(str(tmp_path), "attempts-ledger.jsonl")


def _rows(path):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def test_append_increases_row_count_and_fields(ledger):
    """给定固定调用 ⇒ 台账行数 +1 且新行字段齐全。"""
    assert attempts.append_attempt("factor_screen", "F-007", "ok",
                                   ledger=ledger, git_sha="abc123") is True
    rows = _rows(ledger)
    assert len(rows) == 1
    rec = rows[0]
    assert set(rec) == {"ts", "kind", "key", "verdict", "git_sha"}
    assert rec["kind"] == "factor_screen"
    assert rec["key"] == "F-007"
    assert rec["verdict"] == "ok"
    assert rec["git_sha"] == "abc123"


def test_idempotent_same_commit_not_duplicated(ledger):
    """幂等键 = git_sha+kind+key：同一提交重复调用不虚增。"""
    attempts.append_attempt("variant", "V-H7", "ok",
                            ledger=ledger, git_sha="abc123")
    attempts.append_attempt("variant", "V-H7", "ok",
                            ledger=ledger, git_sha="abc123")
    attempts.append_attempt("variant", "V-H7", "worse",
                            ledger=ledger, git_sha="abc123")  # 同键不同 verdict 也跳过
    assert len(_rows(ledger)) == 1


def test_different_commit_or_key_appended(ledger):
    """不同 commit 或不同 key ⇒ 各记一条（真实的新尝试）。"""
    attempts.append_attempt("hypothesis", "H-030", "pending",
                            ledger=ledger, git_sha="aaa")
    attempts.append_attempt("hypothesis", "H-030", "pending",
                            ledger=ledger, git_sha="bbb")
    attempts.append_attempt("hypothesis", "H-031", "pending",
                            ledger=ledger, git_sha="aaa")
    assert len(_rows(ledger)) == 3


def test_count_attempts_kind_filter(ledger):
    attempts.append_attempt("factor_screen", "F-001", "reported",
                            ledger=ledger, git_sha="a")
    attempts.append_attempt("variant", "V-X", "ok",
                            ledger=ledger, git_sha="a")
    assert attempts.count_attempts(ledger) == 2
    assert attempts.count_attempts(ledger, kind="variant") == 1


def test_invalid_kind_rejected(ledger):
    with pytest.raises(AssertionError):
        attempts.append_attempt("bogus", "K", "v", ledger=ledger)
