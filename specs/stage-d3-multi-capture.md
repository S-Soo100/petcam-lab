# Stage D3 — 다중 캡처 워커 + `camera_clips` FK 마이그레이션

> 카메라 1대 → N대로 확장. `.env RTSP_URL` 단일 워커 방식을 폐기하고, DB 의 `cameras` 테이블에서 `is_active=true` 행을 전부 읽어 워커 N개를 동시에 돌린다. 클립 메타 테이블도 `camera_id TEXT` → `camera_id UUID REFERENCES cameras(id)` 로 바꿔 정식 FK 연결.

**상태:** ✅ 완료 (2026-04-22)
**작성:** 2026-04-22
**연관 SOT:** `../../tera-ai-product-master/docs/specs/petcam-backend-dev.md` — Stage D 다중 카메라
**연관 로드맵:** [`stage-d-roadmap.md`](stage-d-roadmap.md) — 결정 5 (camera_clips FK 마이그레이션)

## 1. 목적

- **사용자 가치**: 한 집에 Tapo 여러 대 운영. 현재는 `.env RTSP_URL` 1개만 받아 워커 1개 → 실제 물리 설치 완료된 cam2 가 무의미.
- **학습 목표**: FastAPI lifespan 에서 N개 백그라운드 스레드 관리, PostgreSQL `ADD COLUMN FK` + backfill + `NOT NULL` 3단계 마이그레이션, Fernet 복호화 파이프라인 실전 조립.
- **구조 정비**: Stage D1/D2 가 만든 `cameras` 테이블 + Fernet 암호화 레이어가 이제 실제로 "캡처 파이프라인의 입구" 역할을 함. 지금까진 등록만 되고 녹화엔 안 쓰이는 상태 → D3 에서 이어붙임.

## 2. 스코프

### In (이번 스펙에서 한다)

- **사전 준비**: cam1, cam2 를 `cameras` 테이블에 `POST /cameras` 로 등록 (UUID 확보)
- **DB 마이그레이션 (3단계)**:
  1. `camera_clips.camera_uuid UUID REFERENCES cameras(id) ON DELETE CASCADE` 추가 (nullable)
  2. 기존 72행 backfill — `camera_id='cam-1'` → cam1 UUID
  3. `camera_uuid` NOT NULL + 기존 `camera_id TEXT` DROP + `camera_uuid` → `camera_id` RENAME
- **`backend/main.py` lifespan 재작성**:
  - `.env` 의 `RTSP_URL` / `CAMERA_ID` **제거** (정식 경로는 DB)
  - 서버 시작 시 `cameras` 테이블 SELECT → 각 row 마다 `CaptureWorker` 1개
  - `app.state.capture_workers: dict[camera_id_uuid, CaptureWorker]`
  - 각 워커의 `rtsp_url` = host/port/path/username + Fernet.decrypt(password_encrypted) 로 동적 조립
- **`backend/capture.py` 수정**: `CaptureWorker.camera_id` 의미가 "문자열 라벨" → "cameras.id UUID 문자열" 로 변경. 나머지 로직 그대로.
- **`/streams/{camera_id}/status`** UUID 기반으로 동작 (기존 "cam-1" → UUID 문자열)
- **`clip_recorder`**: payload 의 `camera_id` 가 UUID 문자열이라 변경 없음 (타입만 달라짐)
- **`.env.example`** 업데이트: `RTSP_URL` / `CAMERA_ID` 제거 + 설명
- **테스트**:
  - `test_main_lifespan.py` 추가 — FakeSupabase + CaptureWorker mock 으로 "cameras 행 2개 → 워커 2개 생성 + dict 에 등록" 검증
  - 기존 테스트 (`test_capture.py`, `test_clips_api.py`, `test_cameras_api.py`) 회귀 없이 통과
- **실기 검증**: cam1 + cam2 동시에 5분 녹화 → DB 에 각 카메라 UUID 로 row 생성 확인 + `/clips?camera_id=<uuid>` 필터링

