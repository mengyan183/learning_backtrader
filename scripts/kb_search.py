#!/usr/bin/env python3
"""知识库检索：语义查询 YouTube 交易知识库（ChromaDB）。
用法: .venv/bin/python scripts/kb_search.py "止盈策略"
      .venv/bin/python scripts/kb_search.py "risk management" -n 5
      .venv/bin/python scripts/kb_search.py "宏观" --since 90    只看近90天观点优先
      .venv/bin/python scripts/kb_search.py "factor investing" --channel BenFelix,QuantPy
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


def search_results(query, n=4, since=None, channel=None):
    """结构化检索：返回 list[dict(channel,title,date,score,snippet)]。库接口，供其他脚本 import。
    since: 近 N 天观点优先（有日期且在 N 天内者前置，NA/超期者排后，不排除）。
    channel: 逗号分隔频道名过滤（如 'BenFelix,QuantPy'）。"""
    import datetime
    import chromadb
    from chromadb.utils.embedding_functions import OllamaEmbeddingFunction
    client = chromadb.PersistentClient(path=str(DB_DIR))
    emb = OllamaEmbeddingFunction(url=OLLAMA_URL, model_name=EMBED_MODEL)
    col = client.get_or_create_collection(COLLECTION, embedding_function=emb)
    if col.count() == 0:
        return []
    where = None
    if channel:
        chs = [c.strip() for c in channel.split(",") if c.strip()]
        if len(chs) == 1:
            where = {"channel": chs[0]}
        elif len(chs) > 1:
            where = {"channel": {"$in": chs}}
    res = col.query(query_texts=[query], n_results=n * 2 if since else n,
                    where=where)
    out = []
    for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0],
                               res["distances"][0]):
        out.append({
            "channel": meta.get("channel", "?"),
            "title": meta.get("title", "?"),
            "date": meta.get("date", "?"),
            "score": round(1 - dist, 3),
            "snippet": doc.strip(),
        })
    if since:
        cutoff = (datetime.date.today() - datetime.timedelta(days=since)).strftime("%Y%m%d")

        def _rank(it):
            d = it["date"]
            recent = bool(d and d != "NA" and d >= cutoff)
            return (0 if recent else 1, -it["score"])

        out.sort(key=_rank)
        out = out[:n]
    return out


def search(query, n=4, top_only=False, since=None, channel=None):
    for r in search_results(query, n=n, since=since, channel=channel):
        tag = ""
        if since:
            d = r["date"]
            if d and d != "NA":
                recent = d >= (__import__("datetime").date.today() -
                               __import__("datetime").timedelta(days=since)).strftime("%Y%m%d")
                tag = " 近" if recent else " 旧"
            else:
                tag = " 日期NA"
        if top_only:
            print(f"▶ [{r['channel']}] {r['title']} ({r['date']}){tag}")
        else:
            print(f"【{r['channel']}】{r['title']}（{r['date']}） 相关度 {r['score']:.3f}{tag}")
            print(r["snippet"][:600])
            print("-" * 60)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("query", help="检索问题")
    ap.add_argument("-n", type=int, default=4)
    ap.add_argument("--top", action="store_true")
    ap.add_argument("--since", type=int, default=None,
                    help="近 N 天观点优先（如 30/90），NA 日期排后不排除")
    ap.add_argument("--channel", default=None,
                    help="按频道过滤，逗号分隔（如 BenFelix,QuantPy）")
    args = ap.parse_args()
    search(args.query, n=args.n, top_only=args.top,
           since=args.since, channel=args.channel)
