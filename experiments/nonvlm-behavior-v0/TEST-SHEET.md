# nonvlm-behavior-v0 테스트 시험지 (Test Sheet) — pre-registration

> 규칙: [`.claude/rules/research-testing.md`](../../.claude/rules/research-testing.md). **실행 전 고정 — 합격 기준 사후 변경 금지.**
> 무결성 6단계 참조: [`specs/experiment-claude-montage-v2.md`](../../specs/experiment-claude-montage-v2.md) §4-3a (이 실험은 LLM 추론이 없어 ②·④를 결정론 실행·discordant review로 대체, §9)

**실험 ID:** nonvlm-behavior-v0 · **phase:** E1 · **작성일:** 2026-09-09 · **상태:** 🔒 고정(실행대기) — owner 승인 2026-09-10 ("시작해", §7 숫자·§5 룰 v0 그대로). 이후 §5·§7 변경 금지
**실행 전 정정 (2026-09-10, 결과 확인 전):** R4 조건을 `F9 not_visible ≥ 0.9` → `unknown + not_visible ≥ 0.9` 로 정정. 사유: v1 엔진 `aggregate_states` 는 미검출 프레임을 `not_visible` 이 아니라 `unknown` 으로 내므로 원문 그대로면 R4 가 절대 발화하지 않는다(코드 실독). 게이트 숫자·다른 룰 변경 없음.
**결정 게이트:** [`docs/decision-gate.md`](../../docs/decision-gate.md) 2026-09-09 레코드 · **도메인 SOT:** tera-ai-product-master `docs/specs/petcam-ai-pipeline.md` 헤더 노트(비-VLM 판정 범위는 실험으로만) · `petcam-behavior-shedding.md` §6-3

---

## 0. 배경 (왜 이 테스트인가)

- owner 질문(2026-09-09): **"VLM 없이 행동을 어느 정도 알아낼 수 있나"** — 문헌·해외 사례 유추로 확정하지 않고 실험으로만 판정한다는 지시.
- 이미 있는 것 두 개로 **새 VLM 호출 0회**에 답한다: ① v4.0 Sonnet의 185건 blind 예측(`experiments/v40-regression/raw/`), ② production과 동일 계약의 GME v2.6(10fps, `gme-motion-v1`)을 로컬에서 돌린 궤적 artifact.
- 예전 local router(2026-07, `invalid-for-adoption`)와의 차이를 명시한다: 그건 **OpenCV metadata JSON만, 영상 0, 라우팅 목적, 사후 threshold 튜닝**이었다. 이 실험은 **픽셀에서 나온 detector·tracker 출력**을 입력으로 **행동 evidence** 를 묻고, 임계값은 이 문서에서 사전 고정한다. 라우팅·skip·production 활성화는 이 실험이 결정하지 않는다.

## 1. 가설

- **H1 (대립):** GME 궤적·시간 특징만으로 사람 GT 기준 `moving`·`hand_feeding`은 높은 recall로 판정되고, `drinking+eating_paste`(급여 묶음)는 VLM v4.0 대비 −10%p 이내로 회수된다. 또한 VLM과 궤적은 **서로 다른 클립에서 틀려** 결합 시 급여경계 정확도가 오른다.
- **H0 (귀무):** 궤적 특징은 moving/hand_feeding조차 안정적으로 못 가르거나, 급여 묶음 회수가 VLM 대비 −10%p를 넘게 떨어지며, VLM과 오답이 겹쳐 결합 이득이 없다.

## 2. Sample list (고정)

| 항목 | 값 |
|---|---|
| 전체 측정 | **197건** = `/Users/baek/petcam-lab/storage/dataset-203/manifest.csv` 전체 (gitignored 로컬 mp4/mov 197/197 존재 확인 2026-09-09) |
| **paired 비교** | **185건 동결셋** = `source ∉ {eval-0615, eval-0617}`. GT 분포 moving 72 / shedding 29 / hand_feeding 28 / eating_prey 22 / eating_paste 17 / drinking 15 / unseen 2 (v40-regression 시험지와 동일) |
| eval-0615·0617 12건 | 197 측정에만 포함, paired 제외 (v4.0 예측 없음) |
| 재현 | manifest.csv가 곧 sample list. [`sample_list.json`](sample_list.json) = manifest 197행의 `filename·clip_id·gt·source` 스냅샷 (2026-09-10 생성, 실행 전 고정) |
| v4.0 예측 조인 키 | `experiments/v40-regression/frames/sample-NN/meta.json`의 `src`(파일명) ↔ manifest `filename`. 조인 185/185 일치를 채점 전 **게이트로 검증**(불일치 1건이라도 있으면 중단) |
| 그룹 CV 단위 | manifest `source` 5그룹(cam-motion 71 / uploaded 70 / eval-0608 44 / eval-0615 2 / eval-0617 10). DB read-only로 camera_id를 붙일 수 있으면 camera 단위로 상향(사전 결정, 결과 무관) |

