# S0.1 Frame Sampling Self-Healing — 실행 보고서

> task_id: `s0-frame-sampling-self-healing`
> handoff: `storage/handoffs/2026-07-16-s0-frame-sampling-self-healing-handoff.md`
> plan: `docs/superpowers/plans/2026-07-16-s0-frame-sampling-self-healing.md`
> design: `docs/superpowers/specs/2026-07-16-s0-frame-sampling-self-healing-design.md`
> 상태: **완료** — `PASS_WITH_COVERAGE_GAP` (Mac mini canary + 자연 hourly cycle + S0 재감사 완료)

## 0. 최종 판정

- **`PASS_WITH_COVERAGE_GAP`** — `frames_sampled=0` 데이터 계약 결함은 완전 해소(자가치유 배포 VERIFIED: Mac mini canary + 자연 hourly cycle 실측, 신규 불완전 evidence 0). S0 재감사 verdict = `S0_PASS_WITH_COVERAGE_GAP` (core_complete==policy_ready==2889). 잔여 gap 은 pre-existing strata coverage(카메라 `90119209` 0.70)뿐이며 결함과 무관.
- **S1 은 covered subset `5b3ea7aa`·`f6599924` 로만 계획 가능. 본 세션에서 S1 미착수.**
- 상태: **완료**.

## 1. Handoff 검증 (Task 1 Step 1)

- validator: `HANDOFF_OK task=s0-frame-sampling-self-healing repo=petcam-lab commit=93c719f6 runtime=launchagent@baeg-endeuui-Macmini.local`
- petcam-lab HEAD = `93c719f67d0f4a10f22471615b28040d9b6dc3dc` (manifest SHA 일치)
- gate `origin/main` = `9e39596bdb907a86496948f4bf3a13fe760d8222` (pinned 일치, drift 없음)
- nightly `origin/main` = `cbd2e09ed00857bdbd8a27c3f0483881c9abdbd6` (pinned 일치, drift 없음)
- nightly primary tree = `feat/vlm-basking-classification` + 미커밋(다른 세션). **건드리지 않음**, worktree 사용.

## 2. Live 불완전 evidence 조사 (Task 1 Step 2, read-only)

- 진단 snapshot(UTC): 약 `2026-07-16T13:36Z`
- `frames_sampled < 6` prelabel = **24건**, 전부 현재 `activity-v1` assessment가 참조 중 (`decision=unknown`).
  - frames 분포: `{0:14, 1:3, 3:3, 4:2, 5:2}`
  - 카메라: `f6599924`(P4 Cam 2 dev) 23건 + `90119209`(P4 Cam 3) 1건
  - historical/non-current low prelabel = **0** (relink 시 보존 대상은 24개 current prelabel 자신)
- ⚠️ 감사 snapshot(as-of 10:41Z) 당시 `frames_sampled=0` 4건 → 3시간 뒤 24건으로 증가. 결함이 매 cycle 활성 상태로 불완전 evidence를 계속 생성 중.

## 3. 근본 원인 진단 (Task 1 Step 3~5)

각 clip을 단일 `TemporaryDirectory`로 다운로드해 decode. detector/VLM 미실행. 산출물 즉시 삭제.

| 지표 | 결과 |
|---|---|
| `CAP_PROP_FRAME_COUNT` (meta_count) | 32~58 (0 아님) |
| indexed reads (`cap.set(POS_FRAMES)`+read, 12 target) | **0~5** 성공 |
| sequential 디코딩 가능 프레임 | **12~46 (전부 ≥ MIN=6)** |
| `db_frames == idx_ok` | 거의 전 clip 일치 → 워커의 indexed sampler가 live 실패 지점 |
| root cause 분류 | **24/24 = `indexed_seek_failure`** |
| `permanent_candidate` | **0** (전 clip 순차 fallback으로 복구 가능) |
| temp media (cleanup 후) | **0** |

**해석:** clip은 ~7fps sparse-keyframe H.264(≈5.5s). OpenCV `POS_FRAMES` 인덱스 seek이 비-keyframe에 착지해 read가 실패 → 0~5장만 획득. 순차 디코딩은 12~46장 정상. 따라서 설계 §4.2 fallback 트리거 "균등 index sampling 결과가 요청 수보다 적음"이 정확히 이 케이스를 커버한다. 설계가 상정한 `CAP_PROP_FRAME_COUNT=0`은 실제 live 원인이 아니지만, 동일 fallback이 두 경우를 모두 복구한다.

