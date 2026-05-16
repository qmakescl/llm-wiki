# llm-wiki

LLM이 자동으로 유지하는 **개인 연구 지식베이스** — 로컬 웹앱 + CLI.

카파시의 [LLM Wiki 아이디어](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)를 Python으로 구현했습니다.  
PDF·논문·메모를 업로드하면 LLM이 자동으로 위키 페이지를 작성하고, 이후 질문으로 검색합니다.

---

## 빠른 시작 (웹 UI)

**방법 1 — 더블클릭 원클릭 실행 (권장)**

| OS | 파일 |
|---|---|
| macOS / Linux | `launch.sh` |
| Windows | `launch.bat` |

가상환경 생성, 패키지 설치, 브라우저 오픈까지 자동으로 처리됩니다.

**방법 2 — 직접 설치**

```bash
pip install -e .
python -m wiki_web
# → http://localhost:8000
```

---

## 주요 기능

### 멀티 도메인

하나의 앱에서 여러 위키를 관리합니다. 네비게이션 바의 드롭다운으로 즉시 전환.

```
AI 논문 위키  ▼   ← 클릭 한 번으로 전환
├── 딥러닝 연구
├── 신약 개발
└── 경제학 노트
```

### 백그라운드 Ingest

Ingest 중 다른 페이지로 이동해도 서버에서 계속 처리됩니다.  
돌아오면 작업 패널에서 누락 없이 이어받아 진행 로그를 확인할 수 있습니다.

### 구조화 Ingest + 재시도 캐시

소스 분석 결과를 `summary`, `claims`, `entities`, `concepts`, `evidence` 중심의 구조 데이터로 먼저 추출합니다.  
구조화 추출이 성공하면 entity/concept 계획용 LLM 호출을 생략해 ingest 호출 수와 반복 토큰을 줄입니다.

PDF·텍스트 추출 결과와 동일 파일/동일 프롬프트의 `call_with_file()` 결과는 source hash 기준으로 캐시됩니다.  
중간 실패 후 재시도하거나 같은 문서를 디버깅할 때 초기 분석 비용을 줄일 수 있습니다.

### 출력 언어 설정

Markdown 문서와 query 답변의 출력 언어를 설정에서 선택할 수 있습니다.

| 설정 | 설명 |
|---|---|
| 한국어 | 본문, bullet, table, callout, query 답변을 한국어로 작성 |
| English | 본문과 답변을 영어로 작성 |
| 원문 언어 유지 | source 문서의 원문 언어를 최대한 유지 |

제목, 파일명, tags, sources, aliases, `[[wikilink target]]`은 Obsidian 링크 안정성을 위해 영어 또는 원문을 유지합니다.  
`Heading은 원문 언어 사용` 옵션은 기본으로 켜져 있으며, 본문 출력 언어와 별개로 Markdown heading은 원문 언어를 따릅니다.

### Source Registry

업로드된 원본은 `data/{domain}/sources.jsonl`에 `sha256`, 파일 크기, ingest 시각, summary page, model 정보와 함께 기록됩니다.  
같은 내용을 다른 파일명으로 다시 ingest하려 하면 LLM 호출 전에 중복으로 차단합니다.

### 실시간 진행 표시

SSE(Server-Sent Events)로 LLM 처리 단계를 실시간 스트리밍합니다.

### Obsidian Vault 연동

`wiki/` 폴더를 Obsidian에서 바로 열 수 있습니다.  
entity/concept 파일명이 display name 기반이라 `[[위키링크]]`가 자동으로 해결됩니다.

#### remotely-save 자동 동기화

ingest 또는 `wiki query --save` 완료 시 Obsidian의 **remotely-save** 플러그인으로 자동 동기화가 트리거됩니다.

**초기 설정 (1회)**

1. **Vault 열기** — Obsidian에서 `{workspace_root}/wiki/` 디렉터리를 Vault로 열고,  
   이름이 **`wiki`** 인지 확인합니다 (폴더명이 vault 이름이 됩니다).
2. **remotely-save 설치** — Obsidian 설정 → 커뮤니티 플러그인 → `remotely-save` 검색 후 설치·활성화.
3. **동기화 대상 설정** — remotely-save 설정에서 S3·OneDrive·Dropbox 등 원하는 원격 스토리지를 연결하고 연결 테스트를 완료합니다.
4. **obsidian CLI 설치** — Obsidian 설정 → 커뮤니티 플러그인 → `Obsidian CLI` 설치·활성화  
   (CLI 없이 obsidian 명령어를 찾지 못하면 동기화를 건너뛰고 경고만 출력합니다).

