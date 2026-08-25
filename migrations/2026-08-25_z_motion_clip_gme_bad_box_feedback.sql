BEGIN;

-- 이미 운영에 적용된 통합 원장을 다시 쓰지 않고, bbox 위치·크기 오류를 새 종류로 확장한다.
ALTER TABLE public.motion_clip_gme_feedback_events
  DROP CONSTRAINT motion_clip_gme_feedback_events_feedback_kind_check;
ALTER TABLE public.motion_clip_gme_feedback_events
  ADD CONSTRAINT motion_clip_gme_feedback_events_feedback_kind_check
  CHECK (feedback_kind IN ('miss','false_positive','bad_box'));

CREATE OR REPLACE FUNCTION public.fn_append_motion_clip_gme_feedback(
  p_event_id uuid,
  p_clip_id uuid,
  p_reviewer_id uuid,
  p_feedback_kind text,
  p_surface text,
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
     OR p_feedback_kind IS NULL OR p_surface IS NULL OR p_gme_run_id IS NULL
     OR p_overlay_revision IS NULL OR p_timestamp_sec IS NULL THEN
    RAISE EXCEPTION 'required parameter is missing' USING ERRCODE = '22023';
  END IF;
  IF p_feedback_kind NOT IN ('miss','false_positive','bad_box')
     OR p_surface NOT IN ('blind_live','blind_canary','owner_direct') THEN
    RAISE EXCEPTION 'invalid feedback kind or surface' USING ERRCODE = '22023';
  END IF;
  IF (p_surface = 'blind_canary') <> (p_cohort_id IS NOT NULL) THEN
    RAISE EXCEPTION 'cohort scope mismatch' USING ERRCODE = '22023';
  END IF;
  IF p_surface = 'owner_direct' AND p_cohort_id IS NOT NULL THEN
    RAISE EXCEPTION 'owner direct feedback cannot have a cohort' USING ERRCODE = '22023';
  END IF;
  IF p_overlay_revision !~ '^[0-9a-f]{64}$' OR p_timestamp_sec < 0 THEN
    RAISE EXCEPTION 'invalid overlay revision or timestamp' USING ERRCODE = '22023';
  END IF;

  IF p_surface IN ('blind_live','blind_canary') AND NOT EXISTS (
    SELECT 1
    FROM public.motion_clip_review_slots s
    WHERE s.clip_id = p_clip_id
      AND s.reviewer_id = p_reviewer_id
      AND s.cohort_kind = CASE WHEN p_surface = 'blind_canary' THEN 'canary' ELSE 'live' END
      AND s.cohort_id IS NOT DISTINCT FROM p_cohort_id
  ) THEN
    RAISE EXCEPTION 'reviewer is not assigned to this clip'
      USING ERRCODE = 'PT403';
  END IF;

  IF p_surface = 'blind_canary' AND NOT EXISTS (
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
    concat_ws('|', p_clip_id::text, p_reviewer_id::text, p_feedback_kind,
      p_surface, coalesce(p_cohort_id::text, ''), v_run.id::text,
      v_run.detector_identity, v_run.permanent_artifact_sha256,
      v_timestamp::text),
    'UTF8'
  )), 'hex');

  INSERT INTO public.motion_clip_gme_feedback_events (
    id, clip_id, reviewer_id, feedback_kind, surface, cohort_id, gme_run_id,
    detector_identity, permanent_artifact_sha256, timestamp_sec, digest
  ) VALUES (
    p_event_id, p_clip_id, p_reviewer_id, p_feedback_kind, p_surface, p_cohort_id,
    v_run.id, v_run.detector_identity, v_run.permanent_artifact_sha256,
    v_timestamp, v_digest
  )
  ON CONFLICT ON CONSTRAINT uq_motion_clip_gme_feedback_digest DO NOTHING;

  RETURN QUERY
  SELECT e.id, e.timestamp_sec, 'recorded'::text
  FROM public.motion_clip_gme_feedback_events e
  WHERE e.digest = v_digest;
END;
$$;

REVOKE ALL ON FUNCTION public.fn_append_motion_clip_gme_feedback(
  uuid, uuid, uuid, text, text, uuid, uuid, text, numeric
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_append_motion_clip_gme_feedback(
  uuid, uuid, uuid, text, text, uuid, uuid, text, numeric
) TO service_role;

COMMENT ON TABLE public.motion_clip_gme_feedback_events IS
  '라벨러가 제보한 GME 미탐·오탐·부정확 bbox 시점의 immutable provenance 원장. 사람 GT/consensus와 분리된다.';

COMMIT;
