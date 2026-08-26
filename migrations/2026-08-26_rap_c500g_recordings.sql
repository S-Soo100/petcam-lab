-- RAP C500G 장시간 연구 원본 전용 원장.
-- 기존 camera_clips/motion_clips/GME/GT 소비자와 의도적으로 분리한다.

CREATE TABLE public.rap_c500g_recordings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  bundle_id TEXT NOT NULL UNIQUE,
  mode TEXT NOT NULL CHECK (mode IN ('test', 'production')),
  camera_key TEXT NOT NULL CHECK (camera_key IN ('cam01', 'cam02', 'cam03')),
  test_run_id TEXT,
  night_date DATE,
  scheduled_start_utc TIMESTAMPTZ NOT NULL,
  actual_start_utc TIMESTAMPTZ NOT NULL,
  ended_at_utc TIMESTAMPTZ,
  partial BOOLEAN NOT NULL DEFAULT FALSE,
  duration_sec DOUBLE PRECISION NOT NULL CHECK (duration_sec > 0),
  codec TEXT NOT NULL CHECK (codec IN ('hevc', 'h264')),
  width INTEGER NOT NULL CHECK (width > 0),
  height INTEGER NOT NULL CHECK (height > 0),
  fps DOUBLE PRECISION NOT NULL CHECK (fps > 0),
  video_size_bytes BIGINT NOT NULL CHECK (video_size_bytes >= 0),
  video_sha256 TEXT NOT NULL CHECK (video_sha256 ~ '^[0-9a-f]{64}$'),
  video_r2_key TEXT,
  thumbnail_r2_key TEXT,
  log_r2_key TEXT,
  manifest_r2_key TEXT,
  relative_bundle_path TEXT NOT NULL CHECK (relative_bundle_path !~ '^/'),
  capture_status TEXT NOT NULL CHECK (
    capture_status IN ('capturing', 'captured', 'capture_failed')
  ),
  upload_status TEXT NOT NULL CHECK (
    upload_status IN ('pending', 'uploading', 'uploaded', 'upload_failed', 'integrity_conflict')
  ),
  upload_attempts INTEGER NOT NULL DEFAULT 0 CHECK (upload_attempts >= 0),
  last_error_code TEXT,
  uploaded_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK ((mode = 'test' AND test_run_id IS NOT NULL AND night_date IS NULL)
      OR (mode = 'production' AND test_run_id IS NULL AND night_date IS NOT NULL)),
  CHECK (upload_status <> 'uploaded' OR manifest_r2_key IS NOT NULL),
  CHECK (upload_status <> 'uploaded' OR uploaded_at IS NOT NULL)
);

CREATE UNIQUE INDEX rap_c500g_recordings_logical_segment_uidx
  ON public.rap_c500g_recordings (
    mode,
    camera_key,
    scheduled_start_utc,
    COALESCE(test_run_id, '')
  );

CREATE INDEX rap_c500g_recordings_night_camera_idx
  ON public.rap_c500g_recordings (night_date DESC, camera_key, scheduled_start_utc);

CREATE INDEX rap_c500g_recordings_upload_status_idx
  ON public.rap_c500g_recordings (upload_status, scheduled_start_utc);

ALTER TABLE public.rap_c500g_recordings ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.rap_c500g_recordings FROM anon, authenticated;
GRANT ALL ON TABLE public.rap_c500g_recordings TO service_role;

COMMENT ON TABLE public.rap_c500g_recordings IS
  'RAP C500G 연구 원본 bundle의 capture/R2 검증 원장. service-role 전용.';
