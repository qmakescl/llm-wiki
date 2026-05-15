# llm-wiki v0.1 개선 보고서 해결 기록

> 작성일: 2026-04-21
> 기준 문서: [project_improvement_report.md](./project_improvement_report.md)
> 대상 버전: `pyproject.toml` 기준 `0.2.0`

---

## 0. 개요

개선 보고서의 P0/P1/P2 항목을 모두 반영하고, 그 과정에서 드러난 추가 버그(문서 페이지 "추출" 버튼 클릭 무반응)를 함께 해결했다. 자동 회귀 테스트 25개를 새로 추가해 모든 변경점이 CI 가능한 형태로 보호된다.

테스트 명령어: `./.venv/bin/python -m pytest tests/ -v` → **25 passed**.

---

## 1. P0. 설정 변경의 런타임 반영 방식 정리

### 원인
`wiki_cli/llm.py`에서 `_CHUNK_STRATEGY`, `_CHUNK_SIZE`, `_CHUNK_OVERLAP`, `_MAX_CHUNKS`, `_PDF_MAX_CHARS`, `_LLM_TIMEOUT`이 import-time 상수로 고정되어 있어, `/settings` 또는 `/admin/settings`에서 값을 바꿔도 이미 로드된 프로세스에서는 반영되지 않았다.

### 해결
- import-time 상수를 제거하고 getter 함수로 전환했다: `_get_chunk_config()`, `_get_llm_timeout()`, `_get_pdf_max_chars()`.
- 각 getter는 호출 시점에 `os.environ`을 읽고, 잘못된 값(`int()` 실패)은 기본값으로 폴백한다.
- `_cap_chunks()`가 `_MAX_CHUNKS` 전역을 참조하던 부분도 파라미터로 전달받도록 변경했다.

### 수정 파일
- [wiki_cli/llm.py](../../wiki_cli/llm.py)

### 회귀 테스트
- `tests/test_llm_runtime.py::test_chunk_config_reads_env_each_call` — 환경변수 변경 후 즉시 새 값을 반환하는지 확인.
- `tests/test_llm_runtime.py::test_pdf_and_timeout_read_env_each_call`
- `tests/test_llm_runtime.py::test_invalid_env_falls_back_to_default`
- `tests/test_llm_runtime.py::test_cap_chunks_merges_to_max`

---

## 2. P0. 업로드 경로 안전성 보강

### 원인
`/documents/upload`는 `raw / file.filename`으로 사용자가 보낸 파일명을 그대로 경로 결합했다. 상대경로 요소(`../`) 포함 시 raw 디렉터리 밖으로 이탈할 수 있고, 동일 파일명 업로드 시 기존 파일이 즉시 덮어써졌다.

### 해결
`wiki_cli/fs.py`에 업로드 안전 헬퍼 3종을 추가하고 CLI/Web 공용 정책으로 통합했다.

- `sanitize_upload_name(raw_name)` — `Path(...).name`으로 basename만 추출, dotfile·NUL·빈 문자열 거부.
- `resolve_upload_path(raw, raw_name)` — 허용 확장자 화이트리스트(`.pdf/.md/.txt`), 충돌 시 `<stem>__<YYYYMMDD-HHMMSS>.<ext>` suffix, resolve 후 raw/ 내부 보장.
- `UnsafeUploadError` 예외로 거부 사유를 UI에 전달.

### 수정 파일
- [wiki_cli/fs.py](../../wiki_cli/fs.py) — 헬퍼 추가
- [wiki_web/routers/documents.py](../../wiki_web/routers/documents.py) — `fs.resolve_upload_path()` 사용, 거부 시 `<p class="log-error">` 행 반환

### 회귀 테스트
- `tests/test_fs.py::test_sanitize_upload_strips_traversal_to_basename`
- `tests/test_fs.py::test_sanitize_upload_rejects_empty_and_dotfiles`
- `tests/test_fs.py::test_sanitize_upload_strips_directory_prefix`
- `tests/test_fs.py::test_resolve_upload_path_rejects_bad_extension`
- `tests/test_fs.py::test_resolve_upload_path_collision_gets_suffix`
- `tests/test_fs.py::test_resolve_upload_path_stays_inside_raw`
- `tests/test_fs.py::test_resolve_upload_rejects_traversal_result`

---

## 3. P1. 설치 가이드와 패키징 정의 불일치 해소

### 원인
README는 `pip install -e ".[web]"`, `pip install -e ".[dev]"`를 안내했지만 `pyproject.toml`에 해당 extras가 없었다. 현재 `fastapi`·`uvicorn` 등이 이미 core dependency에 포함되어 있어 `web` extras는 불필요하다.

### 해결
- README의 설치 안내를 `pip install -e .` 중심으로 정리하고 extras는 `bm25`/`embedding`/`dev`로 명시.
- `pyproject.toml`에 실제 `dev` extras(`pytest`, `httpx`)를 추가해 README와 정합성 확보.

