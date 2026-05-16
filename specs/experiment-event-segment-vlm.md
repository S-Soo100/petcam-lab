# Experiment — SegmentVLM 파이프라인

> 1~4분 영상을 통째로 한 번 분류하지 않고, motion/ROI 기반 이벤트 세그먼트로 쪼개서 각각 분석한 뒤 원본 영상 타임라인으로 병합하는 사이드 플랜.

**상태:** 🚧 제안 / 실험 설계
**작성:** 2026-05-16
**연관 SOT:** 없음 — 현재 production VLM 파이프라인의 대안 검증용 내부 실험

## 1. 목적

현재 production 분석 전략은 `60초 motion clip → Gemini VLM top-1 행동 라벨` 이다. 이 방식은 단순하고 운영 비용이 낮지만, 1~4분 영상 안에 여러 행동이 섞이거나 짧은 P0 행동이 묻히면 한 라벨로 뭉개질 수 있다.

이 실험은 **영상을 잘게 쪼개서 분석하면 행동 인식 품질과 설명 가능성이 좋아지는지** 검증한다.

이 전략의 이름은 **SegmentVLM** 으로 고정한다. 한국어 문서/대화에서는 **세그먼트VLM** 또는 **세그먼트 분석법** 이라고 부른다.

정의:

> **SegmentVLM**: 긴 영상을 motion/ROI 기반 짧은 이벤트 세그먼트로 나눈 뒤, 각 세그먼트를 VLM으로 분석하고 결과를 원본 영상 타임라인으로 병합하는 분석 전략.

핵심 질문:
- 60초~4분 전체 영상을 한 번 보는 것보다, 5~15초 event 여러 개를 보는 게 P0 행동을 더 잘 잡나?
- ROI/시간대/motion 메타를 VLM에 같이 주면 ambiguous case를 더 잘 분리하나?
- 정확도 상승이 작더라도, HITL 검수 대상과 타임라인 설명 품질이 좋아지나?

## 1.1 투 트랙 분리 원칙

이후 영상 분석 전략은 **두 트랙을 완전히 분리**해서 다룬다.

| 트랙 | 이름 | 역할 | 현재 상태 | 금지 |
|---|---|---|---|---|
| Track A | **Zero-shot VLM** | production baseline. 60초 motion clip 전체를 Gemini v3.5 prompt로 top-1 분류 | 운영 기준선 / 회귀 가드 | SegmentVLM 실험 결과를 검증 없이 섞지 않음 |
| Track B | **SegmentVLM** | side experiment. 긴 영상을 event segment로 쪼개고 event별 분석 후 timeline 병합 | 샘플 검증 중 | production `behavior_logs`에 바로 쓰지 않음 |

Track A는 안정성과 회귀 가드가 핵심이다. 이미 `v3.5 85.5%` baseline, feeding merge, HITL 방향성이 lock-in 되어 있다. 여기서는 prompt/모델을 가볍게 흔들지 않는다.

Track B는 탐색과 비교가 핵심이다. SegmentVLM 은 Track A를 당장 대체하지 않고, mismatch case에서 **회복 가능성 / 설명 가능성 / HITL 라우팅 가치**를 본다.

판단 기준:
- Track B가 몇 샘플에서 좋아 보여도 production 전환하지 않는다.
- 최소 30~50개 mismatch/representative clip 비교 리포트가 필요하다.
- Track B 결과는 `experiments/segment-vlm/` 아래 artifact 로만 남긴다.
- 두 트랙의 metric은 같은 GT 기준으로 비교하되, 저장 경로와 결론은 분리한다.

## 2. 스코프

### In (이번 스펙에서 한다)

- production 코드와 DB write 경로를 건드리지 않는 **사이드 실험 파이프라인** 작성
- 입력 mp4 1개 또는 R2 key 목록을 받아 event segment 후보 생성
- 기존 `MotionDetector` 아이디어를 확장해 `changed_ratio` 시계열 기반 event boundary 추출
- 카메라별 수동 ROI config 적용 (`food_dish`, `water_dish`, `hide`, `basking` 등)
- event별 deterministic metadata 생성
  - `start_sec`, `end_sec`, `duration_sec`
  - `motion_score`, `peak_changed_ratio`
  - ROI별 변화량, nearest ROI, ROI 진입/이탈 힌트
