# llm-wiki v0.1 프로젝트 개선 보고서

> 작성일: 2026-04-21
> 기준 문서: [instruction.md](./instruction.md)
> 대상 버전: `pyproject.toml` 기준 `0.2.0`
> 점검 범위: `wiki_cli/`, `wiki_web/`, `README.md`, `pyproject.toml`

---

## 1. 요약

- 코드베이스의 기본 방향은 적절하다. `wiki_cli`에 도메인 로직을 모으고 `wiki_web`이 얇은 래퍼로 붙는 구조는 유지보수성이 높다.
- `docs/v0.1/instruction.md`에 정리된 주요 흐름은 현재 코드와 대체로 일치한다.
- 다만 현재 개선 우선순위는 기능 추가보다도 **설정 반영 일관성**, **업로드 안전성**, **설치/온보딩 신뢰성**, **회귀 테스트 부재 해소**에 있다.
- 특히 웹 설정 변경이 런타임 동작에 즉시 반영되지 않는 지점과, 업로드 파일명 검증이 없는 지점은 v0.1 이후 안정화 단계에서 우선 처리할 가치가 크다.

---

## 2. 현재 상태 평가

### 강점

- CLI와 Web이 `run_init`, `run_ingest`, `run_query`, `run_lint`를 공유한다. 이 구조는 기능 동등성 유지에 유리하다.
- 설정이 `wiki_web/config.py`로 모이고, 웹에서 저장한 값을 CLI도 읽도록 연결되어 있다.
- SSE 기반 진행 표시와 백그라운드 ingest 구조는 사용자 경험 측면에서 방향이 좋다.
- 문서 계층(`instruction.md`, `interim_report.md`, `resolve_interim_report.md`)이 이미 형성되어 있어 개선 이력을 축적하기 쉽다.

### 제한

- 자동 검증 체계가 없다. 저장소 내 `tests/`나 `pytest` 기반 회귀 테스트가 보이지 않는다.
- 일부 핵심 동작은 "문서상 기대"와 "실제 런타임 반영 방식" 사이에 차이가 있다.
- README의 설치 가이드와 패키징 정의가 어긋나 있어 신규 작업자 온보딩 실패 가능성이 있다.

---

## 3. 우선순위별 개선 과제

### P0. 설정 변경의 런타임 반영 방식 정리

**문제**

- `wiki_web/config.py`는 설정 저장 후 `apply_env()`로 환경변수를 갱신한다.
- 그러나 `wiki_cli/llm.py`는 청킹/타임아웃/PDF 제한값을 모듈 import 시점 상수로 고정한다.
- 결과적으로 웹의 `/settings` 또는 `/admin/settings`에서 값을 바꿔도, 이미 import된 프로세스에서는 일부 설정이 즉시 반영되지 않을 수 있다.

**근거**

