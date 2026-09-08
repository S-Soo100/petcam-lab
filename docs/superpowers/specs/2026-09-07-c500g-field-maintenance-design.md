# RAP C500G 화요일 현장 정비 설계

> 30분 슬롯을 절대 벽시계 경계로 닫고, 녹화부터 DB 완료까지의 생명주기와 저장공간 위험을 관측하며, 화요일 현장 점검을 한 시간 안에 가역적으로 끝낸다.

**상태:** Task 1~6 구현 검증 완료, 현장 canary·배포 대기

**작성:** 2026-09-07

**기준 runtime:** `7b0d19e9039ab5fd46089e4a86c80e99e5df8d63`

**실측 production local root:** `/Volumes/RAP-C500G/RAP-c500g-recordings`

**승인된 교체 target root:** `/Volumes/Extreme SSD/RAP-c500g-recordings`

**관련 문서:**

- [RAP C500G 녹화 우선·원본 즉시 R2 파이프라인](2026-09-03-rap-c500g-capture-first-pipeline-design.md)
- [RAP C500G recorder 운영 절차](../../runbooks/rap-c500g-recorder.md)

## 1. 문제와 실측 근거

2026-09-03~05의 production manifest 216개를 읽기 전용으로 대조했을 때 시작 지연과 영상
길이의 상관계수는 `-1.000`이었고, 재시작 극단치를 제외한 207개에서도 `-0.9999`였다.
`영상 길이 + 시작 지연` 중앙값은 `1783.0초`로, 현재 코드의 17초 reserve와 정확히 맞는다.

문제는 FFmpeg `-t`가 벽시계가 아니라 입력 media timestamp를 따라간다는 점이다. 실제 벽시계
실행시간은 저장된 media duration보다 중앙값 `31.0초`, p95 `45.2초`, 최대 `53.0초` 길었다.
이전 MP4의 마지막 기록시각은 다음 00/30분 경계보다 중앙값 `14초`, p95 `28초`, 최대 `36초`
늦었고, 이 값과 다음 슬롯 시작 지연의 상관계수는 `0.9764`였다. 첫 슬롯은 약 0.35초 안에
시작했으므로 카메라별 네트워크 장애보다 이전 child 종료가 다음 child를 막는 공통 경계 문제가
우세하다.

별도 capture, raw upload, daytime finalize executor 구조는 유지한다. 후처리는 주원인이 아니며,
이번 변경은 이 분리를 되돌리지 않는다.

## 2. 목표

1. 각 카메라 FFmpeg child를 media clock과 무관한 절대 벽시계 deadline에 정상 종료한다.
2. 정상 야간에서 다음 슬롯 시작 지연 p95를 2초 이하로 만들고 24개 슬롯에 지연이 누적되지 않게 한다.
3. 예정·실제 시작, capture 종료, raw R2, finalize, DB 완료를 한 슬롯 생명주기로 추적한다.
4. manager 시작·정상 종료·fatal·launchd 재시작 단서를 append-only로 남긴다.
5. Slack 호출 결과와 USB 잔여 GiB·예상 녹화 일수를 원장과 알림으로 확인한다.
6. R2와 DB에 최종 완료가 증명된 로컬 bundle만 기본 dry-run, 명시 실행으로 정리한다.
7. 화요일 현장에서 전원·LAN·카메라·USB·launchd를 확인하고 3카메라 30분 canary까지 한 시간 안에 끝낸다.

## 3. 비목표와 절대 경계

- 승인된 exact Extreme SSD로의 저장 root 전환 외 외장하드 교체는 하지 않으며, 포맷·파티션 변경은 항상 금지한다.
- 기존 local/R2/DB 원본을 자동 삭제하거나 덮어쓰지 않는다.
- production DB schema를 바꾸지 않는다. lifecycle은 기존 local SQLite append-only event를 쓴다.
- C500G codec, 해상도, RTSP 경로, 20:00~08:00 계획, 30분 슬롯, 카메라 3대 계약을 바꾸지 않는다.
- raw upload와 daytime full decode/finalize 분리를 되돌리지 않는다.
- 새 daemon이나 service label을 만들지 않는다.
- 카메라 firmware, SD 카드, 네트워크 설정을 자동 변경하지 않는다.
- FileVault를 끄거나 비밀번호를 파일에 기록하지 않는다.
- 비밀값, 전체 RTSP URL, webhook URL을 상태·로그·Slack·문서에 기록하지 않는다.

