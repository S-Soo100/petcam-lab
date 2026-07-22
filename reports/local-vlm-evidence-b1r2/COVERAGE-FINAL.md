# B1R2 Media Coverage & Selector 재판정 — 최종 (Task 7)

> **최종 verdict: recoverable coverage OPEN (draining) → NOT `B1R2_DATA_AVAILABLE`**
> 중간 gate: `B1R2_MEDIA_AUDIT_VERIFIED` ✅ · `B1R2_CANARY_VERIFIED` ✅ · `B1R2_RECOVERABLE_COVERAGE_CLOSED` ❌(미도달, 드레인 중)
> Stop Point: Task 7 보고·SOT·push 후 정지. B2·사람 GT·Local VLM 벤치 미착수.
> secret/R2 key/signed URL/per-clip availability 는 tracked 산출물·이 보고서에 없음.

## 0. 시작 계약 / host

- validator 전문:
  `HANDOFF_OK task=local-vlm-evidence-b1r2-media-availability repo=local-vlm-evidence-web-gt commit=6c5c3d8e runtime=scheduled-job@baeg-endeuui-Macmini.local`
- implementation host(이 세션): `BaekBook-Pro-14-M5.local` · runtime host(정본): `baeg-endeuui-Macmini.local`
- lab 실행 repo: `/Users/baek/petcam-lab/.worktrees/local-vlm-evidence-web-gt` branch `codex/local-vlm-evidence-web-gt`, HEAD == manifest `6c5c3d8e`, clean, 736→761 pytest PASS.

### runtime 세 repo (Mac mini 실측)

| repo | Mac mini HEAD | origin/main | service |
|---|---|---|---|
| petcam-lab | `7a087b74` | `7a087b74` | (lab 코드는 laptop worktree 실행, Mac mini 는 storage 만) |
| petcam-nightly-reporter | **`6ab6dd2`** | `6ab6dd2` | `com.petcam.python-evidence-worker` loaded, StartInterval 1800, WorkingDir `/Users/baek-end/petcam-nightly-reporter`, exit 0 |
| gecko-vision-gate | `9ea55eb7` | `9ea55eb7` | clean |

- runtime drift 0. LaunchAgent plist/schedule/env 미수정.

## 1. study_total 5-상태 partition (audit 정본, cutoff `2026-07-22T02:45:33+00:00`)

```text
study_total            = 16786
evidence_succeeded     = 2841
media_available_open   = 0
media_available_silent = 13837
media_available_terminal = 0
source_expired         = 108
등식: 2841 + 0 + 13837 + 0 + 108 = 16786 ✅
recoverable_total      = 16678 (= study − source_expired)
recoverable_coverage_closed(open==0 ∧ silent==0) = False
```

**핵심 정정:** B1R 의 `eligible=16786` 은 DB `r2_key` 존재만 봐서 소실분 과대계상. B1R2 실측: **소실은 108건뿐**,
13837 은 R2 object 존재(복구 가능). B1R 의 "보존창(~30일) 전량 소실" 은 oldest-first canary 28/30 실패로 인한
**과일반화**였음(design §1 경고대로). 정확한 R2 lifecycle 보존기간은 policy 직접 미확인 → 주장 안 함.

## 2. R2 inventory + 독립 검증 (Task 2, read-only)

- `list_objects_v2` prefix `terra-clips/clips/` (실측: 16797/16797 clip 이 이 prefix — 가정 아닌 검증값):
  objects=33433, mp4_available=16729, total_bytes 기록, pages=34, watermark 기록.
- availability_sha256 = `e69baec9429ef83f274940bd9aa1b05e16de4bb9b79ab056d6190d2e810c8fe3`.
- 독립 recompute(주 구현 미import, stdlib): **MATCH** (counts·SHA).
- private manifest `media-availability.jsonl` (16786 lines, clip_id/camera_id/started_at/source_date/status 만) gitignored,
  laptop↔Mac mini byte SHA `71314273…` 일치.
- bounded HEAD 표본(camera/date 당 ≤6): available **173/173 present**, expired **42/42 404**, mismatch **0**, 403/5xx 0.
- camera/date 별 available vs source_expired 분포는 aggregate `camera_date_status_counts` 에 기록.

## 3. failure-code typing + forward migration (Task 3·5)

