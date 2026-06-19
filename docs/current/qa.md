# QA 기준 — MiroFish-localized

## 목적

이 문서는 QA/Canary 에이전트가 단순 HTTP 200이 아니라, 이번 프로젝트의 의도에 맞게 무엇을 확인해야 하는지 정의합니다.

## 현재 릴리즈에서 검증할 사용자 가치

1. ZEP Cloud 없이 로컬 Docker Compose 기반으로 MiroFish 기본 흐름을 실행할 수 있다.
2. Graphiti/Neo4j 로컬 그래프 메모리 경로가 기본 provider로 연결되어 있다.
3. Graphiti ingest/search 실패가 fallback provider로 가려지지 않고 `pass/repaired/failed`로 드러난다.
4. 세션/그래프별 group_id 삭제 시 Graphiti group cleanup과 projection cache cleanup이 함께 수행된다.
5. GitHub Pages는 전체 앱 배포가 아니라 정적 체크포인트/문서 페이지임을 명확히 보여준다.
6. Multiverse Simulation MVP는 하나의 graph/topic에서 여러 universe child simulation을 만들고, status frequency를 실제 확률이 아닌 `ensemble_frequency`로 집계한다.
7. Multiverse outcome cluster label은 `Semantic outcome cluster` 같은 내부 문구가 아니라 사용자가 읽을 수 있는 한국어 label로 표시된다.
8. BettaFish→MiroFish bridge runner는 SIGTERM/timeout 이후 resume state로 이어서 실행 가능해야 한다.
9. README와 current docs는 현재 localized 상태, 한국어 화면, 실제 검증 범위를 반영해야 한다.
10. 반복 사이클 안정화 기준: Graphiti duplicate edge 경고는 실패와 분리되어 `native_warning_state=warning`으로 기록되어야 하며, OASIS command-wait 후 stop된 run도 durable `actions.jsonl`의 양 플랫폼 `simulation_end`가 있으면 completed로 승격되어야 한다.
11. 리포트 생성 watcher가 끊겨도 `full_report.md`가 완성되어 있으면 같은 `report_id`를 재실행/조회할 때 completed 상태로 복구되어야 한다.

## 로컬 QA 기준

- Frontend: `http://127.0.0.1:3000/` 렌더링
- Backend: `/health` 정상
- Graphiti: `/healthcheck` 정상
- UI: Step1~Step5 설명과 최근推演记录 카드 표시
- Console: blocker JS error 없음
- Smoke: `./scripts/local-smoke.sh` PASS
- Native extraction gate: `GRAPHITI_NATIVE_ONLY_SMOKE=1 ./scripts/graphiti-native-smoke.py` PASS 또는 명확한 BLOCKED 사유
- Multiverse focused tests: `cd backend && ./.venv/bin/python -m unittest tests.test_multiverse_manager tests.test_route_smoke tests.test_runtime_cycle_hardening -v` PASS
- Multiverse API smoke: `/api/simulation/multiverse/create`, `/api/simulation/multiverse/<mv_id>`, `/api/simulation/multiverse/list`, `/prepare`, `/prepare/status`, `/start`, `/advance`, `/status`, `/aggregate`, `/report`, `/report-agent-context`가 실험/child simulation/queue/aggregate/report-agent context shape을 반환해야 합니다.
- Multiverse UI smoke: Step1의 “멀티버스 시뮬레이션” 버튼이 `/multiverse/:multiverseId` dashboard로 이동하고, universe card/status/async prepare task/progress/semantic aggregate/report/disclaimer가 보여야 합니다.
- Multiverse label smoke: `cd backend && ./.venv/bin/python -m unittest tests.test_multiverse_manager.MultiverseManagerTest.test_semantic_clusters_use_human_readable_market_labels -v`에서 human-readable market label 테스트가 PASS해야 하며, 결과 label에 `Semantic outcome cluster`가 남아 있으면 실패입니다.
- Live local-runtime canary: `python scripts/multiverse-long-run-eval.py --mode live --topic "RWA 실물자산 토큰화 시장 반응"`은 LLM/embedding/Graphiti endpoint preflight를 통과하거나, 실패 시 `BLOCKED`로 fail-closed해야 합니다.
- Documentation QA: `README.md`, `docs/README.md`, `docs/current/product.md`, `docs/current/design.md`가 현재 localized 상태와 한국어 screenshot을 가리켜야 합니다.

## Pages Canary 기준

- Live URL: `https://crimson-joo.github.io/mirofish-localized/`
- Cache-busted URL도 200
- Playwright browser canary에서 live render/console/marker 확인
- 문서 페이지에 다음 의도 표시:
  - ZEP-free
  - Compose-first
  - Graphiti
  - Local quickstart
- Pages는 실제 MiroFish runtime이 아니라 정적 checkpoint임을 명시

## 다국어 제품 QA 기준

한국어/영어/중국어가 사용자 선택 언어로 지원되는 동안 QA는 단순 UI 라벨 확인이 아니라 실제 사용자 흐름 기준으로 수행합니다.

- 언어 전환: 브라우저의 실제 언어 스위처로 `ko`, `en`, `zh`를 선택하고 `html lang`, 로컬 저장값, 홈 화면 핵심 문구가 일치해야 합니다.
- 홈/입력 흐름: 각 언어에서 업로드 영역, 시뮬레이션 프롬프트, 시작 버튼 상태, 워크플로우, 시뮬레이션 기록이 의도한 언어로 보이는지 확인합니다.
- 기록/보고서 흐름: 완료된 시뮬레이션 또는 report route에 진입해 그래프, 보고서, 심화 인터랙션/Report Agent chrome이 선택 언어로 보이는지 확인합니다.
- Report Agent Q&A: 같은 시뮬레이션 질문을 `ko`, `en`, `zh` 사용자처럼 각각 묻고, 새로 생성된 답변이 선택 언어로 출력되는지 검증합니다.
- 언어 누수 판정: 현재 UI chrome과 새 Report Agent 답변의 wrong-language leakage는 실패로 봅니다. 단, 과거에 생성된 보고서 본문/시뮬레이션 제목/업로드 파일명은 원본 데이터 언어가 유지될 수 있으므로 별도 번역 요구가 없는 한 실패로 보지 않습니다.

## 2026-06-09 수동 제품 QA 기준선

- 범위: `ko`, `en`, `zh` 실제 사용자 관점의 홈 → 언어 전환 → 기록/보고서 → 심화 인터랙션 → Report Agent Q&A.
- 결과: PASS.
- 자동 canary: `scripts/local-runtime-canary-runner.py` 기준 `HEALTHY` — browser locale canary와 Report Agent locale E2E 모두 PASS.
- 수동 제품 QA: 각 언어별 홈 화면/심화 인터랙션 화면/Report Agent 새 답변 언어 검증 PASS.
- 증거: `canary-artifacts/manual-locale-product-qa/` 및 `canary-artifacts/local-runtime-locale-{ko,en,zh}.png`.
- 관찰: 기존 히스토리 카드 제목과 과거 보고서 본문은 생성 당시 원문 언어가 유지됩니다. 이는 현재 언어 선택 UI chrome 또는 새 답변 언어 누수와 구분해 판정합니다.

## 보고 기준

QA/Canary 보고는 다음을 분리합니다.

```text
로컬 앱 동작: PASS/PARTIAL/FAIL
GitHub Pages 정적 배포: PASS/PARTIAL/FAIL
Graphiti native extraction: PASS/PARTIAL/FAIL
자동화 파이프라인: PASS/PARTIAL/FAIL
Webhook/Hermes 후속 QA: PASS/SKIPPED/FAIL
```
