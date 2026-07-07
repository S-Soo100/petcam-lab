# TEST-SHEET — gate detector recall/specificity 검증

> 실행 전 고정 (pre-reg). 사후 변경 금지. (2026-07-07)
> 목적: gecko-vision-gate detector(RF-DETR v2)를 RBA 분석 전 **unseen 필터(gate)**로 쓸 수 있는지 판정.

## 1. 가설
- **H0**: detector 가 gate 로 부적합 — 게코를 놓치거나(recall↓) unseen 을 못 걸러냄(specificity↓).
- **H1**: detector recall 높음(게코 거의 안 놓침) + specificity 유의미(unseen 상당수 걸러 claude 절감).

## 2. Sample
- `backlog.jsonl` 300개 (07-03밤 20:00~02:25, claude v4.0 Sonnet 판정).
- 구성: moving 218 · unseen 80 · shedding 2.
- ⚠️ **claude 판정을 프록시 GT 로 사용** — 한계: claude 도 오답 가능. 이 검증은 절대 정확도가 아니라 **detector↔claude 정합** 측정. 불일치는 육안(사람 GT) 확인 대상.

## 3. 모델/입력
- detector: gecko-vision-gate RF-DETR, `runs/gecko_v2/checkpoint_best_regular.pth`.
- threshold 0.25 · frames 12 (batch_prelabel 기본).
- 입력: 동일 300 clip R2 다운 mp4 (clip_id = 파일 stem 으로 backlog 와 매칭).

## 4. 측정 지표
- **recall** = detector_visible / claude "게코 있음"(moving+shedding = 220). ← 게코 놓침(FN) 위험도.
- **specificity** = detector_NOT_visible / claude unseen(80). ← unseen 필터 효과(gate 절감 상한).
- **bbox 위치 분포** (고정 위치 오탐 진단 — 스모크서 5개 동일 위치 `[~1,~39,~175,~125]` 의심).
- confidence 분포.

## 5. 합격 기준 (숫자, 사전 고정)
- **adopt**: recall ≥ 95% AND specificity ≥ 50%.
- **hold**: recall ≥ 95% AND specificity < 50% (게코는 안 놓치나 오탐 많아 절감 미미 → threshold 상향/재학습).
- **reject**: recall < 95% (게코 놓쳐 케어행동 손실 위험 → gate 자체 부적합).

## 6. 예상 비용
- claude 0 (detector 로컬 추론). R2 다운 300개(~600MB) + RF-DETR 추론(로컬).

## 7. decision 룰
- 위 5의 adopt/hold/reject 라벨 그대로.
- 스모크 예비신호(unseen 2/2 를 visible 로 오탐, bbox 고정)가 전수에서 재현되면 specificity 바닥 → hold/reject 유력.
- 불일치 케이스(claude unseen ↔ detector visible)는 REPORT 에 육안 확인 항목으로 분리.
