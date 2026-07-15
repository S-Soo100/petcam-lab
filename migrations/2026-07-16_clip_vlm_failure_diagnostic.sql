-- Safe cli_rc_1 diagnostic for clip_vlm_jobs (design §8.1). Forward-only, idempotent.
-- Adds a nullable jsonb column that stores ONLY redacted, allowlisted failure metadata.
-- Raw stdout/stderr, email, token, full path, full UUID must NEVER be written here.
-- Existing RLS policies and grants on clip_vlm_jobs are unchanged by this migration.

ALTER TABLE public.clip_vlm_jobs
  ADD COLUMN IF NOT EXISTS failure_diagnostic jsonb;

-- object-or-null only: NULL on success, a redacted JSON object on diagnosed failure.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'clip_vlm_jobs_failure_diagnostic_object_or_null'
  ) THEN
    ALTER TABLE public.clip_vlm_jobs
      ADD CONSTRAINT clip_vlm_jobs_failure_diagnostic_object_or_null
      CHECK (failure_diagnostic IS NULL OR jsonb_typeof(failure_diagnostic) = 'object');
  END IF;
END $$;

COMMENT ON COLUMN public.clip_vlm_jobs.failure_diagnostic IS
  'Redacted CLI failure diagnostic (design §8.1). Allowlisted keys only: version, phase, code, exit_code, fingerprint, markers, stdout_bytes, stderr_bytes, provider_subattempts, recovered. Never store raw stdout/stderr, email, token, full path, or full UUID.';

-- Rollback:
--   ALTER TABLE public.clip_vlm_jobs DROP CONSTRAINT IF EXISTS clip_vlm_jobs_failure_diagnostic_object_or_null;
--   ALTER TABLE public.clip_vlm_jobs DROP COLUMN IF EXISTS failure_diagnostic;
