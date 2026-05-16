# SegmentVLM 샘플 — d95e9eaa

> 기존 Gemini v3.5 오답 케이스를 SegmentVLM + CodexFrameAnalyzer 방식으로 수동 검증한 샘플.

## 케이스

- `clip_id`: `d95e9eaa-3203-478b-9d0b-cfc05b7b9f2f`
- 원본 영상: `/Users/baek/petcam-lab/inbox/0430/물 마시기.mp4`
- GT: `drinking`
- 기존 Gemini v3.5 raw: `eating_paste`
- mismatch 유형: `drinking → eating_paste`

## SegmentVLM 처리

영상 길이가 8.64초라 event 하나로 처리했다.

- `segmentvlm_sample.json` — 원본 영상/GT/raw/segmentation/event metadata
- `event_00.mp4` — 잘라낸 event clip
- `event_00_contact.jpg` — Codex/Claude/OpenAI frame analyzer 가 우선 보는 contact sheet
- `frames/` — 개별 key frame
- `codex-frame-analysis.json` — CodexFrameAnalyzer 수동 판정 결과

## CodexFrameAnalyzer 판정

결론: `drinking` 으로 회복.

근거:
- 투명 벽면에 물방울이 보인다.
- 도마뱀이 벽면 가까이에 붙어 있고 머리/입 방향이 젖은 벽 쪽이다.
- paste dish 또는 불투명 먹이원이 보이지 않는다.
- licking-like action 이지만 맥락상 paste feeding 보다 wall-droplet drinking 이 더 자연스럽다.

## 다음 샘플 재현 힌트

상세 절차는 `specs/experiment-event-segment-vlm.md` 의 “다른 에이전트용 Quickstart” 와 “산출물 계약” 섹션을 따른다.
