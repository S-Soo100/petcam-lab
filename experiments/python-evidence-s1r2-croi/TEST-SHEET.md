# TEST-SHEET — Python Evidence S1R2: CROI/MPS/cold 단독 처리량 합격시험

**상태:** `PRE_REGISTERED` (실행 전 고정, 사후 변경 금지)
**사전등록 시각:** 2026-07-17T04:46:29Z (UTC) / 2026-07-17T13:46:29+09:00 (KST)
**feature commit:** `f25eb0000e66a0cabf147b10d8e17bdb70ffd421` (branch `feat/python-evidence-s1-benchmark`)
**선행 기록:** `S1_HOLD_RUNTIME_BUDGET`, `S1R_HOLD_INCOMPLETE` (둘 다 history 로 보존)
**design:** `docs/superpowers/specs/2026-07-17-python-evidence-s1r2-croi-design.md`
**plan:** `docs/superpowers/plans/2026-07-17-python-evidence-s1r2-croi.md`

> ⚠️ 이 문서는 Mac mini runtime 실행 **전에** commit + push 된다. runtime canary/benchmark 는
> 이 commit 이 remote 에 존재한 뒤에만 시작한다.

---

## 0. 이번 시험의 단 하나의 질문

> CROI MPS cold path 가 frozen 32 clips 에서 measured 3회(= **96 measured key**)를 완주하고,
> projected 4-camera p95 의 2배인 `160 clips/h` 이상을 **production 운영 영향 없이** 처리하는가?

CROI/MPS/cold **only**. A6/B12 standalone/DALL/CPU/warm_same_run 은 이번 시험의 **non-goal** 이며
verdict 계산에 넣지 않는다. 이는 실패를 제외하는 조치가 아니라 새 질문의 경계를 사전 고정하는 것이다.

## 1. 가설

- **H0 (귀무):** CROI/MPS/cold 는 96 measured key 를 안전하게 완주하지 못하거나, 완주해도
  capacity `< 160 clips/h` 이거나, 운영 안전을 위반한다.
- **H1 (대립):** CROI/MPS/cold 는 96/96 measured 를 완주하고 capacity `>= 160 clips/h` 를
  운영 안전 위반 0 으로 달성한다.

## 2. sample list (고정, 재생성 금지)

- manifest: `experiments/python-evidence-s1-throughput/sample_manifest.json`
  - SHA-256 `931ce37a772d921cf26017801003efebff8686a23a189eca9adcabf397b590d0`
  - 32 clips (frozen). clip 선택·재생성하지 않는다.
- influx snapshot: `experiments/python-evidence-s1-throughput/influx_snapshot.json`
  - SHA-256 `885a45ba3974aa73e1e9bd19a37171829cf6b9174f926bedcf70f71cb20a5cc3`
  - `projected_4_camera_p95 = 80.0s` → 처리량 gate = `80.0 × 2 = 160 clips/h`.
- 두 SHA 만 S1 과 공유한다(throughput 비교 동등성용 고정 입력). raw record 는 공유하지 않는다.

## 3. 모델 / 입력표현 / 실행 계약

- execution profile: `croi-mps-cold` (신규 고정 profile)
  - condition = `CROI` only
  - device = `mps` only (cpu 요청은 `profile_device_mismatch` fail-closed)
  - cache mode = `cold_independent` only (cross-process R2 중복 포함 = 보수적 정본)
- warmup = clip당 1회 (통계 제외), measured repeats = clip당 3회
- threshold = `0.10` (production activity-v1 gate_threshold, H3 provenance — 결과 본 뒤 변경 금지)
- CROI 내부 Gate 12-frame sampling → gecko detector → bbox ROI dense OpenCV flow 는
  production adapter 그대로 실행한다.
- FFmpeg: A6 없는 profile 이라 `not_required`. (full profile 의 A6 FFmpeg preflight 는 보존.)

## 4. 완전성 정본 (측정 지표 ①)

