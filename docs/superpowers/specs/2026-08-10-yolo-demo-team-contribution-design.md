# YOLO 게코 감지 시연과 초대 팀원 bbox 기여 설계

**상태:** owner 승인 제품 결정을 구현 가능한 계약으로 고정

**목표:** 라벨링 웹에 공개 사진·영상 게코 bbox 시연과 초대 팀원 전용 blind-first bbox 기여 흐름을
추가하되, 모델 prediction·사람 후보·Owner 승인 GT·Dataset 버전·active 모델을 서로 다른 원장으로
보존한다.

## 1. 확정 결정

1. 공개 사용자는 로그인 없이 사진/영상을 올리고 연구용 bbox 결과를 본다.
2. 공개 업로드는 기본 학습 제외다. 명시적 동의도 `public_opt_in_candidate`일 뿐 GT가 아니다.
3. 학습 기여는 로그인한 승인 라벨러 중 Owner가 bbox task를 배정한 초대 팀원만 한다.
4. 팀원은 prediction을 보지 않고 사람 bbox를 잠근 뒤 reveal한다. reveal 뒤 보정은 별도 revision이다.
5. Owner가 승인한 사람 revision만 특정 Dataset 버전 membership에 들어간다.
6. 모델 artifact/version은 immutable이다. 고정 시험과 future holdout 통과, Owner 수동 승인 뒤에만
   append-only activation event를 추가한다. 이전 version 재활성화가 즉시 롤백이다.
7. 결과 화면은 model version, confidence, 처리시각, `연구용 결과이며 오류 가능` 문구를 표시한다.
8. 사진은 정적 overlay, 영상은 `timestamp_ms`별 overlay를 재생 위치와 동기화한다.
9. 형식·크기·횟수 제한, 임시 저장 TTL, 악성 입력 방어를 fail-closed로 둔다.
10. Vercel은 추론하지 않는다. 주입 가능한 worker adapter와 fake를 먼저 만들고 실제 checkpoint는
    별도 gate다.
11. prediction은 GT·자동 skip·삭제·행동명 근거가 아니다. 종료된 연구 트랙은 재개하지 않는다.

## 2. 접근법 비교와 선택

### A. Vercel 내부 동기 YOLO

배포는 단순하지만 큰 영상과 모델 메모리를 serverless 수명에 묶는다. checkpoint/런타임 교체가 웹
배포와 결합하므로 제외한다.

### B. 브라우저의 worker 직접 업로드

Vercel의 byte relay는 줄지만 worker 주소·인증·CORS·rate limit이 공개 클라이언트 계약이 된다.
Mac mini를 인터넷 경계에 직접 놓는 위험 때문에 제외한다.

### C. same-origin API + inference adapter — 채택

브라우저는 `/api/yolo-demo/infer`만 호출한다. route는 요청 제한·magic byte·동의값을 검증한 뒤
`GeckoDetectionProvider.analyze()`를 호출한다. 기본 fake는 테스트/로컬 시연 전용이고, 후속 HTTP
adapter는 인증된 worker에 전달한다. 어느 provider도 Vercel process 안에서 YOLO를 실행하지 않는다.

## 3. 시스템 경계

```text
public browser ─┐
                ├─ Next.js same-origin API ─ validation/rate limit ─ provider interface
invited member ─┘                                                   │
                                                                    ├─ fake (test/local only)
                                                                    └─ HTTP worker (follow-up gate)

prediction ledger ──X──> GT
human blind submission -> reveal -> human revision -> Owner approval -> Dataset membership
model release -> fixed test -> future holdout -> Owner approval -> activation event -> active model
```

Vercel route가 받는 파일 byte는 요청 처리 동안만 메모리에 있고 파일시스템/R2/DB에 쓰지 않는다.
실제 worker adapter가 생기면 worker가 random object id로 임시 저장하고 `expires_at` 이내 삭제한다.
이번 구현은 worker TTL 계약과 응답 필드를 검증하지만 실제 외부 저장은 만들지 않는다.

## 4. 공개 사용자 체험 흐름

### 4.1 첫 화면

`[화면]` 제목 `게코 찾기 연구실`, 사진/영상 drop zone, 지원 형식·용량, 연구용 경고가 보인다.

→ `[조작]` 사용자가 파일 하나를 끌어놓거나 선택한다.

→ `[반응]` 브라우저가 확장자만 믿지 않고 API가 magic byte와 크기를 확인한다. 잘못된 파일은 업로드
전에 명확한 한글 오류로 끝난다.

