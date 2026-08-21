---
handoff_version: 1
task_id: gme-detected-labeling-activity
execution_repo: /Users/baek/.codex/worktrees/gme-detected-labeling-activity/petcam-lab
plan_path: /Users/baek/.codex/worktrees/gme-detected-labeling-activity/petcam-lab/docs/superpowers/plans/2026-08-22-gme-detected-human-labeling-activity-use.md
design_path: /Users/baek/.codex/worktrees/gme-detected-labeling-activity/petcam-lab/docs/superpowers/specs/2026-08-22-gme-detected-human-labeling-activity-use-design.md
commit_sha: 531ef3586b2efb23c89f1e4ee4d87cc5d554e424
implementation_host: BaekBook-Pro-14-M5.local
runtime_kind: none
---

# GME 탐지 영상 라벨링·활동량 연계 검증 보고

## 판정

`IMPLEMENTED_UNVERIFIED`. 최신 코드 기준점은
`531ef3586b2efb23c89f1e4ee4d87cc5d554e424`이고, GME rank를 담는 public cursor를 AES-256-GCM
`bq3`로 인증 암호화한 commit까지 포함한다. 최신 focused/full web과 TypeScript 검사는 통과했지만
이 commit의 build는 저장소 정책에 따라 실행하지 않았으므로 `REVIEWED_READY_FOR_INTEGRATION`이나
`PREVIEW_READY`로 올리지 않는다. 이 파일만 담은 바로 다음 manifest-only commit에서 handoff
verifier를 실행한다. production DB·R2·service·model·Vercel·라벨링 웹에는 아무것도 적용하지 않았다.

## Git 증거

| 항목 | 실제 값 |
|---|---|
| branch | `codex/gme-detected-labeling-activity` |
| latest code baseline / implementation commit | `531ef3586b2efb23c89f1e4ee4d87cc5d554e424` (`motionBlindReviewServer.ts`와 관련 test 2개 변경) |
| upstream | 없음(`fatal: no upstream configured for branch 'codex/gme-detected-labeling-activity'`) |
| code commit 직후 status | tracked/untracked 변경 0 |
| final handoff 구조 | implementation commit의 바로 다음 commit은 이 manifest 한 파일만 변경 |

최종 manifest-only commit SHA와 `HANDOFF_OK` 전문은 git log와 Task 5 SDD report에 남긴다.
manifest가 자기 commit SHA를 내용에 넣을 수 없는 순환을 피하려고 verifier가 허용하는
`implementation commit + manifest-only successor` 구조를 사용한다.

## 최신 코드 검증과 build 경계

| 검증 | 결과 |
|---|---|
| latest GME blind queue focused web | `3 files passed`, `52 tests passed` at `531ef358` |
| latest full web | `105 files passed`, `964 tests passed` at `531ef358` |
| latest `npx tsc --noEmit` | exit 0 at `531ef358` |
| latest web production build | **미실행** — 저장소 donts#9 정책 경계 |
| predecessor Python regression | `2137 passed, 5 skipped` at `776a9c0` |
| predecessor web production build | `npx next build` exit 0, static pages `32/32` at `776a9c0` |

`776a9c0` 시점의 `npx next build` 성공은 predecessor 증거일 뿐 AES-GCM cursor commit
`531ef358`의 build 증거가 아니다. 최신 code에서는 donts#9 정책에 따라 build를 실행하지 않았고,
focused/full web과 `tsc` 성공을 build 성공으로 대체하지 않는다.

## public cursor 보안 계약

- public cursor는 `bq3.` prefix 뒤에 AES-256-GCM nonce+ciphertext+auth tag를 base64url로 담는다.
- GME `detected`/`activity_sec`, 날짜·cohort scope, `started_at`, clip id는 인증 암호문 안에만 있다.
  public base64url을 decode해도 GME rank·날짜·clip id 평문이나 JSON이 나오지 않는다.
- 같은 위치도 fresh nonce로 다른 cursor가 나오고 ciphertext/tag 변조, 다른 날짜·scope replay,
  legacy plaintext v1/v2 cursor는 `invalid_blind_cursor`로 fail closed한다.
