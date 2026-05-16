"""documents router file-state tests."""

from __future__ import annotations

from wiki_cli import source_registry
from wiki_web.routers.documents import _raw_files


def test_raw_files_uses_registry_completion_not_source_page_existence(tmp_path):
    wiki_root = tmp_path / "wiki"
    data_root = tmp_path / "data"
    raw = data_root / "raw"
    (wiki_root / "sources").mkdir(parents=True)
    raw.mkdir(parents=True)
    source = raw / "paper.txt"
    source.write_text("content", encoding="utf-8")
    source_registry.register_uploaded_source(data_root, source)

    (wiki_root / "sources" / "paper.md").write_text("partial", encoding="utf-8")
    [file_info] = _raw_files(wiki_root, data_root)

    assert file_info["ingested"] is False
    assert file_info["partial"] is True

    source_registry.mark_ingested(
        data_root,
        source,
        summary_page="sources/paper.md",
        model="",
    )
    [file_info] = _raw_files(wiki_root, data_root)

    assert file_info["ingested"] is True
    assert file_info["partial"] is False
