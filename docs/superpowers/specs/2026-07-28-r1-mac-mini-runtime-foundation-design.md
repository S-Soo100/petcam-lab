# R1 Mac mini Research Runtime Foundation 설계

**상태:** Owner 승인 · Claude Desktop 독립 검토 반영 · 구현 전
**승인:** 2026-07-28
**상위 정본:** [`RBA 연구 시스템 v1`](2026-07-27-rba-research-system-v1-design.md) ·
[`AI 연구 운영 계약`](../../research/AI-OPERATING-CONTRACT.md)
**독립 검토:** [`Claude review`](../../handoff-prompts/2026-07-28-r1-mac-mini-runtime-foundation-claude-review-report.md)

## 1. 목적

Mac mini가 ChatGPT Desktop이나 MacBook 연결과 무관하게 승인된 연구 job을 실행하고, 재부팅과
sleep 뒤에도 중복 실행 없이 복구하며, MacBook·스마트폰에서는 SSH pull로 상태를 확인할 수 있는
최소 runtime foundation을 만든다.

R1은 연구 결과를 만드는 단계가 아니다. dataset, prompt, model, VLM 정확도, Python Evidence
효과를 측정하지 않는다. R1이 실행하는 실제 canary workload는 synthetic no-op뿐이다.

## 2. 범위

### 포함

- Mac mini 단일-host LaunchAgent runner의 코드와 설치 artifact
- local SQLite 현재 상태 ledger
- append-only JSONL 감사 원장
- ledger-native job spec
- 원자 claim, heartbeat, fencing, crash/reboot recovery
- provider call·비용·wall time·deadline 집행
- production lock·quiet-window 관측과 `deferred`/`blocked` 상태
- 쓰기 전 redaction과 안전한 파일 권한
- `researchctl submit/status/show/tail/cancel`
- synthetic·adversarial test harness
- 별도 P3 설치·재부팅 canary가 사용할 runtime attestation 계약

### 제외

- dataset-v1 inventory와 split
- 실제 media, DB, R2, model, Claude/VLM 호출
- production worker 코드·스케줄·lock 변경
- Slack 또는 push notifier
- 웹 대시보드와 모바일 UI
- R2 이후 연구 workload handler
- Mac mini LaunchAgent 설치·bootstrap·재부팅 시험

## 3. Claude 검토 반영

| 검토 항목 | 결정 |
|---|---|
| job마다 RUN-MANIFEST를 쓰면 validator와 충돌 | 채택. RUN-MANIFEST는 사람 주도 구현 패키지만 지배하고, 반복 job은 ledger-native job spec을 사용한다. |
| 재부팅·sleep fencing 부족 | 채택하되 시계 계약을 교정한다. 다른 `boot_id`는 즉시 stale, 같은 boot에서만 monotonic lease와 PID를 판정한다. UTC는 실행 deadline과 감사용이다. |
| production 양보 관측값 부족 | 채택. 실제 flock 비점유 probe와 tracked quiet-window config를 함께 쓰고 `deferred/blocked`로 기록한다. |
| secret 차단이 출력 단계뿐 | 채택. child output은 redactor를 통과하기 전에는 ledger·JSONL·로그에 쓰지 않는다. |
| R1 원격 관측 전송 계층 미정 | R1은 SSH pull-only로 확정한다. push 알림은 후속 패키지다. |
| 기존 runtime 코드 재사용 미정 | 아래 §14 표로 재사용·비재사용을 고정한다. |

## 4. 두 층의 실행 계약

### 4.1 사람 주도 구현 패키지

이 설계와 구현계획이 들어간 commit을 `A`로 한다. 그 위에 start manifest 하나만 담은 `M`을
만들고 `runtime_kind: none`으로 검증한다. 별도 구현 승인 뒤 runner·ledger·CLI를 구현해 `B`,
final manifest record를 `C`로 만든다.

이 문서 패키지는
[`AI 운영 계약 완료 보고서`](../../handoff-prompts/2026-07-27-ai-operating-contract-report.md)의
“다음 허용 행동: R1 실행 manifest와 구현계획 작성” 권한으로 작성하며, 자신을 위한 별도
RUN-MANIFEST는 만들지 않는다.

### 4.2 무인 반복 research job

runner는 Git commit을 만들지 않는다. `researchctl submit --spec <file>`이 job spec을 검증하고
SQLite에 원자 삽입한다. job spec은 R1 구현을 승인한 manifest를 아래 값으로 참조한다.

- `task_id`
- `manifest_blob_sha`
- `manifest_commit_sha`
- `repo_head`
- `expected_host`

job은 arbitrary shell string을 받지 않는다. `handler`는 코드에 등록된 allowlist ID만 허용한다.
R1의 유일한 handler는 `synthetic_noop_v1`이다. 후속 workload는 새 설계·테스트·manifest를 거쳐
handler registry에 추가해야 한다.

