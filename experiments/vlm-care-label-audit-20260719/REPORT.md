# REPORT — daily VLM candidate 케어행동 라벨 육안 감사 (2026-07-19)

> 종류: production 산출물 감사 (post-hoc, 사람 GT). 인퍼런스 배치 실행 아님 — daily 워커가 이미 낸 결과를 전수 육안 확인.
> decision: **케어행동(eating/drinking) VLM 라벨 = 정지프레임 천장 오탐. 앱 노출 금지 유지, 비-VLM evidence 경로 재확인.**

## 0. 배경 / 감사 대상

Mac mini `com.petcam.vlm-candidate-worker`(model `claude-sonnet-5`, prompt `v4.0-direct-images`, temperature=0)가
`clip_vlm_jobs` 에 쓴 최근 5일(2026-07-15 ~ 07-19 KST) succeeded 397건 중,
**moving / unseen 을 제외한 케어행동 라벨 전수 11건**을 owner 가 R2 원본 영상으로 육안 확인했다.

- **selection bias 회피:** "오답 의심" 건만 고른 게 아니라, 창 안의 **비-moving/unseen 라벨 전수 11건**을 대상으로 삼았다 (`.claude/rules/research-testing.md` selection-bias 함정 준수). 정확도 수치는 이 전수 집합에서만 인용.
- 11건 전부 **단일 카메라 `p4cam-79b5d844`** 산출 (밥그릇 상시 프레임 존재 환경).

## 1. 결과 표 — GT 대비

| 라벨 (VLM) | 건수 | conf 범위 | 육안 GT | 정오 |
|---|---|---|---|---|
| hand_feeding | 1 | 0.85 | 사람 손+급여스틱 입에 접촉 (명확) | ✅ 정답 |
| eating_paste | 8 | 0.55~0.75 | 7건 = 그냥 돌아다님 / 1건 = 정지 + 카메라 주야간 모드전환 | ❌ 전부 오답 |
| drinking | 2 | 0.55 | 밥그릇 근처 이동 (물 핥기 아님) | ❌ 전부 오답 |
| **합계** | **11** | | | **10/11 오답 (91%)** |

- 유일한 정답이 conf 0.85 hand_feeding. **conf 순위와 정오는 정렬 안 됨** (0.75 eating_paste 도 오답) → conf threshold 단독 게이트 위험 재확인 (`feedback_vlm_confidence_abstain_limit`).

## 2. Failure mode 분석

### A. dish-presence confabulation (9/11)

게코가 **상시 프레임의 밥그릇 근처를 이동**하면, 모델이 reasoning 에 *"머리를 그릇 위에 두고 혀를 페이스트로 뻗음"* 같은 **먹는 근거를 지어냄**. 정지프레임엔 혀-페이스트 접촉이라는 결정 증거가 없어 서사로 대체.
- 실제 GT = 전부 `moving`.
- 원인 = 입력(정지프레임)에 정보 부재. 프롬프트/모델/재분석으로 못 고침 → `v1-drinking-close`·`roi-crop-close` 천장 재확인.

### B. 카메라 주/야간 모드전환 = 가짜 모션 트리거 (1/11, 신규)

eat_paste #3 (07-18 17:24:59, conf 0.70). 게코는 **정지**. 카메라가 주간↔야간(IR) 모드를 전환하며 **전역 밝기/색 급변 → 모션 디텍터 오발동 → non-event 클립 저장**. 그 프레임을 VLM 이 또 eating 으로 confabulate. **캡처層 오탐 + 분석層 오탐 2겹.**
- 과거 IR 아티팩트 오탐(흰 모프→shedding, `gecko-morph-shedding-false-positive`)과 동일한 결.
- 모드전환은 감지가 싸다 (클립 내 saturation 컬러→흑백 급변 / 전역 luminance 점프 = 로컬 객체모션 아님) → evidence 레이어 필터 후보.

## 3. 앱 노출 경계 검증 (중요 — 실피해 여부)

daily 오탐이 실제 사용자에게 가는지 DB 로 확인:

