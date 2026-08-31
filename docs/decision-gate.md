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

### 2026-07-22 — Local VLM Evidence GT 웹 워크스페이스 (판정자: Codex + owner 승인)

맥락: Local VLM Work Package A가 `HARDENED_IMPLEMENTATION_READY_FOR_DATA_REVIEW`에 도달했다. 다음 병목은 production Python Evidence에서 6 strata 후보를 올바르게 구성하고, 모델·Gate·Python 결과를 숨긴 채 사람 evidence GT 180개를 만드는 일이다. owner는 CSV 단독 방식 대신 라벨링 웹 전용 화면을 선택했고, 일반 라벨링 큐의 최신순 계약도 함께 강화하도록 승인했다. 설계 정본: [`2026-07-22-local-vlm-evidence-web-gt-design.md`](superpowers/specs/2026-07-22-local-vlm-evidence-web-gt-design.md) · [`2026-07-22-labeling-queue-newest-order-design.md`](superpowers/specs/2026-07-22-labeling-queue-newest-order-design.md).

| 제안 | G1 SOT | G2 효과 | G3 측정 | G4 계획 | 판정 | 근거 |
|---|---|---|---|---|---|---|
| Python Evidence 후보 가용성 → owner 전용 blind evidence GT 180개 웹 수집 | ✓ | ✓ | ✓ | ✓ | **설계 승인** | RBA Data Engine v1의 사람 blind GT·export manifest·provenance 분리 요구와 직접 부합한다. 효과 소비처는 Local VLM 240-key 벤치마크의 사람 정답이며 6 strata×30, dev120/holdout60, clip·episode 중복 0, 두 SHA 동결로 측정한다. B1 SELECT-only → B2 preview → B3 별도 production 승인으로 쓰기 범위를 분리한다. 모델 출력·자동 label·자동 skip은 금지한다. |
| 일반 라벨링 큐 `(started_at DESC, id DESC)` 복합 cursor·stale-response 방어 | ✓ | ✓ | ✓ | ✓ | **구현 승인** | RBA Data Engine v1의 지속 GT 생산 UX를 안정화한다. 같은 timestamp의 누락·중복 0, API 2페이지 단조 감소, stale response 회귀 테스트, production 최신 eligible clip 대조로 측정한다. DB schema·라벨 의미는 바꾸지 않는다. |

### 2026-07-22 — `motion_clips` 네이티브 운영 라벨링 전환 (판정자: Codex + owner 승인)

맥락: production 신규 영상 정본은 `motion_clips`인데 일반 라벨링 큐는 7월 8일 이후 유입이 끊긴
legacy `camera_clips`만 읽고 있었다. 2026-07-21 17시 자율급여 영상을 찾는 owner smoke에서 최근 3일
큐가 0건인 반면 `motion_clips`에는 2번 카메라 16:30~17:30 영상 41건이 존재함을 SELECT-only로
확인했다. 세 테스트 카메라의 소유 계정도 product owner 계정과 분리돼 있어 기존 owner 자기소유 필터는
카메라 옵션을 비우는 두 번째 결함이었다. 설계 정본:
[`2026-07-22-motion-clips-native-labeling-design.md`](superpowers/specs/2026-07-22-motion-clips-native-labeling-design.md).

| 제안 | G1 SOT | G2 효과 | G3 측정 | G4 계획 | 판정 | 근거 |
|---|---|---|---|---|---|---|
| 일반 운영 라벨링을 `camera_clips` 미러 없이 `motion_clips` 네이티브 v3로 전환 | ✓ | ✓ | ✓ | ✓ | **설계 승인** | RBA Data Engine v1의 지속 사람 GT 생산과 운영 영상 SOT를 일치시킨다. owner는 승인 없이 모든 운영 영상을 최신순으로 보고 직접 라벨링하며, 일반 라벨러만 owner가 `label`로 보낸 영상을 본다. 성공은 최신 DB clip 일치, 카메라·날짜 필터, owner 전체 접근, labeler 격리, 2페이지 keyset 무중복, legacy 튜토리얼/GT 불변, `camera_clips` mirror write 0으로 검증한다. Evidence GT 연구·자동 skip·VLM 선택 로직은 범위 밖이다. |

### 2026-07-23 — 그룹 이중 블라인드 라벨링 운영 (판정자: Codex + owner 승인)

맥락: `motion_clips` 네이티브 v3는 owner가 먼저 `label`로 고른 영상만 일반 라벨러에게 보여 owner가 모든 원본 영상의 1차 분류를 떠안는다. 승인 라벨러 4명을 두 그룹으로 나눠 담당 카메라의 같은 영상을 두 명이 독립 판정하고, 불일치만 owner가 최종 검수하는 운영 방향을 owner가 승인했다. 설계 정본: [`2026-07-23-double-blind-labeling-groups-design.md`](superpowers/specs/2026-07-23-double-blind-labeling-groups-design.md).

| 제안 | G1 SOT | G2 효과 | G3 측정 | G4 계획 | 판정 | 근거 |
|---|---|---|---|---|---|---|
| 담당 카메라 그룹 2인 이중 블라인드 + 불일치 owner 검수 + 활동일 순차 큐 | ✓ | ✓ | ✓ | ✓ | **설계 승인** | Phase 1 외부 운영자 확대·사람 blind GT·검수 이력 SOT와 부합한다. 소비처는 `motion_clips` 운영 GT이며, owner는 conflict만 기본 검수한다. 상대 답 누출 0, clip당 서로 다른 최초 제출 2개, comparator 독립 재계산, preview 12건·production 첫 30건 owner 감사로 측정한다. 새 group/slot/submission/consensus 경계를 forward migration과 단계별 canary로 도입하며 legacy·VLM·Gate·Python Evidence는 변경하지 않는다. |

### 2026-07-24 — 짧은 영상 장치 오류 격리·7일 보존 (판정자: Codex + owner 승인)

맥락: P4 Cam 2(dev)에서 라벨링 웹 표시 4초 1건·11초 39건이 Owner 판정 40/40 `skip`, 연결 라벨링 세션 0이었다. 반면 15초 미만 비율은 P4 Cam 2 33.8%, P4 Cam (dev) 0.7%, P4 Cam 3 0.6%로 카메라별 분포가 달라 전 카메라 `<15초` 즉시 삭제는 정상 희소 행동 손실 위험이 있다. 설계 정본: [`2026-07-24-short-clip-device-error-retention-design.md`](superpowers/specs/2026-07-24-short-clip-device-error-retention-design.md).

| 제안 | G1 SOT | G2 효과 | G3 측정 | G4 계획 | 판정 | 근거 |
|---|---|---|---|---|---|---|
| 전 카메라 15초 미만 즉시 제외·R2 삭제 | ✗ | ✓ | △ | ✗ | **탈락** | Data Engine v1의 GT 독립 검증 전 영구 삭제 금지와 충돌한다. 다른 카메라에는 정상 짧은 영상일 수 있고 삭제는 복구 불가다. |
| 전 카메라 `<15초` 후보 감지 + 검증된 카메라별 시그니처만 자동 격리 + 7일 복구 후 안전 삭제 | ✓ | ✓ | ✓ | ✓ | **설계 승인** | 길이는 장치 오류 후보 신호로만 사용한다. 최초 자동 격리는 P4 Cam 2의 검증된 표시 4/11초만, 다른 카메라는 감사 대기다. 40/40 baseline, Owner 복구, false exclusion 0, 최초 R2 delete 30건, 사람 GT·blind·151 frozen set mutation 0으로 측정한다. |

### 2026-07-31 — 일상 live highlight-only nonblocking comparator v2 (판정자: Codex + Mac mini read-only replay + owner 승인)

맥락: `motion-blind-v1`은 label GT 11개 필드 중 하나만 달라도 clip 전체를 owner conflict로
보낸다. production immutable paired submission 95개를 SELECT-only 재계산했을 때 v1 conflict
69개 중 9개가 `highlight_recommendation` 단독 차이였다. soft 4필드 전체 완화는 13개를 줄이지만
highlight-only보다 추가 효과가 4개뿐이고 `human_confidence`·`context_tags` 품질 신호를 잃는다.
formal Blind30 v2는 v1 comparator 불변을 요구하므로 기존 버전 직접 수정은 금지한다. 설계 정본:
[`2026-07-31-motion-blind-live-v2-highlight-soft-design`](superpowers/specs/2026-07-31-motion-blind-live-v2-highlight-soft-design.md).

| 제안 | G1 SOT | G2 효과 | G3 측정 | G4 계획 | 판정 | 근거 |
|---|---|---|---|---|---|---|
| 기존 `motion-blind-v1`에서 highlight 비교 제거 | ✗ | ✓ | ✓ | ✗ | **탈락** | formal Blind30 comparator 동결과 기존 provenance를 깨뜨린다 |
| soft 4필드 전체 nonblocking | △ | ✓ | ✓ | ✓ | **보류** | conflict 13/69 감소지만 highlight-only 대비 추가 4건뿐이고 환경·확신도 신호 손실 위험 |
| **새 live v2에서 highlight-only nonblocking + `uncertain` 병합** | ✓ | ✓ | ✓ | ✓ | **adopt** | 9/69(13.0%) conflict 감소, core conflict 유실 0. 2026-08-01 새 live slot만 version snapshot하며 formal/canary·기존 row는 v1 유지 |

