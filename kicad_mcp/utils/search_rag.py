import json
import sqlite3
import faiss
import numpy as np
from pathlib import Path
from sentence_transformers import SentenceTransformer

CACHE_DIR  = Path(__file__).parent.parent.parent / "rag_cache"
DB_FILE    = CACHE_DIR / "kicad_data.db"
FAISS_FILE = CACHE_DIR / "kicad_index.faiss"

_model: SentenceTransformer | None = None
_index = None

def _load():
    global _model, _index
    if _model is not None:
        return 
    
    if not FAISS_FILE.exists() or not DB_FILE.exists():
        raise FileNotFoundError("Rag File not found. Run update_db.py.")
    
    _model = SentenceTransformer("nomic-ai/nomic-embed-text-v1.5", trust_remote_code=True)
    _index = faiss.read_index(str(FAISS_FILE))


def search(query: str, top_k: int = 4) -> list[tuple[str, float]]:
    _load()
    
    q_emb = _model.encode(
        [f"search_query: {query}"],
        show_progress_bar=False
    ).astype("float32")
    faiss.normalize_L2(q_emb)
    
    scores, ids = _index.search(q_emb, top_k)
    found_ids = [i for i in ids[0].tolist() if i != -1]
    if not found_ids:
        return []

    with sqlite3.connect(DB_FILE) as conn:
        placeholders = ",".join("?" * len(found_ids))
        rows = conn.execute(
            f"SELECT id, content, metadata FROM chunks WHERE id IN ({placeholders})",
            found_ids
        ).fetchall()

    db_rows = {
        row[0]: {"content": row[1], "metadata": json.loads(row[2])}
        for row in rows
    }


    return [
        {
            "text": db_rows[chunk_id]["content"],
            "score": float(score),
            "source": db_rows[chunk_id]["metadata"].get("source", ""),
            "images": db_rows[chunk_id]["metadata"].get("images", []),
        }
        for score, chunk_id in zip(scores[0], found_ids)
        if chunk_id in db_rows
    ]