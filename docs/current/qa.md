# QA 기준 — MiroFish-localized

## 목적

이 문서는 QA/Canary 에이전트가 단순 HTTP 200이 아니라, 이번 프로젝트의 의도에 맞게 무엇을 확인해야 하는지 정의합니다.

## 현재 릴리즈에서 검증할 사용자 가치

1. ZEP Cloud 없이 로컬 Docker Compose 기반으로 MiroFish 기본 흐름을 실행할 수 있다.
2. Graphiti/Neo4j 로컬 그래프 메모리 경로가 연결되어 있다.
3. Graphiti native / repair / fallback 상태를 혼동하지 않고 확인할 수 있다.
4. GitHub Pages는 전체 앱 배포가 아니라 정적 체크포인트/문서 페이지임을 명확히 보여준다.

## 로컬 QA 기준

- Frontend: `http://127.0.0.1:3000/` 렌더링
- Backend: `/health` 정상
- Graphiti: `/healthcheck` 정상
- UI: Step1~Step5 설명과 최근推演记录 카드 표시
- Console: blocker JS error 없음
- Smoke: `./scripts/local-smoke.sh` PASS
- Native extraction gate: `GRAPHITI_NATIVE_ONLY_SMOKE=1 ./scripts/graphiti-native-smoke.py` PASS 또는 명확한 BLOCKED 사유

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

## 보고 기준

QA/Canary 보고는 다음을 분리합니다.

```text
로컬 앱 동작: PASS/PARTIAL/FAIL
GitHub Pages 정적 배포: PASS/PARTIAL/FAIL
Graphiti native extraction: PASS/PARTIAL/FAIL
자동화 파이프라인: PASS/PARTIAL/FAIL
Webhook/Hermes 후속 QA: PASS/SKIPPED/FAIL
```
