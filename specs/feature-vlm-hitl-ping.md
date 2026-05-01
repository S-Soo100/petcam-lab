# VLM HITL ping — 모호 케이스 사용자 검수 파이프라인

> v3.5 86.2% baseline 잔존 오답 중 UI 매핑으로 흡수 안 되는 그룹 (defecating G2 5건, shedding G5 3건, eating_prey G4 3건, drinking G3 5건) + 모든 신규 클립의 모호 케이스를 **사용자에게 1-tap ping**으로 검수받는다. 누적된 사용자 답을 (a) GT 데이터셋 확장, (b) 향후 fine-tune 데이터, (c) 사용자별 모델 보정 시드로 활용. UX 매핑([feature-vlm-feeding-merge-ux.md](feature-vlm-feeding-merge-ux.md))과 함께 "시각 한계는 prompt 아닌 다른 채널로 푼다" 정공법의 두 번째 카드.

**상태:** 🚧 진행 중 (2026-05-02) — 스코프·완료 조건 합의 단계
**작성:** 2026-05-02
**연관 SOT:** `../../tera-ai-product-master/docs/specs/petcam-poc-vlm.md` (라운드 진화 + 결정 16건)

## 1. 목적

- **사용자 가치**:
  - 모호 케이스(낮은 confidence 또는 confusion-prone 클래스 페어)를 자동 분류로 강제하지 않고 사용자가 1-tap으로 정정 → **개별 사육자 루틴에 맞춘 정확도** 달성. UI 묶음으로 안 풀리는 minor class(defecating, shedding, eating_prey)도 누적되며 정확도 회복.
  - 사용자 부담은 일주일에 N건(상한 명시) — UX 비용 < 정확도 가치.
- **기술 학습**:
  - HITL 큐 설계 패턴 (저신뢰 케이스 추출 → 큐 적재 → 사용자 노출 → 답변 누적)
  - confidence × class-pair 기반 큐 우선순위 (단순 confidence threshold는 무용 — `feedback_vlm_confidence_abstain_limit`)
  - GT 누적이 향후 fine-tune·평가셋 확장에 어떻게 쓰이는지 데이터 흐름
  - Supabase RLS로 사용자별 답 격리 + 운영자 view (전체 GT 모음)
- **결정 근거**:
  - `feedback_vlm_visual_information_limit` — "사람도 헷갈리는 케이스는 UX 통합·메타데이터 보강·HITL로"
  - `feature-vlm-feeding-postfilter.md` (폐기) §5.2 — multi-track ablation으로 prompt 한계 6번째 검증, "시각 한계 결론" 굳어짐
  - 오답 26건 분포: G2/G4/G5 11건은 묶을 카운터파트 없음 → UI 매핑만으로 부족, HITL 필수

## 2. 스코프

### In (이번 스펙에서 한다)

#### 2.1 ping 트리거 룰
- 다음 중 하나 만족 시 클립을 HITL 큐에 적재:
  - **저 confidence**: VLM 출력 `confidence < 0.7`
  - **confusion-prone class**: VLM 출력이 `{eating_paste, drinking, defecating, shedding, eating_prey}` 중 하나 (= confusion 발생 빈도 높은 클래스. 단순 moving은 제외 — moving은 default fallback이라 거짓 양성 비용 큼)
  - **사용자 옵트인**: 사용자가 "내 클립 검수에 참여" 토글 켰을 때만 발동 (디폴트 OFF)
- 룰은 단순 OR. 두 시그널 (저 confidence × confusion-prone class) 조합은 미세 튜닝 단계 후순위.

#### 2.2 큐 노출 UX
- 위치: 클립 피드 내 **별도 탭** "검수 (N)" — 알림 카운트 빨간 점.
- 1-tap 체크: 클립 카드 하단에 "이 행동 맞나요?" 질문 + 8-class 버튼(UI 매핑 기준) + "다른 행동" + "확실치 않음".
  - "다른 행동" 선택 시 raw 9-class 드롭다운 (정밀 입력 옵션, 디폴트 미노출).
  - "확실치 않음" 선택 시 큐에서 제거 + GT 데이터셋엔 미반영 (사용자 부담 회피).
- 사용자 부담 상한: **하루 최대 5건 노출**. 그 이상은 큐에 쌓아두고 다음 날.
- 답변 후 카드 즉시 fade-out + 카운트 감소.