## 5. 코드·호스트·경로 결정

| 항목 | 결정 |
|---|---|
| 구현 host | `BaekBook-Pro-14-M5.local` |
| 구현 repo/worktree | `/Users/baek/petcam-lab/.worktrees/r1-mac-mini-runtime-foundation` |
| 구현 branch | `codex/r1-mac-mini-runtime-foundation` |
| 코드 소유 repo | `petcam-lab` |
| Mac mini runtime checkout | `/Users/baek-end/petcam-lab-research-runtime` |
| Mac mini runtime host | `baeg-endeuui-Macmini.local` |
| LaunchAgent label | `com.petcam.research-runtime` |
| runtime root | `/Users/baek-end/petcam-lab-research-runtime/storage/research-runtime` |
| ledger | `<runtime-root>/ledger.sqlite3` |
| event log | `<runtime-root>/events/events.jsonl` |
| result/log | `<runtime-root>/jobs/<job-id>/attempt-<n>/` |
| max concurrency | `1` |

현재 `CLAUDE.md`의 “Mac mini에는 petcam-rba-worker만 clone” 문장은 R1 전용 checkout과 충돌한다.
구현 패키지에서 “production RBA worker는 기존 규칙 유지, research runtime 전용 checkout은 위
경로 하나만 예외”로 갱신한다. `petcam-mac-runner`는 import dependency가 아니라 launchd와 PATH
함정의 참조 자료로만 사용한다.

## 6. job spec

job spec schema version은 `1`이다. 최소 필드는 다음과 같다.

```json
{
  "schema_version": 1,
  "job_id": "r1-noop-20260728-001",
  "task_id": "r1-mac-mini-runtime-foundation",
  "handler": "synthetic_noop_v1",
  "handler_args": {"steps": 3, "step_seconds": 1},
  "manifest_blob_sha": "<64 lowercase hex>",
  "manifest_commit_sha": "<40 lowercase hex>",
  "repo_head": "<40 lowercase hex>",
  "expected_host": "baeg-endeuui-Macmini.local",
  "budget": {
    "max_provider_calls": 0,
    "max_cost_krw": 0,
    "max_wall_seconds": 300,
    "deadline": "2026-08-31T23:59:59+09:00"
  },
  "resources": [],
  "privacy_class": "internal"
}
```

검증 규칙:

- unknown·missing field, duplicate JSON key, control 문자, 앞뒤 whitespace를 거부한다.
- `job_id`는 `[a-z0-9][a-z0-9._-]{2,79}`만 허용한다.
- SHA는 lowercase hex exact 길이만 허용한다.
- `handler=synthetic_noop_v1`의 `resources`는 빈 배열, provider/cost budget은 0이어야 한다.
- deadline이 이미 지났으면 enqueue하지 않는다.
- 같은 `job_id`는 byte-identical spec만 멱등 성공한다. 다른 bytes면 충돌로 거부한다.
- spec 원문은 secret 키 이름과 secret-like 값을 통과하지 못한다.

## 7. ledger와 이벤트 원장

SQLite는 현재 상태, JSONL은 append-only 감사 이력이다.

### 7.1 SQLite

- local APFS에만 둔다. iCloud·Dropbox·network filesystem은 금지한다.
- `journal_mode=WAL`
- `synchronous=FULL`
- `busy_timeout=5000`
- `foreign_keys=ON`
- DB·WAL·SHM은 `0600`, 상위 디렉터리는 `0700`
- schema migration은 forward-only 정수 `ledger_schema_version`으로 관리한다.

job row 최소 필드:

`job_id`, `spec_sha256`, `task_id`, `handler`, `manifest_blob_sha`, `manifest_commit_sha`,
`repo_head`, `expected_host`, `state`, `boot_id`, `pid`, `lease_epoch`,
`lease_expires_monotonic`, `heartbeat_at_utc`, `attempt`, `max_attempts`, `yield_count`,
`last_yield_reason`, `first_queued_at`, `started_at`, `finished_at`, `deadline_utc`,
`max_wall_seconds`, `max_provider_calls`, `max_cost_krw`, `provider_calls`, `cost_krw`,
`cancel_requested_at`, `exit_code`, `error_code`, `error_detail_redacted`, `result_dir`,
`result_bytes`, `ledger_schema_version`.

상태:

`queued / running / deferred / blocked / succeeded / failed / cancelled`

### 7.2 JSONL

모든 상태 전이는 SQLite transaction 성공 뒤에 redacted event 한 줄을 append하고 `flush+fsync`
한다. 이벤트 append가 실패하면 다음 상태를 성공으로 보고하지 않고 `blocked`로 전환한다.
JSONL에는 job spec 전체, 환경변수, argv 원문, child raw output을 넣지 않는다.

## 8. claim·lease·재부팅 fencing

