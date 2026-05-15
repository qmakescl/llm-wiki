"""llm.py가 환경변수를 call-time에 다시 읽는지 검증."""

from __future__ import annotations

from wiki_cli import llm
from wiki_cli.metrics import Metrics


class _FakeMessage:
    content = "ok"


class _FakeChoice:
    message = _FakeMessage()


class _FakeResponse:
    choices = [_FakeChoice()]


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


def test_call_records_metrics(monkeypatch):
    monkeypatch.setenv("WIKI_MODEL", "gpt-4o")
    monkeypatch.setattr(llm.litellm, "completion", lambda **kwargs: _FakeResponse())

    metrics = Metrics()
    assert llm.call("hello", system="sys", metrics=metrics) == "ok"

    summary = metrics.summary()
    assert summary["counters"]["llm.calls"] == 1
    assert summary["values"]["llm.model"] == ["gpt-4o"]
    assert summary["values"]["llm.prompt_chars"] == [8]
    assert summary["values"]["llm.response_chars"] == [2]
    assert "llm.call_total" in summary["timings"]


def test_default_model_uses_installed_ollama_tag(monkeypatch):
    monkeypatch.delenv("WIKI_MODEL", raising=False)
    monkeypatch.setattr(llm, "ollama_tags", lambda *args, **kwargs: ["gemma4:e4b"])

    assert llm.default_model() == "ollama/gemma4:e4b"


def test_cap_chunks_merges_to_max():
    chunks = [f"c{i}" for i in range(10)]
    capped = llm._cap_chunks(chunks, max_chunks=3)
    assert len(capped) == 3


def test_cache_root_uses_data_domain_for_raw_files(tmp_path):
    source = tmp_path / "data" / "domain" / "raw" / "papers" / "paper.txt"
    source.parent.mkdir(parents=True)
    source.write_text("content", encoding="utf-8")

    assert llm._get_cache_root(source) == tmp_path / "data" / "domain" / ".cache"


def test_read_file_content_uses_extraction_cache(tmp_path, monkeypatch):
    source = tmp_path / "paper.txt"
    source.write_text("first", encoding="utf-8")
    from wiki_cli import source_registry
    original_hash = source_registry.sha256_file(source)

    text = llm._read_file_content(source, source_hash=original_hash)
    assert text == "first"

    cache_files = list((tmp_path / ".llm_wiki_cache" / "extracted_text").glob("*.txt"))
    assert len(cache_files) == 1

    source.unlink()
    # Supplying the original hash simulates a retry of the same file fingerprint.
    monkeypatch.setenv("WIKI_EXTRACT_CACHE", "1")
    cached = llm._read_file_content(source, source_hash=original_hash)
    assert cached == "first"


def test_call_with_file_result_cache_skips_second_llm_call(tmp_path, monkeypatch):
    source = tmp_path / "paper.txt"
    source.write_text("hello world", encoding="utf-8")
    monkeypatch.setenv("WIKI_MODEL", "gpt-4o")
    monkeypatch.setenv("WIKI_CHUNK_STRATEGY", "none")

    calls = {"count": 0}

    def fake_call(prompt: str, **kwargs):
        calls["count"] += 1
        assert "hello world" in prompt
        return "cached answer"

    monkeypatch.setattr(llm, "call", fake_call)

    first = llm.call_with_file("Summarize", source, system="sys", model=None)
    second = llm.call_with_file("Summarize", source, system="sys", model=None)

    assert first == "cached answer"
    assert second == "cached answer"
    assert calls["count"] == 1


def test_call_with_file_cache_can_be_disabled(tmp_path, monkeypatch):
    source = tmp_path / "paper.txt"
    source.write_text("hello world", encoding="utf-8")
    monkeypatch.setenv("WIKI_MODEL", "gpt-4o")
    monkeypatch.setenv("WIKI_CHUNK_STRATEGY", "none")
    monkeypatch.setenv("WIKI_LLM_FILE_CACHE", "0")

    calls = {"count": 0}

    def fake_call(prompt: str, **kwargs):
        calls["count"] += 1
        return f"answer {calls['count']}"

    monkeypatch.setattr(llm, "call", fake_call)

    assert llm.call_with_file("Summarize", source) == "answer 1"
    assert llm.call_with_file("Summarize", source) == "answer 2"
    assert calls["count"] == 2