## 4. 절대 wall-clock capture deadline

### 4.1 종료 계약

매니저가 슬롯을 claim할 때 다음 값을 고정한다.

- `scheduled_start_kst`: 00/30분 예정 경계
- `scheduled_end_kst`: 정확히 다음 30분 경계 또는 08:00
- `actual_start_kst`: capture worker가 시작한 시각
- `graceful_stop_at`: `scheduled_end_kst - 3초`
- `force_kill_at`: `scheduled_end_kst - 1초`

FFmpeg의 `-t`는 출력 media duration 상한으로 유지하지만 종료의 정본으로 사용하지 않는다.
벽시계가 `graceful_stop_at`에 닿으면 manager가 직접 소유한 해당 child에만 `SIGINT`를 보내 MP4
trailer를 닫게 한다. 2초 안에 종료하지 않으면 해당 child에만 `SIGKILL`하고 그 slot을
`capture_deadline_forced`로 실패 처리한다. 종료 신호는 PID 재사용을 피하도록 보유한 `Popen`
객체에만 전달한다.

SIGINT 뒤 FFmpeg가 종료 코드 255를 반환해도 deadline 요청에 의해 시작된 종료이고 ffprobe·파일
승격 검사가 통과하면 정상 capture로 인정한다. 다른 nonzero 종료나 강제 종료는 성공으로 승격하지
않는다. `.part` 파일은 증거로 보존하고 다음 슬롯을 막지 않는다.

### 4.2 스케줄 계약

- manager tick은 현재 1초를 유지한다.
- 이전 child가 `force_kill_at` 뒤에도 `_active`에 남을 수 없게 완료 수거를 먼저 한다.
- 같은 카메라의 두 RTSP 세션을 겹쳐 띄우지 않는다.
- 늦게 시작한 슬롯도 종료 경계는 연장하지 않는다.
- graceful stop과 bounded force-kill은 항상 다음 00/30분 경계 전에 끝나야 한다.
- 재시도는 같은 절대 deadline 안에서만 가능하다.
- 24개 합성 슬롯에서 시작 오차가 다음 슬롯로 누적되면 테스트 실패다.

### 4.3 운영 acceptance

- 3카메라 30분 canary에서 시작 지연 p95 `<=2.0초`
- 카메라별 다음 슬롯 시작 최대 지연 `<=3.0초`
- stale FFmpeg 0
- MP4 ffprobe·전체 decode 3/3
- raw R2 size/SHA 3/3, final manifest-last 3/3, DB 완료 3/3
- 강제 종료·재시도·누락 0

## 5. 슬롯 lifecycle 원장

기존 `manager_event`를 append-only로 확장하고 새 production DB write는 만들지 않는다. 이벤트에는
`slot`, `camera_key`, 안전한 상태·시각·duration·bytes·attempt만 넣는다.

| 이벤트 | 기록 시점 | 필수 안전 필드 |
|---|---|---|
| `capture_scheduled` | claim 직전 | scheduled start/end |
| `capture_started` | child 시작 | actual start, start delay |
| `capture_stopped` | child 종료 | wall elapsed, signal, exit class |
| `raw_uploaded` | R2 HEAD 일치 | completed at, bytes |
| `finalize_started` | daytime worker claim | started at, attempt |
| `finalize_completed` | manifest-last 확인 | completed at |
| `db_synced` | DB upsert 반환 뒤 | completed at |
| `manager_started` | service process 시작 | boot marker, prior stop class |
| `manager_stopped` | 정상 signal 종료 | reason |
| `manager_fatal` | loop 예외 | 안전한 exception class |

이벤트 시각은 UTC ISO 8601로 저장하고 UI/Slack에서만 KST로 표시한다. 동일 slot/camera/stage의
성공 이벤트는 idempotency key로 한 번만 기록한다. restart 뒤에도 기존 event를 수정하지 않는다.

