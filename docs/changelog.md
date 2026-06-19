# Changelog — MiroFish-localized

## 2026-06-19

- 반복 실행 안정화를 위해 Graphiti duplicate edge warning을 native ingest 실패와 분리해 `native_warning_state=warning` 및 `warnings[]`로 기록하도록 했습니다.
- OASIS bounded loop가 완료된 뒤 command-wait 상태에서 stop되어도 durable `actions.jsonl`의 `simulation_end` 근거로 child/multiverse 상태를 `completed`로 승격하도록 했습니다.
- 리포트 생성 watcher/세션이 끊긴 경우에도 같은 `report_id`의 non-empty `full_report.md`를 기준으로 completed 상태를 복구하는 `ReportManager.reconcile_report_completion()`을 추가했습니다.
- 위 세 가지 반복 사이클 hardening에 대한 regression test를 `backend/tests/test_runtime_cycle_hardening.py`에 추가했습니다.
- Simulation action memory를 Graphiti native ingest/search/Report Agent quick_search evidence까지 검증하는 canary를 추가하고, native action ingest 실패 시 projection evidence로 기록하지 않도록 fail-closed 처리했습니다.
- Report Agent의 `tool_call + Final Answer` protocol conflict를 도구 실행 없는 재시도 후 fail-closed로 바꾸고, search tool 실패를 문자열 evidence로 삼키지 않도록 했습니다.
- Graphiti structured edge/node-resolution 정규화에서 payload-local duplicate edge와 self/invalid duplicate resolution을 줄였습니다.
- Multiverse prepare task 중복 등록 방지, start 실패 child의 failed 고정, orphan/invalid persisted runner state 정규화로 long-run queue 안정성을 보강했습니다.

## 2026-06-18

- README를 원본 MiroFish 소개문 중심에서 MiroFish-localized의 현재 상태를 설명하는 한국어 진입 문서로 교체했습니다.
- 현재 한국어 홈/업로드 화면을 직접 캡처한 `static/image/Screenshot/localized-home-ko.png`를 README 대표 screenshot으로 추가했습니다.
- `docs/README.md`, `docs/current/product.md`, `docs/current/design.md`를 추가해 문서 에이전트/QA/Release가 따라야 할 canonical docs 기준을 명시했습니다.
- Multiverse live-local-runtime canary와 RWA topic evaluation, human-readable outcome cluster label 기준을 architecture/QA 문서에 반영했습니다.
- BettaFish→MiroFish resume-safe bridge runner 사용법과 SIGTERM/timeout resume 표현 기준을 README/architecture 문서에 반영했습니다.
- 로컬 quickstart 경로를 외장 SSD 기준 `/Volumes/ExternalSSD/Workspace/Projects/mirofish-localized`로 정정했습니다.

## 2026-06-09

- Graphiti/Neo4j를 기본 그래프 메모리 provider로 승격했습니다.
- Docker Compose 앱 기본값도 `GRAPH_PROVIDER=graphiti`로 맞췄습니다.
- `local_simple` 제품 런타임 provider를 제거하고 Graphiti projection cache를 UI read-model로 분리했습니다.
- Graphiti OpenAI-compatible structured-output 응답을 Graphiti Pydantic schema로 정규화해 native extraction `pass` 경로를 안정화했습니다.
- Graphiti ingest/search 실패는 projection cache로 조용히 성공 처리하지 않습니다.
- Graphiti group 삭제와 projection cache 삭제를 함께 검증하는 테스트를 추가했습니다.
- Kanban 멀티에이전트 운영 기준에 Shared Task Contract와 역할별 의존성 순서를 반영했습니다.
- 한국어/영어/중국어 실제 사용자 관점의 홈·보고서·심화 인터랙션·Report Agent Q&A 제품 QA 기준선을 문서화했습니다.
