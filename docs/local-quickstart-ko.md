# MiroFish-localized Local Demo MVP 빠른 시작

## 목표

이 문서는 ZEP Cloud 없이 Docker Compose 로컬 스택으로 MiroFish를 재현하는 절차입니다.

현재 기준은 다음입니다.

```text
MiroFish Step1~Step5 제품 흐름을 로컬에서 실행하고,
Graphiti native ingest/search가 pass 상태로 동작하는지 API/UI/문서에서 확인한다.
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
# Graphiti extraction만 별도 모델로 강화하려면 GRAPH_MEMORY_MODEL_NAME / GRAPH_MEMORY_SMALL_MODEL_NAME 조정
docker compose up -d --build
```

기본 `docker compose up`은 MiroFish + Graphiti + Neo4j를 함께 올립니다. 즉 Graphiti를 따로 호스트에 띄워둘 필요가 없습니다.

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

기본 smoke는 Graphiti native fact smoke도 실행합니다. 이 검증은 MiroFish projection cache를 우회해서 Graphiti service 자체 `/messages` → `/search`가 searchable fact를 만들 수 있는지 확인합니다.

```text
PASS messages {'message': 'Messages processed synchronously; native=1, repaired=0', 'success': True}
PASS native_search facts=1 ...
```

native smoke를 건너뛰려면:

```bash
RUN_GRAPHITI_NATIVE_SMOKE=0 ./scripts/local-smoke.sh
```

2차 hardening에서는 repair adapter 없이 Graphiti LLM extraction 자체가 통과하는지 확인하는 strict gate도 제공합니다.

```bash
GRAPHITI_NATIVE_ONLY_SMOKE=1 ./scripts/graphiti-native-smoke.py
```

이 모드는 `/messages` 결과가 `native>=1, repaired=0`일 때만 PASS입니다. 현재 로컬 endpoint가 strict structured-output schema를 만족하지 못하면 FAIL이 정상이며, 그 경우 `GRAPH_MEMORY_MODEL_NAME` 또는 `GRAPH_MEMORY_SMALL_MODEL_NAME`을 structured-output에 강한 모델 endpoint로 바꿔 재검증합니다.

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
     - `projection_cache_enabled`
     - `product_flow_state`

## Graphiti native vs fallback

현재 provider는 두 층으로 동작합니다.

```text
1. Graphiti native source of truth
   - /messages ingest
   - /search native fact retrieval
   - Neo4j 저장

2. Graphiti projection cache
   - 기존 frontend/backend가 기대하는 nodes/edges/search 형태의 UI read-model
   - Graphiti 실패를 성공으로 바꾸는 fallback provider가 아님
```

판정은 항상 분리합니다.

```text
Product flow: PASS
Graphiti native ingest: PASS | REPAIRED | FAILED
Graphiti native search: PASS | FAILED | UNKNOWN
Projection cache: ENABLED | DISABLED
local_simple fallback: REMOVED
```

## Multimodal / Ollama Gemma4

현재 Step1~Step5의 GraphRAG/시뮬레이션/보고서 흐름은 텍스트, 이미지 파일, 그리고 시각 요소가 들어간 PDF를 함께 받을 수 있습니다. 이미지(`PNG/JPG/WEBP/GIF`)와 PDF 안의 차트/그림/스캔 페이지는 `MULTIMODAL_*` endpoint로 먼저 텍스트/차트 신호를 추출한 뒤 ontology/graph build 입력에 합쳐집니다.

```text
gemma4:12b-mlx
- Apple/macOS 호스트의 Ollama/MLX 런타임용
- Docker 컨테이너에서는 http://host.docker.internal:11434/v1 로 접근
- 이미지+텍스트 질의가 가능한 vision-capable LLM 성격

Docker 안의 Ollama
- Linux 컨테이너 런타임이므로 MLX tag가 아니라 일반 tag를 사용
- 예: OLLAMA_MULTIMODAL_MODEL=gemma4:12b docker compose --profile ollama up ollama-pull
```

주의: 멀티모달 LLM은 이미지 이해/요약/OCR-like 질의는 할 수 있지만, 전용 OCR 엔진이나 문서 레이아웃 파서와 완전히 같은 역할은 아닙니다. 정확한 표 추출, 좌표 기반 OCR, 대량 PDF 파싱이 필요해지면 OCR/문서 파서 + multimodal LLM을 함께 붙이는 구조가 더 안정적입니다.

리소스 기준: 선택지 A를 기본으로 사용하므로 Docker Compose는 Ollama 컨테이너를 기본으로 띄우지 않습니다. `--profile ollama`는 Linux 컨테이너 Ollama가 정말 필요할 때만 사용하세요.

업로드 지원 형식:

```text
텍스트/PDF: PDF, MD, TXT
이미지/차트: PNG, JPG, JPEG, WEBP, GIF
PDF 내부 시각자료: 차트/그림/스캔 페이지를 페이지 이미지로 렌더링해 분석
```

PDF 시각 분석 조정:

```text
PDF_MULTIMODAL_ANALYSIS=true
PDF_MULTIMODAL_MAX_PAGES=6
PDF_MULTIMODAL_DPI=96
MULTIMODAL_MAX_TOKENS=768
```

## Known limitations

- 현재 기본 local endpoint에서는 structured-output normalization을 통해 strict native smoke가 `native>=1, repaired=0` 기준으로 통과해야 합니다.
- 다른 사용자가 다른 OpenAI-compatible 모델을 붙일 경우, 먼저 `GRAPHITI_NATIVE_ONLY_SMOKE=1 ./scripts/graphiti-native-smoke.py`로 native ingest/search를 검증합니다.
- 모델이 strict structured-output을 계속 깨면 `GRAPH_MEMORY_MODEL_NAME` 또는 `GRAPH_MEMORY_SMALL_MODEL_NAME`을 더 강한 structured-output 모델로 분리 지정합니다.
- public tunnel/cloud demo, multi-user production security, million-agent production scale은 1차 로컬 재현 범위가 아닙니다.

## Troubleshooting

### backend health 실패

```bash
docker compose ps
docker compose logs --tail=120 mirofish
```

### graphiti health 실패

```bash
docker compose logs --tail=160 graph-memory
docker compose logs --tail=120 neo4j
```

### Graphiti native ingest blocked

`/api/graph/data/<graph_id>`에서 다음을 확인하세요.

```text
graphiti_status.native_ingest_state
graphiti_errors
graphiti_events
```

주요 원인은 Graphiti가 요구하는 structured-output schema와 현재 LLM endpoint 응답 불일치입니다. 다음 단계에서는 Graphiti 전용 model endpoint 또는 schema repair adapter를 분리해서 해결합니다.
