# Local VLM Evidence B1R2 — Media Availability 최종 보고

> **최종 verdict: recoverable coverage OPEN (드레인 중) → NOT `B1R2_DATA_AVAILABLE`**
> 중간 gate: `B1R2_MEDIA_AUDIT_VERIFIED` ✅ · `B1R2_CANARY_VERIFIED` ✅ · `B1R2_RECOVERABLE_COVERAGE_CLOSED` ❌
> handoff: `/Users/baek/.codex/handoffs/2026-07-22-local-vlm-evidence-b1r2-media-availability-handoff.md`
> 상세 coverage/selector: [`reports/local-vlm-evidence-b1r2/COVERAGE-FINAL.md`](../../reports/local-vlm-evidence-b1r2/COVERAGE-FINAL.md)
> 작성 2026-07-22. **Task 7 보고·SOT·push 후 정지. B2·사람 GT·Local VLM 벤치 미착수.**

## 0. 시작 계약 / host / runtime

- validator 전문: `HANDOFF_OK task=local-vlm-evidence-b1r2-media-availability repo=local-vlm-evidence-web-gt commit=6c5c3d8e runtime=scheduled-job@baeg-endeuui-Macmini.local`
- implementation host(이 세션): `BaekBook-Pro-14-M5.local` · runtime host(정본): `baeg-endeuui-Macmini.local`
- lab HEAD == manifest `6c5c3d8e`, tree clean, 736→761 pytest PASS.

| repo | Mac mini HEAD | origin/main | 상태 |
|---|---|---|---|
| petcam-lab | `7a087b74` | `7a087b74` | clean (lab 코드 laptop 실행) |
| petcam-nightly-reporter | `6ab6dd2` | `6ab6dd2` | service loaded, exit 0, plist 불변 |
| gecko-vision-gate | `9ea55eb7` | `9ea55eb7` | clean |

## 1. 한 줄 결론

B1R 의 "역사 media 보존창 전량 소실"은 **oldest-first canary 과일반화**였다. 실측 inventory 결과 소실은 **108건뿐**,
**13837 건은 R2 object 존재(복구 가능)**. failure typing + migration + manifest-bound canary/backfill 로 복구 메커니즘을
**실증**(canary 30/30 + bulk 179 clean, 실패 0). 다만 recoverable 전량 closure 는 cap-500 페이싱·30분 스케줄로 **~9일
자율 드레인** = 동기 완주 불가. selector v2 는 4/6 strata(absent·big_move·rest_micro·hardcase)가 **30 도달**, lick/wheel 은
0(coverage vs semantic 은 closure 후 확정). → coverage OPEN, `B1R2_DATA_AVAILABLE` 미도달, Stop Point 정지.

## 2. study_total 5-상태 partition (cutoff `2026-07-22T02:45:33+00:00`)

```text
study_total 16786 = evidence_succeeded 2841 + media_available_open 0 + media_available_silent 13837
                     + media_available_terminal 0 + source_expired 108   ✅ 등식 성립
recoverable_total 16678 · recoverable_coverage_closed False
availability_sha256 e69baec9429ef83f274940bd9aa1b05e16de4bb9b79ab056d6190d2e810c8fe3 (독립 recompute MATCH)
```

## 3. R2 inventory (Task 2, read-only)

- prefix `terra-clips/clips/`(실측 16797/16797), objects 33433, mp4_available 16729, pages 34, byte/watermark 기록.
- bounded HEAD: available 173/173 present · expired 42/42 404 · mismatch 0 · 403/5xx 0.
- private manifest gitignored, laptop↔Mac mini byte SHA `71314273…` 일치. camera/date별 available/expired 분포 aggregate 기록.
- ⚠️ 초기 prefix 가정(`clips/`)은 218 object 만 잡아 HEAD mismatch 159 로 fail-closed → 실측 prefix 로 정정 후 통과. (가정 금지 교훈)

## 4. failure typing + forward migration (Task 3·5)

- typed `R2SourceMissing`/`R2AccessDenied` + `classify_r2_client_error`; worker: 404→source_media_missing(terminal),
  403→r2_access_denied(terminal), 429/5xx/timeout→r2_download_failed(retryable). raw key/secret 미포함. RED→GREEN 양쪽 repo.
