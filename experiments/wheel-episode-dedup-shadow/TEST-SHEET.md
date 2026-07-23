# TEST-SHEET — P4 Cam(dev) 쳇바퀴 에피소드 중복 묶음 read-only shadow

> 🔒 **실행 전 동결 (pre-registration). 사후 변경 금지.**
> 작성일: 2026-07-23 · 트랙: RBA Data Engine v1 (owner 라벨링 UX) · Phase: S1 read-only shadow
> 설계 정본(SOT): [`docs/superpowers/specs/2026-07-23-wheel-episode-dedup-design.md`](../../docs/superpowers/specs/2026-07-23-wheel-episode-dedup-design.md)
> 결정 게이트: `docs/decision-gate.md` 2026-07-23 항목 (shadow 설계 승인)
> 계획: [`docs/superpowers/plans/2026-07-23-wheel-episode-dedup-shadow.md`](../../docs/superpowers/plans/2026-07-23-wheel-episode-dedup-shadow.md)

---

## 0. 대상 카메라 별칭 해소 (사전등록 근거)

설계·태스크의 대상 명칭은 **"P4 Cam 1"** 이지만 production DB `cameras` 테이블에는 그 exact name 이 없다.
2026-07-23 SELECT-only 실측:

- `cameras` 총 4대: `P4 Cam (dev)` · `P4 Cam 2(dev)` · `P4 Cam 3` · `P4 Cam 4`. **"P4 Cam 1" 부재.**
- v3 `motion_clip_labeling_sessions` 의 `enrichment_object='wheel'` GT = **24건, 전부 `P4 Cam (dev)` 소속** (전량 촬영일 2026-07-22). 설계 §2.1 의 "wheel GT 24개" 와 정확히 일치.
- owner 확정(2026-07-23): 대상 = **`P4 Cam (dev)`**. "P4 Cam 1" 은 이 카메라의 별칭으로 간주.

**규칙:** camera UUID 는 하드코딩하지 않는다. shadow 는 `cameras` 에서 **exact name `"P4 Cam (dev)"`** 로 조회해 UUID 를 얻는다. 조회 결과가 정확히 1건이 아니면 즉시 중단(HOLD).
(관측된 UUID = `5b3ea7aa-b4a7-4146-8f48-caf69e29e49c` — 기록용, 코드 입력값 아님.)

---

## 1. 가설

- **H0 (귀무):** 고정 wheel ROI + ROI temporal motion + perceptual similarity + 시간 외곽 경계로는 P4 Cam(dev) 반복 쳇바퀴 clip 을, 서로 다른 행동을 섞지 않고(precision-first) 대표 축약으로 묶을 수 없다. (false merge 발생 OR 결정론/overlap 위반 OR 검토량 감소 미달)
- **H1 (대립):** 위 조합으로 fresh camera-night 표본에서 false merge 0 · overlap 0 · 결정론 100% 를 지키며, known wheel 표본의 우선 검토량을 50% 이상 줄이는 read-only 묶음 후보를 만들 수 있다.

이 테스트의 산출물은 **owner 전수 감사에 넘길 artifact** 다. 최종 false-merge/대표보존 판정은 owner blind 감사(BLIND-REVIEW.csv)가 수행한다. shadow 는 owner 판단이 필요없는 게이트(결정론·overlap·temp·mutation·검토량)만 자체 검증한다.

---

## 2. Sample list — frozen cohort (재현 방법 고정)

shadow 시작 시 아래 규칙으로 cohort 를 **동결**하고 `frozen-cohort.json` 에 기록한다. 시작 이후 추가·수정된 라벨/clip 은 frozen 평가셋에 섞지 않는다.

### 2.1 fresh 평가 cohort (grouping 대상)

- camera: `P4 Cam (dev)` (exact name 조회)
- started_at 범위: `2026-07-19T00:00:00+00:00` ≤ started_at < `2026-07-22T00:00:00+00:00` (UTC)
  - = 독립 camera-night 3개 (07-19 / 07-20 / 07-21). **07-22 는 known wheel GT 보유 → held-out(§2.3), 07-23 은 부분(6건) → 제외.**
- 필터: `r2_key IS NOT NULL` (2026-07-23 실측 779/779 충족)
- 정렬·재현: `ORDER BY started_at ASC, id ASC` (결정론 앵커)
- 관측 규모(2026-07-23): **779 clips, 전부 r2_key + Python Evidence run 100% 커버**

