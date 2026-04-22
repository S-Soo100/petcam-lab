# Stage D2 — cameras 테이블 + CRUD API + 테스트 연결

> Stage D 의 두 번째 서브. `camera_clips.camera_id` 가 `.env` 하드코딩 한 값인 현 구조를 **유저 소유 카메라 레코드** 로 올리고, 앱에서 등록·수정·삭제·테스트 가능한 CRUD API 를 제공. 비번은 D1 Fernet 으로 암호화.

**상태:** ✅ 완료 (2026-04-22)
**작성:** 2026-04-22
**상위 로드맵:** [stage-d-roadmap.md](stage-d-roadmap.md)
**연관 SOT:** `../../tera-ai-product-master/docs/specs/petcam-backend-dev.md` — Stage D 섹션
**선행 조건:** D1 완료 ✅ (`get_current_user_id`, `encrypt_password` 필요)

---

## 1. 목적

- **사용자 가치**: 앱에서 카메라 직접 추가·관리 가능. 현재는 `.env` 수정하고 서버 재시작해야 카메라 바뀜. CRUD API 로 올리면 Flutter UI 에서 필드 입력 → 즉시 등록.
- **즉시 피드백**: "테스트 연결" 엔드포인트로 등록 전에 RTSP 핸드쉐이크 검증 → 오타·방화벽·권한 오류를 등록 버튼 누르기 전에 잡음.
- **보안**: 비번은 Fernet 으로만 저장, API 응답에서 완전 배제 → 유출 경로 차단.
- **학습 목표**:
  - Supabase RLS INSERT 정책을 **일부러 안 만드는** 패턴 (service_role 전담) 과 그 이유
  - Pydantic v2 의 `model_dump(exclude=...)` 로 비밀 필드 응답 배제
  - FastAPI PATCH 부분 업데이트 (Optional 필드 + `exclude_unset=True`)
  - `cv2.VideoCapture` 타임아웃 제어 (`CAP_PROP_OPEN_TIMEOUT_MSEC`) 와 단발성 검증 로직

---

## 2. 스코프

### In (이번 스펙에서 한다)

#### 데이터 모델
- `cameras` 테이블 신설 (로드맵 결정 5 기반)
  - RLS: SELECT/UPDATE/DELETE 는 본인 행만 (`auth.uid() = user_id`)
  - INSERT 는 **service_role 전담** (백엔드가 테스트 연결 검증 후 insert)
  - 유니크 제약: `(user_id, host, port, path)` — 같은 유저가 완전 동일 RTSP 를 중복 등록 방지
  - `updated_at` 자동 갱신 트리거 (`moddatetime` extension)
- 마이그레이션은 **Supabase MCP `apply_migration`** 로 적용 (Stage C 와 동일 패턴)

#### API 엔드포인트 6 종
- `POST /cameras/test-connection` — RTSP 핸드쉐이크 검증 (등록 전 호출 가능)
- `POST /cameras` — 카메라 등록 (비번 평문 입력 → 서버가 암호화 저장)
- `GET /cameras` — 목록 조회
- `GET /cameras/{id}` — 단건 조회
- `PATCH /cameras/{id}` — 부분 수정 (비번 포함 가능, 들어오면 재암호화)
- `DELETE /cameras/{id}` — 삭제

#### 보안
- 응답 `CameraOut` 스키마에 `password_encrypted` **절대 포함 금지**
- 로깅 시 RTSP URL 마스킹 (`rtsp://user:***@host`)
- `test-connection` 도 성공 시 비번 로그 금지

