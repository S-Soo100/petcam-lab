# REPORT — Python Evidence S1 Recovery

**verdict:** `S1R_HOLD_INCOMPLETE`
**실행일:** 2026-07-17 (KST)
**runtime host:** `baeg-endeuui-Macmini.local`
**feature HEAD:** `7a260b97f0e30ad97fb9a5f62fefdb066c964074` (pushed `feat/python-evidence-s1-benchmark`)
**TEST-SHEET:** [`TEST-SHEET.md`](TEST-SHEET.md) (`PRE_REGISTERED`, 사후 변경 없음)
**선행:** `S1_HOLD_RUNTIME_BUDGET` (`experiments/python-evidence-s1-throughput/`, 보존)

---

## 1. 요약

A6 실패의 확정 원인(FFmpeg PATH 전파 누락)을 fail-closed preflight 로 고치고, 동결 workload 를 안전창별 resume 로 완주하려 했다. 첫 안전창(MPS window 1, 333 records)에서 **A6 는 정상 동작**했으나, **3개 clip 이 `extract_six` 프레임 추출에 결정론적으로 실패**함을 발견했다. 이 3 clip × 2 cache × 3 repeat = **18 measured key 는 영구 미완성**이라, 동결 계약(§9 PASS = 전체 key 완전성)상 `S1R_PASS` 는 원리적으로 불가능하다. 따라서 불필요한 추가 계산(window 2+·CPU)을 중단하고 `S1R_HOLD_INCOMPLETE` 로 판정한다. **CROI 처리량 수치는 게이트를 크게 상회하나 참고값(informative)일 뿐 PASS 근거가 아니다.**

## 2. A6 RED→GREEN (확정 원인 + 수정 검증)

| 단계 | PATH | `shutil.which("ffmpeg")` | `--verify-deps` ffmpeg | rc |
|---|---|---|---|---|
| **RED (재현)** | `/usr/bin:/bin:/usr/sbin:/sbin` (SSH 비로그인) | `None` | `ffmpeg_missing` | 3 |
| **GREEN (수정)** | `/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin` | `/opt/homebrew/bin/ffmpeg` | `PASS` | 0 |

- 확정 원인 = benchmark 실행 환경 PATH 에 `/opt/homebrew/bin` 누락(기존 보고서의 PYTHONPATH/temp 추정 정정, additively).
- 수정 = detector/R2/temp 부작용 전 `verify_executable_dependency` fail-closed 검사(`ffmpeg_missing`/`ffmpeg_unusable`). production `reporter/vlm_frames.py` 미수정.
- **A6 canary (1 clip `beb2e0b9`):** frames=6, decodable=6, temp cleanup 후 media=0, detector/VLM 호출 0.

## 3. 실행 segment

| window | device | 시작 KST | 종료 KST | 안전창 | exit | records added | temp after |
|---|---|---|---|---|---|---|---|
| 1 | mps | 11:44:06 | 12:04:07 | 45분 | 3 (HOLD_RUNTIME_BUDGET, deadline 1201s) | 333 (0→333) | 0 |
| 2 | mps | 12:06~12:14 probe | — | 22→16분 (NO_GO) | 미실행 | 0 | 0 |

- window 2 는 안전창 `<25분`(activity-worker 12:29 근접)으로 probe NO_GO, adapter 미실행. 이후 PASS 불가 확정으로 halt.
- 각 window 시작 전 flock 프로브(activity/vlm-candidate advisory lock free) + 다음 job 까지 분 계산.

## 4. 완전성 (동결 계약 §4/§7)

| device | expected | success | missing | unexpected | dup-success | complete |
|---|---|---|---|---|---|---|
| MPS | 672 | 215 | 457 | 0 | 0 | ❌ |
| CPU | 384 | 0 (미착수) | 384 | — | — | ❌ |

- MPS missing 457 = **A6 영구 결정론 실패 18** + **의도적 halt 로 미실행 439**.
- missing_by_condition(MPS): A6 135 / B12 129 / CROI 128 / DALL 65.
- **동일 measured key 중복 성공 record = 0** (success-only resume 계약 준수).

## 5. A6 결정론 실패 — read-only 6단계 진단

실패 clip `7af0e302`(dur 5.202s) vs 유사 길이 성공 clip `9b784542`(dur 5.504s) 비교(production extract_six·영상 미수정):

| 항목 | 실패 `7af0e302` | 성공 `9b784542` |
|---|---|---|
| (2) format.duration / stream.duration / probe_duration | 5.202 / 5.202 / 5.202 (일치) | 5.504 / 5.504 / 5.504 (일치) |
| (5) decodable frames / 마지막 decodable ts | **13** / 5.0575s | 32 / 5.3626s |
| (3) sample_times | 0.433, 1.300, 2.167, 3.034, 3.901, 4.769 | 0.459, 1.376, 2.293, 3.211, 4.128, 5.045 |
| (4) 각 timestamp ffmpeg rc | **234,234,234,234**,0,0 | 0,0,0,0,0,0 |
| (4) stderr tail | 이른 4개 "Conversion failed!" | 전부 정상 frame=1 |
| (6) 첫 실패 timestamp | **0.433s (이른 쪽)** | 없음 |