- Python allowlist ↔ DB CHECK canonical 11-code 1:1 pin(양쪽 테스트).
- migration `python_evidence_source_media_failure_codes`(forward-only, 기존 migration byte SHA pin):
  apply success · rollback probe **11 accepted/bogus rejected/0 leaked** · job 분포 apply 전후 동일(2882) · advisor 신규 critical **0**.

## 5. canary 30/30 (Task 6) — `B1R2_CANARY_VERIFIED`

- silent round-robin 30(cameras 3·dates 20), 선택 직전 HEAD 30/30 present, content SHA `7e369906…`.
- dry-run `selected=30 enqueued=0` → enqueue 30(total 2883→2913, 다른 clip 0).
- 처리: succeeded 30 / active run 30 / **실패 0**(source_media_missing·access_denied·retryable 0), temp 0, exit 0, drift 0.
- live lag: canary 문맥 2.21분(≤15) · live backlog>15분 0. (ambient 6h p95 27.42분=30분 폴링 아티팩트, backfill 무관.)

## 6. bulk backfill + closure (Task 7 Step 1·2)

- cap-500: full manifest(SHA `e69baec9…`) `candidates=13837 selected=500 enqueued=500`(비-silent 0·중복 0).
- 4 cycle 드레인: 매 cycle `jobs=30 ok+reused=30 fail=0 terminal=0`, exit 0.
- delta: historical_succeeded 179 · active_runs 3003 · open_historical 381 · 신규 source_media_missing/access_denied **0** ·
  recent historical fail 0 · live backlog>15분 0 · temp 0.
- **recoverable closure: open 381>0, silent≈13337>0 → 미충족(드레인 중)**. 전량 closure ~9일 자율. private_manifest_missing 0.

## 7. selector v2 재판정 (Task 7 Step 3)

| stratum | B1R | **B1R2** | | stratum | B1R | **B1R2** |
|---|---:|---:|---|---|---:|---:|
| absent | 24 | **30** | | hardcase | 12 | **30** |
| big_move | 8 | **30** | | lick_water_food | 0 | **0** |
| rest_micro | 25 | **30** | | wheel_object | 0 | **0** |

- clip_overlap 0 · episode_overlap 0 · camera 3 · date 23 · pool_sha256 `cec461e807ee…`(독립 recompute MATCH) · manifest_emitted False.
- coverage↑(evidence +162)로 4 strata 8·12·24·25→**30**. lick/wheel 0 의 coverage vs semantic 은 closure 후 확정(B1R 사람 retrieval 도 0 → semantic 시사, 미확정). 기준 사후 완화 없음.

## 8. 허용/금지 mutation

- 승인 write 만: migration apply · `python_evidence_jobs` enqueue(canary 30 + bulk 500) · worker 정상 append-only run/prelabel.
- 금지 0: R2 put/delete/copy/lifecycle · DB DELETE/기존 run UPDATE · VLM/GT/behavior/activity/app write · B2 · model download/inference ·
  MacBook worker/expected-host 우회 · secret/key/URL/per-clip 노출 · 타 세션 untracked · source-expired 위장 — **전부 0**.

## 9. commit / push / 동기화

- nightly: `feat/local-vlm-evidence-b1r2-media` 2 commit(fix R2 typing, feat manifest enqueue) → origin/main FF **`6ab6dd2`** → Mac mini FF pull, focused tests 56 PASS.
- lab: `codex/local-vlm-evidence-web-gt` Task 0~7 커밋 후 push. lab main FF 통합은 B1R 선례대로 보류(런타임 무관·Stop Point owner review).
- migration: production `slxjvzzfisxqwnghvrit`(.env SUPABASE_URL 일치) apply 완료.

## 10. 미검증 사실 + 최종 verdict

- 미검증: 정확한 R2 lifecycle 보존기간(policy 직접 미확인) · lick/wheel=0 의 coverage/semantic 구분(closure 필요).
- **최종 verdict: recoverable coverage OPEN(드레인 중) — NOT `B1R2_DATA_AVAILABLE`.** media available 확정(13837 복구가능/108 소실),
  복구 메커니즘 verified, closure 자율 pending. 전량 closure 후 → lick/wheel 채워지면 `B1R2_DATA_AVAILABLE`, 여전히 0 이면 `B1R2_BLOCKED_SEMANTIC_DATA`. **Stop Point 정지.**

**B1/B1R namespace artifact 는 수정 안 함. 전부 B1R2 신규.**