→ `[감정]` 무엇을 올릴 수 있고 데이터가 어떻게 다뤄지는지 예측할 수 있다.

### 4.2 선택적 학습 동의

`[화면]` 기본 해제된 `이 업로드를 연구 데이터 후보로 제공` checkbox와 “GT가 아니며 Owner 검수
전 학습에 쓰지 않음” 설명이 보인다.

→ `[조작]` 사용자가 선택하거나 그대로 둔다.

→ `[반응]` 선택하지 않으면 inference 외 사용 금지, 선택해도 응답의 `contribution_status`는
`candidate_only`다.

→ `[감정]` 공개 시연과 학습 제공이 강제로 묶이지 않았음을 안다.

### 4.3 사진 결과

`[화면]` 처리 중에는 진행 상태와 취소 불가 범위가 보인다.

→ `[반응]` 완료되면 원본 사진 위에 bbox와 confidence가 표시되고, 옆에 model version·처리시각·
provider mode·연구용/오류 가능 경고가 보인다.

→ `[조작]` 사용자가 박스 표시를 켜고 끈다.

→ `[감정]` 모델의 관측과 원본을 쉽게 비교하되 정답으로 오해하지 않는다.

### 4.4 영상 결과 — 프레임 단위

`[화면]` 영상과 canvas overlay, 재생/탐색 bar, 현재 시각의 bbox/confidence가 보인다.

→ `[조작]` 재생하거나 scrub한다.

→ `[반응]` `requestAnimationFrame`에서 `currentTime`과 가장 가까운 과거 detection frame을 고르고
허용 간격을 넘으면 박스를 지운다. resize 시 normalized 좌표로 다시 그린다.

→ `[감정]` 박스가 영상과 함께 움직이고 없는 구간을 임의 보간하지 않는다는 신뢰를 얻는다.

### 4.5 실패·제한

`[화면]` 429는 다시 시도 가능한 시각, 413은 실제 한도, 415는 지원 형식, 422는 손상/악성 의심,
502/503은 연구 worker 일시 중단으로 표시한다. 내부 URL·credential·checkpoint 경로는 보이지 않는다.

## 5. 초대 팀원 체험 흐름

### 5.1 접근과 blind 작업

`[화면]` 승인 라벨러 메뉴의 `게코 박스 기여`에 본인에게 배정된 다음 task와 진행률이 보인다.

→ `[조작]` 사진 또는 영상의 지정 frame에서 drag로 박스를 만들고, 선택/이동/크기 조정/삭제한다.

→ `[반응]` 좌표는 media 표시 크기가 아니라 normalized `[0,1]` 값으로 저장된다. 빈 박스 제출은
`게코 없음`을 명시적으로 선택해야만 허용한다.

→ `[감정]` 모델 힌트 없이 자신의 관찰만 기록하고 있다는 확신을 얻는다.

### 5.2 blind 잠금과 reveal

`[화면]` 제출 전에는 model version, confidence, prediction box가 DOM/API 응답 모두에 없다.

→ `[조작]` `내 박스 잠그고 모델 결과 보기`를 누른다.

→ `[반응]` 서버가 append-only blind submission을 만든 뒤에만 reveal timestamp와 prediction을
반환한다. 원본 사람 박스는 수정되지 않는다.

→ `[감정]` 자신의 판단이 모델에 끌리지 않았음을 보존한다.

### 5.3 차이 수정

`[화면]` 사람 blind box와 model box가 색으로 구분되고 frame별 추가/수정/삭제가 가능하다.

→ `[조작]` 차이를 검토해 최종 사람 revision과 짧은 변경 사유를 제출한다.

→ `[반응]` 새 revision이 `owner_review` 후보로 쌓이고 모델 prediction은 그대로 남는다.

→ `[감정]` 모델을 채점하면서도 최종 사람 판단을 독립적으로 남긴다.

### 5.4 Owner 승인

`[화면]` Owner는 blind 원본, reveal 후 revision, model prediction을 나란히 보고 provenance를 확인한다.

→ `[조작]` 승인 또는 반려한다. 승인은 대상 Dataset draft version을 명시한다.

→ `[반응]` 승인 event와 Dataset membership이 append되고 같은 revision의 중복 승격은 거부된다.

→ `[감정]` 어떤 사람 라벨이 어떤 dataset에 들어갔는지 되짚을 수 있다.

## 6. 공개 inference 계약

### 6.1 요청 제한

