# SegmentVLM Experiments

> Track B side experiment. Track A Zero-shot VLM production baseline 과 분리해서 관리한다.

에이전트 주의: **SegmentVLM = Track B** 다. Track A는 비교 기준선이고 SegmentVLM 자체가 아니다. 사용자가 SegmentVLM 을 물으면 event segmentation / contact sheet / analyzer backend / selective fallback 중심으로 답한다.

## 트랙 분리

| Track | 이름 | 저장 위치 | 의미 |
|---|---|---|---|
| A | Zero-shot VLM | `web/eval/v35/`, `backend/vlm/` | production baseline. Gemini v3.5 top-1 |
| B | SegmentVLM | `experiments/segment-vlm/`, `scripts/segmentvlm_sample_poc.py` | side experiment. event/contact sheet 기반 비교 |

SegmentVLM 산출물은 production DB 에 쓰지 않는다. 샘플 분석은 `codex-frame-analysis.json` 같은 artifact 로 남긴다.

주의: repo `.gitignore` 정책상 `*.mp4`, `*.jpg`, `*.png` 는 커밋되지 않는다. `segmentvlm_sample.json` 안의 `event_mp4`, `contact_sheet`, `key_frames` 경로는 로컬 재현 산출물 위치를 가리킨다. 다른 환경에서 이미지를 다시 보려면 `scripts/segmentvlm_sample_poc.py` 로 재생성한다.

## Selective fallback 규칙

VT label 이 있는 초기 검증 단계에서는 전체 159개를 전부 SegmentVLM 으로 돌리지 않는다. 먼저 Track A Zero-shot VLM 결과와 VT label 을 비교하고, 불일치한 clip 만 Track B로 넘긴다.

```text
VT label == Track A prediction → 통과
VT label != Track A prediction → SegmentVLM artifact 생성
```

이 규칙은 비용을 낮추면서 Track B의 실제 가치를 빠르게 보는 장치다. 판단 기준은 "전체 정확도"보다 "Track A가 틀린 항목 중 몇 개를 회복했는가"를 우선한다.

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
uv run python scripts/claude_segmentvlm_batch.py --all --model sonnet
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
  claude-blind-input.json
  claude-frame-analysis.json
  codex-blind-input.json
  codex-cli-frame-analysis.json
