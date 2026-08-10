# YOLO v2.1 보호 Preview Worker 설계

**상태:** Owner 승인 · 구현/보호 Preview 배포 진행

## 1. 목적

내일 시연을 위해 Vercel Preview의 `/gecko-detector`가 Mac mini의 실제 YOLO v2.1 checkpoint를
호출해 사진과 짧은 영상의 게코 bbox를 표시하게 한다. 이 연결은 **보호된 Preview shadow**에만
존재하며 production active model 전환, production worker 연결, GT/Dataset 승격을 하지 않는다.

checkpoint 정본:

- runtime host: `baeg-endeuui-Macmini.local`
- path: `/Users/baek-end/private-rba/yolo26n-owner-dataset-v21/attempt-20260810-owner-final-v1/runs/baseline-960-v21/weights/best.pt`
- size: `5,408,389 bytes`
- SHA-256: `9ba825697693a0e84078a32120f64ea4e9da6a20bb50b9636403c9409200036e`
- training runtime provenance: Ultralytics `8.4.104`, AGPL-3.0, `imgsz=960`, deterministic seed 26

## 2. 채택 근거와 승격 금지

같은 신규 held-out development 34장(23 boxes)에서 old-v20 대비 new-v21은 recall과 mAP가 개선됐다.

| model | precision | recall | mAP50 | mAP50-95 |
|---|---:|---:|---:|---:|
| old-v20 | 0.711 | 0.478 | 0.491 | 0.270 |
| new-v21 | 0.674 | 0.565 | 0.640 | 0.317 |

이 34장은 이미 모델 선택에 사용된 **development holdout**이다. 따라서 위 결과는 Preview 연결을
시작할 근거일 뿐 production 일반화·active 승격 근거가 아니다. 별도 future holdout 통과와 그 이후
Owner 수동 승인 전에는 production provider, active model event, Dataset membership을 바꾸지 않는다.

## 3. 접근법 비교와 결정

1. **기존 Cloudflare Named Tunnel + 별도 hostname + application bearer — 채택.** Mac mini는
   localhost에만 bind하고 기존 tunnel `1e7a9232-2934-44de-a39b-aee1c6b54af7`에
   `yolo-preview.tera-ai.uk → http://127.0.0.1:8093` ingress만 추가한다. 고정 URL이라 시연 중
   재시작에 견디고 기존 `cvat.tera-ai.uk` ingress를 보존한다.
2. Cloudflare Quick Tunnel — 기각. 시작은 빠르지만 재시작 때 URL이 바뀌어 시연 안정성이 낮다.
3. R2 queue/outbound polling — 기각. Mac mini inbound를 없앨 수 있지만 R2 write와 비동기 job UI가
   필요해 이번 승인 범위를 넘는다.

## 4. 사용자 체험 흐름 — 프레임 단위

### 4.1 Preview 진입

`[화면]` Vercel Deployment Protection을 통과한 사용자가 `/gecko-detector`에서
`YOLO v2.1 보호 Preview · production active 아님` 배너와 drop zone을 본다.

→ `[감정]` 실제 checkpoint 시연이지만 운영 판정 모델은 아니라는 경계를 먼저 이해한다.

### 4.2 업로드와 처리

`[조작]` 사용자가 JPEG/PNG/WebP 또는 MP4/WebM 한 개를 drop하거나 file input으로 선택하고
`게코 찾기`를 누른다.

→ `[반응]` 화면은 `v2.1 worker에 안전하게 전달하고 있어` 상태를 표시한다. Vercel은 byte를 DB/R2에
쓰지 않고 인증된 worker 요청 한 번으로 전달한다.

→ `[감정]` 중복 제출 여부와 처리 위치를 예측할 수 있다.

### 4.3 사진 결과

`[화면]` 원본 사진 위에 bbox/confidence, `yolo26n-owner-v2.1+9ba825697693`, 처리시각,
`Preview shadow · 연구용 결과이며 오류 가능` 경고가 보인다.

→ `[조작]` bbox 표시를 켜고 끄며 원본과 비교한다.

→ `[감정]` 실제 v2.1 결과를 보되 GT·행동 판정으로 오해하지 않는다.

### 4.4 영상 결과

