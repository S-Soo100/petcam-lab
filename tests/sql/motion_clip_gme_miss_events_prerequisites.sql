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
  started_at timestamptz NOT NULL DEFAULT now(),
  duration_sec double precision,
  r2_key text
);
CREATE TABLE public.labelers (user_id uuid PRIMARY KEY);
CREATE TABLE public.labeler_applications (
  user_id uuid PRIMARY KEY,
  status text NOT NULL DEFAULT 'pending',
  display_name text
);

-- psql의 \i는 probe 실행 cwd(repo root)를 기준으로 하므로 nested \ir 경로 중복을 피한다.
\i migrations/2026-07-23_motion_double_blind_labeling.sql

ALTER TABLE public.motion_clips
  ADD COLUMN clip_purpose text NOT NULL DEFAULT 'production';

CREATE FUNCTION public.fn_is_motion_clip_production_labeling_eligible(p_clip_id uuid)
RETURNS boolean
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = '' AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.motion_clips m
    WHERE m.id = p_clip_id
      AND m.clip_purpose = 'production'
      AND m.r2_key IS NOT NULL
  );
$$;

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
  status text NOT NULL,
  candidate_moving_sec_any_gecko numeric NOT NULL,
  visible_sec numeric NOT NULL,
  max_simultaneous_geckos integer NOT NULL,
  state_intervals jsonb NOT NULL DEFAULT '[]'::jsonb,
  detector_identity text NOT NULL DEFAULT repeat('a', 64),
  duration_sec numeric NOT NULL DEFAULT 60,
  permanent_artifact_key text NOT NULL DEFAULT 'local-probe/artifact.json.gz',
  permanent_artifact_sha256 text NOT NULL DEFAULT repeat('b', 64),
  permanent_artifact_bytes bigint NOT NULL DEFAULT 100
);
ALTER TABLE public.gme_jobs
  ADD CONSTRAINT fk_gme_jobs_result_run
  FOREIGN KEY (result_run_id) REFERENCES public.gme_runs(id) ON DELETE RESTRICT;
