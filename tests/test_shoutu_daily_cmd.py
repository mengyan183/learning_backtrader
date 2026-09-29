# -*- coding: utf-8 -*-
"""`scripts/*.cmd` 的守卫测试。

【为什么需要】
`cmd.exe` 用**系统代码页**（本机 GBK）读 `.bat` / `.cmd`，**不是 UTF-8**。
REM 行里的非 ASCII 字节会被误解析；GBK 是双字节编码，**错位的字节对会吞掉换行**，
两行合并后整段被当命令执行：

    '...' is not recognized as an internal or external command

**这在 2026-09-23 真实发生过** —— 文件里写了一段中文说明，定时任务直接挂掉。
而 `.cmd` 是**无人值守**的（Task Scheduler 06:30 跑），坏了没人当场看见，
只能第二天翻日志才发现。所以必须有测试守着。

另外 `.gitattributes` 把 `*.cmd` 钉成 **CRLF**（Windows 批处理必须 CRLF），
这里一并守住 —— 否则在 macOS/Linux 上编辑过再提交就会变成 LF。
"""
import glob
import os

import pytest

from fg_system import config

CMD_FILES = sorted(glob.glob(os.path.join(config.ROOT, "scripts", "*.cmd")))


def test_cmd_files_exist():
    """守卫本身要有效 —— 找不到文件时不能静默通过。"""
    assert CMD_FILES, "scripts/ 下没有 .cmd，测试形同虚设"


@pytest.mark.parametrize("path", CMD_FILES, ids=os.path.basename)
def test_cmd_is_ascii_only(path):
    """**核心守卫**：`.cmd` 必须是纯 ASCII。

    非 ASCII 会被 GBK 误解析、吞换行、把 REM 文本当命令执行 ——
    2026-09-23 实际发生过，定时任务直接失败。
    中文说明请写在 `docs/trading-discipline.md` 里，文件里只留 ASCII 摘要。
    """
    raw = open(path, "rb").read()
    bad = [(i, b) for i, b in enumerate(raw) if b > 127]
    assert not bad, (
        "%s 含 %d 个非 ASCII 字节（首个在偏移 %d）。\n"
        "cmd.exe 按 GBK 读这个文件，非 ASCII 会吞掉换行并把 REM 文本当命令执行。\n"
        "请改成 ASCII，中文理由写进 docs/trading-discipline.md。"
        % (os.path.basename(path), len(bad), bad[0][0]))


@pytest.mark.parametrize("path", CMD_FILES, ids=os.path.basename)
def test_cmd_uses_crlf(path):
    """`.cmd` 必须 CRLF（`.gitattributes` 里钉死了，这里防回归）。"""
    raw = open(path, "rb").read()
    assert b"\r\n" in raw, "%s 没有 CRLF 换行" % os.path.basename(path)
    # 不应出现「裸 LF」（即前面不是 CR 的 LF）
    lone = sum(1 for i, b in enumerate(raw) if b == 0x0A and (i == 0 or raw[i - 1] != 0x0D))
    assert lone == 0, "%s 有 %d 个裸 LF" % (os.path.basename(path), lone)


def test_daily_task_prefers_browser_path():
    """**守卫**：每日任务必须**先用浏览器路径**（用户 2026-09-24 明确要求）。

    这是**成本**决策，不是正确性决策：

      - 浏览器路径 = 1 次页面加载读 11 张表，**零逐标的请求**
      - API 路径   = **每个标的一次请求**（8 个标的就是 8 次）

    `fetch_shoutu.py` 开头记录过当初否掉 API 的原因：探测返回
    `{"status":2,"msg":"参数校验失败，IP 已记录"}` —— 该端点会**记录未授权 IP**。
    现在凭据（`Data/shoutu_token`）是合法持有的，但请求量仍是 8 倍，
    且对着的是**合作方端点**，没有收益。

    历史上这里曾一度写成「API 优先」（提交 cacf025），那是**改错了方向**：
    当时只看到浏览器路径漏 AXTX/CRCG，没看到二者成本差 8 倍。
    漏标的的正确修法是**补数据源**（个股贪恐视图），不是**换主路径**。
    """
    p = os.path.join(config.ROOT, "scripts", "shoutu_daily.cmd")
    text = open(p, encoding="ascii").read()
    api = text.find("fetch_shoutu_api.py")
    browser = text.find("fetch_shoutu.py")
    assert api != -1, "每日任务没有保留 API 兜底"
    assert browser != -1, "每日任务没有调用浏览器路径"
    assert browser < api, "浏览器路径必须排在 API 路径之前（API 是逐标的请求，量级 8 倍）"


def test_daily_task_fallback_avoids_parenthesised_errorlevel():
    """**守卫**：不能用 `if (...)` 块里读 `%ERRORLEVEL%`。

    cmd.exe 在**解析**整个括号块时就展开 `%VAR%`，所以块内
    `set RC=%ERRORLEVEL%` 拿到的是**进块之前**的值 ——
    兜底路径的退出码会错，而且错得很隐蔽（看起来像成功）。
    故改用 `goto` + 标签。
    """
    p = os.path.join(config.ROOT, "scripts", "shoutu_daily.cmd")
    text = open(p, encoding="ascii").read()
    assert "goto :shoutu_done" in text, "兜底没有用 goto 绕开括号块"
    assert ":shoutu_done" in text, "缺少 :shoutu_done 标签"
    # 不允许在括号块里 set RC
    for line in text.splitlines():
        stripped = line.strip().lower()
        if stripped.startswith("set rc="):
            assert not line.startswith(" ") and not line.startswith("\t"), \
                "set RC= 出现在缩进行（多半在 if 括号块里）：%s" % line
