import sys
import hashlib
import sqlite3
import json
import faiss
import numpy as np
from pathlib import Path
from sentence_transformers import SentenceTransformer

from kicad_mcp.utils.chunking_utils import chunk_file
from kicad_mcp.utils.get_datasheets import run_pipeline

_KICAD_BASE = Path("C:/Users/messeel/KiCad/9.0/projects")

MARKDOWN_DIR  = _KICAD_BASE / "markdown"
CACHE_DIR     = Path(__file__).parent.parent / "rag_cache"
DB_FILE       = CACHE_DIR / "kicad_data.db"
FAISS_FILE    = CACHE_DIR / "kicad_index.faiss"

def get_file_hash(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()

def init_system():
    CACHE_DIR.mkdir(exist_ok=True)
    
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,
            file_hash TEXT,
            content TEXT,
            metadata TEXT
        )
    """)
    conn.commit()
    conn.close()

    if not FAISS_FILE.exists():
        # 768 dimensions for nomic-embed-text, L2 normalization = Cosine Similarity
        base_index = faiss.IndexFlatIP(768)
        index = faiss.IndexIDMap(base_index)
        faiss.write_index(index, str(FAISS_FILE))

def sync_database():
    print("=== Pipeline: PDF → Markdown ===", file=sys.stderr)
    run_pipeline() 

    print("start faiss + sql Lite", file=sys.stderr)
    init_system()
    
    md_files = list(MARKDOWN_DIR.glob("*.md"))
    if not md_files:
        print("No markdown files found.", file=sys.stderr)
        return

    model = SentenceTransformer("nomic-ai/nomic-embed-text-v1.5", trust_remote_code=True)
    index = faiss.read_index(str(FAISS_FILE))
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    #also delete entrys that do not have a src in md anymore
    existing_stems = {p.stem for p in md_files}
    cursor.execute("SELECT DISTINCT source FROM chunks")
    db_sources = {row[0] for row in cursor.fetchall()}

    for removed in db_sources - existing_stems:
        print(f"removed (MD deleted): {removed}...")
        cursor.execute("SELECT id FROM chunks WHERE source = ?", (removed,))
        ids_to_delete = [r[0] for r in cursor.fetchall()]
        if ids_to_delete:
            index.remove_ids(np.array(ids_to_delete, dtype=np.int64))
        cursor.execute("DELETE FROM chunks WHERE source = ?", (removed,))

    updated_count = 0

    for md_path in md_files:
        source_name = md_path.stem
        current_hash = get_file_hash(md_path)

        # check hash in file
        cursor.execute("SELECT file_hash FROM chunks WHERE source = ? LIMIT 1", (source_name,))
        row = cursor.fetchone()
        stored_hash = row[0] if row else None

        if stored_hash == current_hash:
            continue  #md did not change, hashes are the same

        #else delete old files from faiss and sqlLite 
        if stored_hash:
            print(f"update {source_name}...", file=sys.stderr)
            cursor.execute("SELECT id FROM chunks WHERE source = ?", (source_name,))
            ids_to_delete = [r[0] for r in cursor.fetchall()] #all chunk ids that are part of the file that need to be deleted
            
            if ids_to_delete:
                index.remove_ids(np.array(ids_to_delete, dtype=np.int64))
                cursor.execute("DELETE FROM chunks WHERE source = ?", (source_name,))
        else:
            print(f"new datasheet: {source_name}...", file=sys.stderr)

        #if no hash was stored at all create chunks for new md
        chunks = chunk_file(md_path)
        if not chunks:
            continue

        texts_to_embed = []
        db_ids = []

        for c in chunks:
            cursor.execute("""
                INSERT INTO chunks (source, file_hash, content, metadata) 
                VALUES (?, ?, ?, ?)
            """, (source_name, current_hash, c.page_content, json.dumps(c.metadata)))
            
            chunk_id = cursor.lastrowid
            db_ids.append(chunk_id)

            header = (
                c.metadata.get('Header 2') or
                c.metadata.get('Header 1') or
                c.metadata.get('header') or
                ''
            )
            texts_to_embed.append(f"search_document: Section: {header} | {c.page_content}")

        #embedding and safe in faiss
        embeddings = model.encode(texts_to_embed, show_progress_bar=True).astype("float32")
        faiss.normalize_L2(embeddings)
        
        index.add_with_ids(embeddings, np.array(db_ids, dtype=np.int64))
        updated_count += 1

    conn.commit()
    conn.close()
    faiss.write_index(index, str(FAISS_FILE))
    
    print(f"sync completed {updated_count} file updated", file=sys.stderr)

if __name__ == "__main__":
    sync_database()