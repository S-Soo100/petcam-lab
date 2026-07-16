# Activity Worker Single-Host Migration — Closure Report

작성: 2026-07-16 (implementation host `BaekBook-Pro-14-M5.local`).
선행 보고서(불변): `2026-07-16-activity-worker-single-host-migration-report.md`.

## 1. 최종 판정

**VERIFIED** — 움직임 요약 시간창 소수 정밀도 버그를 복구했고, Git/runtime 정합(Mac mini HEAD == origin/main == final commit)과 `activity-worker` 의 **자연 두 번째 StartInterval 실행**(runs=2, exit 0)을 kickstart/수동실행/재bootstrap 없이 관측해 single-host 이전을 마감했다.

## 2. 시간창 버그 원인과 수정

- 원인: `reporter/worker.py` `_format()` 의 `disp_start = disp_end - timedelta(hours=int(config.WINDOW_HOURS))` 에서 `int(0.5)=0` 으로 잘려, 기본값 `WINDOW_HOURS=0.5` 일 때 창이 `02:00~02:00`(0폭)으로 표기됨.
- 수정(최소): `int()` 제거 → `disp_start = disp_end - timedelta(hours=config.WINDOW_HOURS)`. formatter 문구·Slack 구조·조회 시간창 로직 무변경.
- 결과: `WINDOW_HOURS=0.5 → 01:30~02:00`, `WINDOW_HOURS=2.0 → 00:00~02:00`.
- 참고: production movement worker 는 plist 에서 `WINDOW_HOURS=2` 를 override 해 카드가 이미 2h 로 정상 표기돼 왔음 → 이 버그는 소수(30분) 계약에서만 발현되는 잠재 결함이었고, 이번 수정으로 30분 계약이 단위 테스트로 고정됨.

## 3. RED→GREEN 및 전체 테스트 결과

- RED(수정 전): `test_format_movement_summary_shape` 가 실제 `02:00~02:00` 로 FAIL. 2h 계약을 `monkeypatch(config.WINDOW_HOURS, 2.0)` 로 명시하고 30분 회귀 테스트(`test_format_preserves_fractional_window_hours`, 0.5 → `01:30~02:00`) 추가 후 → 30분 테스트만 RED(`1 failed, 4 passed`).
- GREEN(수정 후): `tests/test_worker.py` **5 passed**.
- 전체 `uv run pytest -q` → **284 passed** (직전 세션의 `282 passed, 1 failed` 에서 pre-existing 실패 해소 + 회귀 테스트 1개 추가).
- `compileall reporter` OK, `bash -n install-launchd-activity.sh` OK, `git diff --check` OK.
- scoped diff: `worker.py` 1줄(int 제거) + `test_worker.py`(config import·shape 시그니처·30분 테스트 1개) 외 변경 없음.

## 4. final commit SHA와 origin/main

- FINAL commit: **`cbd2e09ed00857bdbd8a27c3f0483881c9abdbd6`** (`fix: 움직임 요약 시간창 소수 정밀도 복구`, staged 3파일: `reporter/worker.py`, `tests/test_worker.py`, closure plan).
- push: fast-forward `c0e0eb9..cbd2e09 → origin/main`. `HEAD^ == origin/main`(직전) 확인, force 없음. remote `refs/heads/main` == HEAD 확인.

## 5. HANDOFF_OK 전문과 manifest 경로

manifest: `/Users/baek/petcam-lab/docs/handoff-prompts/2026-07-16-activity-worker-single-host-manifest.md`
(task_id `activity-worker-single-host-closure`, commit_sha `cbd2e09…`, plan=closure plan, design=single-host design).

```
HANDOFF_OK task=activity-worker-single-host-closure repo=petcam-nr-activity-wt commit=cbd2e09e runtime=launchagent@baeg-endeuui-Macmini.local
```

출력 `commit=cbd2e09e` = `git rev-parse --short=8 HEAD` 와 일치.

## 6. Mac mini HEAD/plist/launchctl

- `git pull --ff-only origin main` → HEAD `cbd2e09ed00857bdbd8a27c3f0483881c9abdbd6` (== FINAL_SHA). `.env.bak-20260708-vlmoff` 보존(commit/삭제 없음).
- plist 무변경(재설치/bootout/bootstrap/kickstart 없음): `ACTIVITY_EXPECTED_HOST=baeg-endeuui-Macmini.local`, `ACTIVITY_POLICY_VERSION=activity-v1`, `StartInterval=3600`, `WorkingDirectory=/Users/baek-end/petcam-nightly-reporter`.
- launchctl: `state = not running`, `runs = 2`, `last exit code = 0`.

## 7. 자연 두 번째 cycle 증거

- launchd `StartInterval=3600` 이 만든 자연 실행: **runs=2**, `last exit code=0`.
- 로그: `[activity] 07-16 08:25 cameras=3 no unprocessed clips` (08:25 UTC = **17:25 KST**, 첫 RunAtLoad 16:23 KST 종료 ~1h 후). kickstart/수동/재bootstrap 아님.
- 두 번째 cycle 은 **정상 early-return**(미처리 clip 0 → detector 미로드, exit 0, `queried=` summary 없음). 첫 cycle 이 88건을 모두 처리해 이후 신규 미처리가 없었음.
- DB 근거: Mac mini prelabel `producer_run_id` 는 `{20260716T072301: 88}` 단일(첫 cycle) — 08:25 run 은 신규 evidence 0. no-work 정합.

