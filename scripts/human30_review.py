# -*- coding: utf-8 -*-
"""Human 3.0 AI 复盘（H-REV-001，C-3 已审批 2026-10-10）。

边界（提案硬约束，不可改动）：
- LLM 只解读自评数据（Data/human30.json + 市场快照），**不判交易**：
  输出固定前缀 `AI 复盘（🟡 研究参考，非系统信号）`，禁止买卖/仓位/账户建议
- 数据只读：不写任何状态
- 失败降级：模型不可用/超时/无记录 → 自动降级为确定性窗口统计（window_stats），
  绝不阻塞简报生成
- 无调参：prompt 固定规则模板，不随会话漂移

用法：
  python scripts/human30_review.py [--days 7] [--model qwen2.5-coder:3b]
"""
import argparse
import json
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from fg_system import human30

PREFIX = "AI 复盘（🟡 研究参考，非系统信号）"


def _build_data_lines(days=7):
    """窗口内记录 → 数据行文本（确定性，含市场快照）。

    用「字段名=值」键值对而非 CSV 列序——实测 3b 模型对纯列序数字易错位
    （把 body 的 100 安到 spirit 上），键值对可大幅降低张冠李戴。
    """
    recs = human30.history(200)[-days:] if human30.history(200) else []
    if not recs:
        return None
    lines = []
    for r in recs:
        agg = human30.aggregate(r)
        mkt = r.get("market") or {}
        lines.append(
            "日期=%s | mind=%d | body=%d | spirit=%d | vocation=%d | 均分=%.1f | "
            "意识层级=%s | 短板=%s | fg_index=%s | zone=%s" % (
                r["date"], r["mind"], r["body"], r["spirit"], r["vocation"],
                agg["avg"], agg["level_name"].split(" ")[0],
                agg["weakest_label"],
                mkt.get("fg_index", "N/A"), mkt.get("zone", "N/A")))
    return "\n".join(lines)


def _ollama_generate(prompt, model, host="http://localhost:11434", timeout=45):
    req = urllib.request.Request(
        host + "/api/generate",
        data=json.dumps({"model": model, "prompt": prompt,
                         "stream": False, "options": {"temperature": 0.3}}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        resp = json.loads(r.read())
    text = (resp.get("response") or "").strip()
    return text


_TRADE_WORDS = ("交易策略", "仓位", "买入", "卖出", "止损", "加仓", "减仓",
                "做多", "做空", "建仓", "清仓", "投资建议",
                "避免过度贪婪", "过度贪婪", "避免贪婪")


def _guard_filter(text):
    """输出后过滤（守卫层 2）：剔除交易字眼，防止模型越界。"""
    for bad in _TRADE_WORDS:
        text = text.replace(bad, "行动")
    return text


SUGGEST_PROMPT = (
    "你是个人成长教练。以下是某交易者的四象限自评数据"
    "（mind 心/认知、body 体/行动、spirit 精神/意义、vocation 职/事业，0-100；"
    "字段名=值，N/A 表示缺失）：\n{data}\n"
    "任务：用不超过 60 字给出 1 条针对个人成长的可执行建议。\n"
    "约束：只谈个人成长；禁止买卖/仓位/投资/交易策略/止损/加仓/贪婪/市场波动等任何市场建议字眼；"
    "事实只来自给出的数据，不得编造。"
)


def _facts_line(days=7):
    """确定性事实句：最新四象限 + 均分 + 层级 + 短板 + 窗口分布。

    核心数字由系统给出（永不漂移），LLM 只生成建议文本——
    防止 3b 模型对趋势/数字做不稳定概括。
    """
    latest = human30.latest()
    if not latest:
        return None
    agg = human30.aggregate(latest)
    w = human30.window_stats(days)
    lv = w["level_counts"]
    lv_txt = " / ".join("L%d×%d" % (k, lv[k]) for k in (1, 2, 3) if lv.get(k)) or "无"
    return ("近 %d 日打卡 %d 次 · 最新四象限 mind=%d body=%d spirit=%d vocation=%d · "
            "均分 %.1f · 意识层级 %s · 短板 %s · 层级分布 %s" % (
                days, w["records"], latest["mind"], latest["body"],
                latest["spirit"], latest["vocation"], agg["avg"],
                agg["level_name"].split(" ")[0], agg["weakest_label"], lv_txt))
def review(days=7, model="qwen2.5-coder:3b", host="http://localhost:11434"):
    """生成 AI 复盘（≤260 字）：确定性事实句 + LLM 建议。

    架构（防 3b 模型数字错位/概括漂移）：
    - 事实句（均分/层级/短板/四象限）由系统确定性生成，永不漂移
    - LLM 只生成 ≤60 字成长建议；越界由 _guard_filter 兜底
    - 任何失败降级为确定性事实句 + 确定性建议（短板导向），绝不阻塞
    """
    facts = _facts_line(days)
    if facts is None:
        return PREFIX + "：尚无自评记录，无法复盘（数据从打卡开始积累）。"
    data = _build_data_lines(days)
    try:
        suggestion = _ollama_generate(SUGGEST_PROMPT.format(data=data), model, host)
        if not suggestion:
            raise RuntimeError("empty response")
        suggestion = _guard_filter(suggestion)
        suggestion = " ".join(suggestion.split())
        if len(suggestion) > 60:
            cut = suggestion.rfind("。", 0, 60)
            suggestion = suggestion[:cut + 1] if cut > 20 else suggestion[:60]
        text = facts + "。建议：" + suggestion
    except Exception:
        # 降级：确定性建议（短板导向，绝不阻塞）
        agg = human30.aggregate(human30.latest())
        text = facts + ("。建议：优先补齐短板「%s」——围绕它设定本周一个可完成的小行动。"
                        "（模型暂不可用，建议降级为确定性规则）" % agg["weakest_label"])
    # 规范：压单行；超过 260 字时优先在句号处截断，避免半句
    text = " ".join(text.split())
    if len(text) > 260:
        cut = text.rfind("。", 0, 260)
        text = text[:cut + 1] if cut > 130 else text[:260]
    return PREFIX + "：" + text


def main():
    p = argparse.ArgumentParser(description="Human 3.0 AI 复盘（只读自评，不判交易）")
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--model", default="qwen2.5-coder:3b")
    p.add_argument("--host", default="http://localhost:11434")
    args = p.parse_args()
    print(review(args.days, args.model, args.host))


if __name__ == "__main__":
    main()
