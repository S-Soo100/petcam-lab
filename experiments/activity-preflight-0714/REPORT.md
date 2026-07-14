# REPORT — 활동필터 v0 사람 preflight (activity-preflight-0714)

> 실행 2026-07-14. TEST-SHEET 대비 사후 변경 없음. decision: **두 스위치 모두 reject**.
> 카메라 A blind 30 clip, 사람 동영상 판단 vs detector(Gate v2 EMA, thr 0.25, policy activity-v0).

## 1. 결과 표

| 지표 | 값 | 합격기준 | 판정 |
|---|---|---|---|
| false exclusion → exclude_absent | **10건** | 0 | ❌ |
| false exclusion → exclude_static | **1건** | 0 | ❌ |
| exclude_absent precision | **0%** (0/10) | ≥90% | ❌ |
| exclude_static precision | 90% (9/10) | ≥90% | ⚠️(false excl 때문에 무의미) |
| active recall(참고) | 39% (7/18) | — | 낮음 |

분포: detector {exclude_absent 10, exclude_static 10, active 10} · 사람 {static 12, active 18, **absent 0**}.

## 2. 시험지 대비
- sample 목표 absent/static/active = 10/10/10 **달성**(85 clip 스캔). 사후 변경 없음.
- 단 사람 판단 결과 **absent 0건** — detector 가 absent 로 뽑은 10개를 사람은 전부 active(9)/… 로 봄.

## 3. 가설 판정
- **H1 기각, H0 유지.** 사람=active 를 detector 가 exclude 로 판정한 경우가 11건(absent 10 + static 1).
  fail-open 이 지켜지지 않아 활동시간을 잘못 깎는다.

## 4. decision label
- **exclude_absent 스위치 = `reject`** (Phase 5 활성화 금지).
- **exclude_static 스위치 = `reject`** (Phase 5 활성화 금지).
- 결과적으로 카메라 A 는 두 스위치 모두 비활성 유지 → 앱 활동시간은 raw(현행) 유지.

## 5. discordant 분석 (근본 원인)

### (A) exclude_absent 전멸 — detector FN (게코 검출 실패) 10/10
`no_gecko_detected`(vr=0.0 = 12프레임 전부 gecko 미검출)한 10개를 사람은 전부 **active**로 판단.
→ **RF-DETR v2 가 이 clip 들에서 게코를 아예 못 잡음.** glob 1.1~1.6(움직임 있음)인데도 bbox 0.
- 이것은 policy/임계값 문제가 아니라 **detector recall 문제**. threshold 를 낮춰도 bbox 자체가 0이라 회복 불가.
- gate-v3.md 경고("petcam backlog specificity 40%, FN 후보")와 §435 금지("gecko_visible=false 무조건 제외 금지")가 실증됨.
- **exclude_absent 는 Gate detector recall 이 사람 GT 로 검증되기 전까지 절대 켜면 안 된다.**

### (B) exclude_static — 미세 움직임 1건 놓침
`7cebd236`: vr=0.92(게코 잘 보임), disp=0.0028, iou=0.94, flow=0.525 → 수치상 거의 정지인데 사람은 active.
미세 혀·머리 움직임이 roi_flow(임계 2.0) 아래라 static 으로 판정. exclude_static 은 검출은 되지만
**미세 활동 민감도가 부족**해 활동 clip 1건을 정지로 오판.

### (C) 반대 방향(무해): static→active 과탐 3건
`ef5c8bd5·9404fb88·cd53ee20`: 사람 static 인데 detector active (iou 0.80~0.84 < move_iou_max 0.85).
detection bbox 노이즈로 active 과탐. **활동시간 포함 방향이라 무해**(false exclusion 아님)지만
move_iou_max 가 bbox 지터에 민감함을 시사.

## 6. 한계·노이즈
- 30 clip 단일 카메라·단일 판단자(owner) blind. 통계적 표본은 작음.
- 그러나 exclude_absent 10/10 실패는 명백한 신호(우연 아님) — detector FN 이 지배적.

## 7. 다음 액션
1. **Phase 5 제한적 활성화 취소** — 두 스위치 다 켜지 않는다. 앱 활동시간 raw 유지(변화 없음).
2. **evidence 축적은 계속** — worker shadow 저장으로 clip_prelabels/assessments 데이터 확보(FN 사례가 Gate v3 재학습 골드).
3. **exclude_absent 재도전 전제** = Gate detector recall 을 사람 GT 로 재검증(gate-v3 재학습). v0 범위 밖.
4. **exclude_static 재도전 전제** = 미세 움직임 민감도(roi_flow/추가 신호) 튜닝 후 재-preflight. 단 (A)가 더 큰 병목.
5. 이번 FN 10건 clip_id 를 Gate hardcase 후보로 gecko-vision-gate 에 기록(별도).

**결론:** v0 파이프라인(Gate evidence + four-state + worker + DB view)은 완성·검증됐고, **preflight 안전장치가
제 역할을 해서 detector 품질 부족으로 인한 잘못된 활동시간 삭감을 사전 차단**했다. 현재 Gate v2 로는
어느 스위치도 안전하지 않다 → 활성화 보류, detector 개선이 선결.