## 8. MacBook absent 재확인

- `launchctl print … com.petcam.activity-worker` → service not found.
- `~/Library/LaunchAgents/com.petcam.activity-worker.plist` absent.
- 백업 보존: `~/Library/LaunchAgents/activity-worker-decommissioned-20260716-162235/com.petcam.activity-worker.plist`.

## 9. DB producer/identity/settings/금지 테이블 대조 (read-only, production service-role client)

| 지표 | 값 | 판정 |
|---|---|---|
| assessments producer=MacBook | 2703 (max_created 2026-07-16T05:29:34Z, 이전 前) | 이전 이후 신규 0 ✓ |
| assessments producer=Mac mini | 88 (max_created 2026-07-16T07:25:56Z = 첫 cycle) | 자연 2nd run 신규 0 ✓ |
| assessments total / prelabels total | 2791 / 2791 | 정합 ✓ |
| Mac mini prelabel run_ids | `{20260716T072301: 88}` | 단일 cycle ✓ |
| evidence 7컬럼 identity 결손 | 0 | ✓ |
| identity 중복 그룹 | 0 | ✓ |
| camera_activity_filter_settings | 3 카메라 activity-v1, exclude_absent 전부 false, exclude_static = `5b3ea7aa`만 true | baseline 대비 불변 ✓ |
| behavior_labels total | 258 | 불변 ✓ |
| clip_vlm_jobs total | 229 → **255 (+26)** | **이 작업 무관** ↓ |

- **clip_vlm_jobs +26 귀속**: activity worker 경로(`activity_worker`/`activity_store`/`activity_indexer`/`activity_settings`/`gate_runner`)는 `clip_vlm_jobs` 를 **참조조차 하지 않음**(grep 결과 NONE — 이 worker 는 `clip_prelabels` + `clip_activity_assessments` 만 upsert). +26 은 독립 스케줄 worker `com.petcam.vlm-historical-backfill`(runs=8, 07~19 KST calendar, 이번 작업에서 무수정)의 정상 backfill job 생성분이다. single-host 이전과 인과 없음.

## 10. temp media와 secret scan

- Mac mini `/tmp` mp4/`*frame*` = 0건(worker `TemporaryDirectory`+`unlink` 정리, `/tmp/petcam-activity-worker.lock` flock 파일만 잔존).
- `/tmp/activity-worker.log` secret 패턴(`cloudflarestorage|token=|SUPABASE_SERVICE|r2.`) = 0.

## 11. 미검증 또는 잔여 위험

- **3회차+ hourly cycle**: runs≥3 및 야간(20~06 KST) 고모션 시간대 대량 배치 처리량/오류율은 미관측(현재 검증 = 첫 cycle 88건 + 2nd no-op).
- **재부팅/재로그인 자동 로드**: GUI 로그인 시 RunAtLoad 자동 기동 미검증.
- **movement Slack 카드 실물**: 시간창 수정은 unit test 로 고정됐고 Mac mini 코드에 반영(다음 movement worker run 이 새 코드로 자동 spawn)됐으나, 다음 자연 movement Slack emission(22:05 KST 계열)의 실물 카드는 closure 시점에 미관측. production movement worker 는 `WINDOW_HOURS=2` override 라 표기가 이미 정상이었으므로 회귀 위험 낮음.
- **전체 pytest**는 284 passed(무실패)로, 직전 pre-existing 실패는 해소됨.

## 12. Codex 가 SOT 에 반영할 정확한 문구

> petcam-lab 의 dirty next-session/설계 파일은 다른 세션 소유라 이 세션에서 수정하지 않았다. 아래를 해당 SOT 에 반영할 것:

```
[activity-worker single-host 이전 — 2026-07-16 CLOSURE VERIFIED]
- activity-worker 유일 production runtime = Mac mini (baeg-endeuui-Macmini.local,
  LaunchAgent com.petcam.activity-worker, policy activity-v1, StartInterval 3600).
  MacBook(BaekBook-Pro-14-M5.local) absent(백업 보존). 두 호스트 loaded 수 = 1.
- 코드 정본: petcam-nightly-reporter origin/main cbd2e09 (= Mac mini HEAD).
  포함: ACTIVITY_EXPECTED_HOST fail-closed host guard + partial-failure nonzero exit +
  clip 실패 로그 위생 + 움직임 요약 시간창 소수 정밀도 복구(reporter.worker._format).
- 실사이클: 1st RunAtLoad queried=88 ok=88 fail=0 exit0(evidence +88 전량 Mac mini producer,
  7컬럼 결손 0·중복 0); 2nd 자연 StartInterval run=2 exit0 no-op(미처리 0).
- 불변: exclusion settings, behavior_labels(258). clip_vlm_jobs 증가(+26)는 독립
  vlm-historical-backfill worker 소관으로 activity 이전과 인과 없음.
- 자매 레포 규칙: worker 코드/실험은 petcam-lab 이 아니라 petcam-nightly-reporter 에서만 작업.
```

---
산출물: 이 closure report · manifest(§5) · nightly-reporter closure plan/design(§4 commit) · commit `cbd2e09`.
Codex 독립 검수(보고서·양쪽 host·Git·DB) 전에는 SOT 최종 마감으로 주장하지 않는다.