**2026-07-31 구현 검증 기록 (append):** Task 1~5를 TDD로 완료해
`IMPLEMENTED_VERIFIED_NOT_DEPLOYED`로 고정했다. v1/formal migration·TEST-SHEET 변경 0,
production DB/R2/Vercel write 0이다. 전체 Web 884, Python 939(환경 고정 절대경로 1 deselect),
disposable PostgreSQL probe residue 0을 통과했다. production 적용과 activation 측정은 Task 6에서만
진행한다.

### 2026-07-31 — RBA 사건 단위 전수 분석 제품 방향 (판정자: Codex + owner 승인)

맥락: owner는 실제 게코 활동 원본을 전부 볼 수 있어야 하고, 모든 활동 사건이 결국 하나
이상의 AI 분석 결과를 가져야 한다고 확정했다. 고정 top-N은 이 요구를 만족하지 못하며 T1
합성점수 v1도 reject다. 모든 원본 clip을 cloud VLM에 각각 보내는 방식은 연속 장면의 중복
비용이 크다. 설계 정본:
[`2026-07-31-rba-event-first-total-coverage-design`](superpowers/specs/2026-07-31-rba-event-first-total-coverage-design.md).

| 제안 | G1 SOT | G2 효과 | G3 측정 | G4 계획 | 판정 | 근거 |
|---|---|---|---|---|---|---|
| 고정 top-N만 사용자 노출·분석 | ✗ | △ | ✓ | ✓ | **탈락** | 실제 활동 전수 열람·전수 분석 요구와 충돌하며 T1도 Δ+5%p로 reject다 |
| 모든 원본 clip별 cloud VLM | ✓ | △ | ✓ | △ | **보류** | 전수 범위는 만족하지만 사건 중복 호출 비용과 결과 중복을 줄이는 계약이 없다 |
| **원본 전부 보존 + 논리적 사건 묶음 + 사건별 local VLM 전수 1차 + 선택적 cloud/HITL** | ✓ | ✓ | ✓ | ✓ | **방향 adopt / Phase 1 shadow 승인** | Data Engine의 전수 원본·사람 GT·provenance와 부합하고 소비처는 사용자 사건 타임라인이다. 사건 할당률·over-merge/split·사람 수정량·local 완료율·케어 FP·cloud 비율·사건당 비용으로 측정한다. owner가 TEST-SHEET 동결과 Fable 5 교차리뷰 뒤 read-only metadata Phase 1만 승인했으며 local VLM 이후 단계는 별도 gate다 |

**안전 경계:** Python Evidence·Gate는 sensor이며 자동 skip 근거가 아니다. 원본 파일은
합치거나 대체하지 않는다. local router v0/v1/v2와 care-guard는 `invalid-for-adoption`을
유지한다. formal Blind30 v2, backlog 300 human-first Gate 감사, future holdout 계약도
변경하지 않는다.

**2026-07-31 Fable 5 교차리뷰 반영 (append):** iTerm의 기존 Claude Code
`Fable 5 / high effort` 세션이 설계·Data Engine·Blind30 v2·decision gate를 read-only로
교차리뷰해 `APPROVE_WITH_CHANGES`를 판정했다. P0는 ① 자유형 사건 GT 정의 부재
② integrity가 새 암묵 skip이 될 위험 ③ Blind30 v2 future pool 노출 위험이었다.
이에 [`rba-event-grouping-shadow-v1 TEST-SHEET`](../experiments/rba-event-grouping-shadow-v1/TEST-SHEET.md)를
동결했다. 인접 pair 3값 GT, 전체 clip accounting, pre-v2 closed-day 표본, metadata-only v0,
camera-night dev/holdout 분리, over-merge 0, 3회 byte-identical을 실행 gate로 추가했다.

### 2026-07-31 — RBA 사건 묶기 shadow v2 기존 inventory 복구 (판정자: Codex + owner 승인)

맥락: shadow v1 production SELECT 결과 closed source `19,279` 중 `18,917`이
`motion_clip_review_slots` 존재만으로 blocked돼 activity candidate가 `261`로 줄었다. 실제 slot은
영상당 reviewer 2명의 배정 자리이며 사람 제출 증거가 아니다. 실제 제출·formal·tutorial·terminal
consensus·frozen manifest만 차단해 다시 계산하면 activity candidate `17,134`, adjacent pair
`16,211`, 54 camera-nights, 3 cameras가 남는다. v1 `<=15s` bin은 1 pair뿐이고 실측 gap 중앙값은
`29.4s`라 현재 캡처 cadence와 맞지 않았다. 설계 정본:
[`2026-07-31-rba-event-grouping-shadow-v2-design`](superpowers/specs/2026-07-31-rba-event-grouping-shadow-v2-design.md).

| 제안 | G1 SOT | G2 효과 | G3 측정 | G4 계획 | 판정 | 근거 |
|---|---|---|---|---|---|---|
| 모든 slot clip 차단을 유지하고 새 영상만 대기 | △ | ✗ | ✓ | ✗ | **reject** | Data Engine의 기존 원본·사람 GT 자산을 활용하지 못하고 slot 배정을 실제 노출로 오인한다. 같은 fixed cutoff에서 데이터가 늘지도 않는다. |
| 기존 clip을 노출 종류와 무관하게 전부 허용 | △ | ✓ | △ | ✓ | **reject** | formal/frozen·실제 제출까지 섞어 같은 연구 목표의 누출을 만든다. |
| **slot-only 허용 + 실제 제출/formal 보호 + 실측 gap v2 + deterministic bounded search** | ✓ | ✓ | ✓ | ✓ | **설계 adopt / v2 승인** | 사건 단위 전수 분석 SOT와 원본 보존·사람 GT 분리를 유지한다. exact 120, camera-night split, over-merge 0, event reduction, reviewer agreement로 측정한다. `<=30 / 30–60 / 60–300s` inventory는 `10,094 / 3,804 / 2,313` pairs이고 read-only witness search 7번째 partition에서 exact 12박·120쌍·unique clip 240·camera cap 36/14를 충족했다. |

**승인 경계:** historical holdout은 내부 사건 경계 타당성만 인증하고 production 일반화는 별도
future holdout으로 남긴다. 새 영상 수집은 v2 시작 조건이 아니다. production DB/R2/service/model
write와 앱 노출은 승인 범위 밖이다.

### 2026-07-31 — owner-final GT 채택·Blind30 비차단·사건 묶기 v2 실행 (판정자: owner)

맥락: paired production 교차검수 88건의 exploratory formal 지표는 decision agreement 80/86
`93.0%`, primary action 77/80 `96.25%`였고 세부 visibility·observed set·target·segment는 더
낮았다. owner는 큰 행동이 일치하면 reviewer 합의 또는 owner 최종 결정된 값을 운영 정본으로
사용하고, 세부 필드는 별도 품질 수준으로 다루기로 했다. formal Blind30 v2는 이 GT의 사용을
막는 재시험이 아니라 reviewer calibration·owner 개입률 감소를 보는 후순위 별도 시험으로
내렸다.

| 제안 | G1 SOT | G2 효과 | G3 측정 | G4 계획 | 판정 | 근거 |
|---|---|---|---|---|---|---|
| Blind30 v2가 끝날 때까지 다른 RBA 연구 중단 | ✗ | ✗ | ✓ | △ | **reject** | 이미 owner-resolved 운영 GT가 있고 사건 경계·Gate·VLM은 서로 다른 연구 질문이다 |
| 일반 행동 GT가 있는 clip을 사건 경계 연구에서 모두 차단 | △ | ✗ | ✓ | ✓ | **reject** | 행동 정답과 boundary 정답을 혼동해 usable pool을 불필요하게 줄인다 |
| **행동 답은 읽지 않고 ordinary clip은 허용, formal/canary/tutorial/frozen만 보호해 event grouping v2 실행** | ✓ | ✓ | ✓ | ✓ | **adopt / 실행 승인** | 최종 runner 재계산 activity candidate `17,628`, adjacent pair `16,633`, 55 camera-nights로 exact-120 witness가 가능하다. TDD·SELECT-only·private artifact·iTerm Fable 5 리뷰를 유지한다 |
| 검증 전 local VLM을 바로 모든 사건에 운영 적용 | ✗ | △ | ✓ | ✗ | **hold** | 모델·가중치·행동 성능 baseline이 없다. event grouping 뒤 owner-final GT baseline과 작은 safety smoke가 먼저다 |

**운영 경계:** legacy 연구 자동화 7개는 owner 승인으로 가역 pause한다. production capture→DB/R2,
Python Evidence worker, 라벨링 웹은 유지한다. event grouping v2 one-shot은 DB SELECT와 R2 HEAD만
사용하며 R2 write/GET·모델·서비스를 건드리지 않는다. local router v0/v1/v2와 care-guard는 계속
`invalid-for-adoption`, 자동 skip은 금지다.

