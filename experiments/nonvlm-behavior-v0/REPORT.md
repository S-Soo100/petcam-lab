# nonvlm-behavior-v0 테스트 보고서 (Report)

> 규칙: [`.claude/rules/research-testing.md`](../../.claude/rules/research-testing.md).

**실험 ID:** nonvlm-behavior-v0 · **phase:** E1 · **날짜:** 2026-09-10 · **상태:** ✅ 실행 완료 · **decision: `reject`** (B 궤적 룰 v0) · C 결합은 기록만
**시험지:** [`TEST-SHEET.md`](TEST-SHEET.md) (🔒 2026-09-10) · **결정 게이트:** `docs/decision-gate.md` 2026-09-09 nonvlm-behavior-v0 · **결과 파일:** [`results/results.md`](results/results.md) · [`results/results.json`](results/results.json) · [`results/features.csv`](results/features.csv) · [`results/predictions_rule_v0.csv`](results/predictions_rule_v0.csv) · [`results/join_gate.json`](results/join_gate.json) · 사후 진단 [`results/diagnostics.txt`](results/diagnostics.txt)

## 1. 무엇을 측정했나 (시험지 요약)

| 항목 | 값 |
|---|---|
| 질문 | VLM 없이 GME 궤적·시간 특징만으로 사람 GT 를 어디까지 맞히나 |
| 표본 | 197 전체 측정, paired 는 185 동결셋(v4.0 Sonnet 예측 존재) |
| Arm A | v4.0 Sonnet 저장 예측 (2026-06-13 blind 배치, 재호출 0) |
| Arm B | GME v2.6 로컬 run(production 계약 핀) → 특징 F1~F11 → 룰 v0 (임계값 사전 고정) |
| Arm C | A + B 특징 결합 룰(§5-3) |
| 게이트 | G0 실행 유효성 · G-B1 moving recall ≥0.90 · G-B2 hand_feeding ≥0.80 · G-B3 급여 묶음 recall ≥ A−10%p · G-B4 급여 과탐 ≤10% · G-C |
| decision 룰 | G-B1·B2 미달 → reject / B3·B4 미달 → hold / 전부 통과 → adopt |

## 2. 결과

**GME 로컬 run (G0):** 197/197 `ok` (smoke 3 + 본 run 194), v4.0 조인 185/185, 계약 핀 전부 일치(detector identity `deccfc83…`, `gme-motion-v1`, `gme-shadow-v1`, `GMEConfig.v26()`, gate `246b23c`, ultralytics 8.4.104 / torch 2.12.0, MPS). 본 run 총 2,051초(≈34분, `nice -n 10`, YOLO 학습과 GPU 공유), 클립당 elapsed/duration 중앙값 0.22. **G0 통과.**

| 게이트 | 판정 | 값 |
|---|---|---|
| G-B1 moving recall ≥0.90 | ❌ | 46/72 = 63.9% |
| G-B2 hand_feeding recall ≥0.80 | ❌ | 10/28 = 35.7% |
| G-B3 급여 묶음 recall ≥ A−10%p | ❌ | B 0/32 = 0.0% vs A 26/32 = 81.2% |
| G-B4 급여 과탐 ≤10% | ✅ | 0/153 (급여로 판정한 클립 자체가 0) |
| G-C C 급여경계 ≥ A AND recovered ≥ broken | ❌ | acc A 86.5% / C 72.4% · recovered 1 / broken 27 |

| 지표 | A (v4.0) | B (룰 v0) | C (결합) |
|---|---|---|---|
| 급여경계 정확도 (185) | 86.5% | 31.9% | 72.4% |
| B raw 6-class | — | 31.9% (185) / 29.9% (197) | — |
| 분류기 arm 그룹 LOO CV (§5-2, 상한) | — | **20.0%** (그룹 = source 3개) | — |

