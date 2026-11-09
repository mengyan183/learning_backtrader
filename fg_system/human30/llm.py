# fg_system/human30/llm.py
# -*- coding: utf-8 -*-
"""Human 3.0 的 🟡 LLM 通道（**已登记例外 H-REV-001**）。

🔴 纪律（设计 §10 / decision-log H-REV-001 条）：
  1. 只服务 `assess.judge_via_llm()` 与 `metatype.generate()` 两个入口 ✓
  2. **不进判决链** ✗；产物不得流向 pipeline/signal/target_position ✗
  3. 失败必须由**上层**确定性降级 ✓（本层**不吞异常** ⇒ 抛出 ✓）
  4. 🟡 输出必须标注、不入下游 ✓
  5. 登记检查在**调用时**读文件 ⇒ **不**在 import 路径上 ✓（设计 §9.3）

客户端**可注入** ✓（`client(prompt) -> str`）⇒ 测试离线可跑、无需网络 ✓。
"""
import json
import os
import urllib.request

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DECISION_LOG = os.path.join(_REPO, "docs", "decision-log.md")
EXCEPTION_ID = "H-REV-001"

HERMES_URL = "http://127.0.0.1:8642/v1/chat/completions"
# 🔴 2026-11-09 用户要求：**取消 NVIDIA 云端兜底** ✗（本层只留 Hermes 一条路 ✓）


def is_exception_registered(path=None):
    """守卫 3：`decision-log.md` 里是否存在 H-REV-001 登记。"""
    p = path or DECISION_LOG
    try:
        with open(p, encoding="utf-8") as f:
            return EXCEPTION_ID in f.read()
    except OSError:
        return False


def require_exception(path=None):
    """未登记 ⇒ raise（🟡 入口的第一道闸 ✓）。"""
    if not is_exception_registered(path):
        raise RuntimeError(
            "🟡 LLM 通道被拒：%s 中未找到 %s 登记 —— "
            "按设计 §9.3，登记必须先于 🟡 入口可用。"
            % (path or DECISION_LOG, EXCEPTION_ID))


def _read_secret_env():
    """从 ~/.hermes/.env 读键值（照 scripts/evolve_review.py ✓，**不硬编码 key** ✗）。"""
    env = {}
    p = os.path.expanduser("~/.hermes/.env")
    try:
        for ln in open(p, encoding="utf-8"):
            if "=" in ln and not ln.strip().startswith("#"):
                k, _, v = ln.strip().partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return env


def _hermes_key():
    return (os.environ.get("API_SERVER_KEY")
            or _read_secret_env().get("API_SERVER_KEY"))


def _post_json(url, body, headers, timeout):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _hermes(prompt, timeout=240):
    body = {"model": "hermes-agent",
            "messages": [{"role": "user", "content": prompt}]}
    d = _post_json(HERMES_URL, body,
                   {"Authorization": "Bearer %s" % (_hermes_key() or ""),
                    "Content-Type": "application/json"}, timeout)
    return d["choices"][0]["message"]["content"]




def call_llm(prompt, client=None, timeout=240):
    """调用 **Hermes(8642)**，返回 `(text, via)`。

    `client` 可注入 ✓（`client(prompt) -> str`）⇒ 测试无需网络 ✓。
    🔴 2026-11-09 用户要求：**取消 NVIDIA 云端兜底** ✗ ——
       云端降级会掩盖 Hermes 自己的故障 ✗（11-09 就是超时被静默换通道）✗
       ⇒ 失败直接抛，由**上层**确定性降级 ✓（本层仍不吞异常 ✓）
    """
    if client is not None:
        return client(prompt), "injected"
    return _hermes(prompt, timeout=timeout), "hermes(8642)"


def extract_json(text):
    """从 LLM 回复里抽出 JSON（容忍 ```json 围栏 ✓）。"""
    import re
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.S)
    if m:
        text = m.group(1)
    return json.loads(text)
