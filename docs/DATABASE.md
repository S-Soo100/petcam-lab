# 데이터베이스 스키마

> Supabase(Postgres) 핵심 테이블 + RLS + 인덱스 + 마이그레이션 이력. 스키마는 `public` 기준.

## 목차

- [ERD (ASCII)](#erd-ascii)
- [테이블](#테이블)
  - [`cameras`](#cameras)
  - [`camera_clips`](#camera_clips)
  - [`clip_router_features`](#clip_router_features)
  - [`pets`](#pets)
  - [`clip_mirrors`](#clip_mirrors)
  - [`labelers`](#labelers)
  - [`behavior_labels`](#behavior_labels)
  - [`clip_labeling_sessions`](#clip_labeling_sessions)
  - [`labeler_applications`](#labeler_applications)
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
                                             │ 1
                                             │ trigger: AFTER INSERT
                                             │ 1
                                   ┌─────────▼─────────┐
                                   │ clip_router_      │
                                   │ features          │
                                   │  clip_id PK/FK    │
                                   │  started_at       │
                                   │  window counts    │
                                   │  motion bursts    │
                                   │  baseline         │
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
- `clip_router_features.clip_id` → `camera_clips.id` (CASCADE, 1:1)
- `clip_router_features.camera_id` → `camera_clips.camera_id` raw copy (soft reference, FK 없음)
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
  camera_id UUID REFERENCES cameras(id) ON DELETE CASCADE,
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

### `clip_router_features`

Local Router v3용 feature-store. `camera_clips`는 "영상이 언제 찍혔고 어디 저장됐는지"를 저장하고, 이 테이블은 "이 clip을 즉시 VLM에 보낼지, 나중에 보낼지" 판단할 cheap metadata를 저장한다.

핵심 보장: migration 적용 시 기존 `camera_clips`를 한 번 백필하고, 이후 `camera_clips` INSERT 때 DB trigger가 placeholder row를 자동 생성한다. 즉 캡처 worker, R2 업로드 fallback, 수동 백필 등 어느 경로로 clip이 들어와도 **모든 clip에 feature row가 생긴다**.

```sql
CREATE TABLE clip_router_features (
  clip_id UUID PRIMARY KEY REFERENCES camera_clips(id) ON DELETE CASCADE,
  user_id UUID NOT NULL,
  pet_id UUID,
  camera_id UUID,
  started_at TIMESTAMPTZ NOT NULL,
  duration_sec DOUBLE PRECISION NOT NULL,
  has_motion BOOLEAN NOT NULL,
  motion_frames INT NOT NULL DEFAULT 0,
  width INT,
  height INT,
  fps DOUBLE PRECISION,

  window_clip_count_10m INT,
  window_clip_count_30m INT,
  window_clip_count_60m INT,
  seconds_since_prev_clip DOUBLE PRECISION,
  seconds_until_next_clip DOUBLE PRECISION,

  recent_activity_baseline DOUBLE PRECISION,
  same_hour_7d_avg_motion DOUBLE PRECISION,
  today_activity_percentile DOUBLE PRECISION,
  activity_delta_from_baseline DOUBLE PRECISION,

  motion_mean DOUBLE PRECISION,
  motion_peak DOUBLE PRECISION,
  motion_std DOUBLE PRECISION,
  active_motion_ratio DOUBLE PRECISION,
  center_motion_ratio DOUBLE PRECISION,
  late_motion_ratio DOUBLE PRECISION,
  motion_burst_count INT,
  longest_motion_burst_sec DOUBLE PRECISION,
  first_motion_sec DOUBLE PRECISION,
  last_motion_sec DOUBLE PRECISION,
  motion_coverage_ratio DOUBLE PRECISION,

  evidence_reliability TEXT CHECK (
    evidence_reliability IS NULL OR evidence_reliability IN ('low', 'medium', 'high')
  ),
  active_feature_run_id UUID,
  feature_version TEXT NOT NULL DEFAULT 'v1',
  producer_name TEXT,
  producer_host TEXT,
  producer_run_id TEXT,
  producer_code_ref TEXT,
  feature_params JSONB NOT NULL DEFAULT '{}'::jsonb,
  processing_status TEXT NOT NULL DEFAULT 'pending'
    CHECK (processing_status IN ('pending', 'processing', 'ready', 'failed')),
  processing_error TEXT,
  processed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**컬럼 그룹**

| 그룹 | 컬럼 | 설명 |
|------|------|------|
| 기본 clip 메타 | `clip_id`, `user_id`, `pet_id`, `camera_id`, `started_at`, `duration_sec`, `has_motion`, `motion_frames`, `width`, `height`, `fps` | trigger가 `camera_clips`에서 복사하는 placeholder 값. 과거/외부 백필 clip은 `camera_id`가 NULL이거나 `cameras`에 없는 orphan 값일 수 있음 |
| window context | `window_clip_count_10m`, `window_clip_count_30m`, `window_clip_count_60m`, `seconds_since_prev_clip`, `seconds_until_next_clip` | 같은 카메라의 전후 clip 밀도. `camera_id`가 NULL이면 비워두고, orphan 값이면 같은 raw camera_id끼리 best-effort 계산 |
| baseline context | `recent_activity_baseline`, `same_hour_7d_avg_motion`, `today_activity_percentile`, `activity_delta_from_baseline` | 평소 대비 얼마나 특이한 움직임인지 |
| event-shape | `motion_mean`, `motion_peak`, `motion_std`, `active_motion_ratio`, `center_motion_ratio`, `late_motion_ratio`, `motion_burst_count`, `longest_motion_burst_sec`, `first_motion_sec`, `last_motion_sec`, `motion_coverage_ratio` | OpenCV/R2 worker가 채우는 frame-level 특징 |
| provenance | `active_feature_run_id`, `feature_version`, `producer_name`, `producer_host`, `producer_run_id`, `producer_code_ref`, `feature_params` | 현재 운영 snapshot이 어떤 worker/code/params/run에서 나왔는지 |
| worker 상태 | `evidence_reliability`, `processing_status`, `processing_error`, `processed_at`, `created_at`, `updated_at` | feature extraction 진행 상태 |

**인덱스**

- `(camera_id, started_at DESC)` — 카메라별 시간 윈도우 계산.
- `(processing_status, started_at ASC)` — metadata worker pending queue.
- `(user_id, started_at DESC)` — owner별 후속 조회/디버깅.

**RLS 정책**

RLS ENABLE + 정책 0건. 초기에는 metadata worker/local-router가 `service_role`로만 읽고 쓴다. 앱 직접 노출이 필요해지면 raw 테이블을 열지 말고 owner SELECT policy 또는 curated view를 별도 migration으로 추가한다.

**자동 생성 trigger**

Migration이 먼저 기존 `camera_clips`를 `clip_router_features`로 백필한다. 그 다음 `trg_camera_clips_create_router_features`가 `camera_clips` INSERT 후 `fn_create_clip_router_features_placeholder()`를 실행한다. 이 함수는 기본 clip 메타만 복사하고, motion burst/window/baseline 값은 `NULL`로 남긴다. 후속 metadata worker가 `processing_status='pending'` row를 읽어 feature를 채운다.

### `clip_router_feature_runs`

Local Router feature generation history. `clip_router_features`가 운영용 current snapshot이라면, 이 테이블은 같은 clip을 여러 버전/파라미터로 재처리한 결과를 append-only로 남기는 연구/감사용 history다.

```sql
CREATE TABLE clip_router_feature_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  clip_id UUID NOT NULL REFERENCES camera_clips(id) ON DELETE CASCADE,

  feature_version TEXT NOT NULL,
  producer_name TEXT NOT NULL,
  producer_host TEXT,
  producer_run_id TEXT NOT NULL,
  producer_code_ref TEXT,
  feature_params JSONB NOT NULL DEFAULT '{}'::jsonb,

  camera_id UUID,
  started_at TIMESTAMPTZ,
  duration_sec DOUBLE PRECISION,
  has_motion BOOLEAN,
  motion_frames INT,
  width INT,
  height INT,
  fps DOUBLE PRECISION,

  -- window/baseline/event-shape columns mirror clip_router_features
  evidence_reliability TEXT CHECK (
    evidence_reliability IS NULL OR evidence_reliability IN ('low', 'medium', 'high')
  ),
  processing_status TEXT NOT NULL DEFAULT 'ready' CHECK (
    processing_status IN ('ready', 'failed')
  ),
  processing_error TEXT,

  input_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
  output_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  UNIQUE (producer_run_id, clip_id)
);
```

핵심 원칙:

- `clip_router_features`: 라우터가 읽는 최신/승인 current snapshot.
- `clip_router_feature_runs`: 비교 실험용 run history. `sample_frames`, threshold, OpenCV version, git commit hash가 바뀌어도 과거 결과를 보존한다.
- worker는 feature 생성 시 `clip_router_feature_runs`에 먼저 append하고, 그 run id를 `clip_router_features.active_feature_run_id`로 연결한다.
- RLS는 enable되어 있고 policy는 없다. `service_role` 전용이다.

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

### `clip_labeling_sessions`

Labeling Web v2의 단계형 검수 row. `(clip_id, reviewed_by)`당 하나이며
`initial_gt`는 trigger로 최초 저장 뒤 변경할 수 없다. `prediction_snapshot`은 클라이언트가
보내지 않고 GT 잠금 시 서버가 최신 `behavior_logs(source='vlm')` 원문을 복사한다.

| 컬럼 | 설명 |
|------|------|
| `stage` | `draft / gt_locked / completed` |
| `initial_gt` | VLM 공개 전 최초 사람 답. 불변 |
| `current_gt` | 이후 교정 가능한 현재 GT. owner correction(아래 revision RPC)만 변경 |
| `prediction_snapshot` | GT 잠금 시점 exact VLM row |
| `vlm_verdict` | `correct / partially_correct / incorrect / unjudgeable` |
| `vlm_error_tags` | 행동·대상·미검출·IR·구간 등 오류 원인 |
| `completion_reason` | `vlm_reviewed / no_prediction` |

마이그레이션 파일은 `migrations/2026-07-12_clip_labeling_sessions.sql`. 2026-07-12
운영 Supabase 적용 및 REST `HTTP 200` 확인을 완료했다.

---

### `clip_labeling_session_revisions` (owner 현재 GT 보정, 2026-07-13)

owner 가 본인이 검수 완료한 세션의 `current_gt`/VLM review 를 사유와 함께 보정한 **append-only 감사 기록**.
**최초 blind `initial_gt` 는 절대 바꾸지 않는다**(RPC 가 안 건드리고 `protect_initial_labeling_gt`
트리거가 재차 보호). 컬럼: `session_id`·`clip_id`·`revised_by` FK, `previous_gt`/`revised_gt`,
`previous_vlm_review`/`revised_vlm_review`, `reason`(10~500 CHECK), `created_at`.

**보정 RPC** — `fn_revise_clip_labeling_session(p_clip_id, p_revised_by, p_revised_gt, p_vlm_verdict,
p_vlm_error_tags, p_vlm_review_note, p_reason, p_action, p_lick_target, p_behavior_note)`
(SECURITY DEFINER, service_role EXECUTE 전용). 대상 세션은 `(clip_id, reviewed_by, stage='completed')`
로 **서버가 결정**한다(body 의 session/clip/revised_by 불신). 한 트랜잭션에서 revision insert →
`current_gt`/VLM review update → `behavior_labels` mirror upsert. 미완료·다른 reviewer·미존재는 `P0002`.
Next.js API(`/api/labeling-v2/[clipId]/revise`, `requireOwner`)가 호출 전 owner 를 검증한다.

RLS ENABLE + 정책 0건 + service_role GRANT. 마이그레이션 `migrations/2026-07-13_labeling_session_revisions.sql`.
2026-07-13 Supabase 적용·rollback probe 검증 완료(원자성·`initial_gt` 불변·reviewer/reason 차단).

**append-only 강제(`_labeling_session_revisions_append_only.sql`, 2026-07-13 후속).** REVOKE 만으로는
service_role 이 감사 기록을 UPDATE·DELETE 할 수 있어 계약이 성립하지 않았다. `fn_block_session_revision_mutation`
트리거(BEFORE UPDATE/DELETE row + BEFORE TRUNCATE statement)가 **역할 무관하게**(service_role 포함) 변경·삭제를
`0A000` 로 차단한다(INSERT 만 허용). rollback probe 로 UPDATE/DELETE 차단 확인. ⚠️ revision 참조 FK 는
ON DELETE CASCADE 라, revision 이 달린 clip/session/user hard-delete 는 이 트리거에 막혀 부모 삭제도 실패한다
(감사행 영구 보존이 원칙 — 의도된 동작. 부모를 지우려면 먼저 아카이브/분리).

---

### `labeler_applications`

라벨링 웹 공개 가입 신청 + owner 승인 상태(2026-07-13). **실제 영상 접근 권한 SOT 는
`labelers` 이며 `application.status='approved'` 단독으로 접근을 허용하지 않는다.**
service_role 전용 — RLS ENABLE + 정책 0건 (`labelers` 동일 패턴).

```sql
CREATE TABLE labeler_applications (
  user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  email TEXT NOT NULL,               -- 신청 당시 auth.users.email snapshot
  display_name TEXT NOT NULL,        -- CHECK: BTRIM 후 1~80자
  status TEXT NOT NULL DEFAULT 'pending',  -- pending/approved/rejected
  requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  reviewed_at TIMESTAMPTZ,           -- approved/rejected 이면 NOT NULL (CHECK)
  reviewed_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_labeler_applications_status_requested_at
  ON labeler_applications (status, requested_at DESC);
```

**승인/거절/권한 해제 RPC** — `fn_review_labeler_application(p_user_id, p_reviewer_id, p_decision)`
(SECURITY DEFINER, service_role EXECUTE 전용). 한 트랜잭션에서:
- `approve` → `labelers` upsert + `status='approved'`
- `reject` / `deactivate` → `labelers` delete + `status='rejected'`

owner 자신(`p_user_id = p_reviewer_id`)·없는 신청·잘못된 decision 은 RPC 가 `RAISE`.
Next.js API(`requireOwner`)가 호출 전 `DEV_USER_ID` 로 owner 를 검증한다.

**backfill** — 기존 `labelers` row 는 migration 에서 `approved` 신청으로 채웠다
(이름 fallback: auth `display_name` → 이메일 앞부분 → `기존 라벨러`). 적용·검증 완료
(2026-07-13, `approved_without_labeler=0`, 정책 0건).

마이그레이션 파일 `migrations/2026-07-13_labeler_applications.sql`.

---

### `labeling_tutorial_*` (대화형 튜토리얼, 2026-07-13)

승인된 신규 라벨러가 본 큐 전에 owner 고정 5개 영상으로 `Blind GT → VLM 검수 → 기준 해설`을
학습한다. **정답(reference_gt / prediction_snapshot / reference_vlm_review / feedback_content)은
service_role 전용이며 VLM 검수 제출 전에는 API 응답에 넣지 않는다.** 튜토리얼 답안은
`behavior_labels` / `clip_labeling_sessions` 에 **절대 쓰지 않는다**(학습 시도와 운영 GT provenance 분리).

- **`labeling_tutorial_sets`** — 버전. `status` `draft/active/archived`. `status='active'` 는
  partial unique index 로 전체 1개만. activation RPC 로만 전환.
- **`labeling_tutorial_lessons`** — 고정 5개. `UNIQUE(set,position 1..5)`·`UNIQUE(set,clip_id)`.
  활성화 뒤 clip/reference/prediction/feedback 불변(변경은 새 version) — DB trigger
  `protect_activated_tutorial_lesson` 가 active/archived lesson(**OLD set 기준**)의 10필드
  (set/position/clip/title/objective/tip/reference/prediction/reference_vlm_review/feedback)
  변경·삭제를 차단(2차 하드닝: set 이동 우회 포함).
- **`labeling_tutorial_progress`** — `PK(set,user)`. 본 큐 gate hot path = 이 한 row 의
  `completed_at`/`waived_at`. `current_run_no`·`waiver_reason`(1~200 CHECK).
- **`labeling_tutorial_attempts`** — 시도. `UNIQUE(set,lesson,user,run_no)`. 최초
  `submitted_gt`/`submitted_vlm_review`/`comparison` 은 trigger(`protect_tutorial_attempt`)로 불변.

**RPC (모두 SECURITY DEFINER, service_role EXECUTE 전용):**
- `fn_activate_tutorial_set(set, owner)` — position 1..5·기준 snapshot 완전성 검사 후 active 전환(기존 active archive).
- `fn_acknowledge_tutorial_lesson(attempt, user)` — 피드백 확인→lesson completed, 5개면 같은 트랜잭션에서 progress completed.
- `fn_reset_tutorial(set, user, owner)` — `current_run_no + 1`, 기존 attempt 보존.
- `fn_waive_tutorial(set, user, owner, reason)` — 완료 면제(사유 1~200자, audit 보존).
- `fn_seed_tutorial_lesson_from_owner(...)` — owner 완료 `clip_labeling_sessions` 에서 기준 답 복사(seed). **position 별 v1 lesson 의미 preflight**(1 absent/unseen·2 moving·**3 drinking+wheel**·4 hand_feeding·5 VLM shedding 오판) 를 검사해 lesson 목적과 reference GT 가 안 맞으면 seed 전에 `22023` fail-loud. **4차 하드닝(`_hardening_4.sql`): 검사를 `IF (조건) IS NOT TRUE` 로 바꿔 JSON 키 누락(NULL)도 반드시 차단 + position 3 을 `primary drinking + target ∈ 물 집합`까지 요구**(이전 `target != tool` 은 moving+wheel 오답 통과).

4 테이블 모두 RLS ENABLE + 정책 0건 + service_role GRANT. 마이그레이션 파일
`migrations/2026-07-13_labeling_tutorial.sql`. 2026-07-13 Supabase 적용·검증 완료
(`client_policies=0`, RLS 4/4, funcs 6). **raw SQL(apply_migration)로 적용.**

**production 활성 상태(2026-07-14 KST).** `tutorial-v1` 1개가 active이며 lesson은 정확히 5개다
(position 5개·clip 5개 모두 distinct, reference/prediction/review/feedback 5/5 완전). 기준 GT는
owner revision 경로로 `e679f8ad target=glass`, `d9346cbe context=human`을 반영했다. activation 직후
attempt/progress는 0/0, `behavior_labels=233`·`clip_labeling_sessions=6`으로 seed 전후 production
row 수가 같았다. 2026-07-14 운영 재확인에서는 승인 대기 0명·활동 중 라벨러 2명이며 두 명 모두
`tutorial-v1` 0/5였다. 다음 게이트는 둘 중 1명을 pilot으로 지정해 5/5 완료와 본 큐 진입을 확인하는 것이다.

---

### `clip_vlm_selector_runs` / `clip_vlm_jobs` (야간 후보 shadow, 2026-07-15)

밤 22·00·02·04시 KST의 후보 선택 실행과 clip별 VLM 결과를 재현 가능하게 보존한다.
`clip_vlm_selector_runs`는 카메라·2시간 창·selector별 입력 수/episode/선택 ID/예산 snapshot을,
`clip_vlm_jobs`는 네 목적 슬롯·선택 근거·activity/Gate provenance·모델/prompt/sampler·token/비용·상태를 가진다.
카메라·창·selector run과 clip·selector job은 각각 unique라 같은 창을 다시 실행해도 중복 호출하지 않는다.

RPC `fn_create_clip_vlm_selector_run`은 run+최대 4 job을 원자 생성하고,
`fn_reserve_clip_vlm_job`은 advisory lock 아래 월 비용을 예약한 뒤에만 submitted로 바꾼다.
둘 다 service_role 전용이다. 테이블 RLS는 owner SELECT만 허용하며 anon write는 없다.

**현재 운영:** `claude_cli_batch` 구독 provider라 `reserved_cost_usd=0`, `cost_usd=0`,
`pricing_version=claude-code-subscription-v1`이다. 결과는 이 두 shadow 테이블에만 기록하고
`behavior_logs`·`camera_clips`·앱 하이라이트를 쓰지 않는다. migration
`2026-07-15_clip_vlm_candidate_jobs.sql`은 production에 적용됐다.

---

### `clip_labeling_triage` / `clip_labeling_triage_events` (라벨링 격리함, 2026-07-15)

라벨링 가치가 낮아 보이는 `camera_clips`를 owner 전용 격리함으로 라우팅한다. 설계 정본
`docs/superpowers/specs/2026-07-15-labeling-triage-quarantine-design.md`.

- `clip_labeling_triage` — 현재 라우팅 상태(1 clip = 1 row). `suggested_route(label|quarantine)`,
  `suggestion_reason(gate_active|gate_absent|gate_static|manual)`, `suggestion_source`,
  `policy_version`, `evidence_snapshot jsonb`(최소 evidence, **API 응답엔 절대 미노출**),
  `owner_decision(label|skip|null)` + `decided_by/decided_at/decision_note`. CHECK: owner 결정
  3필드는 all-null 또는 all-set. **유효 상태 우선순위**: owner 결정 > 시스템 제안(§5.2).
- `clip_labeling_triage_events` — append-only 감사(`suggested|owner_labeled|owner_skipped|owner_reset|manual_quarantined`).
  clip 삭제 뒤에도 남도록 **FK 없이 `clip_id uuid`만 보존**. **트리거로 UPDATE/DELETE/TRUNCATE 차단(0A000)** — service_role 도 불가, INSERT 만.

**RPC 3종(전부 service_role 전용, `SECURITY DEFINER`):**
- `fn_upsert_clip_labeling_triage_suggestion(uuid,text,text,text,text,jsonb)` — worker 시스템 제안.
  owner 결정을 덮지 않고, 세션 존재 시 `quarantine` 제안은 `labeling_started` 거부(`label`은 fail-open).
  제안 변경 시에만 `suggested` 이벤트.
- `fn_decide_clip_labeling_triage(uuid,uuid,text,timestamptz,text)` — owner `label|skip|reset`.
  `expected_updated_at` 불일치=`stale_state`, `skip`+세션=`labeling_started`, 없음=`not_found`.
- `fn_manual_quarantine_clip_for_labeling(uuid,uuid,text)` — owner 수동 격리. owner_decision 초기화 →
  `검토 필요`. 세션 있으면 거부, r2_key 없으면 `not_labelable`.

일반 라벨링 큐(`GET /api/labeling-v2/queue`)는 후보 batch별로 triage를 조회해 유효 상태
`검토 필요`/`라벨링 안 함`을 제외한다(전역 `NOT IN` 없이 bounded scan 안에서).

**2차 하드닝(양방향 원자성):** `clip_labeling_sessions` INSERT/`clip_id` 변경 시 발동하는
가드 트리거 `fn_guard_labeling_session_vs_triage`(SECURITY DEFINER)가 quarantine/skip 상태 clip의
새 세션 생성을 `PT409`로 차단한다 — production `clip_labeling_sessions`에는 authenticated 자기
세션 INSERT RLS가 있어 Next.js 큐 필터만으론 부족하기 때문. RPC 3개 + 가드 트리거의 lock 순서를
`camera_clips FOR UPDATE → triage FOR UPDATE`로 통일해 quarantine/skip과 세션 INSERT가 동시에
성공하지 못하게 한다. GT 저장 API(`POST /api/labeling-v2/[clipId]/gt`)는 저장 전 triage 상태를
확인해 `409 triage_quarantined`를 먼저 주고, 트리거 `PT409`는 최종 안전장치다. 자동 제안·수동
격리 모두 `has_motion=true AND r2_key NOT NULL`이 아니면 `not_labelable`로 fail-closed. 카메라
필터 옵션은 `fn_triage_camera_options()`(DISTINCT, service_role)로 triage 대상 카메라만 준다.

**상태:** production migration·rollback probe·Web 배포·owner E2E 완료. Worker read-only Preview 30의 owner blind 검수에서 시스템 quarantine 3건 중 2건이 실제 `라벨링 필요`로 확인돼 write canary를 중단했다. triage/event row는 계속 0이며 일반 큐 데이터는 변하지 않았다.
`2026-07-15_labeling_triage.sql` 적용 후 Supabase 기본 권한으로 가드 트리거 함수에 남은 명시적
EXECUTE를 후속 `2026-07-15_labeling_triage_guard_execute_revoke.sql`로 anon/authenticated/service_role
모두에서 회수했다. DB probe는 quarantine·skip 세션 INSERT 차단, owner label·system label·triage 없음
허용, stale state, duplicate no-op, event UPDATE/DELETE/TRUNCATE `0A000`을 확인하고 전량 rollback했다.
제안 worker는 `petcam-nightly-reporter` main에 구현돼 있으나 기본 write disabled다. 다음 재검증 전까지 `gate_static` 자동 격리는 금지하고, `gate_absent`도 독립 표본을 추가 확보하기 전에는 DB에 쓰지 않는다.

---

### `motion_clip_labeling_*` (운영 라벨링 v3, 2026-07-22) — ✅ **production 적용됨**

**운영(신규 촬영) 영상의 라벨링 정본을 legacy `camera_clips`에서 production `motion_clips`로 전환한 v3.** 설계 정본 `docs/superpowers/specs/2026-07-22-motion-clips-native-labeling-design.md`. legacy `camera_clips` 기반 v2·튜토리얼·과거 GT는 그대로 보존하고, `motion_clips` FK를 쓰는 4개 테이블 + service-role 전용 RPC 6개를 **독립 추가**한다. `camera_clips` mirror INSERT/UPDATE·자동 라벨 생성·Evidence GT mutation은 하지 않는다. 여섯 번째 RPC는 일반 라벨러에게 실제 처리 가능한 `label + media ready + 본인 미완료` clip이 존재하는 카메라만 중복 없이 반환한다.

✅ **production 적용됨** — base `migrations/2026-07-22_motion_clip_labeling_v3.sql`(tracked `motion_clip_labeling_v3`) + guard `migrations/2026-07-22_motion_clip_gt_decision_guard.sql`(tracked `motion_clip_gt_decision_guard`, 2026-07-22) 모두 production DB에 적용. 아래는 스키마 요약.

| 테이블 | 역할 |
|---|---|
| `motion_clip_labeling_triage` | `clip_id uuid PK → motion_clips(id) ON DELETE RESTRICT`. `owner_decision('label'\|'hold'\|'skip')` + 결정 메타(all-null 또는 all-set). row 없음=`unreviewed`. `label`만 일반 라벨러 큐 포함 |
| `motion_clip_labeling_triage_events` | append-only 감사(`owner_labeled/held/skipped/reset/started_labeling`). UPDATE/DELETE/TRUNCATE 트리거 차단(`0A000`). clip_id는 UUID만(FK 없음, 감사 보존) |
| `motion_clip_labeling_sessions` | blind GT. `unique(clip_id, reviewed_by)`, `stage(draft\|gt_locked\|completed)`, `initial_gt` 불변(트리거), `prediction_snapshot`은 GT 잠금 시 서버가 최신 성공 `clip_vlm_jobs.result` 복사 |
| `motion_clip_labeling_session_revisions` | owner 완료 후 `current_gt` 보정 append-only 감사(`reason` 10~500). `initial_gt`는 불변 유지 |

**RPC(service_role EXECUTE 전용, 고정 `search_path`):** `fn_list_motion_clip_labeling_queue`(최신순 `(started_at DESC, id DESC)` keyset, owner=전체·labeler=label만), `fn_decide_motion_clip_labeling`(label/hold/skip/reset + optimistic concurrency `PT409` + 세션 skip `PT410`), `fn_lock_motion_clip_gt`(owner 직접 GT는 triage label+세션을 원자 전환. **2026-07-22 guard**: owner가 이미 `hold/skip`으로 접은 clip의 GT 잠금은 triage row 잠근 직후·세션 쓰기 전에 `PT424 decision_blocks_labeling`(→API 409)로 거부해 제외/보류 결정이 GT 저장으로 조용히 `label`로 뒤집히는 결함 차단), `fn_complete_motion_clip_vlm_review`(prediction 있으면 `vlm_reviewed`·없으면 `no_prediction`), `fn_revise_motion_clip_gt`(owner completed 세션 current_gt 보정).

**API/UI:** `/api/labeling-v3/**` + 숨은 preview `/labeling/motion` · `/labeling/motion/[clipId]`. `/labeling` 기본은 `LABELING_QUEUE_SOURCE` env(기본 `legacy`)로 legacy↔motion 전환하고 legacy는 `/labeling/legacy`로 유지. 4개 테이블 모두 RLS ON + anon/authenticated REVOKE + client policy 0.

---

### `python_evidence_jobs` / `clip_python_evidence_runs` (전 영상 Python evidence, 2026-07-17)

**모든 `motion_clips`가 Python/OpenCV/Gate 전처리(Python Evidence)를 반드시 거치게 하는 durable queue + append-only 결과 원장.** 설계 정본 `docs/superpowers/specs/2026-07-17-python-evidence-universal-worker-design.md`. activity filter의 부가기능이 아니라 전 제품 공통 전처리 계층으로 독립한다(활동시간 정책·selector와 결합하지 않음).

- `python_evidence_jobs` — clip 1건 = 활성 (schema,algorithm) 버전당 1 job. `source(live|historical)`, `priority`(live 100 > historical 10), `status(queued|processing|succeeded|failed_retryable|failed_terminal)`, `attempt_count`/`max_attempts`, `next_attempt_at`/`claimed_at`/`claimed_by`/`lease_expires_at`, allowlist `failure_code`(raw 예외·URL 저장 금지), `result_run_id`. unique `(clip_id, evidence_schema_version, algorithm_version)`.
- `clip_python_evidence_runs` — 결과 원장(append-only). Gate 7-column provenance + producer host/run/code ref + `level0_status`/`level1_status` + bounded JSON(metadata/global·ROI motion series/dwell/periodicity/excursions, **point cap 256**) + `source_prelabel_identity`(Gate identity canonical SHA-256, prelabel 없으면 `none`, 항상 non-null). unique `(clip_id, evidence_schema_version, algorithm_version, source_prelabel_identity)` → 동일 identity 재실행 멱등.

신규 clip은 `motion_clips` AFTER INSERT trigger `fn_enqueue_python_evidence_job()`가 현재 버전 live job을 원자 생성한다(중복 no-op). **마이그레이션은 기존 clip을 대량 enqueue하지 않는다** — 과거 영상은 별도 bounded enqueuer가 날짜·batch 단위로 넣는다. claim/complete/fail은 `fn_claim_python_evidence_jobs`(live 우선·`FOR UPDATE SKIP LOCKED`·lease 만료 회수)/`fn_complete_python_evidence_job`(자기 lease만, stale 완료 거부)/`fn_fail_python_evidence_job`(retryable 지수 backoff, max 초과 시 terminal). 결과 삽입은 `fn_insert_python_evidence_run`(멱등). 모든 함수 service_role 전용·`SECURITY INVOKER SET search_path=''`. 두 테이블 RLS ENABLE + client policy 0. `clip_python_evidence_runs`는 role 무관 UPDATE/DELETE/TRUNCATE를 `0A000`으로 차단한다.

**상태:** `2026-07-17_python_evidence_universal_worker.sql` 작성 + 정적 계약 테스트 통과. **production 미적용**(S2A 구현 단계, 설계 §9 S2B에서 canary 후 적용 예정).

---

## RLS 정책 요약

| 테이블 | RLS | SELECT | INSERT | UPDATE | DELETE | 비고 |
|--------|-----|--------|--------|--------|--------|------|
| `cameras` | ON | `auth.uid() = user_id` | (정책 없음) | `auth.uid() = user_id` | `auth.uid() = user_id` | INSERT 는 백엔드 `service_role` 전담 |
| `camera_clips` | ON | `auth.uid() = user_id` | (정책 없음) | (정책 없음) | (정책 없음) | 전부 백엔드에서만 기록 |
| `clip_router_features` | ON | (정책 없음) | (정책 없음) | (정책 없음) | (정책 없음) | service_role 전용 feature-store |
| `pets` | ON | `auth.uid() = user_id` | `auth.uid() = user_id` | `auth.uid() = user_id` | `auth.uid() = user_id` | Flutter 앱에서 CRUD |
| `clip_mirrors` | ON | (정책 없음) | (정책 없음) | (정책 없음) | (정책 없음) | service_role 전용, anon/authenticated 완전 차단 |
| `labelers` | ON | (정책 없음) | (정책 없음) | (정책 없음) | (정책 없음) | service_role 전용 (clip_mirrors 동일 패턴) |
| `behavior_labels` | ON | `auth.uid() = labeled_by` OR `clip owner` | `auth.uid() = labeled_by` | `auth.uid() = labeled_by` | `auth.uid() = labeled_by` | 라벨러 멤버 체크는 백엔드 `service_role` 코드 |
| `clip_labeling_sessions` | ON | `auth.uid() = reviewed_by` | `auth.uid() = reviewed_by` | `auth.uid() = reviewed_by` | (정책 없음) | Vercel route가 bearer 권한 확인 후 service_role로 기록 |
| `labeler_applications` | ON | (정책 없음) | (정책 없음) | (정책 없음) | (정책 없음) | service_role 전용. 가입/승인은 Next.js route(`requireOwner`)+RPC로만 |
| `labeling_tutorial_sets/lessons/progress/attempts` | ON | (정책 없음) | (정책 없음) | (정책 없음) | (정책 없음) | service_role 전용. 정답 JSON 은 브라우저 직접 조회 불가. Next.js route가 bearer 확인 후 접근 |
| `clip_labeling_session_revisions` | ON | (정책 없음) | (정책 없음) | (정책 없음) | (정책 없음) | service_role 전용. owner correction 감사 기록. Next.js route(`requireOwner`)+RPC로만. **append-only 트리거로 service_role 도 UPDATE/DELETE/TRUNCATE 불가**(INSERT 만) |
| `clip_vlm_selector_runs` | ON | clip camera owner | (정책 없음) | (정책 없음) | (정책 없음) | authenticated owner read, service_role worker write |
| `clip_vlm_jobs` | ON | clip owner | (정책 없음) | (정책 없음) | (정책 없음) | shadow VLM job/result provenance. 앱 행동/하이라이트 테이블과 분리 |
| `clip_labeling_triage` | ON | (정책 없음) | (정책 없음) | (정책 없음) | (정책 없음) | service_role 전용. owner-only Next.js route(`requireOwner`)+RPC로만. anon/authenticated 완전 차단 |
| `clip_labeling_triage_events` | ON | (정책 없음) | (정책 없음) | (정책 없음) | (정책 없음) | service_role 전용 append-only 감사. **트리거로 service_role 도 UPDATE/DELETE/TRUNCATE 불가**(INSERT 만) |
| `python_evidence_jobs` | ON | (정책 없음) | (정책 없음) | (정책 없음) | (정책 없음) | service_role 전용 durable queue. claim/complete/fail RPC(`search_path=''`)로만 상태 전환 |
| `clip_python_evidence_runs` | ON | (정책 없음) | (정책 없음) | (정책 없음) | (정책 없음) | service_role 전용 append-only 결과 원장. **트리거로 service_role 도 UPDATE/DELETE/TRUNCATE 불가**(`0A000`, INSERT 만) |

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
| local-router-v3 | `create_clip_router_features` | clip_router_features 테이블 + 기존 camera_clips 백필 + camera_clips INSERT trigger + RLS ENABLE/정책 0건 |
| labeler-signup | `2026-07-13_labeler_applications.sql` | `labeler_applications` 테이블 + `(status, requested_at DESC)` 인덱스 + RLS ENABLE/정책 0건 + 기존 labelers→approved backfill + `fn_review_labeler_application` RPC. **raw SQL 로 적용**(Supabase Migrations 목록엔 미등록) |
| labeling-tutorial | `2026-07-13_labeling_tutorial.sql` | `labeling_tutorial_sets/lessons/progress/attempts` 4테이블 + partial unique(active 1개) + 불변 트리거 + activation/acknowledge/reset/waive/seed RPC 5개. 전부 RLS ENABLE/정책 0건/service_role. **apply_migration 로 등록** (2026-07-13 검증: client_policies=0) |
| labeling-tutorial(hardening) | `2026-07-13_labeling_tutorial_hardening.sql` | `protect_activated_tutorial_lesson` 트리거(active/archived lesson clip/reference/prediction/feedback 변경·삭제 차단) + `fn_seed`(draft 전용·owner VLM review 완전성) / `fn_activate`(draft 전용·verdict/feedback 완전성) CREATE OR REPLACE. **apply_migration + DB 롤백 검증**(update/delete/activate-nondraft/seed-active 4차단, 2026-07-13) |
| labeling-tutorial(hardening 2) | `2026-07-13_labeling_tutorial_hardening_2.sql` | 트리거 판단을 **OLD.tutorial_set_id 기준**으로(active lesson→draft set 이동 우회 차단) + 차단 필드 **10개**(set/position/clip/title/objective/tip/reference/prediction/reference_vlm_review/feedback) 확대. **apply_migration + DB 롤백 검증**(move/position/title/reference/delete 5차단, OLD 기준 배포 확인, 2026-07-13) |
| labeling-reference-hardening | `2026-07-13_labeling_session_revisions.sql` | `clip_labeling_session_revisions`(append-only) + `fn_revise_clip_labeling_session` RPC. owner 만 current_gt/VLM review 보정, initial_gt 불변. RLS ENABLE/정책 0건/service_role. **apply_migration + rollback probe 검증**(원자성·initial_gt 불변·reviewer/reason 차단, 2026-07-13) |
| labeling-reference-hardening | `2026-07-13_labeling_tutorial_hardening_3.sql` | `fn_seed_tutorial_lesson_from_owner` CREATE OR REPLACE — position 별 lesson 의미 preflight(§8.2) 추가. reference GT 가 lesson 목적과 안 맞으면 seed 전 `22023`. **apply_migration + rollback probe 검증**(mismatched position 차단, 2026-07-13) |
| labeling-reference-hardening | `2026-07-13_labeling_tutorial_hardening_4.sql` | 3차 preflight 를 CREATE OR REPLACE 로 대체 — (a) 검사를 `IF (조건) IS NOT TRUE` 로 바꿔 **JSON 키 누락(NULL) 도 차단**(구멍 봉인), (b) **position 3 을 `primary drinking + target ∈ {water,water_bowl,glass,floor,uncertain}`** 까지 요구(이전 `target != tool` 은 moving+wheel 통과). **apply_migration + rollback probe 검증**(누락→22023·moving✗·tool✗·drinking+water✓, 2026-07-13) |
| labeling-reference-hardening | `2026-07-13_labeling_session_revisions_append_only.sql` | `fn_block_session_revision_mutation` + BEFORE UPDATE/DELETE(row)·TRUNCATE(statement) 트리거 — **service_role 포함 누구도** revision 감사 기록 변경·삭제 불가(`0A000`), INSERT 만. `search_path=''` 고정. **apply_migration + rollback probe 검증**(UPDATE/DELETE 차단, 2026-07-13) |
| VLM candidate shadow | `2026-07-15_clip_vlm_candidate_jobs.sql` | `clip_vlm_selector_runs/jobs` + owner read RLS + service_role 전용 원자 run/job 생성·월 예산 예약 RPC. **production apply_migration 완료**, 첫 4-job Claude CLI batch 4/4 succeeded·모델 exact·비용 0 확인(2026-07-15) |
| labeling-triage-quarantine | `2026-07-15_labeling_triage.sql` + `_guard_execute_revoke.sql` | `clip_labeling_triage` + append-only events + service_role RPC 4개 + 세션 가드(`PT409`). 후속 migration은 Supabase 기본 권한으로 트리거 함수에 남은 anon/authenticated/service_role EXECUTE를 회수한다. **production apply_migration + rollback probe 완료**(세션 양방향 차단·owner/system label 허용·stale/no-op·감사로그 3종 변경 차단, 잔류 0, 2026-07-15). |
| python-evidence-universal | `2026-07-17_python_evidence_universal_worker.sql` | `python_evidence_jobs`(durable queue) + `clip_python_evidence_runs`(append-only 원장) + `motion_clips` AFTER INSERT enqueue trigger + claim/complete/fail/insert RPC(service_role, `search_path=''`, `FOR UPDATE SKIP LOCKED`, lease 회수, stale 완료 거부, terminal cap) + runs UPDATE/DELETE/TRUNCATE `0A000` 차단 + point cap 256. **production 미적용**(S2A 구현, 정적 계약 테스트 통과. 2026-07-17). |

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
