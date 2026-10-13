# -*- coding: utf-8 -*-
"""D6 守卫：设计文档 §12「风险与已知局限」表**逐行收口**。

【为什么存在】
`docs/2026-10-12-贪恐系统迭代规划v2.0.md` D6 行要求：把
`docs/superpowers/specs/2026-09-21-fear-greed-index-v2-design.md` §12 的
**12 项**风险**逐条给状态或封存理由**，堵住"S3：§12 未闭环风险继续被
误引用 6~12 个月"的窗口。

【验收口径（已按实测改正）】
规划原验收写的是「§12 表每行匹配 `^\\| \\d+ \\|` 且第 3 列非空，且全文
`grep "状态:"` 非零」——但实测：§12 表头是「**# / 风险 / 状态·缓解**」，
全文根本没有 `状态:` 这种带冒号的行 ✗ ⇒ 原口径写不出来。**改正后**：
  (a) §12 表恰好 **12 行**、每行编号 1..12；
  (b) 每行**第 3 列（状态/缓解）非空**；
  (c) 每行第 3 列含显式 **`【D6 收口`** 标记 ⇒ 每行都"新增/明确了
      封存理由或收口状态"，而不是只有一句原始缓解描述。

本测试**从文档文本重新解析**（不钉死任何人工抄写的内容），因此 §12 表若
被改成空列、少行、或漏掉收口标记 ⇒ 立即报红。
"""
import io
import os

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DESIGN = os.path.join(
    REPO, "docs", "superpowers", "specs",
    "2026-09-21-fear-greed-index-v2-design.md")

# 收口标记：每行第 3 列必须带它，证明 D6 对该行给出了封存理由/收口状态。
CLOSURE_MARK = u"【D6 收口"

EXPECTED_ROWS = 12


def _read(path):
    with io.open(path, encoding="utf-8") as fh:
        return fh.read()


def _parse_section12(text):
    """返回 §12 表格的数据行：[(行号, [列...]), ...]，按 `| <数字> |` 判定。"""
    lines = text.split(u"\n")
    try:
        start = next(i for i, ln in enumerate(lines)
                     if ln.startswith(u"## 12"))
    except StopIteration:
        pytest.fail("设计文档找不到 §12 标题（`## 12 ...`）")

    rows = []
    for i in range(start, len(lines)):
        s = lines[i].strip()
        if s.startswith(u"##") and i > start + 3:
            break  # 进入下一节
        if not s.startswith(u"|"):
            continue
        cols = [c.strip() for c in s.strip(u"|").split(u"|")]
        if cols and cols[0].isdigit():
            rows.append((i + 1, cols))
    return rows


def test_parser_smoke_on_injected_text():
    """解析器对注入样例的行为（自证 + 便于离线理解）。"""
    sample = (
        u"## 12. 风险\n\n"
        u"| # | 风险 | 状态/缓解 |\n"
        u"|---|---|---|\n"
        u"| 1 | 甲 | 【D6 收口 2026-10-13】已处置 |\n"
        u"| 2 | 乙 | 缓解描述 |\n\n"
        u"## 13. 别的\n"
    )
    rows = _parse_section12(sample)
    assert [r[1][0] for r in rows] == [u"1", u"2"]
    assert rows[0][1][2].startswith(CLOSURE_MARK)
    assert not rows[1][1][2].startswith(CLOSURE_MARK)


def test_section12_has_exactly_twelve_numbered_rows():
    """§12 表恰好 12 行、编号 1..12 连续（D6 原文：实测 12 项）。"""
    rows = _parse_section12(_read(DESIGN))
    numbers = [int(r[1][0]) for r in rows]
    assert len(rows) == EXPECTED_ROWS, (
        u"§12 表应有 %d 行，实测 %d 行：%s" % (EXPECTED_ROWS, len(rows), numbers))
    assert numbers == list(range(1, EXPECTED_ROWS + 1)), (
        u"§12 表编号不连续：%s" % numbers)


def test_every_row_has_nonempty_third_column():
    """每行第 3 列（状态/缓解）非空 —— 规划改正后的口径 (b)。"""
    rows = _parse_section12(_read(DESIGN))
    empty = [ln for ln, cols in rows if len(cols) < 3 or not cols[2]]
    assert not empty, u"§12 以下行第 3 列为空：%s" % empty


def test_every_row_carries_explicit_closure_mark():
    """每行第 3 列含 `【D6 收口 ...】` —— 口径 (c)，D6 的核心交付。"""
    rows = _parse_section12(_read(DESIGN))
    missing = [ln for ln, cols in rows
               if len(cols) < 3 or CLOSURE_MARK not in cols[2]]
    assert not missing, (
        u"§12 以下行未给出『封存理由/收口状态』（缺 `%s...】`）：%s"
        % (CLOSURE_MARK, missing))


def test_closure_marks_state_are_nonempty_and_not_a_bare_marker():
    """收口标记后面必须真有一句理由/状态，而不是空壳标记（防形式过场）。"""
    rows = _parse_section12(_read(DESIGN))
    bad = []
    for ln, cols in rows:
        col3 = cols[2] if len(cols) > 2 else u""
        idx = col3.find(CLOSURE_MARK)
        if idx < 0:
            continue
        tail = col3[idx + len(CLOSURE_MARK):]
        # 去掉紧随标记的日期/年份与右括号等，剩余应仍有实质文字
        tail = tail.strip()
        for ch in (u"】", u"）", u")"):
            tail = tail.replace(ch, u"")
        if len(tail.strip()) < 4:
            bad.append(ln)
    assert not bad, u"§12 以下行的收口标记后无实质状态/理由：%s" % bad


def test_guard_has_teeth_on_dropped_marker():
    """变异测试：删掉某行的收口标记 ⇒ 守卫必须能发现（证明非恒真断言）。"""
    text = _read(DESIGN)
    rows = _parse_section12(text)
    assert rows, u"未解析到 §12 行 ⇒ 解析器与文档脱节"
    victim_line = rows[0][0]
    lines = text.split(u"\n")
    lines[victim_line - 1] = lines[victim_line - 1].replace(CLOSURE_MARK, u"")
    mutated = u"\n".join(lines)
    mrows = _parse_section12(mutated)
    missing = [ln for ln, cols in mrows
               if len(cols) < 3 or CLOSURE_MARK not in cols[2]]
    assert victim_line in missing, (
        u"删除第 %d 行标记后，守卫应判定该行缺失收口状态" % victim_line)