**A↔B 상보성 (급여경계):** both 55 · A만 정답 105 · B만 정답 4 · 둘 다 오답 21. B만 맞힌 4건: `hand_feeding__moving__e0e38e0c`, `moving__drinking__48b5582e`, `moving__moving__0ce3cc59`, `moving__moving__a3a453c3`.

**B 클래스별 (급여 묶음):** moving 46/72 (→shedding 21) · feeding 0/32 (→moving 22, shedding 5, unseen 3, hand_feeding 2) · shedding 3/29 (→moving 20) · hand_feeding 10/28 (→moving 13) · eating_prey 0/22 · unseen 0/2. 룰 v0 발화 분포(197): moving 129 · shedding 37 · hand_feeding 23 · unseen 8 · **feeding 0**.

**C paired:** recovered 1(A eating_prey→C hand_feeding, GT hand_feeding) · broken 27 = C1 강등 17(GT drinking/eating_paste 인데 최장 정지 <3s 로 moving 강등) + C3 손급여 오승격 10(moving 3·shedding 5·eating_prey 3 → hand_feeding).

## 3. 분석

**시험지 대비 사후 변경:** 게이트·룰·임계값 변경 없음. 실행 전 정정 1건(R4 unknown+not_visible, 시험지 헤더에 기록). 아래 진단은 사전등록 밖의 **사후 설명**이며 게이트 판정에 반영하지 않았다.

**가설 판정:** H0 유지. 궤적 룰 v0 는 Tier 1 급 클래스(moving·hand_feeding)조차 게이트에 못 미쳤고, 급여 묶음은 0 건, A 와의 상보성도 4 건뿐이다.

**왜 이렇게 나왔나 (사후 진단, `results/diagnostics.txt`):**

1. **평가셋 자체가 클래스×촬영 원천으로 완전히 교락돼 있다.** paired 185 에서 moving 67/72 = `cam-motion`(고정 production 캠), shedding 29/29 = `uploaded`, hand_feeding·eating_prey·feeding 은 `eval-0608`/`uploaded`(handheld·업로드)에 몰려 있다. 궤적 특징은 카메라 흔들림·트랙 단절에 민감하므로 이 셋에서는 **행동이 아니라 촬영 방식을 재는 꼴**이 된다. 그룹 LOO CV 가 20% 인 이유도 이것(hold-out 그룹의 클래스가 학습 그룹에 없음). 참고로 층화 5-fold(사전등록 아님)는 46.5% 로 다수 클래스 기준선 38.9% 를 조금 넘는 수준.
2. **"정지 체류" 특징이 역전됐다.** longest_static 중앙값: moving 6.6s > feeding 2.5s. 급여 클립은 handheld 라 트랙이 끊겨(unknown 구간) 정지 구간이 잘게 쪼개지고, moving GT 클립(고정캠)은 게코가 대부분 가만히 있어(moving_ratio 중앙값 0.10) 정지 구간이 길다. "moving" GT 의 실체는 '높은 이동량' 이 아니라 '다른 행동이 없음' 이다. C1 강등 17건이 이 역전의 직접 결과.
3. **F8 머리 끝 미세움직임은 스케일이 임계값과 안 맞고 신호도 약하다.** head_micro ≥2.0 은 185 중 1건(shedding). 분위수: feeding 중앙값 0.019 / p75 0.31 vs moving 0.0 / p75 0.05 — 상위 사분위에서 약한 분리만 있다. 고정캠 drinking 클립(`9e9f164b`) 실측: 머리 2.19 vs 몸통 1.73 vs 배경 1.0 gray → 비율 0.38. 10fps bbox 절대차 수준에서는 핥기가 몸통 대비 0.5 gray 정도만 더 움직인다. 버그가 아니라(합성 테스트 통과·조인 128/129) 신호 크기 문제.
4. **R1(손 침입)이 카메라 움직임과 뒤섞인다.** global_change≥5 는 hand_feeding 13/28 뿐 아니라 eating_prey 12/22 에서도 발화(핀셋 급여). area_jump≥2 는 moving 52/72 에서 발화(재검출 시 박스 크기 요동). 결과적으로 C3 오승격 10건.
5. **R3(탈피 = 종횡비 진동+bout)은 방향이 반대.** aspect_osc≥0.25 가 moving 27/72 vs shedding 7/29. 박스 요동은 탈피 몸 비틀기가 아니라 검출 jitter 다(jitter 스펙과 같은 뿌리). moving→shedding 오분류 21건의 원인.

