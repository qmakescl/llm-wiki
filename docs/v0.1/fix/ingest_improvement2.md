# ingest 개선 대화 요약

> Codex 검토
> 작성일: 2026-04-21
> 범위: ingest 시간 단축, Karpathy LLM Wiki와의 개념 비교, ingest 유연성 향상 방향

---

## 1. ingest 시간이 오래 걸리는 주된 요인

- 가장 큰 병목은 LLM 호출 횟수와 문서 크기다.
- 현재 ingest는 다음 호출 흐름을 가진다.
  - source overview 생성
  - entity/concept 계획 생성
  - source page 생성
  - entity/concept별 개별 페이지 생성 또는 업데이트
- 문서가 길면 `wiki_cli/llm.py`의 청킹 로직에서 청크별 호출과 최종 통합 호출이 추가된다.
- entity/concept 수가 많을수록 `_write_or_update_page()`가 직렬로 반복 호출되어 시간이 늘어난다.

---

## 2. 페이지 수를 줄이지 않는 조건에서의 개선 방향

사용자 조건:

- wiki 목적상 entity/concept 페이지 수 감소는 고려하지 않는다.

이에 따라 제안한 핵심 개선 방향:

1. `overview`를 단순 자유서술 문자열이 아니라 구조화된 ingest 결과로 전환
2. 청크 단계 결과를 긴 자연어 요약이 아니라 구조 데이터 중심으로 축소
3. entity/concept 페이지 생성 시 전체 `overview`를 반복 전달하지 않고 항목별 evidence만 전달
4. update를 전체 재생성 대신 증분 병합 방식으로 전환
5. entity/concept 생성 루프를 제한적으로 병렬화

핵심 철학:

- 생성 개수를 줄이지 않고도, 중복 해석과 중복 토큰 입력을 줄이면 ingest 시간을 단축할 수 있다.

---

## 3. 문서화한 결과물

이번 대화 중 아래 문서를 생성했다.

- [docs/fix/ingest_improvement.md](../../fix/ingest_improvement.md)
  - 페이지 수를 유지하는 전제에서 ingest 개선 방향 정리
- [docs/fix/design_ingest.md](../../fix/design_ingest.md)
  - `wiki_cli/llm.py`, `wiki_cli/ops/ingest.py` 기준 함수 시그니처 수준 설계안
- [docs/v0.1/project_improvement_report.md](../project_improvement_report.md)
  - 현재 코드베이스 전반 개선 보고서

---

## 4. Karpathy의 LLM Wiki 글과의 개념 비교

대화 중 Karpathy의 LLM Wiki 원문과 현재 제안 방향을 비교했다.

일치하는 점:

- raw source는 불변
- LLM이 persistent wiki를 유지
- ingest 때 source summary, entity/concept 갱신, index/log 업데이트 수행
- query 결과도 다시 wiki에 축적 가능
- 한 source가 여러 페이지를 동시에 갱신할 수 있다는 관점 유지

차이점:

- Karpathy 원문은 패턴 설명에 가깝고 구현은 열어둔다.
- 현재 제안은 성능 최적화를 위해 중간 산출물을 더 강하게 구조화한다.
- 즉 철학 충돌은 아니고, 구현 구체화와 최적화 정도의 차이다.

정리:

- 현재 제안은 Karpathy의 개념과 충돌하지 않는다.
- 다만 원문보다 더 강한 구조화와 파이프라인 제어를 전제한다.

---

## 5. LLM이 더 유연하게 위키를 유지하려면 필요한 점

대화에서 정리한 유연성 조건:

- 출력 스키마를 완전히 고정하지 않을 것
- page type을 `sources/entities/concepts/synthesis`에만 묶지 않을 것
- ingest를 선형 파이프라인이 아니라 계획 기반 편집 작업으로 바꿀 것
- 개별 evidence뿐 아니라 위키 전체 맥락도 더 많이 줄 것
- `AGENTS.md`를 형식 문서보다 편집 철학 문서로 강화할 것
- query 결과도 wiki maintenance 입력으로 연결할 것
- deterministic 규칙보다 편집 판단 여지를 확대할 것

trade-off:

- 유연성이 올라갈수록 속도, 예측 가능성, 테스트 용이성은 일부 낮아진다.
- 현실적으로는 “하위 레벨 deterministic + 상위 레벨 LLM 계획” 혼합형이 적절하다는 결론을 정리했다.

---

## 6. 현재 코드 기준 유연성 향상 논점

대화 마지막 요청에 따라, 현재 코드에서 유연성을 높이려면 어디를 느슨하게 풀어야 하는지 별도 설명이 필요하다고 정리했다.

핵심 후보:

- `wiki_cli/ops/ingest.py`의 고정된 6단계 ingest 순서
- `_plan_related_pages()`의 entity/concept 이분법
- `_write_or_update_page()`의 고정 파일명/title 강제와 전체 재작성 방식
- `wiki_cli/llm.py`의 청크별 완전 요약 후 통합 요약 구조
- 엄격한 frontmatter/section/template 강제 방식

이 부분은 후속 응답에서 코드 기준으로 구체적으로 짚기로 했다.

---

## 7. 현재 코드에서 유연성을 높이려면 느슨하게 풀어야 할 지점

### 7.1 `run_ingest()`의 고정 선형 파이프라인

현재 [wiki_cli/ops/ingest.py](../../../wiki_cli/ops/ingest.py) 의 `run_ingest()`는 다음 순서를 고정한다.

