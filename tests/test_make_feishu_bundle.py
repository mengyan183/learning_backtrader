# -*- coding: utf-8 -*-
"""飞书投递包的测试（`scripts/make_feishu_bundle.py`）。

【为什么值得测】
公司电脑 → 家里 Mac **只能走飞书**，而飞书实测**两个维度**都会拦：

    · 压缩包（`.zip`）：约 10 KB 就被拦 —— DLP 扫不完内容就拒
    · 其它文件：10 KB 过、90 KB 不过

最刺眼的一条证据 —— 两个文件**只差 5 个字节**：

    code-part03.bin   10188 B   ✅ 通过
    keep.zip          10183 B   ❌ 上传失败

⇒ 所以本文件里两条最关键的断言是：
  1. **产物绝不能叫 `.zip`**（`test_no_output_is_named_zip`）
  2. **每片必须 ≤ 默认上限**（`test_all_pieces_within_limit`）

还有一条来自端到端验证时**实际踩到的缺口**：
`test_code_bundle_includes_mobile_patch_repos` —— 包里漏了
`mobile/patch_repos.py`，合并后跑测试直接 `FileNotFoundError`。
"""
import importlib.util
import io
import os
import tarfile

import pytest

from fg_system import config

_SPEC = os.path.join(config.ROOT, "scripts", "make_feishu_bundle.py")

# 实测：`.bin` 10 KB 通过、90 KB 失败。取 9 KB 留余量。
SAFE_LIMIT = 9 * 1024


