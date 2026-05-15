# 문서 인덱스

> 작성일: 2026-05-14  
> 범위: `docs/`, `report/`

## docs/

| 파일 | 설명 |
|---|---|
| [implementationPlan_01.md](./implementationPlan_01.md) | CLI 중심 프로젝트를 FastAPI/HTMX 로컬 웹앱으로 전환하기 위한 Phase 1~2 구현 계획. |
| [ideas.md](./ideas.md) | Obsidian Vault 연동, 원본 파일 접근 방식 등 향후 개선 아이디어 모음. |
| [karpathy_alignment_review.md](./karpathy_alignment_review.md) | Andrej Karpathy의 LLM Wiki 메모와 현재 구현을 대조한 기능/성능 개선 점검 문서. |
| [karpathy_improvement_implementation_plan.md](./karpathy_improvement_implementation_plan.md) | Karpathy alignment 개선을 phase별로 실행하기 위한 구현 계획과 측정 기준. |
| [karpathy_improvement_status_2026-05-14.md](./karpathy_improvement_status_2026-05-14.md) | Source registry, 추출 캐시, 구조화 ingest 등 2026-05-14 개선 작업의 진행 상황 요약. |
| [llm-wiki-guide.docx](./llm-wiki-guide.docx) | llm-wiki 사용/운영 가이드로 보이는 Word 문서. |

## docs/metrics/

| 파일 | 설명 |
|---|---|
| [metrics/karpathy_improvement_baseline.md](./metrics/karpathy_improvement_baseline.md) | Karpathy alignment 개선 전 기준 상태와 테스트/기능 baseline 기록. |
| [metrics/karpathy_improvement_after_phase1.md](./metrics/karpathy_improvement_after_phase1.md) | Phase 1 이후 pytest 수집 안정화와 source registry 도입 결과. |
| [metrics/karpathy_improvement_after_extraction_cache.md](./metrics/karpathy_improvement_after_extraction_cache.md) | 추출 텍스트 캐시와 `call_with_file()` 결과 캐시 도입 결과. |
| [metrics/karpathy_improvement_after_structured_ingest.md](./metrics/karpathy_improvement_after_structured_ingest.md) | 구조화 ingest 도입과 entity/concept planning LLM 호출 생략 결과. |
| [metrics/karpathy_improvement_after_remaining_phases.md](./metrics/karpathy_improvement_after_remaining_phases.md) | 남은 Karpathy alignment phase 구현 결과와 테스트/한계 기록. |

## docs/fix/

| 파일 | 설명 |
|---|---|
| [fix/2026-04-16.md](./fix/2026-04-16.md) | 2026-04-16 기준 수정/개선 작업 기록. |
| [fix/2026-04-20.md](./fix/2026-04-20.md) | 2026-04-20 기준 수정/개선 작업 기록. |
| [fix/2026-05-14.md](./fix/2026-05-14.md) | 2026-05-14 기준 Karpathy alignment 점검, source registry, 추출 캐시, 구조화 ingest 개선 기록. |
| [fix/2026-05-15.md](./fix/2026-05-15.md) | 2026-05-15 기준 서비스 흐름 리뷰 갱신과 문서 인덱스 생성 기록. |
| [fix/2026-05-15-remaining-phases.md](./fix/2026-05-15-remaining-phases.md) | Karpathy alignment 계획서의 남은 phase 구현 기록. |

## docs/v0.1/

| 파일 | 설명 |
|---|---|
| [v0.1/ARCHITECTURE.md](./v0.1/ARCHITECTURE.md) | v0.1 웹앱/CLI/파일시스템 구조와 SSE, 멀티 도메인 라우팅 설명. |
| [v0.1/RELEASE_NOTES.md](./v0.1/RELEASE_NOTES.md) | v0.1 릴리스 변경 사항과 배포 메모. |
| [v0.1/design_ingest.md](./v0.1/design_ingest.md) | ingest 파이프라인 설계 문서. |
| [v0.1/ingest_improvement.md](./v0.1/ingest_improvement.md) | ingest 속도 개선을 위한 구조화 결과, evidence map, 병렬화 제안. |
| [v0.1/instruction.md](./v0.1/instruction.md) | v0.1 구현/검증 지시사항과 체크리스트 성격의 문서. |
| [v0.1/interim_report.md](./v0.1/interim_report.md) | v0.1 중간 점검 보고서. |
| [v0.1/project_improvement_report.md](./v0.1/project_improvement_report.md) | 설정 반영, 업로드 안전성, 테스트 도입 등 프로젝트 개선 보고서. |
| [v0.1/resolve_interim_report.md](./v0.1/resolve_interim_report.md) | 중간 보고서에서 나온 이슈에 대한 해결/반영 기록. |
| [v0.1/resolve_project_improvement_report.md](./v0.1/resolve_project_improvement_report.md) | 프로젝트 개선 보고서 이슈의 해결/반영 기록. |

## docs/v0.1/fix/

| 파일 | 설명 |
|---|---|
| [v0.1/fix/2026-04-20.md](./v0.1/fix/2026-04-20.md) | v0.1 기준 2026-04-20 수정 기록. |
| [v0.1/fix/2026-04-21.md](./v0.1/fix/2026-04-21.md) | v0.1 기준 2026-04-21 수정 기록. |
| [v0.1/fix/ingest_improvement2.md](./v0.1/fix/ingest_improvement2.md) | ingest 개선 2차 작업 또는 후속 수정 기록. |

## report/

| 파일 | 설명 |
|---|---|
| [../report/service_flow_review.md](../report/service_flow_review.md) | 서비스 흐름을 검토한 보고서. 사용자 흐름, 기능 연결, 개선 지점 점검용 문서. |
