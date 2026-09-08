---
handoff_version: 1
task_id: rap-c500g-field-maintenance
execution_repo: /Users/baek-end/.codex/worktrees/rap-c500g-field-maintenance/petcam-lab
plan_path: /Users/baek-end/.codex/worktrees/rap-c500g-field-maintenance/petcam-lab/docs/superpowers/plans/2026-09-07-c500g-field-maintenance.md
design_path: /Users/baek-end/.codex/worktrees/rap-c500g-field-maintenance/petcam-lab/docs/superpowers/specs/2026-09-07-c500g-field-maintenance-design.md
commit_sha: ab11ae4c1fa09c7a16a3c2e4736591f1bba8d751
implementation_host: baeg-endeuui-Macmini.local
runtime_kind: launchagent
runtime_host: baeg-endeuui-Macmini.local
runtime_label: com.teraai.rap-c500g-manager
---

# RAP C500G 화요일 현장 정비 handoff

## Bootstrap SHA와 final SHA

`commit_sha`는 design, plan, Task 1~6 구현과 검증 기록을 포함한 bootstrap commit이다. final HEAD는 이 manifest만 추가한
한 개의 descendant commit이다. `verify_agent_handoff.py`는 bootstrap SHA가 plan/design을 포함하고
final HEAD와의 변경이 이 manifest 하나뿐인 기존 프로젝트 패턴을 검증한다. 구현자는 literal
`HANDOFF_OK` 전에는 Task 1을 시작하지 않는다.

## Task 6 verification

- C500G focused/readiness suite: `172 passed`
- full suite: `2570 passed, 5 skipped, 5 failed`
- C500G 관련 실패: `0`
- 범위 밖 실패: 잘못된 절대 Python 경로 1건, news runtime 환경 probe 2건, 로컬 PostgreSQL 미기동 2건
- compileall, diff-check, credential pattern scan: pass
- production runtime/service/FFmpeg: read-only 확인
- canary, prune execute, USB/R2/DB/network write, deploy: `0`

현재 구현 판정은 `FIELD_MAINTENANCE_IMPLEMENTED_VERIFIED`다. Task 7 현장 canary와 배포는 이
handoff 범위에서 실행하지 않는다.

## Runtime ownership

- implementation host: `baeg-endeuui-Macmini.local`
- runtime host: `baeg-endeuui-Macmini.local`
- runtime kind: `launchagent`
- exact service label: `com.teraai.rap-c500g-manager`
- starting runtime SHA: `7b0d19e9039ab5fd46089e4a86c80e99e5df8d63`

## Absolute safety boundary

현재 운영 worktree `/Users/baek-end/.codex/worktrees/rap-c500g-capture-first/petcam-lab`, service,
plist, SQLite, USB recording, R2 object, DB row는 구현·테스트 동안 변경하지 않는다. 배포 단계에서도
target label 하나만 다루며 canary 실패 시 이전 plist와 runtime HEAD로 복원한다. local/R2/DB evidence는
삭제·이동·덮어쓰기하지 않는다.

local prune은 기본 dry-run이다. exact mount/root, final manifest, R2 size/SHA, DB 완료, active/pipeline
제외와 plan digest가 모두 맞고 Owner가 실행을 승인한 경우만 검증된 local bundle을 개별 삭제한다.

실측 production local root는 `/Volumes/RAP-C500G/RAP-c500g-recordings`다. execute 직전에 exact
mountpoint, volume device identity, root device/inode, lexical/resolved containment를 다시 확인하고
symlink를 하나라도 만나면 중단한다. DB는 `capture_status=captured`, `upload_status=uploaded`,
`manifest_r2_key/uploaded_at` 존재를 요구하고, local pipeline `verified_uploaded`와 R2 manifest-last
size/SHA를 finalization 증거로 함께 요구한다. current slot, active/partial/stale artifact, 현재·직전
night, 실패·미완료 pipeline, 복구용 manifest/log는 삭제 대상이 아니다.

prune receipt는 삭제 트리 밖인
`/Users/baek-end/Library/Application Support/rap-c500g-manager/prune-audit`에 0700/0600으로
write-new-only 저장한다. USB 포맷, R2/DB delete, broad glob delete는 금지한다.

LaunchAgent의 로그인 의존성은 readiness 결과로만 보고한다. auto-login을 자동 설정하거나 credential을
요청·저장하지 않는다. slot capture는 경계 직전 SIGINT graceful stop과 bounded SIGKILL fallback으로
다음 슬롯 시작 p95 `<=2초`를 검증한다.

비밀값, 전체 RTSP URL, webhook URL을 stdout, Git, event, Slack에 출력하지 않는다.

## 2026-09-08 Extreme SSD preparation extension

- exact mount: `/Volumes/Extreme SSD`
- partition / physical device: `disk4s1` / `disk4`
- volume UUID: `7B1FBB20-01C3-35CF-B4B5-9A638AFFF177`
- filesystem / free: `ExFAT` / 약 `1.2 TB`
- dedicated root: `/Volumes/Extreme SSD/RAP-c500g-recordings`
- 기존 데이터: 약 `844.3 GB`, 보존 필수, 포맷 금지
- rollback storage: `/Volumes/RAP-C500G`

준비 단계는 dedicated root, 그 안의 bounded write/fsync/read/hash/delete probe, non-secret 설치 metadata만
허용한다. 기존 runtime/service/finalize, R2, DB, Slack, network는 변경하지 않는다. 새 root에서
3-camera 60초 canary와 R2/DB/Slack 검증이 전부 통과하기 전에는 production env/plist/root를 전환하지
않는다. 기존 USB prune은 R2+DB+local `verified_uploaded`와 exact digest guard를 요구하며 partial,
unverified, recovery staging, active/current bundle을 제외한다.

## 2026-09-08 Task 7 deployment evidence

- previous finalize: natural drain active 11→0, verified pipeline 327, active capture/FFmpeg 0
- new volume: exact UUID/device/ExFAT/RW, 64 MiB preparation probe hash match, residue 0
- predeploy 60초: local/R2 12/12, DB 3/3, decode 3/3, manifest-last 3/3
- predeploy 30분: 1799.963~1800.028초, local/R2 12/12, DB 3/3, decode 3/3,
  manifest-last 3/3, Slack 4/4 `2xx`
- postdeploy 60초: local/R2 12/12, DB 3/3, decode 3/3, manifest-last 3/3,
  Slack 4/4 `2xx`
- deployed service: exact label, maintenance WD, HEAD
  `385d7e40c82231a98fc56ee36894645630525099`, running, runs 1, exit 없음, idle FFmpeg 0
- active plan: revision 7, 20:00~08:00, cam01~03, retry 3, volume `Extreme SSD`
- readiness: sleep 0, autorestart 1, auto-login enabled, FileVault off, Ethernet default,
  camera 3/3, host/volume/service/HEAD/lifecycle pass
- capacity: 1,155,204,644,864 bytes free; 30분 실측 기반 7일 약 110.32 GB
- old USB prune: mount absent로 `SKIPPED`, delete 0
- residual boundaries: Wi-Fi off, runtime UUID direct recheck 미구현. exact name+actual mount guard와
  설치 metadata/preflight를 유지하고 저장장치 교체 시 Owner가 UUID를 재확인한다.
- verdict: `FIELD_MAINTENANCE_DEPLOYED_VERIFIED`
- pending observation: 2026-09-08 20:00 KST부터 자연 슬롯 2회. 이 evidence 전에는 plan Step 6을
  완료 처리하지 않는다.