### 2026-07-31 — 사건 경계 사람 검수 채널 + 팀 공용 데이터 현황 (판정자: owner + Codex)

맥락: media eligibility v1이 historical exact-120·R2 HEAD 240/240을 준비했지만 사람의
`same_event / different_event / uncertain`을 안전하게 받는 채널은 없었다. owner는 기존 행동
교차검수를 유지한 채 본인과 지정 peer가 경계를 독립 판정하고, 별도로 승인 팀원 모두가 영상·사람
GT 누적량을 보는 대시보드를 요청·승인했다. 설계 정본:
[`2026-07-31-rba-boundary-review-dashboard-design`](superpowers/specs/2026-07-31-rba-boundary-review-dashboard-design.md).

| 제안 | G1 SOT | G2 효과 | G3 측정 | G4 계획 | 판정 | 근거 |
|---|---|---|---|---|---|---|
| 기존 행동 교차검수 화면에 사건 경계 답을 섞기 | ✗ | △ | △ | △ | **reject** | 행동 GT와 boundary GT의 질문·불변 제출·holdout 공개 시점이 달라 provenance를 섞는다 |
| owner-only 데이터 현황 | △ | △ | ✓ | ✓ | **reject** | 축적 현황은 개인 판정이 아닌 팀 공용 aggregate이며 승인 팀원 모두가 알아야 한다 |
| **별도 2인 boundary assignment + immutable 최초 답 + any-uncertain owner 해결 + 팀 공용 사람-GT aggregate** | ✓ | ✓ | ✓ | ✓ | **구현·배포 승인** | exact-120 사람 GT 채널을 열고 기존 교차검수 write 0, peer 답 누출 0, holdout sealed, GT 분모=행동별 합계, active membership+assignment 이중 guard로 측정한다 |

**안전 경계:** dashboard는 완료된 사람 행동 GT만 집계하며 VLM/Gate/Python Evidence/boundary 답을
행동 정답으로 섞지 않는다. boundary는 자동 사건 병합·원본 병합·자동 skip을 하지 않는다.

**2026-07-31 실행 결과 (append):** exact 120 pair·unique clip 240 선택은 성공했다. canonical
selection은 attempt `1125`, dev/holdout 60/60, split별 bin 20/20/20, camera cap 35/36이었다.
하지만 artifact 전 R2 HEAD 전수검사에서 `228/240`만 확인되고 12개가 실패해
`BLOCKED_MEDIA_PREFLIGHT_FAILED`로 중단했다. replacement·output directory·manifest·worksheet·사람
배정은 0이다. 이는 historical 영상 총량 부족이 아니라 고정 선택 표본의 DB→R2 media integrity
불일치다. 후속 ID-private read-only 감사에서 12건 모두 `404 Not Found`, auth/기타 오류 0으로
분류됐다. R2 404를 source eligibility에서 다루는 재실행 정책은 별도 decision gate/TEST-SHEET
전까지 **hold**다.

### 2026-07-31 — 사건 묶기 R2 media eligibility v1 (판정자: owner + Codex)

맥락: shadow v2 metadata exact-120은 성공했지만 고정 240개 중 12개가 R2 `404 Not Found`였다.
영상 수 부족이 아니라 DB key와 실제 객체의 불일치다. owner는 새 영상 대기 대신 실제 존재하는
historical 영상 풀에서 exact-120을 다시 준비하도록 승인했다. 설계 정본:
[`2026-07-31-rba-event-media-eligibility-v1-design`](superpowers/specs/2026-07-31-rba-event-media-eligibility-v1-design.md).

| 제안 | G1 SOT | G2 효과 | G3 측정 | G4 계획 | 판정 | 근거 |
|---|---|---|---|---|---|---|
| cutoff 이전 약 1.9만 건 모두 HEAD | ✓ | △ | ✓ | ✓ | **보류** | 정확하지만 요청·시간이 크고 full bucket inventory와 최종 HEAD가 더 작다 |
| 240 선택 후 404만 제외해 반복 replacement | △ | ✓ | △ | △ | **reject** | 결과 후 replacement provenance와 종료 횟수가 복잡하다 |
| **R2 LIST inventory와 DB fixed source 교집합 동결 → exact 120 → 최종 HEAD 240** | ✓ | ✓ | ✓ | ✓ | **adopt / read-only 실행 승인** | label·영상 내용을 보지 않는 media availability만 source eligibility로 쓰고, 최종 240/240과 aggregate hash로 측정한다 |

**승인 경계:** DB SELECT, R2 LIST/HEAD, private artifact만 허용한다. DB/R2 mutation, R2 GET,
frame/model/Gate/Python Evidence, service 변경, 404 repair/delete, 사람 배정은 범위 밖이다. iTerm
공식 AppleScript Claude 교차리뷰와 TDD를 통과한 뒤 Mac mini one-shot을 실행한다.

**iTerm Claude Fable 5/high 교차리뷰 (append):** `APPROVE_WITH_CHANGES`, P0 0. P1 여섯 건을
Codex가 현재 boto3 service model·runner와 대조해 전부 채택했다. ① `KeyCount=0`의 정상 Contents
생략 허용 ② duplicate DB key 관련 clip만 diagnostic ③ missing/duplicate/object-absent reason 분리
④ wall-clock hashed manifest 제외 ⑤ short-clip deletion race read-only 사전감사 ⑥ final HEAD
404/auth/invalid/other aggregate 분류. raw key·ID는 계속 출력하지 않는다.

**2026-07-31 실행 결과 (append):** Mac mini read-only one-shot은 cutoff 이전 fixed DB inventory
`19,279`를 R2 LIST 37 pages와 교차해 available `17,702`, object absent/size 0 `1,577`을 확인했다.
missing/duplicate key는 0이고, 선택된 12 camera-night source/accounting은 `5,034/5,034`였다.
exact 120, dev/holdout `60/60`, bin `20/20/20`, 12
camera-nights, unique clip 240, camera cap `36/14`를 충족했고 최종 R2 HEAD `240/240`을 통과했다.
pair/source hash와 `0700/0600` 권한도 독립 재감사했다. DB/R2 mutation·R2 GET·모델·프레임·서비스
변경·사람 배정은 0이다. 판정은 `PREPARED_MEDIA_VERIFIED_AWAITING_HUMAN_CHANNEL`; 다음 gate는
사람 검수 채널 동결이며 사건 묶기 채택과 local VLM 실행은 아직 hold다.

### 2026-08-02 — Mac mini local VLM 사건 경계 baseline v1 (판정자: Codex + owner 승인)

맥락: 두 reviewer와 Owner가 development 경계 74개를 모두 확정해 78개 clip을 사람 사건 21개로
묶었다. gap-only 규칙은 over-merge 0을 지키면 same 경계를 하나도 회수하지 못해 utility hold다.
owner는 최신 local VLM을 다시 조사하고 Mac mini에 격리 설치·커스터마이징·구동한 뒤 결과보고서까지
자동 진행하도록 승인했다. 공식 자료 재감사 결과 M1 16GB에서 비교 가능한 Apache-2.0 후보는
`MiniCPM-V 4.6` 1B Ollama 양자화와 `Qwen3-VL 2B` Ollama 양자화다.

| 제안 | G1 SOT | G2 효과 | G3 측정 | G4 계획 | 판정 | 근거 |
|---|---|---|---|---|---|---|
| 기존 7~8B local VLM을 곧바로 모든 사건에 연결 | ✗ | △ | △ | ✗ | **reject** | 모델·가중치·사건 경계 성능 baseline이 없고 production 자동 병합으로 바로 이어질 위험이 있다 |
| 74개 development 경계를 보며 prompt를 반복 튜닝 | △ | △ | ✗ | △ | **reject** | 같은 정답을 보고 설정을 바꾸면 결과가 낙관적으로 오염돼 모델 비교가 불가능하다 |
| **고정 8-frame contact sheet + 고정 prompt로 1B/2B 두 모델을 74개 전수 비교** | ✓ | ✓ | ✓ | ✓ | **baseline 실행 승인** | Data Engine v1의 사람 사건 GT→pretrained baseline 순서와 부합한다. over-merge·same recall·완주율·구조화 응답률·latency·메모리·disk를 같은 입력으로 측정하며, 모델 설치와 결과는 Mac mini 격리 경로에만 둔다 |

**안전 경계:** development 74개만 사용하고 historical/future holdout은 열지 않는다. R2는 GET만,
DB는 SELECT만 허용하며 사람 답·GT·Python Evidence·Gate·production service를 수정하지 않는다.
결과가 좋아도 자동 사건 병합·자동 skip·production VLM/router 활성화는 별도 future holdout과
승인 전까지 금지한다. 모델별 full run을 시작한 뒤 prompt·sampler를 고치지 않으며 실패도 그대로
점수화한다.

