# -*- coding: utf-8 -*-
"""D7 守卫：walk-forward 判定**必须从报告文本解析**，不得钉死人工抄的数字。

【为什么存在】
`docs/2026-10-12-贪恐系统迭代规划v2.0.md` D7 行给「防御降仓 OOS 不划算」
这条既有结论补量化依据（劣化窗占比）。该结论散落在两处文档：
  - `docs/blocked-registry.md`（C-5 行）
  - `docs/roadmap.md`（阶段 2️⃣）
旧表述只有定性文字、**无窗数**；补写后必须与机器可读源
（`evolution/walkforward-report.md`）**保持一致**，否则格式/口径漂移时无人报警。

【纪律】
- **不得**在测试里把 21/28、20/28 之类人工抄来的数字写死 ✗ —— 那只会在格式
  微调时误报，或把错数字焊死。
- 本测试的做法：**从报告文本重新解析**（`### <变体>` 段内逐行 tag 计数），
  再用报告自带的「合计」行做**交叉校验**；文档里的数字同样**从文档文本正则抽**，
  与报告解析结果比对。两侧都是抽取值 ⇒ 无人工常量。
"""
import io
import os
import re

import pytest

from fg_system.backtest.walkforward_verdict import (
    parse_report,
    section_verdicts,
)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORT = os.path.join(REPO, "evolution", "walkforward-report.md")
BLOCKED = os.path.join(REPO, "docs", "blocked-registry.md")
ROADMAP = os.path.join(REPO, "docs", "roadmap.md")

# D7 关注的「防御降仓」同族变体（劣化窗占比在文档里被引用）。
DOC_VARIANTS = ("V-ATR", "V-VOL")


