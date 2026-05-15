# llm-wiki 로컬 웹 전환 구현 계획 (Phase 1 & 2)

> 작성일: 2026-04-16  
> 목적: CLI 전용 도구 → 연구자 원클릭 로컬 웹앱 전환  
> 대상: 프로그래밍 경험이 낮은 연구자 (논문·기사·보고서 관리)

---

## 1. 전환 배경 및 목표

### 현황
- **현재**: Click 기반 CLI (`wiki init / ingest / query / lint`)
- **문제**: 연구자들이 터미널 사용에 익숙하지 않아 실제 활용이 어려움

### 목표
| 항목 | 내용 |
|---|---|
| 실행 방법 | `launch.sh` (macOS/Linux) / `launch.bat` (Windows) 더블클릭 |
| UI | 브라우저 기반 단일 페이지 앱 |
| LLM | 로컬(Ollama/LM Studio), 클라우드(Anthropic, OpenAI) 모두 지원 |
| 데이터 | 개인 PC 완전 로컬 (클라우드 의존 없음) |
| CLI | 기존 CLI 그대로 유지 (additive web layer) |

---

## 2. 기술 스택 결정

### 선택: FastAPI + HTMX + Jinja2 + Pico CSS

```
Streamlit / Gradio  →  탈락
  이유: 30~120초 걸리는 ingest 파이프라인을 UI 블로킹 없이 처리 불가
       다중 화면(문서 관리, 질문, 설정 등) 지원이 비자연스러움

FastAPI + HTMX  →  채택
  이유: SSE(Server-Sent Events)로 ingest 진행상황 실시간 스트리밍 가능
       HTMX 14KB CDN만으로 JS 없이 동적 UI 구현
       기존 ops/ 함수를 그대로 재사용 (progress_callback 추가만)
       uvicorn 한 줄로 실행, launch 스크립트로 자동화
```

### 추가 의존성

```toml
[project.optional-dependencies]
web = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.29",
    "python-multipart>=0.0.9",   # 파일 업로드
    "aiofiles>=23.0",            # 비동기 파일 I/O
    "jinja2>=3.1",               # HTML 템플릿
    "markdown>=3.6",             # LLM 답변 → HTML 변환
]
```

`pypdf>=4.0` 은 선택적 → 필수 의존성으로 승격

---

## 3. 최종 디렉토리 구조

```
llm-wiki/
├── launch.sh                    ← macOS/Linux 원클릭 실행
├── launch.bat                   ← Windows 원클릭 실행
├── pyproject.toml               ← [web] extras 추가
│
├── wiki_cli/                    ← 기존 CLI (변경 최소화)
│   ├── main.py                  ← 변경 없음
│   ├── llm.py                   ← Ollama 자동 감지, api_base 지원 추가
│   ├── search.py                ← 무음 폴백 → logging.warning으로 변경
│   ├── fs.py                    ← 변경 없음
│   └── ops/
│       ├── init.py              ← 변경 없음
│       ├── ingest.py            ← progress_callback 추가, 중복 검사, _extract_section 수정
│       ├── query.py             ← progress_callback 추가, read_index 버그 수정
│       └── lint.py              ← 변경 없음 (Phase 2에서 progress_callback 추가 예정)
│
└── wiki_web/                    ← 신규 웹 패키지
    ├── __init__.py
    ├── __main__.py              ← python -m wiki_web 진입점
    ├── app.py                   ← FastAPI 앱 팩토리
    ├── config.py                ← JSON 설정 파일 읽기/쓰기
    ├── progress.py              ← SSE용 asyncio.Queue 브리지
    ├── routers/
    │   ├── __init__.py
    │   ├── wiki.py              ← GET / (대시보드), POST /init
    │   ├── documents.py         ← 문서 관리 + Ingest SSE 스트리밍
    │   ├── query.py             ← 질문 답변 + SSE 스트리밍
    │   ├── settings.py          ← 설정 조회/저장
    │   └── lint.py              ← 위키 건강 검사
    └── templates/
        ├── base.html            ← 공통 레이아웃 (nav, Pico CSS, HTMX)
        ├── dashboard.html       ← 통계, 최근 로그, 빠른 시작
        ├── documents.html       ← 파일 목록, 드래그앤드롭 업로드, Ingest 버튼
        ├── query.html           ← 질문 입력, 마크다운 답변 렌더링
        ├── settings.html        ← 모델, API 키, 검색 티어 설정
        └── lint.html            ← 건강 검사 결과 테이블
```