- [wiki_web/config.py](../../wiki_web/config.py)
- [wiki_cli/llm.py:49](../../wiki_cli/llm.py#L49)
- [wiki_cli/llm.py:53](../../wiki_cli/llm.py#L53)
- [wiki_cli/llm.py:56](../../wiki_cli/llm.py#L56)
- [wiki_cli/llm.py:57](../../wiki_cli/llm.py#L57)
- [wiki_cli/llm.py:58](../../wiki_cli/llm.py#L58)
- [wiki_cli/llm.py:60](../../wiki_cli/llm.py#L60)

**영향**

- 설정 UI 신뢰도가 떨어진다.
- 사용자는 값을 바꿨는데도 ingest 결과가 이전 청킹 전략으로 처리되는 상황을 겪을 수 있다.

**권장 개선**

- `wiki_cli/llm.py`의 환경값을 import-time 상수 대신 함수 호출 시 조회하는 방식으로 변경한다.
- 예: `_get_chunk_config()`, `_get_timeout()`, `_get_pdf_limits()` 같은 getter 함수로 전환한다.
- 설정 저장 후 재시작이 필요한 항목과 즉시 반영되는 항목을 문서에 명확히 구분한다.

### P0. 업로드 경로 안전성 보강

**문제**

- `/documents/upload`는 `dest = raw / file.filename`으로 사용자가 보낸 파일명을 그대로 경로 결합한다.
- 파일명에 상대경로 요소가 포함되면 raw 디렉터리 밖으로 이탈할 가능성이 있다.
- 파일 충돌 정책도 없어 동일 이름 업로드 시 기존 파일이 그대로 덮어써진다.

**근거**

- [wiki_web/routers/documents.py:85](../../wiki_web/routers/documents.py#L85)
- [wiki_web/routers/documents.py:87](../../wiki_web/routers/documents.py#L87)

**영향**

- 경로 traversal 및 의도치 않은 파일 덮어쓰기 위험이 있다.
- 멀티 사용자까지 가지 않더라도 로컬 웹앱으로서는 방어가 약하다.

**권장 개선**

- `Path(file.filename).name`으로 basename만 허용한다.
- 허용 확장자 목록(`.pdf`, `.md`, `.txt`)을 두고 그 외는 거부한다.
- 동일 파일명은 `(1) 덮어쓰기 금지`, `(2) 타임스탬프 suffix`, `(3) 해시 기반 rename` 중 하나로 정책화한다.
- 파일 저장 로직을 `wiki_cli/fs.py`로 이동해 CLI/Web 공용 규칙으로 통합한다.

### P1. 설치 가이드와 패키징 정의 불일치 해소

**문제**

- README는 `pip install -e ".[web]"`, `pip install -e ".[dev]"`를 안내한다.
- 하지만 `pyproject.toml`에는 `web`, `dev` optional dependency 그룹이 없다. 현재 정의된 extras는 `bm25`, `embedding`뿐이다.

**근거**

- [README.md:14](../../README.md#L14)
- [README.md:185](../../README.md#L185)
- [README.md:186](../../README.md#L186)
- [pyproject.toml:24](../../pyproject.toml#L24)

**영향**

- 신규 작업자 설치 단계에서 바로 실패한다.
- README 신뢰성이 낮아지고 운영 문서와 실제 프로젝트 정의가 어긋난다.

**권장 개선**

- 둘 중 하나로 정리한다.
- `web`와 `dev` extras를 실제로 추가한다.
- 또는 README를 현재 구조에 맞게 `pip install -e .` 중심으로 수정한다.
- `launch.sh`, `launch.bat`, README의 설치 문구를 한 번에 같이 맞춘다.

### P1. 회귀 테스트 최소 세트 도입

**문제**

- `instruction.md`에는 점검 체크리스트가 존재하지만, 이를 자동 검증하는 테스트 코드가 없다.
- 수동 점검은 이미 문서화되어 있으므로 pytest로 옮기기 좋은 상태다.

**근거**

- [instruction.md:444](./instruction.md#L444)
- 저장소 상위 구조에 `tests/` 디렉터리 없음

**영향**

- 향후 설정/파일시스템/인덱스 로직 회귀를 문서와 사람 기억에 의존하게 된다.

**권장 개선**

- `tests/`를 만들고 아래 4가지는 즉시 자동화한다.
- `config` 마이그레이션 및 active domain 해석
- `fs.update_index_entry()` 섹션별 upsert
- `lint._check_orphans()` 공백 포함 페이지명 케이스
- `create_app()` 및 CLI import smoke test

### P1. 저장 로직의 단일화

**문제**

- 일반 페이지는 `fs.write_page()`를 사용해 `created/updated/aliases` 정책을 강제한다.
- 하지만 synthesis 저장은 `wiki_cli/ops/query.py`에서 직접 파일 문자열을 작성한다.

**근거**

- [wiki_cli/fs.py:36](../../wiki_cli/fs.py#L36)
- [wiki_cli/fs.py:40](../../wiki_cli/fs.py#L40)
- [wiki_cli/ops/query.py:100](../../wiki_cli/ops/query.py#L100)
- [wiki_cli/ops/query.py:117](../../wiki_cli/ops/query.py#L117)

**영향**

- 메타데이터 정책이 분산된다.
- 향후 frontmatter 규칙이 바뀌면 synthesis만 따로 수정해야 한다.

**권장 개선**

- `_save_synthesis()`도 `fs.write_page()`를 사용하도록 맞춘다.
- `title`, `aliases`, 날짜 정책을 전 페이지 유형에서 동일하게 유지한다.

### P2. 설정 저장 엔드포인트 중복 제거

**문제**

- `/settings`와 `/admin/settings`가 거의 같은 저장 로직을 중복 구현하고 있다.

**근거**

- [wiki_web/routers/settings.py:36](../../wiki_web/routers/settings.py#L36)
- [wiki_web/routers/admin.py:179](../../wiki_web/routers/admin.py#L179)

**영향**

- 필드 추가나 검증 규칙 변경 시 한쪽만 수정될 위험이 있다.

**권장 개선**

- 설정 저장 로직을 `wiki_web/config.py` 또는 별도 service 함수로 추출한다.
- 라우터는 파라미터 파싱만 담당하고 동일 service를 호출하도록 단순화한다.

### P2. 임베딩 검색 성능 최적화

**문제**

- embedding 검색 시 `SentenceTransformer("all-MiniLM-L6-v2")`를 매 호출마다 새로 생성하고 전체 문서를 다시 인코딩한다.

**근거**

- [wiki_cli/search.py:123](../../wiki_cli/search.py#L123)
- [wiki_cli/search.py:134](../../wiki_cli/search.py#L134)
- [wiki_cli/search.py:143](../../wiki_cli/search.py#L143)

**영향**

- 문서 수가 늘수록 query 지연 시간이 급격히 커진다.
- embedding tier가 "있지만 실사용은 어려운" 기능이 되기 쉽다.

**권장 개선**

- 모델 singleton 캐시를 둔다.
- 문서별 임베딩 캐시 파일을 `data/{folder}` 아래에 관리한다.
- 문서 변경 시 부분 재계산하는 인덱싱 단계로 분리한다.

---

## 4. 제안 로드맵

### 1주차

- 업로드 파일명 sanitize 및 충돌 정책 추가
- `llm.py` 설정값 runtime getter 전환
- README 설치 가이드 정리

### 2주차

- pytest 기반 smoke/regression 테스트 도입
- synthesis 저장을 `fs.write_page()`로 통일
- 설정 저장 service 추출

### 3주차

- embedding 캐시 설계 및 성능 계측
- 운영 문서와 실제 UX 차이 재정리

---

## 5. 검증 메모

- `.venv` 기준 스모크 체크:
- `./.venv/bin/python -c "from wiki_cli.main import cli; ..."` 성공
- `./.venv/bin/python -c "from wiki_web.app import create_app; ..."` 성공
- 시스템 `python3` 기준으로는 `click`, `fastapi` 미설치로 실패
- `litellm`는 네트워크 차단 환경에서 원격 cost map fetch 경고를 출력했지만 로컬 fallback으로 import는 진행됨

---

## 6. 결론

- 이 프로젝트는 아키텍처를 다시 뒤엎을 단계가 아니다.
- 지금 필요한 것은 기능 확장보다 **설정-실행 정합성 강화**, **입출력 경계 방어**, **문서와 패키징의 일치**, **자동 회귀 검증 도입**이다.
- 위 P0/P1 항목만 정리해도 v0.1 코드베이스는 운영 안정성과 신규 작업자 진입성이 크게 좋아질 것이다.
