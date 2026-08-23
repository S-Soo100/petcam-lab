-- GME negative-audit migration이 소비하는 외부 schema의 disposable 최소 계약.
-- 실제 사용자/영상/GT/GME row는 복사하지 않고 probe가 만든 합성 UUID만 사용한다.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
    CREATE ROLE anon NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
    CREATE ROLE authenticated NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
    CREATE ROLE service_role NOLOGIN;
  END IF;
END $$;

CREATE SCHEMA IF NOT EXISTS auth;
CREATE TABLE auth.users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid()
);

CREATE TABLE public.cameras (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text
);

CREATE TABLE public.motion_clips (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  camera_id uuid REFERENCES public.cameras(id),
  started_at timestamptz NOT NULL,
  duration_sec double precision NOT NULL,
  r2_key text
);

-- Audit migration은 current human consensus의 아래 다섯 컬럼만 읽는다.
CREATE TABLE public.motion_clip_consensus (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  clip_id uuid NOT NULL REFERENCES public.motion_clips(id) ON DELETE RESTRICT,
  status text NOT NULL,
  final_decision text,
  final_gt jsonb
);

CREATE TABLE public.gme_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  clip_id uuid NOT NULL REFERENCES public.motion_clips(id) ON DELETE RESTRICT,
  status text NOT NULL,
  result_run_id uuid,
  completed_at timestamptz
);

CREATE TABLE public.gme_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  clip_id uuid NOT NULL REFERENCES public.motion_clips(id) ON DELETE RESTRICT,
  job_id uuid NOT NULL REFERENCES public.gme_jobs(id) ON DELETE RESTRICT,
  detector_identity text NOT NULL,
  status text NOT NULL,
  candidate_moving_sec_any_gecko numeric NOT NULL,
  visible_sec numeric NOT NULL,
  max_simultaneous_geckos integer NOT NULL,
  state_intervals jsonb NOT NULL DEFAULT '[]'::jsonb
);

ALTER TABLE public.gme_jobs
  ADD CONSTRAINT fk_gme_negative_probe_result_run
  FOREIGN KEY (result_run_id) REFERENCES public.gme_runs(id) ON DELETE RESTRICT;

-- Production 함수와 같은 current pointer semantics. Audit import는 run_id/detected만 소비한다.
CREATE FUNCTION public.fn_current_gme_activity(p_clip_id uuid)
RETURNS TABLE (
  run_id uuid,
  detected boolean,
  activity_sec numeric,
  visible_sec numeric,
  state_intervals jsonb
)
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = '' AS $$
  SELECT
    run.id,
    (run.visible_sec > 0 AND run.max_simultaneous_geckos > 0),
    run.candidate_moving_sec_any_gecko,
    run.visible_sec,
    run.state_intervals
  FROM public.gme_jobs job
  JOIN public.gme_runs run ON run.id = job.result_run_id
  WHERE job.clip_id = p_clip_id
    AND job.status = 'succeeded'
    AND run.status = 'ok'
  ORDER BY job.completed_at DESC NULLS LAST, job.id DESC
  LIMIT 1;
$$;
