# Python Evidence Hybrid — RBA shadow evidence 계층 설계 (정본)

> **상태:** 설계 정본 / 구현 착수 전 / commit 전 (사용자·Codex 검토 대기)
> **작성:** 2026-07-16
> **결정:** `ADOPT_HYBRID` — 기존 VLM 운영 골격(A)을 유지하고, Python Evidence Layer(B)를 **shadow evidence 계층**으로 추가한다.
> **이 문서는 "무엇을/왜"의 설계다. "어떻게 구현"은 승인 후 별도 plan + handoff manifest로 넘긴다.**
> **선행 리뷰:** 2026-07-16 독립 아키텍처 리뷰(A vs B) → `ADOPT_HYBRID` (근거는 §3).
> **live runtime 재검증:** 2026-07-16 ~13:37 KST, 세 레포 read-only (§0).
> **S1 throughput benchmark (2026-07-17):** `S1_HOLD_RUNTIME_BUDGET` — MPS 20분 budget 소진(346/~1024 records). CROI p95=2.541s / cap=1,417/h / throughput_ratio=17.71x. warm·CPU·A6 미완. A6 전량 FileNotFoundError. 안전 위반 없음. → S2 착수 전 재실행 필요. 보고서: [`experiments/python-evidence-s1-throughput/REPORT.md`](../../experiments/python-evidence-s1-throughput/REPORT.md).

---

## 0. Live runtime 사실 (2026-07-16 재검증, read-only)

이 절은 설계의 전제다. 아래는 추론이 아니라 실측이다.

### 0.1 호스트·레포 HEAD

| 호스트 | hostname | TZ | 레포 | branch@HEAD |
|---|---|---|---|---|
| Mac mini | `baeg-endeuui-Macmini.local` | KST(+0900) | nightly-reporter | `main` @ `cbd2e09ed00857bdbd8a27c3f0483881c9abdbd6` (=origin/main, production) |
| Mac mini | — | — | petcam-lab | `main` @ `df7811c12e3518096c92271b5e549d9154468001` |
| Mac mini | — | — | gecko-vision-gate | `main` @ `9e39596bdb907a86496948f4bf3a13fe760d8222` |
| MacBook | `BaekBook-Pro-14-M5.local` | KST | (개발 워킹트리) | petcam-lab `main` @ `df7811c`, nightly-reporter **`feat/vlm-basking-classification` @ `97a24a4`** (feature, 8 ahead, **production 아님**) |

**production runtime = Mac mini main.** MacBook의 nightly-reporter feature branch(`97a24a4`)와 혼동하지 않는다. basking 작업은 canary REJECTED로 main 미반영.

### 0.2 Mac mini LaunchAgents (전부 last exit 0)

| label | WorkingDir | schedule (KST) | provider/model | 비고 |
|---|---|---|---|---|
| `com.petcam.vlm-candidate-worker` | nightly-reporter | 22/00/02/04:00 | `claude_cli_batch` / `claude-sonnet-5` | `VLM_EXPECTED_HOST`=Mac mini, `VLM_ROUTER_ENABLED=1`, `REGISTER_HIGHLIGHTS=0` |
| `com.petcam.vlm-historical-backfill` | nightly-reporter | 매시 :35 (00:35–23:35 = 24×) | `claude_cli_batch` | rolling backfill. **live 처리 확인**: `source=2026-07-12 selected=30 succeeded=19+11` |
| `com.petcam.vlm-backfill-finalizer` | nightly-reporter | 20:30 | (claude headless) | one-shot self-unload 스크립트(`run-vlm-backfill-finalizer.sh`), handoff prompt 1회성 |
| `com.petcam.nightly-reporter` | nightly-reporter | 22/00/02/04:05 | (claude 샘플) | `WINDOW_HOURS=2` 야간 리포트 |
| `uk.tera-ai.petcam-router-features` | petcam-lab | RunAtLoad (상주, pid 749 running) | OpenCV only, LLM/VLM 0 | `clip_router_features` 생산자 |
| `com.petcam.activity-worker` | nightly-reporter | 매시간 (`StartInterval=3600`) | detector(12f) + OpenCV, VLM 0 | 테스트 카메라 3대 `activity-v1`, `ACTIVITY_EXPECTED_HOST` fail-closed. 첫 RunAtLoad `queried=88 / ok=88 / fail=0 / exit 0`, 2번째 자연 cycle 미처리 0건 exit 0 |

Mac mini temp media = **0** (mp4/jpg 잔여 없음).

### 0.3 MacBook LaunchAgents

| label | schedule | 비고 |
|---|---|---|
| (없음) | — | activity-worker는 Mac mini로 단일 이전됨. MacBook service/plist **absent**, decommissioned plist 백업만 보존 |

### 0.4 발견한 SOT 모순 (§1에서 정정)

1. **candidate-worker 호스트**: `specs/next-session.md`(lab·nightly 공통) 상단은 "정규 candidate LaunchAgent는 MacBook에서 발견, Mac mini verified 아님(planned)"이라 기록. **live: candidate-worker는 Mac mini에 정상 로드**(`VLM_EXPECTED_HOST`=Mac mini), MacBook엔 없음 → single-host hardening 완료됨. 해당 SOT 라인 **superseded**.
2. **rolling backfill**: lab next-session의 07-16(2/3) 블록은 "Mac mini rolling 반영 PENDING(SSH 불가)". 07-16(4) 블록은 "배포 완료·첫 cycle VERIFIED". **live: rolling 가동 중**(2026-07-12 처리). PENDING 라인은 VERIFIED 블록으로 **superseded**.
3. **activity-worker 호스트 — RESOLVED:** 초기 live audit에서 MacBook 오배치를 발견했다. 이후 host guard와 partial-failure nonzero exit를 추가하고 Mac mini로 단일 이전했다. 현재 Mac mini `com.petcam.activity-worker`만 loaded이며 MacBook은 absent다. 첫 실사이클 88/88 성공과 자연 두 번째 cycle exit 0을 확인했다.

---

## 1. 문제 정의

RBA의 현 병목은 두 겹이다.

1. **후보 utility 병목** — 정규 VLM selector는 야간 window·카메라당 4슬롯이라는 고정 예산을 쓴다. 이 예산이 "라벨링·케어 가치가 높은 후보"에 배분되는지 검증되지 않았다. 첫 candidate canary(2026-07-15)는 44개 중 4개를 뽑아 **판정 8/8이 moving 7 / unseen 1** — motion 편향 신호. 과거 실증도 "motion_score 상위 = moving 편향, 정적 케어행동 누락"(`nightly next-session` 07-07(2)).
2. **미세행동 시각 천장** — drinking/eating_prey/미세 접촉은 정지프레임 VLM 4레버(입력·프롬프트·모델·ROIcrop) 전부 천장 확인(메모리 `v1-drinking-close`, `roi-crop-close`). 이건 라우팅이 아니라 캡처·시간축·HITL 문제.

계획 A(운영 골격)는 (1)에 대해 "고정 예산을 안전하게 배급"까지 왔지만, **어떤 clip을 뽑을지(selector utility)** 는 미검증이다. 계획 B(Python evidence)는 정확히 그 selector 신호를 강화하자는 것이다.

