# Changelog — MiroFish-localized

## 2026-06-09

- Graphiti/Neo4j를 기본 그래프 메모리 provider로 승격했습니다.
- Docker Compose 앱 기본값도 `GRAPH_PROVIDER=graphiti`로 맞췄습니다.
- `local_simple` 제품 런타임 provider를 제거하고 Graphiti projection cache를 UI read-model로 분리했습니다.
- Graphiti OpenAI-compatible structured-output 응답을 Graphiti Pydantic schema로 정규화해 native extraction `pass` 경로를 안정화했습니다.
- Graphiti ingest/search 실패는 projection cache로 조용히 성공 처리하지 않습니다.
- Graphiti group 삭제와 projection cache 삭제를 함께 검증하는 테스트를 추가했습니다.
- Kanban 멀티에이전트 운영 기준에 Shared Task Contract와 역할별 의존성 순서를 반영했습니다.
- 한국어/영어/중국어 실제 사용자 관점의 홈·보고서·심화 인터랙션·Report Agent Q&A 제품 QA 기준선을 문서화했습니다.
