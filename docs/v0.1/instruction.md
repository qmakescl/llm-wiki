# llm-wiki v0.1 코드베이스 인스트럭션

> 용도: 코드베이스 점검·리뷰·신규 작업자 온보딩용 레퍼런스
> 작성 기준: pyproject `version = "0.2.0"`, `§5.B` 등 [interim_report.md](interim_report.md) 수정 반영 완료 상태
> 업데이트: 2026-04-21

---

## 1. 프로젝트 개요

- **제품**: LLM이 유지·관리하는 개인 연구 위키 (Obsidian Vault 호환)
- **러너**: 비기술자도 원클릭 실행 (`launch.sh` / `launch.bat`) → FastAPI + HTMX 웹앱
- **이중 진입**: CLI (`wiki ...`) 와 Web (`http://localhost:8000`) — 도메인 로직(ops) 100% 공유
- **파이썬**: 3.11+ , 의존성 관리는 `pyproject.toml` + `uv.lock`
- **핵심 의존성**: `litellm`(모델 추상화), `click`(CLI), `fastapi`+`uvicorn`(웹), `python-frontmatter`, `pypdf`, `jinja2`, `markdown`, `rich`

---

## 2. 디렉터리 구조

```
llm-wiki/
├── pyproject.toml           # 0.2.0 — console script "wiki" 등록
├── launch.sh / launch.bat   # 비기술자 원클릭 실행
├── wiki_cli/                # 도메인 로직 (CLI + 웹 공용)
│   ├── main.py              # click CLI 엔트리 ("wiki" 명령)
│   ├── llm.py               # litellm 어댑터, 청킹, PDF 추출
│   ├── search.py            # Grep / BM25 / Embedding 3-티어 검색
│   ├── fs.py                # 파일 I/O + index 업서트 + 로그
│   └── ops/                 # 연산 파이프라인
│       ├── init.py          # run_init — 위키 스캐폴드
│       ├── ingest.py        # run_ingest — 6단계 LLM 파이프라인
│       ├── query.py         # run_query — 검색 + 답변 + synthesis 저장
│       └── lint.py          # run_lint — 고아/TODO/stale/LLM 검사
├── wiki_web/                # FastAPI 래퍼
│   ├── __main__.py          # `python -m wiki_web` → uvicorn + 브라우저
│   ├── app.py               # create_app + Jinja2 globals 주입
│   ├── config.py            # ~/.config/llm-wiki/config.json 입출력
│   ├── progress.py          # IngestJob + ProgressChannel (SSE 버퍼 + 재연결)
│   ├── render.py            # 마크다운 → HTML + [[위키링크]] 아이콘 치환
│   ├── routers/             # 엔드포인트별 라우터
│   │   ├── wiki.py          # "/" 대시보드 + "/init"
│   │   ├── documents.py     # "/documents" 파일 목록/업로드/ingest
│   │   ├── query.py         # "/query" Q&A + 저장
│   │   ├── synthesis.py     # "/synthesis" 저장된 답변 관리
│   │   ├── lint.py          # "/lint" 건강 검사
│   │   ├── settings.py      # "/settings" 모델/키/청킹
│   │   └── admin.py         # "/admin" 도메인 CRUD + workspace
│   └── templates/           # Jinja2 + HTMX (base/dashboard/... + partials/)
└── docs/v0.1/               # ARCHITECTURE / interim_report / resolve / instruction(본문서)
```

파일시스템 레이아웃 (런타임 생성):

```
{workspace_root}/               ← 설정에 저장되는 공용 루트 (예: ~/llm-wikis)
├── wiki/{folder}/              ← Obsidian Vault로 직접 열 수 있는 마크다운 모음
│   ├── AGENTS.md               ← 에이전트 헌법 (도메인·규칙·형식 명시)
│   ├── index.md                ← 페이지 인덱스 (Pages 카운트 + 섹션 표 4개)
│   ├── log.md                  ← append-only 타임라인
│   ├── sources/{slug}.md       ← 소스 문서 요약
│   ├── entities/{Display}.md   ← 인물/모델/데이터셋/기관
│   ├── concepts/{Display}.md   ← 개념 심층 페이지
│   └── synthesis/{qslug}.md    ← 저장된 Q&A
└── data/{folder}/
    └── raw/
        ├── papers/
        ├── articles/
        └── assets/
```

---

## 3. 계층 아키텍처

