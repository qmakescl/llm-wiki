"""Filesystem helpers — all wiki I/O goes through here."""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

import frontmatter as fm


# ── Slug / ID helpers ────────────────────────────────────────────────────────

def file_slug(stem: str) -> str:
    """raw 파일명 stem을 CSS id·URL 경로에 안전한 slug로 변환.

    기존 호환성을 위해 underscore(`_`)는 유지하고, 공백은 `-`로 치환한다.
    CSS selector에서 분리자로 해석되는 쉼표·점·괄호 등은 모두 `-`로 바꾼다
    (예: "Zamanian, PhD" → "zamanian-phd"). 결과가 빈 문자열이면 "doc" 폴백.
    """
    lowered = stem.lower().replace(" ", "-")
    cleaned = re.sub(r"[^a-z0-9가-힣_\-]+", "-", lowered)
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-_")
    return cleaned or "doc"


# ── Upload safety ─────────────────────────────────────────────────────────────

ALLOWED_UPLOAD_EXTS = {".pdf", ".md", ".txt"}


class UnsafeUploadError(ValueError):
    """업로드가 허용 규칙(파일명/확장자)을 위반할 때."""


def sanitize_upload_name(raw_name: str) -> str:
    """사용자 제공 파일명에서 basename만 추출하고 경로 탈출 문자를 제거.

    - 경로 구분자(`/`, `\\`)가 섞여 있어도 basename만 사용한다.
    - `..` 등 상대경로 요소가 basename에 남으면 거부한다.
    - 빈 문자열이나 dotfile도 거부한다.
    """
    if not raw_name:
        raise UnsafeUploadError("빈 파일명은 허용되지 않습니다.")
    name = Path(raw_name.replace("\\", "/")).name
    if not name or name in (".", "..") or name.startswith("."):
        raise UnsafeUploadError(f"허용되지 않는 파일명: {raw_name!r}")
    if "/" in name or "\x00" in name:
        raise UnsafeUploadError(f"허용되지 않는 파일명: {raw_name!r}")
    return name


def resolve_upload_path(raw: Path, raw_name: str) -> Path:
    """raw/ 디렉터리 안의 최종 저장 경로를 결정한다.

    - 파일명을 basename 으로 정규화하고 허용 확장자(`.pdf`/`.md`/`.txt`)만 허용한다.
    - 동일 이름이 이미 존재하면 `<stem>__<YYYYMMDD-HHMMSS>.<ext>` suffix로 회피한다.
    - resolve된 경로가 raw/ 밖이면 거부한다(경로 traversal 방어).
    """
    name = sanitize_upload_name(raw_name)
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_UPLOAD_EXTS:
        allowed = ", ".join(sorted(ALLOWED_UPLOAD_EXTS))
        raise UnsafeUploadError(f"허용되지 않는 확장자: {ext or '(없음)'} — 허용: {allowed}")

    raw_resolved = raw.resolve()
    dest = (raw / name)
    if dest.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = raw / f"{Path(name).stem}__{stamp}{ext}"

    final = dest.resolve()
    # raw/ 밖으로 이탈하는 경로는 무조건 차단
    if raw_resolved not in final.parents and final != raw_resolved:
        raise UnsafeUploadError(f"raw/ 외부로 이탈하는 경로: {raw_name!r}")
    return dest


# ── Directory helpers ─────────────────────────────────────────────────────────

def wiki_dir(root: Path) -> Path:
    """wiki_root 자체가 wiki 디렉터리. 호환성을 위해 root를 그대로 반환."""
    return root


def raw_dir(data_root: Path) -> Path:
    """원본 파일 디렉터리. data_root/raw/"""
    return data_root / "raw"


def index_path(root: Path) -> Path:
    return wiki_dir(root) / "index.md"


def log_path(root: Path) -> Path:
    return wiki_dir(root) / "log.md"


