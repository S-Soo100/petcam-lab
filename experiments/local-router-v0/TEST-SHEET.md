# Local Router v0 Test Sheet

> 규칙: [`.claude/rules/research-testing.md`](../../.claude/rules/research-testing.md). 실행 전 고정.

## 1. 가설

H0: OpenCV/metadata evidence JSON만으로는 cloud VLM 호출 우선순위를 의미 있게 줄일 수 없다. deterministic rule 또는 local text LLM router가 P0를 낮은 우선순위로 밀거나, `cloud_now` 비율이 너무 높아 운영 절감 효과가 없다.

H1: 이미지/영상 없이 evidence JSON만 사용해도 P0를 안전하게 보존하면서 cloud VLM 즉시 호출 대상을 줄일 수 있다.

## 2. Sample List

- 데이터셋: `storage/dataset-203/manifest.csv`
- 대상: 영상 파일 확장자 `.mp4`, `.mov`
- 예상 N: 197
- 샘플링: `--sample-size 0`이면 full dataset, 정렬은 `(gt, clip_id)`
- seed: `20260709`

GT label은 scoring에만 사용한다. router 입력에는 넣지 않는다.

## 3. 모델 / 입력표현 / 프롬프트

### L0 deterministic router

- 모델 없음
- 입력: `VideoEvidence` JSON
- 금지 입력:
  - GT label
  - 파일명 label
  - 이미지/frame/video
  - detector bbox

### L1 local text LLM smoke

- 실행 조건: local model이 이미 설치되어 있고, 30개 smoke sample을 3초/clip 근처로 처리 가능할 때만 실행
- 후보 기본값: Ollama 모델 중 사용 가능 모델 1개
- 입력: L0와 같은 evidence JSON
- temperature: 0
- output: JSON only

이번 1차 성적서에서 local model이 준비되지 않았으면 L1은 `blocked`로 기록하고, L0 결과만 decision한다.

## 4. 측정 지표

- route 분포: `cloud_now / cloud_later / activity_only / review_candidate`
- `cloud_now` 비율
- P0가 `activity_only`로 밀린 비율
- P0가 `cloud_later` 이하로 밀린 비율
- average router latency
- route별 GT class 분포
- cloud fallback 포함 운영 정확도 proxy

P0 정의:

- `drinking`
- `eating_paste`
- `eating_prey`
- `hand_feeding`
- `shedding`

## 5. 합격 기준

### Adopt

- `cloud_now` 비율이 40% 이하
- P0 → `activity_only` 비율이 2% 이하
- 평균 router latency가 3초/clip 이하
- local router가 deterministic L0보다 명확히 낫거나, L0 자체가 운영 후보로 충분함

### Hold

- P0 → `activity_only` 비율은 2% 이하이나 `cloud_now`가 40%를 초과
- local LLM smoke가 모델 준비 문제로 미실행
- metadata 부족 때문에 보수적으로만 라우팅됨

### Reject

- P0 → `activity_only` 비율이 5% 이상
- deterministic rule보다 local LLM이 나쁘거나 불안정
- 평균 router latency가 3초/clip을 초과
- route JSON이 파싱 불가하거나 재현성이 낮음

## 6. 예상 비용/토큰

- L0: cloud/API 토큰 0
- L1 local LLM: cloud/API 토큰 0, 로컬 CPU/GPU 시간만 사용
- cloud VLM fallback 비용은 실제 호출하지 않고 route 분포로만 추정한다.

## 7. Decision Rule

- L0가 기준을 만족하면 `hold` 이상으로 기록한다.
- L1은 L0보다 P0 안전성을 유지하면서 `cloud_now`를 줄일 때만 다음 phase 후보가 된다.
- v0에서는 `skip`, `auto_moving`, `auto_p0` route를 절대 만들지 않는다.
