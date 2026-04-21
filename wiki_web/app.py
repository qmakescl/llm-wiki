"""FastAPI 앱 팩토리."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates

from wiki_web import config as cfg

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# base.html에서 도메인 목록을 항상 읽을 수 있도록 Jinja2 전역 함수 등록
templates.env.globals["get_all_domains"] = lambda: cfg.get_all_domains()
templates.env.globals["get_active_domain_id"] = lambda: cfg.load().get("active_domain_id", "")


def create_app() -> FastAPI:
    app = FastAPI(title="llm-wiki", docs_url=None, redoc_url=None)

    settings = cfg.load()
    cfg.apply_env(settings)
    logger.info("활성 도메인: %s", cfg.get_active_domain(settings))

    from wiki_web.routers import wiki, documents, query, settings as settings_router, lint
    from wiki_web.routers import admin
    from wiki_web.routers import synthesis

    app.include_router(wiki.router)
    app.include_router(documents.router)
    app.include_router(query.router)
    app.include_router(settings_router.router)
    app.include_router(lint.router)
    app.include_router(admin.router)
    app.include_router(synthesis.router)

    return app
