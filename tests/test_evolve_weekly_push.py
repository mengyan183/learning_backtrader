# -*- coding: utf-8 -*-
"""S-3 守卫：`evolve_weekly.py --push` 必须真的推得出去、且失败不静默。

背景（团队评审 2026-10-12）：
原实现
    subprocess.run([sys.executable, ".../feishu_send.py", out_path], check=False)
把周报路径当**位置参数**传，但 `feishu_send.py` 的 argparse **没有位置参数**
（只收 --chat/--dry-run/--pkg/…）⇒ argparse 直接 `SystemExit(2)`，
而 `check=False` 把非零返回吞掉 ⇒ 周报**永远推不出去且不报错**。

修法：写分片到 `dist/feishu/text/<pkg>-t001.txt` → 调 `feishu_send.py --pkg <pkg>`
（照 `evolve_approve.push_pending` 的已验证路径），并检查返回码。
"""
import importlib.util
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "evolve_weekly.py")


def _load():
    spec = importlib.util.spec_from_file_location("evolve_weekly", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _prepare(tmp_path, monkeypatch):
    ew = _load()
    monkeypatch.setattr(ew, "WEEKLY_DIR", str(tmp_path / "weekly"))
    monkeypatch.setattr(ew, "REPO", str(tmp_path))          # dist/ 落到 tmp
    monkeypatch.setattr(ew, "EVO", str(tmp_path / "evolution"))
    monkeypatch.setattr(sys, "argv", ["evolve_weekly.py", "--push"])
    return ew


def test_push_passes_pkg_not_positional(tmp_path, monkeypatch):
    """**守卫**：调用 feishu_send 必须带 `--pkg`，**不得**把路径当位置参数。"""
    ew = _prepare(tmp_path, monkeypatch)
    seen = {}

    class _R:
        returncode = 0

    def fake_run(cmd, **kw):
        seen["cmd"] = list(cmd)
        return _R()

    monkeypatch.setattr(ew.subprocess, "run", fake_run)
    ew.main()

    cmd = seen["cmd"]
    assert "--pkg" in cmd, "没传 --pkg ⇒ feishu_send 的 argparse 会 SystemExit(2)"
    # 位置参数检查：除脚本自身外，不得出现裸文件路径
    tail = [c for c in cmd[2:] if not c.startswith("-") and c != "feishu_send.py"]
    pkg_idx = cmd.index("--pkg")
    for c in tail:
        assert c == cmd[pkg_idx + 1], "出现了位置参数 %r ⇒ argparse 会直接退出" % c


def test_push_writes_chunk_under_dist(tmp_path, monkeypatch):
    """分片必须落在 `dist/feishu/text/<pkg>-t001.txt`（与 feishu_send --pkg 约定一致）。"""
    ew = _prepare(tmp_path, monkeypatch)
    seen = {}

    class _R:
        returncode = 0

    monkeypatch.setattr(ew.subprocess, "run",
                        lambda cmd, **kw: (seen.update(cmd=cmd), _R())[1])
    ew.main()

    pkg = seen["cmd"][seen["cmd"].index("--pkg") + 1]
    chunk = os.path.join(str(tmp_path), "dist", "feishu", "text", "%s-t001.txt" % pkg)
    assert os.path.exists(chunk), "未写分片 ⇒ feishu_send --pkg 找不到内容"
    assert open(chunk, encoding="utf-8").read().strip(), "分片为空"


def test_push_failure_is_not_swallowed(tmp_path, monkeypatch):
    """**守卫**：推送非零返回必须**退出非零**，不得静默成功。"""
    ew = _prepare(tmp_path, monkeypatch)

    class _R:
        returncode = 3

    monkeypatch.setattr(ew.subprocess, "run", lambda cmd, **kw: _R())
    try:
        ew.main()
    except SystemExit as e:
        assert e.code == 3
    else:
        raise AssertionError("推送失败被吞掉了（check=False 的老毛病）")
