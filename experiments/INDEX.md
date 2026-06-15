# 실험 보고서 인덱스

> 연구 테스트 보고서 일람. 규칙: [`.claude/rules/research-testing.md`](../.claude/rules/research-testing.md).
> 새 테스트 = 시험지(TEST-SHEET.md) → 실행 → 보고서(REPORT.md) → 이 표에 한 줄 추가.

## 진행 중 트랙 — Claude 구독 입력표현 연구 (`specs/experiment-claude-montage-v2.md`)

| 날짜 | 실험 | decision | 한 줄 결과 | 보고서 |
|---|---|---|---|---|
| 2026-06-12 | **M0** 몽타주 v2 12변형 스크리닝 (Sonnet, 20건) | `hold` | 12변형 전부 frames(12/20) 미달. 최고 18f-2s-nots 11/20. 2장>1장(셀 해상도=레버) 확인하나 천장 못 넘음, micro 붕괴 | [m0-montage/REPORT.md](m0-montage/REPORT.md) |
| 2026-06-13 | **v4.0 회귀** v3.6.1 vs v4.0 (Sonnet blind, 적응형 frames@1080, 185건) | `adopt` | raw 동등 85.9% · 급여경계 +0.5%p · 게이트 4/4. drinking 타겟 개선(클래스 10→11·누출 5→4·과탐 2→1) + 클래스 3개 폐기. broken 5는 무관 노이즈. v4.0=새 기준선 | [v40-regression/REPORT.md](v40-regression/REPORT.md) |
| 2026-06-15 | **M1/M3** (몽타주 매듭) | `not-proceed` | V1 close(입력레버 소진) + M0 hold로 몽타주 트랙 전체 종료 — 확정 측정 불필요, 입력 천장=적응형 frames@1080 | [m0-montage/REPORT.md](m0-montage/REPORT.md) |
| 2026-06-15 | **V1** drinking 표적 (적응형@1080 v4.0, pos15+neg6, 재활용+육안) | `close` | 입력레버 소진 — 적응형 누출4 전부 시각부재/거리/자세(ROI여지 0). 과탐 1/6 안전. occlusion진단 폐기·GT 4건 전부 유효(제거 철회)·새영상 0.82 정확 | [v1-drinking-targeted/REPORT.md](v1-drinking-targeted/REPORT.md) |
| 2026-06-15 | **Opus vs Sonnet** 186 (적응형@1080 v4.0 blind) | `Opus 우위` | **Opus 88.7% > Sonnet 85.5% (+3.2%p, 186)** · 회귀셋185 89.2 vs 85.9(v40 정확일치=검증). P1(+3%p)과 일관=실제격차. 클래스 대부분 Opus≥. discordant 8:2 Opus. production 전환은 비용 trade-off별도(캐스케이드 후보) | [opus-sonnet-186/REPORT.md](opus-sonnet-186/REPORT.md) |

## 소급 참고 — 규칙 신설(2026-06-12) 이전 주요 테스트

표준 시험지/보고서 형식 이전이라 형식은 제각각이나, 결과 기록은 아래에 보존:

| 트랙 | 산출물 | 핵심 |
|---|---|---|
| Gemini 트랙 클로징 | [gemini-final-partial/README.md](gemini-final-partial/README.md) | 4버전×202 회귀 63%(145건 paired) 중단 박제. v3.5 82.2%/v3.6.1 78.3%, IR가드 Gemini −2.3%p |
| P1 4모델 baseline | `experiments/eval-frames-full/` + `scripts/_score_frames_models.py` | frames 202 blind: Fable 85.1 > Opus 81.2 > Sonnet 78.2 |
| 약한모델 레버 P1~P4 | `specs/experiment-weak-model-levers.md` | 격차=단일 실패모드(Sonnet IR shedding 과탐) → 표적룰/캐스케이드 회수 |
| frames vs 몽타주(0608) | `experiments/eval-159-claude/` | 개별프레임 > contact sheet, 입력표현이 정확도 레버 |
