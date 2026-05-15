"""Vector index tests."""

from __future__ import annotations

from wiki_cli import fs, search, vector_index
from wiki_cli.ops import query as query_ops


class FakeEmbeddingModel:
    def encode(self, texts, show_progress_bar=False):
        return [_fake_vector(text) for text in texts]


def _fake_vector(text: str) -> list[float]:
    lowered = text.lower()
    return [
        float(lowered.count("apple")),
        float(lowered.count("banana")),
        float(lowered.count("carrot")),
        float(lowered.count("retrieval")),
    ]


def test_chunk_markdown_for_search_preserves_headings():
    chunks = vector_index.chunk_markdown_for_search(
        "# Intro\n\nAlpha\n\n## Details\n\nBeta",
        strategy="section",
        chunk_size=500,
        chunk_overlap=50,
    )

    assert [c.heading for c in chunks] == ["Intro", "Details"]
    assert "Alpha" in chunks[0].text
    assert "Beta" in chunks[1].text


def test_fixed_chunk_overlap_applies():
    text = "a" * 120
    chunks = vector_index.chunk_markdown_for_search(
        text,
        strategy="fixed",
        chunk_size=100,
        chunk_overlap=20,
    )

    assert [len(c.text) for c in chunks] == [100, 40]
    assert chunks[1].text == text[80:]


def test_refresh_page_replaces_existing_chunks(wiki_root, monkeypatch):
    monkeypatch.setattr(vector_index, "_EMBEDDING_MODEL", FakeEmbeddingModel())
    page = wiki_root / "concepts" / "Fruit.md"
    fs.write_page(page, {"title": "Fruit", "type": "concept"}, "# Fruit\n\napple apple")

    first = vector_index.refresh_page(wiki_root, page)
    fs.write_page(page, {"title": "Fruit", "type": "concept"}, "# Fruit\n\nbanana banana")
    second = vector_index.refresh_page(wiki_root, page)
    results = vector_index.search_chunks("banana", wiki_root, top_k=3)
    info = vector_index.stats(wiki_root)

    assert first.chunks_indexed == 1
    assert second.chunks_indexed == 1
    assert info["chunks"] == 1
    assert results[0].wiki_path == "concepts/Fruit.md"
    assert "banana" in results[0].chunk_text
    assert "apple" not in results[0].chunk_text


def test_search_vector_tier_returns_chunk_metadata(wiki_root, monkeypatch):
    monkeypatch.setattr(vector_index, "_EMBEDDING_MODEL", FakeEmbeddingModel())
    monkeypatch.setenv("WIKI_SEARCH", "vector")
    page = wiki_root / "concepts" / "Retrieval.md"
    fs.write_page(
        page,
        {"title": "Retrieval", "type": "concept"},
        "# Retrieval\n\nretrieval retrieval\n\n## Other\n\ncarrot",
    )
    vector_index.refresh_page(wiki_root, page)

    results = search.search("retrieval", wiki_root, top_k=3)

    assert results
    assert results[0].metadata
    assert results[0].metadata["kind"] == "vector_chunk"
    assert "retrieval" in results[0].metadata["chunk_text"]


def test_search_vector_tier_falls_back_to_grep(wiki_root, monkeypatch):
    monkeypatch.setenv("WIKI_SEARCH", "vector")
    monkeypatch.setattr(vector_index, "search_chunks", lambda query, wiki_dir, top_k: [])
    page = wiki_root / "concepts" / "Fallback.md"
    fs.write_page(page, {"title": "Fallback", "type": "concept"}, "# Fallback\n\nlexical fallback works")

    results = search.search("lexical fallback", wiki_root, top_k=3)

    assert results
    assert results[0].path.name == "Fallback.md"
    assert results[0].metadata is None


def test_refresh_page_skips_when_embedding_model_load_fails(wiki_root, monkeypatch):
    monkeypatch.setattr(vector_index, "_EMBEDDING_MODEL", None)

    def fail_import(name, *args, **kwargs):
        if name == "sentence_transformers":
            raise RuntimeError("model cache unavailable")
        return original_import(name, *args, **kwargs)

    original_import = __import__
    monkeypatch.setattr("builtins.__import__", fail_import)
    page = wiki_root / "concepts" / "Offline.md"
    fs.write_page(page, {"title": "Offline", "type": "concept"}, "# Offline\n\nretrieval")

    stats = vector_index.refresh_page(wiki_root, page)

    assert stats.errors == 1


def test_build_context_uses_vector_chunk_text(wiki_root):
    result = search.SearchResult(
        path=wiki_root / "concepts" / "Retrieval.md",
        score=0.9,
        snippet="short",
        metadata={
            "kind": "vector_chunk",
            "heading": "Evidence",
            "chunk_text": "chunk-only retrieval evidence",
        },
    )

    context = query_ops._build_context([result])

    assert "## Evidence" in context
    assert "chunk-only retrieval evidence" in context
