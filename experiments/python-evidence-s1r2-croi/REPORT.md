# REPORT — Python Evidence S1R2: CROI/MPS/cold 단독 합격시험

**verdict:** `S1R2_PASS_CROI_THROUGHPUT`
**실행일:** 2026-07-17 (KST)
**runtime host:** `baeg-endeuui-Macmini.local` (hostname 실측)
**runtime feature HEAD:** `05c5354b0184cb710ed8d9bc8811d8b078b927e2` (pushed `feat/python-evidence-s1-benchmark`)
**TEST-SHEET:** [`TEST-SHEET.md`](TEST-SHEET.md) (`PRE_REGISTERED`, 사후 변경 없음)
**선행 (history 보존):** `S1_HOLD_RUNTIME_BUDGET`, `S1R_HOLD_INCOMPLETE`

---

## 1. 요약

S1R 은 비교용 A6 baseline 이 sparse-decodable clip 3개에서 결정론적으로 실패해 전체 key 완전성을
못 채워 HOLD 됐다. A6 는 CROI production path 의 선행 의존성이 아니므로, S1R2 는 질문을
**CROI/MPS/cold 단독 처리량 하나로 좁혀** 새 raw run 으로 사전등록·측정했다.

한 번의 자연 안전창(≈5분)에서 **warmup 32 + measured 96 = 128 record 를 완주**했다. 96/96
measured key 가 정확히 채워졌고(unexpected 0, duplicate 0), CROI/mps/cold capacity 는
**1,411.69 clips/h** 로 gate `160 clips/h` 의 **8.82배**다. 자원·운영 안전 gate 전부 통과했고,
harness 와 독립 재계산이 counts·percentile 까지 정확히 일치한다. → `S1R2_PASS_CROI_THROUGHPUT`.

PASS 는 **S2 raw-evidence shadow 구현계획 작성만** 허용한다. production selector 적용·자동
제외·행동 분류 승인이 아니다.

## 2. runtime 시작 여부

시작함(`BLOCKED_ENVIRONMENT` 아님). `--verify-deps` 로 `mps_available=True`,
checkpoint sha256 `cd1162b4…` 로드, import 실패 0, ffmpeg `not_required`(croi profile) 를
먼저 확인한 뒤 실행했다. preflight OK(host `baeg-endeuui-macmini`, head `05c5354b`,
window 35min, device mps), ffmpeg `not_required`.

## 3. 96-key 완전성 (정본)

| 항목 | 값 |
|---|---|
| expected measured keys | **96** |
| success | **96** |
| missing | **0** |
| unexpected | **0** |
| duplicate success | **0** |
| warmup records (통계 제외) | 32 |
| measured records | 96 |
| error records | 0 |
| total successful raw records | **128** (warmup 32 + measured 96) |

CROI/mps/cold repeat{1,2,3} × 32 clips = 96. A6/B12/DALL/warm/CPU key 는 0(profile 이 고정).
`s1r2_complete: True` (summary.meta), `complete: True` (gate).

## 4. 처리량·자원 + 160 gate

| 지표 | harness | 독립 재계산 | gate | 판정 |
|---|---|---|---|---|
| p50 (s/clip) | 1.835951 | 1.835951 | — | — |
| p95 (s/clip) | 2.550137 | 2.550137 | `<= 22.5` | ✅ |
| capacity (clips/h) | **1,411.6890** | **1,411.6890** | `>= 160` | ✅ (8.82×) |
| ratio vs projected 4cam p95(80s) | 17.6461 | 17.6461 | — | — |
| peak RSS | 1,185,300,480 B (1.104 GiB) | 동일 | `<= 4 GiB` | ✅ |
| peak temp | 16,763,565 B (15.99 MiB) | 동일 | `<= 2 GiB` | ✅ |

p95 = 2.55s → `3600/2.55 = 1,411.69`. gate 여유 8.82배(capacity/160), projected 단일카메라 대비 17.65배.

## 5. profile provenance + raw SHA

- execution profile: `croi-mps-cold` (device mps / conditions CROI / cache cold_independent, 불변)
- manifest SHA-256: `931ce37a772d921cf26017801003efebff8686a23a189eca9adcabf397b590d0` (동결, S1 과 동일)
- influx SHA-256: `885a45ba3974aa73e1e9bd19a37171829cf6b9174f926bedcf70f71cb20a5cc3` (동결, S1 과 동일)
- threshold 0.10 · warmup 1 · repeats 3 · budget-s 1200 · window-minutes 35
- checkpoint: `…/myPythonProjects/gecko-vision-gate/runs/gecko_v2/checkpoint_best_ema.pth`
  sha256 `cd1162b4…` (plan 의 `/Users/baek-end/gecko-vision-gate/…` 경로는 stale → canonical
  `myPythonProjects/` 로 실측 정정. S1R 감사에서도 동일 정정 기록됨)
