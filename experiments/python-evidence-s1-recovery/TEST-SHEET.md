# TEST-SHEET — Python Evidence S1 Recovery (분할 실행 완주)

**상태:** `PRE_REGISTERED`
**사전등록 시각(UTC):** 2026-07-17T02:29:57Z (= 2026-07-17 11:29 KST)
**lab_head (recovery pre-reg 시점):** `8236712d0311` (Task 1 A6 preflight commit)
**선행 결과:** `S1_HOLD_RUNTIME_BUDGET` (`2026-07-17 04:41~05:01 KST`, `experiments/python-evidence-s1-throughput/REPORT.md`) — 소급 변경 안 함.
**실행 host(계획):** Mac mini `baeg-endeuui-Macmini.local` (nightly-reporter uv 환경, read-only manual foreground)
**규칙:** `.claude/rules/research-testing.md` — 이 시트는 recovery 인퍼런스(A6 canary 포함) 전에 동결되며, 결과를 본 뒤 게이트를 바꾸지 않는다. 결과 기입은 recovery `REPORT.md` 로만 한다.

---

## 0. 왜 recovery 인가 (변경된 것은 스케줄뿐)

첫 S1 실행은 20분 hard budget 을 정상 준수했지만 full workload 를 끝내지 못했고(A6 FileNotFoundError 99건 + warm/CPU 미실행) `S1_HOLD_RUNTIME_BUDGET` 로 종료됐다. A6 실패 원인은 확정됐다: **SSH 비로그인 PATH 에 `/opt/homebrew/bin` 이 없어 `shutil.which("ffmpeg") is None`** → `extract_six` 의 `subprocess.run(["ffmpeg", ...])` FileNotFoundError. production `extract_six` 결함이 아니라 benchmark 실행 환경의 PATH 전파 결함이다.

recovery 는 **동결된 표본·조건·반복을 그대로** 여러 안전창에서 append-safe resume 으로 완주한다. 과학적 workload·판정 기준은 원본과 동일하고, **바뀌는 것은 실행 스케줄(한 번의 20분 → 여러 20분 resume)뿐이다.**

## 1. 가설 (원본과 동일)

- **H0 (귀무):** CROI(MPS, cold_independent) 지속 처리 능력 < projected_4_camera_p95 × 2, 또는 안전 게이트 위반.
- **H1 (대립):** CROI(MPS, cold_independent) 지속 처리 능력 ≥ projected_4_camera_p95 × 2 AND 모든 안전 게이트 통과.

## 2. Sample (원본 동결 값 그대로 재고정)

- **workload:** `../python-evidence-s1-throughput/sample_manifest.json` — 32 clip covered-subset.
  - `sha256 = 931ce37a772d921cf26017801003efebff8686a23a189eca9adcabf397b590d0`
- **influx:** `../python-evidence-s1-throughput/influx_snapshot.json` — 최근 7일 유입량.
  - `sha256 = 885a45ba3974aa73e1e9bd19a37171829cf6b9174f926bedcf70f71cb20a5cc3`
- **seed:** `20260717`. camera allowlist = `5b3ea7aa`, `f6599924`. **`90119209` 일반화 금지.**
- **reduced 16 (D/CPU 비교용):** manifest 의 `reduced_clip_ids` 고정. **결과를 보고 표본을 바꾸지 않는다.**
- **strata / eligibility / duration quartile:** 원본 TEST-SHEET §2 와 동일(변경 없음).
- **accuracy GT 미참조** — 처리량 표본.

## 3. 처리 조건 (원본 Frozen Contract 그대로)

| ID | 조건 | production 후보 여부 |
|---|---|---|
| `A6` | 현행 `vlm_frames.extract_six` 6-frame 추출 | 기준선 |
| `B12` | Gate `sample_frames(..., 12)` + `GeckoDetector` | 구성요소 |
| `CROI` | `B12` + bbox 내부 dense OpenCV flow (raw·의미 중립) | **후보** |
| `DALL` | 모든 decodable frame 에 detector | **위험 대조군, 채택 대상 아님** |

- **device:** 전체 paired workload = MPS 정본. CPU 는 reduced 16 장치 비교. **MPS 미가용 시 CPU 를 MPS 로 보고 금지·중단.**
- **cache modes:** `cold_independent`(게이트 정본), `warm_same_run`(참고). `cross_process_cache` = NOT RUN.
- **반복:** 각 measured path = **warmup 1(제외) + measured 3**. p50/p95 는 measured 3 회.
- **threshold:** GeckoDetector `gate_threshold = 0.10` (H3 동결, 결과 후 변경 금지).

## 4. 완전성 계약 (성공 판정 전 key 정확 일치)

`condition/device/cache_mode/clip/repeat` 예상 key = 실제 유효 key 여야 한다(`missing=0 ∧ unexpected=0 ∧ duplicate_success=0`).

- **MPS:** A6/B12/CROI = 32 clip + DALL = reduced 16, cache mode 2개, repeat 1..3.
- **CPU:** A6/B12/CROI/DALL = reduced 16, cache mode 2개, repeat 1..3.
- warmup record 는 존재 가능하나 measured key 를 채우지 않고 p50/p95 에서 제외.
- `error_code` 있는 measured key 는 완료 아님 — 명시적 재시도 대상.
- 동일 measured key 중복 성공 record = 0 (2건이면 `BenchContractError`).

