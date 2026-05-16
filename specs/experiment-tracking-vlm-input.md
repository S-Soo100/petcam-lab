# Tracking 파이프라인으로 VLM 입력 정규화 PoC

> VLM 76~85% 정확도 천장이 "도마뱀이 frame 어디 있고 배경이 너무 많아서" 인가, 아니면 "행동 자체가 시각적으로 풀리지 않아서" 인가를 분리 검증한다.

**상태:** 🗑️ 폐기 (2026-05-14, 결론: 시각 한계 가설 (A) 강화)
**작성:** 2026-05-14
**연관 SOT:** (해당 없음 — 내부 실험. 결과에 따라 `tera-ai-product-master/docs/specs/petcam-backend-dev.md` 에 행동 분류 파이프라인 반영 검토)

## 1. 목적

**VLM 정확도 천장의 정체를 분리한다.**

현재 가설은 두 갈래로 충돌:
- (A) "시각 정보 한계" — 픽셀에 정답 신호 없음. prompt/모델 교체로 못 풂. (메모리 [[feedback_vlm_visual_information_limit]])
- (B) "사전학습 모델의 분포 편향" — VLM이 학습한 도마뱀 영상은 자연 다큐가 다수. 케이지 안의 정적·근접 행동은 distribution 밖.

(B)가 사실이라면 **입력을 정규화** (도마뱀 중심 crop + 일관된 구도) 했을 때 정확도가 올라야 한다. 안 오르면 (A) 결론 강화 → 다음 단계는 UX 매핑·HITL·video classifier fine-tune 으로 명확히 분기.

**Codex + Gemini 교차 자문** (2026-05-14, 라운드 2회) 결과 합의된 우선순위: `tracking > segmentation > keypoint`. 이 PoC는 그 중 1순위 검증.

## 2. 스코프

### In (이번 스펙에서 한다)

- **Step 0 — 클립 선정**: production DB 159건 중 30~50건을 tracker 품질 게이트용으로 수동 선정 (IR/주간, occlusion 있음/없음 골고루).
- **Step 1 — CSRT tracking 스크립트**: `scripts/tracking_csrt_poc.py`. OpenCV `cv2.TrackerCSRT`. 첫 프레임 bbox는 SAM 2 한 번 호출로 자동 추출. 클립당 bbox 시계열 JSON 출력.
- **Step 1.5 — Tracker 품질 게이트**: 수동 검수. **median IoU ≥ 0.6 AND catastrophic drift ≤ 20% AND "Loss 0회" 클립 비율** 측정. 게이트 미통과 시 SAM 2 video predictor 로 교체 후 재측정.
- **Step 2 — A/B/C VLM 재평가**: 159건 전체. 동일 모델/prompt (Gemini 2.5 Flash, v3.5).
  - **A**: raw frame (기존 동치, baseline)
  - **B**: raw + tracked crop (배경 마진 20~30% 포함) 둘 다 입력
  - **C**: raw + crop + bbox trajectory 요약 텍스트 (속도/방향/정지구간)
  - 결과: 전체 정확도 + 클래스별 변화 + confused pair 변화 + IR/주간 분리.
- **Step 3 — Motion feature 미니 실험**: `scripts/tracking_motion_features_poc.py`. bbox 시계열 → 속도·가속도·방향 feature 추출 → 간단 rule 또는 LightGBM → `moving vs resting` binary F1 측정.
- **종합 결론 메모**: 4가지 분기 매트릭스 (아래 "설계 메모") 중 어느 경로로 갈지 결정 기록.

### Out (이번 스펙에서 **안 한다**)

