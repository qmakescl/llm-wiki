# llm-wiki v0.1 중간 점검 보고서

> 점검 일자: 2026-04-21
> 대상 버전: v0.1 (pyproject `0.2.0`)
> 점검 목적: (1) 전체 코드 구조 점검 · (2) 데이터 생성·전달 정합성 확인 · (3) CLI와 Web의 동작 동등성 검증

---

## 1. 요약

- **구조 건전성**: 전반적으로 `wiki_cli`(도메인 로직) + `wiki_web`(FastAPI 래퍼) 2계층 분리가 깔끔하게 유지되고 있음. 웹 라우터는 모두 `asyncio.to_thread(...)`로 CLI `ops/*`를 그대로 호출하므로 **핵심 파이프라인은 한 벌**.
- **CLI ↔ Web 동등성**: Ingest / Query / Lint / Init 모두 동일한 `run_*()` 함수 진입점을 공유하므로 **논리적 동등성은 확보**. 단, **진입 시점에 wiki_root를 찾는 방식이 다름**(아래 §5.A 참조).
- **치명 버그 발견 (§5.B)**: [wiki_cli/fs.py:120](wiki_cli/fs.py#L120) `_upsert_index_row` 는 **마지막 섹션(Synthesis) 외에는 행을 삽입하지 않음**. 결과적으로 CLI·Web 모두 Ingest 후 `index.md`의 Sources/Entities/Concepts 표가 영원히 비어 있음.
- **중간 심각도 버그 (§5.C)**: [wiki_cli/ops/lint.py:80](wiki_cli/ops/lint.py#L80) orphan 탐지는 공백이 포함된 페이지명(예: `Test Entity.md`)을 항상 고아로 오탐.

---

## 2. 전체 구조도

```
┌─────────────────────── 사용자 진입점 (2가지) ─────────────────────────┐
│                                                                      │
│  ① 브라우저                              ② 터미널                     │
│    ↓                                       ↓                          │
│  launch.sh / launch.bat                  wiki <command>               │
│    ↓                                       ↓                          │
│  python -m wiki_web                      wiki_cli/main.py             │
│    ↓                                       │   _apply_saved_config()  │
│  uvicorn + FastAPI                         │   find_wiki_root(cwd)    │
│    ↓                                       ↓                          │
│  wiki_web/app.py (create_app)            click 명령 디스패치           │
│    ↓                                       │                          │
│  Jinja2 + HTMX 템플릿                      │                          │
│    ↓                                       │                          │
│  wiki_web/routers/*.py                     │                          │
│    ├─ wiki.py       (대시보드 / 초기화)     │                          │
│    ├─ documents.py  (파일 업로드 + SSE)    │                          │
│    ├─ query.py      (Q&A + SSE)           │                          │
│    ├─ synthesis.py  (저장된 답변 관리)      │                          │
│    ├─ lint.py       (건강 검사)            │                          │
│    ├─ settings.py   (모델/검색/청킹)        │                          │
│    └─ admin.py      (도메인 CRUD)          │                          │
│         │                                  │                          │
│         └─────── asyncio.to_thread ───────►│                          │
│                                            ▼                          │
│                                 wiki_cli/ops/*.py (공통 파이프라인)   │
│                                   ├─ init.py    run_init              │
│                                   ├─ ingest.py  run_ingest            │
│                                   ├─ query.py   run_query             │
│                                   └─ lint.py    run_lint              │
│                                            │                          │
│                                            ▼                          │
│                               wiki_cli/{llm,search,fs}.py             │
│                                   llm.call / call_with_file           │
│                                   search.search (grep/BM25/embedding) │
│                                   fs.read_page / write_page /         │
│                                   update_index_entry / append_log     │
│                                            │                          │
│                                            ▼                          │
│                           파일시스템 (워크스페이스)                    │
│                           └─ {workspace_root}/                        │
│                               ├─ wiki/{folder}/  (Obsidian Vault)     │
│                               │   ├─ AGENTS.md · index.md · log.md    │
│                               │   ├─ sources/  · entities/            │
│                               │   └─ concepts/ · synthesis/           │
│                               └─ data/{folder}/                       │
│                                   └─ raw/{papers,articles,assets}/    │
│                                                                       │
│  설정 단일 진실: ~/.config/llm-wiki/config.json                        │
│  (웹은 config 기준 / CLI는 cwd 기준 + config env 적용)                 │
└───────────────────────────────────────────────────────────────────────┘
```

---

## 3. 데이터 흐름도

### 3-A. Ingest 파이프라인 ([wiki_cli/ops/ingest.py](wiki_cli/ops/ingest.py))

```
 [사용자]
   │  웹: POST /documents/upload → raw/{파일}
   │     POST /documents/ingest/{slug}
   │  CLI: wiki ingest <path>
   ▼
 run_ingest(wiki_root, source, model, progress_callback)
   │
   ├─ 중복 검사: wiki/sources/{slug}.md 존재 여부 → DuplicateSourceError
   │
   ├─ Step 1. 소스 읽기 + 요약 ▶ llm.call_with_file
   │    └─ PDF→pypdf / MD→read_text → 청킹(_CHUNK_STRATEGY) → LLM "overview"
   │
   ├─ Step 2. 관련 페이지 계획 ▶ _plan_related_pages(overview)
   │    └─ LLM 출력을 `ENTITIES:` / `CONCEPTS:` 섹션 파싱
   │       → (action, slug) 튜플 리스트 × 2
   │
   ├─ Step 3. 소스 요약 페이지 작성 ▶ llm.call
   │    └─ planned entity/concept 이름을 프롬프트에 주입 (위키링크 이름 통일)
   │    └─ _parse_llm_page (```yaml / --- 양형식 지원) → fs.write_page
   │    → wiki/sources/{slug}.md  (frontmatter + 본문, aliases 자동)
   │
   ├─ Step 4. index.md 업데이트 ▶ fs.update_index_entry
   │    ⚠ _upsert_index_row 버그: 마지막 섹션 외에는 행 미삽입 (§5.B)
   │
   ├─ Step 5. 엔티티/개념 페이지 작성 ▶ _write_or_update_page × N
   │    └─ display_name = slug.replace("-"," ").title()
   │    └─ 파일명 = {display_name}.md  (Obsidian [[위키링크]] 호환)
   │    → wiki/entities/{Display}.md · wiki/concepts/{Display}.md
   │
   └─ Step 6. 로그 기록 ▶ fs.append_log
       → wiki/log.md 에 `## [YYYY-MM-DD] ingest | ...` 추가

  진행 메시지:
    CLI: rich.Progress 스피너 (progress_callback=None)
    Web: progress_callback = IngestJob.emit → SSE 스트림 + 누적 버퍼
```

### 3-B. Query 파이프라인 ([wiki_cli/ops/query.py](wiki_cli/ops/query.py))

```
 [사용자]
   │  웹: POST /query  (question, save)
   │  CLI: wiki query "…" [--save]
   ▼
 run_query(wiki_root, question, model, save, progress_callback)
   │
   ├─ Step 1. index.md 읽기 ▶ search.read_index
   │
   ├─ Step 2. 관련 페이지 검색 ▶ search.search(top_k=6)
   │    └─ WIKI_SEARCH 환경변수로 티어 전환
   │       - grep    : 단어 빈도 기반 정렬 (기본)
   │       - bm25    : rank_bm25 (옵션 설치)
   │       - embedding: sentence-transformers (옵션 설치)
   │
   ├─ Step 3. 컨텍스트 구성 ▶ _build_context
   │    └─ 각 페이지 앞 3000자 발췌 + 점수 표시
   │
   ├─ Step 4. LLM 답변 생성 ▶ llm.call
   │
   ├─ (선택) Step 5. synthesis 저장 ▶ _save_synthesis
   │    → wiki/synthesis/{slug}.md  (frontmatter + Q + answer)
   │    → fs.update_index_entry  (Synthesis 섹션 — 버그 영향 없음)
   │
   └─ Step 6. 로그 ▶ fs.append_log

  답변 출력:
    CLI: rich.Markdown 콘솔 출력, --save 또는 _is_notable 시 저장 프롬프트
    Web: render_answer (마크다운 → HTML + [[…]] → wiki-entity-tag/source-btn SVG)
         SSE `event: done` 으로 query_result.html 조각 전송
         /query/save 별도 엔드포인트로 LLM 재호출 없이 저장
```

### 3-C. Lint 파이프라인 ([wiki_cli/ops/lint.py](wiki_cli/ops/lint.py))

```
 run_lint(wiki_root, model, auto_fix)
   │
   ├─ fs.list_pages → 대상 페이지 집합
   ├─ _check_orphans     ▶ 위키링크 역참조 집합 대비 페이지 stem 비교
   │                       ⚠ 공백/하이픈 정규화 버그 (§5.C)
   ├─ _check_todos       ▶ `<!-- TODO: verify -->` 검색
   ├─ _check_stale       ▶ frontmatter `updated` > 90일
   └─ _check_with_llm    ▶ 샘플 20개 페이지 발췌 → LLM 모순·미싱 페이지 탐지

  웹: /lint/run → _collect_issues(root, model) → 렌더링
  CLI: rich.Table 콘솔 출력
```

### 3-D. Init 파이프라인 ([wiki_cli/ops/init.py](wiki_cli/ops/init.py))

```
 run_init(wiki_root, data_root, domain)
   ├─ AGENTS.md 생성 (도메인 명시 + 규칙)
   ├─ wiki/{sources,entities,concepts,synthesis}/.gitkeep
   ├─ data/raw/{papers,articles,assets}/.gitkeep
   ├─ wiki/index.md (빈 표 4개)
   └─ wiki/log.md (init 항목)

  CLI 호출: wiki init [DIR] -d "domain"
       → base/wiki  , base/data  (base = DIR)
  Web 호출: POST /  (dashboard),  POST /admin/domains/{id}/init
       → {ws}/wiki/{slug}, {ws}/data/{slug}
       → config.json 에 도메인 자동 등록 + active_domain_id 갱신
```

---

## 4. CLI vs Web 동등성 점검 매트릭스

| 항목                               | CLI 동작                                              | Web 동작                                                        | 동등성                  |
|:-----------------------------------|:-----------------------------------------------------|:----------------------------------------------------------------|:------------------------|
| wiki_root 결정                     | `find_wiki_root()`: cwd부터 상위로 `AGENTS.md` 탐색  | `cfg.get_wiki_root()`: `workspace_root/wiki/{folder}`           | **⚠ 비동등** (§5.A)    |
| 설정 적용                          | `_apply_saved_config()` → 환경변수                   | `cfg.apply_env()` @ `create_app` + 저장 시                      | ✓ 동일 env vars        |
| 모델 선택                          | `--model` > `WIKI_MODEL` > Ollama 감지 > 클라우드    | settings.model > 동일 해석                                       | ✓ (resolve_model 공유)  |
| 검색 티어                          | `WIKI_SEARCH` env                                    | `cfg.search_tier` → env                                         | ✓                       |
| 청킹 전략                          | `WIKI_CHUNK_*` env                                   | `cfg.chunk_*` → env                                             | ✓                       |
| Ingest 진행 상태                   | `rich.Progress` 스피너                               | `IngestJob.emit` → SSE + 누적 버퍼 (재연결 가능)                 | ◐ UX 차이, 파이프라인 동일 |
| Ingest 입력 소스                   | 임의 경로의 파일 허용 (raw/ 강제 아님)               | 업로드 시 자동으로 `data_root/raw/` 저장                          | ◐ CLI는 검증 약함      |
| 중복 ingest 처리                   | `DuplicateSourceError` 예외                           | `DuplicateSourceError` → `job.emit_error`                        | ✓                       |
| Query 실행                         | `run_query(..., progress_callback=None)`              | `run_query(..., progress_callback=channel.emit)`                 | ✓ 같은 함수             |
| Query 답변 저장                    | `--save` 또는 `_is_notable` → 대화형 확인             | 폼 `save=true` 또는 `/query/save` 별도 엔드포인트                 | ✓ 결과 파일 동일        |
| Query 출력 렌더링                  | `rich.Markdown` 콘솔                                   | `render_answer` HTML + wiki 태그 SVG                             | ◐ 표현만 다름, 내용 동일 |
| Lint                                | CLI가 `run_lint` 실행 → `rich.Table`                  | `_collect_issues` 가 내부 `_check_*` 재호출 → HTML 테이블        | ✓ 같은 검사 함수        |
| Init                                | `wiki init DIR` → `DIR/wiki` + `DIR/data`             | `POST /init` → `ws/wiki/{slug}` + config.json 등록               | ⚠ CLI는 config 미기록   |
| log.md append                       | `fs.append_log`                                        | 동일                                                             | ✓                       |
| index.md 업데이트                  | `fs.update_index_entry`                                | 동일                                                             | ⚠ 공통 버그 (§5.B)     |

- ✓ 동등  /  ◐ 기능 동등 · UX 다름  /  ⚠ 동등성 결함

---

## 5. 발견된 이슈

### 5.A [중간] CLI가 config.json의 active_domain을 참조하지 않음

- 위치: [wiki_cli/main.py:21-29](wiki_cli/main.py#L21-L29) `find_wiki_root`
- 현상: 사용자가 웹에서 `~/llm-wikis/wiki/ai_research` 도메인을 활성화해도, 쉘에서 `wiki query "..."` 를 실행하면 **cwd 상위에 `AGENTS.md`가 없으면 실패**.
- 영향: "원클릭 런처 + CLI 병용" 시나리오에서 혼란. 사용자가 매번 `cd`를 해야 함.
- 권장: `_apply_saved_config()` 이후 `find_wiki_root()` 실패 시 `cfg.get_wiki_root()` 폴백. 웹에서 초기화된 위키도 CLI가 그대로 사용할 수 있도록.

### 5.B [심각] `index.md` 의 Sources/Entities/Concepts 섹션이 영구 비어있음

- 위치: [wiki_cli/fs.py:120-145](wiki_cli/fs.py#L120-L145) `_upsert_index_row`
- 원인: 루프에서 `in_section` 플래그는 다음 `## ` 헤더를 만나면 False로 재설정됨. 따라서 루프 종료 시점에 `in_section`은 **파일의 마지막 섹션이 대상일 때만 True**. 이후 `if not replaced and in_section:` 분기가 걸리지 않아 **새 행이 삽입되지 않음**.
- 재현:
  ```python
  from wiki_cli import fs
  from pathlib import Path
  root = Path('/tmp/wiki-test/wiki')  # wiki init 완료 상태
  fs.write_page(root/'entities'/'Test Entity.md', {'title':'Test Entity','type':'entity'}, '# Test')
  fs.update_index_entry(root, root/'entities'/'Test Entity.md', 'Test Entity', 'desc')
  # index.md 확인 → Entities 표가 여전히 비어있음.
  # 동일 동작을 synthesis/ 에서 시도하면 정상 삽입됨 (마지막 섹션이라서).
  ```
- 영향: **CLI·Web 공통**. Ingest가 매번 정상처럼 완료돼도 대시보드의 index 표(Sources/Entities/Concepts)는 항상 빈 상태. Pages 카운트(`_refresh_index_header`)만 증가하므로 사용자 관점에서 "기록은 되는 듯한데 목록이 안 보인다"는 혼란 유발.
- 권장 수정 방향:
  ```python
  # 루프 종료 시 in_section 대신 "우리 섹션을 한 번이라도 만났는가" 플래그 사용
  saw_section = False
  for line in lines:
      if line.startswith(f"## {section}"):
          in_section = True; saw_section = True
      elif line.startswith("## ") and in_section:
          in_section = False
      ...
  if not replaced and saw_section:
      # 기존 삽입 로직 그대로
  ```

### 5.C [중간] Orphan 탐지가 공백을 포함한 페이지명을 오탐

- 위치: [wiki_cli/ops/lint.py:71-80](wiki_cli/ops/lint.py#L71-L80) `_check_orphans`
- 현상: 링크 측은 `link.lower().replace(" ", "-")` 로 정규화(예: `[[Test Entity]]` → `"test-entity"`)하지만, 페이지 측은 `page.stem.lower()`(예: `"test entity"`) 로만 비교.
- 결과: 공백이 포함된 모든 엔티티/개념 페이지는 **들어오는 링크가 있어도 orphan으로 분류됨**.
- 권장 수정: 양쪽 모두 `.replace(" ", "-")` 적용 또는 반대 방향으로 `-`를 공백으로 복원한 뒤 비교.

### 5.D [낮음] CLI `ingest` 가 raw/ 바깥 파일도 허용

- 위치: [wiki_cli/main.py:47-67](wiki_cli/main.py#L47-L67)
- 현상: AGENTS.md 규칙은 "raw/ 는 읽기 전용"을 명시하지만, CLI는 임의 경로를 받아 처리하고 파일을 raw/로 복사하지도 않음. 웹은 업로드 시 자동으로 `data_root/raw/`에 저장.
- 영향: CLI로 ingest한 소스는 `sources/{slug}.md` 는 생기지만 `data/raw/` 와 연결되지 않아 추후 재처리·링크(`raw/{source.name}`)가 깨질 수 있음.
- 권장: (a) 경로가 raw/ 밖이면 경고 후 복사 / (b) raw/ 기준 상대경로 강제.

### 5.E [낮음] CLI `init` 이 config.json 에 도메인을 등록하지 않음

- 위치: [wiki_cli/ops/init.py:13-33](wiki_cli/ops/init.py#L13-L33)
- 현상: `wiki init ~/new-wiki -d "foo"` 으로 만든 위키는 파일은 만들어지지만 `~/.config/llm-wiki/config.json` 의 `domains` 배열에 반영되지 않음. 결과: 웹 `/admin` 에는 보이지 않음.
- 권장: run_init 성공 후, 웹 `init_wiki` 와 동일하게 domains 배열에 추가 + active 로 지정하는 헬퍼 호출.

### 5.F [낮음] `/settings/test-model` 과 `/admin/test-model` 중복

- 위치: [wiki_web/routers/settings.py:87-94](wiki_web/routers/settings.py#L87-L94), [wiki_web/routers/admin.py:210-218](wiki_web/routers/admin.py#L210-L218)
- 완전히 동일한 동작을 하는 엔드포인트 2개. 한 곳으로 통일 권장.

---

## 6. 데이터 생성·전달 점검 결과

| 단계                       | 생성 결과물                                            | 상태                                          |
|:---------------------------|:-------------------------------------------------------|:----------------------------------------------|
| init                       | AGENTS.md, index.md, log.md, 4개 하위폴더              | ✓ CLI·Web 동일 (§5.E는 설정 등록 누락만)      |
| upload (Web)               | `data/{folder}/raw/{filename}`                         | ✓                                             |
| ingest → sources/          | `sources/{slug}.md` (frontmatter + aliases)            | ✓                                             |
| ingest → entities/concepts | `entities/{Display}.md` / `concepts/{Display}.md`      | ✓ (Obsidian 위키링크 호환)                   |
| ingest → index.md          | Pages 카운트만 갱신, 섹션 표 미갱신                     | **✗ §5.B 버그**                               |
| ingest → log.md            | `## [YYYY-MM-DD] ingest | …` 추가                      | ✓                                             |
| query → synthesis/         | `synthesis/{question-slug}.md`                         | ✓                                             |
| query → index.md Synthesis | 행 삽입                                                 | ✓ (마지막 섹션이라 §5.B 영향 없음)           |
| query → log.md             | `## [YYYY-MM-DD] query | …` 추가                       | ✓                                             |
| lint                       | 결과 리스트                                             | ◐ orphan 검사 오탐 (§5.C)                    |
| 설정 저장                  | `~/.config/llm-wiki/config.json` + env vars            | ✓                                             |
| SSE 진행 스트림 (Web)      | `IngestJob.messages` 누적 + 재연결 안전                | ✓                                             |
| SSE done (Query)           | `render_answer` HTML 을 multi-line `data:` 로 전송      | ✓                                             |

---

## 7. 결론 / 권장 액션

1. **§5.B를 최우선으로 수정할 것.** Ingest 흐름의 핵심 산출물인 `index.md` 표가 기능하지 않아 사용자 신뢰에 직결.
2. **§5.A를 보조로 수정.** CLI 사용자가 웹에서 만든 위키를 자연스럽게 이어받도록 `find_wiki_root()`에 config 폴백을 추가.
3. §5.C·§5.E·§5.F 는 후속 개선 과제로 큐잉.
4. 파이프라인(ops 계층)은 CLI·Web 이 완전히 공유하므로, 위 수정은 **한 곳에서만 고쳐도 양쪽 모두 반영**된다는 장점이 유지됨.

### 검증에 사용한 명령

```bash
# 임포트 건전성
python3 -c "from wiki_cli.main import cli; from wiki_cli.ops import ingest, query, lint, init"

# CLI 도움말
python3 -c "from click.testing import CliRunner; from wiki_cli.main import cli; \
  print(CliRunner().invoke(cli, ['--help']).output)"

# init + index 업서트 재현 (§5.B)
cd /tmp && rm -rf wiki-test && mkdir wiki-test && cd wiki-test
python3 -c "from wiki_cli.ops.init import run_init; from pathlib import Path; \
  run_init(Path('wiki'), Path('data'), 'test')"
python3 -c "from wiki_cli import fs; from pathlib import Path; \
  r=Path('wiki'); \
  fs.write_page(r/'entities'/'Test Entity.md', {'title':'Test Entity','type':'entity'}, '# x'); \
  fs.update_index_entry(r, r/'entities'/'Test Entity.md', 'Test Entity', 'd'); \
  print(open(r/'index.md').read())"
```

> 재현 결과: Entities 섹션 표는 비어있고 헤더 Pages 카운트만 증가 → §5.B 확정.
