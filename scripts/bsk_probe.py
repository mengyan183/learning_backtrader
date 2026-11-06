# -*- coding: utf-8 -*-
"""一次性采集 bsk 控制上下文的全部关键事实 ✓（只读诊断，**不写业务数据**）。

【为什么需要】`fetch_shoutu_history` 连续 5 轮失败 ✗ 而每轮只带回一条错误 ✗
⇒ 一轮一轮试太慢 ✗ 且用户明确要求「避免在 Mac 上反复重试」✗
⇒ 这个脚本**一次跑完**所有候选调用，把每条的原始输出都打出来 ✓

采集项：
  ① `observe` 能否成功、返回多长
  ② `cooperate sync` / `cooperate sync --json` 的**原始输出**（context 就在里面）
  ③ `evaluate 1+1`：不带 --context / 带 --context 各试一次
  ④ `step --action evaluate --params ...`（新 CLI 的动作入口）

⚠️ 只做只读动作（`1+1`、`observe`），**不碰页面业务数据** ✓
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_shoutu as fs                          # noqa: E402


def _run(label, args, sid):
    try:
        out = fs.bsk(args, sid)
        print("[%s] ok len=%d\n%s" % (label, len(out), (out or "").strip()[:800]))
        return out
    except RuntimeError as exc:
        print("[%s] FAIL %s" % (label, str(exc)[:400]))
        return ""


def main():
    sid = ""
    try:
        sid = fs.bsk(["session", "start", "--no-focus"]).strip().splitlines()[-1].strip()
        print("session:", sid)
        fs.bsk(["navigate", fs.UNIVERSE_PAGE], sid)
        time.sleep(4)

        _run("observe", ["observe"], sid)
        out1 = _run("sync", ["cooperate", "sync"], sid)
        _run("sync --json", ["cooperate", "sync", "--json"], sid)
        ctx = fs._parse_context(out1)
        print("parsed ctx=%r" % (ctx[:60],))

        _run("eval no-ctx", ["evaluate", "1+1"], sid)
        if ctx:
            _run("eval with-ctx", ["evaluate", "1+1", "--context", ctx], sid)
        _run("step eval", ["step", "--action", "evaluate",
                           "--params", json.dumps({"expression": "1+1"})], sid)
        _run("step observe", ["step", "--action", "observe", "--params", "{}"], sid)
    finally:
        if sid:
            try:
                fs.bsk(["session", "stop", sid])
            except RuntimeError:
                pass


if __name__ == "__main__":
    main()
