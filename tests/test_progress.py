"""progress job store tests."""

from __future__ import annotations

import pytest

from wiki_web import progress


@pytest.mark.anyio
async def test_clear_jobs_for_domain_removes_only_matching_jobs():
    progress._store.clear()
    progress._store["a"] = progress.IngestJob("a", "a.pdf", "Domain A")
    progress._store["b"] = progress.IngestJob("b", "b.pdf", "Domain B")

    progress.clear_jobs_for_domain("Domain A")

    assert list(progress._store) == ["b"]
    progress._store.clear()
