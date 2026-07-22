# Local VLM Evidence B1R — 최종 보고서

> **verdict: `B1R_BLOCKED_EVIDENCE_COVERAGE`**
> handoff: `/Users/baek/.codex/handoffs/2026-07-22-local-vlm-evidence-b1r-handoff.md`
> execution_repo: `/Users/baek/petcam-lab/.worktrees/local-vlm-evidence-web-gt` (branch `codex/local-vlm-evidence-web-gt`)
> 작성 2026-07-22. **Task 7 에서 정지. B2·모델 실행은 owner/Codex 검수 + 새 handoff 전까지 시작 안 함.**

## 0. 시작 계약

- validator: `HANDOFF_OK task=local-vlm-evidence-b1r repo=local-vlm-evidence-web-gt commit=f1cc0861 runtime=scheduled-job@baeg-endeuui-Macmini.local`
- lab worktree HEAD == manifest SHA `f1cc0861…`, clean. plan/design 전부 읽음.

## 1. 한 줄 결론

selector v1 굶김은 **v2 multi-match + scarcity-first 로 실증 해소**(absent 0→24, rest 7→25 episode 회복). 그러나
역사 Python Evidence **coverage 완주는 불가** — old cohort 의 R2 media 가 보존창(약 30일) 초과로 삭제돼
재처리해도 `r2_download_failed`. 두 원인 중 selector 는 고쳤고, coverage 는 **media 가용성**이 막는다. → 계약대로
정지, B2·모델 금지.

## 2. Runtime 정본 (Task 0, read-only 실측)

| repo | Mac mini path | HEAD | origin/main | 비고 |
|---|---|---|---|---|
| petcam-lab | /Users/baek-end/petcam-lab | 7a087b74 | 7a087b74 | clean |
| petcam-nightly-reporter | /Users/baek-end/petcam-nightly-reporter | **a7635a9** | a7635a9 | Task 6 FF 배포 후(원래 618f4f8) |
| gecko-vision-gate | /Users/baek-end/myPythonProjects/gecko-vision-gate | 9ea55eb7 | 9ea55eb7 | clean |

- hostname `baeg-endeuui-Macmini.local` 일치. service `com.petcam.python-evidence-worker` loaded (StartInterval 1800s, last exit 0).
- plist: `PYTHON_EVIDENCE_ENABLED=1`, `PYTHON_EVIDENCE_EXPECTED_HOST=baeg-endeuui-Macmini.local`, `PYTHON_EVIDENCE_GATE_THRESHOLD=0.10`, WorkingDirectory `/Users/baek-end/petcam-nightly-reporter`.
- active evidence identity(runtime venv import 실측): `python-evidence-raw-v1` / `croi-temporal-v1`.
- **runtime_verdict = B1R_RUNTIME_OK** (drift 없음). laptop nightly local main(1d681ff8)을 runtime 으로 가정하지 않고 Mac mini origin/main 기준 판정.

## 3. Cutoff

- `coverage_cutoff_started_at = 2026-07-22T02:45:33+00:00` = production `motion_clips.started_at` 최댓값(SELECT-only). 이 시각 이하만 역사 분모. 이후 신규 live clip 은 분모 불변.

## 4. Coverage before / after (동일 cutoff, SELECT-only 독립 대조)

| 지표 | before | after |
|---|---:|---:|
| eligible (r2_key≠∅ ∧ dur>0 ∧ ≤cutoff) | 16786 | 16786 |
| succeeded_with_active_run | 2841 (16.9%) | 2841 |
| allowlisted_terminal | 0 | 0 |
| open (queued+processing+failed_retryable) | 0 | 30 |
| silent_missing | 13945 | 13915 |
| coverage_verdict | COVERAGE_OPEN | COVERAGE_OPEN |

완료 등식 `eligible == succeeded + terminal ∧ silent_missing=0 ∧ open=0` **불충족**.

⚠️ `eligible` 는 r2_key 존재만 확인하고 **R2 object 존재는 검증하지 않는다** → 처리가능 clip 을 과대계상.