- event mp4 + metadata를 VLM에 넣는 평가 스크립트 작성
- Gemini / OpenAI-Codex 계열 / Claude / local VLM 을 analyzer backend 로 분리해 비교 가능하게 설계
- 기존 baseline 결과와 event 방식 결과를 human GT 기준으로 비교
- 산출물은 `experiments/event-vlm/` 아래 JSONL/리포트로 저장

### Out (이번 스펙에서 **안 한다**)

- production `backend/vlm/worker.py` 교체
- `behavior_logs`에 event-level 결과 INSERT
- Flutter/UI 변경
- tracker/crop 정규화 재도입
- 도마뱀 detector, SAM 2, keypoint 모델 도입
- prompt v3.5 자체 수정
- fine-tune 또는 전용 video classifier 학습

> **스코프 변경은 합의 후에만.** 이 실험은 production 전략을 대체하는 작업이 아니라, 다음 세대 분석 전략의 채택 가능성을 보는 비교 실험이다.

## 3. 완료 조건

- [x] `experiments/segment-vlm/README.md` 작성 — 실험 목적, 실행 순서, 산출물 포맷 정리
- [ ] `experiments/event-vlm/roi-config.example.json` 작성 — normalized ROI config 예시
- [x] `scripts/segmentvlm_sample_poc.py` 작성 — mismatch row → event boundary JSON + event mp4/contact sheet 조각 생성
- [ ] `scripts/event_roi_meta_poc.py` 작성 — ROI config + event JSON → event metadata JSONL 생성
- [ ] `scripts/event_vlm_eval_poc.py` 작성 — event mp4/frame bundle + metadata → analyzer backend별 결과 JSONL 저장
- [ ] `scripts/compare_event_vs_baseline.py` 작성 — baseline vs event 방식 비교 리포트 생성
- [ ] analyzer backend 인터페이스 초안 작성 — Gemini direct-video, OpenAI/Claude/local frame-based 입력 차이를 흡수
- [x] CodexFrameAnalyzer 수동 샘플 5~10건 생성 — mismatch case 7건에서 GT 회복 여부 기록
- [ ] 30~50개 클립으로 1차 실험 실행
- [ ] 비교 리포트에 아래 지표 포함
  - clip-level accuracy
  - P0 recall (`feeding`, `defecating`, `shedding`, `eating_prey`)
  - false highlight rate
  - HITL review rate
  - cost per clip
  - latency per clip
  - event count / 평균 event 길이 / empty event 비율
- [ ] 채택/폐기 판단 기록

## 4. 설계 메모

### 4.0 다른 에이전트용 Quickstart

사용자가 “SegmentVLM 샘플 하나 더 해줘”라고 하면 아래 순서로 진행한다. production DB/worker는 건드리지 않는다.

1. mismatch 후보를 고른다.
   - 1순위: [`web/eval/v35/error-set-154.jsonl`](../web/eval/v35/error-set-154.jsonl)
   - 이 파일은 `clip_id`, `gt`, `raw`, `file_path`, `notes` 를 갖는다.
   - `file_path` 가 없으면 `notes` 의 `auto-imported from inbox/...` 원본 영상을 찾는다.
2. 원본 mp4를 `experiments/segment-vlm/sample-{clip8}/` 아래에 처리한다.
3. motion 기반 event boundary를 생성한다.
4. event별 `event_XX.mp4`, `event_XX_contact.jpg`, key frames를 만든다.
5. Codex/Claude/OpenAI 같은 frame analyzer는 **mp4 직접 분석이 아니라 contact sheet + key frames + metadata** 를 본다.
6. 결과는 `codex-frame-analysis.json` 같은 normalized JSON 으로 저장한다.
7. 최종 답변에는 “GT / 기존 raw / SegmentVLM 판정 / 회복 여부 / 근거”만 간결히 보고한다.

현재 수동 샘플:

