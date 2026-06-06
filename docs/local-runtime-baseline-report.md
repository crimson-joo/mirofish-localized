# MiroFish-localized local runtime baseline report

Date: 2026-06-06 KST
Branch: `feat/zep-free-compose-local`
HEAD observed: `9840e10`

## Conclusion

Minimum stable local runtime scope is usable as a ZEP-free, Docker Compose-first baseline:

- Frontend renders at `http://127.0.0.1:3000/`.
- Backend health passes at `http://127.0.0.1:5001/health`.
- Graphiti service health passes at `http://127.0.0.1:8000/healthcheck`.
- Neo4j runs under the `graphiti` compose profile.
- `GRAPH_PROVIDER=graphiti` can build graphs, create/prepare/start simulations, produce actions, generate reports, and answer report chat through the MiroFish product flow.

Important limitation: Graphiti native `/messages` episode extraction is not fully stable with the current local GPT auth endpoint because Graphiti expects strict structured-output/Pydantic schemas. The provider therefore records Graphiti mirror errors and continues through a local compatibility cache. Report this as:

```text
Local runtime baseline: PASS
Graph service infrastructure: PASS
Provider fallback/product flow: PASS
Native Graphiti episode extraction: BLOCKED/PARTIAL
```

## Original MiroFish vs localized baseline

### Original shape

Original MiroFish primarily assumes cloud-style graph memory integration around Zep/Zep Cloud-compatible tooling and its own frontend/backend flow.

### Localized baseline shape

This branch changes the runtime direction to local-first:

1. Docker Compose is the primary launcher.
2. Zep Cloud is no longer required for the minimum flow.
3. Graph memory is behind a provider interface.
4. `local_simple` remains as scaffold/fallback.
5. `graphiti` profile adds local Graphiti + Neo4j.
6. Local OpenAI-compatible LLM/embedding endpoints are configurable through environment variables.

## Code changes observed

Changed/untracked files:

```text
.env.example
backend/app/services/graphiti_provider.py
docker-compose.yml
services/graphiti-patched/Dockerfile
services/graphiti-patched/ingest.py
```

### `.env.example` and `docker-compose.yml`

- Default app LLM endpoint changed from `host.docker.internal:11434/v1` / `gpt-4o-mini` to this machine's local GPT auth endpoint defaults: `host.docker.internal:10531/v1` / `gpt-5.5`.
- Graphiti profile defaults aligned to the same OpenAI-compatible local endpoint.
- Graphiti embedding endpoint remains separately configurable.

### `backend/app/services/graphiti_provider.py`

- Graphiti `/messages` mirroring now uses a longer timeout.
- If `/messages` fails, the provider records `graphiti_errors` in the compatibility graph cache and continues instead of crashing the whole product flow.
- This keeps Step1-Step5 usable while native Graphiti extraction is tuned.

### `services/graphiti-patched/Dockerfile`

- Copies patched `ingest.py` router into the Graphiti image.
- Applies file permissions so the container can read patched files.

### `services/graphiti-patched/ingest.py`

- Adds synchronous `/messages` handling for deterministic local smoke tests.
- Passes `uuid=None` to `graphiti.add_episode(...)` for new episodes, avoiding current Graphiti `NodeNotFoundError` behavior when client-generated UUIDs are treated like update lookups.
- Re-exposes basic entity/group/delete/clear routes needed by the local graph-memory smoke path.

## Verification evidence

### Unit tests

Provider tests passed previously:

```text
Ran 3 tests in 0.867s
OK
```

### Compose/services

Observed running containers:

```text
mirofish-localized                    running, ports 3000/5001
mirofish-localized-graph-memory-1     running, port 8000
mirofish-localized-neo4j-1            running, ports 7474/7687
```

Health checks observed:

```text
http://127.0.0.1:5001/health       200 { "service": "MiroFish Backend", "status": "ok" }
http://127.0.0.1:8000/healthcheck  200 { "status": "healthy" }
http://127.0.0.1:3000/             200 MiroFish frontend HTML
```

### Product-flow evidence

Previously completed API flow:

```text
ontology generation: success, 10 entities / 8 edge types
graph build: completed, graph local_mirofish_f476606378714a58, 10 nodes / 33 edges / 2 chunks
search: success, 5 results
simulation create: success, sim_cc63a20997e4
simulation prepare: ready, 100%, 10 entities / 10 profiles
simulation start: produced 15 actions
simulation stop: stopped at 100%
report generate: completed, report_277bd572b796
report chat: success
```

