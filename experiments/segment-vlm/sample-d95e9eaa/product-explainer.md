# Track B SegmentVLM 샘플 — d95e9eaa

## 요약

이 샘플은 Track A가 60초/전체 클립 top-1 분류에서 `eating_paste`로 잘못 본 케이스를, Track B SegmentVLM이 프레임 샘플과 이벤트 맥락을 다시 보고 `drinking`으로 회복한 사례다.

- 원본: `/Users/baek/petcam-lab/inbox/0430/물 마시기.mp4`
- 길이: 8.64초
- GT: `drinking`
- Track A 기존 판정: `eating_paste`
- Track B 판정: `drinking`
- 결과: `recovered`

## Track B 처리 흐름

```text
원본 영상
→ 2fps 프레임 샘플링
→ changed_ratio 기반 motion event 탐지
→ 0.00s~8.64s event 1개 생성
→ key frame 5장 + contact sheet 생성
→ frame analyzer가 event 단위로 행동 판정
→ clip-level 결과로 병합
```

## 이벤트 메타데이터

- event: `e00`
- 구간: `0.00s ~ 8.64s`
- peak changed ratio: `10.726`
- mean changed ratio: `4.046`
- motion centroid: `[0.223, 0.618]`
- 분석 confidence: `0.78`
- human review: 불필요

## Contact Sheet

![event_00_contact](/Users/baek/petcam-lab/experiments/segment-vlm/sample-d95e9eaa/event_00_contact.jpg)

## Key Frames

![0.0s](/Users/baek/petcam-lab/experiments/segment-vlm/sample-d95e9eaa/frames/event_00_frame_000.0s.jpg)

![1.7s](/Users/baek/petcam-lab/experiments/segment-vlm/sample-d95e9eaa/frames/event_00_frame_001.7s.jpg)

![3.5s](/Users/baek/petcam-lab/experiments/segment-vlm/sample-d95e9eaa/frames/event_00_frame_003.5s.jpg)

![5.2s](/Users/baek/petcam-lab/experiments/segment-vlm/sample-d95e9eaa/frames/event_00_frame_005.2s.jpg)

![6.9s](/Users/baek/petcam-lab/experiments/segment-vlm/sample-d95e9eaa/frames/event_00_frame_006.9s.jpg)

## 정밀 분석 결과

판정은 `drinking`이다.

근거:
- 게코가 투명 벽면 또는 젖은 표면 쪽에 몸을 붙이고 있다.
- 머리와 입 방향이 먹이그릇이 아니라 벽면/물방울 쪽이다.
- 샘플 프레임에 paste dish 또는 불투명한 먹이원이 보이지 않는다.
- 움직임은 이동보다 벽면 접촉 자세 주변에 국소적으로 나타난다.

Track A가 틀렸을 가능성:
- 전체 클립을 한 번에 top-1로 보면 licking-like action을 `eating_paste`로 끌고 가기 쉽다.
- 벽면 물방울은 작고 대비가 약해서, 물 마시기와 paste feeding을 구분하려면 프레임/ROI 맥락이 더 중요하다.

## 제품 설명용 문장

Track A는 모든 움직임 클립을 빠르게 훑는 1차 자동 라벨링이고, Track B SegmentVLM은 중요한 장면을 이벤트 단위로 쪼개 다시 본다. 이 샘플처럼 전체 클립 기준으로는 `eating_paste`처럼 보인 장면도, Track B가 샘플 프레임과 위치 맥락을 함께 보면 벽면 물방울을 핥는 `drinking` 행동으로 회복할 수 있다.