원장은 다음 파생값을 제공한다.

- slot start delay와 capture wall/media duration
- raw upload, finalize, DB sync 각각의 latency
- queued finalize와 실제 실행 중 worker 수
- process lifetime과 종료 이유
- nightly expected/captured/raw/finalized/db-synced gap

## 6. Slack delivery와 저장공간 경보

`SlackWebhookNotifier`는 호출 성공 여부를 버리지 않고 다음 안전 결과를 반환한다.

```text
delivered: bool
http_status_class: 2xx | 4xx | 5xx | transport_error | disabled
elapsed_ms: int
```

webhook URL, response body, request body 원문은 event에 저장하지 않는다. notifier 실패는 capture를
실패시키지 않지만 `slack_delivery` event로 남긴다. 같은 idempotency key의 성공 알림은 재전송하지
않고, 실패는 bounded backoff 정책으로 다음 manager tick에서 최대 3회까지만 재시도한다.

USB runway는 최근 완결된 최대 3개 night의 실제 local video bytes 평균으로 계산한다.

```text
estimated_nights = free_bytes / mean_completed_night_bytes
```

완결 night가 없으면 `insufficient_history`로 표시하고 임의 bitrate를 쓰지 않는다. 다음 중 하나면
`storage_runway_low`를 한 번 알린다.

- free bytes `< 35 GiB`
- estimated nights `< 2.0`

회복은 free bytes `>=40 GiB`이면서 estimated nights `>=2.5`일 때만 기록해 경계 진동을 막는다.
매 tick 전체 디스크를 스캔하지 않고 slot summary 또는 night acceptance 때만 갱신한다.

## 7. 안전한 local prune

2026-09-07 실측에서 `.env`의 `RAP_C500G_LOCAL_ROOT`, 실제 디렉터리, manager SQLite의
pipeline root가 모두 `/Volumes/RAP-C500G/RAP-c500g-recordings`로 일치했다. 새 CLI는 이 exact
root만 받고 항상 dry-run으로 시작한다. 삭제 후보 bundle은 아래 조건을 모두 만족해야 한다.

1. canonical mount가 정확히 `/Volumes/RAP-C500G`이고 실제 mountpoint이며 symlink가 아니다.
2. root가 정확히 `/Volumes/RAP-C500G/RAP-c500g-recordings`이며 lexical path와 resolved path가
   모두 이 root 안에 포함된다.
3. dry-run 때 고정한 volume device identity, mountpoint, root device/inode가 execute 직전에도 같다.
4. root, bundle, artifact 경로 어디에도 symlink가 없고 `..` 또는 다른 device로 탈출하지 않는다.
5. final local manifest가 존재하고 schema·bundle identity가 안전하다.
6. R2의 video/thumbnail/log/manifest HEAD가 local manifest의 size/SHA와 모두 일치한다.
7. R2 manifest가 마지막 object이고 최종 `r2_verified=true`다.
8. DB row는 `capture_status=captured`, `upload_status=uploaded`, `manifest_r2_key`와 `uploaded_at`이
   존재해야 한다. 현재 schema에는 별도 `finalized` 컬럼이 없으므로 local pipeline의
   `verified_uploaded`와 final manifest-last를 함께 finalization 증거로 쓴다.
9. current slot, active claim, partial/stale artifact, 현재·직전 night, pipeline 미완료·실패 bundle,
   재시작 복구에 필요한 manifest/log는 후보에서 제외한다.

dry-run은 candidate count/bytes, 제외 이유 count, plan digest만 출력한다. 실행에는
`--execute --plan-digest <dry-run digest>`를 동시에 요구한다. digest가 현재 재검증 결과와 다르면
아무것도 지우지 않는다. 삭제는 검증된 개별 bundle 안의 정확한 네 artifact와 빈 bundle 디렉터리만
대상으로 하며 glob, prefix delete, R2/DB delete는 사용하지 않는다. 한 건 실패하면 즉시 중단하고
남은 후보를 지우지 않는다.