**동기화 활성화/비활성화**

웹 UI **설정** 페이지 하단 "Obsidian 동기화" 체크박스에서 토글할 수 있습니다.  
환경변수로 직접 제어하려면:

```bash
export WIKI_OBSIDIAN_SYNC=off   # 비활성화
export WIKI_OBSIDIAN_SYNC=on    # 활성화 (기본값)
```

---

## 화면 구성

| 경로 | 기능 |
|---|---|
| `/` | 대시보드 — 통계 카드, 최근 활동 로그 |
| `/documents` | 파일 업로드(드래그앤드롭) + Ingest + 작업 상태 |
| `/query` | 질문 입력 → LLM 답변 (synthesis/ 저장 옵션) |
| `/lint` | 위키 건강 검사 — 고아 페이지, TODO, 모순 탐지 |
| `/settings` | LLM 모델, API 키, 검색 방식, 출력 언어 설정 |
| `/admin` | 도메인 CRUD, 위키 초기화, 청킹 설정 |

---

## LLM 설정

웹 UI의 **설정** 페이지에서 변경하거나, 환경변수로 직접 지정할 수 있습니다.

| 모델 | 환경변수 |
|---|---|
| Anthropic Claude Sonnet 4 | `ANTHROPIC_API_KEY=sk-ant-...` |
| OpenAI GPT-4o | `OPENAI_API_KEY=sk-...` |
| 로컬 Ollama (llama3 등) | 설정 불필요 — 자동 감지 |

```bash
# CLI에서 일시적으로 모델 지정
wiki ingest paper.pdf --model claude-sonnet-4-20250514
```

### 출력 언어 환경변수

웹 UI 설정이 우선이지만 CLI 환경에서 직접 지정할 수도 있습니다.

| 환경변수 | 값 | 설명 |
|---|---|---|
| `WIKI_OUTPUT_LANGUAGE` | `ko`, `en`, `source` | Markdown 본문과 query 답변 출력 언어 |
| `WIKI_HEADING_ORIGINAL_LANGUAGE` | `on`, `off` | `on`이면 Markdown heading은 원문 언어 사용 |

---

## 검색 계층

| 티어 | 설치 | 특징 |
|---|---|---|
| `grep` (기본) | 기본 포함 | 단어 빈도 기반, 즉시 사용 |
| `bm25` | 기본 포함 | TF-IDF 개선판, 정확도 향상 |
| `embedding` | 기본 포함 | 의미 기반 유사도 검색 |
| `vector` | 기본 포함 | `.vectors/vector_index.sqlite` 기반 chunk 의미 검색 |

웹 UI 설정 페이지 또는 환경변수 `WIKI_SEARCH=vector` 로 전환. `vector` 티어는 ingest 후 생성/수정된 페이지를 chunk 단위로 인덱싱하고, DB나 모델을 사용할 수 없으면 기존 grep 검색으로 대체합니다.

---

## CLI 사용

웹 UI와 동일한 ops 레이어를 공유합니다. `~/.config/llm-wiki/config.json` 설정을 자동으로 읽습니다.

```bash
wiki init my-research --domain "딥러닝 이론과 구현"
wiki ingest my-research/data/raw/attention.pdf
wiki query "attention mechanism이란?"
wiki query "BERT와 GPT 비교" --save
wiki lint
wiki vector rebuild
```

| 명령어 | 설명 |
|---|---|
| `wiki init [dir]` | 새 위키 디렉토리 생성 (wiki/ + data/ 분리 구조) |
| `wiki ingest <file>` | 소스 파일을 위키에 추가 |
| `wiki query "<질문>"` | 위키에서 질문 검색 |
| `wiki query "..." --save` | 답변을 synthesis/ 에 저장 |
| `wiki lint` | 위키 건강 점검 |
| `wiki vector rebuild` | 전체 위키 vector index 재생성 |
| `wiki vector stats` | vector index 페이지/청크 수 확인 |
| `wiki vector clear` | 로컬 vector index 삭제 |

---

## 위키 구조