| 확인 | 결과 |
|---|---|
| 11개 care clip_id 가 `behavior_logs` / `behavior_labels` 에 존재? | **0건** |
| daily 워커 저장 경계 | `clip_vlm_jobs` 에만 (앱·GT·활동시간과 격리, 계약 준수) |
| petcam-lab `/clips/highlights` `HIGHLIGHT_ACTIONS` | eating_paste/drinking **제외** (5-class 만) |

→ **daily 오탐 10건은 현재 사용자에게 노출되지 않는다.** 격리 계약 유효.

**단, 열린 리스크:** `behavior_logs` 에 daily 와 무관한 vlm eating_paste 31 + drinking 15 = **46건**(구 워커/nightly-board 유래) 존재. production highlight 실경로 = terra-server(레포 밖, `confidence>=0.5 + moving/unseen/shedding 억제`)라 eating_paste/drinking 은 억제 목록에 없어 **앱 노출 가능**. 이 레포에서 확정 불가 = 후속 확인 항목.

## 4. decision

- **label:** `reject`(케어행동 정지프레임 VLM 라벨을 신뢰 신호로 사용) / `confirm`(비-VLM evidence 경로 필요성).
- 근거: 전수 11건 91% 오답, failure mode 전부 시각정보 부재/캡처 아티팩트 = 입력·프롬프트·모델 레버로 해결 불가.
- **conf threshold 로 건지기 금지** — 0.75 오답 존재.

## 5. 다음 액션

1. **terra-server highlight 경로 확인** — behavior_logs vlm eating_paste/drinking 46건이 앱에 노출되는지. 노출되면 억제 목록에 두 클래스 추가 필요. (rec #2, 코드 위치 레포 밖)
2. **카메라 모드전환 필터 spec** — Failure mode B. evidence 레이어에 전역 조명전환 감지 게이트. (rec #3, `specs/feature-capture-mode-switch-filter.md`)
3. **비-VLM 급여/음수 evidence** — 미스팅·급여 타임스탬프 매칭. dish-presence confabulation 의 유일 해법. (기존 `feature-rba-evidence-based-feeding-drinking.md`)

## 부록 — 감사 대상 11건 (clip_id / 녹화시각 KST / conf)

| label | clip_id | 녹화(KST) | conf | GT |
|---|---|---|---|---|
| hand_feeding | da5e9eed-90f0-4bc5-8054-c3d1cfd3300b | 2026-07-07 14:57:47 | 0.85 | ✅ |
| eating_paste | 375377db-a3fe-444f-90de-022252199e26 | 2026-07-18 17:18:56 | 0.75 | ❌ moving |
| eating_paste | b1bfe960-1a2b-499f-b148-35812e37fc7f | 2026-07-18 17:17:03 | 0.75 | ❌ moving |
| eating_paste | 7b5b32cb-fb04-4dc0-876d-941122d88044 | 2026-07-18 17:24:59 | 0.70 | ❌ 정지+모드전환 |
| eating_paste | 1c8a9369-e924-47c0-b3e7-a67626bb532d | 2026-07-18 17:32:30 | 0.65 | ❌ moving |
| eating_paste | d0bf7bfc-89ab-4b3f-bc0b-22388ffcf3a4 | 2026-07-15 17:22:14 | 0.60 | ❌ moving |
| eating_paste | 33968d46-b383-466f-a4c6-e40da3cb8715 | 2026-07-15 17:50:57 | 0.60 | ❌ moving |
| eating_paste | 3280bb7e-99fb-4367-a0e5-050f44029224 | 2026-07-15 17:53:05 | 0.55 | ❌ moving |
| eating_paste | 840949dc-d4c5-46fa-8778-4116f8beed22 | 2026-07-15 17:26:24 | 0.55 | ❌ moving |
| drinking | 6c16a62b-f572-4008-84dc-b6c700777ada | 2026-07-16 13:44:28 | 0.55 | ❌ moving |
| drinking | b0171f2d-329d-43b7-8cbb-b742065ad1b6 | 2026-07-16 13:40:58 | 0.55 | ❌ moving |

> 원본 R2 prefix: `terra-clips/clips/p4cam-79b5d844/` (bucket `petcam-clips`). 소스 테이블 `motion_clips`.
