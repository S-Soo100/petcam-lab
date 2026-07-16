# activity-worker Single-Host Migration — 실행 보고서

작성: 2026-07-16 (implementation host `BaekBook-Pro-14-M5.local`)

## 1. 최종 판정

**VERIFIED** — `activity-worker` 의 유일한 production runtime 이 Mac mini
(`baeg-endeuui-Macmini.local`) 로 이전됐고, Mac mini 에서 `activity-v1` 실사이클 1회가
`queried=88 / ok=88 / fail=0 / exit 0` 로 완료됐다. 완료 조건(§2) 전항 충족.

## 2. 원인과 기존 오배치 증거

- **오배치**: `com.petcam.activity-worker` 가 상시 가동 Mac mini 가 아니라 휴대용 MacBook
  (`BaekBook-Pro-14-M5.local`, working dir `/Users/baek/petcam-nightly-reporter`) 에 loaded,
  `runs=38`. Mac mini 는 absent 였다.
- **DB 증거**: 이전 전 `clip_activity_assessments` 2703건 전량이 `producer_host=BaekBook-Pro-14-M5.local`
  (MacBook), `producer_host=baeg-endeuui-Macmini.local`(Mac mini) = **0건**. 즉 모든 evidence 를
  잘못된 호스트가 써 왔음이 producer_host 로 입증됨.
- **취약점 2가지**:
  1. activity worker 에 host guard 부재 → 어느 host 에서나 실행 가능(VLM candidate worker 는
     `require_expected_host` 로 이미 보호됨).
  2. `run()` 이 `process_batch` 의 `failed` 와 무관하게 항상 `return 0` → MacBook 네트워크 불안
     cycle(`queried 55 / ok 43 / fail 12`, `RemoteProtocolError`/`ConnectError`/DNS)이 exit 0 으로
     정상처럼 기록됨.

## 3. 변경 파일과 구현 계약

repo: `petcam-nightly-reporter` (worktree `/Users/baek/petcam-nr-activity-wt`, base `origin/main` b9dc9eb).

| 파일 | 변경 | 계약 |
|---|---|---|
| `reporter/config.py` | `ACTIVITY_EXPECTED_HOST` env 추가(기본 `""`) | §5.1 |
| `reporter/activity_worker.py` | (1) `run()` 최상단(lock/DB/R2/detector/Slack 이전) fail-closed host guard(`require_expected_host` 재사용), 실패 시 side effect 0회+`return 2`. (2) `return 1 if stats["failed"] else 0`. (3) clip-skip 로그에서 예외 전문 제거(타입명만) | §5.1 §5.3 |
| `install-launchd-activity.sh` | expected host 누락/불일치 abort, plist 에 `ACTIVITY_EXPECTED_HOST` 주입, 자동 hostname 승인 없음 | §5.2 |
| `tests/test_activity_worker.py` | 기존 run() 테스트 guard-통과 인자 주입 + host guard/partial-failure/로그위생 신규 테스트 | |
| `tests/test_install_activity_launchd.py` (신규) | installer 계약 테스트(render/lint/abort/정적검사) | |
| `specs/2026-07-16-activity-worker-single-host-design.md`, `docs/superpowers/plans/2026-07-16-activity-worker-single-host-migration.md` (신규) | 설계/계획 정본 | §4 |

Python Evidence Hybrid selector, VLM batch, Gate threshold, DB schema, policy preset 값, exclusion
설정, 타 LaunchAgent 는 무변경.

## 4. RED→GREEN 및 전체 테스트 결과

- **RED**(구현 전): `tests/test_activity_worker.py tests/test_install_activity_launchd.py` → **14 failed, 9 passed**
  (guard 인자 미지원 TypeError, installer host guard 부재, 로그 위생 미적용).
- **GREEN**(구현 후, targeted): **23 passed**.
- **전체 pytest**(`uv run pytest -q`): **282 passed, 1 failed**.
  - 유일 실패 = `tests/test_worker.py::test_format_movement_summary_shape` (상황판 worker 의
    시간창 표기 `00:00~02:00` 기대 vs `02:00~02:00`). 이 파일과 `reporter/worker.py` 는 **origin/main
    과 byte-identical**(`git diff --quiet origin/main` 확인) → 이 task 이전부터 존재하던 실패이며
    `WINDOW_HOURS 2h→0.5h` drift 가 원인. activity worker 와 무관·범위 밖이라 미수정.
- `uv run python -m compileall reporter` OK, `bash -n install-launchd-activity.sh` OK,
  `git diff --check` clean.
- installer plist fixture(임시 HOME/stub launchctl) 검증 = `test_install_activity_launchd.py` 4 테스트
  + Mac mini 실기 dry render(§8) 로 이중 확인.

## 5. commit SHA와 push 상태

