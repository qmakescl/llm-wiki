"""위키 건강 검사 라우터."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from wiki_web.app import templates
from wiki_web import config as cfg
from wiki_cli.ops.lint import run_lint

router = APIRouter(prefix="/lint")


@router.get("", response_class=HTMLResponse)
async def lint_page(request: Request):
    return templates.TemplateResponse(request, "lint.html", {"issues": None})


@router.post("/run", response_class=HTMLResponse)
async def run_lint_check(request: Request):
    """건강 검사 실행 — 결과 테이블 반환."""
    root = cfg.get_wiki_root()
    settings = cfg.load()
    model = settings.get("model") or None

    issues: list[dict] = []
    error: str = ""

    try:
        # run_lint는 내부적으로 rich 테이블을 출력하므로
        # 직접 검사 함수들을 호출해 issues 목록만 수집
        issues = await asyncio.to_thread(_collect_issues, root, model)
    except Exception as e:
        error = str(e)

    return templates.TemplateResponse(
        request,
        "partials/lint_result.html",
        {"issues": issues, "error": error},
    )


def _collect_issues(root, model) -> list[dict]:
    """run_lint의 검사 결과를 dict 목록으로 반환 (rich 출력 없이)."""
    from wiki_cli import fs
    from wiki_cli.ops.lint import (
        _check_orphans,
        _check_todos,
        _check_stale,
        _check_with_llm,
    )
    pages = fs.list_pages(root)
    issues = []
    issues += _check_orphans(pages, root)
    issues += _check_todos(pages, root)
    issues += _check_stale(pages, root)
    issues += _check_with_llm(pages, root, model)
    return sorted(issues, key=lambda x: {"high": 0, "medium": 1, "low": 2}.get(x.get("severity", "medium"), 1))
