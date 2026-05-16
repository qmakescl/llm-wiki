"""documents router file-state tests."""

from __future__ import annotations

from types import SimpleNamespace

from wiki_cli import source_registry
from wiki_web.app import templates
from wiki_web.routers.documents import _done_control_html, _raw_files


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


def test_done_control_html_replaces_progress_with_complete_badge():
    job = SimpleNamespace(status="done", slug="paper")

    html = _done_control_html(job)

    assert "badge-success" in html
    assert "완료" in html
    assert "추출 진행 중" not in html


def test_failed_done_control_html_allows_retry():
    job = SimpleNamespace(status="failed", slug="paper")

    html = _done_control_html(job)

    assert "실패" in html
    assert "다시 Ingest" in html
    assert 'hx-post="/documents/ingest/paper"' in html


def test_ingest_progress_root_swaps_on_done_event():
    html = templates.env.get_template("partials/ingest_progress.html").render({
        "job_id": "job1",
        "filename": "paper.txt",
        "slug": "paper",
    })

    assert 'id="ingest-ctrl-paper"' in html
    assert 'sse-swap="done"' in html
    assert 'hx-swap="outerHTML"' in html
