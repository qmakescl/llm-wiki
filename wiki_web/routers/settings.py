"""설정 라우터 — 모델, API 키, 검색 티어 저장 (도메인 경로는 /admin에서 관리)."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from contextlib import contextmanager
from html import escape

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from wiki_web.app import templates
from wiki_web import config as cfg
from wiki_cli import llm

router = APIRouter(prefix="/settings")


@router.get("", response_class=HTMLResponse)
async def settings_page(request: Request, saved: bool = False):
    c = cfg.load()
    model_presets, ollama_models = _model_presets_with_ollama(c)
    preset_values = [v for v, _ in model_presets if v != "__custom__"]
    is_custom = c["model"] not in preset_values
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "cfg": c,
            "llm_providers": cfg.LLM_PROVIDERS,
            "model_presets": model_presets,
            "ollama_models": ollama_models,
            "search_tiers": cfg.SEARCH_TIERS,
            "chunk_strategies": cfg.CHUNK_STRATEGIES,
            "is_custom": is_custom,
            "saved": saved,
        },
    )


@router.post("", response_class=HTMLResponse)
async def save_settings(
    llm_provider: str = Form("ollama"),
    model: str = Form(""),
    model_custom: str = Form(""),
    search_tier: str = Form("grep"),
    ollama_base_url: str = Form("http://localhost:11434"),
    openai_api_key: str = Form(""),
    anthropic_api_key: str = Form(""),
    google_api_key: str = Form(""),
    openrouter_api_key: str = Form(""),
    chunk_strategy: str = Form("section"),
    chunk_size: int = Form(500),
    chunk_overlap: int = Form(100),
    obsidian_sync: str = Form(""),
):
    cfg.save_runtime_settings(
        llm_provider=llm_provider,
        model=model,
        model_custom=model_custom,
        search_tier=search_tier,
        ollama_base_url=ollama_base_url,
        openai_api_key=openai_api_key,
        anthropic_api_key=anthropic_api_key,
        google_api_key=google_api_key,
        openrouter_api_key=openrouter_api_key,
        chunk_strategy=chunk_strategy,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        obsidian_sync=(obsidian_sync == "on"),
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
async def test_model_saved():
    c = cfg.load()
    cfg.apply_env(c)
    return await _test_model(c.get("model") or None, c)


@router.post("/test-model", response_class=HTMLResponse)
async def test_model_form(
    llm_provider: str = Form("ollama"),
    model: str = Form(""),
    model_custom: str = Form(""),
    ollama_base_url: str = Form("http://localhost:11434"),
    openai_api_key: str = Form(""),
    anthropic_api_key: str = Form(""),
    google_api_key: str = Form(""),
    openrouter_api_key: str = Form(""),
):
    model_id = cfg.normalize_model(llm_provider, model, model_custom)
    test_cfg = cfg.load()
    test_cfg.update({
        "llm_provider": llm_provider,
        "model": model_id,
        "ollama_base_url": ollama_base_url,
        "openai_api_key": openai_api_key,
        "anthropic_api_key": anthropic_api_key,
        "google_api_key": google_api_key,
        "openrouter_api_key": openrouter_api_key,
    })
    return await _test_model(model_id or None, test_cfg)


def _model_presets_with_ollama(c: dict) -> tuple[list[tuple[str, str]], list[str]]:
    ollama_models = llm.ollama_tags(c.get("ollama_base_url"), timeout=1)
    presets = [(value, label) for value, label in cfg.MODEL_PRESETS if value != "__custom__"]
    known = {value for value, _ in presets}
    for tag in ollama_models:
        value = f"ollama/{tag}"
        if value not in known:
            presets.insert(1, (value, f"Ollama 로컬 — {tag}"))
            known.add(value)
    presets.append(("__custom__", "직접 입력..."))
    return presets, ollama_models


async def _test_model(model_id: str | None, test_cfg: dict) -> HTMLResponse:
    try:
        with _temporary_llm_env(test_cfg):
            result = await asyncio.to_thread(
                llm.call,
                "Reply with OK only.",
                model=model_id,
                max_tokens=10,
                temperature=0,
            )
        model_label = escape(llm.resolve_model(model_id))
        return HTMLResponse(
            f'<span class="test-ok">✓ 연결 성공: {model_label} → {escape(result[:50])}</span>'
        )
    except Exception as e:
        return HTMLResponse(f'<span class="test-error">✗ 오류: {escape(str(e)[:240])}</span>')


@contextmanager
def _temporary_llm_env(test_cfg: dict):
    keys = [
        "WIKI_MODEL",
        "WIKI_LLM_PROVIDER",
        "WIKI_OLLAMA_BASE_URL",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "OPENROUTER_API_KEY",
    ]
    previous = {key: os.environ.get(key) for key in keys}
    try:
        cfg.apply_env(test_cfg)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