- nightly-reporter: `R2SourceMissing`/`R2AccessDenied` typed 예외 + `classify_r2_client_error`. worker download 블록이
  404/NoSuchKey→`source_media_missing`(terminal), 403/AccessDenied→`r2_access_denied`(terminal), timeout/429/5xx→
  `r2_download_failed`(retryable) 로 분리. typed 예외에 raw key/secret 미포함. RED(404/403/5xx 매핑)→GREEN.
- Python allowlist(store `ALLOWED_FAILURE_CODES`) 와 DB CHECK 를 canonical 11-code 로 양쪽 테스트 pin(1:1 drift 0).
- migration `python_evidence_source_media_failure_codes` (forward-only, 기존 migration byte 불변 SHA pin):
  - apply: success. constraint `python_evidence_jobs_failure_code_check` 를 같은 이름으로 교체, 신규 2 code 추가.
  - rollback probe(transaction, RAISE 로 전량 rollback): **11 accepted / bogus rejected / 0 rows leaked**.
  - apply 전후 job count/status/failure 분포 **동일**(total 2882, succeeded 2852, failed_terminal 30).
  - advisor(security) 신규 critical **0** (before==after, ERROR 0).

## 4. canary 30/30 (Task 6) — `B1R2_CANARY_VERIFIED`

- 선택: `media_available_silent` round-robin 30, cameras=3, dates=20, 선택 직전 HEAD **30/30 present**.
- canary content SHA `7e369906…`, laptop↔Mac mini file SHA `30f3b3fa…` 일치.
- dry-run `selected=30 enqueued=0` → enqueue `enqueued=30`, total_jobs `2883→2913`(정확히 +30, 다른 clip 0).
- 처리: 2 worker cycle, **succeeded 30 / active run 30 / failures 0**(source_media_missing·access_denied·retryable 0),
  temp 0, service exit 0, drift 0, 금지 write 0.
- live lag: canary 문맥 live claim lag **2.21분**(≤15분) · 현재 15분 초과 live backlog **0**.
  (ambient 6h claim-latency p95=27.42분은 StartInterval 30분 폴링 주기 아티팩트, backfill 무관 — priority 10<100. 상세 CANARY.md)

## 5. bounded bulk backfill (Task 7 Step 1) — 드레인 중

- cap 500-open 준수: open_historical=0 상태에서 full manifest(SHA `e69baec9…`)로 `candidates=13837 selected=500 enqueued=500`.
  비-silent enqueue 0, 중복 job 0(missing-progress 로 canary 30 skip).
- 자연 worker cycle 4회 드레인: 매 cycle `jobs=30 ok+reused=30 fail=0 terminal=0`, exit 0.
- 현재 DB delta:
  ```text
  historical_succeeded (canary+bulk) = 179
  active_runs_total                  = 3003  (B1R 2841 → +162: canary 30 + bulk 149 + live 소량)
  open_historical (드레인 중)          = 381
  new source_media_missing / r2_access_denied = 0   (lifecycle race 404 없음)
  recent historical failures          = 0
  live backlog >15분                  = 0
  temp media 잔류                     = 0
  ```
- **recoverable closure 재계산**: `media_available_open=381>0`, `media_available_silent≈13337>0` → **미충족(드레인 중)**.
  전량 closure(open=0 ∧ silent=0)는 cap-500 페이싱 + 30분 StartInterval 로 자연 드레인 시 **~9일 자율 진행**(동기 불가).
  availability manifest recompute 자체는 MATCH(§2). private_manifest_missing=0.

## 6. selector v2 재판정 (Task 7 Step 3, 같은 cutoff, 현재 evidence 3003)

| stratum | B1R final | **B1R2 final** | raw | episode |
|---|---:|---:|---:|---:|
| absent | 24 | **30** | (aggregate) | 30 |
| big_move | 8 | **30** | | 30 |
| rest_micro | 25 | **30** | | 30 |
| hardcase | 12 | **30** | | 30 |
| lick_water_food | 0 | **0** | 0 | 0 |
| wheel_object | 0 | **0** | 0 | 0 |

