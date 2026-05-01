# VLM feeding-merge UX 통합

> v3.5 86.2% baseline 잔존 오답 중 drinking ↔ eating_paste 시각 한계를 UI 레이어 매핑으로 흡수. 평가 레이어에서 이미 93.1% 검증된 `drinking + eating_paste → feeding` 매핑을 결과 비교·피드·필터까지 일관 노출하고, raw 라벨은 DB·human label 입력에 그대로 보존.

**상태:** 🚧 진행 중 (2026-05-02 재개) — post-filter 폐기 후 정공법으로 복귀.
- 보류 해제 사유: dish-presence post-filter 폐기 ([feature-vlm-feeding-postfilter.md](feature-vlm-feeding-postfilter.md)) — 154건 84.42% FAIL + 오답 26건 multi-track ablation에서 prompt 보정 불가 6번째 검증.
- 의미: 잔존 오답이 시각 한계라는 결론 굳어짐 → UX 매핑 정공법(이미 93.1% 평가 검증)이 가장 강한 카드로 남음.
- 함께: defecating G2(5건), shedding G5(3건), eating_prey G4(3건)는 묶을 카운터파트 없음 → HITL ping spec([feature-vlm-hitl-ping.md](feature-vlm-hitl-ping.md))로 보완.

**작성:** 2026-05-01 / **재개:** 2026-05-02
**연관 SOT:** `../../tera-ai-product-master/docs/specs/petcam-poc-vlm.md` (라운드 진화 + 결정 16건)

## 1. 목적

- **사용자 가치**: v3.5 prompt 변경 ROI 0 검증 후, prompt 아닌 layer로 잔존 오답을 푸는 첫 정공법. 평가 레이어 한정으로 매핑된 86.2% (feeding-merged) 수치를 **사용자가 실제로 보는 화면**까지 일관 적용해서 노출 정확도를 88.5%+로 끌어올린다 (drinking 시각 한계 4건 + eating_paste over-trigger 일부 흡수).
- **기술 학습**: TS의 `as const` + literal union을 이용해 raw enum과 UI enum을 분리 관리하는 패턴, 매핑 함수의 유닛 테스트, 평가 스크립트와 UI 코드 간 매핑 일치성을 어떻게 강제할지 (단일 ground truth 함수 export → Python 측은 별도 미러).
- **결정 근거**: `feedback_vlm_ux_merge_validation.md` (메모리) + `feature-poc-vlm-web.md §3-12` (평가 매핑 93.1% 검증) + `project_vlm_v35_baseline_lock.md` (prompt 변경 시도 3회 모두 퇴행 → 다른 layer 필요).

## 2. 스코프

### In (이번 스펙에서 한다)

- `web/src/types.ts`
  - `toFeedingMerged(action: string): string` 매핑 함수 export — `drinking | eating_paste → feeding`, 그 외는 그대로.
  - `UI_BEHAVIOR_CLASSES` 8클래스 readonly tuple export (raw 9클래스에서 drinking + eating_paste를 feeding으로 통합).
  - 매핑 단위 검증 (간단 assert 또는 `__tests__` 파일).
- F3 결과 비교 화면: `web/src/app/results/page.tsx` + `PairTable.tsx`
  - 모델 출력 라벨과 human GT 라벨 둘 다 표시 시점에 `toFeedingMerged()` 통과.
  - 일치/불일치 판정도 매핑 후 값으로 비교.
- 클립 피드 필터 (위치 확인 후 정확히 명시 — `app/page.tsx` 또는 `app/clips/page.tsx` 후보)
  - 필터 옵션을 `UI_BEHAVIOR_CLASSES` 8클래스로 노출.
  - 클립의 표시 라벨도 매핑 함수 통과.
- 회귀 가드 (코드 검증)
  - `scripts/analyze-*.py`에 박힌 평가 매핑(`drinking + eating_paste → feeding`)과 `toFeedingMerged()` 정의가 동일한지 한 곳에서 단언. 미스매치는 빌드 단계 에러 또는 PR 체크리스트 항목.
- 문서 동기화
  - `feature-poc-vlm-web.md`에 §3-14 (UX 통합 결과) 추가, 본 spec 링크.
  - SOT (`petcam-poc-vlm.md`) 결정 항목 동기화 (필요 시 — 사용자 확인 후).

### Out (이번 스펙에서 **안 한다**)

- VLM prompt / 모델 / generationConfig 변경 — v3.5 락인 (`project_vlm_v35_baseline_lock.md`).
- DB 스키마 변경 — `behavior_logs.action` enum/check 그대로. raw 9클래스 보존.
- F2 LabelForm UX 변경 — human label 입력은 raw 9클래스, 단축키 1~9 그대로. **이유**: GT 정밀도 보존 + 향후 모델·평가 비교 시 raw 분리 필요. UI 통합은 표시 레이어 한정.
- hiding ↔ moving UI 매핑 — 평가 레이어 한정 (motion-trigger 시스템 충돌 보정용). UI에선 hiding 그대로 노출.
- 159건 재추론 — raw 동일, 매핑 코드만 변경. 추론 비용 0 원칙.
- 새 기능 (메타데이터 보강 / HITL 큐) — 별도 spec.

