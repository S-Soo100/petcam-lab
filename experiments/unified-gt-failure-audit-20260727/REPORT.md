# Unified GT Catalog · VLM/Evidence Failure Audit

## Verdict

`UNIFIED_GT_FAILURE_AUDIT_HOLD_INSUFFICIENT_CONFIRMED_ROOT_CAUSES`

데이터 통합 자체의 실효성은 확인했어. Owner GT만의 172 clips·39 episodes에서 legacy 사람 GT를
연결하니 **709 source rows → 431 unique domain clips → 122 independent 5-minute episodes →
38 camera-nights**로 분석 범위가 늘었어. legacy에는 기존 VLM 결과도 203 clips 연결돼 있어
Owner GT 23 VLM success만 볼 때보다 반복 오판 패턴을 훨씬 명확히 볼 수 있었어.

하지만 현재 worktree에는 dataset203 manifest와 reviewable media가 없어, DB의 GT↔VLM
불일치가 **어떤 시각·시간축 원인 때문에 생겼는지 blind 영상 검수로 확정할 수 없었어**.
사람이 이미 고른 error tag도 최대 8 independent episodes라 root-cause 최소 기준 10에
도달하지 못했어. 그래서 반복 **failure mode** 2개는 확인했지만, 다음 production 개선 투자
1개를 root cause에 연결하는 READY 판정은 보류해.

## Exact source counts and eligibility

Snapshot: `2026-07-27T07:27:36.257795Z`

| Source | Source rows | Unique clips | Trust | 포함 계약 |
|---|---:|---:|---|---|
| Owner motion GT | 172 | 172 | T1 | audited Owner, completed, initial/current GT와 completed_at 존재 |
| Legacy blind sessions | 42 | 26 | T1 | completed, immutable initial GT, current GT, prediction snapshot |
| Legacy behavior labels | 258 | 242 | T2 | 사람 label row, labeler 2명 |
| Legacy human behavior logs | 237 | 237 | T3 | `source='human'`, blind/provenance 불완전 |
| 합계 | 709 | 중복 제거 전 합계 아님 | — | source row 수 |

Owner 진행 중 2건, draft 0건은 제외했어. Owner revision 0, Canary overlap 0이야.
Legacy blind session 26 clips는 behavior labels와 전부 겹쳐. behavior labels와 human logs는
220 clips가 겹쳐. Owner motion clip과 legacy clip의 DB identity overlap은 0이야.

dataset203은 이름과 historical count만 믿지 않았어. 이 worktree에 manifest가 없어서
203/202/197 정리 이력을 정확한 현재 membership으로 재구성하지 않았고, DB상 legacy VLM
coverage와 별도로 표시했어.

## Unique clips, episodes, camera-nights, overlap

| 단위 | 수 |
|---|---:|
| source rows | 709 |
| unique domain clips | 431 |
| 5-minute independent episodes | 122 |
| camera-nights | 38 |
| legacy union unique clips | 259 |

단순히 `172 + 42 + 258 + 237`을 데이터 수라고 부르면 709로 과장돼. source overlap을 제거한
실제 clip 단위는 431이고, 시간 누출을 줄인 episode 단위는 122야. 이번 결과가 사용자가 제안한
“전부 긁어오면 더 많은 내용이 나오지 않나”에 대한 정확한 답이야: **그렇다. 다만 유효한 증가는
709가 아니라 431 clips / 122 episodes로 봐야 해.**

byte-identical checksum은 원장에 없고 dataset203 manifest/media도 없어 물리 파일 중복은 증명하지
못했어. 확인된 주요 mismatch mode 안에서는 object key·started_at·duration·size capture tuple이
모두 distinct였고, 자동 삭제·병합은 하지 않았어.

## GT trust and canonical mapping loss

| Trust tier | Rows | 역할 |
|---|---:|---|
| T1 | 214 | primary benchmark |
| T2 | 258 | 확장/민감도 분석 |
| T3 | 237 | EDA only |
| X | 0 | GT 제외 |

Owner GT는 moving 128, basking 36으로 치우쳐 있었지만, legacy behavior labels를 더하면
hand_feeding 32, shedding 29, drinking 26, eating_prey 24, eating_paste 20이 추가돼
희소 행동 실패를 볼 수 있게 됐어.

사람 label conflict가 있는 clips는 6개라 단일 GT VLM 비교에서 제외했어. 원천 ontology를
motion/visibility/action/care의 교집합으로만 mapping하고, 없는 축을 추론하지 않았어.

## Existing VLM/Evidence/Gate coverage

| Source | Python Evidence | Gate | 기존 VLM |
|---|---:|---:|---:|
| Owner 172 | 172 | 172 | any 24 / success 23 |
| Legacy union 259 | 0 | 0 | behavior-log 203 |
| Legacy blind sessions 26 | — | — | prediction review 26 |

Python Evidence와 Gate는 Owner domain에만 있어. 따라서 Evidence/Gate 실패가 legacy 행동
다양성에서도 반복된다고 주장할 수 없어. 반대로 VLM은 legacy coverage가 커서 행동 오판 패턴
분석에 실효성이 있었어.

## VLM retrospective result

behavior label에서 사람 action이 하나로 합의되고 기존 VLM row가 있는 180 clips만 비교했어.

