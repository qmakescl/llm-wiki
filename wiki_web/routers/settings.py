"""설정 라우터 — 모델, API 키, 검색 티어 저장 (도메인 경로는 /admin에서 관리)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from wiki_web.app import templates
from wiki_web import config as cfg

router = APIRouter(prefix="/settings")


@router.get("", response_class=HTMLResponse)
async def settings_page(request: Request, saved: bool = False):
    c = cfg.load()
    preset_values = [v for v, _ in cfg.MODEL_PRESETS if v != "__custom__"]
    is_custom = c["model"] not in preset_values
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "cfg": c,
            "model_presets": cfg.MODEL_PRESETS,
            "search_tiers": cfg.SEARCH_TIERS,
            "chunk_strategies": cfg.CHUNK_STRATEGIES,
            "is_custom": is_custom,
            "saved": saved,
        },
    )


@router.post("", response_class=HTMLResponse)
async def save_settings(
    model: str = Form(""),
    model_custom: str = Form(""),
    search_tier: str = Form("grep"),
    ollama_base_url: str = Form("http://localhost:11434"),
    openai_api_key: str = Form(""),
    anthropic_api_key: str = Form(""),
    chunk_strategy: str = Form("section"),
    chunk_size: int = Form(500),
    chunk_overlap: int = Form(100),
):
    cfg.save_runtime_settings(
        model=model,
        model_custom=model_custom,
        search_tier=search_tier,
        ollama_base_url=ollama_base_url,
        openai_api_key=openai_api_key,
        anthropic_api_key=anthropic_api_key,
        chunk_strategy=chunk_strategy,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    return RedirectResponse("/settings?saved=1", status_code=303)


@router.get("/browse")
async def browse_dir(path: str = "/"):
    from fastapi.responses import JSONResponse
    p = Path(path).expanduser().resolve()
    if not p.is_dir():
        p = p.parent
    try:
        dirs = sorted(
            [d for d in p.iterdir() if d.is_dir() and not d.name.startswith(".")],
            key=lambda d: d.name.lower(),
        )
    except PermissionError:
        dirs = []
    return JSONResponse({
        "path": str(p),
        "parent": str(p.parent) if p != p.parent else None,
        "dirs": [{"name": d.name, "path": str(d)} for d in dirs],
    })


@router.get("/test-model", response_class=HTMLResponse)
async def test_model():
    from wiki_cli import llm
    try:
        result = await asyncio.to_thread(llm.call, "Say 'OK' in one word.", max_tokens=10)
        return HTMLResponse(f'<span class="test-ok">✓ 모델 응답: {result[:50]}</span>')
    except Exception as e:
        return HTMLResponse(f'<span class="test-error">✗ 오류: {str(e)[:100]}</span>')
