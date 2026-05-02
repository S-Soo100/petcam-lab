# CHALLENGE — 이걸 깨봐라

> v3.5 production baseline **85.5%**(159) / **85.7%**(154 floor). 6번 시도 모두 실패. 외부 모델·에이전트가 **다른 채널**로 뚫어보길 환영. 단, 안티패턴 4종은 이미 검증되어 ROI 0이니 반복 금지.

---

## 1. 깨야 할 baseline

| 평가셋 | 매핑 | 정확도 | 의미 |
|---|---|---|---|
| 159건 raw | 9-class | 130/159 = **81.8%** | 모델 출력 그대로 |
| 159건 | feeding-merged (UI) | 133/159 = **83.6%** | 사용자 화면 노출 정확도 |
| 159건 | feeding + hiding-merge (eval) | 136/159 = **85.5%** | **production 락인 baseline** |
| 154건 (floor) | feeding + hiding-merge (eval) | 132/154 = **85.7%** | unseen 5건 제외, 실효 floor |

**채택 기준 (둘 다 충족):**
1. **Δ > +3.0%p** — feeding-merged eval 기준
2. **recovered > broken** — 5-카테고리 분석에서 회복 > 파괴

이유: 작은 +1%p delta는 noise일 수 있고, 회복=파괴면 분포만 바뀐 거지 실력은 동등.

---

## 2. 잔존 오답 26건의 본질

**→ 시각 정보 한계.** 영상 픽셀에 정답 신호가 없는 케이스가 26건 중 다수.

### 그룹별 분포

| 그룹 | 패턴 | 건수 | 처방 |
|---|---|---|---|
| G1 | moving → eating_paste 오버트리거 | 12 | UX 매핑 + HITL |
| G2 | defecating mismatch | 5 | HITL ping |
| G3 | drinking ↔ eating_paste 혼동 | 4 | UX 매핑 ✅ (Round 2 적용) |
| G4 | eating_prey mismatch | 3 | HITL ping |
| G5 | shedding mismatch | 3 | HITL ping |
| 기타 | hiding/unseen edge | 2 | 무시 |

**핵심 통찰:**
- G3 4건은 **drinking + eating_paste 시각적으로 같은 자세 + 같은 dish** → prompt로 못 가른다. UI 통합으로 흡수했음.
- G2/G4/G5 11건은 **모호 케이스** → 사람이 봐도 헷갈림. HITL 정정 외엔 답 없음.
- G1 12건은 prompt + UX 매핑 적용 후에도 잔존 → 다른 채널 필요.

---

## 3. 안티패턴 (반복 금지)

Round 3에서 6번 검증된 실패. 같은 시도 반복하면 ROI 0이다.

### A. evidence-forcing rule
- **시도:** 프롬프트에 "타임스탬프와 함께 근거를 적어라" 룰 추가
- **결과:** v3.2 → -2.6%p, v3.6 → -1.9%p
- **원인:** 모델이 "근거 적어라"를 "정답이라고 우길 근거 적어라"로 해석. 가짜 timestamp 만들어 confabulation.
- **참고:** [`.claude/rules/donts/vlm.md` rule 5](../.claude/rules/donts/vlm.md)

### B. confidence threshold 단독 분기
- **시도:** confidence < 0.7 → uncertain 처리 / > 0.95 → trust
- **결과:** floor 미달
- **원인:** confidence가 calibration 안 됨. 0.95+ 케이스도 76% 정확도. confidence는 모델 자체 추정이라 신뢰도 없음.

### C. clean-slate prompt 재작성
- **시도:** v4 — 기존 룰 모두 버리고 처음부터 작성
- **결과:** -6.9%p
- **원인:** 누적된 도메인 룰의 가치 ↑↑. v3.5는 단순 prompt 아니라 round 1~2 학습이 압축된 자산.

### D. binary 라우터 / post-filter
- **시도:** dish_present + licking_behavior → eating_paste 라우터
- **결과:** 154건 84.42%, floor 85.7% 미달. broken=0/recovered=2/still-wrong=24
- **원인:** 같은 시각 정보, 같은 모델 호출 → 같은 한계. 라우터 = prompt 레이어 변형.

---

## 4. 환영 — 미검증 시도 (시도 가치 ↑)

### A. 다른 모델 영상 입력 비교
- **대상:** Anthropic Claude (Sonnet 4.6 이상), OpenAI GPT-4o, Gemini Pro
- **목표:** Gemini Flash 한계가 모델 한계인지 / Flash 한계인지 구분
- **방법:** `eval/run.py`의 model adapter 패턴으로 같은 평가셋 재실행
- **주의:** 비용 비교 — Gemini Flash 1x 기준 Pro 10x, Claude/GPT 추정 5~20x

### B. 메타데이터 보강
- **대상:** dish detection (ROI box) / before-after frame / 시간대 컨텍스트
- **방법:** VLM 호출 전 OpenCV/YOLO로 외부 시그널 추가 → prompt에 주입
- **목표:** 시각 한계의 보완 시그널. binary 라우터(폐기)와 다름 — VLM 호출 전 단계.

