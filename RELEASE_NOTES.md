# llm-wiki v0.2.1 릴리스 노트

> 릴리스 날짜: 2026-04-21  
> 버전: v0.2.1  
> 코드명: "Obsidian 위키링크 완전 지원"

---

## 개요

v0.2.0(2026-04-20)의 후속 패치 릴리스입니다.  
전체 데이터 흐름을 처음부터 재검토하여 발견된 **7개 버그 수정** + **2개 성능 개선**을 포함합니다.  
특히 Obsidian vault에서 `[[위키링크]]`가 동작하지 않던 근본 원인을 3가지 측면에서 모두 해결했습니다.

---

## 버그 수정

### 1. CLI `wiki init` 명령어 완전 불능 (TypeError)

`wiki init` 실행 시 `TypeError: run_init() got an unexpected keyword argument 'target'` 발생.  
`run_init` 시그니처 변경(`wiki_root`, `data_root` 분리) 후 CLI 호출부가 미반영된 상태였음.

**수정**: `wiki_cli/main.py` — `base/wiki` + `base/data` 경로 분리 계산 후 전달.

---

### 2. CLI 저장 완료 메시지 미표시 (죽은 코드)

`wiki query "..." --save` 실행 후 저장 완료 메시지가 출력되지 않음.  
`_save_synthesis()` 내부에 `if not True:` 조건으로 묶인 죽은 코드 상태였음.

**수정**: `wiki_cli/ops/query.py` — 불필요한 조건 제거, 항상 출력.

---

### 3. 위키 초기화 실패 시 500 Internal Server Error

관리 화면(`/admin`)에서 위키 초기화 실패 시 에러 메시지 대신 500 오류 발생.  
실패 처리 코드가 `admin.html` 렌더링에 필요한 컨텍스트 변수를 전달하지 않아 Jinja2 UndefinedError.

**수정**: `wiki_web/routers/admin.py` — 실패 시 에러 메시지 포함 RedirectResponse로 교체.

---

### 4. 관리 화면 청킹 설정 저장 안 됨

`/admin` 청킹 전략 변경 후 저장해도 기본값으로 유지됨.  
`/admin/settings` POST 핸들러에 `chunk_strategy`, `chunk_size`, `chunk_overlap` 처리 로직 누락.

**수정**: `wiki_web/routers/admin.py` — 3개 청킹 필드 추가, 유효성 보정 로직 적용.

---

### 5. 동기식 질문 답변(`/query/ask`) 저장 기능 불능

답변 후 "저장" 버튼 클릭 시 빈 내용으로 저장됨.  
`ask_sync` 핸들러가 `raw_answer` 컨텍스트 변수를 템플릿에 전달하지 않아 hidden 필드가 빈 값.

**수정**: `wiki_web/routers/query.py` — `raw_answer` 초기화 및 템플릿 컨텍스트에 명시 전달.

---

### 6. 도메인 폴더 중복 시 하이픈/언더스코어 혼합

동일 이름 도메인 추가 시 `my_wiki-1` 처럼 혼합 형식 폴더명 생성.  
중복 카운터 부분이 구형 하이픈 형식(`slug-1`)으로 남아 있었음.

**수정**: `wiki_web/routers/admin.py` — 카운터를 `slug_1` 형식(언더스코어)으로 통일.

---

### 7. Obsidian 위키링크가 기존 파일을 찾지 못하고 새 노트 생성

`[[Entity Name]]` 클릭 시 기존 파일로 이동하지 않고 새 노트 생성.

**원인 3가지**:
1. 파일명이 slug 기반(`google-agentspace.md`)이나 링크는 display name 기반(`[[Google Agentspace]]`)
2. alias가 미설정되거나 링크 텍스트와 불일치
3. source 페이지가 entity 페이지보다 먼저 작성되어 링크 이름 불일치 발생

**해결**:
- entity/concept 파일명을 display name 기반(`Google Agentspace.md`)으로 변경
- `title = display_name` 강제 설정으로 파일명·alias·링크 3중 일치
- ingest 순서 변경: entity/concept 계획 먼저 → source 페이지에 확정 이름 명시

**수정**: `wiki_cli/ops/ingest.py` — `_plan_related_pages()`, `_page_display_name()` 신규 함수 추가.

---

## 성능 개선

### 1. Ingest 증분 업데이트 (delta 방식)

기존 entity/concept 페이지 업데이트 시 전체 페이지를 LLM으로 재생성했음.  
변경: 관련 evidence만 추출(`_extract_relevant_evidence()`) → delta만 출력(`SECTION:`/`NEW_SECTION:` 지시) → `_apply_delta()`로 병합.

**효과**: 입력·출력 토큰 모두 절감, 기존 내용 보존 보장.

### 2. 청크 단계 evidence 추출 구조화

기존 `_chunk_and_call()`은 청크마다 완성형 분석을 생성했음.  
변경: 청크별 경량 evidence 목록 추출(`max_tokens=1024`) + 최종 1회 통합 분석.

**효과**: 청크당 출력 토큰 대폭 절감, 통합 품질 향상.

---

## 수정 파일 요약

| 파일 | 내용 |
|---|---|
| `wiki_cli/main.py` | `wiki init` TypeError 수정 |
| `wiki_cli/ops/query.py` | 저장 완료 메시지 죽은 코드 제거 |
| `wiki_cli/ops/ingest.py` | Obsidian 위키링크 수정, delta 업데이트, evidence 추출 구조화 |
| `wiki_web/routers/admin.py` | 초기화 실패 처리, 청킹 설정 저장, 폴더 네이밍 통일 |
| `wiki_web/routers/query.py` | raw_answer 누락 수정 |

---

## 테스트

```
25 passed in 0.78s
```

전체 테스트 25개 통과.

---

## 알려진 제한 사항

- Ingest 작업은 서버 메모리에만 유지 → 서버 재시작 시 작업 이력 소실
- 임베딩 검색 첫 실행 시 모델 다운로드 약 500MB 소요
- 멀티유저 시나리오 미지원 (개인/소규모 용도)
