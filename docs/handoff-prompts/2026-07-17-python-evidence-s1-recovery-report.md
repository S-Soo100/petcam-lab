# Python Evidence S1 Recovery — 완료 보고서

**verdict:** `S1R_HOLD_INCOMPLETE`
**S2:** blocked
**작성:** 2026-07-17 KST · **runtime host:** `baeg-endeuui-Macmini.local`
**feature commit:** `7a260b97f0e30ad97fb9a5f62fefdb066c964074` (pushed `feat/python-evidence-s1-benchmark`)
**상세 REPORT:** [`experiments/python-evidence-s1-recovery/REPORT.md`](../../experiments/python-evidence-s1-recovery/REPORT.md) · **TEST-SHEET:** [`experiments/python-evidence-s1-recovery/TEST-SHEET.md`](../../experiments/python-evidence-s1-recovery/TEST-SHEET.md)

---

## 단일 verdict

**`S1R_HOLD_INCOMPLETE`** — A6 baseline 3 clip × 2 cache × 3 repeat = **18 measured key 가 결정론적으로 영구 미완성**. 동결 계약(§9 PASS = 전체 key 완전성)상 `S1R_PASS` 는 원리적으로 불가능하므로 불필요한 추가 계산을 중단했다. CROI 처리량은 게이트를 크게 상회하나 **참고값**일 뿐 PASS 근거가 아니다.

## A6 RED→GREEN + canary

- **RED 재현:** PATH `/usr/bin:/bin:/usr/sbin:/sbin`(SSH 비로그인) → `shutil.which("ffmpeg")=None` → `--verify-deps` `ffmpeg=ffmpeg_missing` rc=3.
- **GREEN:** PATH `/opt/homebrew/bin:…` → `ffmpeg=PASS` rc=0. detector/R2/temp 부작용 전 fail-closed(`verify_executable_dependency`). production `vlm_frames.py` 미수정.
- **canary (clip `beb2e0b9`):** frames=6, decodable=6, temp cleanup 후 media=0, detector/VLM 호출 0.
- 확정 원인 = 실행 PATH `/opt/homebrew/bin` 누락(기존 PYTHONPATH/temp 추정 additively 정정).

## feature commit / push

- `8236712` fix: A6 FFmpeg 실행환경 사전검사 (preflight + 원인 정정)
- `7a260b9` test: recovery 분할 실행 계약 동결 (success-only resume + 완전성 + TEST-SHEET) — **push 완료**
- 본 보고/SOT commit 은 이 뒤에 추가.

## Mac mini hostname & production 불변 증거

- hostname `baeg-endeuui-Macmini.local`, isolated worktree `/Users/baek-end/pe-s1-benchmark` @ `7a260b9`.
- **production HEAD 불변:** nightly `19a1fe56792c` · gate `f182ea4b59c1` (baseline == final).
- **LaunchAgent 불변:** bootout/bootstrap/kickstart/plist/env 0. 전 service `LastExitStatus=0`, router-features PID 749 불변.
- **production job 지연 없음:** activity-worker lock mtime `11:29:20` 불변(실행창 내 미발화).

## 실행 segment (KST / 안전창 / exit / records)

| window | device | 시작 | 종료 | 안전창 | exit code | records added |
|---|---|---|---|---|---|---|
| 1 | mps | 11:44:06 | 12:04:07 | 45분 | 3 (deadline 1201s) | 333 (0→333) |
| 2 | mps | 12:06~12:14 probe | 미실행 | 22→16분(NO_GO) | — | 0 |

window 2 는 안전창 <25분(activity 12:29 근접)으로 미실행, 이후 PASS 불가 확정으로 halt.

## MPS cold/warm · CPU completeness (expected/actual/missing/dup-success)

| device/cell | expected | actual success | missing | duplicate-success |
|---|---|---|---|---|
| MPS 전체 measured | 672 | 215 | 457 (A6 영구 18 + 미실행 439) | 0 |
| MPS CROI cold | 완주 아님 | 64 record | — | 0 |
| MPS CROI warm | — | 미측정(warm pass 미도달) | — | — |
| CPU reduced | 384 | 0 (미착수) | 384 | — |

## CROI p50/p95/capacity + 160 게이트 (참고값)

- CROI mps **cold_independent:** count 64 · p50 **1.799s** · p95 **2.5081s** · capacity **1435.36 clips/h** · ratio **17.94× vs 80** → 160 게이트 상회(**informative-only**).
- 자원: peak RSS **1.10 GiB**(<4) · peak temp **0.016 GiB**(<2).

## 독립 재계산 대조

- harness aggregation 미import, numpy 'linear' percentile 재구현 별도 read-only 프로세스.
- CROI cold **count/p50/p95/capacity 가 harness `summary.json` 과 정확히 일치.** 완전성 카운트도 일치.

## temp media · DB/R2 mutation · Claude/VLM · LaunchAgent

- temp media 종료 후 **0**. DB write **0** · R2 write **0**(GET·SELECT only). Claude/VLM **0**. LaunchAgent 조작 **0**, 지연/exit·error 증가 **0**.

## original ↔ recovery 분리

- original `experiments/python-evidence-s1-throughput/`(`S1_HOLD_RUNTIME_BUDGET`, 346 records) **삭제·재작성 없음**.
- recovery `experiments/python-evidence-s1-recovery/`(빈 output 새 측정, 333 records, raw sha256 `e77ab1ec…`) — **original partial 미복사**.

## A6 18 key 영구 미완성 — read-only 진단 확정

실패 `7af0e302`(5.202s) vs 성공 `9b784542`(5.504s):
- format/stream/probe duration 3자 일치(mismatch 아님).
- 실패 clip decodable frame **13개**(성공 clip 32개) = sparse.
- `extract_six` input-seek(`ffmpeg -ss t -i`)이 **이른 timestamp(0.43~3.03s)에서 rc=234 'Conversion failed!'** 로 파일 미생성, 늦은 것(3.9/4.77s)만 성공 → 6개 미확보.
- **'clip 짧음' 아님**(늦은 프레임 성공). 3 clip 전부 3/3 실패, retry 회복 불가. production extract_six×인코딩 상호작용, 결정론적. **production 코드·영상 미수정.**

## S2 allowed/blocked

**blocked.** `S1R_PASS_CROI_THROUGHPUT` 만 S2 착수 허용 → 미충족.

## 아직 검증 못한 항목 + stop reason

- **미검증(의도적):** CROI warm, CPU reduced, 전체 key 완전성.
- **stop reason:** A6 3 clip(18 key) 결정론적 영구 실패로 **동결 계약상 전체 key 완전성이 원리적으로 불가능** → `S1R_PASS` 불가 확정 → 불필요한 추가 계산 중단. TEST-SHEET·완전성 기준 사후 변경 없음.

## 다음

1. A6 baseline 을 완전성 계약에 어떻게 둘지 재설계(새 spec + TEST-SHEET): (a) 결정론 실패 clip 명시 제외, (b) `extract_six` 견고화(production 변경=별도 승인), (c) sparse-decodable clip 표본 분리.
2. 재설계 전 CROI 처리량 수치 adoption 재사용 금지.
