# YOLO Dataset v2.3 라벨링 보조 Worker 설계

**상태:** Owner 승인 · 구현 전

## 1. 목적

Mac mini에서 개발 완료된 Dataset v2.3 `warm-start` checkpoint를 라벨링 웹의 보호 Preview에서
후보 bbox를 보여주는 보조 모델로 배포한다. 학습 원본은 읽기 전용으로 유지하고 별도 immutable release
copy와 manifest를 만든다. 기존 v2.1 worker는 그대로 보존해 Preview 설정 한 번으로 즉시 rollback한다.

이 작업의 최대 상태는 `PREVIEW_READY_LABELING_ASSIST_ONLY`다. v2.3은 development-only이며 production
자동분류 모델, GT 생성기, 게코 부재 판정기로 채택하지 않는다.

## 2. 확정 provenance와 안전 경계

- 원본 루트:
  `/Users/baek-end/private-rba/yolo26n-owner-dataset-v23/attempt-20260812-owner-v1`
- 선택 후보: `warm-start`
- 원본 checkpoint: `runs/warm-start/weights/best.pt`
- checkpoint size: `5,400,581 bytes`
- checkpoint SHA-256:
  `dbed3a2d8018a2eb6e4130de57d301414fcd6c9ba80aef8aafdaba55b19a6a34`
- inference threshold: `0.25`
- fixed test: TP 53 / FP 19 / FN 37, precision `0.7361111111111112`, recall
  `0.5888888888888889`
- evaluation tier: `development`, future holdout required

허용 용도는 사용자가 업로드한 사진·영상에 후보 bbox를 보여주는 라벨링 보조 기능뿐이다. GT 자동확정,
빈 이미지/게코 부재 판정, GME routing, R2 A/B 분류, 삭제, VLM skip, 행동명, 사건 묶기에는 연결하지 않는다.
미검출은 `게코 없음`이 아니라 `이 모델이 threshold 0.25에서 후보를 내지 못함`으로만 해석한다.

## 3. 배포 방식 비교와 선택

### A. 기존 v2.1 checkpoint in-place overwrite

변경량은 작지만 실행 중인 모델 identity와 파일 provenance가 깨지고 rollback copy에 의존한다. 원본 보존과
즉시 rollback 요구를 충족하지 못해 제외한다.

### B. 같은 LaunchAgent에서 versioned path만 교체

artifact는 보존할 수 있지만 단일 서비스 재시작이 필요하고 v2.3 startup 실패 시 Preview도 함께 중단된다.
rollback도 다시 restart해야 하므로 canary 격리가 약하다.

### C. v2.3 blue/green 병렬 worker — 채택

v2.1 service·port·worktree·env·hostname을 그대로 둔다. v2.3은 별도 immutable release, exact-SHA
worktree, LaunchAgent, localhost port, tunnel hostname을 사용한다. localhost와 remote health, 실제 media
canary를 먼저 통과한 뒤 보호 Vercel Preview의 branch-scoped worker URL/token만 v2.3으로 바꾼다.
rollback은 Preview env를 v2.1 hostname으로 되돌리는 한 단계다.

## 4. 사용자 체험

### 4.1 업로드 전

`[화면]` 보호 Preview의 게코 찾기 화면에 `Dataset v2.3 라벨링 보조 · development-only`와
`박스가 없어도 게코가 없다는 뜻은 아니야` 경고가 보인다.

→ `[조작]` 사용자가 JPEG/PNG/WebP 또는 MP4/WebM 파일 하나를 선택하거나 drop한다.

→ `[반응]` 기존 형식·크기·decode 제한을 통과한 입력만 v2.3 worker로 전달된다. 파일은 DB/R2에 쓰지
않고 worker temp directory에서 처리 후 삭제된다.

→ `[감정]` 사용자는 결과가 자동 판정이나 학습 정답이 아니라 후보임을 먼저 이해한다.

### 4.2 후보 bbox 확인

`[화면]` 사진 또는 영상 frame 위에 후보 bbox와 confidence가 나타나고
`yolo26n-owner-dataset-v2.3-warm-start+dbed3a2d8018`, threshold `0.25`, 처리시각이 보인다.

→ `[조작]` 사용자는 overlay를 켜고 끄거나 기존 bbox 편집 흐름에서 후보를 수정·삭제·추가한다.

→ `[반응]` worker 응답은 prediction snapshot일 뿐 사람 revision을 만들거나 저장하지 않는다. 사람 제출은
기존 labeling contribution API가 별도 provenance로 처리하며, 이 작업은 DB schema/data를 변경하지 않는다.

→ `[감정]` 사용자는 AI 박스와 자신의 최종 판단이 섞이지 않았음을 확인한다.

### 4.3 미검출과 실패

`[화면]` detection이 0개면 `후보 박스를 찾지 못했어. 게코 없음 판정이 아니니 직접 확인해줘.`를
표시한다. worker timeout·decode 실패는 내부 경로·secret·exception 없이 안전한 오류만 표시한다.

→ `[조작]` 사용자는 직접 박스를 추가하거나 원본을 다시 확인한다.

→ `[감정]` recall 58.9% 모델의 미검출을 부재 정답으로 오해하지 않는다.

## 5. 시스템 구조

