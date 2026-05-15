# ingest 개선 제안

> 작성일: 2026-04-21
> 범위: `wiki_cli/llm.py`, `wiki_cli/ops/ingest.py`
> 전제: 위키 목적상 entity/concept 페이지 수는 줄이지 않는다

---

## 1. 목표

- ingest 시 생성되는 페이지 수는 유지한다.
- 대신 동일 정보를 반복 해석하고 반복 전달하는 로직을 줄여 전체 시간을 단축한다.
- 핵심은 "페이지 수 감소"가 아니라 "중간 산출물 구조화", "프롬프트 토큰량 절감", "증분 업데이트", "병렬화"다.

---

## 2. 현재 병목의 핵심

현재 `run_ingest()`는 한 번 읽은 source 내용을 여러 단계에서 다시 자연어로 재해석한다.

1. source 원문에서 `overview` 생성
2. `overview`를 다시 넣어 entity/concept 계획 생성
3. 같은 `overview`를 다시 넣어 source page 생성
4. 같은 `overview`를 entity/concept별로 반복 전달하며 페이지 생성
5. 기존 페이지가 있으면 `existing_body` 전체를 다시 넣어 업데이트

즉, 원문에서 만든 중간 결과를 구조화하지 않은 채 자유서술 텍스트로 계속 재사용하면서 LLM 호출당 입력 토큰과 해석 비용이 커진다.

---

## 3. 우선 개선안

### 3.1 `overview`를 구조화 산출물로 변경

현재:

- `source 원문 -> overview 텍스트`

개선:

- `source 원문 -> structured ingest result`

구조화 결과에는 다음 정보를 함께 담는다.

- `summary`
- `key_claims`
- `uncertainties`
- `entities`
- `concepts`
- `page_briefs`
- `entity_evidence`
- `concept_evidence`

이렇게 바꾸면 후속 단계가 `overview`를 다시 읽고 해석하지 않아도 된다.

효과:

- `_plan_related_pages()`의 역할 축소 또는 제거 가능
- source page 생성 시 구조화 필드를 바로 템플릿에 주입 가능
- entity/concept 페이지 생성 시 전체 요약문 재전달 불필요

---

### 3.2 청크 처리 결과를 긴 자연어 요약이 아니라 구조 데이터로 축소

현재 `wiki_cli/llm.py`의 `call_with_file()`은:

- 청크마다 긴 요약 생성
- 마지막에 그 긴 요약들을 다시 통합

이 방식은 청크 수가 많을수록 토큰 낭비가 커진다.

개선:

- 청크 단계에서는 긴 설명 대신 구조 데이터만 추출
- 예:
  - `claims[]`
  - `entities[]`
  - `concepts[]`
  - `evidence snippets[]`
  - `source summary`
- 마지막 단계에서만 통합 후 자연어 페이지로 렌더링

효과:

- 청크 수를 줄이지 않아도 호출당 입출력 토큰량 감소
- 통합 단계의 중복 서술 감소

---

### 3.3 entity/concept 생성 시 전체 `overview` 재전달 제거

현재 `_write_or_update_page()`는 각 페이지마다 `overview` 전체를 프롬프트에 넣는다.

문제:

- 엔티티 10개면 같은 overview가 10번 다시 전달됨
- concept까지 합치면 중복 입력이 매우 큼

개선:

- ingest 초기에 entity/concept별 evidence map 생성
- 각 페이지 생성 시 해당 항목과 직접 관련된 evidence만 전달

예시:

- `"Transformer"` -> source summary 일부 + 청크 3의 claim + 관련 문장들
- `"Self Attention"` -> claim 2 + concept note + 관련 snippet

효과:

- 페이지 수는 유지하면서 페이지별 프롬프트 길이 대폭 감소
- 모델이 각 페이지에서 더 직접적인 근거만 보게 되어 품질도 안정화 가능

---

### 3.4 update를 전체 재생성에서 증분 병합으로 변경

현재 기존 페이지가 있으면 `existing_body`를 통째로 프롬프트에 넣어 다시 생성한다.

