"""Structured ingest extraction helpers.

This module keeps the first source-reading step machine-parseable. When it
works, ingest can skip the separate entity/concept planning LLM call and reuse
page-level evidence directly.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, TypedDict

import yaml

from wiki_cli import fs, llm

logger = logging.getLogger(__name__)


class Evidence(TypedDict, total=False):
    quote: str
    location: str
    confidence: str


class PageBrief(TypedDict, total=False):
    title: str
    slug: str
    action: str
    kind: str
    summary: str
    evidence: list[Evidence]


class StructuredIngestResult(TypedDict, total=False):
    summary: str
    claims: list[dict[str, Any]]
    entities: list[PageBrief]
    concepts: list[PageBrief]
    uncertainties: list[dict[str, Any]]
    contradiction_candidates: list[dict[str, Any]]


def prompt_for_structured_ingest(schema: str, source_name: str) -> str:
    return f"""
{schema}

Read the source document and return ONLY valid JSON. Do not wrap it in a code
fence. Keep evidence short and specific. Prefer stable page titles over slugs.

Required JSON shape:
{{
  "summary": "3 sentence source summary",
  "claims": [
    {{"claim": "specific claim", "evidence": "short quote or paraphrase", "confidence": "high|medium|low"}}
  ],
  "entities": [
    {{"title": "Exact Page Title", "slug": "lowercase-hyphen-slug", "action": "create|update", "summary": "why it matters", "evidence": [{{"quote": "short evidence", "location": "page/section if known", "confidence": "high|medium|low"}}]}}
  ],
  "concepts": [
    {{"title": "Exact Page Title", "slug": "lowercase-hyphen-slug", "action": "create|update", "summary": "why it matters", "evidence": [{{"quote": "short evidence", "location": "page/section if known", "confidence": "high|medium|low"}}]}}
  ],
  "uncertainties": [
    {{"note": "what is uncertain", "evidence": "why"}}
  ],
  "contradiction_candidates": [
    {{"claim": "new claim", "possible_conflict": "older or conflicting claim if apparent"}}
  ]
}}

