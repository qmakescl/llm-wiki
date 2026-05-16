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

## 추가 변경: 본문 한국어 작성 정책

wiki 문서의 link 안정성과 Obsidian 호환성을 위해 title, filename, tag, source, alias, wikilink target은 영어 또는 원문을 유지하되, 사람이 읽는 본문은 한국어로 작성하도록 LLM 프롬프트 정책을 추가했다.

정책:

- YAML frontmatter, page title, filename, tag, source, alias는 영어/원문 유지
- `[[wikilink target]]`은 대상 page title과 정확히 일치해야 하므로 번역하지 않음
- 본문 설명, 요약, bullet, query 답변은 한국어로 작성
- technical term, model name, paper title, organization name, product name, established concept name은 한국어 문장 안에서도 영어/원문 유지

### 추가 수정 파일

| 파일 | 변경 내용 |
|---|---|
| `wiki_cli/ops/ingest.py` | source/entity/concept 생성 및 update 프롬프트에 한국어 본문 작성 정책 추가 |
| `wiki_cli/structured_ingest.py` | 구조화 ingest JSON 설명 필드는 한국어, title/slug는 영어/원문 유지하도록 지시하고 source page heading 일부 한국어화 |
| `wiki_cli/ops/query.py` | query 답변 프롬프트에 한국어 답변 및 wikilink 원문 유지 정책 추가 |
| `tests/test_structured_ingest.py` | 구조화 ingest 프롬프트와 생성 page heading 회귀 테스트 추가 |
| `tests/test_query.py` | query 프롬프트의 한국어 답변 정책 회귀 테스트 추가 |
| `docs/fix/2026-05-16-ingest-completion.md` | 본 추가 변경 기록 |

### 추가 검증

```bash
uv run pytest tests/test_structured_ingest.py tests/test_query.py
uv run pytest tests/test_fs.py tests/test_search_index.py
```

결과:

```text
tests/test_structured_ingest.py tests/test_query.py: 8 passed
tests/test_fs.py tests/test_search_index.py: 18 passed
```

## 추가 변경: 출력 언어 설정 및 Heading 원문 유지 옵션

본문 한국어 작성 정책을 고정 프롬프트에서 설정 기반 정책으로 확장했다.

설정 메뉴에서 다음 값을 선택할 수 있다.

- 출력 언어: `한국어`, `English`, `원문 언어 유지`
- Heading은 원문 언어 사용: 켜면 body 출력 언어와 관계없이 Markdown heading은 source/original language를 따르도록 지시

동작 기준:

- title, filename, tags, sources, aliases, wikilink target은 계속 영어/원문 유지
- body prose, bullet, table, callout, query answer는 출력 언어 설정을 따름
- heading은 기본적으로 출력 언어를 따르지만, `Heading은 원문 언어 사용`을 켜면 원문 언어 유지
- CLI와 Web이 같은 정책을 쓰도록 `WIKI_OUTPUT_LANGUAGE`, `WIKI_HEADING_ORIGINAL_LANGUAGE` 환경변수로 ops 레이어에 전달

### 추가 수정 파일

| 파일 | 변경 내용 |
|---|---|
| `wiki_cli/language.py` | 출력 언어와 heading 정책을 LLM 프롬프트 문구로 변환하는 helper 추가 |
| `wiki_cli/ops/ingest.py` | 고정 한국어 정책 대신 설정 기반 language policy 사용 |
| `wiki_cli/structured_ingest.py` | 구조화 ingest prompt와 deterministic source page heading에 설정 기반 language policy 적용 |
| `wiki_cli/ops/query.py` | query 답변 프롬프트에 설정 기반 language policy 적용 |
| `wiki_web/config.py` | `output_language`, `heading_original_language` 기본값/저장/env 적용 추가 |
| `wiki_web/routers/settings.py` | `/settings` 저장 폼에 출력 언어 설정 반영 |
| `wiki_web/routers/admin.py` | `/admin/settings` 저장 폼에 출력 언어 설정 반영 |
| `wiki_web/templates/settings.html` | 설정 메뉴에 출력 언어 radio와 heading 원문 유지 checkbox 추가 |
| `wiki_web/templates/admin.html` | 관리 설정에도 동일한 출력 언어 UI 추가 |
| `tests/test_language.py` | language policy helper 테스트 추가 |
| `tests/test_config.py` | 출력 언어 설정 env 적용 테스트 추가 |
| `tests/test_structured_ingest.py` | 설정 기반 language policy 회귀 테스트 보강 |
| `tests/test_query.py` | query 프롬프트 language policy 회귀 테스트 보강 |
| `docs/fix/2026-05-16-ingest-completion.md` | 본 추가 변경 기록 |

### 추가 검증

```bash
uv run pytest tests/test_config.py tests/test_language.py tests/test_structured_ingest.py tests/test_query.py
uv run pytest tests/test_smoke.py tests/test_fs.py
```