```
┌───────────────────────── 사용자 ─────────────────────────┐
│  브라우저                                  터미널         │
│     │                                         │           │
│  launch.sh                                 wiki <cmd>     │
│     ▼                                         ▼           │
│  python -m wiki_web                       wiki_cli/main.py│
│     │                                         │           │
│  ┌──┴───── wiki_web (FastAPI) ──────┐   ┌─────┴─────┐     │
│  │ app.py / routers/ / templates/   │   │ click cli │     │
│  │ progress.py / render.py          │   │           │     │
│  └────────────┬─────────────────────┘   └─────┬─────┘     │
│               │  asyncio.to_thread(...)       │           │
│               └──────────────┬─────────────────┘           │
│                              ▼                             │
│              wiki_cli.ops.{init,ingest,query,lint}         │
│              wiki_cli.{llm, search, fs}                    │
│                              ▼                             │
│                   파일시스템 (wiki_root / data_root)       │
└────────────────────────────────────────────────────────────┘
```

**원칙**: 웹 라우터는 얇은 래퍼. 모든 비즈니스 로직은 `wiki_cli/ops/*.py` 의 `run_*()` 함수에 있고, 웹은 `asyncio.to_thread(run_*, ..., callback)` 으로 그대로 호출. CLI와 Web의 동작 동등성이 이 원칙으로 보장된다.

---

## 4. 데이터 모델

### 4.1 설정 파일 `~/.config/llm-wiki/config.json`

```jsonc
{
  "workspace_root": "/Users/me/llm-wikis",  // wiki/, data/ 공용 부모
  "domains": [
    {
      "id": "fb922e6c",                     // 8자 UUID prefix
      "name": "AI 연구",
      "folder": "ai_research"               // wiki/{folder}, data/{folder}
    }
  ],
  "active_domain_id": "fb922e6c",

  "model": "claude-sonnet-4-20250514",      // "" → 자동 감지
  "search_tier": "grep",                    // grep | bm25 | embedding
  "ollama_base_url": "http://localhost:11434",
  "openai_api_key": "",
  "anthropic_api_key": "",

  "chunk_strategy": "section",              // section | fixed | none
  "chunk_size": 500,
  "chunk_overlap": 100
}
```

**주요 헬퍼** (`wiki_web/config.py`):

| 함수 | 반환 / 동작 |
|------|-------------|
| `load() -> dict` | 파일 읽기 + DEFAULTS 병합 + `_migrate()` 적용 |
| `save(cfg)` | JSON 저장 (부모 디렉터리 자동 생성) |
| `apply_env(cfg)` | cfg 값을 `WIKI_MODEL`, `WIKI_SEARCH`, `WIKI_CHUNK_*`, `OPENAI_API_KEY` 등 env로 내보냄 — ops 레이어는 env만 읽으므로 CLI·Web 공용 |
| `get_active_domain(cfg?) -> dict?` | active_id 일치 도메인 (없으면 첫 번째) |
| `get_wiki_root(cfg?) -> Path` | `ws_root/wiki/{folder}` |
| `get_data_root(cfg?) -> Path` | `ws_root/data/{folder}` |
| `add_domain(name, folder) -> dict` | 새 도메인 추가 + 최초면 active 지정 |
| `switch_domain(id)` | active 전환 + `apply_env` |
| `update_workspace_root(str)` | workspace_root 업데이트 |
| `wiki_is_initialized(root?) -> bool` | `AGENTS.md` 존재 여부 |

**마이그레이션** (`_migrate`):
- 1차: 구형 최상단 `wiki_root` → `domains[0]` 이동
- 2차: `domains[i].wiki_root`(절대경로) → `workspace_root` + `domains[i].folder` 로 분리

### 4.2 페이지 frontmatter (YAML)

```yaml
---
title: Agentic AI              # 필수 — Obsidian 위키링크 표시 이름
type: entity | concept | source | synthesis
tags: [llm, agent]
sources: ["paper-x.pdf"]       # source 페이지는 원본 파일명
aliases: [Agentic AI]          # title 기반 자동 생성 (fs.write_page)
created: 2026-04-21            # 자동 (기존 값 유지)
updated: 2026-04-21            # 매 저장마다 today로 갱신
---
```

`fs.write_page(path, meta, body)`:
- `created` 가 없으면 today 로 세팅, `updated` 는 항상 today
- `title` 존재 + `aliases` 미존재면 `aliases: [title]` 자동 삽입 → Obsidian 위키링크 해결 보장

### 4.3 `index.md` 형식

