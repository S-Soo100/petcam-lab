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

### 2026-07-21 — 연구방향 상담 P1/P2/P3 판정 (판정자: Claude 제안 + owner 승인)

맥락: owner 고충 3개 — ① 야간 IR→shedding 오탐 ② 쳇바퀴→drinking 오탐 ③ 전량 VLM 호출 불가·사전 필터 한계. 논의 결과를 P1/P2/P3로 구조화, owner가 plan 승인 (계획 파일: Claude 세션 plan `swirling-stargazing-wand`).

| 제안 | G1 SOT | G2 효과 | G3 측정 | G4 계획 | 판정 | 근거 |
|---|---|---|---|---|---|---|
| **P1** nightly classify 결정론 픽스 (`claude -p`→SDK temperature=0 배선) + 기존 오탐 전량 재측정 | ✓ | ✓ | ✓ | ✓ | **adopt** | 이미 진단 완료된 버그(랩 재현: 오탐 32건이 v4.0·v4.1 둘 다 64/64 moving = temperature 원인)의 미이행 팔로업. SDK 경로(`reporter/anthropic_analyzer.py`) 이미 존재, 배선만 필요. ⚠️ analyzer가 reject된 v4.1 프롬프트 로드 중 → v4.0 핀 포함. 자매 레포 작업 → petcam-lab은 핸드오프 문서만(`docs/handoff-prompts/2026-07-21-nightly-classify-determinism-handoff.md`). 재측정은 저쪽 레포 TEST-SHEET/REPORT 의무 |
| **P2** 케이지 프로필 메타 (개체 외형 기준선·붙박이 사물 컨텍스트 주입) | ✓ | △ | ○ | △ | **hold** | SOT "메타 강화" 정방향이나 효과 크기 미확정 — **P1 재측정이 남기는 진짜 오탐 목록이 스코프를 정의** (P1 결과 전 착수 금지). owner 우려 3개 기록: 입력 가능성·최신화·효과 크기. owner 구현 아이디어 병기: 카메라별 DB 정보 필드 마이그레이션 + 앱 카메라 등록 시퀀스에서 입력. 부활 시 paired 재추론(recovered≥broken) 게이트 필수 |
| **P3** "볼만한 N개" 하이라이트 선별 probe (DB-only 점수식 vs 무작위, T0 blind 인프라 재사용) | ✓ | ✓ | ✓ | △ | **adopt (TEST-SHEET 선행 조건)** | RBA Data Engine v1(사람 blind GT 적립) 정방향 + DB-first top-N 샘플 아키텍처의 뽑기 로직 검증. T0 부산물(dwell=존재 신호 유효, absent 3% vs 55%) 활용. 측정: top20 vs random20 blind informative율. 부산물 = 사람 GT. 조건: `experiments/t1-highlight-selection/TEST-SHEET.md` pre-reg + owner 승인 후 실행 |
| 사전 필터(나쁜 클립 제거) 재도전 | ✗ | - | - | - | **탈락 재확인** | 상단 레코드 #1 참조 — detector v2 specificity 40%로 분리 불가 + SOT §11.3 비용 게이팅 폐기. 선별은 "빼기(필터)"가 아니라 "뽑기(top-N 샘플)"로 접근 (P3) |

**2026-07-21 실행 개시 기록 (append):** P3 조건 충족 — `experiments/t1-highlight-selection/TEST-SHEET.md` owner 승인·🔒 동결(2026-07-21), 실행 개시. P1 핸드오프 발행 — `docs/handoff-prompts/2026-07-21-nightly-classify-determinism-handoff.md`, validator `HANDOFF_OK task=nightly-label-determinism repo=petcam-nightly-reporter commit=46ca39e5 runtime=launchagent@baeg-endeuui-Macmini.local`. 진행 상황 SOT: `specs/next-session.md` 2026-07-21 블록.

