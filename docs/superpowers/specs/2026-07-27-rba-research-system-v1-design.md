# RBA 연구 시스템 v1 설계

**상태:** 방향 승인 · 구현계획 전 owner 문서 검토
**승인:** 2026-07-27 — Mac mini 연구 기준 호스트, dataset-v1 재구축, 최신 모델·evidence 재평가
**중앙 카탈로그:** `docs/research/README.md`

## 1. 목표

모델이 바뀔 때마다 과거 실험을 처음부터 반복하지 않고, 동일한 데이터 계약과 평가 절차로 새
VLM·local LLM·Python/Gate evidence의 실제 개선분을 비교할 수 있는 지속 가능한 연구 시스템을
만든다.

핵심 결과는 세 가지다.

1. Mac mini가 노트북 연결과 무관하게 연구 작업을 지속한다.
2. 기존 203건과 지금까지의 검수 자료를 보존하면서 재현 가능한 `dataset-v1`을 만든다.
3. 프롬프트·모델·evidence 개선을 fresh holdout으로 검증해 과적합을 막는다.

## 2. 확정 원칙

### 기존 성적의 의미

기존 성공률은 폐기하지 않는다. 각 수치는 당시의 model, prompt, sampler, dataset 버전에 대한
역사적 기준선이다. 새 모델의 성능으로 그대로 전이할 수 없으므로 새 계약에서 재측정한다.

### 기존 프롬프트 실패의 해석

데이터 부족만을 원인으로 단정하지 않는다. 현재 증거가 지지하는 원인은 다음 세 가지다.

- 카메라·날짜·episode·희귀 행동 다양성 부족
- 작은 게코·가림·거리처럼 입력에 실제 시각 정보가 부족한 사례
- 같은 입력에서도 결과가 바뀌는 모델 판정 비결정성

### 연구의 기억

ChatGPT Desktop은 연구 계획·코드 작업·결과 해석의 주체가 될 수 있지만 연구 상태의 유일한
저장소가 될 수 없다. Git, 중앙 카탈로그, dataset manifest, TEST-SHEET, 실행 ledger가 연구의
내구성 있는 기억이다.

## 3. Mac mini 연구 운영 구조

| 구성 | 책임 |
|---|---|
| Mac mini | clean repo/worktree, 모델 환경, 실제 연구 실행, 로그·결과 저장 |
| LaunchAgent / job runner | 장기 실행, 주기 작업, 재부팅 복구, fail-closed host guard |
| ChatGPT Desktop | 연구 설계, 구현, 검수, 결과 해석, 다음 결정 |
| Claude | 독립 구현·교차검수 보조. 결과는 동일 카탈로그와 문서 계약으로 합류 |
| MacBook·스마트폰 | 원격 명령·진행 확인·사람 검수 클라이언트 |
| Git·catalog·manifest·DB ledger | 세션과 앱 재시작을 넘어 보존되는 연구 상태 |

production worker와 research worker는 분리한다. 연구 작업은 낮은 우선순위로 실행하며 production
lock·deadline·정규 스케줄과 겹치면 자동 양보한다. 대화형 Desktop 앱을 주기 실행 daemon으로
사용하지 않는다.

### 운영 완료 조건

- MacBook 연결을 끊은 뒤 24시간 작업 지속
- Mac mini 재부팅 후 승인된 연구 job 복구
- 원격에서 현재 HEAD, job 상태, 최근 결과, 실패 원인을 확인
- 세션 종료 후에도 catalog·manifest·ledger만으로 재개 가능

## 4. Dataset v1 계약

기존 자료를 하나의 무작위 split으로 합치지 않는다. 먼저 전수 inventory를 만들고 목적별로 네
층으로 분리한다.