**2026-08-02 iTerm Claude 교차리뷰 (append):** 공식 AppleScript로 기존 Claude 세션에 설계만
전달해 P0 0, P1 2, P2 4를 받았고 전부 채택했다. 두 이미지 주의력 합성 smoke와 공정한 combined
fallback, B 시작부 early-heavy sampling, Ollama `format/num_ctx/seed`, 2초 자원 측정·중단 기준,
Wilson 95% CI와 self-adjudication caveat, development 후보 한정 문구를 설계와 TEST-SHEET에
반영한다.

**2026-08-02 Claude 계획 재검수 (append):** P0 0, P1 4를 전부 채택했다. measured request마다
unload해 latency를 왜곡하던 모순을 `keep_alive=15m`+모델 전환 시 명시적 unload로 고쳤고,
representation별 sheet 수 `148/74`, timeout 120초·retry 0, 선행 분석 `0600` salt 재사용을
TEST-SHEET와 구현 계획에 동결했다.

**2026-08-02 Claude 구현 검수 (append):** P0 0, P1 3을 전부 채택했다. combined fallback용 실제
prompt 문장과 `think=false`를 TEST-SHEET에 동결했고, two-image smoke의 4xx를 fallback으로
분류하며 인프라 실패는 전파한다. resource probe timeout/실패·monitor thread 예외는 모두
`abort`로 fail-closed한다. 비차단 P2였던 prompt digest 독립 재검증과 run 후 model digest 재확인도
함께 반영한다.

**2026-08-02 Claude 구현 최종 재검수 (append):** P0 0, 잔여 P1 1을 채택했다. runner에만 있는
`load_sec` 때문에 전체 summary byte-equivalence가 원천적으로 불가능하므로, 독립 재계산 계약을
모델별 `score`·`latency_sec` exact subtree 일치로 고정하고 cold-load metadata는 비교에서
제외했다.

**2026-08-02 실행 결과 (append):** exact HEAD `30eab8c5bb27083c07b5073bd011e322ab5135bb`로
Mac mini measured run을 수행했다. MiniCPM-V 4.6은 74/74를 완주했지만 human-different 17/17을
전부 same으로 합쳐 `REJECT_SAFETY`다. Qwen3-VL 2B는 47/74 모두 empty content·schema 0이었고
swap delta가 사전 한도 `+1GiB`를 넘어 primary `REJECT_RESOURCE`로 fail-closed했다. schema
0/47의 `REJECT_RELIABILITY`는 부수 관찰이다. retry·resume·설정
변경은 0이고 실행 뒤 model unload를 확인했다. 최종 판정은 `NO_DEVELOPMENT_CANDIDATE`; 다음
runtime/모델 비교는 새 TEST-SHEET 전까지 hold다. production 연결·holdout 접근·DB/R2/GT/service
write는 0이다.

### 2026-08-02 — Production local VLM clip shadow canary v1 (판정자: owner + Codex)

맥락: 사건 경계 baseline v1은 `NO_DEVELOPMENT_CANDIDATE`였지만 owner는 오늘 밤 실제 production
영상에서 local VLM을 구동하고 내일 확대 여부를 결정하길 승인했다. 실패한 경계 모델을 자동 사건
병합에 쓰지 않으면서도 운영 증거를 만들기 위해 clip-first private shadow로 범위를 줄였다. 설계 정본:
[`2026-08-02-production-local-vlm-clip-shadow-canary-v1-design`](superpowers/specs/2026-08-02-production-local-vlm-clip-shadow-canary-v1-design.md).

| 제안 | G1 SOT | G2 효과 | G3 측정 | G4 계획 | 판정 | 근거 |
|---|---|---|---|---|---|---|
| MiniCPM/Qwen3 경계 결과를 사용자에게 즉시 노출 | ✗ | △ | △ | ✗ | **reject** | safety/resource/reliability 탈락을 사용자에게 전파한다 |
| 새 사건 묶기 모델이 완성될 때까지 production 입력을 전혀 쓰지 않음 | △ | ✗ | ✗ | △ | **hold** | 안전하지만 오늘 밤 실제 운영 자원·관찰 품질 증거를 만들지 못한다 |
| **새 clip 최대 20개를 Gemma 3 4B가 관찰하고 private JSONL에만 기록** | ✓ | ✓ | ✓ | ✓ | **설계·구현·야간 구동 승인** | 원본·GT·라우팅·UI 영향 0으로 실제 production 입력의 schema·latency·resource·관찰 품질을 내일 바로 감사할 수 있다 |

**안전 경계:** 새 clip 한 개를 임시 사건 한 개로 유지한다. DB SELECT, R2 HEAD/GET, Mac private
artifact만 허용한다. 기존 production DB/VLM job/GT/submission/service 설정을 수정하지 않고,
별도 임시 LaunchAgent label 하나만 추가한다. 사용자 노출,
자동 사건 병합·skip·cloud 차단은 금지한다. 20개 또는 07:00 KST에 종료하며 timeout/schema 실패는
retry하지 않는다. Gate A synthetic 3/3과 자원 preflight 전 LaunchAgent load는 금지한다.

### 2026-08-02 — Production local VLM clip shadow canary v2, individual 12 frames (판정자: owner + Codex)

맥락: v1은 6-frame 3×2 contact sheet에서 static과 moving을 구분하지 못해 production request 0으로
종료됐다. owner는 다음 기본값을 개별 12프레임으로 지정하고 구현·실행을 승인했다. 설계 정본:
[`2026-08-02-production-local-vlm-clip-shadow-canary-v2-design`](superpowers/specs/2026-08-02-production-local-vlm-clip-shadow-canary-v2-design.md).

| 제안 | G1 SOT | G2 효과 | G3 측정 | G4 계획 | 판정 | 근거 |
|---|---|---|---|---|---|---|
| contact sheet prompt를 계속 튜닝 | ✗ | △ | ✗ | △ | **reject** | 이미 같은 표현에서 세 번 Gate 실패해 결과 후 튜닝이 된다 |
| 12장을 다시 한 contact sheet로 합침 | ✗ | △ | ✓ | ✓ | **reject** | v1의 패널별 상대 위치 실패 원인을 유지한다 |
| **5~95% 균등 개별 이미지 12장 + static/moving 반대 대조 Gate** | ✓ | ✓ | ✓ | ✓ | **설계·구현·조건부 구동 승인** | 짧은 행동 누락 가능성을 줄이고 contact-sheet 좌표 혼동을 제거하며 Gate/schema/resource/latency로 측정 가능하다 |

**안전 경계:** v2 Gate A 통과 전 production DB/R2를 열거나 LaunchAgent를 만들지 않는다. PASS 뒤에도
private max20 shadow만 허용하며 사용자 노출·GT/write·사건 병합·skip·cloud 차단은 금지한다.

### 2026-08-02 — Local VLM Mac Studio 구매 판단 Gate v1 (판정자: owner + Codex)

맥락: Mac mini 4B clip canary는 개별 12프레임에서도 합성 static/moving을 구분하지 못했다. owner는
더 큰 Mac Studio가 실제 해결책인지 구매 전에 확신할 수 있는 실험을 승인했다. 현재 32GB MacBook에서
모델 크기와 계열을 함께 올려 품질 향상이 하드웨어 용량에서 오는지 분리한다. 설계 정본:
[`2026-08-02-local-vlm-mac-studio-purchase-gate-v1-design`](superpowers/specs/2026-08-02-local-vlm-mac-studio-purchase-gate-v1-design.md).

| 제안 | G1 SOT | G2 효과 | G3 측정 | G4 계획 | 판정 | 근거 |
|---|---|---|---|---|---|---|
| Mac Studio를 먼저 구매한 뒤 큰 모델을 탐색 | △ | △ | ✗ | ✗ | **hold** | 품질 실패가 모델·입력·하드웨어 중 무엇 때문인지 분리되지 않는다 |
| 같은 Gemma 3 4B의 Q8만 재시험 | ✓ | △ | ✓ | ✓ | **비교군만 승인** | 양자화 가설은 확인하지만 큰 모델 필요성을 단독으로 증명하지 못한다 |
| **4B Q8→12B→8B→30B 고정 사다리, 합성 선행 후 development 74경계** | ✓ | ✓ | ✓ | ✓ | **실행 승인** | 같은 입력·gate로 작은 모델과 큰 모델을 비교해 구매 필요성과 기대효과를 직접 측정한다 |

**안전 경계:** MacBook private artifact와 Mac mini 기존 frozen manifest/input/media의 read-only 복사만
허용한다. historical/future holdout, production DB/R2/service/plist, 자동 병합·skip·GT·사용자 노출은
0이다. 30B만 통과해도 구매 판정은 별도 64GB 장비와 future holdout 전까지 `PENDING_HOLDOUT`이다.

**iTerm Claude 교차리뷰 (append):** `APPROVE_WITH_CHANGES`, P0 0, P1 3을 받았다. 모델별
PASS/품질/합성/자원/tag 상태와 구매 판정 우선순위, 4개 tag·digest 사전검증, 실제 8-image boundary
schema의 same/different 합성 4회를 전부 채택했다. 추가로 development 74의 누적 재사용 caveat,
상시가동 16GB host 교체라는 구매 프레이밍, 32GB 자원 한도 완화 근거도 반영한다.

