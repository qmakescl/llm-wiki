# llm-wiki Service Flow Review Report

> 업데이트일: 2026-05-15  
> 기준 버전: README 현재 상태, Karpathy alignment 개선 반영 후 코드  
> 범위: 웹 UI, CLI/Ops, 파일 저장 구조, ingest/query/synthesis/lint 흐름

## 1. 요약

`llm-wiki`는 개인 연구 자료를 로컬 파일시스템에 보관하고, LLM을 이용해 Obsidian 친화적인 마크다운 위키를 유지하는 로컬 웹앱 + CLI 도구다. 현재 버전은 초기 query/synthesis 중심 흐름에서 확장되어, 멀티 도메인 관리, 백그라운드 ingest, source registry, 추출 캐시, 구조화 ingest까지 포함한다.

최근 개선의 핵심은 ingest/extraction 단계다. PDF/text 원본은 `data/{domain}/raw/`에 저장되고, source hash 기반 registry와 캐시를 통해 중복 ingest와 재시도 비용을 줄인다. 구조화 ingest가 성공하면 entity/concept 계획을 위한 별도 LLM 호출을 생략한다.

검증 상태:

```bash
.venv/bin/python -m pytest
```

결과: 38개 테스트 통과.

## 2. 시스템 아키텍처 개요

| Layer | 구성 | 역할 |
|---|---|---|
| Frontend | Jinja2, Pico CSS, HTMX, SSE | 서버 렌더링 기반 UI, 부분 갱신, 진행 로그 스트리밍 |
| Web Backend | FastAPI, asyncio | 라우팅, 업로드, 백그라운드 task, SSE 연결 관리 |
| Ops/Core | `wiki_cli/ops/*` | init, ingest, query, lint의 실제 비즈니스 로직 |
| LLM Adapter | `wiki_cli/llm.py` | LiteLLM 기반 provider 추상화, 파일 읽기, 청킹, 캐시 |
| Storage | Local filesystem | `wiki/` 마크다운 위키, `data/` 원본/registry/cache |
| Search | `wiki_cli/search.py` | grep/BM25/embedding tier 검색 |

## 3. 데이터 저장 구조

도메인별 저장 구조는 `workspace_root` 아래에서 wiki와 data를 분리한다.

```text
{workspace_root}/
├── wiki/{domain}/
│   ├── AGENTS.md
│   ├── index.md
│   ├── log.md
│   ├── sources/
│   ├── entities/
│   ├── concepts/
│   └── synthesis/
└── data/{domain}/
    ├── raw/
    ├── sources.jsonl
    └── .cache/
        ├── extracted_text/
        └── llm_results/
```

주요 의미:

- `wiki/{domain}/`: Obsidian에서 열 수 있는 마크다운 vault 성격의 폴더
- `data/{domain}/raw/`: 업로드한 PDF, txt, md 원본 저장 위치
- `data/{domain}/sources.jsonl`: source id, relative path, sha256, size, ingest 상태 기록
- `data/{domain}/.cache/extracted_text/`: PDF/text 추출 결과 캐시
- `data/{domain}/.cache/llm_results/`: 같은 파일/프롬프트/config의 `call_with_file()` 결과 캐시

## 4. 주요 서비스 흐름

### 4.1 문서 업로드 흐름

1. 사용자가 `/documents`에서 파일을 업로드한다.
2. `wiki_web/routers/documents.py`가 활성 도메인의 `data_root`를 조회한다.
3. `fs.resolve_upload_path()`가 파일명을 sanitize하고 확장자를 검증한다.
4. 파일은 `data/{domain}/raw/{filename}`에 저장된다.
5. 같은 이름이 이미 있으면 `<stem>__<YYYYMMDD-HHMMSS>.<ext>` 형식으로 저장된다.
6. `source_registry.register_uploaded_source()`가 `sources.jsonl`에 metadata를 기록한다.

지원 확장자:

- `.pdf`
- `.md`
- `.txt`

현재 특징:

- 업로드 시점에는 아직 위키 페이지를 만들지 않는다.
- 원본 파일은 `wiki/`가 아니라 `data/raw/`에 저장된다.
- 경로 traversal과 dotfile 업로드는 차단한다.

### 4.2 Ingest 흐름

Ingest는 업로드된 원본을 위키 페이지로 변환하는 핵심 흐름이다.

1. 사용자가 `/documents`에서 특정 파일의 ingest를 시작한다.
2. 웹 라우터는 `IngestJob`을 만들고 `asyncio.create_task()`로 백그라운드 작업을 시작한다.
3. 실제 작업은 `asyncio.to_thread(run_ingest, ...)`로 thread에서 실행된다.
4. `run_ingest()`는 먼저 중복 여부를 확인한다.
   - `wiki/sources/{slug}.md` 존재 여부
   - `sources.jsonl`의 sha256 기반 중복 ingest 여부
5. 첫 source 분석은 `structured_ingest.extract_from_file()`을 통해 JSON 구조로 시도한다.
6. 구조화 파싱 성공 시:
   - compact markdown overview를 렌더링한다.
   - `entities[]`, `concepts[]`에서 page plan을 바로 만든다.
   - `_plan_related_pages()` LLM 호출을 생략한다.
