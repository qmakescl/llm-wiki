# Ingest 완료 기준 재정의 및 재시도 기능

날짜: 2026-05-16

## 배경

LLM 연결이 불안정할 때 ingest 첫 단계 또는 중간 단계에서 timeout이 발생할 수 있다.

예:

```text
소스 파일 읽는 중...
✗ 오류: litellm.APIConnectionError: OllamaException - litellm.Timeout: Connection timed out after 1200.0 seconds.
```

기존 문서 목록은 `wiki/sources/{slug}.md` 파일 존재 여부만 보고 완료 상태를 표시했다. 이 때문에 source page만 생성된 뒤 entity/concept 생성, log 기록, source registry 기록 전에 실패하면 문서 목록에서는 완료처럼 보일 수 있었다.

## 변경 전

완료 판정이 위치별로 달랐다.

| 위치 | 기존 기준 |
|---|---|
| 문서 목록 | `wiki/sources/{slug}.md` 파일 존재 |
| 작업 패널 | 메모리 `IngestJob.status` (`done` / `failed`) |
| 중복 검사 | source page 파일 존재 또는 hash duplicate |
| source registry | ingest 맨 끝의 `mark_ingested()` 호출 여부 |

이 구조에서는 부분 실패한 문서를 다시 ingest하기 어렵다. 같은 slug의 source page 파일이 이미 있으면 `run_ingest()` 시작 단계에서 `DuplicateSourceError`가 발생했기 때문이다.

## 변경 후

완료 기준을 source registry 중심으로 재정의했다.

완료 조건:

```text
sources.jsonl에 해당 source record가 있고
ingested_at 이 채워져 있고
summary_page 가 채워져 있고
그 summary_page 파일이 실제로 존재함
```

source page 파일만 존재하는 상태는 완료가 아니라 `partial` 상태로 취급한다.

## 구현 내용

### 1. Source registry 완료 판정 helper 추가

`wiki_cli/source_registry.py`에 다음 helper를 추가했다.

| 함수 | 역할 |
|---|---|
| `find_record_for_source()` | source path에 해당하는 registry row 조회 |
| `record_is_complete()` | `ingested_at`, `summary_page`, summary 파일 존재 여부로 완료 판정 |
| `source_is_ingested()` | 특정 source가 완전히 ingest되었는지 확인 |

`find_ingested_duplicate()`도 `wiki_root`를 받을 수 있게 확장해, hash duplicate 판정 시 실제 summary page가 남아 있는 완료 기록만 중복으로 본다.

### 2. `run_ingest()` 중복 검사 변경

`wiki_cli/ops/ingest.py`의 시작 중복 검사를 변경했다.

- `data_root`가 있는 웹/도메인 기반 ingest에서는 `source_is_ingested()`가 참일 때만 중복으로 차단한다.
- 같은 slug의 source page가 이미 있어도 registry 완료 기록이 없으면 재시도를 허용한다.
- CLI처럼 `data_root`가 없는 호출은 기존처럼 source page 파일 존재 기준으로 중복 차단한다.

### 3. 문서 목록 완료 표시 변경

`wiki_web/routers/documents.py`의 `_raw_files()`와 업로드 응답에서 완료 상태를 registry 기준으로 계산하도록 변경했다.

- `ingested`: registry 완료 기록이 있고 summary page가 존재함
- `partial`: source page 파일은 있지만 registry 완료 기준은 만족하지 못함

### 4. 미완료 문서 재 Ingest UI 추가

`wiki_web/templates/partials/file_row.html`에서 부분 실패 문서는 다음처럼 표시한다.

- `미완료` 배지
- `다시 Ingest` 버튼

완전히 ingest되지 않은 문서는 다시 버튼을 눌러 ingest를 재시도할 수 있다.

## 수정 파일

| 파일 | 변경 내용 |
|---|---|
| `wiki_cli/source_registry.py` | registry 기반 완료 판정 helper 추가, duplicate 판정 강화 |
| `wiki_cli/ops/ingest.py` | 완료된 source만 중복 차단하고 부분 실패 source는 재시도 허용 |
| `wiki_web/routers/documents.py` | 문서 목록 완료/부분완료 상태를 registry 기준으로 계산 |
| `wiki_web/templates/partials/file_row.html` | 부분완료 문서에 `미완료` 배지와 `다시 Ingest` 버튼 표시 |
| `tests/test_source_registry.py` | 완료 판정 및 재시도 허용 테스트 추가 |
| `tests/test_documents_router.py` | 문서 목록이 source page 존재만으로 완료 처리하지 않는지 테스트 |
| `docs/fix/2026-05-16-ingest-completion.md` | 본 변경 기록 추가 |

## 검증

관련 테스트:

```bash
uv run pytest tests/test_source_registry.py tests/test_documents_router.py tests/test_structured_ingest.py tests/test_progress.py
```

결과:

```text
15 passed
```

전체 테스트:

```bash
uv run pytest
```

결과:

```text
66 passed
```

## 남은 개선 제안

- 실패한 ingest job에서 어느 단계까지 파일이 생성되었는지 UI에 더 자세히 표시
- 부분 실패 상태에서 재시도 전 기존 partial source page를 자동 백업하거나 overwrite 안내 추가
- LLM timeout 발생 시 `소스 파일 읽는 중...` 대신 실제 단계가 LLM 분석 중임을 명확히 표시

## 추가 변경: Obsidian tag frontmatter 정규화

Markdown 문서를 생성·저장할 때 LLM이 `tags` 값에 공백이 포함된 라벨을 만들면 Obsidian tag로 제대로 쓰기 어렵다.

`obsidian-markdown` 스킬의 frontmatter/tag 규칙을 기준으로 저장 계층에서 다음 정책을 강제했다.

- `tags`는 항상 YAML list로 저장한다.
- `Machine Learning`처럼 공백이 있는 tag는 `machine-learning`으로 변환한다.
- `#LLM #RAG`처럼 inline tag 형태로 섞인 값은 개별 tag로 분리한다.
- `2026 Research`처럼 숫자로 시작하는 tag는 `tag-2026-research`로 보정한다.
- 중복 tag는 제거하고 입력 순서는 유지한다.

### 추가 수정 파일

| 파일 | 변경 내용 |
|---|---|
| `wiki_cli/fs.py` | `write_page()` 저장 전 frontmatter 정규화 추가, Obsidian 호환 tag sanitizer 추가 |
| `wiki_cli/ops/ingest.py` | source/entity/concept 생성 프롬프트의 tag 예시와 규칙을 Obsidian 호환 형태로 명시 |
| `tests/test_fs.py` | 공백·해시·쉼표·숫자 시작 tag 정규화 회귀 테스트 추가 |
| `docs/fix/2026-05-16-ingest-completion.md` | 본 추가 변경 기록 |

### 추가 검증

```bash
uv run pytest tests/test_fs.py
uv run pytest tests/test_structured_ingest.py
```

결과:

```text
tests/test_fs.py: 14 passed
tests/test_structured_ingest.py: 6 passed
```
