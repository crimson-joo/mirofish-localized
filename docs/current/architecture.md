# Architecture — MiroFish-localized

## 현재 기준 경로

MiroFish-localized의 그래프 메모리 기준 경로는 `GRAPH_PROVIDER=graphiti`입니다.

```text
Backend API
→ Graphiti provider
→ Graphiti service
→ Neo4j
```

## Provider 정책

- `graphiti`: 기본값. Graphiti/Neo4j ingest/search를 기준으로 사용합니다.
- `zep`: 원본 Zep Cloud 경로이며 `ZEP_API_KEY`가 필요합니다.
- `local_simple`: 제품 런타임 provider에서 제거되었습니다.

## Fail-closed 정책

Graphiti ingest/search 실패는 로컬 fallback으로 조용히 성공 처리하지 않습니다.

- ingest 실패: `pass` / `repaired` / `failed`로 구분합니다.
- search 실패: projection cache로 fallback하지 않고 실패로 드러냅니다.
- search 결과가 비어있는 경우: 빈 native 결과로 처리하며 projection cache 결과를 섞지 않습니다.

## Projection cache

기존 MiroFish UI가 node/edge 목록을 기대하기 때문에 내부 read-model인 Graphiti projection cache는 남아 있습니다. 이는 UI 표시용 projection이며 Graphiti 실패를 PASS로 바꾸는 fallback provider가 아닙니다.

## Group cleanup

그래프 삭제 시 Graphiti group 삭제 API를 호출한 뒤 projection cache를 삭제합니다. 세션/그래프 단위 group_id는 graph_id를 기준으로 분리합니다.

## Multiverse Simulation MVP

단일 simulation을 보존하면서 상위 ensemble 계층을 추가합니다.

```text
MultiverseManager
→ MultiverseExperiment (mv_*)
→ UniverseChild[] (u1..uN)
→ 기존 SimulationManager child simulation (sim_*)
→ aggregate_experiment() ensemble_frequency 요약
```

- 저장 위치: `uploads/multiverses/<mv_id>/experiment.json`
- 각 child simulation에는 `uploads/simulations/<sim_id>/multiverse_context.json`을 저장합니다.
- 기본값: `universe_count=5`, `max_parallel=2`, `rounds=24`, `variation_mode=realistic`, `persona_selection_mode=core`, `graph_memory_enabled=true`.
- `probability_note`는 결과를 실제 확률이 아니라 `ensemble_frequency`로 명시합니다.
- `prepare_experiment()`는 각 child simulation에 scenario/persona overlay를 주입해 준비합니다.
- `start_experiment()`는 `max_parallel` 슬롯만 실행하고 나머지 child를 `queued` 상태로 남깁니다.
- `aggregate_experiment()`는 status frequency, sensitivity axes, outcome clusters, ensemble report markdown을 생성합니다.
- API 확장: `/multiverse/<mv_id>/prepare`, `/prepare/status`, `/start`, `/advance`, `/status`, `/report`, `/report-agent-context`.
- UI 확장: `/multiverse/:multiverseId` dashboard에서 universe list/status/progress/aggregate/report를 표시합니다.
- 고도화 계층: `prepare_experiment_async()`는 TaskManager 기반 prepare 진행률을 제공하고, 같은 `multiverse_id`의 active prepare task는 중복 생성하지 않고 재사용합니다. `auto_advance_queue()`는 열린 run slot에 queued/ready child를 자동 투입합니다.
- `aggregate_experiment(clustering_strategy="semantic")`는 deterministic token-similarity 기반 semantic cluster MVP와 evidence snippet을 반환합니다. API shape는 향후 embedding/LLM clustering으로 교체 가능하게 유지합니다.
- `report_agent_context`는 child simulation 요약, outcome clusters, sensitivity axes, probability caveat, suggested questions를 Report Agent Q&A가 읽을 수 있는 형태로 묶습니다.
- 기존 prepare/start/report 경로는 child `simulation_id` 단위로 그대로 재사용하고, 상위 aggregate/report 확장은 `mv_*` 단위에서 수행합니다.

## Live local-runtime canary / RWA evaluation

`./scripts/multiverse-long-run-eval.py`는 bounded-real backend 평가와 live-local-runtime canary를 분리합니다.

```bash
python scripts/multiverse-long-run-eval.py --mode bounded --topic "RWA 실물자산 토큰화 시장 반응"
python scripts/multiverse-long-run-eval.py --mode live --topic "RWA 실물자산 토큰화 시장 반응"
```

- `bounded`: 실제 backend manager/API path를 사용하되 deterministic completed child state로 빠르게 비교합니다.
- `live`: 로컬 LLM/embedding/Graphiti endpoint preflight를 먼저 수행하고, 실패하면 fallback으로 숨기지 않고 `BLOCKED`로 종료합니다.
- RWA/실물자산/토큰화 topic은 시장형 universe summaries와 human-readable cluster label을 사용합니다.
- cluster label은 `Semantic outcome cluster` 같은 내부 개발자 문구가 아니라 `규제 명확성 확산형`, `DeFi 담보 확산형`, `규제 제한 지연형`처럼 사용자-facing label을 우선합니다.

## Runtime cycle hardening

반복 canary/OASIS/report 사이클은 process 상태보다 durable artifact를 우선해 판정합니다.

```text
Graphiti /messages accepted + duplicate edge warning
→ native_ingest_state=pass 또는 repaired 유지
→ native_warning_state=warning 및 warnings[]에 duplicate_edge 기록
→ 동일 warning은 batch/status 단위에서 중복 누적하지 않음
```

```text
Simulation action memory
→ actions.jsonl의 agent action을 Graphiti /messages로 먼저 native ingest
→ 성공한 action만 projection cache/actions.jsonl read-model에 기록
→ native action ingest 실패는 run failure로 드러내고 리포트 evidence로 쓰지 않음
→ native_action_ingest_state=pass/repaired/failed 로 별도 기록
```

```text
Report Agent evidence protocol
→ tool call 단계와 Final Answer 단계는 한 응답에서 섞을 수 없음
→ tool_call + Final Answer 충돌 응답은 폐기/재시도 후 fail-closed
→ Graphiti search tool 실패는 문자열 evidence로 삼키지 않고 실패로 전파
```

```text
OASIS bounded loop 완료
→ twitter/actions.jsonl + reddit/actions.jsonl 의 simulation_end 확인
→ command-wait 상태에서 stop되어도 semantic completion은 completed로 승격
→ unknown/orphan persisted running 상태는 live process가 없으면 failed로 정규화해 queue slot을 영구 점유하지 않음
```

```text
Report generation watcher timeout
→ 같은 report_id의 full_report.md가 존재하고 non-empty이면
→ ReportManager.reconcile_report_completion()이 completed 상태로 복구
```

## BettaFish bridge runner

`./scripts/bettafish-single-e2e-runner.py`는 BettaFish 최종 Markdown 보고서를 MiroFish seed로 투입하는 resume-safe runner입니다.

```text
BettaFish final_report.md
→ MiroFish project/upload
→ graph build
→ simulation prepare/start
→ action 확인
→ report generate
→ Report Agent QA
```

저장 state:

```text
project_id, graph_task_id, graph_id, simulation_id,
prepare_task_id, report_task_id, report_id,
attempts, stage, final_summary
```

긴 E2E가 SIGTERM/timeout으로 끊겨도 다음 실행에서 state를 읽고 이어가며, 실패 attempt와 성공 resume을 하나의 summary로 구분합니다.
