# VLM 행동 분류 — 크레스티드 게코 펫캠

> **자기충족 기획 문서.** 다른 모델·에이전트가 이 문서 + 첨부 자원만 보고 5분에 컨텍스트 파악 → 비판·개선·교차 평가 가능하도록 작성. 외부 검토 보내기 전 이 문서 우선 갱신.

**버전**: v1.0 (2026-05-02) · **상태**: production 락인 (Round 3 종료) · **연관 SOT**: [`../../tera-ai-product-master/docs/specs/petcam-poc-vlm.md`](../../tera-ai-product-master/docs/specs/petcam-poc-vlm.md)

---

## TL;DR (30초)

- **무엇** — 60초 영상 1개 → 크레스티드 게코의 8개 행동 중 1개 (top-1 classification)
- **왜** — 펫캠 멤버십 핵심 가치 (P0 알림: 섭식·음수·배변·탈피)
- **어떻게** — Gemini 2.5 Flash zero-shot · temperature 0.1 · JSON 응답
- **현재 성능** — **86.2%** top-1 (159건 평가, feeding-merged UX 매핑 후)
- **상태** — production 락인. prompt tuning ROI 0 결론(6번 시도 실패), 다음 정공법 = UX 매핑 ✅ + HITL ping 🚧

---

## 1. 기능 정의 (입력/출력 명세)

### 1.1 입력

| 항목 | 형식 | 비고 |
|---|---|---|
| **영상** | mp4 60초 (motion 트리거 구간) | base64 inline 전송, ~5MB |
| **종 컨텍스트** | `species = "crested_gecko"` | 사용자 입력 SOT, VLM이 영상에서 종 추론 X |
| **system prompt** | `system_base.md` + `species/{species}.md` 병합 | `web/src/lib/prompts.ts` |

### 1.2 출력

```json
{
  "action": "eating_paste",
  "confidence": 0.85,
  "reasoning": "Gecko approaches the food dish at 12s and engages in sustained licking behavior characteristic of paste consumption."
}
```

- `action` ∈ raw 9-class enum (아래 §1.3)
- `confidence` ∈ [0, 1] (모델 자체 추정, calibration 안 됨)
- `reasoning` — 자유 텍스트 (사용자 비노출, 디버깅·HITL용)

### 1.3 클래스 정의

DB는 raw 9-class 보존, UI는 8-class 노출 (`drinking` + `eating_paste` → `feeding` 통합).

