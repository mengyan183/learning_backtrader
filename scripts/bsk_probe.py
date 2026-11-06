# -*- coding: utf-8 -*-
"""一次性采集 bsk 控制上下文的全部关键事实 ✓（只读诊断，**不写业务数据**）。

【为什么需要】`fetch_shoutu_history` 连续 5 轮失败 ✗ 每轮只带回一条错误 ✗
⇒ 一轮一轮试太慢 ✗ 用户明确要求「避免在 Mac 上反复重试」✗
⇒ 本脚本**一次跑完**所有候选调用，把每条的原始输出都打出来 ✓

采集项（对应 dsh 给的 E0~E3）：
  E0 版本代际：`bsk --version` + `bsk status --json`（看 version_skew ✗）
  E1 `cooperate sync --settle --json` / `cooperate sync` 的原始输出
  E2 `evaluate 1+1`：不带 context / 带 context 各一次
  E3 `tab list --scope user --json`（人是否占着 tab）
  +  `step --action evaluate --params ...`（新 CLI 的动作入口，试一次）

⚠️ 只做只读动作（`1+1` / `observe` / 列表），**不碰页面业务数据** ✓
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_shoutu as fs                          # noqa: E402


def _run(label, args, sid=None):
    """跑一条 bsk 命令并打印原始结果（成功/失败都打，失败不中断 ✓）。"""
    try:
        out = fs.bsk(args, sid) if sid else fs.bsk(args)
        print("[%s] ok len=%d\n%s" % (label, len(out), (out or "").strip()[:900]))
        return out
    except (RuntimeError, OSError) as exc:
        print("[%s] FAIL %s" % (label, str(exc)[:500]))
        return ""


def main():
    # ---- E0 版本代际（不需要 session）
    _run("version", ["--version"])
    _run("status", ["status", "--json"])

    sid = ""
    try:
        try:
            sid = fs.bsk(["session", "start", "--no-focus"]).strip().splitlines()[-1].strip()
        except (RuntimeError, OSError) as exc:
            print("[session start] FAIL %s" % str(exc)[:500])
            return
        print("session:", sid)
        fs.bsk(["navigate", fs.UNIVERSE_PAGE], sid)
        time.sleep(4)

        _run("observe", ["observe"], sid)
        # ---- E3 谁占着 tab
        _run("tab list", ["tab", "list", "--scope", "user", "--json"], sid)
        # ---- E1 context 的三种取法
        out_settle = _run("sync --settle --json",
                          ["cooperate", "sync", "--settle", "--json"], sid)
        out_plain = _run("sync", ["cooperate", "sync"], sid)
        ctx = fs._parse_context(out_settle) or fs._parse_context(out_plain)
        print("parsed ctx=%r" % (ctx[:60],))
        # ---- E2 evaluate 两种方式
        _run("eval no-ctx", ["evaluate", "1+1"], sid)
        if ctx:
            _run("eval with-ctx", ["evaluate", "1+1", "--context", ctx], sid)
        # ---- 新 CLI 的动作入口（试一次，失败也算信息）
        _run("step eval", ["step", "--action", "evaluate",
                           "--params", json.dumps({"expression": "1+1"})], sid)
    finally:
        if sid:
            try:
                fs.bsk(["session", "stop", sid])
            except RuntimeError:
                pass


if __name__ == "__main__":
    main()