### Out (이번 스펙에서 **안 한다**)

- **동적 워커 추가/제거** — `POST /cameras` 후 즉시 반영 금지. 서버 재시작 필요. 다음 이터레이션 과제.
- **워커 장애 감지 / 자동 재시작** — 현재 CaptureWorker 가 RTSP 재연결 로직 보유. 워커 프로세스 자체 죽음은 기존처럼 로그만.
- **카메라 삭제 시 영상 파일 cleanup** — Stage E retention job.
- **storage 디렉토리 구조 변경** — 기존 `storage/clips/YYYY-MM-DD/cam-1/*.mp4` 파일 건드리지 않음. 새 클립만 `storage/clips/YYYY-MM-DD/{UUID}/`. 기존 DB row 는 `file_path` 그대로 유지 (`/clips/{id}/file` 재생 가능).
- **`/streams` 전체 목록 엔드포인트** — YAGNI. 필요 시 별도 추가.
- **test-connection 이 cameras 테이블 저장까지 자동** — 분리 유지 (D2 결정).
- **Flutter 앱 업데이트** — 모델 필드 타입 변경 공지만. 실제 수정은 Flutter 세션에서.

> **스코프 변경은 합의 후에만.**

## 3. 완료 조건

- [x] cam1, cam2 둘 다 `cameras` 테이블에 등록 (`POST /cameras`) — UUID 2개 기록
  - cam1: `1c1aea9f-31dc-4801-a8f5-ee74d7f2e3b6` (192.168.219.106, pet 연결됨)
  - cam2: `3a6cffbf-be83-4c77-9fa7-4fcc517c74a6` (192.168.219.107, pet_id=NULL)
- [x] Supabase 마이그레이션 3단계 성공 — `information_schema.columns` 로 `camera_clips.camera_id UUID NOT NULL` 재확인 + FK 제약 확인
- [x] 기존 106개 `camera_clips` 행의 `camera_id` 가 cam1 UUID 로 backfill 됨 (Supabase Studio 확인)
- [x] `backend/main.py` 리팩터링: 다중 워커 부트스트랩 + `app.state.capture_workers: dict`
- [x] `.env.example` + `README.md` 업데이트 — `RTSP_URL` / `CAMERA_ID` 제거 + "카메라는 `POST /cameras` 로 등록" 안내
- [x] `/streams/{camera_id}/status` UUID 기반 동작 (curl 로 cam1 + cam2 각각 확인)
- [x] `tests/test_main_lifespan.py` 신규 — 다중 워커 부트스트랩 + dict 등록 검증 (4 테스트 추가)
- [x] `pytest -q` 전수 통과 — 회귀 없음 (126 tests passed)
- [x] 실기 검증: cam1 + cam2 동시 녹화 → `/health` `capture_workers: 2` + 각 카메라 status 1280×720 @ 13.6fps 확인 → DB 에 각 카메라 UUID 별 clip row 생성 + `storage/clips/YYYY-MM-DD/{cam1_uuid}/` + `{cam2_uuid}/` 디렉토리 생성
- [x] `/clips?camera_id=<cam1_uuid>` 필터링 정상 (cam1 행만 반환)
- [x] `docs/learning/flutter-handoff.md` 의 Stage D3 예정 섹션을 "완료" 로 갱신 + 필드 타입 변경 명시
- [x] `specs/README.md` + `stage-d-roadmap.md` 상태 갱신 (D3 → ✅)
- [x] `.claude/donts-audit.md` 한 줄 추가

## 4. 설계 메모

### 4.1 마이그레이션 전략 — "Add → Backfill → Enforce → Rename"