| 항목 | 수 |
|---|---:|
| VLM covered, single human action | 180 |
| exact | 114 |
| mismatch | 66 |
| retrospective exact rate | 63.3% |
| 사람 action conflict로 제외 | 6 clips |

이 수치는 과거 모델·prompt·sampling이 섞인 retrospective diagnostic이야. 현재 production
VLM의 정확도나 future holdout 성능으로 일반화하지 않아.

## Repeated failure modes

### 1. Morph/shedding overcall

`GT moving 또는 basking → VLM shedding`

- 28 clips
- 20 independent episodes
- 7 camera-nights
- 가장 큰 capture-tuple group 3.57%
- 분류된 mismatch episode mass 45.5%

clip·episode·night 기준으로 가장 큰 반복 패턴이야. 기존 human error tag에도
`morph_confusion` 10 clips, `ir_or_glare` 3 clips가 있어 신체 무늬·IR 오인의 가능성을 지지해.
하지만 해당 tag는 각각 5·3 episodes에 그쳐, 28건 전체가 같은 root cause라고 확정하지 않아.

### 2. Motion-as-licking/care overcall

`GT moving → VLM eating_paste 또는 drinking`

- 16 clips
- 13 independent episodes
- 5 camera-nights
- 가장 큰 capture-tuple group 6.25%
- 분류된 mismatch episode mass 29.5%

움직임을 혀·섭취 care 행동으로 과해석하는 반복 패턴이야. `action_confusion` tag가 14 clips에서
보이지만 독립 episode는 8이라 root cause 최소 기준 10에는 못 미쳐.

### 3. Feeding context lost — 표본 기준 미달

`GT hand_feeding → VLM eating_paste 또는 eating_prey`

- 15 clips
- 6 independent episodes
- 4 camera-nights

clip 수는 많지만 같은 촬영 episode 안 반복이 커서 top cause 자격을 주지 않았어. 사람 손·도구
맥락을 잃는지, top-1 ontology가 행위와 섭취 대상을 동시에 표현하지 못하는지는 영상 검수가 필요해.

## Why this is HOLD, not failure

이번 감사에서 분명해진 것은 **무엇을 자주 틀리는지**야. 아직 확정되지 않은 것은 **왜 틀리는지**야.

예를 들어 shedding overcall은 아래 원인이 모두 가능해.

- 신체 무늬를 허물로 오인하는 semantic 문제
- IR·glare가 만든 texture 문제
- 특정 frame만 선택한 temporal/sampling 문제
- 낮은 해상도·원거리 visibility 문제

원인을 확인하지 않고 prompt부터 바꾸면 같은 오류를 다른 class로 이동시킬 수 있어. 승인된 설계의
목표가 “다음 투자 1개를 고르는 것”이므로, failure mode를 root cause라고 바꿔 부르지 않았어.

## Minimum next action

모델 재실행이나 추가 labeling campaign이 아니라 아래 한 단계면 돼.

1. dataset203의 현재 manifest와 reviewable media를 이 worktree의 gitignored raw 경로에 제공
2. 두 qualified mode의 44 clips(28 + 16)를 GT·기존 예측을 숨긴 상태로 영상 검수
3. 각 episode에 primary root cause 1개, secondary cause 최대 2개 부여
4. 10 episodes·2 nights·duplicate dominance 20% 계약을 다시 적용
5. 통과한 root cause가 있으면 개선 후보 1개만 추천

이 과정에서도 VLM·Evidence·Gate를 재실행하거나 production을 바꾸지 않아.

## Mutation 0

- 시작: `2026-07-27T07:27:04.519659Z`
- 종료: `2026-07-27T07:31:02.706619Z`
- 12개 관련 table의 row count와 ordered MD5 fingerprint가 전부 동일
- SELECT query만 실행
- DB/R2/runtime write 없음

관찰 table:

`behavior_labels`, `behavior_logs`, `clip_labeling_session_revisions`,
`clip_labeling_sessions`, `clip_prelabels`, `clip_python_evidence_runs`,
`clip_vlm_jobs`, `motion_clip_blind_submissions`, `motion_clip_consensus`,
`motion_clip_labeling_sessions`, `motion_clip_labeling_triage`,
`motion_clip_labeling_triage_events`

## Verification

- focused: 30 passed
- full project suite: 832 passed, 3 skipped, 0 failed
- `verify_artifacts.py`: `UNIFIED_GT_ARTIFACTS_OK`
- `inventory.sql`: `SELECT_ONLY_OK`
- `git diff --check`: clean

## Git state

- worktree: `/Users/baek/.codex/worktrees/7896/petcam-lab`
- branch: `codex/unified-gt-failure-audit-20260727`
- snapshot artifact parent HEAD:
  `338edc815eb035a884efcd21c30a3a21a758a181`
- origin/main: `8e0d62ba679863c6f84f2429a1be7a590dfd075a`
- main merge·production 반영 없음

최종 handoff HEAD/upstream/status는 이 보고서 커밋·push 후 별도로 확인해.

## Explicit non-actions

- 모델 학습·LoRA·classifier fitting 없음
- prompt·threshold·feature weight 튜닝 없음
- selector·자동 skip 변경 없음
- VLM·Python Evidence·Gate 재실행 없음
- 사람 GT 수정·자동 병합·자동 제외 없음
- R2 GET/write·signed URL 저장 없음
- labeling web/API/runtime/LaunchAgent/deploy 변경 없음
- Slack 없음
- main merge 없음
