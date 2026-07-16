# TEST-SHEET — Python Evidence S1 Throughput Benchmark

**상태:** `PRE_REGISTERED`
**사전등록 시각(UTC):** 2026-07-16T16:10:15Z (= 2026-07-17 01:10 KST)
**lab_head:** `7418bbb3f6f8` (manifest commit)
**실행 host(계획):** Mac mini `baeg-endeuui-Macmini.local` (nightly-reporter uv 환경)
**규칙:** `.claude/rules/research-testing.md` — 이 시트는 벤치마크 인퍼런스 전에 동결되며, 결과를 본 뒤 게이트를 바꾸지 않는다. 결과 기입은 REPORT.md 로만 하고 여기엔 링크만 추가한다.

---

## 0. 질문 (Question)

`sparse Gate 12-frame + bbox ROI dense OpenCV`(조건 CROI)가 Mac mini(MPS)에서
**projected 4-camera p95 유입량의 최소 2배**를 production 데이터 변경 없이 지속 처리할 수 있는가?

성공은 production 배포 승인이 **아니다** — 성공해도 "S2 raw evidence shadow 계획 작성 가능"까지만 의미한다.

## 1. 가설

- **H0 (귀무):** CROI(MPS) 지속 처리 능력 < projected_4_camera_p95 × 2, 또는 안전 게이트 위반.
- **H1 (대립):** CROI(MPS) 지속 처리 능력 ≥ projected_4_camera_p95 × 2 AND 모든 안전 게이트 통과.

## 2. Sample (동결)

- **workload:** `sample_manifest.json` — 32 clip covered-subset.
  - `sha256 = 931ce37a772d921cf26017801003efebff8686a23a189eca9adcabf397b590d0`
- **influx:** `influx_snapshot.json` — 최근 7일 유입량.
  - `sha256 = 885a45ba3974aa73e1e9bd19a37171829cf6b9174f926bedcf70f71cb20a5cc3`
- **strata (target / available / selected):**
  | camera_short | bbox_stratum | target | available | selected |
  |---|---|---|---|---|
  | 5b3ea7aa | present | 8 | 2750 | 8 |
  | 5b3ea7aa | absent | 8 | 204 | 8 |
  | f6599924 | present | 16 | 115 | 16 |
  | f6599924 | absent | 0 | 0 | 0 (가용 clip 없음 = 제약) |
- **seed:** `20260717`. camera allowlist = `5b3ea7aa`, `f6599924` (policy_ready≥80% covered subset). **`90119209` 일반화 금지.**
- **eligibility:** current `activity-v1` assessment ∧ 연결 prelabel `frames_sampled≥6` ∧ `r2_key` 존재 ∧ `duration_sec>0`. lookback 60일(사전등록, 결과 보고 튜닝 금지).
- **duration quartile:** stratum 안에서 rank 기반 4분위 균등 (5b3ea7aa present 2/quartile, f6599924 present 4/quartile).
- **reduced 16 (D/CPU 비교용):** 32 중 stratum·quartile 유지한 deterministic subset (5b3ea7aa present 4, absent 4, f6599924 present 8). `reduced_clip_ids` 는 manifest 에 고정. **결과를 보고 표본을 바꾸지 않는다.**
- **accuracy GT 미참조** — 처리량 표본이며 label 품질 판정에 쓰지 않는다.

## 3. 처리 조건 (Frozen Experiment Contract)

| ID | 조건 | production 후보 여부 |
|---|---|---|
| `A6` | 현행 `vlm_frames.extract_six` 6-frame 추출 | 기준선 |
| `B12` | Gate `sample_frames(..., 12)` + `GeckoDetector` | 구성요소 |
| `CROI` | `B12` + bbox 내부 dense OpenCV flow (raw·의미 중립) | **후보** |
| `DALL` | 모든 decodable frame 에 detector | **위험 대조군, 채택 대상 아님** |

- `CROI`: bbox 없으면 `roi_status=no_bbox`, dense ROI 비용 0. full frame 을 ROI 로 바꾸지 않는다.
- `CROI`: raw ROI motion series 만. basking/drinking 분류·head 위치 추정·threshold 도입 **금지**.
- `DALL`: 결과 무관하게 production 채택 아님, 모든 결과 `risk_control_only=true`, reduced 16 + hard deadline 강제.
- **device:** 전체 paired workload = MPS 정본. CPU 는 reduced 16 에서 장치 비교만. **MPS 미가용 시 CPU 를 MPS 로 보고하지 말고 중단.**

### Cache/download modes

- `cold_independent`: 조건별 독립 다운로드·decode → cross-process 중복 상한.
- `warm_same_run`: 같은 run 에서 원본 mp4 재사용 → 다운로드 제외 처리비.
- `cross_process_cache`: **NOT RUN / NOT IMPLEMENTED** → 결과표에 `not_run_design_required`.

### 반복

- 각 measured path = warmup 1 회(제외) + measured 3 회. p50/p95 는 measured 3 회로 계산.

