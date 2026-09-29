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
    """⚠️ **变异验证（常驻）**：`if _box_has_text(...)` 不能被短路成 `if False and ...`。

    **为什么需要它**：先写过一版纯字符串守卫（断言「`press Enter` 之后出现过
    `_box_has_text`」）—— 实测把它改成 `if False and _box_has_text(...)` 后
    **那条断言照样通过** ⇒ 守卫失效（**静默通过 = 最坏的失败模式**，同
    `test_script_only_records_the_history_endpoint` 的教训）。

    ⇒ 走 **AST**：`press Enter` 之后必须存在一个 `if`，其 **test 本身就是**
    `_box_has_text(...)` 的调用，且**分支体里有 `raise`**（否则失败会被静默吞掉）。
    """
    import ast
    src = _src()
    idx = src.index('bsk.run("press", "Enter"')
    line0 = src[:idx].count("\n") + 1
    for node in ast.walk(ast.parse(src)):
        if not (isinstance(node, ast.If) and node.lineno > line0):
            continue
        t = node.test
        if (isinstance(t, ast.Call) and isinstance(t.func, ast.Name)
                and t.func.id == "_box_has_text"):
            assert any(isinstance(n, ast.Raise) for n in ast.walk(node)), \
                "该 if 分支里必须有 raise —— 否则「没发出去」被静默吞掉"
            return
    raise AssertionError(
        "`press Enter` 之后没有「`if _box_has_text(...)` + raise」的校验"
        "（注意：被 `and` 短路、或只写了字符串但没真判，都算失败）")


def test_send_loop_raises_with_resume_hint_on_failure():
    """失败必须**抛错并给出 `--start N` 续发指令**，不得静默计成已发。"""
    src = _src()
    idx = src.index('bsk.run("press", "Enter"')
    tail = src[idx:]
    assert "--start" in tail, "发送失败时应给出 --start 续发指令"
    assert "raise SystemExit" in tail, "发送失败必须抛错，不得静默继续"
