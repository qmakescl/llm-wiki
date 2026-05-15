"""Draft review helpers for staged wiki changes."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class Draft:
    job_id: str
    path: Path
    manifest: dict


def drafts_root(wiki_root: Path) -> Path:
    return wiki_root / ".drafts"


def create_draft(wiki_root: Path, job_id: str, files: dict[str, str]) -> Draft:
    """Create a draft directory with relative wiki paths as keys."""
    root = drafts_root(wiki_root) / job_id
    root.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    manifest = {
        "job_id": job_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "files": sorted(files),
        "status": "draft",
    }
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return Draft(job_id=job_id, path=root, manifest=manifest)


def load_draft(wiki_root: Path, job_id: str) -> Draft | None:
    root = drafts_root(wiki_root) / job_id
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return Draft(job_id=job_id, path=root, manifest=manifest)


def approve_draft(wiki_root: Path, job_id: str) -> list[Path]:
    draft = load_draft(wiki_root, job_id)
    if draft is None:
        raise FileNotFoundError(f"draft not found: {job_id}")
    written: list[Path] = []
    for rel in draft.manifest.get("files", []):
        source = draft.path / rel
        target = wiki_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        written.append(target)
    draft.manifest["status"] = "approved"
    (draft.path / "manifest.json").write_text(json.dumps(draft.manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return written


def delete_draft(wiki_root: Path, job_id: str) -> None:
    root = drafts_root(wiki_root) / job_id
    if root.exists():
        shutil.rmtree(root)
