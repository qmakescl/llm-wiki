"""Lint operation — health-check the wiki."""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

from rich.console import Console
from rich.table import Table

from wiki_cli import llm, fs, search_index

console = Console()

_SYSTEM = """You are a meticulous wiki editor performing a health check.
Identify real issues only — don't invent problems.
Be specific: cite page names and the exact claim that contradicts another."""


def run_lint(wiki_root: Path, model: str | None, auto_fix: bool) -> None:
    pages = fs.list_pages(wiki_root)
    issues: list[dict] = []

    console.print(f"\n[bold]Linting {len(pages)} wiki pages...[/bold]\n")

    # ── Check 1: Orphan pages (no inbound wikilinks) ──────────────────────
    issues += _check_orphans(pages, wiki_root)

    index_payload, _stats = search_index.refresh_index(fs.wiki_dir(wiki_root))
    issues += _check_broken_wikilinks(index_payload)
    issues += _check_duplicate_titles(index_payload)
    issues += _check_missing_frontmatter(index_payload)
    issues += _check_invalid_source_refs(index_payload, wiki_root)

    # ── Check 2: TODO markers ─────────────────────────────────────────────
    issues += _check_todos(pages, wiki_root)

    # ── Check 3: Stale pages (updated > 90 days ago, sources added since) ─
    issues += _check_stale(pages, wiki_root)

    # ── Check 4: LLM-assisted contradiction & gap detection ───────────────
    llm_issues = _check_with_llm(pages, wiki_root, model)
    issues += llm_issues

    # ── Report ────────────────────────────────────────────────────────────
    if not issues:
        console.print("[green]✓ Wiki looks healthy — no issues found.[/green]")
        return

    table = Table(title="Lint report", show_lines=True)
    table.add_column("Severity", style="bold", width=10)
    table.add_column("Type", width=18)
    table.add_column("Page", width=24)
    table.add_column("Detail")

    for issue in sorted(issues, key=lambda x: x.get("severity", "medium")):
        sev = issue.get("severity", "medium")
        color = {"high": "red", "medium": "yellow", "low": "dim"}.get(sev, "white")
        table.add_row(
            f"[{color}]{sev}[/{color}]",
            issue.get("type", ""),
            issue.get("page", ""),
            issue.get("detail", ""),
        )

    console.print(table)
    console.print(f"\n[bold]{len(issues)} issue(s) found.[/bold]")


def _check_orphans(pages: list[Path], root: Path) -> list[dict]:
    all_links: set[str] = set()
    for page in pages:
        try:
            body = page.read_text(encoding="utf-8")
            for link in re.findall(r"\[\[([^\]]+)\]\]", body):
                all_links.add(link.lower().replace(" ", "-"))
        except OSError:
            pass

    issues = []
    wiki = fs.wiki_dir(root)
    for page in pages:
        rel = page.relative_to(wiki)
        stem_slug = page.stem.lower().replace(" ", "-")
        if stem_slug not in all_links and str(rel) not in all_links:
            # Skip index/log and synthesis (synthesis pages are often standalone)
            if "synthesis" not in str(rel):
                issues.append({
                    "severity": "low",
                    "type": "orphan page",
                    "page": str(rel),
                    "detail": "No other page links here",
                })
    return issues


def _check_broken_wikilinks(index_payload: dict) -> list[dict]:
    issues = []
    for entry in index_payload.get("entries", {}).values():
        for link in entry.get("outgoing_links", []):
            if search_index.resolve_wikilink(link, index_payload) is None:
                issues.append({
                    "severity": "high",
                    "type": "broken wikilink",
                    "page": entry.get("path", ""),
                    "detail": f"Cannot resolve [[{link}]]",
                })
    return issues