| clip_id | GT | 기존 raw | SegmentVLM/CodexFrame | outcome | 산출물 |
|---|---|---|---|---|---|
| `18585ae4` | `defecating` | `moving` | `defecating` | recovered | [`../experiments/segment-vlm/sample-18585ae4/`](../experiments/segment-vlm/sample-18585ae4/) |
| `31da5684` | `shedding` | `moving` | `shedding` | recovered_but_review | [`../experiments/segment-vlm/sample-31da5684/`](../experiments/segment-vlm/sample-31da5684/) |
| `94cd5cd3` | `defecating` | `moving` | `defecating` | recovered | [`../experiments/segment-vlm/sample-94cd5cd3/`](../experiments/segment-vlm/sample-94cd5cd3/) |
| `b0b57a47` | `defecating` | `moving` | `defecating` | recovered_but_review | [`../experiments/segment-vlm/sample-b0b57a47/`](../experiments/segment-vlm/sample-b0b57a47/) |
| `cc9463c9` | `eating_prey` | `moving` | `moving` | still_wrong_or_insufficient_visual_evidence | [`../experiments/segment-vlm/sample-cc9463c9/`](../experiments/segment-vlm/sample-cc9463c9/) |
| `d88e1390` | `defecating` | `drinking` | `defecating` | recovered | [`../experiments/segment-vlm/sample-d88e1390/`](../experiments/segment-vlm/sample-d88e1390/) |
| `d95e9eaa` | `drinking` | `eating_paste` | `drinking` | recovered | [`../experiments/segment-vlm/sample-d95e9eaa/`](../experiments/segment-vlm/sample-d95e9eaa/) |

초기 신호:
- 7건 중 `recovered` 4건, `recovered_but_review` 2건, `still_wrong_or_insufficient_visual_evidence` 1건.
- `defecating`, `drinking` 오답은 contact sheet 기반 SegmentVLM 에서 회복 신호가 좋다.
- `shedding` 은 회복 가능하지만 human review 유지가 맞다.
- `eating_prey` 는 frame sample 만으로 prey capture 증거가 약해서 아직 회복하지 못했다.

주의:
- `experiments/segment-vlm/sample-*` 산출물은 실험 artifact 다. production 코드와 DB에 반영하지 않는다.
- 샘플이 사용자의 기존 변경과 섞여 있을 수 있으니, 기존 artifact를 삭제/덮어쓰기 전에 경로를 확인한다.
- `python` 대신 `uv run python` 을 쓴다.

### 4.1 현재 baseline

현재 구조:

```text
60초 motion clip
→ R2 upload
→ VLM worker polling
→ Gemini 2.5 Flash + v3.5 prompt
→ behavior_logs(source='vlm') top-1 INSERT
```

장점:
- 구조가 단순하다.
- motion clip만 분석해서 비용을 줄인다.
- production DB-as-message-bus 구조와 잘 맞는다.

한계:
- 1개 클립에 행동 1개만 저장한다.
- 짧은 행동이 긴 이동/정지 구간에 묻힐 수 있다.
- “언제 무슨 일이 있었는가” 타임라인 설명이 약하다.
- confidence calibration이 안 되어 있어 자동 알림 기준으로 쓰기 어렵다.

### 4.2 제안하는 side pipeline

```text
1~4분 원본 영상
→ 1~2fps frame sampling
→ changed_ratio 시계열 생성
→ motion burst를 5~15초 event로 병합
→ event 앞뒤 3~5초 padding
→ event별 ROI/motion metadata 생성
→ event mp4 + metadata VLM 분석
→ event 결과를 clip-level summary/timeline으로 병합
```

정식 명칭은 **SegmentVLM**. 구현/파일/스크립트에서는 `segment_vlm` 또는 `segment-vlm` 네이밍을 우선한다. 기존 파일명 `experiment-event-segment-vlm.md` 는 처음 작성 시점 이름이므로 유지해도 되고, 나중에 정리할 때 `experiment-segment-vlm.md` 로 rename 해도 된다.

출력 예시:

