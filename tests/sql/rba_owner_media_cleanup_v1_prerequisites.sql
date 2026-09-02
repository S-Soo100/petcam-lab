CREATE EXTENSION IF NOT EXISTS pgcrypto;
DO $$ BEGIN CREATE ROLE anon; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE authenticated; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE service_role; EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE public.cameras (
  id uuid PRIMARY KEY,
  name text NOT NULL
);
CREATE TABLE public.motion_clips (
  id uuid PRIMARY KEY,
  camera_id uuid NOT NULL REFERENCES public.cameras(id),
  started_at timestamptz NOT NULL,
  duration_sec double precision,
  r2_key text,
  thumbnail_key text
);

CREATE TABLE public.motion_clip_labeling_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  clip_id uuid NOT NULL REFERENCES public.motion_clips(id),
  initial_gt jsonb,
  current_gt jsonb
);

CREATE TABLE public.motion_clip_consensus (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  clip_id uuid NOT NULL REFERENCES public.motion_clips(id),
  status text NOT NULL,
  final_decision text,
  final_gt jsonb
);

CREATE TABLE public.rba_boundary_review_pairs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  left_clip_id uuid NOT NULL REFERENCES public.motion_clips(id),
  right_clip_id uuid NOT NULL REFERENCES public.motion_clips(id)
);

CREATE TABLE public.rba_boundary_eligibility_reviews (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  pair_id uuid NOT NULL REFERENCES public.rba_boundary_review_pairs(id),
  decision text NOT NULL
);

CREATE TABLE public.rba_boundary_eligibility_corrections (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  review_id uuid NOT NULL REFERENCES public.rba_boundary_eligibility_reviews(id),
  replacement_decision text
);

CREATE TABLE public.motion_clip_system_exclusions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  clip_id uuid NOT NULL UNIQUE REFERENCES public.motion_clips(id),
  camera_id uuid NOT NULL REFERENCES public.cameras(id),
  state text NOT NULL,
  reason_code text NOT NULL,
  rule_version text NOT NULL,
  observed_duration_sec double precision NOT NULL,
  displayed_duration_sec integer NOT NULL,
  detected_at timestamptz NOT NULL,
  quarantined_at timestamptz,
  delete_after timestamptz,
  restored_at timestamptz,
  restored_by uuid,
  restore_reason text,
  media_deleted_at timestamptz,
  delete_lease_token uuid,
  delete_lease_expires_at timestamptz,
  delete_worker_host text,
  delete_result_code text,
  delete_result_fingerprint text,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT motion_clip_system_exclusions_reason_code_check
    CHECK (reason_code = 'short_device_error')
);