- 코드 commit: **`3610f15c753a248679c5b1897e140320b1b97a5a`** (fix: host guard + partial-failure + 로그 위생).
- SOT 문서 commit: **`c0e0eb99a890616c473027b2d1943ce868d28ba6`** (docs: next-session VERIFIED 반영).
- push: 둘 다 `origin/main` 으로 **fast-forward** (`b9dc9eb..3610f15`, `3610f15..c0e0eb9`). force push 없음.
- push 전 origin/main 이 시작 SHA `b9dc9eb` 에서 변하지 않음을 재확인 후 push. 현재 origin/main = `c0e0eb9`.

## 6. HANDOFF_OK 전문과 manifest 절대경로

manifest: `/Users/baek/petcam-lab/docs/handoff-prompts/2026-07-16-activity-worker-single-host-manifest.md`
(commit_sha = 코드 commit `3610f15…`, runtime_kind=launchagent, runtime_host=`baeg-endeuui-Macmini.local`,
runtime_label=`com.petcam.activity-worker`).

검증 명령: `cd /Users/baek/petcam-lab && uv run python scripts/verify_agent_handoff.py --manifest <위 경로>` → exit 0:

```
HANDOFF_OK task=activity-worker-single-host repo=petcam-nr-activity-wt commit=3610f15c runtime=launchagent@baeg-endeuui-Macmini.local
```

handoff gate 는 runtime 이전 **착수 전**에 통과됨(올바른 순서).

## 7. MacBook 최종 plist/launchctl 상태와 백업 경로

- 이전 전 상태: `state = not running`, `runs = 38`, `last exit code = 0` (실행 중 아님 → 안전하게 중단).
- 비파괴 이동: plist 를 `~/Library/LaunchAgents/activity-worker-decommissioned-20260716-162235/com.petcam.activity-worker.plist`
  로 `mv`(삭제 아님, 보존).
- `launchctl bootout gui/<uid>/com.petcam.activity-worker` → **plist ABSENT**(원경로), **service ABSENT**.
- 백업 디렉터리는 보존(삭제 금지 준수).

## 8. Mac mini hostname/HEAD/plist/launchctl 상태

- hostname: `baeg-endeuui-Macmini.local` (expected host 일치).
- repo HEAD: `git pull --ff-only origin main` 후 **`3610f15c753a248679c5b1897e140320b1b97a5a`**
  (= manifest commit_sha, 검증된 runtime SHA). 워킹트리 clean(유일 untracked = `.env.bak-20260708-vlmoff`, 보존).
- preflight 9/9: SSH·hostname·repo·origin 동기화·`.env` 6키 존재·Gate checkpoint(120MB) 존재·기존 5개
  LaunchAgent 유지·activity-worker absent(설치 전)·시각 16:18 KST(VLM 22/00/02/04·backfill 07 창과 무충돌).
- 실기 dry render(stub launchctl): 정상 host → plist lint OK + `ACTIVITY_EXPECTED_HOST=baeg-endeuui-Macmini.local`
  + `ACTIVITY_POLICY_VERSION=activity-v1` + WorkingDirectory 정상. host 누락/불일치 → 설치 abort.
- 실설치: plist `~/Library/LaunchAgents/com.petcam.activity-worker.plist`,
  `state = not running` + `last exit code = 0`(첫 cycle 후), WorkingDirectory `/Users/baek-end/petcam-nightly-reporter`.
- **두 호스트 전체 loaded 수 = 정확히 1** (MacBook absent, Mac mini loaded).

## 9. 첫 실사이클 queried/ok/fail/exit/runtime

```
[activity] 07-16 07:23 cameras=3 queried=88 ok=88 reused=0 fail=0 active=61 absent=2 static=5 unknown=20 avg=1.95s max=8.63s model=gecko_v2 (checkpoint_best_ema) policy=activity-v1
```

- hostname Mac mini, policy `activity-v1`, **exit code 0**, `queried = ok = 88`, `fail = 0`.
- detector/checkpoint 정상 로드(`model=gecko_v2`), RunAtLoad 로 즉시 1회 실행 후 정상 종료.
- 처리 대상 확인: 이전 직전 read-only 로 미처리 clip 87건(직전) → cycle 시점 88건 관측(모션 clip 지속 유입),
  queried=88 로 정합. `queried>0` 실사이클(§195 충족, 처리 0 아님).

## 10. DB pre/post 및 금지 테이블 불변 증거

| 지표 | pre | post | Δ |
|---|---|---|---|
| clip_prelabels total | 2703 | 2791 | +88 |
| clip_activity_assessments total | 2703 | 2791 | +88 |
| assessments producer=MacBook | 2703 | 2703 | 0 (신규 MacBook 쓰기 없음) |
| assessments producer=Mac mini | 0 | 88 | +88 (신규 evidence 전량 Mac mini) |
| behavior_labels total | 258 | 258 | **0 (불변)** |
| clip_vlm_jobs total | 229 | 229 | **0 (불변)** |