```json
{
  "clip_id": "example",
  "summary_action": "feeding",
  "highlight": true,
  "needs_human_review": true,
  "events": [
    {
      "start_sec": 19.0,
      "end_sec": 31.0,
      "action": "moving",
      "confidence": 0.82
    },
    {
      "start_sec": 32.0,
      "end_sec": 44.0,
      "action": "feeding",
      "confidence": 0.76,
      "nearest_roi": "food_dish",
      "ambiguity": "medium"
    }
  ]
}
```

### 4.3 Event segmentation v0

처음부터 detector/tracker를 쓰지 않는다. 기존 motion 기반 구조와 같은 철학으로 간다.

1. mp4를 1~2fps로 샘플링한다.
2. 각 샘플 frame에 대해 `MotionDetector`와 유사한 전처리로 `changed_ratio`를 계산한다.
3. rolling median 또는 짧은 min-duration rule로 튐을 제거한다.
4. threshold 이상 구간을 motion burst로 묶는다.
5. burst 앞뒤에 3~5초 padding을 붙인다.
6. 너무 긴 event는 15~20초 단위로 split한다.
7. 너무 짧은 event는 버리거나 앞뒤 event에 merge한다.

v0 파라미터 후보:

| 파라미터 | 초깃값 | 의미 |
|---|---:|---|
| `sample_fps` | 2.0 | 분석용 frame sampling rate |
| `changed_ratio_threshold` | 0.7~1.5 | motion 후보 임계 |
| `min_event_sec` | 4.0 | 이보다 짧으면 noise 후보 |
| `max_event_sec` | 20.0 | 이보다 길면 split |
| `pre_padding_sec` | 3.0 | 행동 시작 전 문맥 |
| `post_padding_sec` | 5.0 | 행동 직후 문맥 |
| `merge_gap_sec` | 4.0 | 가까운 burst 병합 |

### 4.4 ROI metadata

ROI는 자동 detection보다 **카메라별 수동 설정**으로 시작한다. 고정 케이지 환경에서는 이게 가장 싸고 안정적이다.

예시:

```json
{
  "camera_id": "cam2",
  "rois": {
    "food_dish": [0.62, 0.70, 0.18, 0.16],
    "water_dish": [0.18, 0.66, 0.15, 0.14],
    "hide": [0.02, 0.45, 0.24, 0.30],
    "basking": [0.52, 0.05, 0.26, 0.20]
  }
}
```

좌표는 `[x, y, w, h]` normalized 0~1. 해상도 변화에도 재사용하기 위해 pixel 좌표가 아니라 normalized 좌표를 쓴다.

event별로 계산할 메타:
- 전체 changed ratio 평균/최대
- ROI별 changed ratio 평균/최대
- motion centroid와 각 ROI center 거리
- nearest ROI
- food/water ROI 내부 변화량
- hide ROI 진입/이탈 힌트
- event 시작/중간/끝 thumbnail path

### 4.5 VLM 입력 포맷

기존 v3.5 prompt는 유지한다. 대신 user input에 event metadata를 추가한다.

입력:
- event mp4 1개 (대략 5~15초)
- event 시작/중간/끝 frame thumbnail 3장 또는 영상 자체
- metadata text

metadata 예시:

```text
Event metadata:
- original_clip_id: ...
- event_time: 00:32.0-00:44.0
- duration_sec: 12.0
- motion_score: 0.73
- peak_changed_ratio: 4.8
- nearest_roi: food_dish
- roi_motion: food_dish=high, water_dish=low, hide=low
- time_context: night_ir
```

응답 schema 후보:

```json
{
  "primary_action": "feeding",
  "raw_action": "eating_paste",
  "confidence": 0.78,
  "ambiguity": "medium",
  "needs_human_review": true,
  "evidence": [
    "head/body remains near food dish",
    "motion concentrated inside food_dish ROI"
  ],
  "possible_alternatives": ["drinking", "moving"]
}
```

### 4.6 Analyzer backend 비교 전략

SegmentVLM 의 핵심 전처리는 모델과 분리한다. event segmentation, ROI metadata, thumbnail/contact sheet 생성은 공통으로 두고, 마지막 분석기만 갈아끼운다.

```text
SegmentVLM 공통 전처리
→ event mp4
→ representative frames / contact sheet
→ ROI + motion metadata
→ analyzer backend
→ normalized event result JSON
```

