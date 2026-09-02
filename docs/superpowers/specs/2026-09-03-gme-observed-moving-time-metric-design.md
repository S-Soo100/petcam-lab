# GME 관측 움직임 시간 지표 v1 설계

> 상태: `REVIEWED_READY_FOR_INTEGRATION / NOT_DEPLOYED`
>
> 승인일: 2026-09-03 KST
>
> 범위: 모든 GME 대상 영상에 관측 움직임 시간과 측정 상태를 기록·조회

> 구현 메모: `fn_get_gme_observed_moving_time_v1`과 라벨링 웹의 GT 잠금 후 표시 계약을
> 구현했고 Python 1,572개·웹 980개 전체 회귀, TypeScript, 일회용 PostgreSQL 15의 migration
> runtime·권한·rollback·residue 0 검사를 통과했다. production migration 적용,
> `GME_ACTIVE_DETECTOR_IDENTITY` 운영 설정, Preview canary, 배포는 수행하지 않았다.

## 1. 결정

개체의 활동을 하나의 합성 점수로 만들지 않는다. 다음 두 값을 독립 지표로 유지한다.

1. **관측 움직임 시간**: 한 마리 이상 게코가 화면에서 실제로 움직인 시간의 합집합
2. **관측 이동 거리**: 추적된 개체가 이동한 누적 거리

이번 단계에서는 관측 움직임 시간만 정식 지표로 연결한다. 이동 거리는 tracker 안정성과
몸길이 정규화가 검증된 뒤 별도 버전으로 설계한다.

## 2. 사용자 체험

- **[화면]** 사용자는 영상 목록이나 상세 화면에서 `확인된 움직임 18.4초`처럼 이해하기 쉬운 값을 본다.
- **[조작]** 사용자가 영상을 열면 활동 구간과 전체 영상 길이를 함께 확인할 수 있다.
- **[반응]** 게코가 보이지 않았거나 분석이 끝나지 않은 영상에는 임의의 `0초` 대신 측정 상태가 표시된다.
- **[감정]** 사용자는 `0초`가 오류나 미탐이 아니라 실제로 관측된 정지라는 점을 신뢰할 수 있다.

사람 blind 라벨링에서는 최초 판정 전에 이 지표를 숨겨 기존 GT 독립성을 유지한다. 지표는 기록되지만
라벨러의 최초 정답을 유도하지 않는다.

## 3. 지표 의미

### 3.1 대표값

외부 이름은 `관측 움직임 시간`이며 단위는 초다. 내부 계산은 현재 GME의
`candidate_moving_sec_any_gecko`를 사용한다.

- 한 마리 이상 움직인 실제 시계 시간의 합집합이다.
- 두 마리가 동시에 10초 움직여도 대표값은 10초다.
- 개체별 시간 합계인 `moving_gecko_seconds`와 섞지 않는다.
- 보이지 않는 시간이나 `unknown`, `camera_motion` 구간을 움직임 0초로 강등하지 않는다.
- 의료·건강 상태를 진단하거나 행동명을 확정하는 값이 아니다.

사용자 문구는 `총 활동량`보다 `영상에서 확인된 움직임`을 사용한다. 화면 밖이나 은신처 안의 움직임까지
측정했다는 오해를 막기 위해서다.

### 3.2 측정 상태

모든 GME 대상 영상은 숫자와 별개로 다음 상태 중 하나를 가진다.

| 상태 | 숫자 노출 | 의미 |
|---|---:|---|
| `measured` | O | 정상 run에서 게코가 한 번 이상 관측돼 시간을 계산함 |
| `not_observed` | X | 정상 분석은 끝났지만 게코가 관측되지 않아 측정 불가 |
| `pending` | X | 현재 detector identity의 분석이 대기 또는 처리 중 |
| `failed` | X | 현재 detector identity의 분석이 실패함 |

`0초`는 `measured`이면서 `visible_sec > 0`이고 관측 움직임이 없을 때만 허용한다. 게코 미관측,
디코딩 실패, 모델 실패, 아직 처리하지 않은 영상에는 0을 쓰지 않는다.

`visible_sec`, `unknown_sec`, `camera_motion_sec`, `state_intervals`, `tracking_quality`는 대표 숫자의
근거와 품질 감사에 계속 보존한다.

## 4. 정본과 조회 계약

### 4.1 정본

새 숫자를 `motion_clips`에 복사하지 않는다. 기존 append-only 원장을 그대로 정본으로 사용한다.

```text
motion_clips
  └─ gme_jobs (detector identity별 상태와 result_run_id)
       └─ gme_runs (움직인 시간·관측 시간·상태 구간·provenance)
```

이 방식은 v2.6 뒤에 v2.7을 다시 실행해도 과거 계산과 새 계산을 모두 재현한다. `motion_clips`에 최신
숫자를 덮어쓰면 모델 교체 시 값의 출처가 사라지므로 금지한다.

### 4.2 현재값 해석

API는 호출자가 지정한 active detector identity에 대해서만 현재 상태를 해석한다.

- 성공한 `gme_jobs.result_run_id`와 exact `gme_runs`를 연결한다.
- 다른 detector identity의 과거 성공값으로 조용히 대체하지 않는다.
- 재분석은 새 run을 append하고 기존 run을 수정하지 않는다.
- 반환값에는 최소한 `run_id`, `detector_identity`, `measurement_status`, `moving_time_sec`,
  `visible_sec`, `unknown_sec`, `camera_motion_sec`를 포함한다.
- 기존 소비자를 깨지 않도록 기존 조회 계약을 덮어쓰기보다 versioned RPC/view를 추가한다.

