-- 경계 검수의 두 최초 답을 cohort/split 전체 완료 전까지 서로 숨긴다.
-- UI가 우회되더라도 DB가 최종 방어선이며, 기존 제출·해결 이력은 변경하지 않는다.

CREATE OR REPLACE FUNCTION public.fn_list_rba_boundary_conflicts(p_owner_id uuid)
RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  v_cohort_id uuid;
  v_split text;
  v_ready boolean := false;
  v_items jsonb;
  v_total integer;
BEGIN
  SELECT p.cohort_id, p.split
  INTO v_cohort_id, v_split
  FROM public.rba_boundary_review_assignments owner_a
  JOIN public.rba_boundary_review_pairs p ON p.id = owner_a.pair_id
  JOIN public.rba_boundary_review_cohorts c ON c.id = p.cohort_id
  WHERE owner_a.reviewer_id = p_owner_id
    AND owner_a.reviewer_role = 'owner'
    AND (
      (c.status IN ('development_open','development_frozen') AND p.split = 'development')
      OR (c.status IN ('holdout_open','closed') AND p.split = 'holdout')
    )
  ORDER BY c.created_at DESC
  LIMIT 1;

  IF v_cohort_id IS NULL THEN
    RETURN jsonb_build_object('ready', false, 'items', '[]'::jsonb, 'total', 0);
  END IF;

  SELECT count(a.id) > 0 AND count(s.id) = count(a.id)
  INTO v_ready
  FROM public.rba_boundary_review_pairs p
  JOIN public.rba_boundary_review_assignments a ON a.pair_id = p.id
  LEFT JOIN public.rba_boundary_review_submissions s ON s.assignment_id = a.id
  WHERE p.cohort_id = v_cohort_id AND p.split = v_split;

  IF NOT coalesce(v_ready, false) THEN
    -- 준비 전에는 상대 진행 수와 conflict 수까지 숨긴다.
    RETURN jsonb_build_object('ready', false, 'items', '[]'::jsonb, 'total', 0);
  END IF;

  WITH conflicts AS (
    SELECT p.id AS pair_id, p.ordinal, p.split, p.gap_sec, p.gap_bin,
           jsonb_agg(
             jsonb_build_object('reviewer_role', a.reviewer_role, 'decision', s.decision)
             ORDER BY a.reviewer_role
           ) AS submissions
    FROM public.rba_boundary_review_pairs p
    JOIN public.rba_boundary_review_assignments a ON a.pair_id = p.id
    JOIN public.rba_boundary_review_submissions s ON s.assignment_id = a.id
    LEFT JOIN public.rba_boundary_review_resolutions r ON r.pair_id = p.id
    WHERE p.cohort_id = v_cohort_id AND p.split = v_split AND r.id IS NULL
    GROUP BY p.id, p.ordinal, p.split, p.gap_sec, p.gap_bin
    HAVING count(*) = 2
       AND (count(DISTINCT s.decision) = 2 OR bool_or(s.decision = 'uncertain'))
  )
  SELECT COALESCE(jsonb_agg(to_jsonb(conflicts) ORDER BY ordinal), '[]'::jsonb), count(*)
  INTO v_items, v_total
  FROM conflicts;

  RETURN jsonb_build_object('ready', true, 'items', v_items, 'total', v_total);
END;
$$;

CREATE OR REPLACE FUNCTION public.fn_resolve_rba_boundary_conflict(
  p_owner_id uuid, p_pair_id uuid, p_final_decision text, p_reason text
) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  v_cohort_id uuid;
  v_split text;
  v_ready boolean := false;
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

  SELECT p.cohort_id, p.split
  INTO v_cohort_id, v_split
  FROM public.rba_boundary_review_assignments a
  JOIN public.rba_boundary_review_pairs p ON p.id = a.pair_id
  WHERE a.pair_id = p_pair_id
    AND a.reviewer_id = p_owner_id
    AND a.reviewer_role = 'owner';
  IF v_cohort_id IS NULL THEN
    RAISE EXCEPTION 'owner_forbidden' USING ERRCODE = 'PT403';
  END IF;

  SELECT count(a.id) > 0 AND count(s.id) = count(a.id)
  INTO v_ready
  FROM public.rba_boundary_review_pairs p
  JOIN public.rba_boundary_review_assignments a ON a.pair_id = p.id
  LEFT JOIN public.rba_boundary_review_submissions s ON s.assignment_id = a.id
  WHERE p.cohort_id = v_cohort_id AND p.split = v_split;
  IF NOT coalesce(v_ready, false) THEN
    RAISE EXCEPTION 'adjudication_not_ready' USING ERRCODE = 'PT409';
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

REVOKE ALL ON FUNCTION public.fn_list_rba_boundary_conflicts(uuid) FROM public, anon, authenticated;
REVOKE ALL ON FUNCTION public.fn_resolve_rba_boundary_conflict(uuid, uuid, text, text) FROM public, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_list_rba_boundary_conflicts(uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.fn_resolve_rba_boundary_conflict(uuid, uuid, text, text) TO service_role;
