# Stage C — 메타데이터 DB + 클립 조회 API

> Stage A/B 가 만든 세그먼트(`storage/clips/YYYY-MM-DD/{camera_id}/HHMMSS_{motion|idle}.mp4`) 를 앱이 조회 가능한 형태로 구조화. Supabase Postgres 에 `camera_clips` 테이블 신설 → 세그먼트 close 시 INSERT → FastAPI 가 조회 API 3 종 제공.

**상태:** ✅ 완료
**작성:** 2026-04-21
**완료:** 2026-04-21
**연관 SOT:** `../../tera-ai-product-master/docs/specs/petcam-backend-dev.md` — Stage C 상세 설계 (213~395줄)

## 1. 목적

- **사용자 가치**: Flutter 앱이 "오늘 우리 게코 영상 목록" 을 조회할 수 있게. motion 있는 세그먼트만 필터, 펫 단위 조회, 개별 클립 재생까지. Stage D 의 앱 연동을 위한 **데이터 레이어 준비**.
- **학습 목표**:
  - Supabase Postgres + Row-Level Security (RLS) 정책 설계·적용
  - `service_role` vs `anon` 키 분리 (서버-클라이언트 권한 모델)
  - FastAPI `Depends()` 로 싱글톤 클라이언트 주입
  - HTTP Range 헤더 기반 비디오 스트리밍 (시크 가능한 재생)
  - 파일 기반 재시도 큐 (JSONL) — Redis 없이 네트워크 장애 완충
- **부가**: Flutter 앱 레포(`tera-ai-flutter`) 의 `supabase-schema.md` 를 SOT 로 유지하는 관습 정착. 양 레포 스키마 동기화 워크플로 검증.

## 2. 스코프

### In (이번 스펙에서 한다)