- **핵심:** 실패는 clip 이 짧아서가 아니다(늦은 timestamp 3.901/4.769s 는 성공). `extract_six` 의 input-side seek(`ffmpeg -ss t -i`)이 **decodable frame 이 sparse 한 이 clip 의 이른 timestamp 에서 rc=234 'Conversion failed!'**로 파일을 못 만든다. duration mismatch 도 아니다(3자 일치). production extract_six × 이 clip 인코딩(sparse-keyframe, ~13 decodable frames)의 결정론적 상호작용.
- 3 clip 전부 3/3 repeat 실패, 성공 0 → **retry 로 회복 불가**. 다른 29 A6 clip 은 정상.
- B12/CROI/DALL 은 Gate `sample_frames` 경로(별도)라 이 3 clip 도 영향 없을 수 있으나, A6 baseline 완전성은 회복 불가.

## 6. CROI 처리량 (참고값 — PASS 근거 아님)

| cell | count | p50 (s) | p95 (s) | capacity (clips/h) | ratio vs 80 | 160 게이트 |
|---|---|---|---|---|---|---|
| CROI mps cold_independent | 64 | 1.799 | 2.5081 | **1435.36** | 17.94× | 상회(참고) |
| CROI mps warm_same_run | — | — | — | 미측정(window 1 warm 미도달) | — | — |

- **완전성 미충족이므로 이 수치는 informative-only.** 동결 게이트 사후 완화 없음.
- 자원(참고): peak RSS **1.10 GiB**(<4), peak temp **0.016 GiB**(<2).

## 7. 독립 재계산 대조

- harness aggregation(`aggregate`/`percentile`) 미import, numpy 'linear' percentile 재구현한 별도 read-only 프로세스로 raw JSONL 재계산.
- **CROI mps cold_independent: count 64 / p50 1.799 / p95 2.5081 / capacity 1435.36 — harness `summary.json` 과 정확히 일치.**
- 완전성(expected 672/success 215/missing 457/unexpected 0/dup 0)도 독립 재계산 일치.

## 8. 안전성

| 항목 | 결과 |
|---|---|
| temp media (종료 후) | 0 |
| DB write / R2 write | 0 / 0 (R2 GET·Supabase SELECT only) |
| Claude/VLM 호출 | 0 |
| LaunchAgent bootout/bootstrap/kickstart/plist/env | 0 |
| production job 지연 | 없음 (activity-worker lock mtime 11:29 불변 = 실행창 내 미발화) |
| service LastExitStatus | 전부 0 (router-features PID 749 불변) |
| production HEAD | nightly `19a1fe5` · gate `f182ea4b` 불변(baseline==final) |

## 9. original ↔ recovery 분리

- **original:** `experiments/python-evidence-s1-throughput/` — `S1_HOLD_RUNTIME_BUDGET`, 346 records. **삭제·재작성 없음.**
- **recovery:** `experiments/python-evidence-s1-recovery/` — 빈 output 에서 새로 측정, 333 records, raw sha256 `e77ab1ec…`. **original partial 을 recovery raw 로 복사하지 않음.**

## 10. TEST-SHEET 대비

- 사후 변경 없음. 표본(32/16)·threshold(0.10)·warmup(1)·repeats(3)·160 clips/h 게이트 모두 원본 동결값 유지.
- 유일한 운영 변경(여러 ≤20분 안전창 append-safe resume)은 사전등록대로 적용. **결과를 보고 workload·게이트를 축소하지 않음.**

## 11. 가설 판정 / decision

- H1(CROI 처리량 ≥160 AND 전체 안전+완전성)은 **완전성 미충족**으로 성립 불가. CROI 처리량 자체는 게이트를 크게 상회하나 완전성 gate 를 통과 못 함.
- **decision: `S1R_HOLD_INCOMPLETE`.** 근거: A6 3 clip(18 key) 결정론적 영구 실패 → 동결 계약상 전체 key 완전성 원리적 불가.

## 12. 다음 액션

1. **S2 blocked.** `S1R_PASS_CROI_THROUGHPUT` 만 S2 착수 허용 → 현재 미충족.
2. A6 baseline 을 완전성 계약에 포함할지 재설계 필요(새 spec + TEST-SHEET). 선택지: (a) A6 결정론 실패 clip 을 계약에서 명시 제외(사유 고정), (b) `extract_six` output-seek/frame-count 견고화(production 코드 변경 = 별도 승인), (c) 표본에서 sparse-decodable clip 정의·분리.
3. 위 재설계 전에는 CROI 처리량 수치를 adoption 근거로 재사용 금지.

## 13. 한계

- window 1 단일 안전창 데이터라 CROI cold 64 record 기반(warm·CPU 미측정). 완전성 미충족이 지배 결론이므로 처리량 정밀도는 부차적.
- A6 진단은 3 clip 중 대표 1개(`7af0e302`)만 프레임 단위로 재현. 나머지 2개(`8c472464`, `cfa27599`)는 동일 증상(3/3 실패, dur 5.49~5.50s)으로 동일 원인 추정.
