# vlm-classifier-portable

> **크레스티드 게코 행동 분류 VLM 패키지** (Tera AI Petcam). 외부 모델·에이전트에게 전달 가능한 자기충족 패키지. v3.5 Gemini Flash zero-shot baseline **85.5%** (159 클립).
>
> 본 레포 `petcam-lab` 의 VLM 행동 분류 기능을 떼낸 것. 다른 LLM/에이전트로 교차 검증·업그레이드 시도 환영.

---

## 1분 onboarding

**무엇:** 게코 도마뱀 영상 클립 → 9 행동 클래스 중 하나 분류 (zero-shot, no fine-tune)
**입력:** 5~30초 영상 (ELDP·움직임 트리거 → 24fps RGB)
**출력:** `{action, confidence, reasoning}` JSON
**모델:** Gemini 2.5 Flash (vision native, video 직접 입력)
**현재 정확도:** 159건 평가 85.5% (136/159, production baseline 락인, 2026-04-30)

---

## 빠른 사용 (외부 에이전트)

### 1. 데이터 보기

```bash
ls vlm-classifier-portable/data/
# eval-159.jsonl   ← 모델 출력 159건
# gt-159.jsonl     ← GT 정답 라벨 159건
# classes.json     ← 클래스 정의 + 매핑 룰
```

### 2. 베이스라인 검증

```python
import json

eval_jsonl = [json.loads(l) for l in open('data/eval-159.jsonl')]
gt = {json.loads(l)['clip_id']: json.loads(l) for l in open('data/gt-159.jsonl')}

def to_eval(action):
    if action == 'hiding': return 'moving'
    if action in ('drinking', 'eating_paste'): return 'feeding'
    return action

correct = sum(1 for r in eval_jsonl
              if r.get('ok') and to_eval(r['action']) == to_eval(gt[r['clip_id']]['gt_action']))
print(f"production baseline: {correct}/{len(eval_jsonl)} = {correct/len(eval_jsonl)*100:.1f}%")
# → 136/159 = 85.5%
```

### 3. 새 모델/prompt 시도

[`CHALLENGE.md`](CHALLENGE.md) 읽고 시작. 안티패턴 4종 회피 필수.

### 4. 교차 리뷰 의뢰

[`for-cross-review.md`](for-cross-review.md) 의 §1~§4 중 하나 골라 외부 LLM에 전달.

---

## 디렉토리 구조

```
vlm-classifier-portable/
├── README.md              ← 이 파일
├── CHALLENGE.md           ← 깨야 할 baseline + 안티패턴 + 환영 시도
├── HISTORY.md             ← Round 1~3 진화 + 6번 실패 이력 + 26 잔존 오답
├── for-cross-review.md    ← 외부 LLM/에이전트 교차 리뷰 지시문 (§1~§4)
│
├── prompt/
│   ├── system_base.md            ← v3.5 production lock prompt
│   └── species/crested_gecko.md  ← 종별 분기 (현재 1종)
│
├── data/
│   ├── eval-159.jsonl     ← 159건 모델 출력 (v3.5 baseline)
│   ├── gt-159.jsonl       ← 159건 GT 정답 라벨
│   ├── classes.json       ← raw 9 / UI 8 + 매핑 룰
│   ├── README.md          ← 데이터 형식 설명
│   └── _export-gt.py      ← (운영자만) Supabase → gt-159.jsonl 재생성
│
└── eval/
    ├── README.md          ← 사용법
    ├── run.py             ← 모델 어댑터 (Gemini 구현, Anthropic/OpenAI 포팅 가이드)
    ├── analyze.py         ← 정확도 + confusion matrix + mismatch top-N
    └── compare.py         ← 5-카테고리 비교 (baseline vs new)
```

---

## 클래스 정의 (요약)

raw 9-class (DB/GT 단위):
- `eating_paste` — 과일 퓨레 핥기 (크레스티드/가고일만)
- `eating_prey` — 곤충 사냥 + stalking 자세
- `drinking` — 물·이슬 핥기
- `defecating` — 배변
- `shedding` — 탈피
- `basking` — 일광욕
- `hiding` — 은신처 정지 (motion-trigger 카메라엔 거의 없음)
- `moving` — 일반 이동
- `unseen` — 화면에 없음

UI 8-class (사용자 노출):
- `feeding` ← drinking + eating_paste 통합 (시각 구분 불가, 사용자 직관)
- 나머지 7 동일

자세한 정의/매핑/tie-break: [`data/classes.json`](data/classes.json)

---

## 의존성

**zero-shot 평가 재현:** Python 3.10+, `numpy`, `google-generativeai` (Gemini 사용 시)
**다른 모델 비교:** `anthropic`, `openai` 등 (모델 어댑터 추가 시)

설치:
```bash
pip install google-generativeai numpy python-dotenv
# or
uv add google-generativeai numpy python-dotenv
```

API key:
```bash
export GEMINI_API_KEY=...
# 다른 모델 시:
export ANTHROPIC_API_KEY=...
export OPENAI_API_KEY=...
```

---

## 다음 단계 — 외부 에이전트가 할 수 있는 것

1. **다른 모델 비교** — Anthropic Sonnet 4.6+ / OpenAI GPT-4o / Gemini Pro 동일 평가 ([for-cross-review.md §3](for-cross-review.md))
2. **prompt critique** — v3.5의 약점 발견, 안티패턴 회피하면서 ([for-cross-review.md §1](for-cross-review.md))
3. **잔존 오답 검증** — 26건이 정말 시각 한계인지 다른 모델 시각으로 ([for-cross-review.md §4](for-cross-review.md))
4. **메타데이터 보강 제안** — dish detection / before-after frame / 시간대 컨텍스트 ([CHALLENGE.md §4-B](CHALLENGE.md))

**금지:** 안티패턴 4종 (CHALLENGE.md §3) — Round 3에서 6번 검증된 실패. ROI 0.

---

## 프로젝트 컨텍스트 (선택 읽기)

이 패키지는 자기충족이지만, 더 깊은 컨텍스트는 본 레포에 있음:

- 본 레포: `/Users/baek/petcam-lab/`
- SOT 문서: [`docs/VLM-CLASSIFIER.md`](../docs/VLM-CLASSIFIER.md) (10섹션 + 부록 2개)
- 비즈니스 컨텍스트: [`tera-ai-product-master/docs/specs/petcam-poc-vlm.md`](../../tera-ai-product-master/docs/specs/petcam-poc-vlm.md) (22 결정 전체)

---

## 라이센스 / 사용 조건

- 본 데이터셋 (eval-159.jsonl, gt-159.jsonl)은 Tera AI Petcam 사용자 동의 하에 수집된 영상 클립의 라벨 메타데이터.
- 영상 자체는 본 패키지에 포함되지 않음 (privacy). 평가/검증용으로만 사용.
- 외부 LLM 호출 시 영상 데이터는 본 레포 운영자가 직접 처리.
