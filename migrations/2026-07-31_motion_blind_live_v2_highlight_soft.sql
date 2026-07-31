-- Daily live 교차검수의 highlight-only 완화를 slot 생성 시점 버전으로 고정한다.
-- Formal/canary와 기존 live 원장은 motion-blind-v1을 그대로 유지한다.

BEGIN;

ALTER TABLE public.motion_clip_review_slots
  ADD COLUMN comparator_version text NOT NULL DEFAULT 'motion-blind-v1'
  CHECK (comparator_version IN (
    'motion-blind-v1',
    'motion-blind-live-v2-highlight-soft'
  ));

COMMENT ON COLUMN public.motion_clip_review_slots.comparator_version IS
  'Slot 생성 시 고정되는 비교기 버전. 기존/canary/formal=v1, 2026-08-01 이후 신규 live=v2.';

CREATE OR REPLACE FUNCTION public.fn_set_motion_blind_slot_comparator_version()
RETURNS trigger
LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN
  IF TG_OP = 'UPDATE' THEN
    IF OLD.comparator_version IS DISTINCT FROM NEW.comparator_version THEN
      RAISE EXCEPTION 'slot comparator version is immutable'
        USING ERRCODE = '0A000';
    END IF;
    RETURN NEW;
  END IF;

  IF NEW.cohort_kind = 'canary' THEN
    NEW.comparator_version := 'motion-blind-v1';
  ELSIF NEW.activity_day_kst >= DATE '2026-08-01' THEN
    NEW.comparator_version := 'motion-blind-live-v2-highlight-soft';
  ELSE
    NEW.comparator_version := 'motion-blind-v1';
  END IF;
  RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.fn_set_motion_blind_slot_comparator_version() FROM PUBLIC, anon, authenticated;

CREATE TRIGGER trg_set_motion_blind_slot_comparator_version
  BEFORE INSERT ON public.motion_clip_review_slots
  FOR EACH ROW EXECUTE FUNCTION public.fn_set_motion_blind_slot_comparator_version();

CREATE TRIGGER trg_guard_motion_blind_slot_comparator_version_update
  BEFORE UPDATE OF comparator_version ON public.motion_clip_review_slots
  FOR EACH ROW EXECUTE FUNCTION public.fn_set_motion_blind_slot_comparator_version();

CREATE OR REPLACE FUNCTION public.fn_guard_motion_blind_consensus_comparator_version()
RETURNS trigger
LANGUAGE plpgsql SET search_path = '' AS $$
DECLARE
  v_slot_count integer;
  v_version_count integer;
  v_slot_version text;
  v_min_activity_day date;
BEGIN
  IF NOT (
    OLD.status = 'awaiting'
    AND NEW.status IN ('agreed', 'conflict')
  ) THEN
    RETURN NEW;
  END IF;

  PERFORM 1
  FROM public.motion_clip_review_slots s
  WHERE s.clip_id = NEW.clip_id
    AND s.cohort_kind = NEW.cohort_kind
    AND s.cohort_id IS NOT DISTINCT FROM NEW.cohort_id
  ORDER BY s.id
  FOR UPDATE;

  SELECT
    COUNT(*),
    COUNT(DISTINCT s.comparator_version),
    MIN(s.comparator_version),
    MIN(s.activity_day_kst)
  INTO
    v_slot_count,
    v_version_count,
    v_slot_version,
    v_min_activity_day
  FROM public.motion_clip_review_slots s
  WHERE s.clip_id = NEW.clip_id
    AND s.cohort_kind = NEW.cohort_kind
    AND s.cohort_id IS NOT DISTINCT FROM NEW.cohort_id;

  IF v_slot_count <> 2 THEN
    RAISE EXCEPTION 'consensus requires exactly two versioned slots'
      USING ERRCODE = 'PT425';
  END IF;
  IF v_version_count <> 1 THEN
    RAISE EXCEPTION 'slot comparator versions are not uniform'
      USING ERRCODE = 'PT425';
  END IF;
  IF NEW.comparator_version IS DISTINCT FROM v_slot_version THEN
    RAISE EXCEPTION 'consensus comparator does not match slot snapshot'
      USING ERRCODE = '22023';
  END IF;
  IF NEW.cohort_kind = 'canary'
     AND NEW.comparator_version <> 'motion-blind-v1' THEN
    RAISE EXCEPTION 'canary comparator must remain motion-blind-v1'
      USING ERRCODE = '22023';
  END IF;
  IF NEW.comparator_version = 'motion-blind-live-v2-highlight-soft'
     AND (
       NEW.cohort_kind <> 'live'
       OR v_min_activity_day < DATE '2026-08-01'
     ) THEN
    RAISE EXCEPTION 'live v2 comparator is outside its activation boundary'
      USING ERRCODE = '22023';
  END IF;
  IF NEW.comparator_version NOT IN (
    'motion-blind-v1',
    'motion-blind-live-v2-highlight-soft'
  ) THEN
    RAISE EXCEPTION 'unknown comparator version'
      USING ERRCODE = '22023';
  END IF;

  RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.fn_guard_motion_blind_consensus_comparator_version() FROM PUBLIC, anon, authenticated;

