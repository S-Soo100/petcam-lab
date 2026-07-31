-- 사건 경계 사람 GT와 팀 공용 사람-GT 집계를 기존 행동 교차검수와 분리한다.
-- 이 migration은 새 도메인만 만들며 기존 slot/submission/consensus/legacy GT를 수정하지 않는다.

BEGIN;

CREATE TABLE public.rba_boundary_review_cohorts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  experiment_id text NOT NULL UNIQUE,
  manifest_digest text NOT NULL CHECK (manifest_digest ~ '^[0-9a-f]{64}$'),
  status text NOT NULL DEFAULT 'prepared'
    CHECK (status IN ('prepared','development_open','development_frozen','holdout_open','closed')),
  created_by uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.rba_boundary_review_pairs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  cohort_id uuid NOT NULL REFERENCES public.rba_boundary_review_cohorts(id) ON DELETE RESTRICT,
  split text NOT NULL CHECK (split IN ('development','holdout')),
  ordinal integer NOT NULL CHECK (ordinal > 0),
  left_clip_id uuid NOT NULL REFERENCES public.motion_clips(id) ON DELETE RESTRICT,
  right_clip_id uuid NOT NULL REFERENCES public.motion_clips(id) ON DELETE RESTRICT,
  gap_sec double precision NOT NULL CHECK (gap_sec >= 0),
  gap_bin text NOT NULL CHECK (gap_bin IN ('le30','30to60','60to300')),
  pair_digest text NOT NULL CHECK (pair_digest ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (left_clip_id <> right_clip_id),
  UNIQUE (cohort_id, split, ordinal),
  UNIQUE (cohort_id, pair_digest)
);

CREATE TABLE public.rba_boundary_review_assignments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  pair_id uuid NOT NULL REFERENCES public.rba_boundary_review_pairs(id) ON DELETE RESTRICT,
  reviewer_id uuid NOT NULL,
  reviewer_role text NOT NULL CHECK (reviewer_role IN ('owner','peer')),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (pair_id, reviewer_id),
  UNIQUE (pair_id, reviewer_role)
);

CREATE TABLE public.rba_boundary_review_submissions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  assignment_id uuid NOT NULL UNIQUE
    REFERENCES public.rba_boundary_review_assignments(id) ON DELETE RESTRICT,
  pair_id uuid NOT NULL REFERENCES public.rba_boundary_review_pairs(id) ON DELETE RESTRICT,
  reviewer_id uuid NOT NULL,
  decision text NOT NULL CHECK (decision IN ('same_event','different_event','uncertain')),
  digest text NOT NULL,
  submitted_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.rba_boundary_review_resolutions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  pair_id uuid NOT NULL UNIQUE REFERENCES public.rba_boundary_review_pairs(id) ON DELETE RESTRICT,
  owner_id uuid NOT NULL,
  final_decision text NOT NULL CHECK (final_decision IN ('same_event','different_event','uncertain')),
  reason text NOT NULL CHECK (char_length(btrim(reason)) BETWEEN 3 AND 1000),
  digest text NOT NULL,
  resolved_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_rba_boundary_assignments_reviewer
  ON public.rba_boundary_review_assignments (reviewer_id, pair_id);
CREATE INDEX idx_rba_boundary_pairs_cohort_split
  ON public.rba_boundary_review_pairs (cohort_id, split, ordinal);
CREATE INDEX idx_rba_boundary_submissions_pair
  ON public.rba_boundary_review_submissions (pair_id, submitted_at);
CREATE UNIQUE INDEX uq_rba_boundary_single_open_cohort
  ON public.rba_boundary_review_cohorts ((true))
  WHERE status IN ('development_open','holdout_open');

ALTER TABLE public.rba_boundary_review_cohorts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.rba_boundary_review_pairs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.rba_boundary_review_assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.rba_boundary_review_submissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.rba_boundary_review_resolutions ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.rba_boundary_review_cohorts FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.rba_boundary_review_pairs FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.rba_boundary_review_assignments FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.rba_boundary_review_submissions FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.rba_boundary_review_resolutions FROM PUBLIC, anon, authenticated;