`moving_time_sec`는 `measurement_status = measured`일 때만 숫자다. 나머지 상태에서는 `null`이다.

## 5. 모든 영상 적용 범위

대상은 보존 중인 GME eligible 영상 전체와 앞으로 들어오는 live 영상이다.

- 진행 중인 v2.6 과거 영상 backfill을 삭제·초기화·재실행하지 않는다.
- 완료된 v2.6 run은 그대로 사용한다.
- 대기 중인 과거 영상은 현재 queue가 순차 처리한다.
- 새 live 영상은 기존 우선순위 계약대로 과거 backfill보다 먼저 처리한다.
- 원본 부재·명시적 시스템 제외·삭제 완료 영상은 eligible 모수와 섞지 않는다.

모든 eligible 영상은 최소한 `pending / measured / not_observed / failed` 중 하나로 조회돼야 한다.

## 6. 제품 활용

### 6.1 라벨링 웹

- 최초 blind 판정 전에는 움직임 시간을 숨긴다.
- 판정 뒤 검수 화면과 일반 영상 화면에는 `확인된 움직임 N초` 또는 측정 상태를 표시할 수 있다.
- 날짜가 같은 영상의 내부 우선순위에는 관측 움직임 시간을 사용할 수 있다.
- 낮은 값이나 측정 불가를 자동 제외 근거로 사용하지 않는다.

### 6.2 하이라이트와 VLM

- 움직임 시간은 하이라이트 후보 순위를 정하는 하나의 신호다.
- 움직임 시작 전·활동 구간·종료 뒤 프레임을 VLM 입력 준비에 사용할 수 있다.
- 물 마시기·먹기처럼 이동이 적은 중요한 행동을 낮은 활동량만으로 탈락시키지 않는다.
- GME 숫자는 행동 GT나 VLM 정답이 아니다.

### 6.3 앱

앱 노출은 API 계약과 운영 검증 뒤 별도 단계로 진행한다. 초기 문구는 다음 네 가지로 제한한다.

- `확인된 움직임 18.4초`
- `확인된 움직임 0초`
- `게코 미관측 · 측정 불가`
- `GME 분석 대기 중` 또는 `GME 분석 실패`

## 7. 이동 거리 후속 지표 경계

이동 거리는 이번 구현 범위가 아니다. 다음 조건을 만족한 별도 설계에서만 추가한다.

- bbox 중심의 단순 픽셀 합이 아니라 추적 ID별 경로를 사용한다.
- 카메라 해상도와 원근 차이를 줄이기 위해 `몸길이 대비 이동 거리`를 우선 검토한다.
- bbox 흔들림, 반사상, 중복 검출, ID switch, 가림 구간을 거리로 누적하지 않는다.
- tracker 품질과 사람 검수 표본으로 오차를 먼저 측정한다.
- 움직임 시간과 이동 거리를 합쳐 근거 없는 단일 활동 점수를 만들지 않는다.

## 8. 오류 처리와 안전 경계

- 현재 identity의 job이 실패하면 `failed`를 반환하고 과거 모델 값을 현재값처럼 노출하지 않는다.
- run의 `candidate_moving_sec_any_gecko > visible_sec` 같은 불변식 위반은 저장 단계에서 거부한다.
- `unknown`과 `camera_motion`은 움직임 0으로 변환하지 않는다.
- 분석 실패가 생겨도 원본 영상, 사람 GT, 과거 GME run을 삭제하거나 덮어쓰지 않는다.
- 이 지표로 영상 삭제, 자동 skip, 행동 확정, production 모델 자동 승격을 수행하지 않는다.

## 9. 검증

### 9.1 계약 테스트

- `measured + visible_sec > 0 + moving=0`만 숫자 0을 반환한다.
- 게코 미관측·대기·실패는 `moving_time_sec = null`이다.
- active detector identity가 다르면 과거 모델 값을 현재값으로 반환하지 않는다.
- job과 result run의 identity·run id·status가 정확히 연결돼야 한다.
- blind 라벨 제출 전 API와 화면에 지표가 노출되지 않는다.

### 9.2 운영 canary

- 게코가 움직인 영상, 보이지만 정지한 영상, 미관측 영상, pending, failed 표본을 각각 확인한다.
- API 값과 원본 `gme_runs`를 독립 재계산해 일치시킨다.
- live 우선 처리와 과거 backfill 진행률이 기존 계약을 유지하는지 확인한다.
- DB/R2 원본·사람 GT·production 모델에는 부수 변경이 없어야 한다.

### 9.3 완료 기준

1. 모든 eligible 영상이 정확히 하나의 현재 측정 상태로 조회된다.
2. `0초`와 `측정 불가`가 혼동되지 않는다.
3. 숫자마다 exact run과 detector provenance를 추적할 수 있다.
4. 기존 v2.6 backfill을 재시작하지 않고 완료된 run을 재사용한다.
5. 새 live 영상이 같은 계약으로 자동 기록된다.
6. 최초 blind 사람 판정과 GME prediction의 분리가 유지된다.

## 10. 구현 순서

1. versioned 조회 계약과 상태 매핑 테스트를 먼저 작성한다.
2. DB migration으로 service-role 전용 RPC/view를 추가한다.
3. backend API에 숫자와 상태를 함께 연결한다.
4. 라벨링 웹의 판정 후 화면에서 문구와 상태를 canary 검증한다.
5. 과거 v2.6 backfill과 live 처리 coverage를 read-only로 감사한다.
6. 앱 노출은 별도 승인과 canary 뒤 진행한다.
7. 이동 거리 지표는 별도 사람 표본 검증 설계로 분리한다.
