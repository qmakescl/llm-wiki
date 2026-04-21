"""관리자 라우터 — 도메인 CRUD, 위키 초기화, 시스템 정보."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from wiki_web.app import templates
from wiki_web import config as cfg
from wiki_cli import fs

router = APIRouter(prefix="/admin")


def _domain_stats(domain: dict, workspace_root: Path) -> dict:
    folder = domain.get("folder", domain.get("id"))
    wiki_root = workspace_root / "wiki" / folder
    initialized = cfg.wiki_is_initialized(wiki_root)
    if not initialized:
        return {"initialized": False, "total": 0, "sources": 0}
    pages = fs.list_pages(wiki_root)
    return {
        "initialized": True,
        "total": len(pages),
        "sources": sum(1 for p in pages if "sources" in str(p)),
        "entities": sum(1 for p in pages if "entities" in str(p)),
        "concepts": sum(1 for p in pages if "concepts" in str(p)),
    }


@router.get("", response_class=HTMLResponse)
async def admin_page(request: Request):
    c = cfg.load()
    domains = cfg.get_all_domains(c)
    active_id = c.get("active_domain_id", "")
    workspace_root = Path(c.get("workspace_root") or str(Path.home() / "llm-wikis"))
    domain_info = []
    for d in domains:
        stats = _domain_stats(d, workspace_root)
        folder = d.get("folder", d.get("id"))
        domain_info.append({
            **d,
            **stats,
            "is_active": d["id"] == active_id,
            "wiki_root": str(workspace_root / "wiki" / folder),
        })

    preset_values = [v for v, _ in cfg.MODEL_PRESETS if v != "__custom__"]
    is_custom = c.get("model", "") not in preset_values

    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "workspace_root": str(workspace_root),
            "is_workspace_set": bool(c.get("workspace_root")),
            "domains": domain_info,
            "active_id": active_id,
            "config_path": str(cfg.CONFIG_FILE),
            "cfg": c,
            "model_presets": cfg.MODEL_PRESETS,
            "search_tiers": cfg.SEARCH_TIERS,
            "is_custom": is_custom,
            "saved": request.query_params.get("saved") == "1",
        },
    )


@router.post("/domains/add", response_class=HTMLResponse)
async def add_domain(
    name: str = Form(...),
):
    import re
    # 한글, 영문, 숫자 이외의 문자를 언더스코어(_)로 치환하고 연속된 언더스코어 제거, 소문자화
    slug = re.sub(r'[^a-zA-Z0-9가-힣]+', '_', name).strip('_').lower()
    if not slug:
        slug = "domain"
    
    # 중복 방지를 위한 간단한 처리
    c = cfg.load()
    existing_folders = {d.get("folder") for d in c.get("domains", [])}
    folder = slug
    counter = 1
    while folder in existing_folders:
        folder = f"{slug}_{counter}"
        counter += 1

    cfg.add_domain(name, folder)
    return RedirectResponse("/admin", status_code=303)


@router.post("/domains/{domain_id}/activate")
async def activate_domain(domain_id: str):
    cfg.switch_domain(domain_id)
    return RedirectResponse("/admin", status_code=303)


@router.post("/domains/{domain_id}/delete")
async def delete_domain(domain_id: str):
    cfg.remove_domain(domain_id)
    return RedirectResponse("/admin", status_code=303)


@router.post("/domains/{domain_id}/rename")
async def rename_domain(domain_id: str, name: str = Form(...)):
    import re
    import shutil
    c = cfg.load()
    domain = next((d for d in c.get("domains", []) if d["id"] == domain_id), None)
    if not domain:
        return RedirectResponse("/admin", status_code=303)
    
    slug = re.sub(r'[^a-zA-Z0-9가-힣]+', '_', name).strip('_').lower()
    if not slug:
        slug = "domain"
    
    existing_folders = {d.get("folder") for d in c.get("domains", []) if d["id"] != domain_id}
    new_folder = slug
    counter = 1
    while new_folder in existing_folders:
        new_folder = f"{slug}_{counter}"
        counter += 1

    old_folder = domain.get("folder")
    if old_folder and old_folder != new_folder:
        ws_root = Path(c.get("workspace_root") or str(Path.home() / "llm-wikis"))
        for subdir in ("wiki", "data"):
            old_path = ws_root / subdir / old_folder
            new_path = ws_root / subdir / new_folder
            if old_path.exists() and not new_path.exists():
                shutil.move(str(old_path), str(new_path))
        
    cfg.update_domain(domain_id, name=name, folder=new_folder)
    return RedirectResponse("/admin", status_code=303)


@router.post("/domains/{domain_id}/init")
async def init_domain_wiki(
    domain_id: str,
    domain_topic: str = Form("연구"),
    reset: str = Form(""),
):
    """해당 도메인 위키 초기화 (reset=1이면 wiki/raw/ 삭제 후 재생성)."""
    c = cfg.load()
    domain = next((d for d in c.get("domains", []) if d["id"] == domain_id), None)
    if domain is None:
        return HTMLResponse("도메인을 찾을 수 없습니다.", status_code=404)

    ws_root = Path(c.get("workspace_root") or str(Path.home() / "llm-wikis"))
    folder = domain.get("folder", domain.get("id"))
    wiki_root = ws_root / "wiki" / folder
    data_root = ws_root / "data" / folder

    if reset == "1":
        for target in (wiki_root, data_root):
            if target.exists():
                shutil.rmtree(target)

    from wiki_cli.ops.init import run_init
    try:
        await asyncio.to_thread(run_init, wiki_root, data_root, domain_topic)
    except Exception as e:
        return RedirectResponse(f"/admin?error={e}", status_code=303)

    return RedirectResponse("/admin", status_code=303)


@router.post("/workspace/update")
async def update_workspace_root(workspace_root: str = Form(...)):
    cfg.update_workspace_root(workspace_root)
    return RedirectResponse("/admin", status_code=303)



@router.post("/settings", response_class=HTMLResponse)
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
    return RedirectResponse("/admin?saved=1", status_code=303)