- **환경 주의:** 위 decode는 implementation host(BaekBook, 로컬 OpenCV/ffmpeg)에서 수행. Mac mini 런타임에서의 재현/복구는 Task 5 canary 전 pre-deploy 진단으로 교차확인한다(파일 특성상 동일 예상).

## 4. Gate sequential fallback (Task 2)

- worktree: `gecko-vision-gate-wt-s0`, branch `feat/s0-frame-sampling-self-healing` (base `9e39596`).
- 변경: `frame_sampling.py` — 기본 index 경로 불변, `len(out)<num_frames` 시 2-pass 순차 fallback
  (`_count_sequential_frames` O(1) 메모리 카운트 → `_sample_sequential` O(num_frames) 보관). 전 capture release.
- 테스트 5종(fake VideoCapture, 바이너리 fixture 없음): count=0/seek부족/정상불변/bounded/release.
  - `pytest tests/test_frame_sampling.py` → 9 passed · full → **65 passed** · `git diff --check` clean.
- R0003-frame-sampling-fallback.md (인프라 복구 명시).
- **commit `f182ea4b59c11bd9b7cf4dbb90dc2b2bc9ef022e`**, feature branch push 완료(merge 미실시).

## 5. Nightly write barrier + requeue (Task 3~4)

- worktree: `petcam-nightly-reporter-wt-s0`, branch `feat/s0-evidence-self-healing` (base `cbd2e09`). primary tree(`feat/vlm-basking-classification` + 미커밋) 미접촉.
- **Task 3 (write barrier):** `gate_runner.assess_clip` 이 sample 직후 `len(frames)<policy.min_frames`면
  `InsufficientSampleFrames(found,required)` raise (detector·store 도달 전). 경로 미노출(개수만).
  `process_batch` 가 failed 격리·store 미호출·다른 clip 계속, `run()` 실패 시 rc 1.
- **Task 4 (requeue self-heal):** `list_unprocessed_clips` 완료 판정을 2단계로 강화 — assessment 참조
  prelabel 이 존재하며 `frames_sampled>=min_frames`여야 완료. 불완전/prelabel 소실 → 재선정.
  재처리 시 옛 0프레임 prelabel 보존 + `(clip_id,policy)` assessment 만 새 완전 prelabel 로 relink.
  worker 가 `min_frames=policy.min_frames` 명시 전달(회귀 가드 테스트 포함).
- 테스트: gate_runner 6 · activity_worker(+relink/regression/insufficient) · activity_indexer 15(신규 requeue 경계 0/5/6/missing/mixed-1200).
  - **full suite 297 passed · `compileall` ok · `git diff --check` clean.**
- **commit `19a1fe56792cf43497da8884b9c42ac8db51b5ba`**, feature branch push 완료(merge 미실시).

## 6. 배포 + Mac mini canary (Task 5)

### Step 1 — cross-repo contract (로컬 완료)
- nightly → Gate editable 의존은 **상대 형제 경로** `../myPythonProjects/gecko-vision-gate`
  (`tool.uv.sources`, editable). Mac mini 에서 Gate main pull 시 nightly 가 자동으로 새 sampler 사용.
- Gate feature 65 passed · nightly feature 297 passed (개별 suite).
- **실 데이터 end-to-end 실측:** 새 Gate `sample_frames` 를 불완전 clip 24건에 직접 실행 →
  **24/24 모두 12프레임 복구**(기존 0~5 → 12), temp media 0. 순차 fallback 이 실제 seek-fail 파일에서 동작 확인.

### Step 2 — fast-forward main push (완료)
- 두 origin/main 이 pinned base 그대로임을 재확인 후 FF push(비-force):
  - Gate main: `9e39596 → f182ea4` (feature parent == base, linear)
  - nightly main: `cbd2e09 → 19a1fe5`