7. 구조화 파싱 실패 시:
   - 기존 overview 기반 흐름으로 fallback한다.
   - `_plan_related_pages()`를 호출해 entity/concept 계획을 얻는다.
8. source summary page를 생성한다.
9. `index.md`를 갱신한다.
10. entity/concept page를 생성하거나 업데이트한다.
11. `log.md`에 ingest 기록을 append한다.
12. `sources.jsonl`에 `ingested_at`, `summary_page`, `model`을 기록한다.

### 4.3 PDF 읽기 및 캐시 흐름

사용자에게는 “소스 파일 읽는 중...”으로 보이지만, 내부에서는 여러 단계가 수행된다.

1. 파일 전체 sha256 계산
2. `llm_results` 캐시 조회
3. `extracted_text` 캐시 조회
4. PDF인 경우 `pypdf.PdfReader`로 전체 페이지 텍스트 추출
5. chunk strategy 적용
6. 청크가 여러 개면 청크별 evidence 추출 LLM 호출
7. 최종 구조화 ingest LLM 호출 또는 통합 호출

속도가 오래 걸리는 주된 이유:

- 큰 PDF의 sha256 계산과 텍스트 추출
- PDF 레이아웃이 복잡할 때 `pypdf` 처리 시간 증가
- 청크 수가 많을 때 반복 LLM 호출 증가
- 로컬 Ollama 모델 사용 시 LLM 응답 속도 제한

캐시 제어:

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `WIKI_EXTRACT_CACHE` | on | `0`, `false`, `no`, `off`면 추출 텍스트 캐시 비활성화 |
| `WIKI_LLM_FILE_CACHE` | on | `0`, `false`, `no`, `off`면 `call_with_file()` 결과 캐시 비활성화 |

### 4.4 Query & Answer 흐름

1. 사용자가 `/query`에서 질문을 제출한다.
2. `wiki_web/routers/query.py`가 `ProgressChannel`과 job id를 생성한다.
3. `run_query()`가 thread에서 실행된다.
4. `index.md`를 읽어 위키 개요를 확보한다.
5. `search.search()`로 관련 페이지 top-k를 찾는다.
6. 검색 결과 페이지 내용을 context로 묶어 LLM에 전달한다.
7. 답변은 `[[PageName]]` 형태의 wikilink citation을 포함하도록 유도된다.
8. 진행 메시지는 SSE로 전송된다.
9. 최종 답변은 `render_answer()`를 거쳐 HTML로 렌더링되고 `done` 이벤트로 UI에 전달된다.

현재 한계:

- LLM token-level streaming은 아직 없다.
- 답변은 생성 완료 후 한 번에 렌더링된다.
- 검색 tier는 pluggable이지만 grep/BM25 index cache는 아직 미구현이다.

### 4.5 Synthesis 관리 흐름

1. Query 결과에서 저장 버튼을 누르면 `/query/save`로 raw answer를 전달한다.
2. LLM을 재호출하지 않고 `_save_synthesis()`가 `wiki/synthesis/`에 markdown 파일을 저장한다.
3. `fs.write_page()`를 통해 frontmatter 정책을 통일한다.
4. `/synthesis`는 `synthesis/` 폴더의 파일을 최신순으로 보여준다.
5. 항목 클릭 시 HTMX로 미리보기 partial을 로드한다.
6. 삭제 요청은 해당 markdown 파일을 로컬 파일시스템에서 제거한다.

### 4.6 Markdown 렌더링 흐름

`wiki_web/render.py`가 query/synthesis preview의 공통 렌더링을 담당한다.

1. `_preprocess_md()`가 LLM 출력의 리스트 렌더링 문제를 줄이기 위해 필요한 빈 줄을 삽입한다.
2. Python `markdown` 라이브러리의 `extra`, `toc` 확장으로 HTML 변환을 수행한다.
3. `[[...]]` wikilink를 HTML badge/span으로 바꾼다.
   - `[[파일명.md]]`: source link 스타일
   - `[[Entity Name]]`: entity tag 스타일

주의:

- 렌더링된 wikilink가 실제 파일/alias와 매칭되는지 검증하는 단계는 아직 없다.
- 이 검증은 향후 deterministic lint 또는 search index phase에서 처리하는 것이 자연스럽다.

### 4.7 Lint 흐름

현재 lint는 `wiki_cli/ops/lint.py`에서 다음을 수행한다.

- orphan page 검사
- TODO/unverified marker 검사
- stale page 검사
- LLM 기반 contradiction/gap 샘플 검사

현재 한계:

- broken wikilink, duplicate title/alias, missing frontmatter 검사는 아직 미구현이다.
- LLM contradiction check는 일부 페이지 excerpt 샘플 기반이다.
- search index가 생기면 deterministic lint를 더 빠르고 정확하게 구현할 수 있다.

## 5. 핵심 컴포넌트 요약

