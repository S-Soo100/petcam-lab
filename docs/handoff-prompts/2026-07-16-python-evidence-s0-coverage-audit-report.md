# Python Evidence Hybrid — S0 Coverage Audit 검수 보고서

> task_id: `python-evidence-s0-coverage-audit` · execution_repo: `/Users/baek/petcam-lab` · runtime_kind: `none`
> handoff: `storage/handoffs/2026-07-16-python-evidence-s0-coverage-audit-handoff.md`
> Codex 독립 검수용. production 은 read-only 로만 접근했다.

## 0. 최종 판정

- **감사 무결성 판정: VERIFIED** — 독립 SQL 재조정이 `summary.json` 과 완전히 일치했고, 감사 실행이 production 을 변경하지 않았다(아래 §7).
- **S0 coverage 판정: `S0_HOLD_DATA_CONTRACT`** — core completeness 99.85%(2630/2634). camera `f6599924` 의 4건 evidence 가 `frames_sampled=0` 으로 필수 provenance 계약(`frames_sampled>0`, 설계 §5.3)을 위반한다.
- **결론: S1 벤치마크 착수 보류.** `frames_sampled=0` 원인 규명·해소 후 재감사한다. 이 감사는 selector/threshold/자동제외/행동라벨/앱 활동시간을 변경하지 않는다.

## 1. 감사 파라미터

| 항목 | 값 |
|---|---|
| snapshot_id | `213586c2a3bd6f0c` |
| as_of | `2026-07-16T19:41:02+09:00` (KST) / `2026-07-16T10:41:02+00:00` (UTC) |
| start | `2026-07-14T00:00:00+09:00` (KST) / `2026-07-13T15:00:00+00:00` (UTC) |
| policy_version | `activity-v1` |
| regular selector | `budget-router-v1` |
| execution/data HEAD (petcam-lab) | `7f2390eb098016db13367590f298310494469e2d` |
| runtime HEADs (설계 SOT 인용, 본 감사서 재검증 안 함 — DB read-only) | nightly `cbd2e09` · gate `9e39596` |

실행 명령:

```bash
AS_OF="2026-07-16T19:41:02+09:00"
uv run python scripts/audit_python_evidence_coverage.py \
  --start 2026-07-14T00:00:00+09:00 --as-of "$AS_OF" \
  --policy-version activity-v1 --regular-selector-version budget-router-v1 \
  --output reports/python-evidence-s0-coverage-20260716
# exit 2 (S0_HOLD_DATA_CONTRACT), 산출물 5종 생성
```

## 2. 카메라 × KST 날짜 coverage

| camera_short | camera_name | KST 날짜 | eligible | any_prelabel | policy_ready | core_complete | any_prelabel_ratio | policy_ready_ratio |
|---|---|---|---|---|---|---|---|---|
| 5b3ea7aa | P4 Cam (dev) | 2026-07-14 | 671 | 671 | 671 | 671 | 1.0 | 1.0 |
| 5b3ea7aa | P4 Cam (dev) | 2026-07-15 | 1138 | 1138 | 1138 | 1138 | 1.0 | 1.0 |
| 5b3ea7aa | P4 Cam (dev) | 2026-07-16 | 751 | 744 | 744 | 744 | 0.9907 | 0.9907 |
| 90119209 | P4 Cam 3 | 2026-07-14 | 34 | 7 | 7 | 7 | 0.2059 | 0.2059 |
| 90119209 | P4 Cam 3 | 2026-07-15 | 3 | 3 | 3 | 3 | 1.0 | 1.0 |
| 90119209 | P4 Cam 3 | 2026-07-16 | 40 | 36 | 36 | 36 | 0.9 | 0.9 |
| f6599924 | P4 Cam 2(dev) | 2026-07-14 | 25 | 0 | 0 | 0 | 0.0 | 0.0 |
| f6599924 | P4 Cam 2(dev) | 2026-07-16 | 38 | 35 | 35 | 31 | 0.9211 | 0.9211 |

**0% coverage strata:** camera `f6599924` 2026-07-14 (25 clip 전부 prelabel 0). `f6599924` 는 2026-07-15 eligible clip 0 이라 행 없음.

## 3. evidence identity · core completeness