# ── Page read/write ──────────────────────────────────────────────────────────

def read_page(path: Path) -> tuple[dict, str]:
    """Return (frontmatter_dict, body_text)."""
    if not path.exists():
        return {}, ""
    post = fm.load(str(path))
    return dict(post.metadata), post.content


def write_page(path: Path, metadata: dict, body: str) -> None:
    """Write a wiki page with YAML frontmatter."""
    path.parent.mkdir(parents=True, exist_ok=True)
    today = str(date.today())
    metadata.setdefault("created", today)
    metadata["updated"] = today
    # title이 있으면 Obsidian 위키링크 해결을 위해 aliases 자동 추가
    if metadata.get("title") and not metadata.get("aliases"):
        metadata["aliases"] = [metadata["title"]]

    post = fm.Post(body, **metadata)
    path.write_text(fm.dumps(post), encoding="utf-8")


def list_pages(root: Path) -> list[Path]:
    """All .md files under wiki/ except index and log."""
    w = wiki_dir(root)
    if not w.exists():
        return []
    return [
        p for p in w.rglob("*.md")
        if p.name not in ("index.md", "log.md")
    ]


# ── Index maintenance ────────────────────────────────────────────────────────

def update_index_entry(root: Path, page_path: Path, title: str, description: str) -> None:
    """Upsert a single entry in index.md."""
    idx = index_path(root)
    content = idx.read_text(encoding="utf-8") if idx.exists() else _empty_index()

    rel = page_path.relative_to(wiki_dir(root))
    entry = f"| [{title}]({rel}) | {description} |"

    # Determine section from subdirectory
    section = _section_for(page_path, root)
    content = _upsert_index_row(content, section, str(rel), entry)

    # Update header counts
    content = _refresh_index_header(content, root)
    idx.write_text(content, encoding="utf-8")


def _section_for(page_path: Path, root: Path) -> str:
    parts = page_path.relative_to(wiki_dir(root)).parts
    mapping = {
        "sources": "Sources",
        "entities": "Entities",
        "concepts": "Concepts",
        "synthesis": "Synthesis",
    }
    return mapping.get(parts[0], "Other") if parts else "Other"


def _empty_index() -> str:
    today = str(date.today())
    return f"""# Wiki index
Last updated: {today} | Pages: 0 | Sources: 0

## Sources
| Page | Description |
|------|-------------|

## Entities
| Page | Description |
|------|-------------|

## Concepts
| Page | Description |
|------|-------------|

## Synthesis
| Page | Description |
|------|-------------|
"""


def _upsert_index_row(content: str, section: str, rel: str, entry: str) -> str:
    lines = content.splitlines()
    in_section = False
    saw_section = False
    replaced = False
    result = []
    for line in lines:
        if line.startswith(f"## {section}"):
            in_section = True
            saw_section = True
        elif line.startswith("## ") and in_section:
            in_section = False
        if in_section and rel in line and line.startswith("|"):
            result.append(entry)
            replaced = True
            continue
        result.append(line)

    if not replaced and saw_section:
        for i, line in enumerate(result):
            if line.startswith(f"## {section}"):
                j = i + 1
                while j < len(result) and (result[j].startswith("|") or result[j].strip() == ""):
                    j += 1
                result.insert(j, entry)
                break
    return "\n".join(result) + "\n"


def _refresh_index_header(content: str, root: Path) -> str:
    pages = list_pages(root)
    sources = sum(1 for p in pages if "sources" in str(p))
    today = str(date.today())
    header = f"Last updated: {today} | Pages: {len(pages)} | Sources: {sources}"
    return re.sub(r"Last updated:.*", header, content, count=1)


# ── Log append ───────────────────────────────────────────────────────────────

def append_log(root: Path, entry: str) -> None:
    """Append an entry to log.md (never overwrites)."""
    log = log_path(root)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as f:
        f.write("\n" + entry.rstrip() + "\n")
