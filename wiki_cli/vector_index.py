"""Local SQLite vector index for chunk-level wiki search."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from wiki_cli import fs

logger = logging.getLogger(__name__)

_EMBEDDING_MODEL = None
_EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Chunk:
    heading: str
    chunk_index: int
    text: str


@dataclass(frozen=True)
class VectorIndexStats:
    pages_indexed: int = 0
    chunks_indexed: int = 0
    pages_deleted: int = 0
    errors: int = 0


@dataclass(frozen=True)
class VectorChunkResult:
    chunk_id: str
    wiki_path: str
    page_title: str
    heading: str
    chunk_index: int
    chunk_text: str
    score: float


def refresh_page(wiki_dir: Path, page_path: Path) -> VectorIndexStats:
    """Rebuild vector chunks for a single markdown page."""
    if not page_path.exists() or page_path.suffix.lower() != ".md":
        delete_page(wiki_dir, page_path)
        return VectorIndexStats(pages_deleted=1)

    model = _get_embedding_model()
    if model is None:
        return VectorIndexStats(errors=1)

    try:
        rel = _relative_wiki_path(wiki_dir, page_path)
        metadata, body = fs.read_page(page_path)
        title = str(metadata.get("title") or page_path.stem)
        strategy, chunk_size, chunk_overlap = _get_chunk_config()
        chunks = chunk_markdown_for_search(body, strategy, chunk_size, chunk_overlap)
        vectors = model.encode([c.text for c in chunks], show_progress_bar=False) if chunks else []
        now = _now()

        with _connect(wiki_dir) as conn:
            _init_db(conn)
            conn.execute("DELETE FROM chunks WHERE wiki_path = ?", (rel,))
            for chunk, vector in zip(chunks, vectors, strict=True):
                content_hash = _hash(chunk.text)
                chunk_id = _chunk_id(rel, chunk.heading, chunk.chunk_index, content_hash)
                vector_list = _to_float_list(vector)
                conn.execute(
                    """
                    INSERT INTO chunks (
                        chunk_id, wiki_path, page_title, heading, chunk_index,
                        chunk_text, content_hash, model_name, embedding_dim,
                        embedding, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk_id,
                        rel,
                        title,
                        chunk.heading,
                        chunk.chunk_index,
                        chunk.text,
                        content_hash,
                        _EMBEDDING_MODEL_NAME,
                        len(vector_list),
                        json.dumps(vector_list),
                        now,
                        now,
                    ),
                )
        return VectorIndexStats(pages_indexed=1, chunks_indexed=len(chunks))
    except Exception as exc:
        logger.warning("vector index refresh failed for %s: %s", page_path, exc)
        return VectorIndexStats(errors=1)


def refresh_all(wiki_dir: Path) -> VectorIndexStats:
    """Rebuild the vector index for every wiki markdown page."""
    total = VectorIndexStats()
    for page in fs.list_pages(wiki_dir):
        if _should_index_page(wiki_dir, page):
            total = _merge_stats(total, refresh_page(wiki_dir, page))
    return total


def search_chunks(query: str, wiki_dir: Path, top_k: int) -> list[VectorChunkResult]:
    """Search indexed chunks by cosine similarity."""
    model = _get_embedding_model()
    if model is None:
        return []

    try:
        query_vector = _to_float_list(model.encode([query], show_progress_bar=False)[0])
        with _connect(wiki_dir) as conn:
            _init_db(conn)
            rows = conn.execute(
                """
                SELECT chunk_id, wiki_path, page_title, heading, chunk_index,
                       chunk_text, embedding
                FROM chunks
                WHERE model_name = ?
                """,
                (_EMBEDDING_MODEL_NAME,),
            ).fetchall()
    except Exception as exc:
        logger.warning("vector search failed: %s", exc)
        return []

    scored: list[VectorChunkResult] = []
    for row in rows:
        try:
            vector = [float(v) for v in json.loads(row["embedding"])]
            score = _cosine(query_vector, vector)
        except Exception:
            continue
        if score <= 0:
            continue
        scored.append(
            VectorChunkResult(
                chunk_id=row["chunk_id"],
                wiki_path=row["wiki_path"],
                page_title=row["page_title"],
                heading=row["heading"],
                chunk_index=int(row["chunk_index"]),
                chunk_text=row["chunk_text"],
                score=score,
            )
        )
    scored.sort(key=lambda r: r.score, reverse=True)
    return scored[:top_k]


def delete_page(wiki_dir: Path, page_path: Path) -> None:
    rel = _relative_wiki_path(wiki_dir, page_path)
    with _connect(wiki_dir) as conn:
        _init_db(conn)
        conn.execute("DELETE FROM chunks WHERE wiki_path = ?", (rel,))


def clear(wiki_dir: Path) -> None:
    db_path = _db_path(wiki_dir)
    if db_path.exists():
        db_path.unlink()


def stats(wiki_dir: Path) -> dict[str, int | str]:
    with _connect(wiki_dir) as conn:
        _init_db(conn)
        row = conn.execute(
            "SELECT COUNT(DISTINCT wiki_path) AS pages, COUNT(*) AS chunks FROM chunks"
        ).fetchone()
    return {
        "path": str(_db_path(wiki_dir)),
        "pages": int(row["pages"] or 0),
        "chunks": int(row["chunks"] or 0),
    }