```

## ClaudeFrameAnalyzer blind batch — 2026-05-16

Claude CLI (`claude-sonnet-4-6`, `--model sonnet`) 로 SegmentVLM blind batch 를 실행했다.

실행 원칙:
- Claude 입력에서 `gt_action`, `baseline_action`, `baseline_error`, `source_video`, `notes` 를 제거했다.
- Claude 에게는 `claude-blind-input.json`, contact sheet, key frames, event metadata 만 제공했다.
- Claude 출력은 `claude-frame-analysis.json` 으로 정규화했다.
- GT 비교는 Claude 호출 이후 `claude-batch-summary.json` 에서만 수행했다.

범위:
- mismatch 후보: 26건
- 로컬 원본 영상 발견: 9건
- 원본 영상 없음: 17건 (`storage/clips/...` 경로가 현재 머신에 없음)

결과:

| clip_id | GT | Zero-shot raw | ClaudeFrame | outcome | review |
|---|---|---|---|---|---|
| `18585ae4` | `defecating` | `moving` | `defecating` | recovered | yes |
| `31da5684` | `shedding` | `moving` | `moving` | still_wrong_but_review | yes |
| `94cd5cd3` | `defecating` | `moving` | `moving` | still_wrong_but_review | yes |
| `b0b57a47` | `defecating` | `moving` | `defecating` | recovered | yes |
| `cc9463c9` | `eating_prey` | `moving` | `moving` | still_wrong_but_review | yes |
| `d88e1390` | `defecating` | `drinking` | `defecating` | recovered | yes |
| `d95e9eaa` | `drinking` | `eating_paste` | `drinking` | recovered | yes |
| `dfcf1099` | `eating_prey` | `moving` | `moving` | still_wrong_but_review | yes |
| `e0589541` | `defecating` | `moving` | `unknown` | still_wrong_but_review | yes |

집계:
- `recovered`: 4/9
- `still_wrong_but_review`: 5/9
- `needs_human_review`: 9/9
- Claude CLI reported cost 합계: 약 `$1.78` / 9건

성공률 추정:
- 현재 9건은 Track A가 이미 틀린 mismatch 샘플이므로, Track A 기준 정답률은 0/9 이다.
- ClaudeFrameAnalyzer blind batch 는 4/9 를 GT label 로 회복했다. 즉 Track A 오답에 대한 recovery rate 는 44.4% 다.
- 154건 평가셋에서 Track A 오답 26건 전체에 같은 회복률이 적용된다고 가정하면, 약 11~12건을 추가 회복한다.
- 이 낙관 가정에서는 전체 정확도가 대략 83.1% 에서 90~91% 근처까지 올라갈 수 있다.
- 단, 현재 샘플은 9건뿐이고 원본 누락 17건을 아직 못 돌렸으므로 운영 추정은 더 보수적으로 봐야 한다. 자동 확정 기준으로는 86~88%, HITL selective fallback 까지 포함하면 90% 근처를 목표로 볼 수 있다.

해석:
- `defecating`, `drinking` 일부는 ClaudeFrameAnalyzer blind 조건에서도 회복했다.
- `shedding`, `eating_prey` 는 contact sheet 만으로 회복하지 못했다.
- Claude 는 보수적으로 전 건을 human review 로 남겼다. 운영용 자동 확정기보다는 reviewer / second opinion 쪽에 가깝다.
- Claude CLI 가 JSON schema 요청을 가끔 prose 로 반환해서, batch runner 는 prose fallback parser 로 정규화한다.

## CodexFrameAnalyzer blind batch — 2026-05-18

Codex CLI (`gpt-5.5`, `codex exec --image`) 로 같은 9건을 SegmentVLM blind batch 로 실행했다.

실행 원칙:
- 기존 수동 `codex-frame-analysis.json` 과 충돌하지 않도록 Codex CLI 결과는 `codex-cli-frame-analysis.json` 으로 저장했다.
- Codex 입력에서 `gt_action`, `baseline_action`, `baseline_error`, `source_video`, `notes` 를 제거했다.
- contact sheet / key frames 는 `codex exec --image` 로 첨부하고, blind metadata 는 prompt 안에 직접 넣었다.
- GT 비교는 Codex 호출 이후 `codex-cli-batch-summary.json` 에서만 수행했다.

결과:

| clip_id | GT | Zero-shot raw | ClaudeFrame | CodexCLIFrame | Codex outcome | review |
|---|---|---|---|---|---|---|
| `18585ae4` | `defecating` | `moving` | `defecating` | `moving` | still_wrong | no |
| `31da5684` | `shedding` | `moving` | `moving` | `moving` | still_wrong | no |
| `94cd5cd3` | `defecating` | `moving` | `moving` | `defecating` | recovered | yes |
| `b0b57a47` | `defecating` | `moving` | `defecating` | `defecating` | recovered | yes |
| `cc9463c9` | `eating_prey` | `moving` | `moving` | `eating_prey` | recovered | yes |
| `d88e1390` | `defecating` | `drinking` | `defecating` | `defecating` | recovered | no |
| `d95e9eaa` | `drinking` | `eating_paste` | `drinking` | `drinking` | recovered | no |
| `dfcf1099` | `eating_prey` | `moving` | `moving` | `moving` | still_wrong_but_review | yes |
| `e0589541` | `defecating` | `moving` | `unknown` | `shedding` | still_wrong | no |

집계:
- Codex CLI `recovered`: 5/9
- Codex CLI `still_wrong`: 3/9
- Codex CLI `still_wrong_but_review`: 1/9
- Codex CLI `needs_human_review`: 3/9
- ClaudeFrameAnalyzer 같은 9건: 4/9 recovered, 9/9 review

해석:
- Codex CLI 는 Claude 보다 자동 판정 성향이 강했다. review 를 적게 남기고, 5/9 를 회복했다.
- `94cd5cd3`, `cc9463c9` 는 Codex CLI 만 회복했다.
- `18585ae4` 는 Claude 만 회복했다.
- Codex CLI 는 `e0589541` 을 `shedding` 으로 오판했다. 자동 확정기로 쓰기 전에 false positive 검증이 필요하다.
- 현재 신호만 보면 ChatGPT/Codex 계열은 SegmentVLM analyzer backend 후보로 충분히 테스트 가치가 있다.

## 다음 작업

1. 샘플 수를 30~50건까지 늘린다.
2. selective fallback 기준으로 mismatch 전체 후보 수와 실제 실행 수를 기록한다.
3. `recovered_but_review` 와 `still_wrong` 을 별도 그룹으로 분석한다.
4. CodexFrameAnalyzer / ClaudeFrameAnalyzer / local frame analyzer 를 30~50건 blind set 에서 비교한다.
5. Track A baseline 과 같은 GT 기준으로 P0 recall / false highlight / review rate / cost multiplier 를 계산한다.
