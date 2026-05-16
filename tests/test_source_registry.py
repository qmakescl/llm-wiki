"""source registry tests."""

from __future__ import annotations

from wiki_cli import source_registry
from wiki_cli.ops.ingest import DuplicateSourceError, run_ingest


def test_register_uploaded_source_creates_registry_row(tmp_path):
    data_root = tmp_path / "data"
    raw = data_root / "raw"
    raw.mkdir(parents=True)
    source = raw / "paper.txt"
    source.write_text("same content", encoding="utf-8")

    record = source_registry.register_uploaded_source(data_root, source)

    assert record["filename"] == "paper.txt"
    assert record["relative_path"] == "raw/paper.txt"
    assert record["size"] == len("same content")
    assert record["sha256"] == source_registry.sha256_file(source)
    assert record["ingested_at"] == ""
    assert source_registry.registry_path(data_root).exists()


def test_mark_ingested_updates_existing_row(tmp_path):
    data_root = tmp_path / "data"
    raw = data_root / "raw"
    raw.mkdir(parents=True)
    source = raw / "paper.txt"
    source.write_text("content", encoding="utf-8")
    source_registry.register_uploaded_source(data_root, source)

    record = source_registry.mark_ingested(
        data_root,
        source,
        summary_page="sources/paper.md",
        model="gpt-4o",
    )

    assert record["ingested_at"]
    assert record["summary_page"] == "sources/paper.md"
    assert record["model"] == "gpt-4o"
    records = source_registry.load_records(data_root)
    assert len(records) == 1


def test_find_ingested_duplicate_uses_hash_not_filename(tmp_path):
    data_root = tmp_path / "data"
    wiki_root = tmp_path / "wiki"
    raw = data_root / "raw"
    (wiki_root / "sources").mkdir(parents=True)
    raw.mkdir(parents=True)
    first = raw / "paper.txt"
    second = raw / "renamed.txt"
    first.write_text("same content", encoding="utf-8")
    second.write_text("same content", encoding="utf-8")
    (wiki_root / "sources" / "paper.md").write_text("summary", encoding="utf-8")

    source_registry.mark_ingested(
        data_root,
        first,
        summary_page="sources/paper.md",
        model="",
    )

    duplicate = source_registry.find_ingested_duplicate(data_root, second, wiki_root)
    assert duplicate is not None
    assert duplicate["relative_path"] == "raw/paper.txt"
    assert duplicate["summary_page"] == "sources/paper.md"


def test_record_is_complete_requires_summary_page_when_wiki_root_is_supplied(tmp_path):
    data_root = tmp_path / "data"
    wiki_root = tmp_path / "wiki"
    raw = data_root / "raw"
    raw.mkdir(parents=True)
    source = raw / "paper.txt"
    source.write_text("content", encoding="utf-8")

    record = source_registry.mark_ingested(
        data_root,
        source,
        summary_page="sources/paper.md",
        model="",
    )

    assert not source_registry.record_is_complete(record, wiki_root)
    (wiki_root / "sources").mkdir(parents=True)
    (wiki_root / "sources" / "paper.md").write_text("summary", encoding="utf-8")
    assert source_registry.record_is_complete(record, wiki_root)


def test_register_same_path_refreshes_without_duplicate_rows(tmp_path):
    data_root = tmp_path / "data"
    raw = data_root / "raw"
    raw.mkdir(parents=True)
    source = raw / "paper.txt"
    source.write_text("v1", encoding="utf-8")
    first = source_registry.register_uploaded_source(data_root, source)

    source.write_text("v2", encoding="utf-8")
    second = source_registry.register_uploaded_source(data_root, source)

    assert first["source_id"] == second["source_id"]
    assert second["sha256"] == source_registry.sha256_file(source)
    assert len(source_registry.load_records(data_root)) == 1


def test_run_ingest_rejects_hash_duplicate_before_llm_call(tmp_path):
    wiki_root = tmp_path / "wiki"
    data_root = tmp_path / "data"
    raw = data_root / "raw"
    (wiki_root / "sources").mkdir(parents=True)
    raw.mkdir(parents=True)
    (wiki_root / "AGENTS.md").write_text("schema", encoding="utf-8")

    first = raw / "paper.txt"
    second = raw / "renamed.txt"
    first.write_text("same content", encoding="utf-8")
    second.write_text("same content", encoding="utf-8")
    (wiki_root / "sources" / "paper.md").write_text("summary", encoding="utf-8")
    source_registry.mark_ingested(
        data_root,
        first,
        summary_page="sources/paper.md",
        model="",
    )

    try:
        run_ingest(wiki_root, second, model=None, data_root=data_root)
    except DuplicateSourceError as e:
        assert "동일한 내용" in str(e)
    else:
        raise AssertionError("expected DuplicateSourceError")


def test_run_ingest_allows_retry_when_source_page_exists_without_registry_completion(tmp_path, monkeypatch):
    wiki_root = tmp_path / "wiki"
    data_root = tmp_path / "data"
    raw = data_root / "raw"
    (wiki_root / "sources").mkdir(parents=True)
    raw.mkdir(parents=True)
    (wiki_root / "AGENTS.md").write_text("schema", encoding="utf-8")
    source = raw / "paper.txt"
    source.write_text("content", encoding="utf-8")
    (wiki_root / "sources" / "paper.md").write_text("partial", encoding="utf-8")
    source_registry.register_uploaded_source(data_root, source)

    monkeypatch.setattr(
        "wiki_cli.structured_ingest.extract_from_file",
        lambda **kwargs: (
            {
                "summary": "summary",
                "claims": [],
                "entities": [],
                "concepts": [],
                "uncertainties": [],
                "contradiction_candidates": [],
            },
            "raw",
        ),
    )
    monkeypatch.setattr("wiki_cli.vector_index.refresh_page", lambda *args, **kwargs: None)
    monkeypatch.setattr("wiki_cli.ops.ingest.trigger_sync", lambda *args, **kwargs: None)

    run_ingest(wiki_root, source, model=None, data_root=data_root)

    assert source_registry.source_is_ingested(data_root, wiki_root, source)
