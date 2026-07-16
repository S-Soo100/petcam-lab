# Python Evidence S1 Throughput Benchmark — REPORT

> **decision:** `S1_HOLD_RUNTIME_BUDGET`
> **실행일:** 2026-07-17 04:41~05:01 KST (MPS 20분 budget 소진)
> **실험 디렉토리:** `experiments/python-evidence-s1-throughput/`
> **TEST-SHEET:** [`TEST-SHEET.md`](TEST-SHEET.md)
> **raw artifacts:** `raw_results.jsonl` (346 records) · `summary.json`

---

## 1. 실행 환경 (동결)

| 항목 | 값 |
|---|---|
| 실행 host | `baeg-endeuui-Macmini.local` (Mac mini) |
| feature branch HEAD | `cf20dcef67648190fc141755117c1aba49bb8a7c` |
| worktree | `/Users/baek-end/pe-s1-benchmark` (isolated) |
| runtime 환경 | `petcam-nightly-reporter` uv venv + `PYTHONPATH=/Users/baek-end/pe-s1-benchmark` |
| checkpoint | `gecko-vision-gate/runs/gecko_v2/checkpoint_best_ema.pth` |
| checkpoint SHA256[:16] | `cd1162b4c95041bc` |
| gate_threshold | `0.10` (production activity-v1 동일) |
| MPS start | 04:41:33 KST |
| MPS deadline hit | 05:01 KST (elapsed 1200s exactly) |
| CPU | **NOT RUN** — HOLD_NO_SAFE_WINDOW (13 min < 25 min required) |
| nightly-reporter HEAD | `19a1fe5` |
| gecko-vision-gate HEAD | `f182ea4` |

---

## 2. 유입량 기준선 (frozen influx_snapshot)

| 지표 | 값 |
|---|---|
| observed cameras | 2 (`5b3ea7aa`, `f6599924`) |
| projected_4_camera_p95 | **80.0 clips/h** |
| required_capacity (2×) | **160.0 clips/h** |
| 32-clip manifest seed | `20260717` |

---

## 3. 실행 결과표 (MPS cold_independent, 부분 완료)

| 조건 | p50 (s) | p95 (s) | cap/h | RSS peak | temp peak | count |
|---|---|---|---|---|---|---|
| **A6** | — | — | — | — | — | 0 (FileNotFoundError 99건) |
| **B12 MPS cold** | 1.392 | 2.226 | 1,617 | 1.17 GiB | 16.7 MB | 67 |
| **CROI MPS cold** | 1.591 | 2.541 | 1,417 | 1.17 GiB | 16.7 MB | 67 |
| **DALL MPS cold** | 21.164 | 23.509 | 153 | 1.17 GiB | 16.7 MB | 33 (risk_control_only) |

- **MPS warm_same_run:** NOT RUN (20min deadline hit during cold_independent pass)
- **CPU:** NOT RUN — safe window insufficient (05:03 KST, 13 min < 25 min to next activity ~05:16)

### 독립 재계산 (raw JSONL 직접)

```python
# filter: cache_mode=cold_independent, not is_warmup, error_code=None, e2e_s > 0
B12  MPS cold (n=67): p50=1.392s  p95=2.229s  cap=1,614.8/h
CROI MPS cold (n=67): p50=1.591s  p95=2.553s  cap=1,410.1/h
DALL MPS cold (n=33): p50=21.164s p95=23.510s cap=153.1/h
```

summary.json vs 독립 재계산: p95 최대 Δ=0.012s (percentile 구현 반올림 차이, 결론 무영향).

### throughput_ratio

```
CROI MPS cap / projected_4_camera_p95 = 1,416.8 / 80.0 = 17.71x
CROI MPS cap / required_capacity(2×)  = 1,416.8 / 160.0 = 8.86x   ✅
```

→ 완료된 CROI cold_independent 셀 기준으로는 throughput gate PASS 범위.  
**단, warm pass·CPU·A6가 미완료이므로 본 비교를 PASS 근거로 쓰지 않는다.**

---

## 4. A6 FileNotFoundError 분석

전체 A6 records 99건 모두 `FileNotFoundError` (non-warmup 0건 유효).

