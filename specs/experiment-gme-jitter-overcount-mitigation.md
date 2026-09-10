# GME 활동시간 jitter-overcount 완화 (gme-motion-v2 후보)

> 저신뢰·분절 추적의 재획득 위치 떨림(jitter)이 "움직임 시간"으로 산정되는 overcount를 활동 알고리즘 레벨에서 제거한다.

**상태:** ⏸️ 보류 (스펙 정리 완료 — TEST-SHEET pre-reg + owner 승인 후 착수)
**작성:** 2026-09-04
**연관 SOT:** [`../docs/superpowers/specs/2026-08-03-gecko-motion-engine-v1-design.md`](../docs/superpowers/specs/2026-08-03-gecko-motion-engine-v1-design.md) · [`../docs/superpowers/specs/2026-09-03-gme-slow-motion-v1-design.md`](../docs/superpowers/specs/2026-09-03-gme-slow-motion-v1-design.md)
**결정 게이트:** [`../docs/decision-gate.md`](../docs/decision-gate.md) 2026-09-04 레코드

## 1. 목적

GME의 사용자 가치는 "게코가 실제로 움직인 시간"의 신뢰성이다. v1(느린 움직임 승격)은
undercount를 회수했지만(2026-09-04 owner 감사에서 5클립 실증: moving 0.0→10.6s 등),
같은 감사에서 **반대 방향 오류**가 실증됐다:

- **실증 사례** (비공개 원장 `review-ledger.csv` 2026-09-04T11:10 세션, overcount 행):
  식재 사육장 카메라의 초점 밖(흐림) 영역에 웅크린 게코. 검출 conf 0.2~0.4,
  트랙 85개 / 프레임 공백 82회로 분절. **v1 moving 18.4s / 63.1s** 산정.
  그러나 moving 판정 구간(14.2~17.0s 포함 4쌍)의 게코 bbox 영역 프레임 픽셀 차이가
  **배경 노이즈와 동일**(mean ≈1.1, >20 변화 픽셀 0) — 게코는 완전 정지 상태였다.
- v1 설계 완료조건 3("합성 bbox jitter 회귀 표본은 static 유지")은 통과했으나,
  실세계의 **흐림 + 저신뢰 + 트랙 분절 조합**은 합성 표본이 커버하지 못했다.

overcount는 owner 활동 요약·관측 움직임 시간 카드의 신뢰를 직접 깎는다
(정지 개체를 "18초 움직임"으로 보고). undercount 회수(v1의 성과)를 깨지 않으면서
jitter 유래 moving만 걷어내는 것이 목표다.

## 2. 원인 구조 (코드 확인 기반, 2026-09-04)

판정 경로는 `gecko-vision-gate` `gme_motion.py` 2개다 (worktree
`yolo-v26-production-normalization` 기준 실독):

1. **즉시 변위**: `classify_track_motion` — 같은 track의 인접 포인트 bbox **중심** 변위 /
   체장(bbox 대각 평균) ≥ `moving_threshold_body_lengths`(0.08) → moving.
2. **느린 움직임 승격**: `promote_slow_motion` — 같은 track segment(포인트 간격 ≤0.25s,
   창의 80% 관측) 3초 중심창 양끝 순변위 ≥ 0.08 체장 → 창 중심 시점 static→moving 승격.

jitter가 오염시키는 방식:

- 저신뢰 재획득 시 **bbox 크기·위치가 함께 요동** → 중심 변위가 실이동 없이 0.08 체장을
  넘는 스파이크 발생 (경로 1). 체장이 작게 잡히는 프레임에서는 분모까지 줄어 증폭된다.
- 흔들리는 segment의 **양끝이 우연히 반대편으로 요동**하면 3초 순변위가 임계 초과 →
  창 전체가 moving으로 승격 (경로 2). 관찰된 1~3s 연속 moving 구간이 이 패턴과 부합.
- 신뢰도는 판정에 안 쓰인다: `tracker_confidence_floor`(0.35)는 트랙 유지용이고,
  변위 판정은 conf 0.2짜리 검출도 동등하게 신뢰한다.

## 3. 스코프

### In (이번 스펙에서 한다)
- gme-motion-**v2** 후보 레버 정의와 우선순위 (아래 §5)
- 평가 설계 (paired 회귀 게이트 골격 — 숫자 동결은 TEST-SHEET에서)
- 버전 격리·소유권 경계 명시

### Out (안 한다)
- **구현·배포** — 엔진은 `gecko-vision-gate`, 워커는 `petcam-nightly-reporter`(맥미니 런타임)
  소유. 착수 시 cross-repo handoff manifest + `HANDOFF_OK` 게이트 필수.
- **YOLO 재학습** — 같은 감사에서 나온 검출 안정화(흐림 영역·중복 박스)는 별도
  v2.6.1 데이터 트랙. 이 스펙은 "박스가 흔들려도 활동시간이 안 속는" 알고리즘 레버만.
- v0/v1 원장·아티팩트 수정 (append-only 불변).
- 웹 active algorithm 전환 (v1 canary 절차와 동일하게 별도 결정).

## 4. 완료 조건

- [ ] 후보 레버별 설계가 gecko-vision-gate 구현 담당이 그대로 받을 수 있는 수준으로 기술됨 (§5)
- [ ] 평가용 클립 세트 3종(jitter 양성 / 실이동 보존 / random)의 선정 기준 정의 (§6)
- [ ] `experiments/<exp>/TEST-SHEET.md` pre-reg 작성 + owner 승인 (착수 게이트)
- [ ] (착수 후) paired 회귀 REPORT — decision adopt/hold/reject 기록
- [ ] (adopt 시) gme-motion-v2 계약 문서 + cross-repo handoff 발행

