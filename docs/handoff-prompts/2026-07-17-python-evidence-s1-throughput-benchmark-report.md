# Python Evidence S1 Throughput Benchmark — 실행 보고 (2026-07-17)

> **verdict:** `S1_HOLD_RUNTIME_BUDGET`
> **실행 host:** `baeg-endeuui-Macmini.local`
> **feature branch HEAD:** `cf20dcef67648190fc141755117c1aba49bb8a7c`
> **정본 보고서:** [`experiments/python-evidence-s1-throughput/REPORT.md`](../../experiments/python-evidence-s1-throughput/REPORT.md)

---

## 요약

MPS 벤치마크를 Mac mini에서 실행(04:41:33 KST). 20분 hard budget 소진으로 cold_independent pass 부분 완료(346 records / ~1024 planned). warm_same_run·CPU·A6 미실행.

완료된 CROI MPS cold 셀: **p95=2.541s, cap=1,417/h, throughput_ratio=17.71x** (required 2×의 8.86배). Resource/safety gates 전부 통과. 단, full workload가 미완이므로 PASS 불가.

## 실행 요약

| 항목 | 값 |
|---|---|
| MPS 실행 | 04:41~05:01 KST (20분 budget 소진) |
| record count | 346 (cold_independent 부분; B12/CROI 67건, DALL 33건, A6 0건) |
| CPU | HOLD_NO_SAFE_WINDOW (13분 잔여 < 25분 계약) |
| 안전 위반 | 없음 |
| temp media 잔류 | 0 |
| runtime repo HEAD 변경 | 없음 |

## 핵심 수치

```
CROI MPS cold: p50=1.591s / p95=2.541s / cap=1,417 clips/h
throughput_ratio (cap / projected_4cam_p95) = 1417 / 80 = 17.71x
required capacity (2×) = 160 clips/h → CROI 8.86x초과
```

## 독립 재계산 일치

raw JSONL 직접: CROI p95=2.553s / cap=1,410/h (summary 대비 Δ=0.012s — percentile 반올림 차이, 결론 무영향)

## A6 전량 실패

99/99 records: `FileNotFoundError`. 기준선 측정 불가.

**원인 확정 (2026-07-17 10:50 KST 재검증):** SSH 비로그인 PATH에는 `/opt/homebrew/bin`이 없었고, FFmpeg는 `/opt/homebrew/bin/ffmpeg`에 존재했으며 같은 Python에서 `shutil.which("ffmpeg")`는 None이었다. 따라서 A6 실패 원인은 PYTHONPATH/temp가 아니라 benchmark 실행 환경의 PATH 전파 누락이다(production `extract_six` 결함 아님).

## 다음 필요 조치

1. A6 FFmpeg 경로 격리 수정 후 재실행
2. 더 넓은 안전창(> 60분) 확보 또는 실행 예산 확장
3. CPU는 MPS와 별도 시간대 독립 실행

## 관련 artifact

- raw: `experiments/python-evidence-s1-throughput/raw_results.jsonl` (346 records)
- summary: `experiments/python-evidence-s1-throughput/summary.json`
- report: `experiments/python-evidence-s1-throughput/REPORT.md`
- TEST-SHEET: `experiments/python-evidence-s1-throughput/TEST-SHEET.md`
- handoff: `storage/handoffs/2026-07-17-python-evidence-s1-runtime-execution.md`
