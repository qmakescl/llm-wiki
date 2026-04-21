"""Smoke tests — 핵심 모듈 import와 FastAPI 앱 부팅만 확인."""

from __future__ import annotations


def test_cli_imports():
    from wiki_cli.main import cli
    assert cli is not None


def test_create_app(isolated_config):
    from wiki_web.app import create_app

    app = create_app()
    routes = {r.path for r in app.routes}
    assert "/documents/upload" in routes
    assert "/settings" in routes
    assert "/admin" in routes