#### 2.3 데이터 스키마
- `behavior_logs` 테이블에 `source = 'human_hitl'` 신규 enum 값 추가 (`human` 기존 라벨러 입력과 구분). 또는 `notes` 컬럼에 `[hitl]` 프리픽스로만 구분 (단순화 옵션).
- 추가 필드 옵션:
  - `vlm_action`: 사용자 ping 시점의 VLM 예측 (모델·룰 분석용)
  - `vlm_confidence`: 같은 시점 confidence
  - `responded_at`: 답변 timestamp (ping → 답까지 latency 추적)
- 결정: 단순화 우선 — `notes` 프리픽스 + `behavior_logs` 그대로. 추가 컬럼은 데이터 누적 후 분석 필요해질 때.

#### 2.4 백엔드 큐 추출 API
- `GET /clips/hitl-queue?limit=5` — 위 트리거 룰에 맞고 `source IN ('human', 'human_hitl')` 답이 없는 클립 N건 반환.
- 정렬: 가장 최근 클립 우선 (오래된 거 먼저 검수해도 가치 낮음).
- 페이지네이션 단순: 한 번에 최대 5 (UX 부담 상한과 일치).

#### 2.5 답변 저장 API
- `POST /clips/{id}/hitl-label` — body `{action: BehaviorClass, confidence?: 'sure' | 'unsure'}`.
- "확실치 않음" → 저장 X, 큐에서만 제거 (별도 silent dismissal 컬럼? — 단순화 위해 일단 in-memory만, 새로고침 시 재노출 허용).

#### 2.6 분석 대시보드 (운영자용)
- `GET /admin/hitl-stats`: 누적 HITL 라벨 수, 사용자별 분포, vlm_action vs human_action 일치율 (자체 정확도 추적).
- 일치율이 raw VLM 정확도(86.2%)보다 낮으면 → ping 트리거 룰 조정 필요 신호.

#### 2.7 회귀 가드
- 본 spec의 ping 룰 변경 시 154건 평가셋이 ping 큐에 어떻게 들어가는지 시뮬레이션 → 노이즈/부담 미리 측정.
- `web/eval/v35/simulate-hitl-queue.py` 신규 — 154건에 룰 적용해 큐 사이즈/구성 시뮬.

#### 2.8 문서 동기화
- `feature-poc-vlm-web.md`에 §3-15 (HITL ping 도입) 추가.
- SOT (`petcam-poc-vlm.md`) 결정 항목 추가 — 사용자 확인 후. 결정 한 줄 후보: "분류 보정 = (a) UI 묶음 매핑 + (b) HITL ping 큐 (저 confidence + confusion-prone class). raw 라벨은 보존."

### Out (이번 스펙에서 **안 한다**)

- VLM raw prompt / 모델 / generationConfig 변경 — v3.5 락인 (`project_vlm_v35_baseline_lock`).
- F2 LabelForm UX 변경 — human label은 raw 9클래스 그대로. HITL은 UI 매핑(8) 디폴트 + raw 9 옵션.
- 자동 fine-tune 파이프라인 — HITL 답을 모델 학습에 자동 반영하는 로직은 별도 spec. 본 spec은 데이터 누적까지만.
- 모델 출력 confidence 보정(calibration) — 별도 분석 필요. 일단 raw confidence 사용.
- 사용자별 다른 모델 — 누적된 HITL 답이 충분해진 후 별도 spec.
- F3 결과 비교에 HITL 통계 표시 — 운영자 대시보드에만.
- HITL 답을 둘러싼 사용자 간 disagreement 처리 — 사용자별 격리(RLS), 그 사용자 본인 데이터만.

> **스코프 변경은 합의 후에만.** 작업 중 In/Out 경계가 흔들리면 이 섹션 수정 + 사유 기록.

## 3. 완료 조건