```markdown
# Wiki index
Last updated: 2026-04-21 | Pages: 12 | Sources: 3

## Sources
| Page | Description |
|------|-------------|
| [paper-x](sources/paper-x.md) | 요약 문장 |

## Entities
| Page | Description |
|------|-------------|
| [Transformer Architecture](entities/Transformer Architecture.md) | ... |

## Concepts
| Page | Description |
|------|-------------|

## Synthesis
| Page | Description |
|------|-------------|
```

`fs.update_index_entry(root, page_path, title, desc)`:
- 섹션은 경로 첫 세그먼트(`sources/entities/concepts/synthesis`) 로 결정
- `_upsert_index_row()`: 이미 해당 파일 rel이 있는 행은 교체, 없으면 해당 섹션 마지막에 삽입
- `_refresh_index_header()`: Pages / Sources 카운트 재계산
- 행 삽입 로직은 `saw_section` 플래그로 섹션을 한 번이라도 만났으면 삽입 (§5.B 수정 반영)

### 4.4 `log.md` 형식 (append-only)

```markdown
# Wiki log

## [2026-04-21] init | Wiki created
- Domain: initialised

## [2026-04-21] ingest | Attention Is All You Need
- Source: raw/attention.pdf
- Summary page: sources/attention.md
- Overview: ...

## [2026-04-21] query | what is attention
- References: entities/Transformer.md, concepts/Self Attention.md
- Saved: wiki/synthesis/what-is-attention.md
```

`fs.append_log(root, entry)` 만 사용 — 기존 내용 덮어쓰기 금지.

### 4.5 Ingest Job / Progress Channel (인메모리)

`wiki_web/progress.py` — 전역 dict 기반 스토어, 서버 프로세스 수명 동안 유지.

| 클래스 | 용도 |
|--------|------|
| `IngestJob(id, filename, domain_name)` | `messages: list[str]` 누적 버퍼 + `_waiters: list[Queue]` 다중 SSE 연결. `status`: running/done/failed |
| `ProgressChannel()` | query 라우터용 경량 채널 — 누적 없이 실시간만 |

**재연결 시나리오** (ingest): SSE 끊김 → asyncio Task는 계속 진행 → 메시지 누적 → 재연결 시 `stream()` 이 `messages[offset:]` 부터 즉시 전송 → 이후 실시간 대기.

`cleanup_old_jobs(max_done=30)`: done/failed 작업 30개 초과분 삭제.

---

## 5. 기능 명세

### 5.1 CLI (`wiki <cmd>`)

| 명령 | 인자 | 동작 |
|------|------|------|
| `wiki init [DIR] -d "domain"` | DIR (기본 cwd) | `DIR/wiki` + `DIR/data` 스캐폴드 생성. 성공 후 `config.json` 에 도메인 자동 등록 + active 전환 (§5.E 반영) |
| `wiki ingest PATH [-m MODEL] [-y]` | PATH 필수 | 소스 1개 ingest. 중복(sources/{slug}.md 존재) 시 `DuplicateSourceError` |
| `wiki query "..." [-m MODEL] [-s]` | 질문 (여러 단어 가능) | 위키 검색 + LLM 답변 + 선택적 synthesis 저장 |
| `wiki lint [-m MODEL] [--fix]` | — | 4종 검사 실행 + rich 테이블 출력 |

**공통**: 모든 명령은 실행 전 `_apply_saved_config()` → config.json env 주입. `find_wiki_root()` 는 cwd 상위에서 `AGENTS.md` 탐색, 실패 시 `cfg.get_wiki_root()` 폴백 (§5.A 반영).

### 5.2 Web 엔드포인트

