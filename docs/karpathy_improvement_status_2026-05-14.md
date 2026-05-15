# Karpathy Alignment 개선 작업 현황

> 작성일: 2026-05-14  
> 범위: `docs/karpathy_improvement_implementation_plan.md` 기준 진행 상황 점검  
> 관련 결과: `docs/metrics/karpathy_improvement_after_phase1.md`, `docs/metrics/karpathy_improvement_after_extraction_cache.md`, `docs/metrics/karpathy_improvement_after_structured_ingest.md`

## 1. 요약

이번 개선 작업은 검색보다 먼저 ingest/extraction 단계의 반복 비용을 줄이는 데 집중했다. 현재까지 완료된 핵심 개선은 다음 네 가지다.

1. pytest 기본 수집 문제 해결
2. source registry와 hash 기반 중복 추적
3. source 추출 및 `call_with_file()` 결과 캐시
4. 구조화 ingest 결과 도입 및 entity/concept planning LLM 호출 생략

최종 검증 결과:

```bash
.venv/bin/python -m pytest
```

결과:

- 38 passed
- 실행 시간: 약 0.72초

## 2. 계획 대비 진행 상황

| Phase | 계획 | 상태 | 비고 |
|---|---|---|---|
| Phase 0 | 테스트 안전망, pytest 수집 정리 | 완료 | `pyproject.toml`의 `testpaths = ["tests"]` 적용 |
| Phase 1 | Source Registry 및 중복 추적 | 완료 | `data/{domain}/sources.jsonl`, sha256 중복 검사 |
| Phase 1.5 | Extraction/Ingest Cache | 완료 | extracted text cache, LLM file-result cache |
| Phase 2 | Search Index Cache | 미착수 | 다음 검색 속도 개선 대상 |
| Phase 3 | Deterministic Lint 강화 | 미착수 | search index와 함께 진행하면 효율적 |
| Phase 4 | Structured Ingest Result | 부분 완료 | planning LLM 호출 생략까지 완료, evidence 직접 전달은 남음 |
| Phase 5 | 제한 병렬화 | 미착수 | entity/concept write 병렬화 후보 |
| Phase 6 | Draft Review Workflow | 미착수 | 품질 관리용 UI phase |

## 3. 추출/ingest 속도 개선 점검

### 3.1 Extraction cache

구현 내용:

- `llm.call_with_file()`에서 source 파일의 텍스트 추출 결과를 캐시한다.
- `data/{domain}/raw/...` 파일은 `data/{domain}/.cache/extracted_text/`를 사용한다.
- 임의 CLI 파일은 `<file parent>/.llm_wiki_cache/extracted_text/`를 사용한다.
- `WIKI_EXTRACT_CACHE=0`으로 비활성화할 수 있다.

개선 효과:

- PDF/text 추출을 반복하지 않아 재시도 비용이 줄어든다.
- 첫 ingest는 cache miss라 큰 차이가 없지만, 실패 후 재시도와 디버깅 반복에서 효과가 있다.

### 3.2 LLM file-result cache

구현 내용:

- 같은 파일 sha256, 같은 prompt/system hash, 같은 model/chunk 설정이면 `call_with_file()` 결과를 재사용한다.
- `WIKI_LLM_FILE_CACHE=0`으로 비활성화할 수 있다.

개선 효과:

- 동일 source에 대한 Step 1 분석 재실행을 건너뛸 수 있다.
- ingest 중간 실패 후 재시도할 때 source 분석 비용이 크게 줄어든다.

한계:

- prompt나 chunk 설정이 바뀌면 cache miss가 난다.
- 실제 운영에서는 LLM 모델이 바뀌면 의도적으로 새 분석을 수행한다.

### 3.3 Structured ingest

구현 내용:

- 첫 source 분석 결과를 JSON 형태의 `StructuredIngestResult`로 요청한다.
- JSON 파싱 성공 시 `summary`, `claims`, `entities`, `concepts`, `uncertainties`를 compact markdown overview로 렌더링한다.
- `entities[]`, `concepts[]`에서 page plan을 바로 생성한다.
- 기존 `_plan_related_pages()` LLM 호출을 생략한다.
- 파싱 실패 시 기존 overview + planning 흐름으로 fallback한다.

개선 효과:

테스트 fixture 기준 LLM 호출 수:

| 항목 | 기존 흐름 | 구조화 성공 흐름 |
|---|---:|---:|
| source 분석 `call_with_file()` | 1 | 1 |
| entity/concept planning `llm.call()` | 1 | 0 |
| source page 생성 `llm.call()` | 1 | 1 |
| entity page 생성 `llm.call()` | 1 | 1 |
| concept page 생성 `llm.call()` | 1 | 1 |
| 총 LLM 호출 | 5 | 4 |

속도 개선 판단:

- 구조화 추출이 성공하면 source당 최소 1회의 LLM 호출이 줄어든다.
- 줄어든 호출은 overview 전체를 다시 읽는 planning 단계라서 입력 토큰 절감 효과도 있다.
- 실패 시 fallback하므로 안정성을 우선했다.

남은 병목:

- source page는 아직 LLM이 구조 결과를 다시 markdown으로 작성한다.
- entity/concept page 생성은 여전히 페이지별 LLM 호출이다.
- page별 evidence를 직접 넘기는 최적화는 아직 구현되지 않았다.

## 4. Source provenance 개선 점검

구현 내용:

- `wiki_cli/source_registry.py` 추가
- 웹 업로드 시 source metadata 등록
- ingest 완료 시 `ingested_at`, `summary_page`, `model` 기록
- 같은 내용의 다른 파일명이 이미 ingest되어 있으면 LLM 호출 전에 중단

개선 효과:

- 파일명/slug보다 안정적인 hash 기반 추적이 가능해졌다.
- 같은 source를 이름만 바꿔 중복 ingest하는 문제를 줄였다.
- 향후 claim/evidence provenance를 source id에 연결할 기반이 생겼다.

## 5. README 반영 필요 사항

README에는 다음 변경을 반영해야 한다.

- 현재 테스트 수: 25개 → 38개
- ingest 최적화 상태: overview 구조화 일부 완료
- source registry와 `sources.jsonl` 설명 추가
- `.cache/`와 `WIKI_EXTRACT_CACHE`, `WIKI_LLM_FILE_CACHE` 설명 추가
- 향후 개선 예정 항목에서 “미구현: overview 구조화” 문구 수정

## 6. 다음 권장 작업

추천 순서:

1. source page를 구조 데이터 기반 template 렌더링으로 전환
2. entity/concept page prompt에 전체 overview 대신 page별 evidence만 전달
3. 제한 병렬화로 entity/concept page write wall-clock time 단축
4. search index cache 도입
5. deterministic lint 강화

특히 1~3은 검색이 아니라 ingest 속도에 직접 영향을 주는 작업이다.
