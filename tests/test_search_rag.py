import json
import sqlite3
import pytest
import numpy as np
from pathlib import Path
from unittest.mock import MagicMock, patch



def _make_db(path: Path, rows: list[tuple]) -> None:
    """Create a minimal chunks SQLite DB at *path* with the given rows (id, content, metadata)."""
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE chunks (id INTEGER PRIMARY KEY, content TEXT, metadata TEXT)"
    )
    conn.executemany("INSERT INTO chunks VALUES (?, ?, ?)", rows)
    conn.commit()
    conn.close()


def _fake_encode(texts, **kwargs):
    return np.zeros((len(texts), 768), dtype="float32")


class TestLoad:
    def test_missing_files_raise(self, tmp_path, monkeypatch):
        import kicad_mcp.utils.search_rag as rag
        monkeypatch.setattr(rag, "_model", None)
        monkeypatch.setattr(rag, "_index", None)
        monkeypatch.setattr(rag, "FAISS_FILE", tmp_path / "missing.faiss")
        monkeypatch.setattr(rag, "DB_FILE", tmp_path / "missing.db")

        with pytest.raises(FileNotFoundError):
            rag._load()

    def test_already_loaded_is_noop(self, monkeypatch):
        import kicad_mcp.utils.search_rag as rag
        sentinel = MagicMock()
        monkeypatch.setattr(rag, "_model", sentinel)

        rag._load()

        assert rag._model is sentinel 

    def test_loads_model_and_index(self, tmp_path, monkeypatch):
        import kicad_mcp.utils.search_rag as rag
        monkeypatch.setattr(rag, "_model", None)
        monkeypatch.setattr(rag, "_index", None)

        faiss_path = tmp_path / "index.faiss"
        db_path = tmp_path / "data.db"
        faiss_path.write_bytes(b"placeholder")
        db_path.write_bytes(b"placeholder")

        monkeypatch.setattr(rag, "FAISS_FILE", faiss_path)
        monkeypatch.setattr(rag, "DB_FILE", db_path)

        mock_model = MagicMock()
        mock_index = MagicMock()

        with patch("sentence_transformers.SentenceTransformer", return_value=mock_model), \
             patch("faiss.read_index", return_value=mock_index):
            rag._load()

        assert rag._model is mock_model
        assert rag._index is mock_index



class TestSearch:
    def _setup(self, monkeypatch, tmp_path, db_rows, faiss_scores, faiss_ids):
        """Inject mocked model, index, and DB into the search_rag module."""
        import kicad_mcp.utils.search_rag as rag

        db = tmp_path / "test.db"
        _make_db(db, db_rows)

        mock_model = MagicMock()
        mock_model.encode.side_effect = _fake_encode

        mock_index = MagicMock()
        mock_index.search.return_value = (
            np.array([faiss_scores], dtype="float32"),
            np.array([faiss_ids], dtype="int64"),
        )

        monkeypatch.setattr(rag, "_model", mock_model)
        monkeypatch.setattr(rag, "_index", mock_index)
        monkeypatch.setattr(rag, "DB_FILE", db)

        return rag

    def test_returns_results(self, tmp_path, monkeypatch):
        rows = [(1, "Voltage range 3.3V", json.dumps({"source": "ds1", "images": []}))]
        rag = self._setup(monkeypatch, tmp_path, rows, [0.92], [1])

        with patch("faiss.normalize_L2"):
            results = rag.search("voltage range", top_k=1)

        assert len(results) == 1
        assert results[0]["text"] == "Voltage range 3.3V"
        assert results[0]["source"] == "ds1"
        assert results[0]["score"] == pytest.approx(0.92)
        assert results[0]["images"] == []

    def test_no_results_returns_empty(self, tmp_path, monkeypatch):
        rag = self._setup(monkeypatch, tmp_path, [], [-1.0], [-1])

        with patch("faiss.normalize_L2"):
            results = rag.search("unknown", top_k=1)

        assert results == []

    def test_top_k_respected(self, tmp_path, monkeypatch):
        rows = [
            (1, "Content one", json.dumps({"source": "a", "images": []})),
            (2, "Content two", json.dumps({"source": "b", "images": []})),
            (3, "Content three", json.dumps({"source": "c", "images": []})),
        ]
        rag = self._setup(monkeypatch, tmp_path, rows, [0.9, 0.8, 0.7], [1, 2, 3])

        with patch("faiss.normalize_L2"):
            results = rag.search("query", top_k=3)

        assert len(results) == 3

    def test_images_returned_in_result(self, tmp_path, monkeypatch):
        rows = [(1, "Pin diagram", json.dumps({"source": "ds", "images": ["/data/img/p.png"]}))]
        rag = self._setup(monkeypatch, tmp_path, rows, [0.85], [1])

        with patch("faiss.normalize_L2"):
            results = rag.search("pinout", top_k=1)

        assert results[0]["images"] == ["/data/img/p.png"]

    def test_missing_db_entry_skipped(self, tmp_path, monkeypatch):
        rows = [(1, "Real chunk", json.dumps({"source": "ds", "images": []}))]
        rag = self._setup(monkeypatch, tmp_path, rows, [0.9, 0.8], [99, 1])

        with patch("faiss.normalize_L2"):
            results = rag.search("query", top_k=2)

        assert len(results) == 1
        assert results[0]["text"] == "Real chunk"

    def test_faiss_minus_one_ids_ignored(self, tmp_path, monkeypatch):
        # FAISS pads with -1 when fewer results than top_k exist
        rows = [(1, "Only result", json.dumps({"source": "ds", "images": []}))]
        rag = self._setup(monkeypatch, tmp_path, rows, [0.9, 0.0], [1, -1])

        with patch("faiss.normalize_L2"):
            results = rag.search("query", top_k=2)

        assert len(results) == 1

    def test_search_uses_query_prefix(self, tmp_path, monkeypatch):
        rows = [(1, "content", json.dumps({"source": "ds", "images": []}))]
        rag = self._setup(monkeypatch, tmp_path, rows, [0.9], [1])

        with patch("faiss.normalize_L2"):
            rag.search("I2C address", top_k=1)

        call_args = rag._model.encode.call_args[0][0]
        assert call_args[0].startswith("search_query:")
