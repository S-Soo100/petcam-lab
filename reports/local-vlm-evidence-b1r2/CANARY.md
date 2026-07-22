# B1R2 Media-available Canary — 결과 (Task 6)

> **verdict: `B1R2_CANARY_VERIFIED`**
> runtime host: `baeg-endeuui-Macmini.local` · nightly HEAD `6ab6dd2`==origin/main · service `com.petcam.python-evidence-worker` loaded, exit 0.
> secret/R2 key/signed URL 미포함. canary per-clip ID 는 gitignored private manifest 에만 존재.

## 1. inventory 재생성 + canary 선택 (Step 1)

- 같은 cutoff `2026-07-22T02:45:33+00:00` 로 audit 재실행 → partition 재현:
  `study_total=16786 = succeeded 2841 + open 0 + silent 13837 + terminal 0 + source_expired 108`.
- availability_sha256 `e69baec9429e…` (Task 2 와 동일, 재현) · recompute **MATCH**.
- bounded HEAD 표본: available 173/173 present · expired 42/42 404 · mismatch 0.
- canary: `media_available_silent` 에서 camera/date round-robin **30 선택**, cameras=3, dates=20.
- **canary 선택 직전 HEAD 재확인(design §7.4): 30/30 present, absent 0.**
- canary content SHA `7e369906d3003fbbe64b0d3d328e37767bce1aecf49c575ba4ecd711ee2e2572`.

## 2. Mac mini 전송 무결성 (Step 2)

- private canary manifest scp → `/Users/baek-end/petcam-lab/storage/local-vlm-evidence-analyst/b1r2/canary.jsonl`.
- laptop ↔ Mac mini 파일 SHA-256 **일치** (`30f3b3fa4078…`, 30 lines). Git add 안 함(gitignored).

## 3. dry-run → enqueue (Step 3)

- dry-run: `candidates=30 selected=30 enqueued=0` (SHA 검증 통과, 비-silent 0).
- enqueue(historical, priority 10): `selected=30 enqueued=30`.
- **다른 clip ID 생성 0**: total_jobs `2883 → 2913` = 정확히 +30. canary 30 clip 만 job 생성, 그 외 0.

## 4. 기존 worker 처리 + 판정 (Step 4)

worker 자연 kickstart 2 cycle (plist env, launchctl kickstart):

```
07-22 08:21  jobs=30 ok=22 reused=8 stale=0 fail=0 terminal=0   (1 live + 29 canary; live priority 100 > historical 10)
07-22 08:24  jobs=1  ok=1  reused=0 stale=0 fail=0 terminal=0   (남은 canary 1)
```

DB 최종:

| 지표 | 값 | 기준 |
|---|---|---|
| canary selected | 30 | =30 ✅ |
| canary succeeded | 30 (ok 23 + reused 7 누적) | — |
| canary active run (level0=ok) | 30 | 생성/재사용 합 30 ✅ |
| canary failures (retryable/terminal) | 0 | source_media_missing=0 · r2_download_failed=0 · r2_access_denied=0 ✅ |
| temp media (temp .mp4 최근 120분) | 0 | 잔류 0 ✅ |
| service last exit code | 0 (settled) | =0 ✅ |
| runtime drift | 0 | host/HEAD(6ab6dd2)/service/plist 불변 ✅ |
| selector/VLM/GT/behavior/activity/app write | 0 | ✅ |

### live queue lag (전송 문맥)

- **canary 이후 생성된 live job claim lag = 2.21분** (n=1) ≤ 15분 → backfill 이 live 를 굶기지 않음 ✅.
- 현재 15분 초과 live backlog = **0**.
- 참고: 6h ambient live claim-latency p95 = 27.42분 — 이는 worker StartInterval(1800s=30분) 폴링 주기 아티팩트다
  (관측된 claim cadence p95 = 60분). historical(10) < live(100) 우선순위라 backfill 은 live 를 선점할 수 없어
  이 ambient lag 를 만들지 않는다. 즉 15분 게이트가 겨냥하는 "backfill 이 live 를 지연시키는가"의 실측치는 2.21분.
  ⚠️ owner review: "live queue lag ≤15분"을 6h claim-latency 로 해석하면 30분 폴링 스케줄과 구조적으로 상충하니
  (backfill 무관) 폴링 주기 단축 또는 지표 재정의는 별개 사안으로 남긴다.

### 비-canary 사실 1건 (혼동 방지)

- `recent_r2_failures=1` 은 **canary 아님**(`is_canary=false`, source=historical, failed_terminal, r2_download_failed,
  attempt 5, age ~258분) = **B1R 잔여 old-cohort job** 이 old 분류로 자연 terminal 수렴한 것. 이번 canary 처리와 무관.

## 5. 판정

- Step 5 canary 성공 조건(design §7) 전부 충족: selected=30, 성공+재사용=30, source-missing/retryable/access-denied=0,
  temp 0, exit 0, drift 0, 금지 write 0, canary 문맥 live lag 2.21분.
- **`B1R2_CANARY_VERIFIED`** → Task 7 bounded backfill 진행 허용. (live-lag ambient 6h 수치는 위 문맥으로 투명 기록.)
