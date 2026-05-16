"""Query operation — answer a question from the wiki."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.progress import Progress, SpinnerColumn, TextColumn

from wiki_cli import fs, language, llm, search, search_index
from wiki_cli.metrics import Metrics
from wiki_cli.obsidian_sync import trigger_sync

console = Console()

_SYSTEM = """You are a precise research assistant with access to a personal wiki.
Answer questions using only information from the provided wiki pages.
Cite sources using [[PageName]] links. Be concise but thorough.
If the wiki doesn't contain enough information, say so clearly."""

def run_query(
    wiki_root: Path,
    question: str,
    model: str | None,
    save: bool,
    progress_callback: Callable[[str], None] | None = None,
    metrics: Metrics | None = None,
) -> str:
    """위키에서 질문에 답변합니다. 답변 문자열을 반환합니다."""
    schema = _load_schema(wiki_root)

    def _emit(msg: str) -> None:
        if progress_callback:
            progress_callback(msg)

    with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console,
                  disable=progress_callback is not None) as p:
        task = p.add_task("위키 검색 중...", total=None)

        # ── Step 1: Read index for overview ──────────────────────────────
        _emit("위키 인덱스 읽는 중...")
        p.update(task, description="위키 인덱스 읽는 중...")
        index_content = search.read_index(fs.wiki_dir(wiki_root))

        # ── Step 2: Find relevant pages ───────────────────────────────────
        _emit("관련 페이지 검색 중...")
        p.update(task, description="관련 페이지 검색 중...")
        results = search.search(question, fs.wiki_dir(wiki_root), top_k=6, metrics=metrics)
        context_pages = _build_context(results)
        if metrics:
            metrics.record("query.context_chars", len(context_pages))
        _emit(f"관련 페이지 {len(results)}개 발견")
        p.update(task, description=f"관련 페이지 {len(results)}개 읽는 중...")

        # ── Step 3: Generate answer ───────────────────────────────────────
        _emit("LLM 답변 생성 중...")
        p.update(task, description="답변 생성 중...")
        prompt = f"""
{schema}

{language.language_policy(answer=True)}

Wiki index overview:
{index_content[:2000]}

Relevant wiki pages:
{context_pages}

Question: {question}

Provide a comprehensive answer with citations to wiki pages using [[PageName]] syntax.
If multiple pages contradict each other, note the contradiction.
"""
        if metrics:
            with metrics.timer("query.llm_generation"):
                answer = llm.call(prompt, system=_SYSTEM, model=model, max_tokens=2048)
            metrics.count("query.llm_calls")
        else:
            answer = llm.call(prompt, system=_SYSTEM, model=model, max_tokens=2048)
        p.update(task, description="완료.", completed=True)
        _emit("답변 생성 완료")

    # ── CLI 전용: 터미널에 출력 ───────────────────────────────────────────────
    if not progress_callback:
        console.print()
        console.print(Markdown(answer))

        # ── Step 4: Optionally save to synthesis/ ────────────────────────
        if save or _is_notable(answer):
            if not save:
                save = console.input("\n[dim]답변을 synthesis/에 저장할까요? [y/N][/dim] ").lower() == "y"

    if save:
        _save_synthesis(wiki_root, question, answer)
        trigger_sync(wiki_root)

    # ── Log ───────────────────────────────────────────────────────────────
    refs = [str(r.path.relative_to(wiki_root)) for r in results]
    log_entry = f"""## [{date.today()}] query | {question[:60]}
- References: {", ".join(refs[:3])}
{"- Saved: wiki/synthesis/" + _question_to_slug(question) + ".md" if save else ""}
"""
    fs.append_log(wiki_root, log_entry)

    return answer


def _save_synthesis(wiki_root: Path, question: str, answer: str) -> Path:
    """답변을 synthesis/ 에 저장하고 페이지 경로를 반환.

    일반 페이지와 동일하게 fs.write_page()를 사용해 title/aliases/created/updated
    정책을 통일한다. 본문은 `# question` + 답변 본문 구조를 유지.
    """
    slug = _question_to_slug(question)
    page_path = fs.wiki_dir(wiki_root) / "synthesis" / f"{slug}.md"
    metadata = {
        "title": question[:80],
        "type": "synthesis",
        "tags": [],
    }
    body = f"# {question}\n\n{answer}\n"
    fs.write_page(page_path, metadata, body)
    fs.update_index_entry(wiki_root, page_path, question[:60], "Synthesis answer")
    console.print(f"\n[green]✓[/green] Saved to synthesis/{slug}.md")
    return page_path


def _build_context(results: list[search.SearchResult]) -> str:
    parts = []
    for r in results:
        try:
            if r.metadata and r.metadata.get("kind") == "vector_chunk":
                heading = str(r.metadata.get("heading") or "").strip()
                chunk_text = str(r.metadata.get("chunk_text") or r.snippet)
                heading_prefix = f"## {heading}\n" if heading else ""
                parts.append(
                    f"=== {r.path.name} (score: {r.score:.2f}) ===\n"
                    f"{heading_prefix}{chunk_text[:3000]}"
                )
                continue
            wiki_dir = r.path.parent.parent if r.path.parent.name in {"sources", "entities", "concepts", "synthesis"} else r.path.parent
            payload, _ = search_index.refresh_index(wiki_dir)
            entry = None
            for candidate in payload.get("entries", {}).values():
                if candidate.get("path", "").endswith(r.path.name):
                    entry = candidate
                    break
            if entry:
                body = _best_chunk_text(entry, r.snippet)
            else:
                body = r.path.read_text(encoding="utf-8")[:3000]
            parts.append(f"=== {r.path.name} (score: {r.score:.2f}) ===\n{body}")
        except OSError:
            pass
    return "\n\n".join(parts)


def _best_chunk_text(entry: dict, snippet: str) -> str:
    chunks = entry.get("chunks", [])
    if not chunks:
        return entry.get("plain_text_preview", "")
    if snippet:
        for chunk in chunks:
            if snippet[:40].lower() in chunk.get("text", "").lower():
                return f"## {chunk.get('heading', '')}\n{chunk.get('text', '')}"[:3000]
    chunk = max(chunks, key=lambda c: len(c.get("text", "")))
    return f"## {chunk.get('heading', '')}\n{chunk.get('text', '')}"[:3000]


def _is_notable(answer: str) -> bool:
    """길고 다단락인 답변은 저장할 가치가 있다고 판단."""
    return len(answer) > 800 and answer.count("\n\n") >= 2


def _question_to_slug(question: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", question.lower().strip())
    return slug[:60].strip("-")


def _load_schema(root: Path) -> str:
    agents = root / "AGENTS.md"
    return agents.read_text(encoding="utf-8") if agents.exists() else ""
