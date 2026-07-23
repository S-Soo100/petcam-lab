# 쳇바퀴 에피소드 10분 경계 교정 설계

**상태:** owner 승인 · 구현 전  
**성격:** 기존 shadow v1의 구조적 결함을 고치는 1회성 salvage  
**기준 branch:** `feat/wheel-episode-dedup-shadow @ 898278ff57aab089b46d2fbb616df479212820c4`

## 1. 문제

동결 시험지는 각 그룹이 `시간 외곽 경계 ≤10분`을 만족해야 한다고 규정했다. 하지만 v1은
현재 clip과 **바로 이전 clip**의 간격만 검사한다. 5분마다 비슷한 clip이 계속 들어오면 각 간격은
10분 이하지만 첫 clip부터 마지막 clip까지는 수시간이 될 수 있다.

독립 감사 결과:

- 전체 그룹: 32
- 전체 길이 600초 초과 그룹: 19
- 위반 그룹의 멤버: 296/326
- 최장 그룹: `wheel_ep_025`, 118개, 18,224초(5시간 4분 24초)
- 기존 단위 테스트는 20분의 명시적 공백만 검사해 연쇄 결합을 재현하지 못했다.

따라서 v1 결과의 `32 groups / 326 membership / 71 representatives`와 day/IR 비교는 채택 근거로
사용할 수 없다. known wheel 24개에서 계산한 62.5% 축약도 교정 후 재계산해야 한다.

## 2. 결정

자동 중복 묶음을 즉시 폐기하지 않고 **구조적 결함 교정 1회만** 허용한다.

다음 두 시간 제한을 분리한다.

1. `max_inter_clip_gap_sec=600`: 앞 clip과 현재 clip 사이의 최대 허용 간격
2. `max_episode_span_sec=600`: 한 run의 첫 clip부터 현재 clip까지의 최대 허용 길이

새 clip은 다음 중 하나라도 참이면 새 run을 시작한다.

```text
current - previous > max_inter_clip_gap_sec
OR
current - run_start > max_episode_span_sec
```

정확히 600초는 같은 run에 포함하고 600초를 초과하면 분리한다. 그룹은 한 run 내부에서만
만들므로 모든 그룹은 `started_at_last - started_at_first ≤ 600초`를 만족해야 한다.

## 3. 변경하지 않는 것

- wheel ROI 좌표
- `wheel_motion_floor=0.01`
- `hamming_threshold=7`
- `motion_tolerance=0.02`
- `novelty_min_hamming=6`
- IR/day 판정
- anchor와 대표영상 선택 규칙
- known wheel GT 24개와 fresh 779개 frozen cohort
- production DB, R2, 라벨링 웹, worker, selector

mode-scoped IR, day 전용 threshold, 모션 정지점 탐색, perceptual 급변 분할은 이번 교정에 넣지 않는다.
경계 교정 이후에도 품질이 부족하면 추가 튜닝하지 않고 자동화 폐기를 기본값으로 한다.

## 4. 재실행 방식

R2 영상과 DB를 다시 읽지 않는다. 아래 커밋된 입력을 그대로 사용한다.

| 입력 | SHA-256 |
|---|---|
| `EVIDENCE-AUDIT.json` | `23789fa8ea430c4dc24b015847c360a6afa72565c897c3d4b7b8654702a508e3` |
| `frozen-cohort.json` | `b67b32f27259d132cda5861f8126f6b48f4bb704528c0458ebbf63a95d17f953` |
| `wheel-roi-profile-v1.json` | `653e64c25e057339ce9a1844d27c570ce99916d20986023fafdabd84935c7825` |

새 runner는 저장된 `fresh`·`known_wheel` signature를 읽어 교정된 grouping만 수행한다.
기존 `experiments/wheel-episode-dedup-shadow/` 산출물은 수정하지 않고
`experiments/wheel-episode-dedup-boundary-fix/`에 새 결과를 쓴다.

새 알고리즘 버전은 `wheel-episode-dedup-shadow-v1.1-boundary-fix`다.

## 5. 기계 게이트

다음을 모두 만족해야 `BOUNDARY_CORRECTION_READY_FOR_OWNER_REVIEW`다.

1. 모든 fresh·known wheel 그룹의 전체 길이 ≤600초
2. overlap 0
3. 동일 입력 재실행 2회의 결과 SHA 동일
4. 입력 3개의 SHA가 §4와 동일
5. known wheel 검토량 감소 ≥50%
6. 기존 전체 Python 테스트와 wheel focused 테스트 통과
7. DB/R2 read·write 0, VLM 0, temp media 0

하나라도 실패하면 `BOUNDARY_CORRECTION_REJECTED`로 종료한다.

## 6. 사람 게이트와 최종 결정

기계 게이트를 통과해도 자동화를 채택하지 않는다. blind review에는 그룹·clip·대표 여부·라벨링
URL만 표시하고 evidence 점수는 숨긴다.

owner가 다음을 확인한다.

- 다른 행동이 하나라도 같은 그룹에 섞이면 reject
- 서로 다른 중요한 wheel interaction이 대표에서 하나라도 사라지면 reject
- 모호해서 확신하기 어려운 그룹이 있어도 reject

전부 통과할 때만 제한 canary를 별도 승인할 수 있다. reject면 추가 threshold/ROI 튜닝 없이
자동 중복 묶기를 폐기하고 기존 수동 검수를 유지한다.

## 7. 안전 경계

- main merge, migration, DB write, R2 write/delete, 배포 금지
- 라벨·GT·triage·세션·activity·VLM·Python Evidence 수정 금지
- 기존 v1 산출물 수정·삭제 금지
- 자동 label/hold/skip 및 UI 반영 금지
- 사람 검수 결과를 에이전트가 추정해 채우기 금지