| split | 구성 | 용도 |
|---|---|---|
| `legacy_regression` | 기존 203 중 재생 가능하고 GT가 확인된 자료 | 과거 기능 퇴행 확인 |
| `development` | Owner GT와 일반 연구 선별 자료 | prompt·evidence·local LLM 개발 |
| `challenge` | 역사적 오답·가림·희귀 행동·난제 | 알려진 실패 회귀 확인 |
| `fresh_holdout` | 앞으로 이중 블라인드로 수집하고 잠근 자료 | 최종 평가에 한 번만 사용 |

같은 사건의 유사 clip이 다른 split에 들어가지 않도록 `episode + camera-night` 단위로 분리한다.
기존 203, Owner GT 172, historical 오류셋은 이미 관찰된 자료이므로 fresh holdout에 들어갈 수
없다. 서로 겹치는 clip과 episode를 제거한 뒤 실제 수량을 계산하며 단순 합산하지 않는다.

### Clip 최소 필드

- `dataset_version`, 불변 `clip_id`
- 원본 media content hash와 현재 재생 가능 여부
- camera, captured_at, camera-night, 주야, duration
- `episode_id` 또는 dedup group
- `selection_reason`
- visibility, occlusion, motion extent
- 행동·interaction GT와 label contract version
- 두 라벨러의 원본 제출, 합의 상태, Owner adjudication
- split과 할당 근거
- 입력으로 허용되는 metadata와 평가 전용 metadata의 구분
- model, prompt, sampler, evidence, 실행 provenance

Owner 메모, 기존 VLM 출력, reasoning은 모델 입력용 metadata나 사람 GT에 섞지 않는다. 원본 media가
보존창에서 사라진 경험이 있으므로 manifest만 만들고 끝내지 않고 hash와 실제 보존 위치를 함께
확인한다.

## 5. 평가 순서

1. dataset-v1 inventory와 split을 동결한다.
2. 현재 production worker의 model·prompt·sampler를 dataset-v1에 재측정해 새 기준선을 만든다.
3. 같은 입력·prompt·sampler에서 candidate model만 바꿔 비교한다.
4. `VLM-only`와 `Evidence + VLM`을 비교해 Python/Gate evidence의 증분 효과를 측정한다.
5. local LLM을 행동 정답 생성기가 아니라 evidence 요약·라우팅 보조로 비교한다.
6. development에서 prompt 후보를 만들고 challenge로 알려진 실패를 확인한다.
7. 후보 하나를 동결한 뒤 fresh holdout에 한 번만 평가한다.
8. 통과한 후보만 production과 분리된 shadow로 운영한다.

한 실험에서는 model, prompt, evidence 중 하나만 변경하는 것을 기본으로 한다. 둘 이상을 바꾸는
경우에는 개별 기여도를 확인할 ablation이 반드시 필요하다.

## 6. Prompt lifecycle

- 모든 prompt에 불변 version과 content hash를 부여한다.
- 변경 전 가설, 기대되는 개선 class, 안전 지표를 TEST-SHEET에 사전 등록한다.
- prompt 수정은 development에서만 한다.
- challenge는 알려진 오류의 회귀 확인에 사용한다.
- fresh holdout은 후보 동결 후 한 번만 사용한다.
- holdout 결과를 보고 수정했다면 해당 자료를 development로 강등하고 새 holdout을 만든다.
- 실시간 누적 수정 대신 주간 또는 격주 release 단위로 평가한다.
- 평균 정확도뿐 아니라 행동별 성능, 사람 합의율, 3회 VLM 불일치율을 기록한다.

사람 이중 블라인드 consensus는 GT 생성 절차이고, VLM 3회 consensus shadow는 모델 안정성
측정이다. 이름이 비슷해도 서로 대체하지 않는다.

## 7. 30·60·90일 게이트

### 30일 — 실행 기반과 데이터 계약

- Mac mini 24시간 지속·재부팅 복구 시험 통과
- 기존 203과 Owner GT 172의 clip·episode 중복, media availability 전수 확인
- dataset schema와 네 split 계약 동결
- fresh 이중 블라인드 수집 가동
- 현재 worker 재현 기준선 확보
- manifest 필수 필드 누락 0, split 간 episode 중복 0, media availability 미확인 0

