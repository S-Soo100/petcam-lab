# SegmentVLM Experiments

> Track B side experiment. Track A Zero-shot VLM production baseline 과 분리해서 관리한다.

## 트랙 분리

| Track | 이름 | 저장 위치 | 의미 |
|---|---|---|---|
| A | Zero-shot VLM | `web/eval/v35/`, `backend/vlm/` | production baseline. Gemini v3.5 top-1 |
| B | SegmentVLM | `experiments/segment-vlm/`, `scripts/segmentvlm_sample_poc.py` | side experiment. event/contact sheet 기반 비교 |

SegmentVLM 산출물은 production DB 에 쓰지 않는다. 샘플 분석은 `codex-frame-analysis.json` 같은 artifact 로 남긴다.

주의: repo `.gitignore` 정책상 `*.mp4`, `*.jpg`, `*.png` 는 커밋되지 않는다. `segmentvlm_sample.json` 안의 `event_mp4`, `contact_sheet`, `key_frames` 경로는 로컬 재현 산출물 위치를 가리킨다. 다른 환경에서 이미지를 다시 보려면 `scripts/segmentvlm_sample_poc.py` 로 재생성한다.

## 현재 샘플 요약

| clip_id | GT | Zero-shot raw | SegmentVLM/CodexFrame | outcome | review |
|---|---|---|---|---|---|
| `18585ae4` | `defecating` | `moving` | `defecating` | recovered | no |
| `31da5684` | `shedding` | `moving` | `shedding` | recovered_but_review | yes |
| `94cd5cd3` | `defecating` | `moving` | `defecating` | recovered | no |
| `b0b57a47` | `defecating` | `moving` | `defecating` | recovered_but_review | yes |
| `cc9463c9` | `eating_prey` | `moving` | `moving` | still_wrong_or_insufficient_visual_evidence | yes |
| `d88e1390` | `defecating` | `drinking` | `defecating` | recovered | no |
| `d95e9eaa` | `drinking` | `eating_paste` | `drinking` | recovered | no |

현재 7건 중:
- `recovered`: 4건
- `recovered_but_review`: 2건
- `still_wrong_or_insufficient_visual_evidence`: 1건

해석:
- `defecating` 과 `drinking` 오답은 contact sheet + event context 에서 회복 신호가 좋다.
- `shedding` 은 회복 가능하지만 시각 증거가 약해 human review 유지가 맞다.
- `eating_prey` 는 frame sample 만으로 prey capture 증거가 약해서 아직 회복하지 못했다.

## 샘플 생성

```bash
uv run python scripts/segmentvlm_sample_poc.py --limit 5
uv run python scripts/segmentvlm_sample_poc.py --clip-id d95e9eaa
```

입력 후보는 `web/eval/v35/error-set-154.jsonl` 의 mismatch 목록이다.

샘플 디렉토리:

```text
experiments/segment-vlm/sample-{clip8}/
  segmentvlm_sample.json
  event_00.mp4          # gitignore, 로컬 재생성 산출물
  event_00_contact.jpg  # gitignore, 로컬 재생성 산출물
  frames/
  codex-frame-analysis.json
```

## 다음 작업

1. 샘플 수를 30~50건까지 늘린다.
2. `recovered_but_review` 와 `still_wrong` 을 별도 그룹으로 분석한다.
3. CodexFrameAnalyzer 결과를 Claude/OpenAI/local frame analyzer 와 비교한다.
4. Track A baseline 과 같은 GT 기준으로 P0 recall / false highlight / review rate 를 계산한다.
