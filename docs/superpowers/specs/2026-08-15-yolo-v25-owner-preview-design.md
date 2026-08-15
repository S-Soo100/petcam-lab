# YOLO26n v2.5 Owner 전용 Preview 설계

**상태:** Owner 승인 · 구현 전
**승인일:** 2026-08-15 KST

## 1. 목표

동결된 YOLO26n Dataset v2.5 `warm-start` checkpoint를 라벨링 웹의 Owner 전용 Vercel Preview에만
연결한다. Owner가 사진 또는 짧은 영상을 넣으면 threshold `0.20`의 게코 bbox 제안을 원본 위에서
확인한다. prediction과 업로드 byte는 DB/R2/GT/학습 원장에 쓰지 않는다.

최대 완료 상태는 `PREVIEW_READY_V25_OWNER_ONLY`다. 현재 공개 production의 v2.3 라벨링 보조,
팀원용 모델, Gecko Vision Gate, GME, production 자동판정 모델은 바꾸지 않는다.

## 2. 확인된 기준 상태와 provenance

- production 라벨링 웹은 Vercel deployment `dpl_FtC5Up5MANYieALZyqysagvmgC3Y`가
  `label.tera-ai.uk` alias를 가진다.
- production 소스 계보는 `codex/yolo-v23-labeling-assist-worker`이고 공개 `/gecko-detector`는
  Dataset v2.3 worker를 사용한다.
- Mac mini의 v2.3 worker `com.petcam.yolo-preview-worker-v23`과 전용 tunnel은 실행 중이다.
- v2.5 연구 코드 commit은 `125d6433c887402dbc244f4adf713e9bb05b2835`다.
- 선택 후보는 `warm-start`, checkpoint size는 `5,400,517 bytes`, SHA-256은
  `2b128f105e898bc472ed66861583ab80007dae6e94b291db497d7a2f8081f84a`다.
- public model version은
  `yolo26n-owner-dataset-v2.5-warm-start+2b128f105e89`로 고정한다.
- threshold는 `0.20`이다.
- internal fixed-test는 TP 68 / FP 25 / FN 22 / duplicate 9, precision
  `0.7311827956989247`, recall `0.7555555555555555`다.
- 이 결과는 반복 노출된 과거 분포의 regression-only 수치다. `evaluation_tier=development`,
  `future_holdout_required=true`, `production_adoption=false`다.

## 3. 접근법 비교와 선택

### A. 현재 공개 v2.3 worker를 v2.5로 in-place 교체

현재 공개 사용자 경험과 rollback 기준을 동시에 바꾼다. future holdout 전 공개 기본 모델 승격 금지와
충돌하므로 제외한다.

### B. v2.5 artifact를 MacBook 또는 관리형 worker로 복사

Preview worker 실행은 단순해지지만 private artifact의 배포 범위가 넓어진다. 기존 Mac mini에 검증된
MPS runtime과 worker 운영 패턴이 있으므로 제외한다.

### C. Mac mini 병렬 worker + Owner 전용 same-origin Preview — 채택

기존 v2.3 release/service/tunnel을 보존한다. v2.5는 별도 immutable release, exact-SHA runtime
worktree, LaunchAgent, localhost port, Named Tunnel을 사용한다. Vercel feature-branch Preview의
Owner 전용 API만 v2.5 hostname/token을 받는다. production alias와 공개 API는 건드리지 않는다.

## 4. 사용자 체험 흐름

### 4.1 진입

`[화면]` Owner가 보호된 Vercel Preview의 `/labeling/owner/yolo/preview`에 들어오면
`Development-only Owner Preview`, model version, threshold `0.20`, regression-only/future-holdout 경고가
업로드 전부터 보인다.

→ `[조작]` Owner가 JPEG/PNG/WebP 또는 MP4/WebM 하나를 선택하거나 drop한다.

→ `[반응]` 브라우저는 같은 origin의 Owner API만 호출한다. 서버가 bearer 인증과 Owner UUID를 먼저
검사하고 Preview flag·worker origin·secret·model identity가 모두 맞을 때만 byte를 전달한다.

→ `[감정]` Owner는 이 화면이 팀원/공개 기본 모델이 아니라 격리된 개발 검토임을 이해한다.

### 4.2 bbox 제안 확인

`[화면]` 원본 사진 또는 영상 위에 bbox와 confidence가 나타난다. 결과 옆에 정확한 model version,
threshold `0.20`, 처리시각, `prediction은 GT가 아님`이 표시된다.

→ `[조작]` Owner는 영상 재생·scrub, bbox 표시/숨기기를 사용한다.

→ `[반응]` 화면은 prediction을 그리기만 한다. GT 저장, 승인, Dataset membership, 학습 enqueue API는
호출하지 않는다. 파일은 worker의 mode 0700 temporary directory에서 처리 후 삭제된다.

→ `[감정]` Owner는 모델 제안과 사람 정답이 섞이지 않았음을 확인한다.

### 4.3 미검출과 실패

`[화면]` detection이 0이면 `후보 박스를 찾지 못했어. 게코 없음 판정이 아니니 직접 확인해줘.`를
표시한다. 인증 실패, Preview flag 누락, worker identity mismatch, timeout, decode 실패는 내부 경로·token·
exception 없이 각각 401/403/404 또는 안전한 5xx로 끝난다.

→ `[감정]` Owner는 recall `75.56%`의 미검출을 부재 정답으로 오해하지 않는다.

## 5. 시스템 구조

