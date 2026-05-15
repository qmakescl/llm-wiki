"""LLM adapter — swap any model via litellm without changing call sites."""

from __future__ import annotations

import logging
import os
import json
import hashlib
from pathlib import Path
from typing import Any

import litellm

from wiki_cli import source_registry

logger = logging.getLogger(__name__)

# ── Default model resolution ──────────────────────────────────────────────────
# Priority: CLI --model flag → WIKI_MODEL env → Ollama (if reachable) → cloud
_CLOUD_FALLBACK = "claude-sonnet-4-20250514"
_CACHE_VERSION = "v1"


def ollama_tags(base_url: str | None = None, timeout: float = 1) -> list[str]:
    """Return installed Ollama model tags from `/api/tags`."""
    import urllib.request
    base = (base_url or os.environ.get("WIKI_OLLAMA_BASE_URL") or "http://localhost:11434").rstrip("/")
    try:
        with urllib.request.urlopen(f"{base}/api/tags", timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return []
    models = payload.get("models") or []
    return [m.get("name") or m.get("model") for m in models if m.get("name") or m.get("model")]


def _ollama_reachable() -> bool:
    """Check if Ollama is running at the configured base URL (1-second timeout)."""
    return bool(ollama_tags())


def _choose_ollama_tag(tags: list[str]) -> str:
    for preferred in ("llama3", "gemma4:e4b", "gemma4:31b", "gemma3", "mistral"):
        if preferred in tags:
            return preferred
    return tags[0]


def default_model() -> str:
    if env := os.environ.get("WIKI_MODEL"):
        return env
    if tags := ollama_tags():
        tag = _choose_ollama_tag(tags)
        logger.info("Ollama 감지됨 — ollama/%s 사용", tag)
        return f"ollama/{tag}"
    return _CLOUD_FALLBACK


def resolve_model(override: str | None) -> str:
    m = override or default_model()
    # Ollama 모델 태그 형식 (e.g. "gemma4:31b") → "ollama/gemma4:31b" 자동 변환
    # 클라우드 모델(gpt-4o, claude-...)은 ":" 없이 "-" 만 사용하므로 충돌 없음
    if ":" in m and "/" not in m:
        m = f"ollama/{m}"
    return m


# ── Core call ────────────────────────────────────────────────────────────────
# 값은 매 호출마다 환경변수를 읽어온다. 웹 UI의 /settings 또는 /admin/settings에서
# 값을 바꾼 뒤 cfg.apply_env()가 적용되면 다음 ingest/query부터 즉시 반영된다.


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, str(default)))
    except ValueError:
        return default


def _get_pdf_max_chars() -> int:
    """PDF 텍스트 최대 길이 (글자 수) — none 전략에서 초과 시 앞부분만 사용."""
    return _env_int("WIKI_PDF_MAX_CHARS", 60000)


def _get_llm_timeout() -> int:
    """LLM 호출 타임아웃(초) — Ollama 대형 모델 대응."""
    return _env_int("WIKI_LLM_TIMEOUT", 1200)


def _get_chunk_config() -> tuple[str, int, int, int]:
    """(strategy, size, overlap, max_chunks)."""
    strategy = os.environ.get("WIKI_CHUNK_STRATEGY", "section")
    return (
        strategy,
        _env_int("WIKI_CHUNK_SIZE", 500),
        _env_int("WIKI_CHUNK_OVERLAP", 100),
        _env_int("WIKI_MAX_CHUNKS", 20),
    )


def _env_flag(key: str, default: bool = True) -> bool:
    value = os.environ.get(key)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _get_cache_root(file_path: Path) -> Path:
    """Return the cache root for a source file.

    Files inside `data/<domain>/raw/...` use `data/<domain>/.cache/`.
    Other ad-hoc CLI files use a local `.llm_wiki_cache/` next to the file.
    """
    resolved = file_path.resolve()
    for parent in [resolved.parent, *resolved.parents]:
        if parent.name == "raw":
            return parent.parent / ".cache"
    return resolved.parent / ".llm_wiki_cache"


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _cache_key(payload: dict) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def call(
    prompt: str,
    *,
    system: str = "",
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.3,
    metrics: Any | None = None,
) -> str:
    """Single-turn LLM call. Returns the assistant reply as a plain string."""
    m = resolve_model(model)
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    # Ollama 로컬 서버 base URL 지원
    kwargs: dict = dict(
        model=m,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=_get_llm_timeout(),
    )
    if m.startswith("ollama/"):
        base = os.environ.get("WIKI_OLLAMA_BASE_URL", "http://localhost:11434")
        kwargs["api_base"] = base

    prompt_chars = sum(len(str(msg.get("content") or "")) for msg in messages)
    if metrics:
        metrics.count("llm.calls")
        metrics.record("llm.model", m)
        metrics.record("llm.prompt_chars", prompt_chars)
        metrics.record("llm.max_tokens", max_tokens)

    if metrics:
        with metrics.timer("llm.call_total"):
            resp = litellm.completion(**kwargs)
    else:
        resp = litellm.completion(**kwargs)

    content = resp.choices[0].message.content.strip()
    if metrics:
        metrics.record("llm.response_chars", len(content))
    return content