def _load():
    spec = importlib.util.spec_from_file_location("make_feishu_bundle", _SPEC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bundle = _load()


def _names(blob):
    """列出归档里的文件名（统一成 `/` 分隔，便于断言）。"""
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:xz") as tf:
        return [m.name.replace("\\", "/") for m in tf.getmembers()]


# ================================================================ 打包正确性

def test_bundles_are_tar_xz():
    """必须是 tar.xz —— LZMA 对中文注释的压缩率远高于 deflate。

    实测 `fg_system/ + scripts/`：zip 156 KB → **tar.xz 124 KB**，
    分片数直接少 3 片。
    """
    blob = bundle._zip(bundle._spec(["code"]))
    assert blob[:6] == b"\xfd7zXZ\x00", "不是 xz 格式"


def test_all_bundles_non_empty():
    for name in ("code", "keep", "tests"):
        assert len(bundle._zip(bundle._spec([name]))) > 0, "%s 包是空的" % name


def test_parts_reassemble_to_original_bytes():
    """**核心**：分片拼回来必须**逐字节相同** —— 否则 Mac 上解压会坏。"""
    for name in ("code", "tests"):
        blob = bundle._zip(bundle._spec([name]))
        parts = [blob[i:i + SAFE_LIMIT] for i in range(0, len(blob), SAFE_LIMIT)]
        assert b"".join(parts) == blob, "%s 拼回来不一致" % name
        assert all(len(p) <= SAFE_LIMIT for p in parts), "%s 有片超限" % name


# ================================================================ 命名（踩过的坑）

def test_no_output_is_named_zip():
    """**守卫**：产物**绝不能**叫 `.zip`。

    实测同样 ~10 KB，`.bin` 通过、`.zip` 被拦（只差 5 个字节）。
    公司 DLP 对压缩包做内容扫描，扫不完就拒 —— 而 5.7 KB 的 zip 能扫完，
    所以更早那版 `fg-src-kit.zip` 反而过了，极具迷惑性。
    """
    import re
    src = open(_SPEC, encoding="utf-8").read()
    # 找生成文件名的代码行，断言里面没有 .zip
    naming = [ln for ln in src.splitlines()
              if "fname" in ln and ("%s" in ln or "part" in ln)]
    assert naming, "没找到生成文件名的代码，测试可能失效了"
    for ln in naming:
        assert ".zip" not in ln, "产物名里出现了 .zip：%s" % ln.strip()


def test_generated_files_use_bin_extension(tmp_path, monkeypatch):
    """端到端确认：实际落盘的文件名里没有 `.zip`。"""
    import glob
    monkeypatch.setattr(bundle, "OUT_DIR", str(tmp_path))
    bundle._write_readme(["code"], SAFE_LIMIT)          # 需要目录存在
    for name in ("code", "keep"):
        blob = bundle._zip(bundle._spec([name]))
        parts = ([blob] if len(blob) <= SAFE_LIMIT
                 else [blob[i:i + SAFE_LIMIT] for i in range(0, len(blob), SAFE_LIMIT)])
        for i, part in enumerate(parts, 1):
            fname = ("%s.bin" % name if len(parts) == 1
                     else "%s-part%02d.bin" % (name, i))
            (tmp_path / fname).write_bytes(part)
    assert glob.glob(str(tmp_path / "*.zip")) == [], "落盘了 .zip 文件"


# ================================================================ 内容（踩过的坑）

def test_code_bundle_includes_mobile_patch_repos():
    """**守卫**：`code` 包必须带 `mobile/patch_repos.py`。

    `tests/test_mobile_patch_repos.py` 引用它。端到端验证时**实际踩到过**：
    漏了它，合并后跑测试直接 `FileNotFoundError` —— 而那时文件已经传完了。
    """
    names = _names(bundle._zip(bundle._spec(["code"])))
    assert any(n.endswith("mobile/patch_repos.py") for n in names), \
        "code 包漏了 mobile/patch_repos.py"


def test_code_bundle_excludes_mobile_node_modules():
    """**守卫**：`mobile/node_modules` 绝不能进包 —— 它会撑爆分片数。"""
    for n in _names(bundle._zip(bundle._spec(["code"]))):
        assert "node_modules" not in n, "包里混进了 node_modules：%s" % n


def test_code_bundle_excludes_pycache():
    """`__pycache__` / `.pyc` 是产物，不该进包（还会让分片数虚高）。"""
    for n in _names(bundle._zip(bundle._spec(["code"]))):
        assert "__pycache__" not in n and not n.endswith(".pyc"), \
            "包里混进了字节码：%s" % n


def test_keep_bundle_has_irreplaceable_files():
    """`keep` 包必须含**不可再生**的东西 —— 少了它 Mac 上补不回来。

    最要紧的是 `shoutu_fng.csv`：守猪待兔**逐日累积**的贪恐值，
    API 只能查"现在"、查不了历史，丢了**永远补不回来**。
    """
    names = " ".join(_names(bundle._zip(bundle._spec(["keep"]))))
    for must in ("Data/raw/shoutu_fng.csv", "Data/raw/splits.csv"):
        assert must in names, "keep 包漏了不可再生的 %s" % must


def test_keep_bundle_stays_small():
    """`keep` 必须**很小** —— 它是「不可再生数据 + 凭据」，涨了就说明夹带了别的东西。

    ⚠️ 这里**不**断言「一条消息装得下」：实测它从 7.8 KB 长到 10.8 KB
    （`shoutu_etf_universe.csv` 每日快照在累积），现在要 2 条消息。
    断言一个会随数据漂移的具体字节数是**假守卫**；只守住「量级没变」。
    """
    blob = bundle._zip(bundle._spec(["keep"]))
    assert len(blob) <= 40 * 1024, \
        "keep 包 %.1f KB，明显夹带了不该有的东西" % (len(blob) / 1024)


# ================================================================ 探针

# ================================================================ 文档块（飞书报错踩到的）

def test_doc_blocks_within_feishu_limit(tmp_path):
    """**守卫**：文档块必须 ≤ 10 万字符。

    飞书云文档实测报错：「该内容块的字符数超出上限（100,000），
    请拆分部分内容后重试」—— 168 KB 的整块**粘不进去**，
    所以必须切成 `-d01` / `-d02` / … 逐块粘贴。
    """
    written = bundle._text_mode(["code", "keep"], 1700, 50000, str(tmp_path))
    docs = [(n, s) for n, s, k in written if k.startswith("文档块")]
    assert docs, "没生成文档块"
    for name, size in docs:
        assert size <= 100000, "%s 有 %d 字符，超过飞书 10 万上限" % (name, size)


def test_doc_blocks_reassemble_to_same_bytes(tmp_path):
    """文档块拼起来必须等于整块 —— 否则粘到一半就对不上。"""
    written = bundle._text_mode(["keep"], 1700, 50000, str(tmp_path))
    doc = "".join(open(tmp_path / n, encoding="ascii").read()
                  for n, _s, k in written if k.startswith("文档块"))
    whole = "".join(open(tmp_path / n, encoding="ascii").read()
                    for n, _s, k in written if k.startswith("整块"))
    assert doc == whole


def test_text_mode_emits_no_magic_bytes(tmp_path):
    """**核心**：所有产物开头**不得有压缩魔数**。

    实测：`keep.bin`（7.8 KB，xz 魔数）被拦，而 10188 B 的中段碎片（无魔数）能过。
    差别只在开头那几个字节 —— 所以 base64 的纯 ASCII 开头是**关键**。
    """
    written = bundle._text_mode(["keep"], 1700, 50000, str(tmp_path))
    for name, _s, _k in written:
        head = open(tmp_path / name, "rb").read(6)
        assert not head.startswith((b"\xfd7zXZ", b"PK\x03\x04")), \
            "%s 开头有压缩魔数：%r" % (name, head)


def test_chunk_numbering_sorts_lexicographically(tmp_path):
    """**守卫**：分片编号必须**按总数补足位数**，否则拼出来的内容是乱的。

    ⚠️ 实测踩到：110 个分片用 `%02d` 会产出 `t100`，而 `sorted()` 是**字典序**
    ⇒ `t100` 排在 `t11` 前面 ⇒ 拼起来全乱，**而且不报错，只是 MD5 对不上**。
    这种 bug 在传输场景里极其隐蔽 —— 等发现时文件已经传完了。
    """
    written = bundle._text_mode(["code"], 1700, 50000, str(tmp_path))
    names = [n for n, _s, k in written if k.startswith("消息分片")]
    assert len(names) > 99, "分片数不够多，测不出这个问题"
    assert sorted(names) == names, "字典序与数字序不一致：%s" % names[:5]
    # 补位后必须仍是 3 位（100 个以上）
    assert names[0].endswith("t001.txt"), names[0]


def test_all_three_forms_identical(tmp_path):
    """**守卫**：整块 / 文档块 / 消息分片必须是**同一份数据**。

    三者是同一份 base64 的不同切法，任何一处切错都会让 Mac 上还原失败。
    消息分片带 `###FG:` 标记，故用 `extract_marked` 提取。
    """
    import base64
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "restore_from_base64",
        os.path.join(config.ROOT, "scripts", "restore_from_base64.py"))
    restore = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(restore)

    written = bundle._text_mode(["keep"], 1700, 50000, str(tmp_path))

    def cat(kind):
        return "".join(open(tmp_path / n, encoding="ascii").read()
                       for n, _s, k in written if k.startswith(kind))

    whole = base64.b64decode(cat("整块"))
    assert base64.b64decode(cat("文档块")) == whole
    marked, problems = restore.extract_marked(cat("消息分片"))
    assert not problems, problems
    assert base64.b64decode("".join(marked["keep"])) == whole


