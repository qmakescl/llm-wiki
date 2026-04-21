"""Ingest operation — process a single source into the wiki."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from wiki_cli import llm, fs

console = Console()
logger = logging.getLogger(__name__)

_SYSTEM = """You are a meticulous research wiki editor.
Your job is to process a source document and produce structured wiki content.
Always respond with valid markdown.
For internal links use [[Exact Page Title]] syntax — the title must match the target page's title field EXACTLY (including capitalization). For example [[Google Agentspace]], [[Agentic AI]]. Never use file slugs such as [[google-agentspace]].
Be precise, cite specific claims, and flag uncertainty with ⚠️.
Always output YAML frontmatter as a bare --- block, never inside a ```yaml code fence."""


class DuplicateSourceError(Exception):
    """이미 ingest된 소스 파일을 다시 처리하려 할 때 발생."""


def run_ingest(
    wiki_root: Path,
    source: Path,
    model: str | None,
    progress_callback: Callable[[str], None] | None = None,
) -> None:
    slug = fs.file_slug(source.stem)

    # ── 중복 검사 ─────────────────────────────────────────────────────────────
    existing_page = fs.wiki_dir(wiki_root) / "sources" / f"{slug}.md"
    if existing_page.exists():
        raise DuplicateSourceError(
            f"'{slug}'은(는) 이미 ingest되었습니다 ({existing_page}). "
            "다시 처리하려면 해당 파일을 삭제 후 재시도하세요."
        )

    schema = _load_schema(wiki_root)

    def _emit(msg: str) -> None:
        if progress_callback:
            progress_callback(msg)

    with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console,
                  disable=progress_callback is not None) as p:
        task = p.add_task("소스 읽는 중...", total=None)

        # ── Step 1: Read & discuss ────────────────────────────────────────
        _emit("소스 파일 읽는 중...")
        p.update(task, description="소스 파일 읽는 중...")
        summary_prompt = f"""
{schema}

Read the following source document and extract:
1. A 3-sentence summary
2. Key contributions or claims (bullet list)
3. Important entities mentioned (people, models, datasets, institutions)
4. Key concepts introduced or discussed
5. Connections to existing research (if apparent)
6. Any claims that seem uncertain or require verification

Source: {source.name}
---
"""
        overview = llm.call_with_file(summary_prompt, source, system=_SYSTEM, model=model)

        # ── Step 2: Plan entity/concept pages (source 페이지 작성 전에 먼저) ──
        # display_name을 source 페이지에 그대로 사용해 링크 이름이 일치하도록 함
        _emit("관련 엔티티/개념 계획 수립 중...")
        p.update(task, description="관련 엔티티/개념 계획 수립 중...")
        entity_entries, concept_entries = _plan_related_pages(
            wiki_root, overview, model, schema
        )
        entity_names = [_page_display_name(s) for _, s in entity_entries]
        concept_names = [_page_display_name(s) for _, s in concept_entries]

        # ── Step 3: Write source summary page ────────────────────────────
        _emit("소스 요약 페이지 생성 중...")
        p.update(task, description="소스 요약 페이지 생성 중...")
        page_path = fs.wiki_dir(wiki_root) / "sources" / f"{slug}.md"

        # 이미 계획된 entity/concept 이름 목록을 프롬프트에 포함해 링크 이름 통일
        planned_entities_str = "\n".join(f"- [[{n}]]" for n in entity_names) or "  (없음)"
        planned_concepts_str = "\n".join(f"- [[{n}]]" for n in concept_names) or "  (없음)"

        source_page_prompt = f"""
{schema}

Write a wiki page summarising this source document.
Use this analysis as your basis:

{overview}

IMPORTANT: Use ONLY the following exact names when creating wikilinks.
These names are the exact page titles that exist (or will be created) in this wiki.

Entities to link (use exactly as shown):
{planned_entities_str}

Concepts to link (use exactly as shown):
{planned_concepts_str}

Output a markdown file with YAML frontmatter (bare --- block, NOT inside a code fence):
---
title: <document title>
type: source
tags: [tag1, tag2]
sources: ["{source.name}"]
---

# <title>

## Summary
(3-5 sentences)

## Key contributions
- bullet points

## Entities mentioned
- [[Exact Entity Name]] — brief note

## Key concepts
- [[Exact Concept Name]] — brief note

## Notes & uncertainties
(optional)

Source filename: {source.name}
"""
        source_page = llm.call(source_page_prompt, system=_SYSTEM, model=model)
        _meta, _body = _parse_llm_page(source_page)
        # title이 없거나 파싱 실패 시에도 반드시 설정
        if not _meta.get("title"):
            _meta["title"] = _extract_title(source_page) or source.stem
        fs.write_page(page_path, _meta, _body)

        # ── Step 4: Update index ──────────────────────────────────────────
        _emit("인덱스 업데이트 중...")
        p.update(task, description="인덱스 업데이트 중...")
        title = _meta["title"]
        desc = _extract_first_sentence(overview)
        fs.update_index_entry(wiki_root, page_path, title, desc)

        # ── Step 5: Write entity & concept pages ─────────────────────────
        _emit("관련 엔티티/개념 페이지 작성 중...")
        p.update(task, description="관련 엔티티/개념 페이지 작성 중...")
        for kind, entries in (("entities", entity_entries), ("concepts", concept_entries)):
            for action, s in entries:
                display = _page_display_name(s)
                _emit(f"  {'생성' if action == 'create' else '업데이트'}: {kind}/{display}")
                _write_or_update_page(
                    wiki_root, kind, s, action, source.name, overview, model, schema
                )

        # ── Step 6: Log ───────────────────────────────────────────────────
        today = str(date.today())
        log_entry = f"""## [{today}] ingest | {title}
- Source: raw/{source.name}
- Summary page: sources/{slug}.md
- Overview: {_extract_first_sentence(overview)}
"""
        fs.append_log(wiki_root, log_entry)
        _emit(f"완료: {title}")
        p.update(task, description="완료.", completed=True)

    console.print(f"\n[green]✓[/green] Ingested: [bold]{title}[/bold]")
    console.print(f"  Summary page : wiki/sources/{slug}.md")
    console.print(f"  Log updated  : wiki/log.md")


def _page_display_name(slug: str) -> str:
    """slug → Obsidian 파일명 겸 위키링크 표시 이름 (Title Case)."""
    return slug.replace("-", " ").replace("_", " ").title()


def _plan_related_pages(
    wiki_root: Path,
    overview: str,
    model: str | None,
    schema: str,
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """overview에서 entity/concept 페이지 계획을 추출한다.

    반환: (entity_entries, concept_entries) — 각각 [(action, slug), ...]
    source 페이지 작성 전에 호출해 display_name을 확정한다.
    """
    existing = fs.list_pages(wiki_root)
    existing_display = [p.stem for p in existing]

    prompt = f"""
{schema}

Based on this source overview, list:
1. Entity pages that should be created or updated (people, models, datasets, institutions)
2. Concept pages that should be created or updated

For each, specify CREATE or UPDATE and a slug (lowercase-hyphenated English, no special chars).
The slug will become the page title in Title Case (e.g. slug "agentic-ai" → title "Agentic Ai").
Existing wiki pages (stems): {existing_display}

Overview:
{overview}

Respond ONLY in this exact format (no extra text):
ENTITIES:
- create: transformer-architecture
- update: bert-model

CONCEPTS:
- create: self-attention
- update: language-modeling
"""
    page_plan = llm.call(prompt, system=_SYSTEM, model=model)

    entity_entries = _extract_section(page_plan, "ENTITIES")
    concept_entries = _extract_section(page_plan, "CONCEPTS")

    if not entity_entries and not concept_entries:
        logger.warning("entity/concept 계획 파싱 결과 없음 — LLM 출력 형식 확인 필요")

    return entity_entries, concept_entries


def _write_or_update_page(
    wiki_root: Path, kind: str, slug: str, action: str,
    source_name: str, overview: str, model: str | None, schema: str
) -> None:
    display_name = _page_display_name(slug)
    page_path = fs.wiki_dir(wiki_root) / kind / f"{display_name}.md"

    if action == "create" and page_path.exists():
        action = "update"

    existing_meta: dict = {}
    existing_body = ""
    if page_path.exists():
        existing_meta, existing_body = fs.read_page(page_path)

    legacy_path = fs.wiki_dir(wiki_root) / kind / f"{slug}.md"
    if not page_path.exists() and legacy_path.exists():
        existing_meta, existing_body = fs.read_page(legacy_path)
        action = "update"

    evidence = _extract_relevant_evidence(overview, display_name)

    if action == "create":
        prompt = f"""
{schema}

Create a new wiki page for: {display_name}
Kind: {kind[:-1]}

Evidence from source "{source_name}":
{evidence}

Output a markdown file with YAML frontmatter (bare --- block, NOT inside a code fence).
The title field MUST be exactly "{display_name}" — do not change it.
---
title: "{display_name}"
type: {kind[:-1]}
tags: [tag1, tag2]
sources: ["{source_name}"]
---

# {display_name}

<content using [[Exact Page Title]] wikilinks, ⚠️ for uncertainties>
"""
        page_content = llm.call(prompt, system=_SYSTEM, model=model)
        _meta, _body = _parse_llm_page(page_content)
        _meta["title"] = display_name
        fs.write_page(page_path, _meta, _body)
    else:
        # 증분 업데이트: 관련 evidence만 전달, 새 내용만 출력 요청
        delta_prompt = f"""
{schema}

New evidence about "{display_name}" from source "{source_name}":
{evidence}

Current wiki page body (do NOT rewrite — output only additions):
{existing_body}

Output ONLY new content to add to this page using this format:

SECTION: <Exact Section Title>
<new bullets or sentences to append to that section>

NEW_SECTION: <New Section Title>
<full content for a new section>

Use [[Exact Page Title]] wikilinks, ⚠️ for uncertainties.
If there is nothing new to add, output exactly: NO_UPDATE
"""
        delta = llm.call(delta_prompt, system=_SYSTEM, model=model)

        if delta.strip() == "NO_UPDATE":
            return

        new_body = _apply_delta(existing_body, delta)
        sources = list(existing_meta.get("sources") or [])
        if source_name not in sources:
            sources.append(source_name)
        existing_meta["sources"] = sources
        existing_meta["title"] = display_name
        fs.write_page(page_path, existing_meta, new_body)

    fs.update_index_entry(wiki_root, page_path, display_name, f"Updated from {source_name}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_schema(root: Path) -> str:
    agents = root / "AGENTS.md"
    return agents.read_text(encoding="utf-8") if agents.exists() else ""


def _parse_llm_page(text: str) -> tuple[dict, str]:
    """LLM 출력에서 YAML frontmatter dict와 본문 str을 추출.

    지원 형식:
      A) ---\\nfrontmatter\\n---\\nbody
      B) ```yaml\\n---\\nfrontmatter\\n---\\nbody\\n```   (본문이 코드 블록 안)
      C) ```yaml\\n---\\nfrontmatter\\n---\\n```\\nbody   (본문이 코드 블록 밖)
    """
    import re
    import yaml

    text = text.strip()

    # ── 형식 B / C: ```yaml 블록으로 시작 ─────────────────────────────────────
    m = re.match(r'^```(?:yaml)?\s*\n(.*?)```(.*?)$', text, re.DOTALL)
    if m:
        block_inner = m.group(1)
        after_block = m.group(2).strip()

        # 블록 내부에서 ---...--- 추출
        if block_inner.startswith("---"):
            parts = block_inner.split("---", 2)
            fm_text = parts[1] if len(parts) >= 2 else ""
            body_in_block = parts[2].strip() if len(parts) >= 3 else ""
        else:
            fm_text = ""
            body_in_block = block_inner.strip()

        try:
            metadata = yaml.safe_load(fm_text) or {}
        except Exception:
            metadata = {}

        # 형식 B: 본문이 블록 내부에 있음
        # 형식 C: 본문이 블록 밖에 있음
        body = body_in_block or after_block
        return metadata, body

    # ── 형식 A: ---로 시작 ────────────────────────────────────────────────────
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                metadata = yaml.safe_load(parts[1]) or {}
            except Exception:
                metadata = {}
            return metadata, parts[2].strip()

    # ── 형식 없음: 그대로 반환 ────────────────────────────────────────────────
    return {}, text


