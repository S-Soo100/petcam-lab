# 데이터 가용성 진단 — local-vlm-evidence-analyst (Task 7)

> **판정: `BLOCKED_DATA_INSUFFICIENT`** (design §6 / verdict §11-2)
>
> SELECT-only 진단만 수행. DB write·모델 출력·GT 생성 0. TEST-SHEET 상태는 `DRAFT_PLAN_REVIEW`
> 유지(→`PRE_REGISTERED` flip 금지 — owner blind evidence GT 미완료).

## 방법

`scripts/probe_local_vlm_evidence_availability.py` (SELECT only) 로 `behavior_logs(source=human)`
× `camera_clips` × `clip_prelabels` 를 읽어 candidate pool 을 측정. 원본 수치는
`data-availability.json`. 실행 host = `BaekBook-Pro-14-M5.local`(구현 host, DB SELECT only).

## 측정 결과 (읽기 전용)

- 사람 행동 GT clip: **237** (전부 camera_clips 매칭, camera_meta 누락 0)
- 카메라 다양성: **3** (≥2 ✅) · 촬영일 다양성: **29** (≥3 ✅)
- GT clip 중 Gate prelabel 보유: **0** (라벨 GT set 과 Gate prelabel set 은 분리된 id 공간)

### strata candidate pool (행동 GT → evidence strata 대략 매핑, 30분 episode dedup)

| strata | GT pool | dedup episodes | 목표 | 충족 |
|---|---:|---:|---:|:--:|
| absent | 2 | **2** | 30 | ❌ |
| big_move | 93 | 39 | 30 | ✅ |
| rest_micro | 0 | **0** | 30 | ❌ |
| lick_water_food | 97 | **28** | 30 | ❌ |
| wheel_object | 0 | **0** | 30 | ❌ |
| hardcase | 45 | **3** | 30 | ❌ |

**6개 strata 중 1개(big_move)만 30 episode 목표 충족.**

## 왜 blocked 인가 (3중 결손)

1. **strata 표본 부족** — 5/6 strata 가 30 episode 미달. `rest_micro`·`wheel_object` 는 대응
   행동 라벨 자체가 0. `absent` 2, `hardcase` 3(shedding 이 소수 30분 창에 군집), `lick_water_food`
   28. design §6 "특정 strata 부족 시 다른 class 로 대체 금지" → 대체하지 않고 blocked 로 기록.
2. **evidence-축 GT 부재** — `behavior_logs` 는 `action`(행동 class)만 갖는다. design §6.3 이 요구하는
   `presence_observation·visibility·motion_extent·body_region·object` 5축 사람 GT 는 **0건**.
   행동 라벨에서 이 축을 추측으로 채우는 것은 계약 위반(§6.3, [[selection-bias-error-only-tagging]] 결).
   → 필요한 사람 evidence GT: **180행(전부 신규)**. 현재 0/180.
3. **holdout blind GT 미완료** — holdout 60 은 모델 출력을 보기 전 owner 가 blind 로 확정해야 한다
   (이번 세션 범위 밖, 사람 작업). model/prompt freeze 이전 완료 조건.

## owner 가 해야 할 일 (runtime 이전)

1. `rest_micro`·`wheel_object` 표본을 새로 수집하거나, 6-strata 설계를 데이터 현실에 맞게 재조정
   (design SOT 갱신 먼저). `bowl 위치 급여마다 변동`([[project_bowl_position_not_static]]) 처럼
   가정이 데이터와 어긋나면 strata 정의부터 수정.
2. 180개 evidence GT worksheet 를 blind 로 작성(5축). dev 120 은 기존 행동 GT 를 strata 구성에만
   재사용 가능하나 evidence 축 값은 별도 관찰로 채운다.
3. manifest 확정 후 `scripts/validate_local_vlm_evidence_manifest.py` 로 계약 검증 → 통과 시
   TEST-SHEET `PRE_REGISTERED` commit.

## 재현

```bash
cd /Users/baek/petcam-lab
uv run python scripts/probe_local_vlm_evidence_availability.py \
  --out experiments/local-vlm-evidence-analyst/data-availability.json
```

## 상태 요약

- 구현(Task 1~6)·검증 코드: 완료·테스트 통과.
- 표본/GT: **BLOCKED_DATA_INSUFFICIENT**. 필요한 사람 evidence GT = 180행(현재 0).
- manifest.json: **생성하지 않음**(유효한 180 표본 불가, 위조 금지 — design §6 fail path 준수).