```sql
-- Step 1: 새 컬럼 (nullable, FK)
ALTER TABLE camera_clips
  ADD COLUMN camera_uuid UUID REFERENCES cameras(id) ON DELETE CASCADE;

-- Step 2: 기존 행 채우기 (cam1 UUID 로)
UPDATE camera_clips
  SET camera_uuid = '<cam1 uuid>'
  WHERE camera_id = 'cam-1';

-- Step 3: NOT NULL 강제 + 기존 컬럼 제거 + rename
ALTER TABLE camera_clips ALTER COLUMN camera_uuid SET NOT NULL;
ALTER TABLE camera_clips DROP COLUMN camera_id;
ALTER TABLE camera_clips RENAME COLUMN camera_uuid TO camera_id;

-- Step 4: 인덱스 (camera_id + started_at desc — /clips?camera_id= 쿼리용)
CREATE INDEX idx_camera_clips_camera_id_started_at
  ON camera_clips (camera_id, started_at DESC);
```

**왜 이 순서?**
- 한 번에 `ALTER COLUMN ... TYPE UUID` 는 UPDATE 중 실패 시 rollback 부담 큼.
- "nullable 새 컬럼 → backfill → NOT NULL" 이 Postgres 실전 표준 (Stripe/Shopify 마이그레이션 가이드 동일).
- 기존 TEXT `camera_id` DROP 은 코드 레벨에서 더 이상 참조 안 되는 것 확인 후.

### 4.2 `backend/main.py` lifespan 구조

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    load_dotenv(...)
    app.state.capture_workers = {}
    app.state.pending_queue = None
    app.state.startup_error = None

    # cameras 로드 (DEV_USER_ID 기준, prod 는 추후)
    sb = get_supabase_client()
    user_id = os.getenv("DEV_USER_ID")
    rows = sb.table("cameras").select("*").eq("user_id", user_id).eq("is_active", True).execute().data

    # pending queue + flush task 공용 (1개면 충분)
    pending_queue = PendingInsertQueue(REPO_ROOT / "storage" / "pending_inserts.jsonl")
    flush_task = asyncio.create_task(_periodic_flush(...))

    for row in rows:
        rtsp_url = build_rtsp_url(row)  # Fernet decrypt 포함
        worker = CaptureWorker(
            camera_id=row["id"],  # UUID 문자열
            rtsp_url=rtsp_url,
            storage_dir=REPO_ROOT / "storage" / "clips",
            ...
            clip_recorder=make_clip_recorder(sb, pending_queue, user_id, row["pet_id"]),
        )
        worker.start()
        app.state.capture_workers[row["id"]] = worker

    try:
        yield
    finally:
        for w in app.state.capture_workers.values():
            w.stop()
        flush_task.cancel()
        ...
```

**핵심 변경점:**
- `app.state.capture_worker` (단수) → `app.state.capture_workers: dict` (복수)
- cam 별 `pet_id` 가 다를 수 있어 `clip_recorder` 도 워커 별 생성 (`dev_pet_id` → `row["pet_id"]`)
- `pending_queue` 는 1개 공용 (파일 락 경합 없음 — append only)

### 4.3 `build_rtsp_url` 헬퍼 (신규)

```python
def build_rtsp_url(camera_row: dict) -> str:
    password = decrypt_password(camera_row["password_encrypted"])
    # 비번 특수문자 URL 인코딩 (D2 에서 rtsp_probe.py 동일 로직 있음 — 재사용)
    user = quote(camera_row["username"], safe="")
    pwd = quote(password, safe="")
    return f"rtsp://{user}:{pwd}@{camera_row['host']}:{camera_row['port']}/{camera_row['path']}"