비교 후보:

| Backend | 입력 방식 | 장점 | 한계 | 1차 역할 |
|---|---|---|---|---|
| `GeminiVideoAnalyzer` | event mp4 직접 + metadata | 현재 production 과 가장 가까움. video input native | 비용/쿼터 의존. 1fps sampling 한계 | 메인 baseline |
| `OpenAIFrameAnalyzer` | 대표 프레임/contact sheet + metadata | reasoning/분류 비교군. Codex/OpenAI 계열 교차검증 | mp4 direct-video 대신 frame 기반으로 봐야 함 | second opinion |
| `ClaudeFrameAnalyzer` | 대표 프레임/contact sheet + metadata | 긴 설명/검수 reasoning 비교에 유리 | 공식 입력은 image 중심. temporal motion은 약할 수 있음 | critic / reviewer |
| `LocalFrameAnalyzer` | 대표 프레임/contact sheet + metadata | 비용 0, privacy/오프라인 가능 | 품질/속도/VRAM 제약. 도메인 일반화 미확인 | cheap prefilter |

중요한 설계 원칙:
- analyzer backend 는 모두 같은 normalized schema 를 반환한다.
- production DB 에 바로 쓰지 않고, 실험 JSONL 로만 저장한다.
- Gemini 외 backend 는 처음부터 "메인 교체"가 아니라 **교차검증 / disagreement 감지 / HITL 라우팅** 용도로 본다.

응답 schema 초안:

```json
{
  "backend": "gemini_video",
  "event_id": "clip123:e002",
  "primary_action": "feeding",
  "raw_action": "eating_paste",
  "confidence": 0.78,
  "ambiguity": "medium",
  "needs_human_review": true,
  "evidence": [
    "motion concentrated near food_dish ROI",
    "animal remains at dish for most of the event"
  ],
  "possible_alternatives": ["drinking", "moving"],
  "tokens_input": 1234,
  "tokens_output": 80,
  "latency_ms": 4300,
  "cost_usd": 0.0012
}
```

교차검증 사용 예:

```text
Gemini = feeding
OpenAI/Claude/local 중 2개 이상 = feeding
→ 자동 확정 후보

Gemini = feeding
다른 backend = moving/unseen
→ HITL review 후보

Gemini = defecating/shedding/eating_prey
다른 backend disagree
→ P0 라벨이므로 HITL 우선순위 높임
```

### 4.7 Backend별 입력 생성 규칙

Gemini는 event mp4를 직접 넘기는 경로를 우선한다.

```text
event.mp4 + metadata text → GeminiVideoAnalyzer
```

OpenAI/Claude/local 계열은 frame bundle을 우선한다.

```text
event_start.jpg
event_mid.jpg
event_end.jpg
optional contact_sheet.jpg
+ metadata text
→ FrameAnalyzer
```

FrameAnalyzer용 contact sheet는 3~12장 프레임을 한 장 이미지로 묶는다. 이렇게 하면 native video input 이 없는 모델에게 시간 흐름을 어느 정도 전달할 수 있다.

초기 프레임 추출 규칙:
- event 길이 ≤ 8초: 시작/중간/끝 3장
- event 길이 8~20초: 균등 6장 + contact sheet
- event 길이 > 20초: split 우선. split 전 임시 분석 시 8~12장 contact sheet

metadata는 모든 backend에 동일하게 넣는다. 그래야 모델 차이를 비교할 때 입력 차이 때문에 해석이 흐려지지 않는다.

### 4.8 산출물 계약

샘플 하나의 디렉토리 구조:

```text
experiments/segment-vlm/sample-{clip8}/
  segmentvlm_sample.json          # 원본 영상, GT/raw, segmentation 메타, event 목록
  event_00.mp4                    # event clip
  event_00_contact.jpg            # frame analyzer 가 우선 보는 이미지
  frames/
    frame_00.0s.jpg
    frame_01.7s.jpg
    ...
  codex-frame-analysis.json       # CodexFrameAnalyzer 수동/반자동 분석 결과
```

`segmentvlm_sample.json` 최소 필드:

```json
{
  "clip_id": "uuid",
  "source_video": "/abs/path/video.mp4",
  "gt_action": "drinking",
  "baseline_action": "eating_paste",
  "baseline_error": "GT drinking, Gemini v3.5 predicted eating_paste",
  "video": {
    "duration_sec": 8.64,
    "fps": 29.97,
    "width": 854,
    "height": 480
  },
  "segmentation": {
    "sample_fps": 2.0,
    "threshold": 1.2
  },
  "events": [
    {
      "event_id": "uuid:e00",
      "start_sec": 0.0,
      "end_sec": 8.64,
      "duration_sec": 8.64,
      "peak_changed_ratio": 10.726,
      "mean_changed_ratio": 4.046,
      "motion_centroid": [0.223, 0.618],
      "contact_sheet": "/abs/path/event_00_contact.jpg",
      "event_mp4": "/abs/path/event_00.mp4"
    }
  ]
}
```

`codex-frame-analysis.json` 최소 필드:

```json
{
  "backend": "codex_frame_visual_check",
  "clip_id": "uuid",
  "baseline": {
    "gt_action": "drinking",
    "gemini_v35_action": "eating_paste",
    "error_type": "drinking_misclassified_as_eating_paste"
  },
  "prediction": {
    "primary_action": "drinking",
    "raw_action": "drinking",
    "confidence": 0.78,
    "ambiguity": "medium",
    "needs_human_review": false,
    "possible_alternatives": ["moving"],
    "evidence": [
      "The gecko stays close to a transparent wall with visible water droplets.",
      "No paste dish or opaque food source is visible."
    ],
    "why_baseline_may_have_failed": [
      "A full-clip top-1 model may map any licking-like action to eating_paste when water context is weak."
    ]
  }
}
```

### 4.9 임시 수동 샘플 생성 레시피

정식 `scripts/event_segment_poc.py` 가 생기기 전에는 아래 임시 절차를 쓴다.

1. mismatch 목록 확인:

```bash
uv run python - <<'PY'
import json
from pathlib import Path
p = Path('web/eval/v35/error-set-154.jsonl')
for line in p.read_text().splitlines():
    r = json.loads(line)
    print(r['clip_id'][:8], r['gt'], '->', r['raw'], r['file_path'], '|', r.get('notes'))
PY
```

2. 원본 영상 찾기:
   - `file_path` 가 존재하면 그대로 사용.
   - 없으면 `notes` 의 `auto-imported from inbox/...` 경로를 사용.
   - 한글 파일명은 macOS NFD/NFC 차이가 있으므로 `unicodedata.normalize('NFC', p.name)` 로 비교한다.

3. event/contact sheet 생성:
   - OpenCV로 1~2fps sampling.
   - grayscale + blur + `absdiff` + threshold 로 `changed_ratio` 시계열 생성.
   - motion burst를 event로 묶고, 짧은 영상이면 전체를 event 하나로 둔다.
   - ffmpeg로 `event_00.mp4` 를 자른다.
   - 시작/중간/끝 또는 균등 6장 frame으로 `event_00_contact.jpg` 를 만든다.

4. frame analyzer 분석:
   - `event_00_contact.jpg` 를 열어 시각 증거를 확인한다.
   - 필요하면 `frames/frame_XXs.jpg` 중 핵심 프레임을 추가로 본다.
   - normalized JSON 으로 저장한다.

5. 보고:

```text
clip d95e9eaa
- GT: drinking
- baseline: eating_paste
- SegmentVLM/CodexFrame: drinking
- 회복 여부: recovered
- 근거: wall droplets + no visible food dish + mouth oriented to wet wall
```

### 4.10 Clip-level 병합

event 결과를 원본 클립 단위로 다시 합친다.

초기 병합 규칙:
- `defecating`, `shedding`, `eating_prey`, `feeding`이 하나라도 있으면 `highlight=true`
- P0 action이 여러 개면 summary 하나로 뭉개지 않고 timeline에 모두 보존
- `moving`만 있으면 일반 motion
- `unseen` 또는 low-confidence event만 있으면 review 후보
- `ambiguity=high` 또는 confusion-prone action이면 `needs_human_review=true`

