# 계층 줌인 + ROI crop — frame-side 마지막 레버 확인 사살

> 급여 3종(eating_paste/drinking/eating_prey)이 "정지프레임 VLM 입력"으로 정말 못 풀리는지, 아직 측정 안 된
> 마지막 frame-side 레버(ROI-local 확대)로 확인한다. 결과로 "비-VLM이 유일한 길"을 확정하거나 뒤집는다.

**상태:** ✅ 완료 — **decision `close`** (2026-06-16, `experiments/roi-crop-center/`). frame-side 레버 종료: center ROI crop 56건 paired 순 0 · 4K급 10건 순 0 · 정확도 Δ +0.0%p. 정밀 crop/자동검출(Out) 미진행 — 레버가 죽어 불필요. drinking/paste/prey = RBA 비-VLM 유일.
**작성:** 2026-06-16
**연관 SOT:** `docs/AI-VIDEO-ANALYSIS-STRATEGY.md` (RBA 전략)

## 1. 목적

- **frame-side 마지막 미답 레버 확인.** V1(2026-06-15, `experiments/v1-drinking-targeted/`)이 입력표현 레버를 `close`했지만, 측정한 건 **"풀프레임 → 긴변 1080 다운스케일"** 입력의 천장이다. **"원본에서 관심영역만 잘라 1080을 전부 할당하는" ROI-local 확대는 측정한 적이 없다** — 학습노트 §6 표의 유일한 빈칸.
- **비-VLM 투자의 게이트.** RBA spec(`feature-rba-evidence-based-feeding-drinking.md` §4.5/§6.5)은 prey/drinking을 비-VLM(motion 시퀀스 + 메타 + ROI 체류)으로 보내기로 결정했고 C/D2(Opus도 모델불변 시각한계)가 뒷받침한다. 그 결정의 전제 = **"frame-side가 죽었다."** 이 PoC가 그 전제를 확인 사살한다. **실패 → RBA 비-VLM이 유일한 길로 확정**(학습노트 §6 표 마지막 칸을 ❌로 메움). **통과 → 싼 frame-side 레버가 반나절짜리 비-VLM 트랙보다 먼저.**
- **학습 목표:** ROI crop 파이프라인(원본 seek → crop → 재샘플) + 2축(시간밀도 ⊥ 공간해상도) 동시 공략 실측.

## 2. 스코프

### In (이번 스펙에서 한다)
- **수동 ROI crop 상한선 측정 (전수 paired)** — 타겟 클래스 **전수**(오답+정답)에 게코 입/머리 영역을 crop + 의심구간 촘촘 재샘플(원본 `-ss` seek) → VLM blind 측정. 자동검출 배제(아래 Out). 같은 클립의 적응형@1080 입력과 **paired** → **recovered**(오답→정답) + **broken**(정답→오답) 둘 다 측정.
- **타겟 = 급여/미세접촉 3종 전수**: `eating_paste`(17) + `drinking`(17) + `eating_prey`(22) = **56건** (manifest 187 중 GT 해당 전부). moving·shedding·hand_feeding·unseen 제외.
- **crop 규칙 = GT-무관** — "게코 머리/입 중심 정사각 crop"으로 고정(행동 라벨 모르고 **게코 위치만** 보고). 세 행동 다 입 근처에서 일어나 한 규칙 통일 + GT 누출 차단(§4-5). bbox 결정 방법(수동 클릭/자동검출/center)은 TEST-SHEET에서 확정.
- **2축 동시 공략**: ROI crop(공간해상도↑) AND 의심구간 촘촘 재샘플(시간밀도↑) — 한 입력에 둘 다.
- **채점 = 급여경계 게이트**(`_score_v40.py` 재사용 — drinking↔paste 무해·비급여 누출만 카운트) + prey 포함 조정. (메모리 `feeding-boundary-gate-design`)
- TEST-SHEET(pre-reg) → 측정 → REPORT(decision) → `experiments/INDEX.md` 등록. (`.claude/rules/research-testing.md`)

### Out (이번 스펙에서 **안 한다** — 단계 분리)
- **YOLO custom 입/혀/먹이 자동검출** — PoC `adopt` 이후로. OWLv2 47.5% 검출실패 교훈 + 검출 트랙은 반나절~. **수동 crop이 "레버가 있나"부터 격리**하고, 있을 때만 자동검출에 투자.
- **ROI-local motion 1차 트리거 자동화** — 자동화는 PoC `adopt` 시. (§4 "전체 설계"에 그림만 둠)
- **moving·shedding·hand_feeding·unseen 클래스** — ROI crop은 미세접촉/급여 클래스의 시각병목 가설이라 비대상. moving 등은 정지프레임에서 이미 90%대(입력병목 아님).
- **production 통합 / RBA 비-VLM evidence layer 구현** — 후자는 별도 spec(`feature-rba-...`). 이 PoC가 실패하면 그게 유일한 길이 된다.