- Supabase 프로젝트 공유 결정 문서화 + `tera-ai-flutter/docs/supabase-schema.md` 에 `camera_clips` 섹션 추가 (테이블 14→15, 인덱스 3개 추가)
- `camera_clips` 테이블 + 인덱스 3개 + SELECT RLS 정책 마이그레이션 (MCP `apply_migration`)
- `.env.example` / `.env` 에 `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `DEV_USER_ID`, `DEV_PET_ID` 추가
- `uv add supabase` (supabase-py 의존성)
- `backend/supabase_client.py` — 싱글톤 클라이언트 + `Depends()` 팩토리
- `backend/capture.py` 수정 — `_close_and_tag_segment` 안에서 INSERT 호출 + 실패 시 대기열 enqueue
- `backend/pending_inserts.py` — `storage/pending_inserts.jsonl` append + 주기적 flush + 성공 라인 제거
- `backend/routers/clips.py` — 3 개 엔드포인트:
  - `GET /clips` — 목록 + 쿼리 필터 (`camera_id`, `has_motion`, `from`, `to`, `limit`, `cursor`)
  - `GET /clips/{id}` — 단건 메타
  - `GET /clips/{id}/file` — mp4 스트리밍 (HTTP Range 지원)
- 단위 테스트 (Supabase 클라이언트 mock):
  - 대기열 enqueue → flush → 성공 시 라인 제거 경로
  - `/clips` 목록 조회 응답 스키마
- 실 카메라 2분 이상 녹화 → `camera_clips` 행 2개 이상 생성 확인 (MCP `execute_sql`)
- README 업데이트 — Supabase 환경변수, Stage C API 사용 예시

### Out (이번 스펙에서 **안 한다**)

- **JWT 인증** — `Authorization: Bearer` 헤더 검증 → Stage D. Stage C 는 `DEV_USER_ID` 하드코딩
- **썸네일 생성** (`thumbnail_path` 컬럼) — Stage D 이후
- **Supabase Storage 업로드** — 영상 파일은 전부 로컬 디스크. Stage E 이후 "중요 클립만 선별 업로드"
- **움직임 없는 세그먼트 자동 삭제 정책** — 별도 스펙으로
- **멀티 카메라 워커 동시 처리** — 단일 워커 전제 유지
- **앱 측 Repository 구현** — Flutter 쪽 작업 (Stage D 이후)
- **재시도 큐 스케줄링 정교화** — 단순 주기 + 시작 시 1회면 충분. 백오프·jitter 는 Stage D 이후

### 경계 사유

- Stage C 는 **"메타데이터를 DB 에 기록하고 조회 가능하게"** 까지. 인증·썸네일·Storage 업로드는 각각 독립 이슈. 한 번에 하면 디버깅 시 어느 레이어 문제인지 분리 어려움.
- JWT 는 Stage D 에서 Flutter 앱 연동할 때 함께 하는 게 E2E 테스트 자연스러움.

## 3. 완료 조건

SOT 10 번 섹션(383~395줄) 미러링 + 이 레포 관점 추가.

### DB / 스키마
- [x] `tera-ai-flutter/docs/supabase-schema.md` 에 `camera_clips` 섹션 추가 (15 번째 테이블)
- [x] Supabase `camera_clips` 테이블 생성 (`apply_migration` 로)
- [x] 인덱스 3 개 생성: `(user_id, started_at DESC)`, `(pet_id, started_at DESC) WHERE pet_id IS NOT NULL`, `(user_id, has_motion, started_at DESC) WHERE has_motion = true`
- [x] RLS 활성화 + `"User reads own clips"` SELECT 정책 적용

### 환경 / 의존성
- [x] `uv add supabase`
- [x] `.env.example` 에 4 개 키 추가: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `DEV_USER_ID`, `DEV_PET_ID`
- [x] `.env` 에 실제 값 기입 (service_role key 는 Supabase 대시보드 > Settings > API)

### 코드
- [x] `backend/supabase_client.py` — 싱글톤 + FastAPI `Depends` 팩토리
- [x] `backend/pending_inserts.py` — JSONL 큐 (enqueue / flush / 성공 라인 제거)
- [x] `backend/capture.py` — `_close_and_tag_segment` 에서 INSERT → 실패 시 enqueue
- [x] `backend/routers/clips.py` — 3 개 엔드포인트 구현
- [x] `backend/app.py` (또는 `main.py`) 에 `clips` 라우터 등록

### 테스트
- [x] `tests/test_pending_inserts.py` — enqueue / flush 단위 테스트 (9 ケース)
- [x] `tests/test_clips_api.py` — Supabase mock 기반 목록/단건 API 응답 검증 (21 ケース)
- [x] 실 카메라 2 분 이상 녹화 → `SELECT * FROM camera_clips` 로 행 2 개 이상 확인 (3개 row, file_size 디스크 일치, pet_id/user_id 주입 확인)
- [x] `curl http://localhost:8000/clips?camera_id=<id>&has_motion=true` 응답 검증

### 문서
- [x] `README.md` Stage C API 섹션 추가 (환경변수 표, 엔드포인트 예시)

## 4. 설계 메모

### 선택한 방법

- **Supabase 공유 프로젝트**: Flutter 앱이 쓰는 `slxjvzzfisxqwnghvrit` 재사용. SOT 결정 (217~225줄) 그대로 따름.
- **DEV_USER_ID 확정**: `380d97fd-cb83-4490-ac26-cf691b32614f` (`bss.rol20@gmail.com`). Stage D 에서 JWT 기반으로 교체 예정.
- **DEV_PET_ID 확정**: `55518f35-b251-4ed7-962f-b65611d63223` (`테스트1`, 크레스티드 게코). Stage C 는 camera 1 대 → 펫 1 마리 하드 매핑. Stage D 에서 "카메라 ↔ 펫 매핑 테이블" 검토.
- **네트워크 장애 대응**: `storage/pending_inserts.jsonl` 파일 append + 서버 시작 시 1 회 flush + 주기적(30 초) flush. Redis 등 별도 인프라 불필요 (초기 단계 과잉).
- **테스트 전략**: `supabase-py` 클라이언트를 `Depends()` 로 주입 → 테스트에서 `app.dependency_overrides[get_supabase] = lambda: MockClient()`. 실 Supabase 의존 없이 단위 테스트 가능.