```

→ `backend/rtsp_probe.py` 의 `build_rtsp_url` 을 재사용. password 만 복호화 붙이면 됨.

### 4.4 `/streams/{camera_id}/status` 변경

- UUID 문자열로 들어오면 `app.state.capture_workers.get(camera_id)` 로 조회
- 없으면 404 (기존과 동일)
- worker.snapshot() 은 `camera_id` 필드가 UUID 로 바뀌는 것만 차이

### 4.5 Flutter 영향 (문서 갱신만)

- `Clip.cameraId` 타입은 Dart 에선 `String` 유지 (UUID 도 String). **런타임 영향 없음.**
- 필터링 URL 은 `?camera_id=cam-1` → `?camera_id=<uuid>` — 앱이 `cameras` 테이블에서 받은 UUID 그대로 넘기면 됨.
- 기존 하드코딩 "cam-1" 참조가 있으면 제거 (현재 Flutter 코드 없으니 해당 없음).

### 4.6 기존 구조와의 관계

- `CaptureWorker` 자체는 재사용. `camera_id` 필드 의미만 재해석.
- `backend/motion.py`, `backend/capture.py` 내부 로직 건드리지 않음.
- `backend/clip_recorder.py` 변경 없음 (payload 의 `camera_id` 가 UUID 문자열로 들어와도 DB 컬럼 UUID 에 그대로 insert).
- `backend/routers/clips.py` 변경 없음 (UUID 도 문자열 비교).

### 4.7 리스크 / 미해결 질문

- **cam2 녹음 실패 시** cam1 은 계속 녹화돼야 함 → 워커 독립 스레드라 자동 격리.
- **기존 `storage/clips/cam-1/` 디렉토리**: DB `file_path` 절대 경로라 그대로 두면 재생 OK. 새 클립만 UUID 디렉토리.
- **Fernet 복호화 실패 (키 변경 등)**: 해당 워커만 skip + `startup_error` 에 기록? → 현재 제안. 서버 자체는 뜨게.
- **동일 네트워크에서 2대 동시 캡처 시 대역폭**: Tapo 720p ~ 2 Mbps × 2 = 4 Mbps. 가정용 Wi-Fi 충분.
- **테스트 coverage**: lifespan async 컨텍스트 테스트는 `TestClient` 가 자동 lifespan 트리거하는 것 활용. 상세 검증은 실기 위주.
- **마이그레이션 롤백 전략**: `camera_id TEXT` 컬럼 DROP 후 되돌리기 어려움 → backup 필수 (Supabase 자동 백업 있음, 재확인).

## 5. 학습 노트

- **Postgres ADD COLUMN + FK 마이그레이션**: Stripe "safe migrations" 원칙. `NOT NULL` 은 항상 backfill 이후에만. 단일 트랜잭션보다 3~4 트랜잭션 분리가 원복 쉬움.
- **FastAPI lifespan 의 background task 관리**: `asyncio.create_task` 로 띄우고 `finally` 에서 `cancel()`. 스레드 기반 `CaptureWorker.stop()` 과 공존 가능 (이벤트 루프 + daemon thread).
- **dict 기반 worker 레지스트리**: Node 의 Express 에서 `app.locals.workers = {}` 와 같음. FastAPI 는 `app.state.workers` 가 표준.
- **`quote()` URL 인코딩**: Python `urllib.parse.quote(value, safe="")` — JS 의 `encodeURIComponent` 대응. 비번 `@`, `:`, `/` 포함 시 필수.
- **`ON DELETE CASCADE`**: 카메라 삭제 시 클립 row 자동 삭제. 파일 cleanup 은 별도 (Stage E).

## 6. 참고

- 로드맵: [`stage-d-roadmap.md`](stage-d-roadmap.md) 결정 5 (camera_clips FK), 7 (본인 재택 다중 설치)
- Stage D1: [`stage-d1-auth-crypto.md`](stage-d1-auth-crypto.md) — `decrypt_password`
- Stage D2: [`stage-d2-cameras-api.md`](stage-d2-cameras-api.md) — `build_rtsp_url` 재사용, cameras 테이블 DDL
- Stripe Safe Migrations: https://stripe.com/blog/online-migrations
- FastAPI lifespan: https://fastapi.tiangolo.com/advanced/events/#lifespan