**Claude 계획 재검수 (append):** P0 0, P1 1을 채택했다. frozen combined JPEG cell을 잘라 쓰면
과거 축소·JPEG 열화가 남아 큰 모델 효과를 왜곡할 수 있다. 대신 같은 private artifact의 media 78개를
ledger SHA로 확인하고, 원본 A/B contact sheet 조합의 재생성 SHA가 frozen combined SHA와 exact
유일 일치할 때만 pair 대응을 복원한 뒤 768px 개별 8장을 재추출한다. DB/R2/GT 재조회는 계속 0이다.

**Claude 구현 검수 (append):** 1차 P0 1·P1 1을 전부 채택하고 재검수에서 P0/P1 0을 확인했다.
synthetic의 resource abort 재전파, HTTPError와 timeout/connection 분리, 단계별 terminal status,
swap 중간 최고치, prompt 개행, 독립 recompute의 input/human 대조를 반영했다. 실제 source preflight는
media/input SHA `78/78·74/74`, regenerated exact unique mapping `74/74`, 768px 개별 input `592`다.

**2026-08-02 실행 결과 (append):** MacBook Pro M5 32GB, Ollama 0.32.5, exact HEAD
`b005d4d5fa71f742cd98974dbf91ea5954912955`에서 measured run을 끝냈다. Gemma3 4B Q8은 합성
`4/18`, Qwen3-VL 8B는 `12/18`로 둘 다 `SYNTHETIC_GATE_FAIL`이다. Gemma4 12B는 16건 뒤
swap `+2.316GiB`, Qwen3-VL 30B-A3B는 scored request 전 swap `+2.566GiB`로 `RESOURCE_FAIL`했다.
따라서 판정은 `INCONCLUSIVE_NEEDS_COMPATIBLE_HARDWARE`; 구매 전 64GB 대여 장비에서 같은 18개
합성 Gate를 먼저 재실행한다. development model request 0(입력 preflight만 완료)·holdout 접근 0,
production mutation은 0이고 독립 recompute의 status/verdict와 manifest/results SHA가 runner와
exact 일치했다.

**Claude 결과보고서 검수 (append):** P0/P1 0, `REVIEW_REPORT_CLEAR`다. 자원 실패를 품질 실패로
해석하지 않았고, “지금 구매 근거 없음”과 “큰 모델 무용도 미확정”을 함께 유지했다. P2로 지적된
development 입력 preflight와 model request 0의 표현도 분리해 보정했다.

### 2026-08-03 — OpenAI VLM 월 2만 영상 비용 선택지 (판정자: owner + Codex)

맥락: local router v0/v1/v2와 care-guard는 `invalid-for-adoption`이고, 2026-08-02 Mac mini local
VLM baseline·clip canary도 safety/reliability/synthetic Gate를 통과하지 못했다. 32GB MacBook의
12B/30B 비교는 resource fail이라 더 큰 local 모델의 품질도 미확정이다. owner는 월 2만 영상을
VLM 분석까지 수행하는 비용 대비 효율을 문서화하되 현재는 고민 중인 선택지로 공유하라고 했다.
설계 정본:
[`2026-08-03-openai-vlm-monthly-20k-cost-options-design`](superpowers/specs/2026-08-03-openai-vlm-monthly-20k-cost-options-design.md).

| 제안 | G1 SOT | G2 효과 | G3 측정 | G4 계획 | 판정 | 근거 |
|---|---|---|---|---|---|---|
| Mac Studio를 먼저 구매해 local 30B 전수 운영 | △ | △ | ✗ | ✗ | **hold** | 64GB 실행·품질·처리량·future holdout 근거가 없고 초기 투자가 비가역적이다 |
| GPT-5.6 Terra로 20,000개를 즉시 전수 production 분석 | ✓ | △ | △ | ✗ | **hold** | 약 21만 원/월 Batch 추정이나 우리 GT 품질·실제 token·보존 계약이 미측정이다 |
| **GPT-5.4 mini 전수 + Terra 10~20% 재검수의 300건 파일럿을 설계** | ✓ | ✓ | ✓ | ✓ | **preferred option / under review** | 모든 영상 1차 VLM을 유지하면서 추정 월 11만~13만 원이고, 300건에서 품질·실청구·escalation 비율을 비교할 수 있다 |

**현재 경계:** 이 로그는 production 채택이나 파일럿 실행 승인이 아니다. `OPTION_UNDER_REVIEW`로만
기록한다. 별도 TEST-SHEET와 Owner 승인 전 API key·DB/R2/service·GT·submission·사건 병합·자동
skip·cloud 차단·사용자 노출 변경은 금지한다. Batch의 24시간/50% 할인과 모델 가격은 2026-08-03
OpenAI 공식 문서를 기준으로 했고, 환율·프레임 크기·output·retry가 바뀌면 원화 추정도 다시 계산한다.

### 2026-08-03 — OpenAI 구독 VLM 사건 경계 v1 (판정자: owner + Codex, Claude 교차검수)

맥락: owner는 API 투입 전에 Mac mini의 ChatGPT 구독 Codex CLI로 local VLM과 같은 시험지를
비용 후보 GPT 모델별로 즉시 실행하고 성적표·Slack 보고까지 승인했다. 입력은 사람-final development
74경계의 기존 combined JPEG와 동일 prompt/schema다.

| 제안 | G1 SOT | G2 효과 | G3 측정 | G4 계획 | 판정 | 근거 |
|---|---|---|---|---|---|---|
| GPT 결과를 바로 자동 사건 묶기에 연결 | ✗ | △ | ✓ | ✗ | **reject** | 세 모델 over-merge 12/14/10으로 safety Gate 실패 |
| schema 222/222만 보고 월 2만 행동 VLM 품질 확정 | ✗ | △ | ✗ | ✗ | **reject** | 기술 실행 성공과 행동 정확도는 다른 질문이다 |
| **사건 묶기는 hold하고 행동/관찰 300건 API pilot을 별도 동결** | ✓ | ✓ | ✓ | ✓ | **preferred next / not started** | 경계 실패를 행동 실패로 확대하지 않으면서 실제 품질·usage·비용을 측정한다 |

**실행 결과:** GPT-5.4 Mini/Luna/Terra는 각각 schema `74/74`, error/quota 0을 달성했지만
over-merge `12/14/10`으로 모두 `REJECT_SAFETY`다. Claude 계획 검수에서 최초 partial 67건의 GT
격리 P0를 발견해 성적 사용 없이 중단했고, 새 run은 pair별 image-only cwd·GT-free ledger·CLI
tool/file event 0 hard gate로 재실행했다. 독립 recompute 222건 exact 일치, production
API/DB/R2/GT/사건/skip/UI/service 변경 0이다. 상세:
[`REPORT`](../experiments/openai-subscription-vlm-event-boundary-v1/REPORT.md).

### 2026-08-03 — VLM 사건 경계 밀집 v2 교정 재시험 (판정자: owner + Codex, Claude 교차검수)

맥락: owner가 기존 전체구간 4+4 입력은 실제 경계 대신 전체 닮음을 보게 한다고 지적했고, 같은
owner-final 74경계를 A끝6+B시작6으로 GPT 3개와 local VLM 2개에 전부 다시 시험하도록 승인했다.

| 제안 | G1 SOT | G2 효과 | G3 측정 | G4 계획 | 판정 | 근거 |
|---|---|---|---|---|---|---|
| 기존 4+4 결과를 모델 채택 근거로 유지 | ✗ | ✗ | ✗ | ✗ | **superseded** | 실제 경계 정보가 아닌 전체구간 닮음을 과대표현 |
| dense 6+6 결과로 자동 사건 묶기 연결 | ✗ | △ | ✓ | ✗ | **reject** | 최선 Terra도 over-merge 7로 safety Gate 실패 |
| 같은 74개에서 frame/prompt 추가 튜닝 | △ | △ | △ | ✗ | **stop** | 입력 교정은 일부 개선만 만들었고 미촬영 구간 정보 한계는 해소 못 함 |
| **owner-final 사건 유지, 행동·관찰 VLM은 별도 시험으로 분리** | ✓ | ✓ | ✓ | ✓ | **adopt current boundary policy** | 경계 실패를 행동 의미 분석 실패로 확대하지 않음 |

**실행 결과:** dense JPEG 148/148 hash, GPT 222 ledger + local 148 ledger를 완주했다. GPT
Mini/Luna/Terra over-merge `11/10/7`, MiniCPM `17`; Qwen은 two-image smoke 실패로 본 호출을
막았다. runner와 독립 recompute 5/5 exact, ledger human key 0/370, local context/resource gate 통과,
production write 0이다. Claude 계획 리뷰 `P0=0/P1=0`. 상세:
[`REPORT`](../experiments/vlm-event-boundary-dense-v2/REPORT.md).

### 2026-08-03 — RBA OpenAI 전환·Dataset v2·R2 초기 영상 정리 (판정자: owner + Codex)

