# MiroFish-localized Local Demo MVP 빠른 시작

## 목표

이 문서는 1차 완성본(Local Demo MVP)을 로컬에서 재현하는 절차입니다.

1차 완성본의 기준은 **Graphiti native extraction 100%**가 아니라 다음입니다.

```text
Zep Cloud 없이 Docker Compose 로컬 스택으로 MiroFish Step1~Step5 제품 흐름을 실행하고,
Graphiti native/fallback 상태를 API/UI/문서에서 투명하게 확인한다.
```

## 구성

```text
frontend + Flask backend: mirofish container
Graph memory service: patched Graphiti FastAPI
Graph database: Neo4j
LLM: OpenAI-compatible local endpoint
Embedding: OpenAI-compatible local embedding endpoint
```

## 실행

```bash
cd /Users/crimson/Projects/mirofish-localized
cp .env.example .env
# 필요 시 .env에서 LLM/embedding endpoint 조정
GRAPH_PROVIDER=graphiti docker compose --profile graphiti up -d --build
```

기본 URL:

```text
Frontend: http://127.0.0.1:3000/
Backend:  http://127.0.0.1:5001/health
Graphiti: http://127.0.0.1:8000/healthcheck
Neo4j:    http://127.0.0.1:7474/
```

## Smoke 검증

```bash
./scripts/local-smoke.sh
```

기대 출력 예:

```text
PASS backend_health 200
PASS graphiti_health 200
PASS frontend 200
PASS graph_tasks 200
PASS graph_project_list 200
PASS simulation_history 200
PASS report_list 200
PASS graph_data_status ...
```

선택적으로 mini graph build smoke를 붙일 수 있지만, LLM token/시간을 쓰므로 기본값은 skip입니다.

```bash
RUN_MINI_BUILD=1 ./scripts/local-smoke.sh
```

## 브라우저 확인

1. `http://127.0.0.1:3000/` 접속
2. 하단 `推演记录` 최근 기록 클릭
3. 상세 modal에서 다음 확인
   - `graph_id`
   - `simulation_id`
   - `report_id`
   - Step1~Step5 상태
   - Graphiti badge
     - `provider`
     - `native_ingest_state`
     - `native_search_state`
     - `fallback_cache_enabled`
     - `product_flow_state`

## Graphiti native vs fallback

현재 provider는 두 층으로 동작합니다.

```text
1. Graphiti native mirror
   - /messages ingest
   - /search native fact retrieval

2. MiroFish compatibility cache
   - 기존 frontend/backend가 기대하는 nodes/edges/search 형태 유지
   - native Graphiti extraction 실패 시에도 제품 흐름 유지
```

따라서 보고/판정은 항상 분리합니다.

```text
Product flow: PASS
Graphiti infrastructure: PASS
Graphiti native ingest: PASS | BLOCKED | UNKNOWN
Graphiti native search: PASS | FALLBACK | UNKNOWN
Fallback cache: ENABLED
```

## Known limitations

- Graphiti native `/messages` extraction은 local LLM endpoint의 strict structured-output 호환성에 따라 실패할 수 있습니다.
- 이 경우 Local Demo MVP는 compatibility cache로 Step1~Step5를 계속 통과하지만, 이를 “순수 Graphiti native success”로 보지 않습니다.
- public tunnel/cloud demo, multi-user production security, million-agent production scale은 1차 완성본 범위가 아닙니다.
- Graphiti native extraction 완전 안정화는 1.5차/2차 milestone입니다.

## Troubleshooting

### backend health 실패

```bash
docker compose --profile graphiti ps
docker compose --profile graphiti logs --tail=120 mirofish
```

### graphiti health 실패

```bash
docker compose --profile graphiti logs --tail=160 graph-memory
docker compose --profile graphiti logs --tail=120 neo4j
```

### Graphiti native ingest blocked

`/api/graph/data/<graph_id>`에서 다음을 확인하세요.

```text
graphiti_status.native_ingest_state
graphiti_errors
graphiti_events
```

주요 원인은 Graphiti가 요구하는 structured-output schema와 현재 LLM endpoint 응답 불일치입니다. 다음 단계에서는 Graphiti 전용 model endpoint 또는 schema repair adapter를 분리해서 해결합니다.