def _extract_title(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("title:"):
            return line.split(":", 1)[1].strip().strip('"')
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _extract_first_sentence(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith(("#", "-", "|", ">")):
            return line[:120]
    return text[:120]


def _extract_relevant_evidence(overview: str, display_name: str) -> str:
    """overview에서 display_name 관련 줄과 전후 문맥만 추출. 관련 내용이 적으면 전체 반환."""
    target = display_name.lower()
    lines = overview.splitlines()
    included: set[int] = set()

    for i, line in enumerate(lines):
        if target in line.lower():
            for j in range(max(0, i - 1), min(len(lines), i + 3)):
                included.add(j)

    if not included:
        return overview

    filtered = "\n".join(lines[j] for j in sorted(included)).strip()
    return filtered if len(filtered) > 80 else overview


def _apply_delta(body: str, delta: str) -> str:
    """SECTION/NEW_SECTION 지시를 파싱해 기존 body에 병합."""
    import re

    result = body
    lines = delta.splitlines()
    i = 0

    while i < len(lines):
        line = lines[i]

        if line.startswith("SECTION:"):
            section_title = line[8:].strip()
            content_lines: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].startswith(("SECTION:", "NEW_SECTION:")):
                content_lines.append(lines[i])
                i += 1
            content = "\n".join(content_lines).strip()
            if content:
                pattern = rf'(## {re.escape(section_title)}[^\n]*\n)(.*?)(?=\n## |\Z)'
                def _appender(m: re.Match, _c: str = content) -> str:
                    return m.group(1) + m.group(2).rstrip() + "\n" + _c + "\n"
                new_result = re.sub(pattern, _appender, result, flags=re.DOTALL)
                if new_result != result:
                    result = new_result
                else:
                    result = result.rstrip() + f"\n\n## {section_title}\n{content}"

        elif line.startswith("NEW_SECTION:"):
            section_title = line[12:].strip()
            content_lines = []
            i += 1
            while i < len(lines) and not lines[i].startswith(("SECTION:", "NEW_SECTION:")):
                content_lines.append(lines[i])
                i += 1
            content = "\n".join(content_lines).strip()
            if content:
                result = result.rstrip() + f"\n\n## {section_title}\n{content}"

        else:
            i += 1

    return result.strip()


def _extract_section(text: str, header: str) -> list[tuple[str, str]]:
    """ENTITIES: / CONCEPTS: 섹션에서 action:slug 쌍을 파싱.
    대소문자·콜론 여부에 관계없이 매칭."""
    results = []
    in_section = False
    for line in text.splitlines():
        # 헤더 인식: 대소문자 무시, 콜론 제거 후 비교
        normalized = line.strip().rstrip(":").upper()
        if normalized == header.upper():
            in_section = True
            continue
        if in_section and line.strip().startswith("-"):
            parts = line.strip("- ").split(":", 1)
            if len(parts) == 2:
                action = parts[0].strip().lower()
                slug = parts[1].strip().lower().replace(" ", "-")
                results.append((action, slug))
        elif in_section and line.strip() and not line.strip().startswith("-"):
            # 다음 섹션 시작 → 종료
            break
    return results
