"""synthesis/ 문서 목록 및 미리보기 라우터."""

from __future__ import annotations

import markdown as md_lib
import re
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from wiki_web.app import templates
from wiki_web import config as cfg
from wiki_web.render import render_answer
from wiki_cli import fs

router = APIRouter(prefix="/synthesis")


def _fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 ** 2:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 ** 2:.1f} MB"


def _parse_frontmatter(text: str) -> dict:
    """YAML frontmatter에서 title, created 파싱."""
    meta = {}
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            block = text[3:end]
            for line in block.splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    meta[k.strip()] = v.strip().strip('"')
    return meta


def _list_synthesis(root: Path) -> list[dict]:
    """synthesis/ 하위 .md 파일 목록을 최신순으로 반환."""
    synth_dir = fs.wiki_dir(root) / "synthesis"
    if not synth_dir.exists():
        return []

    files = []
    for f in sorted(synth_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
        text = f.read_text(encoding="utf-8")
        meta = _parse_frontmatter(text)
        mtime = datetime.fromtimestamp(f.stat().st_mtime)
        files.append({
            "slug": f.stem,
            "name": f.name,
            "title": meta.get("title") or f.stem.replace("-", " "),
            "created": meta.get("created") or mtime.strftime("%Y-%m-%d"),
            "mtime": mtime.strftime("%Y-%m-%d %H:%M"),
            "size": _fmt_size(f.stat().st_size),
        })
    return files


@router.get("", response_class=HTMLResponse)
async def synthesis_page(request: Request):
    root = cfg.get_wiki_root()
    files = _list_synthesis(root)
    return templates.TemplateResponse(
        request,
        "synthesis.html",
        {"files": files},
    )


@router.get("/{slug}", response_class=HTMLResponse)
async def synthesis_preview(request: Request, slug: str):
    """HTMX 부분 요청: 문서 미리보기 HTML 반환."""
    root = cfg.get_wiki_root()
    path = fs.wiki_dir(root) / "synthesis" / f"{slug}.md"

    if not path.exists():
        return HTMLResponse(
            '<p class="error">문서를 찾을 수 없습니다.</p>',
            status_code=404,
        )

    raw = path.read_text(encoding="utf-8")
    meta = _parse_frontmatter(raw)

    # frontmatter 블록 제거 후 본문만 추출
    body = raw
    if raw.startswith("---"):
        end = raw.find("---", 3)
        if end != -1:
            body = raw[end + 3:].lstrip()

    answer_html = render_answer(body)

    return templates.TemplateResponse(
        request,
        "partials/synthesis_preview.html",
        {
            "slug": slug,
            "title": meta.get("title") or slug.replace("-", " "),
            "created": meta.get("created", ""),
            "answer_html": answer_html,
        },
    )


@router.delete("/{slug}", response_class=HTMLResponse)
async def synthesis_delete(slug: str):
    """문서 삭제."""
    root = cfg.get_wiki_root()
    path = fs.wiki_dir(root) / "synthesis" / f"{slug}.md"

    if path.exists():
        path.unlink()

    return HTMLResponse("")  # 삭제 후 빈 HTML → 행이 사라짐
