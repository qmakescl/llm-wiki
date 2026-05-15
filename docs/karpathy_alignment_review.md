# Karpathy LLM Wiki 구현 점검 및 개선안

> 작성일: 2026-05-14  
> 기준: Andrej Karpathy의 [LLM Wiki 메모](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f), `README.md`, `docs/`, `wiki_cli/`, `wiki_web/`

## 1. 요약

현재 프로젝트는 Karpathy 메모의 핵심 패턴을 이미 상당 부분 구현했다. 특히 `raw source`와 `wiki` 분리, `AGENTS.md` 기반 schema, `index.md`/`log.md`, ingest/query/lint 운영, Obsidian 친화 구조, CLI와 로컬 웹 UI가 모두 존재한다.

다음 단계의 초점은 새 화면을 늘리는 것보다 **위키가 오래 커져도 품질과 속도를 유지하는 운영 레이어**를 보강하는 것이다.

우선순위는 다음과 같다.

1. Claim/evidence 단위 provenance를 구조화해 각 페이지의 근거와 충돌 후보를 추적한다.
2. Ingest 중간 산출물을 JSON/YAML 구조로 고정해 중복 LLM 호출과 반복 토큰을 줄인다.
3. 검색 인덱스를 매 쿼리 재구성하지 않고 파일 변경 기반으로 캐싱한다.
4. Lint를 샘플 기반 점검에서 graph/evidence/index 기반의 전체 위키 건강 검사로 확장한다.
5. 사용자가 ingest 결과를 승인하거나 수정하는 human-in-the-loop 흐름을 만든다.

## 2. Karpathy 원문 기준 현재 구현 매핑

| Karpathy 패턴 | 현재 구현 | 평가 |
|---|---|---|
| Raw sources는 불변 source of truth | `data/{domain}/raw/` 분리, 업로드 파일 저장 | 방향 적합. 단, 원본 해시/중복/출처 메타데이터가 약함 |
| LLM이 markdown wiki 유지 | `sources/`, `entities/`, `concepts/`, `synthesis/` 생성 | 구현됨. 페이지별 근거 구조는 부족 |
| Schema 파일로 운영 규칙 고정 | 각 위키의 `AGENTS.md` 생성 | 구현됨. 다만 schema 버전/마이그레이션 개념은 없음 |
| Ingest가 여러 페이지를 업데이트 | `run_ingest()`가 source/entity/concept/index/log 갱신 | 구현됨. 직렬 LLM 호출과 자연어 overview 재사용이 병목 |
| Query 결과를 wiki에 저장 | `wiki query --save`, 웹 synthesis 저장 | 구현됨 |
| Lint로 모순, stale, orphan, missing links 검사 | `run_lint()`가 orphan/TODO/stale/LLM 샘플 검사 | 기초 구현. 전체 위키 규모에서는 약함 |
| `index.md`는 content catalog | `fs.update_index_entry()`가 섹션별 upsert | 구현됨. 검색/탐색용 메타데이터가 더 필요 |
| `log.md`는 append-only timeline | `fs.append_log()` | 구현됨. 로그 entry에 파일 해시/모델/실행시간 없음 |
| 선택적 local search engine | grep/BM25/embedding tier | 구현됨. BM25/grep은 매번 전체 재계산 |
| Obsidian graph 활용 | wiki 폴더와 wikilink 생성 | 구현됨. 링크 정합성 검증과 orphan 개선 자동화 필요 |

## 3. 부족한 기능

### P0. Evidence/provenance map

현재 페이지 frontmatter의 `sources`는 파일명 수준이다. Karpathy 메모의 핵심은 “새 자료가 기존 synthesis를 강화하거나 반박하는지”를 누적하는 것인데, 지금 구조에서는 어떤 문장이나 claim이 어떤 source의 어떤 부분에서 왔는지 추적하기 어렵다.

권장 기능:

- ingest 결과에 `claims`, `evidence`, `uncertainties`, `contradiction_candidates`를 구조 필드로 저장
- 각 entity/concept 페이지에 `## Evidence` 또는 frontmatter `claims:` 블록 추가
- 원본 파일 해시, 페이지/청크 위치, 발췌 snippet, ingest 날짜, 모델명을 함께 기록
- query 답변 citation을 `[[Page]]`뿐 아니라 source claim id까지 연결

예상 효과:

- Lint가 LLM 감상문이 아니라 claim graph를 대상으로 모순 후보를 찾을 수 있음
- 페이지 업데이트 시 전체 본문을 다시 읽지 않고 관련 claim만 비교 가능
- 장기적으로 “왜 이 페이지가 이렇게 쓰였는지”를 재현 가능