| Raw 9 (DB 저장) | UI 8 (사용자 노출) | 우선순위 | 설명 |
|---|---|---|---|
| `eating_paste` | **`feeding`** | P0 | 과일 퓨레(CGD/MRP) 핥기 |
| `drinking` | **`feeding`** | P0 | 물·이슬 핥기 |
| `eating_prey` | `eating_prey` | P0 | 곤충 사냥/포식 (시선 고정 stalking 포함) |
| `defecating` | `defecating` | P0 | 배변 |
| `shedding` | `shedding` | P0 | 탈피 (입/발로 허물 제거 + 허물 섭취) |
| `basking` | `basking` | P1 | 열원 아래 정자세 일광욕 |
| `moving` | `moving` | P1 | 일반 이동 + 부분 가림 + 은신처 입출입 |
| `hiding` | `hiding` (raw 보존, eval만 → moving) | — | 폐기됨 (§4 결정 #18) |
| `unseen` | `unseen` | — | 카메라 시야 밖 |

**멀티 라벨 tie-break**: `eating_prey > eating_paste > drinking > defecating > shedding > basking > moving > unseen`

### 1.4 매핑 함수 (단일 SOT)

- TypeScript: `web/src/types.ts toFeedingMerged(action) → string`
- Python (mirror): `web/eval/v35/check-feeding-merge.py FEEDING_MERGE`
- 일치 검증: `uv run python web/eval/v35/check-feeding-merge.py` (9 케이스 단언)

---

## 2. 비즈니스 가치 — 왜 만드나

### 2.1 제품 맥락
- 펫캠 멤버십 (B2C) 핵심 가치 = **P0 알림** (게코가 밥을 먹었다/물 먹었다/배변했다)
- 사육자가 늘 카메라 들여다볼 수 없으니, AI가 행동 분류해서 **알림 + 일별 요약** 제공
- 라이브 RTSP 스트림 + 모션 감지 + VLM 분류 + 알림 = 펫캠 AI 파이프라인 전체

### 2.2 PoC 가치
- 펫캠 AI 파이프라인의 **가장 큰 미지수**. VLM zero-shot이 70%+ top-1 가능한가?
- 가설 깨지면 Phase 2 YOLO 직접 학습으로 직행 (1~2년 데이터 수집 필요).
- 가설 성립하면 즉시 베타 가능 (학습 없이 prompt만으로 운영).

### 2.3 결과 (2026-04-30)
- **86.2%** top-1 (159건 평가, feeding-merged) → **가설 성립** ✅
- Phase 1 진입 가능 임계 (≥70%) 충족 + Phase 2 YOLO 학습 보류

---

## 3. 현재 구현

### 3.1 모델 + 디코딩 설정

| 항목 | 값 | 결정 근거 |
|---|---|---|
| model | `gemini-2.5-flash` | 비용/지연 균형 + 영상 입력 native |
| temperature | **0.1** | 분류 task 결정성 우선 (§5 룰 6) |
| topP | 0.95 | 단순 분류 |
| responseMimeType | `application/json` | 파싱 안정성 (regex fallback 제거) |

코드: [`web/src/lib/gemini.ts`](../web/src/lib/gemini.ts)

### 3.2 Prompt 파이프라인

```
system_base.md (공통)
  + species/{species}.md (종별)
  + {available_classes_block} (종별 사용 가능 클래스)
  → buildSystemPrompt(species)
  → Gemini API
```

코드: [`web/src/lib/prompts.ts`](../web/src/lib/prompts.ts)
프롬프트: [`web/prompts/system_base.md`](../web/prompts/system_base.md), [`web/prompts/species/crested_gecko.md`](../web/prompts/species/crested_gecko.md)
v3.5 백업 (락인): [`web/prompts/backups/system_base.v3.5.md`](../web/prompts/backups/system_base.v3.5.md), [`crested_gecko.v3.5.md`](../web/prompts/backups/crested_gecko.v3.5.md)

### 3.3 평가 셋

| 셋 | 클립 수 | 위치 | 비고 |
|---|---|---|---|
| **v3.5 SOT** | **159** | `web/eval/v35/v3.5-zeroshot.jsonl` (또는 `/tmp/`) | 정확도 86.2%(merged) lock-in baseline |
| 154 변형 | 154 | (동일 셋에서 사진 5건 제외) | floor 85.7% (post-filter 평가용) |
| GT 라벨 | DB | Supabase `behavior_logs(source='human')` | 사용자가 F2 페이지에서 입력 |

평가 스크립트:
- `web/eval/v35/analyze-v35-full.py` — confusion matrix + feeding-merged 분석
- `web/eval/v35/check-feeding-merge.py` — TS ↔ Python 매핑 동치 검증
- `web/eval/v35/diagnose-results-page.py` — DB vs jsonl 화면 시뮬

---

## 4. 결정 이력 핵심 (외부 에이전트 필독)

전체 22건은 [SOT](../../tera-ai-product-master/docs/specs/petcam-poc-vlm.md). 외부 검토 시 알아야 할 핵심 8건:

| # | 결정 | 근거 |
|---|---|---|
| #2 | **Gemini 2.5 Flash** 채택 | 영상 input native + 비용 (Pro 대비 1/10) |
| #5 | **8 클래스** (v3.5부터, raw는 9 보존) | hiding 폐기 (#18) + drinking/eating_paste UX 통합 (#17) |
| #17 | **drinking + eating_paste → `feeding` UI 통합** | 시각만으로 구분 불가능, 평가 검증 93.1% |
| #18 | **hiding 클래스 폐기** | motion-trigger 카메라 ↔ "은신처 정지" 정의 충돌 |
| #19 | eating_prey **stalking 포함** 정의 | 사용자 직관 ("사냥 자세도 사냥") 정합 |
| #20 | **HITL** 도입 — UX + GT + 진단 + per-user 보정 | per-user 보정은 부가, 본 가치는 앞 3개 |
| #21 | **v3.5 production 락인** (2026-04-30) | baseline 깨기 6번 시도 모두 퇴행 |
| #22 | **다음 layer 3축** (A. UX 매핑 ✅ / C. HITL 🚧 / B. 메타 보강) | prompt tuning ROI 0 결론 |

---

## 5. 시도 + 폐기 이력 (같은 함정 회피용)

baseline (v3.5 86.2%) 깨기 시도 6번 모두 floor 미달. **다른 에이전트가 반복하지 말 것.**

| 시도 | 변경 | 결과 | 학습 |
|---|---|---|---|
| **v3.6** (rule 강화) | evidence-forcing 추가 ("타임스탬프 명시 필수") | **−1.9%p** | 모델이 가짜 timestamp 만들어 오답 정당화 (confabulation) |
| **v3.7-B** (rule 약화) | 일부 rule 제거 | **−5.0%p** | rule이 noise라는 가설 깨짐 |
| **v4** (clean-slate) | prompt 전면 재작성 | **−6.9%p** | 누적된 도메인 룰의 가치 확인 |
| **Track B** (분류 보정) | confidence threshold 분기 | 무용 | 0.95+도 76% 정확도 — confidence calibration 안 됨 |
| **Track C/D/E** | few-shot · 분기 룰 추가 | 동률/퇴행 | 같은 시각 정보로 다른 방식 표현해도 동일 한계 |
| **dish-postfilter** | binary 라우터 (dish_present + licking) | 154건 **84.42%** (floor 85.7%) | binary 라우터도 같은 prompt 레이어 — 같은 시각 한계 |

### 결론

잔존 오답 26건의 본질은 **시각 정보 한계** (영상 픽셀에 정답 신호가 없음). "사람도 헷갈리는 케이스"는 prompt/모델 변경으로 못 풀음.

→ **다음 정공법 = 다른 채널**:
1. **UX 매핑** (시각 한계를 표시 레이어에서 흡수) — drinking + eating_paste → `feeding` 통합 ✅ 완료
2. **HITL ping** (사용자가 1-tap 정정, 누적된 답이 GT 확장 + per-user 보정 시드) 🚧 spec 단계
3. **메타데이터 보강** (dish detection / before-after / 시간대 컨텍스트) — 인프라 비용 크고 ROI 미검증

---

## 6. 알려진 한계

### 6.1 시각 정보 한계 (해결 불가, 다른 채널로)
- `drinking ↔ eating_paste` — 같은 dish 위 같은 자세 (UX 매핑으로 흡수)
- `defecating` — 빈도 낮고 자세 모호 (HITL로 사용자 정정)
- `shedding` — 진행 단계별 시각 차이 큼, 부분 탈피 모호
- `eating_prey` 모호 (먹잇감 안 보일 때 stalking인지 moving인지)

### 6.2 데이터 한계
- 159건 평가셋 단일 카메라 (`3a6cffbf-...`) 한 마리 게코
- 다른 환경(조명·각도·dish 종류)에서 일반화 검증 부족
- 사용자별 환경 다양성 → HITL ping으로 점진 수집

### 6.3 모델 한계
- Gemini Flash confidence calibration 안 됨 (0.95+도 76% 정확도)
- Pro 교차 검증 비용 1/10 → 정확도 격차 미세 (Round 2 결정)
- 비결정성 — temperature 0.1로도 같은 클립 재호출 시 1~2% 라벨 흔들림

### 6.4 평가 한계
- 159건 = 모션 트리거 클립만 (idle 클립 미포함)
- GT 라벨러 단일 (사용자 본인) → labeling bias 가능
- raw 9-class 평가 vs UI 8-class 평가 둘 다 추적 (raw 81.8% / merged 86.2%)

---

## 7. 다음 단계

| 카드 | 상태 | 위치 |
|---|---|---|
| **(A) UX feeding-merge** — drinking + eating_paste → `feeding` UI 통합 | ✅ 완료 (2026-05-02) | [`specs/feature-vlm-feeding-merge-ux.md`](../specs/feature-vlm-feeding-merge-ux.md) |
| **(C) HITL ping** — 일일 5건 + opt-in + low-conf/confusion-prone 트리거 | 🚧 spec 단계 | [`specs/feature-vlm-hitl-ping.md`](../specs/feature-vlm-hitl-ping.md) |
| **(B) 메타데이터 보강** — dish detection / before-after | 미착수 | — |
| **다음 라운드 평가셋** — 신규 클립 + 다른 환경 + 다른 종 추가 | 미착수 | — |
| **Fine-tune** — HITL 답 충분히 누적되면 사용자별 모델 보정 | 미착수 (HITL 누적 후) | — |

---

## 8. 재현 + 평가 방법

### 8.1 환경
```bash
cd /Users/baek/petcam-lab/web
npm install        # Node deps
uv sync            # Python deps (프로젝트 루트에서)
cp .env.example .env.local  # GEMINI_API_KEY 등 채우기
```

### 8.2 평가 (현재 v3.5 baseline)
```bash
uv run python eval/v35/analyze-v35-full.py
# → confusion matrix + raw / feeding-merged 정확도
```

### 8.3 신규 모델/prompt 평가 (다른 에이전트 시나리오)
1. prompt 변경 → `web/prompts/{system_base,species/crested_gecko}.md` 편집
2. 159건 재추론 → `web/src/app/api/inference/route.ts` 호출 (또는 batch script)
3. 결과 jsonl 저장 → `web/eval/v3X/{name}-zeroshot.jsonl`
4. 분석 → `analyze-v35-full.py` 패턴으로 confusion matrix
5. baseline (86.2%) 비교 → 5-카테고리 분석 (held-correct/recovered/broken/still-wrong)

### 8.4 5-카테고리 분석 (변경 영향 측정)
```
held-correct       : 둘 다 정답
recovered          : 변경 후 정답으로 됨 (변경의 효과)
broken             : 변경 전 정답 → 후 오답 (변경의 부작용)
still-wrong-same   : 둘 다 오답, 같은 라벨로 틀림
still-wrong-changed: 둘 다 오답, 다른 라벨로 틀림
```

**채택 기준** (memory `feedback_fewshot_eating_paste`): Δ > +3%p AND `recovered > broken` 둘 다 충족.

---

## 9. 확장 방향

### 9.1 다른 종
- 코드: `web/prompts/species/{new_species}.md` 추가
- 클래스 가용성: `web/src/types.ts SPECIES_CLASSES`에 분기
- 종별 평가셋 별도 수집

### 9.2 다른 모델
- `web/src/lib/gemini.ts` model_id 교체 (또는 어댑터화)
- Anthropic Claude / OpenAI GPT-4o 영상 입력 비교 가능
- 평가 jsonl 형식 동일 → 같은 분석 스크립트 재사용

### 9.3 Fine-tune
- HITL 답 누적 (`source='human_hitl'`) → 사용자별 데이터셋
- Gemini Tuning API 또는 다른 모델 LoRA
- per-user 보정 (특정 게코 환경 특화) — 결정 #20 부가 기능

---

## 10. 연관 자원

### 10.1 코드 (이 레포)
- `web/src/lib/gemini.ts` — Gemini API 호출 + 디코딩 설정
- `web/src/lib/prompts.ts` — prompt 컴포지션
- `web/prompts/` — system_base + species + v3.5 backups
- `web/src/types.ts` — 클래스 enum + 매핑 함수
- `web/eval/v35/` — 평가 스크립트 5종
- `web/src/app/api/inference/route.ts` — F3 추론 endpoint
- `web/src/app/results/page.tsx` — F3 결과 비교 UI

### 10.2 Spec
- 개발 spec (어떻게):
  - [`specs/feature-poc-vlm-web.md`](../specs/feature-poc-vlm-web.md) — Round 1~3 결정 이력
  - [`specs/feature-vlm-feeding-merge-ux.md`](../specs/feature-vlm-feeding-merge-ux.md) — UX 매핑 (✅ 완료)
  - [`specs/feature-vlm-hitl-ping.md`](../specs/feature-vlm-hitl-ping.md) — HITL ping (🚧 진행 중)
  - [`specs/feature-vlm-feeding-postfilter.md`](../specs/feature-vlm-feeding-postfilter.md) — 폐기된 시도
- SOT (무엇/왜): [`tera-ai-product-master/docs/specs/petcam-poc-vlm.md`](../../tera-ai-product-master/docs/specs/petcam-poc-vlm.md)

### 10.3 자동 메모리 (Claude 로컬)
- `~/.claude/projects/-Users-baek-petcam-lab/memory/`
  - `project_vlm_v35_baseline_lock.md` — 86.2% / 85.7% floor
  - `feedback_vlm_visual_information_limit.md` — 시각 한계 결론
  - `feedback_vlm_rule_overcorrection.md` — prompt tuning ROI 0
  - `feedback_vlm_ux_merge_validation.md` — UX 매핑 정공법
  - `feedback_vlm_error_set_ablation_pattern.md` — 멀티트랙 ablation 방법론

### 10.4 룰
- [`.claude/rules/donts/vlm.md`](../.claude/rules/donts/vlm.md) — VLM 작업 don'ts (룰 5: evidence-forcing 신중, 룰 6: deterministic config)

---

## 부록 A. 외부 에이전트에게 검토 요청할 때

이 문서 + 다음 자원 첨부:

1. **이 문서** (`docs/VLM-CLASSIFIER.md`) — 컨텍스트
2. **현재 prompt** — `web/prompts/backups/system_base.v3.5.md` + `crested_gecko.v3.5.md`
3. **평가 데이터** — `web/eval/v35/v3.5-zeroshot.jsonl` (159건 jsonl)
4. **GT 라벨 export** — Supabase `behavior_logs(source='human')` → jsonl로 export 필요 (현재 미존재)
5. **잔존 오답 분석** — `analyze-v35-full.py` 출력 (mismatch top-10)
6. **시도/폐기 이력** — 본 문서 §5 또는 SOT §"Round 3 baseline 깨기 실패"

검토 요청 예시:
- "이 prompt 비판해줘" — Gemini Pro/Claude Opus
- "이 평가 코드 결정성/엣지케이스 측면 review" — Codex
- "다른 모델로 같은 159건 평가하면?" — Anthropic Claude / OpenAI GPT-4o
- "잔존 오답 26건이 정말 시각 한계인지, 사람한테 보여줘서 검증" — 사용자 + 다른 사육자

---

## 부록 B. 자주 묻는 질문

**Q. 왜 prompt tuning을 멈췄나?**
A. baseline 깨기 시도 6번 모두 floor 미달. 잔존 오답이 prompt가 아닌 시각 정보 한계라는 결론. §5 참조.

**Q. 왜 86.2%를 production이라 하나? 더 높일 수 있지 않나?**
A. ① 향후 정확도 회귀 판단 baseline 필요 ② prompt tuning ROI 0 결론 후 다음 정공법(UX/HITL)으로 진행하기 위한 락인. floor 미달 시 채택 X.

**Q. UI에서 hiding은 왜 그대로 노출되나?**
A. UX 매핑은 평가 레이어 한정 (motion-trigger 충돌 보정용). UI에선 hiding raw 보존. drinking/eating_paste의 feeding 통합과는 별개 결정.

**Q. 9 클래스 raw 라벨은 왜 보존하나?**
A. 향후 모델 평가·fine-tune에서 분리 비교 필요. 사용자 UX는 통합, GT 정밀도는 raw 유지가 단일 ground truth 원칙.

**Q. 다른 종으로 확장하려면?**
A. §9.1 참조. prompt 종별 파일 추가 + 클래스 가용성 분기 + 종별 평가셋. 인프라 동일.

**Q. fine-tune 안 하나?**
A. HITL 답 충분히 누적된 후 별도 spec. 현재는 zero-shot으로 충분 (86.2%).