- **SAM 2 video predictor 채택** — 게이트 실패 시 Step 1 만 교체하고 동일 절차 재실행. 별도 production 통합은 다음 스펙.
- **CoTracker3 / ByteTrack** — 시간 대비 ROI 낮음 (PoC 단계 아님).
- **DeepLabCut keypoint** — confused pair 가 미세 행동에 집중되면 별도 스펙.
- **9 클래스 전체 fine-tune (VideoMAE / TimeSformer 등)** — Step 2 결과 보고 별도 스펙.
- **Production 워커 (`backend/vlm/`) 에 tracker 통합** — PoC 통과 후 별도 스펙.
- **UI / Flutter 변경** — 분류 결과 표시 레이어는 [[feature-vlm-feeding-merge-ux]] 가 담당.
- **데이터 수집 확장 / 새 라벨링** — 현재 159건으로만.

### 변경 시 합의

스코프 흔들리면 이 섹션 수정 + 사유 기록. 특히 "Out → In" 이동은 사용자 확인 필요.

## 3. 완료 조건

체크리스트가 곧 진행 상태.

- [x] **Step 0** (2026-05-14): 게이트용 40건 stratified sample 완료 — `experiments/tracking-poc/clips-gate.txt`. stratify 축은 `action_group × motion_intensity` 2축 (started_at 이 업로드 시각이라 시간대 stratify 제거). 분포: active 16 / feeding 12 / physiological 10 / static 2. unseen 그룹 제외
- [x] **Step 1** (2026-05-14): `scripts/tracking_csrt_poc.py` 작성. OWLv2 zero-shot detect → CSRT 트래킹. 40건 batch 결과: ok 21 / no_detection 10 / no_valid_bbox 9. trajectories JSON + init/last jpg 출력
- [x] **Step 1.5** (2026-05-14): `experiments/tracking-poc/tracker-quality.md` — proxy 메트릭 + 시각 모자이크 + 정성 검수. **게이트 FAIL** (drift 28.6% > 20%, 검출률 52.5% < 80%). 4분기 매트릭스 (α) 분기. 단 71% 클립이 사용가능 — Step 2 진행 가치 있다는 결론. 다음 액션 옵션 1~4 사용자 결정 대기
- [~] **Step 2**: ~~A/B/C 평가~~ — **취소** (2026-05-14). Step 1.5 게이트 fail + 검출 단계 47.5% 실패로 입력 정규화 가설 자체 약화. 사용자 결정: PoC 중단
- [~] **Step 3**: ~~motion feature 미니 실험~~ — **취소** (2026-05-14). 동일 사유
- [x] **종합 결론** (2026-05-14): 4분기 매트릭스 (α) Tracker drift 많음. 검출+트래킹 양쪽 보틀넥 → 시각 한계 가설 (A) 강화. 다음 액션: tracking/crop 정규화 폐기. 별도 전략 탐색 진행

## 4. 설계 메모

### 선택한 방법

**CSRT (OpenCV `cv2.TrackerCSRT`) Day-1 baseline**.

**근거**:
- OpenCV 내장. uv add 추가 의존성 0 (이미 `opencv-python` 있음).
- 30~50줄 스크립트로 첫 결과 확인 가능. PoC 정신에 부합.
- 단일 객체·고정 카메라·bbox init 기반 = CSRT 가정과 정확히 일치.
- 게이트 실패해도 "왜 실패했는가"가 진짜 인사이트 — SAM 2 로 바로 가면 비용 큰 모델이 왜 필요한지 근거가 사라짐.

### 고려했던 대안

| 후보 | 강점 | 안 고른 이유 |
|------|------|-------------|
| **SAM 2 video predictor** | occlusion 재획득 강력. 마스크까지 얻음 | PoC Day-1로는 비용 큼. CSRT 실패 시 fallback 으로 활용 |
| **CoTracker3 (point trajectory)** | 머리·몸통·꼬리 sparse motion feature | PoC 복잡도 증가. keypoint 단계로 미룸 |
| **ByteTrack** | multi-object SOTA | detector 필요. 단일 개체 PoC 엔 과함 |
| **MOG2 background subtraction** | 단독으로도 moving 감지 | "정지 시 배경 흡수" 약점이 게코 케이지에 정통으로 부딪힘. cheap proposal generator 로만 보조 가능 |

