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
| `current_gt` | 이후 교정 가능한 현재 GT |
| `prediction_snapshot` | GT 잠금 시점 exact VLM row |
| `vlm_verdict` | `correct / partially_correct / incorrect / unjudgeable` |
| `vlm_error_tags` | 행동·대상·미검출·IR·구간 등 오류 원인 |
| `completion_reason` | `vlm_reviewed / no_prediction` |

마이그레이션 파일은 `migrations/2026-07-12_clip_labeling_sessions.sql`. 2026-07-12
운영 Supabase 적용 및 REST `HTTP 200` 확인을 완료했다.

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
  활성화 뒤 clip/reference/prediction/feedback 불변(변경은 새 version).
- **`labeling_tutorial_progress`** — `PK(set,user)`. 본 큐 gate hot path = 이 한 row 의
  `completed_at`/`waived_at`. `current_run_no`·`waiver_reason`(1~200 CHECK).
- **`labeling_tutorial_attempts`** — 시도. `UNIQUE(set,lesson,user,run_no)`. 최초
  `submitted_gt`/`submitted_vlm_review`/`comparison` 은 trigger(`protect_tutorial_attempt`)로 불변.

**RPC (모두 SECURITY DEFINER, service_role EXECUTE 전용):**
- `fn_activate_tutorial_set(set, owner)` — position 1..5·기준 snapshot 완전성 검사 후 active 전환(기존 active archive).
- `fn_acknowledge_tutorial_lesson(attempt, user)` — 피드백 확인→lesson completed, 5개면 같은 트랜잭션에서 progress completed.
- `fn_reset_tutorial(set, user, owner)` — `current_run_no + 1`, 기존 attempt 보존.
- `fn_waive_tutorial(set, user, owner, reason)` — 완료 면제(사유 1~200자, audit 보존).
- `fn_seed_tutorial_lesson_from_owner(...)` — owner 완료 `clip_labeling_sessions` 에서 기준 답 복사(seed).

4 테이블 모두 RLS ENABLE + 정책 0건 + service_role GRANT. 마이그레이션 파일
`migrations/2026-07-13_labeling_tutorial.sql`. 2026-07-13 Supabase 적용·검증 완료
(`client_policies=0`, RLS 4/4, funcs 6). **raw SQL(apply_migration)로 적용.**

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
