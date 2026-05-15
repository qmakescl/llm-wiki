"""대시보드 및 위키 초기화 라우터."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from wiki_web.app import templates
from wiki_web import config as cfg
from wiki_cli import fs
from wiki_cli.ops.init import run_init

router = APIRouter()


def _wiki_stats(root: Path) -> dict:
    if not cfg.wiki_is_initialized(root):
        return {}
    pages = fs.list_pages(root)
    return {
        "total": len(pages),
        "sources": sum(1 for p in pages if "sources" in str(p)),
        "entities": sum(1 for p in pages if "entities" in str(p)),
        "concepts": sum(1 for p in pages if "concepts" in str(p)),
        "synthesis": sum(1 for p in pages if "synthesis" in str(p)),
    }


def _recent_log(root: Path, n: int = 10) -> list[str]:
    log = fs.log_path(root)
    if not log.exists():
        return []
    text = log.read_text(encoding="utf-8")
    entries = re.split(r"\n(?=## \[)", text.strip())
    return [e.strip() for e in entries if e.strip()][-n:][::-1]


def _wiki_domain(root: Path) -> str:
    agents = root / "AGENTS.md"
    if not agents.exists():
        return ""
    for line in agents.read_text(encoding="utf-8").splitlines():
        if line.startswith("**Domain**"):
            return line.split(":", 1)[-1].strip().strip("*")
    return ""


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    c = cfg.load()
    domains = cfg.get_all_domains(c)
    if not domains:
        return RedirectResponse("/admin", status_code=303)
    active_domain = cfg.get_active_domain(c)
    root = cfg.get_wiki_root(c) if active_domain else None
    initialized = cfg.wiki_is_initialized(root) if root else False
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "initialized": initialized,
            "wiki_root": str(root) if root else "",
            "wiki_domain": _wiki_domain(root) if initialized and root else "",
            "domain_name": active_domain["name"] if active_domain else "",
            "stats": _wiki_stats(root) if root else {},
            "log_entries": _recent_log(root) if initialized and root else [],
            "has_domains": len(domains) > 0,
            "active_domain": active_domain,
        },
    )


@router.post("/init", response_class=HTMLResponse)
async def init_wiki(
    request: Request,
    directory: str = Form(...),
    domain: str = Form(...),
    domain_name: str = Form("새 위키"),
):
    """Legacy first-run endpoint; first wiki setup now lives in /admin."""
    return RedirectResponse("/admin", status_code=303)
    import re
    ws_root = Path(directory).expanduser().resolve()
    slug = re.sub(r'[^a-zA-Z0-9가-힣]+', '_', domain_name).strip('_').lower() or "my_wiki"
    wiki_root = ws_root / "wiki" / slug
    data_root = ws_root / "data" / slug
    try:
        run_init(wiki_root=wiki_root, data_root=data_root, domain=domain)
        c = cfg.load()
        c["workspace_root"] = str(ws_root)
        new_domain = {"id": __import__("uuid").uuid4().hex[:8],
                      "name": domain_name.strip() or domain.strip() or "새 위키",
                      "folder": slug}
        c.setdefault("domains", []).append(new_domain)
        c["active_domain_id"] = new_domain["id"]
        cfg.save(c)
        cfg.apply_env(c)
    except Exception as e:
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "initialized": False,
                "wiki_root": directory,
                "wiki_domain": "",
                "domain_name": "",
                "stats": {},
                "log_entries": [],
                "has_domains": False,
                "active_domain": None,
                "error": str(e),
            },
        )
    return RedirectResponse("/", status_code=303)
