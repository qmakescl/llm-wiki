"""Language policy helpers for LLM-authored wiki content."""

from __future__ import annotations

import os

OUTPUT_LANGUAGE_OPTIONS = {
    "ko": "Korean",
    "en": "English",
    "source": "the source document's original language",
}


def output_language() -> str:
    value = os.environ.get("WIKI_OUTPUT_LANGUAGE", "ko").strip().lower()
    return value if value in OUTPUT_LANGUAGE_OPTIONS else "ko"


def heading_original_language() -> bool:
    return os.environ.get("WIKI_HEADING_ORIGINAL_LANGUAGE", "on").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def output_language_label() -> str:
    return OUTPUT_LANGUAGE_OPTIONS[output_language()]


def heading_label(korean: str, english: str) -> str:
    if heading_original_language():
        return english
    if output_language() == "ko":
        return korean
    return english


def language_policy(*, answer: bool = False) -> str:
    target = output_language_label()
    if output_language() == "source":
        write_instruction = (
            "Write human-facing prose in the source document's original language."
        )
    elif answer:
        write_instruction = f"Answer in {target}."
    else:
        write_instruction = f"Write human-facing body prose in {target}."

    if heading_original_language():
        heading_instruction = (
            "Write Markdown headings in the source/original language; do not localize headings "
            "just because the body prose uses a different output language."
        )
    else:
        heading_instruction = f"Write Markdown headings in {target}, matching the body language."

    return f"""Language policy:
- {write_instruction}
- {heading_instruction}
- Keep YAML frontmatter, page titles, filenames, tags, sources, aliases, and wikilink targets in English or the source's original language.
- Keep technical terms, model names, paper titles, organization names, product names, and established concept names in English/original form inside prose.
- Do not translate [[wikilink targets]]; they must match the target page title exactly."""