- 단일 detector identity: `gecko_v2 (checkpoint_best_ema)` / `gate-evidence-v1` / checkpoint `cd1162b4…2bef17` / threshold `0.1` / sampler `even-uniform-v1`.
- `frames_sampled` 분포(unique clips): **12→2615**, 9→5, 10→3, 11→2, 8→1, 5→1, 4→1, 3→1, 1→1, **0→4**.

| 지표 | 값 |
|---|---|
| total_eligible motion clips | 2700 |
| any_prelabel unique clips | 2634 (97.6%) |
| policy_ready (`activity-v1` + 유효 prelabel 참조) | 2634 |
| core_complete (필수 provenance/presence/motion 8키 완비) | 2630 |
| **core incomplete** | **4** — 전부 `frames_sampled=0` (camera `f6599924`, 2026-07-16 18:44~18:59 KST, clip shorts `3af66f0a`/`679e9e52`/`7af0e302`/`fa112350`) |

`gecko_bbox=null`·`best_frame_ts=null` 은 absent evidence 에서 정상이라 결손으로 세지 않았다(§5.3). core incomplete 원인은 전적으로 `frames_sampled=0`.

## 4. selector 시점 coverage (정규/backfill 분리)

| selector_kind | selector_version | runs | jobs | 비고 |
|---|---|---|---|---|
| regular | `budget-router-v1` | 5 | 19 | 전부 camera `5b3ea7aa`. 다른 두 카메라는 감사 창에서 정규 run 0 |
| backfill | `budget-router-backfill-20260707-14-v1` | 71 | 266 | 대부분 window 가 감사 시작(2026-07-14) 이전이라 window_clips=0 |

정규 run window-time availability(estimate, `prelabel.created_at <= run.created_at`):

| run_short | window (KST) | window_clips | with_prelabel_at_run | availability |
|---|---|---|---|---|
| 907a1c7e | 07-15 00:00~02:00 | 44 | 40 | 0.909 |
| 0d65f89e | 07-15 02:00~04:00 | 50 | 46 | 0.920 |
| 43266e70 | 07-15 20:00~22:00 | 100 | 66 | 0.660 |
| 9997b4ef | 07-15 22:00~00:00 | 106 | 64 | 0.604 |
| e2caf6d1 | 07-16 00:00~02:00 | 80 | 58 | 0.725 |

**exact / estimate / not_reconstructable (합산 금지):**
- **exact** = `clip_vlm_jobs` FK(`prelabel_id`/`activity_assessment_id`) 로 선택 결과에 실제 연결된 evidence. 정규 job 19건 중 prelabel 연결은 run 별 표에 그대로.
- **estimate** = window `[window_start, window_end)` 안 motion clip 중 selector 실행 시점(`created_at`) 이전에 prelabel 이 있던 비율. 근사치이며, 감사 시작 이전 window(backfill 다수)는 motion clip 이 로더 범위 밖이라 window_clips=0 로 과소집계된다(경계 caveat, 명시).
- **not_reconstructable** = episode reduction·제외 전 eligible pool 의 clip 단위 snapshot 은 저장되지 않는다. 집계치·선택 clip 으로 정확 pool 을 복원하지 않는다.

## 5. 독립 재조정 (Task 5 Step 3)

동일 경계(`started_at`/`created_at` ∈ [`2026-07-13T15:00:00Z`, `2026-07-16T10:41:02Z`))로 별도 SQL 을 돌려 `summary.json` 과 대조했다.

| 지표 | 독립 SQL | summary.json | 일치 |
|---|---|---|---|
| eligible motion clips | 2700 | 2700 | ✅ |
| any_prelabel unique clips | 2634 | 2634 | ✅ |
| policy_ready unique clips | 2634 | 2634 | ✅ |
| 정규 selector runs | 5 | (source_counts 76 중) | ✅ |
| backfill selector runs | 71 | (source_counts 76) | ✅ |
| 정규 jobs | 19 | (source_counts 285 중) | ✅ |
| backfill jobs | 266 | (source_counts 285) | ✅ |
| selector runs 합계 | 76 | 76 | ✅ |
| jobs 합계 | 285 | 285 | ✅ |

모든 핵심 총계가 일치 → 감사 무결성 확인.

## 6. 판정과 S1 권고 (범위 한정)