def _read(path):
    with io.open(path, encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# 1) 解析器行为：用**注入的样例文本**（真实格式片段）断言，离线可测
# ---------------------------------------------------------------------------
SAMPLE = """# 报告
## TQQQ

| 窗 | B0 年化 | 变体 年化 | B0 回撤 | 变体 回撤 | 判定 |
|---|---|---|---|---|---|
### V-ATR
2016-10-01 ~ 2016-12-31 | 0.0% | 0.0% | 0.0% | 0.0% | 不劣化/等价
2017-01-01 ~ 2017-03-31 | 0.0% | 0.0% | 0.0% | 0.0% | 不劣化/等价
2019-10-01 ~ 2019-12-31 | 62.7% | 40.2% | -1.7% | -1.3% | 劣化
2020-01-01 ~ 2020-03-31 | -65.3% | 0.3% | -35.7% | -5.7% | 不劣化/等价
2020-04-01 ~ 2020-06-30 | 495.4% | 182.3% | -8.0% | -7.2% | 劣化
| **合计** | | | | | **3/5 窗不劣化 ⇒ 建议归档** |
### V-VOL
2016-10-01 ~ 2016-12-31 | 0.0% | 0.0% | 0.0% | 0.0% | 不劣化/等价
2019-10-01 ~ 2019-12-31 | 62.7% | 40.7% | -1.7% | -1.8% | 劣化
| **合计** | | | | | **1/2 窗不劣化 ⇒ 建议归档** |
"""


def test_parse_reports_line_tags_and_crosschecks_total():
    """逐行 tag 计数 + 与「合计」行交叉校验（无人工常量）。"""
    res = parse_report(SAMPLE)
    atr = res[("TQQQ", "V-ATR")]
    assert atr.total == 5
    assert atr.equivalent == 3
    assert atr.degraded == 2
    # 前两行全 0 ⇒ warmup；有效窗 = 5 − 2 = 3；劣化 2/3
    assert atr.warmup == 2
    assert atr.effective == 3
    # 「合计」行声明 3/5 不劣化 ⇒ 与逐行计数一致
    assert atr.declared_not_degraded == 3
    assert atr.declared_total == 5
    assert atr.matches_declared  # 交叉校验通过

    vol = res[("TQQQ", "V-VOL")]
    assert (vol.total, vol.equivalent, vol.degraded) == (2, 1, 1)


def test_section_verdicts_reads_from_injected_path(tmp_path):
    """解析器同时接受**注入的文本**与**注入的路径**（离线可测，不依赖真实报告）。"""
    p = tmp_path / "sample.md"
    p.write_text(SAMPLE, encoding="utf-8")

    def proj(res):
        return {k: (v.total, v.equivalent, v.degraded, v.warmup, v.effective,
                    v.declared_not_degraded, v.declared_total)
                for k, v in res.items()}

    assert proj(section_verdicts(str(p))) == proj(parse_report(SAMPLE))


def test_parser_flags_declared_mismatch():
    """若「合计」行与逐行计数不符 ⇒ 必须报出，而不是静默吞掉。"""
    bad = SAMPLE.replace("**3/5 窗不劣化", "**4/5 窗不劣化")
    atr = parse_report(bad)[("TQQQ", "V-ATR")]
    assert atr.equivalent == 3
    assert atr.declared_not_degraded == 4
    assert not atr.matches_declared


# ---------------------------------------------------------------------------
# 2) 真实报告：整份交叉校验（每个 `### <变体>` 段的自证）
# ---------------------------------------------------------------------------
def _report_text():
    if not os.path.exists(REPORT):
        pytest.skip("真实报告不在本机（Mac 本地产物）：%s" % REPORT)
    return _read(REPORT)


def test_real_report_declared_totals_match_line_counts():
    """真实报告里每个段的逐行计数必须等于它自己的「合计」行。"""
    res = parse_report(_report_text())
    assert res, "未解析到任何 `### <变体>` 段 ⇒ 解析器与报告格式脱节"
    mismatched = ["%s/%s" % k for k, v in res.items() if not v.matches_declared]
    assert not mismatched, "以下段的自证「合计」行与逐行计数不符：%s" % mismatched


# ---------------------------------------------------------------------------
# 3) 文档数字必须 = 报告解析值（D7 的核心：补上的窗数是可机械验证的）
# ---------------------------------------------------------------------------
def _quoted_windows(doc_text, variant):
    """从文档文本抽取该变体被引用的「劣化窗数/有效窗数」。"""
    hits = set()
    for m in re.finditer(
            r"%s[^\n]{0,40}?(\d+)\s*/\s*(\d+)" % re.escape(variant), doc_text):
        hits.add((int(m.group(1)), int(m.group(2))))
    return hits


@pytest.mark.parametrize("doc_path", [BLOCKED, ROADMAP])
def test_docs_quote_report_derived_numbers(doc_path):
    """`blocked-registry.md` / `roadmap.md` 引用的窗数必须可回溯到报告。"""
    res = parse_report(_report_text())
    doc_text = _read(doc_path)
    for variant in DOC_VARIANTS:
        st = res.get(("TQQQ", variant))
        assert st is not None, "报告缺 TQQQ/%s 段" % variant
        quoted = _quoted_windows(doc_text, variant)
        assert quoted, "%s 未引用 %s 的窗数（D7 要求补量化依据）" % (doc_path, variant)
        assert (st.degraded, st.effective) in quoted, (
            "%s 引用的 %s 窗数 %s 与报告解析值 (%d/%d) 不一致"
            % (os.path.basename(doc_path), variant, quoted,
               st.degraded, st.effective))


def test_doc_guard_has_teeth_on_wrong_number():
    """变异测试：文档若引用**错的**窗数（如错把 UPRO 的 21/28 当成 TQQQ）⇒ 守卫必须红。

    这证明上面的 `test_docs_quote_report_derived_numbers` 有判别力，
    而不是恒真断言。
    """
    res = parse_report(_report_text())
    atr = res[("TQQQ", "V-ATR")]
    wrong = "#%d/%d#" % (atr.degraded + 1, atr.effective)  # 故意偏 1
    fake = "依据 V-ATR %s ⇒ 归档" % wrong
    quoted = _quoted_windows(fake, "V-ATR")
    assert quoted, "变异文本应能被抽出数字（否则本测试无效）"
    assert (atr.degraded, atr.effective) not in quoted, (
        "错数字不应被误判为与报告一致")


def test_docs_cite_the_report_as_source():
    """D7 要求注明数据来源 ⇒ 文档须指向报告文件名。"""
    for doc_path in (BLOCKED, ROADMAP):
        assert "walkforward-report.md" in _read(doc_path), (
            "%s 未注明窗数来源为 evolution/walkforward-report.md" % doc_path)
