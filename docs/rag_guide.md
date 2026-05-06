# Datasheet RAG Guide

This guide explains the Retrieval-Augmented Generation (RAG) pipeline that lets Claude search your component datasheets for technical information.

## Overview

The RAG pipeline automatically:
1. Scans all your KiCad schematics for datasheet URLs
2. Downloads the referenced PDFs
3. Converts them to searchable markdown with extracted images
4. Indexes the content in a FAISS vector index backed by a SQLite database

Once indexed, Claude can call `search_datasheets` to retrieve relevant excerpts for any technical question about your components.

## MCP Tools

| Tool | Description |
|------|-------------|
| `search_datasheets(query, k=4)` | Semantic search over all indexed datasheets.  |
| `read_local_image(image_path)` | Loads an image extracted from a datasheet for visual inspection (diagrams, pinouts, timing charts). |

### Example prompts

```
What is the I2C address configuration for U3?
What is the maximum output current of the voltage regulator?
Show me the pinout of the STM32 in my schematic.
```

If a search result contains a `[Referenzbild (...): path]` marker, Claude will call `read_local_image` to display the referenced diagram.

## How the Pipeline Works

```
KiCad Schematics (.kicad_sch)
    ↓
[1] Collect datasheet URLs from symbol Datasheet properties
    ↓
[2] Download PDFs  →  {KICAD_USER_DIR}/datasheets/
    ↓
[3] Convert PDF → Markdown  →  {KICAD_USER_DIR}/markdown/
                  Extract images  →  {KICAD_USER_DIR}/markdown/img/
    ↓
[4] Split markdown into chunks (1000 chars, 100 overlap)
    Filter boilerplate sections (copyright, revision history, …)
    Annotate useful images as [Referenzbild] markers
    ↓
[5] Embed chunks with nomic-ai/nomic-embed-text-v1.5
    Store vectors  →  {project root}/rag_cache/kicad_index.faiss
    Store text + metadata  →  {project root}/rag_cache/kicad_data.db
```

The pipeline runs automatically in a background thread when the MCP server starts. On subsequent starts the FAISS index is loaded from disk — only changed or new markdown files are re-embedded.

## File Storage

| Path | Contents |
|------|----------|
| `{KICAD_USER_DIR}/datasheets/` | Downloaded PDF datasheets |
| `{KICAD_USER_DIR}/markdown/` | Converted markdown files (one per PDF) |
| `{KICAD_USER_DIR}/markdown/img/` | Images extracted from PDFs |
| `{project root}/rag_cache/kicad_index.faiss` | FAISS vector index |
| `{project root}/rag_cache/kicad_data.db` | SQLite database with chunk text and metadata |

`KICAD_USER_DIR` defaults to `~/KiCad/9.0/projects` on Windows and can be overridden via the `KICAD_USER_DIR` environment variable. The `rag_cache/` directory sits inside the `kicad-mcp` project folder and is excluded from version control via `.gitignore`.

## Manually Re-indexing

To force a full re-index (e.g. after adding new projects or deleting the cache or for setup):

```bash
python scripts/update_db.py
```

This runs the complete pipeline and updates only files whose content has changed since the last run (hash-based diffing).

## Image Filtering

Not every image extracted from a PDF is useful. The pipeline keeps an image only if:
- File size ≥ 3 KB (filters out spacers and icons)
- Dimensions ≥ 150 × 150 px
- Aspect ratio between 0.25 and 4.0 (excludes banners and thin dividers)

