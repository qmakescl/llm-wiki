# 2026-05-15 남은 Phase 구현 기록

---

## 배경

`docs/karpathy_improvement_implementation_plan.md` 기준으로 아직 코드로 생성하지 못한 항목을 점검한 결과, 다음 항목이 남아 있었다.

- metrics collector
- search index cache
- deterministic lint 강화
- structured ingest의 source page template/evidence 직접 전달
- entity/concept 제한 병렬화
- draft review workflow 기반

이번 작업에서 위 항목들을 최소 동작 가능한 형태로 구현했다.

---

## 구현 내용

### 개선 1: Metrics Collector 추가

**변경 내용**

- `wiki_cli/metrics.py` 추가
- `count`, `record`, `timer`, `summary`, `write_json` 제공
- search/query/ingest에 선택적 metrics hook 연결

**수정 파일**

| 파일 | 수정 내용 |
|---|---|
| `wiki_cli/metrics.py` | metrics collector 신규 구현 |
| `wiki_cli/search.py` | `search(..., metrics=...)` 지원 |
| `wiki_cli/ops/query.py` | query context/LLM generation metrics 기록 |
| `wiki_cli/ops/ingest.py` | structured extraction, LLM call, related page count metrics 기록 |
| `tests/test_metrics_and_drafts.py` | metrics 동작 테스트 추가 |

---

### 개선 2: Search Index Cache 추가

**변경 내용**

- `wiki_cli/search_index.py` 추가
- `wiki/.search/index.json`에 markdown metadata 저장
- 변경되지 않은 파일은 재파싱하지 않음
- grep fallback과 BM25 검색이 index payload를 사용하도록 개선
- `rg`가 있으면 grep tier에서 ripgrep 사용

**수정 파일**

| 파일 | 수정 내용 |
|---|---|
| `wiki_cli/search_index.py` | incremental markdown index 신규 구현 |
| `wiki_cli/search.py` | search index refresh, index 기반 grep/BM25 입력 사용 |
| `tests/test_search_index.py` | index 재사용, 변경 파일만 갱신, 검색 결과 테스트 추가 |

---

### 개선 3: Deterministic Lint 강화

**변경 내용**

LLM 기반 샘플 검사 전에 deterministic issue를 먼저 검출하도록 추가했다.

추가 검사:

- broken wikilinks
- duplicate title/alias
- missing frontmatter
- invalid source reference

**수정 파일**

| 파일 | 수정 내용 |
|---|---|
| `wiki_cli/ops/lint.py` | deterministic lint 검사 추가 |
| `tests/test_lint.py` | broken link, duplicate title/alias, missing frontmatter 테스트 추가 |

---

### 개선 4: Structured Ingest 추가 최적화

**변경 내용**

- 구조화 결과가 있으면 source page를 LLM 재작성 없이 template으로 생성
- entity/concept page 생성 시 전체 overview 대신 해당 page evidence만 전달
- 구조화 결과가 없으면 기존 LLM source page 생성 흐름 유지

**효과**

테스트 fixture 기준 LLM 호출 수가 구조화 1차 구현 대비 1회 더 줄었다.

| 항목 | 이전 | 현재 |
|---|---:|---:|
| source page 생성 LLM 호출 | 1 | 0 |
| 총 LLM 호출 | 4 | 3 |

**수정 파일**

| 파일 | 수정 내용 |
|---|---|
| `wiki_cli/structured_ingest.py` | source page template renderer, slug별 evidence 추출 추가 |
| `wiki_cli/ops/ingest.py` | 구조화 결과 기반 source page 생성, evidence 직접 전달 |
| `tests/test_structured_ingest.py` | source template과 planning/source LLM 생략 테스트 갱신 |

---

### 개선 5: Entity/Concept 제한 병렬화

**변경 내용**

- entity/concept page write job을 worker pool로 실행할 수 있게 추가
- 환경변수 `WIKI_INGEST_WORKERS`로 1~4 범위 제어
- 기본값은 안정성을 위해 1

**수정 파일**

| 파일 | 수정 내용 |
|---|---|
| `wiki_cli/ops/ingest.py` | `ThreadPoolExecutor` 기반 제한 병렬화 추가 |

---

### 개선 6: Draft Review 기반 함수 추가

**변경 내용**

- `.drafts/{job_id}`에 후보 파일 저장
- `manifest.json` 생성
- 승인 시 실제 wiki 경로로 copy
- draft 삭제 지원

**수정 파일**

| 파일 | 수정 내용 |
|---|---|
| `wiki_cli/drafts.py` | draft 생성/로드/승인/삭제 함수 추가 |
| `tests/test_metrics_and_drafts.py` | draft 생성/승인/삭제 테스트 추가 |

---

## 검증

```bash
.venv/bin/python -m pytest
```

결과:

```text
48 passed in 0.95s
```

---

## 추가/수정 파일 목록

| 파일 | 내용 |
|---|---|
| `wiki_cli/metrics.py` | 신규 metrics collector |
| `wiki_cli/search_index.py` | 신규 incremental search index |
| `wiki_cli/drafts.py` | 신규 draft review 기반 |
| `wiki_cli/search.py` | search index와 metrics 연결 |
| `wiki_cli/ops/query.py` | query metrics, chunk 중심 context 구성 |
| `wiki_cli/ops/lint.py` | deterministic lint 강화 |
| `wiki_cli/ops/ingest.py` | source page template, evidence 전달, 병렬화, metrics |
| `wiki_cli/structured_ingest.py` | source page renderer, evidence helper |
| `tests/test_search_index.py` | search index 테스트 |
| `tests/test_metrics_and_drafts.py` | metrics/draft 테스트 |
| `tests/test_lint.py` | deterministic lint 테스트 추가 |
| `tests/test_structured_ingest.py` | 구조화 ingest 최적화 테스트 갱신 |
| `docs/metrics/karpathy_improvement_after_remaining_phases.md` | 남은 phase 구현 결과 기록 |
| `docs/fix/2026-05-15-remaining-phases.md` | 이번 구현 내용 기록 |

---

## 남은 한계

- draft review는 아직 웹 UI에 연결되지 않았다.
- search index는 chunk ranking의 초안이며, 더 정교한 relevance scoring은 남아 있다.
- 병렬화는 worker 수 제한만 제공하며 provider별 retry/backoff는 별도 구현이 필요하다.
- metrics는 수집 API만 있고 UI 시각화는 없다.
