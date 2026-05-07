# 라벨링 웹 백엔드 분리 — Vercel → Supabase/R2 직결

> 사용자 맥북 의존 제거. 라벨링 페이지가 영상/라벨/추론/클립 메타를 Vercel Next.js API route 에서 직접 발급받음.

**상태:** ✅ 완료 (2026-05-07)
**작성:** 2026-05-07
**연관 SOT:** `../../tera-ai-product-master/products/petcam/README.md`
**상위 spec:** [cloud-migration-roadmap.md](cloud-migration-roadmap.md)

## 1. 목적

[cloud-migration-roadmap.md](cloud-migration-roadmap.md) 락인 후, fly.io 로 VLM 워커는 옮겼지만 **라벨링 웹 (label.tera-ai.uk) 의 영상 재생/라벨 조회/추론 표시가 여전히 사용자 맥북 (`api.tera-ai.uk` Cloudflare Tunnel) 의존** 이었음. 맥북 꺼지면 라벨링 페이지 진입 자체가 안 됨.

`/api/label`, `/api/poc/summary`, `/api/clips/[id]` (DELETE), `/api/upload/sign`, `/api/upload/finalize` 는 이미 Vercel→Supabase/R2 직결. 이 패턴을 4개 endpoint 더 확장해서 owner PoC 흐름이 완전 클라우드에서 돌게 만든다.

## 2. 스코프

### In
- `web/src/lib/r2.ts`: `presignGet` + `SIGNED_URL_TTL_SEC` (1h, backend `DEFAULT_SIGNED_URL_TTL` 동치).
- `web/src/lib/clipPerms.ts` 신규: Bearer token verify + owner/labeler 분기 helper. `backend/clip_perms.py` 동치.
- 4개 Next.js API route 신규/추가:
  - `GET /api/clips/[id]` — 클립 메타 (owner-only).
  - `GET /api/clips/[id]/file/url` — R2 signed URL (owner+labeler).
  - `GET /api/clips/[id]/labels` — behavior_labels (owner 전체 / labeler 본인만).
  - `GET /api/clips/[id]/inference` — behavior_logs source=vlm 최신 1건 (owner-only).
- `web/src/lib/labelingApi.ts`: `request()` 가 `/api/` prefix 면 same-origin, 아니면 `BACKEND_URL`. 4개 함수 (`getClip`, `getMyLabels`, `getInference`, `getClipFileUrl`) 만 전환.

### Out (이번 spec 에서 안 함)
- 라벨러 큐 (`/labels/queue`) / 내 라벨 회고 (`/labels/mine`) — 라벨러 흐름. owner PoC 범위 밖.
- 썸네일 URL (`/clips/{id}/thumbnail/url`) — 라벨링 페이지에서 안 씀.
- 라벨 저장 endpoint (`POST /clips/{id}/labels`) — owner 는 이미 `/api/label` (Supabase 직결) 사용.
- 캡처 워커 클라우드 이전 — 자체 HW 대체 예정 (메모리 참고: `project_capture_replaced_by_own_hw.md`).
- API 서버 전체 fly.io 이전 — 옵션 2 였으나 사용자가 옵션 1 (최소 변경) 선택.

## 3. 완료 조건

- [x] `web/src/lib/r2.ts` 에 `presignGet` 추가 (1h TTL).
- [x] `web/src/lib/clipPerms.ts` 작성 — `verifyBearer`, `loadClipWithPerms`, `isLabeler` (내부).
- [x] `GET /api/clips/[id]` 추가 (route.ts 기존 DELETE 옆).
- [x] `GET /api/clips/[id]/file/url` 신규.
- [x] `GET /api/clips/[id]/labels` 신규.
- [x] `GET /api/clips/[id]/inference` 신규.
- [x] `labelingApi.ts` 4개 함수 `/api/` prefix 로 전환 + `request()` 분기.
- [x] `tsc --noEmit` 통과.
- [x] `git push origin main` → Vercel 자동 배포.
- [x] `label.tera-ai.uk` 라벨링 페이지 실기 검증 (영상 재생 + 라벨 prefill + VLM 추론 표시 + 라벨 저장 toast). 사용자 스크린샷 확인 (clip 3b0d9995 — shedding conf 1.00).

## 4. 설계 메모

### 권한 모델 — backend 와 동치 유지

