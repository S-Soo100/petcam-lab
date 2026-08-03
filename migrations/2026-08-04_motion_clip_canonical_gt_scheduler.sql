-- Supabase pg_cron 기반 canonical GT projector scheduler.
-- config는 기본 disabled라 이 migration만으로 projection write가 시작되지 않는다.

BEGIN;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_catalog.pg_extension WHERE extname = 'pg_cron'
  ) THEN
    RAISE EXCEPTION 'pg_cron_required' USING ERRCODE = 'PT503';
  END IF;
END;
$$;

CREATE TABLE public.motion_clip_gt_projection_config (
  singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
  owner_id uuid,
  enabled boolean NOT NULL DEFAULT false,
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CHECK (NOT enabled OR owner_id IS NOT NULL)
);

INSERT INTO public.motion_clip_gt_projection_config(singleton, owner_id, enabled)
VALUES (true, NULL, false)
ON CONFLICT (singleton) DO NOTHING;

ALTER TABLE public.motion_clip_gt_projection_config ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.motion_clip_gt_projection_config FROM PUBLIC, anon, authenticated;
GRANT ALL ON TABLE public.motion_clip_gt_projection_config TO service_role;

CREATE OR REPLACE FUNCTION public.fn_configure_motion_clip_gt_projection(
  p_actor_id uuid,
  p_enabled boolean
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  v_config public.motion_clip_gt_projection_config%ROWTYPE;
BEGIN
  IF p_actor_id IS NULL OR p_enabled IS NULL THEN
    RAISE EXCEPTION 'actor_and_enabled_required' USING ERRCODE = '22023';
  END IF;
  UPDATE public.motion_clip_gt_projection_config
  SET owner_id = p_actor_id,
      enabled = p_enabled,
      updated_at = clock_timestamp()
  WHERE singleton
  RETURNING * INTO v_config;
  RETURN jsonb_build_object(
    'enabled', v_config.enabled,
    'updated_at', v_config.updated_at
  );
END;
$$;

CREATE OR REPLACE FUNCTION public.fn_run_motion_clip_canonical_gt_schedule()
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  v_config public.motion_clip_gt_projection_config%ROWTYPE;
  v_run_id uuid := gen_random_uuid();
  v_started_at timestamptz := clock_timestamp();
  v_result jsonb;
BEGIN
  SELECT * INTO v_config
  FROM public.motion_clip_gt_projection_config
  WHERE singleton;
  IF NOT FOUND OR NOT v_config.enabled OR v_config.owner_id IS NULL THEN
    RETURN jsonb_build_object('status', 'disabled');
  END IF;

  BEGIN
    v_result := public.fn_project_motion_clip_canonical_gt(
      v_config.owner_id, true, 500, NULL, v_run_id
    );
    PERFORM public.fn_record_motion_clip_gt_projection_run(
      v_run_id,
      'succeeded',
      COALESCE((v_result->>'scanned')::integer, 0),
      COALESCE((v_result->>'inserted')::integer, 0),
      NULL,
      v_started_at
    );
    RETURN jsonb_build_object('status', 'succeeded', 'run_id', v_run_id, 'result', v_result);
  EXCEPTION WHEN OTHERS THEN
    -- 내부 block의 projection write는 먼저 rollback되고 안정 코드만 별도 기록돼.
    PERFORM public.fn_record_motion_clip_gt_projection_run(
      v_run_id, 'failed', 0, 0, 'projection_schedule_failed', v_started_at
    );
    RETURN jsonb_build_object(
      'status', 'failed', 'run_id', v_run_id,
      'error_code', 'projection_schedule_failed'
    );
  END;
END;
$$;

REVOKE ALL ON FUNCTION public.fn_configure_motion_clip_gt_projection(uuid, boolean)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_configure_motion_clip_gt_projection(uuid, boolean)
  TO service_role;

REVOKE ALL ON FUNCTION public.fn_run_motion_clip_canonical_gt_schedule()
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_run_motion_clip_canonical_gt_schedule()
  TO service_role;

DO $$
DECLARE
  v_job_id bigint;
BEGIN
  SELECT j.jobid INTO v_job_id
  FROM cron.job j
  WHERE j.jobname = 'canonical-motion-gt-projector-v1';

  IF v_job_id IS NULL THEN
    PERFORM cron.schedule(
      'canonical-motion-gt-projector-v1',
      '*/10 * * * *',
      'SELECT public.fn_run_motion_clip_canonical_gt_schedule()'
    );
  ELSE
    PERFORM cron.alter_job(
      v_job_id,
      schedule => '*/10 * * * *',
      command => 'SELECT public.fn_run_motion_clip_canonical_gt_schedule()'
    );
  END IF;
END;
$$;

COMMIT;

-- Rollback은 먼저 config를 false로 바꾼 뒤 아래 job만 이름으로 해제해.
-- SELECT cron.unschedule('canonical-motion-gt-projector-v1');