### 고려했던 대안 (왜 안 골랐는지)

- **SQLite 먼저 + Stage D 이관**: 초기 A안 후보. SOT 와 충돌 + 이관 공수 + `pet_id`/`user_id` FK 를 이관 시 재작성. 기각.
- **Supabase Storage 에 영상 업로드**: 분당 2~5MB × 24h = 4GB/일. 무료 플랜(1GB) 즉시 초과. 기각. 로컬 디스크 유지.
- **기존 `media` 테이블에 camera_clips 정보 병합**: `media` 는 "수동 업로드한 펫 사진/영상" 전용. `camera_clips` 는 "실시간 자동 녹화 세그먼트". 용도·생명주기·수량(일당 1440 행) 다 다름. 같은 테이블이면 쿼리 복잡도 폭증. 기각.
- **재시도 큐에 Redis/Celery**: 초기 단계 인프라 과잉. 파일 하나로 충분. 기각.

### 기존 구조와의 관계

- `backend/capture.py` — 기존 `_close_and_tag_segment` 마지막 줄에 INSERT 호출 1 개 추가. motion/idle 분기는 그대로.
- `CaptureWorker` 생성자에 Supabase 클라이언트 주입 (`Depends`). 생성자 시그니처 약간 변경.
- `backend/routers/` — Stage A 에 `status.py` 있으면 같은 패턴으로 `clips.py` 추가.
- 환경변수: Stage A~B 의 `RTSP_URL`, `MOTION_*` 와 나란히 `SUPABASE_*`, `DEV_USER_ID` 추가.

### 리스크 / 미해결 질문

- **`.env` 의 service_role 키 유출** — 커밋 사고 치명적. `.gitignore` 이미 엄수. 추가로 커밋 훅으로 `SUPABASE_SERVICE_ROLE_KEY=` 패턴 감지 고려 (Stage D 이후).
- **대기열 무한 증가** — Supabase 장기 다운 시 `pending_inserts.jsonl` 이 계속 커짐. 일단 **최대 1000 라인 제한 + 초과 시 가장 오래된 것 drop + 로그**. Stage D 이후 재검토.
- **테스트 데이터 오염** — 실 Supabase 에 테스트 행이 섞임. Stage C 는 `camera_id="cam-dev-*"` 접두어 규약 + 사용자 수동 DELETE. Stage D 이후 별도 테스트 프로젝트 또는 브랜치 DB 검토.
- **`started_at` timezone 처리** — Python `datetime.now()` 는 naive → `datetime.now(timezone.utc)` 로 통일. Supabase `TIMESTAMPTZ` 는 UTC 저장 기본.
- **Range 요청 구현 정확도** — FastAPI `StreamingResponse` 는 기본 Range 헤더 처리 안 함. 직접 파싱 + `206 Partial Content` 응답 필요. Flutter `video_player` 가 어떤 요청 패턴 보내는지 실측 필요.

## 5. 학습 노트

### 개념 1 — RLS (Row-Level Security)

Postgres 의 행 단위 권한. 정책 SQL 로 "이 행을 누가 SELECT/INSERT/UPDATE/DELETE 할 수 있나" 를 선언. Supabase 는 JWT 의 `sub` 클레임을 `auth.uid()` 로 주입.

```sql
CREATE POLICY "User reads own clips" ON camera_clips
  FOR SELECT USING (auth.uid() = user_id);
```

→ 앱이 `SELECT * FROM camera_clips` 해도 **본인 것만** 나옴. 앱 코드에 `WHERE user_id = ?` 안 써도 됨.

**Node/NestJS 비유**: 모든 라우트에 ownership guard 미들웨어 다는 대신, DB 자체가 소유권 체크. 중복 코드 제거 + 보안 레이어 DB 내려감 (서버 실수로 `WHERE` 빼도 데이터 안 샘).

### 개념 2 — `service_role` vs `anon` 키 분리

Supabase 가 주는 2 종 API 키:

| 키 | RLS | 용도 |
|----|-----|------|
| `anon` | **적용** | 브라우저/앱 코드. JWT 기반 본인 데이터만 |
| `service_role` | **바이패스** | 서버 코드. 어떤 user_id 로도 INSERT/UPDATE 가능 |

**우리 구조**: FastAPI 서버는 여러 유저(나중엔) 의 세그먼트를 INSERT 해야 하니까 `service_role`. Flutter 앱은 `anon` + 본인 JWT 로 SELECT.

**절대 규칙**: `service_role` 키는 클라이언트 코드에 절대 포함 금지 (GitHub 공개 레포에 커밋하면 즉시 유출). petcam-lab `.env` 한정.

### 개념 3 — Partial Index (부분 인덱스)

```sql
CREATE INDEX idx_camera_clips_motion
  ON camera_clips(user_id, has_motion, started_at DESC)
  WHERE has_motion = true;
```

전체 행이 아니라 **조건 만족 행만** 인덱스. SQLite 도 지원하지만 Postgres 에서 훨씬 많이 쓰임.

**왜 이득?**: motion 있는 세그먼트는 24 시간 중 ~5%. 전체 인덱스 대비 용량 1/20. 앱의 주 쿼리("오늘 움직임 있는 클립") 는 이 인덱스 타고 매우 빠름.

### 개념 4 — HTTP Range Request (부분 전송)

비디오 플레이어가 "0:30 부터 재생" 하려면 mp4 중간부터 다운로드 가능해야 함. 브라우저·`video_player` 가 `Range: bytes=1048576-` 헤더 보냄.

**서버 응답 형식**:
```
HTTP/1.1 206 Partial Content
Content-Range: bytes 1048576-2097151/5242880
Content-Length: 1048576
```

FastAPI 에서 `StreamingResponse` 로 구현 가능하지만 Range 파싱은 수동. 단순한 스트리밍(`StreamingResponse(open(path, 'rb'))`)은 시크 불가.

**Node 비유**: `express` 의 `res.sendFile()` 은 Range 자동 처리. FastAPI 는 명시적으로 해줘야 함.

### 개념 5 — JSONL (JSON Lines) 큐

```
{"user_id": "...", "camera_id": "...", "started_at": "..."}
{"user_id": "...", "camera_id": "...", "started_at": "..."}
```

한 줄 = 한 이벤트. append-only 쓰기 + 재시작 시 처음부터 재생 가능. Redis Bull Queue / Kafka 의 간이 버전.

**장점**: 인프라 제로, 디버깅 간단 (파일 열어서 읽음), 서버 크래시에도 데이터 안전.
**단점**: 동시 쓰기 경합 (단일 워커니까 문제 없음), 성공 라인 제거가 파일 rewrite → 큰 큐에 부적합 (우리는 1000 라인 제한).

### 개념 6 — FastAPI `Depends()` 싱글톤 패턴

```python
@lru_cache
def get_supabase() -> Client:
    return create_client(url, key)

@router.get("/clips")
async def list_clips(sb: Client = Depends(get_supabase)):
    ...
```

**NestJS 비유**: `@Injectable()` + 모듈 provider. `@lru_cache` 가 "singleton scope" 역할. 테스트에서는 `app.dependency_overrides[get_supabase] = lambda: MockClient()` 로 교체.

## 6. 참고

- SOT 스펙: `../../tera-ai-product-master/docs/specs/petcam-backend-dev.md` (Stage C 상세 설계, 213~395줄)
- Flutter 스키마 SOT: `/Users/baek/myProjects/tera-ai-flutter/docs/supabase-schema.md` (동기화 필수)
- Stage B 스펙 (선행): `./stage-b-motion-detect.md`
- supabase-py 공식 문서: https://supabase.com/docs/reference/python/introduction
- Postgres RLS 공식: https://www.postgresql.org/docs/current/ddl-rowsecurity.html
- FastAPI Range 구현 예시: https://fastapi.tiangolo.com/advanced/custom-response/#streamingresponse
