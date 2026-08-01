-- 사건 이어짐 v2: Owner 자격 선별 뒤 유효한 연속 경계만 두 사람에게 배정한다.
-- 기존 잘못된 cohort와 사람 답 테이블은 삭제하지 않고 감사 이력으로 보존한다.

BEGIN;

ALTER TABLE public.rba_boundary_review_cohorts
  DROP CONSTRAINT IF EXISTS rba_boundary_review_cohorts_status_check;
ALTER TABLE public.rba_boundary_review_cohorts
  ADD CONSTRAINT rba_boundary_review_cohorts_status_check CHECK (
    status IN (
      'prepared','eligibility_open','development_open','development_frozen',
      'holdout_open','insufficient_valid','invalid_eligibility','closed'
    )
  );
ALTER TABLE public.rba_boundary_review_cohorts
  ADD COLUMN owner_id uuid,
  ADD COLUMN peer_id uuid,
  ADD COLUMN invalidated_reason text,
  ADD COLUMN invalidated_at timestamptz,
  ADD CONSTRAINT rba_boundary_review_cohorts_reviewers_differ
    CHECK (owner_id IS NULL OR peer_id IS NULL OR owner_id <> peer_id);

DROP INDEX IF EXISTS public.uq_rba_boundary_single_open_cohort;
CREATE UNIQUE INDEX uq_rba_boundary_single_open_cohort
  ON public.rba_boundary_review_cohorts ((true))
  WHERE status IN ('eligibility_open','development_open','holdout_open');