`[화면]` 영상은 실제 source timestamp를 가진 sampled frame bbox를 최대 5 fps로 표시한다.

→ `[조작]` 재생하거나 scrub한다.

→ `[반응]` 가장 가까운 과거 sampled frame만 허용 간격 안에서 표시하고 중간 박스를 임의 보간하지
않는다. 최대 60초·300 sampled frames를 넘지 않는다.

→ `[감정]` 박스가 실제 추론 frame에서만 나온다는 신뢰를 얻는다.

### 4.5 실패와 rollback

`[화면]` 인증 실패·worker timeout·decode 실패는 checkpoint 경로, tunnel 정보, 원문 exception 없이
`Preview inference unavailable`로 표시된다. 기존 선택 파일은 화면에 남아 다시 시도할 수 있다.

→ `[반응]` worker/Preview env를 끄면 Preview도 즉시 기존 503 fail-closed로 돌아가고 production은
처음부터 끝까지 503을 유지한다.

## 5. 시스템 구조

```text
Protected Vercel Preview /gecko-detector
  → same-origin /api/yolo-demo/infer
  → HttpGeckoDetectionProvider (preview target only)
  → HTTPS yolo-preview.tera-ai.uk/v1/infer + 256-bit bearer
  → existing Cloudflare Named Tunnel
  → 127.0.0.1:8093 FastAPI worker on Mac mini
  → pinned YOLO v2.1 checkpoint on MPS
```

production은 `VERCEL_ENV=production`이면 환경변수 존재 여부와 무관하게 `FakeGeckoDetectionProvider`
와 production guard를 유지해 503을 반환한다. Preview worker 선택 조건은 다음 셋이 모두 참일 때뿐이다.

- `VERCEL_ENV=preview`
- `YOLO_PREVIEW_ENABLED=true`
- `YOLO_WORKER_URL`과 `YOLO_WORKER_TOKEN`이 모두 존재

## 6. Worker 계약

### 6.1 프로세스와 identity

- module: `backend.yolo_preview_worker`
- bind: `127.0.0.1:8093`
- LaunchAgent: `com.petcam.yolo-preview-worker`
- package pin: optional dependency group `ultralytics==8.4.104`
- startup에서 hostname, checkpoint regular file/size/SHA, expected model class `gecko`를 검증한다.
- checkpoint SHA가 다르면 model load 전 종료한다.
- model은 프로세스당 한 번 load하고 MPS를 우선하되 MPS 부재 시 시작을 거부한다.

### 6.2 HTTP

- `GET /v1/health`: bearer 필수. `status`, public model version, device, checkpoint SHA만 반환하고 path는
  반환하지 않는다.
- `POST /v1/infer`: bearer 필수. raw byte body와 allowlisted request metadata만 받는다.
- bearer는 `secrets.compare_digest`로 검사하고 모든 오류 응답은 allowlist된 코드로만 낸다.
- worker 자체 global limiter는 1분 30회, 동시 inference는 1개다. 초과는 429/503으로 닫는다.

### 6.3 입력 방어

- Vercel 제한을 worker에서 독립적으로 재검사한다: image 10 MiB, video 50 MiB, image 20 MP,
  video 60초/30 fps/1920×1080.
- body는 0700 random temp directory로 bounded streaming하고 client filename을 사용하지 않는다.
- image는 Pillow verify/decode, video는 ffprobe/OpenCV metadata와 실제 순차 decode를 함께 검사한다.
- animated image, signature/type mismatch, decode 불가, frame cap 위반은 422다.
- 성공·실패·timeout 모두 `finally` cleanup하며 startup에서 15분 지난 동일-prefix temp를 정리한다.

### 6.4 inference와 출력

- fixed params: `imgsz=960`, `conf=0.25`, `iou=0.7`, `max_det=20`, `device=mps`, `verbose=false`.
- image는 frame 0 한 번, video는 source fps에서 균등 stride를 계산해 최대 5 fps·300 frames를 추론한다.
- bbox는 decoded width/height로 normalized `[0,1]` 좌표를 만들고 class `gecko`만 반환한다.
- 기존 `GeckoDetectionResult`와 정확히 같은 schema, request identity, consent status를 반환한다.
- 모델 출력은 GT, skip, 삭제, 행동명, 사건 묶기 근거가 아니다.

