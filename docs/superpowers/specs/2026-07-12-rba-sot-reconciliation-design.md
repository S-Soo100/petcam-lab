# RBA SOT 정합성 복구 설계

**작성일:** 2026-07-12
**상태:** 승인됨 — 사용자 요청에 따라 문서화·정합성 복구·main 반영을 한 번에 수행

## 1. 목적

petcam-lab의 목표, 현재 VLM/RBA 판단, router 연구 유효성 감사, 다음 실행 계획을 하나의 결정 체계로 맞춘다. 과거 실험 기록은 보존하되, 활성 진입 문서가 폐기된 Gemini production 계획이나 무효화된 router 평가를 다음 작업으로 안내하지 않게 한다.

## 2. SOT 우선순위

충돌 시 아래 순서로 해석한다.

1. `docs/petcam-north-star.md`: 제품·사업의 최종 목표
2. `docs/AI-VIDEO-ANALYSIS-STRATEGY.md`: RBA 구성요소와 역할
3. 최신 판정 문서: 연구 유효성 감사와 사전 등록된 시험지
4. `specs/next-session.md`: 다음 실행 순서
5. `README.md`, `AGENTS.md`, `CLAUDE.md`, `docs/FEATURES.md`, `docs/GLOSSARY.md`: 위 SOT의 요약·진입점

개별 과거 spec, report, audit log는 당시 판단을 보존하는 역사 기록이다. 최신 판정과 충돌해도 원문을 소급 수정하지 않고 활성 인덱스에서 historical 또는 invalid-for-adoption으로 표시한다.

## 3. 고정할 결정

### 3.1 제품 목표

목표는 VLM 정확도 경쟁이 아니라 카메라 영상을 행동 타임라인, 케어 후보, 개체별 장기 baseline으로 바꾸는 RBA다. 첫 제품 출력은 활동량, 중요 행동 후보, 확인할 하이라이트, 평소와 다른 변화, 수의사에게 전달할 근거 영상이다. 의료 진단은 주장하지 않는다.

### 3.2 Track A와 Track B

- Track A는 **전수 또는 넓은 범위의 저비용 의미 분석 역할**이다. Gemini 2.5 Flash와 v3.5는 2026-04 historical baseline이며 현재 production 모델이 아니다.
- Track B는 중요한 후보를 event segment로 정밀 분석하는 품질 연구 역할이다. 구독 기반 Claude 연구는 자매 레포에서 유지한다.
- 현재 production 모델은 미확정이다. 저비용 API 모델, adaptive-frame 입력, prompt, 클래스, 비용 계약을 한 세트로 동결한 뒤에만 새 baseline이라고 부른다.

### 3.3 비용 절감

- Python/OpenCV adaptive-frame 전처리는 비용 절감용 입력 경로로 유지한다.
- OpenCV motion-only 자동라벨, detector v2 unseen skip, local router v0의 skip/auto-label은 채택하지 않는다.
- local router v0/v1/v2 및 care-guard v1/v1.1은 exploratory failure evidence다. production 채택 근거는 `invalid-for-adoption`, 비용 절감은 `not-measured`, 현재 production eligibility는 `rejected`다.
- metadata/provenance/review UI는 GT 수집과 실패 분석 인프라로 유지한다.

### 3.4 다음 검증 계약

`router-cost-v2`는 바로 실행하지 않는다. 다음 항목을 먼저 동결한다.

- baseline API 모델·입력·prompt·클래스와 실제 토큰/KRW 산식
- candidate router commit·feature schema·threshold·route별 후속 처리
- 미래 camera-night 분할, sample seed, clip list와 checksum
- blind GT 절차와 label provenance
- budget limit, 실제 호출별 비용 기록, transient error만 최대 3회 retry, 반복 prompt caching 적용 여부

독립 표본은 승인 이후 연속 14박, 최소 300 labeled clips를 사용한다. P0 30건은 pilot 판정까지만 허용하고 adoption의 2pp 비열등성 판단은 최소 150 P0 events를 기본 목표로 한다. 150건에서도 paired confidence interval이 2pp를 확정하지 못하면 결론을 `hold / inconclusive`로 둔다.

## 4. 다음 실행 순서

1. 활성 SOT 정합성 복구
2. 저비용 production VLM baseline 후보 하나 선정·비용 계약 작성
3. baseline과 router policy 동결
4. 미래 GT 수집 및 provenance 기록
5. 30 P0 pilot로 실행·운영 결함 확인
6. 150 P0 adoption set까지 확장
7. total eventual VLM KRW, P0 recall, review burden, delay를 함께 평가
8. 전 gate 통과 시에만 router production 적용 검토

추가 router threshold 튜닝, 기존 72/203/v1/v1.1 데이터의 holdout 재사용, route 이동만으로 비용 절감 주장, 미검수 backlog를 비용 0으로 계산하는 행위는 금지한다.

## 5. 변경 범위

- 정합화: `README.md`, `AGENTS.md`, `CLAUDE.md`, `docs/petcam-north-star.md`, `docs/AI-VIDEO-ANALYSIS-STRATEGY.md`, `docs/FEATURES.md`, `docs/GLOSSARY.md`, `specs/README.md`, `specs/next-session.md`
- 보강: `experiments/router-cost-v2/TEST-SHEET.md`
- 보존: 과거 실험 spec/report, 데이터, 코드, DB, worker 설정

## 6. 완료 조건

- 활성 진입 문서에서 Gemini/v3.5를 현재 production baseline으로 부르지 않는다.
- local router의 현재 판정이 모든 활성 문서에서 중단·exploratory·invalid-for-adoption으로 일치한다.
- `next-session.md`가 기존 72건 threshold 재조정이 아니라 baseline 동결과 미래 GT 수집을 첫 작업으로 안내한다.
- `router-cost-v2`가 P0 30 pilot / 150 adoption을 구분하고 실제 비용 추적·retry·prompt caching 계약을 포함한다.
- 문서 링크 검사, `git diff --check`, Python 전체 테스트, web TypeScript 검사가 통과한다.