receipt는 삭제 대상 USB 트리 밖인
`/Users/baek-end/Library/Application Support/rap-c500g-manager/prune-audit`에 둔다. 디렉터리는
0700, receipt는 write-new-only 0600이며 실행 전·후 receipt를 append-only로 보존한다. receipt path가
recording root 안이거나 parent가 symlink면 execute를 거부한다.

### 7.1 Extreme SSD 저장 root 전환 gate

Owner가 2026-09-08 기존 데이터를 보존한 채 다음 exact volume을 새 녹화 저장소로 준비하도록 승인했다.

- mount: `/Volumes/Extreme SSD`
- partition device / physical device: `disk4s1` / `disk4`
- volume UUID: `7B1FBB20-01C3-35CF-B4B5-9A638AFFF177`
- filesystem: `ExFAT`
- 실측 여유: 약 `1.2 TB`
- dedicated root: `/Volumes/Extreme SSD/RAP-c500g-recordings`

기존 약 `844.3 GB` 데이터는 이동·삭제·덮어쓰기하지 않고 포맷도 하지 않는다. 준비 단계에서는 exact
dedicated root와 non-secret 설치 metadata, 그 안의 bounded write/fsync/read/hash/delete probe만
허용한다. 기존 `/Volumes/RAP-C500G`와 그 runtime은 active finalize가 끝날 때까지 그대로 두며,
전환 실패 시 rollback 저장소로 유지한다.

production runtime root 전환은 새 root에서 3-camera 60초 canary와 local/R2/DB/Slack 검증이 모두
통과한 뒤에만 허용한다. 기존 USB prune은 R2와 DB 완료, local `verified_uploaded`, exact plan digest가
모두 일치할 때만 별도 실행하며 partial, unverified, recovery staging, active/current bundle은 항상
제외한다.

## 8. 화요일 1시간 현장 runbook

### 0~10분: 전원·부팅·저장장치

- Mac mini, 공유기, 카메라 3대 전원 어댑터와 케이블 고정을 눈으로 확인한다.
- UPS가 있으면 상시전원·배터리 표시만 확인하고 운영 중 강제 정전 시험은 하지 않는다.
- `/Volumes/RAP-C500G` 실제 mount, read-write, free space, device identity를 확인한다.
- USB 포맷·First Aid 쓰기·케이블 분리는 하지 않는다.
- `pmset -g custom`, FileVault, loginwindow 상태를 읽는다.
- Owner가 현장에서 승인한 경우에만 `sleep 0`, `autorestart 1`을 적용한다. FileVault는 끄지 않는다.
- 자동 로그인이 없으면 정전 뒤 LaunchAgent 시작에는 사용자 로그인이 필요하다는 사실만 체크리스트에
  남긴다. readiness 도구와 runbook은 auto-login을 설정하거나 비밀번호를 요청·저장하지 않는다.

### 10~20분: LAN·카메라

- 기본 route가 유선 Ethernet이고 Wi-Fi fallback에 의존하지 않는지 확인한다.
- gateway, `.23/.24/.25` TCP 554, 카메라별 bounded ffprobe를 확인한다.
- 카메라 이름·물리 위치·IP 대응, 전원, IR 반사, 초점, 가림, 낮/밤 전환을 눈으로 확인한다.
- 카메라 설정·firmware·SD 내용은 바꾸지 않는다.

### 20~30분: lifecycle·보존 검증

- service label, WorkingDirectory, exact HEAD, state DB, 현재 claim을 확인한다.
- local prune dry-run을 실행해 후보 count/bytes와 제외 이유를 본다.
- Owner가 plan digest와 R2/DB 완료 집계를 직접 확인한 경우에만 같은 digest로 실행한다.
- 외장하드 여유가 충분하면 삭제 실행을 생략한다.

### 30~60분: 3카메라 30분 canary

- production service를 graceful stop하고 active FFmpeg 0을 확인한다.
- 격리 runtime에서 test namespace 30분 canary를 세 카메라 동시에 시작한다.
- 시작 지연, stale process, local 12 artifacts, ffprobe/full decode, R2 HEAD size/SHA,
  manifest-last, DB test row 3개를 확인한다.
