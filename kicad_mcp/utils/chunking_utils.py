from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from pathlib import Path
import re
import sys

from kicad_mcp.config import KICAD_USER_DIR

_KICAD_BASE   = Path(KICAD_USER_DIR)
MARKDOWN_DIR  = _KICAD_BASE / "markdown"

headers_to_split_on = [
    ("#", "Header 1"),
    ("##", "Header 2"),
    ("###", "Header 3"),
]

SKIP_PATTERNS = [
    r'disclaimer', r'trademark', r'legal', r'copyright',
    r'revision history', r'contents', r'table of content',
    r'all rights reserved', r'definitions', r'data sheet status'
]

markdown_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on)

text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=100,
    separators=["\n\n", "\n", " ", ""]
)


def is_useful_chunk(chunk) -> bool:
    content = chunk.page_content.strip()
    text_only = re.sub(r'<br>', '', content).strip()
    if len(text_only) < 50:
        return False
    header = chunk.metadata.get("Header 2", "")
    if any(re.search(p, header.lower()) for p in SKIP_PATTERNS):
        return False
    return True

def get_final_chunks() -> list:
    all_chunks = []

    md_files = list(MARKDOWN_DIR.glob("*.md"))
    
    if not md_files:
        return []

    print("start chunking",  file=sys.stderr)
    for md_path in md_files:
        try:
            md_text = md_path.read_text(encoding="utf-8")
            sections = markdown_splitter.split_text(md_text)
            chunks = text_splitter.split_documents(sections)
            chunks = [c for c in chunks if is_useful_chunk(c)]

            for chunk in chunks:
                chunk.metadata["source"] = md_path.stem  # z.B. "PRTR5V0U2X"

            all_chunks.extend(chunks)
        except Exception as e:
            print(f"  FEHLER beim Chunken von {md_path.name}: {e}", file=sys.stderr)
    
    print("finish chunking",  file=sys.stderr)


    return all_chunks