### 60일 — 비교 실험

- 목표: 최소 2 cameras, 14 camera-nights, 100 independent episodes의 fresh 자료
- 희귀 핵심 행동은 20 episodes 미만이면 성능 결론 대신 `HOLD_DATA`
- 최신 candidate VLM 2종 이상을 동일 계약으로 반복 비교
- VLM-only와 Evidence+VLM ablation 완료
- local LLM 보조 역할의 정확도·지연·검수부담 측정
- 행동별 성능, 위험행동 recall, 3회 불일치율, token·비용·시간, 사람 검수율 기록

### 90일 — 잠금 평가와 shadow

- 후보 model·prompt·evidence 조합 하나 동결
- fresh holdout 1회 평가
- 통과 후보를 production 결과와 분리해 최소 2주 shadow 운영
- 표본 부족 stratum은 통과로 계산하지 않음

잠정 adoption gate는 첫 30일에 TEST-SHEET로 고정한다. 최소 요구는 위험 행동 성능 저하 없음,
전체 품질의 의미 있는 향상 또는 2%p 이내 비열등과 비용 25% 이상 감소, 판정 불일치율 30% 이상
감소, 처리 실패율 1% 미만이다. 실제 수치는 dataset inventory 결과를 보기 전에 동결한다.

## 8. 실행 패키지 순서

각 항목은 별도 spec·plan·검증·커밋 단위로 하나씩 진행한다.

R1의 plan과 runtime 작업은 먼저 [`AI 연구 운영 계약`](../../research/AI-OPERATING-CONTRACT.md)에 맞는
run manifest를 A→M→B→C lifecycle로 기록하고
[`validator`](../../../scripts/verify_research_run_manifest.py)로 통과해야 한다. 운영 계약 v1은
`AI_OPERATING_CONTRACT_V1_VERIFIED`로 독립 final review와 전체 회귀를 통과했다. 다음은 R1
설계·구현계획·start manifest 작성만 허용되며, R1 자체 start manifest가 host·clean
Git·trusted approval 조건을 통과하기 전에는 runtime 구현이나 장기 job을 시작하지 않는다.

1. **R1 Mac mini research runtime foundation** — 실행·재부팅·원격 관측 계약
2. **R2 Dataset v1 inventory** — 기존 자료 중복·미디어·provenance 전수 감사
3. **R3 Dataset v1 split freeze** — 네 split과 manifest v1 동결
4. **R4 Current worker rebaseline** — 현 모델·prompt·sampler 재측정
5. **R5 Candidate model benchmark** — 최신 VLM model-only 비교
6. **R6 Evidence ablation** — VLM-only vs Python/Gate Evidence+VLM
7. **R7 Local LLM assistant benchmark** — evidence 요약·라우팅 보조 평가
8. **R8 Prompt release candidate** — development/challenge 반복 후 후보 동결
9. **R9 Fresh holdout + shadow** — 1회 평가와 분리 shadow

R1과 R2는 설계상 독립적이지만 사용자가 요청한 “하나씩” 원칙에 따라 R1부터 완료하고 R2로
넘어간다.

## 9. 금지 경계

- 기존 203·Owner GT·기각 연구 삭제
- 과거 수치를 새 모델의 성능으로 간주
- historical error-selected set을 fresh holdout으로 사용
- holdout을 보며 prompt·threshold를 반복 수정
- local LLM을 검증 없이 행동 GT 또는 자동 label로 사용
- Gate/Python Evidence 처리량 PASS를 행동 정확도 PASS로 해석
- 연구 worker가 production lock·deadline을 침범
- Desktop 대화 세션만을 연구의 유일한 상태 저장소로 사용

## 10. 첫 재개점

이 문서 승인 후 `R1 Mac mini research runtime foundation`의 구현계획을 별도 작성한다. R1에서는
dataset·prompt·model benchmark를 시작하지 않는다.
