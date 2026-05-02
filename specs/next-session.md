# 다음 세션 시작 지점

> 매 세션 마지막에 갱신. 다음 세션 초입에 먼저 읽는다.
> **최종 갱신:** 2026-04-30 (Opus 4.7, Round 3 종료 — v3.5 85.5% production 락인)

## ✅ 직전 세션 산출 — VLM Round 3 종료, v3.5 production 락인

**v3.5 zero-shot 159건 평가 = 85.5% (feeding-merged) → production 확정.**

Round 3에서 잔존 오답(특히 `moving → eating_paste` 9건)을 prompt로 풀어보려 3가지 방향 시도, 모두 baseline 대비 퇴행:

| 시도 | 방향 | 결과 (feeding-merged) | 5-카테고리 |
|---|---|---|---|
| v3.6 | rule 강화 + duration 메타 prior | 84.3% (-1.9%p) | recovered 5 / broken 10 |
| v3.7-B | rule 약화 (6 spots) | 81.1% (-5.0%p) | recovered 4 / broken 12 |
| v4 | clean slate (6 클래스, 1641 chars) | 79.2% (-6.9%p) | recovered 4 / broken 15 |

채택 가드(`Δ > +2%p AND recovered > broken`) 3건 모두 ❌ → v3.5 production 확정.

**커밋:** `8166131 docs(specs): Round 3 종료 — v3.5 85.5% production 락인 (baseline 깨기 3회 실패)`

상세: [feature-poc-vlm-web.md §3-13](feature-poc-vlm-web.md)

## 🔒 락인된 결정 — 새 세션에서 재논의 금지

사용자 명시: "이거보다 더 나빠져서는 안 됨." → **85.5%가 production floor.**

- **v3.5 prompt 백업** = `web/prompts/backups/{system_base,crested_gecko}.v3.5.md` — 회귀 시 즉시 롤백
- **prompt 추가 변경 시도 자체가 ROI 0** (3회 실패 검증). 잔존 오답은 prompt 한계가 아닌 **시각 한계**.
- 회귀 가드 의무: 159건 동일 평가셋으로 새 변경 측정 → 85.5% 미달이면 채택 X
- 단일 변경 ablation 원칙 (다지점 동시 변경 금지)
- 메타 prior / clean slate 시도 금지 (이미 검증됨)

상세 메모리: `~/.claude/projects/-Users-baek-petcam-lab/memory/project_vlm_v35_baseline_lock.md` + `feedback_vlm_rule_overcorrection.md`

## 🧭 방향 결정 필요 — 잔존 오답 정공법 (3 layer 후보)

prompt로 못 푸니까 다른 layer로 풀어야 함. 3 후보 모두 spec/메모리에 검증 박힘.

### 1. ⭐ UX 통합 — drinking + eating_paste → "feeding" 묶음 (추천)

가장 먼저 손댈 거. 평가 레이어에서 이미 93.1% 검증된 매핑을 **UI/스키마/필터까지 일관되게** 반영.

- **무엇:** F2 라벨 폼 + F3 결과 화면 + 클립 피드 필터를 9 클래스 → 8 클래스(feeding 묶음)로 노출. raw 라벨은 DB 보존 (drinking/eating_paste 분리 유지).
- **왜 먼저:** drinking 시각 한계 4건 + eating_paste over-trigger 일부를 UX 한 번 손보면 사용자 노출 정확도 88.5%+ 달성 가능. 추가 모델 비용 0.
- **체크포인트:** 변경 후 159건 재추론 X (raw 동일). 평가 매핑 코드만 바꿔서 즉시 검증.
- 메모리: `feedback_vlm_ux_merge_validation.md`

### 2. 메타데이터 보강

prompt가 못 풀던 시각 한계 케이스를 **추가 시그널**로 보충.

- 후보: dish detection (밥그릇 위치 박스 사전 학습) / before-after behavior (전·후 클립 컨텍스트) / 시간대 (먹이 시간 prior) / 카메라 ROI 위치 prior
- **언제:** UX 통합 끝난 뒤. 단일 변수 ablation 가능한 형태로 도입.
- **주의:** 이건 prompt 안 박음. **별도 분류기 또는 후처리 레이어**로. donts/vlm.md 룰 5(evidence-forcing) 회피.