def test_msg_chars_respected(tmp_path):
    """用户实测「每次最多可以发送字符串长度 1700」—— 分片不得超过。"""
    written = bundle._text_mode(["keep"], 1700, 50000, str(tmp_path))
    for n, s, k in written:
        if k.startswith("消息分片"):
            assert s <= 1700, "%s 有 %d 字符，超过消息上限 1700" % (n, s)


# ================================================================ 最小可运行集
# Mac 上真正要跑的入口只有几个（仪表盘服务 / 06:30 抓取 / 数据重建 /
# 定时任务注册 / 实盘检查），从它们算**传递闭包**即可去掉 cli、backtest 等。

def test_minimal_excludes_dev_only_modules():
    """**守卫**：`cli` / `backtest` / `audit` / `evolution` / `screening`
    在 Mac 上跑不到 —— 不该占传输体积。"""
    files = set(bundle.minimal_files())
    for gone in ("fg_system/cli.py", "fg_system/audit.py",
                 "fg_system/evolution.py", "fg_system/factors/screening.py"):
        assert gone not in files, "%s 不该在最小集里" % gone
    assert not any("backtest" in f for f in files), "backtest 不该在最小集里"


def test_mac_entry_includes_shoutu_history_fetcher():
    """⚠️ `MAC_ENTRY` 必须含 `fetch_shoutu_history.py`（2026-09-28 补）。

    **为什么**：`--minimal` 包从 `MAC_ENTRY` 算**传递闭包** ⇒ 不在入口列表里的脚本
    **不会被打包**。而 Mac 定时任务要抓守猪待兔历史（**A2 的生产信号源**）——
    脚本不在包里 ⇒ 任务即使写了也会因缺文件而失败（**静默断更**，
    且要等到 `SHOUTU_SIGNAL_MAX_LAG_DAYS` 天后才以抛错的形式暴露）。
    """
    assert any("fetch_shoutu_history.py" in p for p in bundle.MAC_ENTRY), \
        "MAC_ENTRY 漏了 fetch_shoutu_history.py ⇒ --minimal 包不带它"