- expected measured keys = `32 clips × CROI × mps × cold_independent × repeat{1,2,3}` = **정확히 96**.
- expected successful raw records = warmup 32 + measured 96 = **128** (error record 0).
- A6/B12/DALL/warm_same_run/CPU key 는 모두 **unexpected**.
- warmup record 는 measured key 를 채우지 못한다. error record 도 채우지 못하고 재시도 대상.
- 동일 measured key 성공 중복 = contract error (MEASUREMENT_INTEGRITY).
- 95/96 = incomplete, 96/96 = complete.

## 5. 처리량·자원·운영 안전 (측정 지표 ②~④)

- p50/p95 = CROI/mps/cold 성공 measured e2e 초. capacity = `3600 / p95`.
- 처리량 gate: p95 `<= 22.5s/clip` ⟺ capacity `>= 160 clips/h`.
- 자원 gate: peak RSS `<= 4 GiB`, temp peak `<= 2 GiB`.
- 운영 안전 gate (runtime audit 에서 명시 주입, timing 으로 추론 금지):
  `service_ok`(production job 지연/exit/error 증가 0) · `temp_after_zero`(종료 후 media 0) ·
  `no_db_write` · `no_r2_write` · `no_vlm_call` · `production_head_unchanged`.

## 6. 합격 기준 — 5개 verdict (숫자 게이트, HOLD 없음)

실행이 시작됐다면 아래 **정확히 하나**를 적용한다. 우선순위:
`OPERATIONAL_RISK > MEASUREMENT_INTEGRITY > RELIABILITY > THROUGHPUT`.

| verdict | 조건 |
|---|---|
| `S1R2_PASS_CROI_THROUGHPUT` | 96/96 complete, duplicate/unexpected 0, capacity `>=160`, RSS`<=4GiB`, temp`<=2GiB`, 운영 안전 전부 통과 |
| `S1R2_REJECT_CROI_THROUGHPUT` | 96/96 complete + 안전 gate 통과했지만 capacity `<160` |
| `S1R2_REJECT_OPERATIONAL_RISK` | 운영 안전/자원천장 위반 (성능이 좋아도 override) |
| `S1R2_REJECT_CROI_RELIABILITY` | 최대 3회 안전창 뒤에도 96 measured key 미완성 |
| `S1R2_REJECT_MEASUREMENT_INTEGRITY` | unexpected/duplicate success 또는 harness ↔ 독립 재계산 불일치 |

`BLOCKED_ENVIRONMENT` 는 오직 MPS/checkpoint/import 실패 또는 자연 안전창 부재로 runtime 을
**한 번도 시작하지 못한** 경우에만. 운영 서비스를 조작해 우회하지 않는다.

## 7. 결과 독립성 (previous raw 미사용)

- `python-evidence-s1-throughput` / `python-evidence-s1-recovery` raw·summary·report 를
  복사·병합하지 않는다.
- 기존 CROI `1,435 clips/h` 참고치는 예상값일 뿐 S1R2 판정 계산에 넣지 않는다.
- 새 raw 는 빈 `experiments/python-evidence-s1r2-croi/raw_results.jsonl` 에서 시작한다.

## 8. 예상 비용/토큰

- LLM/VLM 호출 **0** (Claude/Anthropic/Gemini 모두). API 토큰 비용 0.
- Supabase SELECT + R2 GET only. DB/R2 write 0.
- compute: 32 clips × (warmup 1 + measured 3) = 128 CROI 실행. 1 run `<= 1200s`,
  20분 자연 안전창 1개에서 완주 예상. 필요 시 동일 명령 `--resume` 최대 3회.

## 9. decision 룰 (사전 명시)

- 위 §6 표의 조건을 그대로 적용한다. 게이트 숫자(96 / 160 / 4GiB / 2GiB)는 결과를 본 뒤
  바꾸지 않는다 (research-testing 하드룰 ③).
- `S1R2_PASS_CROI_THROUGHPUT` 만 **S2 raw-evidence shadow 구현계획 작성**을 허용한다.
  PASS 도 production selector 적용·자동 제외·행동 분류 승인이 **아니다**.
- 그 외 모든 verdict 는 S2 를 blocked 로 둔다.
