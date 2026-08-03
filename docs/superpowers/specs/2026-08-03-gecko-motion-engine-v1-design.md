# Gecko Motion Engine v1 설계

> 상태: `OWNER_APPROVED / PRODUCTION_SHADOW_DIRECT_CUTOVER_APPROVED`
> 승인일: 2026-08-03 KST
> 이름: **Gecko Motion Engine(GME, 게코 움직임 측정 엔진)**
> 후속 승인: 신규 영상 전수 shadow + KST 2026-07-15 이후 eligible 기존 영상 backfill을 같은 날
> 직접 전환한다. 기존 Python Evidence는 GME operational smoke 통과 직후 신규 enqueue부터 중단하고
> historical archive로 보존한다.

## 1. 한 줄 결정

기존 `Python Evidence`의 신규 이름과 역할을 **Gecko Motion Engine**으로 확정한다. GME는
모든 영상을 최대 30fps로 분석하면서 Gecko Vision Gate를 계속 업그레이드해 사용하고, 게코
검출·개체 추적·노이즈 제거를 거쳐 **게코가 실제로 움직인 시간**을 측정한다.

기존 `Python Evidence` 이름은 과거 DB provenance, experiment, report의 역사 식별자에서만
보존한다. 과거 기록을 소급 개명하지 않는다.

## 2. 제품 지표 정의

검증 전 production shadow 출력은 `candidate_moving_sec_any_gecko`다. 사람 시간구간 GT와 독립
future holdout을 통과한 뒤 사용자 대표 지표 `verified_moving_sec_any_gecko`로 승격한다. 한 마리
이상이 실제로 움직인 시간의
합집합을 초 단위로 계산한다. 두 마리가 같은 10초 동안 동시에 움직여도 사용자 활동시간은
10초다. 내부 연구 지표로는 개체별 움직임 시간을 더한 `moving_gecko_seconds`도 별도로 둔다.

프레임·시간 구간 상태는 다섯 가지다.

| 상태 | 의미 | 사용자 활동시간 |
|---|---|---|
| `moving` | 게코 몸의 실제 위치·자세 변화가 확인됨 | 포함 |
| `static` | 게코가 보이지만 움직임이 확인되지 않음 | 제외 |
| `not_visible` | 게코가 화면에 보이지 않음 | 제외, 별도 시간 기록 |
| `unknown` | 가림·검출 실패·노이즈로 판단할 수 없음 | 0으로 만들지 않고 미측정 기록 |
| `camera_motion` | 카메라나 화면 전체 변화가 지배적임 | 제외, 품질 문제로 기록 |

사용자 결과는 `확인된 활동시간`, `관찰 가능 시간`, `판단 불가 시간`을 함께 표시해야 한다.
현재 production `activity-v1`의 clip-duration 기반 `effective_activity_sec`는 이 정의와 다르므로
`legacy estimated activity`로 취급하고 GME가 검증되기 전 교체하지 않는다.

## 3. 시스템 경계

```text
RBA
└─ Gecko Motion Engine
   ├─ Media QA: decode·FPS·밝기·동결·카메라·IR 변화
   ├─ Gecko Vision Gate: bbox/mask/confidence
   ├─ Multi-gecko Tracker: 프레임 간 동일 개체 연결
   ├─ Motion Normalizer: 흔들림·노출·IR·카메라별 크기 보정
   ├─ Provenance Splitter: observed/tracked/interpolated/unknown
   ├─ State Estimator: moving/static/not_visible/unknown/camera_motion
   └─ Time Aggregator: any-gecko seconds + gecko-seconds + tracking quality
```

GME는 행동명, 물 마시기, 먹이 섭취, 하이라이트를 확정하지 않는다. VLM 호출 여부를 결정하거나
영상을 자동 skip하지도 않는다. 모든 영상은 별도 VLM 정책에 따라 분석될 수 있고 GME는 위치·시간·
품질·재현 provenance를 공급한다.

## 4. 처리 계약

1. 한 영상은 **한 번만** 끝까지 순차 디코딩한다. 같은 프레임 스트림을 Gate, tracker, media QA,
   motion normalizer가 공유하고 전체 프레임 배열은 메모리에 쌓지 않는다.
2. 원본이 30fps 이하면 모든 프레임을 분석한다. 30fps를 넘으면 모두 디코딩하되 분석 시계는 최대
   30fps로 정규화한다.