GRANT SELECT, INSERT, UPDATE ON TABLE public.rba_boundary_review_cohorts TO service_role;
GRANT SELECT, INSERT ON TABLE public.rba_boundary_review_pairs TO service_role;
GRANT SELECT, INSERT ON TABLE public.rba_boundary_review_assignments TO service_role;
GRANT SELECT, INSERT ON TABLE public.rba_boundary_review_submissions TO service_role;
GRANT SELECT, INSERT ON TABLE public.rba_boundary_review_resolutions TO service_role;

CREATE OR REPLACE FUNCTION public.fn_reject_rba_boundary_history_mutation()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = '' AS $$
BEGIN
  RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = '0A000';
END;
$$;

CREATE TRIGGER trg_rba_boundary_submissions_append_only
  BEFORE UPDATE OR DELETE OR TRUNCATE ON public.rba_boundary_review_submissions
  FOR EACH STATEMENT EXECUTE FUNCTION public.fn_reject_rba_boundary_history_mutation();
CREATE TRIGGER trg_rba_boundary_resolutions_append_only
  BEFORE UPDATE OR DELETE OR TRUNCATE ON public.rba_boundary_review_resolutions
  FOR EACH STATEMENT EXECUTE FUNCTION public.fn_reject_rba_boundary_history_mutation();

REVOKE ALL ON FUNCTION public.fn_reject_rba_boundary_history_mutation()
  FROM PUBLIC, anon, authenticated;