### C. fine-tune
- **대상:** Gemini Flash fine-tune API (지원 시) 또는 다른 vision 모델
- **선결:** GT 라벨 충분한 누적 (현재 159 → 1000+ 필요 추정)
- **주의:** zero-shot baseline 비교 필수, fine-tune이 항상 이기는 게 아님

### D. 사용자별 모델 보정
- **대상:** per-user few-shot (해당 사용자 GT 누적분 사용)
- **이유:** 사육 환경별 dish/조명/각도 편차 큼
- **주의:** few-shot은 prompt-dependent — Round 3에서 동일 example이 v3.3 +3.9%p / v3.4 -5.1%p ([feedback memory](../web/CLAUDE.md))

---

## 5. 평가 방법 (외부 에이전트용)

### 입력
- `data/eval-159.jsonl` — 모델 출력 (or 새 모델로 재추론한 jsonl)
- `data/gt-159.jsonl` — GT 정답 라벨

### 평가 절차

```python
# 1. raw 9-class 정확도
correct_raw = sum(1 for r in eval_jsonl if r['action'] == gt[r['clip_id']]['gt_action'])
accuracy_raw = correct_raw / len(eval_jsonl)

# 2. feeding-merged (UI) 정확도
def to_ui(action):
    return 'feeding' if action in ('drinking', 'eating_paste') else action

correct_ui = sum(1 for r in eval_jsonl if to_ui(r['action']) == to_ui(gt[r['clip_id']]['gt_action']))
accuracy_ui = correct_ui / len(eval_jsonl)

# 3. eval-only hiding-merge 추가 (production baseline 비교용)
def to_eval(action):
    if action == 'hiding': return 'moving'
    return to_ui(action)

correct_eval = sum(1 for r in eval_jsonl if to_eval(r['action']) == to_eval(gt[r['clip_id']]['gt_action']))
accuracy_eval = correct_eval / len(eval_jsonl)
```

### 5-카테고리 비교 (baseline vs 새 시도)

기존 baseline jsonl과 새 시도 jsonl 둘 다 있을 때:

| 카테고리 | 정의 | 의미 |
|---|---|---|
| **held-correct** | 둘 다 정답 | 안전 영역 |
| **recovered** | baseline 오답 → 새 시도 정답 | 새 시도의 이득 |
| **broken** | baseline 정답 → 새 시도 오답 | 새 시도의 손실 |
| **still-wrong-same** | 둘 다 오답, 같은 라벨 | 시각 한계 (시도 무관) |
| **still-wrong-changed** | 둘 다 오답, 다른 라벨 | 라벨이 흔들림 (불안정) |

**채택:** `recovered > broken AND total Δ > +3%p`

---

## 6. 외부 에이전트 행동 가이드

### 시작하기 전에 읽기
1. [`README.md`](README.md) — 1분 onboarding
2. [`HISTORY.md`](HISTORY.md) — 라운드 진화 + 6번 실패 이력
3. [`prompt/system_base.md`](prompt/system_base.md) — 현재 prompt
4. [`data/classes.json`](data/classes.json) — 클래스/매핑 정의

### 절대 하지 말 것
- 안티패턴 4종 재시도 (위 §3)
- baseline 깨지지도 않은 prompt 변경 채택 ("좋아 보인다"로 채택 금지, Δ 측정 필수)
- 5건 cherry-pick으로 결정 ([feedback memory](../web/CLAUDE.md): cherry-pick 진단 무용)

### 필수 절차
1. 새 prompt/모델 → `data/eval-159.jsonl` 형식으로 재추론
2. `analyze.py` (TBD) 또는 위 §5 코드로 정확도 측정
3. `compare.py` (TBD) 또는 5-카테고리 분석
4. **둘 다 충족 시에만** 채택 권장 → 사용자에게 PR/제안

---

## 7. 결과 보고 양식

외부 에이전트가 시도 결과 공유 시:

```markdown
## 시도: {짧은 이름}

### 변경
- {prompt/model/code 어디 어떻게}

### 결과 (159건 평가)
- raw: {X}/159 = {X.X}%
- feeding-merged: {X}/159 = {X.X}%
- production baseline: {X}/159 = {X.X}% (vs 85.5%, Δ = ±X.Xp)

### 5-카테고리
- held-correct: {N}
- recovered: {N}
- broken: {N}
- still-wrong-same: {N}
- still-wrong-changed: {N}

### 결론
- 채택 권장: YES/NO ({이유})
- 다음 단계: {있다면}
```

---

## 8. SOT 문서 (본 레포 운영자만 접근)

이 portable 패키지는 자기충족이지만, 더 깊은 컨텍스트는 본 레포에 있음:

- [`docs/VLM-CLASSIFIER.md`](../docs/VLM-CLASSIFIER.md) — 10섹션 + 부록 2개
- [`tera-ai-product-master/docs/specs/petcam-poc-vlm.md`](../../tera-ai-product-master/docs/specs/petcam-poc-vlm.md) — 22 결정 전체 + 비즈니스 컨텍스트
- [`.claude/rules/donts/vlm.md`](../.claude/rules/donts/vlm.md) — VLM 작업 안티패턴 룰
