"""pytest 공통 fixtures — config 파일을 테스트용으로 임시 경로로 재설정."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def isolated_config(tmp_path, monkeypatch):
    """wiki_web.config의 CONFIG_FILE을 tmp_path로 치환.

    테스트가 사용자의 실제 ~/.config/llm-wiki/config.json을 건드리지 않게 한다.
    """
    from wiki_web import config as cfg

    test_config = tmp_path / "config.json"
    monkeypatch.setattr(cfg, "CONFIG_FILE", test_config)
    yield cfg


@pytest.fixture()
def wiki_root(tmp_path: Path) -> Path:
    """최소 wiki 디렉터리 구조."""
    root = tmp_path / "wiki"
    root.mkdir()
    (root / "AGENTS.md").write_text("test schema", encoding="utf-8")
    return root