## 5. Backfill 처리 (Task 6) — canary → STOP

**배포**: nightly `origin/main` `618f4f8→a7635a9` FF-only push(enqueuer 하드닝, worker 무변경) → Mac mini `merge --ff-only`.

1. **dry-run**(범위 2026-06-17..2026-07-22, limit 30, cutoff): `missing=30 enqueued=0` — missing-scan 전진 확인, mutation 0.
2. **enqueue 30**(source=historical, priority=10): `enqueued=30`.
3. **process**(launchctl kickstart, production env): worker `jobs=30 ok=1 reused=1 fail=28 terminal=0`.
   - batch(30)에 내 canary 28 + 다른 recent due job 2 혼입. `ok/reused=2`는 recent clip, `fail=28`은 내 old clip.
   - 내 30 canary 최종: **28 failed_retryable + 2 queued, active run 0/30**, 실패 코드 전부 `r2_download_failed`.
   - 실패 clip 날짜: 2026-06-17(19)+2026-06-22(9) = old cohort.
4. **근본 원인**(read-only R2 HEAD 표본): 2026-06-17·06-22 = 0/6 존재, 2026-07-02~07-21 = 6/6 존재. **보존창(~30일) 이전 object 삭제.**
5. **STOP**: canary 93% 실패 = 건강한 canary 아님 → 계약대로 **대량 enqueue 금지**, bounded drain 반복 미착수.

**terminal / live 영향 / temp**: allowlisted_terminal 아직 0(잔여 28은 max_attempts 후 `failed_terminal(r2_download_failed)`로 자연 수렴). live priority(100)>historical(10) 유지, live 미영향. temp media 는 worker 가 `TemporaryDirectory`+즉시 unlink(잔류 0).

**잔여물**: canary 30 job(28 failed_retryable+2 queued)은 재시도→terminal 자연 수렴. handoff 승인 write=enqueue 뿐이라 job DELETE/강제 terminal 안 함(fail-closed).

**실패 clip 링크**: motion→camera 인가 mapping 을 확인 못 해 `label.tera-ai.uk` URL 을 붙이지 않는다. clip8 만 사적으로: 실패는 전부 old-cohort r2 소실(가짜 URL·R2 key 생성 금지 준수).

## 6. Selector v1 vs v2 (Task 7 diagnostic, current 2841 evidence, cutoff 동일)

> coverage 미완주 상태의 **진단용**(설계 §3.B). 최종 manifest 아님.

| stratum | v1 raw | v2 raw | v1 ep | v2 ep | v1 final | v2 final |
|---|---:|---:|---:|---:|---:|---:|
| absent | 0 | 347 | 0 | 24 | 0 | **24** |
| big_move | 1006 | 2643 | 14 | 69 | 14 | 8 |
| rest_micro | 576 | 644 | 7 | 36 | 7 | **25** |
| lick_water_food | 0 | 0 | 0 | 0 | 0 | 0 |
| wheel_object | 0 | 0 | 0 | 0 | 0 | 0 |
| hardcase | 1259 | 1259 | 48 | 48 | 30 | 12 |

- **굶김 해소 실증**: v1 은 hardcase-first 단일 배정이라 absent raw 를 0 으로 흡수. v2 multi-match 는 같은 clip 을
  absent 347·rest 644 로 드러내고, scarcity-first 가 hardcase(final 30→12)를 눌러 absent 24·rest 25 를 회복.
- **미충족**: 어느 strata 도 30 미달(absent 24·rest 25·big 8·hardcase 12·lick/wheel 0) → `manifest_emitted=False`.
  원인 2겹: ① coverage 미완주(처리 evidence 2841 뿐, backfill media-block), ② lick/wheel 은 current evidence 에
  실제 신호 0 = **semantic 부족**.
- camera_count=3, date_count=7 (v2 final pool). clip_overlap=0, episode_overlap=0.
- exact human join 만 허용(fuzzy filename/time join 금지, 테스트로 고정). current evidence 에서 lick/wheel raw=0 →
  사람 retrieval 신호로도 두 strata 안 떠오름.

