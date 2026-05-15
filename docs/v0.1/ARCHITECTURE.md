# llm-wiki v0.1 아키텍처 문서

---

## 시스템 구성도

```
사용자 브라우저
    │  HTMX (HTML-over-the-wire)
    ▼
FastAPI (wiki_web)
    │
    ├── GET/POST /          → wiki.py       (대시보드)
    ├── GET/POST /documents → documents.py  (파일 관리 + Ingest)
    ├── GET/POST /query     → query.py      (Q&A)
    ├── GET/POST /settings  → settings.py   (LLM 설정)
    ├── GET      /lint      → lint.py       (건강 검사)
    └── GET/POST /admin     → admin.py      (도메인 관리)
           │
           ▼
    wiki_cli (ops 레이어)
    ├── ops/ingest.py   (5단계 LLM 파이프라인)
    ├── ops/query.py    (검색 → 컨텍스트 → 답변)
    ├── ops/lint.py     (고아 페이지, TODO, 모순 탐지)
    ├── ops/init.py     (위키 디렉터리 초기화)
    ├── llm.py          (litellm 어댑터)
    ├── search.py       (Grep / BM25 / Embedding)
    └── fs.py           (파일 I/O, index 관리)
           │
           ▼
    파일시스템 (wiki_root/)
    ├── AGENTS.md         (위키 헌법 - 도메인, 규칙, 형식)
    ├── raw/              (원본 소스 파일)
    └── wiki/
        ├── index.md      (마스터 인덱스)
        ├── log.md        (타임라인 로그)
        ├── sources/      (소스 요약 페이지)
        ├── entities/     (인물, 모델, 데이터셋)
        ├── concepts/     (개념 심층 페이지)
        └── synthesis/    (Q&A 저장)
```

---

## 설정 관리 (config.py)

### 파일 위치
```
~/.config/llm-wiki/config.json
```

### 스키마 (v0.1)
```json
{
  "domains": [
    {
      "id": "fb922e6c",
      "name": "AI 연구 위키",
      "wiki_root": "/Users/me/ai-wiki"
    }
  ],
  "active_domain_id": "fb922e6c",
  "model": "claude-sonnet-4-20250514",
  "search_tier": "grep",
  "ollama_base_url": "http://localhost:11434",
  "openai_api_key": "",
  "anthropic_api_key": ""
}
```

### 마이그레이션
구형 `wiki_root` 단일 키를 domains 리스트로 자동 변환:
```python
if "wiki_root" in cfg and not cfg.get("domains"):
    cfg["domains"] = [{"id": ..., "name": "기본 위키", "wiki_root": cfg.pop("wiki_root")}]
```

---

## Ingest 백그라운드 작업 흐름

```
POST /documents/ingest/{slug}
    │
    ├─ IngestJob 생성 (job_id, filename, domain_name)
    │   └─ JobStore에 등록
    │
    ├─ asyncio.create_task(_run())  ← 이벤트 루프에서 백그라운드 실행
    │   │  (SSE 연결 끊겨도 계속 실행됨)
    │   └─ asyncio.to_thread(run_ingest, ..., job.emit)
    │       └─ 스레드풀에서 LLM 호출 (블로킹)
    │           │ job.emit("메시지") 호출 시:
    │           │   self.messages.append(html_msg)  ← 누적 버퍼
    │           │   self._notify(html_msg)          ← 활성 SSE에 push
    │
    └─ 즉시 ingest_progress.html 반환 (SSE 리스너 포함)

브라우저: GET /documents/ingest/{job_id}/stream (SSE)
    │
    └─ IngestJob.stream()
        ├─ 누적 messages[offset:] 즉시 전송
        ├─ _done 아니면 Queue 대기
        ├─ 새 메시지 도착 → offset 업데이트 후 전송
        └─ complete() 호출 → done 이벤트 → SSE 종료
```

### 재연결 시나리오
```
1. 사용자 Ingest 시작
2. 다른 페이지 이동 (SSE 연결 끊김)
   → asyncio Task는 계속 실행
   → messages 리스트에 계속 누적
3. 문서 페이지 복귀
   → jobs_panel 폴링 (4초) → 진행 중 작업 표시
   → "로그 보기" 클릭 → 새 SSE 연결
   → stream()에서 messages[0:] 전체 즉시 전송 + 이후 실시간
```

---

## 멀티 도메인 라우팅

모든 라우터는 `cfg.get_wiki_root()`를 통해 활성 도메인의 경로를 얻음:

```python
def get_wiki_root(cfg: dict | None = None) -> Path:
    domain = get_active_domain(cfg)
    return Path(domain["wiki_root"]) if domain else Path.home() / "my-wiki"
```

도메인 전환은 `POST /admin/domains/{id}/activate` → `cfg.switch_domain(id)` → `config.json` 저장.  
이후 모든 요청은 새 active_domain_id 기준으로 처리됨.

---

## 네비게이션 도메인 선택기

Jinja2 전역 함수로 매 요청마다 최신 도메인 목록 주입:

```python
# app.py
templates.env.globals["get_all_domains"] = lambda: cfg.get_all_domains()
templates.env.globals["get_active_domain_id"] = lambda: cfg.load().get("active_domain_id", "")
```

```jinja2
{# base.html #}
{% set _nav_domains = get_all_domains() %}
{% set _nav_active_id = get_active_domain_id() %}
<select onchange="switchDomain(this)">
  {% for d in _nav_domains %}
  <option value="{{ d.id }}" {% if d.id == _nav_active_id %}selected{% endif %}>
    {{ d.name }}
  </option>
  {% endfor %}
</select>
```

---

## SSE 진행상황 스트리밍 패턴

Ingest와 Query 모두 동일한 패턴 사용:

```
ops 함수 (스레드) → progress_callback(msg) → 이벤트 루프 큐
                                              ↓
                                         SSE stream → 브라우저
                                         HTMX sse-swap="message"
                                         hx-swap="beforeend"
                                              ↓
                                         progress-log div에 추가
```

완료 시 `event: done` SSE 이벤트 → HTMX `sse-swap="done"` 타깃에 결과 교체.