## 4. 측정 지표

- R2 다운로드 포함/제외 wall time + **중복 다운로드 횟수**
- decode 시간, detector 시간(MPS vs CPU), dense ROI flow 시간
- clip end-to-end p50 / p95 (조건·device·cache_mode 별)
- peak RSS(`resource.getrusage`), peak local temp disk
- 임시파일 수(=0 확인)
- 기존 worker(candidate/backfill/router-features/nightly) schedule 지연·exit/error 증가
- 처리 능력 `capacity = 3600 / clip_e2e_p95_seconds` (clips/hour)

## 5. 합격 기준 (숫자 게이트 — 사후 변경 금지)

**유입량 기준값 (동결): `projected_4_camera_p95 = 80.0 clips/hour`** (influx_snapshot: total p95=60, cameras=3, 80 = 60×4/3).

CROI 를 **S1_PASS** 로 판정하려면 아래 **전부** 충족:

1. **처리량:** `CROI_MPS capacity ≥ projected_4_camera_p95 × 2 = 160.0 clips/hour`
   ⇔ `CROI_MPS clip_e2e_p95 ≤ 3600 / 160 = 22.5 초/clip` (warm_same_run 및 cold_independent 각각 보고, 게이트는 **e2e 정본 = cold_independent** 기준으로 적용).
2. **정규 VLM/backfill deadline 지연 = 0**
3. **기존 worker exit/error 증가 = 0**
4. **temp media = 0** (원본 영상·frame, 실행 후 벤치마크 temp root 및 알려진 project temp root)
5. **peak RSS ≤ 4 GiB** AND **peak local temp disk ≤ 2 GiB**

> 게이트 정본은 cold_independent(중복 다운로드 포함 = 현행 cross-process 실태 상한)로 적용한다. warm_same_run 은 다운로드 제외 처리비 참고값으로 병기한다.

## 6. 예상 비용/토큰

- VLM/Claude 호출 **0**, DB write **0**. R2 GET only (read-only).
- 다운로드량 ≈ 32 clip × (조건 paired × cache mode) — cold 모드가 중복을 최대화. 20분 hard budget 안에서만.

## 7. Stop rules (사전등록)

- **시작 게이트:** 다음 예약 production job 까지 **≥ 25분** 안전창 + activity/VLM lock 비차단 확인. 미달이면 **시작 안 함** → `S1_HOLD_RUNTIME_BUDGET`.
- **hard runtime budget:** 20분. 초과 시 fail-closed 중단·cleanup → `S1_HOLD_RUNTIME_BUDGET`. **사후 표본 축소 금지.**
- **안전 위반:** 실행 전후 LaunchAgent run count/last exit/log error 비교에서 예약 지연·exit/error 증가 1건이라도 → 성능 수치와 무관하게 `S1_REJECT_OPERATIONAL_RISK`.
- **systemic 실패:** detector/R2 계통 실패는 run 중단. 단일 clip 실패는 sanitized error code 기록 후 cleanup·deadline 안전할 때만 계속.

## 8. Decision 룰 (정확히 하나)

- `S1_PASS_CROI_THROUGHPUT`: §5 게이트 전부 통과 → **S2 raw-evidence shadow 계획 착수만** 허용.
- `S1_HOLD_REDUCE_CONFIG`: CROI 가 운영 오염 없이 처리량/자원 게이트만 미달 → 더 작은 sampling 구성 **제안**(구현 안 함).
- `S1_HOLD_RUNTIME_BUDGET`: 동결 벤치마크가 20분 안전창에서 완료 불가.
- `S1_REJECT_OPERATIONAL_RISK`: 예약 지연·worker error/exit 증가·temp leak·mutation 등 안전 위반.

## 9. Non-goals / 하드 금지

- production 배포·selector 변경·자동 skip/label·VLM 호출·DB write·LaunchAgent 조작·cross-process cache 채택 **전부 금지**.
- S1 결과를 production adoption 으로 표현 금지.
- 다른 세션·unrelated untracked 파일 수정 금지.
- **H3 threshold 동결 (2026-07-17 preflight hardening 추가):** `gate_threshold=0.10` 은 본 벤치마크 전에 production `activity-v1` 기준으로 고정됐다. 결과를 본 뒤 threshold 를 바꾸는 것은 사후 게이트 조정이며 이 시험지 무결성 위반이다.

## 10. 무결성

- blind 불필요(처리량 측정, 사람 판정 없음). 대신 **독립 재계산** 의무: 별도 read-only 스크립트로 raw JSONL 에서 p50/p95·capacity·temp/service 게이트를 재계산해 `summary.json` 과 정확히 일치해야 함(REPORT §3).
- influx 는 prep 시각(2026-07-16T16:10Z, MacBook) 기준 최근 7일. 벤치마크는 이후 Mac mini 에서 실행되므로 유입량 스냅샷과 실행 시점 간 시차는 한계로 보고한다.

---

> 결과는 [`REPORT.md`](REPORT.md) 로만 기입.
