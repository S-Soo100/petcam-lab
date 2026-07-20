# Decision Gate — 방향 제안 4게이트 프로토콜 + 판정 로그

> **모든 AI 에이전트(Claude / Codex / Gemini / 기타) 공통.** 새 작업 방향·투자·실험을 제안하거나 착수하기 전에 아래 4게이트를 명시적으로 통과시키고, 결과를 이 파일 하단 로그에 **append-only**로 기록한다. (2026-07-21 owner 제정 — T0 직후 Claude 제안 5개 중 3개가 이 게이트로 걸러진 게 계기.)

## 4게이트

| # | 게이트 | 통과 기준 | 흔한 탈락 사유 |
|---|---|---|---|
| 1 | **SOT 부합** | `tera-ai-product-master` 스펙·현행 실행 SOT(예: RBA Data Engine v1)에 기록된 목표와 정합. **SOT를 실제로 열어 확인** — 기억으로 단정 금지 | SOT가 이미 폐기한 설계 재제안 (예: Gate 게이팅 §11.3), Phase 2로 미룬 것 앞당김 |
| 2 | **기대효과 명확** | 효과의 소비처·크기를 구체적으로 말할 수 있음. "정보 전달" "방향 서술"은 효과 아님 | 근거 신호 없는 힌트/메타 제안, 실측 안 된 절감액 |
| 3 | **측정가능** | 성공/실패를 가르는 검증 방법이 있고, 필요하면 TEST-SHEET 선행 (`.claude/rules/research-testing.md`) | 측정 계획 없음, 기존 결과 재사용(validity audit 위반) |
| 4 | **유효한 계획** | 실행 내용이 정의됨(스코프·선행조건·쓰기 범위). 승인·스펙이 필요하면 그것부터 | 의도만 있고 매핑/스코프 미정, 하드계약 밖 쓰기를 계획 없이 포함 |

**운영 규칙**
- 판정은 게이트별 ✓/△/✗ + 근거 한 줄. △가 있으면 "조건부 — 조건 명시".
- 탈락한 제안도 기록한다 (같은 아이디어 재등판 시 즉시 참조 — 재평가하려면 탈락 사유가 해소됐음을 먼저 보여야 함).
- 이 로그는 **의사결정 기록이지 실험 보고서가 아님** — 실험 무결성은 기존 TEST-SHEET/REPORT 체계가 SOT.
- Codex/Gemini 등 다른 에이전트도 이 로그를 읽고 이어서 기록한다. 형식 유지, 기존 행 수정 금지.

## 판정 로그 (append-only, 최신이 아래)

### 2026-07-21 — T0 bowl-dwell probe 직후 후속 방향 판정 (판정자: Claude + owner 게이트 질의)

맥락: [T0 REPORT](../experiments/t0-bowl-dwell-probe/REPORT.md) `reject`(체류-단독 무효) + absent 분리 조사(80건 전수, detector v2 bbox로는 absent/present 분리 불가 — absent가 오히려 roi_max 높음 = 환경모션 오검출) 이후 나온 제안들.

| 제안 | G1 SOT | G2 효과 | G3 측정 | G4 계획 | 판정 | 근거 |
|---|---|---|---|---|---|---|
| detector v3 재학습 → absent 제외 → VLM 비용 절감 | ✗ | △ | ○ | ✗ | **탈락** | SOT §11.3이 게이팅 명시 폐기("메타 강화 > VLM 막기"), exclude_absent는 safety holdout 기각 이력, detector류는 Phase 2(3조건 미충족). 절감 실측 0 (router validity audit) |
| absent를 "메타 힌트로 남기기" | △ | ✗ | ✗ | ✗ | **탈락** | 조사 결론 자체가 "현 evidence로 absent 분리 불가"(present 손실 0으로 걸러지는 absent 0/13) — 힌트의 근거 신호가 없음. 실행 내용 미정의 |
| hard negative 21건(near_bowl_no_care) → T2 GT 엔진 투입 | ✓ | ✓ | ✓ | △ | **조건부 통과** | RBA Data Engine v1(현행 실행 SOT) + T0 계획서 T2 목표 "hard neg ≥200"의 첫 10%. T3 사전등록 필수 입력. **조건: ⓐ 기존 라벨 체계에 없는 클래스라 스키마 매핑 결정 ⓑ DB 쓰기 = T0 하드계약 밖 → 별도 스펙+승인 선행** |
| gate 레포 피드백 이슈 (bbox≠presence, v2 specificity 40%가 absent 오검출 유발) | ✓ | △ | △ | ✓ | **약한 통과** | §11.2 단방향 lab→gate 피드백 흐름 명시. 효과는 "정보 전달"이라 간접적이나 비용 ~0. v3 prelabel 품질 개선 근거로 전달 (비용 게이팅 목적 아님) |
| 분무 이벤트 검출 probe (drinking 시간축 접근) | - | - | - | - | **보류 (owner)** | owner가 "안 해도 됨" 지시. 도메인 사실(그릇보다 벽/잎 응결수 음수)은 T0 REPORT §3·§5에 기록됨. 재등판 시 게이트 통과 필요 |
