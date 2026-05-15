# Obsidian remotely-save 자동 동기화 연동

날짜: 2026-05-15

## 배경

ingest 또는 `wiki query --save` 완료 시 생성된 MD 파일을 Obsidian의 remotely-save 플러그인으로 자동 동기화하는 기능 추가 요청.

## 변경 파일

### 1차 — 자동 동기화 트리거

| 파일 | 변경 내용 |
|------|-----------|
| `wiki_cli/obsidian_sync.py` | 신규 생성 — `trigger_sync(wiki_root)` 함수 |
| `wiki_cli/ops/ingest.py` | `run_ingest()` 완료 직후 `trigger_sync()` 호출 |
| `wiki_cli/ops/query.py` | `--save` 저장 직후 `trigger_sync()` 호출 |
| `README.md` | Obsidian Vault 연동 섹션에 remotely-save 설정 안내 추가 |

### 2차 — 웹 설정 페이지 토글

| 파일 | 변경 내용 |
|------|-----------|
| `wiki_web/config.py` | `DEFAULTS`에 `obsidian_sync: True` 추가, `apply_env()`에서 `WIKI_OBSIDIAN_SYNC` 환경변수 적용, `save_runtime_settings()`에 `obsidian_sync` 파라미터 추가 |
| `wiki_web/routers/settings.py` | `obsidian_sync: str = Form("")` 수신 → `== "on"` 비교로 bool 변환 후 저장 |
| `wiki_web/templates/settings.html` | "Obsidian 동기화" 카드에 체크박스 토글 추가 |

## 구현 내용

### `wiki_cli/obsidian_sync.py`

- `trigger_sync(wiki_root: Path)` 함수 — `subprocess.Popen` 으로 비동기(fire-and-forget) 실행
- vault 이름 추론: `wiki_root.parent.name` → 구조상 항상 `"wiki"`
- 실행 명령: `obsidian vault=wiki command id=remotely-save:start-sync`
- `WIKI_OBSIDIAN_SYNC=off` 환경변수로 비활성화 가능
- obsidian CLI 미설치 / Obsidian 미실행 시 경고 로그만 출력, 흐름 중단 없음

### 트리거 지점

- **ingest 완료**: `run_ingest()` → `p.update(task, description="완료.")` 직후
- **query --save**: `_save_synthesis()` 반환 직후

### 웹 설정 페이지 토글

- 설정 페이지 하단 "Obsidian 동기화" 카드에 체크박스 추가
- 저장 시 `config.json`의 `obsidian_sync` 필드에 반영
- `apply_env()` 호출로 `WIKI_OBSIDIAN_SYNC` 환경변수에 즉시 적용 (앱 재시작 불필요)
- 체크박스 미체크 = HTML 폼이 필드를 아예 전송하지 않으므로 빈 문자열 → `False` 변환

## 사용자 사전 조건

1. `{workspace_root}/wiki/` 폴더를 Obsidian에서 vault(`wiki`)로 열기
2. Obsidian 커뮤니티 플러그인 — `remotely-save` 설치·활성화·원격 스토리지 연결
3. Obsidian 커뮤니티 플러그인 — `Obsidian CLI` 설치·활성화 (obsidian 명령어 제공)

## 동기화 비활성화

웹 UI 설정 페이지에서 체크박스 해제 후 저장, 또는 환경변수로 직접 제어:

```bash
export WIKI_OBSIDIAN_SYNC=off
```
