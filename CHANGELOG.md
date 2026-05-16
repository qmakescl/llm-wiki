# Changelog

## v0.3.1 - 2026-05-16

### Added

- Added configurable Markdown output language for generated wiki pages and query answers.
- Added `/settings` and `/admin` controls for output language: Korean, English, or source language.
- Added `Heading은 원문 언어 사용` option so Markdown headings can remain in the source/original language even when body prose uses a different language.
- Added shared `wiki_cli.language` policy helper so CLI and Web flows use the same language policy.
- Added regression tests for language policy, query prompts, structured ingest prompts, and settings environment propagation.
- Added `CHANGELOG.md` for release history.

### Changed

- Updated ingest, structured ingest, and query prompts to use the configured language policy instead of a fixed Korean policy.
- Kept page titles, filenames, tags, sources, aliases, and `[[wikilink target]]` values in English/original language for Obsidian link stability.
- Updated README for v0.3.1 and documented output language settings.

### Fixed

- Fixed raw file list progress UI staying on `추출 진행 중...` after ingest completion.
- SSE `done` events now replace the per-file progress control with a complete badge, or with a retry control on failure.
- Fixed LLM connection test success message showing a model resolved from the previous environment instead of the temporary form settings.
- Changed `Heading은 원문 언어 사용` to be enabled by default.

### Verified

```bash
uv run pytest
```

Result:

```text
77 passed
```

## v0.3 - 2026-05-15

### Added

- Added Obsidian plugin sync support.
- Added multi-domain web UI and runtime settings improvements.
- Added structured ingest, source registry, extraction cache, and vector search foundations.

### Changed

- Improved ingest reliability and source provenance tracking.

### Verified

- Main regression test suite passed before release.
