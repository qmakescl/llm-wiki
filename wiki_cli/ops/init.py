"""Init operation — scaffold a new wiki directory."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from rich.console import Console

console = Console()


def run_init(wiki_root: Path, data_root: Path, domain: str) -> None:
    """wiki_root: 마크다운 콘텐츠 (Obsidian 연결), data_root: 원본 파일(raw/)."""
    wiki_root.mkdir(parents=True, exist_ok=True)
    data_root.mkdir(parents=True, exist_ok=True)

    _create_agents_md(wiki_root, domain)
    _create_directory_structure(wiki_root, data_root)
    _create_index(wiki_root)
    _create_log(wiki_root)

    console.print(f"\n[green]✓ Wiki initialised[/green]")
    console.print(f"  wiki : {wiki_root}")
    console.print(f"  data : {data_root}\n")
    console.print("Next steps:")
    console.print("  1. Edit [bold]AGENTS.md[/bold] — fill in your domain details")
    console.print("  2. Drop a source file into [bold]raw/[/bold]")
    console.print("  3. Run [bold]wiki ingest raw/your-paper.pdf[/bold]")
    console.print("\nOptional — set your LLM:")
    console.print("  export WIKI_MODEL=claude-sonnet-4-20250514   # Anthropic")
    console.print("  export WIKI_MODEL=gpt-4o                     # OpenAI")
    console.print("  export WIKI_MODEL=ollama/llama3              # local")


def _create_agents_md(wiki_root: Path, domain: str) -> None:
    path = wiki_root / "AGENTS.md"
    if path.exists():
        console.print("[yellow]AGENTS.md already exists, skipping.[/yellow]")
        return

    today = str(date.today())
    path.write_text(f"""# LLM Wiki — Personal Research Knowledge Base

## Overview

This is a personal research wiki maintained by an LLM agent.

**Domain**: {domain}
**Owner**: [your name]
**Started**: {today}

---

## Directory structure

```
{{workspace_root}}/
├── wiki/{{domain}}/       ← 이 폴더 (Obsidian Vault로 연결)
│   ├── AGENTS.md          ← 에이전트 헌법 (이 파일)
│   ├── index.md           ← 전체 페이지 목록
│   ├── log.md             ← 작업 타임라인
│   ├── sources/           ← 소스 문서별 요약 페이지
│   ├── entities/          ← 인물, 모델, 데이터셋, 기관
│   ├── concepts/          ← 주제 심층 분석
│   └── synthesis/         ← 질문 답변 저장
└── data/{{domain}}/       ← 운영 데이터 (Obsidian 외부)
    └── raw/               ← 원본 소스 파일 (읽기 전용)
        ├── papers/
        ├── articles/
        └── assets/
```

---

## Page format

All wiki pages begin with YAML frontmatter:

```yaml
---
title: Page title
type: entity | concept | source | synthesis
tags: [tag1, tag2]
sources: [source-filename.pdf]
created: YYYY-MM-DD
updated: YYYY-MM-DD
---
```

- Internal links: `[[PageName]]`
- Source references: `[text](../raw/papers/file.pdf)`
- Uncertainty: `> ⚠️ Note: ...`
- Unverified: `<!-- TODO: verify -->`

---

## Operations

### Ingest

Trigger: `wiki ingest raw/papers/paper.pdf`

1. Read source → discuss key takeaways
2. Write `wiki/sources/<slug>.md`
3. Update `wiki/index.md`
4. Update/create relevant entity pages
5. Update/create relevant concept pages
6. Flag contradictions with ⚠️
7. Append to `wiki/log.md`

### Query

Trigger: `wiki query "your question here"`

1. Read `wiki/index.md` for overview
2. Search for relevant pages
3. Synthesise answer with [[citations]]
4. Optionally save to `wiki/synthesis/`
5. Append to `wiki/log.md`

### Lint

Trigger: `wiki lint`

Checks: contradictions · orphan pages · TODO markers · stale content · missing links

---

## Critical rules

1. **raw/ is read-only.** Never modify source files.
2. **log.md is append-only.** Never overwrite.
3. **One source at a time.** Batch ingest degrades quality.
4. **Save good answers.** Use `wiki query "..." --save`.
5. **Cite everything.** No unsourced claims.
""", encoding="utf-8")


def _create_directory_structure(wiki_root: Path, data_root: Path) -> None:
    for subdir in ["entities", "concepts", "sources", "synthesis"]:
        (wiki_root / subdir).mkdir(parents=True, exist_ok=True)
        (wiki_root / subdir / ".gitkeep").touch()
    for subdir in ["raw/papers", "raw/articles", "raw/assets"]:
        (data_root / subdir).mkdir(parents=True, exist_ok=True)
        (data_root / subdir / ".gitkeep").touch()


def _create_index(target: Path) -> None:
    idx = target / "index.md"
    if idx.exists():
        return
    today = str(date.today())
    idx.write_text(f"""# Wiki index
Last updated: {today} | Pages: 0 | Sources: 0

## Sources
| Page | Description |
|------|-------------|

## Entities
| Page | Description |
|------|-------------|

## Concepts
| Page | Description |
|------|-------------|

## Synthesis
| Page | Description |
|------|-------------|
""", encoding="utf-8")


def _create_log(target: Path) -> None:
    log = target / "log.md"
    if log.exists():
        return
    today = str(date.today())
    log.write_text(f"""# Wiki log

## [{today}] init | Wiki created
- Domain: initialised
""", encoding="utf-8")


