"""lint._check_orphans — 공백 포함 페이지명이 정상적으로 연결로 인식되는지."""

from __future__ import annotations

from wiki_cli import fs
from wiki_cli.ops import lint


def _write(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_orphan_detects_page_with_no_backlinks(wiki_root):
    page_a = wiki_root / "concepts" / "Self Attention.md"
    page_b = wiki_root / "concepts" / "Transformer.md"
    _write(page_a, "# Self Attention\n\nIsolated page.")
    _write(page_b, "# Transformer\n\nBasic.")

    pages = fs.list_pages(wiki_root)
    issues = lint._check_orphans(pages, wiki_root)
    orphans = {i["page"] for i in issues}
    assert "concepts/Self Attention.md" in orphans
    assert "concepts/Transformer.md" in orphans


def test_orphan_skips_page_with_wikilink_using_spaces(wiki_root):
    """[[Self Attention]] 같이 공백 포함 링크도 slug 매칭으로 연결을 인식해야 한다."""
    page_a = wiki_root / "concepts" / "Self Attention.md"
    page_b = wiki_root / "concepts" / "Transformer.md"
    _write(page_a, "# Self Attention\n\nReferenced from Transformer.")
    _write(page_b, "# Transformer\n\nUses [[Self Attention]] everywhere.")

    pages = fs.list_pages(wiki_root)
    issues = lint._check_orphans(pages, wiki_root)
    orphans = {i["page"] for i in issues}
    # Self Attention는 Transformer가 링크하므로 orphan이 아니어야 함
    assert "concepts/Self Attention.md" not in orphans


def test_orphan_skips_synthesis_pages(wiki_root):
    synth = wiki_root / "synthesis" / "some-question.md"
    _write(synth, "# question\n\nstandalone synthesis page")

    pages = fs.list_pages(wiki_root)
    issues = lint._check_orphans(pages, wiki_root)
    orphans = {i["page"] for i in issues}
    # synthesis는 orphan 체크에서 제외된다
    assert all("synthesis" not in p for p in orphans)
