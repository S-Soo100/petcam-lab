# Local VLM Evidence — Gate B0 통합 + Gate B1 가용성 보고

- **task_id:** local-vlm-evidence-b1
- **execution_repo:** `/Users/baek/petcam-lab/.worktrees/local-vlm-evidence-web-gt` (branch `codex/local-vlm-evidence-web-gt`)
- **handoff manifest:** `/Users/baek/.codex/handoffs/2026-07-22-local-vlm-evidence-b1-handoff.md`
- **handoff 검증:** `HANDOFF_OK task=local-vlm-evidence-b1 repo=local-vlm-evidence-web-gt commit=e2d3920e runtime=none`
- **작성 시각(UTC):** 2026-07-21T17:2x (probe query_watermark `2026-07-21T17:27:02.500641+00:00`)

---

## 0. 최종 판정

> ## B1_BLOCKED_DATA_INSUFFICIENT
>
> 6 strata 중 **hardcase(47) 만 DATA_AVAILABLE**, 나머지 5개는 30 episode 미만.
> 180 manifest 미생성. **B2 금지** (handoff step 11 — 한 strata라도 30 미만이면 B2 착수 불가).
> owner 검토 + 새 handoff 발행 전까지 STOP.

무결성/변조 판정: **B1_REJECT_INTEGRITY 아님** (독립 재계산 전부 일치), **B1_BLOCKED_SOURCE_ERROR 아님** (source 정상).

---

## 1. Gate B0 — 검수된 hardening 기반 통합

| 레포 | 조치 | main HEAD (origin) | 근거 |
|---|---|---|---|
| **petcam-lab** | **no-op** (이미 통합됨) | `e2d3920e3c098b97edd3f17657ab2ba127ed6a62` | hardening `fdb1ec76` 는 이미 origin/main 의 조상. 빈 커밋 만들지 않음 |
| **petcam-rba-worker** | **FF-only 통합** | `e846ba50ec65457d5cca795f801960a41c0041b3` | `c2249af..e846ba5` (17 commits) `--ff-only` merge → `push origin HEAD:main` |

**ancestry 확인 (읽기 전용, `merge-base --is-ancestor`):**
- lab: `fdb1ec76` 는 origin/main 의 조상 → 이미 포함 (no-op). origin/main 은 `fdb1ec76` 의 조상 아님(main 이 앞섬).
- rba: `e846ba50` 는 origin/main 에 미포함. origin/main(`c2249af7`) 은 `e846ba50` 의 조상 → **FF 가능**.
- 둘 다 non-ancestor 아님 → `B0_BLOCKED_NON_FF` 해당 없음.

**통합 방식 (안전):** disposable detached worktree `/tmp/rba-b0-ff`(origin/main 기준)에서 `--ff-only` 후 push,
사용자 primary checkout 은 건드리지 않음, 완료 후 worktree 제거. force push/history rewrite 없음.

**재검증 테스트 (통합 전 green gate):**
- lab main(`e2d3920`) `uv run pytest`: **660 passed**
- rba hardening(`e846ba50`) `uv run pytest`: **172 passed, 1 skipped**
- rba 격리 런타임 offline(`HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`, `runtime/local-vlm`):
  `test_local_evidence_mlx_runtime_contract / _runtime_environment / _runtime_project / _isolated_wrapper`
  **17 passed** — model download 0.

---

## 2. Gate B1 — SELECT-only 가용성

### 2.1 판정 표 (probe 산출)

- selector_version: `local-vlm-evidence-selector-v1`
- overall_verdict: **BLOCKED_DATA_INSUFFICIENT**
- camera_count: **3** · date_count: **6**
- pool_sha256: **`6edd80f44875489e2d961dd218bfb98695a7a0a072ef0d7d9575ff5ee00cf776`**
- manifest_emitted: **False** (180 manifest 미생성)
- total_source_rows: **2678** → total_episodes: **64**
- excluded_counts: `unclassified_clips=0`, `episode_deduped_clips=2614`
- per_clip_stratum_distribution: `hardcase=1257, big_move=898, rest_micro=523` (absent/lick/wheel 0)

