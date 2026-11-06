# -*- coding: utf-8 -*-
"""`scripts/feishu_send.py` 的**发送验证**（2026-09-28）。

【背景】实测事故：全量发送的最后一条 `fill` 成功、`press Enter` 也没报错，
但消息**停在输入框里没发出去**，而脚本照样打印「已发」⇒ 用户**无法分辨**
「真发出」和「只填进了输入框」（用户当场报告输入框里残留着 `###FG:tests:85/85###`）。

⇒ 发送后**必须**再验证一次：**输入框已被清空**（发送成功的强信号）。

⚠️ 判据**只能看输入框那一行** —— 消息列表里本来就可能有同样的文本（**发过的**消息），
若匹配任意行，**续发时会把「已经发过」误判成「填进去了」**（同一 bug 的另一面）。
"""
import importlib.util
import os

import pytest

from fg_system import config

_SPEC = os.path.join(config.ROOT, "scripts", "feishu_send.py")


def _load():
    spec = importlib.util.spec_from_file_location("feishu_send", _SPEC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fs = _load()


def _src():
    return open(_SPEC, encoding="utf-8").read()


def test_box_has_text_matches_the_textbox_line():
    vom = ('  @e10 button "别的"\n'
           '  @e11 textbox "###FG:tests:1/85###AAAA" [filled]\n')
    assert fs._box_has_text(vom, "###FG:tests:1/85###") is True


def test_box_has_text_ignores_the_message_list():
    """⚠️ **只在消息列表里出现 ⇒ 不得判为「输入框里有」**。

    这是「续发」场景的关键：那条文本**已经作为消息发过**，所以它会出现在消息列表里；
    若判据匹配任意行，脚本就会以为"填进去了"、进而 `press Enter` 发**空**内容
    （或重复发送），而错误信息还指向错误的方向。
    """
    only_list = '  @e10 button "###FG:tests:1/85###AAAA"\n'
    assert fs._box_has_text(only_list, "###FG:tests:1/85###") is False


def test_box_has_text_empty_vom():
    assert fs._box_has_text("", "x") is False


def test_send_failure_check_is_not_short_circuited():
    """⚠️ **变异验证（常驻）**：发送成功判据不能被短路，失败必须 raise。

    **为什么需要它**：先写过一版纯字符串守卫（断言「`press Enter` 之后出现过
    `_box_has_text`」）—— 实测把它改成 `if False and _box_has_text(...)` 后
    **那条断言照样通过** ⇒ 守卫失效（**静默通过 = 最坏的失败模式**，同
    `test_script_only_records_the_history_endpoint` 的教训）。

    🔴 2026-11-06 更新：代码改成**轮询 3 秒等输入框清空**（`cleared` 标志），
    旧守卫只认「`if _box_has_text(...)` 直连 raise」⇒ 守卫与实际实现脱钩变红 ✗。
    新判据（两条都必须在 `press Enter` 之后成立）：
      ① `if not _box_has_text(...)` —— **test 就是它本身**（含 `and` 即算短路 ✗）
         且分支把 `cleared` 置 True；
      ② `if not cleared:` 分支里有 `raise`（否则失败被静默吞掉 ✗）。
    """
    import ast
    src = _src()
    idx = src.index('bsk.run("press", "Enter"')
    line0 = src[:idx].count("\n") + 1

    def _sets_cleared_true(node):
        for n in ast.walk(node):
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant) \
                    and n.value.value is True:
                if any(isinstance(t, ast.Name) and t.id == "cleared"
                       for t in n.targets):
                    return True
        return False

    poll_ok = fail_ok = False
    for node in ast.walk(ast.parse(src)):
        if not (isinstance(node, ast.If) and node.lineno > line0):
            continue
        t = node.test
        # ① 判据本身 = `not _box_has_text(...)`（不套 `and` ⇒ 不会被短路）
        if (isinstance(t, ast.UnaryOp) and isinstance(t.op, ast.Not)
                and isinstance(t.operand, ast.Call)
                and isinstance(t.operand.func, ast.Name)
                and t.operand.func.id == "_box_has_text"
                and _sets_cleared_true(node)):
            poll_ok = True
        # ② 未清空 ⇒ raise
        if (isinstance(t, ast.UnaryOp) and isinstance(t.op, ast.Not)
                and isinstance(t.operand, ast.Name) and t.operand.id == "cleared"
                and any(isinstance(n, ast.Raise) for n in ast.walk(node))):
            fail_ok = True

    assert poll_ok, (
        "`press Enter` 之后的成功判据必须是 `if not _box_has_text(...)` 且把 "
        "`cleared` 置 True（被 `and` 短路 / 只写字符串 / 换成别的判据都算失败）")
    assert fail_ok, "「没发出去」必须走 `if not cleared: ... raise`，不得静默吞掉"


def test_send_loop_raises_with_resume_hint_on_failure():
    """失败必须**抛错并给出 `--start N` 续发指令**，不得静默计成已发。"""
    src = _src()
    idx = src.index('bsk.run("press", "Enter"')
    tail = src[idx:]
    assert "--start" in tail, "发送失败时应给出 --start 续发指令"
    assert "raise SystemExit" in tail, "发送失败必须抛错，不得静默继续"


def test_send_lock_blocks_concurrent_run(tmp_path, monkeypatch):
    """**守卫**：两个发送进程不许并发 ✓。

    2026-10-28 实测：并发时后启动的进程会先 `bsk.reap()`（清残留会话）✗
    ⇒ 把前一个正在用的会话踢掉 ⇒ 前一批**只发出 1 片就中止** ✗
    （`--limit 2` 连续四次都只发 1 片，日志还全空 ✗）。
    """
    monkeypatch.setattr(fs, "TEXT_DIR", str(tmp_path))
    fd = fs._acquire_lock()
    try:
        with pytest.raises(SystemExit):
            fs._acquire_lock()
    finally:
        fs._release_lock(fd)
    # 释放后必须能再拿到 ✓（否则发完一包就永久卡死 ✗）
    fs._release_lock(fs._acquire_lock())