- **새 raw SHA-256: `48ffe6e947fe9cada51462c9bdf42a74e39da0628d67cfb68aa6ae50dae2300e`**
  (`raw_results.jsonl`, gitignored — Mac mini 잔류)

## 6. previous raw 미사용 증거

- 새 output 은 빈 `experiments/python-evidence-s1r2-croi/`(TEST-SHEET 만 존재)에서 시작.
  실행 후 raw_results.jsonl 128 record 는 전부 CROI/mps/cold(다른 조건·cache 0).
- S1(`python-evidence-s1-throughput`)·S1R(`python-evidence-s1-recovery`) raw·summary 를
  복사/병합/import 하지 않았다. 독립 재계산은 새 raw 파일 하나만 읽는다([`recompute_independent.py`](recompute_independent.py)).
- 기존 CROI 참고치(S1 1,417/h · S1R 1,435/h)는 판정 계산에 넣지 않았다(별개 raw·별개 안전창).

## 7. 독립 재계산 (measurement integrity)

harness aggregator(`aggregate`/`percentile`/`evaluate_s1_gates`/S1R2 gate) 를 import 하지 않는
별도 read-only stdlib 프로세스([`recompute_independent.py`](recompute_independent.py))로 새 raw 만 재계산:

- counts **정확 일치**: total 128 / warmup 32 / error 0 / measured 96 / distinct 96 / dup 0 /
  missing 0 / unexpected 0.
- percentile **정확 일치**: p50 1.835951 · p95 2.550137 → capacity 1,411.6890 · ratio 17.6461.
- resource **정확 일치**: peak RSS 1,185,300,480 B · peak temp 16,763,565 B.

counts 불일치·percentile 이 판정을 바꾸는 차이 **없음** → `MEASUREMENT_INTEGRITY` reject 아님.

## 8. 운영 안전 (before/after audit)

증거: [`runtime-baseline-before.txt`](runtime-baseline-before.txt) ↔ [`runtime-baseline-after.txt`](runtime-baseline-after.txt)

| 안전 gate | before | after | 판정 |
|---|---|---|---|
| production nightly HEAD | `19a1fe56` | `19a1fe56` | 불변 ✅ |
| production gate HEAD | `f182ea4b` | `f182ea4b` | 불변 ✅ |
| production lab HEAD | `df7811c1` | `df7811c1` | 불변 ✅ |
| launchd 워커 exit code | 전부 0 | 전부 0 | ✅ |
| router-features PID | 749 (+child 847) | 749 (+child 847) | 무재시작 ✅ |
| 워커 로그 error/traceback | activity 40·backfill 4·router 296/2 | 동일 | Δ0 ✅ |
| activity/vlm flock 홀더 | 0 (free) | 0 (free) | ✅ |
| temp media (s1bench dir) | 0 | 0 | temp_leak_after=0 ✅ |
| DB write / R2 write | — | 0 / 0 | 정적 audit(SELECT·GET only) ✅ |
| Claude/VLM 호출 | — | 0 | 정적 audit(anthropic/claude/gemini 0) ✅ |
| LaunchAgent/plist/env | — | 미수정 | ✅ |

router-features(PID 749)는 별 트랙 상시 daemon(`router_features_main`)으로, benchmark 와 activity/vlm
lock 을 공유하지 않는 co-tenant. err.log 가 +96 줄 늘었으나 **error/traceback count 는 Δ0**(daemon
정상 출력). production job 지연·exit·error 증가 0.

## 9. 시험지 대비

사후 변경 **없음**. TEST-SHEET §6 게이트 숫자(96 / 160 / 4GiB / 2GiB) 그대로 적용.
`checkpoint` 경로만 plan stale → canonical 실측 정정(게이트·workload 무영향, S1R 과 동일 정정).

## 10. 가설 판정 · decision

- H0(완주 실패 or capacity<160 or 운영 위반) **기각**.
- H1(96/96 완주 + capacity≥160 + 운영 위반 0) **채택**.
- decision label: **`S1R2_PASS_CROI_THROUGHPUT`**.

## 11. 다음 액션

- **S2 allowed** — S2 raw-evidence shadow 구현계획 작성 허용(오직 계획 작성). production selector
  적용·자동 제외·행동 분류 승인은 여전히 blocked.
- A6/B12 standalone/DALL/CPU/warm 은 이 시험의 non-goal 로 종결(verdict 무관).
