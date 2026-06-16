# roi-crop-center 테스트 시험지 (Test Sheet)

> 규칙: [`.claude/rules/research-testing.md`](../../.claude/rules/research-testing.md). **실행 전 고정 — 사후 변경 금지.**
> 무결성 6단계: `specs/experiment-claude-montage-v2.md` §4-3a.

**실험 ID:** roi-crop-center · **phase:** C1 (frame-side 마지막 레버 1차) · **작성일:** 2026-06-16 · **상태:** ✅ 실행 완료 (decision `close` — [REPORT.md](REPORT.md), 합격기준 사후변경 없음)
**스펙:** [`specs/experiment-hierarchical-zoom-roi-crop.md`](../../specs/experiment-hierarchical-zoom-roi-crop.md)

## 1. 가설
- **H1 (대립)**: 원본 기반 center ROI crop이 급여 3종 recall을 올린다 (paired **recovered > broken**), 특히 eating_prey. → **frame-side 헤드룸 잔존** → 정밀 crop 2차 정당화.
- **H0 (귀무)**: center crop이 recall을 못 올린다 (recovered ≤ broken). → **frame-side 천장 = 입력으로 못 풂 확정**(close) → RBA 비-VLM이 유일한 길.

## 2. Sample list
- 구성: **전수** (manifest 187 중 GT∈{eating_paste, drinking, eating_prey}) · **N = 56** (drinking 17 / eating_paste 17 / eating_prey 22)
- 고정 방법: `experiments/roi-crop-center/sample_list.json` (clip_id 정렬, 결정론 — seed 불필요)
- **고정 후 불변.** 유일 변수 = 입력표현(center crop) 하나. 시간밀도·모델·프롬프트는 baseline과 동일 통제.

## 3. 모델 / 입력표현 / 프롬프트
- **모델**: Claude Sonnet 4.6 (채택 게이트 = production 목표 모델) · **blind** (GT/가설 미공개 서브에이전트)
- **입력표현 (변수)**: **center ROI crop** — **원본 프레임에서** 가운데 정사각(한 변 = **min(짧은변, 1080)**, `--roi-crop 1.0`) crop → 1080 no-upscale. 고해상일수록 큰 확대(4K 짧은변 2160→1080 풀디테일), 저해상은 짧은변 전체에 가까워 거의 무변화.
  - ⚠️ crop은 반드시 **원본**에서 (적응형@1080 결과물에서 crop하면 업스케일=가짜픽셀=무효). 1080 cap = 업스케일 0.
  - **⚠️ 데이터 특성 (2026-06-16 측정 전 발견)**: 56건 원본 짧은변 = 4K급(≥1440) **10건** / HD 15 / 저해상(<720) **31**. **prey는 22건 중 4K급 1건(중앙값 476)** — crop 이득은 4K급 10건(drinking 4·paste 5·prey 1)에 집중, 저해상 46건은 무변화 대조군. (당초 crop 비율 0.5 → 1건 테스트서 저해상 과소crop(328px) 발견 → min(짧은변,1080)으로 개선)
  - **시간밀도 통제**: 적응형과 **동일 프레임 위치**(같은 `-ss` 타임스탬프, 간격 3.5s/구간중앙/clamp 6~20). crop만 변수, 시간밀도 불변 → crop 효과 격리.
- **baseline (대조)**: 같은 56건의 **적응형@1080 (crop 없음)** — `experiments/v40-regression/` Sonnet v4.0 blind 재활용(prey 22 + paste 17 + drinking 15) + eval-0615 drinking 2건 신규 추출.
- **프롬프트**: v4.0 (production SOT 동치, `build_system_prompt(prompt_version="v4.0")`)

## 4. 측정 지표
- **paired recovered** (baseline 오답 → crop 정답) / **broken** (baseline 정답 → crop 오답)
- 클래스별 raw recall (crop vs baseline)
- 비급여 누출 (급여 3종 → moving 등) 변화
- 채점: `scripts/_score_v40.py` **급여경계 게이트**(drinking↔paste 무해, 비급여 경계 누출만 카운트) + eating_prey 포함 조정
- **broken 케이스 원인 태깅**(필수): "crop이 게코를 잘랐나"(center crop 아티팩트) vs "진짜 crop 효과 손실" 분리

## 5. 합격 기준 (게이트 — 숫자)
- **adopt** (헤드룸 잔존): paired **recovered − broken ≥ +3** (전체 56). (사용자 2026-06-16: prey 조건 제거 — prey 4K급 1/22라 prey 게이트 비현실적, §3 데이터 특성. 인퍼런스 전 조정, 사유 기록.)
- **보조 분석 (게이트 아님)**: 4K급 10건 층화 recovered/broken — crop 이득 원리적 가능 케이스. 전체 게이트가 주, 4K급 recovered는 방향 보조 신호.
- **close** (천장 확정): **recovered − broken ≤ 0** (crop 순손실/무효) **AND** 클래스별 recall이 baseline과 동등 이내(±1).
- 그 사이 = **hold**.
- 기준선 출처: `experiments/v40-regression/` (Sonnet v4.0 blind, 적응형@1080) + eval-0615 2건 신규 측정.

## 6. 예상 비용 / 토큰
- 신규 인퍼런스 = crop 입력 **56건만** (baseline은 재활용). 서브에이전트 1건당 6~20프레임.
- v40-regression(185건) 대비 ~30% → 추정 ~1M 서브에이전트 토큰 안팎. Workflow blind 배치.
- baseline 누락분(eval-0615 drinking 2건) 적응형@1080 신규 추출 = 무시 가능.

## 7. Decision 룰 (사전)
- **adopt** → 정밀 crop(사용자 클릭 bbox) 2차 + 시간밀도 축 추가(2축 동시)로 spec In 확장. frame-side 레버 살아있음.
- **close** → frame-side 종료 **확정**. RBA 비-VLM evidence layer(`feature-rba-evidence-based-feeding-drinking.md`)가 유일한 길. 학습노트 §6 표 마지막 칸 ❌로 메움.
- **hold** → 부분 효과(특정 클래스만 회복) → 클래스별 분해 후 crop 비율/방법 재설계.
- **해석 가드**:
  - 56건이나 클래스 단위론 소표본(prey 22 / paste 17 / drinking 17) — 클래스 단독 ±1~2 노이즈, 단독 판정 금지.
  - **원본 해상도 층화 필수**: crop 이득은 4K급 10건에서만 원리적 가능, 저해상 46건은 무변화 예상(대조군). 전체 recovered가 저해상 희석으로 낮아도 **4K급서 recovered>broken이면 "고해상 한정 frame-side 헤드룸" 신호** → close 아닌 hold/2차 검토.
  - center crop은 게코가 가장자리인 클립에서 게코를 잘라 **broken 노이즈** 발생 가능 — broken은 §4 원인 태깅으로 "crop 아티팩트 vs 진짜 효과" 분리 후 해석.
  - temperature 노이즈 ±1. crop 비율 0.5는 1차 거친 측정 — 비율 민감도는 미검증(2차 과제).
