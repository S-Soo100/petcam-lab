# RBA/VLM 활성 연구 정본

> 상태 기준: 2026-07-21 KST 17:55
>
> 연구 최종 책임: **ChatGPT/Codex** · 제품/GT 승인: **Owner** · 구현/실험 수행: **Claude 또는 별도 coding agent**

## 1. 이 문서의 역할

이 문서는 여러 레포와 AI 세션에 흩어진 연구를 찾는 단일 인덱스다. 원본 TEST-SHEET·REPORT·Git commit을 대체하지 않고, 어떤 결과가 현재 활성인지와 다음에 무엇을 해야 하는지만 확정한다.

신뢰 순서:

1. [`docs/decision-gate.md`](../decision-gate.md)의 append-only 판정
2. 이 문서
3. [`specs/next-session.md`](../../specs/next-session.md)
4. 개별 handoff·REPORT

## 2. 역할 계약

| 주체 | 책임 | 금지 |
|---|---|---|
| ChatGPT/Codex | 목표·계획·decision-gate·시험 계약·결과 독립 검수·SOT 통합 | 검수 없이 agent 완료보고를 활성 판정으로 승격 |
| Claude/coding agent | 승인된 plan의 TDD 구현·실험 실행·재현 가능한 보고 | 새 연구방향 임의 착수, SOT 단독 변경, reject 결과 자동 활성화 |
| Owner | 도메인 GT·우선순위·production write/deploy 승인 | 없음 |

Claude가 2026-07-21까지 남긴 연구 결과는 폐기하지 않는다. 다만 ChatGPT 검수와 이 문서 반영 전에는 historical input이다.

## 3. 논리 통합 브랜치

서로 다른 Git 저장소는 물리적으로 같은 branch object를 공유할 수 없어, 변경이 필요한 두 레포에서 같은 이름을 쓴다.

`codex/research-consolidation-20260721`

| 레포 | 통합 전 기준 | 활성 통합 상태 |
|---|---|---|
| `petcam-lab` | `origin/main` `5f50242f0971275dd98da9e32b9df85605d15419` | 이 문서와 ChatGPT 운영 계약을 보유한 통합 branch |
| `petcam-nightly-reporter` | Python Evidence main `618f4f854254525b0ebc6f0fcf9153f8e0cd6bc1` + Claude P1 `139ff895e9f92145e183ab6be24b7486ed9ea2a1` | 양쪽 이력을 merge. REJECT된 basking runtime은 follow-up commit으로 active tip에서 제거 |
| `gecko-vision-gate` | `origin/main` `9ea55eb740e9c87dd240b9282d612772dbc798f3` | 관련 Claude branch 전부 이미 main 포함, 변경 없음 |
| `petcam-rba-worker` | `origin/main` `c2249af7b902d20fba62fb1f15c89e342a5a11b4` | 미병합 연구 branch 없음, 변경 없음 |
| `tera-ai-product-master` | `origin/main` `2c7cae65d4973e64993126e1b1d96e3303183cfe` | 제품 SOT 참조점, 변경 없음 |

## 4. 활성 판정

| 트랙 | 현재 판정 | 활성 의미 |
|---|---|---|
| P1 라벨 결정론 | `adopt` 약식 | 42건 재측정에서 안정 confabulation 1건. 지배 원인은 CLI temperature 비결정성. API temp=0 배선은 결제/키 전제 미충족으로 보류 |
| P2 케이지 프로필 | `hold` | 근거 1/42뿐. temp=0 확정 결과 전 착수 금지 |
| T0 bowl-dwell | `reject` | 체류 단독은 케어행동 분류 신호로 무효 |
| T1 highlight score v1 | `reject` | detector 오염이 존재·주기성 점수를 함께 오염. v2는 decision-gate 재통과 필요 |
| 사전 필터로 VLM 차단 | 영구 탈락 | 자동 skip/비용 게이팅 재제안 금지 |
| Python Evidence CROI | raw shadow 유효 | 전 영상 evidence 생성은 유지. selector·자동 제외·행동 GT 승격은 별도 승인 필요 |
| basking v4.1 canary | `reject` | 보고서·commit 이력만 보존. active runtime은 v4.0/7-class 기준 유지 |

## 5. 다음 작업 큐

### W1 — 2026-07-22 아침 밤 사이클 복구 검증

- production DB `SELECT only`
- 적체·failed_retryable 해소, 신규 야간 clip/job/result 확인
- Slack 수신 여부는 owner에게 확인
- 장애가 남으면 수정하지 말고 diagnostic 증거와 함께 보고

### W2 — T2 GT 엔진 스펙 초안

- 문서만 작성
- `near_bowl_no_care` 스키마 매핑과 GT 이중저장 경계를 비교
- owner 승인 전 DB write·migration·구현 금지

### W3 — T1 점수식 v2

- 선택 작업
- 오검출 시그니처 페널티·카메라 정규화·Gate prelabel 중 하나의 해소 근거를 먼저 제시
- decision-gate 재통과와 새 TEST-SHEET 승인 전 실행 금지

### 운영 하드닝 backlog — Python Evidence 실패 Slack 링크

- 기존 `/labeling/{motion_clip_id}`는 `camera_clips` mirror가 없어 404가 발생하므로 사용 금지
- 권장안은 owner 전용 `/labeling/evidence-failures/{motion_clip_id}` review page
- retryable은 2번째 실패 시 1회, terminal은 즉시 1회, durable dedup
- 이 연구 통합 branch가 확정된 뒤 별도 design/plan으로 재개

## 6. Superseded branch 정책

아래 branch는 이력 보존용 read-only다. 신규 작업·추가 commit의 출발점으로 쓰지 않는다.

- `petcam-nightly-reporter/feat/vlm-basking-classification`
- `petcam-lab/feat/python-evidence-s1-benchmark`
- `petcam-lab/feat/python-evidence-threshold-tolerance`
- `petcam-lab/feat/python-evidence-universal-worker`
- 각 레포의 이미 main에 포함된 activity/self-healing feature branches

삭제는 통합 branch가 main에 반영되고 owner가 별도로 승인한 뒤에만 한다.

## 7. 세션 시작·종료 계약

시작:

1. 이 문서 읽기
2. decision-gate 최신 append 확인
3. 대상 레포·branch·40자리 SHA 확인
4. 쓰기 작업이면 tracked plan + handoff validator 확인

종료:

1. 테스트·diff·Git ancestry를 독립 검증
2. 이 문서의 판정이나 SHA가 바뀌면 additive 갱신
3. `specs/next-session.md`에 다음 한 작업만 명확히 기록
4. agent 보고만으로 production 완료를 주장하지 않기
