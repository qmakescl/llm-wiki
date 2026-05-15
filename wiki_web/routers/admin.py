"""관리자 라우터 — 도메인 CRUD, 위키 초기화, 시스템 정보."""

from __future__ import annotations

import asyncio
import platform
import subprocess
import shutil
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from wiki_web.app import templates
from wiki_web import config as cfg
from wiki_web import progress as jobs
from wiki_cli import fs
from wiki_cli import llm

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


def _domain_view(domain: dict, workspace_root: Path, active_id: str = "") -> dict:
    stats = _domain_stats(domain, workspace_root)
    folder = domain.get("folder", domain.get("id"))
    return {
        **domain,
        **stats,
        "is_active": domain["id"] == active_id,
        "wiki_root": str(workspace_root / "wiki" / folder),
        "data_root": str(workspace_root / "data" / folder),
    }


def _find_domain(c: dict, domain_id: str) -> dict | None:
    return next(
        (
            d
            for d in c.get("domains", []) + c.get("archived_domains", [])
            if d["id"] == domain_id
        ),
        None,
    )


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


@router.get("", response_class=HTMLResponse)
async def admin_page(request: Request):
    c = cfg.load()
    domains = cfg.get_all_domains(c)
    archived_domains = cfg.get_archived_domains(c)
    active_id = c.get("active_domain_id", "")
    workspace_root = Path(c.get("workspace_root") or str(Path.home() / "llm-wikis"))
    domain_info = [_domain_view(d, workspace_root, active_id) for d in domains]
    archived_domain_info = [_domain_view(d, workspace_root) for d in archived_domains]

    model_presets, ollama_models = _model_presets_with_ollama(c)
    preset_values = [v for v, _ in model_presets if v != "__custom__"]
    is_custom = c.get("model", "") not in preset_values

    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "workspace_root": str(workspace_root),
            "is_workspace_set": bool(c.get("workspace_root")),
            "domains": domain_info,
            "archived_domains": archived_domain_info,
            "active_id": active_id,
            "config_path": str(cfg.CONFIG_FILE),
            "cfg": c,
            "llm_providers": cfg.LLM_PROVIDERS,
            "model_presets": model_presets,
            "ollama_models": ollama_models,
            "search_tiers": cfg.SEARCH_TIERS,
            "is_custom": is_custom,
            "saved": request.query_params.get("saved") == "1",
            "error": request.query_params.get("error", ""),
        },
    )


@router.post("/domains/add", response_class=HTMLResponse)
async def add_domain(
    name: str = Form(...),
    domain_topic: str = Form(...),
):
    import re
    # 한글, 영문, 숫자 이외의 문자를 언더스코어(_)로 치환하고 연속된 언더스코어 제거, 소문자화
    slug = re.sub(r'[^a-zA-Z0-9가-힣]+', '_', name).strip('_').lower()
    if not slug:
        slug = "domain"
    
    # 중복 방지를 위한 간단한 처리
    c = cfg.load()
    existing_folders = {
        d.get("folder")
        for d in c.get("domains", []) + c.get("archived_domains", [])
    }
    folder = slug
    counter = 1
    while folder in existing_folders:
        folder = f"{slug}_{counter}"
        counter += 1

    ws_root = Path(c.get("workspace_root") or str(Path.home() / "llm-wikis"))
    wiki_root = ws_root / "wiki" / folder
    data_root = ws_root / "data" / folder

    from wiki_cli.ops.init import run_init
    new_domain = cfg.add_domain(name, folder)
    try:
        await asyncio.to_thread(run_init, wiki_root, data_root, domain_topic)
        cfg.switch_domain(new_domain["id"])
    except Exception as e:
        cfg.remove_domain(new_domain["id"])
        return RedirectResponse(f"/admin?error={quote(str(e))}", status_code=303)

    return RedirectResponse("/admin", status_code=303)


@router.post("/domains/{domain_id}/activate")
async def activate_domain(domain_id: str):
    cfg.switch_domain(domain_id)
    return RedirectResponse("/admin", status_code=303)


