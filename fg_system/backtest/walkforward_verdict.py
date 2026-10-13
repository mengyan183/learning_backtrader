# -*- coding: utf-8 -*-
"""解析 `evolution/walkforward-report.md`，把每段判定**从文本**还原成窗数。

【用途】D7：文档里引用的「劣化窗数/有效窗数」必须可回溯到报告，而不是人工抄写。
`scripts/evolve_walkforward.py` 生成报告；本模块只做**反向解析**（只读，无副作用）。

【报告真实格式】（实测，勿按想象改）
```
## TQQQ                     <- 标的小节
### V-ATR                   <- 变体段
2019-10-01 ~ 2019-12-31 | 62.7% | 40.2% | -1.7% | -1.3% | 劣化
| **合计** | | | | | **20/40 窗不劣化 ⇒ 建议归档** |
```
- 每个数据行 `|` 分隔后 **6 列**，末列是判定（`劣化` / `不劣化/等价`）。
- 「合计」行声明「<不劣化数>/<总窗数> 窗不劣化」。

【口径】
- `total`    = 数据行数（含 warmup）。
- `warmup`   = 5 个指标列全为 `0.0%` 的行（前 12 个季度窗，所有变体一致）。
- `effective`= total − warmup（= 报告没写、但文档引用的分母 28）。
- `degraded` = 末列 == `劣化` 的行数。
- `matches_declared` = 「合计」行是否与逐行计数一致（自证）。
"""
import io

VERDICT_DEGRADED = "劣化"
VERDICT_EQUIVALENT = "不劣化/等价"
_ZERO = "0.0%"


class SectionVerdict(object):
    """一个 `### <变体>` 段的窗数汇总。"""

    __slots__ = ("symbol", "variant", "total", "equivalent", "degraded",
                 "warmup", "declared_not_degraded", "declared_total")

    def __init__(self, symbol, variant):
        self.symbol = symbol
        self.variant = variant
        self.total = 0
        self.equivalent = 0
        self.degraded = 0
        self.warmup = 0
        self.declared_not_degraded = None
        self.declared_total = None

    @property
    def effective(self):
        return self.total - self.warmup

    @property
    def matches_declared(self):
        if self.declared_total is None or self.declared_not_degraded is None:
            return False
        return (self.declared_not_degraded == self.equivalent
                and self.declared_total == self.total)

    def __repr__(self):
        return ("SectionVerdict(%s/%s degraded=%d/%d warmup=%d declared=%s/%s)"
                % (self.symbol, self.variant, self.degraded, self.effective,
                   self.warmup, self.declared_not_degraded, self.declared_total))


def _cells(line):
    """把 `a | b | c` 拆成去空白后的列（不保留首尾空串）。"""
    if not line.startswith("|") and "|" not in line:
        return None
    return [c.strip() for c in line.split("|")]


def _all_zero(cells):
    """5 个指标列（索引 1..5，末列是判定）是否全为 0.0%。"""
    metrics = cells[1:-1]
    return bool(metrics) and all(c == _ZERO for c in metrics)


def parse_report(text):
    """解析报告全文，返回 `{(symbol, variant): SectionVerdict}`。

    `text` 为报告正文（调用方负责读文件），便于离线测试注入样例片段。
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    result = {}
    symbol = None
    current = None
    for line in text.split("\n"):
        line = line.rstrip()
        if line.startswith("## "):
            name = line[3:].strip()
            symbol = None if name in ("汇总", "") else name
            current = None
            continue
        if line.startswith("### "):
            variant = line[4:].strip()
            if symbol and variant:
                current = SectionVerdict(symbol, variant)
                result[(symbol, variant)] = current
            else:
                current = None
            continue
        if current is None:
            continue
        if line.startswith("| **合计**"):
            nums = _declared_numbers(line)
            if nums:
                current.declared_not_degraded, current.declared_total = nums
            continue
        cells = _cells(line)
        if not cells or len(cells) < 6:
            continue
        verdict = cells[-1]
        if verdict not in (VERDICT_DEGRADED, VERDICT_EQUIVALENT):
            continue
        current.total += 1
        if _all_zero(cells):
            current.warmup += 1
        if verdict == VERDICT_DEGRADED:
            current.degraded += 1
        else:
            current.equivalent += 1
    return result


def _declared_numbers(line):
    """从「合计」行抽 `<不劣化>/<总>`。"""
    import re
    m = re.search(r"(\d+)\s*/\s*(\d+)", line)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def section_verdicts(path):
    """便捷入口：直接读报告文件路径。"""
    with io.open(path, encoding="utf-8") as fh:
        return parse_report(fh.read())
