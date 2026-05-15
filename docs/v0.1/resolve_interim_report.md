# llm-wiki v0.1 중간 점검 보고서 — 수정 내역

> 작성일: 2026-04-21
> 원본 보고서: [docs/v0.1/interim_report.md](../interim_report.md)

---

## 수정 완료 목록

### §5.B [심각] `index.md` Sources/Entities/Concepts 섹션 행 미삽입

- **파일**: `wiki_cli/fs.py:120`
- **원인**: `_upsert_index_row` 루프 종료 시 `in_section` 플래그가 마지막 섹션일 때만 True — 나머지 섹션은 새 행 삽입 분기에 도달 불가
- **수정**: `saw_section` 플래그를 별도로 추적하여 섹션을 한 번이라도 만났으면 삽입 시도

```python
# Before
if not replaced and in_section:

# After
saw_section = False
...
    if line.startswith(f"## {section}"):
        in_section = True
        saw_section = True  # 추가
...
if not replaced and saw_section:  # in_section → saw_section
```

- **검증**: `/tmp/wiki-test` 에서 `update_index_entry` 호출 후 Entities 행 삽입 확인

---

### §5.C [중간] Orphan 탐지 — 공백 포함 페이지명 오탐

- **파일**: `wiki_cli/ops/lint.py:79`
- **원인**: 링크 측은 `link.lower().replace(" ", "-")` 정규화 적용, 페이지 측은 `page.stem.lower()` 만 사용 → `"test entity"` ≠ `"test-entity"`
- **수정**: 페이지 stem에도 동일한 정규화 적용

```python
# Before
stem_slug = page.stem.lower()

# After
stem_slug = page.stem.lower().replace(" ", "-")
```

---

### §5.A [중간] CLI `find_wiki_root()` — config 폴백 미적용

- **파일**: `wiki_cli/main.py:21`
- **원인**: cwd 상위에 `AGENTS.md` 없으면 바로 예외 발생 — 웹에서 만든 위키를 CLI가 자동 인식 불가
- **수정**: cwd 탐색 실패 시 `wiki_web.config.get_wiki_root()` 폴백 시도

```python
# 추가된 폴백 로직
try:
    from wiki_web import config as _cfg
    candidate = _cfg.get_wiki_root()
    if (candidate / "AGENTS.md").exists():
        return candidate
except Exception:
    pass
```

---

### §5.E [낮음] CLI `wiki init` — config.json 도메인 미등록

- **파일**: `wiki_cli/main.py:119` (`init` 커맨드)
- **원인**: `run_init()` 후 파일시스템만 생성하고 `~/.config/llm-wiki/config.json` 의 `domains` 배열에 미반영
- **수정**: `run_init` 성공 후 `cfg.add_domain()` + `cfg.switch_domain()` 호출

```python
from wiki_web import config as _cfg
folder = re.sub(r"[^a-z0-9]+", "-", domain.lower()).strip("-") or "my-wiki"
cfg_data = _cfg.load()
cfg_data["workspace_root"] = str(base)
_cfg.save(cfg_data)
new_domain = _cfg.add_domain(name=domain, folder=folder)
_cfg.switch_domain(new_domain["id"])
```

- 실패 시 경고만 출력하고 init 자체는 성공으로 처리 (config 등록은 선택 사항)

---

### §5.F [낮음] `/admin/test-model` · `/settings/test-model` 중복

- **파일**: `wiki_web/routers/admin.py`, `wiki_web/templates/admin.html`
- **수정**:
  - `admin.py` 의 `/admin/test-model` 엔드포인트 제거
  - `admin.html` 의 `hx-get` URL을 `/settings/test-model` 로 변경

---

## 미적용 이슈

| 이슈 | 이유 |
|------|------|
| §5.D — CLI ingest raw/ 외부 파일 허용 | 동작 변경 범위가 크고 기존 CLI 사용자 워크플로에 영향. 후속 개선 과제로 유지. |
