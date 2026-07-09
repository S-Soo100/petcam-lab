-- Local Router v3 준비: clip별 라우터 feature-store placeholder
--
-- 목적:
--   camera_clips row가 생길 때마다 clip_router_features row를 DB trigger로 자동 생성한다.
--   백엔드/펌웨어/백필 경로가 달라도 "모든 clip에 feature row가 있다"는 불변식을 DB가 보장한다.
--
-- 운영 방식:
--   1. camera_clips INSERT → trigger가 기본 메타를 복사해 placeholder row 생성
--   2. metadata worker가 R2/로컬 mp4를 읽고 motion burst/window/baseline feature를 UPDATE
--   3. local-router v3는 영상 대신 이 테이블/JSON feature만 읽는다
--
-- 보안:
--   RLS ENABLE + 정책 0건. service_role 전용 feature-store로 시작한다.
--   앱 직접 노출이 필요해지면 owner SELECT policy 또는 curated view를 별도 migration으로 추가한다.

CREATE TABLE IF NOT EXISTS public.clip_router_features (
  clip_id UUID PRIMARY KEY REFERENCES public.camera_clips(id) ON DELETE CASCADE,
  user_id UUID NOT NULL,
  pet_id UUID,
  camera_id UUID REFERENCES public.cameras(id) ON DELETE CASCADE,
  started_at TIMESTAMPTZ NOT NULL,
  duration_sec DOUBLE PRECISION NOT NULL,
  has_motion BOOLEAN NOT NULL,
  motion_frames INT NOT NULL DEFAULT 0,
  width INT,
  height INT,
  fps DOUBLE PRECISION,

  -- window context
  window_clip_count_10m INT,
  window_clip_count_30m INT,
  window_clip_count_60m INT,
  seconds_since_prev_clip DOUBLE PRECISION,
  seconds_until_next_clip DOUBLE PRECISION,

  -- baseline context
  recent_activity_baseline DOUBLE PRECISION,
  same_hour_7d_avg_motion DOUBLE PRECISION,
  today_activity_percentile DOUBLE PRECISION,
  activity_delta_from_baseline DOUBLE PRECISION,

  -- frame-level/event-shape features
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

  -- reliability / worker bookkeeping
  evidence_reliability TEXT CHECK (
    evidence_reliability IS NULL OR evidence_reliability IN ('low', 'medium', 'high')
  ),
  feature_version TEXT NOT NULL DEFAULT 'v1',
  processing_status TEXT NOT NULL DEFAULT 'pending' CHECK (
    processing_status IN ('pending', 'processing', 'ready', 'failed')
  ),
  processing_error TEXT,
  processed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 실제 운영 DB에는 Stage D3 이전/외부 백필 row 중 camera_id가 NULL인
-- camera_clips가 있다. "모든 clip에 feature row" 불변식을 지키려면 feature-store도
-- legacy NULL camera_id를 허용하고, window context만 비워둔다.
ALTER TABLE public.clip_router_features
  ALTER COLUMN camera_id DROP NOT NULL;

CREATE INDEX IF NOT EXISTS idx_clip_router_features_camera_started
  ON public.clip_router_features(camera_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_clip_router_features_status_started
  ON public.clip_router_features(processing_status, started_at ASC);

CREATE INDEX IF NOT EXISTS idx_clip_router_features_user_started
  ON public.clip_router_features(user_id, started_at DESC);

ALTER TABLE public.clip_router_features ENABLE ROW LEVEL SECURITY;

INSERT INTO public.clip_router_features (
  clip_id,
  user_id,
  pet_id,
  camera_id,
  started_at,
  duration_sec,
  has_motion,
  motion_frames,
  width,
  height,
  fps
)
SELECT
  cc.id,
  cc.user_id,
  cc.pet_id,
  cc.camera_id,
  cc.started_at,
  cc.duration_sec,
  cc.has_motion,
  COALESCE(cc.motion_frames, 0),
  cc.width,
  cc.height,
  cc.fps
FROM public.camera_clips AS cc
ON CONFLICT (clip_id) DO UPDATE SET
  user_id = EXCLUDED.user_id,
  pet_id = EXCLUDED.pet_id,
  camera_id = EXCLUDED.camera_id,
  started_at = EXCLUDED.started_at,
  duration_sec = EXCLUDED.duration_sec,
  has_motion = EXCLUDED.has_motion,
  motion_frames = EXCLUDED.motion_frames,
  width = EXCLUDED.width,
  height = EXCLUDED.height,
  fps = EXCLUDED.fps,
  updated_at = NOW();

CREATE OR REPLACE FUNCTION public.fn_create_clip_router_features_placeholder()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  INSERT INTO public.clip_router_features (
    clip_id,
    user_id,
    pet_id,
    camera_id,
    started_at,
    duration_sec,
    has_motion,
    motion_frames,
    width,
    height,
    fps
  )
  VALUES (
    NEW.id,
    NEW.user_id,
    NEW.pet_id,
    NEW.camera_id,
    NEW.started_at,
    NEW.duration_sec,
    NEW.has_motion,
    COALESCE(NEW.motion_frames, 0),
    NEW.width,
    NEW.height,
    NEW.fps
  )
  ON CONFLICT (clip_id) DO UPDATE SET
    user_id = EXCLUDED.user_id,
    pet_id = EXCLUDED.pet_id,
    camera_id = EXCLUDED.camera_id,
    started_at = EXCLUDED.started_at,
    duration_sec = EXCLUDED.duration_sec,
    has_motion = EXCLUDED.has_motion,
    motion_frames = EXCLUDED.motion_frames,
    width = EXCLUDED.width,
    height = EXCLUDED.height,
    fps = EXCLUDED.fps,
    updated_at = NOW();

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_camera_clips_create_router_features
  ON public.camera_clips;

CREATE TRIGGER trg_camera_clips_create_router_features
  AFTER INSERT ON public.camera_clips
  FOR EACH ROW
  EXECUTE FUNCTION public.fn_create_clip_router_features_placeholder();

REVOKE ALL ON FUNCTION public.fn_create_clip_router_features_placeholder() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.fn_create_clip_router_features_placeholder() FROM anon;
REVOKE ALL ON FUNCTION public.fn_create_clip_router_features_placeholder() FROM authenticated;
GRANT EXECUTE ON FUNCTION public.fn_create_clip_router_features_placeholder() TO service_role;

COMMENT ON TABLE public.clip_router_features IS
  'Local Router용 clip feature-store. camera_clips INSERT trigger가 placeholder row를 만들고 metadata worker가 R2/OpenCV/window/baseline feature를 채운다.';

COMMENT ON FUNCTION public.fn_create_clip_router_features_placeholder() IS
  'camera_clips INSERT 시 clip_router_features placeholder row를 보장한다. service_role/trigger 전용.';
