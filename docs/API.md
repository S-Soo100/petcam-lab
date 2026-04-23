# API 레퍼런스

> FastAPI 가 띄우는 HTTP 엔드포인트 전부. 로컬 `http://localhost:8000`, 배포 `https://api.tera-ai.uk`.

## 목차

- [인증](#인증)
- [에러 포맷](#에러-포맷)
- [엔드포인트 요약](#엔드포인트-요약)
- [루트 / 상태](#루트--상태)
  - [`GET /`](#get-)
  - [`GET /health`](#get-health)
  - [`GET /streams/{camera_id}/status`](#get-streamscamera_idstatus)
- [클립 (`/clips`)](#클립-clips)
  - [`GET /clips`](#get-clips)
  - [`GET /clips/{id}`](#get-clipsid)
  - [`GET /clips/{id}/file`](#get-clipsidfile)
  - [`GET /clips/{id}/thumbnail`](#get-clipsidthumbnail)
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
| `prod` | `Authorization: Bearer <JWT>` 필수, Supabase JWKS 로 서명 검증 | 배포 (Cloudflare Tunnel) |

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
| GET | `/health` | ❌ | 워커 상태 요약 |
| GET | `/streams/{camera_id}/status` | ❌ | 특정 워커 스냅샷 |
| GET | `/clips` | ✅ | 클립 목록 + 필터 + seek pagination |
| GET | `/clips/{id}` | ✅ | 클립 단건 메타 |
| GET | `/clips/{id}/file` | ✅ | mp4 스트리밍 (Range 지원) |
| GET | `/clips/{id}/thumbnail` | ✅ | 클립 썸네일 jpg |
| POST | `/cameras/test-connection` | ✅ | 등록 전 RTSP 핸드쉐이크 확인 |
| POST | `/cameras` | ✅ | 카메라 등록 (자동 probe) |
| GET | `/cameras` | ✅ | 본인 카메라 목록 |
| GET | `/cameras/{id}` | ✅ | 카메라 단건 |
| PATCH | `/cameras/{id}` | ✅ | 부분 수정 (비번 변경 시 재암호화) |
| DELETE | `/cameras/{id}` | ✅ | 카메라 삭제 |

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

캡처 워커 상태 요약. Flutter 앱이 "서버 점검 중" 분기할 때 참조.

**응답 200**
```json
{
  "status": "ok",
  "capture_workers": 2,
  "camera_ids": [
    "11111111-1111-1111-1111-111111111111",
    "22222222-2222-2222-2222-222222222222"
  ],
  "skipped_cameras": [],
  "startup_error": null
}
```

**필드**

| 필드 | 타입 | 설명 |
|------|------|------|
| `status` | string | 항상 `"ok"` (엔드포인트 자체 응답) |
| `capture_workers` | int | 기동된 워커 수 |
| `camera_ids` | UUID[] | 기동된 워커들의 camera_id |
| `skipped_cameras` | string[] | 비번 복호화 실패 등으로 skip 된 카메라 |
| `startup_error` | string \| null | Supabase 미설정, 카메라 0개 등 치명적이지 않은 startup 경고 |

**startup_error 예시**
- `"Supabase 미설정: 캡처 없이 기동 (SUPABASE_URL 환경변수가 비어있음)"`
- `"등록된 카메라 없음. POST /cameras 로 등록 필요"`
- `"CAMERA_SECRET_KEY 문제: CAMERA_SECRET_KEY 가 placeholder 인 채로 기동"`
- `"일부 카메라 skip: <uuid> (거실)"`

---

### `GET /streams/{camera_id}/status`

특정 카메라 워커의 실시간 상태 스냅샷.

**경로 파라미터**

| 이름 | 타입 | 설명 |
|------|------|------|
| `camera_id` | UUID | `cameras.id` |

**응답 200**
```json
{
  "state": "running",
  "frames_read": 7212,
  "frames_failed": 3,
  "reconnect_attempts": 1,
  "segments_written": 10,
  "measured_fps": 12.0,
  "declared_fps": 12.0,
  "last_error": null,
  "last_segment_path": "/Users/baek/petcam-lab/storage/clips/2026-04-22/<uuid>/183000_motion.mp4",
  "last_segment_written_at": "2026-04-22T18:31:00+09:00"
}
```

**응답 404**
```json
{"detail": "camera '<uuid>' not active (등록 안 됐거나 is_active=false 이거나 비번 복호화 실패)"}
```

**상태 머신 (`state`)**: `idle` → `connecting` → `running` → `reconnecting` ↔ `running` → `stopped`.
정확한 정의는 [`backend/capture.py`](../backend/capture.py) `CaptureState`.

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

### `GET /clips/{id}`

단건 메타.

**응답 200** — [`GET /clips`](#get-clips) `items[0]` 과 동일 스키마.
**응답 404** — 미존재 or 타 유저 것.

---

### `GET /clips/{id}/file`

mp4 바이너리 스트리밍. HTTP Range 헤더 지원.

**요청 헤더 (선택)**
```
Range: bytes=0-
Range: bytes=1048576-2097151
```

**응답 200** (Range 없음) — 전체 파일, `Content-Length`, `Accept-Ranges: bytes`.

**응답 206 Partial Content** (Range 있음)
```
Content-Range: bytes 1048576-2097151/5242880
Content-Length: 1048576
Accept-Ranges: bytes
```

**응답 410 Gone** — DB 행은 있는데 디스크에 파일이 없음 (수동 삭제, 디스크 이슈).
**응답 416 Range Not Satisfiable** — Range 포맷 오류 or 파일 크기 초과.

**청크 크기** 256KB. 너무 작으면 첫 바이트 빨라도 네트워크 비효율, 크면 시크 응답성 저하. 비디오 스트리밍 표준(64KB~1MB) 중간값.

---

### `GET /clips/{id}/thumbnail`

클립 썸네일 jpg (Stage D4).

**응답 200** — `image/jpeg`, `FileResponse` 가 내부에서 `Content-Length` 자동 설정.

**응답 404 3분기** (전부 같은 코드, `detail` 로 원인 구분)
- `"clip '<uuid>' not found"` — DB 행 없음
- `"thumbnail not generated for clip '<uuid>'"` — Stage D4 이전 생성 클립이라 `thumbnail_path` NULL
- `"thumbnail file missing on disk: <path>"` — 디스크에서 파일이 사라짐

**생성 시점** — 세그먼트 종료 시 첫 유효 프레임을 OpenCV 로 `cv2.imwrite(quality=85)`. 320x240 내외.

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