```
my-research/
├── wiki/                  Obsidian Vault (마크다운 위키)
│   ├── AGENTS.md          LLM 헌법 (도메인, 규칙, 형식)
│   ├── index.md           마스터 인덱스
│   ├── log.md             타임라인 로그
│   ├── sources/           소스별 요약 페이지
│   ├── entities/          인물·모델·데이터셋
│   ├── concepts/          개념 심층 페이지
│   └── synthesis/         Q&A 저장
└── data/
    ├── raw/               원본 소스 파일 (PDF, 텍스트)
    ├── sources.jsonl      원본 파일 registry (hash, ingest 상태)
    └── .cache/            추출 텍스트 및 call_with_file 결과 캐시
```

`AGENTS.md`를 수정하면 LLM의 글쓰기 방식과 도메인 포커스를 커스터마이징할 수 있습니다.

---

## 설정 파일

`~/.config/llm-wiki/config.json` 에 저장됩니다.

```json
{
  "workspace_root": "/path/to/workspace",
  "domains": [
    { "id": "abc123", "name": "AI 논문", "folder": "ai_papers" }
  ],
  "active_domain_id": "abc123",
  "model": "claude-sonnet-4-20250514",
  "search_tier": "grep",
  "chunk_strategy": "section",
  "chunk_size": 500,
  "chunk_overlap": 100,
  "output_language": "ko",
  "heading_original_language": true
}
```

기존 단일 `wiki_root` 설정은 앱 시작 시 자동으로 멀티 도메인 구조로 마이그레이션됩니다.

---

## 프로젝트 구조

```
wiki_cli/              CLI + ops 핵심 로직
├── main.py            Click 진입점
├── llm.py             litellm 어댑터 (Ollama/OpenAI/Anthropic)
├── search.py          플러그형 검색 (grep/BM25/embedding/vector)
├── vector_index.py    SQLite chunk vector index
├── fs.py              파일시스템 헬퍼
├── source_registry.py 원본 파일 hash registry
├── structured_ingest.py 구조화 ingest 추출/파싱
├── language.py        Markdown 출력 언어 정책
└── ops/
    ├── ingest.py      5단계 LLM Ingest 파이프라인
    ├── query.py       질문-답변 파이프라인
    ├── lint.py        위키 건강 점검
    └── init.py        위키 초기화

wiki_web/              FastAPI 웹 레이어
├── app.py             앱 팩토리 + Jinja2 globals
├── config.py          멀티 도메인 설정 관리
├── progress.py        IngestJob + 글로벌 JobStore
└── routers/
    ├── wiki.py        대시보드
    ├── documents.py   파일 관리 + 백그라운드 Ingest
    ├── query.py       Q&A + SSE
    ├── settings.py    모델·키 설정
    ├── lint.py        건강 검사
    ├── admin.py       도메인 관리 + 청킹 설정
    └── synthesis.py   저장된 Q&A 조회
```

---

## 의존성

```toml
# 핵심 (CLI)
litellm, click, python-frontmatter, rich, pypdf

# 웹 UI
fastapi, uvicorn[standard], python-multipart, jinja2, markdown, aiofiles

# 검색
rank-bm25, sentence-transformers
```

```bash
pip install -e .              # CLI + 웹 UI (기본)
pip install -e ".[dev]"       # 개발 환경 (pytest 포함)
```

---

## 시스템 요구사항

- **Python**: 3.11 이상
- **OS**: macOS, Linux, Windows
- **LLM**: Ollama(로컬), OpenAI API, 또는 Anthropic API 중 하나

---

## 알려진 제한 사항

- Ingest 작업은 서버 메모리에만 유지 → 서버 재시작 시 작업 이력 소실
- 첫 ingest는 캐시 miss이므로 추출 캐시는 재시도·반복 실행에서 주로 효과가 큼
- 구조화 추출 실패 시 기존 overview 기반 흐름으로 fallback함
- 임베딩 검색 첫 실행 시 모델 다운로드 약 500MB 소요
- 멀티유저(동시 접속) 시나리오 미지원 (개인/소규모 용도)

---

## 현재 버전

**v0.3.1** (2026-05-16) — current