맥락: local router v0/v1/v2와 care-guard는 이미 `invalid-for-adoption`이었고, local VLM은
Mac mini safety/reliability gate를 반복 실패했다. 자동 사건 묶기도 owner-final 74경계의 dense
입력에서 최선 모델조차 over-merge 7로 안전 기준을 통과하지 못했다. Claude CLI 영상 판독은
비용이 높아 owner가 종료했다. 동시에 KST 2026-06-30~07-15 초기 R2 원본 11,629개 중 현재
행동 GT 정본은 폐기된 옛 `basking/static` 4개뿐이고, Owner 자격검사에서 게코 없음 23개와
실제 활동 없음 23개를 직접 확인했다.

| 제안 | G1 SOT | G2 효과 | G3 측정 | G4 계획 | 판정 | 근거 |
|---|---|---|---|---|---|---|
| local VLM/router/자동 사건 묶기/Claude CLI를 추가 튜닝 | ✗ | ✗ | △ | ✗ | **stop / archive** | 반복 실패·비용·owner 종료 결정. 사람 GT와 제품 결과를 개선하는 다음 독립 근거가 없다 |
| 최근 새 영상만으로 데이터셋을 다시 시작 | △ | ✗ | ✓ | ✓ | **reject** | 희귀·복수 행동이 부족하고 기존 사람 GT 자산을 버린다 |
| 기존 dataset-203 폴더에 새 GT를 직접 추가 | △ | △ | ✗ | ✓ | **reject** | 과거 provider 예측이 파일명/manifest에 결합돼 재현성과 새 모델 비교를 섞는다 |
| **기존 197 기준판 + 최근 Owner-final GT의 Dataset v2, 예측 ledger 분리** | ✓ | ✓ | ✓ | ✓ | **adopt** | 행동 다양성과 실제 운영 분포를 함께 쓰며 provider/model 변경과 GT를 분리한다 |
| 비슷해 보이는 초기 영상을 모델로 자동 삭제 | ✗ | △ | ✗ | △ | **reject** | local/Gate/Evidence 실패 이력상 정상 원본 오삭제를 막을 수 없다 |
| **Owner 확정 46 삭제 + 같은 두 camera-day 951 격리 + 904 사람 검수** | ✓ | ✓ | ✓ | ✓ | **adopt / production cleanup 승인** | exact `951/46/1 GT 보호/904`, confirmed-invalid∩canonical-GT=0, R2 HEAD 951/951로 측정하고 copy→HEAD→DB CAS→source delete 순서로 복구 가능하다 |
| **Dataset v2 뒤 OpenAI API 행동·관찰 pilot** | ✓ | ✓ | ✓ | ✓ | **preferred next / pilot 별도 gate** | ChatGPT 구독과 별도 key/billing을 준비하고 실제 품질·token·비용을 작은 versioned 시험으로 측정한다 |

**당시 안전 경계:** Python/OpenCV는 media preparation만 유지한다고 정했다. 이 역할 범위는 바로
아래 GME 후속 결정으로 확장됐지만, 삭제 권한은 계속 immutable Owner 판정만 가진다.
quarantine/uncertain은 연구·Dataset·API 입력에서 제외하지만 자동 삭제하지 않는다.
`motion_clips`, 사람 GT, boundary/submission/consensus 원장은 삭제하지 않는다. Git commit/push와
OpenAI production 호출은 이 승인에 포함되지 않는다. 설계:
[`2026-08-03-rba-openai-reset-and-dataset-v2-design`](superpowers/specs/2026-08-03-rba-openai-reset-and-dataset-v2-design.md).

### 2026-08-03 — Gecko Motion Engine v1 정본 전환 (판정자: owner + Codex)

맥락: 3클립 30fps Python→OpenAI smoke에서 Python은 디코딩·무결성·밝기·흔들림 원장을 정상
생산했지만, 혀 움직임과 느린 이동을 의미구간으로 고르지 못했다. owner는 Python을 VLM skip
문지기로 쓸 필요가 크지 않다고 판단했고, 대신 Gecko Vision Gate를 계속 업그레이드하면서 검출·추적·
노이즈 제거·실제 움직인 시간을 Python이 담당하도록 승인했다. 이름은 Gecko Motion Engine(GME)으로
확정했다.

| 제안 | G1 SOT | G2 효과 | G3 측정 | G4 계획 | 판정 | 근거 |
|---|---|---|---|---|---|---|
| 현재 화면 변화량을 바로 사용자 활동량으로 표시 | ✗ | △ | ✗ | △ | **reject** | 그림자·IR·노출·카메라 흔들림이 섞이고 미세 혀 움직임·느린 이동을 놓친다 |
| Python을 media preparation에만 제한하고 Gate 연구 종료 | △ | ✗ | ✓ | ✓ | **reject** | RBA의 장기 핵심 지표인 게코 활동시간을 만들 경로가 사라진다 |
| **GME가 Gate+tracker+noise normalizer로 verified moving time을 shadow 측정** | ✓ | ✓ | ✓ | ✓ | **adopt / SOT 승인** | 게코 몸의 움직임과 화면 변화를 분리하고 사람 시간구간 GT로 오차를 측정할 수 있다 |

**정의:** 사용자 대표값은 `verified_moving_sec_any_gecko`다. 두 마리가 동시에 움직여도 실제 시계
시간의 합집합으로 센다. 내부 `moving_gecko_seconds`는 개체별 시간을 합한다. 상태는 `moving /
static / not_visible / unknown / camera_motion`이며 검출 실패·가림은 `unknown`이다.

**현재 경계:** 과거 `Python Evidence` 이름과 결과는 provenance로 보존한다. production
`activity-v1`, DB/R2, Flutter, worker, Gate checkpoint는 이번 SOT 커밋에서 바꾸지 않는다. GME는
행동명·하이라이트·VLM route·자동 skip·삭제를 결정하지 않는다. 다음 허용 단계는 사람 활동시간 GT와
offline Gate/tracker baseline TEST-SHEET 작성이다. 설계:
[`2026-08-03-gecko-motion-engine-v1-design`](superpowers/specs/2026-08-03-gecko-motion-engine-v1-design.md).

### 2026-08-03 — GME 신규 전수 shadow·기존 영상 직접 교체 (판정자: owner + Codex)

맥락: GME 역할을 게코 검출·추적·노이즈 분리·실제 움직인 시간 계측으로 확정한 뒤, owner는 24시간
Python Evidence 병행 없이 오늘 밤 GME로 직접 교체하고 KST 2026-07-15 이후 정상 기존 영상도 전부
처리하도록 승인했다. 별도 YOLO 연구 작업을 읽기 전용 검토해 detector는 행동 판독기가 아니며,
관측·추적·보간·판단불가 분리와 tracking quality가 필수임을 보강했다.

| 제안 | G1 SOT | G2 효과 | G3 측정 | G4 계획 | 판정 | 근거 |
|---|---|---|---|---|---|---|
| 기존 Python Evidence 이름만 GME로 변경 | ✗ | ✗ | △ | ✗ | **reject** | 현재 worker는 sparse 12-frame Gate+화면 변화량이며 multi-gecko tracking·실제 움직인 시간·관측 출처가 없다 |
| GME 정확도 연구가 끝날 때까지 production 실행 보류 | △ | △ | ✓ | ✓ | **reject for hidden shadow** | 사용자 노출은 막아야 하지만 hidden shadow 자료가 없으면 Gate/tracker 실패와 실제 운영 부하를 측정할 수 없다 |
| **10-clip operational smoke 직후 Python Evidence를 가역 중단하고 GME 신규 전수+07-15 이후 eligible backfill 직접 교체** | ✓ | ✓ | ✓ | ✓ | **adopt / direct-cutover 승인** | 사용자 값은 불변인 채 실제 운영 coverage·lag·tracking quality·unknown을 축적하고, 실패 시 legacy worker를 다시 켤 수 있다 |

**경계:** 한 영상 1회 디코딩, 0.5초 Gate anchor+confidence-drop 재검출, 전 프레임 tracker,
`observed/tracked/interpolated/unknown` 출처와 1초 초과 gap=`unknown`을 고정한다. DB 영구 요약, R2
압축 trajectory, 14일 debug artifact만 쓰고 원본·GT·Flutter·`activity-v1`·VLM route·자동 skip·삭제는
변경하지 않는다. 신규 live가 항상 우선이며 lag p95>15분이면 backfill만 중단한다.

### 2026-08-10 — 공개 YOLO 게코 감지 시연 + 초대 팀원 bbox 기여 (판정자: owner)

맥락: 라벨링 웹에서 외부 사용자가 사진·영상을 올려 연구용 게코 bbox를 확인하고, 별도로 초대된
팀원이 사람 bbox를 blind-first로 만들어 다음 detector dataset 후보를 쌓는 방향을 owner가 승인했다.
현재 v2.1 최종 checkpoint는 없으므로 실제 모델 연결보다 provider 계약·가짜 구현·사람 GT 승격
경계를 먼저 고정한다. 설계 정본:
[`2026-08-10-yolo-demo-team-contribution-design`](superpowers/specs/2026-08-10-yolo-demo-team-contribution-design.md).