### Step 3 — pre-deploy snapshot (Mac mini, 완료)
- host `baeg-endeuui-Macmini.local` (`home-mac` alias, BatchMode+IdentityFile).
- repos: `~/petcam-nightly-reporter`(main cbd2e09) · `~/myPythonProjects/gecko-vision-gate`(main 9e39596), pre-pull.
- LaunchAgent `com.petcam.activity-worker`: program `/opt/homebrew/bin/uv run python -m reporter.activity_worker`,
  `StartInterval=3600`, WorkingDirectory `~/petcam-nightly-reporter`, env `ACTIVITY_EXPECTED_HOST`·`ACTIVITY_POLICY_VERSION=activity-v1`, last exit 0, not running.
- nightly untracked `.env.bak-20260708-vlmoff` 존재 → **미접촉**.
- pre-deploy incomplete current assessment = **24** (IDs frozen `/tmp/s0_predeploy_incomplete.json`).
- table baseline: motion_clips 12976 · clip_prelabels 3056 · clip_activity_assessments 3056. temp media 0.

### Step 4 — deploy Gate→nightly (Mac mini, 완료)
- `launchctl bootout` → 스케줄 중단 확인 → `git pull --ff-only`(Gate `f182ea4`·nightly `19a1fe5`, untracked 보존)
  → `uv sync --frozen`(91 pkg, 변화 없음) → editable Gate 가 pulled sibling(`~/myPythonProjects/gecko-vision-gate/src`)로 resolve 확인.
- Mac mini 전체 테스트: **Gate 65 passed · nightly 297 passed**. → `launchctl bootstrap`(plist 불변) → loaded.
- ⚠️ 비-interactive shell PATH 에 `/opt/homebrew/bin` 없음 → 모든 원격 명령에 PATH 선주입(cron-launchd PATH 교훈).

### Step 5 — canary cycle (kickstart, 완료)
- `launchctl kickstart -k` 1회(14:09:25Z). 로그: `cameras=3 queried=55 ok=55 reused=0 fail=0 active=18 absent=0 static=2 unknown=35 avg=2.25s max=8.61s`.
- **fail=0** → barrier 가 발동하지 않음(전 clip ≥6프레임 = fallback 성공). unknown=35 는 policy 레벨 fail-open(insufficient_frames 아님).
- **relink 실측:** 옛 prelabel(3/1프레임) 보존 + current assessment 는 새 12프레임 prelabel 로 relink(1789dfae·1791455b·2a9cfc4a 확인).
- **current_incomplete = 0** (pre 24 → 0). 새 `frames_sampled<6` 행 생성 0(historical <6 세트 24 불변).
- count 귀속: clip_prelabels +55(신규 완전 evidence) · assessments +31(신규 clip 31; relink 24 는 upsert=무증가). temp media 0. hostname guard 통과(정상 실행).
- hostname guard·다른 LaunchAgent 불변. **kickstart 만으로 VERIFIED 주장 안 함 → Step 6 자연 cycle 대기.**

### Step 6 — 자연 hourly cycle 관찰 (완료)
- 자연 fire **15:11Z** (canary 14:09Z + ~1h, kickstart 아님). 로그:
  `cameras=3 queried=45 ok=45 reused=0 fail=0 active=12 absent=1 static=0 unknown=32 avg=2.35 max=18.72`.
- HEAD 불변(gate `f182ea4` · nightly `19a1fe5`), last exit 0, temp media 0.
- **DB 검증:** current_incomplete = **0** 유지 · historical `<6` prelabel = **24 불변**(신규 `frames_sampled<6` 생성 0) ·
  clip_prelabels +45(신규 완전 evidence, ok=45와 일치) · assessments +45(전부 신규 clip). fail=0 = barrier 미발동 = 전 clip ≥6프레임.
- **결론:** kickstart 뿐 아니라 자연 cycle 도 불완전 evidence 를 만들지 않음 → 배포 VERIFIED.

### Step 7 — rollback readiness
- 미발동(중단 조건 해당 없음). rollback 절차는 준비됨: `launchctl bootout` → 두 구현 커밋 역순 revert(normal revert, force 금지) → main push → Mac mini pull → 서비스 복구 → 로그 보존. feature branch(f182ea4/19a1fe5)와 base(9e39596/cbd2e09) 모두 원격 보존.

## 7. S0 재감사 (Task 6)