- 키는 `SUPABASE_SERVICE_ROLE_KEY`에서 용도 분리 HMAC-SHA256으로 파생한다. service-role key가
  회전하면 이전 cursor는 복호화되지 않아 만료되고 사용자는 첫 페이지에서 새 cursor를 받는다.
- 공개 item allowlist에도 GME/VLM/rank 필드는 없으며, 내부 rank는 복호화 뒤 DB keyset 인자로만 쓴다.

## disposable PostgreSQL probe

로컬 Homebrew PostgreSQL의 무작위 `blind_probe_*` DB에 prerequisite snapshot → 단일 migration
`migrations/2026-08-22_gme_activity_blind_queue.sql` 순서로 적용했다. production 연결은 사용하지
않았고 probe가 만든 DB와 role만 정리했다.

```text
GME_ACTIVITY_CONTEXT_OK
GME_ACTIVITY_BLIND_QUEUE_OK
DB_RUNTIME_PROBE_OK
PROBE_RESIDUE=0
```

기존 concurrency runner도 별도로 통과했다.

```text
DB_RUNTIME_PROBE_OK
DB_CONCURRENCY_PROBE_OK
PROBE_RESIDUE=0
```

## production 원문·GT 없는 fixture canary

합성 UUID와 합성 R2 key만 쓴 rollback fixture를 두 라벨러 대상으로 실행했다. 원본 영상, 실제 GT,
실제 사용자 identity는 읽거나 출력하지 않았다.

- 어제 live 큐는 `detected activity 9 → detected activity 2 → detected activity 0 → undetected eligible`
  순서였고, 네 clip 모두 두 slot씩 유지됐다.
- 두 라벨러는 같은 live/canary 순서를 받았다.
- canary는 GME rank를 적용하지 않아 기존 `started_at DESC, id DESC` 순서를 유지했다.
- canary 조회 전후 submission 수는 `0 → 0`, 두 라벨러 canary slot 수는 8로 불변이었다.
- 두 라벨러가 공통으로 거치는 공개 allowlist mapper와 live/canary route fixture 52건을 검증했다.
  공개 item에는 GME activity/run/state, VLM, highlight rank, `rank_detected`,
  `rank_activity_sec`가 없고 내부 rank는 cursor 생성에만 쓰인다.

```text
TASK5_LIVE_ORDER_9_2_0_UNDETECTED_OK
TASK5_TWO_LABELER_QUEUE_OK
TASK5_CANARY_ORDER_SUBMISSION_COUNT_UNCHANGED
TASK5_FIXTURE_RESIDUE=0
```

실제 Vercel Preview deployment나 production cohort를 만들지 않았으므로 `PREVIEW_READY` 또는
`DEPLOYED_VERIFIED`라고 부르지 않는다.

## 적용·write 사실

| 대상 | 실제 값 |
|---|---:|
| production migration apply | 0 (`applied=false`) |
| production DB write | 0 |
| production R2 read/write/delete | 0 / 0 / 0 |
| service 설정·재시작·배포 | 0 |
| OpenAI/기타 model API 호출·write | 0 / 0 |
| Vercel Preview/production deployment | 0 / 0 |
| labeling web production 반영 | 0 |

disposable DB에만 합성 row를 썼고 전부 rollback했으며 최종 residue는 0이다. 기존 canary slot,
submission, consensus, GME worker identity/checkpoint는 건드리지 않았다.

## 승인 경계와 남은 위험

이 문서는 production 적용 명령이나 승인서가 아니다. owner가 별도로 승인한 뒤에만 단일 migration,
라벨링 웹 배포, Mac mini OpenAI 연구 runner handoff를 각각 exact commit으로 진행해야 한다.
적용 후에는 두 slot 누락 0, live rank 단조 감소와 페이지 중복·누락 0, 공개 응답 내부 필드 0,
기존 consensus/submission 수정 0, worker identity/checkpoint 변화 0을 read-only로 다시 확인해야 한다.

Task 4 review에서 남긴 비차단 minor가 하나 있다. 극단적인 timezone-aware timestamp를 UTC로
정규화할 때 `OverflowError`가 `GmeActivityError`로 정규화되지 않을 수 있다. 일반 입력과 이번 DB
queue/canary 계약에는 영향을 주지 않지만 final whole-branch review에서 판정해야 한다.