**원인 추정:**  
`vlm_frames.extract_six`(nightly-reporter venv)가 내부적으로 FFmpeg temp 파일 경로를 참조할 때, `PYTHONPATH` 혼합 환경에서 nightly-reporter venv의 FFmpeg 바이너리가 pe-s1-benchmark temp 경로를 찾지 못하는 것으로 보임.  
A6는 기준선 조건이므로 후보(CROI) 평가에는 영향 없음. 다음 실행 전 A6 FFmpeg 경로 격리가 필요.

---

## 5. 안전 게이트 (summary.json `gates`)

| 게이트 | 결과 | 값 |
|---|---|---|
| throughput_pass (CROI MPS cold) | ✅ PASS | cap 1,417/h ≥ required 160/h |
| rss_pass | ✅ PASS | 1.17 GiB < 4 GiB |
| disk_pass | ✅ PASS | 16.7 MB < 2 GiB |
| all_pass | ✅ PASS (완료 셀 기준) | — |
| temp media 잔류 | ✅ ZERO | `/tmp` 0 · out-dir 0 |
| Claude/VLM call | ✅ ZERO | — |
| Supabase mutation | ✅ ZERO | — |
| runtime repo HEAD unchanged | ✅ | nightly `19a1fe5`, gate `f182ea4` |
| LaunchAgent exit/error 악화 | ✅ NONE | all last exit 0, runs=7 unchanged |

### 02:05 KST nightly deviation 검증

```
[worker] 07-17 02:05 clips=49 sampled=0 ok=0 fail=0 slack=OK actions={}
```

LaunchAgent last exit 0 ✅. 이 no-op은 handoff plan에서 미리 기록된 deviation이며 benchmark와 무관.

### cross_process_cache

```json
"cross_process_cache": "not_run_design_required"
```

설계·계약 부재로 미구현. 결과표에 보존.

---

## 6. 미완료 항목 (S1_HOLD 사유)

1. **MPS cold_independent 부분 완료** — 346/~512 records (A6 포함 시 모든 clips 미완료; B12/CROI 67건은 32 clip 중 절반 이하)
2. **MPS warm_same_run 미실행** — deadline 소진으로 진입 불가
3. **CPU 미실행** — 완료 후 안전창 13분 (< 25분 계약)
4. **A6 완전 실패** — 0 유효 레코드 (FFmpeg 경로 문제)

---

## 7. 결론 — Verdict

> ### `S1_HOLD_RUNTIME_BUDGET`

frozen benchmark가 20분 budget 내에 완료되지 못했다.  
완료된 CROI MPS cold 셀은 throughput_ratio 17.71x (required 2x의 8.86배)로 한계 범위 밖에 있으나,  
warm/CPU/A6를 포함한 full workload가 필요하며 현재 결과만으로 PASS를 주장할 수 없다.

**다음 액션 (제안):**
1. **A6 경로 수정** — extract_six FFmpeg 경로를 pe-s1-benchmark 환경에서 격리·검증
2. **실행 시간 최적화** — warmup 1→0, repeat 3→2로 시험하거나, 별도 창(더 긴 안전창)에서 실행
3. **S1 재실행** — A6 수정 + 더 넓은 안전창(> 60분) 확보 후 full workload 재시도
4. **CPU 분리 실행** — CPU는 MPS와 다른 시간에 독립 실행 (manifest 16-clip subset 사용)

---

## 8. 한계

- **일반화 범위:** S1은 `5b3ea7aa`·`f6599924` covered subset만. `90119209` 일반화 금지.
- **partial cold만 완료:** 완료된 67건은 full 32-clip repeat=3이 아님. 일부 clip은 warmup만 포함.
- **A6 비교 불가:** B12/CROI vs A6 delta를 이 실행에서 측정할 수 없음.
- **warm cache 이익 미측정:** download 제외 처리비용(warm)을 이번에 측정하지 못함.
- **S1 성공 ≠ production 배포:** S1 PASS 여부와 무관하게 S2 raw evidence shadow 계획 착수만 의미.

---

*시험지 사후 변경 없음. TEST-SHEET.md PRE_REGISTERED 그대로.*
