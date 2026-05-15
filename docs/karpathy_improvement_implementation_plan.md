# Karpathy Alignment 개선 구현 계획

> 작성일: 2026-05-14  
> 기준 문서: [`docs/karpathy_alignment_review.md`](./karpathy_alignment_review.md)  
> 목적: 현재 코드를 변경하기 전에 개선 범위, 순서, 측정 방법을 합의한다.

## 1. 목표

이번 개선의 목표는 기능을 넓히는 것보다, 위키가 커져도 빠르고 검증 가능하게 유지되는 기반을 만드는 것이다.

핵심 목표:

- ingest가 같은 내용을 반복 해석하지 않도록 중간 산출물을 구조화한다.
- source 중복과 provenance를 파일명보다 안정적인 id/hash 기준으로 추적한다.
- query/search가 매번 전체 파일을 재처리하지 않도록 인덱스와 캐시를 둔다.
- lint가 샘플 기반 LLM 점검을 넘어 deterministic health check를 수행한다.
- 각 개선 전후로 wall-clock time, 파일 수, cache hit, lint issue 수를 기록한다.

## 2. 작업 원칙

- 한 번에 대규모 리라이트하지 않고, 기능 flag 또는 fallback을 두고 단계적으로 바꾼다.
- 기존 CLI/Web 진입점은 유지한다.
- `wiki_cli`의 ops 레이어를 먼저 개선하고, `wiki_web`은 그 결과를 얇게 연결한다.
- 테스트는 구현 단계마다 추가한다.
- 성능 측정은 실제 LLM 호출이 필요한 항목과 로컬 deterministic 항목을 분리한다.

## 3. 측정 기준

### 3.1 Baseline 수집

코드 변경 전에 아래를 기록한다.

| 영역 | 측정 항목 | 방법 |
|---|---|---|
| Test | 기존 회귀 테스트 | `.venv/bin/python -m pytest tests` |
| Ingest | wall-clock time | 작은 `.txt` fixture로 `time wiki ingest ...` |
| Ingest | LLM 호출 수 | `wiki_cli.llm.call` wrapper 계측 또는 debug log |
| Ingest | 생성/수정 파일 수 | ingest 전후 `find wiki -type f` 비교 |
| Search | query latency | grep/BM25/embedding tier별 동일 질문 3회 평균 |
| Search | cache hit ratio | 캐시 도입 후부터 기록 |
| Lint | deterministic issue 수 | broken link, orphan, duplicate title, stale |
| Query | context 길이 | LLM prompt에 들어가는 page/chunk 글자 수 |

### 3.2 측정 산출물

측정 결과는 다음 파일에 누적한다.

- `docs/metrics/karpathy_improvement_baseline.md`
- `docs/metrics/karpathy_improvement_after_phase1.md`
- `docs/metrics/karpathy_improvement_after_phase2.md`

`docs/metrics/`가 없으면 생성한다.

## 4. Phase 0: 계측과 안전망

목적: 개선 전후 비교가 가능하도록 최소 계측과 테스트를 먼저 추가한다.

### 구현 항목

- `wiki_cli/metrics.py` 추가
  - `timer(name)`
  - `count(name)`
  - `record(name, value)`
  - JSONL 또는 dict summary 출력
- ingest/query/search/lint에서 선택적으로 metrics collector를 받을 수 있게 확장
- 기본 동작은 바꾸지 않고, 테스트/CLI debug 모드에서만 활성화
- `pytest`가 release 복제 테스트를 수집하지 않도록 설정 검토

### 테스트

- metrics collector가 disabled일 때 기존 동작 불변
- timer/count가 예상 key를 기록하는지 단위 테스트
- `.venv/bin/python -m pytest tests`

### 완료 기준

- baseline 문서 작성 가능
- 기존 25개 테스트 통과
- 전체 `pytest` 수집 문제가 해결되거나, 공식 테스트 명령을 `pytest tests`로 문서화

## 5. Phase 1: Source Registry 및 중복 추적

목적: 파일명/slug가 아니라 source id와 hash로 원본을 추적한다.

### 구현 항목

- `wiki_cli/source_registry.py` 추가
- registry 위치: `data/{domain}/sources.jsonl`
- 필드:
  - `source_id`
  - `relative_path`
  - `filename`
  - `sha256`
  - `size`
  - `uploaded_at`
  - `ingested_at`
  - `summary_page`
  - `model`
- upload 시 registry에 파일 정보 등록
- ingest 시작 시 sha256 중복 검사
- `_find_source(data_root, slug)`는 유지하되 내부적으로 source id 기반 조회로 이동할 준비

### 테스트

- 같은 내용/다른 파일명 업로드 시 중복 감지
- 같은 파일명/다른 내용 업로드 시 별도 source로 기록
- registry가 깨진 경우 graceful fallback

### 측정

- duplicate detection time
- registry lookup time
- ingest 전후 registry row 변화

### 완료 기준

- 중복 source page 생성 가능성이 줄어듦
- 기존 slug 기반 UI가 깨지지 않음

## 6. Phase 2: Search Index Cache

