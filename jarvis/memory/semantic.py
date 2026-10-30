"""
J.A.R.V.I.S. — L4 Semantic Memory
Long-term, meaning-based recall of facts and preferences. Unlike the keyword
facts list, this retrieves by MEANING: "what browser do I like?" matches
"User prefers Brave" even without shared words.

Backed by SQLite. Uses sentence-transformer embeddings when available (cosine
similarity); degrades gracefully to keyword search if the model/numpy aren't
installed. The embedding model is loaded lazily on the first semantic recall so
startup stays fast.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any, List, Optional

from loguru import logger

try:
    import numpy as np
    _HAS_NUMPY = True
except Exception:
    np = None
    _HAS_NUMPY = False


def _vector_model_name() -> str:
    try:
        from jarvis.core.config import load_config
        return load_config().get("memory", {}).get("vector_model", "sentence-transformers/all-MiniLM-L6-v2")
    except Exception:
        return "sentence-transformers/all-MiniLM-L6-v2"


class SemanticMemory:
    """Meaning-based long-term memory (singleton)."""

    def __init__(self, db_path: str | Path = "data/memory/semantic.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._model: Any = None
        self._tried_model = False
        self._init_db()
        logger.debug("[Memory] Semantic memory (L4) ready.")

    def _init_db(self) -> None:
        con = sqlite3.connect(self.db_path)
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                text      TEXT NOT NULL UNIQUE,
                category  TEXT DEFAULT 'general',
                ts        REAL NOT NULL,
                embedding BLOB
            )
            """
        )
        con.commit()
        con.close()

    # ── Embedding model (lazy) ────────────────────────────────────────────────
    def _ensure_model(self):
        if self._model is not None or self._tried_model:
            return self._model
        self._tried_model = True
        if not _HAS_NUMPY:
            return None
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(_vector_model_name())
            logger.info("[Memory] Semantic embedding model loaded (vector recall enabled).")
        except Exception as e:
            logger.info(f"[Memory] Embeddings unavailable, using keyword recall ({e}).")
            self._model = None
        return self._model

    def _embed(self, text: str) -> Optional[bytes]:
        model = self._ensure_model()
        if model is None:
            return None
        try:
            vec = model.encode([text], normalize_embeddings=True)[0].astype("float32")
            return vec.tobytes()
        except Exception:
            return None

    # ── Public API ────────────────────────────────────────────────────────────
    def add(self, text: str, category: str = "general") -> bool:
        text = (text or "").strip()
        if not text:
            return False
        try:
            con = sqlite3.connect(self.db_path)
            con.execute(
                "INSERT OR IGNORE INTO memories (text, category, ts, embedding) VALUES (?, ?, ?, ?)",
                (text, category, time.time(), None),  # embedding filled lazily on recall
            )
            con.commit()
            con.close()
            return True
        except Exception as e:
            logger.debug(f"[Memory] Semantic add failed: {e}")
            return False

    def recall(self, query: str, k: int = 5) -> List[str]:
        query = (query or "").strip()
        if not query:
            return []
        self._backfill_if_empty()
        model = self._ensure_model()
        if model is not None and _HAS_NUMPY:
            vectors = self._vector_recall(query, k)
            if vectors:
                return vectors
        return self._keyword_recall(query, k)

    def count(self) -> int:
        con = sqlite3.connect(self.db_path)
        n = con.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        con.close()
        return int(n)

    # ── Backends ──────────────────────────────────────────────────────────────
    def _keyword_recall(self, query: str, k: int) -> List[str]:
        con = sqlite3.connect(self.db_path)
        q = f"%{query}%"
        rows = con.execute(
            "SELECT text FROM memories WHERE text LIKE ? OR category LIKE ? ORDER BY ts DESC LIMIT ?",
            (q, q, k),
        ).fetchall()
        con.close()
        return [r[0] for r in rows]

    def _vector_recall(self, query: str, k: int) -> List[str]:
        try:
            self._ensure_embeddings()
            if np is None or self._model is None:
                return []
            con = sqlite3.connect(self.db_path)
            rows = con.execute("SELECT text, embedding FROM memories WHERE embedding IS NOT NULL").fetchall()
            con.close()
            if not rows:
                return []
            _np: Any = np
            texts = [r[0] for r in rows]
            matrix = _np.frombuffer(b"".join(r[1] for r in rows), dtype="float32")
            dim = matrix.size // len(rows)
            matrix = matrix.reshape(len(rows), dim)
            qvec = self._model.encode([query], normalize_embeddings=True)[0].astype("float32")
            scores = matrix @ qvec  # cosine (vectors are normalized)
            top = _np.argsort(-scores)[:k]
            return [texts[i] for i in top if scores[i] > 0.25]
        except Exception as e:
            logger.debug(f"[Memory] Vector recall failed: {e}")
            return []

    def _ensure_embeddings(self) -> None:
        """Compute and persist embeddings for any rows missing them."""
        con = sqlite3.connect(self.db_path)
        rows = con.execute("SELECT id, text FROM memories WHERE embedding IS NULL").fetchall()
        for rid, text in rows:
            blob = self._embed(text)
            if blob is not None:
                con.execute("UPDATE memories SET embedding = ? WHERE id = ?", (blob, rid))
        con.commit()
        con.close()

    def _backfill_if_empty(self) -> None:
        """Seed the semantic store from the existing facts list the first time."""
        if self.count() > 0:
            return
        try:
            from jarvis.core.memory import memory_manager
            for item in memory_manager._facts:
                fact = item.get("fact", "")
                if fact:
                    self.add(fact, item.get("category", "general"))
        except Exception as e:
            logger.debug(f"[Memory] Semantic backfill skipped: {e}")


# Process-wide singleton
semantic_memory = SemanticMemory()
