# Design — MiroFish-localized

## UX 방향

MiroFish-localized의 UI/문서는 **한국어-first + 핵심 영어 병기**를 기준으로 합니다.

예:

```text
분류 구조(Ontology)
대상(Entity)
그래프(GraphRAG)
참가자(Agent)
인물 설정(Persona)
보고서 AI(Report Agent)
흐름 완료(FLOW PASS)
Graphiti 직접 처리(Native)
대체 처리(Fallback)
```

영어를 완전히 제거하지 않는 이유는 GraphRAG, Entity, Agent, Persona, Report Agent 같은 용어가 제품 이해의 기준 단어이기 때문입니다.

## 현재 화면 기준

대표 화면:

```text
static/image/Screenshot/localized-home-ko.png
```

이 화면은 현재 로컬 UI에서 직접 캡처한 한국어 홈/업로드 화면입니다.

현재 화면에서 보여야 하는 것:

- 언어 선택: 한국어
- 시작 문구: “보고서를 업로드하고 미래를 예측하세요”
- 업로드 영역: PDF/MD/TXT/PNG/JPG/WEBP
- 시뮬레이션 프롬프트 입력
- Step1~Step5 workflow
- Report Agent와 GraphRAG 개념이 한국어 UI 안에 자연스럽게 보임

## 원본 이미지 취급

원본 MiroFish 이미지:

```text
static/image/Screenshot/运行截图*.png
```

이 파일들은 원본 보존용으로 남길 수 있습니다. 다만 localized fork의 README나 current docs에서 “현재 상태 증거”로 사용하지 않습니다.

## 문서 스크린샷 갱신 기준

UI/UX 변경이 있을 때:

1. 로컬 앱 또는 Pages checkpoint를 실제로 띄웁니다.
2. 한국어 화면을 캡처합니다.
3. screenshot 파일명에 의미를 담습니다.
   - 예: `localized-home-ko.png`
   - 예: `multiverse-dashboard-ko.png`
4. README와 `docs/current/design.md`가 새 이미지를 가리키게 합니다.
5. QA 문서에는 어떤 화면/상태를 확인했는지 남깁니다.

## Multiverse / Report Agent 시각화 기준

멀티버스 화면은 단순 개발자 JSON viewer가 아니라, 의사결정자가 다음을 빠르게 이해할 수 있어야 합니다.

- 각 universe 상태
- prepare/run progress
- outcome cluster label
- `ensemble_frequency`
- sensitivity axes
- evidence snippet
- “확률이 아니라 ensemble 내 빈도”라는 주의 문구
- Report Agent 추천 질문의 출처/이유

## 한국어 품질 기준

- 버튼/상태/경고/설명은 한국어로 읽혀야 합니다.
- 기술 용어는 필요 시 괄호 병기합니다.
- 중국어 UI chrome이 새 화면에 남아 있으면 실패로 봅니다.
- 과거 생성 보고서/파일명/원본 데이터 언어는 별도 번역 요구가 없으면 실패로 보지 않습니다.

## 문서 디자인 기준

README는 마케팅 원문보다 현재 상태/사용법/검증 여부를 우선합니다.

권장 순서:

```text
1. 현재 상태
2. 현재 한국어 화면
3. 사용 흐름
4. 실행 방법
5. 검증 방법
6. 한계/주의
7. 에이전트 문서 운영 원칙
```
