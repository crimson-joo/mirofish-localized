# Product — MiroFish-localized

## 한 줄 정의

MiroFish-localized는 한국어 사용자가 현실 문서/보고서를 올려 **GraphRAG 기반 사회·시장 시뮬레이션과 Report Agent 분석**을 로컬에서 재현하는 실험 제품입니다.

## 현재 제품 범위

### 완료된 사용자 흐름

1. **현실 seed 업로드**
   - PDF, MD, TXT
   - 이미지 파일
   - PDF 내부 차트/그림/스캔 페이지의 multimodal 분석

2. **Graph/Ontology 구축**
   - Graphiti/Neo4j를 기본 그래프 메모리 provider로 사용
   - Entity/관계/사실 기반 graph build
   - projection cache는 UI read-model일 뿐 fallback provider가 아님

3. **Persona / Agent 준비**
   - Persona generation 전에 Core-vs-All scope 표시
   - Core는 entity-type diversity와 graph connectivity 기준으로 제한/선택
   - All은 추출된 모든 Entity 사용

4. **Simulation 실행**
   - 기본 Graph memory update ON
   - 기본 짧은 실행 24 rounds
   - 긴 실행은 명시적으로 선택

5. **Report Agent**
   - 보고서/시뮬레이션/멀티버스 context를 읽고 질의응답
   - 한국어 Q&A 기준

6. **Multiverse / Ensemble**
   - 하나의 graph/topic에서 여러 universe child simulation 생성
   - scenario/persona variation 비교
   - outcome cluster, sensitivity axes, `ensemble_frequency` 제공
   - 단일 실행 대비 비교 report와 Report Agent context 제공

7. **BettaFish bridge**
   - BettaFish 최종 Markdown 보고서를 MiroFish seed로 투입
   - graph build → simulation prepare/start → action 확인 → report → Report Agent QA
   - resume-safe state/log 저장

## 현재 아닌 것

- GitHub Pages는 전체 MiroFish runtime이 아닙니다. 정적 checkpoint/문서/데모 확인용입니다.
- `ensemble_frequency`는 실제 시장 확률 예측이 아닙니다.
- 원커맨드 BettaFish→MiroFish full orchestrator는 아직 별도 상위 스크립트로 완성된 상태가 아닙니다. 현재는 BettaFish report 생성과 MiroFish bridge runner가 각각 존재합니다.
- public multi-user SaaS, production security, million-agent 상시 운영은 현재 release 범위가 아닙니다.

## 사용자가 얻는 가치

- 한국어로 로컬에서 end-to-end 실험을 재현할 수 있습니다.
- 외부 Zep Cloud 없이 Graphiti/Neo4j 기반 memory path를 검증할 수 있습니다.
- 긴 E2E가 중단되어도 state/log로 이어서 실행하고 성공/실패를 구분할 수 있습니다.
- 단일 simulation보다 여러 universe 결과가 어디서 갈리는지 볼 수 있습니다.

## 다음 후보

`필수 안정화`:

- README/docs가 기능 변경과 함께 계속 갱신되도록 PR gate에 문서 체크 유지
- live-local-runtime canary 결과를 release report에 더 자동으로 연결

`실사용 품질 개선`:

- BettaFish report 생성부터 MiroFish bridge runner까지 묶는 상위 orchestrator
- Multiverse dashboard에 outcome cluster label/evidence를 더 직관적으로 표시

`나중 후보`:

- embedding/LLM 기반 semantic clustering 고도화
- production-like hosted demo

`하지 말아야 할 고도화`:

- Graphiti 실패를 숨기는 permissive fallback 복귀
- 원본 스크린샷/문구를 current localized evidence처럼 재사용
