import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from langchain_core.documents import Document

from kicad_mcp.utils.chunking_utils import (
    is_useful_chunk,
    _is_useful_image,
    _annotate_images,
    chunk_file,
)



def _chunk(content: str, header2: str = "") -> Document:
    return Document(page_content=content, metadata={"Header 2": header2})


def _pil_mock(size: tuple = (200, 200)):
    """Context-manager mock for PIL.Image.open returning a fixed image size."""
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=ctx)
    ctx.__exit__ = MagicMock(return_value=False)
    ctx.size = size
    return ctx



class TestIsUsefulChunk:
    def test_useful_content(self):
        assert is_useful_chunk(_chunk("A" * 60)) is True

    def test_too_short(self):
        assert is_useful_chunk(_chunk("A" * 49)) is False

    def test_exactly_50_chars_is_useful(self):
        assert is_useful_chunk(_chunk("A" * 50)) is True

    def test_br_tags_stripped_only_breaks_filtered(self):
        assert is_useful_chunk(_chunk("<br>" * 20)) is False

    def test_br_tags_stripped_real_content_kept(self):
        assert is_useful_chunk(_chunk("<br>" * 5 + "A" * 60)) is True

    @pytest.mark.parametrize("header", [
        "Disclaimer",
        "Trademark Notice",
        "Legal Information",
        "Copyright 2024",
        "Revision History",
        "Table of Contents",
        "All Rights Reserved",
        "Definitions",
        "Data Sheet Status",
    ])
    def test_boilerplate_headers_filtered(self, header):
        assert is_useful_chunk(_chunk("A" * 100, header2=header)) is False

    def test_technical_header_kept(self):
        assert is_useful_chunk(_chunk("A" * 100, header2="Electrical Characteristics")) is True

    def test_missing_header2_defaults_to_empty(self):
        chunk = Document(page_content="A" * 100, metadata={})
        assert is_useful_chunk(chunk) is True



class TestIsUsefulImage:
    def test_nonexistent_file(self, tmp_path):
        assert _is_useful_image(str(tmp_path / "missing.png")) is False

    def test_file_too_small(self, tmp_path):
        p = tmp_path / "tiny.png"
        p.write_bytes(b"x" * 100)
        assert _is_useful_image(str(p)) is False

    def test_valid_image(self, tmp_path):
        p = tmp_path / "valid.png"
        p.write_bytes(b"x" * 4000)
        with patch("PIL.Image.open", return_value=_pil_mock((200, 200))):
            assert _is_useful_image(str(p)) is True

    def test_dimensions_too_small(self, tmp_path):
        p = tmp_path / "small_dims.png"
        p.write_bytes(b"x" * 4000)
        with patch("PIL.Image.open", return_value=_pil_mock((100, 100))):
            assert _is_useful_image(str(p)) is False

    def test_ratio_too_wide(self, tmp_path):
        p = tmp_path / "banner.png"
        p.write_bytes(b"x" * 4000)
        with patch("PIL.Image.open", return_value=_pil_mock((1000, 100))):  
            assert _is_useful_image(str(p)) is False

    def test_ratio_too_tall(self, tmp_path):
        p = tmp_path / "divider.png"
        p.write_bytes(b"x" * 4000)
        with patch("PIL.Image.open", return_value=_pil_mock((100, 1000))): 
            assert _is_useful_image(str(p)) is False

    def test_pil_exception_returns_false(self, tmp_path):
        p = tmp_path / "corrupt.png"
        p.write_bytes(b"x" * 4000)
        with patch("PIL.Image.open", side_effect=OSError("corrupt file")):
            assert _is_useful_image(str(p)) is False

    def test_boundary_ratio_accepted(self, tmp_path):
        p = tmp_path / "wide.png"
        p.write_bytes(b"x" * 4000)
        with patch("PIL.Image.open", return_value=_pil_mock((600, 150))):  # ratio exactly 4.0
            assert _is_useful_image(str(p)) is True