| 경로 | 메서드 | 라우터 | 기능 |
|------|--------|--------|------|
| `/` | GET/POST | wiki.py | 대시보드 / 최초 init (`/init`) |
| `/documents` | GET | documents.py | raw/ 파일 목록 + 실행 중 jobs 패널 |
| `/documents/upload` | POST | documents.py | 다중 파일 → `data/{folder}/raw/` 저장, file_row HTML 조각 반환 |
| `/documents/ingest/{slug}` | POST | documents.py | asyncio Task로 ingest 시작 + SSE 리스너 HTML 반환 |
| `/documents/ingest/{job_id}/stream` | GET | documents.py | SSE — 누적 로그 + 실시간 + `done` 이벤트 |
| `/documents/jobs` | GET | documents.py | 실행중/최근완료 jobs_panel 프래그먼트 (HTMX 폴링 4초) |
| `/query` | GET/POST | query.py | 질문 제출 → SSE 리스너 HTML |
| `/query/{job_id}/stream` | GET | query.py | SSE progress + `event: done` 에 query_result.html |
| `/query/save` | POST | query.py | LLM 재호출 없이 `_save_synthesis` 만 실행 |
| `/query/ask` | POST | query.py | 동기식 (스트리밍 없이 결과 반환) |
| `/synthesis` | GET | synthesis.py | 저장된 답변 목록 (mtime 역순) |
| `/synthesis/{slug}` | GET | synthesis.py | 답변 미리보기 HTML 부분 |
| `/synthesis/{slug}` | DELETE | synthesis.py | 파일 삭제 |
| `/lint` | GET | lint.py | 검사 페이지 |
| `/lint/run` | POST | lint.py | `_collect_issues()` → lint_result.html |
| `/settings` | GET/POST | settings.py | 모델/키/검색/청킹 설정 |
| `/settings/browse` | GET | settings.py | 디렉터리 브라우저 JSON (workspace root 선택용) |
| `/settings/test-model` | GET | settings.py | "OK" 1단어 응답 호출 — 모델 연결 테스트 |
| `/admin` | GET | admin.py | 도메인 CRUD + workspace + 설정 통합 |
| `/admin/domains/add` | POST | admin.py | 도메인 생성 (folder slug 자동 + 중복 회피) |
| `/admin/domains/{id}/activate` | POST | admin.py | active 전환 |
| `/admin/domains/{id}/delete` | POST | admin.py | 제거 (파일시스템은 보존) |
| `/admin/domains/{id}/rename` | POST | admin.py | 이름 변경 + folder rename + `shutil.move` 로 wiki/data 디렉터리 이동 |
| `/admin/domains/{id}/init` | POST | admin.py | 해당 도메인 위키 초기화 (`reset=1` 시 기존 삭제 후 재생성) |
| `/admin/workspace/update` | POST | admin.py | workspace_root 변경 |
| `/admin/settings` | POST | admin.py | 설정 저장 (settings.py 와 동일 필드) |

### 5.3 Jinja2 템플릿

| 페이지 | 부분(partials) |
|--------|----------------|
| `base.html` | 네비게이션 + 도메인 선택기 (globals: `get_all_domains`, `get_active_domain_id`) |
| `dashboard.html` | 대시보드 (stats + recent log) |
| `documents.html` | 파일 목록 + 업로드 + jobs 폴링 | `file_row`, `ingest_progress`, `jobs_panel` |
| `query.html` | 질문 폼 | `query_progress`, `query_result` |
| `synthesis.html` | 저장된 답변 리스트 | `synthesis_preview` |
| `lint.html` | 검사 결과 | `lint_result` |
| `settings.html`, `admin.html` | 설정 / 관리 | — |

---

## 6. 데이터 흐름

### 6.1 Init

```
run_init(wiki_root, data_root, domain)
  ├─ AGENTS.md   생성 (도메인 + 규칙 + 구조 + 규칙)
  ├─ wiki/{sources,entities,concepts,synthesis}/.gitkeep
  ├─ data/raw/{papers,articles,assets}/.gitkeep
  ├─ index.md    (Pages:0, 빈 표 4개)
  └─ log.md      (init 엔트리)
```

### 6.2 Ingest (6단계)

```
run_ingest(wiki_root, source, model, progress_callback)
  ├─ 중복 검사 → DuplicateSourceError
  ├─ Step 1  소스 읽기 + overview (llm.call_with_file)
  │     PDF → pypdf / MD · TXT → read_text
  │     청킹: section(헤더기반) | fixed(크기+overlap) | none
  │     len > _PDF_MAX_CHARS(60000) 시 앞부분만 처리 + 경고
  │     청크 N개 → 각각 요약 → 통합 synthesis
  │     _MAX_CHUNKS(20) 초과 시 인접 청크 균등 병합
  ├─ Step 2  _plan_related_pages (llm.call)
  │     "ENTITIES:" / "CONCEPTS:" 섹션에서 (action, slug) 파싱
  │     slug → display_name = slug.replace("-"," ").title()
  ├─ Step 3  소스 요약 페이지 작성
  │     계획된 이름을 프롬프트에 주입 (위키링크 일치 보장)
  │     _parse_llm_page: ```yaml 블록 / bare --- 양형식 지원
  │     → wiki/sources/{slug}.md (frontmatter + aliases 자동)
  ├─ Step 4  index.md 업데이트 (fs.update_index_entry)
  ├─ Step 5  entity / concept 페이지 작성 (_write_or_update_page × N)
  │     파일명 = {display_name}.md (Obsidian [[위키링크]] 직결)
  │     이미 존재 시 create→update 자동 전환, legacy slug.md 폴백
  │     title 필드 강제로 display_name 고정
  └─ Step 6  log.md 엔트리 append
