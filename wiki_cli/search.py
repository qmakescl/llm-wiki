"""Pluggable search over wiki/ markdown files.

Tier 1 (default): grep / ripgrep — zero deps, works instantly.
Tier 2 (opt-in):  BM25 via rank_bm25 — set WIKI_SEARCH=bm25.
Tier 3 (opt-in):  Embedding similarity — set WIKI_SEARCH=embedding.

Switching tiers never changes the call sites — same interface throughout.
"""

from __future__ import annotations

import hashlib
import logging
import os
import pickle
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# 임베딩 검색용 전역 모델/캐시 — 각 쿼리마다 재생성하지 않도록 singleton으로 유지.
_EMBEDDING_MODEL = None  # SentenceTransformer 인스턴스 (lazy init)
_EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"


@dataclass
class SearchResult:
    path: Path
    score: float          # higher = more relevant
    snippet: str          # short context around the match


# ── Public API ───────────────────────────────────────────────────────────────

def search(query: str, wiki_dir: Path, top_k: int = 8) -> list[SearchResult]:
    """Return the top_k most relevant wiki pages for query."""
    tier = os.environ.get("WIKI_SEARCH", "grep").lower()
    if tier == "bm25":
        return _bm25_search(query, wiki_dir, top_k)
    if tier == "embedding":
        return _embedding_search(query, wiki_dir, top_k)
    return _grep_search(query, wiki_dir, top_k)


def read_index(wiki_dir: Path) -> str:
    """Return the full text of index.md (used before targeted search)."""
    idx = wiki_dir / "index.md"
    return idx.read_text(encoding="utf-8") if idx.exists() else ""


# ── Tier 1: grep ─────────────────────────────────────────────────────────────

def _grep_search(query: str, wiki_dir: Path, top_k: int) -> list[SearchResult]:
    """Simple grep over all .md files. Ranks by match count."""
    words = [w for w in query.lower().split() if len(w) > 2]
    if not words:
        return []

    md_files = list(wiki_dir.rglob("*.md"))
    scored: list[tuple[float, Path, str]] = []

    for md in md_files:
        try:
            text = md.read_text(encoding="utf-8", errors="replace").lower()
        except OSError:
            continue
        score = sum(text.count(w) for w in words)
        if score == 0:
            continue
        # snippet: first line that contains a query word
        snippet = _first_matching_line(md, words)
        scored.append((score, md, snippet))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        SearchResult(path=p, score=s, snippet=snip)
        for s, p, snip in scored[:top_k]
    ]


def _first_matching_line(path: Path, words: list[str]) -> str:
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if any(w in line.lower() for w in words):
                return line.strip()[:120]
    except OSError:
        pass
    return ""


# ── Tier 2: BM25 (rank_bm25) ─────────────────────────────────────────────────

def _bm25_search(query: str, wiki_dir: Path, top_k: int) -> list[SearchResult]:
    try:
        from rank_bm25 import BM25Okapi
    except ImportError:
        logger.warning(
            "rank_bm25 미설치 — grep으로 대체합니다. "
            "BM25 검색을 사용하려면: pip install rank-bm25"
        )
        return _grep_search(query, wiki_dir, top_k)

    md_files = list(wiki_dir.rglob("*.md"))
    corpus = []
    for md in md_files:
        try:
            corpus.append(md.read_text(encoding="utf-8", errors="replace").lower().split())
        except OSError:
            corpus.append([])

    bm25 = BM25Okapi(corpus)
    scores = bm25.get_scores(query.lower().split())

    indexed = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
    words = [w for w in query.lower().split() if len(w) > 2]
    return [
        SearchResult(
            path=md_files[i],
            score=float(s),
            snippet=_first_matching_line(md_files[i], words),
        )
        for i, s in indexed[:top_k]
        if s > 0
    ]


# ── Tier 3: embedding (sentence-transformers) ─────────────────────────────────