def chunk_markdown_for_search(
    text: str,
    strategy: str,
    chunk_size: int,
    chunk_overlap: int,
) -> list[Chunk]:
    """Split markdown into search chunks without truncating long pages."""
    normalized_strategy = (strategy or "section").lower()
    chunk_size = max(100, int(chunk_size or 500))
    chunk_overlap = max(0, min(int(chunk_overlap or 0), chunk_size - 1))

    if normalized_strategy == "fixed":
        return _fixed_chunks(text, chunk_size, chunk_overlap, heading="")
    if normalized_strategy == "none":
        if len(text) <= chunk_size:
            cleaned = text.strip()
            return [Chunk("", 0, cleaned)] if cleaned else []
        logger.warning("WIKI_CHUNK_STRATEGY=none but page is long; using fixed search chunks")
        return _fixed_chunks(text, chunk_size, chunk_overlap, heading="")
    return _section_chunks(text, chunk_size, chunk_overlap)


def _section_chunks(text: str, chunk_size: int, chunk_overlap: int) -> list[Chunk]:
    sections: list[tuple[str, str]] = []
    current_heading = ""
    current_lines: list[str] = []

    def flush() -> None:
        body = "\n".join(current_lines).strip()
        if body:
            sections.append((current_heading, body))

    for line in text.splitlines():
        if line.startswith("#"):
            stripped = line.lstrip("#").strip()
            if stripped:
                flush()
                current_heading = stripped
                current_lines = [line]
                continue
        current_lines.append(line)
    flush()

    chunks: list[Chunk] = []
    for heading, section_text in sections or [("", text.strip())]:
        if not section_text:
            continue
        if len(section_text) <= chunk_size:
            chunks.append(Chunk(heading, len(chunks), section_text))
        else:
            for chunk in _fixed_chunks(section_text, chunk_size, chunk_overlap, heading):
                chunks.append(Chunk(chunk.heading, len(chunks), chunk.text))
    return chunks


def _fixed_chunks(text: str, chunk_size: int, chunk_overlap: int, heading: str) -> list[Chunk]:
    cleaned = text.strip()
    if not cleaned:
        return []
    chunks: list[Chunk] = []
    start = 0
    while start < len(cleaned):
        part = cleaned[start:start + chunk_size].strip()
        if part:
            chunks.append(Chunk(heading, len(chunks), part))
        next_start = start + chunk_size - chunk_overlap
        if next_start <= start:
            break
        start = next_start
    return chunks


def _connect(wiki_dir: Path) -> sqlite3.Connection:
    db_path = _db_path(wiki_dir)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chunks (
            chunk_id TEXT PRIMARY KEY,
            wiki_path TEXT NOT NULL,
            page_title TEXT NOT NULL,
            heading TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            chunk_text TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            model_name TEXT NOT NULL,
            embedding_dim INTEGER NOT NULL,
            embedding TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_wiki_path ON chunks(wiki_path)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_model ON chunks(model_name)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "INSERT OR REPLACE INTO metadata(key, value) VALUES ('schema_version', ?)",
        (str(_SCHEMA_VERSION),),
    )


def _db_path(wiki_dir: Path) -> Path:
    return wiki_dir / ".vectors" / "vector_index.sqlite"


def _get_chunk_config() -> tuple[str, int, int]:
    return (
        os.environ.get("WIKI_CHUNK_STRATEGY", "section"),
        _env_int("WIKI_CHUNK_SIZE", 500),
        _env_int("WIKI_CHUNK_OVERLAP", 100),
    )


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _get_embedding_model():
    global _EMBEDDING_MODEL
    if _EMBEDDING_MODEL is not None:
        return _EMBEDDING_MODEL
    try:
        from sentence_transformers import SentenceTransformer
    except Exception as exc:
        logger.warning(
            "sentence-transformers 로드 실패 - vector 검색은 grep으로 대체됩니다: %s",
            exc,
        )
        return None
    try:
        logger.info("SentenceTransformer 모델 로드: %s", _EMBEDDING_MODEL_NAME)
        _EMBEDDING_MODEL = SentenceTransformer(_EMBEDDING_MODEL_NAME)
    except Exception as exc:
        logger.warning("SentenceTransformer 모델 로드 실패 - vector 검색은 grep으로 대체됩니다: %s", exc)
        return None
    return _EMBEDDING_MODEL


def _relative_wiki_path(wiki_dir: Path, page_path: Path) -> str:
    try:
        return page_path.relative_to(wiki_dir).as_posix()
    except ValueError:
        return page_path.name


def _should_index_page(wiki_dir: Path, page_path: Path) -> bool:
    try:
        rel = page_path.relative_to(wiki_dir)
    except ValueError:
        return False
    return not any(part.startswith(".") for part in rel.parts)


def _chunk_id(wiki_path: str, heading: str, chunk_index: int, content_hash: str) -> str:
    return _hash(f"{wiki_path}\n{heading}\n{chunk_index}\n{content_hash}")


def _hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="replace")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_float_list(vector) -> list[float]:
    if hasattr(vector, "tolist"):
        vector = vector.tolist()
    return [float(v) for v in vector]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _merge_stats(a: VectorIndexStats, b: VectorIndexStats) -> VectorIndexStats:
    return VectorIndexStats(
        pages_indexed=a.pages_indexed + b.pages_indexed,
        chunks_indexed=a.chunks_indexed + b.chunks_indexed,
        pages_deleted=a.pages_deleted + b.pages_deleted,
        errors=a.errors + b.errors,
    )