-- assignment 하나라도 있는지 메뉴용 boolean만 반환한다. pair/상대 정보는 반환하지 않는다.
CREATE OR REPLACE FUNCTION public.fn_get_rba_boundary_access(p_reviewer_id uuid)
RETURNS jsonb
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = '' AS $$
  SELECT jsonb_build_object(
    'enabled', EXISTS (
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

-- 본인 progress와 다음 미제출 pair 하나. 다른 reviewer의 답·UUID는 projection에 없다.
CREATE OR REPLACE FUNCTION public.fn_get_rba_boundary_workspace(p_reviewer_id uuid)
RETURNS jsonb
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = '' AS $$
  WITH assigned AS (
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
  ), next_pair AS (
    SELECT * FROM assigned WHERE submitted_at IS NULL ORDER BY ordinal LIMIT 1
  )
  SELECT jsonb_build_object(
    'enabled', EXISTS (SELECT 1 FROM assigned),
    'reviewer_role', (SELECT reviewer_role FROM assigned LIMIT 1),
    'split', (SELECT split FROM assigned LIMIT 1),
    'total', (SELECT count(*) FROM assigned),
    'completed', (SELECT count(*) FROM assigned WHERE submitted_at IS NOT NULL),
    'next_pair', (
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
      ) FROM next_pair
    )
  );
$$;

-- API signer만 쓰는 raw key 반환. 배정·열린 split·활성 media를 모두 재검사한다.
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

  SELECT CASE WHEN p_side = 'left' THEN p.left_clip_id ELSE p.right_clip_id END
  INTO v_clip_id
  FROM public.rba_boundary_review_assignments a
  JOIN public.rba_boundary_review_pairs p ON p.id = a.pair_id
  JOIN public.rba_boundary_review_cohorts c ON c.id = p.cohort_id
  WHERE a.reviewer_id = p_reviewer_id AND p.id = p_pair_id
    AND (
      (c.status = 'development_open' AND p.split = 'development')
      OR (c.status = 'holdout_open' AND p.split = 'holdout')
    );
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

  SELECT a.*
  INTO v_assignment
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
  WHERE p.id = p_pair_id;
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

-- owner assignment을 가진 conflict만 두 최초 답과 함께 반환한다.
CREATE OR REPLACE FUNCTION public.fn_list_rba_boundary_conflicts(p_owner_id uuid)
RETURNS jsonb
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = '' AS $$
  WITH conflicts AS (
    SELECT p.id AS pair_id, p.ordinal, p.split, p.gap_sec, p.gap_bin,
           jsonb_agg(
             jsonb_build_object('reviewer_role', a.reviewer_role, 'decision', s.decision)
             ORDER BY a.reviewer_role
           ) AS submissions
    FROM public.rba_boundary_review_pairs p
    JOIN public.rba_boundary_review_cohorts c ON c.id = p.cohort_id
    JOIN public.rba_boundary_review_assignments owner_a
      ON owner_a.pair_id = p.id AND owner_a.reviewer_role = 'owner'
    JOIN public.rba_boundary_review_assignments a ON a.pair_id = p.id
    JOIN public.rba_boundary_review_submissions s ON s.assignment_id = a.id
    LEFT JOIN public.rba_boundary_review_resolutions r ON r.pair_id = p.id
    WHERE owner_a.reviewer_id = p_owner_id AND r.id IS NULL
      AND (
        (c.status IN ('development_open','development_frozen') AND p.split = 'development')
        OR (c.status IN ('holdout_open','closed') AND p.split = 'holdout')
      )
    GROUP BY p.id, p.ordinal, p.split, p.gap_sec, p.gap_bin
    HAVING count(*) = 2
       AND (count(DISTINCT s.decision) = 2 OR bool_or(s.decision = 'uncertain'))
  )
  SELECT jsonb_build_object(
    'items', COALESCE(jsonb_agg(to_jsonb(conflicts) ORDER BY ordinal), '[]'::jsonb),
    'total', count(*)
  ) FROM conflicts;
$$;

CREATE OR REPLACE FUNCTION public.fn_resolve_rba_boundary_conflict(
  p_owner_id uuid, p_pair_id uuid, p_final_decision text, p_reason text
) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  v_is_owner boolean;
  v_distinct integer;
  v_count integer;
  v_has_uncertain boolean;
  v_id uuid;
BEGIN
  IF p_final_decision NOT IN ('same_event','different_event','uncertain') THEN
    RAISE EXCEPTION 'invalid_decision' USING ERRCODE = '22023';
  END IF;
  IF char_length(btrim(coalesce(p_reason,''))) < 3 THEN
    RAISE EXCEPTION 'resolution_reason_required' USING ERRCODE = '22023';
  END IF;

  SELECT EXISTS (
    SELECT 1 FROM public.rba_boundary_review_assignments a
    WHERE a.pair_id = p_pair_id AND a.reviewer_id = p_owner_id
      AND a.reviewer_role = 'owner'
  ) INTO v_is_owner;
  IF NOT v_is_owner THEN
    RAISE EXCEPTION 'owner_forbidden' USING ERRCODE = 'PT403';
  END IF;

  SELECT count(*), count(DISTINCT s.decision), bool_or(s.decision = 'uncertain')
  INTO v_count, v_distinct, v_has_uncertain
  FROM public.rba_boundary_review_assignments a
  JOIN public.rba_boundary_review_submissions s ON s.assignment_id = a.id
  WHERE a.pair_id = p_pair_id;
  IF v_count <> 2 OR (v_distinct <> 2 AND NOT coalesce(v_has_uncertain, false)) THEN
    RAISE EXCEPTION 'not_a_conflict' USING ERRCODE = 'PT409';
  END IF;

  INSERT INTO public.rba_boundary_review_resolutions
    (pair_id, owner_id, final_decision, reason, digest)
  VALUES (
    p_pair_id, p_owner_id, p_final_decision, btrim(p_reason),
    md5(p_pair_id::text || '|' || p_final_decision || '|' || btrim(p_reason))
  )
  ON CONFLICT (pair_id) DO NOTHING
  RETURNING id INTO v_id;
  IF v_id IS NULL THEN
    RAISE EXCEPTION 'already_resolved' USING ERRCODE = 'PT410';
  END IF;
  RETURN jsonb_build_object('resolved', true, 'pair_id', p_pair_id);
END;
$$;

-- 승인 멤버십은 API guard가 확인한다. 이 RPC는 사람 canonical GT만 한 번 집계한다.
CREATE OR REPLACE FUNCTION public.fn_get_labeling_data_dashboard(p_owner_id uuid)
RETURNS jsonb
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = '' AS $$
  WITH playable AS (
    SELECT m.*
    FROM public.motion_clips m
    WHERE m.r2_key IS NOT NULL
      AND NOT EXISTS (
        SELECT 1 FROM public.motion_clip_system_exclusions sx
        WHERE sx.clip_id = m.id AND sx.state IN ('quarantined','media_deleted')
      )
  ), sources AS (
    SELECT m.id,
           lc.final_gt AS live_gt,
           cy.canary_gt,
           ls.legacy_gt
    FROM playable m
    LEFT JOIN public.motion_clip_consensus lc
      ON lc.clip_id = m.id AND lc.cohort_kind = 'live'
     AND lc.status IN ('agreed','owner_resolved') AND lc.final_decision = 'label'
    LEFT JOIN LATERAL (
      SELECT cc.final_gt AS canary_gt
      FROM public.motion_clip_consensus cc
      JOIN public.motion_blind_review_cohorts co ON co.id = cc.cohort_id
      WHERE cc.clip_id = m.id AND cc.cohort_kind = 'canary'
        AND cc.status IN ('agreed','owner_resolved') AND cc.final_decision = 'label'
      ORDER BY (co.status = 'open') DESC, co.created_at DESC, cc.id DESC
      LIMIT 1
    ) cy ON true
    LEFT JOIN LATERAL (
      SELECT coalesce(s.current_gt, s.initial_gt) AS legacy_gt
      FROM public.motion_clip_labeling_sessions s
      WHERE s.clip_id = m.id AND s.initial_gt IS NOT NULL
      ORDER BY (s.reviewed_by = p_owner_id) DESC, s.updated_at DESC, s.id DESC
      LIMIT 1
    ) ls ON true
  ), canonical AS (
    SELECT id,
      coalesce(canary_gt, live_gt, legacy_gt) AS final_gt
    FROM sources
  ), behavior AS (
    SELECT final_gt ->> 'primary_action' AS primary_action, count(*) AS clip_count
    FROM canonical
    WHERE final_gt IS NOT NULL
      AND jsonb_typeof(final_gt) = 'object'
      AND coalesce(final_gt ->> 'primary_action','') <> ''
    GROUP BY final_gt ->> 'primary_action'
  )
  SELECT jsonb_build_object(
    'video_record_count', (SELECT count(*) FROM public.motion_clips),
    'playable_video_count', (SELECT count(*) FROM playable),
    'gt_labeled_video_count', (SELECT coalesce(sum(clip_count), 0) FROM behavior),
    'behavior_counts', COALESCE(
      (SELECT jsonb_object_agg(primary_action, clip_count ORDER BY primary_action) FROM behavior),
      '{}'::jsonb
    ),
    'generated_at', now()
  );
$$;

-- 검증 완료 private manifest를 한 트랜잭션에 exact-120으로 준비한다. raw pair는 함수 응답에 없다.
CREATE OR REPLACE FUNCTION public.fn_seed_rba_boundary_review(
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
  v_assignment_count integer;
  v_development_count integer;
  v_holdout_count integer;
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

  WITH input AS (
    SELECT * FROM jsonb_to_recordset(p_pairs) AS x(
      split text, ordinal integer, left_clip_id uuid, right_clip_id uuid,
      gap_sec double precision, gap_bin text, pair_digest text
    )
  )
  SELECT count(*) FILTER (WHERE split = 'development'),
         count(*) FILTER (WHERE split = 'holdout')
  INTO v_development_count, v_holdout_count
  FROM input;
  IF v_development_count <> 60 OR v_holdout_count <> 60 THEN
    RAISE EXCEPTION 'seed_split_60_60_required' USING ERRCODE = '22023';
  END IF;
  IF EXISTS (
    WITH input AS (
      SELECT * FROM jsonb_to_recordset(p_pairs) AS x(
        split text, ordinal integer, left_clip_id uuid, right_clip_id uuid,
        gap_sec double precision, gap_bin text, pair_digest text
      )
    )
    SELECT 1 FROM input
    WHERE split NOT IN ('development','holdout') OR ordinal NOT BETWEEN 1 AND 60
       OR left_clip_id = right_clip_id OR gap_sec < 0
       OR gap_bin NOT IN ('le30','30to60','60to300')
       OR pair_digest !~ '^[0-9a-f]{64}$'
  ) THEN
    RAISE EXCEPTION 'seed_pair_invalid' USING ERRCODE = '22023';
  END IF;

  INSERT INTO public.rba_boundary_review_cohorts
    (experiment_id, manifest_digest, status, created_by)
  VALUES (p_experiment_id, p_manifest_digest, 'development_open', p_created_by)
  ON CONFLICT (experiment_id) DO NOTHING;
  SELECT * INTO v_cohort
  FROM public.rba_boundary_review_cohorts c
  WHERE c.experiment_id = p_experiment_id
  FOR UPDATE;
  IF v_cohort.manifest_digest <> p_manifest_digest OR v_cohort.created_by <> p_created_by THEN
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

  SELECT count(*) INTO v_assignment_count
  FROM public.rba_boundary_review_assignments a
  JOIN public.rba_boundary_review_pairs p ON p.id = a.pair_id
  WHERE p.cohort_id = v_cohort.id;
  IF v_assignment_count = 0 THEN
    INSERT INTO public.rba_boundary_review_assignments(pair_id, reviewer_id, reviewer_role)
    SELECT p.id, reviewers.reviewer_id, reviewers.reviewer_role
    FROM public.rba_boundary_review_pairs p
    CROSS JOIN LATERAL (
      VALUES (p_owner_id, 'owner'::text), (p_peer_id, 'peer'::text)
    ) AS reviewers(reviewer_id, reviewer_role)
    WHERE p.cohort_id = v_cohort.id;
  ELSIF v_assignment_count <> 240 THEN
    RAISE EXCEPTION 'seed_partial_state' USING ERRCODE = 'PT409';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM public.rba_boundary_review_pairs p
    JOIN public.rba_boundary_review_assignments a ON a.pair_id = p.id
    WHERE p.cohort_id = v_cohort.id
      AND (
        (a.reviewer_role = 'owner' AND a.reviewer_id <> p_owner_id)
        OR (a.reviewer_role = 'peer' AND a.reviewer_id <> p_peer_id)
      )
  ) THEN
    RAISE EXCEPTION 'seed_reviewer_mismatch' USING ERRCODE = 'PT409';
  END IF;

  RETURN jsonb_build_object(
    'seeded', true, 'pair_count', 120, 'assignment_count', 240,
    'status', v_cohort.status, 'manifest_digest', v_cohort.manifest_digest
  );
END;
$$;

REVOKE ALL ON FUNCTION public.fn_get_rba_boundary_access(uuid)
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.fn_get_rba_boundary_workspace(uuid)
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.fn_get_rba_boundary_pair_media(uuid, uuid, text)
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.fn_submit_rba_boundary_decision(uuid, uuid, text)
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.fn_list_rba_boundary_conflicts(uuid)
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.fn_resolve_rba_boundary_conflict(uuid, uuid, text, text)
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.fn_get_labeling_data_dashboard(uuid)
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.fn_seed_rba_boundary_review(text, text, uuid, uuid, uuid, jsonb)
  FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.fn_get_rba_boundary_access(uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.fn_get_rba_boundary_workspace(uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.fn_get_rba_boundary_pair_media(uuid, uuid, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.fn_submit_rba_boundary_decision(uuid, uuid, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.fn_list_rba_boundary_conflicts(uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.fn_resolve_rba_boundary_conflict(uuid, uuid, text, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.fn_get_labeling_data_dashboard(uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.fn_seed_rba_boundary_review(text, text, uuid, uuid, uuid, jsonb)
  TO service_role;

COMMIT;
