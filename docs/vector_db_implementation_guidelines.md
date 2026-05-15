# 벡터 DB 구축 구현 지침

> 작성일: 2026-05-15  
> 목적: 현재 lazy embedding 검색을 ingest-time chunk vector indexing 구조로 확장하기 위한 구현 지침을 정리한다.  
> 기준 코드: `wiki_cli/search.py`, `wiki_cli/ops/ingest.py`, `wiki_cli/search_index.py`, `wiki_web/config.py`

## 1. 목표

현재 임베딩 검색은 query 시점에 `wiki/*.md` 파일을 훑고, 각 파일 앞 2,000자만 `all-MiniLM-L6-v2`로 임베딩해 pickle 캐시에 저장한다. 이 방식은 가볍지만 긴 문서, 다주제 문서, 섹션 단위 근거 검색에 약하다.

벡터 DB 도입의 목표는 다음과 같다.

- ingest 완료 시점에 페이지를 chunk 단위로 임베딩한다.
- chunk vector와 출처 메타데이터를 로컬 DB에 저장한다.
- query 시점에는 이미 저장된 vector index에서 관련 chunk를 검색한다.
- LLM context에는 페이지 전체보다 관련 chunk와 출처 정보를 우선 전달한다.
- 기존 `grep`, `bm25`, `embedding` 검색 경로와 CLI/Web 진입점은 유지한다.

## 2. 권장 1차 설계

1차 구현은 외부 서버 없이 로컬 파일로 끝나는 구성을 권장한다.

| 항목 | 선택 |
|---|---|
| 벡터 저장소 | SQLite 기반 로컬 인덱스 |
| 임베딩 모델 | 현재 모델 유지: `sentence-transformers` `all-MiniLM-L6-v2` |
| 인덱싱 시점 | ingest 완료 후 생성/수정된 markdown page 기준 upsert |
| 검색 단위 | page-level이 아니라 chunk-level |
| 검색 API | 기존 `search.search()` 인터페이스 유지 |
| fallback | 벡터 DB/모델 사용 불가 시 기존 `_embedding_search()` 또는 grep으로 fallback |

SQLite 확장은 실제 구현 시 환경 안정성을 확인해 선택한다.

- `sqlite-vec`: 단일 파일 배포에 적합한 최신 후보
- `sqlite-vss`: Faiss 기반 후보
- fallback: 확장 설치가 부담스러우면 SQLite metadata table + NumPy brute-force부터 시작

처음부터 Qdrant, Chroma, Pinecone 같은 외부/별도 서버형 DB를 붙이지 않는다. 개인 위키 앱의 설치 난이도와 백업 단순성이 더 중요하다.

## 3. 저장 위치

벡터 인덱스는 wiki 콘텐츠 디렉터리 아래 숨김 디렉터리에 둔다.

```text
<wiki_dir>/.vectors/
  vector_index.sqlite
```

현재 임베딩 pickle 캐시 위치인 `<wiki_dir>/.embeddings/`와는 별도로 둔다. 새 구조가 안정화되기 전까지 기존 캐시는 삭제하지 않는다.

## 4. 메타데이터 스키마

최소 스키마는 다음 필드를 포함한다.

| 필드 | 설명 |
|---|---|
| `chunk_id` | 안정적인 chunk id. 예: `sha1(wiki_path + heading + chunk_index + content_hash)` |
| `wiki_path` | `wiki_dir` 기준 상대 경로 |
| `page_title` | frontmatter title 또는 파일 stem |
| `heading` | chunk가 속한 markdown heading |
| `chunk_index` | 페이지 내 chunk 순번 |
| `chunk_text` | LLM context에 넣을 실제 텍스트 |
| `content_hash` | chunk text 기준 SHA1 또는 SHA256 |
| `model_name` | 임베딩 모델명 |
| `embedding_dim` | 벡터 차원 |
| `created_at` | 최초 생성 시각 |
| `updated_at` | 마지막 갱신 시각 |

삭제/수정 동기화를 쉽게 하려면 `wiki_path`에 index를 두고, 문서 재색인 시 해당 `wiki_path`의 기존 chunk를 삭제한 뒤 새 chunk를 삽입한다.

## 5. 청킹 전략

현재 설정에는 이미 다음 값이 있다.

- `WIKI_CHUNK_STRATEGY`
- `WIKI_CHUNK_SIZE`
- `WIKI_CHUNK_OVERLAP`

벡터 인덱싱에서도 이 설정을 재사용한다. 단, ingest용 LLM 추출 청킹과 검색용 markdown 청킹은 목적이 다르므로 함수는 분리한다.

권장 함수:

```text
wiki_cli/vector_index.py
  chunk_markdown_for_search(text, strategy, chunk_size, chunk_overlap) -> list[Chunk]
```

권장 동작:

- `section`: heading 경계를 우선 보존하고 너무 긴 section만 추가 분할
- `fixed`: 글자 수 기준 분할, overlap 적용
- `none`: 짧은 문서용. 너무 길면 앞부분만 쓰지 말고 경고 또는 fixed fallback

기존 구현처럼 파일 앞 2,000자만 대표로 쓰는 방식은 새 벡터 DB 경로에서는 사용하지 않는다.

## 6. 구현 단계

### Phase 1: 벡터 인덱스 모듈 추가

새 파일을 추가한다.

```text
wiki_cli/vector_index.py
```

담당 기능:

- DB 초기화
- markdown chunking
- embedding model lazy load
- page 단위 delete/upsert
- query vector 검색
- index health check

초기 공개 함수:

```python
def refresh_page(wiki_dir: Path, page_path: Path) -> VectorIndexStats: ...
def refresh_all(wiki_dir: Path) -> VectorIndexStats: ...
def search_chunks(query: str, wiki_dir: Path, top_k: int) -> list[VectorChunkResult]: ...
def delete_page(wiki_dir: Path, page_path: Path) -> None: ...
```