```text
학습 원본 best.pt (read-only)
  -> SHA-256/size 검증
  -> immutable release directory (best.pt + manifest.json, read-only)
  -> exact-SHA v2.3 runtime worktree
  -> com.petcam.yolo-preview-worker-v23
  -> 127.0.0.1:8094
  -> yolo-v23-preview.tera-ai.uk
  -> protected Vercel Preview /api/yolo-demo/infer
  -> candidate bbox overlay / existing human revision boundary

기존 v2.1:
  com.petcam.yolo-preview-worker -> 127.0.0.1:8093
  -> yolo-preview.tera-ai.uk (변경·중단 없음)
```

production `label.tera-ai.uk`는 worker 관련 환경변수가 있어도 실제 provider를 고르지 않고 503
fail-closed를 유지한다.

## 6. Immutable release 계약

release root는 `/Users/baek-end/Library/Application Support/petcam/models/` 아래 version과 전체 digest로
구분한 새 directory를 사용한다. 학습 directory에서 checkpoint를 읽어 새 temporary file에 복사하고,
복사본의 size/SHA를 다시 검증한 뒤 atomic rename한다. 최종 `best.pt`와 `manifest.json`은 read-only로
고정하며 기존 release를 수정하거나 삭제하지 않는다.

manifest에는 다음을 기록한다.

- public model version과 전체 checkpoint SHA-256/size
- source provenance와 candidate `warm-start`
- threshold `0.25`, inference image size, IoU, max detections
- fixed-test TP/FP/FN/precision/recall
- `evaluation_tier=development`, `future_holdout_required=true`
- `allowed_use=labeling_bbox_assist_only`
- 금지된 GT/absence/GME/R2/delete/VLM 용도

manifest나 checkpoint identity가 다르면 모델 load 전에 종료한다. health는 public version, full SHA,
threshold, `development_only`, allowed use만 반환하고 local path는 반환하지 않는다.

## 7. Worker와 Web 계약

- v2.3 worker는 기존 인증, request limiter, concurrency 1, input cap, temp TTL/cleanup, MPS fail-closed,
  error redaction을 그대로 유지한다.
- inference는 `conf=0.25`를 manifest에서 읽고, 코드 default와 불일치하면 startup을 거부한다.
- 응답 schema에 `model_version`과 기존 frame/detection을 유지한다. health에 `threshold`와
  `usage_scope=labeling_bbox_assist_only`를 추가한다.
- UI는 model version, threshold, development-only 경고와 0 detection 경고를 표시한다.
- prediction response 자체가 사람 GT/revision API를 호출하지 않으며 upload byte도 저장하지 않는다.
- Supabase/R2 schema와 data mutation은 없다.

## 8. 배포 순서

1. design/spec, plan, handoff manifest를 tracked clean commit으로 고정하고 `HANDOFF_OK`를 확보한다.
2. TDD로 release manifest, v2.3 identity/health, threshold/UI warning, 별도 runtime manager를 구현한다.
3. 전체 테스트와 독립 리뷰를 통과한 exact branch SHA를 push한다.
4. Mac mini에서 학습 원본을 읽기 전용으로 검증하고 immutable release copy를 만든다.
5. 새 exact-SHA worktree와 v2.3 env 0600, LaunchAgent, localhost 8094를 설치한다.
6. localhost health와 실제 이미지/영상 canary, temp residue 0, 로그 secret/path 0을 확인한다.
7. 기존 Named Tunnel에 새 hostname ingress만 추가하고 기존 v2.1/CVAT ingress를 보존한다.
8. 새 remote authenticated health와 unauthenticated 401을 확인한다.
9. 보호 Vercel Preview branch env를 v2.3 hostname/token으로 설정해 새 deployment를 만든다.
10. 브라우저에서 이미지/영상 bbox, model version, threshold, 0-detection 문구, console error 0을 확인한다.
11. production page 200, inference 503, production 요청이 v2.3 worker count를 늘리지 않음을 확인한다.
12. Preview를 v2.1 URL로 되돌려 rollback canary 후 다시 v2.3으로 전환한다.
13. 최종 evidence를 문서화하고 Slack에 범위·SHA·canary·rollback·금지 경계를 공유한다.

## 9. Rollback

정상 rollback은 보호 Preview의 worker URL/token을 기존 v2.1 값으로 되돌리고 deployment를 재생성하는
것이다. v2.1 health와 실제 inference를 확인한 뒤 v2.3 service는 증거 보존을 위해 loaded 상태로 둘 수
있다. 보안·리소스 문제가 있으면 v2.3 LaunchAgent만 bootout하고 새 tunnel ingress만 제거한다. v2.1
service, release, tunnel, Vercel production, DB/R2는 변경하지 않는다.

## 10. 테스트와 완료 조건

- Python: manifest validation, immutable copy, SHA/size/threshold mismatch fail-closed, health scope,
  input/auth/rate/concurrency/temp cleanup 회귀.
- Web: preview-only provider, production hard 503, version/threshold/development warning, 0 detection copy,
  candidate/GT 분리 회귀.
- Runtime: exact hostname/repo HEAD/clean status, MPS, release SHA, service loaded, localhost/remote health,
  actual image/video inference, temp residue 0.
- Deployment: protected Preview READY, browser bbox/time/version/threshold/warnings, console error 0.
- Negative canary: production inference 503, DB/R2 write 0, GT/skip/delete/GME/VLM 경로 호출 0.
- Rollback: v2.1 Preview 재전환과 inference 성공 뒤 v2.3 재전환 성공.

완료 보고는 위 증거가 모두 있을 때만 `PREVIEW_READY_LABELING_ASSIST_ONLY`로 한다. production 자동분류
채택이나 게코 부재 판정이 완료됐다고 표현하지 않는다.