---

## 4. 핵심 아키텍처: SSE 스트리밍 데이터 흐름

### Ingest 진행상황 실시간 전달

```
[브라우저]
  └─ PDF 업로드 → POST /documents/upload
       └─ raw/ 저장 → 파일 행 렌더링 (Ingest 버튼 포함)

[사용자] Ingest 버튼 클릭
  └─ POST /documents/ingest/{slug}
       └─ asyncio.Task 시작 (백그라운드에서 run_ingest 실행)
       └─ SSE 리스너 HTML 즉시 반환

[브라우저] SSE 연결
  └─ GET /documents/ingest/{slug}/stream
       └─ ProgressChannel.stream() → 이벤트 수신
       └─ HTMX가 progress-log div에 단계별 메시지 append

[run_ingest 완료]
  └─ done 이벤트 → 성공 메시지로 교체
```

### SSE 브리지 구현 (`wiki_web/progress.py`)

```python
class ProgressChannel:
    """ops 스레드 ↔ asyncio 이벤트 루프 브리지"""
    
    def emit(self, message: str) -> None:
        # 스레드에서 안전하게 큐에 push
        loop.call_soon_threadsafe(queue.put_nowait, message)
    
    async def stream(self) -> AsyncGenerator[str, None]:
        # SSE 형식으로 브라우저에 전달
        while True:
            msg = await queue.get()
            if msg is None: break
            yield f"data: <div class='log-step'>{msg}</div>\n\n"
```

### ops 함수 변경 패턴

```python
# 변경 전
def run_ingest(wiki_root, source, model):
    with Progress(...) as p:
        p.update(task, description="Reading source...")

# 변경 후 (CLI도 그대로 작동)
def run_ingest(wiki_root, source, model, progress_callback=None):
    def _emit(msg):
        if progress_callback:
            progress_callback(msg)  # 웹: SSE 큐에 push
        else:
            p.update(task, description=msg)  # CLI: rich 터미널 출력
```

---

## 5. 선행 코드 개선 사항 (Phase 1)

### 5-1. Ingest 중복 처리 (High)
**파일**: `wiki_cli/ops/ingest.py`  
**문제**: 동일 파일 재ingest 시 소스 페이지·index 행 중복 생성  
**수정**: `run_ingest()` 시작 시 `wiki/sources/{slug}.md` 존재 여부 검사 → `DuplicateError` 발생

### 5-2. `_extract_section` 파싱 오류 (High)
**파일**: `wiki_cli/ops/ingest.py:128`  
**문제**: LLM이 `"ENTITIES:"` (콜론 포함) 또는 소문자로 응답하면 파싱 실패 → entity/concept 페이지 미생성  
**수정**: `line.strip().rstrip(':').upper() == header.upper()` 로 비교

### 5-3. `fs.read_index` 버그 (High)
**파일**: `wiki_cli/ops/query.py:31`  
**문제**: `fs.read_index(wiki_root)` 호출하지만 `fs.py`에 `read_index` 함수 없음 → `search.py`에 존재  
**수정**: `search.read_index(fs.wiki_dir(wiki_root))` 로 변경

### 5-4. 무음 검색 폴백 (Medium)
**파일**: `wiki_cli/search.py`  
**문제**: `rank_bm25` 미설치 시 `print()`로만 알림 → 웹 UI에서 사용자 모름  
**수정**: `logging.warning()` 으로 변경, 웹 UI에서 배너로 표시

### 5-5. 기본 모델 Ollama 자동 감지 (Medium)
**파일**: `wiki_cli/llm.py`  
**문제**: 기본값이 `claude-sonnet-4-20250514` → Ollama 사용자 즉시 인증 오류  
**수정**: 시작 시 `localhost:11434` 접속 가능하면 `ollama/llama3` 우선 사용

---

## 6. 화면 구성 (5개)

### 화면 1: 대시보드 (`/`)
- 위키 이름·도메인 (AGENTS.md에서 읽음)
- 페이지 수 (소스/엔티티/개념/합성 분류)
- 최근 10개 로그 타임라인
- 처음 실행 시 → 빠른 시작 가이드 표시