Current persisted UI/API history shows completed/recent records, including:

```text
/api/simulation/history: 200, count 3
/api/report/list: 200, count 2
```

Frontend text shows workflow steps:

```text
01 图谱构建
02 环境搭建
03 开始模拟
04 报告生成
05 深度互动
```

## Stability assessment

### Stable enough for baseline demo

- Local stack boots with Docker Compose.
- The frontend shows system ready state and previous inference records.
- Backend APIs for history/report list respond.
- Graphiti/Neo4j infrastructure runs locally.
- MiroFish product flow can complete without Zep Cloud.

### Not yet stable enough to call final Graphiti replacement

- Native Graphiti episode extraction is blocked/partial due to strict structured-output failures from the current local GPT auth endpoint.
- `/api/graph/tasks` returned HTTP 500 during one check and needs route-level hardening or cleanup.
- Recent-history card click in the browser did not visibly navigate during the latest browser check, although the record list renders and the API history is present.
- Simulation runner state can show `running` even after actions are generated; manual stop succeeded in prior verification.

## Minimum stable running scope

Recommended baseline to freeze now:

```text
Scope name: local-runtime-baseline-v0
Launcher: docker compose --profile graphiti up -d --build
Provider: GRAPH_PROVIDER=graphiti
Required local services:
  - app container: frontend + Flask backend
  - graph-memory: patched Graphiti FastAPI
  - neo4j
  - local OpenAI-compatible LLM endpoint
  - local embedding endpoint
Guaranteed flow:
  - frontend render
  - backend health
  - graph service health
  - ontology generation
  - graph build using compatibility cache + Graphiti mirror attempt
  - graph data/search
  - simulation create/prepare/start
  - report generate
  - report chat
Not guaranteed yet:
  - Graphiti native episode extraction quality
  - Graphiti-only facts without compatibility cache
  - public tunnel/cloud demo
  - production multi-user persistence/security
```

## Recommended roadmap

### Phase 0 — Freeze baseline

- Keep current branch as the minimum working baseline.
- Commit the implementation and this report after final review.
- Label acceptance honestly: product flow passes; native Graphiti extraction remains blocked/partial.

### Phase 1 — Native Graphiti extraction hardening

Recommended first follow-up:

1. Add a Graphiti-specific model/env preset that supports strict structured outputs.
2. Add a small smoke test that calls `/messages` and verifies actual Graphiti-native search/facts, not only compatibility-cache search.
3. Keep compatibility cache as fallback but make native-vs-fallback evidence explicit in API responses/logs.

### Phase 2 — UI run-detail hardening

1. Fix or clarify recent-history card navigation.
2. Add a visible run-detail page/state for graph/simulation/report IDs.
3. Surface PASS/PARTIAL/BLOCKED runtime status in UI for graph-memory mode.

### Phase 3 — API stability cleanup

1. Fix `/api/graph/tasks` 500.
2. Ensure simulation runner status reaches `completed` deterministically after bounded runs.
3. Add route-level smoke tests for graph/project/list, simulation/history, report/list, graph/tasks.

### Phase 4 — Demo packaging

1. Add a one-command bootstrap script.
2. Add Korean quickstart docs.
3. Optionally expose through cloudflared/ngrok only after local stability gates pass.

## Recommended next action

Proceed with Phase 0 freeze, then immediately create a separate Phase 1 branch/task for native Graphiti extraction. Do not expand to public tunnel or production deployment until Phase 1 and Phase 2 pass.

## Phase 1 progress: native/fallback evidence hardening

Implemented after the baseline freeze:

- `GraphitiGraphBuilder.add_text_batches()` records a `graphiti_events` entry for `/messages` native ingest success or fallback failure.
- Graph data now exposes `graphiti_status` and `native_graph_memory_state` so API/UI/reporting can distinguish native Graphiti success from compatibility-cache product-flow success.
- `GraphitiToolsService.search_graph()` records native search pass, empty-native fallback, or failed-native fallback.
- Provider tests now cover both paths:
  - native `/messages` + `/search` pass
  - native `/messages` failure + empty native search with local compatibility fallback

Current acceptance language after this phase:

```text
Graphiti evidence observability: PASS
Fallback behavior regression test: PASS
Native extraction repair: still next milestone
```

This phase does not claim to solve Graphiti's strict structured-output failures. It makes those failures visible and test-covered so the next repair/model-endpoint work can be validated without confusing product-flow fallback with true native Graphiti success.
