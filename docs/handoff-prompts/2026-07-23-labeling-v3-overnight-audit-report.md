# 운영 라벨링 v3 야간 감사 보고서

**감사 시각:** 2026-07-23 04:36~04:40 KST
**판정:** `LABELING_V3_GT_INTEGRITY_VERIFIED_WITH_VLM_FOLLOWUP`

## 1. 이번에 실제로 변경한 운영 데이터

사용자가 직접 지정한 clip `18f6bbc8…` 한 건만 기존 `제외(skip)`에서 라벨 대상으로 되돌린 뒤 사람 판정을 저장했다.

- 사람 판정: `visibility=partial`, `primary_action=basking`, `observed_actions=[static]`
- 구간: 영상 전체 `static`
- 하이라이트: `exclude`
- 환경: `ir`, `occlusion`
- AI 검수: `incorrect`, 오류 `gecko_missed`
- 검수 메모: 사람 판정은 일부 보이는 휴식이며 AI는 게코가 보이지 않는다고 판단함

기존 RPC(`fn_decide_motion_clip_labeling` → `fn_lock_motion_clip_gt` →
`fn_complete_motion_clip_vlm_review`)만 사용했다. 적용 뒤 triage=`label`, session stage=`completed`를
다시 읽어 확인했다. 이 한 건 외의 기존 `skip` 판정은 수정하지 않았고, 감사 종료 시 `skip`은 7건이다.

## 2. 저장된 사람 판정 전수 무결성 감사

웹이 실제 사용하는 `validateGroundTruth`를 현재 TypeScript 소스에서 로드해 저장 GT 전부를 clip의 실제
`duration_sec`와 함께 재검증했다. 별도 완화 규칙이나 Python 재해석은 쓰지 않았다.

| 항목 | 결과 |
|---|---:|
| triage | 88 |
| session | 78 |
| completed / gt_locked | 77 / 1 |
| GT validator 실패 | **0** |
| 구조·참조 무결성 실패 | **0** |
| 중복 session | **0** |
| R2 메타데이터 누락 | **0** |
| revision | 0 |

판정 분포는 `label 78 / skip 7 / hold 3`, 대표 행동은 `moving 59 / basking 15 / unseen 4`,
가시성은 `visible 54 / partial 20 / absent 4`였다. 하이라이트는 `exclude 52 / include 26`이다.
이는 형식·계약 감사 결과이며, 사람이 본 영상 의미를 Python으로 다시 판정했다는 뜻은 아니다.

## 3. `no_prediction` 73건의 원인

session 78건 중 prediction snapshot은 4건, `no_prediction`은 73건, 검수 진행 중은 1건이었다.

| 원인 | 건수 | 의미 |
|---|---:|---|
| 해당 clip의 VLM job 자체가 없음 | 68 | `budget-router-v1`이 모든 영상을 호출하지 않고 window별 후보만 고르는 현재 계약상 정상 |
| VLM 성공이 GT 잠금보다 늦음 | 4 | GT 잠금 때만 snapshot을 복사하므로 뒤늦은 결과가 해당 session 검수로 연결되지 않는 제품 공백 |
| VLM job이 아직 retryable | 1 | 운영 recovery 대상으로 남음 |

따라서 73건을 전부 VLM 장애로 보면 안 된다. 즉시 고쳐야 할 핵심은 **늦게 성공한 4건을 안전하게
후속 검수할 수 있는 경로**다. blind GT를 덮어쓰거나 자동 판정하지 말고, owner에게 `AI 판정 도착 · 검수
필요` 상태로 보여주는 별도 설계가 필요하다.

## 4. 전체 VLM 큐와 backfill 상태

production `clip_vlm_jobs` 606건을 전수 읽었다.

- `succeeded 536 / failed_terminal 46 / failed_retryable 12 / queued 12`
- open 24건: 과거 `auth_probe_failed` queued 12건 + `max_turns` retryable 12건
- 정규 worker는 현재 window를 먼저 처리한 뒤 과거 open을 cycle당 최대 4건만 복구한다. 최신 Mac mini
  로그에서 current 성공 8 + recovery 성공 4가 확인돼 recovery 경로는 작동한다.
- rolling backfill ledger는 2026-07-11~07-21 모두 `completed`다. backfill selector 누적은
  `succeeded 381 / failed_terminal 32`, open 0이다.

open 24건은 즉시 데이터 손상은 아니지만 완전 정상화도 아니다. 다음 정규 cycle에서 수가 감소하는지
관찰하고, 같은 24건이 고정되면 `auth_probe_failed` queued의 재선정 계약을 별도로 진단한다.

## 5. Mac mini 런타임 실측

호스트 `baeg-endeuui-Macmini.local`에서 read-only로 LaunchAgent·HEAD·로그·임시파일을 확인했다.

| 서비스 | 상태 |
|---|---|
| `com.petcam.vlm-candidate-worker` | loaded, last exit 0, 최근 current 8 + recovery 4 성공 |
| `com.petcam.vlm-historical-backfill` | loaded, last exit 0, `no backlog — no-op` |
| `com.petcam.python-evidence-worker` | loaded, last exit 0, 최신 cycle `jobs=30 ok=29 reused=1 fail=0 terminal=0` |
| `com.petcam.nightly-reporter` | loaded, last exit 0 |

Python Evidence production 현황은 job 3,650건(`succeeded 3,603 / queued 17 / failed_terminal 30`),
append-only run 3,603건이다. 최근 run도 Mac mini에서 계속 생성됐고 temp media는 0건이었다.

`com.petcam.router-features`는 현재 loaded가 아니었다. 현행 candidate worker와 universal Python Evidence
worker의 성공에는 영향을 주지 않았으므로 이번 감사에서는 장애로 판정하지 않는다. 과거 SOT에 상주로
기록된 부분은 현행 필요 여부를 별도 결정해야 한다.

## 6. UI 배포 상태

놀이 상호작용 선택 카드 변경은 main `455696c`에 포함됐다. production deployment
`dpl_2XhV2Xfxhx3jCQ41HSZuNsjV1hBG`는 `READY`이고 `https://label.tera-ai.uk` alias가 연결돼 있다.
저장 enum·API payload·migration은 바꾸지 않고 표시와 입력 이해도만 개선했다.

## 7. 다음 권장 순서

1. 사용자는 현재 motion 라벨링을 계속한다. 저장 GT 계약 오류는 발견되지 않았다.
2. 다음 VLM 정규 cycle 뒤 open 24건이 감소하는지 SELECT-only로 재확인한다.
3. 늦게 성공한 VLM 4건을 owner 후속 검수 큐에 노출하는 별도 소규모 설계를 작성한다.
4. `router-features`를 복구할지 역사 서비스로 종료할지 현재 소비자 기준으로 SOT를 정리한다.

자동 재라벨·GT 덮어쓰기·skip 일괄 변경·VLM 재호출·LaunchAgent 변경은 하지 않았다.