| stratum | episodes | verdict | single-camera% | blockers |
|---|---:|---|---:|---|
| absent | **0** | BLOCKED_DATA_INSUFFICIENT | 100.0% | no_candidates |
| big_move | **14** | BLOCKED_DATA_INSUFFICIENT | 50.0% | below_target_30 |
| rest_micro | **3** | BLOCKED_DATA_INSUFFICIENT | 66.7% | below_target_30 |
| lick_water_food | **0** | BLOCKED_DATA_INSUFFICIENT | 100.0% | no_candidates |
| wheel_object | **0** | BLOCKED_DATA_INSUFFICIENT | 100.0% | no_candidates |
| hardcase | **47** | DATA_AVAILABLE | 33.3% | - |

**camera/date 분포 (요약, 상세는 aggregate JSON):**
- hardcase 47: cam `5b3e…`20 / `9011…`10 / `f659…`17; 날짜 07-17(4)·07-18(13)·07-19(11)·07-20(12)·07-21(7)
- big_move 14: cam 4/3/7; 날짜 07-17~07-21 분산
- rest_micro 3: cam 2/1; 날짜 07-07·07-18·07-19

### 2.2 왜 부족한가 (root cause — owner 판단 근거)

전 clip(2678)이 **per-clip 으론 전부 분류**된다(미분류 0). 병목은 분류가 아니라 **다양성·episode dedup**:

1. **다양성 부족이 지배적** — 매칭 evidence 가 있는 clip 은 **camera 3대 / 촬영 6일** 뿐. 모션 트리거
   특성상 한 카메라가 밤에 연속 발화 → 30분 rolling dedup 으로 2678 clip → **64 episode** 로 수축.
   6×30=180 을 채우려면 절대 episode 수가 모자란다.
2. **absent 는 구조적으로 굶는다** — conflict priority 최하위(`… > big_move > absent`)라, episode 안에
   big_move/hardcase clip 이 하나라도 있으면 그 episode 를 뺏긴다. 게다가 `excursion_count>0` 이
   2480/2678 clip 에 있어(모션 트리거라 당연) 대부분 clip 이 big_move/hardcase 로 먼저 분류됨 →
   absent 로 남는 episode 가 0.
3. **lick_water_food / wheel_object = 0** — 이 두 strata 는 사람 신호(behavior_logs / current_gt)에
   의존하는데, 설계 §6.1 대로 **사람 라벨은 `camera_clips` 세계**에 있고 evidence 정본 `motion_clips`
   와 **ID 교집합 0**. 그래서 evidence clip 에는 human_actions/current_gt 가 붙지 않는다(각각 0건).
4. hardcase 47 만 임계 통과 — no_bbox(347)·activity `unknown`(1257) 신호가 풍부.

> **함의:** 이건 selector 버그가 아니라 **현재 운영 데이터 자체의 한계**다. 6×30 blind GT 를 채우려면
> (a) 카메라/개체/사육장 다양성 확대 + 촬영일 확보, 또는 (b) semantic strata(lick/wheel/absent) 정의·
> retrieval 신호 재설계(new `selector_version`) 가 선행돼야 한다. 어느 쪽이든 **새 방향 = decision-gate +
> 새 handoff** 대상이며 이 세션에서 임의로 selector 를 튜닝하지 않았다.

### 2.3 독립 재계산 대조 (Step 3)

summary helper(`build_availability`)를 **import 하지 않고** fresh `load_sources` + `build_episode_candidates`
로 재계산 후 대조:

| 항목 | aggregate | 독립 재계산 | 일치 |
|---|---|---|---|
| per-stratum episode 수 | 0/14/3/0/0/47 | 0/14/3/0/0/47 | ✅ |
| pool_sha256 | `6edd80f4…` | `6edd80f4…` | ✅ |
| camera_count / date_count | 3 / 6 | 3 / 6 | ✅ |
| pool clip 중복 | 0 (64 unique) | 0 (64 unique) | ✅ |
| pool artifact clip set | — | 재계산 pool 과 동일 | ✅ |

→ **INTEGRITY: MATCH** (B1_REJECT_INTEGRITY 아님). pool_sha256 은 최초 run·재계산·drift 이후까지 동일 = 결정론 확인.

---

## 3. SELECT-only / mutation 0 증거 (Step 4)

