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


_IMAGE_RE = re.compile(
    r'!\[([^\]]*)\]\(([^)]+\.(?:png|jpg|jpeg|gif|webp|svg))\)',
    re.IGNORECASE,
)


def _is_useful_image(image_path: str) -> bool:
    path = Path(image_path)
    if not path.exists() or path.stat().st_size < 3000:
        return False
    try:
        from PIL import Image as PILImage
        with PILImage.open(path) as img:
            w, h = img.size
            if w < 150 or h < 150:
                return False
            ratio = w / h
            if ratio > 4.0 or ratio < 0.25:
                return False
        return True
    except Exception:
        return False


def _annotate_images(chunk) -> None:
    """Replace markdown image syntax with [Referenzbild: path] markers.

    Images that are too small, too narrow, or likely decorative are removed.
    Useful image paths are stored in chunk.metadata["images"].
    """
    images: list[str] = []

    def _replace(m: re.Match) -> str:
        alt, path = m.group(1).strip(), m.group(2)
        if not _is_useful_image(path):
            return ""
        images.append(path)
        label = f" ({alt})" if alt else ""
        return f"[Referenzbild{label}: {path}]"

    chunk.page_content = _IMAGE_RE.sub(_replace, chunk.page_content)
    if images:
        chunk.metadata["images"] = images

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
                chunk.metadata["source"] = md_path.stem
                _annotate_images(chunk)

            all_chunks.extend(chunks)
        except Exception as e:
            print(f"  FEHLER beim Chunken von {md_path.name}: {e}", file=sys.stderr)
    
    print("finish chunking",  file=sys.stderr)


    return all_chunks