## 3. Arm / 입력 / 계약

| Arm | 내용 | 새 호출 |
|---|---|---|
| **A (VLM 기록)** | v4.0 Sonnet 적응형 frames@1080 blind 예측, 2026-06-13 배치 그대로. 재실행 없음 | 0 |
| **B (궤적)** | GME v2.6 로컬 run artifact(`intervals`, `track_points` = timestamp·bbox·confidence·provenance·state) → §4 특징 → §5 룰 v0 / 분류기 | 0 (로컬 검출만) |
| **C (결합, 선택)** | A 예측 + B 특징의 사전 고정 결합 룰(§5-3). 오프라인 | 0 |

**B의 GME 실행 계약 — production과 동일하게 핀 (하나라도 다르면 run 무효):**

| 항목 | 값 | 출처 |
|---|---|---|
| detector backend / model | `yolo26n` / `v2.6-warm-start-s28` | nightly `reporter/config.py` 기본값, `install-launchd-gme.sh` 강제값 |
| checkpoint | `/Users/baek/private-rba/yolo26n-v26-recent-dense/attempt-20260826-owner-v1/runs-v26-comparison-v2/warm-start-s28/weights/best.pt`, SHA-256 `a00e5a7a1e1f9197accb036339a38a7c821f03c8ab79611ebce89e5cde59b513` | v2.6 production normalization plan |
| detector freeze SHA / identity | freeze `8f8e02be…b343a0` · identity는 실행 시 `detector_identity(detector)` 산출값이 **production env `GME_ACTIVE_DETECTOR_IDENTITY`(현재 install 스크립트 강제값 `deccfc83…bdb899`)와 일치**해야 함. 불일치 시 중단 | install-launchd-gme.sh · highlight 런북 §6 |
| inference | raw conf 0.001 · score ≥0.15 · imgsz 960 · model NMS 0.70 · post NMS 0.55 · max_det 50 · device mps | config.py |
| 시간축 | analysis 10fps 절대시간 grid · anchor 0.1s(매 분석 프레임 검출) · temporal gate 5중 3 | config.py · gme_temporal.py |
| algorithm | `gme-motion-v1` (느린 움직임 승격 포함), engine schema `gme-shadow-v1` | gme_engine.py |
| 코드 핀 | gecko-vision-gate `codex/yolo-v26-production-normalization-gate` **`246b23c`**(gme-motion-v1 포함). Mac mini runtime HEAD와 같은지 실행 전 확인 | 2026-09-09 실독 |
| 실행 경로 | 연구 러너 `scripts/nonvlm_behavior_v0/run_gme_local.py`(신규)가 `build_yolo_detector` + `analyze_clip` + `serialize_artifacts`를 위 값으로 호출. **DB·R2 write 0**, artifact는 `/Users/baek/petcam-lab/storage/nonvlm-behavior-v0/gme/{filename}.json.gz`(gitignored) + run manifest(계약값·SHA·gate commit) 는 이 폴더에 커밋 | — |
| 실행 환경 | MacBook, `nice -n 10`(YOLO 학습 2개 상시 공존, 메모리 `codex-sessions-concurrent-worktrees`) | — |

## 4. 특징 정의 (B, 사전 고정)

모두 GME artifact에서 **결정론적으로** 계산. 단위: 체장(bbox 대각 평균) 정규화, 시간 초.