**핵심 발견(재사용 감사, §4):** B의 "Python Evidence Layer"는 greenfield가 아니다. 재사용 감사(§4.2)를 필드 단위로 분해하면 **contract 필드 15개 중 직접 재사용 9 / 정규화 필요 2 / 완전 신규 4**이며, 이 중 gate evidence(9개 중 다수)의 **production 카메라 실제 채움률은 미확인**(activity-worker는 Mac mini에서 테스트 카메라 3대를 상시 처리하며 Mac mini producer evidence 88건을 실측했으나, 전체 카메라·날짜별 `clip_prelabels` 채움률과 selector 입력 시점의 coverage는 아직 산출하지 않아 S0 read-only 감사 항목으로 유지). 즉 "코드 완성률"이 아니라 "필드 재사용 가능성" 관점에서 상당 부분이 이미 존재한다. 따라서 이 설계의 실제 작업은 "새 워커 제작"이 아니라 **(a) 이미 존재하는 흩어진 evidence를 shadow 계약으로 정합화, (b) 진짜 gap(시간축·event 필드)만 추가, (c) shadow 비교를 형식화** 이다. (필드별 분해는 §7.1, 채움률 미확인은 §17-1.)

---

## 2. 기존 A 계획과 새 B 계획

### 2.1 계획 A — 운영 중심 (현행, 배포·검증 완료)

- motion clip → selector가 카메라·window당 최대 4 후보 선택 → clip당 6 프레임 → `claude-sonnet-5` batch4 분석.
- 정규 VLM 22/00/02/04, rolling backfill 매시 :35(cycle당 30, 일 600 cap, 정규 ±30분 guard + H1~H5).
- 결과는 `clip_vlm_selector_runs`/`clip_vlm_jobs` shadow 원장에만. GT·앱·활동시간 미반영.
- 성숙도: 배포·하드닝·첫 cycle VERIFIED. **유일하게 운영 검증된 체제.**

### 2.2 계획 B — Python Evidence-First

- 모든 clip을 로컬 Python으로 먼저 분석: Gate presence/bbox/trajectory + OpenCV dense scan → 체류·이동량·미세움직임·행동 경계 → candidate 등급 라우팅.
- Python은 최종 GT를 만들지 않고 `resting_candidate / locomotion_candidate / micro_action_candidate / sustained_lapping_candidate / uncertain` 및 VLM 모드 추천만.
- 계약: presence 3상태, Gate 단독 skip 금지, Python 결과 GT 금지, drinking은 candidate까지, 초기 전량 shadow-only.

---

## 3. ADOPT_HYBRID 결정

**결정: A의 운영 골격을 유지하고, B를 shadow evidence 계층으로 삽입한다. A를 B로 교체하지 않는다.**

근거 (선행 리뷰 + 재사용 감사):

1. **세 레포 SOT가 이미 하이브리드로 수렴해 있다.** ① cascade REPORT: "hold auto-label **until detector evidence adds gecko presence and object/ROI cues**"(`experiments/rba-evidence-first-cascade/REPORT.md`), ② gate-v3.md shadow 단계 = "bbox trajectory × ROI 체류 evidence 생성, VLM frame 우선순위 보조", ③ `feature-rba-data-engine-v1.md` §6 Gate 활용 표. 셋 다 "A 골격 위 B shadow"를 가리킨다.
2. **A의 약점(selector utility 미검증)에 B의 강점(체류·trajectory 증거)이 정확히 대응**하고, B의 약점(운영·안전·관측성 전무)을 A 골격이 메운다.
3. **전면 교체는 정당화 불가** — 검증된 원장·claim/release·failure diagnostic을 버리고 미측정 파이프라인에 거는 것. Gate v2 recall 90.9%(FN 20), 운영 고정카메라 drinking GT 0건, Mac mini 벤치마크 부재가 결정적.
4. **B의 핵심 evidence 필드 상당수가 이미 shadow로 존재**(§4·§7.1: 직접 재사용 9 / 정규화 2 / 신규 4) → 하이브리드가 최소 신규 표면.

이 결정에 대한 **가장 강한 반론**과 그 처리는 §13에 명시한다(요약: 하이브리드가 router 우회의 4번째 반복이 되지 않으려면, evidence **생성**은 지금부터 하되 evidence **룰 채택**은 사람 blind GT + fresh camera-night 게이트 뒤로 강제).

---

## 4. 기존 산출물 재사용 감사 (Phase 2 결과)

### 4.1 이미 존재하고 가동 중인 evidence 생산자

| 생산자 | 레포/파일 | 출력 | 저장 | 가동 |
|---|---|---|---|---|
| RF-DETR detector | gecko-vision-gate `src/.../detector.py` + nightly `reporter/gate_runner.py`(임베드) | `PrelabelResult`(gecko_visible, visibility_confidence, best_frame_ts, gecko_bbox[x,y,w,h], detected_objects[type,confidence,bbox,frame_ts]) | `clip_prelabels` | activity/backfill 경로에서 on-demand |
| Motion evidence | gecko-vision-gate `motion_evidence.py`(nightly가 재사용) | `MotionMetrics`(visible_frame_count/ratio, max_bbox_center_disp, max_bbox_size_change, min_bbox_iou, roi_flow_mag, global_bg_change, bbox_edge_clipped) | `clip_prelabels.motion_metrics` | 위와 동일 |
| 4-state 판정 | gecko-vision-gate `activity_policy.py` + nightly `activity_worker.py`/`activity_store.py` | `ActivityAssessment`(decision∈{active, exclude_absent, exclude_static, unknown}, reason_code, measurements) | `clip_activity_assessments` | **Mac mini activity-worker(테스트 카메라)** |
| Provenance | gecko-vision-gate `provenance.py` | `GateProvenance`(model_name/version, checkpoint_sha256, threshold, sampler_version=`even-uniform-v1`, schema_version=`gate-evidence-v1`, frames_sampled) | `clip_prelabels` | 위와 동일 |
| Evidence selector | nightly `vlm_selector.py` + `vlm_backfill_selector.py` | 4슬롯(CUSTOMER_HIGHLIGHT / SUBTLE_BEHAVIOR / DIVERSITY_DISCOVERY / EXCLUSION_AUDIT) 랭킹, `selection_reason`, `rank_features` | `clip_vlm_jobs`(+`activity_assessment_id`,`prelabel_id`) | **Mac mini candidate/backfill** |
| OpenCV metadata | petcam-lab `backend/router_features.py` | `MotionFeatureSet`(motion_mean/peak/std, active_motion_ratio, center/late_motion_ratio, motion_burst_count, longest_motion_burst_sec, first/last_motion_sec, motion_coverage_ratio, evidence_reliability) + window context(window_clip_count_10/30/60m, seconds_since/until, recent_activity_baseline, activity_delta_from_baseline) | `clip_router_features` + `clip_router_feature_runs` | **Mac mini router-features(상주)** |
| 프레임 추출 | nightly `frames.py`(적응형 6–20, 구간중앙, no-upscale) / `vlm_frames.py`(고정6) · lab `scripts/_extract_frames_clip.py`(적응형+ROIcrop) | JPEG frames | temp(자동정리) | 각 워커 |
| R2 다운로드 | nightly `reporter/r2.py`(`@lru_cache` 싱글톤 client) | 로컬 mp4 | temp | 각 워커 |