3. Gate detector는 shadow v0에서 0.5초마다 anchor detection을 수행하고, tracker confidence가
   하락하면 다음 주기를 기다리지 않고 즉시 재검출한다. tracker와 motion 계산은 모든 분석 프레임을
   소비한다.
4. detector 구현은 교체 가능해야 하며 출력 계약은 `timestamp`, `bbox 또는 mask`, `confidence`,
   `model/checkpoint/schema version`으로 제한한다. 논문 결과만으로 YOLOv8 등 특정 모델을 채택하지 않는다.
5. bbox 또는 mask를 프레임 간 연결해 trajectory를 만든다. 여러 마리는 내부 track id로 분리하되
   identity가 끊기면 억지로 같은 개체로 합치지 않는다.
6. 각 위치점의 출처를 `observed`, `tracked`, `interpolated`, `unknown`으로 구분한다. detector가 직접
   확인한 값만 `observed`다. tracker가 이어간 값과 앞뒤 보정값을 실제 관측처럼 저장하지 않는다.
7. offline clip이므로 짧은 양방향 보정은 허용하지만 detector anchor 두 칸에 해당하는 **1.0초 이하**
   gap만 `interpolated`로 메운다. 그보다 긴 gap, 가림, 신뢰도 부족은 `unknown`이다.
8. global motion, timestamp 영역, 그림자, 노출 변화, IR 모드 전환, codec 반복을 게코 자체 움직임과
   분리한다.
9. 카메라 거리·해상도 차이는 bbox/mask에서 추정한 몸길이와 영상 정규화 좌표를 함께 기록해 보정한다.
   향후 카메라별 polygon을 붙여 은신처·물그릇·먹이·온열 영역 체류를 재계산할 수 있게 하되, shadow
   v0에서는 영역 체류를 행동명으로 바꾸지 않는다.
10. 상태 구간과 함께 track fragmentation, ID switch 후보, detection gap, 위치 급변, provenance별
    시간, multi-gecko 분리율을 tracking quality로 저장한다.
11. 상태 구간을 합쳐 any-gecko 활동시간과 내부 gecko-seconds를 각각 만든다.

## 5. Gecko Vision Gate 운영 원칙

과거 Gate v2 recall reject는 Gate 연구 중단 사유가 아니라 현재 모델을 자동 제외에 쓰지 못한다는
증거다. Gate v3와 이후 모델을 계속 학습·교체하되 다음 계약을 지킨다.

- checkpoint마다 별도 version과 future holdout 성적을 가진다.
- RF-DETR, YOLO, segmentation 등 모델 종류와 무관하게 동일한 detector output 계약을 지킨다.
- 검출 실패를 `not_visible`이나 `static`으로 바꾸지 않고 `unknown`으로 둔다.
- 사람 bbox/mask 교정을 hard-case 학습자료로 append-only 보존한다.
- 새 camera, morph, enclosure, IR, occlusion, multi-gecko strata를 각각 평가한다.
- production 채택 전에는 shadow 계산만 하고 사용자 활동시간과 기존 값을 바꾸지 않는다.
- Gate 결과만으로 VLM skip, 원본 삭제, 행동 GT 확정을 하지 않는다.

별도 prescan 연구가 미래에 `verified_absent` 조건부 VLM 생략을 다시 제안하더라도, 독립 TEST-SHEET와
owner adoption gate를 통과하기 전에는 적용하지 않는다. 그런 외부 routing 결정은 GME의 측정 계약을
바꾸지 않는다.

## 6. 단계별 연구

### 1단계 — direct-cutover 구현·operational smoke

세 레포(`petcam-lab`, `gecko-vision-gate`, `petcam-nightly-reporter`)에 GME core, durable queue,
append-only 원장, Mac mini worker를 구현한다. 실제 영상 10개에서 `10/10 complete`, 재실행 멱등,
임시파일 0, 허용된 GME DB/R2 prefix 외 write 0을 확인한다. 정확도 채택 시험이 아니라 같은 날
숨은 shadow로 안전하게 전환하기 위한 operational smoke다.

### 2단계 — 신규 전수 shadow + 기존 Python Evidence 직접 교체