| id | 특징 | 정의 |
|---|---|---|
| F1 | `moving_ratio` | moving 초 / visible 초 (visible=0이면 결측) |
| F2 | `longest_static_sec` | 게코 보이는 상태에서 static이 끊기지 않고 이어진 최장 구간 |
| F3 | `longest_moving_sec` | moving 최장 연속 구간 |
| F4 | `n_moving_bouts` | moving 구간 개수 |
| F5 | `disp_mean` / `disp_max` | 같은 track 인접 포인트 중심 변위(체장 단위)의 평균·최대 |
| F6 | `aspect_osc` | static 구간 내 bbox w/h 의 표준편차 (몸 비틀기·구르기 proxy) |
| F7 | `global_change_frames` / `first_global_change_sec` | `camera_motion` 판정 프레임 수와 첫 발생 시각 (손·도구 침입 proxy) |
| F8 | `head_micro` | **신규 채널.** F2 구간(≥3s)에서 머리 끝 영역의 프레임 간 평균 절대차 − 몸통 영역 평균 절대차, 배경 절대차로 나눔. 머리 끝 = 직전 이동 벡터의 앞쪽 bbox 30% (이동 이력 없으면 양끝 max). 원본 프레임을 다시 읽되 GME와 같은 10fps grid만 사용 |
| F9 | `unknown_ratio` / `not_visible_ratio` | 판단불가·미관측 비율 |
| F10 | `max_geckos` | 동시 검출 최대 개체 수 |
| F11 | `bbox_area_jump` | 인접 프레임 bbox 면적비 최대 (손 접근·들어올림 proxy) |

특징 추출 코드는 GT를 읽지 않는다(입력 = artifact + 원본 프레임만).

## 5. 판정기 (사전 고정)

### 5-1. 룰 v0 — 임계값을 여기서 고정, 결과 본 뒤 변경 금지

순서대로 첫 매치.

| 순서 | 조건 | 출력 |
|---|---|---|
| R1 | F7 ≥ 5프레임 **AND** F11 ≥ 2.0 | `hand_feeding` |
| R2 | F2 ≥ 8s **AND** F8 ≥ 2.0 (머리 끝 차이가 배경의 2배 이상) | `feeding`(급여 묶음) |
| R3 | F6 ≥ 0.25 **AND** F4 ≥ 4 **AND** F1 ≤ 0.5 | `shedding` |
| R4 | F9 (unknown + not_visible) ≥ 0.9 — *실행 전 정정, 헤더 참조* | `unseen` |
| R5 | 그 외 | `moving` |

`eating_prey`는 룰 v0에 없다(먹이 객체 없이는 판정 불가, 2026-06-16 판정). `drinking` vs `eating_paste`는 그릇 없이는 못 갈라 **급여 묶음으로만** 출력한다(2026-05 UX 매핑 결정과 동일).

### 5-2. 분류기 arm — 상한 확인용

- 입력 F1~F11, 모델 = 로지스틱 회귀(class_weight=balanced) 1개 고정. 하이퍼파라미터 탐색 없음.
- 평가 = **그룹 leave-one-out CV**(§2 그룹). 학습 fold의 GT만 사용, 테스트 fold 예측만 집계.
- 목적: 룰 v0가 놓친 분리 가능성의 상한을 보는 것. **adopt 대상이 아니다**(운영엔 룰만).

### 5-3. 결합 룰 C — 급여경계 수준에서만

- 기본 = A.
- C1: A ∈ {drinking, eating_paste} **AND** F2 < 3s(정지 구간 없음) → `moving`으로 강등.
- C2: A = moving **AND** R2 매치 → `feeding`으로 승격.
- C3: A ≠ hand_feeding **AND** R1 매치 → `hand_feeding`.
- 그 외 A 유지. 7-class raw는 C에서 보고하지 않고 **급여경계·hand_feeding·moving 수준**에서만 채점한다.

## 6. 측정 지표

1. **B raw 정확도** — 급여 묶음을 하나의 클래스로 본 6-class(moving/hand_feeding/feeding/shedding/eating_prey/unseen) 정확도. 정직 보고용.
2. **급여경계 정확도** — `scripts/_score_v40.py`의 `boundary_correct` 로직 재사용(급여 GT는 급여이기만 하면 정답, 비급여는 정확 일치). A·B·C 각각.
3. **클래스별 recall·precision + 혼동행렬** — A·B.
4. **급여 묶음 recall** — GT ∈ {drinking, eating_paste} 32건 중 급여로 판정된 수. A(급여경계 기준)·B·C.
5. **급여 과탐** — 비급여 GT 153건 중 급여로 판정된 수. A·B·C.
6. **A↔B complementarity** — 185 클립을 (A정답,B정답)/(A정답,B오답)/(A오답,B정답)/(둘 다 오답) 4칸으로. 급여경계 기준.
7. **C paired vs A** — 급여경계 기준 recovered(A오답→C정답) / broken(A정답→C오답). 급여 내부 이동은 무해로 제외.
8. **GME run 품질** — 197건 status ok 비율, unknown_ratio 분포, 계약 핀 일치 여부. 이건 결과가 아니라 **실행 유효성 게이트**.