### 3. HITL 저신뢰 케이스 운영자 큐

confidence-abstain은 무력 (memory `feedback_vlm_confidence_abstain_limit.md`). 대안:

- 클래스별 신뢰도 + reasoning 패턴 + 클래스 conflict 매트릭스 기반으로 "검수 큐" 자동 적재
- 운영자 검수 결과로 GT 풀 보강 (Round 4 평가셋 확장 + 모델 측정 데이터)
- **언제:** UX 통합 + 메타데이터 후. PoC 단계에서 무리 안 함.

### 별도 트랙: Stage E 온디바이스 필터링

VLM PoC와 분리. CLAUDE.md에 언급된 "온디바이스 필터링" 스코프 미확정. SOT (`../tera-ai-product-master/docs/specs/petcam-b2c.md`) 먼저 읽어 의미 확인 → spec 킥오프.

## 🗂️ 현재 시스템 상태 스냅샷 (2026-04-30)

- **VLM:** Gemini 2.5 Flash + v3.5 prompt + feeding-merged = **85.5% (136/159)** production 락인
- **평가셋:** 159건 (cam2 motion 17 + inbox/0429 + inbox/0430)
- **클래스:** raw 9 (eating_paste / eating_prey / drinking / defecating / shedding / basking / hiding / moving / unseen) + 평가 매핑 (drinking + eating_paste → feeding, hiding → moving)
- **Backend:** `api.tera-ai.uk` 공개 중 (Cloudflare Named Tunnel). 로컬 수동 실행
- **Auth:** `AUTH_MODE=prod`, Supabase JWT (ES256)
- **카메라:** cam1 / cam2 (오너 bss.rol20) + cam1-mirror / cam2-mirror (QA dlqudan12)
- **Tests:** 134 passing (마지막 확인 2026-04-22, VLM 작업은 web/스크립트 영역이라 미영향)
- **Stage:** A ✅ / B ✅ / C ✅ / D1~D5 ✅ / E 🆕 (스코프 미확정) / VLM PoC ✅ Round 3 종료

## 📂 맥락 복원 — 읽을 파일 (우선순위)

새 세션이 맥락 없이 들어왔을 때 이 순서로:

1. **이 파일** — 오늘의 시작 지점 + 락인 결정
2. [feature-poc-vlm-web.md](feature-poc-vlm-web.md) — VLM PoC 전체 결정 이력 (Round 1~3, §3-13까지)
3. `~/.claude/projects/-Users-baek-petcam-lab/memory/MEMORY.md` — 자동 메모리 인덱스 (특히 `project_vlm_v35_baseline_lock`, `feedback_vlm_rule_overcorrection`, `feedback_vlm_ux_merge_validation`)
4. [../README.md](../README.md) — 1분 요약 + 퀵스타트
5. [../AGENTS.md](../AGENTS.md) — AI 에이전트 공통 진입점
6. [README.md](README.md) — spec 운영 규칙 + 전체 스펙 목록
7. `../tera-ai-product-master/docs/specs/petcam-b2c.md` — 제품 SOT (Stage E 스펙 킥오프 시)
8. `../tera-ai-product-master/docs/specs/petcam-poc-vlm.md` — VLM PoC SOT (결정 16건 + 라운드 진화)

## 💬 사용자가 "뭐부터 해야해?" 물으면

1. **첫 확인 — 락인 존중**: v3.5 baseline은 건드리지 않는다고 인지. prompt 변경/clean slate 제안 금지.
2. **다음 layer 선택지 제시**: UX 통합 (1번, 추천) / 메타데이터 (2번) / HITL (3번) / Stage E (별도 트랙) 중 사용자 선택
3. **사용자 결정 후**: 해당 spec 파일 또는 신규 spec 킥오프
4. **회귀 가드 자동 적용**: 어떤 변경이든 85.5% floor 검증 의무