결과:

```text
tests/test_config.py tests/test_language.py tests/test_structured_ingest.py tests/test_query.py: 20 passed
tests/test_smoke.py tests/test_fs.py: 16 passed
```

## 추가 변경: Ingest 완료 후 raw 목록 진행 UI 잔류 수정

Ingest 작업 자체는 완료되어 최근 작업 패널에는 `완료`로 표시되지만, raw 파일 목록의 개별 파일 행에는 `추출 진행 중...` progress UI가 남을 수 있었다.

원인:

- 파일 행의 `추출` 버튼은 `partials/ingest_progress.html`로 교체된다.
- SSE `done` 이벤트는 진행 wrapper를 완료 상태로 교체하지 않고, 내부의 작은 완료 텍스트 영역만 갱신했다.
- 따라서 registry 완료 기록이 생성되어도 현재 화면의 파일 행은 다시 렌더링되지 않아 progress/log UI가 남아 있었다.

수정:

- `IngestJob`에 `slug`를 저장한다.
- `/documents/ingest/{job_id}/stream`의 `done` 이벤트가 성공 시 완료 badge HTML을 내려준다.
- 실패 시 같은 위치에 `실패` badge와 `다시 Ingest` 버튼을 내려준다.
- `partials/ingest_progress.html`의 root wrapper가 `done` 이벤트에서 `outerHTML`로 교체되도록 변경했다.

### 추가 수정 파일

| 파일 | 변경 내용 |
|---|---|
| `wiki_web/progress.py` | `IngestJob`에 slug 저장 |
| `wiki_web/routers/documents.py` | SSE done 이벤트에서 완료/실패 컨트롤 HTML 반환 |
| `wiki_web/templates/partials/ingest_progress.html` | 완료 이벤트가 진행 wrapper 전체를 교체하도록 수정 |
| `tests/test_documents_router.py` | 완료/실패 컨트롤 HTML과 progress template 교체 동작 회귀 테스트 추가 |
| `docs/fix/2026-05-16-ingest-completion.md` | 본 추가 변경 기록 |

### 추가 검증

```bash
uv run pytest tests/test_documents_router.py tests/test_progress.py
uv run pytest tests/test_smoke.py
```

결과:

```text
tests/test_documents_router.py tests/test_progress.py: 5 passed
tests/test_smoke.py: 2 passed
```

## 추가 변경: LLM 연결 테스트 성공 메시지 모델명 불일치 수정

설정 화면에서 Ollama 서버 URL을 바꾼 뒤 연결 테스트를 실행하면 실제 테스트 호출은 임시 설정을 적용해 수행하지만, 성공 메시지의 모델명은 임시 설정이 해제된 뒤 다시 계산하고 있었다.

그 결과 `http://100.111.143.12:11434` 같은 원격 Ollama 서버를 테스트했는데도, 이전 환경 또는 로컬 Ollama에서 감지한 모델명이 `연결 성공: ...` 메시지에 표시될 수 있었다.

수정:

- 연결 테스트에서 임시 설정 적용 중 `resolved_model`을 먼저 확정한다.
- 실제 `llm.call()`에도 그 `resolved_model`을 전달한다.
- 성공 메시지도 같은 `resolved_model`을 표시한다.

### 추가 수정 파일

| 파일 | 변경 내용 |
|---|---|
| `wiki_web/routers/settings.py` | 연결 테스트 호출 모델과 성공 메시지 모델명을 동일한 resolved model로 고정 |
| `tests/test_config.py` | 임시 Ollama URL에서 감지한 모델명이 성공 메시지에 표시되는지 회귀 테스트 추가 |
| `CHANGELOG.md` | 본 수정 기록 |
| `docs/fix/2026-05-16-ingest-completion.md` | 본 추가 변경 기록 |

### 추가 검증

```bash
uv run pytest tests/test_config.py tests/test_llm_runtime.py
uv run pytest tests/test_smoke.py
```

결과:

```text
tests/test_config.py tests/test_llm_runtime.py: 20 passed
tests/test_smoke.py: 2 passed
```

## 추가 변경: Heading 원문 언어 사용 기본값 변경

언어 설정의 `Heading은 원문 언어 사용` 옵션을 기본 선택 상태로 변경했다.

수정:

- 새 설정의 기본값을 `heading_original_language: true`로 변경
- 환경변수 `WIKI_HEADING_ORIGINAL_LANGUAGE`가 없을 때도 기본 `on`으로 해석
- `/settings`, `/admin` UI에서 기존 설정값이 없으면 checkbox가 기본 checked 되도록 변경
- README 예시 설정과 설명을 기본 enabled 기준으로 갱신

### 추가 검증

```bash
uv run pytest tests/test_config.py tests/test_language.py tests/test_structured_ingest.py
```