## 7. 합격 기준 (숫자 — owner 승인 시 동결)

| 게이트 | 기준 | 근거 |
|---|---|---|
| G0 실행 유효성 | GME 197건 중 `ok` ≥ 95% **AND** 계약 핀 전부 일치 **AND** v4.0 조인 185/185 | 미달 시 채점하지 않고 원인 보고 |
| G-B1 | B `moving` recall ≥ **0.90** (72건) | Tier 1급 클래스는 궤적으로 당연히 돼야 함 |
| G-B2 | B `hand_feeding` recall ≥ **0.80** (28건) | 손 침입은 전역 변화로 잡혀야 함 |
| G-B3 | B 급여 묶음 recall ≥ **A 급여 묶음 recall − 10%p** (32건) | "VLM 없이 어느 정도"의 핵심 숫자 |
| G-B4 | B 급여 과탐 ≤ **10%** of 비급여 153건 (≤15건) | 정지만으로 급여를 남발하지 않는지 |
| G-C | C 급여경계 정확도 ≥ A **AND** recovered ≥ broken | 결합 이득 |
| 보고만 | shedding·eating_prey·unseen 클래스별 수치, 분류기 arm CV 결과 | 게이트 아님. shedding은 행위 클립 한정·모프 오탐 이력 |

## 8. 예상 비용 / 자원

- API 비용 **$0** (A 기록 재사용, B·C 로컬).
- 로컬 검출: 197클립 × 약 60s × 10fps ≈ **12만 프레임** YOLO26n@960 MPS. MacBook 추정 1~2시간(실측 후 기록). F8은 원본 재디코딩 1회 추가.
- 새 코드: 러너 1개, 특징 추출 1개, 채점 1개(`_score_v40.py` 로직 재사용), 테스트 포함. `scripts/nonvlm_behavior_v0/`.

## 9. Decision 룰 (사전)

| label | 조건 |
|---|---|
| **adopt (B = 궤적 evidence 층)** | G0 **AND** G-B1~B4 전부 통과. 의미: moving·hand_feeding·급여 묶음은 궤적만으로 evidence 층 후보. **production 활성화·라우팅·skip은 별도 spec+게이트** |
| **hold (Tier 2 미해결)** | G0·G-B1·G-B2 통과, G-B3 또는 G-B4 미달. 궤적은 Tier 1급만 되고 급여는 안 된다는 뜻 → 어느 특징이 왜 못 가르는지 진단 보고, 다음 레버(keypoint·장면 사건) 결정 |
| **reject** | G0 실패, 또는 G-B1·G-B2 미달. 궤적 자체가 클립 수준 행동을 못 읽음 → GME run 품질부터 재검 |
| **C 별도** | B adopt **AND** G-C 통과일 때만 "결합 후보" 기록. 아니면 complementarity 표만 보고 |
| 해석 가드 | drinking 15·eating_paste 17이라 클래스 단독 수치는 진단용. 결론은 급여 **묶음** 32건과 moving·hand_feeding으로만. 모션 클립이라 탈피 타임라인·수면지점·일주기(Tier 1 측정)는 **이 실험 범위 밖**(RAP M2·GME 4단계). 임계값·룰·결합 룰은 결과 확인 후 변경 금지 — 바꾸려면 v1 시험지 |

## 무결성 단계 매핑

`① pre-reg(이 문서)` → `② 결정론 실행(GME 로컬 run + 특징 추출, GT 미접근)` → `③ deterministic scorer(급여경계 + 조인 검증)` → `④ discordant review: A↔B 불일치 클립 중 최대 20건 owner 육안(라벨 정정 후보 발굴, 게이트 수치엔 미반영)` → `⑤ REPORT.md` → `⑥ INDEX 등록`

---
**다음:** owner가 §7 숫자와 §5 룰 v0 임계값을 승인하면 상태를 🔒로 바꾸고, 러너·특징 추출·채점 코드를 TDD로 작성한 뒤 실행한다. **실행 직전 재확인 필수.**
