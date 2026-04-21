"""llm.py가 환경변수를 call-time에 다시 읽는지 검증."""

from __future__ import annotations

from wiki_cli import llm


def test_chunk_config_reads_env_each_call(monkeypatch):
    monkeypatch.setenv("WIKI_CHUNK_STRATEGY", "section")
    monkeypatch.setenv("WIKI_CHUNK_SIZE", "400")
    monkeypatch.setenv("WIKI_CHUNK_OVERLAP", "50")
    monkeypatch.setenv("WIKI_MAX_CHUNKS", "10")
    strategy, size, overlap, max_chunks = llm._get_chunk_config()
    assert (strategy, size, overlap, max_chunks) == ("section", 400, 50, 10)

    # 값을 바꾼 뒤 다시 호출하면 새 값을 반환해야 한다 (import-time 캐시 X)
    monkeypatch.setenv("WIKI_CHUNK_STRATEGY", "fixed")
    monkeypatch.setenv("WIKI_CHUNK_SIZE", "800")
    strategy2, size2, _, _ = llm._get_chunk_config()
    assert strategy2 == "fixed"
    assert size2 == 800


def test_pdf_and_timeout_read_env_each_call(monkeypatch):
    monkeypatch.setenv("WIKI_PDF_MAX_CHARS", "12345")
    monkeypatch.setenv("WIKI_LLM_TIMEOUT", "77")
    assert llm._get_pdf_max_chars() == 12345
    assert llm._get_llm_timeout() == 77


def test_invalid_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("WIKI_CHUNK_SIZE", "not-a-number")
    _, size, _, _ = llm._get_chunk_config()
    assert size == 500


def test_cap_chunks_merges_to_max():
    chunks = [f"c{i}" for i in range(10)]
    capped = llm._cap_chunks(chunks, max_chunks=3)
    assert len(capped) == 3