### ✅ 스코프 확정 (사용자 2026-06-16)
- **타겟** = `eating_paste` + `drinking` + `eating_prey` **3종 전수 56건**. (사용자: "moving·unseen 빼고 급여 3종, 187 중 해당 전부")
- **전수 paired** — 오답만 보면 selection bias(순환논리), 전수라야 정답 broken까지 측정 가능.
- 남은 결정(TEST-SHEET): crop bbox 결정 방법(수동 클릭/자동검출/center) · 재샘플 간격 · 급여경계 게이트의 prey 처리.

## 3. 완료 조건

- [x] `experiments/roi-crop-center/TEST-SHEET.md` — 가설(H0/H1), `sample_list.json`(56건), 게이트 숫자 (pre-reg, 사후 변경 없음)
- [x] 56건 **center crop**(`scripts/_extract_frames_clip.py --roi-crop`) + blind 폴더 제작
- [x] VLM blind 측정 (Sonnet 4.6 v4.0, Agent 7+1명) + 결정론 채점(`scripts/_score_roi_crop.py`) — 적응형@1080 baseline과 paired
- [x] `REPORT.md` decision: **`close`** (frame-side 완전 종료 → 비-VLM 확정)
- [x] `experiments/INDEX.md` 등록

## 4. 설계 메모

### 4-1. 전체 파이프라인 (목표 설계 — 학습노트 §7 구체화)

```
1차: 적응형 frames@1080 으로 "여기 미세동작/drinking·prey 의심" 후보 구간 검출
2차: 그 구간 + 입·혀·먹이 영역만 crop 해서 확대
3차: crop 영역을 의심구간에서 촘촘히 재샘플  → 시간밀도↑ AND 공간해상도↑
```
- **1차 검출 (자동화 = Out):** 두 후보 — (a) VLM 1패스 "의심 구간" / (b) **ROI-local motion**(게코 입 주변 프레임차분). 학습노트 §7: 1차를 motion으로 잡으면 VLM 1차 detection 약점 우회, **단 global motion은 P2에서 미세행동 실패** → ROI-local로 좁혀야. ROI-local은 게코 입 위치를 알아야 함 → 게코 검출(2차)과 닭-달걀.
- **2차 ROI crop (자동화 = Out):** 게코 입/혀/먹이 영역 검출 → crop. YOLO custom(작은 게코 부위, 운영환경 IR/거리/가림 데이터로 학습 필수 — distribution mismatch 회피, OWLv2 교훈). 카메라 고정 그릇 ROI는 수동 좌표가 더 안정적일 수 있음(RBA spec 메모).
- **3차 재샘플:** crop 영역을 의심구간에서 간격↓로 재추출(원본 `-ss`).
- **이번 In = 1·2차를 사람이 수동으로** 대신해 3차 입력을 만들고 VLM에 먹인다. 자동화 전 "레버 유무"만 격리.

### 4-2. V1 `close`와의 축 구분 (이 spec의 정당성)

| | V1이 측정한 것 | ROI crop (이 spec) |
|---|---|---|
| 입력 | 풀프레임 → **긴변 1080 다운스케일** | 원본에서 입/혀/먹이만 잘라 **1080 전부 할당** |
| 대상 px | 4K에서 차지하던 px가 1080서 1/3~1/4로 축소 | 다운스케일 손실 0 |
| 상태 | **측정됨** (천장 확인 → close) | **미측정** (이 spec이 측정) |

- **단, V1 4건은 ROI crop으로도 무용 예상** — `b5637a1a`(원거리, 4K에도 게코 작음)·`685911a0`(흐림 극심)은 **원본 자체에 디테일이 없다**(V1 §1-3). 다운스케일 손실이 아니라 원본 정보 부재. → drinking은 대조군일 뿐 메인 타겟 아님.

### 4-3. 타겟이 급여 3종(paste/drinking/prey)인 이유