### 4.2 재사용 감사 5문항 답

1. **그대로 재사용 가능한 evidence:** presence(gecko_visible)·bbox·best_frame·detected_objects·MotionMetrics(bbox trajectory 3종·roi_flow·global_bg·edge_clip)·4-state decision·reason_code·전체 provenance·OpenCV MotionFeatureSet·window context·selector 4슬롯 랭킹. **B의 최소 출력 계약(§7) 대부분이 이미 존재.**
2. **부족한 evidence (진짜 gap):**
   - **dwell_duration** (ROI별 체류 시간) — 현재는 clip 단위 aggregate만.
   - **ROI motion series summary** (시간축 시리즈) — `roi_flow_mag`는 단일 스칼라. event 시작·종료·시리즈 없음.
   - **repeated micro-motion / sustained_lapping candidate** — 몸통 고정 + 머리 ROI 반복. 현재 없음. (evidence-feeding spec §4.4/§6.4의 sustained_lapping이 이것.)
   - **event start/end timestamps** — best_frame_ts/detected_objects.frame_ts는 있으나 candidate event 구간 없음.
   - ⚠️ 이 gap들은 전부 **시간축·event** 필드이며, 이를 검증할 **운영 고정카메라 데이터가 0건**(drinking GT 0). 즉 gap 채우기 = passive 녹화 데이터 수집이 전제(§11).
3. **공통 artifact/cache 필요한가:** **미결정 — S1 벤치마크 전에는 계약으로 채택하지 않는다.** 현재 detector는 배치당 1회 로드·프로세스 수명 재사용(중복 재로드 없음, 감사 확인), R2 client는 싱글톤. **하지만 clip 단위로는 Gate(activity)·router_features·candidate가 서로 다른 프로세스·스케줄로 각자 R2 다운로드·디코드**한다. 신규 evidence 경로가 이 중복을 얼마나 늘리는지가 S1의 측정 대상이다. cross-process 공유 캐시(content-addressed)는 cache key·producer/consumer·lock·TTL·부분 생성 복구·용량 상한·영상 보존기간·crash cleanup·temp-0 관계가 **먼저 설계돼야** 하므로, S1 결과 전에는 production 계약으로 채택하지 않는다. S1에서 세 대안(§8.2 A/B/C)을 벤치마크 대상으로만 정의한다.
4. **새 워커 vs 기존 워커 확장:** **기존 워커 확장이 원칙.** 새 evidence는 (a) gate 경로(activity_worker/gate_runner)에 gap 필드를 추가하거나, (b) router_features에 시간축 시리즈를 추가하는 형태. 독립 신규 "evidence worker"는 다운로드·detector·provenance를 중복 생성하므로 **금지**. 단 시간축 dense-ROI가 detector 부하와 스케줄이 크게 다르면 §8/§9 벤치마크 결과에 따라 별도 저빈도 워커로 분리할 수 있다(승인 게이트).
5. **레포별 소유권:** §6.

---

## 5. 전체 데이터 흐름

```text
[camera firmware] → R2 clip + motion_clips row (started_at=녹화 UTC)
        │
        ├─(상주) router-features worker [petcam-lab, Mac mini]
        │        R2 → OpenCV(160x90) → MotionFeatureSet + window context
        │        → clip_router_features / clip_router_feature_runs   (shadow evidence, LLM 0)
        │
        ├─(테스트 카메라, Mac mini) activity-worker [nightly, gate_runner]
        │        R2 → detector(12f) → PrelabelResult + MotionMetrics + 4-state
        │        → clip_prelabels / clip_activity_assessments        (shadow evidence, VLM 0)
        │
        └─(야간 22/00/02/04, Mac mini) vlm-candidate-worker [nightly]
                 pool 적재 → enrich_prepool(gate on-demand: prelabel 없으면 detect)
                 → vlm_selector 4슬롯 랭킹(evidence 소비) → 최대 4/카메라/window
                 → claude batch4 → clip_vlm_jobs                     (shadow 원장)

── 이 설계가 추가하는 것 (전부 shadow, 승인 게이트 전까지 라우팅 없음) ──
   [HYBRID Evidence 정합화]
     - 위 evidence를 "Evidence minimal contract"(§7)로 정규화한 read 모델
     - gap 필드(dwell/ROI series/sustained_lapping/event ts) 계산 추가 (기존 워커 확장)
   [HYBRID Shadow 비교]
     - 같은 camera-window·같은 고정 4슬롯 예산에 대해:
         production_selector_rank  (현행 production selector budget-router-v1 exact 재현 — 동결 통제군)
         evidence_augmented_rank   (production selector + 신규 시간축 evidence만 추가)
         motion_only_rank          (선택적 ablation: 원인 분리용, motion_score만)
       를 나란히 저장 → 사람 blind 검수로 utility 비교 (§10)
     - recommended_vlm_mode(standard/full_plus_roi/human_review/audit_only)만 추천
       (skip·auto_label enum 없음)
```

핵심: **VLM 호출량·batch size·selector·자동 skip을 변경하지 않는다.** 추가되는 것은 전부 "관측·비교·추천"이며 실제 라우팅 전환은 별도 spec + 게이트.

---

## 6. 레포별 책임

| 레포 | 소유(SOT) | 이 설계에서의 역할 | 건드리지 않는 것 |
|---|---|---|---|
| **gecko-vision-gate** | detector·`clip_prelabels` schema·`activity_policy`(4-state)·`motion_evidence`·`provenance`·Gate v3 학습 | presence/bbox/trajectory/4-state의 **evidence 정의 SOT**. gap 중 detector 기반(sustained_lapping의 ROI 시리즈)은 여기서 정의 | 자동 skip·행동 확정 (계약상 금지) |
| **petcam-nightly-reporter** | 런타임 워커(candidate/backfill/activity)·`vlm_selector`·frame 추출·R2 다운로드·gate_runner 임베드 | **shadow 비교 실행·evidence enrichment 파이프라인**. existing vs evidence rank 저장, gap 필드를 기존 워커에 확장 | selector 랭킹 로직·VLM 호출량·batch4 (변경 금지) |
| **petcam-lab** | `clip_router_features`·router-features 워커·평가 harness·**설계/spec 문서**·DB migration DDL·evidence-candidate vocabulary 계약 | **Evidence minimal contract 문서 SOT**(이 문서)·벤치마크 harness·사람 blind GT 평가·OpenCV 시간축 시리즈(router_features 확장) | production DB write (migration 승인 전) |

**cross-repo 원칙:** worker/실험 코드 = nightly·gate에서 우선, petcam-lab은 계약·평가·문서. evidence schema 변경은 gecko-vision-gate(gate evidence) 또는 petcam-lab(router/contract)에서 우선. drift 시 audit 기록.

---

## 7. Evidence 최소 출력 계약 (Python Evidence Layer)

Python Evidence Layer가 clip당 내는 최소 출력. **이 값들은 evidence이지 ground_truth가 아니다.**

### 7.1 필드 (요청 계약 → 기존 매핑)

분모 = contract 필드 15개. 분류: **직접 재사용 9 / 정규화 필요 2 / 완전 신규 4.** (이 숫자는 필드 재사용 가능성이지 코드 완성률이 아니다. gate evidence 필드의 production 카메라 채움률은 §17-1 미확인.)

