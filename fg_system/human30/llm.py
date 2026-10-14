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
import subprocess
import tempfile
import urllib.request

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DECISION_LOG = os.path.join(_REPO, "docs", "decision-log.md")
EXCEPTION_ID = "H-REV-001"

HERMES_URL = "http://127.0.0.1:8642/v1/chat/completions"
NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
NVIDIA_PROXY = "http://127.0.0.1:7890"
NVIDIA_MODEL = "deepseek-ai/deepseek-v4.1-flash"
# NVIDIA WAF 拦截无 UA 的 urllib 请求（照 scripts/evolve_review.py ✓）
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) curl/8.4.0"


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


def _nvidia_key():
    return (os.environ.get("NVIDIA_API_KEY")
            or _read_secret_env().get("NVIDIA_API_KEY"))


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


def _nvidia(prompt, timeout=300):
    """NVIDIA 直连降级（照 scripts/evolve_review.py:168-199 移植 ✓）。

    🔴 key **不得**出现在命令行 ✗ ⇒ 写 0600 的 `--config` 临时文件 ✓。
    """
    key = _nvidia_key()
    if not key:
        raise RuntimeError("Hermes 不可用且无 NVIDIA_API_KEY")
    body = {"model": NVIDIA_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "chat_template_kwargs": {"thinking": False},
            "max_tokens": 1600}
    tmp = os.path.join(tempfile.gettempdir(), "nv_h30_req_%d.json" % os.getpid())
    fd, cfg = tempfile.mkstemp(prefix="nv_h30_curl_", suffix=".cfg")
    try:
        os.chmod(cfg, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write('header = "Authorization: Bearer %s"\n'
                    'header = "Content-Type: application/json"\n'
                    'header = "User-Agent: %s"\n'
                    % (key.replace("\\", "\\\\").replace('"', '\\"'), UA))
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(body))
        out = subprocess.run(
            ["curl", "-s", "-m", "300", "-x", NVIDIA_PROXY,
             "--config", cfg, NVIDIA_URL, "--data-binary", "@" + tmp],
            capture_output=True, text=True, timeout=320)
    finally:
        for p in (tmp, cfg):
            try:
                os.remove(p)
            except OSError:
                pass
    if out.returncode != 0:
        raise RuntimeError("NVIDIA curl 失败 rc=%s: %s"
                           % (out.returncode, (out.stderr or "")[:200]))
    return json.loads(out.stdout)["choices"][0]["message"]["content"]


def call_llm(prompt, client=None, timeout=240, allow_nvidia=True):
    """调用 LLM，返回 `(text, via)`。

    `client` 可注入 ✓（`client(prompt) -> str`）⇒ 测试无需网络 ✓。
    🔴 **不吞异常** ⇒ 两路都失败时 raise，由上层降级 ✓。
    """
    if client is not None:
        return client(prompt), "injected"
    try:
        return _hermes(prompt, timeout=timeout), "hermes(8642)"
    except Exception:
        if not allow_nvidia:
            raise
    return _nvidia(prompt), "nvidia-direct"


def extract_json(text):
    """从 LLM 回复里抽出 JSON（容忍 ```json 围栏 ✓）。"""
    import re
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.S)
    if m:
        text = m.group(1)
    return json.loads(text)