P0 우선순위 후보:

```text
eating_prey > feeding > defecating > shedding > basking > moving > unseen
```

기존 v3.5 문서의 tie-break와 완전히 같을 필요는 없다. 이 실험은 사용자 가치 기준으로 **하이라이트/검수 우선순위**를 따로 평가한다.

### 4.11 비교 기준

기존 baseline 대비 아래 중 하나라도 만족하면 다음 단계로 갈 가치가 있다.

| 기준 | 채택 신호 |
|---|---|
| 전체 정확도 | +3%p 이상 |
| P0 recall | +10%p 이상 |
| false highlight | baseline 대비 크게 증가하지 않음 |
| HITL review | review 대상이 실제 애매한 케이스에 집중됨 |
| 설명 가능성 | 사용자에게 event timeline을 보여줄 수 있음 |
| 비용 | clip당 VLM 호출 증가가 감당 가능한 수준 |
| 교차검증 효율 | backend disagreement가 실제 오답/애매함을 잘 잡음 |

정확도만 보지 않는다. 이 전략의 핵심 가치는 **짧은 행동을 놓치지 않는 것**과 **검수 범위를 1~4분 → 10초 내외로 줄이는 것**이다.

### 4.12 리스크 / 미해결 질문

- event 수가 많아지면 Gemini 호출 비용과 latency가 증가한다.
- motion 기반 event segmentation은 정지형 행동 (`basking`, `hiding`, 일부 `shedding`)을 놓칠 수 있다.
- ROI config를 사용자가 어떻게 편하게 만들지 아직 없다.
- metadata를 많이 주면 VLM이 픽셀보다 텍스트 힌트에 과의존할 수 있다.
- event 단위 분석은 local context는 좋아지지만, 전체 전후 맥락이 약해질 수 있다.
- 1~4분 원본이 아니라 기존 60초 clip만으로 실험하면 장점이 과소평가될 수 있다.
- OpenAI/Claude/local backend 는 mp4 직접 분석이 아니라 frame 기반 분석이므로 Gemini direct-video 와 완전히 같은 조건은 아니다.
- 여러 backend 를 쓰면 비용/latency가 급증한다. 따라서 전체 클립이 아니라 sample set 또는 low-confidence event 에만 적용하는 방식이 현실적이다.

## 5. 학습 노트

- **Event segmentation**: 긴 영상을 “행동이 일어난 짧은 구간”으로 자르는 전처리. JS로 치면 긴 로그 파일에서 의미 있는 span만 뽑아 후속 parser에 넘기는 것과 비슷하다.
- **ROI metadata**: 모델이 픽셀에서 전부 추론하게 두지 않고, 고정 카메라 환경의 구조를 숫자/텍스트 힌트로 제공하는 방식.
- **Clip-level vs event-level**: clip-level은 원본 영상 1개에 대한 최종 요약, event-level은 그 안의 짧은 행동 조각이다. 사용자 경험은 clip-level summary를 보되, 검수는 event-level로 내려가는 구조가 좋다.
- **HITL 효율**: 사람이 4분 영상을 보는 대신 “AI가 애매하다고 표시한 10초”만 확인하면 검수 비용이 크게 줄어든다.
- **Analyzer backend**: SegmentVLM 전처리 결과를 받아 행동 라벨을 반환하는 모델 어댑터. Gemini는 video analyzer, OpenAI/Claude/local은 frame analyzer 로 시작한다.
- **Contact sheet**: 여러 시점의 frame을 한 장 이미지 격자로 묶은 것. native video input 이 없는 모델에게 시간 흐름을 압축해서 보여주는 타협안이다.

## 6. 참고

- 현재 VLM 요약 문서: [`../docs/VLM-CLASSIFIER.md`](../docs/VLM-CLASSIFIER.md)
- 기존 VLM production worker: [`feature-vlm-worker-cloud.md`](feature-vlm-worker-cloud.md)
- 폐기된 tracking/crop 실험: [`experiment-tracking-vlm-input.md`](experiment-tracking-vlm-input.md)
- HITL 후속 스펙: [`feature-vlm-hitl-ping.md`](feature-vlm-hitl-ping.md)