### 수정 파일
- [README.md](../../README.md)
- [pyproject.toml](../../pyproject.toml)

---

## 4. P1. 저장 로직의 단일화 (synthesis)

### 원인
일반 페이지는 `fs.write_page()`가 `created/updated/aliases` 정책을 강제하는 반면, `wiki_cli/ops/query.py::_save_synthesis()`는 직접 `page_path.write_text()`로 파일 문자열을 작성해 frontmatter 정책이 분산되어 있었다.

### 해결
`_save_synthesis()`가 `metadata = {"title": ..., "type": "synthesis", "tags": []}`와 본문을 분리해 `fs.write_page()`에 위임하도록 변경. 날짜·aliases 정책이 다른 페이지 유형과 일치한다.

### 수정 파일
- [wiki_cli/ops/query.py](../../wiki_cli/ops/query.py)

### 회귀 테스트
- `tests/test_fs.py::test_write_page_sets_aliases_from_title` — write_page 정책이 title → aliases 자동 생성을 유지하는지 확인 (synthesis도 이 경로를 공유).

---

## 5. P1. 설정 저장 service 추출 (settings/admin 중복 제거)

### 원인
`/settings`와 `/admin/settings`가 거의 동일한 저장 로직을 각자 구현하고 있었다. 필드를 추가하거나 검증 규칙을 바꿀 때 한쪽만 수정될 위험이 있었다.

### 해결
`wiki_web/config.py`에 `save_runtime_settings(**kwargs)` 서비스 함수를 추가했다. 폼 필드 정규화(커스텀 모델 스트립, chunk_overlap < chunk_size clamp), `save()`, `apply_env()`까지 한 번에 수행한다. 두 라우터는 파라미터 파싱만 담당하고 이 서비스를 호출한다.

### 수정 파일
- [wiki_web/config.py](../../wiki_web/config.py) — `save_runtime_settings()` 추가
- [wiki_web/routers/settings.py](../../wiki_web/routers/settings.py)
- [wiki_web/routers/admin.py](../../wiki_web/routers/admin.py)

### 회귀 테스트
- `tests/test_config.py::test_save_runtime_settings_applies_env` — clamp 동작 및 env 반영 검증.
- `tests/test_config.py::test_save_runtime_settings_custom_model` — `__custom__` 경로 검증.

---

## 6. P1. 회귀 테스트 최소 세트 도입

### 원인
`docs/v0.1/instruction.md`에는 수동 점검 체크리스트만 존재했고 `tests/` 디렉터리 자체가 없었다. 설정·파일시스템·인덱스 회귀는 사람 기억에 의존했다.

### 해결
`tests/` 디렉터리와 pytest 기반 스위트를 신설했다. 보고서에서 지목된 4가지 영역이 모두 커버된다.

- `tests/conftest.py` — `isolated_config` fixture로 `CONFIG_FILE`을 `tmp_path`로 리다이렉트하여 실제 사용자 config를 절대 건드리지 않게 한다.
- `tests/test_config.py` — 구형 `wiki_root` → `workspace_root`+`folder` 2단 마이그레이션, active domain 폴백, `save_runtime_settings()`.
- `tests/test_fs.py` — 업로드 sanitize, 충돌 정책, `update_index_entry()` 섹션별 upsert, `write_page()` aliases 정책, 신규 `file_slug()`.
- `tests/test_lint.py` — `_check_orphans`가 `[[Self Attention]]` 같이 공백 포함 wikilink를 slug 매칭으로 처리하는지, synthesis 제외 로직.
- `tests/test_llm_runtime.py` — llm.py getter 동작과 `_cap_chunks`.
- `tests/test_smoke.py` — CLI import 및 `create_app()` 부팅 smoke.

현재 **25개 테스트 모두 통과**.

### 수정 파일
- `tests/__init__.py`, `tests/conftest.py`
- `tests/test_config.py`, `tests/test_fs.py`, `tests/test_lint.py`
- `tests/test_llm_runtime.py`, `tests/test_smoke.py`

---

## 7. P2. 임베딩 검색 성능 최적화

### 원인
`_embedding_search()`가 매 쿼리마다 `SentenceTransformer("all-MiniLM-L6-v2")`를 새로 로드하고 전체 문서를 다시 인코딩했다. 문서 수가 늘수록 query 지연이 급격히 커져 embedding tier가 "있지만 실사용은 어려운" 상태였다.

