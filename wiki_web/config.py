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
from pathlib import Path

CONFIG_FILE = Path.home() / ".config" / "llm-wiki" / "config.json"

DEFAULTS: dict = {
    "workspace_root": "",
    "domains": [],
    "active_domain_id": "",
    "model": "",
    "search_tier": "grep",
    "ollama_base_url": "http://localhost:11434",
    "openai_api_key": "",
    "anthropic_api_key": "",
    "chunk_strategy": "section",
    "chunk_size": 500,
    "chunk_overlap": 100,
}

MODEL_PRESETS = [
    ("", "자동 감지 (Ollama 우선)"),
    ("ollama/llama3", "Ollama — llama3 (로컬)"),
    ("ollama/mistral", "Ollama — mistral (로컬)"),
    ("ollama/gemma3", "Ollama — gemma3 (로컬)"),
    ("gpt-4o", "OpenAI — GPT-4o"),
    ("gpt-4o-mini", "OpenAI — GPT-4o mini"),
    ("claude-sonnet-4-20250514", "Anthropic — Claude Sonnet 4"),
    ("claude-haiku-4-5-20251001", "Anthropic — Claude Haiku 4.5"),
    ("__custom__", "직접 입력..."),
]

SEARCH_TIERS = [
    ("grep", "Grep (기본 — 추가 설치 불필요)"),
    ("bm25", "BM25 (pip install rank-bm25 필요)"),
    ("embedding", "Embedding / 의미 검색 (pip install sentence-transformers 필요)"),
]

CHUNK_STRATEGIES = [
    ("section", "섹션 분할 (기본 — 헤더/단락 경계로 분리)"),
    ("fixed", "고정 길이 분할 (문서 유형 무관, 글자 수로 분리)"),
    ("none", "분할 없음 (짧은 문서 전용, 초과 시 앞부분만 처리)"),
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


def apply_env(cfg: dict) -> None:
    """설정을 환경변수에 적용 — ops 레이어가 이를 통해 값을 읽음."""
    if cfg.get("model"):
        os.environ["WIKI_MODEL"] = cfg["model"]
    elif "WIKI_MODEL" in os.environ:
        del os.environ["WIKI_MODEL"]

    if cfg.get("search_tier"):
        os.environ["WIKI_SEARCH"] = cfg["search_tier"]

    if cfg.get("openai_api_key"):
        os.environ["OPENAI_API_KEY"] = cfg["openai_api_key"]

    if cfg.get("anthropic_api_key"):
        os.environ["ANTHROPIC_API_KEY"] = cfg["anthropic_api_key"]

    if cfg.get("ollama_base_url"):
        os.environ["WIKI_OLLAMA_BASE_URL"] = cfg["ollama_base_url"]

    os.environ["WIKI_CHUNK_STRATEGY"] = cfg.get("chunk_strategy") or "section"
    os.environ["WIKI_CHUNK_SIZE"] = str(cfg.get("chunk_size") or 500)
    os.environ["WIKI_CHUNK_OVERLAP"] = str(cfg.get("chunk_overlap") or 100)


# ── 도메인 헬퍼 ─────────────────────────────────────────────────────────────

def get_all_domains(cfg: dict | None = None) -> list[dict]:
    return (cfg or load()).get("domains", [])


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
    model: str,
    model_custom: str,
    search_tier: str,
    ollama_base_url: str,
    openai_api_key: str,
    anthropic_api_key: str,
    chunk_strategy: str,
    chunk_size: int,
    chunk_overlap: int,
) -> dict:
    """`/settings`와 `/admin/settings`가 공유하는 저장 로직.

    폼 파라미터를 정규화해 config에 반영하고 환경변수까지 즉시 적용한다.
    반환값은 최종 저장된 설정 dict.
    """
    final_model = model_custom.strip() if model == "__custom__" else model
    size = max(100, int(chunk_size))
    overlap = max(0, min(int(chunk_overlap), size - 1))

    c = load()
    c.update({
        "model": final_model,
        "search_tier": search_tier,
        "ollama_base_url": ollama_base_url.strip(),
        "openai_api_key": openai_api_key.strip(),
        "anthropic_api_key": anthropic_api_key.strip(),
        "chunk_strategy": chunk_strategy,
        "chunk_size": size,
        "chunk_overlap": overlap,
    })
    save(c)
    apply_env(c)
    return c


def wiki_is_initialized(root: Path | None = None) -> bool:
    r = root or get_wiki_root()
    return (r / "AGENTS.md").exists()
