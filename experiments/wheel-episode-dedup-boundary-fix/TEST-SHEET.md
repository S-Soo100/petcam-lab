# TEST-SHEET — 쳇바퀴 에피소드 10분 경계 교정 (v1.1 boundary-fix)

> 🔒 **실행 전 동결 (pre-registration). 사후 변경 금지.**
> 성격: 새 연구가 아니라 v1 shadow 의 chaining 결함을 **1회 교정하는 salvage**.
> 설계 정본(SOT): [`docs/superpowers/specs/2026-07-23-wheel-episode-boundary-correction-design.md`](../../docs/superpowers/specs/2026-07-23-wheel-episode-boundary-correction-design.md)
> 계획: [`docs/superpowers/plans/2026-07-23-wheel-episode-boundary-correction.md`](../../docs/superpowers/plans/2026-07-23-wheel-episode-boundary-correction.md)
> 기준 branch: `feat/wheel-episode-dedup-shadow @ 898278ff57aab089b46d2fbb616df479212820c4`

---

## 1. 가설

- **H0 (귀무):** run 분리에 `이전 clip 간격`과 `run 전체 길이`를 함께 강제해도, v1 결함(전체 길이 10분 초과 chaining)을 없애면서 known wheel 검토량 ≥50% 감소를 유지하지 못한다.
- **H1 (대립):** 두 시간 경계 분리로 모든 그룹 전체 길이 ≤600초를 보장하면서 known wheel 검토량 감소 ≥50%, overlap 0, 결정론 100% 를 만족한다.

산출물은 owner 전수 blind 감사에 넘길 후보이며, 기계 게이트만 자체 검증한다. 채택은 사람 게이트 이후.

---

## 2. 동결 파라미터 (전문)

```text
algorithm_version=wheel-episode-dedup-shadow-v1.1-boundary-fix
max_inter_clip_gap_sec=600
max_episode_span_sec=600
wheel_motion_floor=0.01
hamming_threshold=7
motion_tolerance=0.02
novelty_min_hamming=6
evidence_audit_sha256=23789fa8ea430c4dc24b015847c360a6afa72565c897c3d4b7b8654702a508e3
frozen_cohort_sha256=b67b32f27259d132cda5861f8126f6b48f4bb704528c0458ebbf63a95d17f953
roi_profile_sha256=653e64c25e057339ce9a1844d27c570ce99916d20986023fafdabd84935c7825
```

600초는 정확히 포함하고 600초 초과만 분리한다. `current - previous > max_inter_clip_gap_sec` **또는** `current - run_start > max_episode_span_sec` 이면 새 run 을 시작한다.

---

## 3. 입력 · 재실행 방식

- R2 영상·production DB 를 다시 읽지 않는다. **커밋된 v1 signature replay 전용.**
- 입력: `experiments/wheel-episode-dedup-shadow/{EVIDENCE-AUDIT.json, frozen-cohort.json, wheel-roi-profile-v1.json}` (§2 SHA 로 고정).
- 저장된 `fresh`·`known_wheel` signature 를 명시 필드로 복원해 교정된 grouping 만 수행.
- 새 결과는 `experiments/wheel-episode-dedup-boundary-fix/` 에만 쓴다. 기존 v1 산출물은 읽기만 한다.

---

## 4. 측정 지표

| 지표 | 정의 |
|---|---|
| 그룹 span | `started_at_last − started_at_first` (초) |
| span 위반 수 | span > 600 인 그룹 수 |
| overlap | 한 clip 이 2 그룹 이상 소속된 건수 |
| 결정론 | 동일 입력 2회 grouping 결과 SHA 일치 |
| known wheel 검토량 감소 | 1 − (대표+미묶음)/24 |
| 교정 전/후 | 그룹·membership·representatives·max span |

---

## 5. 합격 기준 (7개 기계 게이트 — design §5, 숫자, 사후 변경 금지)

1. **모든 fresh·known wheel 그룹 전체 길이 ≤ 600초** (span 위반 = 0)
2. **overlap = 0**
3. **동일 입력 2회 재실행 결과 SHA 동일** (결정론 100%)
4. **입력 3개 SHA 가 §2 와 동일**
5. **known wheel 검토량 감소 ≥ 50%**
6. **기존 전체 Python 테스트 + wheel focused 테스트 통과**
7. **DB/R2 read·write 0, VLM 0, temp media 0**

---

## 6. 예상 비용/토큰

- LLM/VLM 토큰 0. 외부 네트워크 0. DB/R2 0. 순수 stdlib + 기존 pure 모듈 replay. temp media 0.

---

## 7. decision 룰 (사전 명시)

| 결과 | 판정 |
|---|---|
| 7개 기계 게이트 전부 통과 | **`BOUNDARY_CORRECTION_READY_FOR_OWNER_REVIEW`** |
| 하나라도 실패 | **`BOUNDARY_CORRECTION_REJECTED`** |

**사람 게이트(채택 전 필수):** 기계 게이트를 통과해도 자동화를 채택하지 않는다. owner blind 감사에서 (a) 다른 행동이 한 그룹에 섞이거나 (b) 중요한 wheel interaction 대표가 하나라도 사라지거나 (c) 모호한 그룹이 있으면 reject. reject 면 추가 튜닝 없이 자동 중복 묶기를 폐기한다.

`ADOPTED`·`PRODUCTION_READY`·`DEPLOYED`·`VERIFIED_FOR_AUTOMATION` 을 주장하지 않는다. 사람 검수 전 main merge·UI 연결·canary 를 수행하지 않는다.

---

## 8. 이번 교정에서 하지 않는 것 (금지 — design §3·§7)

이번 salvage 는 **경계 로직만** 고친다. 아래는 이번 범위에서 **금지**한다.

- wheel ROI 좌표 유지 — 어떤 **ROI 변경**도 하지 않는다.
- `wheel_motion_floor`·`hamming_threshold`·`motion_tolerance`·`novelty_min_hamming` 유지 — 어떤 **threshold 변경**도 하지 않는다.
- IR/day 판정·anchor·대표 선택 규칙·frozen cohort 유지.
- mode-scoped IR, day 전용 threshold, 모션 정지점 탐색, perceptual 급변 분할 등 후속 v2 연구 금지.
- production DB write · R2 read/write · migration · 배포 · 라벨링 웹 수정 · GT/triage/session/activity/behavior/Python Evidence/VLM 수정 · 자동 label/hold/skip · 기존 v1 산출물 수정·삭제 · owner 판정 대행 금지.