### 2.2 Python Evidence run identity

각 clip 의 canonical Python Evidence run = `clip_python_evidence_runs` 중
`evidence_schema_version='python-evidence-raw-v1' AND algorithm_version='croi-temporal-v1'` 를
`ORDER BY created_at DESC` 한 **최신 1건**. run id + 7-column provenance 를 `frozen-cohort.json` 에 박제한다.

### 2.3 known wheel 회귀 표본 (EDA/regression 전용, grouping 대상 아님)

- v3 `motion_clip_labeling_sessions` 에서 `current_gt->>enrichment_object='wheel'` OR `initial_gt->>enrichment_object='wheel'` 인 clip 의 camera_id = P4 Cam(dev) 인 것 = **24건**(관측). 전량 촬영일 2026-07-22.
- 용도: (a) wheel ROI profile 도출 근거, (b) 우선 검토량 감소율 측정. **fresh cohort 와 절대 혼합 금지.**
- snapshot: 이 24 clip_id 목록을 freeze 시점에 `frozen-cohort.json` 에 고정한다. 이후 owner 라벨 변경이 분모(24)를 바꾸지 못하게 한다.

### 2.4 동시 라벨링 안전 계약 (cohort 고정 항목)

`frozen-cohort.json` 에 아래를 모두 기록한다:

- `clip_ids` (fresh) + `camera_id` + `started_at_range`
- `python_evidence_run_identity` (clip_id → run_id/versions)
- `known_wheel_gt_clip_ids` (24, snapshot)
- `gt_snapshot_watermark`: freeze 시점 `motion_clip_labeling_sessions` 의 `max(updated_at)` (P4 Cam dev clip 대상). 이후 갱신 라벨 무시 기준.
- `cohort_sha256`: 위 항목의 **canonical JSON**(정렬된 key, 정렬된 clip_ids) SHA-256

---

## 3. 모델 / 입력표현 / 알고리즘 버전

- **모델:** 없음. VLM/LLM 호출 0. 순수 OpenCV/Numpy 결정론 파이프라인.
- **입력표현:**
  - R2 에서 clip mp4 를 OS temp 로 GET → ffmpeg 적응형 프레임 추출(간격 3.5s, clamp 6~20, 구간중앙, no-upscale @1080; `scripts/_extract_frames_clip.py` 규약과 동일).
  - `wheel_roi_profile_v1` (normalized 좌표 + provenance) 로 각 프레임을 wheel ROI 로 crop.
- **알고리즘 버전:** `wheel-episode-dedup-shadow-v1`
  1. IR/day mode 판정 (ROI 채도 기반)
  2. ROI temporal motion 시계열 + 요약(mean/peak/periodicity autocorr)
  3. ROI perceptual signature (dHash 64-bit, 대표 프레임)
  4. evidence quality/novelty (Python Evidence provenance + 프레임 decode 상태)
  5. 시간 외곽 경계(≤10분) 안에서 anchor 기반 precision-first grouping
  6. representative ≤3 선택
- **wheel_roi_profile_v1 도출:** known wheel GT 24 clip 의 대표 프레임 위에서 ROI 를 시각+모션에너지로 국소화 → normalized 좌표 확정 → `wheel-roi-profile-v1.json` + `ROI-PREVIEW.png`. **fresh grouping 실행 전에 동결.** owner 확인 전까지 provisional(production 계약 아님).
- **similarity threshold 는 known wheel GT(24) 에서 calibration 후 profile 에 동결**, fresh cohort 에서 튜닝 금지.

---

## 4. 측정 지표

| 지표 | 정의 | 산출 위치 |
|---|---|---|
| group 수 / membership 수 / 대표 수 | fresh cohort grouping 결과 | shadow-groups.json |
| ungrouped 수 | 애매·저품질·저모션으로 미분류 | shadow-groups.json |
| known wheel 검토량 감소율 | 1 − (24 GT 를 grouping 했을 때 대표 수) / 24 | REPORT.md |
| clip group overlap | 한 clip 이 2 그룹 이상 소속된 건수 | 자체 검증 |
| 결정론 | 같은 frozen cohort 2회 실행 시 shadow-groups.json SHA 일치 | 자체 검증 |
| temp media 잔존 | 종료 후 temp 디렉토리 mp4/frame 수 | 자체 검증 |
| production mutation fingerprint | SELECT-only 전/후 라벨·triage·evidence·R2 카운트 지문 | 자체 검증 |
| R2 write / VLM 호출 | 각 0 | 코드 계약 + 자체 검증 |
| false merge · 대표 보존 | 서로 다른 행동 오병합 · distinct interaction 대표 보존 | **owner blind 감사(BLIND-REVIEW.csv)** |