## 7. Web adapter와 fail-closed

- `HttpGeckoDetectionProvider`는 65초 AbortSignal timeout, bearer, request id, media kind/content type,
  consent만 전달한다.
- worker의 non-2xx·invalid JSON·schema/identity mismatch는 기존 route에서 일반 502로 숨긴다.
- Preview는 local Vercel limiter와 Mac mini global limiter를 함께 쓴다.
- production test는 worker env가 모두 있어도 provider 호출 0·503임을 증명한다.
- UI는 preview 여부를 서버가 결정하고 production HTML에 preview 문구를 넣지 않는다.

## 8. 배포와 rollback

1. 설계·계획·manifest commit과 `HANDOFF_OK` 뒤에만 구현한다.
2. TDD와 전체 회귀·독립 리뷰를 통과한 branch를 push한다.
3. Mac mini 별도 worktree를 exact branch SHA에 고정하고 optional dependency를 sync한다.
4. secret은 Git/plist/로그가 아닌 mode 0600 env file에 생성한다.
5. LaunchAgent health와 actual image/video one-shot을 localhost에서 먼저 검증한다.
6. 기존 cloudflared config backup 후 ingress 한 줄을 추가하고 `tunnel ingress validate`를 통과한다.
7. DNS route와 tunnel을 연결한 뒤 authenticated remote health만 200인지 확인한다.
8. Vercel branch-specific Preview env를 설정하고 Preview deployment를 만든다.
9. 실제 브라우저에서 사진·짧은 영상 bbox, 버전, 경고, console error 0을 확인한다.
10. production alias의 inference 503과 기존 배포 SHA를 재확인한다.

rollback은 Vercel Preview env disable → LaunchAgent bootout → tunnel ingress 제거 순서다. 기존 CVAT ingress,
production Vercel deployment, Supabase, R2는 바꾸지 않는다.

## 9. 검증

- Python unit: auth, identity, checkpoint hash, input caps, temp cleanup, image/video sampling, bbox normalize,
  model failure redaction, limiter/concurrency.
- Web unit/API: preview-only provider selection, HTTP timeout/auth, worker schema validation, production 503 even
  with worker env, preview UI copy.
- Mac mini runtime: exact hostname/HEAD/checkpoint SHA, MPS, health, temp residue 0, actual image/video response.
- Tunnel: config validation, existing CVAT ingress 보존, unauthenticated 401, authenticated health 200.
- Vercel Preview: build READY, protected page 200, actual upload bbox overlay, model version/confidence/time/warning,
  console error 0.
- Production negative canary: `label.tera-ai.uk` page 200, inference 503, worker request count 증가 0.
- Full: `uv run pytest -q`, `cd web && npm test`, `npx tsc --noEmit`, Vercel Preview build,
  `git diff --check`.

## 10. 범위

### In

- 실제 v2.1 model loader와 Mac mini localhost worker
- 기존 Cloudflare Named Tunnel의 별도 preview hostname
- Vercel branch-specific protected Preview adapter와 UI
- LaunchAgent, secret file, runtime/canary evidence

### Out

- production Vercel provider/active model 전환
- production public worker hostname 사용
- future holdout 생성·개방·평가
- Owner active model 승인 event
- DB migration/write, R2 write, Dataset/GT/skip/삭제/행동명/사건 묶기
- checkpoint 재학습·threshold tuning

## 11. 완료 조건

- 보호된 Preview에서 실제 사진과 짧은 영상이 v2.1 bbox overlay를 반환한다.
- model version, confidence, 처리시각, Preview shadow/연구용 경고가 보인다.
- Mac mini worker는 exact checkpoint SHA/MPS/localhost/secret/temp cleanup 계약을 증명한다.
- production은 worker env와 무관하게 503이고 worker 호출이 없다.
- development holdout 34장의 수치는 provenance로만 남고 active 승격은 차단된다.
- 최종 상태는 최대 `PREVIEW_READY_SHADOW_ONLY`; future holdout+Owner 승인 전 `DEPLOYED_VERIFIED`나
  active model 전환을 주장하지 않는다.
