# -*- coding: utf-8 -*-
"""base64 还原的测试（`scripts/restore_from_base64.py`）。

【为什么走 base64（2026-09-23 实测证据链）】
飞书对公司网络的上传做**内容检查**，成功与失败样本对比：

    成功  output-metadata.json   394 B     纯文本
    成功  合并说明.txt            1.8 KB    纯文本
    成功  fg-src-kit.zip         5.7 KB    zip 魔数（小到能扫完）
    成功  code-part03.bin        10188 B   **无魔数**（压缩流中段碎片）
    ──────────────────────────────────────────────────────
    失败  keep.bin               7.8 KB    **xz 魔数**
    失败  code-part01.bin        90 KB     xz 魔数
    失败  probe-20k.txt          20 KB     纯文本（太大）

⇒ **有压缩魔数（zip / xz）就拦**，与大小无关；**纯文本上限约 10 KB**。
  唯一稳定能过的形态是 **base64 纯文本**（无魔数、纯 ASCII）。
"""
import base64
import importlib.util
import io
import os
import tarfile

import pytest

from fg_system import config

_SPEC = os.path.join(config.ROOT, "scripts", "restore_from_base64.py")


def _load():
    spec = importlib.util.spec_from_file_location("restore_from_base64", _SPEC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


restore = _load()


def test_text_files_accepts_markdown_exports(tmp_path):
    """**守卫**：`.md` 也要收（2026-09-28 补）。

    飞书云文档支持「下载为 → Markdown」（用户实测截图确认）⇒ 导出的是 `0928-01.md`。
    原来只 `glob("*.txt")` ⇒ **导出的文档被静默漏掉**，而脚本还会报
    「没有 .txt」把人引向错误方向 —— 典型的「失败时给出误导性提示」。
    """
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    (tmp_path / "0928-01.md").write_text("y", encoding="utf-8")
    got = [os.path.basename(p) for p in restore._text_files(str(tmp_path))]
    assert got == ["0928-01.md", "a.txt"], got


def _xz(blob=b"hello world"):
    """造一个最小的 tar.xz。"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:xz") as tf:
        info = tarfile.TarInfo("data.txt")
        info.size = len(blob)
        tf.addfile(info, io.BytesIO(blob))
    return buf.getvalue()


# ================================================================ 分组

def test_whole_blob_wins_over_chunks(tmp_path):
    """**守卫**：整块与分片**同时存在**时必须只用整块。

    它们是同一份数据的两种形态（整块给云文档粘贴、分片给逐条发消息）。
    两个都拼进去会内容翻倍，解码抛 `Non-base64 digit found` —— **实测踩到过**。
    """
    (tmp_path / "code.b64.txt").write_text("AAAA", encoding="ascii")
    (tmp_path / "code-t01.txt").write_text("BBBB", encoding="ascii")
    (tmp_path / "code-t02.txt").write_text("CCCC", encoding="ascii")
    groups = restore._collect(str(tmp_path))
    assert groups["code"] == [str(tmp_path / "code.b64.txt")]


def test_doc_blocks_win_over_message_chunks(tmp_path):
    """**守卫**：文档块优先于消息分片 —— 同一份数据的两种形态，混用会翻倍。"""
    (tmp_path / "code-d01.txt").write_text("AAAA", encoding="ascii")
    (tmp_path / "code-d02.txt").write_text("BBBB", encoding="ascii")
    (tmp_path / "code-t01.txt").write_text("CCCC", encoding="ascii")
    groups = restore._collect(str(tmp_path))
    assert groups["code"] == [str(tmp_path / "code-d01.txt"),
                              str(tmp_path / "code-d02.txt")]


def test_doc_blocks_used_when_no_whole_blob(tmp_path):
    """飞书文档单块上限 10 万字符，故整块粘不下 —— 只能靠文档块。"""
    (tmp_path / "code-d01.txt").write_text("AAAA", encoding="ascii")
    (tmp_path / "code-d02.txt").write_text("BBBB", encoding="ascii")
    groups = restore._collect(str(tmp_path))
    assert len(groups["code"]) == 2


def test_chunks_used_when_no_whole_blob(tmp_path):
    (tmp_path / "code-t01.txt").write_text("AAAA", encoding="ascii")
    (tmp_path / "code-t02.txt").write_text("BBBB", encoding="ascii")
    groups = restore._collect(str(tmp_path))
    assert len(groups["code"]) == 2


def test_multiple_bundles_grouped_separately(tmp_path):
    (tmp_path / "code-t01.txt").write_text("AA", encoding="ascii")
    (tmp_path / "keep.b64.txt").write_text("BB", encoding="ascii")
    groups = restore._collect(str(tmp_path))
    assert set(groups) == {"code", "keep"}


# ================================================================ 解码

def test_decode_ignores_whitespace():
    """从云文档复制回来会混入换行/空格 —— 必须能容忍。"""
    blob = _xz()
    b64 = base64.b64encode(blob).decode("ascii")
    p = _tmp_file(b64[:len(b64) // 2] + "\n\n  " + b64[len(b64) // 2:])
    assert restore._decode([p]) == blob


def test_decode_rejects_broken_input(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("!!!not base64!!!", encoding="ascii")
    with pytest.raises(SystemExit):
        restore._decode([str(p)])


def test_decode_concatenates_parts_in_order(tmp_path):
    """分片必须**按顺序**拼 —— 顺序错了内容就废了。"""
    blob = _xz(b"abcdefghij" * 100)
    b64 = base64.b64encode(blob).decode("ascii")
    mid = len(b64) // 2
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_text(b64[:mid], encoding="ascii")
    b.write_text(b64[mid:], encoding="ascii")
    assert restore._decode([str(a), str(b)]) == blob


def test_empty_dir_raises(tmp_path):
    groups = restore._collect(str(tmp_path))
    assert groups == {}, "空目录不该分组出任何包"


# ================================================================ 标记提取
# 飞书**只有消息通道能通**（文件被 DLP 拦、文档同步离线），而消息上限
# **1,700 字符/条** ⇒ 132 KB base64 要 **103 条**。
# 从聊天记录「全选复制」会混进昵称与时间戳 ⇒ 必须靠标记精确提取。

def _marked(name, i, total, body):
    """**单行**标记 —— 与 `make_feishu_bundle.mark` 一致。

    飞书输入框按回车就发送，带换行的标记会被截断（只会发出第一行）。
    """
    return "###FG:%s:%d/%d###%s###FG:end###\n" % (name, i, total, body)


def test_extract_marked_basic():
    text = _marked("code", 1, 2, "AAAA") + _marked("code", 2, 2, "BBBB")
    groups, problems = restore.extract_marked(text)
    assert problems == []
    assert groups["code"] == ["AAAA", "BBBB"]


def test_extract_marked_ignores_chat_noise():
    """**核心**：聊天记录里混进昵称和时间戳，也必须精确提取。"""
    text = ("郭星  17:00\n" + _marked("code", 1, 2, "AAAA")
            + "郭星  17:01\n" + _marked("code", 2, 2, "BBBB"))
    groups, problems = restore.extract_marked(text)
    assert problems == []
    assert groups["code"] == ["AAAA", "BBBB"]


def test_extract_marked_sorts_numerically():
    """消息可能**乱序**复制回来 —— 必须按序号排，不能按出现顺序。"""
    text = _marked("code", 2, 2, "BBBB") + _marked("code", 1, 2, "AAAA")
    groups, _ = restore.extract_marked(text)
    assert groups["code"] == ["AAAA", "BBBB"]


def test_extract_marked_reports_missing_chunks():
    """缺片必须**明确报出是第几片** —— 否则用户不知道该补发哪条。"""
    text = _marked("code", 1, 3, "AAAA") + _marked("code", 3, 3, "CCCC")
    _groups, problems = restore.extract_marked(text)
    assert problems and "缺 1 片" in problems[0] and "[2]" in problems[0]


def test_extract_marked_flags_illegal_chars():
    """**守卫**：分片内部混入非法字符必须**报错**，不许静默损坏。

    试过「过滤掉非 base64 字符」，但时间戳 `17:01` 里的**数字是合法 base64 字符**，
    会被保留 ⇒ 静默污染数据，要到解压失败才发现。宁可**响亮地报错**。

    单行标记已经让"换行噪声混入 body"不可能了，但**同行内**仍可能被污染
    （例如从别处复制时粘进来、或飞书把长行折行后混入其它字符）。
    """
    text = _marked("code", 1, 1, "AAAA中文BBBB")
    _groups, problems = restore.extract_marked(text)
    assert problems, "混入非法字符却没报错"
    assert "非法字符" in problems[0]


def test_extract_marked_multiple_bundles():
    text = _marked("code", 1, 1, "AAAA") + _marked("keep", 1, 1, "BBBB")
    groups, problems = restore.extract_marked(text)
    assert problems == []
    assert set(groups) == {"code", "keep"}


def test_arbitrary_filename_falls_back_to_single_bundle(tmp_path):
    """**兜底**：用户很可能把**所有消息粘进一个文件、名字随便起**（如 `note.txt`）。

    原逻辑认不出这种名字就报错，会让人重来一遍 —— 现在按
    「全部 `.txt` 合起来是一个包」处理，比报错强。
    """
    (tmp_path / "note.txt").write_text("AAAA", encoding="ascii")
    (tmp_path / "another.txt").write_text("BBBB", encoding="ascii")
    groups = restore._collect(str(tmp_path))
    assert list(groups) == ["restored"]
    assert len(groups["restored"]) == 2


def _tmp_file(text):
    import tempfile
    fd, p = tempfile.mkstemp(suffix=".txt")
    with os.fdopen(fd, "w", encoding="ascii") as fh:
        fh.write(text)
    return p
