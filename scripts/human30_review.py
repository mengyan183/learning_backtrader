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
PROMPT_TMPL = (
    "你是个人成长教练。以下是某交易者的 Human 3.0 四象限自评序列"
    "（mind 心/认知、body 体/行动、spirit 精神/意义、vocation 职/事业，0-100）"
    "及当日市场快照 fg_index（贪恐指数）与档位 zone（0极度恐惧/1恐惧/2中性/3贪婪/4极度贪婪）。\n"
    "任务：用不超过 150 字给出 (1) 状态趋势观察 (2) 1 条可执行建议。\n"
    "约束：只解读自评与成长，禁止出现买卖/仓位/投资/交易策略/止损/加仓等任何交易动作字眼；"
    "事实来自给出的数据，不得编造；N/A 表示当日未记录市场快照，一律跳过不要解读。\n"
    "数据（时间升序，每行 日期,心,体,精神,职,均分,意识层级,短板,fg_index,zone）：\n{data}\n"
    "输出：趋势观察 + 建议，150 字内。"
)


def _build_data_lines(days=7):
    """窗口内记录 → 数据行文本（确定性，含市场快照）。"""
    recs = human30.history(200)[-days:] if human30.history(200) else []
    if not recs:
        return None
    lines = []
    for r in recs:
        agg = human30.aggregate(r)
        mkt = r.get("market") or {}
        lines.append("%s,%.0f,%.0f,%.0f,%.0f,%.1f,%s,%s,%s,%s" % (
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
                "做多", "做空", "建仓", "清仓", "投资建议")


def _guard_filter(text):
    """输出后过滤（守卫层 2）：剔除交易字眼，防止模型越界。"""
    for bad in _TRADE_WORDS:
        text = text.replace(bad, "行动")
    return text


def review(days=7, model="qwen2.5-coder:3b", host="http://localhost:11434"):
    """生成 AI 复盘（≤200 字）；任何失败降级为确定性窗口统计。"""
    data = _build_data_lines(days)
    if data is None:
        return PREFIX + "：尚无自评记录，无法复盘（数据从打卡开始积累）。"
    try:
        text = _ollama_generate(PROMPT_TMPL.format(data=data), model, host)
        if not text:
            raise RuntimeError("empty response")
        # 输出后过滤（守卫层 2）：剔除交易字眼，防止模型越界
        text = _guard_filter(text)
        # 规范：压单行、截断 200 字
        text = " ".join(text.split())
        if len(text) > 200:
            text = text[:200]
        return PREFIX + "：" + text
    except Exception as e:
        # 降级：确定性窗口统计（绝不阻塞）
        w = human30.window_stats(days)
        lv = w["level_counts"]
        lv_txt = " / ".join("L%d×%d" % (k, lv[k]) for k in (1, 2, 3) if lv.get(k))
        wk = w["weakest_counts"]
        wk_txt = "、".join("%s×%d" % (k, v)
                          for k, v in sorted(wk.items(), key=lambda x: -x[1])) or "-"
        return (PREFIX + "（模型暂不可用，降级确定性统计）："
                "近 %d 日打卡 %d 次，意识层级 %s，短板高频 %s。" % (days, w["records"], lv_txt, wk_txt))


def main():
    p = argparse.ArgumentParser(description="Human 3.0 AI 复盘（只读自评，不判交易）")
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--model", default="qwen2.5-coder:3b")
    p.add_argument("--host", default="http://localhost:11434")
    args = p.parse_args()
    print(review(args.days, args.model, args.host))


if __name__ == "__main__":
    main()