- **증분 정합**: +88 = queried 88 = ok 88 = Mac mini prelabels 88. 처리량과 DB 증분 일치.
- **evidence identity 결손 0**: Mac mini prelabels 88건 전부 7컬럼(clip_id/model_version/schema_version/
  checkpoint_sha256/threshold/sampler_version/frames_sampled) null 0.
- **중복 evidence 0**: 7컬럼 identity 그룹 count>1 = 0.
- `behavior_labels`(GT 포함)·`clip_vlm_jobs` 변경 0.

## 11. settings 와 앱 effective policy 불변 증거

- `camera_activity_filter_settings` 3행이 pre/post **byte-동일**: 3 카메라 모두 `enabled=true`,
  `active_policy_version=activity-v1`. exclusion 스위치 = 카메라 `90119209`/`f6599924`
  `exclude_absent=false, exclude_static=false`, 카메라 `5b3ea7aa` `exclude_static=true`(나머지 false).
- 이전 과정에서 어떤 exclusion/DB setting 도 변경하지 않음(§217 우회 금지 준수). effective activity
  정책은 이 settings 로부터 파생되며 settings 불변 = effective policy 불변.

## 12. temp media 0 및 secret leak 0 증거

- Mac mini `/tmp/*.mp4` = 0건(worker `TemporaryDirectory` + `dest.unlink` 정리). `frame` 잔재 없음.
  `/tmp/petcam-activity-worker.lock` 만 잔존(flock 파일, 정상·재사용).
- 로그 secret/URL 스캔(`cloudflarestorage|token=|SUPABASE_SERVICE|r2\.`) = **0 hits**. 로그는 rfdetr
  FutureWarning + `[activity] … queried=` summary 만 포함.

## 13. 아직 검증되지 않은 항목

- **hourly 자동 재발화**: `StartInterval=3600` 의 다음 정기 cycle(첫 RunAtLoad 이후 1h) 자동 실행은 아직 미관측.
- **재부팅/재로그인 자동 로드**: GUI 로그인 시 RunAtLoad 자동 기동은 이번 세션에서 미검증.
- **야간 대량 배치**: 검증은 daytime(88건). 야간(20~06 KST) 고모션 시간대 대량 처리량·소요시간·오류율은 미검증.
- **전체 pytest 1건 실패**(§4, `test_worker.py`)는 pre-existing·범위 밖으로 미수정(별도 후속).

## 14. rollback 절차

이중 실행 방지가 최우선 — **한 시점에 한 호스트만** activity-worker loaded.

1. Mac mini 롤백: `ssh home-mac 'launchctl bootout gui/$(id -u)/com.petcam.activity-worker && rm ~/Library/LaunchAgents/com.petcam.activity-worker.plist'`.
2. MacBook 복원(Mac mini bootout **완료 후에만**): 백업 plist 를 `~/Library/LaunchAgents/` 로 복원 후
   `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.petcam.activity-worker.plist`.
   백업 = `~/Library/LaunchAgents/activity-worker-decommissioned-20260716-162235/`.
3. 코드 롤백 필요 시: origin/main 에 fix commit 을 **새 revert 커밋**으로 되돌림(force push·reset --hard 금지).
- DB setting/exclusion 변경으로 우회하지 않음. 데이터 삭제 금지.

## 15. petcam-lab SOT 정정 문구 (Codex 독립 검수 후 반영)

> petcam-lab 의 dirty next-session/설계 파일은 다른 세션 소유라 이 세션에서 수정하지 않았다.
> 아래 문구를 petcam-lab 의 해당 SOT(활동필터/파이프라인 운영 기록)에 반영할 것:

```
[activity-worker 단일 호스트 이전 — 2026-07-16 VERIFIED]
- activity-worker(활동필터 Gate worker)의 유일한 production runtime = Mac mini
  (hostname baeg-endeuui-Macmini.local, LaunchAgent com.petcam.activity-worker, policy activity-v1).
- MacBook(BaekBook-Pro-14-M5.local)에서는 제거(absent). 두 호스트 전체 loaded 수 = 1.
- 코드: petcam-nightly-reporter origin/main 3610f15 — ACTIVITY_EXPECTED_HOST fail-closed host guard +
  partial-failure nonzero exit + clip 실패 로그 위생(예외 전문 미출력). 잘못된 host/미설정 시
  DB/R2/detector/Slack 이전에 nonzero 종료.
- 첫 실사이클: cameras=3 queried=88 ok=88 fail=0 exit0, DB evidence +88(전량 Mac mini producer,
  7컬럼 결손 0·중복 0), exclusion·behavior_labels(258)·clip_vlm_jobs(229) 불변.
- worker 코드/실험은 petcam-lab 에서 직접 건드리지 않고 petcam-nightly-reporter 에서 작업(자매 레포 규칙).
```

---
증거 산출물: manifest(위 §6 경로) · nightly-reporter `specs/2026-07-16-activity-worker-single-host-design.md`
· `docs/superpowers/plans/2026-07-16-activity-worker-single-host-migration.md` · commit `3610f15`/`c0e0eb9`.
