# 데이터베이스 스키마

> Supabase(Postgres) 테이블 6개 + RLS + 인덱스 + 마이그레이션 이력. 스키마는 `public` 기준.

## 목차

- [ERD (ASCII)](#erd-ascii)
- [테이블](#테이블)
  - [`cameras`](#cameras)
  - [`camera_clips`](#camera_clips)
  - [`pets`](#pets)
  - [`clip_mirrors`](#clip_mirrors)
  - [`labelers`](#labelers)
  - [`behavior_labels`](#behavior_labels)
- [RLS 정책 요약](#rls-정책-요약)
- [service_role vs anon](#service_role-vs-anon)
- [마이그레이션 이력](#마이그레이션-이력)
- [Supabase 접근 방법](#supabase-접근-방법)

---

## ERD (ASCII)

```
┌─────────────────────┐
│ auth.users          │  Supabase Auth (관리형)
│  id UUID            │
└──────────┬──────────┘
           │ 1
           │
           │ N                              N
   ┌───────┴───────┐              ┌───────────────────┐
   │ pets          │              │ cameras           │
   │  id UUID      │◄────────────┤  pet_id (nullable)│
   │  user_id      │  SET NULL    │  user_id          │
   │  species      │              │  display_name     │
   │  ...          │              │  host, port, path │
   └───────┬───────┘              │  username         │
           │ 1                    │  password_enc     │
           │                      │  is_active        │
           │ N                    └─────────┬─────────┘
           │                                │ 1
           │                                │
           │                                │ N
           │                      ┌─────────┴─────────┐
           └─────────────────────►│ camera_clips      │
             SET NULL              │  id UUID          │
                                   │  user_id, pet_id  │
                                   │  camera_id (CASCADE)
                                   │  file_path        │
                                   │  started_at       │
                                   │  has_motion       │
                                   │  thumbnail_path   │
                                   │  ...              │
                                   └───────────────────┘

            ┌──────────────────────────────┐
            │ clip_mirrors (QA 전용)       │
            │  source_camera_id (cameras)  │
            │  mirror_camera_id (cameras)  │
            │  mirror_user_id              │
            └──────────────────────────────┘
              * service_role 전용, RLS ENABLE + 정책 0건
```

**핵심 관계**
- `cameras.user_id` → `auth.users.id` (CASCADE)
- `cameras.pet_id` → `pets.id` (SET NULL)
- `camera_clips.user_id` → `auth.users.id`
- `camera_clips.pet_id` → `pets.id` (SET NULL)
- `camera_clips.camera_id` → `cameras.id` (CASCADE)
- `clip_mirrors.source_camera_id` / `mirror_camera_id` → `cameras.id` (CASCADE)

---

## 테이블

### `cameras`

카메라 등록 정보. RTSP 비번은 Fernet 암호화 후 `password_encrypted` 컬럼에 저장.

```sql
CREATE TABLE cameras (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  pet_id UUID REFERENCES pets(id) ON DELETE SET NULL,
  display_name TEXT NOT NULL,
  host TEXT NOT NULL,
  port INT NOT NULL DEFAULT 554,
  path TEXT NOT NULL DEFAULT 'stream1',
  username TEXT NOT NULL,
  password_encrypted TEXT NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT true,
  last_connected_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_cameras_user_id ON cameras(user_id);
CREATE INDEX idx_cameras_pet_id ON cameras(pet_id) WHERE pet_id IS NOT NULL;
CREATE UNIQUE INDEX idx_cameras_user_host_unique
  ON cameras(user_id, host, port, path);

CREATE TRIGGER cameras_updated_at
  BEFORE UPDATE ON cameras
  FOR EACH ROW
  EXECUTE FUNCTION extensions.moddatetime(updated_at);
```

**컬럼**

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `id` | UUID PK | `gen_random_uuid()` |
| `user_id` | UUID NOT NULL | 카메라 소유자 |
| `pet_id` | UUID | 연결된 펫 (선택) |
| `display_name` | TEXT NOT NULL | 사용자 설정 이름 ("거실" 등) |
| `host` | TEXT NOT NULL | RTSP 호스트 (IP 또는 DNS) |
| `port` | INT NOT NULL (default 554) | RTSP 포트 |
| `path` | TEXT NOT NULL (default `stream1`) | RTSP 경로 (`stream1`=1080p, `stream2`=720p) |
| `username` | TEXT NOT NULL | RTSP 계정 |
| `password_encrypted` | TEXT NOT NULL | Fernet 토큰 (URL-safe base64 문자열) |
| `is_active` | BOOL (default true) | false 면 lifespan 에서 skip |
| `last_connected_at` | TIMESTAMPTZ | 마지막 RTSP 연결 성공 시각 (기록 로직은 추후) |
| `created_at` / `updated_at` | TIMESTAMPTZ | 생성/수정. `updated_at` 은 `moddatetime` 트리거로 자동 |

**유니크 제약** `(user_id, host, port, path)` — 한 유저가 동일 RTSP 를 중복 등록 불가.

**왜 INSERT RLS 정책이 없나?** 프론트에서 직접 INSERT 막기 위함. `POST /cameras` 를 강제 거쳐 test-connection → Fernet 암호화 → INSERT 흐름 보장. service_role 전담.

---

### `camera_clips`

1분 세그먼트 mp4 의 메타데이터. 파일 자체는 로컬 디스크 (`storage/clips/<date>/<camera_uuid>/<time>_<motion|idle>.mp4`).

```sql
CREATE TABLE camera_clips (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  pet_id UUID REFERENCES pets(id) ON DELETE SET NULL,
  camera_id UUID NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
  started_at TIMESTAMPTZ NOT NULL,
  duration_sec FLOAT NOT NULL,
  has_motion BOOLEAN NOT NULL,
  motion_frames INT NOT NULL DEFAULT 0,
  file_path TEXT NOT NULL,
  file_size INT NOT NULL,
  codec TEXT,
  width INT,
  height INT,
  fps FLOAT,
  thumbnail_path TEXT,
  r2_key TEXT,                     -- feature-r2-storage-encoding-labeling
  thumbnail_r2_key TEXT,
  encoded_file_size BIGINT,
  original_file_size BIGINT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_camera_clips_user_started_at
  ON camera_clips (user_id, started_at DESC);
CREATE INDEX idx_camera_clips_pet_started_at
  ON camera_clips (pet_id, started_at DESC) WHERE pet_id IS NOT NULL;
CREATE INDEX idx_camera_clips_user_motion_started
  ON camera_clips (user_id, has_motion, started_at DESC) WHERE has_motion = true;
CREATE INDEX idx_camera_clips_camera_id_started_at
  ON camera_clips (camera_id, started_at DESC);
```

**컬럼**

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `id` | UUID PK | — |
| `user_id` | UUID NOT NULL | clip 소유자 |
| `pet_id` | UUID | 당시 카메라에 연결된 펫 |
| `camera_id` | UUID NOT NULL | 어느 카메라의 녹화물인지 (D3 에서 TEXT → UUID FK) |
| `started_at` | TIMESTAMPTZ NOT NULL | 세그먼트 시작 시각 (UTC) |
| `duration_sec` | FLOAT NOT NULL | 실제 재생 길이 (CFR 보정 후) |
| `has_motion` | BOOL NOT NULL | 유효 motion ≥ `MOTION_SEGMENT_THRESHOLD_SEC` |
| `motion_frames` | INT | 유효 motion 프레임 수 (run-length 필터 통과) |
| `file_path` | TEXT NOT NULL | 디스크 절대 경로 |
| `file_size` | INT NOT NULL | 바이트 |
| `codec` | TEXT | `avc1` (기본) 또는 `mp4v` (fallback) |
| `width` / `height` | INT | 프레임 크기 |
| `fps` | FLOAT | 측정 FPS |
| `thumbnail_path` | TEXT | jpg 경로 (Stage D4+ 생성, 이전 행은 NULL) |
| `r2_key` | TEXT | R2 mp4 object key (`clips/{camera_id}/{date}/{HHMMSS}_{tag}_{clip_id}.mp4`). NULL = 인코딩/업로드 실패 또는 백필 전 → `file_path` 로컬 fallback. |
| `thumbnail_r2_key` | TEXT | R2 썸네일 jpg key. NULL 의미는 `r2_key` 와 동일. |
| `encoded_file_size` | BIGINT | 인코딩 후 R2 mp4 바이트. NULL = R2 미업로드. |
| `original_file_size` | BIGINT | 인코딩 전 원본 mp4 바이트 (인코딩 시점에 박음. `file_size` 와 보통 같은 값, 압축률 분석용). |
| `created_at` | TIMESTAMPTZ | — |

**인덱스 설계**
- `(user_id, started_at DESC)` — `/clips` 목록 기본 쿼리.
- `(pet_id, started_at DESC) WHERE pet_id IS NOT NULL` — 펫 기준 조회 (부분 인덱스, NULL 제외로 크기 절약).
- `(user_id, has_motion, started_at DESC) WHERE has_motion = true` — motion 필터 쿼리용 부분 인덱스.
- `(camera_id, started_at DESC)` — `/clips?camera_id=<uuid>` 쿼리용 (Stage D3 추가).

**파일명 규칙** `<HHMMSS>_<motion|idle>.mp4` — 세그먼트 저장 시 일단 `_pending.mp4` → 종료 시 motion 판단 후 rename. 썸네일은 같은 basename + `.jpg`.

---

### `pets`

펫 메타 (SOT: `tera-ai-product-master`). petcam-lab 에서는 FK 참조만 하고 CRUD 는 Flutter 앱/Supabase 쪽.

```sql
CREATE TABLE pets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  species TEXT,
  ...
);
```

**petcam-lab 입장에서 필요한 것**
- `cameras.pet_id` FK 타겟
- `camera_clips.pet_id` FK 타겟 (insert 시 `DEV_PET_ID` 또는 카메라의 `pet_id` 를 채움)

**QA 미러 관련** — QA 테스터용 펫 2건이 `bss.rol20@gmail.com` 의 펫을 별개 행으로 복제. 동일 데이터 소스 아님. [`clip_mirrors`](#clip_mirrors) 참조.

---

### `clip_mirrors`

QA 테스터 계정용 best-effort 미러링. **제품 기능 아님**, QA 종료 시 DROP 대상.

```sql
CREATE TABLE clip_mirrors (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_camera_id UUID NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
  mirror_camera_id UUID NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
  mirror_user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (source_camera_id, mirror_camera_id)
);

ALTER TABLE clip_mirrors ENABLE ROW LEVEL SECURITY;
-- RLS 정책 0건 = service_role 외 접근 불가
```

**동작**
- `backend/clip_recorder.py` 의 `_mirror_clip()` 이 원본 INSERT 성공 후 `source_camera_id` 매핑을 조회.
- 매핑이 있으면 같은 clip 을 `mirror_camera_id` + `mirror_user_id` 로 복사 INSERT.
- **live path** (`record`) + **flush path** (`make_flush_insert_fn`) 양쪽에 훅 — 재시작 gap 방지.
- 실패는 warning 만 찍고 넘김 (원본 무결성 우선).

**QA 종료 정리 체크리스트** (`specs/feature-clip-mirrors-for-qa.md` §6 참조)
1. `DROP TABLE public.clip_mirrors;`
2. `backend/clip_recorder.py` 에서 `_mirror_clip` 제거
3. `tests/test_clip_recorder.py` 미러 케이스 제거
4. QA `auth.users` / `cameras` / `pets` / `camera_clips` 삭제 (CASCADE)

---

### `labelers`

팀 라벨러 화이트리스트. 멤버는 자기 소유가 아닌 클립도 R2 영상 + 라벨 폼 접근 가능.
service_role 전용 — RLS ENABLE + 정책 0건 (clip_mirrors 동일 패턴).

```sql
CREATE TABLE labelers (
  user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  added_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  note TEXT,
  added_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE labelers ENABLE ROW LEVEL SECURITY;
-- 정책 0건 = anon/authenticated 완전 차단
```

**컬럼**

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `user_id` | UUID PK | `auth.users.id`. 중복 추가 자동 차단. |
| `added_by` | UUID | 누가 라벨러 추가했는지 (감사). |
| `note` | TEXT | 메모 (예: "QA 테스터 1번", "외부 라벨러 김OO"). |
| `added_at` | TIMESTAMPTZ | — |

**라벨러 추가/제거** — 백엔드 service_role API 또는 SQL 수동 (`INSERT INTO labelers (user_id) VALUES ('<uuid>')`).

---

### `behavior_labels`

GT 라벨. 한 클립 × 여러 라벨러 = 여러 row. Round 4 평가셋 source.

```sql
CREATE TABLE behavior_labels (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  clip_id UUID NOT NULL REFERENCES camera_clips(id) ON DELETE CASCADE,
  labeled_by UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  action TEXT NOT NULL,
  lick_target TEXT,
  note TEXT,
  labeled_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (clip_id, labeled_by)
);

CREATE INDEX idx_behavior_labels_clip_id ON behavior_labels (clip_id);
CREATE INDEX idx_behavior_labels_labeled_at_desc ON behavior_labels (labeled_at DESC);
```

**컬럼**

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `id` | UUID PK | — |
| `clip_id` | UUID NOT NULL | `camera_clips.id` FK (CASCADE). |
| `labeled_by` | UUID NOT NULL | 라벨 작성자 (`auth.users.id`). |
| `action` | TEXT NOT NULL | 행동 enum. **DB CHECK 없음, Pydantic 레벨 검증** (라벨 클래스가 VLM 진화로 바뀌어도 마이그레이션 부담 회피). 허용값: `eating_paste / drinking / moving / unknown / eating_prey / defecating / shedding / basking / unseen` (9 raw). UI 는 5 main 노출 + 더보기로 raw 9. |
| `lick_target` | TEXT NULL | 핥기 대상 차원. NULL 또는 `air / dish / floor / wall / object / other`. **`action=eating_paste\|drinking` 일 때만 의미** (그 외엔 NULL). 예: 기존 raw `air_lick` 은 `(action=eating_paste, lick_target=air)` 로 표현. |
| `note` | TEXT | 라벨러 메모 (선택). |
| `labeled_at` | TIMESTAMPTZ | — |

**유니크 제약** `(clip_id, labeled_by)` — 한 라벨러가 한 클립에 최대 1 row. UPSERT 패턴으로 수정.

**합의(GT) 산출** — 다중 라벨러 충돌 처리는 별도 스펙 (`feature-gt-consensus.md` 가칭). 이번 스펙에서는 raw 라벨만 쌓고 수동 합의.

**RLS 정책** (4건 — 결정 4 단순화. 라벨러 멤버 체크는 백엔드 `service_role` 코드)
- `SELECT`: `auth.uid() = labeled_by` OR `auth.uid() = clip.user_id` (clip owner 가 모든 라벨러 결과 조회)
- `INSERT`: `WITH CHECK (auth.uid() = labeled_by)`
- `UPDATE` / `DELETE`: `auth.uid() = labeled_by` (본인 라벨만)

---

## RLS 정책 요약

| 테이블 | RLS | SELECT | INSERT | UPDATE | DELETE | 비고 |
|--------|-----|--------|--------|--------|--------|------|
| `cameras` | ON | `auth.uid() = user_id` | (정책 없음) | `auth.uid() = user_id` | `auth.uid() = user_id` | INSERT 는 백엔드 `service_role` 전담 |
| `camera_clips` | ON | `auth.uid() = user_id` | (정책 없음) | (정책 없음) | (정책 없음) | 전부 백엔드에서만 기록 |
| `pets` | ON | `auth.uid() = user_id` | `auth.uid() = user_id` | `auth.uid() = user_id` | `auth.uid() = user_id` | Flutter 앱에서 CRUD |
| `clip_mirrors` | ON | (정책 없음) | (정책 없음) | (정책 없음) | (정책 없음) | service_role 전용, anon/authenticated 완전 차단 |
| `labelers` | ON | (정책 없음) | (정책 없음) | (정책 없음) | (정책 없음) | service_role 전용 (clip_mirrors 동일 패턴) |
| `behavior_labels` | ON | `auth.uid() = labeled_by` OR `clip owner` | `auth.uid() = labeled_by` | `auth.uid() = labeled_by` | `auth.uid() = labeled_by` | 라벨러 멤버 체크는 백엔드 `service_role` 코드 |

**petcam-lab 백엔드는 `service_role` 키 사용 → RLS 완전 바이패스.** 라우터에서 `user_id` 필터를 코드로 명시하는 이유 (Stage D+ anon 전환 시 자동 적용될 RLS 를 미리 흉내).

**Flutter 앱은 `anon` 키 + 본인 JWT** → RLS 가 자동 적용되어 본인 `user_id` 행만 조회.

---

## service_role vs anon

Supabase 가 주는 2종 API 키.

| 키 | RLS | 용도 | petcam-lab 에서 |
|----|-----|------|------------------|
| `anon` | **적용** | 브라우저/앱 코드 | Flutter 앱 (본인 JWT 로 본인 데이터만) |
| `service_role` | **바이패스** | 서버 코드 | FastAPI 백엔드 (여러 유저 clip INSERT) |

**절대 규칙** — `service_role` 키는 클라이언트 코드에 포함 금지. 공개 레포에 커밋하면 즉시 전체 DB 유출. `.env` 한정. `.gitignore` 확인.

---

## 마이그레이션 이력

Supabase 대시보드 `Database > Migrations` 에 공식 이력. 주요 타임라인.

| 시점 | 마이그레이션 | 설명 |
|------|-------------|------|
| Stage C | `create_camera_clips_table` | 초기 테이블 + `camera_id TEXT` + 3 인덱스 + RLS SELECT 정책 |
| Stage D1 | `add_pets_rls_for_petcam` | `pets` RLS 확인/보정 (기존 tera-ai 레포 소유) |
| Stage D2 | `create_cameras_table` | cameras 테이블 + moddatetime 트리거 + RLS (INSERT 정책 생략) |
| Stage D3 | `camera_clips_migrate_camera_id_to_uuid_fk` | `camera_id TEXT → UUID + FK`. 3단계(`ADD COLUMN` nullable → backfill → `NOT NULL`/DROP/RENAME) |
| Stage D3 | `camera_clips_camera_id_index` | `(camera_id, started_at DESC)` 인덱스 추가 |
| Stage D4 | `add_thumbnail_path_to_camera_clips` | `thumbnail_path TEXT NULL` 컬럼 추가 (기존 행은 NULL) |
| QA 미러 | `add_clip_mirrors_for_qa_testers` | `clip_mirrors` 테이블 + RLS ENABLE + 정책 0건 |
| feature-r2 | `add_r2_columns_to_camera_clips` | `r2_key` / `thumbnail_r2_key` / `encoded_file_size` / `original_file_size` 4컬럼 (모두 NULL) |
| feature-r2 | `create_labelers_table` | 팀 라벨러 화이트리스트 + RLS ENABLE + 정책 0건 |
| feature-r2 | `create_behavior_labels_table` | GT 라벨 테이블 + UNIQUE(clip_id, labeled_by) + 인덱스 + RLS 4정책 |

**마이그레이션 작성 원칙** (Stage D3 에서 검증된 3단계 패턴)
1. **Add** — 새 컬럼 nullable + FK
2. **Backfill** — 기존 행에 값 채우기 (`UPDATE ... WHERE`)
3. **Enforce** — `NOT NULL` + 기존 컬럼 `DROP` + 새 컬럼 `RENAME`

→ `ALTER COLUMN ... TYPE` 한 방보다 안전 (UPDATE 중 실패 시 rollback 부담 작음). Stripe/Shopify 실전 가이드 동일.

---

## Supabase 접근 방법

**대시보드**
- https://supabase.com/dashboard → `slxjvzzfisxqwnghvrit` 프로젝트

**MCP (Claude Code)**
- `.mcp.json` 에 Supabase MCP 등록됨 → `mcp__supabase__*` 도구로 스키마 조회, 마이그레이션 적용, SQL 실행 가능.
- 로컬에서 직접 SQL 치는 것보다 안전 (MCP 가 read-only / apply-migration 구분).

**서버 코드**
- [`backend/supabase_client.py`](../backend/supabase_client.py) — `get_supabase_client()` 싱글톤. `@lru_cache(maxsize=1)` 이라 앱 생애주기 내 1개만 생성.
- 사용 패턴: `sb.table("camera_clips").select("*").eq("user_id", uid).execute()`.

**환경변수 2종 필요**
- `SUPABASE_URL` — `https://slxjvzzfisxqwnghvrit.supabase.co`
- `SUPABASE_SERVICE_ROLE_KEY` — 대시보드 `Settings > API > service_role` (secret). 커밋 절대 금지.
