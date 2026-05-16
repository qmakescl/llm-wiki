"""웹 앱 설정 — ~/.config/llm-wiki/config.json 읽기/쓰기.

도메인(위키) 복수 관리를 지원합니다:
  - domains: [{id, name, wiki_root}, ...]
  - active_domain_id: 현재 활성 도메인 ID
  - 구형 단일 wiki_root 설정은 자동으로 마이그레이션됩니다.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

CONFIG_FILE = Path.home() / ".config" / "llm-wiki" / "config.json"

DEFAULTS: dict = {
    "workspace_root": "",
    "domains": [],
    "archived_domains": [],
    "active_domain_id": "",
    "llm_provider": "ollama",
    "model": "",
    "search_tier": "grep",
    "ollama_base_url": "http://localhost:11434",
    "openai_api_key": "",
    "anthropic_api_key": "",
    "google_api_key": "",
    "openrouter_api_key": "",
    "chunk_strategy": "section",
    "chunk_size": 500,
    "chunk_overlap": 100,
    "obsidian_sync": True,
    "output_language": "ko",
    "heading_original_language": True,
}

LLM_PROVIDERS = [
    ("ollama", "Ollama / 로컬·연구소 서버"),
    ("openai", "OpenAI"),
    ("anthropic", "Anthropic"),
    ("google", "Google Gemini"),
    ("openrouter", "OpenRouter"),
    ("custom", "직접 설정"),
]

MODEL_PRESETS = [
    ("", "자동 감지 (Ollama 우선)"),
    ("ollama/llama3", "Ollama — llama3"),
    ("ollama/mistral", "Ollama — mistral"),
    ("ollama/gemma3", "Ollama — gemma3"),
    ("ollama/gemma4:31b", "Ollama — gemma4:31b"),
    ("gpt-4o", "OpenAI — GPT-4o"),
    ("gpt-4o-mini", "OpenAI — GPT-4o mini"),
    ("claude-sonnet-4-20250514", "Anthropic — Claude Sonnet 4"),
    ("claude-haiku-4-5-20251001", "Anthropic — Claude Haiku 4.5"),
    ("gemini/gemini-2.5-pro", "Google — Gemini 2.5 Pro"),
    ("gemini/gemini-2.5-flash", "Google — Gemini 2.5 Flash"),
    ("openrouter/anthropic/claude-sonnet-4", "OpenRouter — Claude Sonnet"),
    ("openrouter/openai/gpt-4o", "OpenRouter — GPT-4o"),
    ("__custom__", "직접 입력..."),
]

SEARCH_TIERS = [
    ("grep", "Grep (빠른 키워드 검색)"),
    ("bm25", "BM25 (정확도 개선 키워드 검색)"),
    ("embedding", "Embedding / 의미 검색"),
    ("vector", "Vector DB / 청크 의미 검색"),
]

CHUNK_STRATEGIES = [
    ("section", "섹션 분할 (기본 — 헤더/단락 경계로 분리)"),
    ("fixed", "고정 길이 분할 (문서 유형 무관, 글자 수로 분리)"),
    ("none", "분할 없음 (짧은 문서 전용, 초과 시 앞부분만 처리)"),
]

OUTPUT_LANGUAGES = [
    ("ko", "한국어"),
    ("en", "English"),
    ("source", "원문 언어 유지"),
]


def load() -> dict:
    if CONFIG_FILE.exists():
        try:
            saved = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            cfg = {**DEFAULTS, **saved}
            cfg = _migrate(cfg)
            return cfg
        except Exception:
            pass
    return DEFAULTS.copy()


def _migrate(cfg: dict) -> dict:
    """구형 설정을 workspace_root와 domains 리스트로 마이그레이션."""
    # 1. 최상단 wiki_root를 domains 배열로 옮기는 1차 마이그레이션
    if "wiki_root" in cfg and not cfg.get("domains"):
        domain_id = _new_id()
        cfg["domains"] = [{
            "id": domain_id,
            "name": "기본 위키",
            "wiki_root": cfg.pop("wiki_root"),
        }]
        cfg["active_domain_id"] = domain_id
        save(cfg)
    elif "wiki_root" in cfg:
        del cfg["wiki_root"]

    # 2. domains 리스트의 요소가 wiki_root(절대경로)를 가진 경우, workspace_root와 folder로 2차 마이그레이션
    domains = cfg.get("domains", [])
    if domains and "wiki_root" in domains[0]:
        first_root = Path(domains[0]["wiki_root"])
        cfg["workspace_root"] = str(first_root.parent)
        for d in domains:
            if "wiki_root" in d:
                d["folder"] = Path(d.pop("wiki_root")).name
        save(cfg)

    return cfg


def _new_id() -> str:
    return str(uuid.uuid4())[:8]


def save(cfg: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def _set_or_clear_env(key: str, value: str | None) -> None:
    value = (value or "").strip()
    if value:
        os.environ[key] = value
    elif key in os.environ:
        del os.environ[key]


def apply_env(cfg: dict) -> None:
    """설정을 환경변수에 적용 — ops 레이어가 이를 통해 값을 읽음."""
    _set_or_clear_env("WIKI_MODEL", cfg.get("model"))
    _set_or_clear_env("WIKI_LLM_PROVIDER", cfg.get("llm_provider"))

    if cfg.get("search_tier"):
        os.environ["WIKI_SEARCH"] = cfg["search_tier"]

    _set_or_clear_env("OPENAI_API_KEY", cfg.get("openai_api_key"))
    _set_or_clear_env("ANTHROPIC_API_KEY", cfg.get("anthropic_api_key"))
    _set_or_clear_env("GOOGLE_API_KEY", cfg.get("google_api_key"))
    _set_or_clear_env("GEMINI_API_KEY", cfg.get("google_api_key"))
    _set_or_clear_env("OPENROUTER_API_KEY", cfg.get("openrouter_api_key"))
    _set_or_clear_env("WIKI_OLLAMA_BASE_URL", cfg.get("ollama_base_url"))

    os.environ["WIKI_CHUNK_STRATEGY"] = cfg.get("chunk_strategy") or "section"
    os.environ["WIKI_CHUNK_SIZE"] = str(cfg.get("chunk_size") or 500)
    os.environ["WIKI_CHUNK_OVERLAP"] = str(cfg.get("chunk_overlap") or 100)

    os.environ["WIKI_OBSIDIAN_SYNC"] = "on" if cfg.get("obsidian_sync", True) else "off"
    output_language = cfg.get("output_language") or "ko"
    if output_language not in {value for value, _label in OUTPUT_LANGUAGES}:
        output_language = "ko"
    os.environ["WIKI_OUTPUT_LANGUAGE"] = output_language
    os.environ["WIKI_HEADING_ORIGINAL_LANGUAGE"] = (
        "on" if cfg.get("heading_original_language", True) else "off"
    )


# ── 도메인 헬퍼 ─────────────────────────────────────────────────────────────

def get_all_domains(cfg: dict | None = None) -> list[dict]:
    return (cfg or load()).get("domains", [])


def get_archived_domains(cfg: dict | None = None) -> list[dict]:
    return (cfg or load()).get("archived_domains", [])


def get_active_domain(cfg: dict | None = None) -> dict | None:
    c = cfg or load()
    domains = c.get("domains", [])
    if not domains:
        return None
    active_id = c.get("active_domain_id", "")
    for d in domains:
        if d["id"] == active_id:
            return d
    return domains[0]


def get_wiki_root(cfg: dict | None = None) -> Path:
    """위키 콘텐츠 루트 — Obsidian이 읽는 마크다운 폴더. ws_root/wiki/{folder}"""
    c = cfg or load()
    domain = get_active_domain(c)
    ws_root = Path(c.get("workspace_root") or str(Path.home() / "llm-wikis"))
    folder = domain["folder"] if domain and "folder" in domain else "my-wiki"
    return ws_root / "wiki" / folder


def get_data_root(cfg: dict | None = None) -> Path:
    """운영 데이터 루트 — 원본 파일(raw/) 저장. ws_root/data/{folder}"""
    c = cfg or load()
    domain = get_active_domain(c)
    ws_root = Path(c.get("workspace_root") or str(Path.home() / "llm-wikis"))
    folder = domain["folder"] if domain and "folder" in domain else "my-wiki"
    return ws_root / "data" / folder


def add_domain(name: str, folder: str) -> dict:
    """새 도메인 추가 후 저장된 도메인 dict 반환."""
    cfg = load()
    domain = {"id": _new_id(), "name": name.strip(), "folder": folder.strip()}
    cfg.setdefault("domains", []).append(domain)
    if not cfg.get("active_domain_id"):
        cfg["active_domain_id"] = domain["id"]
    save(cfg)
    return domain


def remove_domain(domain_id: str) -> None:
    cfg = load()
    cfg["domains"] = [d for d in cfg.get("domains", []) if d["id"] != domain_id]
    if cfg.get("active_domain_id") == domain_id:
        cfg["active_domain_id"] = cfg["domains"][0]["id"] if cfg["domains"] else ""
    save(cfg)


def archive_domain(domain_id: str) -> None:
    """활성 목록에서 도메인을 숨기되 wiki/data 파일은 보존."""
    cfg = load()
    domains = cfg.get("domains", [])
    domain = next((d for d in domains if d["id"] == domain_id), None)
    if domain is None:
        return

    cfg["domains"] = [d for d in domains if d["id"] != domain_id]
    archived = cfg.setdefault("archived_domains", [])
    archived = [d for d in archived if d["id"] != domain_id]
    archived.append({
        **domain,
        "archived_at": datetime.now(timezone.utc).isoformat(),
    })
    cfg["archived_domains"] = archived
    if cfg.get("active_domain_id") == domain_id:
        cfg["active_domain_id"] = cfg["domains"][0]["id"] if cfg["domains"] else ""
    save(cfg)


def restore_domain(domain_id: str) -> None:
    """아카이브된 도메인을 다시 활성 목록으로 복원."""
    cfg = load()
    archived = cfg.get("archived_domains", [])
    domain = next((d for d in archived if d["id"] == domain_id), None)
    if domain is None:
        return

    restored = {k: v for k, v in domain.items() if k != "archived_at"}
    existing_folders = {d.get("folder") for d in cfg.get("domains", [])}
    folder = restored.get("folder") or restored["id"]
    if folder in existing_folders:
        raise ValueError(f"같은 폴더를 사용하는 활성 도메인이 이미 있습니다: {folder}")

    cfg.setdefault("domains", []).append(restored)
    cfg["archived_domains"] = [d for d in archived if d["id"] != domain_id]
    if not cfg.get("active_domain_id"):
        cfg["active_domain_id"] = restored["id"]
    save(cfg)


def delete_domain_record(domain_id: str) -> None:
    """도메인 설정을 활성/아카이브 목록 모두에서 영구 제거."""
    cfg = load()
    cfg["domains"] = [d for d in cfg.get("domains", []) if d["id"] != domain_id]
    cfg["archived_domains"] = [
        d for d in cfg.get("archived_domains", []) if d["id"] != domain_id
    ]
    if cfg.get("active_domain_id") == domain_id:
        cfg["active_domain_id"] = cfg["domains"][0]["id"] if cfg["domains"] else ""
    save(cfg)


def switch_domain(domain_id: str) -> None:
    cfg = load()
    cfg["active_domain_id"] = domain_id
    save(cfg)
    apply_env(cfg)


def update_domain(domain_id: str, name: str | None = None, folder: str | None = None) -> None:
    cfg = load()
    for d in cfg.get("domains", []):
        if d["id"] == domain_id:
            if name is not None:
                d["name"] = name.strip()
            if folder is not None:
                d["folder"] = folder.strip()
            break
    save(cfg)


def update_workspace_root(workspace_root: str) -> None:
    cfg = load()
    cfg["workspace_root"] = workspace_root.strip()
    save(cfg)


# ── 모델/검색/청킹 설정 저장 ─────────────────────────────────────────────────

def save_runtime_settings(
    *,
    llm_provider: str = "ollama",
    model: str,
    model_custom: str,
    search_tier: str,
    ollama_base_url: str,
    openai_api_key: str,
    anthropic_api_key: str,
    google_api_key: str = "",
    openrouter_api_key: str = "",
    chunk_strategy: str,
    chunk_size: int,
    chunk_overlap: int,
    obsidian_sync: bool = True,
    output_language: str = "ko",
    heading_original_language: bool = True,
) -> dict:
    """`/settings`와 `/admin/settings`가 공유하는 저장 로직.

    폼 파라미터를 정규화해 config에 반영하고 환경변수까지 즉시 적용한다.
    반환값은 최종 저장된 설정 dict.
    """
    final_provider = llm_provider.strip() or "ollama"
    final_model = _normalize_model(final_provider, model, model_custom)
    size = max(100, int(chunk_size))
    overlap = max(0, min(int(chunk_overlap), size - 1))
    allowed_languages = {value for value, _label in OUTPUT_LANGUAGES}
    final_output_language = output_language if output_language in allowed_languages else "ko"

    c = load()
    c.update({
        "llm_provider": final_provider,
        "model": final_model,
        "search_tier": search_tier,
        "ollama_base_url": ollama_base_url.strip(),
        "openai_api_key": openai_api_key.strip(),
        "anthropic_api_key": anthropic_api_key.strip(),
        "google_api_key": google_api_key.strip(),
        "openrouter_api_key": openrouter_api_key.strip(),
        "chunk_strategy": chunk_strategy,
        "chunk_size": size,
        "chunk_overlap": overlap,
        "obsidian_sync": obsidian_sync,
        "output_language": final_output_language,
        "heading_original_language": heading_original_language,
    })
    save(c)
    apply_env(c)
    return c


def _normalize_model(provider: str, model: str, model_custom: str) -> str:
    if model != "__custom__":
        return model.strip()
    final_model = model_custom.strip()
    if not final_model:
        return final_model
    if provider == "openrouter" and not final_model.startswith("openrouter/"):
        return f"openrouter/{final_model}"
    if "/" in final_model:
        return final_model
    if provider == "ollama":
        return f"ollama/{final_model}"
    if provider == "google":
        return f"gemini/{final_model}"
    if provider == "openrouter":
        return f"openrouter/{final_model}"
    return final_model


def normalize_model(provider: str, model: str, model_custom: str) -> str:
    return _normalize_model(provider, model, model_custom)


def wiki_is_initialized(root: Path | None = None) -> bool:
    r = root or get_wiki_root()
    return (r / "AGENTS.md").exists()