### 기존 구조와의 관계

- 평가셋 = **production DB `behavior_logs(source='human')` + has_motion + r2_key = 159건** (메모리 [[project_vlm_regression_script]] 참고). web/eval/v35 (8 클래스) 와 다름.
- 영상 다운로드 = `backend.vlm.gemini_client.download_clip_bytes` 재사용.
- 추론 = `backend.vlm.gemini_client.classify_clip` 재사용. **prompt SOT 는 `web/src/lib/prompts.ts` v3.5 그대로 — A/B/C 입력만 다름**.
- 결과 저장 = `experiments/tracking-poc/` 신설 (gitignore 추가). `scripts/` 는 실행 스크립트, `experiments/` 는 산출물.

### 리스크 / 미해결 질문

1. **A/B/C 의 "B" 와 "C" 가 멀티모달 입력으로 Gemini 에 들어갈 때 동작**: Gemini 2.5 Flash 가 영상 + 텍스트 + 크롭 이미지 동시 입력을 지원하는지 확인 필요. 안 되면 frame sample 형태로 재구성.
2. **첫 프레임 bbox 자동화 (SAM 2 1회 호출)**: 모든 클립이 첫 프레임에서 도마뱀 보이는 건 아님 (hiding 케이스). 안 보이면 fallback 룰 필요 — frame N=15 까지 sliding 또는 수동 클릭.
3. **159건 재평가 비용**: A/B/C × 159 = 약 480 API call. Gemini 2.5 Flash 가격 ($0.30/$2.50 per M tokens) 으로 예상 비용 약 $2~5. 감당 가능.
4. **재현성**: temperature 0.1 + JSON 강제는 워커 회귀 스크립트와 동일. seed 노이즈 1~2% 는 감수.

### 4가지 분기 매트릭스 (Codex 라운드 2 결과)

Step 2 결과에 따라 다음 액션이 분기됨. 종합 결론은 이 표 중 어디로 떨어졌는지 기록:

| Step 2 결과 | 해석 | 다음 액션 |
|------------|------|----------|
| **(α) Tracker drift 많음 (게이트 fail)** | CSRT 한계 | SAM 2 video 로 교체 후 Step 1.5 재측정 |
| **(β) Tracker OK, B/C 전체 정확도 무변화** | 입력 정규화로도 안 풀림 = 시각 한계 가설 (A) 강화 | Crop 폐기. video classifier fine-tune 또는 HITL 정공법 |
| **(γ) moving/resting 만 개선** | bbox motion feature 가 보조 신호로 가치 있음 | Crop 도입 X. motion feature 를 production 보조 시그널로 |
| **(δ) eating/tongue/drinking confused pair 개선** | 분포 편향 가설 (B) 강화. crop 입력 가치 있음 | Production 워커에 tracking + crop 통합 (별도 스펙) |

### 🗑️ 종합 결론 (2026-05-14)

**(α) Tracker drift 많음 — 게이트 FAIL 분기** 로 떨어짐.

**근거:**
1. 검출 단계 보틀넥 — OWLv2 가 40건 중 19건 (47.5%) 에서 게코 검출 실패 또는 false positive. 트래커 교체로 해결 안 됨 (SAM 2 도 first frame prompt 필요).
2. 트래킹 단계 보틀넥 — 검출 통과 21건 중 6건 (28.6%) 가 catastrophic drift (게이트 임계 20% 초과). bd96c769 drift 0.55, c928b6ff inflate 4배, 0e7bccb0 collapse 등 시각 검수 일치.
3. 결과적으로 40건 → 사용 가능 트래킹 15건 (37.5%) — A/B/C 평가의 통계적 유의성 확보 어려움.