### 화면 2: 문서 관리 (`/documents`)
- 드래그앤드롭 업로드 존 (PDF, md, txt)
- `raw/` 파일 목록: 이름, 크기, 날짜 + Ingest 버튼
- 이미 ingest된 파일 → "완료" 배지 표시
- Ingest 시: SSE로 단계별 진행 로그 실시간 표시

### 화면 3: 질문 답변 (`/query`)
- 텍스트 입력 → 전송
- SSE로 진행상황 표시 (검색 중, 페이지 읽는 중, 답변 생성 중)
- 마크다운 렌더링 답변
- "synthesis/에 저장" 버튼

### 화면 4: 위키 건강 검사 (`/lint`)
- "검사 실행" 버튼
- 결과: 심각도(high/medium/low) 컬러 배지 + 이슈 테이블

### 화면 5: 설정 (`/settings`)
- 위키 경로 (텍스트 필드)
- LLM 모델 선택 (프리셋 드롭다운 + 커스텀)
- API 키 (password 필드, .config/llm-wiki/config.json에 저장)
- Ollama 서버 URL
- 검색 티어 (grep / BM25 / embedding 라디오)

---

## 7. 단계별 로드맵

| 단계 | 기간 | 작업 내용 | 완료 기준 |
|---|---|---|---|
| **Phase 1** | 1~2주 | ops 버그 수정, progress_callback 추가, 웹 패키지 뼈대 | CLI 그대로 동작, `python -m wiki_web` 실행 가능 |
| **Phase 2** | 2~4주 | 문서 화면, 질문 화면, 설정 화면 | 브라우저에서 PDF 업로드→Ingest→질문 전체 흐름 |
| **Phase 3** | 4~6주 | 대시보드, Lint 화면, 위키 브라우저 | CLI 기능 완전 동등 |
| **Phase 4** | 6~8주 | launch 스크립트, PyInstaller 패키징 | 더블클릭 실행 |

---

## 8. 원클릭 실행 메커니즘

### `launch.sh` (macOS/Linux)
```bash
#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d ".venv" ]; then
    echo "첫 실행: 환경 설정 중 (약 1분)..."
    python3 -m venv .venv
    .venv/bin/pip install -e ".[web]" -q
fi

.venv/bin/python -m wiki_web &
sleep 2
open http://localhost:8000   # macOS
# xdg-open http://localhost:8000  # Linux
wait
```

### `launch.bat` (Windows)
```batch
@echo off
if not exist .venv (
    echo 첫 실행: 환경 설정 중...
    python -m venv .venv
    .venv\Scripts\pip install -e ".[web]" -q
)
start "" .venv\Scripts\python -m wiki_web
timeout /t 2 /nobreak > nul
start http://localhost:8000
```

---

## 9. 구현 완료 체크리스트

### Phase 1 (ops 레이어)
- [ ] `wiki_cli/llm.py` — Ollama 자동 감지
- [ ] `wiki_cli/search.py` — logging.warning 폴백
- [ ] `wiki_cli/ops/ingest.py` — progress_callback, 중복 검사, _extract_section 수정
- [ ] `wiki_cli/ops/query.py` — progress_callback, read_index 버그 수정
- [ ] `pyproject.toml` — web extras 추가, pypdf 필수화

### Phase 2 (웹 레이어)
- [ ] `wiki_web/config.py` — JSON 설정 파일
- [ ] `wiki_web/progress.py` — SSE 브리지
- [ ] `wiki_web/app.py` — FastAPI 앱
- [ ] `wiki_web/__main__.py` — uvicorn 실행
- [ ] `wiki_web/routers/documents.py` — 파일 관리 + SSE ingest
- [ ] `wiki_web/routers/query.py` — 질문 + SSE 답변
- [ ] `wiki_web/routers/settings.py` — 설정 폼
- [ ] `wiki_web/routers/wiki.py` — 대시보드
- [ ] `wiki_web/routers/lint.py` — 건강 검사
- [ ] `wiki_web/templates/*.html` — 모든 템플릿
- [ ] `launch.sh` / `launch.bat` — 실행 스크립트