목적: query마다 markdown 전체를 새로 읽고 BM25 corpus를 재구성하는 비용을 줄인다.

### 구현 항목

- `wiki_cli/search_index.py` 추가
- 캐시 위치: `wiki/.search/index.json`
- 파일별 저장 정보:
  - `path`
  - `mtime_ns`
  - `sha256`
  - `title`
  - `aliases`
  - `headings`
  - `outgoing_links`
  - `plain_text_preview`
- 검색 시 변경된 파일만 재파싱
- BM25 corpus 캐시
- grep tier는 기존 Python fallback 유지, 가능하면 `rg` 사용 path 추가
- query context를 전체 page 앞부분 3,000자가 아니라 관련 heading/chunk 중심으로 구성

### 테스트

- 파일 변경이 없으면 index rebuild 없음
- 파일 하나 수정 시 해당 파일만 갱신
- broken wikilink 검사를 위해 outgoing_links가 정확히 저장됨
- 검색 결과가 기존 grep 결과와 최소 호환

### 측정

- cold index build time
- warm query latency
- changed-file rebuild time
- query prompt context length

### 완료 기준

- warm query가 기존 대비 빨라짐
- 검색 품질이 눈에 띄게 후퇴하지 않음

## 6.5. Phase 1.5: Extraction/Ingest Cache

목적: search 이전 단계인 source 추출과 초기 LLM 분석 재시도 비용을 줄인다.

### 구현 항목

- `llm.call_with_file()` 내부에 extracted text cache 추가
- PDF/text/markdown 추출 결과를 source `sha256` 기준으로 저장
- 캐시 위치:
  - `data/{domain}/.cache/extracted_text/`
  - ad-hoc CLI 파일은 파일 옆 `.llm_wiki_cache/extracted_text/`
- 같은 파일, 같은 prompt, 같은 model/chunk 설정이면 LLM file-result cache 사용
- 캐시 키 구성:
  - file sha256
  - prompt/system hash
  - model
  - max tokens
  - chunk strategy/size/overlap/max chunks
  - PDF truncation limit
  - cache version
- 환경변수:
  - `WIKI_EXTRACT_CACHE=0`이면 추출 캐시 비활성화
  - `WIKI_LLM_FILE_CACHE=0`이면 LLM file-result 캐시 비활성화

### 테스트

- `raw/` 파일의 cache root가 `data/{domain}/.cache`로 잡히는지 확인
- 추출 캐시 hit 시 원본 파일 재읽기 없이 반환
- 동일 파일/동일 prompt의 두 번째 `call_with_file()`이 LLM 호출을 건너뛰는지 확인
- `WIKI_LLM_FILE_CACHE=0`에서 캐시가 비활성화되는지 확인

### 측정

- 첫 실행: 캐시 miss, 기존과 유사한 시간
- 재시도: extracted text cache hit
- 같은 prompt 재실행: LLM file-result cache hit
- 실제 ingest 중간 실패 후 재시도 시 Step 1 비용 감소

### 완료 기준

- 반복 ingest/debug 시 파일 추출과 초기 분석 재실행 비용이 줄어듦
- 기본 테스트가 통과함
- 캐시를 환경변수로 끌 수 있음

## 7. Phase 3: Deterministic Lint 강화

목적: LLM 샘플 검사 전에 빠르고 재현 가능한 health check를 수행한다.

### 구현 항목

- `wiki_cli/ops/lint.py`에 아래 검사 추가
  - broken wikilinks
  - duplicate title/alias
  - missing frontmatter
  - invalid source reference
  - excessive orphan clusters
- `search_index.py`의 title/alias/link 데이터를 재사용
- lint 결과를 구조 데이터로 반환하고 CLI/Web이 렌더링
- 선택적으로 `wiki/lint_reports/YYYY-MM-DD.md` 저장

### 테스트

- 존재하지 않는 `[[Page]]` 검출
- alias로 해결 가능한 링크는 정상 처리
- 중복 title 검출
- frontmatter 없는 페이지 검출

### 측정

- lint total time
- deterministic issue count
- LLM lint 호출 전 후보 수

### 완료 기준

- LLM 없이도 유의미한 wiki 품질 문제가 검출됨
- 기존 orphan/TODO/stale 검사는 유지됨

## 8. Phase 4: Structured Ingest Result

목적: ingest 중간 산출물을 자유서술 overview에서 구조화 데이터로 전환한다.

### 구현 항목

- `wiki_cli/structured_ingest.py` 추가
- 타입 후보:

```python
class Evidence(TypedDict):
    source_id: str
    quote: str
    location: str
    confidence: str

class PageBrief(TypedDict):
    title: str
    slug: str
    action: str
    kind: str
    summary: str
    evidence: list[Evidence]

class StructuredIngestResult(TypedDict):
    summary: str
    claims: list[dict]
    entities: list[PageBrief]
    concepts: list[PageBrief]
    uncertainties: list[dict]
    contradiction_candidates: list[dict]
```