| contract 필드 | 값 | 분류 | 원천 |
|---|---|---|---|
| `presence` | `present` / `absent_candidate` / `uncertain` | **정규화** | 4-state: active∪exclude_static→present, exclude_absent→**absent_candidate**(자동제외 아님), unknown→uncertain |
| `bbox` + provenance | gecko_bbox[x,y,w,h] + checkpoint_sha256/model_version/threshold | 직접 재사용 | `clip_prelabels` |
| `trajectory` | max_bbox_center_disp, max_bbox_size_change, min_bbox_iou | 직접 재사용 | `MotionMetrics` |
| `body_displacement` | max_bbox_center_disp | 직접 재사용 | `MotionMetrics` |
| `dwell_duration` | ROI별 체류 초 | **완전 신규** | 신규(기존 워커 확장) |
| `roi_motion_series_summary` | 시간축 raw motion 시리즈 요약(peak/지속/반복성 등 의미 중립 수치) | **완전 신규(스칼라만 존재)** | 신규 |
| `repeated_micro_motion_candidate` | 전체 이동 작음 + 국소 반복 있음(의미 중립) | **완전 신규** | 신규 |
| `resting_candidate` | 같은 위치 몸통 이동 적음 evidence | 직접 재사용(재명명) | exclude_static / static_confirmed |
| `locomotion_candidate` | bbox/몸통 중심 유의미 위치 변화 | 직접 재사용(재명명) | active / motion_observed |
| `evidence_quality` | 합성 품질 등급 | **정규화(합성)** | evidence_reliability(router) + visible_frame_ratio + bbox_edge_clipped |
| `reason_codes` | 판정 근거 코드 | 직접 재사용 | reason_code(8종) |
| `detector_checkpoint_version` | checkpoint_sha256 + model_version | 직접 재사용 | GateProvenance |
| `sampler_version` | `even-uniform-v1` 등 | 직접 재사용 | GateProvenance |
| `threshold_version` | threshold + policy_version | 직접 재사용 | GateProvenance + policy |
| `source_frame_timestamps` | best_frame_ts + detected_objects.frame_ts + **event start/end** | **완전 신규(event 구간)** | `clip_prelabels`(부분) + 신규 |

집계: 직접 재사용 9(bbox, trajectory, body_displacement, resting, locomotion, reason_codes, detector_checkpoint, sampler, threshold) / 정규화 2(presence, evidence_quality) / 완전 신규 4(dwell, roi_series, micro_motion, event ts). **완전 신규 4개는 전부 시간축·event 필드이며 S2 raw-feature 단계에서만 계산하고, 이를 검증할 고정카메라 데이터는 0건**(§11·§17).

### 7.2 행동 의미 (candidate 어휘)

⚠️ **어휘 정의일 뿐 S2 계산 대상이 아니다.** 아래 중 raw·의미 중립 feature(`locomotion_candidate`, `micro_action_candidate`, `resting_candidate`)만 S2에서 계산하고, **의미 판정(`sustained_lapping_candidate`)은 S2에서 금지**(§12 — 고정카메라 drinking GT 0건이라 룰을 만들 근거가 없음). `sustained_lapping_candidate`는 fresh camera-night passive drinking GT 확보 후 **별도 spec**에서 raw feature→candidate로 연구한다.

- `resting_candidate`: 같은 위치에서 몸통 이동이 적다는 evidence. (≠ "basking 확정") — **S2 허용**(exclude_static 재명명, 판정 아닌 evidence).
- `locomotion_candidate`: bbox/몸통 중심의 의미 있는 위치 변화. — **S2 허용**.
- `micro_action_candidate`: 전체 이동은 작지만 국소 반복 움직임 존재(의미 중립). — **S2 허용**.
- `uncertain`: 가림·IR·흐림·Gate 미검출·evidence 충돌. — **S2 허용**.
- `sustained_lapping_candidate`: 몸통 안정 + 머리 ROI 반복. (≠ "drinking 확정") — **S2 금지, 별도 spec**(head ROI 추측 금지, §12).

### 7.3 금지된 출력 의미 (하드 계약)

- Python 결과를 `ground_truth`라고 부르지 않는다.
- `drinking` 확정값을 만들지 않는다 (최대 `sustained_lapping_candidate`).
- `basking` 확정값을 만들지 않는다 (최대 `resting_candidate`).
- `absent`를 자동 제외로 연결하지 않는다 (`absent_candidate`까지만; 실제 제외는 활동필터 v0의 별도 게이트 대상이며 exclude_absent는 이미 REJECT).
- enum에 `skip` / `auto_label` **없음**.

### 7.4 VLM routing = shadow 추천만

같은 camera-window·같은 고정 4슬롯 예산에 대해 세 랭킹을 저장한다. **통제군은 production을 exact 재현**해야 하며, motion-only는 통제군이 아니다(실제 production과 다른 통제군 비교는 실험 무효 — §10).

- `production_selector_rank` — **동결 통제군.** 현행 production selector를 exact 재현(§10.1 대응표).
- `evidence_augmented_rank` — production selector + **신규 시간축 evidence만** 추가한 랭킹.
- `motion_only_rank` — **선택적 ablation**(원인 분리용, motion_score만). 통제군 아님.
- `recommended_vlm_mode` ∈ { `standard`, `full_plus_roi`, `human_review`, `audit_only` }.
  - `skip`·`auto_label`은 enum에 넣지 않는다. VLM 호출량은 이 설계에서 변경하지 않는다.

---

## 8. 처리량·비용 계약

### 8.1 실측 기준값

- direct video ≈ **120k tok/clip**; adaptive frames ≈ **19.7k tok/clip**(83.6% 절감, drop 0.00pp, cascade REPORT).
- batch4 1회 ≈ API 환산 $0.53~0.59(구독 청구 $0).
- 구독 청결 처리 실적 ≈ **300 clip/밤**(단건 시절, api_error 0).
- rolling: cycle당 30, 일 600 cap, 정규 ±30분 guard(H4 deadline).

### 8.2 하드 계약

1. **VLM 호출량·batch size 불변.** Python evidence는 Claude를 호출하지 않는다.
2. **temp media 0** — 처리 후 잔여 파일 0(현행 계약 유지).
3. **정규 VLM/backfill deadline 지연 0** — evidence 워커는 정규 창·backfill guard와 겹치지 않게 스케줄.
4. **dense detector 전면 적용 금지** — 모든 frame에 detector는 위험 대조군(§14-D), production 후보 아님. 기본은 sparse detector(12f) + dense ROI OpenCV flow.

### 8.2b 다운로드·디코드 재사용 = S1 벤치마크 대상 (하드 계약 아님)

같은 clip을 gate·router_features·evidence가 서로 다른 프로세스·스케줄로 각자 다운로드/디코드한다. "clip당 1회 디코드 공유 캐시"는 매력적이지만 cross-process 공유는 cache key·producer/consumer·lock·TTL·부분 생성 복구·용량 상한·영상 보존기간·crash cleanup·temp-0 관계가 먼저 설계돼야 한다. 따라서 **S1 결과 전에는 어떤 캐시도 production 계약으로 채택하지 않는다.** S1에서 세 대안을 벤치마크로만 비교하고, 신규 evidence 경로가 기존 대비 **중복 다운로드를 얼마나 늘리는지**를 측정한다.