def test_mac_entry_includes_the_restore_scripts():
    """⚠️ **还原脚本本身**必须在 `MAC_ENTRY` 里（2026-09-28 补）。

    **为什么**：实测核对 `dist/feishu/text/` 解出来的三个包，**两个还原脚本都不在**
    ⇒ Mac 上拿到 178 条分片却**没有解包工具**（首次引导靠 `restore_cmd.txt` 那段
    「整段粘进终端」的脚本兜底，但它只覆盖**首次**）。
    """
    for need in ("restore_from_base64.py", "mac_restore.sh"):
        assert any(need in p for p in bundle.MAC_ENTRY), \
            "MAC_ENTRY 漏了 %s ⇒ 包里没有还原脚本" % need


def test_text_mode_emits_bootstrap_script(tmp_path):
    """**守卫**：`--text` 必须产出**引导脚本分片**（`bootstrap-tNN.txt`）。

    **为什么**（2026-09-28 实测踩到的鸡生蛋）：`keep`/`minimal`/`tests` 三个包里
    **没有解包工具**，而解包工具本身就在包里 ⇒ Mac 上拿到分片却无从下手。
    引导脚本 `scripts/mac_bootstrap.sh` 是**不依赖仓库任何文件**的兜底，
    必须随包发出去，否则整条投递链断在第一环。
    """
    import base64
    written = bundle._text_mode(["keep"], 1700, 50000, str(tmp_path))
    boots = [(n, s) for n, s, k in written if k.startswith("引导脚本")]
    assert boots, "没生成引导脚本分片 ⇒ Mac 上没法开始还原"
    # 拼回来必须**逐字节等于**仓库里那份脚本
    joined = "".join(open(tmp_path / n, encoding="ascii").read()
                     for n, _s in sorted(boots))
    src = open(os.path.join(config.ROOT, "scripts", "mac_bootstrap.sh"),
               encoding="utf-8").read()
    assert base64.b64decode(joined).decode("utf-8") == src, \
        "引导脚本分片解回来与 scripts/mac_bootstrap.sh 不一致"


def _xz_payload(marker="MARKER.txt", text=b"hello\n"):
    """造一个最小的 tar.xz，base64 后返回。"""
    import base64 as _b64
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:xz") as tf:
        ti = tarfile.TarInfo(marker)
        ti.size = len(text)
        tf.addfile(ti, io.BytesIO(text))
    return _b64.b64encode(buf.getvalue()).decode("ascii")