| 제안 | G1 SOT | G2 효과 | G3 측정 | G4 계획 | 판정 | 근거 |
|---|---|---|---|---|---|---|
| Vercel route에서 YOLO를 직접 실행 | △ | ✗ | ✓ | △ | **reject** | 영상 프레임 추론을 Vercel 수명·메모리·CPU에 결합하고 Mac mini checkpoint 교체 경계를 잃는다 |
| 브라우저가 Mac mini worker에 직접 업로드 | △ | ✓ | ✓ | △ | **reject** | worker 주소·인증·CORS를 공개 클라이언트에 노출하고 abuse 방어와 provider 교체가 브라우저 계약에 샌다 |
| **Vercel 검증/API → 주입 가능한 inference worker adapter → versioned detection 응답** | ✓ | ✓ | ✓ | ✓ | **adopt / 구현 승인** | 브라우저에는 same-origin 계약만 보이고 실제 checkpoint는 worker 뒤에서 교체한다. fake로 schema·UI·권한을 먼저 검증하고 고정 시험·future holdout·Owner 승인 뒤에만 active version을 바꾼다 |

**측정:** 공개 API의 형식·크기·rate-limit 거부율, image/video schema 성공률, 처리 지연,
임시 객체 TTL 준수, 팀원 blind 제출 완주율, reveal 전 prediction 노출 0건, Owner 승인 후보 수,
고정 시험/future holdout gate와 activation/rollback 원장 재현성을 기록한다.

**안전 경계:** 공개 업로드는 기본 학습 제외이며 opt-in도 후보일 뿐 GT가 아니다. 사람 blind 제출과
reveal 후 수정은 분리·append-only로 남고 Owner 승인된 사람 라벨만 Dataset 버전에 연결한다.
모델 출력은 GT·자동 skip·삭제·행동명 근거가 아니다. local VLM/router/Claude 영상 판독/자동 사건
묶기를 재개하지 않는다. production DB 적용, R2 write, 서비스 변경, Vercel 배포, 실제 checkpoint
연결은 이번 구현 범위 밖이다.
### 2026-08-10 — YOLO26n v2.2 재현율 우선 보강학습 (판정자: owner + Codex)

맥락: 사람 bbox Dataset v2.1 698장으로 YOLO26n 960px를 100 epoch 학습했다. 최고점은 80 epoch였고,
새 camera-night development holdout 34장·23 bbox에서 v2.0 대비 recall `0.478→0.565`,
mAP50 `0.491→0.640`, mAP50-95 `0.270→0.317`로 개선됐지만 precision은 `0.711→0.674`로 내려갔다.
owner는 precision 0.60 하한 안에서 게코 미탐을 우선 줄이는 방향을 승인했다.

| 제안 | G1 SOT | G2 효과 | G3 측정 | G4 계획 | 판정 | 근거 |
|---|---|---|---|---|---|---|
| 같은 698장으로 epoch만 연장 | △ | ✗ | ✓ | ✓ | **reject** | 80 epoch 이후 mAP50-95가 `0.390→0.358`로 하락해 추가 반복의 기대효과가 없다 |
| 무작위 프레임 대량 추가 | ✓ | △ | △ | △ | **reject** | 인접 frame·camera-night 중복이 장수만 키우고 어려운 미탐을 직접 줄인다는 보장이 없다 |
| **hard positive 220 + hard negative 100 표적 후보를 Owner blind bbox로 확정하고 전체 데이터 재학습** | ✓ | ✓ | ✓ | ✓ | **adopt design** | GME의 게코 검출·추적 기반을 개선하며, fixed-threshold recall≥0.70·v2.1 대비 +10%p·precision≥0.60을 새 future holdout 120장으로 검증한다 |

**경계:** 모델·GME는 후보 탐색에만 쓰고 CVAT에는 예측 bbox를 주지 않는다. 현재 34장은
development로 강등하며 최종 시험에 재사용하지 않는다. future holdout은 이후 production-purpose
영상 120장 이상·양성/음성 각 60장 이상·최소 3카메라·6 camera-night로 새로 봉인한다. YOLO 결과로
행동·하이라이트·GT·부재·자동 skip/route/삭제를 확정하지 않으며, DB·R2·production active model은
별도 Owner 승인 전까지 변경하지 않는다. 설계:
[`2026-08-10-yolo26n-v22-recall-reinforcement-design`](superpowers/specs/2026-08-10-yolo26n-v22-recall-reinforcement-design.md).

### 2026-08-14 — YOLO26n v2.5 historical hard-case 보강 후보 (판정자: owner + Codex)

맥락: v2.4의 train 1,458장은 과거 Gecko Vision Gate 운영 사람 GT를 이미 일부 포함하고 있고,
v2.4b validation 153장 후처리 선택은 끝났지만 frozen-at 이후 production future footage가 없어
formal future holdout은 shortage로 멈췄다. owner는 기존 평가 자산과 shortage 결과를 보존한 채,
과거 Gate GT의 미포함분과 Owner 개인 영상 35개에서 다음 개발용 사람 bbox 후보를 만들도록 승인했다.

| 제안 | G1 SOT | G2 효과 | G3 측정 | G4 계획 | 판정 | 근거 |
|---|---|---|---|---|---|---|
| 과거 Gate GT를 lineage 감사 없이 다시 합치기 | △ | ✗ | ✗ | ✗ | **reject** | v2.4 train에 이미 포함된 이미지와 평가 역할 누수를 구분할 수 없다 |
| Owner 영상에서 v2.4 예측 bbox를 그대로 학습 label로 사용 | ✗ | △ | ✗ | △ | **reject** | detector 오차를 정답으로 되먹임하고 blind 사람 검수 경계를 깨뜨린다 |
| validation 153·fixed-test 151·Owner external 60을 hard-case 탐색에 재사용 | ✗ | △ | ✗ | △ | **reject** | 불변 평가 자산을 선택 과정에 노출해 이후 비교를 오염시킨다 |
| **Gate 미포함 train-eligible GT 감사 + Owner 35개 deterministic hard-case blind bbox queue** | ✓ | ✓ | ✓ | ✓ | **adopt / development-only queue** | GME 검출기 지속 개선과 사람 bbox append-only SOT에 맞고, lineage·global SHA/dHash·bucket·blind acceptance를 독립 검증하며 학습 전 사람 검수에서 멈춘다 |

**측정·중단 경계:** Gate 후보는 provenance·license·현재 `gecko` bbox semantics와 v2.4 train 포함
여부를 exact image/source lineage로 검증한다. Owner 영상은 read-only decode·결정론적 frame mining 뒤
기존 1,822 historical fingerprint와 전역 SHA/dHash 중복을 제거하고, frozen v2.4 예측은 hard-case
triage에만 쓴다. CVAT에는 익명 이미지와 빈-frame 허용 계약만 제공하고 예측 bbox·source identity를
숨긴다. 사람 검수 전 v2.5 학습은 시작하지 않으며, validation 153·fixed-test 151·Owner external 60과
v2.4b freeze/locks/shortage artifact는 불변이다. 이번 queue를 formal future holdout으로 주장하지 않고,
DB·R2·service·production model·GME·labeling web write/deploy는 0으로 유지한다.

### 2026-08-14 — YOLO26n v2.5 Owner-only 재개 (판정자: owner + Codex)

맥락: Gate `operational+labeled` 1,951건 가운데 현재 명시 lineage는 accepted 569건과 positive
quarantine 9건, 합계 578건뿐이었다. 결손 1,373건을 추정하지 않는 full-set 계약은 올바르게
fail-closed했지만, Gate와 무관한 Owner 개인 MOV 35개의 development-only hard-case mining까지 막을
필요는 없다. owner는 Gate 전체를 후보·학습·선택에서 격리하고 Owner-only queue를 새 attempt에서
재개하도록 승인했다.

| 제안 | G1 SOT | G2 효과 | G3 측정 | G4 계획 | 판정 | 근거 |
|---|---|---|---|---|---|---|
| 명시 lineage가 있는 Gate 578건만 후보화 | △ | △ | ✓ | ✗ | **reject** | lineage 잔존 여부가 과거 검수 흐름과 결합돼 있어 부분 채택하면 선택편향이 생기며, 결손 1,373건과 같은 모집단이라고 주장할 수 없다 |
| Gate lineage 결손이 해소될 때까지 Owner MOV도 중단 | △ | ✗ | ✓ | ✓ | **reject** | Owner MOV는 별도 development-only 원천이고 historical 1,822 전역 지문·고정 v2.4·사람 blind bbox 경계로 독립 통제할 수 있다 |
| **Gate 1,951건 전량 quarantine + Owner MOV 35개만 blind hard-case queue** | ✓ | ✓ | ✓ | ✓ | **adopt / owner-only development queue** | Gate candidate를 exact 0으로 고정하고 전량 격리 수량·이유를 provenance에 남기면서, Owner source coverage·decode·dedup·bucket·blind acceptance를 별도로 측정할 수 있다 |