- **A.** 각 worker 독립 다운로드·디코드 (현행, 기준선).
- **B.** 같은 run 안에서만 메모리/로컬 프레임 재사용 (프로세스 내 한정).
- **C.** content-addressed cross-process cache (위 계약 8종 선설계 필요).

→ S1 결과 전 C 채택 금지.

### 8.3 정량 (1대 / 4대)

| | 1대 (~600/day) | 4대 (~2,400/day) |
|---|---|---|
| A candidate 호출 | 4 window×1 batch=~4호출/16clip | 4×4=~16호출/64clip |
| A backfill 호출 | 600 cap=~150 batch | 600 cap 동일 → **커버리지 ~28%로 급락, backlog 증가** |
| B sparse detector(12f) | ~7.2k inf/day (현 Gate와 동급) | ~28.8k inf/day (**유일 안전 구성**) |
| B dense detector(전 frame) | ~72k inf/day (위험 대조군) | ~288k inf/day (**금지**) |
| R2 다운로드 중복도 | S1 측정 대상(A/B/C) | S1 측정 대상(A/B/C) |

→ 4대에서 A는 영구 샘플링 체제가 되므로 **selector utility가 전부**. B의 sparse+ROI가 그 utility를 올리는 것이 하이브리드의 정량적 정당화. (유입량 실측은 S1 시작 시 production DB read-only로 산출 — §14.0.)

---

## 9. 실패·fallback 계약

- **presence fail-open**: 애매하면 `uncertain`(활동시간·후보에서 배제하지 않음). exclude_absent의 `absent_candidate` 매핑도 자동 제외 아님.
- **detector 미검출 ≠ absent 확정**: gecko_visible=false여도 global_bg_change 높으면 `uncertain`(gate `no_gecko_but_global_motion` 규칙 재사용).
- **evidence 없음 → production selector 그대로**: prelabel/assessment 없으면 evidence_augmented_rank는 production_selector_rank와 동일해진다(랭킹 붕괴 대신 통제군으로 수렴). production selector 자체는 evidence 없을 때 motion 신호로 자연 폴백(현행 동작 불변).
- **파싱/스키마 실패 → uncertain + needs_review**, 침묵 실패 금지(is_error 교훈).
- **enrich 실패 격리**: 한 clip 실패가 batch를 죽이지 않음(현행 R2 실패 격리·batch breaker 재사용).
- **provenance 필수**: checkpoint_sha256·sampler·schema·threshold 없는 evidence는 저장하지 않음(재현 불가 방지).

---

## 10. Shadow 검증 방식 (Phase 5)

**실제 selector를 변경하지 않는다.** 같은 camera-window·같은 고정 4슬롯 예산에 대해 랭킹을 저장·비교한다.

### 10.1 통제군 동결 — production_selector_rank 대응표

통제군은 **현행 production selector를 exact 재현**해야 한다. production과 다른 통제군(예: motion-only)으로 비교하면 실험이 무효다. 현재 runtime HEAD는 `cbd2e09`지만 selector 알고리즘 비교군은 변경이 없었던 `b9dc9eb` 구현을 동결 기준으로 유지한다. 아래는 production selector가 동결 기준으로 삼는 `b9dc9eb` 구현의 대응표다. (feature branch `97a24a4`는 `config.py`만 변경했고 selector 로직은 동일 — 실측.)

| 항목 | production 값 (동결) |
|---|---|
| selector 코드 | `reporter/vlm_selector.py::select_candidates` @ `b9dc9eb` |
| `VLM_SELECTOR_VERSION` | `budget-router-v1` |
| 4슬롯 ORDER | CUSTOMER_HIGHLIGHT → SUBTLE_BEHAVIOR → DIVERSITY_DISCOVERY → EXCLUSION_AUDIT |
| 슬롯1 pool/score | `activity_decision=="active"` / `(is_active, roi_flow_mag, max_bbox_center_disp, -history_bucket, motion_score)` |
| 슬롯2 pool/score | `gecko_bbox ∧ global_bg_change≤median ∧ roi_flow_mag≥median` / `(roi_flow_mag/(global_bg_change+.001), -history_bucket)` |
| 슬롯3 pool/score | 남은 전부 / `(-history_bucket, -motion_quartile)` |
| 슬롯4 pool/score | `activity_decision∈{exclude_absent,exclude_static,unknown}` / `(-history_bucket, seeded hash)` |
| 예산 | `VLM_MAX_PER_CAMERA_WINDOW=4`, `VLM_MAX_PER_CAMERA_NIGHT=16` |
| 입력 feature | activity_decision, roi_flow_mag, max_bbox_center_disp, global_bg_change, gecko_bbox, motion_score, motion_quartile, bbox_bucket, history bucket |

- `production_selector_rank` = 위 코드/버전/feature/commit을 그대로 재현한 top4. **동결 통제군.**
- `evidence_augmented_rank` = production selector에 **신규 시간축 evidence(dwell/raw series/event ts)만** 추가. 다른 파라미터·슬롯 불변.
- `motion_only_rank` = 선택적 ablation(motion_score만). **통제군 아님, 원인 분리용.**

세 랭킹의 union clip을 **사람 blind 검수**(Python evidence·VLM 결과 비공개) 한다.

### 10.2 평가 계약 (사전 등록, 결과 후 변경 금지)

**표본 최소 조건 (전부 충족해야 adoption 평가, 미달이면 EDA):**
- 독립 camera-night **최소 3개**.
- 카메라 **최소 2대**. **1대뿐이면 결과는 adoption이 아니라 EDA**.
- 30분 episode dedup 적용.
- 사람 blind 검수 union clip **최소 60개**.
- 같은 window의 **고정 4슬롯 예산** 비교(production_selector_rank와 동일 예산).
- Python/VLM evidence는 **최초 사람 GT 확정 전 비노출**.

**"가치 있는 후보" 정의 (기존 GT 필드로 재현 가능):**
- `highlight_recommendation=include` (기존 하이라이트 정책 필드).
- care action ∈ {drinking, feeding, prey, defecating, shedding, hand_feeding} (behavior GT).
- wheel/object interaction evidence (기존 enrichment evidence 필드).
- owner가 별도 확정한 review-worthy 결과.
- (새 주관 필드 불필요 — 위 기존 필드로 재현. 만약 추가 필드가 필요해지면 그 **이유와 입력 계약을 이 절에 명시**한 뒤에만 도입.)

**측정 지표:**
- 일반 moving 비율(낮을수록 이득 — motion 편향 탈피).
- 가치 있는 후보(위 정의) 발견율: evidence_augmented vs production.
- `visible → absent_candidate` 오류 — **안전 보조지표**(0 목표). ⚠️ 단 **shadow rank는 실제 제외를 하지 않으므로**(랭킹 순위만), 이 지표는 "미래 라우팅 시 위험"을 미리 보는 것이지 현재 손실이 아님을 구분 기록.
- 카메라·시간·IR·가림 strata별 오류.
- episode near-duplicate 비율(30분 dedup).
- VLM 호출 예상 절감률(**최초 목표 아님**, 참고만).