## 7. 무결성 / 독립 재계산 (Task 7)

- pool_sha256 = `614615b0801ccc2a4eb47906b21803bba489e0493bfded48140eecb3cee624f9`.
- 독립 recompute(`recompute_local_vlm_evidence_b1r.py`, probe/selector 미import, stdlib canonical 재구현):
  **MATCH** (final counts·clip/episode overlap 0·pool SHA 전부 일치).
- coverage snapshot 은 서로 다른 구현(순수 partition + closure 등식)으로 독립 대조.

## 8. 금지동작 감사 (mutation 0)

- model download/inference: **0**.
- VLM / behavior label / GT / activity / app write: **0**.
- B2 migration / API / UI: **0**.
- production run UPDATE/DELETE: **0** (append-only 보존).
- MacBook worker 실행 / expected-host 우회: **0**.
- committed media / R2 key / signed URL / raw secret: **0** (per-clip pool 은 `storage/` gitignored).
- **승인 write = `python_evidence_jobs` enqueue 30건(historical)** 뿐. 그 외 테이블 mutation 0.

## 9. 최종 판정 우선순위

```
B1R_REJECT_INTEGRITY        → 아님 (recompute MATCH, 금지 write 0)
B1R_BLOCKED_RUNTIME_DRIFT   → 아님 (runtime a7635a9=origin/main, host/service 계약 일치)
B1R_BLOCKED_EVIDENCE_COVERAGE → ✅ 채택 (완료 등식 불충족, silent_missing 13915·open 30)
B1R_BLOCKED_SEMANTIC_DATA   → (부차) coverage 완주 시에도 lick/wheel 0 semantic 부족 잔존
B1R_DATA_AVAILABLE          → 아님 (어느 strata 도 30 미달, manifest 미발행)
```

**verdict = `B1R_BLOCKED_EVIDENCE_COVERAGE`.** 기준(6×30, 30분 episode, 수량) 사후 완화 없음.

## 10. 다음 허용 작업 (owner 결정, 이번 세션 착수 금지)

1. **coverage 분모 정정**: coverage audit 에 R2 object 존재 검증 추가 → `eligible` 를 처리가능 clip 으로 좁힘.
   현재 `eligible=16786` 은 media 소실분 포함 과대치.
2. **backfill 범위 한정**: R2 보존창 이내(대략 2026-07-02~) cohort 만 backfill → 단, recent-only 편향 주의.
3. **역사 evidence 를 원하면 capture 파이프라인**: R2 보존기간 연장 또는 evidence-at-capture(삭제 전 evidence 생성).
4. selector v2 는 **회귀 기준점으로 보존**(굶김 해소 실증). coverage 정정 후 future cohort 로 6×30 재판정.
5. 잔여 canary job 28건은 자연 terminal 수렴 확인만.

**B1(B1_BLOCKED_DATA_INSUFFICIENT) 산출물·보고서는 수정하지 않았다. 전부 B1R namespace 신규 파일.**

## 11. commit / push 상태

- lab worktree branch `codex/local-vlm-evidence-web-gt`: Task 0~7 산출물 커밋 후 push (아래 §12).
- nightly-reporter: `feat/local-vlm-evidence-b1r` push + `origin/main` FF `a7635a9`.
- 다른 세션 untracked 파일 add/commit/delete 안 함.

## 12. 산출물

- `reports/local-vlm-evidence-b1r/{RUNTIME-SNAPSHOT,COVERAGE-BEFORE,COVERAGE-AFTER,BACKFILL-PROGRESS}.md`
- `experiments/local-vlm-evidence-analyst/{b1r-coverage-before,b1r-coverage-after,b1r-candidate-availability}.json` + `B1R-CANDIDATE-AVAILABILITY.md`
- `storage/local-vlm-evidence-analyst/b1r-candidate-pool.json` (gitignored)
- code: `scripts/audit_local_vlm_evidence_b1r_coverage.py`, `scripts/recompute_local_vlm_evidence_b1r.py`, selector v2/probe v2, nightly enqueuer 하드닝 + 각 테스트.