## 5. 설계 메모 — 후보 레버 (우선순위순)

- **A. IoU 단락 (1순위, 최소 변경)**: 인접 검출 bbox IoU ≥ τ(예: 0.5)면 중심 변위와
  무관하게 static. 근거: jitter는 "같은 자리에서 박스가 요동"이라 IoU가 높고, 실이동은
  IoU가 떨어진다. 중심-변위 지표의 박스 크기 요동 민감성을 직접 상쇄. 경로 1·2 양쪽의
  변위 계산에 일괄 적용 가능.
- **B. 신뢰도 게이트**: conf < floor(예: 0.5)인 검출 쌍은 moving evidence로 불인정
  (static/unknown으로만 기여). 실증 사례의 conf 0.2~0.4 스파이크를 원천 차단.
  리스크: 저조도에서 실이동도 conf가 낮을 수 있음 → 실이동 보존 세트로 검증.
- **C. 지속성 히스테리시스**: 0.1s 단발 moving 스파이크는 인접 k프레임(예: 3) 연속
  초과 시에만 인정. v1 관찰의 0.1s blip 다수를 제거. 느린 움직임 승격(경로 2)과는
  독립이라 undercount 회귀 위험 낮음.
- **D. 픽셀 검증 폴백 (최후 수단)**: moving 승격 구간에 한해 bbox 내부 프레임 diff로
  확증 (2026-09-04 감사에서 사람 검증에 쓴 방법 그대로). 프레임은 이미 디코딩하므로
  추가 비용은 diff 연산뿐. 가장 확실하지만 엔진에 픽셀 경로가 새로 생기는 부담 —
  A~C로 부족할 때만.
- **부수 권고**: `aggregate_states`의 `candidate` / `moving_gecko_seconds`를 같은
  병합 interval 리스트에서 계산해 float 누적 순서 차이(±1e-15)를 원천 제거
  (2026-09-04 db_transient 사고의 엔진 측 근본 수정; DB 측은 epsilon 정렬 45d3142로 완료).
- **고려했던 대안**: threshold 0.08 상향 — 기각. 느린 움직임 회수(v1의 존재 이유)를
  직접 깎는 무딘 칼. jitter는 임계가 아니라 **증거의 질** 문제다.
- **리스크 / 미해결 질문**: ① IoU τ·conf floor·k의 조합 탐색이 튜닝 늪이 될 수 있음 —
  TEST-SHEET에서 후보 조합을 사전 고정(최대 3조합)하고 사후 튜닝 금지. ② 흐림 영역
  검출이 v2.6.1 재학습으로 안정화되면 이 레버의 필요 크기가 줄어듦 — 순서 무관하게
  양쪽 다 유효하나, 평가 시점의 detector identity를 고정할 것.

## 6. 평가 설계 (research-testing 의무)

`.claude/rules/research-testing.md` 적용 대상 — **TEST-SHEET 없이 평가 배치 실행 금지.**

- **jitter 양성 세트**: 2026-09-04 감사 원장의 overcount 행 + `tracking_quality`
  fragmentation/gap 상위 클립 중 사람 확인으로 "실제 정지" 판정된 것 (원장 경유,
  클립 식별자는 비공개 원장에만).
- **실이동 보존 세트**: v1이 undercount를 회수한 감사 5클립 (moving 0.0→10.6s 등,
  사람 확인으로 실이동 검증됨). **게이트: v2 후보의 moving이 v1 대비 유의미하게
  줄면 안 됨** (허용 폭은 TEST-SHEET에서 동결).
- **random 세트**: 최근 v1 run에서 무작위 N — 전체 분포 이동 감시.
- 지표: 클립별 moving_sec paired diff (v1 vs v2 후보), jitter 세트는 목표 방향 ↓,
  보존 세트는 유지. 합격 숫자·decision 룰은 TEST-SHEET pre-reg에서 동결하고 사후 변경 금지.
- 오답-전용 태깅 selection bias 주의: jitter 세트는 "오류 사례 모음"이므로 이 세트의
  개선율을 전체 정확도 주장에 쓰지 않는다 (진단·회귀 용도로만).

## 7. 버전·소유권

- 새 `algorithm_version = gme-motion-v2`. `(clip, engine_schema, algorithm,
  detector_identity)` 큐·원장 격리, v0/v1 불변 — slow-motion v1과 동일한 절차
  (shadow → 문제·음성 영상 통과 → live cutover는 별도 결정).
- 엔진: `gecko-vision-gate` / 워커 런타임: `petcam-nightly-reporter`(맥미니 launchd) /
  이 레포: 설계·DB 계약·평가. 착수 시 handoff manifest에 `execution_repo`·
  `runtime_host` 명시 (CLAUDE.md cross-repo 게이트).

## 8. 참고

- 실증 근거: 비공개 원장 `/Users/baek/private-rba/gme-owner-audit-v261/review-ledger.csv`
  (2026-09-04T11:10 세션) — 클립 식별자·스크린샷은 원장에만, 이 레포에 복사 금지.
- v1 회수 실증: 같은 원장 2026-09-04T03:22 세션 + `gme_runs` gme-motion-v1 결과.
- 연관: [`../docs/superpowers/specs/2026-09-03-gme-observed-moving-time-metric-design.md`](../docs/superpowers/specs/2026-09-03-gme-observed-moving-time-metric-design.md)
