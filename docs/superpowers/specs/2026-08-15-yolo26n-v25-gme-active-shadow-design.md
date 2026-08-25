# YOLO26n v2.5 GME Active Shadow + Stored-video Backfill Design

> 상태: Owner 설계 승인, 구현·운영 handoff 준비 중
> 결정일: 2026-08-15
> 선행 결과: v2.5 development fixed-test recall 75.6%, precision 73.1%; 독립 future holdout 미완료

## 1. 목표

동결된 YOLO26n v2.5 warm-start detector를 Gecko Motion Engine(GME)의 새 detector identity로
추가한다. 신규 production 영상과 기존 저장된 eligible production 영상을 v2.5로 분석해 candidate
움직임 시간·추적 품질·실패 사례를 축적한다.

이번 적용은 **active shadow**다. v2.5 결과는 GME candidate 계산에 실제로 사용하지만 Flutter/API의
기존 활동시간, 사람 GT, 행동 라벨, VLM route, 영상 보존정책은 바꾸지 않는다.

## 2. 선택안과 근거

- 완전 교체: 독립 future holdout 전이라 기각한다.
- 일부 영상 passive shadow: 실제 실패 사례 수집 속도가 느려 기각한다.
- **신규 전수 + eligible 저장 영상 active shadow:** 기존 append-only GME identity 계약을 재사용하고
  사용자 값과 원본을 유지하면서 실제 환경의 detector/tracker 성능을 가장 빨리 측정할 수 있어 채택한다.

## 3. 고정 detector 계약

- model family: `YOLO26n`
- model version: `v2.5-warm-start`
- checkpoint: handoff manifest가 고정한 실제 파일 SHA-256
- raw inference confidence: `0.001`
- bbox filter threshold: `0.20`
- image size: `960`
- NMS IoU: `0.70`
- maximum detections: `50`
- detector output: `timestamp_sec`, `bbox_xywh`, `confidence`, `class_name`, model/checkpoint/schema provenance

모델 호출은 `conf=0.001`로 수행하고 score `0.20` 이상만 GME observation으로 전달한다. 그래야
development 평가와 같은 operating point를 재현한다. 검출 실패는 `not_visible` 또는 `static`으로
바꾸지 않고 `unknown`으로 둔다.

## 4. 데이터 흐름

```text
production motion_clips
  -> v2.5 detector_identity의 gme_jobs
  -> Mac mini GME worker
  -> v2.5 observation + tracker + motion state
  -> append-only gme_runs
  -> GME 전용 permanent/debug R2 artifact
```

기존 detector identity의 job/run은 수정하지 않는다. 같은 clip도 새 detector identity면 별도 job과
run을 만들 수 있으며, 비교·rollback provenance가 유지된다.

## 5. 실행 범위

### 신규 live

- `clip_purpose=production`
- 재생 가능한 신규 `motion_clips`
- live priority를 backfill보다 높게 유지

### stored-video backfill

- production이고 원본 media가 실제 존재하며 decode 가능한 영상
- 기존 v2.5 detector identity run이 없는 영상
- `test`, research quarantine, `media_deleted`, `source_missing`, R2 preflight 실패는 제외
- live lag p95가 15분을 넘으면 backfill claim만 중단

원본 영상은 이동·삭제·재인코딩하지 않는다.

## 6. 저장 계약

- DB: 기존 `gme_jobs`, append-only `gme_runs`
- R2 permanent: 기존 GME permanent allowlist prefix
- R2 debug: 기존 14-day debug allowlist prefix
- detector provenance: model name/version, checkpoint SHA, threshold, inference settings, schema version
- engine provenance: GME code ref, algorithm version, runtime host, run identity

새 DB migration은 기존 schema로 identity/provenance를 완전히 표현할 수 없을 때만 제안한다. 우선은
기존 schema와 RPC를 재사용한다.

## 7. 금지 범위

- Flutter/API `activity-v1` 교체
- v2.5 결과의 사용자 노출
- 사람 bbox/행동 GT 자동 수정
- 영상 자동 skip·격리·삭제
- 게코 부재·행동명·하이라이트 확정
- 원본 R2 object 수정
- 과거 GME run 수정·삭제

## 8. Future Holdout 보존

v2.5 active shadow와 독립 future holdout은 병행한다. holdout 후보는 v2.5 결과와 무관한
결정론적 metadata sampling으로 뽑고, 사람 presence/bbox 검수 전에는 저장된 prediction을 공개하지
않는다. 사람 GT가 동결된 뒤 같은 threshold `0.20`에서 v2.4/v2.5를 비교한다.

active shadow 결과를 candidate 선택이나 사람 정답에 사용하지 않는다. 따라서 새 영상에 모델이 이미
실행됐더라도 prediction 비공개·선택 독립성이 유지되면 시험 오염이 아니다.

## 9. 배포·검증 순서

1. cross-repo handoff manifest에 execution repo, design/plan, 40자리 commit, implementation/runtime
   host, runtime kind, service label, checkpoint SHA를 고정한다.
2. `verify_agent_handoff.py`의 `HANDOFF_OK`를 확보한다.
3. detector adapter unit/integration test를 통과시킨다.
4. 실제 production 영상 10건 smoke를 수행한다.
5. `10/10 complete`, 재실행 멱등, temp 0, 허용 prefix 밖 write 0을 독립 검수한다.
6. 신규 live enqueue를 활성화한다.
7. stored-video backfill을 시작한다.
8. 24시간 coverage, live lag, terminal failure, unknown/tracking quality를 확인한다.

## 10. 실패와 rollback

- v2.5 job 실패는 capture, upload, app, 기존 분석을 막지 않는다.
- job 단위 retry/backoff와 terminal failure allowlist를 유지한다.
- 운영 이상 시 v2.5 detector identity의 신규 enqueue/worker만 중단한다.
- 기존 detector identity, GME run, 원본 영상은 그대로 보존한다.
- rollback 뒤에도 이미 생성된 v2.5 shadow run은 연구 provenance로 남긴다.

## 11. 성공 기준

- model/checkpoint/inference provenance 일치 100%
- 10-clip smoke 10/10 complete
- 신규 eligible coverage 100%
- terminal failure 1% 미만
- live lag p95 15분 이내
- temp residue 0
- 원본·GT·Flutter/API write 0
- 허용 GME DB/R2 범위 밖 write 0
- future holdout prediction leak 0

이 기준은 operational shadow 성공 기준이다. v2.5 production 승격 기준은 별도 future holdout 결과다.