### P0. Human review/approval workflow

Karpathy는 사용자가 summary를 읽고 업데이트를 지도하는 방식을 선호한다고 적었다. 현재 웹 UI는 ingest를 바로 적용한다. 품질이 중요한 연구 위키에서는 “초안 생성 → 사용자가 승인 → wiki 반영” 흐름이 필요하다.

권장 기능:

- ingest preview 페이지: 생성될 source/entity/concept 변경 diff 표시
- 승인 전 임시 디렉터리: `.drafts/{job_id}/`
- 사용자가 entity/concept 선택을 제거하거나 이름을 수정할 수 있는 UI
- 승인 후에만 `wiki/` 반영 및 `log.md` append

### P1. Source registry

현재 중복 검사는 `sources/{slug}.md` 존재 여부 중심이다. 같은 파일이 다른 이름으로 들어오거나, 같은 stem이 하위 폴더에 중복되면 정확히 추적하기 어렵다.

권장 기능:

- `data/{domain}/sources.jsonl` 또는 `wiki/source_registry.md` 추가
- 필드: `source_id`, `filename`, `relative_path`, `sha256`, `size`, `uploaded_at`, `ingested_at`, `summary_page`, `model`
- `_find_source(data_root, slug)`의 “첫 번째 slug 매칭” 대신 source id 기반 ingest
- 원본 변경 감지와 재ingest 정책 명확화

### P1. Wiki graph health

현재 orphan 검사는 inbound wikilink만 본다. 더 유용한 graph lint는 다음을 포함해야 한다.

- 깨진 wikilink: `[[Page]]`가 실제 파일/alias와 매칭되지 않는 경우
- 중복 개념: 유사 title 또는 alias를 가진 page 후보
- hub/leaf 분석: 너무 많은 topic이 한 페이지에 몰린 경우
- missing page: 여러 페이지에서 언급되지만 별도 페이지가 없는 개념
- title 정합성: `_page_display_name()`의 Title Case가 `AI`를 `Ai`로 바꾸는 문제

### P1. Asset/image handling

Karpathy 메모는 clipped article의 이미지와 attachment를 로컬로 보존하는 팁을 포함한다. 현재 구현은 PDF/md/txt 중심이며, markdown inline image를 LLM이 별도 view하는 워크플로가 없다.

권장 기능:

- `raw/assets/` 연결 정책 확정: symlink, copy, localhost URL 중 하나
- markdown ingest 시 `![](...)` 이미지 목록 추출
- 이미지가 있는 source page에는 `## Figures` 섹션 생성
- 향후 vision model 사용 시 이미지별 caption/evidence를 claim map에 연결

### P2. Output formats

원문은 질문 답변이 markdown page, comparison table, slide deck, chart, canvas 등으로 저장될 수 있다고 본다. 현재는 synthesis markdown 중심이다.

권장 기능:

- query 저장 시 output type 선택: `note`, `comparison`, `timeline`, `deck-outline`, `chart-spec`
- synthesis frontmatter에 `question`, `answer_type`, `referenced_pages` 저장
- Marp/PowerPoint export는 별도 phase로 분리

## 4. 속도 개선안

### 4.1 Ingest 속도

가장 큰 병목은 LLM 호출 수 자체보다 같은 정보를 자연어 overview로 반복 전달하는 구조다.

현재 흐름:

1. `llm.call_with_file()`로 overview 생성
2. overview로 entity/concept 계획 생성
3. overview로 source page 생성
4. entity/concept마다 overview 일부 또는 전체 전달
5. 기존 페이지 update 시 page body와 delta prompt 사용

권장 변경:

- `overview`를 자유서술 markdown이 아니라 `StructuredIngestResult`로 고정
- source page, entity page, concept page를 구조 데이터에서 렌더링
- `_plan_related_pages()`를 별도 LLM 호출이 아니라 구조 결과의 `entities[]`, `concepts[]` 파싱으로 대체
- entity/concept page 생성은 파일 단위 충돌이 없으므로 worker 2~4개로 제한 병렬화
- LLM 호출 캐시: `sha256(file) + prompt_version + model + chunk_config`가 같으면 재사용

우선 구현 단위:

```python
class StructuredIngestResult(TypedDict):
    summary: str
    claims: list[Claim]
    entities: list[PageBrief]
    concepts: list[PageBrief]
    uncertainties: list[Uncertainty]
    evidence_by_page: dict[str, list[Evidence]]
```