- 동일 인자 재실행(as-of만 갱신), 새 출력 경로(과거 보고서 미덮어씀):
  ```
  uv run python scripts/audit_python_evidence_coverage.py \
    --start 2026-07-14T00:00:00+09:00 --as-of 2026-07-17T00:14:57+09:00 \
    --policy-version activity-v1 --regular-selector-version budget-router-v1 \
    --output reports/python-evidence-s0-coverage-20260716-rerun
  ```
- **verdict: `S0_PASS_WITH_COVERAGE_GAP`** (snapshot `a57f1c3d9f91f5b3`, lab HEAD `93c719f`).
- coverage: eligible **2942** / any_prelabel **2889** / policy_ready **2889** / **core_complete 2889**.
  - `core_complete == policy_ready` → `frames_sampled>0` 계약 **충족**(첫 감사의 HOLD 사유 해소). `core_incomplete_clip_shorts: []`.
- **독립 재조정(read-only, 별도 SQL):** eligible 2942 ✅ 일치 · current_incomplete **0** ✅(audit core_incomplete=[]와 일치) ·
  historical `<6` prelabel **24 보존**(현재 assessment 미참조 = 이력과 현재 링크 구분) · 감사 전후 테이블 총계 불변(3156/3132) = **audit mutation 0**.
- **잔여 coverage gap (pre-existing, 결함 무관):** `policy_ready_below_80:90119209:0.7`
  (카메라 `90119209` 07-14 7/34=20.6% → 전체 0.70). `f6599924` 07-14 0/25 는 첫 감사에도 있던 0% strata.
- **S0 gate 적용:** `S0_PASS_WITH_COVERAGE_GAP` → **covered subset(policy_ready≥80%) = `5b3ea7aa`(100%)·`f6599924`(82.1%)** 로만 S1 한정, 전체 카메라/기간 일반화 금지. **S1 미착수.**
- SOT 추가 갱신(이력 보존): `docs/superpowers/specs/2026-07-16-python-evidence-hybrid-design.md`(§12 rollout 표 S0.1 행 + §17-1) · `specs/next-session.md`(🟢 블록, 🟠 HOLD 는 SUPERSEDED 표기 후 보존).

## 8. 금지 행동 미수행 체크리스트 (모두 준수)

- ✅ nightly primary tree(`feat/vlm-basking-classification` + 미커밋) 미접촉 — 전 작업 별도 worktree.
- ✅ Mac mini nightly untracked `.env.bak-20260708-vlmoff` 미접촉(pull --ff-only, 배포 전후 존재 확인).
- ✅ DB migration·직접 UPDATE/DELETE/보정 RPC 없음 — 기존 24 불완전 prelabel 보존, relink 은 워커 정상 upsert 로만.
- ✅ VLM/Claude/selector/backfill/GT/behavior label/앱 활동시간 설정 변경 없음.
- ✅ production runtime 변경은 `com.petcam.activity-worker` 단일 서비스만(bootout→pull→bootstrap, plist 불변). 타 LaunchAgent 불변.
- ✅ force-push·reset·branch -D 없음 — 전부 fast-forward(비-force) + normal push.
- ✅ 비밀값 커밋 없음(보고서·감사 산출물에 r2_key/키/토큰 없음, secret scan clean).
- ✅ kickstart 단독으로 VERIFIED 주장 안 함 — 자연 hourly cycle 관찰 후 판정.
- ✅ S1 미착수.

## 9. 최종 산출물 요약

- **진단:** 불완전 24건 전부 `indexed_seek_failure`, 0 permanent (순차 fallback 로 24/24 실 데이터 복구 실측).
- **구현 커밋(prod main):** Gate `f182ea4` · nightly `19a1fe5`. 테스트 Gate 65 · nightly 297 (로컬+Mac mini).
- **배포 증거:** canary(queried=55 ok=55 fail=0) + 자연 cycle 15:11Z(queried=45 ok=45 fail=0), 둘 다 신규 불완전 0·temp 0·exit 0·HEAD 불변.
- **현재 링크 카운트:** pre-deploy current-incomplete **24** → post **0**. 옛 24 prelabel 보존.
- **S0 재감사:** `S0_PASS_WITH_COVERAGE_GAP` (계약 충족, covered subset 한정).
- **rollback readiness:** 준비됨, 미발동.
