# Karpathy Alignment 개선 Extraction Cache 결과

> 작성일: 2026-05-14  
> 범위: `llm.call_with_file()` 추출 캐시 및 LLM file-result 캐시

## 1. 변경 요약

검색 단계 이전의 ingest 병목을 줄이기 위해 `llm.call_with_file()`에 두 단계 캐시를 추가했다.

1. **Extracted text cache**
   - PDF/text/markdown에서 추출한 텍스트를 source `sha256` 기준으로 저장한다.
   - PDF 재파싱과 대용량 텍스트 재읽기 비용을 줄인다.

2. **LLM file-result cache**
   - 같은 파일, 같은 prompt, 같은 system prompt, 같은 model/chunk 설정이면 LLM 결과를 재사용한다.
   - ingest 중간 실패 후 재시도하거나 같은 source를 디버깅할 때 Step 1 분석 비용을 줄인다.

## 2. 캐시 위치

| source 위치 | cache 위치 |
|---|---|
| `data/{domain}/raw/...` | `data/{domain}/.cache/` |
| 임의 CLI 파일 | `<file parent>/.llm_wiki_cache/` |

세부 namespace:

- `.cache/extracted_text/*.txt`
- `.cache/llm_results/*.txt`

## 3. 캐시 제어

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `WIKI_EXTRACT_CACHE` | on | `0`, `false`, `no`, `off`면 추출 캐시 비활성화 |
| `WIKI_LLM_FILE_CACHE` | on | `0`, `false`, `no`, `off`면 LLM file-result 캐시 비활성화 |

## 4. 캐시 키

Extracted text cache:

- cache version
- file sha256
- file suffix

LLM file-result cache:

- cache version
- file sha256
- file suffix
- prompt hash
- system prompt hash
- resolved model
- max tokens
- chunk strategy
- chunk size
- chunk overlap
- max chunks
- PDF max chars

## 5. 테스트 결과

```bash
.venv/bin/python -m pytest
```

결과:

- 34 passed
- 실행 시간: 약 0.90초

## 6. 개선 확인

| 항목 | 개선 전 | 개선 후 |
|---|---|---|
| PDF/text 추출 결과 재사용 | 없음 | source hash 기준 캐시 |
| 같은 파일/같은 prompt 재실행 | LLM 재호출 | LLM file-result cache hit |
| 캐시 root | 없음 | raw source는 `data/{domain}/.cache` |
| 캐시 비활성화 | 없음 | 환경변수로 가능 |
| 관련 테스트 수 | 30 | 34 |

## 7. 한계

- 첫 ingest는 캐시 miss이므로 큰 개선이 없다.
- 파일 내용을 `sha256`으로 확인하므로, 매우 큰 파일은 해시 계산 비용이 남는다.
- 구조화 추출은 아직 도입하지 않았으므로 LLM 호출 수 자체는 기존 파이프라인과 같다.
- 캐시 hit는 동일 파일/동일 prompt/config 재시도에서 가장 크게 체감된다.

## 8. 다음 개선

다음 단계는 `StructuredIngestResult` 도입이다. 캐시는 반복 비용을 줄이지만, 첫 실행의 근본 병목인 “자연어 overview 생성 후 반복 재해석”은 구조화 추출로 줄여야 한다.
