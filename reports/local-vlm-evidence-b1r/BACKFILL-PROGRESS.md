# B1R Backfill Progress — canary + STOP

> Task 6 산출물. 역사 Python Evidence backfill 을 dry-run → 30 clip canary 까지 수행하고, canary 실패율
> 게이트에서 **정지**했다. cutoff = `2026-07-22T02:45:33+00:00` (RUNTIME-SNAPSHOT 고정).

## 배포 (FF-only)

- nightly-reporter `origin/main`: `618f4f8 → a7635a9` (FF-only push, force 아님). enqueuer missing-progress 하드닝 포함, worker 코드 무변경.
- Mac mini `/Users/baek-end/petcam-nightly-reporter`: `git merge --ff-only origin/main` → HEAD `a7635a9`. hostname `baeg-endeuui-Macmini.local`, service `com.petcam.python-evidence-worker` loaded.

## 1) dry-run canary — 전진 검증 (mutation 0)

```
--start-date 2026-06-17 --end-date 2026-07-22 --limit 30 --cutoff-started-at 2026-07-22T02:45:33+00:00 --dry-run
→ missing=30 enqueued=0 dry_run=True
```
하드닝된 missing-scan 이 범위를 순회해 30개 missing 을 찾음. dry-run 이라 write 0.

## 2) 30 clip enqueue + process canary — ⚠️ 실패율 게이트에서 STOP

```
enqueue: missing=30 enqueued=30 (source=historical, priority=10)
worker cycle: jobs=30 ok=1 reused=1 stale=0 fail=28 terminal=0
```

- worker batch(limit 30)에 내 canary 30 중 28 + 다른 due job 2가 섞임. `ok=1/reused=1`은 **최근 clip**(R2 존재), `fail=28`은 내 **old canary clip**.
- 내 30 canary clip 최종 상태: **28 failed_retryable + 2 queued, active run 0/30**. 실패 코드 전부 `r2_download_failed`.
- 실패 clip 날짜: 2026-06-17 (19), 2026-06-22 (9) — 전부 old cohort.

## 3) 근본 원인 — R2 media 소실 (read-only R2 HEAD 표본)

| date | exists/sampled |
|---|---|
| 2026-06-17 | 0/6 |
| 2026-06-22 | 0/6 |
| 2026-07-02 | 6/6 |
| 2026-07-07 | 6/6 |
| 2026-07-12 | 6/6 |
| 2026-07-17 | 6/6 |
| 2026-07-21 | 6/6 |

→ **~R2 보존창(약 30일) 이전 clip 의 R2 object 가 삭제됨.** old cohort 는 재처리해도 `r2_download_failed`
로 evidence 를 만들 수 없다. coverage audit 의 `eligible`(r2_key 비어있지 않음 + duration>0)은 **object
존재를 검증하지 않으므로** 처리 가능한 clip 수를 과대계상한다.

## 4) coverage before / after (동일 cutoff, SELECT-only)

| 지표 | before | after |
|---|---:|---:|
| eligible | 16786 | 16786 |
| succeeded_with_active_run | 2841 | 2841 |
| allowlisted_terminal | 0 | 0 |
| queued+processing+failed_retryable (open) | 0 | 30 |
| silent_missing | 13945 | 13915 |
| coverage_verdict | COVERAGE_OPEN | COVERAGE_OPEN |

canary 30건이 silent_missing→open 으로 이동(전부 old cohort, r2 소실로 succeeded 0). 완료 등식
`eligible == succeeded + terminal ∧ silent_missing=0 ∧ open=0` **불충족** → coverage 미완주.

## 5) STOP 판단과 잔여물

- 게이트: canary 는 run/provenance 정상·temp 0·금지테이블 mutation 0 이어야 대량 enqueue 허용. **93% 실패**
  는 건강한 canary 아님 → 계약대로 **대량 enqueue 금지**, bounded drain 반복(Step 4) 착수 안 함.
- **enqueuer(job 기준) vs audit(run 기준) 스코프 차이**: missing-scan 은 "active job 없음"으로 판정하지만
  audit 은 "active run 없음"으로 판정한다. run-without-job clip 을 enqueuer 가 재-enqueue 할 수 있다(멱등
  run 이라 무해하나, old cohort 는 재처리도 r2 실패). 실측: 캐너리 batch 의 `ok/reused` 2건은 audit
  succeeded 를 늘리지 않음(다른/기존 run clip).
- **잔여 job**: 내 canary 30(28 failed_retryable + 2 queued)은 max_attempts(5)까지 재시도 후
  `failed_terminal(r2_download_failed)`로 자연 수렴. handoff 승인 write 는 **enqueue 뿐**이라 job
  DELETE/강제 terminal 은 하지 않음(fail-closed). live priority(100) 미영향(historical=10).

## 6) 함의

- 역사 coverage "완주"는 backfill 로 달성 불가: old cohort media 가 소실됐다. drain 시간 문제가 아니라
  **source media 가용성 문제**다.
- 처리 가능한 것은 R2 보존창 이내(대략 2026-07-02~) clip 뿐. 그 범위만 backfill 하면 recent-only 편향.
- 다음 단계 후보(owner 결정): (a) coverage audit 에 R2 object 존재 검증 추가해 `eligible` 를 처리가능
  분모로 좁힘, (b) 보존창 이내 cohort 만 backfill, (c) capture→R2 보존정책 재검토(역사 evidence 를
  원하면 보존기간 연장 또는 evidence-at-capture).