**성공 threshold (사전 등록, 결과 본 뒤 변경 금지 — TEST-SHEET 의무):**
- evidence_augmented_rank의 "가치 있는 후보" 발견율이 production_selector_rank 대비 **양(+)의 차이**(구체 수치는 TEST-SHEET에 표본 확정 후 사전 기입) AND
- `visible → absent_candidate` 오류가 검수 표본에서 **0** AND
- 정규 VLM crossover 0 유지.

**최초 목표는 VLM 절감이 아니라 후보 utility 개선.** 절감 주장은 fresh camera-night(§11) + 계약 동결 후 별도 보고.

---

## 11. 사람 blind GT 계약

- **blind-first**: 최초 사람 GT 확정 전 Python evidence·VLM prediction을 라벨러에게 노출하지 않는다(GT 앵커링 차단).
- `prediction`(모델)과 `ground_truth`(사람)를 분리 컬럼으로. initial_gt 불변 + append-only revision(현행 계약 재사용).
- **fresh camera-night 게이트**: evidence 룰·threshold·candidate 어휘의 **채택**은 정책 동결 이후 새로 촬영한 camera-night에서만 평가. 기존 72/203/backlog 재사용 금지.
- **passive 녹화 전제**: sustained_lapping/dwell gap을 검증할 "카메라 고정 + 물그릇/급여 표면 + 야간 IR" 데이터는 현재 0건. 이 데이터 수집이 gap 채우기의 선행 조건(evidence-feeding spec §7 Phase 7).
- 승격 전제(활동필터·gate-v3와 동형): **false exclusion 0 확인**, 1건이라도 나오면 canary 즉시 rollback.

---

## 12. 단계별 rollout

| 단계 | 내용 | 산출 | 게이트 |
|---|---|---|---|
| **S0 정합화·검증 — 실측 완료(2026-07-16, verdict `S0_HOLD_DATA_CONTRACT`)** | live runtime SOT 정정(§1), Evidence contract(§7) 문서 확정, 기존 evidence coverage read-only 실측(`scripts/audit_python_evidence_coverage.py`, snapshot `213586c2a3bd6f0c`). 결과: eligible 2700 / any_prelabel 2634(97.6%) / policy_ready 2634 / core_complete 2630. **HOLD 사유 = 4건 `frames_sampled=0` evidence**(camera `f6599924`, 2026-07-16 18:44~18:59 KST). | `reports/python-evidence-s0-coverage-20260716/` + `docs/handoff-prompts/2026-07-16-python-evidence-s0-coverage-audit-report.md` | **S0 계약 미충족(core completeness 99.85%) → S1 착수 보류**. `frames_sampled=0` 원인 규명·해소 후 재감사 |
| **S0.1 frame-sampling self-healing — 재감사 완료(2026-07-17, verdict `S0_PASS_WITH_COVERAGE_GAP`)** | `frames_sampled=0` 원인=indexed seek 실패(sparse-keyframe H.264, live 24건 진단, 0 permanent). Gate 순차 fallback(`f182ea4`) + nightly 최소프레임 barrier·불완전 assessment 재선정(`19a1fe5`) 배포. Mac mini canary + 자연 hourly cycle 실측: 24건 전부 완전 evidence relink, 신규 `frames_sampled<6` 생성 0. 재감사 snapshot `a57f1c3d9f91f5b3`: eligible 2942 / any_prelabel 2889 / policy_ready 2889 / **core_complete 2889 (== policy_ready, `frames_sampled=0` 계약 위반 해소)**. 기존 24 불완전 prelabel 은 audit 이력으로 보존(현재 assessment 미참조). | `reports/python-evidence-s0-coverage-20260716-rerun/` + `docs/handoff-prompts/2026-07-16-s0-frame-sampling-self-healing-report.md` | **데이터 계약 충족 → HOLD 해소.** 잔여 gap = 카메라 `90119209` policy_ready 0.70(<0.8, 대부분 07-14 27건 미처리로 pre-existing). **S1 은 covered subset(policy_ready≥80%: `5b3ea7aa`·`f6599924`)으로만, 전체 일반화 금지. S1 미착수.** |
| **S1 벤치마크** | §14 유입량 산출(§14.0) + A/B/C/D 처리량 측정(Mac mini) | benchmark REPORT | **성공 기준(§14) 미달 시 구성 축소/보류** |
| **S2 raw evidence 생성(shadow)** | **raw·의미 중립 feature만** 기존 워커에 확장: bbox/whole-gecko ROI raw motion series, dwell, event start/end, 반복성·주기성 등 수치 feature, provenance. **판정 없음.** shadow 저장, 라우팅 없음 | raw evidence rows | migration 승인(§15) |
| **S3 shadow selector 비교** | production vs evidence_augmented vs (선택)motion_only rank 저장·사람 blind 검수(§10) | shadow 비교 REPORT + TEST-SHEET | §13 성공 미달 시 B 보류·A 유지 |
| **S4 fresh camera-night 사람 GT** | passive 녹화(고정카메라 + 물그릇/급여 표면 + 야간 IR) + blind GT | GT REPORT | **false exclusion 0** |
| **S4.5 sustained_lapping 연구(별도 spec)** | S4 GT 확보 후에만: raw feature → `sustained_lapping_candidate` 룰 연구. head ROI는 pose/keypoint/head detector 확보 시에만 | 별도 spec + TEST-SHEET | GT + head-detector 전제 |
| **S5 라우팅 추천 surfacing** | recommended_vlm_mode를 실제 selector 우선순위에 반영(여전히 skip/auto_label 없음) | **별도 spec + TEST-SHEET + 게이트 필수** | fresh holdout 승인 |

**S2 하드 금지:** `sustained_lapping_candidate` 판정 · `drinking` candidate · head ROI 추측(pose/keypoint/head detector 없이 bbox 방향만으로 머리 위치 가정 금지) · threshold 채택. 이유: 고정카메라 passive drinking GT가 0건이라 어떤 lapping/head 룰도 검증 근거가 없다. raw feature만 쌓고, 의미 판정은 S4.5 별도 spec으로 분리한다.

S0–S1은 이 설계 범위의 직후 작업(구현 승인 후). S2 이후는 각자 게이트.

---

## 13. 성공·중단 기준

**성공(하이브리드 진행 가치 있음):**
- S1 (단일 처리량 기준, §14): sparse+ROI 구성이 **projected 4-camera p95 유입량의 최소 2배 지속 처리** AND 정규 VLM/backfill deadline 지연 0 AND 기존 worker exit/error 증가 0 AND temp media 0 AND 메모리·디스크 상한 준수.
- S3 (§10.2 사전 등록 계약): evidence_augmented_rank의 "가치 있는 후보"(§10.2 정의) 발견율이 production_selector_rank 대비 **양(+)의 차이**(TEST-SHEET 사전 기입 수치 충족) AND `visible→absent_candidate` 오류 0 AND 정규 VLM crossover 0.

**중단(A 유지 + GT 집중으로 회귀):**
- S1: 위 단일 기준 미달(§14 성공 기준을 못 채우면 구성 축소 또는 보류).
- S3: utility 개선 없음 또는 `visible→absent_candidate` 오류 ≥1.
- 어느 단계든 정규 VLM crossover ≥1 또는 기존 워커 exit/error 증가.