def _embedding_search(query: str, wiki_dir: Path, top_k: int) -> list[SearchResult]:
    try:
        import numpy as np
    except ImportError:
        logger.warning(
            "sentence-transformers 미설치 — grep으로 대체합니다. "
            "임베딩 검색을 사용하려면: pip install sentence-transformers"
        )
        return _grep_search(query, wiki_dir, top_k)

    model = _get_embedding_model()
    if model is None:
        return _grep_search(query, wiki_dir, top_k)

    md_files = list(wiki_dir.rglob("*.md"))
    if not md_files:
        return []

    doc_embs = _compute_doc_embeddings(md_files, wiki_dir, model)
    q_emb = model.encode([query])[0]

    # cosine similarity
    norms = np.linalg.norm(doc_embs, axis=1, keepdims=True) + 1e-9
    sims = (doc_embs / norms) @ q_emb / (np.linalg.norm(q_emb) + 1e-9)

    indexed = sorted(enumerate(sims), key=lambda x: x[1], reverse=True)
    words = [w for w in query.lower().split() if len(w) > 2]
    return [
        SearchResult(
            path=md_files[i],
            score=float(s),
            snippet=_first_matching_line(md_files[i], words),
        )
        for i, s in indexed[:top_k]
        if s > 0.2
    ]


def _get_embedding_model():
    """SentenceTransformer를 프로세스 전역 singleton으로 로드.

    매 쿼리마다 모델 가중치를 다시 읽으면 수 초가 추가되므로 모듈 상수로 캐싱한다.
    """
    global _EMBEDDING_MODEL
    if _EMBEDDING_MODEL is not None:
        return _EMBEDDING_MODEL
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        logger.warning(
            "sentence-transformers 미설치 — grep으로 대체합니다. "
            "임베딩 검색을 사용하려면: pip install sentence-transformers"
        )
        return None
    logger.info("SentenceTransformer 모델 로드: %s", _EMBEDDING_MODEL_NAME)
    _EMBEDDING_MODEL = SentenceTransformer(_EMBEDDING_MODEL_NAME)
    return _EMBEDDING_MODEL


def _compute_doc_embeddings(md_files: list[Path], wiki_dir: Path, model):
    """파일 내용 해시를 키로 per-file 임베딩을 디스크에 캐싱한다.

    캐시 위치: `<wiki_dir>/.embeddings/<model>.pkl` — dict[file_hash, vector].
    변경되지 않은 파일의 임베딩은 재계산 없이 재사용하고, 새/수정된 파일만
    encode() 로 배치 처리한다.
    """
    import numpy as np

    cache_path = wiki_dir / ".embeddings" / f"{_EMBEDDING_MODEL_NAME}.pkl"
    cache: dict[str, "np.ndarray"] = _load_cache(cache_path)

    file_keys: list[str] = []
    texts_for_files: list[str] = []
    for md in md_files:
        try:
            text = md.read_text(encoding="utf-8", errors="replace")[:2000]
        except OSError:
            text = ""
        file_keys.append(_text_hash(text))
        texts_for_files.append(text)

    missing_idx = [i for i, k in enumerate(file_keys) if k not in cache]
    if missing_idx:
        new_vecs = model.encode([texts_for_files[i] for i in missing_idx], show_progress_bar=False)
        for vec_idx, file_idx in enumerate(missing_idx):
            cache[file_keys[file_idx]] = new_vecs[vec_idx]
        _save_cache(cache_path, cache)

    return np.array([cache[k] for k in file_keys])


def _text_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="replace")).hexdigest()


def _load_cache(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with path.open("rb") as f:
            return pickle.load(f)
    except Exception as e:
        logger.warning("임베딩 캐시 로드 실패(%s): %s — 새로 생성합니다.", path, e)
        return {}


def _save_cache(path: Path, cache: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as f:
            pickle.dump(cache, f)
    except OSError as e:
        logger.warning("임베딩 캐시 저장 실패(%s): %s", path, e)