**2026-07-21 P1 재측정 결과 회신 (append):** 결제 결함(콘솔 KR 개인 크레딧 구매 불가)으로 A안(temp=0 Messages API)은 보류, **플랜 B(구독 CLI 3회-일치, TEST-SHEET-B pre-reg `f1f541e`)로 실행 완주** — 126/126콜, 42/42클립. **진짜 오탐(강) 0건**(shedding 0/32 · drinking 0/10), 3회 일치율 83.3%(비일치 7클립 = 비결정성 직접 증거) → **decision `adopt`(약식): 오탐 지배 원인 = temperature 비결정성.** lab v41 재현(64/64 moving)과 방향 일치, 이번엔 production 계약 입력(6장@768)에서 확인. **P2 함의: 강 잔존 오탐 0 → P2(케이지 프로필)는 hold 유지·근거 축소** (A안 temp=0 확정 후 재판단). 예외 관찰 1건: `3e51c7ed`(GT moving)가 drinking 3/3 안정 오분류 — 유일한 안정 컨텍스트-오탐 후보(쳇바퀴 여부 owner 확인 필요). **[07-21 owner 확정: 쳇바퀴 아님 — 물 디스펜서 위를 타고 넘어간 장면(2026-04-29 05:25, P4 Cam dev 정수기 물그릇). GT moving 정당 → 42건 중 유일한 "안정 confabulation" 실증("물그릇 위 몸+머리"가 v4.0 drinking 패턴에 걸림). P2의 근거 = 이 1건뿐(1/42) — hold 유지 타당.]** 다음 = P1 Task 4 결정론 운영 배선(owner 승인 게이트 + API 키 필요, 결제 지원팀 문의 중). 산출물: nightly-reporter `experiments/label-determinism-remeasure/REPORT-B.md` (`ed60b48`).

**2026-07-21 T1 결과 기록 (append):** T1 = **`reject`** (Δ+5%p < 게이트 +10%p, [REPORT](../experiments/t1-highlight-selection/REPORT.md)). 합성점수 v1 폐기. 원인 = detector v2 오검출이 존재+주기성 성분 동시 오염(Cam 2 상시 오염원, S absent 30% 안전점검 발동). **v2 재등판 조건:** ① 오검출 시그니처 페널티(한 셀 고정+전체 관찰+고주기) ② 카메라 정규화 ③ Gate prelabel 결합 중 택해 **새 TEST-SHEET + 이 게이트 재통과** 후에만. T0+T1 blind 판정 누적 120건 = 사람 GT 적립(Data Engine v1 방향 부합). gate 레포 피드백(record #1 약한 통과)에 Cam 2 오염원 사례 추가 사유 발생.

### 2026-07-21 — Mac mini Local VLM Evidence Analyst 벤치마크 (판정자: Codex + owner 승인)

맥락: Universal Python Evidence가 모든 clip에 적용되는 상태에서, Python/OpenCV/Gate가 만든 수치와 선택 프레임·ROI를 소형 local multimodal model이 함께 읽어 보조 관찰을 만들 수 있는지 검증한다. 과거 invalid local router와 local VLM 7-class 행동 분류를 재등판시키지 않는다. 설계 정본: [`2026-07-21-mac-mini-local-vlm-evidence-analyst-design.md`](superpowers/specs/2026-07-21-mac-mini-local-vlm-evidence-analyst-design.md).

| 제안 | G1 SOT | G2 효과 | G3 측정 | G4 계획 | 판정 | 근거 |
|---|---|---|---|---|---|---|
| Python Evidence + 전체 2장·ROI 4장 → Mac mini local VLM 보조 evidence | ✓ | ✓ | ✓ | ✓ | **벤치마크 승인** | SOT의 evidence 강화·local VLM side-worker 연구와 부합. 180개 고유 clip(6 strata×30), fresh holdout 60, 반복 60회를 포함한 총 240 inference로 Mac mini 자원·처리량·일관성·사람 GT 일치도를 측정한다. 결과는 artifact에만 기록하며 행동 GT·자동 제외·selector·cloud 차단에는 사용하지 않는다. 1차 후보는 Qwen2.5-VL 3B 4-bit + MLX-VLM. 설치·실행은 별도 구현계획과 owner 승인 후다. |

**2026-07-21 모델 후보 라이선스 정정 (append):** 위 행 작성 후 공식 모델 라이선스를 재감사한 결과 Qwen2.5-VL 3B 원본은 Qwen Research License의 비상업 연구 조건이라 상용 petcam 연구 기본 후보로 부적합함을 확인했다. 기존 행은 append-only 이력으로 보존하고, **1차 후보를 Apache-2.0인 `mlx-community/SmolVLM2-2.2B-Instruct-mlx`로 정정**한다. Qwen은 별도 상용 허가를 서면으로 확보하기 전 다운로드·실행·비교군 사용 금지다. 연구 질문·표본·240 measured inference·production 미연결 경계는 그대로다.