### 4.2 Search/query 속도

현재 grep/BM25는 쿼리마다 markdown 전체를 읽고, BM25 corpus도 매번 만든다. embedding은 모델 singleton과 디스크 캐시가 들어가 있어 방향은 좋지만, 현재 구현은 파일 앞부분 2,000자만 embedding/hash에 사용한다. 긴 페이지에서는 검색 누락이 생길 수 있다.

권장 변경:

- `.search/index.json`에 파일 path, mtime, sha256, title, aliases, headings, outgoing_links 저장
- BM25 corpus를 파일 변경 시에만 재생성
- grep tier도 Python 전체 파일 scan 대신 ripgrep 사용 가능 시 subprocess로 위임
- embedding은 page-level 하나가 아니라 heading chunk 단위로 저장
- embedding hash는 2,000자 prefix가 아니라 chunk 전체 텍스트 기준으로 계산
- query context는 고정 `[:3000]`보다 관련 heading/chunk만 넣기

예상 효과:

- 페이지 수가 수백 개로 늘어도 query latency가 파일 수에 선형으로 매번 증가하지 않음
- 긴 concept page에서도 관련 섹션만 LLM context에 들어가 답변 품질이 좋아짐

### 4.3 Lint 속도와 정확도

현재 LLM lint는 `pages[:20]` 샘플의 앞 800자만 본다. 빠르지만 wiki 전체 건강 검사로는 약하다.

권장 변경:

- 1단계 deterministic lint: broken links, orphan, duplicate titles, stale pages, missing frontmatter
- 2단계 index 기반 후보 추출: 같은 entity/concept를 언급하는 페이지 그룹만 묶기
- 3단계 LLM contradiction check: 후보 그룹별 claim/evidence만 전달
- lint 결과를 `wiki/lint_reports/YYYY-MM-DD.md`에 저장해 추세 확인

### 4.4 Web/runtime 속도

- `IngestJob`을 메모리뿐 아니라 SQLite/JSONL에 저장해 재시작 후 상태 복구
- 긴 작업은 queue로 관리하고 동시 실행 수 제한
- LLM provider별 rate limit/backoff/retry 정책 추가
- SSE message에는 elapsed time과 stage id를 포함해 병목을 사용자에게 보여주기

## 5. 권장 로드맵

### 1주차: 빠른 체감 개선

- source registry와 sha256 중복 검사 추가
- BM25/grep 인덱스 캐시 설계 및 구현
- broken wikilink/title/alias lint 추가
- query context를 관련 heading 중심으로 축소

### 2주차: ingest 구조 개선

- `StructuredIngestResult` 도입
- `_plan_related_pages()` 호출 제거 또는 fallback화
- entity/concept별 evidence map 생성
- source/entity/concept 렌더링 prompt를 구조 입력 기반으로 재작성

### 3주차: 품질 관리

- draft ingest preview와 승인 UI 추가
- claim/evidence frontmatter 또는 별도 sidecar 파일 저장
- contradiction lint를 claim group 기반으로 변경

### 4주차 이후: 확장 기능

- 이미지/attachment ingest
- Marp/deck/chart output type
- qmd 또는 MCP 기반 외부 검색 엔진 연동 검토
- Git commit/snapshot workflow 추가

## 6. 측정 지표

개선 전후를 비교하려면 기능별 지표를 먼저 남겨야 한다.

| 영역 | 지표 |
|---|---|
| Ingest | 전체 wall-clock time, LLM 호출 수, 입력/출력 토큰 추정치, 생성 페이지 수 |
| Query | 검색 시간, LLM context 길이, 답변 생성 시간, 참조 페이지 수 |
| Search | 인덱스 build time, cache hit ratio, 검색 top-k latency |
| Lint | 검사 페이지 수, deterministic issue 수, LLM contradiction 후보 수 |
| 품질 | broken link 수, orphan page 수, source 없는 claim 수, 사용자 수정률 |

## 7. 결론

이 프로젝트는 “Karpathy 메모의 로컬 웹앱 버전”으로서 기본 골격은 이미 좋다. 부족한 부분은 UI의 양보다 **근거 추적, 변경 승인, 검색/검사 인덱스, 구조화된 ingest 산출물**이다.

가장 먼저 할 일은 `source registry + structured ingest result + search cache` 세 가지다. 이 조합은 기능 품질과 속도를 동시에 개선하고, 이후 human review와 contradiction lint를 얹을 기반이 된다.
