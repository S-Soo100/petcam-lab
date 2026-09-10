# YOLO26n v2.6 C500G holdout clip-unit addendum

> 상태: `OWNER_REVIEW_PENDING / EXECUTION_BLOCKED`
>
> 범위: v2.6 sealed holdout의 `300 clip` 평가 단위만 고정한다. source inventory,
> role freeze, window 추출, 사람 검수, 추론, 학습은 아직 실행하지 않는다.

## 결정

v2.6 sealed holdout의 300 clip은 30분 원본 자체가 아니라, freeze 뒤 첫 3개 complete
camera-night에서 결정론적으로 예약한 60초 evaluation window를 뜻한다. 이 정의는
`c500g-v26-holdout-window-v1`이며, role·window 선택·사람 검수에 prediction을 쓰지 않는다.

```yaml
schema: c500g-v26-holdout-window-v1
source_role: first_3_post_freeze_complete_camera_nights
window_duration_sec: 60
window_alignment: non_overlapping_from_30min_slot_start
selection: sha256_rank_prediction_independent
windows_per_camera_night: 100
total_windows: 300
bbox_frame_offsets_sec: [12, 24, 36, 48]
total_bbox_frames: 1200
clip_presence_review: full_60sec_blind_human
model_input: frozen_v26_full_frame_10fps
group_boundary: camera_night_and_30min_source_sha
reuse_after_open: forbidden
```

## 파생 좌표와 누수 경계

30분 원본은 자르거나 다시 쓰지 않는다. 각 60초 window는 오직
`(source_sha, start_ms, end_ms)` 파생 좌표로 정의한다. `start_ms`는 해당 30분 slot 시작점에서
non-overlapping 60초 경계에 맞추고, `end_ms = start_ms + 60000`으로 정한다.

각 complete camera-night에서 SHA-256 rank로 100개 window를 prediction-independent하게 고른다.
3개 camera-night의 300개 window마다 12, 24, 36, 48초의 bbox frame을 review하므로 총
1,200 bbox frame이다. clip presence는 선택 frame만으로 대체하지 않고 full 60sec blind human
review로 확정한다.

`camera-night`와 30분 `source_sha`는 같은 group boundary다. 같은 group의 원본, window,
파생 frame, crop, near duplicate는 holdout 밖 역할에 두지 않는다. sealed holdout을 open한 뒤에는
어떤 원천도 train, validation, pilot, hard-case ranking에 reuse하지 않는다.

## 실행 전제와 Owner gate

metadata-only role freeze가 pixel 접근보다 먼저 끝나야 한다. eligible complete camera-night가
3개보다 적으면 pre-freeze 원천으로 채우지 않고 `V26_HOLDOUT_SHORTAGE`로 멈춘다. 이 addendum은
holdout source를 열거나 추출하도록 승인하지 않는다.

Owner가 이 addendum과 TEST-SHEET을 함께 승인하기 전에는 Task 1 이후 작업으로 넘어가지 않는다.
승인 직후 두 파일의 SHA-256을 계산해 이후 runtime manifest에 각각 독립 field로 기록하고, 모든
후속 CLI는 승인된 TEST-SHEET SHA-256을 입력 pin으로 검증해야 한다.