- image: JPEG/PNG/WebP, 최대 10 MiB, decoded 최대 4096×4096 및 20 megapixels
- video: MP4/WebM, 최대 50 MiB, worker 검증 duration 최대 60초, 최대 30 fps, 최대 1920×1080
- multipart field는 `media` 하나와 `training_consent=true|false`만 허용한다.
- client filename은 log/storage key로 사용하지 않는다.
- 동일 네트워크 식별자 기준 10분 5회 token bucket 계약을 둔다. serverless 다중 instance를 위한
  durable rate-limit provider는 후속 운영 gate이며, fake/in-memory limiter는 local/test 전용이다.
- `X-Content-Type-Options: nosniff`, `Cache-Control: no-store`를 응답에 둔다.

### 6.2 응답

```ts
type NormalizedBox = { x: number; y: number; width: number; height: number };
type Detection = { label: 'gecko'; confidence: number; bbox: NormalizedBox };
type DetectionFrame = { frame_index: number; timestamp_ms: number; detections: Detection[] };
type GeckoDetectionResult = {
  request_id: string;
  media_kind: 'image' | 'video';
  model_version: string;
  provider_mode: 'fake' | 'worker';
  processed_at: string;
  warning: string;
  frames: DetectionFrame[];
  contribution_status: 'not_requested' | 'candidate_only';
};
```

모든 숫자는 finite여야 한다. bbox는 0..1 범위 안이며 width/height는 0보다 커야 한다. frame은
`timestamp_ms`, `frame_index` 오름차순이다. invalid provider 응답은 502로 fail-closed한다.

## 7. provider와 dependency injection

```ts
interface GeckoDetectionProvider {
  readonly mode: 'fake' | 'worker';
  analyze(input: DetectionInput): Promise<GeckoDetectionResult>;
}

type DetectionInput = {
  requestId: string;
  bytes: Uint8Array;
  mediaKind: 'image' | 'video';
  contentType: string;
  originalSize: number;
  trainingConsent: boolean;
};
```

`createInferRoute({provider, limiter, now, requestId})` factory가 실제 `POST`와 테스트를 분리한다.
`FakeGeckoDetectionProvider`는 deterministic normalized box를 반환하며 `provider_mode=fake`를 UI에
명시한다. production 환경의 fake와 in-memory rate limiter는 항상 503 fail-closed다. 실제
HTTP adapter/checkpoint URL·shared secret·worker temp storage는 별도 승인 후 추가한다.

## 8. DB 원장

새 forward-only migration은 기존 행동/GT 테이블을 수정하지 않는다.

- `yolo_model_versions`: immutable version, artifact digest, architecture, created_at. UPDATE/DELETE 차단.
- `yolo_model_evaluations`: version + suite(`fixed_test|future_holdout`) + manifest digest + metrics + pass.
- `yolo_model_approval_events`: Owner의 approve/reject와 reason.
- `yolo_model_activation_events`: activate/rollback target version의 append-only event. 활성 view는 최신 event.
- `yolo_bbox_tasks`: Owner가 media/frame manifest와 prediction snapshot id를 초대 팀원에게 배정.
- `yolo_bbox_blind_submissions`: reveal 전 사람 boxes, append-only, task당 1개.
- `yolo_bbox_reveals`: submission 뒤 model snapshot 공개 시각, task당 1개.
- `yolo_bbox_revisions`: reveal 뒤 최종 사람 boxes + reason, append-only version.
- `yolo_bbox_owner_decisions`: revision 승인/반려 event.
- `yolo_dataset_versions`: immutable draft/frozen version metadata.
- `yolo_dataset_memberships`: Owner-approved revision만 dataset version에 연결, 중복 방지.

공개 opt-in byte 저장 테이블은 이번 migration에 만들지 않는다. 실제 worker temp/object 계약과 별도
candidate ingestion 정책이 승인되기 전까지 공개 업로드는 inference 종료와 함께 폐기한다.

## 9. 권한·blind 불변식

- 모든 새 테이블은 RLS on, `PUBLIC/anon/authenticated` direct 권한을 revoke하고 service_role API만 쓴다.
- 공개 inference route만 인증 없이 열고 파일 byte를 DB/R2에 쓰지 않는다.
- 팀원 API는 기존 `requireLabelingAccess`와 task `assignee_id == bearer user`를 둘 다 요구한다.
- blind workspace projection에는 prediction/model/confidence/reveal row가 없다.
- reveal RPC는 blind submission 존재를 row lock으로 확인한다. 최초 호출만 immutable reveal row를 만들고,
  네트워크 재시도는 같은 row와 allowlisted prediction을 idempotent replay해 잠긴 작업을 복구한다.
