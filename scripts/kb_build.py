#!/usr/bin/env python3
"""知识库构建：YouTube 交易频道字幕 → ChromaDB（供 fg-qa/裁判检索）。
用法: .venv/bin/python scripts/kb_build.py          # 增量入库
      .venv/bin/python scripts/kb_build.py --full    # 重建集合
说明: 字幕 VTT 解析 → 分块 → 本地 embedding(Ollama bge-m3) → ChromaDB
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
SUB_DIR = REPO / "Data" / "kb" / "subtitles"
DB_DIR = REPO / "Data" / "kb" / "chroma"
META = REPO / "Data" / "kb" / "yt_meta.json"
COLLECTION = "yt_trading"
CHANNELS = {
    "Duomo": "https://www.youtube.com/@Duomoinitiative/videos",
    "SecretMindset": "https://www.youtube.com/@TheSecretMindset/videos",
    "TradingChannel": "https://www.youtube.com/@thetradingchannel/videos",
    "RaynerTeo": "https://www.youtube.com/@tradingwithrayner/videos",
    "ChatWithTraders": "https://www.youtube.com/@ChatWithTradersPodcast/videos",
    "PBoyle": "https://www.youtube.com/@PBoyle/videos",
    "BenFelix": "https://www.youtube.com/@BenFelixCSI/videos",
    "ThePlainBagel": "https://www.youtube.com/@ThePlainBagel/videos",
    "QuantPy": "https://www.youtube.com/@QuantPy/videos",
}
PROXY = "http://127.0.0.1:7890"
OLLAMA_URL = "http://127.0.0.1:11434"
EMBED_MODEL = os.getenv("FG_EMBED_MODEL", "bge-m3")


def load_meta():
    """拉取各频道最近视频 id/title/upload_date 元数据，写 yt_meta.json。"""
    meta = {}
    if META.exists():
        meta = json.loads(META.read_text())
    yt = subprocess.run(
        [".venv/bin/yt-dlp", "--proxy", PROXY, "--flat-playlist",
         "--print", "%(channel)s|%(id)s|%(title)s|%(upload_date)s",
         "--playlist-end", "30", "CH_URL"],
        capture_output=True, text=True, cwd=REPO)
    for name, url in CHANNELS.items():
        r = subprocess.run(
            [".venv/bin/yt-dlp", "--proxy", PROXY, "--flat-playlist",
             "--print", "%(id)s|%(title)s|%(upload_date)s",
             "--playlist-end", "30", url],
            capture_output=True, text=True, cwd=REPO)
        for line in r.stdout.splitlines():
            parts = line.split("|")
            if len(parts) < 3:
                continue
            vid, title, date = parts[0], parts[1], parts[2]
            meta.setdefault(vid, {})
            meta[vid].update({"channel": name, "title": title, "date": date})
    # flat-playlist 拿不到 upload_date 的视频逐条补拉（≤40 个/次）
    missing = [v for v, m in meta.items() if m.get("date", "NA") == "NA"]
    for vid in missing[:40]:
        r = subprocess.run(
            [".venv/bin/yt-dlp", "--proxy", PROXY, "--skip-download",
             "--print", "%(upload_date)s", f"https://www.youtube.com/watch?v={vid}"],
            capture_output=True, text=True, cwd=REPO)
        d = r.stdout.strip()
        if d and d != "NA":
            meta[vid]["date"] = d
    META.write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    return meta


def parse_vtt(path):
    """VTT → 纯文本（去时间戳行/cue序号/内嵌字级标签/重复行）。"""
    raw = path.read_text(encoding="utf-8", errors="ignore")
    lines = raw.splitlines()
    out, seen = [], set()
    for ln in lines:
        s = ln.strip()
        if not s or s == "WEBVTT":
            continue
        if s.isdigit():                       # cue 序号
            continue
        if "-->" in s:                        # 时间戳行
            continue
        if s.startswith(("Kind:", "Language:", "NOTE")):
            continue
        s = re.sub(r"<[^>]*>", "", s)         # 去内嵌 <c> / 时间标签
        s = s.replace("&nbsp;", " ").replace("&#39;", "'")
        s = re.sub(r"\s+", " ", s).strip()
        if not s:
            continue
        if s in seen:                         # 完全重复行
            continue
        seen.add(s)
        out.append(s)
    return " ".join(out)


def chunk_text(text, size=1800, overlap=200):
    """按句子边界分块，块间重叠。"""
    sents = re.split(r"(?<=[.!?])\s+", text)
    chunks, buf = [], ""
    for s in sents:
        if len(buf) + len(s) + 1 <= size:
            buf += (" " + s) if buf else s
        else:
            if buf:
                chunks.append(buf.strip())
            buf = s
    if buf:
        chunks.append(buf.strip())
    if len(chunks) == 1 and len(chunks[0]) > size * 1.5:   # 超大块二次切割
        chunks = []
        for i in range(0, len(text), size - overlap):
            chunks.append(text[i:i + size].strip())
    return [c for c in chunks if len(c) > 60]


def build(full=False):
    import chromadb
    from chromadb.utils.embedding_functions import OllamaEmbeddingFunction
    client = chromadb.PersistentClient(path=str(DB_DIR))
    if full and COLLECTION in [c.name for c in client.list_collections()]:
        client.delete_collection(COLLECTION)
    emb = OllamaEmbeddingFunction(url=OLLAMA_URL, model_name=EMBED_MODEL)
    col = client.get_or_create_collection(COLLECTION, embedding_function=emb)
    meta = load_meta()
    existing = set(col.get()["ids"]) if col.count() else set()
    added = 0
    for vtt in sorted(SUB_DIR.glob("*.vtt")):
        vid = vtt.stem.split(".")[0]
        if vid in existing:
            continue
        text = parse_vtt(vtt)
        if len(text) < 120:
            continue
        m = meta.get(vid, {})
        for i, ch in enumerate(chunk_text(text)):
            col.add(
                ids=[f"{vid}_{i}"],
                documents=[ch],
                metadatas=[{"video_id": vid, "channel": m.get("channel", ""),
                            "title": m.get("title", ""), "date": m.get("date", ""),
                            "chunk": i}],
            )
            added += 1
    print(f"入库完成: 新增 {added} 块, 集合共 {col.count()} 块 (embedding={EMBED_MODEL})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="重建集合")
    args = ap.parse_args()
    build(full=args.full)