- canary가 전부 통과할 때만 production service를 bootstrap한다.
- 실패하면 새 runtime을 unload하고 기존 plist·HEAD로 rollback한다. canary artifact는 삭제하지 않는다.

## 9. 사용자 체험

```text
[현장 도착] Owner가 한 장짜리 체크리스트를 연다.
→ [10분] 전원·USB·자동복구 가능 여부를 확인한다.
→ [20분] 유선 LAN과 세 카메라 화면·IR을 확인한다.
→ [30분] 삭제 예정 용량을 dry-run으로 보고 실행 여부를 직접 결정한다.
→ [60분] 30분 canary가 끝나면 시작 지연·R2·DB 결과가 한 번에 PASS/FAIL로 나온다.
→ [이탈] PASS면 기존 단일 service가 계속 운영되고, FAIL이면 이전 runtime으로 돌아가 있다.
```

야간에는 slot Slack 한 건으로 capture/raw 상태를 보고, 오전에는 finalize/DB 완료를 별도 요약한다.
저장공간이 2일 미만이면 사람이 현장에 가기 전에 경보를 받는다.

## 10. 배포와 rollback

구현은 별도 worktree와 branch에서 끝내고 `HANDOFF_OK` 뒤에만 runtime 설치를 허용한다. 배포 시
`com.teraai.rap-c500g-manager`만 graceful bootout하며 다른 LaunchAgent는 변경하지 않는다.

배포 gate:

1. focused C500G suite와 전체 관련 회귀 통과
2. 기존 runtime baseline 원장과 local/R2/DB count 고정
3. 새 plist가 격리 repo exact SHA와 WorkingDirectory를 가리킴
4. 60초 synthetic canary와 30분 현장 canary 통과
5. 다음 자연 슬롯 2회 start delay p95 `<=2초`

실패하면 target service만 unload하고 이전 plist·runtime HEAD로 복원한다. SQLite, local, R2, DB row는
삭제하거나 되돌리지 않는다.

## 11. 완료 판정

- `FIELD_MAINTENANCE_IMPLEMENTED_VERIFIED`: 코드·테스트·dry-run·handoff만 통과
- `FIELD_MAINTENANCE_CANARY_VERIFIED`: 현장 30분 3카메라 canary까지 통과
- `FIELD_MAINTENANCE_DEPLOYED_VERIFIED`: 자연 슬롯 2회와 lifecycle/Slack/storage evidence까지 통과
- `FIELD_MAINTENANCE_ROLLED_BACK`: target service만 이전 runtime으로 복원

## 12. 2026-09-07 구현 검증 기록

Task 1~6은 격리 branch에서 구현했다. C500G focused/readiness suite는 `172 passed`였고,
compileall·diff-check·credential pattern scan이 통과했다. 전체 `uv run pytest -q`는
`2570 passed, 5 skipped, 5 failed`였으며 실패 5건은 C500G 변경과 무관한 기존 환경 probe다.
존재하지 않는 `/Users/baek/...` Python 절대경로 1건, news runtime probe 환경 불충족 2건,
로컬 PostgreSQL 미기동 2건으로 분리했다.

Task 6 리뷰에서 다음을 추가 보정했다.

- Slack 실패는 manager tick에서 5초·30초 간격, 최대 3회로 제한하고 성공 identity는 재전송하지 않는다.
- storage runway는 production verified item이 정확히 72개인 완결 night만 최근 3개 평균에 포함한다.
- prune candidate는 volume/root뿐 아니라 bundle·artifact inode를 고정하고 dirfd로 개별 unlink한다.
  실행 전·후 receipt는 파일과 디렉터리를 fsync한다.
- FileVault가 켜져 있으면 auto-login marker만으로 무인 LaunchAgent 복구 가능하다고 판정하지 않는다.

현재 판정은 `FIELD_MAINTENANCE_IMPLEMENTED_VERIFIED`다. 현장 30분 canary, 실제 prune, runtime 배포,
자연 슬롯 검증은 Task 7이며 아직 실행하지 않았다. 운영 service/FFmpeg는 기존 runtime에서 계속
동작했고 USB/R2/DB/network write와 production mutation은 0이다.
