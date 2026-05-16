"""wiki_cli.fs 테스트 — index upsert, 업로드 sanitize, write_page 정책."""

from __future__ import annotations

import pytest

from wiki_cli import fs


# ── Slug ──────────────────────────────────────────────────────────────────────

def test_file_slug_strips_css_selector_chars():
    # 쉼표·괄호·점 등은 CSS selector에서 분리자·특수기호로 해석되므로 제거되어야 한다.
    stem = "A Comparative Study _ by Kiumarse Zamanian, PhD _ Medium"
    slug = fs.file_slug(stem)
    assert "," not in slug
    assert slug == "a-comparative-study-_-by-kiumarse-zamanian-phd-_-medium"


def test_file_slug_preserves_existing_underscore_slug():
    # 이미 ingest된 기존 파일의 slug가 그대로 유지되어야 한다(호환성).
    assert fs.file_slug("Google_ai_agents_handbook") == "google_ai_agents_handbook"
    assert fs.file_slug("MS_The AI Decision Brief") == "ms_the-ai-decision-brief"


def test_file_slug_empty_fallback():
    assert fs.file_slug("!!!") == "doc"


# ── Upload safety ─────────────────────────────────────────────────────────────

def test_sanitize_upload_strips_traversal_to_basename():
    # `../../etc/passwd` 같은 입력은 basename만 남아 traversal이 무력화된다.
    assert fs.sanitize_upload_name("../../etc/my.pdf") == "my.pdf"


def test_resolve_upload_rejects_traversal_result(tmp_path):
    # 실제 업로드 경로 결정 단계에서도 raw/ 밖으로 나가지 않아야 한다.
    raw = tmp_path / "raw"
    raw.mkdir()
    dest = fs.resolve_upload_path(raw, "../../etc/passwd.md")
    assert dest.resolve().parent == raw.resolve()
    assert dest.name == "passwd.md"


def test_sanitize_upload_rejects_empty_and_dotfiles():
    with pytest.raises(fs.UnsafeUploadError):
        fs.sanitize_upload_name("")
    with pytest.raises(fs.UnsafeUploadError):
        fs.sanitize_upload_name(".bashrc")


def test_sanitize_upload_strips_directory_prefix():
    # 윈도우·유닉스 혼합 경로 모두 basename만 남아야 한다
    assert fs.sanitize_upload_name("folder/sub/my.pdf") == "my.pdf"
    assert fs.sanitize_upload_name("C:\\Users\\me\\paper.pdf") == "paper.pdf"


def test_resolve_upload_path_rejects_bad_extension(tmp_path):
    with pytest.raises(fs.UnsafeUploadError):
        fs.resolve_upload_path(tmp_path, "malware.exe")


def test_resolve_upload_path_collision_gets_suffix(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "paper.pdf").write_bytes(b"existing")

    dest = fs.resolve_upload_path(raw, "paper.pdf")
    assert dest != raw / "paper.pdf"
    assert dest.name.startswith("paper__") and dest.suffix == ".pdf"
    # 충돌 회피 경로도 여전히 raw/ 내부여야 한다
    assert dest.resolve().parent == raw.resolve()


def test_resolve_upload_path_stays_inside_raw(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    dest = fs.resolve_upload_path(raw, "notes.md")
    assert dest.resolve().parent == raw.resolve()


# ── Index upsert ──────────────────────────────────────────────────────────────

def test_update_index_entry_upserts_by_section(wiki_root):
    sources_page = wiki_root / "sources" / "paper.md"
    fs.write_page(sources_page, {"title": "Paper", "type": "source"}, "body")

    concepts_page = wiki_root / "concepts" / "Self Attention.md"
    fs.write_page(concepts_page, {"title": "Self Attention", "type": "concept"}, "body")

    fs.update_index_entry(wiki_root, sources_page, "Paper", "A source paper")
    fs.update_index_entry(wiki_root, concepts_page, "Self Attention", "Core concept")

    idx = (wiki_root / "index.md").read_text(encoding="utf-8")
    # 섹션별 upsert: 동일 rel 한 줄만 존재
    assert idx.count("sources/paper.md") == 1
    assert idx.count("Self Attention.md") == 1

    # 기존 엔트리 업데이트 시 중복 생성되지 않아야 한다
    fs.update_index_entry(wiki_root, sources_page, "Paper", "A source paper (revised)")
    idx = (wiki_root / "index.md").read_text(encoding="utf-8")
    assert idx.count("sources/paper.md") == 1
    assert "revised" in idx


def test_write_page_sets_aliases_from_title(wiki_root):
    page = wiki_root / "entities" / "Bert Model.md"
    fs.write_page(page, {"title": "Bert Model", "type": "entity"}, "# Bert Model")
    meta, _ = fs.read_page(page)
    assert meta["aliases"] == ["Bert Model"]
    assert meta["created"] == meta["updated"]


def test_write_page_normalizes_obsidian_tags(wiki_root):
    page = wiki_root / "concepts" / "Tag Test.md"
    fs.write_page(
        page,
        {
            "title": "Tag Test",
            "type": "concept",
            "tags": ["Machine Learning", "#AI/Agents", "2026 Research", "AI/Agents"],
        },
        "# Tag Test",
    )

    meta, _ = fs.read_page(page)

    assert meta["tags"] == ["machine-learning", "ai/agents", "tag-2026-research"]


def test_write_page_normalizes_scalar_tag_values(wiki_root):
    page = wiki_root / "sources" / "paper.md"
    fs.write_page(
        page,
        {"title": "Paper", "type": "source", "tags": "#LLM #RAG, Research Notes"},
        "# Paper",
    )

    meta, _ = fs.read_page(page)

    assert meta["tags"] == ["llm", "rag", "research-notes"]
