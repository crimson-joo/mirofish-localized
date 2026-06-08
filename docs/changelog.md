# Changelog — MiroFish-localized

## 2026-06-09

- Graphiti/Neo4j를 기본 그래프 메모리 provider로 승격했습니다.
- Graphiti ingest/search 실패 시 local_simple cache로 조용히 성공 처리하던 경로를 제거했습니다.
- local_simple은 명시적으로 선택한 개발 scaffold로만 남겼습니다.
- Graphiti group 삭제와 local compatibility cache 삭제를 함께 검증하는 테스트를 추가했습니다.
- Kanban 멀티에이전트 운영 기준에 Shared Task Contract와 역할별 의존성 순서를 반영했습니다.