**정리:** "VLM 없이 어느 정도"의 정직한 답은 **이 데이터셋·이 특징·이 룰로는 못 잰다** 이다. 실패 원인의 절반은 룰 v0 의 미보정 임계값(사전 고정 원칙상 예상된 위험), 절반은 평가셋 교락이라 **같은 셋에서 임계값을 다시 잡아도 답이 안 된다**.

## 4. Decision: `reject`

- G-B1·G-B2 미달 → §9 룰대로 `reject`. "궤적 자체가 클립 수준 행동을 못 읽음 → GME run 품질부터 재검" 의 문구 중 GME run 품질(G0)은 통과했으므로, 재검 대상은 **특징·룰·평가셋** 이다.
- C 는 B adopt 가 아니므로 기록만(G-C ❌, broken 27).
- Tier 1 측정(활동시간·체류·일주기)에 대한 판정이 아니다 — 그건 GME 4단계·RAP M2 의 몫이며 이 실험 범위 밖(시험지 §9 해석 가드).

## 5. 한계

- 표본: 급여 32·hand_feeding 28·shedding 29, 그룹 3개. 클래스별 수치는 진단용.
- 모션 클립·handheld 혼재. 탈피 타임라인·수면지점 같은 연속 관측 신호는 애초에 없음.
- 단일 detector 버전(v2.6)·단일 algorithm(gme-motion-v1). jitter 완화 v2 가 들어오면 특징 2·4·5 의 값이 바뀔 수 있다.
- discordant review 는 미실시(불일치 109건, `results/results.md` 표). owner 육안은 GT 정정 후보 발굴용이며 게이트엔 미반영.
- 분류기 arm 은 사전등록대로 source 그룹 LOO 만 게이트 참고값. 층화 5-fold 는 사후 참고.

## 6. 다음 액션

1. **평가셋부터.** 궤적 특징을 공정하게 재려면 **같은 고정 카메라 안에서 클래스가 섞인** GT 가 필요하다. 라벨링 웹 v4 의 O/X·"의미 있는 행동" 체크에서 나오는 고정캠 급여·탈피 GT 를 모아 camera-night 단위 그룹 CV 가 가능한 셋을 만든다. 교락이 풀리기 전엔 v1 시험지를 열지 않는다.
2. **F8 재설계는 keypoint 또는 국소 고fps.** 10fps bbox 절대차는 핥기 신호를 못 담는다. 머리 keypoint(pose) 또는 머리 ROI 만 원본 fps 로 다시 읽는 채널이 다음 후보. 임계값은 **calibration split 을 시험지에 포함**해 정한다(이번 교훈: 물리 근거로 찍은 2.0 은 스케일 자체가 틀렸다).
3. **jitter 완화 v2 이후 재측정.** longest_static·aspect_osc·area_jump 가 전부 검출 jitter 에 오염돼 있다. `experiment-gme-jitter-overcount-mitigation` 이 채택되면 같은 197 로 특징만 재산출해 분포 변화를 본다(게이트 없이 진단).
4. **RAP 연속 데이터가 더 맞는 무대.** 고정캠·연속·개체 고정이라 위 1·3 의 교락과 단절이 구조적으로 없다. 체류 v0(M2) 산출물 위에 이 특징들을 얹어 보는 게 다음 실측.
5. 옛 local router 와 마찬가지로 이 결과를 **adoption 근거로 재사용하지 않는다**. 재등판 조건 = 1(교락 해소 셋) + 2(F8 재설계) 둘 다.
