# ingest 설계안

> 작성일: 2026-04-21
> 대상 파일: `wiki_cli/llm.py`, `wiki_cli/ops/ingest.py`
> 목적: ingest 시간을 줄이기 위한 구조 개편안을 함수 시그니처 수준까지 정리
> 전제: entity/concept 생성 개수는 줄이지 않는다

---

## 1. 설계 목표

- source를 한 번 읽어서 만든 중간 결과를 이후 단계에서 다시 자연어로 해석하지 않도록 한다.
- 청크별 긴 요약을 여러 번 생성하는 구조를, 청크별 구조 데이터 추출 후 최종 렌더링하는 구조로 바꾼다.
- entity/concept 페이지 생성 시 전체 `overview`를 반복 전달하지 않고, 항목별 evidence만 전달한다.
- 기존 페이지 update는 전체 재생성이 아니라 증분 병합 중심으로 바꾼다.
- 가능한 범위에서 병렬화를 고려하되, 파일 write 경계는 명확히 유지한다.

---

## 2. 핵심 구조 변경

현재 구조:

- `call_with_file()` -> 긴 `overview` 문자열
- `_plan_related_pages(overview)` -> entity/concept 계획
- source page 생성 시 `overview` 재사용
- entity/concept page 생성 시 `overview` 재사용
- update 시 `existing_body` 전체 재사용

제안 구조:

- `extract_structured_from_file()` -> `StructuredIngestResult`
- `StructuredIngestResult`에서 source/entity/concept 생성 입력을 직접 파생
- entity/concept별 `EvidencePacket` 생성
- page 생성은 `PageDraftRequest` 단위로 통일
- update는 `PageMergeRequest` 단위로 처리

즉, ingest의 중심 자료형을 `str overview`에서 `StructuredIngestResult`로 바꾼다.

---

## 3. `wiki_cli/llm.py` 설계안

### 3.1 새 데이터 구조

`wiki_cli/llm.py`에 아래 dataclass를 추가하는 설계를 권장한다.

```python
from dataclasses import dataclass, field
from pathlib import Path

@dataclass
class ChunkExtraction:
    chunk_index: int
    summary: str
    claims: list[str]
    uncertainties: list[str]
    entities: list[str]
    concepts: list[str]
    evidence_snippets: list[str]

@dataclass
class StructuredIngestResult:
    source_name: str
    source_path: Path
    document_title: str
    summary: str
    key_claims: list[str]
    uncertainties: list[str]
    entities: list[str]
    concepts: list[str]
    evidence_by_topic: dict[str, list[str]] = field(default_factory=dict)
    chunks: list[ChunkExtraction] = field(default_factory=list)
```

핵심은 LLM 결과를 이후 단계가 바로 사용할 수 있는 구조 데이터로 들고 다니는 것이다.

### 3.2 유지할 함수

기존 함수는 유지 가능하다.

```python
def call(
    prompt: str,
    *,
    system: str = "",
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.3,
) -> str:
    ...
```

이 함수는 low-level primitive로 계속 사용한다.

### 3.3 변경 대상 함수

기존:

```python
def call_with_file(
    prompt: str,
    file_path: Path,
    *,
    system: str = "",
    model: str | None = None,
    max_tokens: int = 4096,
) -> str:
    ...
```

제안:

```python
def call_with_file(
    prompt: str,
    file_path: Path,
    *,
    system: str = "",
    model: str | None = None,
    max_tokens: int = 4096,
) -> str:
    ...
```

`call_with_file()`는 호환성 때문에 유지하되, ingest의 주 경로에서는 더 이상 핵심 함수로 쓰지 않는다.

새 함수:

```python
def extract_structured_from_file(
    file_path: Path,
    *,
    schema: str = "",
    system: str = "",
    model: str | None = None,
    max_tokens: int = 4096,
) -> StructuredIngestResult:
    ...
```

역할:

- 파일 읽기
- 청킹
- 청크별 구조 추출
- 통합 결과 병합
- `StructuredIngestResult` 반환

### 3.4 새 내부 함수

#### `_read_source_text`

```python
def _read_source_text(file_path: Path) -> str:
    ...
```

역할:

- PDF/텍스트 파일을 읽어 문자열 반환
- 기존 `call_with_file()` 안에 있던 I/O를 분리

#### `_split_source_text`

```python
def _split_source_text(text: str) -> list[str]:
    ...
```

역할:

