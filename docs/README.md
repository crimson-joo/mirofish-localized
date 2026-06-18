# MiroFish-localized 문서 허브

## 목적

이 디렉터리는 MiroFish-localized의 **현재 제품/아키텍처/QA/릴리즈 기준**을 한국어로 유지하는 canonical documentation입니다.

원칙:

```text
원본 README/스크린샷 보존 ≠ 현재 localized 상태 문서화
```

현재 사용자가 읽는 기본 문서는 원본 MiroFish 설명이 아니라, 이 fork에서 실제로 구현·검증된 상태를 설명해야 합니다.

## 문서 구조

| 문서 | 역할 |
|---|---|
| `../README.md` | 사용자-facing 한국어 진입점, 현재 화면/사용법/상태 |
| `local-quickstart-ko.md` | 로컬 Compose 실행과 smoke 검증 |
| `current/product.md` | 현재 제품 범위와 사용자 가치 |
| `current/design.md` | UX/한국어/스크린샷/시각 증거 기준 |
| `current/architecture.md` | Graphiti/Neo4j, Multiverse, runner 아키텍처 |
| `current/qa.md` | QA/Canary 에이전트가 확인해야 할 기준 |
| `current/release.md` | 릴리즈/배포/rollback 기준 |
| `current/branch-flow.md` | branch/PR/CI 운영 기준 |
| `changelog.md` | 날짜별 사용자-visible 변경 요약 |

## 에이전트별 문서 책임

| 역할 | 문서 책임 |
|---|---|
| Builder | 기능 변경과 함께 README/quickstart/API 사용법 갱신 후보를 남김 |
| Reviewer | 문서가 코드와 어긋나는지, 과장/누락/오래된 원본 문구가 있는지 확인 |
| QA Lead | 실제 화면/스모크/브라우저 증거와 문서의 주장 일치 여부 확인 |
| Release Manager | develop→main PR 전 canonical docs와 changelog가 현재 release 범위를 반영하는지 확인 |
| Librarian/Docs Agent | `.hermes/runs/*` 실행 증거를 읽고 canonical docs에는 결론/상태/사용법만 정리 |

## 문서 업데이트 체크리스트

기능·UI·운영 흐름을 바꾸는 PR/merge 전 다음을 확인합니다.

- [ ] README가 현재 fork 상태를 한국어로 설명하는가?
- [ ] 원본 중국어/영어 마케팅 문구가 현재 상태처럼 남아 있지 않은가?
- [ ] 스크린샷이 원본 이미지가 아니라 현재 localized UI/canary artifact인가?
- [ ] 로컬 runtime 경로가 `/Volumes/ExternalSSD/Workspace/Projects/mirofish-localized` 기준인가?
- [ ] Graphiti/Neo4j, fail-closed, Graph memory ON, Persona Core-vs-All, Multiverse 상태가 최신인가?
- [ ] BettaFish→MiroFish runner처럼 새 운영 도구의 사용법/한계가 적혀 있는가?
- [ ] 실패한 시도와 최종 성공 resume이 혼동되지 않게 표현되어 있는가?
- [ ] Pages가 전체 앱 runtime이 아니라 static checkpoint임을 명확히 했는가?
- [ ] `.hermes/runs/*`의 raw evidence를 문서에 그대로 붙이지 않고, 필요한 요약/경로만 남겼는가?

## 스크린샷 정책

- 현재 README의 대표 스크린샷은 `static/image/Screenshot/localized-home-ko.png`입니다.
- UI 변경이 있으면 실제 로컬 또는 Pages 화면을 캡처해 새 artifact를 남깁니다.
- 원본 `运行截图*.png`는 보존할 수 있지만, localized fork의 current evidence로 사용하지 않습니다.
- 스크린샷에는 한국어 UI, 현재 workflow, 현재 상태 badge/문구가 드러나야 합니다.

## 문서와 run artifact 구분

```text
canonical docs:
  README.md
  docs/README.md
  docs/current/*.md
  docs/changelog.md

local run artifacts:
  .hermes/runs/<run-id>/*
  canary-artifacts/*
  backend/uploads/*
```

canonical docs에는 사용자가 결정/운영에 필요한 현재 상태를 남기고, 실행 로그·원본 JSON·중간 산출물은 로컬 artifact에 둡니다.