CREATE TABLE public.rba_boundary_eligibility_reviews (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  pair_id uuid NOT NULL UNIQUE
    REFERENCES public.rba_boundary_review_pairs(id) ON DELETE RESTRICT,
  owner_id uuid NOT NULL,
  decision text NOT NULL CHECK (
    decision IN (
      'eligible','left_gecko_absent','right_gecko_absent',
      'both_gecko_absent','capture_or_media_error'
    )
  ),
  digest text NOT NULL,
  submitted_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_rba_boundary_eligibility_owner
  ON public.rba_boundary_eligibility_reviews (owner_id, submitted_at);
ALTER TABLE public.rba_boundary_eligibility_reviews ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.rba_boundary_eligibility_reviews
  FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT ON TABLE public.rba_boundary_eligibility_reviews TO service_role;

CREATE TRIGGER trg_rba_boundary_eligibility_append_only
  BEFORE UPDATE OR DELETE OR TRUNCATE ON public.rba_boundary_eligibility_reviews
  FOR EACH STATEMENT EXECUTE FUNCTION public.fn_reject_rba_boundary_history_mutation();

-- eligibility 중에는 owner와 peer 모두 메뉴 접근만 가능하다. pair는 owner에게만 반환한다.
CREATE OR REPLACE FUNCTION public.fn_get_rba_boundary_access(p_reviewer_id uuid)
RETURNS jsonb
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = '' AS $$
  SELECT jsonb_build_object(
    'enabled',
      EXISTS (
        SELECT 1 FROM public.rba_boundary_review_cohorts c
        WHERE c.status = 'eligibility_open'
          AND p_reviewer_id IN (c.owner_id, c.peer_id)
      ) OR EXISTS (
        SELECT 1
        FROM public.rba_boundary_review_assignments a
        JOIN public.rba_boundary_review_pairs p ON p.id = a.pair_id
        JOIN public.rba_boundary_review_cohorts c ON c.id = p.cohort_id
        WHERE a.reviewer_id = p_reviewer_id
          AND (
            (c.status = 'development_open' AND p.split = 'development')
            OR (c.status = 'holdout_open' AND p.split = 'holdout')
          )
      )
  );
$$;

-- 기존 키를 유지하고 mode만 additive로 추가해 migration→웹 배포 사이 구 UI도 깨지지 않는다.
CREATE OR REPLACE FUNCTION public.fn_get_rba_boundary_workspace(p_reviewer_id uuid)
RETURNS jsonb
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = '' AS $$
  WITH active_eligibility AS (
    SELECT c.*
    FROM public.rba_boundary_review_cohorts c
    WHERE c.status = 'eligibility_open'
      AND p_reviewer_id IN (c.owner_id, c.peer_id)
    ORDER BY c.created_at DESC
    LIMIT 1
  ), eligibility_rows AS (
    SELECT p.id AS pair_id, p.ordinal, p.gap_sec, p.gap_bin,
           p.left_clip_id, p.right_clip_id,
           lm.started_at AS left_started_at, lm.duration_sec AS left_duration_sec,
           lc.name AS left_camera_name,
           rm.started_at AS right_started_at, rm.duration_sec AS right_duration_sec,
           rc.name AS right_camera_name,
           r.submitted_at
    FROM active_eligibility c
    JOIN public.rba_boundary_review_pairs p ON p.cohort_id = c.id
    JOIN public.motion_clips lm ON lm.id = p.left_clip_id
    JOIN public.motion_clips rm ON rm.id = p.right_clip_id
    LEFT JOIN public.cameras lc ON lc.id = lm.camera_id
    LEFT JOIN public.cameras rc ON rc.id = rm.camera_id
    LEFT JOIN public.rba_boundary_eligibility_reviews r ON r.pair_id = p.id
    WHERE c.owner_id = p_reviewer_id AND p.split = 'development'
  ), next_eligibility AS (
    SELECT * FROM eligibility_rows WHERE submitted_at IS NULL ORDER BY ordinal LIMIT 1
  ), assigned AS (
    SELECT a.id AS assignment_id, a.reviewer_role, p.id AS pair_id, p.ordinal, p.split,
           p.gap_sec, p.gap_bin, p.left_clip_id, p.right_clip_id,
           lm.started_at AS left_started_at, lm.duration_sec AS left_duration_sec,
           lc.name AS left_camera_name,
           rm.started_at AS right_started_at, rm.duration_sec AS right_duration_sec,
           rc.name AS right_camera_name,
           s.submitted_at
    FROM public.rba_boundary_review_assignments a
    JOIN public.rba_boundary_review_pairs p ON p.id = a.pair_id
    JOIN public.rba_boundary_review_cohorts c ON c.id = p.cohort_id
    JOIN public.motion_clips lm ON lm.id = p.left_clip_id
    JOIN public.motion_clips rm ON rm.id = p.right_clip_id
    LEFT JOIN public.cameras lc ON lc.id = lm.camera_id
    LEFT JOIN public.cameras rc ON rc.id = rm.camera_id
    LEFT JOIN public.rba_boundary_review_submissions s ON s.assignment_id = a.id
    WHERE a.reviewer_id = p_reviewer_id
      AND (
        (c.status = 'development_open' AND p.split = 'development')
        OR (c.status = 'holdout_open' AND p.split = 'holdout')
      )
  ), next_boundary AS (
    SELECT * FROM assigned WHERE submitted_at IS NULL ORDER BY ordinal LIMIT 1
  ), state AS (
    SELECT
      EXISTS (SELECT 1 FROM active_eligibility) AS has_eligibility,
      EXISTS (SELECT 1 FROM active_eligibility WHERE owner_id = p_reviewer_id) AS is_eligibility_owner,
      EXISTS (SELECT 1 FROM assigned) AS has_assignment
  )
  SELECT jsonb_build_object(
    'enabled', has_eligibility OR has_assignment,
    'mode', CASE
      WHEN is_eligibility_owner THEN 'eligibility'
      WHEN has_eligibility THEN 'waiting'
      WHEN has_assignment THEN 'boundary'
      ELSE 'waiting'
    END,
    'reviewer_role', CASE
      WHEN is_eligibility_owner THEN 'owner'
      WHEN has_eligibility THEN 'peer'
      ELSE (SELECT reviewer_role FROM assigned LIMIT 1)
    END,
    'split', CASE
      WHEN is_eligibility_owner THEN 'development'
      WHEN has_assignment THEN (SELECT split FROM assigned LIMIT 1)
      ELSE NULL
    END,
    'total', CASE
      WHEN is_eligibility_owner THEN (SELECT count(*) FROM eligibility_rows)
      WHEN has_assignment THEN (SELECT count(*) FROM assigned)
      ELSE 0
    END,
    'completed', CASE
      WHEN is_eligibility_owner THEN (SELECT count(*) FROM eligibility_rows WHERE submitted_at IS NOT NULL)
      WHEN has_assignment THEN (SELECT count(*) FROM assigned WHERE submitted_at IS NOT NULL)
      ELSE 0
    END,
    'next_pair', CASE
      WHEN is_eligibility_owner THEN (
        SELECT jsonb_build_object(
          'pair_id', pair_id, 'ordinal', ordinal, 'gap_sec', gap_sec, 'gap_bin', gap_bin,
          'left', jsonb_build_object(
            'clip_id', left_clip_id, 'started_at', left_started_at,
            'duration_sec', left_duration_sec, 'camera_name', left_camera_name
          ),
          'right', jsonb_build_object(
            'clip_id', right_clip_id, 'started_at', right_started_at,
            'duration_sec', right_duration_sec, 'camera_name', right_camera_name
          )
        ) FROM next_eligibility
      )
      WHEN has_assignment THEN (
        SELECT jsonb_build_object(
          'pair_id', pair_id, 'ordinal', ordinal, 'gap_sec', gap_sec, 'gap_bin', gap_bin,
          'left', jsonb_build_object(
            'clip_id', left_clip_id, 'started_at', left_started_at,
            'duration_sec', left_duration_sec, 'camera_name', left_camera_name
          ),
          'right', jsonb_build_object(
            'clip_id', right_clip_id, 'started_at', right_started_at,
            'duration_sec', right_duration_sec, 'camera_name', right_camera_name
          )
        ) FROM next_boundary
      )
      ELSE NULL
    END
  ) FROM state;
$$;

CREATE OR REPLACE FUNCTION public.fn_get_rba_boundary_pair_media(
  p_reviewer_id uuid, p_pair_id uuid, p_side text
) RETURNS TABLE (r2_key text)
LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  v_clip_id uuid;
BEGIN
  IF p_side NOT IN ('left','right') THEN
    RAISE EXCEPTION 'invalid_side' USING ERRCODE = '22023';
  END IF;

  SELECT allowed.clip_id INTO v_clip_id
  FROM (
    SELECT CASE WHEN p_side = 'left' THEN p.left_clip_id ELSE p.right_clip_id END AS clip_id
    FROM public.rba_boundary_review_pairs p
    JOIN public.rba_boundary_review_cohorts c ON c.id = p.cohort_id
    LEFT JOIN public.rba_boundary_eligibility_reviews r ON r.pair_id = p.id
    WHERE p.id = p_pair_id AND c.status = 'eligibility_open'
      AND c.owner_id = p_reviewer_id AND r.id IS NULL
    UNION ALL
    SELECT CASE WHEN p_side = 'left' THEN p.left_clip_id ELSE p.right_clip_id END AS clip_id
    FROM public.rba_boundary_review_assignments a
    JOIN public.rba_boundary_review_pairs p ON p.id = a.pair_id
    JOIN public.rba_boundary_review_cohorts c ON c.id = p.cohort_id
    WHERE a.reviewer_id = p_reviewer_id AND p.id = p_pair_id
      AND (
        (c.status = 'development_open' AND p.split = 'development')
        OR (c.status = 'holdout_open' AND p.split = 'holdout')
      )
  ) allowed
  LIMIT 1;
  IF v_clip_id IS NULL THEN
    RAISE EXCEPTION 'reviewer_forbidden' USING ERRCODE = 'PT403';
  END IF;

  RETURN QUERY
  SELECT m.r2_key
  FROM public.motion_clips m
  WHERE m.id = v_clip_id AND m.r2_key IS NOT NULL
    AND NOT EXISTS (
      SELECT 1 FROM public.motion_clip_system_exclusions sx
      WHERE sx.clip_id = m.id AND sx.state IN ('quarantined','media_deleted')
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.fn_submit_rba_boundary_decision(
  p_reviewer_id uuid, p_pair_id uuid, p_decision text
) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  v_assignment public.rba_boundary_review_assignments%rowtype;
  v_open boolean;
  v_id uuid;
BEGIN
  IF p_decision NOT IN ('same_event','different_event','uncertain') THEN
    RAISE EXCEPTION 'invalid_decision' USING ERRCODE = '22023';
  END IF;

  SELECT a.* INTO v_assignment
  FROM public.rba_boundary_review_assignments a
  WHERE a.reviewer_id = p_reviewer_id AND a.pair_id = p_pair_id
  FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'reviewer_forbidden' USING ERRCODE = 'PT403';
  END IF;
  SELECT (
    (c.status = 'development_open' AND p.split = 'development')
    OR (c.status = 'holdout_open' AND p.split = 'holdout')
  ) INTO v_open
  FROM public.rba_boundary_review_pairs p
  JOIN public.rba_boundary_review_cohorts c ON c.id = p.cohort_id
  WHERE p.id = p_pair_id
  FOR SHARE OF c;
  IF NOT v_open THEN
    RAISE EXCEPTION 'split_closed' USING ERRCODE = 'PT409';
  END IF;

  INSERT INTO public.rba_boundary_review_submissions
    (assignment_id, pair_id, reviewer_id, decision, digest)
  VALUES (
    v_assignment.id, p_pair_id, p_reviewer_id, p_decision,
    md5(v_assignment.id::text || '|' || p_decision)
  )
  ON CONFLICT (assignment_id) DO NOTHING
  RETURNING id INTO v_id;
  IF v_id IS NULL THEN
    RAISE EXCEPTION 'already_submitted' USING ERRCODE = 'PT410';
  END IF;
  RETURN jsonb_build_object('submitted', true, 'pair_id', p_pair_id);
END;
$$;

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
    'both_gecko_absent','capture_or_media_error'
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
    WITH invalid_clips AS (
      SELECT p.left_clip_id AS clip_id
      FROM public.rba_boundary_review_pairs p
      JOIN public.rba_boundary_eligibility_reviews r ON r.pair_id = p.id
      WHERE p.cohort_id = v_cohort_id
        AND r.decision IN ('left_gecko_absent','both_gecko_absent')
      UNION
      SELECT p.right_clip_id AS clip_id
      FROM public.rba_boundary_review_pairs p
      JOIN public.rba_boundary_eligibility_reviews r ON r.pair_id = p.id
      WHERE p.cohort_id = v_cohort_id
        AND r.decision IN ('right_gecko_absent','both_gecko_absent')
    ), valid_pairs AS (
      SELECT p.id
      FROM public.rba_boundary_review_pairs p
      JOIN public.rba_boundary_eligibility_reviews r ON r.pair_id = p.id
      WHERE p.cohort_id = v_cohort_id AND r.decision = 'eligible'
        AND NOT EXISTS (
          SELECT 1 FROM invalid_clips i
          WHERE i.clip_id IN (p.left_clip_id, p.right_clip_id)
        )
    )
    SELECT count(*) INTO v_valid_count FROM valid_pairs;

    IF v_valid_count >= 60 THEN
      WITH invalid_clips AS (
        SELECT p.left_clip_id AS clip_id
        FROM public.rba_boundary_review_pairs p
        JOIN public.rba_boundary_eligibility_reviews r ON r.pair_id = p.id
        WHERE p.cohort_id = v_cohort_id
          AND r.decision IN ('left_gecko_absent','both_gecko_absent')
        UNION
        SELECT p.right_clip_id AS clip_id
        FROM public.rba_boundary_review_pairs p
        JOIN public.rba_boundary_eligibility_reviews r ON r.pair_id = p.id
        WHERE p.cohort_id = v_cohort_id
          AND r.decision IN ('right_gecko_absent','both_gecko_absent')
      ), valid_pairs AS (
        SELECT p.id
        FROM public.rba_boundary_review_pairs p
        JOIN public.rba_boundary_eligibility_reviews r ON r.pair_id = p.id
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

CREATE OR REPLACE FUNCTION public.fn_invalidate_rba_boundary_review_v1(
  p_owner_id uuid, p_experiment_id text, p_reason text
) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  v_cohort public.rba_boundary_review_cohorts%rowtype;
  v_submission_count integer;
  v_resolution_count integer;
BEGIN
  IF char_length(btrim(coalesce(p_reason, ''))) < 3 THEN
    RAISE EXCEPTION 'invalidation_reason_required' USING ERRCODE = '22023';
  END IF;
  SELECT * INTO v_cohort
  FROM public.rba_boundary_review_cohorts c
  WHERE c.experiment_id = p_experiment_id
  FOR UPDATE;
  IF v_cohort.id IS NULL OR v_cohort.created_by <> p_owner_id THEN
    RAISE EXCEPTION 'owner_forbidden' USING ERRCODE = 'PT403';
  END IF;
  IF v_cohort.status <> 'development_open' THEN
    RAISE EXCEPTION 'cohort_not_open' USING ERRCODE = 'PT409';
  END IF;

  SELECT count(*) INTO v_submission_count
  FROM public.rba_boundary_review_submissions s
  JOIN public.rba_boundary_review_pairs p ON p.id = s.pair_id
  WHERE p.cohort_id = v_cohort.id;
  SELECT count(*) INTO v_resolution_count
  FROM public.rba_boundary_review_resolutions r
  JOIN public.rba_boundary_review_pairs p ON p.id = r.pair_id
  WHERE p.cohort_id = v_cohort.id;
  IF v_submission_count <> 0 OR v_resolution_count <> 0 THEN
    RAISE EXCEPTION 'old_cohort_has_answers' USING ERRCODE = 'PT409';
  END IF;

  UPDATE public.rba_boundary_review_cohorts
  SET status = 'invalid_eligibility',
      invalidated_reason = btrim(p_reason),
      invalidated_at = now(),
      updated_at = now()
  WHERE id = v_cohort.id;
  RETURN jsonb_build_object(
    'invalidated', true,
    'pair_count', (
      SELECT count(*) FROM public.rba_boundary_review_pairs p WHERE p.cohort_id = v_cohort.id
    ),
    'submission_count', v_submission_count,
    'resolution_count', v_resolution_count,
    'status', 'invalid_eligibility'
  );
END;
$$;

CREATE OR REPLACE FUNCTION public.fn_seed_rba_boundary_sequence_review_v2(
  p_experiment_id text,
  p_manifest_digest text,
  p_created_by uuid,
  p_owner_id uuid,
  p_peer_id uuid,
  p_pairs jsonb
) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  v_cohort public.rba_boundary_review_cohorts%rowtype;
  v_pair_count integer;
BEGIN
  IF p_owner_id = p_peer_id OR p_created_by <> p_owner_id THEN
    RAISE EXCEPTION 'seed_reviewer_invalid' USING ERRCODE = '22023';
  END IF;
  IF p_experiment_id IS NULL OR btrim(p_experiment_id) = ''
     OR p_manifest_digest !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'seed_manifest_invalid' USING ERRCODE = '22023';
  END IF;
  IF jsonb_typeof(p_pairs) <> 'array' OR jsonb_array_length(p_pairs) <> 120 THEN
    RAISE EXCEPTION 'seed_exact120_required' USING ERRCODE = '22023';
  END IF;
  IF EXISTS (
    WITH input AS (
      SELECT * FROM jsonb_to_recordset(p_pairs) AS x(
        split text, ordinal integer, left_clip_id uuid, right_clip_id uuid,
        gap_sec double precision, gap_bin text, pair_digest text
      )
    )
    SELECT 1 FROM input
    WHERE split <> 'development' OR ordinal NOT BETWEEN 1 AND 120
       OR left_clip_id = right_clip_id OR gap_sec < 0
       OR gap_bin NOT IN ('le30','30to60','60to300')
       OR pair_digest !~ '^[0-9a-f]{64}$'
  ) THEN
    RAISE EXCEPTION 'seed_pair_invalid' USING ERRCODE = '22023';
  END IF;
  IF (
    SELECT count(DISTINCT ordinal)
    FROM jsonb_to_recordset(p_pairs) AS x(ordinal integer)
  ) <> 120 THEN
    RAISE EXCEPTION 'seed_ordinal_invalid' USING ERRCODE = '22023';
  END IF;

  LOCK TABLE public.rba_boundary_review_cohorts IN SHARE ROW EXCLUSIVE MODE;
  SELECT * INTO v_cohort
  FROM public.rba_boundary_review_cohorts c
  WHERE c.experiment_id = p_experiment_id
  FOR UPDATE;
  IF v_cohort.id IS NULL THEN
    IF EXISTS (
      SELECT 1 FROM public.rba_boundary_review_cohorts c
      WHERE c.status IN ('eligibility_open','development_open','holdout_open')
    ) THEN
      RAISE EXCEPTION 'other_open_cohort' USING ERRCODE = 'PT409';
    END IF;
    INSERT INTO public.rba_boundary_review_cohorts
      (experiment_id, manifest_digest, status, created_by, owner_id, peer_id)
    VALUES (
      p_experiment_id, p_manifest_digest, 'eligibility_open',
      p_created_by, p_owner_id, p_peer_id
    )
    RETURNING * INTO v_cohort;
  ELSIF v_cohort.manifest_digest <> p_manifest_digest
        OR v_cohort.created_by <> p_created_by
        OR v_cohort.owner_id <> p_owner_id
        OR v_cohort.peer_id <> p_peer_id THEN
    RAISE EXCEPTION 'seed_manifest_mismatch' USING ERRCODE = 'PT409';
  END IF;

  SELECT count(*) INTO v_pair_count
  FROM public.rba_boundary_review_pairs p WHERE p.cohort_id = v_cohort.id;
  IF v_pair_count = 0 THEN
    INSERT INTO public.rba_boundary_review_pairs
      (cohort_id, split, ordinal, left_clip_id, right_clip_id, gap_sec, gap_bin, pair_digest)
    SELECT v_cohort.id, x.split, x.ordinal, x.left_clip_id, x.right_clip_id,
           x.gap_sec, x.gap_bin, x.pair_digest
    FROM jsonb_to_recordset(p_pairs) AS x(
      split text, ordinal integer, left_clip_id uuid, right_clip_id uuid,
      gap_sec double precision, gap_bin text, pair_digest text
    );
    v_pair_count := 120;
  ELSIF v_pair_count <> 120 THEN
    RAISE EXCEPTION 'seed_partial_state' USING ERRCODE = 'PT409';
  END IF;

  IF EXISTS (
    WITH input AS (
      SELECT * FROM jsonb_to_recordset(p_pairs) AS x(
        split text, ordinal integer, left_clip_id uuid, right_clip_id uuid,
        gap_sec double precision, gap_bin text, pair_digest text
      )
    ), stored AS (
      SELECT p.split, p.ordinal, p.left_clip_id, p.right_clip_id,
             p.gap_sec, p.gap_bin, p.pair_digest
      FROM public.rba_boundary_review_pairs p WHERE p.cohort_id = v_cohort.id
    )
    (SELECT * FROM input EXCEPT SELECT * FROM stored)
    UNION ALL
    (SELECT * FROM stored EXCEPT SELECT * FROM input)
  ) THEN
    RAISE EXCEPTION 'seed_manifest_mismatch' USING ERRCODE = 'PT409';
  END IF;

  RETURN jsonb_build_object(
    'seeded', true,
    'pair_count', v_pair_count,
    'assignment_count', 0,
    'eligibility_count', 0,
    'status', v_cohort.status,
    'manifest_digest', v_cohort.manifest_digest
  );
END;
$$;

REVOKE ALL ON FUNCTION public.fn_seed_rba_boundary_sequence_review_v2(text, text, uuid, uuid, uuid, jsonb)
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.fn_invalidate_rba_boundary_review_v1(uuid, text, text)
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.fn_submit_rba_boundary_eligibility(uuid, uuid, text)
  FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.fn_seed_rba_boundary_sequence_review_v2(text, text, uuid, uuid, uuid, jsonb)
  TO service_role;
GRANT EXECUTE ON FUNCTION public.fn_invalidate_rba_boundary_review_v1(uuid, text, text)
  TO service_role;
GRANT EXECUTE ON FUNCTION public.fn_submit_rba_boundary_eligibility(uuid, uuid, text)
  TO service_role;

COMMIT;