- revision은 reveal 뒤에만 가능하다.
- Owner decision과 Dataset membership은 같은 transaction RPC에서 처리한다.
- Owner reject는 latest revision과 사유를 같은 assignee의 `revealed` task로 되돌린다. pending/approve는
  재제출을 막고 reject 뒤에만 다음 immutable revision을 허용한다.
- Dataset freeze는 append-only status event이며 freeze 이후 membership 추가를 거부한다.
- activation RPC는 fixed test pass, future holdout pass, latest Owner approve를 모두 확인한다.
- activation/rollback은 append-only여서 이전 active version을 즉시 다시 target으로 기록할 수 있다.

## 10. UI 구조

- 공개: `/gecko-detector`
- 팀원: `/labeling/yolo`
- Owner 검수: `/labeling/owner/yolo`
- API: `/api/yolo-demo/infer`, `/api/yolo-contributions/**`, `/api/yolo-owner/**`
- 순수 계약: `web/src/lib/yoloDetection.ts`
- server provider/validation: `web/src/lib/yoloDetectionServer.ts`
- bbox 편집 순수 로직: `web/src/lib/yoloBboxEditor.ts`
- 화면: upload form, media overlay, contributor workspace, Owner review queue

기존 역할 shell에는 승인 labeler/owner만 `게코 박스` 항목을 추가한다. 미승인 사용자는 경로 가드와
API 모두 차단한다.

## 11. 오류·개인정보·악성 입력

- route에서 magic byte 불일치 415·크기 초과 413·rate limit 429를 막는다. 실제 worker 연결 gate에서
  decode/metadata 구조 손상을 422로 추가하며, 그 전 production은 503 fail-closed다.
- worker/provider 원문 오류, URL, secret, checkpoint path는 응답/로그에 넣지 않는다.
- object URL은 component unmount/새 파일 선택 시 revoke한다.
- SVG, archive, animated image, executable, polyglot 의심 입력은 받지 않는다.
- 실제 worker는 decode timeout, frame/dimension/duration cap, isolated temp dir, random id, TTL cleanup
  증거를 제공해야 activation gate에 들어갈 수 있다.

## 12. 테스트와 검증

- Web unit: magic/type/size/rate limit, provider schema validator, fake determinism, bbox coordinate clamp,
  video frame selection, role navigation.
- API: 공개 success/error/no-store, fake production guard, contributor auth+assignment, blind projection,
  submit-before-reveal ordering, Owner-only decision.
- UI: image overlay, video time sync, warning/version/confidence/processed time, blind DOM non-disclosure.
- Python migration contract + disposable PostgreSQL probe: RLS/grants, append-only, blind ordering,
  Owner-approved Dataset membership, activation prerequisites, rollback event, rollback residue 0.
- 전체: `uv run pytest -q`, `cd web && npm test`, `npm run build`, `git diff --check`.

## 13. 구현 범위

### In

- provider interface, deterministic fake, route DI, upload 검증과 local rate limiter
- 공개 image/video overlay UI
- 새 원장 migration과 정적/실행 probe
- 초대 팀원 blind/reveal/revision API·UI
- Owner 승인/Dataset membership과 model activation 계약/API·최소 UI
- 문서와 환경변수 예시

### Out

- production DB migration apply, R2 write, 실제 temp object 저장
- Mac mini/별도 worker 설치·서비스 변경
- 실제 YOLO v2.1 checkpoint 또는 HTTP adapter 활성화
- Vercel Preview/production deploy
- 공개 opt-in media를 실제 dataset 후보 storage로 수집
- 모델 prediction 기반 GT·skip·삭제·행동명·사건 묶기

## 14. 완료 조건

- 공개 사용자가 허용 파일로 fake-backed local 시연을 수행하고 요구 메타데이터와 overlay를 본다.
- 사진/영상 response와 UI가 같은 versioned frame schema를 사용한다.
- 초대 팀원은 reveal 전 prediction을 API/DOM에서 볼 수 없고 blind submission 뒤 보정한다.
- Owner 승인 전 Dataset membership이 생기지 않는다.
- active model 변경은 두 evaluation pass + Owner approve 없이는 실패하고 append-only rollback이 된다.
- migration은 파일과 disposable probe까지만 검증하며 운영에는 적용하지 않는다.
- 실제 checkpoint/worker 연결이 별도 gate임을 UI·문서·환경 예시에 명확히 남긴다.