smoke 통과 직후 Python Evidence 신규 enqueue를 먼저 중단하고 진행 중 job 0을 확인한 뒤 해당
LaunchAgent를 unload한다. 기존 table/run/code는 수정·삭제하지 않고 historical archive로 보존한다.
동시에 GME 신규 trigger와 Mac mini worker를 활성화해 이후 모든 재생 가능한 신규 `motion_clips`를
shadow 처리한다. 24시간 병행은 하지 않는다.

### 3단계 — 2026-07-15 이후 eligible backfill

신규 live job을 항상 우선하면서 KST 2026-07-15 이후 정상·재생 가능 영상을 멱등 enqueue한다.
`research quarantine`, `media_deleted`, `source_missing`, R2 preflight 실패 영상은 제외한다. live lag
p95가 15분을 넘으면 backfill claim만 자동 중단하고 live queue는 계속 처리한다.

### 4단계 — 사람 GT baseline·사용자 지표 채택 평가

사람이 `moving/static/not_visible/unknown/camera_motion` 시간구간과 bbox/mask를 표시한 표본으로
camera/morph/IR/occlusion/multi-gecko별 검출·추적·활동시간 오차를 측정한다. train/validation/test는
프레임 랜덤 분할이 아니라 camera+animal+enclosure+video 단위로 분리한다. 독립 future holdout
TEST-SHEET의 허용 오차와 unknown 기준을 통과한 뒤에만
`verified gecko moving time`을 사용자 대표 활동시간으로 교체한다. 통과하지 못하면 shadow와
hard-case 학습을 계속한다.

## 7. 저장 계약

- **DB 영구:** `gme_jobs`, append-only `gme_runs`, 영상별 candidate 활동시간, 상태 구간, 게코 수,
  tracking quality, detector/tracker/GME provenance, R2 artifact identity를 저장한다.
- **R2 영구:** 압축 trajectory, 상태 전환, 문제구간 요약을 GME 전용 prefix에 저장한다.
- **R2 14일:** 프레임별 상세 판정과 debug bundle을 별도 lifecycle prefix에 저장한다. `unknown`, track
  단절, camera motion 같은 hard case만 장기 영역으로 승격할 수 있다.
- **원본 영상:** 기존 R2 경로를 변경·삭제하지 않는다. 개선된 GME는 원본으로 다시 계산한다.
- **금지:** 프레임별 결과를 DB row로 영구 폭증시키거나 debug artifact lifecycle이 원본 영상에
  적용되게 하지 않는다.

## 8. production shadow 운영 경계

이번 owner 승인은 GME 전용 DB migration, R2 derived artifact write, Mac mini GME LaunchAgent,
Python Evidence enqueue/LaunchAgent의 가역 중단까지 포함한다. 다음은 포함하지 않는다.

- Flutter/API 사용자 값과 기존 `activity-v1` 변경
- 사람 GT·행동 라벨·하이라이트·VLM route 변경
- Gate checkpoint의 성능 승인 없는 교체·학습
- 과거 `Python Evidence` artifact의 소급 개명
- 자동 skip·행동 라벨·하이라이트·원본 삭제

GME 실패는 capture, R2 upload, 앱, VLM을 막지 않는다. job 단위 allowlist failure와 retry/backoff로
격리한다. 심각한 operational 실패 시 GME 신규 enqueue를 중단하고 보존한 Python Evidence trigger와
LaunchAgent를 다시 켤 수 있는 rollback을 유지한다.

## 9. 성공 기준

- 현재 정본 문서가 GME 이름과 `게코가 실제로 움직인 시간` 정의에 일치한다.
- 과거 `Python Evidence`는 historical provenance로만 설명된다.
- `media preparation only`라는 축소 정의가 현재 지시로 남지 않는다.
- Gate는 계속 업그레이드하는 핵심 센서이되 자동 skip 근거가 아님을 명시한다.
- direct-cutover smoke가 10/10 complete, 멱등, temp 0, 원본·GT·앱 write 0을 통과한다.
- 신규 job coverage 100%, live lag p95 15분 이내, terminal failure 1% 미만, capture 영향 0이다.
- 관측 출처와 track fragmentation, ID switch 후보, detection gap, 위치 급변, unknown 비율을 재현할
  수 있다.
- MacBook과 Mac mini가 같은 commit의 SOT를 읽고, Mac mini GME runtime HEAD·service·실제 run
  증거가 일치한다.
