# 배포 전 체크리스트 — v0.2.1

## 코드 품질

- [x] 전체 테스트 통과 (`pytest tests/ -q` → 25/25)
- [x] `wiki_cli/` 와 `wiki_web/` 임포트 정상 동작
- [x] 알려진 버그 7개 수정 완료
- [x] 성능 개선 2개 적용 완료

## 파일 구성

- [x] `pyproject.toml` — 버전 0.2.0, 의존성 명시
- [x] `launch.sh` — macOS/Linux 원클릭 실행 (Python 버전 확인, venv 자동 생성)
- [x] `launch.bat` — Windows 원클릭 실행
- [x] `README.md` — v0.2.1 기준으로 업데이트 (Obsidian 연동, 위키 구조, CLI 명령어)

## 기능 확인 항목

- [x] `wiki init` CLI 명령어 정상 실행
- [x] 멀티 도메인 추가/전환/삭제
- [x] 파일 업로드 (드래그앤드롭 + 다중 파일)
- [x] 백그라운드 Ingest + SSE 진행 표시
- [x] Obsidian 위키링크 (`[[Entity Name]]`) 정상 동작
- [x] Q&A 질문 + synthesis 저장
- [x] 청킹 전략 설정 저장 (`/admin`)
- [x] 위키 초기화 실패 시 에러 표시 (500 아님)

## 의존성

- [x] 핵심 의존성 모두 `pyproject.toml`에 명시
- [x] 선택 의존성 (`bm25`, `embedding`, `dev`) extras로 분리
- [x] `uv.lock` 최신 상태

## 알려진 제한 사항 (미해결, 다음 버전 예정)

- [ ] Ingest 작업 영속화 (서버 재시작 시 이력 소실)
- [ ] 임베딩 검색 최초 모델 다운로드 진행 표시
- [ ] 멀티유저 지원