```text
v2.5 private training best.pt (read-only)
  -> size/SHA 검증
  -> v2.5 immutable release copy (0444 checkpoint + manifest)
  -> exact-SHA Mac mini runtime worktree
  -> com.petcam.yolo-preview-worker-v25 / 127.0.0.1:8095
  -> 별도 Named Tunnel / yolo-v25-preview.tera-ai.uk
  -> Vercel feature-branch Preview
  -> requireOwner POST /api/yolo-owner/preview/infer
  -> /labeling/owner/yolo/preview bbox overlay

existing production:
  public /gecko-detector -> v2.3 worker (변경 없음)
  DB/R2/GT/GME/Gate -> 연결 없음
```

## 6. artifact handoff와 immutable release

artifact를 복사하거나 worker를 시작하기 전에 두 gate를 순서대로 통과한다.

1. design/plan을 tracked commit에 넣고 local implementation manifest가 `HANDOFF_OK`를 반환한다.
2. 구현·검증 commit을 Mac mini의 별도 clean detached worktree에서 checkout한다.
3. runtime manifest에 execution repo, design/plan 절대경로, exact commit SHA, implementation/runtime host,
   runtime label을 기록하고 Mac mini에서 다시 `HANDOFF_OK`를 받는다.
4. 그 뒤에만 private source의 size/SHA를 검증하고 기존 `create_immutable_release` 경계로 새 release를
   만든다.

source checkpoint는 수정하지 않는다. destination은 fresh version+digest directory이고 checkpoint와
manifest는 mode `0444`, release root는 owner-only다. source/copy SHA가 다르거나 existing release identity가
다르면 모델 load 전에 중단한다. 경로·private manifest·token은 HTTP, Git, stdout에 넣지 않는다.

## 7. Worker 계약

- 기존 release schema에 v2.3과 v2.5 두 exact allowlist manifest를 지원한다.
- 기존 v2.3 runtime은 환경값이 없어도 v2.3으로 고정되어 동작을 유지한다.
- v2.5 runtime은 `YOLO_EXPECTED_MODEL_VERSION`과 manifest가 exact 일치해야 시작한다.
- v2.5 manager/service는 별도 파일 또는 profile로 격리하고 label `com.petcam.yolo-preview-worker-v25`,
  port `8095`를 사용한다.
- inference는 `imgsz=960`, `conf=0.20`, `iou=0.70`, `max_det=20`, `device=mps`다.
- 사진은 한 frame, 영상은 기존 최대 60초·30fps·1920×1080·최대 300 sampled frames 계약을 재사용한다.
- 인증 bearer, process limiter, concurrency 1, magic-byte/decode 검증, temp TTL/cleanup, no-store,
  error redaction을 유지한다.
- health/response는 model version, full checkpoint SHA, threshold, `development_only=true`,
  `usage_scope=owner_preview_bbox_suggestion_only`를 반환하고 local path는 반환하지 않는다.

## 8. Web/API 권한과 데이터 흐름

- 새 API는 `/api/yolo-owner/preview/infer`다. 공개 `/api/yolo-demo/infer`를 재사용하거나 바꾸지 않는다.
- 처리 순서는 `requireOwner` → `VERCEL_ENV=preview` → `YOLO_V25_OWNER_PREVIEW_ENABLED=true` → exact
  worker origin/token → upload validation → worker → exact v2.5 identity validation이다.
- 인증/Owner/flag/config 실패 시 body parse와 worker 호출은 0이다.
- production target에서는 flag가 있더라도 새 API가 worker를 호출하지 않는다.
- UI는 기존 detection overlay를 재사용하되 training-consent와 GT/revision control을 렌더하지 않는다.
- response는 client state에만 두며 Supabase, R2, localStorage, analytics payload에 쓰지 않는다.
- 기존 `/labeling/owner/yolo`의 Dataset/model activation UI와 연결하지 않는다.

## 9. 배포와 rollback

1. v2.5 exact branch를 push하고 Mac mini runtime handoff를 검증한다.
2. 새 immutable release와 v2.5 LaunchAgent를 만든다.
3. localhost image/video/zero-detection/auth/temp-residue canary를 통과한다.
4. 별도 Named Tunnel과 hostname을 만들고 authenticated/unauthenticated remote canary를 통과한다.
5. Vercel feature-branch Preview에 v2.5 전용 URL/token/flag만 주입해 Preview deployment를 만든다.
6. Owner 브라우저에서 업로드→bbox→version/threshold/warning→no-write 흐름을 확인한다.
7. production alias/deployment와 공개 v2.3 health/inference가 변하지 않았음을 다시 확인한다.

정상 rollback은 Preview flag/URL을 제거한 새 Preview deployment다. runtime rollback은 v2.5 LaunchAgent와
별도 tunnel만 bootout한다. 기존 v2.3 service/tunnel/release와 production Vercel 설정은 수정하지 않는다.

## 10. 테스트와 완료 조건

- release: v2.3 회귀 + v2.5 exact manifest, SHA/size/metrics/threshold mismatch fail-closed, no-overwrite.
- worker: v2.5 startup identity, threshold invocation, health/response scope, auth/limit/decode/temp cleanup.
- web: unauthenticated 401, non-owner 403, flag/config/production fail-closed, exact identity mismatch 502,
  Owner UI version/threshold/development/future-holdout/no-GT copy.
- full Python/Web test, TypeScript, Next production build, `git diff --check`.
- runtime: hostname, exact repo HEAD, clean status, service loaded, MPS health, image/video inference,
  temp residue 0, secret/path leak 0.
- Preview: deployment READY와 실제 Owner 브라우저 flow.
- negative canary: production deployment/alias unchanged, public v2.3 identity unchanged, DB/R2/GT/GME/Gate
  write/call 0.

모든 증거가 있을 때만 `PREVIEW_READY_V25_OWNER_ONLY`라고 보고한다. future holdout 전에는 팀원 기본 모델,
public model, GME/Gate, production 모델로 승격하지 않는다.