검증: `expected_measured_keys(clips, device=…)` vs `successful_completed_keys(raw_results.jsonl)` → `completeness_report`.

## 5. 합격 기준 (원본 숫자 게이트 그대로 — 사후 변경 금지)

**유입량 기준값 (동결): `projected_4_camera_p95 = 80.0 clips/hour`.**

`S1R_PASS` 판정 조건 (전부 충족):

1. **처리량:** `CROI_MPS(cold_independent) capacity ≥ projected_4_camera_p95 × 2 = 160.0 clips/hour` ⇔ `clip_e2e_p95 ≤ 22.5 초/clip`. (warm_same_run 병기, 게이트는 cold_independent 정본.)
2. **정규 VLM/backfill deadline 지연 = 0**
3. **기존 worker exit/error 증가 = 0**
4. **temp media = 0** (실행 후 벤치마크 temp root 및 알려진 project temp root)
5. **peak RSS ≤ 4 GiB** AND **peak local temp disk ≤ 2 GiB**
6. **완전성:** §4 의 예상 key = 실제 유효 key (missing/unexpected/duplicate-success 모두 0).

## 6. 예상 비용/토큰

- VLM/Claude 호출 **0**, DB write **0**. R2 GET only (read-only).
- 다운로드량 ≈ 32 clip × (조건 paired × cache mode), cold 모드가 중복 최대. 각 run 20분 hard budget 내.
- 안전창 부족·lock busy 시 아무 작업 없이 대기(비용 0).

## 7. 사전등록된 유일한 운영 변경 (사후 변경 금지)

```text
execution = multiple independent <=20m foreground runs with append-safe resume;
each run starts only with >=25m safe window and free activity/VLM locks;
original S1 partial records are not imported.
```

- 여러 안전창이 필요하면 **동일 frozen parameters + `--resume`** 만 쓴다. 결과를 보고 workload 를 축소하지 않는다.
- recovery 는 **새 빈 output directory**(`experiments/python-evidence-s1-recovery/`)에서 전체 workload 를 처음부터 측정한다. 원본 `../python-evidence-s1-throughput/raw_results.jsonl` 을 복사·재사용하지 않는다.

## 8. Stop rules (사전등록)

- **시작 게이트:** 다음 예약 production job 까지 **≥ 25분** 안전창 + activity/VLM lock 비차단. 미달이면 시작 안 함(대기).
- **hard runtime budget:** 각 run 20분(≤1200초). 초과 시 fail-closed 중단·cleanup·partial checkpoint 유지 → 다음 안전창에서 `--resume`.
- **의존성 실패:** FFmpeg preflight 실패 시 R2·detector·temp 전에 즉시 중단(`ffmpeg_missing`/`ffmpeg_unusable`).
- **A6 canary 실패:** full recovery 금지, traceback 은 로컬 임시 진단에만, 보고서는 sanitized code 만.
- **안전 위반:** 실행 전후 LaunchAgent run count/last exit/log error 비교에서 예약 지연·exit/error 증가 1건이라도 → `S1R_REJECT_OPERATIONAL_RISK`.
- **systemic 실패:** detector/R2 계통 실패는 run 중단. 단일 clip 실패는 sanitized error code 기록 후 안전할 때만 계속.

## 9. Decision 룰 (정확히 하나, 원본 `S1_*` 네임스페이스와 분리)

- `S1R_PASS_CROI_THROUGHPUT`: 전체 key 완전성 + CROI MPS cold capacity `≥ 160 clips/h` + 모든 안전 게이트 통과 → **S2 raw-evidence shadow 계획 착수만** 허용(production selector·자동 제외 승인 아님).
- `S1R_REJECT_CROI_THROUGHPUT`: 전체 key 완성됐으나 CROI MPS cold capacity `< 160 clips/h`.
- `S1R_HOLD_INCOMPLETE`: 의존성·안전창·반복 오류로 전체 key 미완성.
- `S1R_REJECT_OPERATIONAL_RISK`: production 지연/오류, temp leak, write, VLM 호출 등 안전 위반.

## 10. Non-goals / 하드 금지

- production 배포·selector 변경·자동 skip/label·VLM 호출·DB write·LaunchAgent 조작(bootout/bootstrap/kickstart/plist/env)·cross-process cache 채택 **전부 금지**.
- `reporter/vlm_frames.py` 등 production 코드 수정 금지 — benchmark preflight·실행 PATH 만 고친다.
- 원본 `raw_results.jsonl`/summary/report 삭제·재작성 금지. recovery verdict 를 원본 `S1_*` 로 개명 금지.
- sample/threshold/warmup/repeat 사후 축소 금지.
- 다른 세션·unrelated untracked 파일 수정 금지.

## 11. 무결성

- blind 불필요(처리량 측정). **독립 재계산** 의무: harness aggregation 을 import 하지 않는 별도 read-only 스크립트로 raw JSONL 에서 완전성·p50/p95·capacity·temp/service 게이트를 재계산해 `summary.json` 과 정확히 일치 확인(REPORT §대조).
- influx 는 원본 prep 시각(2026-07-16T16:10Z) 기준 최근 7일. recovery 실행 시점과의 시차는 한계로 보고.
- **PATH 계약:** Mac mini 실행은 정확히 `PATH=/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin` 사용.

---

> 결과는 [`REPORT.md`](REPORT.md) 로만 기입. 사용자 보고는 `../../docs/handoff-prompts/2026-07-17-python-evidence-s1-recovery-report.md`.