> **스코프 변경은 합의 후에만.** 작업 중 In/Out 경계가 흔들리면 이 섹션 수정 + 사유 기록.

## 3. 완료 조건

- [ ] `web/src/types.ts`에 `toFeedingMerged()` + `UI_BEHAVIOR_CLASSES` 추가, 기존 `BEHAVIOR_CLASSES`는 raw 9클래스 그대로 유지.
- [ ] `toFeedingMerged()` 단위 검증 — 9클래스 입력 → 기대 8클래스 출력 9개 케이스 전부 통과.
- [ ] F3 결과 비교(`results/page.tsx` + `PairTable.tsx`)가 매핑 후 값으로 비교·표시. 기존 159건 평가셋 화면에서 일치율 = 86.2% (137/159) 또는 그 이상으로 표시되는지 육안 확인.
- [ ] 클립 피드 필터 위치 확인 후 8클래스 노출로 변경. 필터 동작 확인 (drinking 클립이 feeding 필터에 잡히는지).
- [ ] 평가 스크립트(`scripts/analyze-*.py`) 매핑 정의와 `toFeedingMerged()` 일치 검증 — 명시적 주석 또는 테스트로 강제.
- [ ] `npm run build` 또는 `pnpm build` 통과 (web 디렉토리).
- [ ] `feature-poc-vlm-web.md` §3-14 추가 (한 단락 + 본 spec 링크).
- [ ] SOT (`../tera-ai-product-master/docs/specs/petcam-poc-vlm.md`) 동기화 — 결정 항목 추가 필요한지 사용자 확인.
- [ ] 본 spec 상태 `✅ 완료` + `specs/README.md` 목록 표 갱신.

## 4. 설계 메모

- **선택한 방법**: 표시 레이어 한정 매핑. raw enum (DB 9클래스) 그대로 두고, UI enum (8클래스) 별도 export. 단일 매핑 함수가 두 enum을 잇는다.
- **고려했던 대안**:
  - (a) DB 자체를 8클래스로 통합 — raw GT 손실로 향후 모델 평가 시 분리 비교 불가. 폐기.
  - (b) F2 LabelForm도 8클래스 입력 — 사용자가 "물 마시는 거"와 "사료 먹는 거"를 구분 입력 못 함 → GT 정밀도 손실. 폐기.
  - (c) Python 측 평가 스크립트와 TS 측 UI에 매핑을 각각 박기 — drift 위험. 단일 정의 export 후 Python은 미러로.
- **기존 구조와의 관계**: `BEHAVIOR_CLASSES` 9 readonly tuple 보존 → `BehaviorClass` literal union 그대로. `UI_BEHAVIOR_CLASSES`는 8 readonly tuple 추가 export, `UIBehaviorClass` literal union 새로 정의.
- **리스크 / 미해결 질문**:
  - 클립 피드 필터 정확한 위치 (확인 후 In 섹션 갱신).
  - SOT 결정 항목 추가 필요? — 제품 정의(노출 카테고리 8개)에 영향이면 추가 필수. 사용자 확인 후 진행.
  - hiding은 UI에 그대로 노출 (분리), 평가에서만 moving 묶음 — 이중 매핑이 사용자/QA 혼란 줄 가능. 추후 `feeding`처럼 hiding도 UI 묶음 검토 별도 spec.
  - F2 LabelForm은 raw 입력 유지인데, 사용자(라벨러)가 "feeding으로만 알아도 충분한 클립"에 대해 drinking/eating_paste 구분 입력하는 비용 — UX 후속 이슈.

## 5. 학습 노트

(작업 중 채움)

## 6. 참고

- 본 레포 spec: [`feature-poc-vlm-web.md`](feature-poc-vlm-web.md) — Round 1~3 전체 결정 이력
- 자동 메모리:
  - `~/.claude/projects/-Users-baek-petcam-lab/memory/feedback_vlm_ux_merge_validation.md`
  - `~/.claude/projects/-Users-baek-petcam-lab/memory/project_vlm_v35_baseline_lock.md`
  - `~/.claude/projects/-Users-baek-petcam-lab/memory/feedback_vlm_visual_information_limit.md`
- SOT: `../../tera-ai-product-master/docs/specs/petcam-poc-vlm.md` (라운드 진화 + 결정 16건)
- 룰: `.claude/rules/donts/vlm.md` 룰 5/6 (evidence-forcing, deterministic config)