- clip_overlap **0**, episode_overlap **0**, camera_count 3, date_count 23.
- pool_sha256 `cec461e807ee5f0254ad86fcd03f4f47bca02aa1495b87647cf9c4e054ed2c61`, 독립 recompute(probe 미import) **MATCH**.
- `manifest_emitted=False` (6×30 미충족: lick/wheel 0).
- **해석(design §9 — coverage vs semantic 분리):** backfill 로 evidence 가 162 늘자 absent/big_move/rest_micro/hardcase 가
  8·12·24·25 → **전부 30 도달**(4/6 = dev120). lick_water_food·wheel_object 는 **현재 evidence raw 0**.
  이 0 이 (a) coverage(미처리 13337 silent 에 해당 clip 존재) 인지 (b) semantic(데이터에 해당 행동 자체 부재)인지는
  **전량 closure 전까지 확정 불가**. 단 B1R 기록상 사람 retrieval 신호로도 lick/wheel 미부상 → semantic 부재 쪽 시사(미확정).
  기준(6×30·30분 episode·수량) **사후 완화 없음**.

## 7. 허용/금지 mutation 증거

- **승인 write 만**: (a) forward migration apply(constraint 교체), (b) `python_evidence_jobs` enqueue — canary 30 + bulk 500,
  (c) 기존 worker 의 정상 append-only run/prelabel(canary+bulk 처리분). 그 외 mutation 0.
- 금지 0: R2 put/delete/copy/lifecycle **0** · DB clip/job/run DELETE·기존 run UPDATE **0** ·
  VLM/GT/behavior/activity/app write **0** · B2 migration/API/UI **0** · model download/inference **0** ·
  MacBook worker 실행/expected-host 우회 **0** · secret/R2 key/signed URL/per-clip 노출 **0** ·
  다른 세션 untracked add/commit/delete **0** · source-expired 를 success 로 위장 **0**.

## 8. commit / push / 동기화

- nightly-reporter: `feat/local-vlm-evidence-b1r2-media` (a7635a9→6ab6dd2) → **origin/main FF `6ab6dd2`** → Mac mini `merge --ff-only`(6ab6dd2). focused tests 56 PASS on Mac mini.
- lab: `codex/local-vlm-evidence-web-gt` 에 Task 0~7 커밋 후 push(§아래 최종 SHA). lab main FF 통합은 B1R 선례대로 보류(feature branch 유지 — 런타임 무관, Stop Point owner review 대상).
- DB migration: production `slxjvzzfisxqwnghvrit` 에 apply 완료(.env SUPABASE_URL 일치 확인).

## 9. 미검증 사실 / 다음

- 정확한 R2 보존기간(lifecycle policy) 직접 미확인 → 날짜 기반 주장 안 함(108 소실은 inventory 실측).
- lick/wheel=0 의 coverage vs semantic 확정은 전량 closure 후 재판정 필요.
- 후속(owner/Codex 새 handoff 대상): (a) cap-500 라운드 반복 or 자연 드레인으로 recoverable closure 완주 → selector 최종 재판정,
  (b) lick/wheel semantic 부재 확정 시 stratum/데이터 수집 전략, (c) live lag 게이트를 폴링 주기 반영해 재정의.

## 10. 최종 verdict

- `B1R2_BLOCKED_INVENTORY_INTEGRITY` → 아님(HEAD 173/173·expired 42/42·recompute MATCH·partition 등식 성립).
- `B1R2_BLOCKED_RUNTIME_DRIFT` → 아님(세 repo HEAD==origin/main, host/service/plist 계약 일치).
- `B1R2_CANARY_REJECTED` → 아님(canary 30/30, 실패 0, drift 0 → `B1R2_CANARY_VERIFIED`).
- `B1R2_DATA_AVAILABLE` → **아님**(recoverable coverage 미완주: open 381 + silent 13337; 6×30 미충족 lick/wheel 0).
- `B1R2_BLOCKED_SEMANTIC_DATA` → **확정 불가**(closure 전이라 lick/wheel 0 이 coverage 인지 semantic 인지 미구분).

**⇒ 최종: recoverable coverage OPEN(드레인 중) — design §10 판정 사다리의 "recoverable coverage open" 단계.**
media 는 **available 확정**(13837 복구 가능, 108 소실), 복구 메커니즘 **verified**(canary+bulk 179 clean), closure 는
자율 드레인 pending. 전량 closure 후 lick/wheel 이 채워지면 `B1R2_DATA_AVAILABLE`, 여전히 0 이면 `B1R2_BLOCKED_SEMANTIC_DATA` 로 확정. **결과 무관 Stop Point 준수 — 정지.**
