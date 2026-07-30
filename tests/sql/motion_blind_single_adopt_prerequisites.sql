-- single-adopt provenance read migration이 참조하는 terminal exclusion 원장 최소 fixture.
-- production 스키마를 흉내 내는 일회용 local probe 전용이며 production에는 적용하지 않는다.

CREATE TABLE public.motion_clip_system_exclusions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  clip_id uuid NOT NULL UNIQUE REFERENCES public.motion_clips(id) ON DELETE RESTRICT,
  camera_id uuid NOT NULL REFERENCES public.cameras(id) ON DELETE RESTRICT,
  state text NOT NULL CHECK (
    state IN ('candidate','quarantined','restored','media_deleted','deletion_blocked')
  ),
  reason_code text NOT NULL CHECK (reason_code = 'short_device_error'),
  rule_version text NOT NULL,
  observed_duration_sec double precision NOT NULL CHECK (observed_duration_sec >= 0),
  displayed_duration_sec integer NOT NULL CHECK (displayed_duration_sec >= 0),
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
  CHECK (
    state NOT IN ('quarantined','media_deleted')
    OR (quarantined_at IS NOT NULL AND delete_after IS NOT NULL)
  ),
  CHECK (state <> 'media_deleted' OR media_deleted_at IS NOT NULL),
  CHECK (
    delete_result_fingerprint IS NULL
    OR delete_result_fingerprint ~ '^[0-9a-f]{64}$'
  ),
  CHECK ((delete_lease_token IS NULL) = (delete_lease_expires_at IS NULL))
);

ALTER TABLE public.motion_clip_system_exclusions ENABLE ROW LEVEL SECURITY;
GRANT SELECT ON TABLE public.motion_clip_system_exclusions TO service_role;
CREATE POLICY motion_clip_system_exclusions_service_read
  ON public.motion_clip_system_exclusions FOR SELECT TO service_role USING (true);

-- Supabase service_role이 이미 가진 base table read 권한을 disposable bare Postgres에도 맞춘다.
GRANT SELECT ON TABLE public.motion_clips, public.cameras TO service_role;
