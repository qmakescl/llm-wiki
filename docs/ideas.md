# 향후 개선 아이디어

## 설치 UX

### Obsidian Vault 연동
- 초기 설치 단계에서 사용자의 Obsidian Vault 경로를 입력받아, 그 아래에 wiki를 저장
- 도메인별 wiki 폴더 구조 예시:
  ```
  {user_vault}/
  └── llm-wiki/
      ├── biology/
      │   ├── concepts/
      │   └── entities/
      ├── economics/
      └── _index.md
  ```
- 개선 방향:
  - 텍스트 입력 대신 폴더 선택 다이얼로그 (브라우저 File API) 사용
  - Mac 기준 `~/Library/Application Support/obsidian/obsidian.json` 에서 최근 Vault 목록 자동 감지

## Obsidian 외부 원본 문서(`data/raw/`) 접근 문제 해결 아이디어

**문제 배경**: 개선 19에서 워크스페이스를 `wiki/`(Obsidian Vault용)와 `data/`(운영 및 원본 데이터용)로 분리함에 따라, `wiki/` 내부 마크다운 파일의 `sources` 속성이나 본문 링크(`[text](../raw/file.pdf)`)를 통해 `data/raw/`에 위치한 원본 문서에 접근할 때, Obsidian이 볼트(Vault) 외부의 파일로 인식하여 정상적으로 열지 못하는 문제가 발생함.

### 아이디어 1: 심볼릭 링크(Symbolic Link) 활용
- **방법**: `wiki/{domain}/raw` 라는 심볼릭 링크를 생성하여 물리적으로 `data/{domain}/raw` 를 가리키게 함. 링크 생성 시 마크다운에서는 `[[raw/papers/file.pdf]]` 형식으로 접근.
- **장점**: 
  - 앱 로직 및 파일 구조의 추가 변경이 거의 불필요함.
  - Obsidian 내부에서 원본 파일이 있는 것처럼 네이티브 탭으로 투명하게 접근 가능.
- **단점**: 
  - Windows 환경의 경우 심볼릭 링크 생성 시 관리자 권한이 필요할 수 있어 이식성이 떨어짐.
  - Obsidian Sync 등 클라우드 동기화 툴에서 심볼릭 링크 폴더를 정상적으로 동기화하지 못할 우려가 있음.

### 아이디어 2: 로컬 웹 서버(llm-wiki) API 라우팅 주소(URL) 사용
- **방법**: 문서 추출(Ingest) 시 마크다운에 상대 경로를 넣는 대신, 웹 서버를 통한 다운로드 혹은 조회 URL을 하드코딩함. (예: `[원문 보기](http://localhost:8000/documents/raw?file=papers/file.pdf)`)
- **장점**: 
  - OS 파일 시스템 제약과 무관하게 완벽하게 작동.
  - 외부 파일 접근 권한 문제가 원천 차단됨.
- **단점**: 
  - llm-wiki 웹 서버가 실행 중이어야만 Obsidian에서 링크를 열람할 수 있음.
  - Obsidian 내부 PDF 뷰어 탭이 아닌 시스템의 기본 웹 브라우저 창으로 열림.

### 아이디어 3: `file:///` 절대 경로 프로토콜 삽입
- **방법**: 파일 추출 시 `data/{domain}/raw`에 해당하는 절대 경로를 생성하여 `[원본 파일](file:///Users/.../data/.../file.pdf)` 형태로 주입.
- **장점**: 서버가 꺼져 있어도 OS 기본 파일 뷰어를 통해 즉시 문서 열람 가능.
- **단점**: 
  - 파일 시스템이 다른 기기 간 동기화 시 링크가 모두 깨짐(경로 하드코딩의 한계).
  - Obsidian 앱 내부가 아닌 OS의 외부 앱으로 띄워짐.

### 아이디어 4: 원본 문서만 Vault 내부(`wiki/assets/` 등)로 부분 복귀/복사
- **방법**: `wiki/`와 `data/`의 분리 기조는 유지하되, Obsidian에서 사용자가 직접 열람해야 하는 원본 문서(PDF 등)에 한해서만 `wiki/{domain}/assets/raw/` 같은 내부 디렉터리로 복사(또는 이동)하여 관리.
- **장점**: 
  - Obsidian 네이티브 연동을 100% 활용할 수 있으며, 기기 간 동기화가 완벽하게 보장됨.
- **단점**: 
  - 원본을 보관하는 `data/` 분리 목적이 일부 훼손될 수 있음.
  - 복사할 경우 스토리지 용량을 2배로 차지하게 됨.
