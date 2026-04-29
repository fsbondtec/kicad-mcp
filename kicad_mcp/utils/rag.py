import numpy as np
from pathlib import Path
from sentence_transformers import SentenceTransformer

from kicad_mcp.config import KICAD_USER_DIR


_KICAD_BASE   = Path(KICAD_USER_DIR)
CACHE_DIR      = _KICAD_BASE / "rag_cache"
EMBEDDINGS_PATH = CACHE_DIR / "embeddings.npy"

_model = None
_chunks = None
_embeddings = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer("nomic-ai/nomic-embed-text-v1.5", trust_remote_code=True)
    return _model


def initialize_rag(chunks: list) -> None:
    global _chunks, _embeddings
    CACHE_DIR.mkdir(exist_ok=True)

    model = _get_model()

    if EMBEDDINGS_PATH.exists():
        embeddings = np.load(EMBEDDINGS_PATH)
        if embeddings.shape[0] == len(chunks):
            print(f"Embeddings geladen ({len(chunks)} Chunks).", file=__import__("sys").stderr)
            _chunks, _embeddings = chunks, embeddings
            return
        print("Chunk-Anzahl geändert — neu embedden...", file=__import__("sys").stderr)

    texts = [
        f"search_document: Section: {c.metadata.get('Header 2', '')} | {c.page_content}"
        for c in chunks
    ]
    embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=True)
    np.save(EMBEDDINGS_PATH, embeddings)
    print(f"Embeddings erstellt ({len(chunks)} Chunks).", file=__import__("sys").stderr)

    _chunks, _embeddings = chunks, embeddings


def search(query: str, k: int = 4) -> list:
    if _chunks is None or _embeddings is None:
        return []

    model = _get_model()
    query_embedding = model.encode([f"search_query: {query}"], normalize_embeddings=True)
    scores = model.similarity(query_embedding, _embeddings)[0].numpy()
    top_k = np.argsort(scores)[::-1][:k]

    return [(str(_chunks[i].page_content), float(scores[i])) for i in top_k]