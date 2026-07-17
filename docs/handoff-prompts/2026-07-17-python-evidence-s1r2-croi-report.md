# S1R2 CROI 단독 합격시험 — 실행 보고

**verdict:** `S1R2_PASS_CROI_THROUGHPUT`
**S2:** allowed (S2 raw-evidence shadow 구현계획 작성만 허용 — production 적용 아님)

---

## HANDOFF_OK (validator 전문)

```
HANDOFF_OK task=python-evidence-s1r2-croi repo=python-evidence-s1 commit=74cc02c0 runtime=scheduled-job@baeg-endeuui-Macmini.local
```

실행 시작 시 execution_repo HEAD == manifest commit_sha(`74cc02c0…`) 재확인 후 구현 착수. 구현·사전등록 커밋 뒤 runtime HEAD = `05c5354`.

## 1. exact verdict

`S1R2_PASS_CROI_THROUGHPUT` (harness gate + 독립 재계산 일치).

## 2. runtime 시작 여부

**시작함** (`BLOCKED_ENVIRONMENT` 아님). `--verify-deps`: mps_available=True, checkpoint sha `cd1162b4…` 로드, import 실패 0, ffmpeg not_required. preflight OK(host `baeg-endeuui-macmini`, head `05c5354b`, window 35min, mps). 한 안전창(≈5분)에서 완주, exit 0.

## 3. 96-key 완전성

| expected | success | missing | unexpected | duplicate |
|---|---|---|---|---|
| **96** | **96** | **0** | **0** | **0** |

- warmup 32 (통계 제외) + measured 96 = total successful **128**, error record 0.
- CROI/mps/cold repeat{1,2,3} × 32 clips = 96. A6/B12/DALL/warm/CPU key = 0.

## 4. p50/p95/capacity + 160 gate

- p50 = **1.8360 s/clip**, p95 = **2.5501 s/clip** (gate p95 `<= 22.5s` ✅)
- capacity = **1,411.69 clips/h** vs gate **160 clips/h** → **8.82× 초과** ✅
- ratio vs projected 4cam p95(80s) = 17.65×
- throughput_pass = True

## 5. profile provenance + 새 raw SHA

- profile `croi-mps-cold` (mps / CROI / cold_independent, 불변)
- manifest SHA `931ce37a…` · influx SHA `885a45ba…` (동결, S1 과 동일 입력)
- threshold 0.10 · warmup 1 · repeats 3 · budget 1200s
- checkpoint `…/myPythonProjects/gecko-vision-gate/runs/gecko_v2/checkpoint_best_ema.pth` (plan 경로 stale → canonical 실측 정정)
- **새 raw SHA-256: `48ffe6e947fe9cada51462c9bdf42a74e39da0628d67cfb68aa6ae50dae2300e`**

## 6. previous raw 미사용 증거

빈 `experiments/python-evidence-s1r2-croi/`(TEST-SHEET 만)에서 시작 → 새 raw 128 record 전부 CROI/mps/cold. S1/S1R raw·summary 복사·병합·import 0. 독립 재계산은 새 raw 하나만 읽음. 기존 CROI 참고치(1,417/1,435 h)는 판정 계산 미포함.

## 7. independent recomputation

harness aggregator 미import stdlib 프로세스(`recompute_independent.py`)로 재계산:
counts 정확 일치(128/32/0/96/96/0/0/0), percentile 정확 일치(p50 1.835951·p95 2.550137→cap 1,411.6890·ratio 17.6461), resource 정확 일치(RSS 1,185,300,480 B·temp 16,763,565 B). → MEASUREMENT_INTEGRITY reject 아님.

## 8. 운영 안전 증거

| gate | 결과 |
|---|---|
| production HEAD (nightly `19a1fe56` / gate `f182ea4b` / lab `df7811c1`) | before==after **불변** ✅ |
| RSS peak | 1.104 GiB `<= 4 GiB` ✅ |
| temp peak / temp_leak_after | 15.99 MiB `<= 2 GiB` / **0** ✅ |
| DB write / R2 write | **0 / 0** (SELECT·GET only, 정적 audit) ✅ |
| Claude/VLM 호출 | **0** (anthropic/claude/gemini 0) ✅ |
| LaunchAgent/plist/env/스케줄 | **미수정** ✅ |
| launchd 워커 exit / router-features PID(749) / error·traceback Δ | 0 / 무재시작 / Δ0 ✅ |
| activity·vlm flock | free (홀더 0) ✅ |

증거: `experiments/python-evidence-s1r2-croi/runtime-baseline-{before,after}.txt`.

## 9. feature final SHA + push 상태

- runtime HEAD (측정 시점) = `05c5354b0184cb710ed8d9bc8811d8b078b927e2`
- 이 보고·SOT 커밋이 feature final SHA → `git push origin feat/python-evidence-s1-benchmark` 완료, main merge 없음. 실제 SHA 는 push 로그·`git log -1` 참조(자기참조 회피).

## 10. S2 allowed 또는 blocked

**S2 allowed** — `S1R2_PASS_CROI_THROUGHPUT` 는 S2 raw-evidence shadow **구현계획 작성만** 허용한다. production selector 적용·자동 제외·행동 분류 승인은 여전히 blocked.

---

**최종 feature SHA:** 이 커밋 = feature branch tip (`git log -1 --format=%H` / push 로그 참조) — `git push origin feat/python-evidence-s1-benchmark` 완료, main merge 없음.
