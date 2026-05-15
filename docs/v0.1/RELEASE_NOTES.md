# llm-wiki v0.1 릴리스 노트

> 릴리스 날짜: 2026-04-20  
> 버전: v0.1 (첫 번째 완성 버전)  
> 코드명: "연구자를 위한 로컬 위키"

---

## 개요

CLI 전용 도구(`wiki init/ingest/query/lint`)를 연구자가 터미널 없이 사용할 수 있는 **로컬 웹앱**으로 전환 완료.  
이번 버전에서 추가된 주요 기능: 멀티 도메인 지원, 백그라운드 Ingest, 관리자 UI, UI/UX 전면 개선.

---

## 기술 스택

| 계층 | 기술 |
|---|---|
| 백엔드 | FastAPI + uvicorn |
| 프론트엔드 | HTMX 1.9 + Jinja2 + Pico CSS v2 |
| LLM | litellm (Ollama / OpenAI / Anthropic 통합) |
| 검색 | Grep / BM25 / Embedding (선택) |
| 설정 | `~/.config/llm-wiki/config.json` (JSON) |
| 데이터 | 마크다운 + YAML frontmatter (파일 기반, DB 없음) |
| 실행 | `launch.sh` / `launch.bat` 더블클릭 원클릭 기동 |

---

## v0.1 신규 기능

### 1. 멀티 도메인 지원

- 하나의 앱에서 **여러 개의 위키(도메인)** 를 관리
- 네비게이션 바 상단 **도메인 드롭다운**으로 즉시 전환
- config.json 구조: `domains: [{id, name, wiki_root}, ...]` + `active_domain_id`
- 기존 단일 `wiki_root` 설정은 앱 시작 시 자동 마이그레이션

**API**

| 엔드포인트 | 설명 |
|---|---|
| `POST /admin/domains/add` | 새 도메인 추가 |
| `POST /admin/domains/{id}/activate` | 도메인 전환 |
| `POST /admin/domains/{id}/rename` | 이름 변경 |
| `POST /admin/domains/{id}/update-root` | 경로 변경 |
| `POST /admin/domains/{id}/delete` | 도메인 삭제 (파일 미삭제) |
| `POST /admin/domains/{id}/init` | 해당 도메인 위키 초기화 |

---

### 2. 백그라운드 Ingest (페이지 이동해도 서버에서 계속)

**문제**: 기존 구현은 SSE 연결이 끊기면 진행 중 메시지를 볼 수 없었음 (asyncio.create_task는 계속 실행되지만 채널 버퍼가 없었음).

**해결**: `IngestJob` 클래스 도입

- `messages: list[str]` 에 모든 진행 메시지 **누적 버퍼링**
- SSE 재연결 시 `messages[offset:]` 부터 순차 전송 → 놓친 메시지 없이 이어받음
- 복수 SSE 연결 동시 지원 (`_waiters: list[asyncio.Queue]`)
- 글로벌 `JobStore` 로 서버 메모리에 작업 유지 (완료 후 최대 30개 보관)

**새 엔드포인트**

| 엔드포인트 | 설명 |
|---|---|
| `GET /documents/jobs` | 현재 도메인의 작업 목록 (4초마다 폴링) |
| `GET /documents/ingest/{job_id}/stream` | SSE 스트림 (재연결 가능) |

**문서 페이지 개선**

- 상단 **작업 패널**: 진행 중·완료·실패 작업을 뱃지로 표시
- 각 작업 로그를 접고 펼 수 있는 토글
- 진행 중 작업 재연결 시 누적 로그 + 실시간 스트림 동시 제공
- 하단 안내 문구: "다른 페이지로 이동해도 서버에서 계속 처리됩니다"

---

### 3. UI/UX 전면 개선

**네비게이션 바**
- 배경: 연한 흰색(Pico 기본) → **진한 다크(`#1a1f2e`)**
- hover: `pico-primary-background`(거의 흰색이라 구분 불가) → **흰색 반투명 overlay**
- active 메뉴: 파란색 배경(`#3b82f6`) + 흰색 텍스트로 명확한 강조

**디렉터리 브라우저**
- hover: 배경색이 거의 없던 상태 → **연한 파란(`#e8f0fe`)** + 파란 텍스트
- selected: 파란 배경 + 흰색 텍스트

**배지 추가**
- `badge-running` (파란): 진행 중 작업 표시
- `badge-failed` (빨간): 실패 작업 표시