세 클래스 모두 **게코 입 근처의 작은 단서**(혀·물·먹이·paste)가 전체 프레임에서 묻혀 →moving 오답이 나는 미세접촉 버킷. ROI crop이 그 입 영역을 키우는 게 맞는 처방인지 가른다.
- **eating_prey** = "게코는 선명한데 먹이객체(귀뚜라미)가 작고 어두워 안 보임"(B1, `class-quality-sensitivity`). "**작음**"이 주원인이면 crop이 그걸 키움 = **이론적 스위트스팟**. RBA가 "객체검출 의존 금지(fuzzy 보너스만)"로 닫은 바로 그 클래스 → "정말 못 보나" 확인이 RBA 투자 결정에 직결.
- **drinking** = quality-sensitive(화질 좋으면 풀림, B1). V1이 풀프레임 다운스케일 천장은 `close`했으나 ROI-local 확대는 미측정. V1 누출 4건은 원본도 디테일 없어 무용 예상(§4-2)이나, **전수라 정답 보존(broken)** + 나머지 13건의 반응까지 본다.
- **eating_paste** = drinking과 동형 미세접촉(혀-표면). 급여경계 짝이라 paired 채점에 자연 포함.
- ⚠️ B1의 quality-invariant/sensitive 판정은 **전체 프레임 화질** 기준 — **ROI-local 확대는 미측정**이라 PoC가 가르는 지점.

### 4-4. 기존 구조와의 관계
- `scripts/_extract_frames_clip.py` 의 적응형 추출(원본 `-ss` 정확 seek + no-upscale)을 재사용. crop 단계만 추가하면 됨(`ffmpeg crop` 필터 또는 cv2 ROI 슬라이스).
- RBA spec과 **경쟁 아니라 게이트** — `close`면 RBA 비-VLM 유일 확정, `adopt`면 frame-side 먼저.

### 4-5. 리스크 / 미해결 질문
- **수동 crop selection bias (전수 56건이라 핵심)** — GT를 알고 crop 위치를 고르면 정답 누출(순환논리). → crop 규칙을 **GT-무관**으로: "게코 머리/입 중심 정사각 crop"만 적용(행동 라벨 모르고 **게코 위치만** — 게코 위치는 행동과 독립이라 GT 누출 X). 클립당 게코 머리 1 bbox로 전 프레임 crop, 게코가 프레임 밖으로 나가는 클립만 조정. bbox 자동화(pretrained 검출)는 OWLv2 47.5% 교훈상 PoC에선 수동/center가 더 확실. (메모리 `selection-bias-error-only-tagging`)
- **"어두워서 안 보임"은 crop으로 안 풀림**(밝기 ≠ 크기). 실패 시 "crop 무용"인지 "어두움 탓"인지 분해 필요 — REPORT에서 케이스별 원인 태깅.
- **소표본**(prey 오답 ~9) → 방향 판정용, 정량 승격 금지(V1과 동일 한계).
- **모델한계 미분리** — Sonnet으로 안 풀려도 같은 클래스 VLM 한계 가능성 잔존. C/D2가 Opus까지 봤으니 보조 근거.

## 5. 학습 노트

- **ROI crop** = 객체 영역만 잘라 입력 = 공간해상도 국소 증폭. ≈ object detection의 2-stage 파이프라인(region proposal → crop → classify)의 1단계 수동판. (TS 비유: 큰 이미지를 통째 `<img>`로 주는 대신 `canvas.drawImage(src, sx,sy,sw,sh, 0,0,W,H)`로 관심영역만 확대해 넘기는 것)
- **다운스케일 vs crop** — 같은 1080이라도 "전체를 줄임"과 "일부를 다 씀"은 대상 px 수가 3~4배 차이. V1이 못 본 축이 이것.
- **2축 직교** — 시간밀도(재샘플 간격) ⊥ 공간해상도(crop). 기존 트릭은 한 축씩만 건드려 막혔다(§6 표). ROI crop+촘촘 재샘플이 둘 다 동시.

## 6. 참고

- V1 입력레버 close: `experiments/v1-drinking-targeted/REPORT.md`
- C/D2 prey 모델불변 시각한계: `experiments/cascade-opus-sim/REPORT.md`
- RBA 비-VLM (게이트 상대): `specs/feature-rba-evidence-based-feeding-drinking.md` §4.5 / §6.5
- 학습노트(설계 골격): `docs/learning/video-classification-learning.md` §5~§7
- 메모리: `class-quality-sensitivity` · `v1-drinking-close` · `input-resolution-micro-contact` · `yolo-evidence-layer-status`
- 연구 테스트 절차: `.claude/rules/research-testing.md`
