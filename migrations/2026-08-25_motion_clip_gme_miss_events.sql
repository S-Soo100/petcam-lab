BEGIN;

-- 라벨러가 영상 재생 중 발견한 GME 미탐 시점을 사람 GT와 분리해 보존한다.
-- browser에는 run UUID·detector identity·R2 key를 노출하지 않고, service_role RPC가
-- 현재 성공 run을 다시 조회해 provenance를 채운다.
CREATE TABLE public.motion_clip_gme_miss_events (
  id uuid PRIMARY KEY,
  clip_id uuid NOT NULL REFERENCES public.motion_clips(id) ON DELETE RESTRICT,
  reviewer_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
  cohort_kind text NOT NULL CHECK (cohort_kind IN ('live','canary')),
  cohort_id uuid REFERENCES public.motion_blind_review_cohorts(id) ON DELETE RESTRICT,
  gme_run_id uuid NOT NULL REFERENCES public.gme_runs(id) ON DELETE RESTRICT,
  detector_identity text NOT NULL CHECK (detector_identity ~ '^[0-9a-f]{64}$'),
  permanent_artifact_sha256 text NOT NULL
    CHECK (permanent_artifact_sha256 ~ '^[0-9a-f]{64}$'),
  timestamp_sec numeric NOT NULL CHECK (
    timestamp_sec >= 0 AND timestamp_sec = round(timestamp_sec, 3)
  ),
  digest text NOT NULL CHECK (digest ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CHECK ((cohort_kind = 'live' AND cohort_id IS NULL)
      OR (cohort_kind = 'canary' AND cohort_id IS NOT NULL)),
  -- digest에 live/canary scope까지 포함해 같은 scope의 재시도만 멱등 처리한다.
  CONSTRAINT uq_motion_clip_gme_miss_event_digest UNIQUE (digest)
);

COMMENT ON TABLE public.motion_clip_gme_miss_events IS
  '라벨러가 제보한 GME 미탐 시점의 immutable provenance 원장. 사람 GT/consensus와 분리된다.';

CREATE INDEX idx_motion_clip_gme_miss_events_clip
  ON public.motion_clip_gme_miss_events (clip_id, created_at DESC);
CREATE INDEX idx_motion_clip_gme_miss_events_run
  ON public.motion_clip_gme_miss_events (gme_run_id, timestamp_sec);

CREATE FUNCTION public.fn_block_motion_clip_gme_miss_mutation()
RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
BEGIN
  RAISE EXCEPTION 'motion clip GME miss events are append-only'
    USING ERRCODE = '0A000';
END;
$$;

CREATE TRIGGER trg_motion_clip_gme_miss_events_no_update_delete
  BEFORE UPDATE OR DELETE ON public.motion_clip_gme_miss_events
  FOR EACH ROW EXECUTE FUNCTION public.fn_block_motion_clip_gme_miss_mutation();

CREATE TRIGGER trg_motion_clip_gme_miss_events_no_truncate
  BEFORE TRUNCATE ON public.motion_clip_gme_miss_events
  FOR EACH STATEMENT EXECUTE FUNCTION public.fn_block_motion_clip_gme_miss_mutation();

ALTER TABLE public.motion_clip_gme_miss_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.motion_clip_gme_miss_events
  FROM PUBLIC, anon, authenticated, service_role;

CREATE FUNCTION public.fn_append_motion_clip_gme_miss(
  p_event_id uuid,
  p_clip_id uuid,
  p_reviewer_id uuid,
  p_cohort_kind text,
  p_cohort_id uuid,
  p_gme_run_id uuid,
  p_overlay_revision text,
  p_timestamp_sec numeric
) RETURNS TABLE (
  event_id uuid,
  timestamp_sec numeric,
  status text
)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
  v_run public.gme_runs%ROWTYPE;
  v_timestamp numeric;
  v_duration numeric;
  v_digest text;
BEGIN
  IF p_event_id IS NULL OR p_clip_id IS NULL OR p_reviewer_id IS NULL
     OR p_gme_run_id IS NULL OR p_overlay_revision IS NULL
     OR p_timestamp_sec IS NULL THEN
    RAISE EXCEPTION 'required parameter is missing' USING ERRCODE = '22023';
  END IF;
  IF p_cohort_kind NOT IN ('live','canary') THEN
    RAISE EXCEPTION 'invalid cohort kind' USING ERRCODE = '22023';
  END IF;
  IF (p_cohort_kind = 'canary') <> (p_cohort_id IS NOT NULL) THEN
    RAISE EXCEPTION 'cohort scope mismatch' USING ERRCODE = '22023';
  END IF;
  IF p_overlay_revision !~ '^[0-9a-f]{64}$' OR p_timestamp_sec < 0 THEN
    RAISE EXCEPTION 'invalid overlay revision or timestamp' USING ERRCODE = '22023';
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM public.motion_clip_review_slots s
    WHERE s.clip_id = p_clip_id
      AND s.reviewer_id = p_reviewer_id
      AND s.cohort_kind = p_cohort_kind
      AND s.cohort_id IS NOT DISTINCT FROM p_cohort_id
  ) THEN
    RAISE EXCEPTION 'reviewer is not assigned to this clip'
      USING ERRCODE = 'PT403';
  END IF;

  IF p_cohort_kind = 'canary' AND NOT EXISTS (
    SELECT 1
    FROM public.motion_blind_review_cohorts c
    WHERE c.id = p_cohort_id
      AND c.kind = 'canary'
      AND c.status = 'open'
  ) THEN
    RAISE EXCEPTION 'canary cohort is closed or missing'
      USING ERRCODE = 'PT427';
  END IF;

  SELECT r.* INTO v_run
  FROM public.gme_jobs j
  JOIN public.gme_runs r ON j.result_run_id = r.id
  WHERE j.clip_id = p_clip_id
    AND j.status = 'succeeded'
    AND j.result_run_id = r.id
    AND r.status = 'ok'
  ORDER BY j.completed_at DESC NULLS LAST, j.id DESC
  LIMIT 1;

  IF NOT FOUND OR v_run.id <> p_gme_run_id
     OR v_run.permanent_artifact_sha256 IS DISTINCT FROM p_overlay_revision THEN
    RAISE EXCEPTION 'overlay_changed' USING ERRCODE = 'PT409';
  END IF;
  IF v_run.detector_identity IS NULL
     OR v_run.detector_identity !~ '^[0-9a-f]{64}$'
     OR v_run.permanent_artifact_sha256 !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'current GME run provenance is incomplete'
      USING ERRCODE = 'PT409';
  END IF;

  SELECT m.duration_sec::numeric INTO v_duration
  FROM public.motion_clips m
  WHERE m.id = p_clip_id;
  v_timestamp := round(p_timestamp_sec, 3);
  IF v_duration IS NULL OR v_timestamp > v_duration THEN
    RAISE EXCEPTION 'timestamp is outside the clip duration'
      USING ERRCODE = '22023';
  END IF;

  v_digest := encode(sha256(convert_to(
    concat_ws('|', p_clip_id::text, p_reviewer_id::text, p_cohort_kind,
      coalesce(p_cohort_id::text, ''), v_run.id::text,
      v_run.detector_identity, v_run.permanent_artifact_sha256,
      v_timestamp::text),
    'UTF8'
  )), 'hex');

  INSERT INTO public.motion_clip_gme_miss_events (
    id, clip_id, reviewer_id, cohort_kind, cohort_id, gme_run_id,
    detector_identity, permanent_artifact_sha256, timestamp_sec, digest
  ) VALUES (
    p_event_id, p_clip_id, p_reviewer_id, p_cohort_kind, p_cohort_id, v_run.id,
    v_run.detector_identity, v_run.permanent_artifact_sha256, v_timestamp, v_digest
  )
  ON CONFLICT ON CONSTRAINT uq_motion_clip_gme_miss_event_digest DO NOTHING;

  RETURN QUERY
  SELECT e.id, e.timestamp_sec, 'recorded'::text
  FROM public.motion_clip_gme_miss_events e
  WHERE e.clip_id = p_clip_id
    AND e.reviewer_id = p_reviewer_id
    AND e.cohort_kind = p_cohort_kind
    AND e.cohort_id IS NOT DISTINCT FROM p_cohort_id
    AND e.gme_run_id = v_run.id
    AND e.timestamp_sec = v_timestamp;
END;
$$;

REVOKE ALL ON FUNCTION public.fn_append_motion_clip_gme_miss(
  uuid, uuid, uuid, text, uuid, uuid, text, numeric
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_append_motion_clip_gme_miss(
  uuid, uuid, uuid, text, uuid, uuid, text, numeric
) TO service_role;

COMMIT;
