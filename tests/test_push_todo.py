# -*- coding: utf-8 -*-
"""守卫：`push_todo.py` 的待办快照。

两件事：
1. **新增**（2026-10-12 用户定案 B）：快照必须列出【Mac 端待执行】任务 ——
   `docs/mac-tasks.md` 是 Windows 端登记的「仅 Mac 可做（需公网 / 需真实 Data）」表；
   Mac 有公网可直读，但要让 Mac 在收到「同步待办」时也看到**自己**该做什么，
   故并入快照（**复用已在 Mac 跑的脚本，不新建推送通道**）。
   ⚠️ 与 `windows-tasks.md` 的区别：那张表必须靠飞书推（Windows 无公网）——
   这点别在后续重构里"对称化"掉。
2. **修既有 bug**（`docs/review/规划审查-2026-10-10.md` 差异 1 的根因）：
   原判定 `re.search(r"\\|\\s*✅\\s*\\|", line)` **只匹配「单元格里恰好只有一个 ✅」**，
   真实状态列写成 `✅ sync_1010e 入库（b5e9ec4）` / `✅ 完成` 时**匹配不上**
   ⇒ 已完成的行被当成待办**反复下发**。改为读**最后一列**再判 ✅。
"""
import importlib.util
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "push_todo.py")

MAC_TASKS = """# Mac 端待执行任务清单

## 待做任务（仅 Mac 可做：需公网 / 需真实 Data）

| 编号 | 任务 | 说明与来源 | 验收标准 | 状态 |
|---|---|---|---|---|
| MT-01 | **A5 闸门补 `inv_vol` 组合权重轨** | 说明一 | 验收一 | 待做 |
| MT-02 | 加密侧真实轨 | 说明二 | 验收二 | ✅ 完成 |

## 默认动作（不占编号）

- 每日链

## 已完成（留痕）

| 编号 | 任务 | 完成依据 | 完成日期 |
|---|---|---|---|
| MT-99 | 已完成区不该被收进来 | x | 2026-10-12 |
"""

WIN_TASKS = """# Windows 端待开发任务清单

## 待做任务（Windows 可立即开工）

| 编号 | 任务 | 说明与来源 | 验收标准 | 状态 |
|---|---|---|---|---|
| WT-15 | fg_system/models/ 补测试 | 说明 | 验收 | 待做 |
| WT-13 | 代码审查剩余项修复 | 说明 | 验收 | ✅ sync_1010k 入库（55c0e4c，18 文件）：已落地 |

## 默认动作（不占编号）

- 全量 pytest 回归

## 已完成（留痕）

| 编号 | 任务 | 完成依据 | 完成日期 |
|---|---|---|---|
| WT-01 | 已完成区不该被收 | x | 2026-10-10 |
"""


def _load():
    spec = importlib.util.spec_from_file_location("push_todo", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_parse_mac_tasks_picks_pending_only(tmp_path):
    """只收「待做任务」表中状态非 ✅ 的行；✅ 行与已完成区都不得再下发。"""
    pt = _load()
    p = tmp_path / "mac-tasks.md"
    p.write_text(MAC_TASKS, encoding="utf-8")

    got = pt.parse_mac_tasks(str(p))

    assert len(got) == 1, got
    assert got[0].startswith("MT-01 "), got
    assert "**" not in got[0], "快照是纯文本，任务名不该带 markdown 强调符"
    joined = "".join(got)
    assert "MT-02" not in joined, "状态 ✅ 的行不得再下发"
    assert "MT-99" not in joined, "「已完成」区的行不得被收进来"


def test_parse_win_tasks_excludes_done_status_cell(tmp_path):
    """**回归守卫**（既有 bug）：状态列是 `✅ sync_1010k 入库（…）` 的行不得再下发。

    旧判定 `\\|\\s*✅\\s*\\|` 对 `| ✅ sync_1010k 入库（55c0e4c，18 文件）：已落地 |`
    匹配不上 ⇒ WT-13 会被当成待办反复推给 Windows。
    """
    pt = _load()
    p = tmp_path / "windows-tasks.md"
    p.write_text(WIN_TASKS, encoding="utf-8")

    got = pt.parse_win_tasks(str(p))

    assert len(got) == 1, got
    assert got[0].startswith("WT-15 "), got
    assert "WT-13" not in "".join(got), "已完成（✅ 前缀带说明）的行不得再下发"
    assert "WT-01" not in "".join(got), "「已完成」区的行不得被收进来"


def test_parse_mac_tasks_missing_file_is_reported(tmp_path):
    """表不存在时必须报错行（而非静默空），与 parse_win_tasks 行为一致。"""
    pt = _load()
    got = pt.parse_mac_tasks(str(tmp_path / "nope.md"))
    assert len(got) == 1 and got[0].startswith("ERR "), got


def test_summary_contains_mac_section(tmp_path, monkeypatch):
    """**守卫**：快照里必须有【Mac 端待执行】段，且含 MT 编号。"""
    pt = _load()
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "mac-tasks.md").write_text(MAC_TASKS, encoding="utf-8")
    monkeypatch.setattr(pt, "REPO", str(tmp_path))
    monkeypatch.setattr(pt, "git_head", lambda: "abc1234")

    out = pt.build_summary()

    assert "【Mac 端待执行" in out, "快照缺 Mac 端段落 ⇒ Mac 看不到自己该执行什么"
    assert "MT-01" in out
    assert "docs/mac-tasks.md" in out, "底部「完整待办」应指向本表"


def test_summary_mac_section_empty_when_no_pending(tmp_path, monkeypatch):
    """无待做时该段必须显式写「（无）」，不得整段消失（否则看不出是漏读还是没任务）。"""
    pt = _load()
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "mac-tasks.md").write_text(
        "# Mac\n\n## 待做任务（x）\n\n| 编号 | 任务 | 说明 | 验收 | 状态 |\n"
        "|---|---|---|---|---|\n| MT-01 | a | b | c | ✅ 完成 |\n\n## 默认动作\n- x\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(pt, "REPO", str(tmp_path))
    monkeypatch.setattr(pt, "git_head", lambda: "abc1234")

    out = pt.build_summary()

    assert "【Mac 端待执行" in out
    assert "（无）" in out


def test_repo_is_derived_not_hardcoded():
    """**守卫**：`REPO` 必须由脚本位置推导（跨端通用）。

    原实现硬编码 `"/Users/xingguo/learning_backtrader"` ⇒ 在 Windows 上必然读错目录
    （只能靠 monkeypatch 打桩才测得动）。本仓库 68+ 个脚本统一用
    `os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`，此处对齐惯例。
    """
    pt = _load()
    assert pt.REPO == REPO, f"REPO 应为仓库根 {REPO}，实际 {pt.REPO}"
    # 硬编码守卫：源码中不得出现 Mac 绝对路径字面量（推导结果在 Mac 上
    # 以 /Users 开头是正常现象，不能据此断言）。
    src = open(SCRIPT, encoding="utf-8").read()
    assert "/Users/xingguo/learning_backtrader" not in src, \
        "不得硬编码 Mac 绝对路径"
    assert os.path.isdir(os.path.join(pt.REPO, "docs")), "REPO 下应能看到 docs/"