- verdict = **`S0_HOLD_DATA_CONTRACT`** (core completeness 99.85% < 100%).
- **S1 착수 보류**: 4건 `frames_sampled=0` evidence 의 producer(activity-worker/gate_runner, camera `f6599924`) 를 규명·해소한 뒤 동일 명령으로 재감사한다.
- 재감사가 `S0_PASS` 면 전 카메라 S1, `S0_PASS_WITH_COVERAGE_GAP` 면 policy_ready≥80% covered subset(현 시점 `5b3ea7aa`)으로만 진행하고 일반화 금지.
- selector 시점 관측상 정규 selector 가 `5b3ea7aa` 한 대에만 도는 점, 최근 정규 run availability 가 ~60% 인 점은 S1 유입량·표본 설계에서 별도로 다룬다(이 감사는 selector 를 바꾸지 않음).

## 7. production 무변경 증거 (Task 5 Step 1·4)

7개 소스 테이블 row count, 감사 전/후:

| 테이블 | 전 | 후 | 변화 |
|---|---|---|---|
| cameras | 3 | 3 | 0 |
| motion_clips | 12781 | 12785 | **+4** |
| clip_prelabels | 2877 | 2877 | 0 |
| clip_activity_assessments | 2877 | 2877 | 0 |
| clip_vlm_selector_runs | 76 | 76 | 0 |
| clip_vlm_jobs | 285 | 285 | 0 |
| camera_activity_filter_settings | 3 | 3 | 0 |

`motion_clips` +4 는 **감사가 만든 것이 아니다**: 그 4건은 `started_at ≥ as_of` 이고 `created_at ≥ as_of` 로 frozen window 밖의 신규 카메라 캡처다(동시 실행 중인 capture producer). frozen window eligible count 는 재조회 시에도 그대로 **2700** 이라 snapshot 결정성이 유지된다. 감사는 SELECT 전용이라 clip 을 INSERT 할 수 없고, `producer_run_id`·migration·write 로그를 남기지 않았다. → mutation 귀속 없음.

## 8. 변경 파일 · 테스트 · commit/push

**변경/신규:**
- `scripts/audit_python_evidence_coverage.py` (신규, read-only 감사 도구)
- `tests/test_audit_python_evidence_coverage.py` (신규, 22 테스트)
- `reports/python-evidence-s0-coverage-20260716/{summary.json,camera_date_coverage.csv,selector_time_coverage.csv,identity_distribution.csv,REPORT.md}` (신규 산출물 5종)
- `docs/superpowers/specs/2026-07-16-python-evidence-hybrid-design.md` (§12 S0 행·§17-1 실측 반영, 이력 보존, S1 미착수)
- `specs/next-session.md` (S0 감사 결과 1블록 추가)
- `docs/handoff-prompts/2026-07-16-python-evidence-s0-coverage-audit-report.md` (본 보고서)

**테스트:** `uv run pytest -q` = 전체 통과(감사 테스트 22 포함). `git diff --check` clean. 산출물/보고서 placeholder 없음. mutation 정적 스캔(`.insert(`/`.update(`/`.delete(`/`.upsert(`/`.rpc(`) = 감사 스크립트에 0건.

**commit/push:** parent = `7f2390eb098016db13367590f298310494469e2d`. 위 파일만 stage 해 커밋 메시지 `docs: Python evidence S0 coverage 감사 완료` 로 커밋 후 `origin/main` fast-forward push. 본 보고서를 포함한 커밋의 최종 SHA 는 push 후 `git log`(및 채팅 회신)로 확인한다(자기참조 회피). 기존 미추적 파일은 stage/수정/삭제하지 않는다.

## 9. 미실행(계약상 금지) 행동 목록

이 감사에서 **하지 않은** 것:
- DB write / migration / RPC / INSERT / UPDATE / DELETE / UPSERT
- R2 다운로드 · 영상 디코딩 · detector / OpenCV / Claude / VLM 호출
- Slack 전송 · LaunchAgent / 스케줄 / 환경변수 변경
- selector / batch / prompt / threshold 변경
- 자동 skip / 자동 GT / behavior label / 앱 활동시간 변경
- **S1 벤치마크 착수** (설계 §12 대로 보류)
- exact / estimate / not_reconstructable 수치 합산
