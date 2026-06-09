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
