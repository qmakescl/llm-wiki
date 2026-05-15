# Karpathy Alignment 남은 Phase 구현 결과

> 작성일: 2026-05-15  
> 범위: `karpathy_improvement_implementation_plan.md`의 미구현 항목 보완

## 1. 요약

계획서 점검에서 남아 있던 항목을 최소 동작 가능한 형태로 구현했다.

완료한 항목:

- metrics collector 추가
- search index cache 추가
- grep/BM25 검색의 index 기반 입력 사용
- deterministic lint 강화
- structured ingest 추가 최적화
- source page template rendering
- entity/concept page별 evidence 전달
- entity/concept 제한 병렬화 옵션
- draft review workflow 기반 함수 추가

검증:

```bash
.venv/bin/python -m pytest
```

결과:

```text
48 passed in 0.95s
```

## 2. Phase별 상태

| Phase | 이전 상태 | 현재 상태 | 비고 |
|---|---|---|---|
| Phase 0: 계측과 안전망 | 부분 완료 | 완료 | `wiki_cli/metrics.py`, search/query/ingest metrics hook 추가 |
| Phase 1: Source Registry | 대부분 완료 | 유지 | 기존 구현 유지 |
| Phase 1.5: Extraction/Ingest Cache | 완료 | 유지 | 기존 구현 유지 |
| Phase 2: Search Index Cache | 미구현 | 완료 | `wiki_cli/search_index.py`, `.search/index.json` 추가 |
| Phase 3: Deterministic Lint | 미구현 | 완료 | broken link, duplicate title/alias, missing frontmatter, invalid source reference |
| Phase 4: Structured Ingest Result | 부분 완료 | 추가 완료 | source page template, page별 evidence 전달 |
| Phase 5: 제한 병렬화 | 미구현 | 완료 | `WIKI_INGEST_WORKERS=1..4` |
| Phase 6: Draft Review Workflow | 미구현 | 기반 완료 | `.drafts/{job_id}` 생성/승인/삭제 함수 |

## 3. Search Index Cache

추가 파일:

- `wiki_cli/search_index.py`
- `tests/test_search_index.py`

구현 내용:

- `wiki/.search/index.json` 생성
- 파일별 `path`, `mtime_ns`, `size`, `sha256`, `title`, `aliases`, `headings`, `outgoing_links`, `plain_text_preview`, `chunks` 저장
- 변경되지 않은 파일은 재파싱하지 않음
- 파일 하나 수정 시 해당 파일만 갱신
- grep 검색은 가능하면 `rg`를 사용하고, fallback은 index payload 사용
- BM25 검색은 markdown 파일을 다시 읽지 않고 index entry의 text/chunks를 corpus로 사용

검증:

- 첫 index build에서 updated file count 확인
- 두 번째 refresh에서 `updated_files == 0`
- 파일 하나 수정 시 `updated_files == 1`
- 검색 결과와 `.search/index.json` 생성 확인

## 4. Deterministic Lint

추가 검사:

- broken wikilinks
- duplicate title/alias
- missing frontmatter
- invalid source reference

구현 방식:

- `search_index.refresh_index()`의 title/alias/link/frontmatter/source metadata를 재사용
- LLM lint 전에 deterministic issue를 먼저 수집

검증:

- 존재하지 않는 `[[Missing Page]]` 검출
- 같은 title/alias 중복 검출
- frontmatter 없는 markdown 검출

## 5. Structured Ingest 추가 최적화

구현 내용:

- 구조화 결과가 있으면 source page를 LLM 재작성 없이 template으로 생성
- entity/concept page 생성 시 전체 overview 대신 해당 slug의 evidence만 전달
- 구조화 결과가 없을 때는 기존 LLM source page 생성 흐름 유지

호출 수 변화:

테스트 fixture 기준:

| 항목 | 초기 구조화 구현 | 현재 구현 |
|---|---:|---:|
| source 분석 `call_with_file()` | 1 | 1 |
| planning `llm.call()` | 0 | 0 |
| source page 생성 `llm.call()` | 1 | 0 |
| entity page 생성 `llm.call()` | 1 | 1 |
| concept page 생성 `llm.call()` | 1 | 1 |
| 총 LLM 호출 | 4 | 3 |

## 6. 제한 병렬화

환경변수:

```bash
WIKI_INGEST_WORKERS=2
```

동작:

- entity/concept page write job을 최대 1~4 worker로 제한 실행
- 기본값은 안정성을 위해 `1`
- 값이 잘못되면 `1`로 fallback

주의:

- 로컬 Ollama에서는 worker를 크게 올리면 오히려 느려질 수 있음
- cloud model 사용 시 provider rate limit을 고려해야 함

## 7. Draft Review 기반

추가 파일:

- `wiki_cli/drafts.py`

구현 내용:

- `.drafts/{job_id}/` draft 생성
- `manifest.json` 저장
- 승인 시 draft 파일을 실제 wiki 경로로 copy
- draft 삭제 함수 제공

현재 범위:

- CLI/Ops에서 재사용 가능한 기반 함수까지 구현
- 웹 UI의 diff preview와 승인 버튼 연결은 아직 별도 작업 필요

## 8. Metrics Collector

추가 파일:

- `wiki_cli/metrics.py`

기능:

- `count(name)`
- `record(name, value)`
- `timer(name)`
- `summary()`
- `write_json(path)`

연결 지점:

- `search.search(..., metrics=metrics)`
- `run_query(..., metrics=metrics)`
- `run_ingest(..., metrics=metrics)`

기록 예:

- `search.index_refresh`
- `search.total`
- `search.result_count`
- `query.context_chars`
- `query.llm_generation`
- `ingest.structured_extract`
- `ingest.related_page_count`
- `ingest.llm_calls`

## 9. 남은 한계

- Draft review는 기반 함수만 있고 웹 UI 연결은 아직 없다.
- Search index는 BM25 객체 자체를 pickle로 저장하지 않고, index text/chunk를 재사용해 corpus 재구성 비용을 줄이는 수준이다.
- Entity/concept 병렬화는 page-level lock까지는 두지 않았다. 현재 plan이 중복 slug를 만들지 않는다는 전제에 기대고 있다.
- Metrics는 선택적 collector이며, 기본 웹 UI에 시각화되지는 않는다.

## 10. 다음 개선 제안

- `/admin` 또는 `/documents`에 draft preview/approve UI 연결
- metrics JSON 저장 옵션과 웹 job detail 표시
- source registry와 lint의 source path 검증 강화
- search index 기반 query context ranking 개선
