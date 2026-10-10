"""一次性入库：微信文章《COIN、HOOD、CRCL》要点 → ChromaDB yt_trading 集合。
channel=wechat_article，与 YouTube 频道区分；kb_search 可检索。"""
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
DB_DIR = REPO / "Data" / "kb" / "chroma"
COLLECTION = "yt_trading"
OLLAMA_URL = "http://127.0.0.1:11434"
EMBED_MODEL = "bge-m3"
VID = "wechat_onchain_finance_20261009"
TITLE = "COIN、HOOD、CRCL：链上金融的赚钱能力，到底差在哪里？"
DATE = "20261009"
CHANNEL = "wechat_article"


def chunk_text(text, size=400, overlap=60):
    chunks = []
    for i in range(0, len(text), size - overlap):
        chunks.append(text[i:i + size].strip())
    return [c for c in chunks if len(c) > 60]


def main():
    import chromadb
    from chromadb.utils.embedding_functions import OllamaEmbeddingFunction
    text = Path(tempfile.gettempdir(), "wx_article.txt").read_text(encoding="utf-8")
    client = chromadb.PersistentClient(path=str(DB_DIR))
    emb = OllamaEmbeddingFunction(url=OLLAMA_URL, model_name=EMBED_MODEL)
    col = client.get_or_create_collection(COLLECTION, embedding_function=emb)
    existing = set(col.get()["ids"]) if col.count() else set()
    added = 0
    for i, ch in enumerate(chunk_text(text)):
        id_ = f"{VID}_{i}"
        if id_ in existing:
            continue
        col.add(ids=[id_], documents=[ch],
                metadatas=[{"video_id": VID, "channel": CHANNEL,
                            "title": TITLE, "date": DATE, "chunk": i}])
        added += 1
    print(f"文章入库完成: 新增 {added} 块, 集合共 {col.count()} 块")
    # 验证检索
    res = col.query(query_texts=["链上金融 储备收益 利率"], n_results=2)
    for doc, meta in zip(res["documents"][0], res["metadatas"][0]):
        print("  ->", meta.get("channel"), "|", meta.get("title"), "|", doc[:60])


if __name__ == "__main__":
    main()
