# eval/

VLM 분류 평가 스크립트. 자기충족 (Supabase 무관, stdlib + 모델 SDK 만).

## 파일

| 파일 | 역할 |
|---|---|
| `run.py` | 모델 추론 — 영상 → jsonl. ABC 패턴으로 Gemini/Anthropic/OpenAI 어댑터. |
| `analyze.py` | 정확도 + confusion matrix + mismatch 리스트. |
| `compare.py` | 두 jsonl 5-카테고리 비교 (held-correct/recovered/broken/...). |

---

## 1. baseline 검증 (영상 없이)

`data/eval-159.jsonl` (모델 출력 baseline) + `data/gt-159.jsonl` (GT) 만으로:

```bash
uv run python eval/analyze.py --confusion
```

기대 출력:
```
## 정확도
  raw 9-class:           130/159 = 81.8%
  feeding-merged (UI):   133/159 = 83.6%
  + hiding→moving (eval): 136/159 = 85.5%   ← v3.5 production baseline
```

confusion matrix 와 mismatch top-20 동시 출력. mismatch 클립별 reasoning 포함.

---

## 2. 새 모델/prompt 시도 (영상 필요)

### 영상 준비
- 본 레포 운영자 (Tera AI) 에게 159 클립 영상 요청
- 영상 디렉토리: `{video_dir}/{clip_id}.mp4` 패턴

### 추론
```bash
export GEMINI_API_KEY=...

uv run python eval/run.py \
  --videos /path/to/videos \
  --target-clips data/eval-159.jsonl \
  --out my-results.jsonl \
  --model gemini
```

`--target-clips` 으로 평가 대상 159건만 처리. 재실행 안전 (기존 ok 결과 스킵).

### 분석
```bash
uv run python eval/analyze.py --eval my-results.jsonl
```

### baseline vs 새 시도 비교
```bash
uv run python eval/compare.py \
  --baseline data/eval-159.jsonl \
  --new my-results.jsonl
```

5-카테고리 + Δ + 채택 판정 출력.

---

## 3. 다른 모델 어댑터 추가

`run.py` 의 `AnthropicAdapter` / `OpenAIAdapter` 는 stub. 구현 가이드는 클래스 docstring 참조.

핵심:
1. `ModelAdapter` ABC 상속
2. `infer(clip_id, video_bytes, system_prompt) -> InferenceResult` 구현
3. `ADAPTERS` dict 에 등록
4. 호출: `python eval/run.py --model {your_name} ...`

**필수 generationConfig** (Round 1 검증, [vlm.md rule 6](../.claude/rules/donts/vlm.md)):
- temperature: 0.1 (또는 0)
- top_p: 0.95
- response_mime_type: 'application/json' (모델이 지원하면)

이유: 분류 task 결정성. temperature 1.0 = 같은 클립 호출마다 다른 라벨.

---

## 4. 커스텀 평가셋

자기 영상셋으로 평가하려면:

1. 영상 파일 → `{clip_id}.mp4` 명명 (UUID 권장)
2. GT 라벨 jsonl 작성:
   ```jsonl
   {"clip_id": "abc123", "gt_action": "moving"}
   {"clip_id": "def456", "gt_action": "eating_paste"}
   ```
3. `run.py` 로 추론
4. `analyze.py` / `compare.py` 분석

`gt_action` 은 `data/classes.json` 의 `raw_classes.values` 중 하나여야 함 (9개).

---

## 5. 의존성

```bash
uv add google-generativeai python-dotenv  # Gemini 사용 시
uv add anthropic                            # Anthropic 추가 시
uv add openai                               # OpenAI 추가 시
```

stdlib만 쓰는 `analyze.py`/`compare.py` 는 추가 의존성 없음.

---

## 6. 트러블슈팅

### "GEMINI_API_KEY 환경변수 없음"
```bash
export GEMINI_API_KEY=your-key
# 또는 .env 파일 + python-dotenv
```

### "videos 디렉토리 없음"
영상 파일 받기 — 본 레포 운영자에게 요청. privacy 사유로 portable 패키지에 미포함.

### "JSON FAIL"
모델 응답이 valid JSON이 아님. 가능 원인:
- response_mime_type 미설정 (Gemini 외 모델)
- 모델이 markdown 코드블록 (```json ... ```) 으로 감싸서 반환 → 파싱 전 strip 필요

### eval/gt clip_id 불일치
`analyze.py` 출력의 "교집합" 확인. 불일치하면:
- file naming 다름 (대소문자, 확장자 포함)
- 다른 평가셋 mix