- `_get_chunk_config()`를 사용해 현재 설정에 맞게 분할
- 기존 `_split_by_section`, `_split_by_fixed`, `_cap_chunks`를 조합하는 상위 헬퍼

#### `_extract_chunk_structured`

```python
def _extract_chunk_structured(
    chunk_text: str,
    *,
    chunk_index: int,
    total_chunks: int,
    source_name: str,
    schema: str,
    system: str,
    model: str | None,
) -> ChunkExtraction:
    ...
```

역할:

- 청크 1개에서 구조 데이터 추출
- 반환은 자연어 문자열이 아니라 `ChunkExtraction`

#### `_merge_chunk_extractions`

```python
def _merge_chunk_extractions(
    chunks: list[ChunkExtraction],
    *,
    source_name: str,
    source_path: Path,
    schema: str,
    system: str,
    model: str | None,
) -> StructuredIngestResult:
    ...
```

역할:

- 청크별 결과를 dedupe/merge
- entity/concept/evidence/topic map 통합

#### `_parse_structured_payload`

```python
def _parse_structured_payload(text: str) -> dict:
    ...
```

역할:

- LLM이 반환한 JSON 또는 YAML payload 파싱
- 파싱 실패 시 fallback 처리

### 3.5 청크 병합 방식 변경

기존 `_chunk_and_call()`:

```python
def _chunk_and_call(
    prompt: str,
    chunks: list[str],
    *,
    system: str,
    model: str | None,
    max_tokens: int,
) -> str:
    ...
```

제안:

```python
def _chunk_and_extract(
    chunks: list[str],
    *,
    source_name: str,
    schema: str,
    system: str,
    model: str | None,
) -> list[ChunkExtraction]:
    ...
```

차이:

- 반환형을 `str`에서 `list[ChunkExtraction]`로 변경
- 최종 자연어 synthesis는 `ingest.py`에서 page rendering 시점에만 수행

### 3.6 호환 전략

- `call_with_file()`는 query나 다른 단순 사용처 대비용으로 남긴다.
- ingest만 `extract_structured_from_file()` 경로로 전환한다.
- 이렇게 하면 범위를 `wiki_cli/ops/ingest.py`에 집중할 수 있다.

---

## 4. `wiki_cli/ops/ingest.py` 설계안

### 4.1 새 데이터 구조

```python
from dataclasses import dataclass, field

@dataclass
class PlannedPage:
    kind: str           # "entities" | "concepts"
    slug: str
    display_name: str
    action: str         # "create" | "update"
    evidence: list[str] = field(default_factory=list)

@dataclass
class SourcePageDraft:
    title: str
    metadata: dict
    body: str
    description: str

@dataclass
class PageDraftRequest:
    kind: str
    slug: str
    display_name: str
    action: str
    source_name: str
    evidence: list[str]
    existing_meta: dict
    existing_body: str

@dataclass
class PageMergeRequest:
    page_path: Path
    display_name: str
    source_name: str
    evidence: list[str]
    existing_meta: dict
    existing_body: str
```

### 4.2 `run_ingest()` 시그니처

기존:

```python
def run_ingest(
    wiki_root: Path,
    source: Path,
    model: str | None,
    progress_callback: Callable[[str], None] | None = None,
) -> None:
    ...
```

제안:

```python
def run_ingest(
    wiki_root: Path,
    source: Path,
    model: str | None,
    progress_callback: Callable[[str], None] | None = None,
    *,
    parallelism: int = 1,
) -> None:
    ...
```

변경 이유:

- 기존 호출부와 호환 가능
- 나중에 entity/concept page 생성 병렬화를 옵션으로 제어 가능

### 4.3 `run_ingest()` 내부 흐름 변경

기존:

1. `overview = llm.call_with_file(...)`
2. `_plan_related_pages(overview)`
3. source page 생성
4. entity/concept 개별 생성

제안:

1. `structured = llm.extract_structured_from_file(...)`
2. `planned_pages = _plan_pages_from_structured(...)`
3. `source_draft = _render_source_page_from_structured(...)`
4. `page_requests = _build_page_requests(...)`
5. `_process_page_requests(...)`

### 4.4 대체 또는 축소될 함수

#### `_plan_related_pages`

기존:

```python
def _plan_related_pages(
    wiki_root: Path,
    overview: str,
    model: str | None,
    schema: str,
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    ...
```

제안:

```python
def _plan_pages_from_structured(
    wiki_root: Path,
    structured: llm.StructuredIngestResult,
) -> list[PlannedPage]:
    ...
```

