import pymupdf4llm
from kiutils.schematic import Schematic
from urllib.parse import urlparse
from curl_cffi import requests as curl_requests
import contextlib
import re
from pathlib import Path
import sys

from kicad_mcp.utils.kicad_utils import find_kicad_projects;
from kicad_mcp.utils.file_utils import get_project_files;

from kicad_mcp.config import KICAD_USER_DIR

_KICAD_BASE   = Path(KICAD_USER_DIR)
DATASHEET_DIR = _KICAD_BASE / "datasheets"
MARKDOWN_DIR  = _KICAD_BASE / "markdown"
IMAGE_DIR     = MARKDOWN_DIR / "img"

def clean_markdown(md: str) -> str:
    """Remove OCR picture-text blocks and normalize excessive whitespace."""
    md = re.sub(
        r'\*\*----- Start of picture text -----\*\*.*?\*\*----- End of picture text -----\*\*',
        '', md, flags=re.DOTALL
    )
    md = re.sub(r'\n{3,}', '\n\n', md)
    return md.strip()

def collect_all_schematic_paths() -> list[str]:
    """Return paths to all .kicad_sch files found across all known KiCad projects."""
    all_schematic_paths = []
    
    projects = find_kicad_projects()
    
    for project in projects:
        files = get_project_files(project["path"])
        
        if "schematic" not in files:
            continue
        
        schematic_paths = files["schematic"]
        
        if isinstance(schematic_paths, str):
            schematic_paths = [schematic_paths]
        
        all_schematic_paths.extend(schematic_paths)
    
    return all_schematic_paths

def collect_datasheet_urls() -> list[str]:
    """Extract unique datasheet URLs from the Datasheet property of all schematic symbols."""
    urls = []

    schematic_paths = collect_all_schematic_paths()

    for sch_path in schematic_paths:
        try:
            sch = Schematic.from_file(sch_path)
            for inst in sch.schematicSymbols:
                for prop in inst.properties:
                    if prop.key == 'Datasheet':
                        val = prop.value.strip()
                        # '~' is KiCad's placeholder for an empty Datasheet field
                        if val and val != '~':
                            urls.append(val)
        except Exception as e:
            print(f"  Error reading {sch_path}: {e}", file=sys.stderr)

    return list(set(urls))

def download_datasheets(urls: list[str]):
    """Download PDFs from the given URLs into DATASHEET_DIR, skipping already-present files."""
    DATASHEET_DIR.mkdir(exist_ok=True)
    session = curl_requests.Session()

    for url in urls:
        filename = url.split("/")[-1].split("?")[0]
        if not filename.endswith(".pdf"):
            filename += ".pdf"
        
        out_path = DATASHEET_DIR / filename
        if out_path.exists():
            print(f"  Bereits vorhanden: {filename}", file=sys.stderr)
            continue

        try:
            parsed = urlparse(url)
            r = session.get(url, impersonate="chrome124", timeout=15,
                          headers={"Referer": f"{parsed.scheme}://{parsed.netloc}/"})
            r.raise_for_status()

            if "pdf" not in r.headers.get("Content-Type", "").lower() and not r.content.startswith(b"%PDF"):
                print(f"  Not a PDF: {url}", file=sys.stderr)
                continue

            out_path.write_bytes(r.content)
            print(f"  OK: {filename}", file=sys.stderr)
        except Exception as e:
            print(f"  FEHLER {url}: {e}", file=sys.stderr)

def convert_pdfs_to_markdown():
    """Convert all PDFs in DATASHEET_DIR to markdown, extracting images to IMAGE_DIR."""
    MARKDOWN_DIR.mkdir(exist_ok=True)
    IMAGE_DIR.mkdir(exist_ok=True)

    for pdf_path in DATASHEET_DIR.glob("*.pdf"):
        md_path = MARKDOWN_DIR / (pdf_path.stem + ".md")

        if md_path.exists():
            print(f"  ueberspringe: {pdf_path.name}", file=sys.stderr)
            continue

        print(f"  Converting: {pdf_path.name}", file=sys.stderr)
        try:
            with contextlib.redirect_stdout(sys.stderr):
                md = pymupdf4llm.to_markdown(
                    str(pdf_path),
                    write_images=True,
                    image_path=str(IMAGE_DIR),
                    header=False,
                    footer=False,
                )
            md_path.write_text(clean_markdown(md), encoding="utf-8")
            print(f"  OK: {md_path.name}", file=sys.stderr)
        except Exception as e:
            print(f"  FEHLER {pdf_path.name}: {e}", file=sys.stderr)

def run_pipeline():
    """Run the full datasheet pipeline: collect URLs → download PDFs → convert to markdown."""
    print("=== 1.get URLs ===", file=sys.stderr)
    urls = collect_datasheet_urls()
    print(f"  {len(urls)} found datasheets", file=sys.stderr)

    print("\n=== 2. download PDFs ===", file=sys.stderr)
    download_datasheets(urls)

    print("\n=== 3. convert PDF to md ===", file=sys.stderr)
    convert_pdfs_to_markdown()

    print("\nPipeline finished.", file=sys.stderr)

if __name__ == "__main__":
    run_pipeline()