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

- `graphiti`: 기본값. Graphiti/Neo4j native ingest/search를 기준으로 사용합니다.
- `local_simple`: 명시적으로 선택할 때만 쓰는 개발용 JSON/JSONL scaffold입니다.
- `zep`: 원본 Zep Cloud 경로이며 `ZEP_API_KEY`가 필요합니다.

## Fail-closed 정책

Graphiti native ingest/search 실패는 local_simple cache로 조용히 성공 처리하지 않습니다.

- ingest 실패: API/서비스 레벨에서 실패로 드러납니다.
- search 실패: local cache로 fallback하지 않고 실패로 드러납니다.
- search 결과가 비어있는 경우: 빈 native 결과로 처리하며 local cache 결과를 섞지 않습니다.

## Compatibility cache

기존 MiroFish UI가 node/edge 목록을 기대하기 때문에 local JSON cache는 남아 있습니다. 단, 이는 UI compatibility cache일 뿐이며 Graphiti 실패를 PASS로 바꾸는 fallback 경로가 아닙니다.

## Group cleanup

그래프 삭제 시 Graphiti group 삭제 API를 호출한 뒤 local compatibility cache를 삭제합니다. 세션/그래프 단위 group_id는 graph_id를 기준으로 분리합니다.
