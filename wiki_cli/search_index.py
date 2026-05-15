"""Incremental markdown search index."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import frontmatter as fm


INDEX_PATH = ".search/index.json"
INDEX_VERSION = 1


@dataclass
class IndexStats:
    total_files: int
    updated_files: int
    removed_files: int


def index_path(wiki_dir: Path) -> Path:
    return wiki_dir / INDEX_PATH


def refresh_index(wiki_dir: Path) -> tuple[dict[str, Any], IndexStats]:
    """Refresh changed markdown files and return the index payload."""
    wiki_dir = wiki_dir.resolve()
    existing = _load_index(wiki_dir)
    old_entries: dict[str, dict] = existing.get("entries", {})
    new_entries: dict[str, dict] = {}
    updated = 0

    md_files = [
        p for p in wiki_dir.rglob("*.md")
        if ".search" not in p.parts and p.name not in {"index.md", "log.md", "AGENTS.md"}
    ]
    for path in md_files:
        rel = str(path.relative_to(wiki_dir))
        stat = path.stat()
        previous = old_entries.get(rel)
        if previous and previous.get("mtime_ns") == stat.st_mtime_ns and previous.get("size") == stat.st_size:
            new_entries[rel] = previous
            continue
        new_entries[rel] = parse_markdown_file(path, wiki_dir)
        updated += 1

    removed = len(set(old_entries) - set(new_entries))
    payload = {
        "version": INDEX_VERSION,
        "entries": new_entries,
    }
    _save_index(wiki_dir, payload)
    return payload, IndexStats(total_files=len(md_files), updated_files=updated, removed_files=removed)


def parse_markdown_file(path: Path, wiki_dir: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    stat = path.stat()
    metadata: dict[str, Any] = {}
    body = text
    try:
        post = fm.loads(text)
        metadata = dict(post.metadata)
        body = post.content
    except Exception:
        pass
    title = str(metadata.get("title") or _first_heading(body) or path.stem)
    aliases = metadata.get("aliases") or []
    if isinstance(aliases, str):
        aliases = [aliases]
    sources = metadata.get("sources") or []
    if isinstance(sources, str):
        sources = [sources]
    chunks = _chunk_by_heading(body)
    return {
        "path": str(path.relative_to(wiki_dir)),
        "mtime_ns": stat.st_mtime_ns,
        "size": stat.st_size,
        "sha256": hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest(),
        "title": title,
        "aliases": [str(a) for a in aliases],
        "type": str(metadata.get("type") or ""),
        "sources": [str(s) for s in sources],
        "has_frontmatter": text.lstrip().startswith("---"),
        "headings": [c["heading"] for c in chunks],
        "outgoing_links": sorted(set(re.findall(r"\[\[([^\]]+)\]\]", body))),
        "plain_text_preview": _strip_markup(body)[:500],
        "chunks": chunks,
    }


def resolve_wikilink(link: str, payload: dict[str, Any]) -> str | None:
    wanted = _norm_link(link)
    for rel, entry in payload.get("entries", {}).items():
        candidates = [entry.get("title", ""), Path(rel).stem, *entry.get("aliases", [])]
        if any(_norm_link(str(c)) == wanted for c in candidates):
            return rel
    return None


def candidate_entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return list(payload.get("entries", {}).values())


def _load_index(wiki_dir: Path) -> dict[str, Any]:
    path = index_path(wiki_dir)
    if not path.exists():
        return {"version": INDEX_VERSION, "entries": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"version": INDEX_VERSION, "entries": {}}
    if data.get("version") != INDEX_VERSION:
        return {"version": INDEX_VERSION, "entries": {}}
    return data


def _save_index(wiki_dir: Path, payload: dict[str, Any]) -> None:
    path = index_path(wiki_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _first_heading(body: str) -> str:
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _chunk_by_heading(body: str) -> list[dict[str, str]]:
    chunks: list[dict[str, str]] = []
    current_heading = "Introduction"
    current: list[str] = []
    for line in body.splitlines():
        if line.startswith("#"):
            if current:
                text = "\n".join(current).strip()
                chunks.append({"heading": current_heading, "text": text[:2000]})
                current = []
            current_heading = line.lstrip("#").strip() or current_heading
        else:
            current.append(line)
    if current:
        text = "\n".join(current).strip()
        chunks.append({"heading": current_heading, "text": text[:2000]})
    return chunks or [{"heading": current_heading, "text": body[:2000]}]


def _strip_markup(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return re.sub(r"[*_`>#|\-]+", " ", text)


def _norm_link(value: str) -> str:
    value = value.split("|", 1)[0].split("#", 1)[0].strip()
    if value.endswith(".md"):
        value = value[:-3]
    return value.lower().replace(" ", "-")