**도메인 선택기**
- 네비게이션 바에 상시 표시
- Jinja2 globals(`get_all_domains()`, `get_active_domain_id()`)로 매 요청마다 최신 목록 로드

---

### 4. 관리 기능 고도화 (`/admin`)

**도메인 관리 화면**
- 도메인 카드: 활성 여부, 초기화 상태, 통계(페이지·소스·엔티티·개념) 한눈에 표시
- 활성 도메인은 파란 테두리 카드로 강조
- 비활성 도메인: **활성화** 버튼 원클릭 전환
- **이름 변경**: 인라인 폼
- **경로 변경**: 폴더 선택기 + 인라인 폼
- **위키 초기화**: 접이식 섹션 → 도메인 주제 입력 + reset 체크박스(wiki/raw/ 삭제)
- **도메인 삭제**: 확인 다이얼로그 (파일은 삭제 안 함)

**새 도메인 추가**
- 이름 + 경로 입력 폼 (폴더 선택기 포함)
- 추가 시 자동으로 domains 리스트에 등록

**시스템 정보 섹션**
- 설정 파일 경로, 등록 도메인 수 표시

**설정 페이지 단순화**
- 기존 `wiki_root` 설정 → 관리 페이지로 이관
- 초기화 섹션 → 관리 페이지로 이관
- 설정 페이지: LLM 모델, API 키, 검색 방식만 관리

---

## 누적 버그 수정 (Phase 1·2)

| # | 현상 | 원인 | 수정 파일 |
|---|---|---|---|
| 1 | 업로드 후 파일 목록 미표시 | `#file-list` div 조건부 렌더링으로 HTMX 타깃 소실 | `documents.html` |
| 2 | Python 3.10+ deprecation 경고 | `asyncio.get_event_loop()` 오용 | `progress.py` |
| 3 | 로딩 스피너 미표시 | `style="display:none"` 인라인이 HTMX opacity 방식 덮어씀 | 여러 템플릿 |
| 4 | CLI Ollama URL 미반영 | CLI가 config.json 미로드 | `wiki_cli/main.py` |
| 5 | litellm provider 오류 | `name:tag` 형식에 `ollama/` prefix 누락 | `wiki_cli/llm.py` |
| 6 | Ingest 과도한 시간 소요 | Step 2에서 PDF 이중 전송 | `wiki_cli/ops/ingest.py` |

---

## 전체 파일 구조 (v0.1)

```
wiki_web/
├── __init__.py
├── __main__.py          # uvicorn 진입점 (원클릭 기동)
├── app.py               # FastAPI 팩토리 + Jinja2 globals
├── config.py            # JSON 설정 (멀티 도메인, 마이그레이션)
├── progress.py          # IngestJob + 글로벌 JobStore (버퍼링)
└── routers/
    ├── wiki.py          # 대시보드 (멀티 도메인)
    ├── documents.py     # 파일 관리 + 백그라운드 Ingest
    ├── query.py         # Q&A + SSE 진행
    ├── settings.py      # LLM 모델 / API 키 / 검색 설정
    ├── lint.py          # 위키 건강 검사
    └── admin.py         # 도메인 CRUD + 위키 초기화  ← NEW

wiki_web/templates/
├── base.html            # 네비게이션 (도메인 선택기, dark nav)
├── dashboard.html       # 대시보드 (멀티 도메인 상태 반영)
├── documents.html       # 파일 관리 + 작업 패널 (폴링)
├── query.html           # Q&A
├── settings.html        # 설정 (단순화)
├── lint.html            # 건강 검사
├── admin.html           # 도메인 관리  ← NEW
└── partials/
    ├── file_row.html
    ├── ingest_progress.html
    ├── jobs_panel.html  ← NEW (작업 목록 폴링용)
    ├── query_progress.html
    ├── query_result.html
    └── lint_result.html
```

---

## 알려진 제한 사항 / 다음 버전 예정

- Ingest 작업은 서버 메모리에만 유지 → 서버 재시작 시 작업 이력 소실
- 멀티 도메인 간 동일 모델/검색 설정 공유 (도메인별 오버라이드 미지원)
- 동시에 여러 사용자가 접속하는 멀티유저 시나리오 미지원
- 임베딩 검색 티어는 별도 pip 설치 필요 (`sentence-transformers`)