#### 테스트
- `tests/test_cameras_api.py` 신설
  - FastAPI TestClient + FakeSupabase (Stage C 패턴 재사용)
  - CRUD 각 endpoint, 필터링, 권한 격리 (다른 user_id 의 카메라 접근 불가)
  - PATCH 부분 업데이트, 비번 변경 시 재암호화
  - `test-connection` 은 cv2 mock (실 RTSP 의존성 X, donts/python#13)

### Out (이번 스펙에서 **안 한다**)

- **`camera_clips.camera_id` FK 마이그레이션** — D3. 기존 문자열 `camera_id` 는 당분간 그대로 두고, D3 에서 UUID 전환 + FK 추가.
- **다중 캡처 워커** — D3. 지금은 `.env` 의 단일 `CAMERA_ID` 가 여전히 캡처 주체. D2 는 "DB 에 등록만" 까지.
- **썸네일** — D4.
- **Cloudflare Tunnel / 외부 접속** — D5.
- **카메라 삭제 시 영상 파일 cleanup** — Stage E 이후. D2 는 DB row 만 삭제.
- **카메라 헬스 체크 주기 polling** — MVP 엔 `last_connected_at` 을 수동 갱신만 (등록 시·캡처 시작 시).
- **Rate limiting** — 별도 스펙.
- **Flutter 등록 UI (F3)** — Flutter 레포에서.

### 경계 사유

- D2 에 `camera_clips` FK 까지 넣으면 "등록" 과 "캡처 워커 다중화" 디버깅이 섞임. 등록 먼저 단단히.
- 기존 Stage A~C 의 캡처 워커는 `.env` 기반으로 **그대로 동작 유지** 가 원칙. D3 에서 DB 기반으로 전환.

---

## 3. 완료 조건

### DB 마이그레이션
- [x] `cameras` 테이블 생성 (`apply_migration` 로) — migration `stage_d2_cameras_table`
- [x] RLS 활성화 + SELECT/UPDATE/DELETE 정책 3 개 적용 (INSERT 정책 고의 생략)
- [x] 유니크 제약 `(user_id, host, port, path)` — `idx_cameras_user_host_unique`
- [x] `updated_at` 자동 갱신 트리거 동작 (`cameras_updated_at`)
- [x] `moddatetime` extension 활성화 (Supabase 기본 제공)
- [x] `list_tables` MCP 로 컬럼·정책·인덱스 재확인

### 코드
- [x] `backend/routers/cameras.py` 신설
  - [x] Pydantic 모델: `CameraCreate`, `CameraUpdate`, `CameraOut`, `TestConnectionRequest`, `TestConnectionResponse`
  - [x] 6 개 엔드포인트 구현
  - [x] 비번 암호화: `encrypt_password` 사용 (D1)
  - [x] 응답 직렬화 시 `password_encrypted` 배제 (스키마 자체에 필드 없음)
- [x] `backend/rtsp_probe.py` 신설 — **services/ 디렉토리 안 만듦, flat 유지 (구조 보존)**
  - [x] `probe_rtsp(host, port, path, username, password) -> ProbeResult` 동기 함수
  - [x] `cv2.VideoCapture` 타임아웃 3 초, 첫 프레임 수신 시도
  - [x] 로깅 시 비번 마스킹 (`mask_rtsp_url`)
- [x] `backend/main.py` 에 router include
- [x] 로깅 유틸: `mask_rtsp_url` 함수 (rtsp_probe.py 내)

### 테스트
- [x] `tests/test_cameras_api.py` 신설 — 25 케이스
  - [x] POST 성공 + 비번 응답 배제 확인
  - [x] POST 중복 (user_id+host+port+path) → 409
  - [x] GET list 본인 것만 + 정렬
  - [x] GET single 다른 유저 것 → 404 (service_role + 코드 필터)
  - [x] PATCH 부분 수정 (display_name 만)
  - [x] PATCH 비번 변경 → 재암호화 확인
  - [x] PATCH 빈 body → 400, 중복 결과 → 409
  - [x] DELETE 성공 + DB 실제 제거 확인
  - [x] test-connection 성공 / 실패 / 422 (probe mock via monkeypatch)
  - [x] 회귀 방지: 전 엔드포인트 password_encrypted 누설 없음
- [x] `tests/test_rtsp_probe.py` 신설 — probe 함수 + URL 빌더 + 마스킹 13 케이스 (cv2 mock)
- [x] `uv run pytest` 전체 통과 — 110 passed

### 검증 (수동 — 사용자가 수행)
- [ ] `/docs` 에서 6 개 엔드포인트 시각 확인
- [ ] Dev 모드 curl POST `/cameras/test-connection` with Tapo C200 → success: true
- [ ] 잘못된 비번으로 호출 → success: false + detail
- [ ] POST `/cameras` 후 GET `/cameras` 에 새 카메라 보임
- [ ] Supabase SQL Editor 로 `cameras` 행 확인 → `password_encrypted` 가 `gAAAA...` Fernet 토큰

### 문서
- [x] 미해결 결정 2 개 확정 (설계 메모 섹션 갱신)
- [ ] README 에 `POST /cameras/test-connection` + `/cameras` CRUD 예시 추가
- [ ] `tera-ai-flutter/docs/supabase-schema.md` 에 `cameras` 섹션 추가 (16 번째 테이블)
- [x] 로드맵 D2 상태 → ✅ 완료
- [x] `specs/README.md` D2 row → ✅

---

## 4. 설계 메모

### DDL 초안 (마이그레이션 전 리뷰용)

```sql
-- extension (Supabase 기본 있지만 확인)
CREATE EXTENSION IF NOT EXISTS moddatetime SCHEMA extensions;

-- 테이블
CREATE TABLE cameras (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  pet_id UUID REFERENCES pets(id) ON DELETE SET NULL,
  display_name TEXT NOT NULL,
  host TEXT NOT NULL,
  port INT NOT NULL DEFAULT 554,
  path TEXT NOT NULL DEFAULT 'stream1',
  username TEXT NOT NULL,
  password_encrypted TEXT NOT NULL,  -- Fernet 토큰 (D1 str I/O 결정)
  is_active BOOLEAN NOT NULL DEFAULT true,
  last_connected_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 인덱스
CREATE INDEX idx_cameras_user_id ON cameras(user_id);
CREATE INDEX idx_cameras_pet_id ON cameras(pet_id) WHERE pet_id IS NOT NULL;
CREATE UNIQUE INDEX idx_cameras_user_host_unique
  ON cameras(user_id, host, port, path);

-- updated_at 자동 갱신
CREATE TRIGGER cameras_updated_at
  BEFORE UPDATE ON cameras
  FOR EACH ROW
  EXECUTE FUNCTION extensions.moddatetime(updated_at);

-- RLS
ALTER TABLE cameras ENABLE ROW LEVEL SECURITY;

CREATE POLICY "User reads own cameras"
  ON cameras FOR SELECT
  USING (auth.uid() = user_id);

CREATE POLICY "User updates own cameras"
  ON cameras FOR UPDATE
  USING (auth.uid() = user_id);

CREATE POLICY "User deletes own cameras"
  ON cameras FOR DELETE
  USING (auth.uid() = user_id);

-- INSERT 정책 생략 = anon/authenticated 직접 INSERT 불가
-- service_role 만 INSERT (백엔드가 test-connection 검증 후 insert)
```

### 왜 INSERT RLS 정책을 안 만드나?

- 프론트에서 Supabase 클라이언트로 바로 `cameras.insert(...)` 하면 **테스트 연결 검증을 우회** 가능 → 유효하지 않은 카메라 행 생김
- 백엔드 경유 (`POST /cameras`) 로 강제하면:
  1. 등록 전에 RTSP 핸드쉐이크 검증
  2. 비번을 평문으로 받아서 서버에서 Fernet 암호화 (클라가 암호화 키 몰라도 됨)
  3. 비즈니스 로직 (중복 체크 등) 을 서버 한 곳에서
- RLS INSERT 안 만들면 anon/authenticated 역할은 INSERT 차단 → 오직 service_role (백엔드) 만 가능

### API 설계 포인트

#### `POST /cameras/test-connection`

```json
// Request
{
  "host": "192.168.0.100",
  "port": 554,
  "path": "stream1",
  "username": "admin",
  "password": "plaintext"
}

// Response 200
{
  "success": true,
  "detail": "첫 프레임 수신 성공",
  "frame_captured": true,
  "elapsed_ms": 847,
  "frame_size": [1280, 720]
}

// Response 200 (실패도 200 — 검증 자체는 성공)
{
  "success": false,
  "detail": "RTSP 연결 실패: 인증 거부",
  "frame_captured": false,
  "elapsed_ms": 3021,
  "frame_size": null
}
```

**왜 실패도 200?** `test-connection` 의 의도는 "연결 시도해봄" 이지 "연결 성공만 정답" 이 아님. 인증 오류·타임아웃도 유효한 응답. 500 은 진짜 서버 버그 (cv2 예상 못 한 크래시) 만.

#### `POST /cameras` (등록)

- body 에 `password` (평문) 받아서 `encrypt_password()` 로 암호화 후 INSERT
- 중복 (user_id+host+port+path) 시 Postgres unique violation → 409 Conflict 매핑
- 응답은 `CameraOut` (비번 배제)

**결정 — 등록 시 test-connection 자동 호출 (skip 옵션 없음)**
- 구현: `POST /cameras` 는 **무조건 probe_rtsp** → 실패 시 400 으로 등록 거부
- 이유: MVP 엔 일관성·간단함 우선. 등록 후 바로 "연결 끊김" 같은 UX 실패를 프론트가 처리하느니 서버가 사전 차단
- 비용: 등록당 cv2 3 초 블로킹 한 번 — 허용 범위
- 나중에 `skip_probe` 필요하면 추가 가능 (YAGNI)

#### `PATCH /cameras/{id}`

- body 의 모든 필드 Optional, `exclude_unset=True` 로 들어온 필드만 UPDATE
- `password` 가 들어오면 재암호화 후 `password_encrypted` 에 저장
- `host/port/path` 변경 시 다시 probe 해야 안전? → MVP 엔 생략, 실패는 다음 캡처 시도 시 드러남

### 비밀번호 응답 배제 구현

Pydantic v2 패턴:
```python
class CameraOut(BaseModel):
    id: UUID
    user_id: UUID
    pet_id: UUID | None
    display_name: str
    host: str
    port: int
    path: str
    username: str
    is_active: bool
    last_connected_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # password_encrypted 필드 자체가 없음 → 자동 배제

    model_config = ConfigDict(extra="ignore")  # Supabase row 의 여분 필드 무시
```

row 에서 Pydantic 객체로 변환 시 `CameraOut.model_validate(row)` 하면 `password_encrypted` 는 **그냥 없는 필드** 라 응답에 못 실음.

### 로깅 마스킹

```python
def mask_rtsp_url(url: str) -> str:
    """rtsp://admin:password@host/path → rtsp://admin:***@host/path"""
    return re.sub(r"(rtsp://[^:]+:)[^@]+(@)", r"\1***\2", url)
```

`logger.info(f"probing {mask_rtsp_url(url)}")` 식으로. test-connection 실패 detail 에 원본 URL 넣지 말 것.

### 테스트 전략

Stage C 의 FakeSupabase 패턴 재사용:
- `.table("cameras").insert(row).execute()` 를 in-memory dict 로
- `.eq("user_id", uid)` 필터 로직도 그대로 흉내
- unique 제약은 `if (user_id, host, port, path) in existing: raise UniqueViolation` 로 흉내

cv2 mock:
```python
@pytest.fixture
def mock_cv2_success(monkeypatch):
    fake_cap = MagicMock()
    fake_cap.isOpened.return_value = True
    fake_cap.read.return_value = (True, np.zeros((720, 1280, 3), dtype=np.uint8))
    monkeypatch.setattr("cv2.VideoCapture", lambda *a, **kw: fake_cap)

@pytest.fixture
def mock_cv2_timeout(monkeypatch):
    fake_cap = MagicMock()
    fake_cap.isOpened.return_value = False
    monkeypatch.setattr("cv2.VideoCapture", lambda *a, **kw: fake_cap)
```

### 리스크 / 미해결 질문

- [x] `moddatetime` extension — Supabase 기본 비활성이었음. migration 에서 `CREATE EXTENSION IF NOT EXISTS moddatetime SCHEMA extensions` 로 명시 활성화 완료.
- [x] RTSP probe 블로킹 (3초) → FastAPI 핸들러 **동기 def** 로 선언 (donts/python#4 준수).
- [x] `host` 포맷 검증 — MVP 엔 `min_length=1` 만. IP/호스트명 모두 허용. 형식 검증은 probe 가 실패로 잡음.
- [x] 등록 시 자동 probe 강제 — skip 옵션 없음 (YAGNI). 위 "등록 시 자동 호출" 결정 참조.
- [ ] 비번 변경 후 기존 캡처 워커는 어떻게 알지? → D3 의 워커 재시작 로직. D2 는 DB 만 갱신.
- [x] 중복 등록 다른 유저 간: 유니크가 `(user_id, host, port, path)` 라 유저별 독립 — 공용 카메라 시나리오 허용.

---

## 5. 학습 노트

### 개념 1 — RLS INSERT 정책 "없음" 패턴

- 기존 멘탈 모델: "모든 작업에 RLS 정책 만든다"
- 이번: **INSERT 는 정책 없음** → anon/authenticated 가 insert 시도하면 Postgres 가 "no policy matches" 로 거부
- service_role 은 RLS 바이패스라 백엔드만 INSERT 가능
- **이점**: 프론트가 DB 직결로 insert 해서 비즈니스 로직 (test-connection, 암호화) 을 우회하는 경로 자체를 막음

### 개념 2 — Pydantic v2 `exclude_unset`

```python
@router.patch("/{id}")
def update_camera(id: UUID, body: CameraUpdate, ...):
    updates = body.model_dump(exclude_unset=True)  # 들어온 필드만
    sb.table("cameras").update(updates).eq("id", id).execute()
```

- `exclude_unset=True` = "클라가 명시적으로 보낸 필드만 dict 로"
- Optional 필드가 디폴트 `None` 인데 클라가 아예 안 보낸 경우와 `null` 로 보낸 경우 구분
- TS/Node 비유: Prisma `update` 의 `data` 에 `undefined` 필드 넣으면 "변경 안 함" 과 같은 동작

### 개념 3 — `cv2.VideoCapture` 타임아웃

```python
cap = cv2.VideoCapture(url)
cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 3000)  # 연결 3초
cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 3000)  # 프레임 읽기 3초
```

- 미설정 시 기본 30초~무한 대기 → 사용자가 "테스트 연결" 버튼 누르고 너무 오래 기다림
- 3초로 짧게 → 실패해도 빠른 피드백
- **주의:** `CAP_PROP_OPEN_TIMEOUT_MSEC` 는 OpenCV 4.5+ 에서만 확실. 4.5 미만은 환경변수 `OPENCV_FFMPEG_CAPTURE_OPTIONS=stimeout;3000000` 써야

### 개념 4 — Fernet 토큰은 str, DB 는 TEXT

- D1 에서 `encrypt_password(str) -> str` 로 str I/O 결정 (바이트 vs 텍스트 고민 끝)
- DB 컬럼도 `TEXT` (`BYTEA` 아님) → Fernet 토큰이 이미 url-safe base64 라 TEXT 로도 데이터 손실 없음
- 로드맵 결정 5 의 `password_encrypted BYTEA` 에서 변경됨 (D1 구현 결과 반영)

### TS/Node 비유 정리

- `password_encrypted` 제외 = NestJS `@Exclude()` 데코레이터 + `ClassSerializerInterceptor`
- `exclude_unset` PATCH = Partial<T> 타입 + undefined 필드 자동 drop
- `service_role` = Firestore Admin SDK (보안 규칙 바이패스)
- RLS = Firestore security rules 의 Postgres 버전

---

## 6. 참고

- 상위 로드맵: [stage-d-roadmap.md](stage-d-roadmap.md) — 결정 3·4·5 근거
- 선행 스펙: [stage-d1-auth-crypto.md](stage-d1-auth-crypto.md) — `encrypt_password` 인터페이스
- 참고 패턴: [stage-c-db-api.md](stage-c-db-api.md) — FakeSupabase 테스트, RLS 적용, `apply_migration` 플로우
- Pydantic v2 `exclude_unset`: https://docs.pydantic.dev/latest/concepts/serialization/#modelmodel_dump
- Supabase RLS: https://supabase.com/docs/guides/auth/row-level-security
- cv2 VideoCapture 타임아웃: https://docs.opencv.org/4.x/d8/dfe/classcv_1_1VideoCapture.html
- SOT 스펙: `../../tera-ai-product-master/docs/specs/petcam-backend-dev.md`
