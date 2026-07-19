# feature — 카메라 주/야간 모드전환 가짜 트리거 필터

> 상태: 📝 spec (미구현). 착수 전 사용자 승인 + clean tree 필요.
> 출처: `experiments/vlm-care-label-audit-20260719/REPORT.md` Failure mode B.
> 트랙: RBA evidence 레이어 (Codex/local router 연구 소유, `backend/router_features.py`).

## 왜

daily VLM 감사에서 eating_paste #3(2026-07-18 17:24:59)이 **게코 정지 상태인데 카메라 주간↔야간(IR) 모드전환으로 전역 밝기/색이 급변 → 모션 디텍터 오발동 → non-event 클립 저장 → VLM 이 eating 으로 confabulate** 하는 2겹 오탐이었다. 캡처層 가짜 트리거를 evidence 레이어에서 저비용으로 걸러 분석 큐 오염을 줄인다.

- 이건 **비용/노이즈 게이트**지 행동 확정이 아니다. `.claude/CLAUDE.md` local-router v0 규칙 준수: `skip`/`auto_*` 자동판정 신설 금지. 산출은 evidence flag 뿐, 라우팅 정책 변경은 별도 spec+TEST-SHEET.

## In scope

- `MotionFeatureSet` 에 `global_illumination_shift`(bool 또는 0~1 score) evidence 필드 1개 추가.
- 감지 신호 (이미 `router_features.py` 가 계산하는 재료 재사용):
  - **전역 밝기 점프** — 인접 프레임 `brightness`(현 `np.mean(gray)`) 델타가 큰 임계 초과. IR on/off = 전체 luminance 계단.
  - **컬러→흑백 전환** — 프레임 saturation(HSV S 평균) 급락 = 주간 컬러 → 야간 IR grayscale. (현재 gray 만 뽑으므로 saturation 은 신규 계산 필요.)
  - **모션이 로컬 아닌 전면** — `motion_mask` 가 프레임 대부분(예: >0.6) 동시에 켜짐 = 객체가 아니라 조명. `center_motion_ratio` 와 결합.
- 전환 프레임을 motion 통계에서 제외하거나 down-weight (선택) → `motion_mean`/`active_*` 왜곡 방지.

## Out of scope

- 클립 삭제 / VLM skip 자동화 (게이트 정책은 별도 spec). 이 필터는 **flag 만** 쓴다.
- 카메라 펌웨어/모션 디텍터 민감도 변경 (캡처는 민감 유지 원칙, `capture-sensitivity-gate-cost`).
- terra-server / 앱 노출 로직 (레포 밖).

## 완료 조건

- [ ] `MotionFeatureSet` + `clip_router_features` 스키마에 flag 필드 추가 (migration).
- [ ] eat_paste #3 클립(`7b5b32cb-…`)에서 flag=true, dish-presence 오탐 9건(실제 moving)에서 flag=false 로 분리 (전환 vs 진짜 이동 구분 검증).
- [ ] 오탐 아닌 정상 야간 클립(모드전환 없는 IR 고정 상태)은 flag=false — false suppress 0.
- [ ] `pytest tests/test_router_features.py` (또는 신규) 통과 — fake 프레임(numpy): 밝기계단/saturation급락/전면모션 각각.
- [ ] 소규모 육안 검증셋(모드전환 N건 + 정상 IR N건)에서 precision/recall 보고 → `experiments/` REPORT.

## 설계 메모

- 신호는 **AND 조합** 권장 (밝기점프 단독은 구름/조명 변화 오검 가능; 전역모션+saturation급락 동반 시 모드전환 확신 ↑).
- 임계값은 하드코딩 말고 상수+주석. 초기값은 검증셋으로 튜닝하되 사후 변경 시 research-testing 규칙(게이트 사후변경 금지) 준수.
- `evidence_reliability`(brightness 기반)와 중복 아닌지 확인 — 그건 프레임 전반 품질, 이건 프레임 간 전환 이벤트.

## 학습 노트

- IR 주야간 전환은 whole-frame luminance/색공간 변화라 프레임차분 모션에 전면 반응. 로컬 객체모션(center-weighted)과 공간 분포가 다름 → `center_motion_ratio` 가 판별 축.
- 같은 결의 IR 아티팩트: 흰 모프→shedding 오판(`gecko-morph-shedding-false-positive`), Sonnet moving→shedding IR 창백패치 환각.