CREATE TRIGGER trg_guard_motion_blind_consensus_comparator_version
  BEFORE UPDATE OF status, comparator_version ON public.motion_clip_consensus
  FOR EACH ROW
  EXECUTE FUNCTION public.fn_guard_motion_blind_consensus_comparator_version();

CREATE OR REPLACE FUNCTION public.fn_finalize_motion_blind_consensus(
  p_clip_id uuid,
  p_cohort_kind text,
  p_cohort_id uuid,
  p_submission_a uuid,
  p_submission_b uuid,
  p_digest_a text,
  p_digest_b text,
  p_comparator_version text,
  p_status text,
  p_final_decision text,
  p_final_gt jsonb,
  p_differing_fields text[]
) RETURNS public.motion_clip_consensus
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  v_a public.motion_clip_blind_submissions%ROWTYPE;
  v_b public.motion_clip_blind_submissions%ROWTYPE;
  v_slot_a public.motion_clip_review_slots%ROWTYPE;
  v_slot_b public.motion_clip_review_slots%ROWTYPE;
  v_consensus public.motion_clip_consensus%ROWTYPE;
  v_did_transition boolean := false;
BEGIN
  IF p_comparator_version NOT IN (
    'motion-blind-v1',
    'motion-blind-live-v2-highlight-soft'
  ) THEN
    RAISE EXCEPTION 'unknown comparator version' USING ERRCODE = '22023';
  END IF;
  IF p_status NOT IN ('agreed','conflict') THEN
    RAISE EXCEPTION 'invalid finalize status' USING ERRCODE = '22023';
  END IF;

  IF p_status = 'agreed' THEN
    IF p_final_decision IS NULL OR p_final_decision NOT IN ('label','hold','exclude') THEN
      RAISE EXCEPTION 'agreed requires final decision' USING ERRCODE = '22023';
    END IF;
    IF p_final_decision = 'label'
       AND (p_final_gt IS NULL OR jsonb_typeof(p_final_gt) <> 'object') THEN
      RAISE EXCEPTION 'agreed label requires final gt object' USING ERRCODE = '22023';
    END IF;
    IF p_final_decision <> 'label' AND p_final_gt IS NOT NULL THEN
      RAISE EXCEPTION 'agreed non-label forbids final gt' USING ERRCODE = '22023';
    END IF;
  ELSE
    IF p_final_decision IS NOT NULL OR p_final_gt IS NOT NULL THEN
      RAISE EXCEPTION 'conflict forbids final decision and gt' USING ERRCODE = '22023';
    END IF;
  END IF;

  SELECT * INTO v_consensus FROM public.motion_clip_consensus c
    WHERE c.clip_id = p_clip_id AND c.cohort_kind = p_cohort_kind
      AND (c.cohort_id IS NOT DISTINCT FROM p_cohort_id)
    FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'consensus not found' USING ERRCODE = 'P0002';
  END IF;

  PERFORM 1 FROM public.motion_clip_review_slots
    WHERE id IN (
      SELECT slot_id FROM public.motion_clip_blind_submissions
      WHERE id IN (p_submission_a, p_submission_b))
    ORDER BY id
    FOR UPDATE;

  PERFORM 1 FROM public.motion_clip_blind_submissions
    WHERE id IN (p_submission_a, p_submission_b)
    ORDER BY id
    FOR UPDATE;
  SELECT * INTO v_a FROM public.motion_clip_blind_submissions WHERE id = p_submission_a;
  IF NOT FOUND THEN RAISE EXCEPTION 'submission not found' USING ERRCODE = 'P0002'; END IF;
  SELECT * INTO v_b FROM public.motion_clip_blind_submissions WHERE id = p_submission_b;
  IF NOT FOUND THEN RAISE EXCEPTION 'submission not found' USING ERRCODE = 'P0002'; END IF;

  SELECT * INTO v_slot_a FROM public.motion_clip_review_slots WHERE id = v_a.slot_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'submission slot not found' USING ERRCODE = 'P0002'; END IF;
  SELECT * INTO v_slot_b FROM public.motion_clip_review_slots WHERE id = v_b.slot_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'submission slot not found' USING ERRCODE = 'P0002'; END IF;

  IF v_a.digest <> p_digest_a OR v_b.digest <> p_digest_b THEN
    RAISE EXCEPTION 'stale_state' USING ERRCODE = 'PT409';
  END IF;

  IF p_submission_a = p_submission_b
     OR v_a.clip_id <> p_clip_id
     OR v_b.clip_id <> p_clip_id
     OR v_a.group_id <> v_b.group_id
     OR v_a.group_id <> v_consensus.group_id
     OR v_a.reviewer_id = v_b.reviewer_id
     OR v_a.cohort_kind <> p_cohort_kind
     OR v_b.cohort_kind <> p_cohort_kind
     OR v_a.cohort_id IS DISTINCT FROM p_cohort_id
     OR v_b.cohort_id IS DISTINCT FROM p_cohort_id
  THEN
    RAISE EXCEPTION 'finalize pair identity violation' USING ERRCODE = '22023';
  END IF;

  IF v_slot_a.clip_id <> v_a.clip_id
     OR v_slot_b.clip_id <> v_b.clip_id
     OR v_slot_a.group_id <> v_a.group_id
     OR v_slot_b.group_id <> v_b.group_id
     OR v_slot_a.reviewer_id <> v_a.reviewer_id
     OR v_slot_b.reviewer_id <> v_b.reviewer_id
     OR v_slot_a.cohort_kind <> v_a.cohort_kind
     OR v_slot_b.cohort_kind <> v_b.cohort_kind
     OR v_slot_a.cohort_id IS DISTINCT FROM v_a.cohort_id
     OR v_slot_b.cohort_id IS DISTINCT FROM v_b.cohort_id
     OR v_slot_a.clip_id <> p_clip_id
     OR v_slot_b.clip_id <> p_clip_id
     OR v_slot_a.group_id <> v_consensus.group_id
     OR v_slot_b.group_id <> v_consensus.group_id
  THEN
    RAISE EXCEPTION 'finalize slot identity violation' USING ERRCODE = '22023';
  END IF;

  IF v_consensus.status = 'awaiting' THEN
    UPDATE public.motion_clip_consensus
      SET status = p_status, comparator_version = p_comparator_version,
          submission_a = p_submission_a, submission_b = p_submission_b,
          final_decision = p_final_decision, final_gt = p_final_gt,
          differing_fields = COALESCE(p_differing_fields, '{}'),
          updated_at = clock_timestamp()
      WHERE id = v_consensus.id
      RETURNING * INTO v_consensus;
    v_did_transition := true;
  END IF;

  IF v_did_transition THEN
    INSERT INTO public.motion_clip_consensus_events
      (clip_id, group_id, cohort_kind, cohort_id, event_type, actor_id,
       comparator_version, result_status, differing_fields, before_state, after_state)
    VALUES (p_clip_id, v_consensus.group_id, p_cohort_kind, p_cohort_id, 'auto_compared', NULL,
       p_comparator_version, v_consensus.status, v_consensus.differing_fields,
       NULL, to_jsonb(v_consensus));
  END IF;

  RETURN v_consensus;
END;
$$;

REVOKE ALL ON FUNCTION public.fn_finalize_motion_blind_consensus(
  uuid, text, uuid, uuid, uuid, text, text, text, text, text, jsonb, text[]
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_finalize_motion_blind_consensus(
  uuid, text, uuid, uuid, uuid, text, text, text, text, text, jsonb, text[]
) TO service_role;

COMMIT;
