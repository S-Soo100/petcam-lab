-- 사건 이어짐 자격검사 사유 분리:
-- 기존 판정은 보존하고 활동 오탐·영상 오류를 A/B/둘 다로 기록한다.

BEGIN;

ALTER TABLE public.rba_boundary_eligibility_reviews
  DROP CONSTRAINT IF EXISTS rba_boundary_eligibility_reviews_decision_check;
ALTER TABLE public.rba_boundary_eligibility_reviews
  ADD CONSTRAINT rba_boundary_eligibility_reviews_decision_check CHECK (
    decision IN (
      'eligible','left_gecko_absent','right_gecko_absent',
      'both_gecko_absent','capture_or_media_error',
      'left_no_gecko_activity','right_no_gecko_activity','both_no_gecko_activity',
      'left_capture_or_media_error','right_capture_or_media_error',
      'both_capture_or_media_error'
    )
  );

CREATE TABLE public.rba_boundary_eligibility_corrections (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  review_id uuid NOT NULL UNIQUE
    REFERENCES public.rba_boundary_eligibility_reviews(id) ON DELETE RESTRICT,
  pair_id uuid NOT NULL UNIQUE
    REFERENCES public.rba_boundary_review_pairs(id) ON DELETE RESTRICT,
  owner_id uuid NOT NULL,
  replacement_decision text NOT NULL CHECK (
    replacement_decision IN (
      'eligible','left_gecko_absent','right_gecko_absent',
      'both_gecko_absent','capture_or_media_error',
      'left_no_gecko_activity','right_no_gecko_activity','both_no_gecko_activity',
      'left_capture_or_media_error','right_capture_or_media_error',
      'both_capture_or_media_error'
    )
  ),
  reason text NOT NULL CHECK (char_length(btrim(reason)) >= 3),
  digest text NOT NULL,
  submitted_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_rba_boundary_eligibility_correction_owner
  ON public.rba_boundary_eligibility_corrections (owner_id, submitted_at);
ALTER TABLE public.rba_boundary_eligibility_corrections ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.rba_boundary_eligibility_corrections
  FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT ON TABLE public.rba_boundary_eligibility_corrections TO service_role;

CREATE TRIGGER trg_rba_boundary_eligibility_correction_append_only
  BEFORE UPDATE OR DELETE OR TRUNCATE ON public.rba_boundary_eligibility_corrections
  FOR EACH STATEMENT EXECUTE FUNCTION public.fn_reject_rba_boundary_history_mutation();

CREATE FUNCTION public.fn_record_rba_boundary_eligibility_correction(
  p_owner_id uuid, p_pair_id uuid, p_replacement_decision text, p_reason text
) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  v_review_id uuid;
  v_original_decision text;
  v_original_digest text;
  v_expected_owner uuid;
  v_status text;
  v_correction_id uuid;
BEGIN
  IF p_replacement_decision NOT IN (
    'eligible','left_gecko_absent','right_gecko_absent',
    'both_gecko_absent','capture_or_media_error',
    'left_no_gecko_activity','right_no_gecko_activity','both_no_gecko_activity',
    'left_capture_or_media_error','right_capture_or_media_error',
    'both_capture_or_media_error'
  ) OR char_length(btrim(coalesce(p_reason, ''))) < 3 THEN
    RAISE EXCEPTION 'invalid_eligibility_correction' USING ERRCODE = '22023';
  END IF;

  SELECT r.id, r.decision, r.digest, c.owner_id, c.status
  INTO v_review_id, v_original_decision, v_original_digest, v_expected_owner, v_status
  FROM public.rba_boundary_eligibility_reviews r
  JOIN public.rba_boundary_review_pairs p ON p.id = r.pair_id
  JOIN public.rba_boundary_review_cohorts c ON c.id = p.cohort_id
  WHERE r.pair_id = p_pair_id AND p.split = 'development'
  FOR UPDATE OF c;
  IF v_review_id IS NULL OR v_expected_owner <> p_owner_id THEN
    RAISE EXCEPTION 'owner_forbidden' USING ERRCODE = 'PT403';
  END IF;
  IF v_status <> 'eligibility_open' THEN
    RAISE EXCEPTION 'eligibility_closed' USING ERRCODE = 'PT409';
  END IF;
  IF v_original_decision = p_replacement_decision THEN
    RAISE EXCEPTION 'correction_must_change_decision' USING ERRCODE = '22023';
  END IF;

  INSERT INTO public.rba_boundary_eligibility_corrections
    (review_id, pair_id, owner_id, replacement_decision, reason, digest)
  VALUES (
    v_review_id, p_pair_id, p_owner_id, p_replacement_decision, btrim(p_reason),
    md5(v_original_digest || '|' || p_replacement_decision || '|' || btrim(p_reason))
  )
  ON CONFLICT (review_id) DO NOTHING
  RETURNING id INTO v_correction_id;
  IF v_correction_id IS NULL THEN
    RAISE EXCEPTION 'already_corrected' USING ERRCODE = 'PT410';
  END IF;

  RETURN jsonb_build_object(
    'corrected', true,
    'pair_id', p_pair_id,
    'original_decision', v_original_decision,
    'replacement_decision', p_replacement_decision
  );
END;
$$;

REVOKE ALL ON FUNCTION public.fn_record_rba_boundary_eligibility_correction(uuid, uuid, text, text)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_record_rba_boundary_eligibility_correction(uuid, uuid, text, text)
  TO service_role;

CREATE OR REPLACE FUNCTION public.fn_submit_rba_boundary_eligibility(
  p_owner_id uuid, p_pair_id uuid, p_decision text
) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  v_cohort_id uuid;
  v_expected_owner uuid;
  v_status text;
  v_review_id uuid;
  v_reviewed_count integer;
  v_valid_count integer := 0;
BEGIN
  IF p_decision NOT IN (
    'eligible','left_gecko_absent','right_gecko_absent',
    'both_gecko_absent','capture_or_media_error',
    'left_no_gecko_activity','right_no_gecko_activity','both_no_gecko_activity',
    'left_capture_or_media_error','right_capture_or_media_error',
    'both_capture_or_media_error'
  ) THEN
    RAISE EXCEPTION 'invalid_eligibility_decision' USING ERRCODE = '22023';
  END IF;

  SELECT c.id, c.owner_id, c.status
  INTO v_cohort_id, v_expected_owner, v_status
  FROM public.rba_boundary_review_pairs p
  JOIN public.rba_boundary_review_cohorts c ON c.id = p.cohort_id
  WHERE p.id = p_pair_id AND p.split = 'development'
  FOR UPDATE OF c;
  IF v_cohort_id IS NULL OR v_expected_owner <> p_owner_id THEN
    RAISE EXCEPTION 'owner_forbidden' USING ERRCODE = 'PT403';
  END IF;
  IF v_status <> 'eligibility_open' THEN
    RAISE EXCEPTION 'eligibility_closed' USING ERRCODE = 'PT409';
  END IF;

  INSERT INTO public.rba_boundary_eligibility_reviews
    (pair_id, owner_id, decision, digest)
  VALUES (
    p_pair_id, p_owner_id, p_decision,
    md5(p_pair_id::text || '|' || p_decision)
  )
  ON CONFLICT (pair_id) DO NOTHING
  RETURNING id INTO v_review_id;
  IF v_review_id IS NULL THEN
    RAISE EXCEPTION 'already_submitted' USING ERRCODE = 'PT410';
  END IF;

  SELECT count(*) INTO v_reviewed_count
  FROM public.rba_boundary_eligibility_reviews r
  JOIN public.rba_boundary_review_pairs p ON p.id = r.pair_id
  WHERE p.cohort_id = v_cohort_id;

  IF v_reviewed_count = 120 THEN
    WITH effective_reviews AS (
      SELECT r.pair_id, coalesce(x.replacement_decision, r.decision) AS decision
      FROM public.rba_boundary_eligibility_reviews r
      LEFT JOIN public.rba_boundary_eligibility_corrections x ON x.review_id = r.id
    ), invalid_clips AS (
      SELECT p.left_clip_id AS clip_id
      FROM public.rba_boundary_review_pairs p
      JOIN effective_reviews r ON r.pair_id = p.id
      WHERE p.cohort_id = v_cohort_id
        AND r.decision IN (
          'left_gecko_absent','both_gecko_absent',
          'left_no_gecko_activity','both_no_gecko_activity',
          'left_capture_or_media_error','both_capture_or_media_error'
        )
      UNION
      SELECT p.right_clip_id AS clip_id
      FROM public.rba_boundary_review_pairs p
      JOIN effective_reviews r ON r.pair_id = p.id
      WHERE p.cohort_id = v_cohort_id
        AND r.decision IN (
          'right_gecko_absent','both_gecko_absent',
          'right_no_gecko_activity','both_no_gecko_activity',
          'right_capture_or_media_error','both_capture_or_media_error'
        )
    ), valid_pairs AS (
      SELECT p.id
      FROM public.rba_boundary_review_pairs p
      JOIN effective_reviews r ON r.pair_id = p.id
      WHERE p.cohort_id = v_cohort_id AND r.decision = 'eligible'
        AND NOT EXISTS (
          SELECT 1 FROM invalid_clips i
          WHERE i.clip_id IN (p.left_clip_id, p.right_clip_id)
        )
    )
    SELECT count(*) INTO v_valid_count FROM valid_pairs;

    IF v_valid_count >= 60 THEN
      WITH effective_reviews AS (
        SELECT r.pair_id, coalesce(x.replacement_decision, r.decision) AS decision
        FROM public.rba_boundary_eligibility_reviews r
        LEFT JOIN public.rba_boundary_eligibility_corrections x ON x.review_id = r.id
      ), invalid_clips AS (
        SELECT p.left_clip_id AS clip_id
        FROM public.rba_boundary_review_pairs p
        JOIN effective_reviews r ON r.pair_id = p.id
        WHERE p.cohort_id = v_cohort_id
          AND r.decision IN (
            'left_gecko_absent','both_gecko_absent',
            'left_no_gecko_activity','both_no_gecko_activity',
            'left_capture_or_media_error','both_capture_or_media_error'
          )
        UNION
        SELECT p.right_clip_id AS clip_id
        FROM public.rba_boundary_review_pairs p
        JOIN effective_reviews r ON r.pair_id = p.id
        WHERE p.cohort_id = v_cohort_id
          AND r.decision IN (
            'right_gecko_absent','both_gecko_absent',
            'right_no_gecko_activity','both_no_gecko_activity',
            'right_capture_or_media_error','both_capture_or_media_error'
          )
      ), valid_pairs AS (
        SELECT p.id
        FROM public.rba_boundary_review_pairs p
        JOIN effective_reviews r ON r.pair_id = p.id
        WHERE p.cohort_id = v_cohort_id AND r.decision = 'eligible'
          AND NOT EXISTS (
            SELECT 1 FROM invalid_clips i
            WHERE i.clip_id IN (p.left_clip_id, p.right_clip_id)
          )
      )
      INSERT INTO public.rba_boundary_review_assignments
        (pair_id, reviewer_id, reviewer_role)
      SELECT v.id, reviewers.reviewer_id, reviewers.reviewer_role
      FROM valid_pairs v
      CROSS JOIN LATERAL (
        SELECT c.owner_id AS reviewer_id, 'owner'::text AS reviewer_role
        FROM public.rba_boundary_review_cohorts c WHERE c.id = v_cohort_id
        UNION ALL
        SELECT c.peer_id AS reviewer_id, 'peer'::text AS reviewer_role
        FROM public.rba_boundary_review_cohorts c WHERE c.id = v_cohort_id
      ) reviewers;
      UPDATE public.rba_boundary_review_cohorts
      SET status = 'development_open', updated_at = now()
      WHERE id = v_cohort_id;
      v_status := 'development_open';
    ELSE
      UPDATE public.rba_boundary_review_cohorts
      SET status = 'insufficient_valid', updated_at = now()
      WHERE id = v_cohort_id;
      v_status := 'insufficient_valid';
    END IF;
  END IF;

  RETURN jsonb_build_object(
    'submitted', true,
    'pair_id', p_pair_id,
    'completed', v_reviewed_count,
    'valid_count', CASE WHEN v_reviewed_count = 120 THEN v_valid_count ELSE NULL END,
    'status', v_status
  );
END;
$$;

REVOKE ALL ON FUNCTION public.fn_submit_rba_boundary_eligibility(uuid, uuid, text)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_submit_rba_boundary_eligibility(uuid, uuid, text)
  TO service_role;

COMMIT;
