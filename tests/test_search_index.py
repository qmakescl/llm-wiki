"""search index cache tests."""

from __future__ import annotations

from wiki_cli import fs, search, search_index
from wiki_cli.metrics import Metrics


def test_search_index_reuses_unchanged_files(wiki_root):
    page = wiki_root / "concepts" / "Attention.md"
    fs.write_page(page, {"title": "Attention", "type": "concept"}, "# Attention\n\nAttention is all you need.")

    payload, stats = search_index.refresh_index(wiki_root)
    assert stats.updated_files == 1
    assert "concepts/Attention.md" in payload["entries"]

    payload2, stats2 = search_index.refresh_index(wiki_root)
    assert stats2.updated_files == 0
    assert payload2["entries"]["concepts/Attention.md"]["title"] == "Attention"


def test_search_index_updates_only_changed_file(wiki_root):
    a = wiki_root / "concepts" / "A.md"
    b = wiki_root / "concepts" / "B.md"
    fs.write_page(a, {"title": "A", "type": "concept"}, "# A\n\nalpha")
    fs.write_page(b, {"title": "B", "type": "concept"}, "# B\n\nbeta")
    search_index.refresh_index(wiki_root)

    fs.write_page(a, {"title": "A", "type": "concept"}, "# A\n\nalpha changed")
    _payload, stats = search_index.refresh_index(wiki_root)

    assert stats.updated_files == 1


def test_search_uses_index_and_returns_results(wiki_root):
    page = wiki_root / "concepts" / "Retrieval.md"
    fs.write_page(page, {"title": "Retrieval", "type": "concept"}, "# Retrieval\n\nHybrid retrieval combines lexical and semantic search.")

    results = search.search("semantic retrieval", wiki_root, top_k=3)

    assert results
    assert results[0].path.name == "Retrieval.md"
    assert (wiki_root / ".search" / "index.json").exists()


def test_search_records_metrics(wiki_root):
    page = wiki_root / "concepts" / "Metrics.md"
    fs.write_page(page, {"title": "Metrics", "type": "concept"}, "# Metrics\n\nSearch metrics are useful.")
    metrics = Metrics()

    results = search.search("metrics", wiki_root, metrics=metrics)

    assert results
    summary = metrics.summary()
    assert "search.total" in summary["timings"]
    assert summary["values"]["search.result_count"][-1] >= 1
