"""config 마이그레이션 및 active domain 해석 테스트."""

from __future__ import annotations

import json


def test_migrate_legacy_single_wiki_root(isolated_config, tmp_path):
    cfg = isolated_config
    legacy = {
        "wiki_root": str(tmp_path / "my-old-wiki"),
        "model": "gpt-4o",
    }
    cfg.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    cfg.CONFIG_FILE.write_text(json.dumps(legacy), encoding="utf-8")

    c = cfg.load()

    # 1차 마이그레이션: wiki_root → domains 배열
    assert "wiki_root" not in c
    assert len(c["domains"]) == 1
    # 2차 마이그레이션: domain[0].wiki_root → workspace_root + folder
    assert c["domains"][0]["folder"] == "my-old-wiki"
    assert c["workspace_root"] == str(tmp_path)
    assert c["active_domain_id"] == c["domains"][0]["id"]


def test_get_active_domain_falls_back_to_first(isolated_config):
    cfg = isolated_config
    cfg.save({
        "workspace_root": "/tmp/ws",
        "domains": [
            {"id": "a", "name": "A", "folder": "a"},
            {"id": "b", "name": "B", "folder": "b"},
        ],
        "active_domain_id": "",  # 빈 상태여도 첫 번째로 폴백
    })
    active = cfg.get_active_domain()
    assert active is not None
    assert active["id"] == "a"


def test_archive_and_restore_domain(isolated_config):
    cfg = isolated_config
    cfg.save({
        "workspace_root": "/tmp/ws",
        "domains": [
            {"id": "a", "name": "A", "folder": "a"},
            {"id": "b", "name": "B", "folder": "b"},
        ],
        "archived_domains": [],
        "active_domain_id": "a",
    })

    cfg.archive_domain("a")
    archived = cfg.get_archived_domains()
    assert [d["id"] for d in cfg.get_all_domains()] == ["b"]
    assert archived[0]["id"] == "a"
    assert archived[0]["archived_at"]
    assert cfg.load()["active_domain_id"] == "b"

    cfg.restore_domain("a")
    saved = cfg.load()
    assert [d["id"] for d in saved["domains"]] == ["b", "a"]
    assert saved["archived_domains"] == []
    assert saved["active_domain_id"] == "b"


def test_delete_domain_record_removes_active_and_archived(isolated_config):
    cfg = isolated_config
    cfg.save({
        "workspace_root": "/tmp/ws",
        "domains": [
            {"id": "a", "name": "A", "folder": "a"},
            {"id": "b", "name": "B", "folder": "b"},
        ],
        "archived_domains": [
            {"id": "c", "name": "C", "folder": "c", "archived_at": "now"},
        ],
        "active_domain_id": "a",
    })

    cfg.delete_domain_record("a")
    cfg.delete_domain_record("c")
    saved = cfg.load()
    assert [d["id"] for d in saved["domains"]] == ["b"]
    assert saved["archived_domains"] == []
    assert saved["active_domain_id"] == "b"


def test_save_runtime_settings_applies_env(isolated_config, monkeypatch):
    cfg = isolated_config
    cfg.save({
        "workspace_root": "/tmp/ws",
        "domains": [{"id": "a", "name": "A", "folder": "a"}],
        "active_domain_id": "a",
    })
    # 청크 오버랩이 크기보다 크면 clamp되어야 함
    saved = cfg.save_runtime_settings(
        model="gpt-4o",
        model_custom="",
        search_tier="grep",
        ollama_base_url="http://localhost:11434",
        openai_api_key="",
        anthropic_api_key="",
        chunk_strategy="section",
        chunk_size=200,
        chunk_overlap=500,  # size보다 큼 → clamp
    )
    assert saved["chunk_size"] == 200
    assert saved["chunk_overlap"] == 199

    import os
    assert os.environ["WIKI_MODEL"] == "gpt-4o"
    assert os.environ["WIKI_CHUNK_STRATEGY"] == "section"


def test_save_runtime_settings_custom_model(isolated_config):
    cfg = isolated_config
    cfg.save({
        "workspace_root": "/tmp/ws",
        "domains": [{"id": "a", "name": "A", "folder": "a"}],
        "active_domain_id": "a",
    })
    saved = cfg.save_runtime_settings(
        model="__custom__",
        model_custom="ollama/gemma4:31b",
        search_tier="grep",
        ollama_base_url="http://localhost:11434",
        openai_api_key="",
        anthropic_api_key="",
        chunk_strategy="section",
        chunk_size=500,
        chunk_overlap=100,
    )
    assert saved["model"] == "ollama/gemma4:31b"


def test_normalize_model_adds_ollama_prefix(isolated_config):
    cfg = isolated_config
    assert cfg.normalize_model("ollama", "__custom__", "gemma4:e4b") == "ollama/gemma4:e4b"


def test_save_runtime_settings_external_provider_env(isolated_config, monkeypatch):
    cfg = isolated_config
    cfg.save({
        "workspace_root": "/tmp/ws",
        "domains": [{"id": "a", "name": "A", "folder": "a"}],
        "active_domain_id": "a",
    })

    saved = cfg.save_runtime_settings(
        llm_provider="openrouter",
        model="__custom__",
        model_custom="anthropic/claude-sonnet-4",
        search_tier="grep",
        ollama_base_url="http://llm-lab.local:11434",
        openai_api_key="openai-key",
        anthropic_api_key="anthropic-key",
        google_api_key="google-key",
        openrouter_api_key="openrouter-key",
        chunk_strategy="section",
        chunk_size=500,
        chunk_overlap=100,
    )

    assert saved["llm_provider"] == "openrouter"
    assert saved["model"] == "openrouter/anthropic/claude-sonnet-4"

    import os
    assert os.environ["WIKI_MODEL"] == "openrouter/anthropic/claude-sonnet-4"
    assert os.environ["WIKI_LLM_PROVIDER"] == "openrouter"
    assert os.environ["WIKI_OLLAMA_BASE_URL"] == "http://llm-lab.local:11434"
    assert os.environ["OPENAI_API_KEY"] == "openai-key"
    assert os.environ["ANTHROPIC_API_KEY"] == "anthropic-key"
    assert os.environ["GOOGLE_API_KEY"] == "google-key"
    assert os.environ["GEMINI_API_KEY"] == "google-key"
    assert os.environ["OPENROUTER_API_KEY"] == "openrouter-key"
