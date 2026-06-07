# Release 기준 — MiroFish-localized

## 릴리즈 의도

현재 릴리즈는 MiroFish 전체 SaaS/프로덕션 배포가 아니라, 다음을 main 기준선으로 확정하는 단계입니다.

1. ZEP-free local runtime baseline
2. Graphiti/Neo4j compose profile
3. Graphiti native extraction hardening gate
4. GitHub Pages 정적 checkpoint
5. PR → main → Pages deploy → canary 확인 루프

## 브랜치 정책

- `develop`: 기능 통합 기준선
- `main`: 공개 checkpoint 및 안정 기준선
- `develop → main`: 일반 merge commit 권장

## 배포 대상

- GitHub Pages: 정적 문서/checkpoint 페이지
- 로컬 앱 runtime: Docker Compose로 실행, Pages로 대체하지 않음

## 필수 릴리즈 게이트

1. PR merge 전
   - backend route/provider tests
   - frontend build
   - docker compose config
   - local smoke
   - native-only Graphiti smoke
   - 브라우저 화면 확인 및 스크린샷

2. PR merge 후
   - GitHub Pages workflow success
   - canonical/cache-busted URL live canary
   - static page markers 확인
   - console/blocker error 확인

3. 자동화 상태
   - CI workflow가 테스트/build를 수행해야 함
   - Pages workflow가 post-deploy scripted canary를 수행해야 함
   - Pages workflow가 Playwright browser canary로 live render/console/marker를 확인해야 함
   - Hermes webhook은 secret과 public tunnel이 있으면 post-deploy 결과를 Telegram으로 전달해야 함
   - quick tunnel 기반 webhook은 개발/도그푸드용이며, 운영 안정화에는 named tunnel/static relay가 필요함

## 롤백 기준

- main merge 이후 Pages deploy가 깨지면 이전 main commit으로 revert PR 생성
- 로컬 runtime 기능이 깨지면 `develop`에서 fix branch 생성 후 재통합
- Pages static checkpoint만 깨진 경우 runtime rollback이 아니라 Pages workflow/docs fix로 대응
