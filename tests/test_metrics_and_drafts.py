"""metrics and draft workflow tests."""

from __future__ import annotations

from wiki_cli import drafts
from wiki_cli.metrics import Metrics


def test_metrics_records_counts_values_and_timers(tmp_path):
    metrics = Metrics()
    metrics.count("llm.calls")
    metrics.record("cache", "hit")
    with metrics.timer("work"):
        pass

    summary = metrics.summary()
    assert summary["counters"]["llm.calls"] == 1
    assert summary["values"]["cache"] == ["hit"]
    assert "work" in summary["timings"]

    out = tmp_path / "metrics.json"
    metrics.write_json(out)
    assert out.exists()


def test_draft_create_approve_and_delete(wiki_root):
    draft = drafts.create_draft(
        wiki_root,
        "job1",
        {"concepts/Draft.md": "---\ntitle: Draft\n---\n# Draft"},
    )
    assert draft.path.exists()
    assert not (wiki_root / "concepts" / "Draft.md").exists()

    written = drafts.approve_draft(wiki_root, "job1")
    assert written == [wiki_root / "concepts" / "Draft.md"]
    assert (wiki_root / "concepts" / "Draft.md").exists()

    drafts.delete_draft(wiki_root, "job1")
    assert not draft.path.exists()
