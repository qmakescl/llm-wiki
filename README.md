# llm-wiki

**LLM이 자동으로 유지·관리하는 개인 연구 지식베이스** — 로컬 웹앱 + CLI

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688)](https://fastapi.tiangolo.com/)
[![Tests](https://img.shields.io/badge/tests-25%20passed-brightgreen)](#)

---

## 개념 출처

이 프로젝트는 **Andrej Karpathy**의 아이디어에서 출발했습니다.

> [**LLM Wiki** — Andrej Karpathy의 Gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)

카파시가 제안한 핵심 통찰은 다음과 같습니다.

> *"RAG처럼 매번 원문에서 검색·합성하는 대신, LLM이 새 소스를 받을 때마다 위키를 직접 업데이트하게 하라.  
> 위키는 **한 번만 합성하고 영구히 활용하는** 복리 자산이 된다."*

### 카파시 원문에서 구현한 항목

| 카파시가 제안한 개념 | 이 프로젝트의 구현 |
|---|---|
| **3계층 구조** (raw sources → wiki → schema) | `data/raw/` → `wiki/` → `AGENTS.md` |
| **Ingest 파이프라인** — 소스 요약, 10~15개 관련 페이지 일괄 업데이트 | 5단계 LLM 파이프라인 (`wiki_cli/ops/ingest.py`) |
| **Query** — 위키 검색 후 합성, 가치 있는 탐색 저장 | Q&A + `synthesis/` 자동 저장 |
| **Lint** — 고아 페이지, 모순, 오래된 주장 점검 | `/lint` (orphan·TODO·contradiction 탐지) |
| **index.md** — 카테고리별 콘텐츠 카탈로그 | 자동 생성·갱신 |
| **log.md** — 시간순 변경 이력 | Ingest 완료 시 자동 기록 |
| **AGENTS.md** — LLM 행동 헌법 (도메인·규칙·형식) | 위키 초기화 시 자동 생성 |
| **Obsidian을 IDE처럼 사용** | `wiki/` 폴더를 Obsidian Vault로 직접 열기, `[[위키링크]]` 완전 동작 |

### 원문 대비 추가 구현

카파시의 원문은 개념 스케치 수준입니다. 이 프로젝트는 **비기술 연구자가 터미널 없이 사용할 수 있도록** 다음을 추가했습니다.

- **로컬 웹앱** (FastAPI + HTMX) — 브라우저에서 드래그앤드롭 업로드, 실시간 진행 표시
- **멀티 도메인** — 한 앱에서 여러 위키 전환 (AI 논문 / 신약 개발 / 경제학 등)
- **다중 LLM 지원** — Ollama(로컬), OpenAI, Anthropic 자동 감지
- **검색 계층** — Grep → BM25 → Embedding 선택적 업그레이드
- **원클릭 실행** — `launch.sh` / `launch.bat`으로 가상환경 포함 자동 설치·실행

---

## 빠른 시작

**방법 1 — 원클릭 실행 (권장)**

```bash
# macOS / Linux
./launch.sh

# Windows
launch.bat
```

가상환경 생성, 패키지 설치, 브라우저 오픈까지 자동 처리.

**방법 2 — uv 사용 (빠른 설치)**

[uv](https://docs.astral.sh/uv/)가 설치되어 있다면 `uv.lock`으로 의존성을 정확히 동기화합니다.

```bash
uv sync              # 기본 의존성 설치
uv sync --extra bm25        # BM25 검색 포함
uv sync --extra embedding   # 임베딩 검색 포함
uv sync --extra dev         # 개발 환경 포함

uv run python -m wiki_web
# → http://localhost:8000
```

**방법 3 — pip 직접 설치**

```bash
pip install -e .
python -m wiki_web
# → http://localhost:8000
```

---

## 주요 기능

### 멀티 도메인
하나의 앱에서 여러 위키를 관리합니다. 네비게이션 바 드롭다운으로 즉시 전환.

### 백그라운드 Ingest
Ingest 중 다른 페이지로 이동해도 서버에서 계속 처리됩니다.  
SSE(Server-Sent Events)로 LLM 처리 단계를 실시간 스트리밍하며, 재연결 시 누락 없이 이어받습니다.

### Obsidian Vault 연동
`wiki/` 폴더를 Obsidian에서 바로 열 수 있습니다.  
entity · concept 파일명이 display name 기반이라 `[[위키링크]]`가 바로 동작합니다.

---

## 화면 구성

| 경로 | 기능 |
|---|---|
| `/` | 대시보드 — 통계 카드, 최근 활동 로그 |
| `/documents` | 파일 업로드(드래그앤드롭) + Ingest 큐 + 작업 상태 |
| `/query` | 질문 입력 → LLM 답변 → `synthesis/` 저장 옵션 |
| `/lint` | 위키 건강 검사 — 고아 페이지, TODO, 모순 탐지 |
| `/settings` | LLM 모델, API 키, 검색 방식, 청킹 설정 |
| `/admin` | 도메인 CRUD, 위키 초기화 |

---

## LLM 설정

| 모델 | 설정 방법 |
|---|---|
| 로컬 Ollama (llama3 등) | 별도 설정 불필요 — 자동 감지 |
| Anthropic Claude | `ANTHROPIC_API_KEY=sk-ant-...` |
| OpenAI GPT-4o | `OPENAI_API_KEY=sk-...` |

웹 UI 설정 페이지에서도 변경 가능합니다.

---

## 검색 계층

| 티어 | 추가 설치 | 특징 |
|---|---|---|
| `grep` (기본) | 불필요 | 단어 빈도 기반, 즉시 사용 가능 |
| `bm25` | `pip install rank-bm25` | TF-IDF 개선판 |
| `embedding` | `pip install sentence-transformers` | 의미 기반 유사도 검색 |

---

## CLI 사용

```bash
wiki init my-research --domain "딥러닝 이론과 구현"
wiki ingest my-research/data/raw/attention.pdf
wiki query "attention mechanism이란?"
wiki query "BERT와 GPT 비교" --save
wiki lint
```

---

## 위키 구조

```
my-research/
├── wiki/                  ← Obsidian Vault로 열기
│   ├── AGENTS.md          LLM 헌법 (도메인·규칙·형식)
│   ├── index.md           마스터 인덱스
│   ├── log.md             타임라인 로그
│   ├── sources/           소스별 요약
│   ├── entities/          인물·모델·데이터셋
│   ├── concepts/          개념 심층 페이지
│   └── synthesis/         Q&A 저장
└── data/
    └── raw/               원본 소스 파일 (PDF 등)
```

---

## 의존성

```bash
pip install -e .               # CLI + 웹 UI
pip install -e ".[bm25]"       # BM25 검색 추가
pip install -e ".[embedding]"  # 임베딩 검색 추가
pip install -e ".[dev]"        # 개발 환경 (pytest)
```

**핵심**: `litellm` · `fastapi` · `htmx` · `jinja2` · `pypdf` · `click`  
**선택**: `rank-bm25` · `sentence-transformers`

---

## 시스템 요구사항

- **Python** 3.11 이상
- **OS** macOS · Linux · Windows
- **LLM** Ollama(로컬), OpenAI API, Anthropic API 중 하나

---

## 알려진 제한 사항

- Ingest 작업은 서버 메모리에만 유지 → 서버 재시작 시 작업 이력 소실
- 임베딩 검색 첫 실행 시 모델 다운로드 약 500MB 소요
- 단일 사용자 용도 (멀티유저 미지원)