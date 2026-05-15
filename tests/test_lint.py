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


def test_broken_wikilink_detected(wiki_root):
    page = wiki_root / "concepts" / "Transformer.md"
    fs.write_page(page, {"title": "Transformer", "type": "concept"}, "# Transformer\n\nSee [[Missing Page]].")
    payload, _ = lint.search_index.refresh_index(wiki_root)

    issues = lint._check_broken_wikilinks(payload)

    assert issues
    assert issues[0]["type"] == "broken wikilink"


def test_duplicate_title_detected(wiki_root):
    fs.write_page(wiki_root / "concepts" / "A.md", {"title": "Same", "type": "concept"}, "# Same")
    fs.write_page(wiki_root / "entities" / "B.md", {"title": "Other", "aliases": ["Same"], "type": "entity"}, "# Other")
    payload, _ = lint.search_index.refresh_index(wiki_root)

    issues = lint._check_duplicate_titles(payload)

    assert any(i["type"] == "duplicate title/alias" for i in issues)


def test_missing_frontmatter_detected(wiki_root):
    _write(wiki_root / "concepts" / "Plain.md", "# Plain\n\nNo frontmatter.")
    payload, _ = lint.search_index.refresh_index(wiki_root)

    issues = lint._check_missing_frontmatter(payload)

    assert any(i["page"] == "concepts/Plain.md" for i in issues)
