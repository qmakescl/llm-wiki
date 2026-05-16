"""Source registry helpers.

The registry tracks raw source files by content hash instead of relying only on
filenames or URL slugs. It lives under the data root so Obsidian-facing wiki
content stays clean.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REGISTRY_NAME = "sources.jsonl"


def registry_path(data_root: Path) -> Path:
    return data_root / REGISTRY_NAME


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_records(data_root: Path) -> list[dict[str, Any]]:
    path = registry_path(data_root)
    if not path.exists():
        return []

    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def write_records(data_root: Path, records: list[dict[str, Any]]) -> None:
    path = registry_path(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in records)
    path.write_text(text + ("\n" if text else ""), encoding="utf-8")


def relative_source_path(data_root: Path, source: Path) -> str:
    try:
        return str(source.resolve().relative_to(data_root.resolve()))
    except ValueError:
        return str(source)


def register_uploaded_source(data_root: Path, source: Path) -> dict[str, Any]:
    """Register or refresh a raw source row after upload."""
    source = source.resolve()
    rel = relative_source_path(data_root, source)
    digest = sha256_file(source)
    size = source.stat().st_size
    records = load_records(data_root)

    for record in records:
        if record.get("relative_path") == rel:
            record.update({
                "filename": source.name,
                "sha256": digest,
                "size": size,
            })
            write_records(data_root, records)
            return record

    record = {
        "source_id": str(uuid.uuid4())[:12],
        "relative_path": rel,
        "filename": source.name,
        "sha256": digest,
        "size": size,
        "uploaded_at": utc_now(),
        "ingested_at": "",
        "summary_page": "",
        "model": "",
    }
    records.append(record)
    write_records(data_root, records)
    return record


def find_ingested_duplicate(
    data_root: Path,
    source: Path,
    wiki_root: Path | None = None,
) -> dict[str, Any] | None:
    """Return an already-ingested record with the same content hash, if any."""
    digest = sha256_file(source)
    rel = relative_source_path(data_root, source.resolve())
    for record in load_records(data_root):
        if record.get("sha256") != digest:
            continue
        if not record_is_complete(record, wiki_root):
            continue
        if record.get("relative_path") == rel:
            continue
        return record
    return None


def find_record_for_source(data_root: Path, source: Path) -> dict[str, Any] | None:
    """Return the registry row for a source path, if present."""
    rel = relative_source_path(data_root, source.resolve())
    for record in load_records(data_root):
        if record.get("relative_path") == rel:
            return record
    return None


def record_is_complete(record: dict[str, Any], wiki_root: Path | None = None) -> bool:
    """A source is complete only after mark_ingested and an existing summary page."""
    if not record.get("ingested_at") or not record.get("summary_page"):
        return False
    if wiki_root is None:
        return True
    return (wiki_root / str(record["summary_page"])).exists()


def source_is_ingested(data_root: Path, wiki_root: Path, source: Path) -> bool:
    """Return True when the exact source path has a complete ingest record."""
    record = find_record_for_source(data_root, source)
    return bool(record and record_is_complete(record, wiki_root))


def mark_ingested(
    data_root: Path,
    source: Path,
    *,
    summary_page: str,
    model: str | None,
) -> dict[str, Any]:
    """Mark a source as ingested, creating the row first if needed."""
    source = source.resolve()
    rel = relative_source_path(data_root, source)
    digest = sha256_file(source)
    records = load_records(data_root)

    for record in records:
        if record.get("relative_path") == rel:
            record.update({
                "filename": source.name,
                "sha256": digest,
                "size": source.stat().st_size,
                "ingested_at": utc_now(),
                "summary_page": summary_page,
                "model": model or "",
            })
            write_records(data_root, records)
            return record

    record = register_uploaded_source(data_root, source)
    records = load_records(data_root)
    for existing in records:
        if existing.get("source_id") == record["source_id"]:
            existing.update({
                "ingested_at": utc_now(),
                "summary_page": summary_page,
                "model": model or "",
            })
            write_records(data_root, records)
            return existing
    return record