- runner singleton은 전용 nonblocking flock
  `/tmp/petcam-research-runtime.lock`으로 보장한다.
- claim은 단일 transaction에서 `queued/deferred` 한 건을 선택하고 `lease_epoch += 1`,
  `boot_id`, `pid`, monotonic expiry를 기록한다.
- 모든 heartbeat·result commit·state transition은
  `WHERE job_id=? AND lease_epoch=? AND state='running'` CAS로만 수행한다.
- CAS rowcount가 0이면 stale attempt로 판단하고 child를 종료한다.

복구 규칙:

| 저장 boot | PID | 처리 |
|---|---|---|
| 현재와 다름 | 무관 | 이전 프로세스 확정 사망. 즉시 attempt+1 reclaim |
| 현재와 같음 | alive | reclaim 금지. monotonic lease와 heartbeat 관측 |
| 현재와 같음 | dead | attempt+1 reclaim |
| 현재와 같음 | 확인 불가 | fail-closed `blocked` |

wall clock은 재부팅을 넘는 job deadline에만 쓴다. 같은 boot의 lease 만료는 monotonic clock만
쓴다. 결과 디렉터리는 attempt별로 분리해 이전 프로세스가 새 attempt 결과를 오염시키지 못한다.

## 9. production 양보 계약

R1은 production lock을 소유한 채 연구를 실행하지 않는다. lock을 비점유 probe하고 즉시
해제한다. 이미 점유됐으면 `deferred`다.

관측할 lock:

- `/tmp/petcam-vlm-candidate-worker.lock`
- `/tmp/petcam-activity-worker.lock`

tracked config `config/research-runtime-quiet-windows.json`의 초기 KST 예약창:

- 정규 VLM: 22:00, 00:00, 02:00, 04:00 각각 시작 30분 전부터 시작 15분 후까지
- rolling backfill: 매시 :35, 시작 10분 전부터 시작 20분 후까지
- segment 최대 길이: 5분
- 다음 예약창까지 필요한 최소 여유: segment budget + 5분

activity worker의 `StartInterval=3600`은 고정 wall-clock 분이 아니므로 lock probe만으로 관측한다.
이 race를 숨기지 않는다. R1은 no-op만 실행하므로 production resource contention을 만들지 않는다.
향후 detector·VLM·MLX workload handler는 자체 production coexistence 계약과 독립 canary 없이는
registry에 추가할 수 없다.

양보 상태:

- lock busy 또는 quiet-window 부족: `deferred`, `yield_count += 1`
- 최초 defer 뒤 6시간 또는 12회 yield 중 먼저 도달: `blocked`
- `blocked` 전이는 한 번만 보고한다.

## 10. budget·cancel·process supervision

`researchctl`의 조회 명령은 read-only다. 변경 명령은 둘만 허용한다.

- `submit --spec`: 검증된 job spec을 queued로 삽입
- `cancel <job-id>`: `cancel_requested_at`만 기록

runner는 child process group을 supervise한다.

- wall budget·absolute deadline·cancel 요청 시 `SIGTERM`
- 10초 grace 뒤 살아 있으면 `SIGKILL`
- exit와 cleanup 확인 전에는 `cancelled` 또는 `failed`를 확정하지 않는다.
- provider/cost budget은 handler가 호출 전 ledger CAS로 reserve해야 한다.
- R1 no-op handler는 provider call과 비용 reserve API를 호출하면 즉시 실패한다.

## 11. secret·privacy 경계

- runner 시작 시 `umask 077`
- raw child stdout/stderr는 디스크에 만들지 않는다.
- pipe로 읽은 chunk는 redactor를 통과한 뒤 bounded log에 쓴다.
- ledger에는 `error_code` enum과 최대 512자의 redacted detail만 저장한다.
- `researchctl tail`은 redacted log만 읽는다.
- absolute home path는 `$HOME` 토큰으로 치환한다.
- Bearer, signed query, RTSP URL, webhook, email, password/key/token 형태를 차단한다.
- redactor가 실패하거나 undecodable bytes가 계약을 위반하면 job을 `blocked`로 만들고 원문을
  보존하지 않는다.

가짜 secret corpus를 ledger, JSONL, log, `status --json`, `tail` 다섯 출력면에 주입해 0 match를
검증한다.

## 12. `researchctl` 계약

명령:

- `submit --spec <path>`
- `status [--json]`
- `show <job-id> [--json]`
- `tail <job-id> [--lines N]`
- `cancel <job-id>`

`--json`은 항상 최상위 `schema_version: 1`을 포함한다. exit code:

- `0`: 성공
- `2`: 입력·spec 오류
- `3`: repo/host/runtime preflight 불일치
- `4`: job 없음
- `5`: ledger 잠김·손상·integrity failure
- `6`: 권한·secret 안전 경계 위반