**측정·중단 경계 (2026-08-14 구현 정정):** Gate manifest·COCO·raw·partial lineage의 과거 감사 결과는
immutable historical report로만 보존한다. Owner runtime/input audit/mining/handoff는 이를 경로 인자로 받거나
열지 않으며, provenance에는 `gate_policy=quarantine_all`, `gate_candidate_count=0`,
`gate_inputs_consumed=false` 세 literal만 기록한다. 따라서 격리된 Gate bbox 품질이나 lineage 결손은 Owner
실행 status를 막지 않는다. 새 0700 owner-only attempt에서만 Owner MOV를 verified FD로 순차 decode하고 영상당
최대 12장, historical 1,822 global SHA/dHash, frozen v2.4 shadow, blind CVAT acceptance 순서로 진행한다.
validation 153·fixed-test 151·Owner external 60, v2.4 train/checkpoint, v2.4b freeze와 기존 attempt/lock은
불변이며 사람 bbox 전 학습은 0이다.

### 2026-08-14 — YOLO26n v2.5 Owner minimal inference 실행기 전환 (판정자: owner + Codex)

맥락: Owner 35개 영상에서 만든 accepted dedup bundle 280장은 이미 고정됐고 v2.4 checkpoint/freeze도
완료됐다. hardened all-in-one 경로는 runtime tree와 producer/inference code identity를 같은 hard stop으로
묶어 과학적으로 유효한 accepted input의 shadow inference를 막았다. owner는 current threat model에 맞춘 focused
runner와 pre/post review 각 1회로 queue 준비를 자동 완주하도록 승인했다. 정본 addendum:
[`2026-08-14-yolo26n-v25-owner-minimal-inference-addendum.md`](superpowers/specs/2026-08-14-yolo26n-v25-owner-minimal-inference-addendum.md).

| 제안 | G1 SOT | G2 효과 | G3 측정 | G4 계획 | 판정 | 근거 |
|---|---|---|---|---|---|---|
| hardened all-in-one 경로를 계속 보강 | △ | ✗ | △ | ✗ | **reject** | 이미 accepted 280 입력과 frozen v2.4의 queue 준비보다 실행환경 동등성 자체가 목적이 돼 현재 development-only 소비처를 반복 차단했다. |
| **focused minimal runner로 280 inference→blind CVAT acceptance** | ✓ | ✓ | ✓ | ✓ | **adopt / development-only queue** | GME 검출기 개선용 사람 bbox 후보를 최대 210장으로 만들며, bundle/checkpoint/freeze hard pins·protected 접근 0·blind leak 0·write 0을 테스트와 기존 independent validator로 측정한다. |

### 2026-08-15 — YOLO26n v2.5 GME active shadow + 저장 영상 backfill (판정자: owner + Codex)

맥락: v2.5 development fixed-test에서 같은 protocol의 v2.4 대비 recall은 `70.0%→75.6%`, precision은
`73.3%→73.1%`, duplicate는 `12→9`로 측정됐다. selection freeze 이후 새 production 영상이 없어
독립 future holdout은 아직 실행할 수 없다. owner는 기다리는 동안 v2.5를 GME candidate 계산에 실제
사용하고 신규·기존 eligible 영상을 처리하되 사용자 값과 자동 조치는 바꾸지 않는 방향을 승인했다.

| 제안 | G1 SOT | G2 효과 | G3 측정 | G4 계획 | 판정 | 근거 |
|---|---|---|---|---|---|---|
| v2.5를 즉시 사용자 활동시간 기본 모델로 완전 교체 | ✗ | ✓ | △ | △ | **reject** | 독립 future holdout이 없어 사용자 값 승격 근거가 부족하다 |
| 새 영상 일부만 passive shadow | ✓ | △ | ✓ | ✓ | **보류** | 안전하지만 실제 hard-case와 운영 coverage 축적 속도가 느리다 |
| **v2.5 신규 전수 GME active shadow + eligible 저장 영상 backfill** | ✓ | ✓ | ✓ | ✓ | **adopt / 구현·shadow 운영 승인** | 기존 detector identity별 append-only job/run 계약으로 과거 결과를 보존하며 실제 candidate 활동시간·tracking quality를 축적할 수 있다. 10-clip smoke, 24시간 coverage/lag/failure, future holdout leak 0으로 측정한다 |

**경계:** v2.5는 GME candidate 계산에는 사용하지만 Flutter/API `activity-v1`, 사람 GT, 행동명,
하이라이트, VLM route, 자동 skip·격리·삭제·부재 확정은 변경하지 않는다. raw inference `conf=.001`,
`imgsz=960`, NMS `.70`, `max_det=50` 뒤 threshold `.20`을 적용한다. 신규 live가 항상 우선이고 lag
p95>15분이면 backfill만 중단한다. future holdout은 prediction-independent selection과 사람 blind GT를
유지한다. 설계 정본:
[`2026-08-15-yolo26n-v25-gme-active-shadow-design`](superpowers/specs/2026-08-15-yolo26n-v25-gme-active-shadow-design.md).

### 2026-08-23 — GME negative audit 캘리브레이션 (판정자: Codex + iTerm Claude 교차검토 + owner 승인)

맥락: 운영 라벨링은 GME 탐지 영상을 우선해 사람 행동 GT를 만들지만, GME가 `detected=false`로 기록한 영상은 사람 눈에 거의 도달하지 않아 존재 미탐을 구조적으로 발견하기 어렵다. 과거 `exclude_absent`는 actual active 누락으로 reject됐으며 이번 제안은 자동 제외를 재개하지 않고 negative 표본을 사람 blind audit로 측정·보존한다. 설계 정본: [`2026-08-23-gme-negative-audit-calibration-design`](superpowers/specs/2026-08-23-gme-negative-audit-calibration-design.md).

| 제안 | G1 SOT | G2 효과 | G3 측정 | G4 계획 | 판정 | 근거 |
|---|---|---|---|---|---|---|
| 기존 라벨링 웹의 별도 GME presence-audit task + 층화 무작위 negative·blind positive control 캘리브레이션 | ✓ | ✓ | ✓ | ✓ | **adopt (TEST-SHEET 선행)** | GME v1의 사람 bbox hard-case·strata·future holdout 계약과 직접 부합한다. negative-pool 내 실제 게코 비율과 control 발견률을 분리 측정하고 suspicious mining은 rate 분모에서 제외한다. 결과는 append-only audit/Owner 승인 Dataset 후보로만 쓰며 자동 exclude·학습 편입·checkpoint 교체·배포는 금지한다. |

### 2026-08-31 — YOLO26n v2.6 GME 운영 정상화·라벨링 웹 적용 (판정자: owner + Codex)

맥락: v2.5는 최근 야간 연속영상에서 대규모 미탐·오탐을 냈고, 라벨링 웹은 model identity를 고정하지
않은 최신 GME run을 표시한다. 공개 `/gecko-detector`는 실제 worker 미연결로 production 503 상태다.
v2.6 warm-start-s28은 같은 recent validation에서 precision `92.69%`, recall `93.62%`, specificity
`91.30%`를 기록했고 old regression 151장에서도 precision `83.95%`, recall `75.56%`로 v2.5의
기존 recall을 유지하면서 precision을 개선했다. owner는 v2.7보다 신규·과거 영상 GME와 라벨링 웹
정상화를 먼저 수행하도록 승인했다. 설계 정본:
[`2026-08-31-yolo26n-v26-production-normalization-design`](superpowers/specs/2026-08-31-yolo26n-v26-production-normalization-design.md).

| 제안 | G1 SOT | G2 효과 | G3 측정 | G4 계획 | 판정 | 근거 |
|---|---|---|---|---|---|---|
| v2.5 checkpoint를 같은 identity·path에서 덮어쓰기 | △ | ✓ | ✗ | △ | **reject** | 과거·신규 결과가 섞여 provenance와 rollback을 잃는다 |
| v2.5/v2.6 장기 병렬 shadow 뒤 전환 | ✓ | △ | ✓ | ✓ | **보류** | 안전하지만 현재 v2.5 장애를 계속 노출해 정상화 우선순위와 충돌한다 |
| **새 v2.6 identity + 10건 smoke 뒤 GME·라벨링 직접 전환 + bounded backfill** | ✓ | ✓ | ✓ | ✓ | **adopt / 운영 정상화 승인** | append-only history와 rollback을 보존하면서 신규 영상을 즉시 v2.6으로 처리하고 저장 영상·web overlay·실제 upload worker를 같은 identity로 수렴시킬 수 있다 |

**경계:** v2.6은 GME 운영 detector와 라벨링 보조 결과로 직접 사용하지만, sealed future holdout 없이
formal `yolo_active_model` 승격 조건을 우회하거나 Flutter 고객 활동량·사람 GT·영상 보존정책을
자동 변경하지 않는다. 신규 live가 historical backfill보다 우선하며 live lag p95가 15분을 넘으면
backfill만 멈춘다. v2.5와 v2.6의 job/run/artifact는 모두 append-only로 보존한다.