```

`progress_callback`:
- CLI: `None` → `rich.Progress` 스피너
- Web: `job.emit` → 메시지 버퍼 + SSE push

### 6.3 Query

```
run_query(wiki_root, question, model, save, progress_callback) -> str
  ├─ Step 1  search.read_index(wiki_dir)
  ├─ Step 2  search.search(question, top_k=6)
  │     WIKI_SEARCH env로 티어 선택:
  │     grep      — 단어 카운트 기반 (기본, 의존성 없음)
  │     bm25      — rank_bm25 (옵션)
  │     embedding — sentence-transformers MiniLM (옵션)
  │     설치 안됨 시 grep으로 폴백 + warning
  ├─ Step 3  _build_context: 각 페이지 앞 3000자 + score 발췌
  ├─ Step 4  llm.call (prompt에 AGENTS.md + index + context 주입, max_tokens=2048)
  ├─ Step 5 (선택)  _save_synthesis
  │     slug = question_to_slug (lowercase, 60자 제한)
  │     → wiki/synthesis/{slug}.md + index 업데이트
  │     CLI: --save 플래그 or _is_notable(answer) → 대화형 확인
  │     Web: 폼 save=true or /query/save 별도 엔드포인트
  └─ Step 6  log.md 엔트리

  CLI: rich.Markdown 콘솔 출력
  Web: render_answer(raw)
        - _preprocess_md: 볼드 단락 뒤 리스트에 빈줄 삽입 (파이썬 markdown 버그 우회)
        - markdown.markdown(..., extensions=["extra","toc"])
        - [[파일.md]] → wiki-source-btn SVG (출처 버튼)
        - [[Entity Name]] → wiki-entity-tag SVG (엔티티 태그)
        SSE `event: done` 에 query_result.html multi-line data:
```

### 6.4 Lint

```
run_lint(wiki_root, model, auto_fix)
  ├─ _check_orphans   — 위키링크 역참조 집합 대비 page.stem 비교
  │                      양쪽 모두 .lower().replace(" ","-") 정규화 (§5.C 반영)
  │                      synthesis/ 는 제외
  ├─ _check_todos     — "<!-- TODO: verify -->" / "TODO: verify" 스캔
  ├─ _check_stale     — frontmatter.updated > 90일
  └─ _check_with_llm  — 샘플 20개 페이지 앞 800자 → LLM에 모순·누락 질의
                          "no issues" 포함 시 비어있음 판정

  CLI: rich.Table
  Web: _collect_issues(root, model) → severity 정렬 → lint_result.html
```

---

## 7. 주요 환경변수

| 변수 | 기본 | 의미 |
|------|------|------|
| `WIKI_MODEL` | (없음) | 모델 override — 최우선. `:` 포함 & `/` 없음 시 `ollama/` 자동 prefix |
| `WIKI_SEARCH` | `grep` | 검색 티어: `grep` / `bm25` / `embedding` |
| `WIKI_OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama 서버 주소 (`ollama/*` 모델 호출 시 `api_base`) |
| `WIKI_CHUNK_STRATEGY` | `section` | 청킹 전략: `section` / `fixed` / `none` |
| `WIKI_CHUNK_SIZE` | `500` | `fixed` 모드 글자 수 |
| `WIKI_CHUNK_OVERLAP` | `100` | `fixed` 모드 오버랩 글자 수 |
| `WIKI_MAX_CHUNKS` | `20` | 청크 상한 (초과 시 균등 병합) |
| `WIKI_PDF_MAX_CHARS` | `60000` | 단일 호출 시 텍스트 최대 길이 (초과 앞부분만) |
| `WIKI_LLM_TIMEOUT` | `1200` | LLM 호출 타임아웃(초) — 대형 Ollama 대응 |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | — | 클라우드 모델용 |

모델 선택 우선순위 (`llm.default_model`):
`WIKI_MODEL` env > Ollama 도달 가능 (`/api/tags` 1초 타임아웃) → `ollama/llama3` > `_CLOUD_FALLBACK = claude-sonnet-4-20250514`

---

## 8. CLI vs Web 동등성 요약