문제:

- 페이지가 커질수록 update 비용이 계속 증가
- source가 하나 추가될 때마다 전체 페이지를 재작성하는 구조가 됨

개선:

- 기존 페이지 전체 대신 다음만 전달
  - frontmatter
  - 핵심 섹션 요약
  - 최근 source에서 추가된 사실
- 생성 결과도 "전체 문서"가 아니라 "추가/변경 블록" 중심으로 받는다

가능한 방식:

- append block 생성
- section-level merge
- delta patch 생성 후 로컬 병합

효과:

- 업데이트 비용 감소
- 누적 데이터가 많아질수록 효과가 커짐

---

### 3.5 entity/concept 생성 루프를 제한적 병렬화

현재 entity/concept 페이지 생성은 직렬 실행이다.

개선:

- entity/concept 페이지 생성을 제한된 worker 수로 병렬화
- 파일 단위로 write 충돌이 없으므로 병렬화 대상이 비교적 명확함

권장:

- worker 2~4 수준
- Ollama 사용 시 자원 상황에 맞춰 보수적으로 조정
- 클라우드 모델 사용 시 rate limit 고려

효과:

- 총 호출 수는 같아도 wall-clock time 단축
- 페이지 수 유지 조건과 충돌하지 않음

---

## 4. 구현 우선순위

### 1순위

- `overview`를 구조화 결과로 전환
- entity/concept별 evidence map 도입

### 2순위

- 청크 결과를 구조 데이터 중심으로 변경
- source/entity/concept 생성 프롬프트를 구조화 입력 기반으로 재작성

### 3순위

- update 로직을 전체 재작성에서 증분 병합 방식으로 변경

### 4순위

- entity/concept 생성의 제한적 병렬화 도입

---

## 5. 코드 단위 제안

### `wiki_cli/llm.py`

변경 포인트:

- `call_with_file()`가 긴 자연어 요약이 아니라 구조화 결과를 반환할 수 있도록 확장
- 청크별 intermediate 결과를 압축된 JSON/YAML 형태로 통합하는 경로 추가

추가 후보 함수:

- `extract_structured_from_file(...)`
- `merge_chunk_results(...)`

---

### `wiki_cli/ops/ingest.py`

변경 포인트:

- `overview` 중심 흐름을 `structured_ingest_result` 중심 흐름으로 전환
- `_plan_related_pages()`를 제거하거나 구조화 결과 파서로 축소
- `_write_or_update_page()` 입력을 `overview` 전체가 아니라 evidence 단위로 변경
- update 시 `existing_body` 전체 전달 제거
- entity/concept 생성 루프를 병렬 실행 가능하게 분리

추가 후보 함수:

- `_build_structured_ingest_result(...)`
- `_build_evidence_map(...)`
- `_render_source_page(...)`
- `_render_related_page(...)`
- `_merge_page_update(...)`

---

## 6. 기대 효과

- 페이지 수를 줄이지 않고도 ingest 시간 단축 가능
- 호출 수 자체보다 "호출당 토큰량"과 "중복 해석" 감소 효과가 큼
- source가 길고 entity/concept가 많을수록 개선 폭이 커짐
- wiki 지향 구조를 유지하면서 확장성 있는 ingest 파이프라인으로 전환 가능

---

## 7. 결론

이 코드에서 ingest 시간을 줄이려면 생성 대상 수를 줄일 것이 아니라, 같은 source 정보를 여러 단계에서 반복 해석하는 구조를 먼저 바꿔야 한다.

우선순위는 다음과 같다.

1. `overview`를 구조화 결과로 바꾸기
2. entity/concept별 evidence만 전달하기
3. 청크 결과를 구조 데이터 중심으로 바꾸기
4. update를 증분 병합으로 바꾸기
5. 생성 루프를 제한적으로 병렬화하기

이 방향이 현재 코드베이스에서 가장 일관되고, wiki 목적과도 충돌하지 않는 개선 경로다.