`backend/clip_perms.py` 의 `load_clip_with_perms`, `is_labeler` 를 web 으로 그대로 옮김:
- owner: `clip.user_id == user_id` → 모든 라벨/추론 조회.
- labeler: `labelers` 테이블 멤버 → 영상/라벨 폼 접근, 본인 라벨만.
- 외부인: 둘 다 아님 → **404** (존재 leak 방지). 403 안 씀.

`/api/clips/[id]` GET 만 owner-only — 이건 backend `get_clip` 이 `.eq("user_id", user_id)` 로 owner-only 라서 동치 유지. 라벨러는 큐 endpoint 로 들어와야 함 (`/labels/queue`, 이번 범위 밖).

`/api/clips/[id]/inference` 도 owner-only — VLM 추론은 검수 화면 (다른 라벨러 결과 비공개 영역과 동일 카테고리).

### request() 분기 패턴

`labelingApi.ts` 의 `request()` 가 path 보고 분기:
- `/api/...` 시작 → same-origin (Vercel)
- 그 외 → `${BACKEND_URL}${path}` (FastAPI)

이렇게 한 이유:
- 함수 시그니처 그대로 유지 (호출부 무수정).
- 단계적 이전 가능 — 나머지 endpoint 도 같은 prefix 만 바꾸면 끝.
- `BACKEND_URL` 변수 자체는 남겨둠 — `/labels/queue`, `/labels/mine`, `/thumbnail/url` 이 아직 의존.

### 미전환 endpoint 가 살아있는 이유

| Endpoint | 사용처 | 결정 |
|---|---|---|
| `/labels/queue` | 라벨러 큐 페이지 | owner 본인은 안 씀, 미전환 |
| `/labels/mine` | 내 라벨 회고 페이지 | 동일 |
| `/clips/{id}/thumbnail/url` | (현재 라벨링 흐름에서 안 씀) | 미전환 |
| `POST /clips/{id}/labels` | (owner 는 `/api/label` 사용) | 미전환 |

라벨러 흐름 클라우드 이전이 필요해지면 별도 spec 으로.

### 검증 — 사용자 스크린샷

clip `3b0d9995` (52초, 모션, 2026-04-30):
- 영상 재생 ✅
- 클립 메타 표시 ✅ (`52s · 모션`)
- VLM 추론 ✅ (`shedding conf 1.00 gemini-2.5-flash-zeroshot-v3.5` + reasoning: "The crested gecko is actively pulling off and consuming its old, pale skin...")
- 라벨 chip UI ✅
- 검수 섹션 ✅

VLM 자동 라벨링 (fly.io 워커) + Vercel 직결 endpoint 가 동시에 정상 가동된 증거.

## 5. 학습 노트

- **`@aws-sdk/client-s3` `GetObjectCommand`**: PutObjectCommand 와 같은 SDK 의 GET 버전. `getSignedUrl(client, cmd, {expiresIn})` 으로 1h URL 발급. boto3 의 `client.generate_presigned_url('get_object', ...)` 동치.
- **Supabase `auth.getUser(token)`**: service_role 클라이언트로 임의 JWT 검증 → user 객체 (id 포함). RLS 우회 라우트에서 토큰 정체성 확인용.
- **Next.js path-based routing**: `/api/` prefix 가 같은 origin 라우팅 트리거. 외부 fetch URL prefix 분기에 활용 — Vercel 한 번 배포로 라우팅 자동 전환.
- **외부인 = 404 패턴**: 403 으로 응답하면 "이 ID 는 존재하지만 권한 없음" 노출 → ID enumeration. 404 통일하면 "존재 자체 leak" 차단.

## 6. 참고

- 상위: [cloud-migration-roadmap.md](cloud-migration-roadmap.md)
- 워커 spec: [feature-vlm-worker-cloud.md](feature-vlm-worker-cloud.md), [feature-vlm-worker-fly-deploy.md](feature-vlm-worker-fly-deploy.md)
- Flutter 측: [flutter-cloud-handoff.md](flutter-cloud-handoff.md) — 백엔드 가동 상태 표 참고
- 백엔드 동치 코드: `backend/clip_perms.py`, `backend/routers/clips.py:get_clip_file_url`, `backend/routers/labels.py:list_labels` / `get_clip_inference`
- 커밋: `c81b5b2`