- **probe 는 구조적으로 read-only** — `insert/update/upsert/delete/rpc` 미사용. `r2_key` 는 재생 판정에만
  in-memory, 산출물·SourceRow 에 미기록. write flag 없음. 테스트가 mutation 호출 0 을 강제
  (`tests/test_probe_local_vlm_evidence_candidates.py`).
- **mutation baseline 재대조** (baseline `17:21:06Z` → recheck `17:28:14Z`):

  | table | baseline | after | 판정 |
  |---|---:|---:|---|
  | behavior_labels | 258 | 258 | 불변 |
  | behavior_logs | 1539 | 1539 | 불변 |
  | clip_labeling_sessions | 42 | 42 | 불변 |
  | clip_activity_assessments | 6727 | 6727 | 불변 |
  | clip_vlm_jobs | 551 | 551 | 불변 |
  | clip_prelabels | 6787 | 6787 | 불변 |
  | clip_python_evidence_runs | 2678 | 2678 | 불변 |
  | motion_clips | 16631 | **16638 (+7)** | **외부 라이브 캡처 유입** (내 probe 아님) |
  | local_vlm_evidence_studies/candidates/annotations | 부재 | 부재 | B2/B3 전 — 정상 |

  `motion_clips` +7 은 **캡처 워커의 실시간 유입**이다. 근거: (a) 라벨/행동/활동/evidence/VLM 테이블은
  전부 byte-불변, (b) `clip_python_evidence_runs` 는 2678 로 불변 → 새 raw clip 은 아직 매칭 evidence 가
  없어 후보 세계에 안 들어옴 → drift 이후 재계산 pool_sha256 이 동일. 내 probe 는 아무것도 쓰지 않았다.
- **model download/inference 0, Slack 0, LaunchAgent/service 변경 0, R2 write 0** — 어떤 모델/HF/mlx/R2
  upload/presign 도 호출하지 않음. 격리 런타임 offline 테스트는 B0 검증용 pytest 였고 다운로드 0.

---

## 4. 산출물·git 상태 (Step 6)

**tracked (commit 대상):**
- `experiments/local-vlm-evidence-analyst/candidate-availability.json` — aggregate (counts/분포/selector version/pool SHA/verdict; per-clip·r2_key 없음)
- `experiments/local-vlm-evidence-analyst/CANDIDATE-AVAILABILITY.md` — 사람용 verdict
- `docs/handoff-prompts/2026-07-22-local-vlm-evidence-b1-report.md` — 이 보고서

**git-ignored (per-clip artifact, 절대 커밋 안 함, `storage/` = .gitignore line 29):**
- `storage/local-vlm-evidence-analyst/candidate-pool.json` — per-clip pool (clip_id·provenance·identity; r2_key/signed URL 없음)
- `storage/local-vlm-evidence-analyst/mutation-baseline.json` — 감사용 baseline

**코드 커밋 (feature branch `codex/local-vlm-evidence-web-gt`):**
- `c25540f` feat: Local VLM evidence 후보 selector 추가 (Task 1)
- `f62a97b` feat: Local VLM 후보 가용성 SELECT probe 추가 (Task 2)
- `1217d46` fix: B1 aggregate 후보 집계 정확화 (dedup 흡수 vs 미분류 분리) — live probe 발견
- (+ 이 보고 커밋)

**테스트:** feature branch `uv run pytest` = **707 passed** (baseline 660 + Task1 31 + Task2 14 + fix 2).

**per-clip pool untracked/ignored 확인:** `git check-ignore` 로 3개 storage 파일 전부 무시 확인.

---

## 5. 하드 스톱 & 다음 (Step 11)

- **verdict 무관 Task 3 에서 STOP.** B1_BLOCKED_DATA_INSUFFICIENT 이므로 **B2 금지**가 확정이다
  (hardcase 외 5 strata 가 30 미만). 전부 충족했어도 owner 검토 + 새 handoff 전엔 B2 시작 안 함.
- **owner 결정 필요 (decision-gate 대상):**
  1. 데이터 다양성 확대(카메라/개체/사육장/촬영일) 후 B1 재실행할지,
  2. semantic strata 정의·conflict priority·retrieval 신호를 재설계(new selector_version)할지,
  3. 6×30 계약 자체(strata 구성·개수)를 조정할지.
- 어떤 선택이든 model download·inference·B2 코드/migration 은 **새 handoff 전까지 금지** 유지.