**메타 교훈:**
- Codex+Gemini 라운드 2 자문이 "tracking > segmentation > keypoint" 로 우선순위 줬으나, 그 자문은 **검출이 이미 풀려 있다는 가정** 위에 있었음. 우리 데이터(IR/야간/원거리/은신)에서는 검출이 더 큰 문제. 외부 AI 자문도 우리 데이터 분포는 모름.
- "PoC Day-1 baseline" 명목으로 CSRT 도입했고, 게이트 fail 시 SAM 2 fallback 도 검출 한계 때문에 무의미. **Day-1 결정 자체가 데이터를 모른 채 내려진 결정**.
- 시각 한계 가설 (A) 가 6번째 검증 — production v3.5 락인 + dish-postfilter 실패 + 6방향 prompt 변경 모두 회귀 + 본 PoC 폐기.

**다음 액션:** Tracking/Crop 경로 폐기. 시각 픽셀 외부에서 신호 찾는 전략으로 회귀. 후보는 별도 검토.

## 5. 학습 노트

### Object Tracking vs Detection

- **Detection** (`f(frame) → bbox`): 단일 frame, stateless. "이 사진에 도마뱀 어디 있어?"
- **Tracking** (`tracker.update(frame) → bbox`): 시퀀스, stateful. "1초 전 그 도마뱀 지금 어디로 갔어?"
- Node 비유: detection = pure function / tracking = closure 또는 클래스 인스턴스 (내부 history 보유).

### IoU (Intersection over Union)

두 bbox 가 얼마나 겹치는지 0~1 점수. `IoU = 교집합 면적 / 합집합 면적`. tracking 품질의 표준 지표.
- IoU ≥ 0.5: 일반적 "맞다" 임계
- IoU ≥ 0.6: 본 PoC 게이트 (단일 개체·고정 카메라라 더 엄격)
- IoU = 1.0: 완벽 일치

### Catastrophic Drift

tracker 가 객체를 놓치고 **다른 영역으로 잘못 따라가는 현상**. 게코 케이지에서는 잎/나무껍질이 흔한 drift 대상 (텍스처 유사 + 위장).
- 측정: "tracker 결과 vs 수동 GT" 의 IoU 가 임계 (예: 0.3) 미만으로 연속 N frame 이상.
- 본 PoC 게이트: 전체 클립의 ≤ 20%.

### CSRT vs SAM 2 vs CoTracker3 차이

- **CSRT**: correlation filter 기반 (전통적). bbox 만 출력. 빠르고 가볍지만 occlusion 약함.
- **SAM 2**: transformer 기반 promptable segmentation. bbox/point/mask prompt 가능. memory mechanism 으로 occlusion 후 재획득 가능. 마스크까지 얻음.
- **CoTracker3**: point trajectory 전용. "머리 끝", "꼬리 베이스" 같은 sparse keypoint 의 frame-wise 위치를 따라감. keypoint 분석에 직접 활용 가능.

### A/B/C 입력 정규화 vs 문맥 보존 트레이드오프

타이트 crop → 도마뱀 확대 BUT 먹이그릇·물그릇·은신처 같은 **행동 분류에 필요한 주변 문맥** 손실.
배경 마진 20~30% 가 trade-off 의 일반적 절충 (Codex + Gemini 둘 다 합의).

## 6. 참고

- Codex / Gemini 교차 자문 라운드 2 (2026-05-14 대화)
- 메모리: [[project_vlm_v35_baseline_lock]] · [[feedback_vlm_visual_information_limit]] · [[feedback_vlm_ux_merge_validation]] · [[project_vlm_regression_script]]
- 워커 회귀 스크립트: `scripts/eval_vlm_worker_regression.py`
- portable eval: `vlm-classifier-portable/eval/` (8 클래스라 본 PoC 와는 다름)
- OpenCV CSRT 공식 문서: https://docs.opencv.org/4.x/d2/da2/classcv_1_1TrackerCSRT.html
- Meta SAM 2: https://ai.meta.com/sam2/
- 연관 스펙: [[feature-poc-vlm-web]] (v3.5 락인 결정) · [[feature-vlm-feeding-merge-ux]] (UX 매핑 정공법)
