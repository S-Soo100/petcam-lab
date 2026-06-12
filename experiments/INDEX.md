# 실험 보고서 인덱스

> 연구 테스트 보고서 일람. 규칙: [`.claude/rules/research-testing.md`](../.claude/rules/research-testing.md).
> 새 테스트 = 시험지(TEST-SHEET.md) → 실행 → 보고서(REPORT.md) → 이 표에 한 줄 추가.

## 진행 중 트랙 — Claude 구독 입력표현 연구 (`specs/experiment-claude-montage-v2.md`)

| 날짜 | 실험 | decision | 한 줄 결과 | 보고서 |
|---|---|---|---|---|
| 2026-06-12 | **M0** 몽타주 v2 12변형 스크리닝 (Sonnet, 20건) | `hold` | 12변형 전부 frames(12/20) 미달. 최고 18f-2s-nots 11/20. 2장>1장(셀 해상도=레버) 확인하나 천장 못 넘음, micro 붕괴 | [m0-montage/REPORT.md](m0-montage/REPORT.md) |
| — | M1 18f-2s-nots × micro55 + Opus | (대기) | 몽타주 트랙 매듭용 확정 측정 | — |
| — | V1 cv-frames drinking pos16+neg16 | (대기) | 개별프레임 밀도 — drinking 한정 (별개 트랙) | — |

## 소급 참고 — 규칙 신설(2026-06-12) 이전 주요 테스트

표준 시험지/보고서 형식 이전이라 형식은 제각각이나, 결과 기록은 아래에 보존:

| 트랙 | 산출물 | 핵심 |
|---|---|---|
| Gemini 트랙 클로징 | [gemini-final-partial/README.md](gemini-final-partial/README.md) | 4버전×202 회귀 63%(145건 paired) 중단 박제. v3.5 82.2%/v3.6.1 78.3%, IR가드 Gemini −2.3%p |
| P1 4모델 baseline | `experiments/eval-frames-full/` + `scripts/_score_frames_models.py` | frames 202 blind: Fable 85.1 > Opus 81.2 > Sonnet 78.2 |
| 약한모델 레버 P1~P4 | `specs/experiment-weak-model-levers.md` | 격차=단일 실패모드(Sonnet IR shedding 과탐) → 표적룰/캐스케이드 회수 |
| frames vs 몽타주(0608) | `experiments/eval-159-claude/` | 개별프레임 > contact sheet, 입력표현이 정확도 레버 |