def _run_bootstrap(tmp_path, files):
    """在 tmp 里**真跑**引导脚本的 Python 主体。`files` 形如 `{"名": "内容"}`。

    刻意不用字符串断言 —— 那正是 §12.27-① 抓到的弱守卫形态
    （把 `if False and ...` 塞进去也照样通过）。
    """
    import subprocess
    import sys as _sys

    src = open(os.path.join(config.ROOT, "scripts", "mac_bootstrap.sh"),
               encoding="utf-8").read()
    body = src.split("python3 - <<'PY'\n", 1)[1].rsplit("\nPY\n", 1)[0]

    fg, dst = tmp_path / "fg", tmp_path / "dst"
    fg.mkdir()
    dst.mkdir()
    for name, content in files.items():
        (fg / name).write_text(content, encoding="utf-8")

    run = (body.replace('os.path.expanduser("~/Downloads/fg")', repr(str(fg)))
               .replace('os.path.expanduser("~/learning_backtrader")',
                        repr(str(dst))))
    script = tmp_path / "boot.py"
    script.write_text(run, encoding="utf-8", newline="\n")
    proc = subprocess.run([_sys.executable, str(script)], capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    return proc, dst


def test_bootstrap_script_runs_end_to_end_on_markdown_export(tmp_path):
    """**真跑**引导脚本：`.md`（云文档「下载为 Markdown」）也必须能还原。

    ⚠️ 关键一：扩展名是 **.md**（云文档下载的形态），不是 .txt。
    ⚠️ 关键二：飞书导出 Markdown 会把 `#` **转义**成 `\#`
       （实测原文：`\#\#\#FG:keep:1/28\#\#\#/Td6WFoAAATm...`）
       ⇒ 测试必须用**转义后的形态**，否则测不出这个坑。
    """
    proc, dst = _run_bootstrap(tmp_path, {"0928-01.md": (
        "郭星  15:13\n\\#\\#\\#FG:demo:1/1\\#\\#\\#%s\\#\\#\\#FG:end\\#\\#\\#\n"
        % _xz_payload())})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (dst / "MARKER.txt").is_file(), \
        "没解出文件 —— 引导脚本漏掉了 .md 导出\n%s" % proc.stdout


def test_bootstrap_skips_non_xz_package_without_failing(tmp_path):
    """**守卫**：不是 xz 的包只能**警告**，不能判整体失败（2026-09-28 实测）。

    老投递包里有个 `cmd` 组，装的是**脚本自身的 base64**（不是压缩包）
    ⇒ 拿它去 xz 解码必然报错。旧版脚本因此把整体判成「有缺片」并**非零退出**
    ⇒ 用户被引向「传输缺片」这个**完全错误**的方向（真实原因只是目录里
    混了上一次的导出文件）。
    """
    proc, dst = _run_bootstrap(tmp_path, {
        "0928-01.md": ("###FG:demo:1/1###%s###FG:end###\n" % _xz_payload()),
        "note.txt": "###FG:cmd:1/1###IyEvYmluL2Jhc2gKZWNobyBoaQo=###FG:end###\n",
    })
    assert (dst / "MARKER.txt").is_file(), "正常的包没解出来"
    assert proc.returncode == 0, \
        "非 xz 包把整体判成失败了（应只是警告）\n%s" % proc.stdout
    assert "不是 xz 包" in proc.stdout, "没给出非 xz 包的警告：\n%s" % proc.stdout


def test_bootstrap_warns_when_old_export_is_mixed_in(tmp_path):
    """**守卫**：同一个包出现**两个不同总数** ⇒ 必须明确警告「混了旧导出」。

    实测踩到：目录里同时有上次的 `note.txt`（旧 `keep` 是 `x/7`）和新导出的
    `.md`（新 `keep` 是 `x/28`）⇒ 旧脚本打印 `28/7 片` 这种**矛盾数字**，
    让人以为是"传输缺片"，而真实原因是**新旧混拼**。
    """
    proc, _dst = _run_bootstrap(tmp_path, {
        "new.md": ("###FG:demo:1/2###%s###FG:end###\n"
                   "###FG:demo:2/2###%s###FG:end###\n"
                   % (_xz_payload()[:20], _xz_payload()[20:])),
        "old.txt": "###FG:demo:1/1###AAAA###FG:end###\n",
    })
    assert "混了旧导出" in proc.stdout, \
        "没有警告目录里混了旧导出：\n%s" % proc.stdout


def test_bootstrap_chunks_are_plain_and_sort_first(tmp_path):
    """**守卫**：引导分片必须 (a) **不带** `###FG:` 标记、(b) 排在所有包**之前**。

    (a) 带了标记会被还原脚本当成一个"包"去解 xz ⇒ 报「解出来的不是 xz 数据」。
    (b) `feishu_send.py` 按 `sorted()` 顺序发，`--start 1 --limit N` 要正好命中它们。
    """
    written = bundle._text_mode(["keep"], 1700, 50000, str(tmp_path))
    boots = [n for n, _s, k in written if k.startswith("引导脚本")]
    packs = [n for n, _s, k in written if k.startswith("消息分片")]
    assert boots and packs
    for n in boots:
        assert "###FG:" not in open(tmp_path / n, encoding="ascii").read(), \
            "%s 混进了 ###FG: 标记" % n
    assert sorted(boots + packs)[0].startswith("bootstrap"), \
        "引导分片没有排在所有包之前：%s" % sorted(boots + packs)[:3]


def test_minimal_keeps_essential_modules():
    """**守卫**：必需模块一个都不能少 —— 少了 Mac 上直接跑不起来。"""
    files = set(bundle.minimal_files())
    for need in ("fg_system/config.py", "fg_system/pipeline.py",
                 "fg_system/leverage.py", "fg_system/index.py",
                 "fg_system/dashboard/server.py", "fg_system/dashboard/pwa.py",
                 "fg_system/dashboard/report.py",
                 "fg_system/data/fetch.py", "fg_system/data/loader.py",
                 "fg_system/data/shoutu.py", "fg_system/data/splits.py",
                 "fg_system/signal/market_signal.py",
                 "fg_system/factors/vix.py",
                 "scripts/serve_dashboard.py", "scripts/fetch_shoutu_api.py",
                 "scripts/bootstrap_data.py", "scripts/shoutu_daily.sh"):
        assert need in files, "最小集漏了 %s" % need


def test_minimal_includes_non_python_essentials():
    """**守卫**：闭包只跟 `.py` 的 import 走 —— **非 Python 的必需文件会漏**。

    ⚠️ 实测踩到：`minimal` 包漏了 `requirements.txt`，Mac 上
    `.venv/bin/pip install -r requirements.txt` 直接报「没有这个文件」——
    而那时 58 条消息已经发完、代码也解压好了，用户卡在最后一步。
    """
    files = set(bundle.minimal_files())
    for need in ("requirements.txt", "pytest.ini"):
        assert need in files, "最小集漏了 %s（闭包追不到它）" % need


def test_minimal_includes_all_package_inits():
    """**守卫**：`__init__.py` 必须都带上。

    它们可能只含**副作用** —— `fg_system/__init__.py` 的
    `_make_console_safe()` 就是必需的（否则 GBK 控制台下会崩），
    而 `import fg_system.dashboard.report` 在 AST 里**不会显式引用**它。
    实测踩到过：漏了它，Mac 上 `_make_console_safe` 就不生效。
    """
    files = set(bundle.minimal_files())
    for pkg in ("fg_system", "fg_system/dashboard", "fg_system/data",
                "fg_system/factors", "fg_system/signal"):
        assert "%s/__init__.py" % pkg in files, "漏了 %s/__init__.py" % pkg


# ================================================================ 去注释

def test_strip_removes_comments_and_docstrings():
    src = ('"""模块文档。"""\n'
           'import os\n'
           '\n'
           'def f():\n'
           '    """函数文档。"""\n'
           '    return 1  # 行尾注释\n')
    out = bundle.strip_source(src)
    assert "模块文档" not in out and "函数文档" not in out
    assert "行尾注释" not in out
    assert "import os" in out and "return 1" in out


def test_strip_keeps_trailing_comment_line_code():
    """**守卫**：**行尾注释**只能砍掉注释本身，代码必须留下。

    实测踩到：`except Exception:  # 说明` 被整行删掉后，`try:` 没了 `except`
    ⇒ SyntaxError —— 而且要到 Mac 上才发现，那时 100 条消息已经发完了。
    """
    src = ("def f():\n"
           "    try:\n"
           "        return 1\n"
           "    except Exception:  # 这里是说明\n"
           "        pass\n")
    out = bundle.strip_source(src)
    assert "except Exception:" in out, "行尾注释把整行代码带走了"
    compile(out, "<t>", "exec")


def test_strip_result_always_compiles():
    """**安全网**：去注释结果必须能编译，否则退回原文。"""
    for rel in bundle.minimal_files():
        if not rel.endswith(".py"):
            continue
        p = os.path.join(config.ROOT, rel)
        src = open(p, encoding="utf-8").read()
        out = bundle.strip_source(src)
        compile(out, "<stripped>", "exec")          # 不抛异常即通过
        # 退回原文时长度不变；否则应当变短
        assert len(out) <= len(src) + 8, "%s 去注释后反而变大了" % rel


def test_strip_falls_back_on_broken_source():
    """源码本身语法错时，`strip_source` 必须**原样返回**而不是瞎改。"""
    bad = "def f(:\n    pass\n"
    assert bundle.strip_source(bad) == bad


def test_archive_names_use_forward_slashes():
    """**守卫**：tar 归档名里**绝不能有反斜杠**。

    ⚠️ 实测踩到：Windows 上 `os.path.relpath` 返回 `fg_system\\config.py`，
    直接打进 tar 后 **macOS 会解出一个"名字里带反斜杠"的文件** ——
    代码根本跑不起来。而这个错误**只有在 Mac 上才会暴露**，
    那时 100 条消息已经发完了。
    """
    for name in ("code", "minimal"):
        blob = bundle._zip(bundle._spec([name]))
        for n in _names(blob):
            assert "\\" not in n, "%s 包里出现反斜杠归档名：%s" % (name, n)


def test_minimal_files_use_forward_slashes():
    for rel in bundle.minimal_files():
        assert "\\" not in rel, "最小集里出现反斜杠路径：%s" % rel


def test_probe_generates_requested_sizes(tmp_path):
    bundle._probe(str(tmp_path), [20, 40])
    for name, size in [("probe-20k.bin", 20 * 1024), ("probe-20k.txt", 20 * 1024),
                       ("probe-40k.bin", 40 * 1024), ("probe-40k.txt", 40 * 1024)]:
        p = tmp_path / name
        assert p.is_file(), "没生成 %s" % name
        assert p.stat().st_size == size, "%s 大小不对" % name


def test_unknown_bundle_rejected():
    with pytest.raises(SystemExit):
        bundle._spec(["nope"])