1. source overview 생성
2. entity/concept 계획 생성
3. source page 생성
4. related page 생성
5. index/log 업데이트

문제:

- LLM이 "이번 source는 comparison page를 만드는 게 더 적절하다"거나
- "기존 page 일부만 수정하면 된다"거나
- "contradiction note를 별도 page로 남기는 편이 낫다"는 판단을 하기 어렵다.

완화 방향:

- 선형 ingest 대신 `plan -> execute` 구조로 전환
- 먼저 LLM이 "이번 source가 위키에 어떤 편집 작업을 가해야 하는지"를 계획하게 함

---

### 7.2 `_plan_related_pages()`의 entity/concept 이분법

현재 `_plan_related_pages()`는 결과를 `ENTITIES`와 `CONCEPTS` 두 카테고리로만 제한한다.

문제:

- 실제 위키 유지에서는 comparison, timeline, contradictions, open questions, methods overview 같은 페이지가 더 자연스러울 수 있다.
- 현재 구조는 그 가능성을 차단한다.

완화 방향:

- 이 함수를 단순 분류기가 아니라 edit planner로 바꾼다.
- 출력도 `create/update + page_type + target + rationale` 수준까지 넓힌다.

---

### 7.3 `_write_or_update_page()`의 고정 파일명/title 강제

현재 `_write_or_update_page()`는:

- `display_name`을 파일명으로 사용
- `title`도 강제로 `display_name`에 맞춤

문제:

- 링크 일관성은 좋아지지만, LLM이 더 나은 페이지명이나 더 적절한 병합 대상을 판단할 여지가 줄어든다.
- "새 page를 만들지 말고 기존 page 하위 섹션으로 흡수" 같은 편집 판단도 어렵다.

완화 방향:

- 파일명과 title 강제는 유지하더라도, page 생성 전 단계에서
  - 새 page 생성
  - 기존 page 업데이트
  - 기존 page 하위 섹션 흡수
  중 하나를 고를 수 있게 planner를 확장한다.

---

### 7.4 update의 전체 재작성 방식

현재 update는 기존 `existing_body` 전체를 프롬프트에 넣고 문서를 다시 생성한다.

문제:

- 속도도 느리고
- LLM이 실제 편집자처럼 "어느 섹션을 어떻게 바꿀지" 판단하기보다 전체 문서를 다시 써버리는 쪽으로 유도된다.

완화 방향:

- update를 section-level merge나 append/update block 방식으로 전환
- LLM에게 전체 문서 재작성보다 "어떤 편집을 가할지"를 먼저 판단하게 한다.

---

### 7.5 `_SYSTEM` 및 프롬프트의 강한 형식 통제

현재 `_SYSTEM`과 source/entity/concept page 프롬프트는:

- 정해진 section 구조
- 정해진 YAML 형식
- 정해진 종류의 페이지

를 강하게 요구한다.

문제:

- 출력 일관성은 확보되지만
- source 특성에 따라 page 구조를 바꾸거나 새로운 문서 유형을 도입하기 어렵다.

완화 방향:

- "필수 제약"과 "권장 구조"를 분리한다.
- 필수 제약:
  - markdown
  - frontmatter
  - wikilink 일관성
- 권장 구조:
  - summary
  - contributions
  - notes

즉 섹션 배치는 고정 규칙이 아니라 권장 템플릿으로 낮춘다.

---

### 7.6 `wiki_cli/llm.py`의 청크별 완전 요약 후 통합 구조

현재 `call_with_file()`과 `_chunk_and_call()`은:

- 청크마다 완성형 요약 생성
- 마지막에 다시 통합 요약 생성

문제:

- 후속 단계가 이 결과를 다시 다른 편집 작업으로 재해석해야 한다.
- "어떤 증거가 어느 page update에 중요할지"를 후단에서 다시 추론해야 한다.

완화 방향:

- 청크 단계에서는 완전 요약보다 evidence 단위 구조 데이터를 추출
- 그 뒤 planner가 어떤 page를 어떤 방식으로 고칠지 결정

---

### 7.7 `AGENTS.md`의 역할 강화 필요

유연한 유지보수로 가려면 `AGENTS.md`는 단순 포맷 규칙 문서보다 편집 철학 문서에 가까워져야 한다.

강화해야 할 내용 예:

- 새 정보가 기존 주장과 충돌하면 어떻게 기록할지
- 새 page를 만들기 전에 기존 page에 흡수 가능한지 어떻게 판단할지
- 어떤 경우 comparison/timeline/open question page를 만들지
- source마다 위키 구조 자체를 개선해도 되는지

즉 schema는 "어디에 써라"보다 "어떻게 판단하라"를 더 많이 담아야 한다.

---

## 8. 정리

현재 코드에서 유연성을 막는 핵심은 파일 형식 강제 자체보다도, 편집 작업 종류를 너무 이른 단계에서 고정해버리는 점이다.

우선적으로 느슨하게 풀어야 할 곳은 다음과 같다.

1. `run_ingest()`의 고정 선형 파이프라인
2. `_plan_related_pages()`의 entity/concept 이분법
3. `_write_or_update_page()`의 전체 재작성 방식
4. `_SYSTEM`과 프롬프트의 강한 섹션 강제
5. `llm.py`의 완성형 overview 중심 청크 처리

실전적으로는 "하위 레벨은 deterministic, 상위 레벨은 planner 기반" 혼합 구조가 가장 현실적인 방향으로 정리되었다.
