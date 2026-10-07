# -*- coding: utf-8 -*-
"""bsk（browser-skill CLI）薄封装 —— 供 fetch_shoutu_history.py 复用。

背景：bsk 时代（2026-09-24 前）的历史抓取依赖 `fetch_shoutu.py` 封装；
该模块随 bsk 通道被 partner-API 通道替代时删除，但
`fetch_shoutu_history.py`（全量历史，网页 stock_emotion/history 旁观）
仍引用它，导致 history 通道在 macOS 上**静默断更**（09-29 停更）。

本封装只暴露两个函数，行为与旧版一致：
    bsk(args, session=None)   -> 运行 bsk 子命令，返回 stdout（stderr 并入报错）
    bsk_eval(js, session)     -> evaluate 一段 JS，返回求值字符串

⚠️ 安全约束（继承 fetch_shoutu_history.py）：
  挂钩 JS 只记录 URL 含 `stock_emotion/history` 的响应体；
  同会话的许可信息端点（含明文凭据）响应一律丢弃，不进日志不进文件。
"""
import subprocess

_BSK = "/Users/xingguo/.local/bin/bsk"


def bsk(args, session=None):
    cmd = [_BSK] + [str(a) for a in args]
    if session:
        cmd += ["--session", str(session)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        raise RuntimeError(
            "bsk %s failed rc=%s: %s" % (args, r.returncode, (r.stderr or r.stdout or "")[:300])
        )
    return r.stdout


def bsk_eval(js, session):
    out = bsk(["evaluate", js], session)
    return out.strip()
