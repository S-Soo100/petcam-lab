# Python Evidence S1R2 CROI Acceptance Design

**상태:** 승인됨  
**작성일:** 2026-07-17  
**선행 기록:** `S1_HOLD_RUNTIME_BUDGET`, `S1R_HOLD_INCOMPLETE`  
**목표:** production 후보인 CROI의 Mac mini MPS cold 처리량과 운영 안전만 새 raw run으로 검증해 PASS 또는 REJECT한다.

## 1. 왜 새 시험이 필요한가

S1R은 A6/B12/CROI/DALL/CPU 전체 key 완전성을 하나의 PASS 조건으로 묶었다. CROI는 `1,435 clips/h`의 참고 처리량을 보였지만, 비교 기준선 A6가 sparse-decodable 영상 3개에서 결정론적으로 실패해 전체 시험이 HOLD가 됐다.

A6는 CROI production data path의 선행 의존성이 아니다. CROI는 Gate `sample_frames(..., 12)` → gecko detector → bbox ROI dense OpenCV flow를 직접 실행한다. 따라서 A6 baseline availability를 CROI 채택 게이트에 결합한 것은 질문보다 넓은 시험 계약이었다.

S1R2는 이전 결과를 PASS 근거로 재사용하지 않고, 질문을 아래 하나로 좁혀 새로 사전등록한다.

> CROI MPS cold path가 frozen 32 clips에서 measured 3회를 완주하고, projected 4-camera p95의 2배인 `160 clips/h` 이상을 production 운영 영향 없이 처리하는가?

## 2. 시험 범위

### 합격 대상

- condition: `CROI` only
- device: `mps` only
- cache mode: `cold_independent` only
- frozen clips: 기존 32개 manifest 그대로
- warmup: clip당 1회, 통계 제외
- measured repeats: clip당 3회
- expected measured keys: `32 × 3 = 96`
- expected successful raw records: warmup 32 + measured 96 = 128
- threshold: `0.10`
- 처리량 gate: CROI MPS cold p95 `<=22.5s/clip`, 즉 capacity `>=160 clips/h`

### 이번 시험에서 실행하지 않는 항목

- A6: baseline availability 진단으로 S1R에 역사 기록 완료
- B12 단독: CROI 내부에서 동일 Gate sampling/detector 단계가 실제 실행됨
- DALL: risk-only 대조군이며 production 후보 아님
- CPU: production Mac mini가 MPS를 사용하므로 이번 채택 질문과 무관
- warm_same_run: production의 cross-process R2 중복을 포함한 cold가 보수적 정본

이 항목들을 실행하지 않는 것은 실패를 제외하는 조치가 아니라, 새 질문의 non-goal을 사전에 고정하는 것이다.

## 3. 결과 독립성

- 기존 `python-evidence-s1-throughput`과 `python-evidence-s1-recovery` raw records를 복사·병합하지 않는다.
- 새 directory `experiments/python-evidence-s1r2-croi/`에서 빈 raw로 시작한다.
- 기존 CROI `1,435 clips/h`는 예상값일 뿐 S1R2 판정 계산에 포함하지 않는다.
- sample manifest와 influx snapshot SHA만 동일하게 재사용한다. throughput 비교의 동등성을 위한 고정 입력이다.

## 4. harness 변경

현재 harness의 full profile을 보존하고, 고정 execution profile `croi-mps-cold`를 추가한다.

```text
profile=full
  기존 동작: conditions=A6,B12,CROI,DALL; cache=cold,warm; device CLI 선택

profile=croi-mps-cold
  고정 동작: conditions=CROI; cache=cold_independent; device=mps
```

임의 condition/cache 조합을 받는 범용 CLI는 만들지 않는다. profile이 device·conditions·cache modes를 하나의 불변 계약으로 반환한다. `croi-mps-cold`에 `--device cpu`를 함께 주면 fail-closed한다.

CROI profile은 A6를 실행하지 않으므로 FFmpeg를 요구하지 않는다. full profile의 A6 FFmpeg preflight는 그대로 유지한다.

## 5. 데이터 흐름

1. host/HEAD/clean/locks/safe-window preflight
2. MPS/checkpoint/Gate imports 검증
3. frozen manifest 32개 로드
4. CROI cold warmup 1회
5. CROI cold measured repeat 1..3
6. 각 record JSONL fsync
7. 96 measured key 완전성 검사
8. p50/p95/capacity/resource 계산
9. 독립 계산기로 재계산
10. 운영 안전 증거와 함께 정확히 하나의 verdict 기록

## 6. 오류와 중단

- MPS/checkpoint/import 실패로 실행 자체를 시작하지 못하면 과학적 verdict를 만들지 않고 `BLOCKED_ENVIRONMENT`로 보고한다.
- lock busy 또는 다음 job까지 25분 미만: 시작하지 않고 다음 자연 안전창을 기다린다.
- 20분 deadline: cleanup 후 partial raw를 보존하고 다음 안전창에서 success-only resume한다.
- 단일 clip error: sanitized record를 남기고 다음 run에서 해당 measured key를 재시도한다.
- 같은 measured key success 중복: contract error.
- 세 번의 안전창에서도 동일 key가 결정론적으로 실패하거나 96 key를 완성하지 못함: `S1R2_REJECT_CROI_RELIABILITY`.
- production job 지연, exit/error 증가, temp leak, DB/R2 write, VLM 호출: `S1R2_REJECT_OPERATIONAL_RISK`.

## 7. 판정

- `S1R2_PASS_CROI_THROUGHPUT`: 96/96 measured success, duplicate/unexpected 0, capacity `>=160 clips/h`, RSS `<=4GiB`, temp peak `<=2GiB`, 모든 운영 안전 gate 통과.
- `S1R2_REJECT_CROI_THROUGHPUT`: 96/96 complete와 안전 gate는 통과했지만 capacity `<160 clips/h`.
- `S1R2_REJECT_OPERATIONAL_RISK`: 운영 안전 위반.
- `S1R2_REJECT_CROI_RELIABILITY`: 최대 세 번의 안전창 뒤에도 96 measured key를 완성하지 못함.
- `S1R2_REJECT_MEASUREMENT_INTEGRITY`: harness와 독립 재계산이 일치하지 않음.

실행이 시작됐다면 정확히 하나의 PASS/REJECT를 적용하며 HOLD verdict는 사용하지 않는다. PASS만 S2 raw-evidence shadow 구현계획 작성을 허용한다. PASS도 production selector 적용, 자동 제외, 행동 분류 승인이 아니다.

## 8. 안전 경계

- Supabase SELECT, R2 GET만 허용
- Claude/VLM 호출 0
- production repo HEAD 변경 0
- LaunchAgent/plist/env/스케줄 변경 0
- 영상·frame은 scoped temp에만 존재하고 종료 후 0
- feature branch commit/push까지만 허용, main merge 금지

## 9. 산출물

- TEST-SHEET: `experiments/python-evidence-s1r2-croi/TEST-SHEET.md`
- ignored raw: `experiments/python-evidence-s1r2-croi/raw_results.jsonl`
- summary: `experiments/python-evidence-s1r2-croi/summary.json`
- report: `experiments/python-evidence-s1r2-croi/REPORT.md`
- 사용자 보고: `docs/handoff-prompts/2026-07-17-python-evidence-s1r2-croi-report.md`

## 10. 승인된 결론

더 이상 비교용 A6가 CROI의 합격을 막게 하지 않는다. CROI production path 자체를 새 raw run으로 완주해 한 번에 PASS 또는 REJECT한다.