class TestAnnotateImages:
    def test_no_images_unchanged(self):
        chunk = _chunk("No images here.")
        _annotate_images(chunk)
        assert chunk.page_content == "No images here."
        assert "images" not in chunk.metadata

    def test_useful_image_replaced_with_marker(self, tmp_path):
        p = tmp_path / "diagram.png"
        p.write_bytes(b"x" * 4000)
        chunk = _chunk(f"See ![]({p})")
        with patch("PIL.Image.open", return_value=_pil_mock((200, 200))):
            _annotate_images(chunk)
        assert "Referenzbild" in chunk.page_content
        assert str(p) in chunk.metadata.get("images", [])

    def test_small_image_removed(self, tmp_path):
        p = tmp_path / "tiny.png"
        p.write_bytes(b"x" * 100)
        chunk = _chunk(f"See ![alt]({p})")
        _annotate_images(chunk)
        assert "Referenzbild" not in chunk.page_content
        assert "images" not in chunk.metadata

    def test_alt_text_included_in_label(self, tmp_path):
        p = tmp_path / "diagram.png"
        p.write_bytes(b"x" * 4000)
        chunk = _chunk(f"![pinout diagram]({p})")
        with patch("PIL.Image.open", return_value=_pil_mock((200, 200))):
            _annotate_images(chunk)
        assert "(pinout diagram)" in chunk.page_content

    def test_no_alt_text_produces_no_label_parens(self, tmp_path):
        p = tmp_path / "diagram.png"
        p.write_bytes(b"x" * 4000)
        chunk = _chunk(f"![]({p})")
        with patch("PIL.Image.open", return_value=_pil_mock((200, 200))):
            _annotate_images(chunk)
        assert "[Referenzbild:" in chunk.page_content
        assert "( )" not in chunk.page_content

    def test_multiple_images_partial_keep(self, tmp_path):
        good = tmp_path / "good.png"
        good.write_bytes(b"x" * 4000)
        bad = tmp_path / "bad.png"
        bad.write_bytes(b"x" * 100)  # fails size check before PIL is called
        chunk = _chunk(f"![]({good}) and ![]({bad})")
        with patch("PIL.Image.open", return_value=_pil_mock((200, 200))):
            _annotate_images(chunk)
        assert str(good) in chunk.metadata.get("images", [])
        assert str(bad) not in chunk.metadata.get("images", [])

    def test_images_metadata_absent_when_none_pass(self, tmp_path):
        p = tmp_path / "bad.png"
        p.write_bytes(b"x" * 100)
        chunk = _chunk(f"![]({p})")
        _annotate_images(chunk)
        assert "images" not in chunk.metadata


class TestChunkFile:
    def test_basic_chunking_returns_chunks(self, tmp_path):
        md = tmp_path / "component.md"
        md.write_text("## Features\n\n" + "Feature content " * 20, encoding="utf-8")
        assert len(chunk_file(md)) > 0

    def test_source_metadata_is_filename_stem(self, tmp_path):
        md = tmp_path / "mycomponent.md"
        md.write_text("## Section\n\n" + "Content " * 20, encoding="utf-8")
        chunks = chunk_file(md)
        assert all(c.metadata.get("source") == "mycomponent" for c in chunks)

    def test_header_metadata_preserved(self, tmp_path):
        md = tmp_path / "test.md"
        md.write_text(
            "## Electrical Characteristics\n\n" + "Voltage range " * 20,
            encoding="utf-8",
        )
        chunks = chunk_file(md)
        assert any(c.metadata.get("Header 2") == "Electrical Characteristics" for c in chunks)

    def test_boilerplate_section_filtered(self, tmp_path):
        md = tmp_path / "test.md"
        md.write_text(
            "## Features\n\n" + "Useful content " * 20 + "\n\n"
            "## Disclaimer\n\n" + "Legal text " * 20,
            encoding="utf-8",
        )
        chunks = chunk_file(md)
        headers = [c.metadata.get("Header 2", "").lower() for c in chunks]
        assert "disclaimer" not in headers

    def test_short_chunks_filtered(self, tmp_path):
        md = tmp_path / "test.md"
        md.write_text("## Section\n\nToo short.", encoding="utf-8")
        chunks = chunk_file(md)
        assert all(len(c.page_content.strip()) >= 50 for c in chunks)

    def test_nonexistent_file_returns_empty(self, tmp_path):
        assert chunk_file(tmp_path / "missing.md") == []

    def test_empty_file_returns_empty(self, tmp_path):
        md = tmp_path / "empty.md"
        md.write_text("", encoding="utf-8")
        assert chunk_file(md) == []

    def test_multiple_sections_all_chunked(self, tmp_path):
        md = tmp_path / "multi.md"
        md.write_text(
            "## Section A\n\n" + "Content A " * 20 + "\n\n"
            "## Section B\n\n" + "Content B " * 20,
            encoding="utf-8",
        )
        chunks = chunk_file(md)
        section_headers = {c.metadata.get("Header 2") for c in chunks}
        assert "Section A" in section_headers
        assert "Section B" in section_headers
