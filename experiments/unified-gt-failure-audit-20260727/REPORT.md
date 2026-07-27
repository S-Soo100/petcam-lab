# Unified GT Catalog · VLM/Evidence Failure Audit

## Verdict

`UNIFIED_GT_FAILURE_AUDIT_READY_FOR_REVIEW`

데이터 통합 자체의 실효성은 확인했어. Owner GT만의 172 clips·39 episodes에서 legacy 사람 GT를
연결하니 **709 source rows → 431 unique domain clips → 122 independent 5-minute episodes →
38 camera-nights**로 분석 범위가 늘었어. legacy에는 기존 VLM 결과도 203 clips 연결돼 있어
Owner GT 23 VLM success만 볼 때보다 반복 오판 패턴을 훨씬 명확히 볼 수 있었어.

후속 승인 후 production R2에 이미 존재하는 두 failure mode의 44 clips를 read-only로 받아
GT와 VLM 예측을 숨긴 12-frame visual audit를 수행했어. 그 결과
`VISIBILITY_SCALE_OCCLUSION`이 **21 clips / 19 independent episodes / 4 camera-nights**에서
확인됐고, largest duplicate share 4.76%로 사전 기준을 통과했어.

따라서 다음 후보는 하나로 좁혔어:
`visibility_bbox_roi_experiment`. 이것은 production 채택이나 detector 자동 skip 승인이 아니라,
full-frame과 visibility-aware dual view를 비교할 **offline experiment 설계 검토 READY**야.

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

후속 blind review의 44 clips는 dataset203 membership을 가정해서 고른 것이 아니라,
DB에서 검증된 두 VLM mismatch mode의 교집합으로 다시 SELECT했어. 따라서 dataset203
manifest 부재는 여전히 전체 dataset203 membership 감사의 한계지만, 44-clip 영상 검수를
막는 조건은 아니었어.

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

## Blind root-cause review

두 qualified failure mode의 44 clips를 deterministic hash 순서로 섞고 `review-001` 같은 별칭만
부여했어. 판독 중에는 사람 GT, VLM 예측, failure mode를 표시하지 않았고 영상마다 12개 균등
시점 contact sheet만 봤어. raw UUID·R2 key·signed URL·영상·개별 판독은 gitignored `raw/`에만
남기고 tracked 파일에는 집계만 기록했어.

| Primary cause | Clips | Episodes | Nights | Largest duplicate share | 판정 |
|---|---:|---:|---:|---:|---|
| Visibility/scale/occlusion | 21 | 19 | 4 | 4.76% | qualified |
| Temporal sampling | 14 | 9 | 2 | 7.14% | 1 episode 부족 |
| Input quality | 8 | 3 | 4 | 12.50% | episode 부족 |
| Direct IR/light reflection | 1 | 1 | 1 | 100% | 부족 |

qualified visibility 원인은 morph/shedding overcall 18 clips·16 episodes와
motion-as-licking/care 3 clips·3 episodes에 걸쳤어. 특히 첫 실패 모드에서 게코가 프레임
일부에만 보이거나, 밝은 전경 물체·유리 반사·가림·작은 화면 점유 때문에 체형과 표면 texture가
불완전하게 들어오는 패턴이 반복됐어.

다만 이것은 historical exposed data의 단일 Codex visual review야. inter-rater agreement가 없고
12-frame 검수라 full-video 시간 인과를 직접 증명하지 못해. 따라서 47.73% selected clip share를
예상 정확도 상승률로 바꿔 말하지 않아.

## Recommended next candidate

`visibility_bbox_roi_experiment`

다음 연구에서는 같은 VLM에 아래 입력만 비교해.

1. baseline full-frame sampling
2. full frame + visibility-aware crop/zoom을 함께 주는 dual view

Gate bbox나 detector 결과는 행동 GT로 쓰지 않고 입력 위치 evidence로만 사용해. historical
44 clips는 개발·회귀 진단용이고, threshold·prompt·crop policy를 이 데이터에 맞춘 뒤 같은
데이터를 holdout이라고 부르면 안 돼.

측정 지표는 morph/shedding false-positive episode rate, 전체 action macro-F1,
care-event recall, judgeability/abstention, clip당 frame·token cost야. split은 clip이 아니라
duplicate group → 5-minute episode → camera-night 순으로 막고, production adoption은 별도의
fresh multi-camera holdout에서 개선이 재현될 때만 검토해.

## Decision gate

| Gate | 근거 | 판정 |
|---|---|---|
| SOT 부합 | data engine의 사람 GT 기반 실패 분석이며 Gate 자동 skip·production selector와 분리 | PASS |
| 기대효과 명확 | shedding 중심 visibility failure를 겨냥하되 47.73%를 gain으로 약속하지 않음 | PASS |
| 측정 가능 | episode 단위 false positive, macro-F1, recall, abstention, cost 측정 | PASS |
| 유효한 계획 | historical dev와 fresh holdout 분리, 단일 후보만 비교 | PASS |

판정은 `PASS_FOR_OFFLINE_EXPERIMENT_DESIGN`이야. 모델·prompt·threshold·selector를 이번 작업에서
바꾸거나 production 적용하는 승인은 아니야.

## Mutation 0

- 최초 inventory 시작: `2026-07-27T07:27:04.519659Z`
- 최초 inventory 종료: `2026-07-27T07:31:02.706619Z`
- blind review 시작: `2026-07-27T07:48:24.221890Z`
- blind review 종료: `2026-07-27T08:08:50.217223Z`
- 12개 관련 table의 row count와 ordered MD5 fingerprint가 전부 동일
- SELECT query만 실행
- DB/R2/runtime write 없음
- 44개 R2 object는 authenticated labeling web이 발급한 signed GET으로만 읽음

관찰 table:

`behavior_labels`, `behavior_logs`, `clip_labeling_session_revisions`,
`clip_labeling_sessions`, `clip_prelabels`, `clip_python_evidence_runs`,
`clip_vlm_jobs`, `motion_clip_blind_submissions`, `motion_clip_consensus`,
`motion_clip_labeling_sessions`, `motion_clip_labeling_triage`,
`motion_clip_labeling_triage_events`

## Verification

- focused: 43 passed
- full project suite: 832 passed, 3 skipped, 0 failed
- `verify_artifacts.py`: `UNIFIED_GT_ARTIFACTS_OK`
- `inventory.sql`, `blind-review-aggregate.sql`: `SELECT_ONLY_OK`
- `git diff --check`: clean

## Independent review

- Codex CLI: 설치된 client/model 조합 비호환으로 실행 불가
- Gemini CLI: 구독 tier/client 비호환으로 실행 불가
- Claude CLI: read-only review를 150초 기다렸으나 출력 없이 종료
- 대체 독립 검증: 원본 집계와 별도 verifier가 count·union·failure partition·fingerprint를 재계산했고,
  focused test와 full project suite를 각각 실행

외부 AI reviewer의 승인 결과를 얻었다고 주장하지 않아. READY는 사전 수치 계약을 통과한
offline experiment review 판정이고, single-reviewer 한계 때문에 production adoption 판정으로
승격하지 않아.

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
- R2 write 없음. review 대상 44개만 read-only GET
- signed URL·R2 key·clip UUID tracked 저장 없음
- labeling web/API/runtime/LaunchAgent/deploy 변경 없음
- Slack 없음
- main merge 없음
