# Karpathy Alignment 개선 Baseline

> 작성일: 2026-05-14  
> 목적: 개선 작업 전후 비교를 위한 시작점 기록

## 1. 기준 상태

이번 baseline은 실제 외부 LLM 호출 없이 로컬에서 확인 가능한 항목을 먼저 기록한다. Ingest wall-clock time과 LLM 호출 수는 fixture와 mock 기반 계측을 추가한 뒤 별도 phase에서 보강한다.

## 2. 테스트 기준

### 변경 전 관찰

```bash
pytest
```

결과:

- 실패
- 원인: `release/2026-04-21/tests` 복제본까지 수집되며 `tests.conftest` import mismatch 발생

```bash
.venv/bin/python -m pytest tests
```

결과:

- 25 passed
- 실행 시간: 약 0.71초

### Phase 0 조치

`pyproject.toml`에 pytest `testpaths = ["tests"]`를 추가해 기본 `pytest`가 활성 테스트 디렉터리만 수집하도록 한다.

## 3. 기능 기준

| 영역 | 기준 |
|---|---|
| Source 중복 | `sources/{slug}.md` 존재 여부로만 검사 |
| Source provenance | page frontmatter의 `sources` 파일명 목록 중심 |
| Source registry | 없음 |
| Search cache | embedding tier 일부 캐시, grep/BM25는 쿼리마다 재처리 |
| Lint | orphan/TODO/stale + LLM 샘플 검사 |
| Query context | 검색 결과 page 앞부분 최대 3,000자 |

## 4. Phase 1 측정 항목

Source registry 도입 후 다음을 확인한다.

| 항목 | 개선 전 | 개선 후 확인 방법 |
---|---:|---|
| 같은 내용/다른 파일명 중복 감지 | 불가 | registry sha256 기반 duplicate test |
| source metadata 보존 | 없음 | `data/{domain}/sources.jsonl` row 확인 |
| 기본 테스트 수 | 25 | pytest 결과 |
| 기본 pytest 수집 | 실패 | `pytest` 성공 여부 |

## 5. 다음 Baseline 보강 필요

아래 항목은 LLM mock 또는 샘플 위키 fixture가 필요하므로 다음 단계에서 추가한다.

- ingest LLM 호출 수
- ingest prompt 크기 추정치
- ingest wall-clock time
- query cold/warm latency
- search cache hit ratio
- deterministic lint issue count
