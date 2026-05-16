"""query operation tests."""

from __future__ import annotations

from wiki_cli import fs, search
from wiki_cli.ops import query as query_ops


def test_run_query_requests_korean_answer_with_original_wikilinks(wiki_root, monkeypatch):
    monkeypatch.setenv("WIKI_OUTPUT_LANGUAGE", "ko")
    monkeypatch.delenv("WIKI_HEADING_ORIGINAL_LANGUAGE", raising=False)
    (wiki_root / "index.md").write_text("# Wiki index\n", encoding="utf-8")
    page = wiki_root / "concepts" / "Retrieval Augmented Generation.md"
    fs.write_page(
        page,
        {"title": "Retrieval Augmented Generation", "type": "concept"},
        "# Retrieval Augmented Generation\n\n검색 기반 생성에 대한 문서.",
    )

    monkeypatch.setattr(
        search,
        "search",
        lambda *args, **kwargs: [
            search.SearchResult(path=page, score=1.0, snippet="검색 기반 생성")
        ],
    )

    captured: dict[str, str] = {}

    def fake_call(prompt: str, **kwargs):
        captured["prompt"] = prompt
        return "Retrieval Augmented Generation은 검색 결과를 context로 활용한다. [[Retrieval Augmented Generation]]"

    monkeypatch.setattr("wiki_cli.llm.call", fake_call)

    answer = query_ops.run_query(wiki_root, "RAG가 뭐야?", model="gpt-4o", save=False)

    assert "Answer in Korean" in captured["prompt"]
    assert "Do not translate [[wikilink targets]]" in captured["prompt"]
    assert "[[Retrieval Augmented Generation]]" in answer
