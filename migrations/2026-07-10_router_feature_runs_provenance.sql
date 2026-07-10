-- Router feature provenance + versioned run history.
-- Applied manually in Supabase SQL Editor on 2026-07-10.
-- Additive only: no existing data deletion or column rewrites.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

ALTER TABLE public.clip_router_features
  ADD COLUMN IF NOT EXISTS active_feature_run_id UUID,
  ADD COLUMN IF NOT EXISTS producer_name TEXT,
  ADD COLUMN IF NOT EXISTS producer_host TEXT,
  ADD COLUMN IF NOT EXISTS producer_run_id TEXT,
  ADD COLUMN IF NOT EXISTS producer_code_ref TEXT,
  ADD COLUMN IF NOT EXISTS feature_params JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE IF NOT EXISTS public.clip_router_feature_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  clip_id UUID NOT NULL REFERENCES public.camera_clips(id) ON DELETE CASCADE,

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

  processing_status TEXT NOT NULL DEFAULT 'ready' CHECK (
    processing_status IN ('ready', 'failed')
  ),
  processing_error TEXT,

  input_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
  output_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,

  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  CONSTRAINT clip_router_feature_runs_unique_run_clip
    UNIQUE (producer_run_id, clip_id)
);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'clip_router_features_active_feature_run_id_fkey'
  ) THEN
    ALTER TABLE public.clip_router_features
      ADD CONSTRAINT clip_router_features_active_feature_run_id_fkey
      FOREIGN KEY (active_feature_run_id)
      REFERENCES public.clip_router_feature_runs(id)
      ON DELETE SET NULL;
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_clip_router_feature_runs_clip_created
  ON public.clip_router_feature_runs(clip_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_clip_router_feature_runs_version_created
  ON public.clip_router_feature_runs(feature_version, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_clip_router_feature_runs_producer_run
  ON public.clip_router_feature_runs(producer_run_id);

CREATE INDEX IF NOT EXISTS idx_clip_router_feature_runs_reliability
  ON public.clip_router_feature_runs(evidence_reliability);

CREATE INDEX IF NOT EXISTS idx_clip_router_feature_runs_created_brin
  ON public.clip_router_feature_runs USING brin(created_at);

CREATE INDEX IF NOT EXISTS idx_clip_router_feature_runs_params_gin
  ON public.clip_router_feature_runs USING gin(feature_params);

CREATE INDEX IF NOT EXISTS idx_clip_router_features_active_run
  ON public.clip_router_features(active_feature_run_id);

ALTER TABLE public.clip_router_feature_runs ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.clip_router_feature_runs FROM anon;
REVOKE ALL ON public.clip_router_feature_runs FROM authenticated;
GRANT ALL ON public.clip_router_feature_runs TO service_role;

COMMENT ON COLUMN public.clip_router_features.active_feature_run_id IS
  '현재 운영 snapshot이 어떤 clip_router_feature_runs row에서 왔는지 가리킨다.';

COMMENT ON COLUMN public.clip_router_features.producer_name IS
  'metadata를 생성한 worker/process 이름. 예: router-feature-worker.';

COMMENT ON COLUMN public.clip_router_features.producer_host IS
  'metadata를 생성한 머신/호스트. 예: home-mac.';

COMMENT ON COLUMN public.clip_router_features.producer_run_id IS
  'worker 실행 또는 batch 단위 run id. 같은 실행에서 만든 feature를 묶는다.';

COMMENT ON COLUMN public.clip_router_features.producer_code_ref IS
  'metadata 생성 코드 버전. 보통 git commit hash.';

COMMENT ON COLUMN public.clip_router_features.feature_params IS
  'sample_frames, threshold, OpenCV version 등 feature 생성 파라미터 JSON.';

COMMENT ON TABLE public.clip_router_feature_runs IS
  'Local Router feature generation history. 같은 clip을 여러 version/params로 재처리한 결과를 비교하기 위한 append-only 연구/감사용 테이블.';