### 해결
- `_EMBEDDING_MODEL` 모듈 전역 singleton 도입 — 첫 호출 시 한 번만 로드하고 이후 재사용.
- per-file SHA1 해시를 키로 하는 임베딩 디스크 캐시 추가. 경로: `<wiki_dir>/.embeddings/<model>.pkl`.
- `_compute_doc_embeddings()`가 변경된 파일(해시가 캐시에 없는 것)만 `encode()` 배치 처리. 나머지는 즉시 재사용.
- `_load_cache()` / `_save_cache()`는 pickle 실패를 grep 폴백이 아니라 "캐시 리셋"으로만 처리해 검색 기능은 항상 복구 가능.

### 수정 파일
- [wiki_cli/search.py](../../wiki_cli/search.py)

---

## 8. 추가 버그. 문서 페이지 "추출" 버튼 클릭 무반응

보고서에는 없었으나 수정 직후 확인 과정에서 드러난 클라이언트-사이드 버그.

### 증상
`/documents` 에서 파일 옆의 "추출" 버튼을 클릭해도 아무 일도 일어나지 않는다. 서버 로그에도 요청이 남지 않는 경우가 있다.

### 원인
파일명 `A Comparative Study of AI Agent Orchestration Frameworks _ by Kiumarse Zamanian, PhD _ Medium.pdf`에 쉼표(`,`)가 포함되어 있었다. slug 생성 로직이 `stem.lower().replace(" ", "-")`만 수행해 slug에 `,`가 그대로 들어갔다.

결과적으로 렌더된 HTML은 다음과 같다.

```html
hx-target="#ingest-ctrl-...zamanian,-phd-..."
```

CSS selector에서 쉼표는 **selector 분리자**이므로 위 값은 `#ingest-ctrl-...zamanian`과 `-phd-...` 두 selector로 파싱된다. 두 번째 토큰은 유효하지 않은 id selector라 `document.querySelector(...)`가 에러/미매칭 상태가 되고, HTMX는 target을 찾지 못해 요청을 중단한다. 동일 문제가 `hx-indicator`에도 있었다.

### 해결
1. `wiki_cli/fs.py`에 `file_slug(stem)` 함수를 추가해 CSS id·URL 경로에서 안전한 문자 집합(`[a-z0-9가-힣_-]`) 외를 모두 `-`로 치환하도록 통일.
2. slug를 계산하는 모든 지점을 이 함수로 교체.
   - [wiki_web/routers/documents.py](../../wiki_web/routers/documents.py) — 목록, 업로드, `_find_source`.
   - [wiki_cli/ops/ingest.py](../../wiki_cli/ops/ingest.py) — `run_ingest()` 내 slug 계산.
3. 기존에 이미 ingest된 파일의 slug를 깨뜨리지 않도록 underscore(`_`)는 보존 (예: `google_ai_agents_handbook`, `ms_the-ai-decision-brief`).

### 검증
- 재실행 후 렌더된 HTML에서 `hx-post="/documents/ingest/a-comparative-study-of-ai-agent-orchestration-frameworks-_-by-kiumarse-zamanian-phd-_-medium"` — 쉼표 제거됨.
- 회귀 테스트 3종:
  - `tests/test_fs.py::test_file_slug_strips_css_selector_chars`
  - `tests/test_fs.py::test_file_slug_preserves_existing_underscore_slug`
  - `tests/test_fs.py::test_file_slug_empty_fallback`

---

## 9. 전체 변경 요약

### 수정된 파일

| 구분 | 파일 |
| --- | --- |
| 런타임 | [wiki_cli/llm.py](../../wiki_cli/llm.py) |
| 파일시스템 | [wiki_cli/fs.py](../../wiki_cli/fs.py) |
| CLI ops | [wiki_cli/ops/query.py](../../wiki_cli/ops/query.py), [wiki_cli/ops/ingest.py](../../wiki_cli/ops/ingest.py) |
| 검색 | [wiki_cli/search.py](../../wiki_cli/search.py) |
| 웹 | [wiki_web/config.py](../../wiki_web/config.py), [wiki_web/routers/documents.py](../../wiki_web/routers/documents.py), [wiki_web/routers/settings.py](../../wiki_web/routers/settings.py), [wiki_web/routers/admin.py](../../wiki_web/routers/admin.py) |
| 패키징 | [pyproject.toml](../../pyproject.toml), [README.md](../../README.md) |
| 테스트 | `tests/__init__.py`, `tests/conftest.py`, `tests/test_config.py`, `tests/test_fs.py`, `tests/test_lint.py`, `tests/test_llm_runtime.py`, `tests/test_smoke.py` |

### 테스트 실행

```bash
./.venv/bin/python -m pytest tests/ -v
# 25 passed in ~0.8s
```

### 남은 과제 (보고서 로드맵 3주차 이후)

- embedding 캐시 실측 성능 계측 (현재는 캐시 로직만 도입).
- 설정 저장 후 "재시작 필요 vs 즉시 반영" 항목을 UI에서 구분해 표기.
- Obsidian Vault 연동 문서 별도 정리 (`docs/ideas.md` 누적).