def call_with_file(
    prompt: str,
    file_path: Path,
    *,
    system: str = "",
    model: str | None = None,
    max_tokens: int = 4096,
    metrics: Any | None = None,
) -> str:
    """Read a file and include its content in the user message."""
    if metrics:
        metrics.count("llm.file_calls")
    source_hash = source_registry.sha256_file(file_path)
    strategy, chunk_size, chunk_overlap, max_chunks = _get_chunk_config()
    cache_payload = {
        "cache_version": _CACHE_VERSION,
        "kind": "call_with_file_result",
        "file_sha256": source_hash,
        "file_suffix": file_path.suffix.lower(),
        "prompt_sha256": _hash_text(prompt),
        "system_sha256": _hash_text(system),
        "model": resolve_model(model),
        "max_tokens": max_tokens,
        "chunk_strategy": strategy,
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
        "max_chunks": max_chunks,
        "pdf_max_chars": _get_pdf_max_chars(),
    }
    if cached := _load_text_cache(file_path, "llm_results", _cache_key(cache_payload)):
        logger.info("LLM file-result cache hit: %s", file_path.name)
        if metrics:
            metrics.count("llm.file_cache_hits")
        return cached
    if metrics:
        metrics.count("llm.file_cache_misses")

    content = _read_file_content(file_path, source_hash)
    if metrics:
        metrics.record("llm.file_chars", len(content))

    if strategy == "section":
        chunks = _split_by_section(content)
    elif strategy == "fixed":
        chunks = _split_by_fixed(content, chunk_size, chunk_overlap)
    else:
        chunks = [content]

    if len(chunks) <= 1:
        text = chunks[0] if chunks else content
        pdf_max = _get_pdf_max_chars()
        if len(text) > pdf_max:
            truncated = len(text) - pdf_max
            text = (
                text[:pdf_max]
                + f"\n\n[... 이하 {truncated:,}자 생략 — 문서가 너무 길어 앞부분만 처리됨 ...]"
            )
            logger.warning("문서 텍스트 트런케이트: %s (%d자 초과)", file_path.name, truncated)
            if metrics:
                metrics.record("llm.file_truncated_chars", truncated)
        if metrics:
            metrics.record("llm.file_chunks", 1)
        result = call(
            f"{prompt}\n\n---\n\n{text}",
            system=system,
            model=model,
            max_tokens=max_tokens,
            metrics=metrics,
        )
        _save_text_cache(file_path, "llm_results", _cache_key(cache_payload), result)
        return result

    chunks = _cap_chunks(chunks, max_chunks)
    if metrics:
        metrics.record("llm.file_chunks", len(chunks))
    logger.info("청킹 전략 '%s' 적용 — %d개 청크: %s", strategy, len(chunks), file_path.name)
    result = _chunk_and_call(prompt, chunks, system=system, model=model, max_tokens=max_tokens, metrics=metrics)
    _save_text_cache(file_path, "llm_results", _cache_key(cache_payload), result)
    return result


def _split_by_section(text: str) -> list[str]:
    """마크다운 헤더(#, ##, ###) 또는 페이지 경계로 섹션 분리."""
    import re
    sections = re.split(r"(?m)^(?=#+ )", text)
    sections = [s.strip() for s in sections if s.strip()]
    return sections if len(sections) > 1 else [text]