---

## 5. 합격 기준 (hard gate — 숫자, 사후 변경 금지)

shadow 자체 검증 게이트 (전부 충족해야 `SHADOW_READY_FOR_OWNER_AUDIT`):

- G-DET **결정론 = 100%** — 같은 frozen cohort 2회 실행 output SHA 동일
- G-OVL **clip group overlap = 0**
- G-TMP **temp media = 0** (종료 시)
- G-MUT **production mutation fingerprint 불변** — SELECT-only 전/후 동일
- G-R2 **R2 write = 0**, G-VLM **VLM 호출 = 0**
- G-SEC **secret/signed URL/raw media git-tracked = 0**
- G-WORKER **production worker deadline 지연·exit/error 증가 = 0**

데이터 충분성 게이트 (미달 시 `SHADOW_BLOCKED_INSUFFICIENT_DATA`):

- D-NIGHT **fresh 독립 camera-night ≥ 3**
- D-MEM **제안 membership ≥ 100**
- D-ROI **ROI 신뢰 가능** (대표 프레임에서 wheel 영역이 육안 확인되고 ROI 가 그 영역을 덮음)

효과 게이트 (측정·보고, owner 최종 판정 대상):

- E-WORKLOAD **known wheel(24) 우선 검토량 감소 ≥ 50%** (= 대표 수 ≤ 12)
- E-FALSEMERGE **owner blind 감사에서 mixed-action false merge = 0** → **1건이라도면 production 도입 reject**
- E-PRESERVE **distinct wheel interaction 대표 보존율 = 100%**

---

## 6. 예상 비용/토큰

- LLM/VLM 토큰: **0** (호출 없음).
- 연산: R2 GET (fresh 779 + known 24 ≈ 803 clip, 각 ~30s mp4) + ffmpeg 프레임 추출 + OpenCV. 로컬 CPU. 네트워크 egress = clip 다운로드분(임시, 즉시 삭제).
- 저장: temp media 는 처리 후 즉시 삭제(피크 = 동시 처리 clip 수 × ~수 MB). 커밋 산출물은 JSON/CSV/MD 만.

---

## 7. decision 룰 (사전 명시)

| 결과 | 판정 |
|---|---|
| 자체 게이트(G-*) 전부 통과 + 데이터 게이트(D-*) 전부 통과 + artifact 완비 | **`SHADOW_READY_FOR_OWNER_AUDIT`** — BLIND-REVIEW.csv 를 owner 에게 넘긴다 |
| 데이터 게이트 미달(night<3 OR membership<100 OR ROI 불신뢰) | **`SHADOW_BLOCKED_INSUFFICIENT_DATA`** — 수치 조작 금지, 부족분 명시 |
| 자체 안전 게이트 위반(overlap>0 회복불가 OR 결정론 실패 OR mutation 감지 OR R2/VLM write 감지) | **`SHADOW_REJECTED_SAFETY`** |

**공통 정지점(Stop Point):** 어떤 판정에서도 main merge · DB/UI 구현 · production 배포는 하지 않는다. E-FALSEMERGE / E-PRESERVE 는 owner 감사 결과이므로 shadow 는 그 값을 **미검증(owner-pending)** 으로 남긴다.

---

## 8. 안전 경계 (금지 — 재확인)

production DB INSERT/UPDATE/DELETE/RPC-write · R2 PUT/DELETE/lifecycle · motion triage/GT/session/revision 변경 · 자동 label/hold/skip · GT 복사/전파 · Claude/Groq/local VLM 호출 · selector/VLM budget 변경 · 라벨링 웹 파일 수정 · migration 작성/적용 · LaunchAgent/worker/배포 변경 · 앱 활동시간 변경 · raw 영상/frame/signed URL/비밀값 commit · main merge / production 배포. **전부 금지.**
