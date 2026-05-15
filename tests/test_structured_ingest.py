"""structured ingest extraction tests."""

from __future__ import annotations

import json

from wiki_cli import structured_ingest
from wiki_cli.ops.ingest import run_ingest


def test_parse_structured_result_from_json_fence():
    raw = """```json
{
  "summary": "A short summary.",
  "claims": [{"claim": "Models can maintain a wiki.", "confidence": "high"}],
  "entities": [{"title": "OpenAI", "action": "update", "summary": "An AI lab"}],
  "concepts": [{"title": "LLM Wiki", "slug": "llm-wiki", "summary": "Persistent wiki"}],
  "uncertainties": [{"note": "Needs validation"}]
}
```"""

    parsed = structured_ingest.parse_structured_result(raw)

    assert parsed is not None
    assert parsed["summary"] == "A short summary."
    assert parsed["entities"][0]["slug"] == "openai"
    assert parsed["entities"][0]["action"] == "update"
    assert parsed["concepts"][0]["slug"] == "llm-wiki"


def test_entries_from_result():
    parsed = structured_ingest.parse_structured_result(json.dumps({
        "summary": "summary",
        "entities": [{"title": "OpenAI", "action": "update"}],
        "concepts": [{"title": "LLM Wiki"}],
    }))
    assert parsed is not None

    entities, concepts = structured_ingest.entries_from_result(parsed)

    assert entities == [("update", "openai")]
    assert concepts == [("create", "llm-wiki")]


def test_to_overview_renders_compact_markdown():
    parsed = structured_ingest.parse_structured_result(json.dumps({
        "summary": "summary",
        "claims": [{"claim": "Claim A", "evidence": "Quote A"}],
        "entities": [{"title": "OpenAI", "summary": "AI lab", "evidence": ["Quote B"]}],
        "uncertainties": [{"note": "Maybe stale"}],
    }))
    assert parsed is not None

    overview = structured_ingest.to_overview(parsed)

    assert "## Summary" in overview
    assert "Claim A" in overview
    assert "OpenAI" in overview
    assert "Maybe stale" in overview


def test_render_source_page_from_structured_result():
    parsed = structured_ingest.parse_structured_result(json.dumps({
        "summary": "summary",
        "claims": [{"claim": "Claim A", "evidence": "Quote A"}],
        "entities": [{"title": "OpenAI", "summary": "AI lab"}],
        "concepts": [{"title": "LLM Wiki", "summary": "Persistent wiki"}],
    }))
    assert parsed is not None

    meta, body = structured_ingest.render_source_page(parsed, source_name="paper.txt", fallback_title="paper")

    assert meta["title"] == "paper"
    assert meta["type"] == "source"
    assert "[[OpenAI]]" in body
    assert "Claim A" in body


def test_run_ingest_structured_path_skips_planning_llm(tmp_path, monkeypatch):
    wiki_root = tmp_path / "wiki"
    wiki_root.mkdir()
    (wiki_root / "AGENTS.md").write_text("schema", encoding="utf-8")
    source = tmp_path / "paper.txt"
    source.write_text("source text", encoding="utf-8")

    structured_json = json.dumps({
        "summary": "This source explains persistent LLM-maintained wikis.",
        "entities": [{"title": "OpenAI", "slug": "openai", "summary": "AI lab"}],
        "concepts": [{"title": "LLM Wiki", "slug": "llm-wiki", "summary": "Persistent wiki"}],
    })
    monkeypatch.setattr("wiki_cli.llm.call_with_file", lambda *args, **kwargs: structured_json)

    prompts: list[str] = []

    def fake_call(prompt: str, **kwargs):
        prompts.append(prompt)
        assert "Based on this source overview" not in prompt
        assert "Write a wiki page summarising" not in prompt
        if "Create a new wiki page for:" in prompt:
            title = prompt.split("Create a new wiki page for:", 1)[1].splitlines()[0].strip()
            return f"""---
title: "{title}"
type: concept
tags: []
sources: ["paper.txt"]
---

# {title}

Created from structured evidence.
"""
        raise AssertionError(f"unexpected prompt: {prompt[:120]}")

    monkeypatch.setattr("wiki_cli.llm.call", fake_call)

    run_ingest(wiki_root, source, model="gpt-4o")

    assert len(prompts) == 2
    assert (wiki_root / "sources" / "paper.md").exists()
    assert (wiki_root / "entities" / "Openai.md").exists()
    assert (wiki_root / "concepts" / "Llm Wiki.md").exists()


def test_run_ingest_refreshes_vector_index_for_created_pages(tmp_path, monkeypatch):
    wiki_root = tmp_path / "wiki"
    wiki_root.mkdir()
    (wiki_root / "AGENTS.md").write_text("schema", encoding="utf-8")
    source = tmp_path / "paper.txt"
    source.write_text("source text", encoding="utf-8")

    structured_json = json.dumps({
        "summary": "This source explains retrieval.",
        "entities": [{"title": "OpenAI", "slug": "openai", "summary": "AI lab"}],
        "concepts": [{"title": "Retrieval", "slug": "retrieval", "summary": "Search concept"}],
    })
    monkeypatch.setattr("wiki_cli.llm.call_with_file", lambda *args, **kwargs: structured_json)

    def fake_call(prompt: str, **kwargs):
        title = prompt.split("Create a new wiki page for:", 1)[1].splitlines()[0].strip()
        kind = "entity" if "Kind: entit" in prompt else "concept"
        return f"""---
title: "{title}"
type: {kind}
tags: []
sources: ["paper.txt"]
---

# {title}

Created from structured evidence.
"""

    refreshed: list[str] = []

    def fake_refresh_page(wiki_dir, page_path):
        refreshed.append(page_path.relative_to(wiki_dir).as_posix())
        from wiki_cli.vector_index import VectorIndexStats
        return VectorIndexStats(pages_indexed=1, chunks_indexed=1)

    monkeypatch.setattr("wiki_cli.llm.call", fake_call)
    monkeypatch.setattr("wiki_cli.vector_index.refresh_page", fake_refresh_page)

    run_ingest(wiki_root, source, model="gpt-4o")

    assert refreshed == [
        "sources/paper.md",
        "entities/Openai.md",
        "concepts/Retrieval.md",
    ]