### Phase 2: ingest 후 upsert 연결

`wiki_cli/ops/ingest.py`에서 markdown page 생성 또는 갱신이 끝난 뒤 `vector_index.refresh_page()`를 호출한다.

주의점:

- 벡터 인덱싱 실패가 ingest 전체 실패로 이어지지 않게 한다.
- 실패 시 warning log를 남기고 기존 검색 fallback을 유지한다.
- LLM 추출 결과가 fallback page로 저장된 경우에도 동일하게 인덱싱한다.

### Phase 3: search tier 통합

`wiki_cli/search.py`에 새 검색 티어를 추가한다.

권장 이름:

```text
WIKI_SEARCH=vector
```

처음에는 기존 `embedding` tier를 바로 대체하지 않는다. 둘을 분리하면 회귀 비교가 쉽다.

검색 반환은 기존 `SearchResult`를 유지하되, chunk 기반 snippet을 넣는다.

```python
SearchResult(
    path=wiki_dir / result.wiki_path,
    score=result.score,
    snippet=result.chunk_text[:240],
)
```

### Phase 4: context builder 개선

현재 `_build_context()`는 검색 결과의 page를 다시 찾아 context를 구성한다. 벡터 검색에서는 이미 관련 chunk가 있으므로 page 전체를 다시 펼치기보다 chunk text를 직접 전달하는 경로가 필요하다.

선택지:

- `SearchResult`에 optional metadata를 추가한다.
- 또는 `VectorSearchResult(SearchResult)` 같은 별도 타입을 만들지 말고, `snippet`을 더 풍부하게 사용한다.

권장안은 `SearchResult`에 `metadata: dict | None = None`을 추가하는 것이다.

예시 metadata:

```python
{
    "kind": "vector_chunk",
    "heading": "...",
    "chunk_text": "...",
    "chunk_id": "...",
}
```

그 다음 `_build_context()`가 `metadata.kind == "vector_chunk"`이면 `chunk_text`를 우선 사용한다.

### Phase 5: Web 설정 노출

`wiki_web/config.py`의 `SEARCH_TIERS`에 vector를 추가한다.

```python
("vector", "Vector DB / 청크 의미 검색")
```

설정 저장 방식은 기존 `search_tier`와 `WIKI_SEARCH` 반영 구조를 그대로 사용한다.

## 7. 동기화 규칙

문서 변경 시 다음 규칙을 지킨다.

- page 생성/수정: 해당 `wiki_path` 기존 chunk 삭제 후 새 chunk 삽입
- page 삭제: 해당 `wiki_path` chunk 삭제
- 모델 변경: `model_name`이 다르면 별도 namespace로 저장하거나 전체 rebuild 요구
- chunk 설정 변경: 전체 rebuild 필요

1차 구현에서는 설정/모델 변경 감지 시 명시적으로 `refresh_all()`을 실행하는 관리 명령을 제공하는 편이 단순하다.

권장 CLI:

```text
wiki vector rebuild
wiki vector stats
wiki vector clear
```

단, 첫 단계에서는 내부 함수와 테스트를 먼저 만들고 CLI는 후속 작업으로 둬도 된다.

## 8. 테스트 계획

필수 테스트:

- markdown heading 기준 chunk 생성
- fixed chunk overlap 적용
- 같은 page 재색인 시 chunk 중복이 생기지 않음
- page 내용 변경 시 이전 chunk가 제거되고 새 chunk만 남음
- query가 관련 chunk를 top result로 반환
- 벡터 모듈 ImportError 또는 DB 오류 시 검색 fallback 동작
- 기존 `grep`, `bm25`, `embedding` 검색 티어 회귀 없음

권장 테스트 파일:

```text
tests/test_vector_index.py
tests/test_search.py
```

기본 검증 명령:

```bash
.venv/bin/python -m pytest tests
```

## 9. 마이그레이션 전략

처음 배포 시 자동 전체 인덱싱을 강제하지 않는다.

권장 순서:

1. `WIKI_SEARCH=vector`가 선택되면 DB가 비어 있을 때 warning 후 grep fallback
2. ingest된 신규/수정 문서부터 vector index에 들어감
3. 관리 명령 또는 Web Admin 버튼으로 전체 rebuild 제공
4. 충분히 안정화되면 `embedding` tier를 vector 기반으로 통합 검토

## 10. 주의할 점

- pickle 기반 `.embeddings` 캐시와 새 `.vectors` DB를 혼동하지 않는다.
- OpenAI API key는 LLM 답변 생성용이지 현재 임베딩용이 아니다.
- chunk text 전체를 DB에 저장하면 검색 context 구성은 쉬워지지만 DB 크기가 증가한다. 개인 위키 규모에서는 우선 저장하는 편이 낫다.
- vector score만 믿지 말고 `top_k`와 threshold를 설정 가능하게 열어둔다.
- 긴 문서의 앞부분만 임베딩하는 기존 한계를 반복하지 않는다.
- 벡터 인덱스 오류는 ingest/query의 주 기능을 깨뜨리지 않도록 fallback을 둔다.

## 11. 완료 기준

- `WIKI_SEARCH=vector`에서 chunk 단위 의미 검색이 동작한다.
- ingest 후 새/수정 page가 자동으로 vector index에 반영된다.
- 같은 문서를 여러 번 ingest 또는 refresh해도 chunk 중복이 없다.
- 관련 chunk text가 LLM context에 직접 들어간다.
- `.venv/bin/python -m pytest tests`가 통과한다.
- 문서에 vector rebuild/clear 방법과 fallback 정책이 기록되어 있다.