| 항목 | 상태 |
|---|---|
| GitHub | [qmakescl/llm-wiki](https://github.com/qmakescl/llm-wiki) |
| 테스트 | `77 passed` |
| 주요 변경 | Markdown 생성 및 query 답변의 희망 출력 언어 설정 |
| 변경 기록 | [`CHANGELOG.md`](CHANGELOG.md) |

---

## 최근 개선 및 향후 개선 예정

### Karpathy Alignment 개선 (`docs/karpathy_improvement_status_2026-05-14.md`)

Karpathy의 LLM Wiki 패턴에 맞춰 source provenance와 ingest 속도 개선을 진행 중입니다.

완료된 개선:

| 항목 | 상태 |
|---|---|
| pytest 수집 안정화 | 완료 — 기본 `pytest`가 활성 `tests/`만 수집 |
| Source Registry | 완료 — `data/{domain}/sources.jsonl`, sha256 중복 감지 |
| 추출 캐시 | 완료 — PDF/text 추출 결과 캐시 |
| LLM file-result 캐시 | 완료 — 동일 파일/프롬프트/config 재시도 시 재사용 |
| 구조화 ingest | 부분 완료 — JSON 추출 성공 시 planning LLM 호출 생략 |

관련 문서:

- `docs/karpathy_alignment_review.md`
- `docs/karpathy_improvement_implementation_plan.md`
- `docs/metrics/karpathy_improvement_after_phase1.md`
- `docs/metrics/karpathy_improvement_after_extraction_cache.md`
- `docs/metrics/karpathy_improvement_after_structured_ingest.md`

### Ingest 파이프라인 최적화 (`docs/v0.1/ingest_improvement.md`)

현재 `run_ingest()`는 overview를 자유서술 텍스트로 유지한 채 후속 단계마다 반복 전달합니다.  
페이지 수를 줄이지 않고도 호출당 토큰량을 줄이는 방향으로 구조 개선이 필요합니다.

| 항목 | 설명 | 우선순위 |
|---|---|---|
| **overview 구조화** | `overview` 텍스트 → `structured_ingest_result` (summary, claims, entities, concepts, evidence map) | 1순위 |
| **entity/concept별 evidence map** | 전체 overview 재전달 대신 항목별 관련 evidence만 전달 | 1순위 |
| **청크 결과 구조화** | 청크별 긴 요약 대신 claims/entities/evidence 구조 데이터 추출 → 마지막 1회 통합 | 2순위 |
| **entity/concept 생성 병렬화** | 직렬 루프 → worker 2~4 제한 병렬화 (파일 단위 충돌 없음) | 3순위 |

> delta 업데이트, 청크 evidence 추출, source registry, 추출 캐시, 구조화 ingest의 1차 연결은 구현 완료.  
> 남은 작업: source page template 렌더링, entity/concept별 evidence 직접 전달, 병렬화, search index cache.

### 캐시 제어 환경변수

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `WIKI_EXTRACT_CACHE` | on | `0`, `false`, `no`, `off`면 추출 텍스트 캐시 비활성화 |
| `WIKI_LLM_FILE_CACHE` | on | `0`, `false`, `no`, `off`면 `call_with_file()` 결과 캐시 비활성화 |

---

### Obsidian 연동 개선 (`docs/ideas.md`)

#### 1. Obsidian Vault 자동 감지

초기 설정 시 Vault 경로를 수동 입력하는 대신 자동 감지:
- macOS: `~/Library/Application Support/obsidian/obsidian.json`에서 최근 Vault 목록 읽기
- 브라우저 폴더 선택 다이얼로그(File API) 연동

#### 2. `data/raw/` 원본 파일 Obsidian 접근 문제

`wiki/`(Vault)와 `data/`(운영 데이터)를 분리한 이후, Obsidian에서 `data/raw/` 원본 파일로 직접 링크가 동작하지 않습니다.  
검토 중인 해결 방안:

| 방안 | 장점 | 단점 |
|---|---|---|
| **심볼릭 링크** `wiki/raw → data/raw` | 앱 로직 변경 최소 | Windows 관리자 권한 필요, 클라우드 동기화 미지원 |
| **웹서버 URL** `localhost:8000/documents/raw?file=...` | OS 제약 없음 | 서버 실행 중이어야 동작 |
| **`file:///` 절대경로** | 서버 불필요 | 기기 간 이동 시 경로 깨짐 |
| **`wiki/assets/` 복사** | Obsidian 100% 네이티브 연동 | 저장공간 2배 소모 |

> 현재 미결정. 심볼릭 링크 방식이 가장 현실적이나 Windows 호환성 검토 필요.