- `llm.call_with_file()` 결과를 JSON/YAML로 받는 경로 추가
- `_plan_related_pages()`는 구조 결과 파싱으로 대체하고 LLM fallback으로만 유지
- source/entity/concept page prompt는 구조 결과를 입력으로 사용
- evidence map을 page별로 전달

### 테스트

- 구조 결과 파싱 성공/실패/fallback
- entity/concept title 정규화
- evidence 없는 page brief 처리
- 기존 markdown output 호환

### 측정

- ingest LLM 호출 수
- ingest prompt input size 추정
- ingest wall-clock time
- 생성 page 수

### 완료 기준

- 동일 source ingest에서 LLM 호출 수 또는 prompt size가 감소
- 생성되는 wiki 구조는 기존과 호환

### 구현 결과 (2026-05-14)

- `wiki_cli/structured_ingest.py`를 추가했다.
- 첫 source 읽기 단계에서 JSON 구조를 요청하고 파싱한다.
- 구조화 결과가 성공하면 `entities[]`, `concepts[]`에서 page plan을 바로 만들고 `_plan_related_pages()` LLM 호출을 생략한다.
- 구조화 파싱이 실패하면 기존 overview 기반 흐름으로 fallback한다.
- 기존 source/entity/concept page 생성 prompt는 유지하되, 입력 overview를 구조 데이터에서 렌더링한 compact markdown으로 바꾼다.
- 테스트에서 entity 1개, concept 1개 source의 ingest 경로가 planning LLM 호출 없이 동작함을 확인했다.

남은 작업:

- entity/concept별 evidence를 `_write_or_update_page()`에 직접 전달하는 방식으로 더 줄일 수 있다.
- source page 자체도 LLM 재작성 대신 구조 데이터 기반 template 렌더링으로 전환할 수 있다.
- JSON schema validation을 더 엄격하게 하고, 실패 원인을 progress log에 표시할 수 있다.

## 9. Phase 5: 제한 병렬화

목적: entity/concept 페이지 생성의 wall-clock time을 줄인다.

### 구현 항목

- entity/concept page write를 worker 2~4개로 제한 병렬화
- 동일 page title 충돌 lock
- provider별 rate limit/backoff 옵션
- 로컬 Ollama 기본 worker는 1 또는 2로 보수적 설정

### 테스트

- 서로 다른 페이지 병렬 생성
- 같은 페이지 update 충돌 방지
- 예외 발생 시 job status와 partial write 처리

### 측정

- serial ingest time vs parallel ingest time
- failed/retried LLM call count
- page write conflict count

### 완료 기준

- cloud model 또는 빠른 local model에서 wall-clock time 개선
- 실패 시 로그와 상태가 명확함

## 10. Phase 6: Draft Review Workflow

목적: Karpathy가 강조한 human-in-the-loop ingest 품질 관리를 UI에 반영한다.

### 구현 항목

- `.drafts/{job_id}/`에 source/entity/concept 후보 저장
- 웹에서 변경 diff 표시
- 사용자 승인 후 `wiki/`에 반영
- 거절/수정/부분 승인 지원은 후순위로 둔다

### 테스트

- draft 생성 후 wiki 원본 불변
- 승인 시에만 index/log 업데이트
- draft 삭제/만료 처리

### 측정

- draft 생성 시간
- 승인 후 write time
- 사용자가 제거/수정한 page 후보 수

### 완료 기준

- 사용자가 ingest 결과를 검토한 뒤 반영할 수 있음
- 기존 즉시 ingest 흐름은 옵션으로 유지 가능

## 11. 구현 순서 제안

권장 순서:

1. Phase 0: 계측과 안전망
2. Phase 1: Source Registry
3. Phase 1.5: Extraction/Ingest Cache
4. Phase 2: Search Index Cache
5. Phase 3: Deterministic Lint
6. Phase 4: Structured Ingest Result
7. Phase 5: 제한 병렬화
8. Phase 6: Draft Review Workflow

이 순서가 좋은 이유는 앞 단계가 뒤 단계의 기반이 되기 때문이다. registry가 있어야 provenance가 안정되고, search index가 있어야 lint가 빨라지며, metrics가 있어야 ingest 구조 변경의 효과를 확인할 수 있다.

## 12. 첫 구현 PR 범위 제안

검토 후 바로 착수하기 좋은 첫 범위는 다음이다.

- `docs/metrics/karpathy_improvement_baseline.md` 생성
- `pyproject.toml` 또는 pytest 설정으로 release 테스트 수집 문제 정리
- `wiki_cli/source_registry.py` 추가
- upload/ingest에 source hash 중복 검사 연결
- 관련 테스트 추가

이 범위는 LLM prompt를 건드리지 않으므로 위험이 낮고, 이후 structured ingest와 provenance 개선의 기반이 된다.

## 13. 검증 명령어

기본 검증:

```bash
.venv/bin/python -m pytest tests
```

현재 알려진 이슈:

```bash
.venv/bin/python -m pytest
```

위 명령은 `release/2026-04-21/tests` 복제본까지 수집하면서 `tests.conftest` import mismatch가 발생한다. Phase 0에서 해결하거나, 공식 테스트 명령을 `tests` 디렉터리 지정으로 고정한다.
