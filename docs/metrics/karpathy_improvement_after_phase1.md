# Karpathy Alignment 개선 Phase 1 측정 결과

> 작성일: 2026-05-14  
> 범위: pytest 수집 설정, source registry, hash 기반 ingest 중복 방어

## 1. 변경 요약

- `pyproject.toml`에 `testpaths = ["tests"]`를 추가해 release 복제본 테스트 수집 문제를 제거했다.
- `wiki_cli/source_registry.py`를 추가해 raw source를 `sha256` 기반으로 기록한다.
- 웹 업로드 시 `data/{domain}/sources.jsonl`에 source metadata를 등록한다.
- 웹 ingest 완료 시 registry row에 `ingested_at`, `summary_page`, `model`을 기록한다.
- ingest 시작 전에 같은 내용의 이미 ingest된 source가 있으면 LLM 호출 전에 중단한다.

## 2. 테스트 결과

```bash
.venv/bin/python -m pytest
```

결과:

- 30 passed
- 실행 시간: 약 0.95초

## 3. 개선 확인

| 항목 | 개선 전 | 개선 후 |
|---|---|---|
| 기본 `pytest` | release 복제본 수집으로 실패 | 30개 테스트 통과 |
| source registry | 없음 | `data/{domain}/sources.jsonl` 생성 |
| 같은 내용/다른 파일명 중복 | 감지 불가 | `sha256`으로 감지 |
| 중복 ingest 차단 시점 | slug page 존재 검사 | slug 검사 + hash duplicate 검사 |
| LLM 호출 전 중복 차단 | 일부 가능 | registry 기록이 있으면 가능 |

## 4. 남은 측정 과제

아직 실제 LLM 호출을 포함한 ingest 성능은 측정하지 않았다. 다음 phase에서 mock 또는 작은 fixture를 사용해 아래를 추가한다.

- ingest LLM 호출 수
- ingest wall-clock time
- prompt/context 크기
- search cold/warm latency
- deterministic lint issue count