변경 이유:

- `overview`를 다시 LLM에 넣지 않고 구조 데이터에서 바로 계획 산출
- 기존 페이지 존재 여부만 로컬에서 판정

#### `_write_or_update_page`

기존:

```python
def _write_or_update_page(
    wiki_root: Path,
    kind: str,
    slug: str,
    action: str,
    source_name: str,
    overview: str,
    model: str | None,
    schema: str,
) -> None:
    ...
```

제안:

```python
def _write_or_update_page(
    wiki_root: Path,
    request: PageDraftRequest,
    *,
    model: str | None,
    schema: str,
) -> Path:
    ...
```

변경 이유:

- 인자 폭발을 줄인다
- `overview` 전체 대신 evidence만 받는다
- 반환값으로 실제 write된 `Path`를 돌려 index/log 후처리에 활용 가능

### 4.5 새 함수 제안

#### `_render_source_page_from_structured`

```python
def _render_source_page_from_structured(
    source: Path,
    structured: llm.StructuredIngestResult,
    *,
    schema: str,
    model: str | None,
) -> SourcePageDraft:
    ...
```

역할:

- source page 생성 전용
- 구조 데이터 기반으로만 source page 초안 생성
- 필요 시 LLM을 호출하되 입력은 `overview` 전체가 아니라 구조 필드

#### `_build_page_requests`

```python
def _build_page_requests(
    wiki_root: Path,
    planned_pages: list[PlannedPage],
    structured: llm.StructuredIngestResult,
    source_name: str,
) -> list[PageDraftRequest]:
    ...
```

역할:

- page 생성에 필요한 evidence, 기존 페이지 내용, action을 모두 묶어서 request 리스트 생성

#### `_load_existing_page_state`

```python
def _load_existing_page_state(page_path: Path, legacy_path: Path | None = None) -> tuple[dict, str, str]:
    ...
```

반환:

- `(metadata, body, resolved_action)`

역할:

- 기존 페이지 존재 여부와 update/create 판정 정리

#### `_select_page_evidence`

```python
def _select_page_evidence(
    structured: llm.StructuredIngestResult,
    display_name: str,
    kind: str,
) -> list[str]:
    ...
```

역할:

- topic별 evidence map에서 해당 page용 evidence만 추출

#### `_render_related_page`

```python
def _render_related_page(
    request: PageDraftRequest,
    *,
    schema: str,
    model: str | None,
) -> tuple[dict, str]:
    ...
```

역할:

- create/update 공통 draft 생성
- 반환은 `(metadata, body)`

#### `_merge_existing_page`

```python
def _merge_existing_page(
    request: PageMergeRequest,
    *,
    schema: str,
    model: str | None,
) -> tuple[dict, str]:
    ...
```

역할:

- 기존 페이지 전체 재작성 대신 증분 병합 결과 생성
- update 전용 경로

#### `_process_page_requests`

```python
def _process_page_requests(
    wiki_root: Path,
    requests: list[PageDraftRequest],
    *,
    model: str | None,
    schema: str,
    parallelism: int,
    emit: Callable[[str], None] | None = None,
) -> list[Path]:
    ...
```

역할:

- 순차/병렬 실행을 한 곳에서 제어
- write된 페이지 목록 반환

### 4.6 함수 책임 재배치

기존 `run_ingest()`가 너무 많은 책임을 가진다.

제안 책임 분해:

- `run_ingest()`:
  - orchestration만 담당
- `llm.extract_structured_from_file()`:
  - source 읽기 + 구조 추출
- `_plan_pages_from_structured()`:
  - create/update 계획
- `_render_source_page_from_structured()`:
  - source page draft
- `_build_page_requests()`:
  - related page 입력 조립
- `_process_page_requests()`:
  - write/update 실행

---

## 5. 제안 시그니처 전체 목록

### `wiki_cli/llm.py`