R1 원격 관측은 SSH pull-only다. MacBook이나 ChatGPT 원격 세션이 Mac mini에서
`researchctl status --json`을 실행한다. 스마트폰 push 알림과 Slack notifier는 R1 범위 밖이다.

## 13. sleep·LaunchAgent·P3 경계

구현 패키지의 RUN-MANIFEST는 `runtime_kind: none`이다. 코드와 installer artifact까지만 만든다.

실제 설치는 별도 P3 manifest에서 다음을 요구한다.

- exact target `/Users/baek-end/petcam-lab-research-runtime`
- service `com.petcam.research-runtime`
- `runtime_kind: launchagent`
- trusted approval verifier
- runtime attestation verifier
- rollback `launchctl bootout` + plist 제거
- canary: manual no-op, natural cycle, SIGKILL recovery, 재부팅 recovery

LaunchAgent는 runner를 `caffeinate -dimsu` 아래에서 실행해 job 수행 중 sleep을 막는다. 설치 전
`EXPECTED_HOST=baeg-endeuui-Macmini.local`, clean HEAD, plist lint를 확인한다.

## 14. 재사용 결정

| 기존 구성 | 결정 | 이유 |
|---|---|---|
| `benchmark_python_evidence_s1.py` preflight | 부분 재사용 | host·HEAD·dirty·budget 골격만 추출한다. 사람이 넘기는 lock/window 인자는 사용하지 않는다. |
| monotonic `Deadline` | 재사용 | 같은 boot wall budget의 검증된 기준이다. |
| `scoped_tempdir` | 재사용 | crash/interrupt cleanup 계약을 유지한다. |
| dependency `which`+실행 probe | 재사용 | launchd PATH 함정을 fail-closed한다. |
| `EXPECTED_HOST` installer 패턴 | 재사용 | 이미 Mac mini single-host에서 검증됐다. |
| `petcam-mac-runner` 코드 | import하지 않음 | 공유 라이브러리가 아닌 참조 skeleton이라는 자체 계약을 지킨다. plist/PATH 패턴만 복제한다. |
| production worker lock 구현 | import하지 않음 | cross-repo runtime import를 만들지 않고 exact lock path만 config로 관측한다. |

## 15. 검증 순서

24시간 시험 전에 synthetic no-op으로 다음을 모두 통과한다.

1. SIGKILL 뒤 같은 boot dead PID reclaim 1회
2. boot ID 변경 모사 뒤 즉시 reclaim
3. stale lease epoch result commit 0건
4. LaunchAgent+수동 중복 기동에서 runner 1개
5. wall clock jump가 monotonic lease에 영향 0
6. production lock busy에서 `deferred`
7. 12 yield 또는 6시간 뒤 `blocked` 1회
8. deadline 지난 queued job 시작 0
9. disk full·JSONL fsync 실패를 성공으로 기록 0
10. secret corpus 다섯 출력면 0 match
11. 대용량 tail bounded memory
12. ledger lock·손상에서 새 ledger 자동 생성 0
13. cancel SIGTERM→SIGKILL과 residue 0
14. temp media 0

그 뒤 별도 P3에서 manual no-op → natural LaunchAgent cycle → reboot recovery → 24시간 지속 시험을
순서대로 실행한다.

## 16. 성공 기준

- 같은 job과 runner의 동시 실행 0
- stale attempt의 ledger/result mutation 0
- 재부팅 뒤 synthetic job 정확히 한 attempt로 복구
- production lock/reserved window에서 연구 시작 0
- production worker exit/deadline drift 0
- ledger·로그·CLI의 secret-like 문자열 0
- temp media·untracked repo residue 0
- SSH `status --json`으로 HEAD, job state, 최근 결과, redacted failure 확인
- 앱·MacBook 연결 없이 24시간 LaunchAgent 지속

## 17. 구현 전 manifest 결정

이번 구현 manifest는 다음으로 고정한다.

- `runtime_kind: none`
- `implementation_host: BaekBook-Pro-14-M5.local`
- `max_permission: P1`
- provider call·cost: `0`
- media/dataset access: `none`
- deadline: `2026-08-31T23:59:59+09:00`
- deadline 전에 구현 승인을 못 받거나 실행 중 만료되면 manifest를 수정하지 않고 새
  A→M→B→C를 시작한다.

## 18. 다음 허용 행동

1. 이 설계와 구현계획을 A commit으로 고정한다.
2. start RUN-MANIFEST 하나만 M commit으로 추가한다.
3. validator `--phase start`의 `RUN_MANIFEST_OK`를 확인한다.
4. 여기서 정지한다.

runner·ledger·CLI 구현은 별도 구현 승인 뒤에만 시작한다. Mac mini 설치·bootstrap·재부팅·24시간
시험은 구현 완료 뒤 별도 P3 승인과 runtime attestation을 거친다.