def _check_duplicate_titles(index_payload: dict) -> list[dict]:
    seen: dict[str, list[str]] = {}
    for entry in index_payload.get("entries", {}).values():
        candidates = [entry.get("title", ""), *entry.get("aliases", [])]
        for candidate in candidates:
            key = candidate.strip().lower()
            if key:
                seen.setdefault(key, []).append(entry.get("path", ""))
    issues = []
    for title, paths in seen.items():
        unique = sorted(set(paths))
        if len(unique) > 1:
            issues.append({
                "severity": "medium",
                "type": "duplicate title/alias",
                "page": ", ".join(unique[:3]),
                "detail": f"Duplicate title or alias: {title}",
            })
    return issues


def _check_missing_frontmatter(index_payload: dict) -> list[dict]:
    return [
        {
            "severity": "medium",
            "type": "missing frontmatter",
            "page": entry.get("path", ""),
            "detail": "Page does not start with YAML frontmatter",
        }
        for entry in index_payload.get("entries", {}).values()
        if not entry.get("has_frontmatter")
    ]


def _check_invalid_source_refs(index_payload: dict, root: Path) -> list[dict]:
    issues = []
    for entry in index_payload.get("entries", {}).values():
        for source in entry.get("sources", []):
            # URLs and opaque source names are allowed; relative raw paths are checked.
            if "://" in source or "/" not in source:
                continue
            candidate = root.parent / "data" / source
            raw_candidate = root.parent / "data" / "raw" / source.removeprefix("raw/")
            if not candidate.exists() and not raw_candidate.exists():
                issues.append({
                    "severity": "low",
                    "type": "invalid source reference",
                    "page": entry.get("path", ""),
                    "detail": f"Source reference does not exist: {source}",
                })
    return issues


def _check_todos(pages: list[Path], root: Path) -> list[dict]:
    issues = []
    wiki = fs.wiki_dir(root)
    for page in pages:
        try:
            body = page.read_text(encoding="utf-8")
        except OSError:
            continue
        if "<!-- TODO: verify -->" in body or "TODO: verify" in body:
            issues.append({
                "severity": "medium",
                "type": "unverified claim",
                "page": str(page.relative_to(wiki)),
                "detail": "Contains TODO: verify markers",
            })
    return issues


def _check_stale(pages: list[Path], root: Path) -> list[dict]:
    issues = []
    wiki = fs.wiki_dir(root)
    cutoff = date.today() - timedelta(days=90)

    for page in pages:
        try:
            import frontmatter as fm
            post = fm.load(str(page))
            updated = post.metadata.get("updated")
            if updated and str(updated) < str(cutoff):
                issues.append({
                    "severity": "low",
                    "type": "stale page",
                    "page": str(page.relative_to(wiki)),
                    "detail": f"Last updated {updated}",
                })
        except Exception:
            pass
    return issues


def _check_with_llm(pages: list[Path], root: Path, model: str | None) -> list[dict]:
    if len(pages) < 3:
        return []

    wiki = fs.wiki_dir(root)
    # Sample a subset for contradiction checking (cost control)
    sample = pages[:20]
    summaries = []
    for page in sample:
        try:
            body = page.read_text(encoding="utf-8")[:800]
            summaries.append(f"### {page.relative_to(wiki)}\n{body}")
        except OSError:
            pass

    prompt = f"""Review these wiki page excerpts and identify:
1. Direct contradictions between pages (cite both pages and the conflicting claims)
2. Important concepts mentioned but lacking their own page
3. Missing cross-references that should exist

Wiki excerpts:
{"".join(summaries)}

Format your response as a bullet list. Be specific.
If no issues found, say "No issues detected."
"""
    try:
        response = llm.call(prompt, system=_SYSTEM, model=model, max_tokens=1024)
    except Exception as e:
        console.print(f"[yellow]LLM lint check skipped: {e}[/yellow]")
        return []

    if "no issues" in response.lower():
        return []

    issues = []
    for line in response.splitlines():
        line = line.strip("- •").strip()
        if len(line) > 20:
            issues.append({
                "severity": "medium",
                "type": "llm-detected",
                "page": "multiple",
                "detail": line[:200],
            })
    return issues