```python
@dataclass
class ChunkExtraction: ...

@dataclass
class StructuredIngestResult: ...

def extract_structured_from_file(
    file_path: Path,
    *,
    schema: str = "",
    system: str = "",
    model: str | None = None,
    max_tokens: int = 4096,
) -> StructuredIngestResult:
    ...

def _read_source_text(file_path: Path) -> str:
    ...

def _split_source_text(text: str) -> list[str]:
    ...

def _extract_chunk_structured(
    chunk_text: str,
    *,
    chunk_index: int,
    total_chunks: int,
    source_name: str,
    schema: str,
    system: str,
    model: str | None,
) -> ChunkExtraction:
    ...

def _chunk_and_extract(
    chunks: list[str],
    *,
    source_name: str,
    schema: str,
    system: str,
    model: str | None,
) -> list[ChunkExtraction]:
    ...

def _merge_chunk_extractions(
    chunks: list[ChunkExtraction],
    *,
    source_name: str,
    source_path: Path,
    schema: str,
    system: str,
    model: str | None,
) -> StructuredIngestResult:
    ...

def _parse_structured_payload(text: str) -> dict:
    ...
```

### `wiki_cli/ops/ingest.py`

```python
@dataclass
class PlannedPage: ...

@dataclass
class SourcePageDraft: ...

@dataclass
class PageDraftRequest: ...

@dataclass
class PageMergeRequest: ...

def run_ingest(
    wiki_root: Path,
    source: Path,
    model: str | None,
    progress_callback: Callable[[str], None] | None = None,
    *,
    parallelism: int = 1,
) -> None:
    ...

def _plan_pages_from_structured(
    wiki_root: Path,
    structured: llm.StructuredIngestResult,
) -> list[PlannedPage]:
    ...

def _render_source_page_from_structured(
    source: Path,
    structured: llm.StructuredIngestResult,
    *,
    schema: str,
    model: str | None,
) -> SourcePageDraft:
    ...

def _build_page_requests(
    wiki_root: Path,
    planned_pages: list[PlannedPage],
    structured: llm.StructuredIngestResult,
    source_name: str,
) -> list[PageDraftRequest]:
    ...

def _load_existing_page_state(
    page_path: Path,
    legacy_path: Path | None = None,
) -> tuple[dict, str, str]:
    ...

def _select_page_evidence(
    structured: llm.StructuredIngestResult,
    display_name: str,
    kind: str,
) -> list[str]:
    ...

def _render_related_page(
    request: PageDraftRequest,
    *,
    schema: str,
    model: str | None,
) -> tuple[dict, str]:
    ...

def _merge_existing_page(
    request: PageMergeRequest,
    *,
    schema: str,
    model: str | None,
) -> tuple[dict, str]:
    ...

def _write_or_update_page(
    wiki_root: Path,
    request: PageDraftRequest,
    *,
    model: str | None,
    schema: str,
) -> Path:
    ...

def _process_page_requests(
    wiki_root: Path,
    requests: list[PageDraftRequest],
    *,
    model: str | None,
    schema: str,
    parallelism: int,
    emit: Callable[[str], None] | None = None,
) -> list[Path]:
    ...
```

---

## 6. 단계별 적용 순서

### 1단계

- `wiki_cli/llm.py`에 `StructuredIngestResult` 경로 추가
- 기존 `call_with_file()`는 유지
- ingest만 새 함수 사용

### 2단계

- `wiki_cli/ops/ingest.py`에서 `overview` 의존 제거
- `_plan_related_pages()`를 `_plan_pages_from_structured()`로 교체

### 3단계

- `_write_or_update_page()`를 request 기반 시그니처로 변경
- evidence 중심 입력으로 전환

### 4단계

- update 전용 병합 함수 추가
- 전체 body 재전달 제거

### 5단계

- `_process_page_requests()`에 병렬 실행 도입

---

## 7. 기대 효과

- ingest 파이프라인의 주 자료형이 문자열에서 구조 객체로 바뀌어 중복 해석 비용이 줄어든다.
- entity/concept 수를 유지해도 페이지별 프롬프트 길이를 크게 줄일 수 있다.
- 기존 페이지가 커질수록 심해지는 update 비용을 제어할 수 있다.
- 함수 책임이 분리되어 이후 유지보수와 테스트 작성도 쉬워진다.

---

## 8. 결론

이 설계의 핵심은 `wiki_cli/llm.py`가 더 이상 "긴 자연어 overview 생성기"가 아니라 "구조화 ingest 결과 추출기"가 되도록 바꾸는 것이다. 그 위에서 `wiki_cli/ops/ingest.py`는 문자열을 다시 해석하는 orchestration이 아니라, 구조 데이터를 page draft와 merge request로 변환하는 orchestration으로 바뀌어야 한다.

이 방향이면 생성 개수는 유지하면서도, 현재 ingest 시간의 주원인인 중복 입력과 중복 해석을 줄일 수 있다.
