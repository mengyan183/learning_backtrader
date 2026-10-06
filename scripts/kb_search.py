#!/usr/bin/env python3
"""知识库检索：语义查询 YouTube 交易知识库（ChromaDB）。
用法: .venv/bin/python scripts/kb_search.py "止盈策略"
      .venv/bin/python scripts/kb_search.py "risk management" -n 5
      .venv/bin/python scripts/kb_search.py --top 只打印来源标题
"""
import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
DB_DIR = REPO / "Data" / "kb" / "chroma"
COLLECTION = "yt_trading"
OLLAMA_URL = "http://127.0.0.1:11434"
EMBED_MODEL = "bge-m3"


def search(query, n=4, top_only=False):
    import chromadb
    from chromadb.utils.embedding_functions import OllamaEmbeddingFunction
    client = chromadb.PersistentClient(path=str(DB_DIR))
    emb = OllamaEmbeddingFunction(url=OLLAMA_URL, model_name=EMBED_MODEL)
    col = client.get_or_create_collection(COLLECTION, embedding_function=emb)
    if col.count() == 0:
        print("知识库为空，先运行 scripts/kb_build.py")
        return
    res = col.query(query_texts=[query], n_results=n)
    for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0],
                               res["distances"][0]):
        ch = meta.get("channel", "?")
        title = meta.get("title", "?")
        date = meta.get("date", "?")
        if top_only:
            print(f"▶ [{ch}] {title} ({date})")
        else:
            print(f"【{ch}】{title}（{date}） 相关度 {1 - dist:.3f}")
            print(doc[:600])
            print("-" * 60)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("query", help="检索问题")
    ap.add_argument("-n", type=int, default=4)
    ap.add_argument("--top", action="store_true")
    args = ap.parse_args()
    search(args.query, n=args.n, top_only=args.top)