Source filename: {source_name}
"""


def extract_from_file(
    *,
    schema: str,
    source: Path,
    system: str,
    model: str | None,
    metrics: Any | None = None,
) -> tuple[StructuredIngestResult | None, str]:
    """Return parsed structured result and raw LLM response."""
    prompt = prompt_for_structured_ingest(schema, source.name)
    raw = llm.call_with_file(prompt, source, system=system, model=model, metrics=metrics)
    parsed = parse_structured_result(raw)
    return parsed, raw


def parse_structured_result(text: str) -> StructuredIngestResult | None:
    """Parse JSON/YAML-like structured ingest output."""
    payload = _extract_payload(text)
    if not payload:
        return None

    data: Any
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        try:
            data = yaml.safe_load(payload)
        except yaml.YAMLError:
            return None

    if not isinstance(data, dict):
        return None

    result: StructuredIngestResult = {
        "summary": str(data.get("summary") or "").strip(),
        "claims": _list_of_dicts(data.get("claims")),
        "entities": _normalize_page_briefs(data.get("entities"), "entity"),
        "concepts": _normalize_page_briefs(data.get("concepts"), "concept"),
        "uncertainties": _list_of_dicts(data.get("uncertainties")),
        "contradiction_candidates": _list_of_dicts(data.get("contradiction_candidates")),
    }
    if not result["summary"] and not result["entities"] and not result["concepts"]:
        return None
    return result


def entries_from_result(
    result: StructuredIngestResult,
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    return (
        [(brief.get("action", "create"), brief["slug"]) for brief in result.get("entities", []) if brief.get("slug")],
        [(brief.get("action", "create"), brief["slug"]) for brief in result.get("concepts", []) if brief.get("slug")],
    )


def brief_for_slug(result: StructuredIngestResult, kind: str, slug: str) -> PageBrief | None:
    key = "entities" if kind == "entities" else "concepts"
    for brief in result.get(key, []):
        if brief.get("slug") == slug:
            return brief
    return None


def evidence_text_for_slug(result: StructuredIngestResult, kind: str, slug: str) -> str:
    brief = brief_for_slug(result, kind, slug)
    if not brief:
        return ""
    lines = []
    if summary := brief.get("summary"):
        lines.append(summary)
    for ev in brief.get("evidence", []):
        quote = ev.get("quote", "").strip()
        location = ev.get("location", "").strip()
        confidence = ev.get("confidence", "").strip()
        if quote:
            suffix = " ".join(part for part in [f"location: {location}" if location else "", f"confidence: {confidence}" if confidence else ""] if part)
            lines.append(f"- {quote}" + (f" ({suffix})" if suffix else ""))
    return "\n".join(lines).strip()


def render_source_page(
    result: StructuredIngestResult,
    *,
    source_name: str,
    fallback_title: str,
) -> tuple[dict, str]:
    title = fallback_title
    metadata = {
        "title": title,
        "type": "source",
        "tags": [],
        "sources": [source_name],
    }
    lines = [f"# {title}", ""]
    if summary := result.get("summary"):
        lines += ["## Summary", summary, ""]
    claims = result.get("claims", [])
    if claims:
        lines += ["## Key contributions"]
        for item in claims:
            claim = str(item.get("claim") or item.get("text") or "").strip()
            evidence = str(item.get("evidence") or "").strip()
            if claim and evidence:
                lines.append(f"- {claim} — {evidence}")
            elif claim:
                lines.append(f"- {claim}")
        lines.append("")
    if result.get("entities"):
        lines += ["## Entities mentioned"]
        for brief in result.get("entities", []):
            title = brief.get("title") or brief.get("slug") or "Untitled"
            summary = brief.get("summary") or ""
            lines.append(f"- [[{title}]]" + (f" — {summary}" if summary else ""))
        lines.append("")
    if result.get("concepts"):
        lines += ["## Key concepts"]
        for brief in result.get("concepts", []):
            title = brief.get("title") or brief.get("slug") or "Untitled"
            summary = brief.get("summary") or ""
            lines.append(f"- [[{title}]]" + (f" — {summary}" if summary else ""))
        lines.append("")
    if result.get("uncertainties"):
        lines += ["## Notes & uncertainties"]
        for item in result.get("uncertainties", []):
            note = str(item.get("note") or item.get("claim") or "").strip()
            if note:
                lines.append(f"- ⚠️ {note}")
        lines.append("")
    return metadata, "\n".join(lines).strip()


def to_overview(result: StructuredIngestResult) -> str:
    """Render structured data into compact markdown for existing prompts."""
    lines: list[str] = []
    if summary := result.get("summary"):
        lines += ["## Summary", summary, ""]

    claims = result.get("claims", [])
    if claims:
        lines += ["## Key claims"]
        for item in claims:
            claim = str(item.get("claim") or item.get("text") or "").strip()
            evidence = str(item.get("evidence") or "").strip()
            confidence = str(item.get("confidence") or "").strip()
            suffix = f" (confidence: {confidence})" if confidence else ""
            if evidence:
                lines.append(f"- {claim}{suffix} — Evidence: {evidence}")
            elif claim:
                lines.append(f"- {claim}{suffix}")
        lines.append("")

    for label, key in (("Entities", "entities"), ("Concepts", "concepts")):
        briefs = result.get(key, [])
        if not briefs:
            continue
        lines += [f"## {label}"]
        for brief in briefs:
            title = brief.get("title") or brief.get("slug") or "Untitled"
            summary = brief.get("summary") or ""
            lines.append(f"- {title}: {summary}".rstrip())
            for ev in brief.get("evidence", [])[:3]:
                quote = ev.get("quote", "").strip()
                if quote:
                    lines.append(f"  - Evidence: {quote}")
        lines.append("")

    uncertainties = result.get("uncertainties", [])
    if uncertainties:
        lines += ["## Notes & uncertainties"]
        for item in uncertainties:
            note = str(item.get("note") or item.get("claim") or item).strip()
            if note:
                lines.append(f"- ⚠️ {note}")
        lines.append("")

    return "\n".join(lines).strip()


def _extract_payload(text: str) -> str:
    text = text.strip()
    fence = re.match(r"^```(?:json|yaml|yml)?\s*(.*?)```$", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    if text.startswith("{") and text.endswith("}"):
        return text
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return text


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _normalize_page_briefs(value: Any, kind: str) -> list[PageBrief]:
    briefs: list[PageBrief] = []
    for item in _list_of_dicts(value):
        title = str(item.get("title") or item.get("name") or "").strip()
        slug = str(item.get("slug") or "").strip()
        if not slug and title:
            slug = fs.file_slug(title)
        if not title and slug:
            title = slug.replace("-", " ").replace("_", " ").title()
        if not title and not slug:
            continue
        action = str(item.get("action") or "create").strip().lower()
        if action not in {"create", "update"}:
            action = "create"
        briefs.append({
            "title": title,
            "slug": fs.file_slug(slug or title),
            "action": action,
            "kind": kind,
            "summary": str(item.get("summary") or "").strip(),
            "evidence": _normalize_evidence(item.get("evidence")),
        })
    return briefs


def _normalize_evidence(value: Any) -> list[Evidence]:
    if not isinstance(value, list):
        return []
    evidence: list[Evidence] = []
    for item in value:
        if isinstance(item, str):
            evidence.append({"quote": item})
        elif isinstance(item, dict):
            evidence.append({
                "quote": str(item.get("quote") or item.get("evidence") or "").strip(),
                "location": str(item.get("location") or "").strip(),
                "confidence": str(item.get("confidence") or "").strip(),
            })
    return evidence