**가장 강한 반론(선행 리뷰 §10 인용):** 하이브리드는 "사람 GT 없이 proxy로 룰 만든" router 실패(v0/v1/v2 invalid-for-adoption)의 4번째 반복이 될 수 있다. **처리:** evidence **생성**(체류·trajectory 기록)은 GT 없이도 미래 검증 표본을 공짜로 쌓는 자산이고 shadow라 틀려도 비용이 저장뿐 → 지금 진행. evidence **룰 채택**은 이 반론이 전적으로 옳음 → S4(fresh camera-night + 사람 blind GT) 게이트 전까지 금지. 이 분리가 무너지면 즉시 ADOPT_A로 회귀.

---

## 14. 처리량 벤치마크 설계 (Phase 4 — 계획만, 실행 안 함)

### 14.0 유입량 산출 (S1 시작 시, production DB read-only)

처리량 기준을 실측 유입에 고정하기 위해 벤치마크 전에 production DB read-only로 아래를 산출한다(VLM/detector 실행 없음):
- 최근 7일 camera별 clips/hour
- 전체 clips/hour p50 / p95 / max
- **projected 4-camera p95** (현재 카메라 수 기준 선형 투영 + 가정 명시)
- 현재 worker 동시 실행 시간대(candidate 22/00/02/04, backfill 매시 :35, router-features 상주, nightly 22/00/02/04:05)

### 14.1 비교 조건

- **A.** 기존 6-frame 추출 (현행 VLM 입력 경로).
- **B.** sparse Gate 12-frame (현행 activity/gate 경로).
- **C.** sparse Gate + bbox 내부 dense OpenCV flow (**production 후보**).
- **D.** 모든 frame detector (**위험 대조군, production 후보 아님**).

각 조건을 다운로드·디코드 재사용 대안(§8.2b A/B/C: 독립 / run 내 재사용 / cross-process cache) 축과 교차해, **신규 evidence 경로가 기존 대비 중복 다운로드를 얼마나 늘리는지**를 함께 측정한다.

### 14.2 측정 항목 (각 조건)

- R2 다운로드 포함/제외 wall time + **중복 다운로드 횟수**
- 디코딩 시간
- detector 시간 (MPS vs CPU)
- dense ROI flow 시간
- clip end-to-end p50/p95
- 메모리 peak / 디스크 사용
- 임시파일 수(=0 확인)
- 기존 워커(candidate/backfill/router-features/nightly) 동시 실행 시 schedule 지연
- 1대/4대 예상 지속 처리량 추정(§14.0 유입량 기준)

### 14.3 성공 기준 (단일, §13과 동일)

- **projected 4-camera p95 유입량의 최소 2배 지속 처리** AND
- 정규 VLM/backfill deadline 지연 **0** AND
- 기존 worker exit/error 증가 **0** AND
- temp media **0** AND
- 메모리·디스크 상한 준수.

**실행 위치:** Mac mini(실 부하 재현). 벤치마크는 read-only(R2 read + 로컬 연산), DB write·VLM 호출 없음. TEST-SHEET 선등록 의무(`research-testing.md`).

---

## 15. Rollback

- **모든 evidence는 shadow-only** → 롤백은 "쓰기 중단 + row 무시"로 충분(GT·앱·활동시간 무영향).
- **kill switch**: evidence 생성/enrichment는 env 플래그로 즉시 off(현행 `REGISTER_HIGHLIGHTS=0` 패턴 재사용).
- **워커 중단**: `launchctl bootout gui/$(id -u)/<label>` — DB row는 감사 원장이므로 삭제하지 않음.
- **selector 불변**: evidence rank는 별도 저장이므로, S5 전에는 실 selector 롤백 대상이 없음.
- **false exclusion 발생 시**: 해당 카메라 evidence 채택 즉시 중단(활동필터 rollback 룰과 동형).

---

## 16. 구현 전 승인 경계 (Phase 6 — cross-repo handoff)

구현은 이 문서만으로 시작하지 않는다. 아래 handoff manifest를 절대경로로 작성하고 `scripts/verify_agent_handoff.py`로 `HANDOFF_OK`를 받은 뒤에만 착수한다.

### 16.1 manifest 필수 필드 (validator 계약, `scripts/verify_agent_handoff.py`)

| 필드 | 필수 | 값 예시 |
|---|---|---|
| `handoff_version` | ✅ | `v1` |
| `task_id` | ✅ | `python-evidence-hybrid-s1-benchmark` |
| `execution_repo` | ✅ | `/Users/baek/petcam-nightly-reporter` 또는 `/Users/baek/myPythonProjects/gecko-vision-gate` 또는 `/Users/baek/petcam-lab` |
| `design_path` | ✅ | `/Users/baek/petcam-lab/docs/superpowers/specs/2026-07-16-python-evidence-hybrid-design.md` |
| `plan_path` | ✅ | (구현 plan 절대경로 — 승인 후 생성) |
| `commit_sha` | ✅ | 40자리 HEAD SHA |
| `implementation_host` | ✅ | `BaekBook-Pro-14-M5.local` |
| `runtime_kind` | ✅ | `none` / `launchagent` / `server` / `scheduled-job` / `mobile-build` |
| `runtime_host` | runtime_kind≠none일 때 필수 | `baeg-endeuui-Macmini.local` |
| `runtime_label` | 선택 | `com.petcam.<...>` |

### 16.2 handoff 규칙

- benchmark(S1)은 `runtime_kind=none` 또는 read-only 실행. **worker 신설·plist 변경은 별도 manifest(`runtime_kind=launchagent` + `runtime_host`=Mac mini + service label).**
- verification command: `cd /Users/baek/petcam-lab && uv run python scripts/verify_agent_handoff.py --manifest /absolute/handoff.md` → `HANDOFF_OK` 전문 포함.
- `HANDOFF_OK` 아니면 중단. HEAD mismatch·untracked·잘못된 repo를 우회하지 않는다.
- 운영 보고는 구현 host가 아니라 실제 `runtime_host`의 hostname·service loaded·working dir·repo HEAD·run 결과를 증거로.
- **이번 작업에서는 manifest를 실행하거나 구현을 시작하지 않는다.**

### 16.3 승인 게이트 요약

1. **S1 benchmark 승인** 전 worker 코드 없음.
2. **migration 승인**(§15/DB DDL) 전 production DB write 없음.
3. **fresh camera-night + 사람 blind GT** 전 evidence 룰 채택·라우팅 없음.
4. **자동 skip / 자동 GT / 자동 행동 라벨 영구 금지** (별도 spec 없이는).

---

## 17. 미결정 항목 (열린 질문)

