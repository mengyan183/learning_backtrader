# -*- coding: utf-8 -*-
"""Markdown 报告文件的**幂等段写入**（单一实现，供多个脚本复用）。

背景（同类非幂等 bug 反复踩）：
- `scripts/crude_factor_check.py` 首次修好：以**段标题**为幂等键，重复运行不产生重复段。
- `scripts/factor_screen_extend.py` 当时仍用 `open(..., "a")` **无条件追加**，
  实测 `evolution/factor-screen-results.md` 里 `## 登记已追加 F-007~F-009` 出现两次。
- 两处需求完全相同 ⇒ 提取到此处**单一实现**，两脚本共同 import，
  避免「同一逻辑两份实现」再次分叉。

用法：
    from fg_system.md_section import write_section
    write_section("evolution/factor-screen-results.md", report, "## 我的段标题")
"""
import os


def write_section(path, section, title):
    """幂等写入：把 section 写入 path。

    幂等键 = 标题 title。若文件中已存在该标题，则先删除从该标题（含其紧邻的
    `---` 分隔行）到文件末尾的旧内容，再写入新 section；否则追加到末尾。
    ⇒ 同一输入重复运行不会产生重复段，且重跑以最新结果替换旧段。

    注意：section 内容里**必须包含**与 title 完全一致的标题行（幂等键），
    否则下次运行找不到旧段而会再次追加。
    """
    old = ""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            old = f.read()
    if old:
        lines = old.splitlines()
        idx = None
        for i, ln in enumerate(lines):
            if ln.strip() == title.strip():
                idx = i
                break
        if idx is not None:
            # 标题前若紧邻 `---` 分隔行，一并删除，避免残留孤立分隔符
            cut = idx
            j = idx - 1
            while j >= 0 and lines[j].strip() == "":
                j -= 1
            if j >= 0 and lines[j].strip() == "---":
                cut = j
            head = "\n".join(lines[:cut]).rstrip()
            old = (head + "\n\n") if head else ""
        else:
            old = old.rstrip() + "\n\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(old + section.lstrip("\n") + ("" if section.endswith("\n") else "\n"))
