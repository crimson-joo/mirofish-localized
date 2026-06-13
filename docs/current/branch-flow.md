# Branch / PR / CI 운영 기준 — MiroFish-localized

## 결론

이 저장소의 기준 운영 흐름은 **Medium / Develop Integration Flow**입니다.

```text
feature worktree/branch
  → local/agent validation
  → squash or curated merge into develop
  → develop integrated QA
  → develop → main PR
  → CI / Pages / canary
  → main merge
```

`main`은 공개 checkpoint와 안정 기준선입니다. `develop`은 여러 feature를 모아 검증하는 통합 기준선입니다.

## 브랜치 역할

| 브랜치 | 역할 |
|---|---|
| `main` | 안정 기준선, GitHub default branch, Pages/static checkpoint 배포 기준 |
| `develop` | 다음 main 반영 전 통합/검증 기준선 |
| `feat/*`, `fix/*`, `docs/*`, `chore/*` | 기능/수정 작업 브랜치. 가능하면 worktree에서 작업 |

## 금지/주의

- GitHub default branch를 `feat/*`로 두지 않습니다.
- 기능 브랜치를 장기간 default branch처럼 사용하지 않습니다.
- 새 기능을 곧바로 `main`에 계속 PR하는 short-breath loop는 지양합니다.
- feature 검증만으로 완료로 보지 않고, `develop` 통합 후 다시 검증합니다.
- Pages는 전체 로컬 runtime이 아니라 정적 checkpoint입니다.

## 정상 개발 흐름

### 1. 작업 시작

```bash
git fetch origin
git checkout develop
git pull --ff-only origin develop
git checkout -b feat/<short-slug>
```

대형/병렬 작업은 repo 내부가 아니라 worktree 사용을 권장합니다.

```bash
git worktree add ~/worktrees/mirofish-localized/feat/<short-slug> -b feat/<short-slug> develop
```

### 2. 로컬 검증

최소 게이트:

```bash
npm run build
cd backend && uv run pytest -q
cd ..
docker compose config --quiet
./scripts/local-smoke.sh
GRAPHITI_NATIVE_ONLY_SMOKE=1 ./scripts/graphiti-native-smoke.py
```

UI/제품 변경이면 브라우저 확인도 포함합니다.

- `http://127.0.0.1:3000/`
- 콘솔 blocker error 없음
- 한국어 UI 기준 문구/흐름 확인

### 3. feature → develop fan-in

feature 브랜치에서 검증이 끝나면 `develop`에 통합합니다.

```bash
git checkout develop
git pull --ff-only origin develop
git merge --squash feat/<short-slug>   # noisy feature일 때 권장
git commit -m "feat: <summary>"
```

feature commit이 이미 깨끗한 경우 일반 merge도 가능하지만, agent/worktree 산출물이 많은 경우 squash를 기본으로 봅니다.

### 4. develop 통합 검증

`develop`에서 다시 검증합니다. feature에서 통과했더라도 통합 기준선에서 다시 봅니다.

```bash
npm run build
cd backend && uv run pytest -q
cd ..
./scripts/local-smoke.sh
```

### 5. develop → main PR

```bash
git push origin develop
gh pr create --base main --head develop --title "Release: <summary>" --body "..."
```

이 PR이 실제 release/sync checkpoint입니다. 기본 merge 방식은 **normal merge commit**입니다. `develop`에는 이미 feature 단위로 정리된 commit이 있어야 하므로, `develop → main`은 squash하지 않는 편이 추적에 유리합니다.

## CI / Webhook / Canary가 언제 도는가

| 트리거 | 실행 |
|---|---|
| PR to `develop` or `main` | Local Runtime CI: backend tests, frontend build, compose config |
| push to `develop` | Local Runtime CI |
| push to `main` | Local Runtime CI + 조건부 Hermes local-runtime webhook. Webhook URL/tunnel이 죽어도 테스트 자체는 통과로 유지하고, webhook 단계만 경고/실패 신호로 남긴다. |
| push to `main` with docs/pages/current 변경 | Pages deploy + scripted/browser Pages canary + 조건부 Hermes Pages webhook. Pages 자체 canary와 webhook 전달 성공은 분리해서 판단한다. |
| manual workflow_dispatch | 수동 CI / webhook handoff 가능 |

Webhook은 GitHub Actions secret이 설정되어 있을 때만 호출됩니다. GitHub-hosted runner는 사용자의 `localhost`를 직접 검증할 수 없으므로, local runtime canary는 Hermes가 Mac에서 후속 검증하는 구조입니다.

## GitHub 설정 기준

- Default branch: `main`
- `develop`은 integration branch로 유지
- stale feature branch는 default나 release 기준으로 쓰지 않고 정리
- 가능하면 branch protection/required checks는 `main`에 우선 적용

## 현재 로컬 runtime 경로

현재 이 Mac의 runtime 기준 경로는 외장 SSD입니다.

```text
/Volumes/ExternalSSD/Workspace/Projects/mirofish-localized
```

README나 quickstart에 과거 `~/Projects` 경로가 남아 있으면 외장 SSD 기준으로 업데이트합니다.