| Component | Path | 역할 |
|---|---|---|
| App Factory | `wiki_web/app.py` | FastAPI 앱 생성, 템플릿 설정, 라우터 등록 |
| Config | `wiki_web/config.py` | 멀티 도메인 설정, wiki/data root 계산, runtime env 적용 |
| Documents Router | `wiki_web/routers/documents.py` | 파일 업로드, raw 파일 목록, ingest job 시작, SSE stream |
| Query Router | `wiki_web/routers/query.py` | 질문 제출, query progress SSE, 답변 저장 |
| Synthesis Router | `wiki_web/routers/synthesis.py` | synthesis 목록, 미리보기, 삭제 |
| Progress | `wiki_web/progress.py` | IngestJob/ProgressChannel, SSE 재연결 버퍼 |
| Render Utility | `wiki_web/render.py` | Markdown 변환, wikilink badge 렌더링 |
| Ingest Ops | `wiki_cli/ops/ingest.py` | source/entity/concept/index/log 갱신 |
| Query Ops | `wiki_cli/ops/query.py` | 검색, context 구성, LLM 답변 생성, synthesis 저장 |
| Lint Ops | `wiki_cli/ops/lint.py` | 위키 건강 검사 |
| LLM Adapter | `wiki_cli/llm.py` | LiteLLM 호출, PDF/text 읽기, 청킹, 캐시 |
| Source Registry | `wiki_cli/source_registry.py` | source hash registry, 중복 ingest 감지 |
| Structured Ingest | `wiki_cli/structured_ingest.py` | JSON 구조화 추출 prompt, parser, overview 렌더링 |
| Search | `wiki_cli/search.py` | grep/BM25/embedding 검색 |
| FS Helpers | `wiki_cli/fs.py` | 파일명 sanitize, page read/write, index/log 갱신 |

## 6. 현재 개선 상태

완료:

- pytest 기본 수집 범위 안정화
- source registry 도입
- sha256 기반 중복 ingest 차단
- extracted text cache 도입
- `call_with_file()` result cache 도입
- 구조화 ingest 1차 도입
- 구조화 성공 시 entity/concept planning LLM 호출 생략

부분 완료:

- 구조화 ingest는 page plan 생략까지 완료됐지만, source page template 렌더링과 page별 evidence 직접 전달은 남아 있다.
- embedding tier는 모델/문서 embedding 캐시가 있으나, grep/BM25 search index cache는 아직 없다.

미착수:

- deterministic broken link lint
- duplicate title/alias lint
- source page template rendering
- entity/concept 제한 병렬화
- draft review workflow
- server restart 후 ingest job 상태 복구

## 7. 주요 리스크와 개선 제안

### 7.1 Ingest 진행 메시지 세분화

현재 “소스 파일 읽는 중...” 단계가 PDF hash, PDF 추출, cache lookup, 청킹, LLM 분석을 모두 포함해 보일 수 있다. 사용자는 어떤 단계가 느린지 알기 어렵다.

권장:

- `PDF 해시 계산 중`
- `추출 캐시 확인 중`
- `PDF 텍스트 추출 중`
- `청크 evidence 추출 중`
- `구조화 분석 생성 중`

처럼 progress event를 더 세분화한다.

### 7.2 Source page template rendering

구조화 결과가 이미 `summary`, `claims`, `entities`, `concepts`를 포함하므로 source page는 LLM 재작성 없이 template으로 생성할 수 있다.

기대 효과:

- source page 생성 LLM 호출 1회 절감 가능
- source page 형식 안정화
- 구조화 결과가 그대로 provenance로 남음

### 7.3 Page별 evidence 전달

현재 entity/concept 생성은 compact overview 기반이다. `StructuredIngestResult`의 `evidence[]`를 page별로 직접 전달하면 prompt 크기를 줄일 수 있다.

기대 효과:

- entity/concept page 생성 prompt 토큰 감소
- 관련 없는 overview 정보로 인한 hallucination 감소

### 7.4 Search index cache

query마다 markdown을 재스캔하는 비용은 위키가 커질수록 커진다.

권장:

- `wiki/.search/index.json`
- path, mtime, sha256, title, aliases, headings, outgoing_links 저장
- BM25 corpus cache
- lint와 search가 같은 index 사용

### 7.5 Deterministic lint

LLM 기반 lint 전에 확정적으로 잡을 수 있는 문제를 먼저 검사해야 한다.

권장:

- broken wikilink
- duplicate title/alias
- missing frontmatter
- invalid source reference
- stale source registry mismatch

## 8. 결론

현재 서비스 흐름은 초기 query/synthesis 위주의 구조에서, source provenance와 ingest 성능 개선을 포함하는 지식베이스 운영 도구로 확장되었다. 특히 source registry, 추출 캐시, 구조화 ingest는 Karpathy LLM Wiki 패턴에 맞게 장기 운영성을 높이는 방향이다.

다음으로 가장 가치가 큰 작업은 source page template rendering과 page별 evidence 전달이다. 이 두 가지는 검색 개선보다 ingest 속도와 품질에 직접적인 효과가 있고, 이미 도입된 `StructuredIngestResult`를 자연스럽게 활용할 수 있다.