1. **production 카메라의 gate evidence 채움 여부 — S0 실측 완료(2026-07-16), verdict `S0_HOLD_DATA_CONTRACT`.** 호스트 오배치는 해결됐고, 이제 `2026-07-14~16` KST 창을 read-only 감사했다(`scripts/audit_python_evidence_coverage.py`, snapshot `213586c2a3bd6f0c`, 독립 SQL 재조정 일치, mutation 0). **재고/현재정책:** eligible motion clip **2700**, any_prelabel **2634(97.6%)**, `activity-v1` policy_ready **2634**, core_complete **2630**. **HOLD 사유 = core completeness 99.85%** — camera `f6599924`의 4건 evidence 가 `frames_sampled=0`(2026-07-16 18:44~18:59 KST)으로 필수 provenance 계약(`frames_sampled>0`, §5.3)을 어긴다. **strata gap:** camera `f6599924` 2026-07-14 는 25 clip 전부 prelabel 0(0% coverage), camera `90119209` 초기일 저조(0.20). **selector 시점(정규/backfill 분리, exact/estimate/not_reconstructable):** 정규 `budget-router-v1` run 은 감사 창에서 **camera `5b3ea7aa` 5건뿐**(다른 두 카메라는 정규 selector run 0), 최근 정규 run 의 window-time availability 는 ~58~66%(estimate). backfill 71 run 은 대부분 감사 시작 이전(2026-07-07~13) window 라 window_clips=0 로 집계된다(경계 caveat). exact eligible-pool 은 복원 불가로 유지. **결론:** `frames_sampled=0` 원인 규명·해소 전까지 **S1 착수 보류**. 정규 candidate 경로는 `enrich_prepool`로 on-demand 채우므로 "선택 전 전체 풀"이 아니라 "적재된 풀"만이라는 한계도 그대로다. 상세: [`S0 coverage audit report`](../../handoff-prompts/2026-07-16-python-evidence-s0-coverage-audit-report.md) · `reports/python-evidence-s0-coverage-20260716/`.
   - **[해소 2026-07-17] S0.1 self-healing → `S0_PASS_WITH_COVERAGE_GAP`.** `frames_sampled=0` 원인은 indexed seek 실패(sparse-keyframe H.264; live 24건 진단, seq 디코딩 12~46장 = 0 permanent)였다. Gate 순차 fallback(prod main `f182ea4`) + nightly 최소프레임 barrier·불완전 assessment 재선정(prod main `19a1fe5`) 배포 후 Mac mini canary + 자연 hourly cycle(15:11Z) 실측: 불완전 24건 전부 완전(12프레임) evidence 로 relink, 신규 `frames_sampled<6` 생성 0, temp media 0, exit 0. 재감사(snapshot `a57f1c3d9f91f5b3`, 독립 SQL 재조정 일치, mutation 0): eligible **2942** / any_prelabel **2889** / policy_ready **2889** / **core_complete 2889 (== policy_ready → `frames_sampled>0` 계약 충족)**. 기존 24 불완전 prelabel 은 삭제·수정 없이 audit 이력으로 보존(현재 assessment 미참조). **잔여 gap = strata coverage**(pre-existing): `90119209` 전체 0.70(07-14 7/34), `f6599924` 07-14 0/25 — `frames_sampled=0` 결함과 무관. **S1 은 covered subset `5b3ea7aa`·`f6599924`(policy_ready≥80%)로만 한정, 일반화 금지.** 상세: `reports/python-evidence-s0-coverage-20260716-rerun/` · [`self-healing report`](../../handoff-prompts/2026-07-16-s0-frame-sampling-self-healing-report.md).
2. **gap 필드를 gate 경로 확장 vs router_features 확장 어디에 둘지** — dwell/ROI series가 detector 의존이면 gate, OpenCV만이면 router_features. S1 벤치마크가 결정.
   - **[2026-07-17] S1 = `S1_HOLD_RUNTIME_BUDGET` → recovery = `S1R_HOLD_INCOMPLETE`(S2 blocked, 이력 additively 보존).** recovery 는 A6 확정 원인(실행 PATH `/opt/homebrew/bin` 누락)을 fail-closed preflight 로 고치고 동결 workload 를 완주 시도했다. MPS window 1(333 records)에서 A6 는 29/32 clip 정상이었으나 **3 clip(dur 5.2~5.5s)이 `extract_six` 결정론적 실패**(read-only 6단계 진단: input-seek `-ss t -i`가 sparse-decodable clip(13 vs 32 frames) 이른 timestamp 에서 rc=234 'Conversion failed!'; duration mismatch·clip-short 아님). 3 clip×2 cache×3 repeat = **18 measured key 영구 미완성** → 동결 계약 §9 PASS(전체 key 완전성) 원리적 불가 → `S1R_PASS` 불가 확정, 추가 계산 중단. **CROI mps cold capacity 1435.36 clips/h 는 160 게이트를 크게 상회하나 완전성 미충족으로 참고값(informative-only)**이며 adoption·gap 필드 배치 결정 근거로 쓰지 않는다. 안전 전부 통과(temp0·DB/R2 write0·VLM0·LaunchAgent 조작0·production job 지연0·nightly `19a1fe5`/gate `f182ea4b` 불변). 독립 재계산 harness 정확 일치. **재개 조건:** A6 baseline 을 완전성 계약에 둘지 재설계(새 spec+TEST-SHEET) — 결정론 실패 clip 명시 제외 / `extract_six` output-seek 견고화(production 변경=별도 승인) / sparse-decodable clip 표본 분리. 상세: [`recovery REPORT`](../../../experiments/python-evidence-s1-recovery/REPORT.md) · [`완료 보고서`](../../handoff-prompts/2026-07-17-python-evidence-s1-recovery-report.md).
3. **sustained_lapping / head ROI 는 이 설계에서 미해결로 남긴다(의도)** — camera_rois 테이블은 spec만 있고 미적용. **S2에서 head ROI를 bbox 방향으로 추측하지 않는다.** head ROI는 pose/keypoint/head detector 확보 + fresh camera-night passive drinking GT 확보 후 S4.5 별도 spec에서만. 이 문서는 sustained_lapping 룰을 정의하지 않는다.
4. **evidence_quality 합성 공식** — reliability + visible_ratio + edge_clip을 어떤 등급으로 묶을지 (S3 전 확정).
5. **motion_only_rank ablation 신호 정의** — 통제군이 아닌 ablation의 정확한 신호(motion_score만 vs active_motion_ratio 포함). 통제군 production_selector_rank는 §10.1로 이미 동결됨.

---

## 18. 참고

- 선행 리뷰: 2026-07-16 A vs B 독립 아키텍처 리뷰(`ADOPT_HYBRID`).
- SOT: `docs/AI-VIDEO-ANALYSIS-STRATEGY.md`(3층 전략) · `specs/feature-rba-data-engine-v1.md` · `specs/feature-rba-evidence-based-feeding-drinking.md`(§4.4/§6.4/§14) · gecko-vision-gate `specs/gate-v3.md`·`specs/architecture.md`.
- 실험: `experiments/rba-evidence-first-cascade/REPORT.md`(83.6%/0.00pp, conservative-v0 false auto 66~77%) · `experiments/gate-recall/`(recall 90.9% reject) · `experiments/roi-crop-center/`(crop 재판정 순 0) · `experiments/drinking-motion-poc/`(global motion 음성).
- 코드: nightly `reporter/{gate_runner,activity_worker,activity_store,vlm_selector,vlm_backfill_selector,vlm_backfill_gate,frames,vlm_frames,r2,vlm_candidate_worker}.py` · gate `src/gecko_vision_gate/{schema,activity_policy,motion_evidence,provenance,frame_sampling}.py` · lab `backend/router_features.py`·`scripts/_extract_frames_clip.py`·`scripts/verify_agent_handoff.py`.