def _split_by_fixed(text: str, size: int, overlap: int) -> list[str]:
    """고정 길이(글자 수) + 오버랩 방식으로 분리."""
    if len(text) <= size:
        return [text]
    chunks, start = [], 0
    step = max(size - overlap, 1)
    while start < len(text):
        chunks.append(text[start : start + size])
        start += step
    return chunks


def _chunk_and_call(
    prompt: str,
    chunks: list[str],
    *,
    system: str,
    model: str | None,
    max_tokens: int,
    metrics: Any | None,
) -> str:
    """청크별 evidence 추출(경량) 후 1회 통합 분석."""
    evidence_parts: list[str] = []
    for i, chunk in enumerate(chunks, 1):
        evidence_prompt = (
            f"[문서 {i}/{len(chunks)} 구간] "
            "이 구간에 등장하는 엔티티, 개념, 핵심 주장·수치를 간결한 목록으로 추출하세요. "
            "서술형 요약 없이 항목 나열만 합니다.\n\n---\n\n" + chunk
        )
        evidence = call(evidence_prompt, system=system, model=model, max_tokens=1024, metrics=metrics)
        evidence_parts.append(f"[구간 {i}/{len(chunks)}]\n{evidence}")

    combined = "\n\n".join(evidence_parts)
    synthesis_prompt = (
        f"{prompt}\n\n"
        f"[아래는 원문을 {len(chunks)}개 구간으로 나누어 추출한 evidence 목록입니다. "
        "원본 문서 전체로 간주하고 위 요청을 수행하세요.]\n\n" + combined
    )
    return call(synthesis_prompt, system=system, model=model, max_tokens=max_tokens, metrics=metrics)


def _read_file_content(file_path: Path, source_hash: str | None = None) -> str:
    """Read source text with an extraction cache.

    PDF extraction is the main win because parsing can be expensive. Text and
    markdown also pass through the same cache so repeated failed ingests avoid
    rereading and re-normalizing large files.
    """
    source_hash = source_hash or source_registry.sha256_file(file_path)
    key = _cache_key({
        "cache_version": _CACHE_VERSION,
        "kind": "extracted_text",
        "file_sha256": source_hash,
        "file_suffix": file_path.suffix.lower(),
    })
    if cached := _load_text_cache(file_path, "extracted_text", key):
        logger.info("extracted-text cache hit: %s", file_path.name)
        return cached

    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        content = _extract_pdf(file_path)
    else:
        content = file_path.read_text(encoding="utf-8", errors="replace")

    _save_text_cache(file_path, "extracted_text", key, content)
    return content


def _load_text_cache(file_path: Path, namespace: str, key: str) -> str | None:
    if namespace == "extracted_text" and not _env_flag("WIKI_EXTRACT_CACHE", True):
        return None
    if namespace == "llm_results" and not _env_flag("WIKI_LLM_FILE_CACHE", True):
        return None
    path = _get_cache_root(file_path) / namespace / f"{key}.txt"
    try:
        if path.exists():
            return path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        logger.warning("캐시 로드 실패(%s): %s", path, e)
    return None


def _save_text_cache(file_path: Path, namespace: str, key: str, value: str) -> None:
    if namespace == "extracted_text" and not _env_flag("WIKI_EXTRACT_CACHE", True):
        return
    if namespace == "llm_results" and not _env_flag("WIKI_LLM_FILE_CACHE", True):
        return
    path = _get_cache_root(file_path) / namespace / f"{key}.txt"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
    except OSError as e:
        logger.warning("캐시 저장 실패(%s): %s", path, e)


def _cap_chunks(chunks: list[str], max_chunks: int) -> list[str]:
    """청크 수가 max_chunks 초과 시 인접 청크를 균등 병합하여 상한을 맞춤."""
    if len(chunks) <= max_chunks:
        return chunks
    logger.warning("청크 수 %d개 → %d개로 자동 병합 (WIKI_MAX_CHUNKS=%d)", len(chunks), max_chunks, max_chunks)
    merged, ratio = [], len(chunks) / max_chunks
    for i in range(max_chunks):
        start = int(i * ratio)
        end = int((i + 1) * ratio)
        merged.append("\n\n".join(chunks[start:end]))
    return merged


def _extract_pdf(path: Path) -> str:
    """Extract text from PDF using pypdf."""
    try:
        import pypdf
        reader = pypdf.PdfReader(str(path))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    except ImportError:
        return (
            f"[PDF: {path.name} — pypdf 설치 필요: pip install pypdf]"
        )
