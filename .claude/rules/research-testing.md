# 연구 테스트 프로토콜 — 시험지 & 보고서

> 연구 목적 테스트는 **실행 전 시험지(Test Sheet)**, **실행 후 보고서(Report)**를 항상 남긴다.
> 결과 무결성을 나중에 감사할 수 있게 하는 절차 규칙. (2026-06-12 신설, 사용자 결정)
> 상세 무결성 6단계는 `specs/experiment-claude-montage-v2.md` §4-3a 가 레퍼런스.

## 🎯 트리거 — 언제 의무인가

**판단 기준 한 줄: "이 실행 결과가 채택/기각/방향 결정에 쓰이나?" → Yes면 시험지+보고서 의무.**

| | 예시 |
|---|---|
| **의무 O** | 모델 정확도 평가 · 입력표현 실험 · 프롬프트 회귀 · 비용/토큰 측정 · 서브에이전트/API 배치로 결과를 내는 모든 테스트 |
| **의무 X** | 단발 디버깅 · 데이터 준비(프레임 추출/몽타주 빌드) · 스크립트 동작 확인 · 1회성 조회 |

> 데이터 준비(빌더 실행)는 면제지만, 그 산출물을 **평가에 넣는 순간** 그 평가는 의무 대상.

## 🔄 흐름

```
시험지(TEST-SHEET.md, 실행 전 고정)
  → [무결성 6단계 §4-3a: blind inference → deterministic scorer → LLM audit → discordant review]
  → 보고서(REPORT.md, 실행 후) → INDEX.md 한 줄 등록
```

시험지 = 6단계의 1단계(pre-reg), 보고서 = 6단계(decision). 가운데는 기존 프로세스 그대로.

## 📋 시험지 (TEST-SHEET.md) — 실행 전 고정, 사후 변경 금지

1. **가설** — H0(귀무) / H1(대립)
2. **sample list** — 고정 + 재현 방법(스크립트/seed). 별도 `sample_list.json` 권장
3. **모델 / 입력표현 / 프롬프트 버전**
4. **측정 지표** — 정확도 · paired recovered/broken · 토큰 등
5. **합격 기준** — 게이트를 **숫자로** (예: "같은 모델 frames 대비 −3%p 이내 AND recovered≥broken")
6. **예상 비용/토큰**
7. **decision 룰** — 어떤 결과면 adopt / hold / reject 인지 사전 명시

## 📊 보고서 (REPORT.md) — 실행 후

1. **결과 표** — 지표별
2. **시험지 대비** — 사후 변경 있었나(있으면 사유). 없으면 "변경 없음"
3. **가설 판정** — H0 기각? 유지?
4. **decision label** — `adopt` / `hold` / `reject` + 근거
5. **paired/discordant 분석 · 한계·노이즈**
6. **다음 액션**

## 🚫 하드룰

1. **시험지 없이 평가 배치 실행 금지** — pre-reg 없이 인퍼런스 시작 금지.
2. **보고서 없이 다음 phase 진행 금지** — 직전 테스트 decision 미기록 상태로 다음 테스트 착수 금지.
3. **합격 기준 사후 변경 금지** — 결과를 본 뒤 게이트를 바꾸지 않는다. 부득이하면 결과 확인 *전* + 사유 기록.

## ⚠️ 해석 함정 — Selection Bias (오답만 태깅)

오답 N건만 골라 quality/난이도 태깅한 뒤 그 그룹 정확도를 "이 난이도가 어렵다"로 해석하면 **순환논리** — 오답을 그 태그로 옮긴 결과일 뿐이다.
- **금지**: 오답-전용 태깅 그룹의 정확도를 클래스/난이도 비교 근거로 인용.
- **OK**: "오답이 어느 quality/클래스에 분포하나" 분포 진단.
- **올바른 방법**: quality별 **정확도 비교**는 정답 포함 **전수 태깅**한 클래스에서만.

상세 사례·적용: 메모리 `selection-bias-error-only-tagging` (2026-06-15 B1 ②, drinking 17 전수 vs 오답 16 태깅 대비).

## 📂 위치 / 템플릿

- 실험별: `experiments/<exp-id>/TEST-SHEET.md` + `REPORT.md` (입력·결과와 같은 폴더)
- 중앙 인덱스: `experiments/INDEX.md` — 실험별 한 줄 + decision + 보고서 링크
- 템플릿: [`specs/_test-sheet-template.md`](../../specs/_test-sheet-template.md) · [`specs/_report-template.md`](../../specs/_report-template.md)
- 레퍼런스 실물: `experiments/m0-montage/REPORT.md` (1호)