- [ ] **트리거 룰 코드 위치 확정** — `web/src/lib/hitl-trigger.ts` (또는 backend Python). 단위 테스트로 confusion-prone class + low confidence 매칭 검증.
- [ ] **큐 추출 API** — `GET /clips/hitl-queue?limit=5`. 로컬에서 mock VLM 결과로 큐 5건 반환 확인.
- [ ] **답변 저장 API** — `POST /clips/{id}/hitl-label`. behavior_logs `source='human_hitl'` (또는 notes 프리픽스)로 저장.
- [ ] **UI 큐 탭** — 클립 피드 내 "검수 (N)" 탭. 카드 클릭 → 답변 → fade-out. 사용자 옵트인 토글 추가.
- [ ] **하루 상한 5건** 작동 확인 (시계 mock으로 검증).
- [ ] **시뮬레이션** — `simulate-hitl-queue.py`로 154건에 룰 적용해 큐 구성 사전 측정.
- [ ] **운영자 통계 API** — vlm_action vs human_action 일치율 + 클래스별 분포.
- [ ] **회귀 가드** — UI 묶음 spec(`feature-vlm-feeding-merge-ux.md`)과의 충돌 검증. 둘 다 적용된 상태에서 일관 표시.
- [ ] **`feature-poc-vlm-web.md` §3-15 추가** + SOT 결정 동기화.
- [ ] 본 spec ✅ + `specs/README.md` 목록 갱신.

## 4. 설계 메모

- **선택한 방법**: 옵트인 + 상한 + 단순 룰. 사용자 부담 최소화 우선.
- **고려했던 대안**:
  - (a) 모든 클립을 HITL 큐에 → 사용자 부담 너무 큼. 하루 5건 상한.
  - (b) confidence threshold 단독 — `feedback_vlm_confidence_abstain_limit`에서 무용 검증됨. confusion-prone class 룰과 OR 조합.
  - (c) 사용자별 다른 모델 호출 → 인프라 비용 큼. 데이터 누적 후 별도 spec.
  - (d) HITL 답을 즉시 모델 fine-tune에 반영 — 모델 학습 파이프라인 별도. 본 spec은 누적까지만.
- **기존 구조와의 관계**:
  - `behavior_logs.source`는 기존 `'human' | 'vlm'` enum. 새 값 `'human_hitl'` 추가 또는 notes 프리픽스로 단순화.
  - F2 LabelForm은 변경 없음 — 라벨러용 raw 9-class 입력.
  - F3 결과 비교는 변경 없음 — vlm vs human 일치율 표시.
- **리스크 / 미해결 질문**:
  - 사용자가 "확실치 않음" 자주 누르면 큐가 무한 재노출 → silent dismissal 정책 필요? (일단 새로고침 시 재노출 허용으로 단순화.)
  - 사용자별 답 disagreement (같은 클립을 다르게 라벨링) → 본 spec은 사용자별 격리. 운영자 view에서 cross-user 통계만.
  - HITL 답이 너무 적게 누적되면 통계 가치 없음 → 일정 누적량 도달까지 별도 분석 보류.
  - GT 데이터셋 확장 시점 — 누적 답이 154건 평가셋 + N건 되면 evaluation 갱신. N의 적정값은 데이터 누적 후 결정.

## 5. 학습 노트

(작업 중 채움)

- HITL 큐 패턴 vs 기존 라벨링 워크플로 차이
- Supabase RLS로 사용자별 GT 격리 + 운영자 cross-user view 패턴
- confidence calibration이 분류기에 어떻게 영향 주는지 (calibrated confidence는 ping 트리거 효과 ↑)

## 6. 참고

- 본 레포 spec:
  - [`feature-poc-vlm-web.md`](feature-poc-vlm-web.md) — Round 1~3 결정 이력
  - [`feature-vlm-feeding-merge-ux.md`](feature-vlm-feeding-merge-ux.md) — UI 매핑 (병행 진행)
  - [`feature-vlm-feeding-postfilter.md`](feature-vlm-feeding-postfilter.md) — post-filter 폐기 (동기 부여 근거)
- 자동 메모리:
  - `~/.claude/projects/-Users-baek-petcam-lab/memory/feedback_vlm_visual_information_limit.md`
  - `~/.claude/projects/-Users-baek-petcam-lab/memory/feedback_vlm_confidence_abstain_limit.md`
  - `~/.claude/projects/-Users-baek-petcam-lab/memory/project_vlm_v35_baseline_lock.md`
- SOT: `../../tera-ai-product-master/docs/specs/petcam-poc-vlm.md`
- 룰: `.claude/rules/donts/vlm.md`