@router.post("/domains/{domain_id}/delete")
async def delete_domain(domain_id: str):
    c = cfg.load()
    domain = _find_domain(c, domain_id)
    if domain is None:
        return RedirectResponse("/admin", status_code=303)

    ws_root = Path(c.get("workspace_root") or str(Path.home() / "llm-wikis"))
    folder = domain.get("folder", domain.get("id"))
    for target in (ws_root / "wiki" / folder, ws_root / "data" / folder):
        if target.exists():
            shutil.rmtree(target)
    jobs.clear_jobs_for_domain(domain.get("name", ""))
    cfg.delete_domain_record(domain_id)
    return RedirectResponse("/admin", status_code=303)


@router.post("/domains/{domain_id}/archive")
async def archive_domain(domain_id: str):
    cfg.archive_domain(domain_id)
    return RedirectResponse("/admin", status_code=303)


@router.post("/domains/{domain_id}/restore")
async def restore_domain(domain_id: str):
    try:
        cfg.restore_domain(domain_id)
    except Exception as e:
        return RedirectResponse(f"/admin?error={quote(str(e))}", status_code=303)
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
    
    existing_folders = {
        d.get("folder")
        for d in c.get("domains", []) + c.get("archived_domains", [])
        if d["id"] != domain_id
    }
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
):
    """Delete and recreate one domain's wiki/data directories."""
    c = cfg.load()
    domain = next((d for d in c.get("domains", []) if d["id"] == domain_id), None)
    if domain is None:
        return HTMLResponse("도메인을 찾을 수 없습니다.", status_code=404)

    ws_root = Path(c.get("workspace_root") or str(Path.home() / "llm-wikis"))
    folder = domain.get("folder", domain.get("id"))
    wiki_root = ws_root / "wiki" / folder
    data_root = ws_root / "data" / folder

    for target in (wiki_root, data_root):
        if target.exists():
            shutil.rmtree(target)
    jobs.clear_jobs_for_domain(domain.get("name", ""))

    from wiki_cli.ops.init import run_init
    try:
        await asyncio.to_thread(run_init, wiki_root, data_root, domain_topic)
    except Exception as e:
        return RedirectResponse(f"/admin?error={quote(str(e))}", status_code=303)

    return RedirectResponse("/admin", status_code=303)


@router.post("/workspace/update")
async def update_workspace_root(workspace_root: str = Form(...)):
    cfg.update_workspace_root(workspace_root)
    return RedirectResponse("/admin", status_code=303)


@router.get("/workspace/pick-directory")
async def pick_workspace_directory():
    """Open the host OS folder picker and return an absolute path."""
    try:
        path = await asyncio.to_thread(_pick_directory_native)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=200)
    if not path:
        return JSONResponse({"ok": False, "error": "선택된 폴더가 없습니다."}, status_code=200)
    return JSONResponse({"ok": True, "path": path})


def _pick_directory_native() -> str:
    system = platform.system()
    if system == "Darwin":
        proc = subprocess.run(
            ["osascript", "-e", 'POSIX path of (choose folder with prompt "llm-wiki 저장 위치 선택")'],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or "Finder 폴더 선택을 열 수 없습니다.").strip())
        return proc.stdout.strip().rstrip("/")
    if system == "Windows":
        script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
            "$d.Description = 'llm-wiki 저장 위치 선택'; "
            "if ($d.ShowDialog() -eq 'OK') { $d.SelectedPath }"
        )
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or "파일 탐색기 폴더 선택을 열 수 없습니다.").strip())
        return proc.stdout.strip()

    for command in (
        ["zenity", "--file-selection", "--directory", "--title=llm-wiki 저장 위치 선택"],
        ["kdialog", "--getexistingdirectory", str(Path.home())],
    ):
        if shutil.which(command[0]):
            proc = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
            if proc.returncode == 0:
                return proc.stdout.strip()
    raise RuntimeError("지원되는 폴더 선택 프로그램을 찾지 못했습니다.")



@router.post("/settings", response_class=HTMLResponse)
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
    )
    return RedirectResponse("/admin?saved=1", status_code=303)
