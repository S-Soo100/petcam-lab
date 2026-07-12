# API 레퍼런스

> FastAPI 가 띄우는 HTTP 엔드포인트 전부. 로컬 `http://localhost:8000`, 배포 `https://api.tera-ai.uk`.

## 목차

- [인증](#인증)
- [에러 포맷](#에러-포맷)
- [엔드포인트 요약](#엔드포인트-요약)
- [루트 / 상태](#루트--상태)
  - [`GET /`](#get-)
  - [`GET /health`](#get-health)
- [클립 (`/clips`)](#클립-clips)
  - [`GET /clips`](#get-clips)
  - [`GET /clips/highlights`](#get-clipshighlights)
  - [`GET /clips/{id}`](#get-clipsid)
  - [`GET /clips/{id}/file`](#get-clipsidfile)
  - [`GET /clips/{id}/file/url`](#get-clipsidfileurl)
  - [`GET /clips/{id}/thumbnail`](#get-clipsidthumbnail)
  - [`GET /clips/{id}/thumbnail/url`](#get-clipsidthumbnailurl)
- [라벨 (`/clips/{id}/labels`, `/labels`)](#라벨-clipsidlabels-labels)
  - [`POST /clips/{id}/labels`](#post-clipsidlabels)
  - [`GET /clips/{id}/labels`](#get-clipsidlabels)
  - [`GET /clips/{id}/inference`](#get-clipsidinference)
  - [`GET /labels/queue`](#get-labelsqueue)
  - [`GET /labels/mine`](#get-labelsmine)
- [본인 (`/me`)](#본인-me)
  - [`GET /me/is_labeler`](#get-meis_labeler)
- [카메라 (`/cameras`)](#카메라-cameras)
  - [`POST /cameras/test-connection`](#post-camerastest-connection)
  - [`POST /cameras`](#post-cameras)
  - [`GET /cameras`](#get-cameras)
  - [`GET /cameras/{id}`](#get-camerasid)
  - [`PATCH /cameras/{id}`](#patch-camerasid)
  - [`DELETE /cameras/{id}`](#delete-camerasid)
- [Swagger UI](#swagger-ui)

---

## 인증

`AUTH_MODE` 환경변수로 두 모드 자동 분기 ([`backend/auth.py`](../backend/auth.py)).

| 모드 | 동작 | 용도 |
|------|------|------|
| `dev` (기본) | `Authorization` 헤더 무시, `DEV_USER_ID` 를 user_id 로 사용 | 로컬 개발 / pytest |
| `prod` | `Authorization: Bearer <JWT>` 필수, Supabase JWKS 로 서명 검증 | 배포 (fly.io `petcam-api`, Cloudflare DNS A/AAAA → fly.io edge) |

**prod 헤더 예시**

```
Authorization: Bearer eyJhbGciOiJFUzI1NiIsImtpZCI6ImFiY2QiLCJ0eXAiOiJKV1QifQ...
```

**검증 항목 (prod)**
- JWT 서명 (JWKS `alg` 필드 기반, 현재 Supabase 는 ES256)
- `exp` (만료 시각)
- `iss` = `SUPABASE_JWT_ISSUER`
- `sub` claim 추출 → `user_id`

**JWKS 캐시** 10분 TTL. 키 로테이션 시 최대 10분 불일치 가능, `kid` 매칭 실패 시 1회 자동 재시도 후 초기화.

**`/` 와 `/health` 만 인증 불필요.** 나머지는 전부 `Depends(get_current_user_id)` 가 걸려 있음.

---

## 에러 포맷

FastAPI 표준 `HTTPException` 포맷.

```json
{
  "detail": "에러 원인 문자열"
}
```

유효성 에러(422) 는 Pydantic 포맷.

```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "display_name"],
      "msg": "Field required",
      "input": { ... }
    }
  ]
}
```

**주요 상태 코드**

| 코드 | 의미 | 발생 케이스 |
|------|------|------------|
| 200 | OK | 조회 성공 |
| 201 | Created | POST 카메라 등록 성공 |
| 206 | Partial Content | `GET /clips/{id}/file` + `Range` 헤더 |
| 400 | Bad Request | RTSP probe 실패, PATCH 빈 바디 |
| 401 | Unauthorized | prod 모드에서 JWT 누락/무효/만료 |
| 404 | Not Found | 클립/카메라 미존재 or 타 유저 것 |
| 409 | Conflict | 카메라 `(user_id, host, port, path)` 중복 |
| 410 | Gone | DB 행은 있는데 mp4 파일 사라짐 |
| 416 | Range Not Satisfiable | `Range` 헤더 포맷 이상 / 파일 범위 초과 |
| 422 | Unprocessable Entity | Pydantic 유효성 실패 |
| 502 | Bad Gateway | Supabase 쿼리 실패 (네트워크/DB) |

---

## 엔드포인트 요약

| 메서드 | 경로 | 인증 | 용도 |
|--------|------|------|------|
| GET | `/` | ❌ | 생존 신호 |
| GET | `/health` | ❌ | 서버 헬스체크 (fly.io probe + Flutter "점검 중" 분기) |
| GET | `/clips` | ✅ | 클립 목록 + 필터 + seek pagination |
| GET | `/clips/highlights` | ✅ | 하이라이트 (행동 라벨 클립) — main 4 제외 |
| GET | `/clips/{id}` | ✅ | 클립 단건 메타 |
| GET | `/clips/{id}/file` | ✅ | mp4 스트리밍 (Range 지원, R2 있으면 302 redirect) |
| GET | `/clips/{id}/file/url` | ✅ | **R2 signed URL JSON** — Flutter R2 직접 GET 용 |
| GET | `/clips/{id}/thumbnail` | ✅ | 썸네일 jpg (R2 있으면 302 redirect) |
| GET | `/clips/{id}/thumbnail/url` | ✅ | **썸네일 R2 signed URL JSON** |
| POST | `/clips/{id}/labels` | ✅ | 라벨 1건 UPSERT (라벨러 또는 owner) |
| GET | `/clips/{id}/labels` | ✅ | 클립의 라벨 목록 (owner=전체 / labeler=본인) |
| GET | `/clips/{id}/inference` | ✅ | 클립의 VLM 추론 (owner 전용) |
| GET | `/labels/queue` | ✅ | 라벨러 큐 (미라벨 클립, 최신순) |
| GET | `/labels/mine` | ✅ | 본인이 라벨한 클립 + 라벨 (회고용) |
| GET | `/me/is_labeler` | ✅ | 본인이 라벨러 멤버인지 |
| POST | `/cameras/test-connection` | ✅ | 등록 전 RTSP 핸드쉐이크 확인 |
| POST | `/cameras` | ✅ | 카메라 등록 (자동 probe) |
| GET | `/cameras` | ✅ | 본인 카메라 목록 |
| GET | `/cameras/{id}` | ✅ | 카메라 단건 |
| PATCH | `/cameras/{id}` | ✅ | 부분 수정 (비번 변경 시 재암호화) |
| DELETE | `/cameras/{id}` | ✅ | 카메라 삭제 |

**프로세스 분리 주의** — 위 endpoint 는 모두 **프로세스 #1 = `backend.main:app` (fly.io `petcam-api`)** 가 서빙. 캡처 워커 (#2) 와 VLM 워커 (#3) 는 별도 프로세스라 HTTP 외부 endpoint 없음. `/streams/{camera_id}/status` 같은 내부 워커 진단 endpoint 는 `feature-capture-worker-extraction` 시점에 제거 — 캡처 워커가 분리되면서 API 서버는 워커 메모리 상태를 모름. ([`docs/ARCHITECTURE.md`](ARCHITECTURE.md) §2 시스템 맵 참조)

---

## 루트 / 상태

### `GET /`

생존 신호.

**응답 200**
```json
{"message": "petcam-lab is alive"}
```

---

### `GET /health`

서버 헬스체크. **fly.io 머신 probe** + Flutter "서버 점검 중" 분기 양쪽에 사용.

**응답 200**
```json
{
  "status": "ok",
  "startup_error": null
}
```

**필드**

| 필드 | 타입 | 설명 |
|------|------|------|
| `status` | string | 항상 `"ok"` (엔드포인트 자체 응답) |
| `startup_error` | string \| null | Supabase 환경변수 누락 등 치명적이지 않은 startup 경고 |

**startup_error 예시**
- `"Supabase 미설정 (SUPABASE_URL 환경변수가 비어있음)"`
- `"CAMERA_SECRET_KEY 가 placeholder 인 채로 기동"`

**capture/vlm 워커 상태는 노출 X** — 캡처 워커 (#2) 와 VLM 워커 (#3) 는 별도 OS 프로세스 (다른 fly.io app) 에서 도므로 API 서버가 워커 메모리 상태를 모름.
- 캡처 워커 헬스: `backend.capture_main` 자체엔 `/health` 없음 (LAN 의존, 외부 모니터링은 fly.io / 자체 HW 운영체제 레벨)
- VLM 워커 헬스: `https://petcam-vlm-worker.fly.dev/health` (별도 fly.io app, [`backend/health.py`](../backend/health.py))

---

## 클립 (`/clips`)

전부 `Depends(get_current_user_id)` 필요. service_role 이라 RLS 우회되므로 라우터에서 `user_id` 필터를 명시적으로 건다.

### `GET /clips`

클립 목록, seek pagination.

**쿼리 파라미터**

| 이름 | 타입 | 기본 | 설명 |
|------|------|------|------|
| `camera_id` | UUID | (전체) | 특정 카메라만 |
| `has_motion` | bool | (전체) | `true` = motion 있는 것만 |
| `from` | ISO8601 | (전체) | `started_at >= from` |
| `to` | ISO8601 | (전체) | `started_at <= to` |
| `limit` | int (1~200) | 50 | 페이지 크기 |
| `cursor` | ISO8601 | (첫 페이지) | 이전 응답의 `next_cursor` |

**응답 200**
```json
{
  "items": [
    {
      "id": "clip-uuid",
      "user_id": "user-uuid",
      "camera_id": "camera-uuid",
      "pet_id": null,
      "file_path": "/Users/baek/.../storage/clips/2026-04-22/<cam>/183000_motion.mp4",
      "thumbnail_path": "/Users/baek/.../storage/clips/.../183000_motion.jpg",
      "started_at": "2026-04-22T18:30:00+09:00",
      "ended_at": "2026-04-22T18:31:00+09:00",
      "duration_seconds": 60,
      "has_motion": true,
      "motion_duration_seconds": 12.5,
      "file_size_bytes": 3512480
    }
  ],
  "count": 1,
  "next_cursor": "2026-04-22T18:30:00+09:00",
  "has_more": false
}
```

**페이지 진행**
- 응답의 `next_cursor` 를 다음 요청 `cursor=` 로 넘기면 다음 페이지.
- `has_more=false` 면 마지막 페이지.

**왜 offset 대신 seek?** offset 은 페이지 깊어질수록 Postgres 가 앞쪽을 버리는 비용이 커짐. `started_at < cursor` 는 항상 인덱스 한 번의 range scan.

---

### `GET /clips/highlights`

하이라이트 클립 목록 — **main 4 (eating_paste / drinking / moving / unknown) 제외 행동만**. (`cloud-migration-roadmap.md` §4-7)

> **현재 앱 경로 주의(2026-07-12):** 이 endpoint는 petcam-lab의 historical 계약이다. Flutter 어젯밤 리포트는 `api.terra-server.uk/clips/highlights`를 호출한다. terra-server 실제 기준은 VLM source, confidence >= 0.5, `moving/unseen/shedding` 억제, 본인 `motion_clips` 존재이며 motion 크기나 Gate 가시성은 조건이 아니다.

**정의**
- `eating_prey` / `defecating` / `shedding` / `basking` / `unseen` 라벨이 붙은 클립.
- 사람 검수 라벨 (`behavior_labels`) 있으면 그것 우선, 없으면 VLM 자동 라벨 (`behavior_logs.source='vlm'`).
- 클립당 1건 (한 클립에 여러 행동 매칭돼도 최우선 1개만 노출).

**쿼리 파라미터**

| 이름 | 타입 | 기본 | 설명 |
|------|------|------|------|
| `limit` | int (1~200) | 50 | 페이지 크기 |
| `cursor` | ISO8601 | (첫 페이지) | 이전 응답의 `next_cursor` (`started_at`) |

**응답 200**
```json
{
  "items": [
    {
      "id": "clip-uuid",
      "user_id": "user-uuid",
      "camera_id": "camera-uuid",
      "started_at": "2026-05-08T10:30:00+09:00",
      "ended_at": "2026-05-08T10:31:00+09:00",
      "has_motion": true,
      "r2_key": "clips/2026-05-08/.../103000_motion.mp4",
      "highlight_action": "shedding",
      "highlight_source": "vlm"
    }
  ],
  "count": 1,
  "next_cursor": null,
  "has_more": false
}
```

**`highlight_source`** — `"human"` (검수 라벨 우선) 또는 `"vlm"` (VLM 자동 라벨).

**구현 노트** — Postgrest 가 `DISTINCT ON` 미지원이라 두 테이블 fetch → set 합집합 → `camera_clips` IN-list 쿼리. 베타 트래픽 (사용자 1, < 5K clips) 가정. IN list 1000 초과면 RPC 로 이전.

**참고 코드:** [`backend/routers/clips.py:132`](../backend/routers/clips.py)

---

### `GET /clips/{id}`

단건 메타.

**응답 200** — [`GET /clips`](#get-clips) `items[0]` 과 동일 스키마.
**응답 404** — 미존재 or 타 유저 것.

---

### `GET /clips/{id}/file`

mp4 byte. **R2 키 있으면 자동으로 R2 signed URL 로 302 redirect**, 없으면 백엔드가 직접 byte stream (Range 지원).

**동작 분기**

| 클립 상태 | 응답 |
|----------|------|
| `r2_key` NOT NULL | **302 Found** → `Location: <R2 signed URL>` (1h TTL) |
| `r2_key` NULL + 디스크 파일 있음 | **200 / 206** mp4 스트리밍 (Range 지원) |
| `r2_key` NULL + 디스크 파일 없음 | **410 Gone** |

**Flutter 권장 — `/file/url` 사용** ([아래](#get-clipsidfileurl)). 이 endpoint 는 파일 스트리밍 fallback (R2 마이그레이션 이전 클립) + 라벨링 웹 server-side proxy 등 특수 케이스 용. 신규 클립은 모두 R2 라 redirect 한 번만 따라가도 결국 R2 GET 으로 끝남.

**Range 동작 (r2_key NULL + 로컬 fallback)**

```
Range: bytes=0-
Range: bytes=1048576-2097151
```

**응답 206 Partial Content**
```
Content-Range: bytes 1048576-2097151/5242880
Content-Length: 1048576
Accept-Ranges: bytes
```

**응답 416 Range Not Satisfiable** — Range 포맷 오류 or 파일 크기 초과.

**청크 크기** 256KB. 너무 작으면 첫 바이트 빨라도 네트워크 비효율, 크면 시크 응답성 저하.

---

### `GET /clips/{id}/file/url`

**Flutter / 라벨링 웹 권장 영상 재생 endpoint.** R2 signed URL 을 JSON 으로 반환 → 클라이언트가 그 URL 을 video element / `VideoPlayerController.networkUrl` 에 그대로 박아 재생.

**왜 redirect 가 아니라 JSON 으로?**
- HTML5 `<video src>` 태그는 cross-origin 요청에 `Authorization` 헤더를 못 보냄 (브라우저 보안 정책).
- 302 redirect 도 첫 요청에선 헤더 박지만 redirect target 으로 헤더를 안 가져감.
- → "URL 만 JSON 으로 받아서 video src 에 박는다" 가 표준 패턴.
- R2 signed URL 자체가 1시간 유효한 단발 토큰 → URL 만 알면 재생 가능 → Authorization 불필요.

**응답 200** — R2 키 있을 때
```json
{
  "url": "https://<account>.r2.cloudflarestorage.com/clips/2026-05-08/.../103000_motion.mp4?X-Amz-Algorithm=...&X-Amz-Signature=...",
  "ttl_sec": 3600,
  "type": "r2"
}
```

**응답 200** — 로컬 fallback (`r2_key` NULL, dev 모드 한정)
```json
{
  "url": "/clips/<id>/file",
  "ttl_sec": null,
  "type": "local"
}
```

`type=local` 은 같은 origin (AUTH_MODE=dev 로컬 개발) 에서만 의미 — prod 배포에선 R2 미업로드 클립은 410.

**응답 404** — 클립 미존재 또는 권한 없음.
**응답 410** — `r2_key` NULL + 디스크 파일도 없음.

**참고 코드:** [`backend/routers/clips.py:352`](../backend/routers/clips.py)

---

### `GET /clips/{id}/thumbnail`

클립 썸네일 jpg. **R2 키 있으면 자동으로 R2 signed URL 로 302 redirect**, 없으면 백엔드가 직접 jpg 반환 (FileResponse).

**응답 200** — `image/jpeg`, `FileResponse` 가 내부에서 `Content-Length` 자동 설정 (로컬 fallback).
**응답 302** — `Location: <R2 signed URL>` (`thumbnail_r2_key` 있을 때).

**응답 404 3분기** (전부 같은 코드, `detail` 로 원인 구분)
- `"clip '<uuid>' not found"` — DB 행 없음 또는 권한 없음
- `"thumbnail not generated for clip '<uuid>'"` — `thumbnail_path` NULL + `thumbnail_r2_key` NULL
- `"thumbnail file missing on disk: <path>"` — 디스크에서 파일이 사라짐

**생성 시점** — 세그먼트 종료 시 첫 유효 프레임을 OpenCV 로 `cv2.imwrite(quality=85)`. 320x240 내외. R2 업로드는 EncodeUploadWorker (프로세스 #2) 가 mp4 와 함께 PUT.

---

### `GET /clips/{id}/thumbnail/url`

썸네일 R2 signed URL JSON. `/file/url` 과 같은 패턴.

**응답 200**
```json
{
  "url": "https://<account>.r2.cloudflarestorage.com/clips/.../103000_motion.jpg?X-Amz-Signature=...",
  "ttl_sec": 3600,
  "type": "r2"
}
```

또는 (로컬 fallback)
```json
{
  "url": "/clips/<id>/thumbnail",
  "ttl_sec": null,
  "type": "local"
}
```

**응답 404** — `thumbnail_r2_key` + `thumbnail_path` 둘 다 NULL.

**참고 코드:** [`backend/routers/clips.py:395`](../backend/routers/clips.py)

---

## 라벨 (`/clips/{id}/labels`, `/labels`)

라벨링 웹 (Vercel `label.tera-ai.uk`) 과 라벨러 워크플로우용. 4-component 아키텍처에서 owner 검수와 라벨러 큐를 같이 다룬다.

**권한 모델 — 3-tier**
- **owner** (`clip.user_id == user_id`) — 모든 라벨 / VLM 추론 / 큐 / 라벨 강제 수정.
- **labeler** (`labelers` 테이블 멤버) — 모든 user 클립의 큐 + 본인 라벨만. VLM 추론 비공개 (영향 회피).
- **외부인** — 404 (`load_clip_with_perms` 차단).

**ActionType (9 raw 클래스)**
```
eating_paste / drinking / moving / unknown        ← main 4 (UI 상단)
eating_prey / defecating / shedding / basking / unseen   ← raw 호환 (하이라이트)
```

**LickTargetType (6 enum, action=eating_paste|drinking 일 때만 의미)**
```
air / dish / floor / wall / object / other
```

> **Why TEXT + 앱 검증?** spec §4 결정 6 — 라벨 클래스가 VLM 진화에 따라 바뀔 가능성 (9 raw → 8 → ...) → DB enum 마이그레이션 부담 없이 Pydantic 만 갈아끼우면 됨.

### `POST /clips/{id}/labels`

라벨 1건 UPSERT. UNIQUE `(clip_id, labeled_by)` — 같은 라벨러가 같은 클립에 다시 달면 update (last-write-wins).

**요청 바디**
```json
{
  "action": "eating_paste",
  "lick_target": "dish",
  "note": "사료 그릇 옆에서 핥기",
  "labeled_by": null
}
```

**필드**

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `action` | ActionType | ✅ | 9 raw 중 하나 |
| `lick_target` | LickTargetType \| null | | `eating_paste`/`drinking` 일 때만 의미 |
| `note` | string \| null | | 최대 2000자 |
| `labeled_by` | UUID \| null | | **owner 만** 다른 라벨러 라벨 강제 수정/생성. None=본인 |

**응답 201**
```json
{
  "id": "label-uuid",
  "clip_id": "clip-uuid",
  "labeled_by": "user-uuid",
  "action": "eating_paste",
  "lick_target": "dish",
  "note": "사료 그릇 옆에서 핥기",
  "labeled_at": "2026-05-08T18:30:00+09:00"
}
```

**응답 403** — `labeled_by` 다른 user 인데 본인이 owner 아님. `detail`: `"only clip owner can write labels for other users"`.
**응답 404** — 외부인 (clip owner 도 labeler 도 아님).
**응답 422** — 잘못된 `action`/`lick_target` enum.

**참고 코드:** [`backend/routers/labels.py:121`](../backend/routers/labels.py)

---

### `GET /clips/{id}/labels`

클립의 라벨 목록. 권한별 결과 다름.

**응답 200** — `LabelOut[]` (POST 응답 스키마 배열)
- `clip.user_id == user_id` (owner) → 모든 라벨러 결과 반환 (GT 합의 검토용)
- 그 외 (labeler) → 본인 라벨만 (`labeled_by == user_id`)
- 외부인 → 404

`order=labeled_at desc` 고정.

**참고 코드:** [`backend/routers/labels.py:173`](../backend/routers/labels.py)

---

### `GET /clips/{id}/inference`

클립의 최신 VLM 추론 1건 (`behavior_logs.source='vlm'`). **owner 전용.**

**응답 200** — `InferenceOut` 또는 `null`
```json
{
  "id": "log-uuid",
  "clip_id": "clip-uuid",
  "action": "drinking",
  "source": "vlm",
  "confidence": 0.87,
  "reasoning": "혀를 그릇에 반복적으로 담그는 모션 관찰",
  "vlm_model": "gemini-2.5-flash",
  "created_at": "2026-05-08T10:30:05+09:00"
}
```

추론 없으면 `null` 반환 (404 아님 — UI 상 "VLM 추론 없음").

**응답 403** — labeler (비-owner) 가 호출. `detail`: `"only clip owner can view VLM inference"`.
**응답 404** — 외부인.

> **Why owner-only?** 라벨러가 VLM 결과 보면 자기 라벨이 그쪽으로 쏠림 (anchoring bias). GT 데이터 품질 보호.

**참고 코드:** [`backend/routers/labels.py:207`](../backend/routers/labels.py)

---

### `GET /labels/queue`

라벨러 큐 — 본인이 아직 라벨 안 한 클립을 최신순 (`started_at desc`) seek pagination.

**스코프**
- labeler 멤버: 모든 user_id 클립 (라벨러 = 전 클립 접근)
- 비-라벨러 owner: 본인 user_id 클립만

**필터 (큐 노출 조건)** — 두 조건 동시 만족만:
- `has_motion = true` — idle 세그먼트 (재생할 만한 모션 없음) 제외
- `r2_key NOT NULL` — 영상 재생 불가 클립 (업로드 실패 / 마이그레이션 이전) 제외
- 본인이 이미 라벨한 clip 은 `not.in` 으로 제외

**쿼리 파라미터**

| 이름 | 타입 | 기본 | 설명 |
|------|------|------|------|
| `limit` | int (1~200) | 50 | 페이지 크기 |
| `cursor` | ISO8601 | (첫 페이지) | 이전 응답의 `next_cursor` (`started_at`) |

**응답 200**
```json
{
  "items": [
    { "id": "clip-uuid", "user_id": "...", "started_at": "...", "r2_key": "...", "has_motion": true }
  ],
  "count": 1,
  "next_cursor": "2026-05-08T10:30:00+09:00",
  "has_more": false
}
```

각 `item` 은 `camera_clips` row (전체 컬럼).

**참고 코드:** [`backend/routers/labels.py:245`](../backend/routers/labels.py)

---

### `GET /labels/mine`

본인이 라벨한 클립 + 라벨 (`labeled_at desc`). 회고 흐름 — '내가 라벨한 거 다시 보고 수정' 진입점.

**queue 와 차이**
- 필터 없음 — `has_motion`/`r2_key` 무관 (이미 라벨한 거면 영상 재생 불가여도 보여줘야 — 구 클립 회고).
- cursor 가 `labeled_at` 기준 (`started_at` 아님).

**쿼리 파라미터**

| 이름 | 타입 | 기본 | 설명 |
|------|------|------|------|
| `limit` | int (1~200) | 50 | 페이지 크기 |
| `cursor` | ISO8601 | (첫 페이지) | 이전 응답의 `next_cursor` (`labeled_at`) |

**응답 200**
```json
{
  "items": [
    {
      "clip": { "id": "clip-uuid", "started_at": "...", "r2_key": "...", "has_motion": true },
      "label": {
        "id": "label-uuid",
        "clip_id": "clip-uuid",
        "labeled_by": "user-uuid",
        "action": "eating_paste",
        "lick_target": "dish",
        "labeled_at": "2026-05-08T18:30:00+09:00"
      }
    }
  ],
  "count": 1,
  "next_cursor": null,
  "has_more": false
}
```

**구현 노트** — orphan 라벨 (clip 이 삭제됐는데 라벨 남은 케이스) 은 응답에서 자동 스킵.

**참고 코드:** [`backend/routers/labels.py:317`](../backend/routers/labels.py)

---

## 본인 (`/me`)

input 이 `user_id` 자체 (path/body 없음) 인 본인 메타 endpoint. clips/labels/cameras 어디에도 안 맞는 것만 모음.

> **Why 별도 라우터?** GitHub API / Spotify Web API 와 동일 패턴 — 본인 메타는 `/me/*` 가 표준. `/clips` 나 `/labels` 에 끼우면 도메인 경계 흐려짐.

### `GET /me/is_labeler`

본인이 `labelers` 테이블 멤버인지.

**응답 200**
```json
{"is_labeler": true}
```

**용도** — Flutter 앱이 라벨링 웹 deep link 노출 여부 결정. `true` 인 owner-labeler 만 chip 옆에 "검수" 버튼 (`https://label.tera-ai.uk/labeling/{clipId}`).

**참고 코드:** [`backend/routers/me.py:28`](../backend/routers/me.py)

---

## 카메라 (`/cameras`)

### `POST /cameras/test-connection`

등록 전 RTSP 핸드쉐이크 검증.

**요청 바디**
```json
{
  "host": "192.168.0.12",
  "port": 554,
  "path": "stream2",
  "username": "tapo_user",
  "password": "tapo_pass"
}
```

**응답 200** (성공/실패 모두 200 + `success` 플래그)
```json
{
  "success": true,
  "detail": "RTSP 3초 내 첫 프레임 수신",
  "frame_captured": true,
  "elapsed_ms": 1245,
  "frame_size": [1280, 720]
}
```

**실패 예시**
```json
{
  "success": false,
  "detail": "3초 내 핸드쉐이크 실패 — 호스트/포트/크리덴셜 확인",
  "frame_captured": false,
  "elapsed_ms": 3021,
  "frame_size": null
}
```

**설계 결정** — 인증/타임아웃 실패도 500 이 아니라 200 + `success=false`. 클라이언트가 "서버 고장" 과 "RTSP 연결 실패" 를 구분할 수 있어야 함. 500 은 진짜 서버 크래시만.

---

### `POST /cameras`

카메라 등록. **자동 probe** (실패 시 400 거부, skip 옵션 없음).

**요청 바디**
```json
{
  "display_name": "거실",
  "host": "192.168.0.12",
  "port": 554,
  "path": "stream2",
  "username": "tapo_user",
  "password": "tapo_pass",
  "pet_id": "optional-pet-uuid"
}
```

**응답 201**
```json
{
  "id": "camera-uuid",
  "user_id": "user-uuid",
  "display_name": "거실",
  "host": "192.168.0.12",
  "port": 554,
  "path": "stream2",
  "username": "tapo_user",
  "pet_id": null,
  "is_active": true,
  "last_connected_at": null,
  "created_at": "2026-04-22T18:30:00+09:00",
  "updated_at": "2026-04-22T18:30:00+09:00"
}
```

**주의** — `password_encrypted` 응답 스키마에 **필드 자체 없음** → 자동 배제. 응답 본 사람이 서버가 평문을 잠깐 갖고 있단 사실을 알 수는 있지만 ciphertext 유출은 없음.

**응답 400** — probe 실패. `detail`: `"RTSP 연결 실패: 3초 내 핸드쉐이크 실패 — ..."`

**응답 409** — `(user_id, host, port, path)` 유니크 제약 위반. `detail`: `"이미 등록된 RTSP (host+port+path 동일)"`

**암호화** — 평문 비번을 Fernet 대칭키 (`CAMERA_SECRET_KEY`) 로 암호화 후 저장. 키 분실 시 모든 카메라 비번 복호화 불가 → 전부 재등록 필요.

---

### `GET /cameras`

본인 카메라 목록, 최근 생성 순.

**응답 200** — `CameraOut[]` ([`POST /cameras`](#post-cameras) 응답 스키마 배열).

---

### `GET /cameras/{id}`

단건.

**응답 200** — `CameraOut`.
**응답 404** — 미존재 or 타 유저.

---

### `PATCH /cameras/{id}`

부분 수정. **들어온 필드만** UPDATE (`exclude_unset`).

**요청 바디** (전부 선택, 최소 1개 필요)
```json
{
  "display_name": "거실 (낮)",
  "host": "192.168.0.13",
  "port": 554,
  "path": "stream1",
  "username": "new_user",
  "password": "new_pass",
  "pet_id": "pet-uuid",
  "is_active": false
}
```

**응답 200** — 업데이트된 `CameraOut`.

**응답 400** — 바디에 수정할 필드 0개.
**응답 404** — 미존재 or 타 유저.
**응답 409** — 변경 결과가 기존 카메라와 `(host, port, path)` 중복.

**비번 변경** — `password` 가 바디에 있으면 Fernet 재암호화 후 `password_encrypted` 컬럼만 UPDATE.

**워커 재시작 주의** — PATCH 만으로는 실행 중 `CaptureWorker` 가 자동 재시작하지 않음. `is_active`/`host`/`path` 변경 후에는 서버 재기동이 필요 (D3 설계 제약, 이후 개선 여지).

---

### `DELETE /cameras/{id}`

삭제. **하드 딜리트** (soft delete 아님).

**응답 200**
```json
{"id": "camera-uuid", "deleted": true}
```

**응답 404** — 미존재 or 타 유저.

**FK 주의** — `camera_clips.camera_id → cameras.id` 가 `ON DELETE CASCADE` 는 아님. 해당 카메라의 클립은 DB 에 남고, 파일도 디스크에 남음. 수동 정리 필요.

---

## Swagger UI

로컬 실행 중이면 자동 생성됨.

```
http://localhost:8000/docs      # Swagger UI
http://localhost:8000/redoc     # ReDoc
http://localhost:8000/openapi.json   # OpenAPI 3 스키마
```

**prod 배포 시** — 같은 경로가 `https://api.tera-ai.uk/docs` 로 노출됨. 외부 공개 상태에서 스키마 노출이 싫으면 `FastAPI(docs_url=None, redoc_url=None)` 로 끄기. 현재는 학습용으로 그대로 열어 둠.
