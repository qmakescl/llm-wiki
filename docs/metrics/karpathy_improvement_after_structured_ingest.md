# Karpathy Alignment 개선 Structured Ingest 결과

> 작성일: 2026-05-14  
> 범위: 구조화 추출 도입, entity/concept planning LLM 호출 생략

## 1. 변경 요약

`run_ingest()`의 첫 source 분석 단계를 자유서술 overview 중심에서 구조화 JSON 중심으로 전환했다.

새 흐름:

1. `llm.call_with_file()`이 source를 읽고 `StructuredIngestResult` JSON을 요청한다.
2. JSON 파싱이 성공하면 compact markdown overview를 렌더링한다.
3. `entities[]`, `concepts[]`에서 바로 page plan을 만든다.
4. 별도 `_plan_related_pages()` LLM 호출을 생략한다.
5. 파싱 실패 시 기존 overview 기반 `_plan_related_pages()` 흐름으로 fallback한다.

## 2. 추가 파일

- `wiki_cli/structured_ingest.py`
- `tests/test_structured_ingest.py`

## 3. 구조화 결과 형식

핵심 필드:

- `summary`
- `claims[]`
- `entities[]`
- `concepts[]`
- `uncertainties[]`
- `contradiction_candidates[]`

각 entity/concept brief:

- `title`
- `slug`
- `action`
- `summary`
- `evidence[]`

## 4. 개선 확인

테스트 fixture 기준:

| 항목 | 기존 흐름 | 구조화 성공 흐름 |
|---|---:|---:|
| source 분석 `call_with_file()` | 1 | 1 |
| entity/concept planning `llm.call()` | 1 | 0 |
| source page 생성 `llm.call()` | 1 | 1 |
| entity page 생성 `llm.call()` | 1 | 1 |
| concept page 생성 `llm.call()` | 1 | 1 |
| 총 LLM 호출 | 5 | 4 |

확인 내용:

- 구조화 추출 성공 시 planning prompt인 `Based on this source overview`가 호출되지 않는다.
- source/entity/concept page 파일은 기존 구조와 호환되게 생성된다.
- 파서가 JSON code fence와 일반 JSON을 모두 처리한다.

## 5. 테스트 결과

```bash
.venv/bin/python -m pytest
```

결과:

- 38 passed
- 실행 시간: 약 0.95초

## 6. 속도 개선 해석

이번 개선은 source 하나당 최소 1회의 LLM planning 호출을 줄인다. source에서 entity/concept가 많을수록 전체 호출 수 대비 비율은 작아질 수 있지만, planning 호출이 overview 전체를 다시 읽는 단계였기 때문에 입력 토큰 절감 효과도 있다.

아직 남은 주요 병목:

- source page는 여전히 LLM이 구조 결과를 다시 markdown으로 작성한다.
- entity/concept page 생성은 여전히 페이지별 LLM 호출이다.
- evidence map을 page별로 직접 전달하는 최적화는 아직 완성되지 않았다.

## 7. 다음 개선

추천 다음 단계:

1. source page를 구조 데이터 기반 template 렌더링으로 전환한다.
2. entity/concept page에 page별 evidence만 전달한다.
3. entity/concept page 생성에 제한 병렬화를 적용한다.
4. 실제 소형 source fixture로 wall-clock time과 prompt size를 측정한다.