| 항목 | 상태 |
|------|------|
| wiki_root 해석 | CLI는 cwd→config 폴백, Web은 `cfg.get_wiki_root()` — §5.A 수정 이후 **동등** |
| 설정 주입 | 양쪽 모두 `cfg.apply_env()` 사용 → env 기반 — **동등** |
| Ingest 파이프라인 | 동일 `run_ingest`. 진행표시만 CLI=rich, Web=SSE |
| Query 파이프라인 | 동일 `run_query`. 답변 렌더링만 CLI=rich.Markdown, Web=render_answer HTML |
| 저장 방식 | 동일 `_save_synthesis` |
| Init | 양쪽 모두 `run_init` + config.json 도메인 등록 (§5.E 수정 이후 **동등**) |
| 모델 테스트 | `/settings/test-model` 단일화 (§5.F 수정) |

---

## 9. 실행 방법

```bash
# (1) 원클릭 (브라우저 자동 실행)
./launch.sh                     # macOS / Linux
launch.bat                      # Windows

# (2) 수동 개발
pip install -e .
python -m wiki_web              # http://localhost:8000

# (3) CLI
wiki init ~/my-wiki -d "deep learning research"
wiki ingest ~/my-wiki/data/raw/papers/attention.pdf
wiki query "What is self-attention?" --save
wiki lint
```

설정 파일은 `~/.config/llm-wiki/config.json` 한 곳이며, 웹 UI 수정과 CLI 실행이 같은 파일을 공유.

---

## 10. 확장 지점

| 영역 | 파일 | 확장 방법 |
|------|------|-----------|
| 새 LLM / 호스팅 | `wiki_cli/llm.py` | litellm 포맷 모델 ID 추가. Ollama 는 `:` 포함 시 자동 처리 |
| 새 검색 티어 | `wiki_cli/search.py` | `search()` 에 분기 추가 + `_xxx_search()` 구현 + DEFAULTS 에 tier 등록 |
| 새 청킹 전략 | `wiki_cli/llm.py` `_split_by_*` | `call_with_file` 분기에 추가 + `CHUNK_STRATEGIES` 등록 |
| 새 Lint 검사 | `wiki_cli/ops/lint.py` | `_check_*` 함수 추가 + `run_lint` / `_collect_issues` 에 포함 |
| 새 Web 페이지 | `wiki_web/routers/` + `templates/` | 라우터 파일 생성 → `app.py` `create_app` 에 `include_router` |
| 새 설정 항목 | `wiki_web/config.py` | `DEFAULTS` 추가 + `apply_env` 반영 + settings.html 폼 + `/settings` POST |

---

## 11. 점검 체크리스트

- [ ] `python3 -c "from wiki_cli.main import cli; from wiki_cli.ops import ingest, query, lint, init"` — 임포트 정상
- [ ] `python3 -c "from wiki_web.app import create_app; create_app()"` — FastAPI 조립 정상
- [ ] `wiki --help` — 4개 명령(init/ingest/query/lint) 출력
- [ ] `wiki init /tmp/test -d "test"` → `/tmp/test/wiki/AGENTS.md` 생성 + `~/.config/llm-wiki/config.json` 의 `domains` 에 등록
- [ ] index.md Sources/Entities/Concepts 섹션 삽입 정상 (§5.B 회귀 방지)
- [ ] `[[Test Entity]]` 링크가 있는 `Test Entity.md` 는 orphan 으로 분류되지 않음 (§5.C)
- [ ] Ingest 중 SSE 끊고 재연결 → 누적 로그 이어받기
- [ ] `wiki query "..."` 를 CWD 밖에서 실행해도 active 도메인 기준으로 동작 (§5.A)

---

## 12. 알려진 제한

| 항목 | 설명 | 위치 |
|------|------|------|
| CLI `ingest` 가 raw/ 외부 파일 허용 | 복사/경고 없이 임의 경로 처리 | [wiki_cli/main.py](../../wiki_cli/main.py) §5.D |
| Job 스토어 인메모리 | 프로세스 재시작 시 진행 내역 소실 | [wiki_web/progress.py](../../wiki_web/progress.py) |
| LLM lint sample | 20 페이지 상한 (앞부분만) | [wiki_cli/ops/lint.py:138](../../wiki_cli/ops/lint.py#L138) |
| Embedding 검색 매 호출 인코딩 | 문서 임베딩 캐시 없음 | [wiki_cli/search.py:143](../../wiki_cli/search.py#L143) |
