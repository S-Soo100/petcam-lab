-- Owner cleanup UI 공개 계약: 재생 가능한 미결 897개만 노출한다.
BEGIN;

CREATE OR REPLACE FUNCTION public.fn_list_rba_owner_media_cleanup_v1(
  p_owner_id uuid, p_cursor_started_at timestamptz DEFAULT NULL,
  p_cursor_clip_id uuid DEFAULT NULL, p_limit integer DEFAULT 20
) RETURNS TABLE (
  clip_id uuid, started_at timestamptz, duration_sec double precision,
  camera_name text, seed_reason text, state text, has_canonical_gt boolean,
  decision text
)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
  IF (p_cursor_started_at IS NULL) <> (p_cursor_clip_id IS NULL)
     OR p_limit NOT BETWEEN 1 AND 50 THEN
    RAISE EXCEPTION 'cleanup_list_arguments_invalid' USING ERRCODE = '22023';
  END IF;
  RETURN QUERY
  SELECT media.id, media.started_at, media.duration_sec, camera.name,
         item.seed_reason, item.state, item.has_canonical_gt, decision_row.decision
  FROM public.rba_owner_media_cleanup_cohorts cohort
  JOIN public.rba_owner_media_cleanup_items item ON item.cohort_id = cohort.id
  JOIN public.motion_clips media ON media.id = item.clip_id
  LEFT JOIN public.cameras camera ON camera.id = media.camera_id
  LEFT JOIN public.rba_owner_media_cleanup_decisions decision_row ON decision_row.item_id = item.id
  WHERE cohort.owner_id = p_owner_id
    AND item.seed_reason = 'owner_review_pending'
    AND item.state = 'quarantined'
    AND decision_row.id IS NULL
    AND (p_cursor_started_at IS NULL OR media.started_at > p_cursor_started_at
      OR (media.started_at = p_cursor_started_at AND media.id > p_cursor_clip_id))
  ORDER BY media.started_at, media.id LIMIT p_limit;
END;
$$;

CREATE FUNCTION public.fn_get_rba_owner_media_cleanup_summary_v1(p_owner_id uuid)
RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT jsonb_build_object(
    'total_review_partition', count(*) FILTER (WHERE item.seed_reason = 'owner_review_pending'),
    'source_missing', count(*) FILTER (WHERE item.state = 'source_missing'),
    'available', count(*) FILTER (
      WHERE item.seed_reason = 'owner_review_pending' AND item.state <> 'source_missing'
    ),
    'completed', count(decision_row.id),
    'remaining', count(*) FILTER (
      WHERE item.seed_reason = 'owner_review_pending' AND item.state = 'quarantined'
        AND decision_row.id IS NULL
    ),
    'kept', count(*) FILTER (WHERE decision_row.decision = 'keep'),
    'delete_gecko_absent', count(*) FILTER (WHERE decision_row.decision = 'delete_gecko_absent'),
    'delete_no_activity', count(*) FILTER (WHERE decision_row.decision = 'delete_no_activity'),
    'uncertain', count(*) FILTER (WHERE decision_row.decision = 'uncertain')
  )
  FROM public.rba_owner_media_cleanup_cohorts cohort
  JOIN public.rba_owner_media_cleanup_items item ON item.cohort_id = cohort.id
  LEFT JOIN public.rba_owner_media_cleanup_decisions decision_row ON decision_row.item_id = item.id
  WHERE cohort.owner_id = p_owner_id;
$$;

CREATE FUNCTION public.fn_get_rba_owner_media_cleanup_key_v1(
  p_owner_id uuid, p_clip_id uuid
) RETURNS TABLE (r2_key text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT media.r2_key
  FROM public.rba_owner_media_cleanup_cohorts cohort
  JOIN public.rba_owner_media_cleanup_items item ON item.cohort_id = cohort.id
  JOIN public.motion_clips media ON media.id = item.clip_id
  LEFT JOIN public.rba_owner_media_cleanup_decisions decision_row ON decision_row.item_id = item.id
  WHERE cohort.owner_id = p_owner_id
    AND item.clip_id = p_clip_id
    AND item.seed_reason = 'owner_review_pending'
    AND item.state = 'quarantined'
    AND decision_row.id IS NULL
    AND media.r2_key IS NOT NULL;
$$;

CREATE OR REPLACE FUNCTION public.fn_decide_rba_owner_media_cleanup_v1(
  p_owner_id uuid, p_clip_id uuid, p_decision text, p_reason text DEFAULT NULL
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  v_item public.rba_owner_media_cleanup_items%rowtype;
  v_expected_owner uuid;
  v_decision_id uuid;
BEGIN
  IF p_decision NOT IN ('keep','delete_gecko_absent','delete_no_activity','uncertain') THEN
    RAISE EXCEPTION 'cleanup_decision_invalid' USING ERRCODE = '22023';
  END IF;
  SELECT cleanup_item.* INTO v_item
  FROM public.rba_owner_media_cleanup_items cleanup_item
  WHERE cleanup_item.clip_id = p_clip_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'cleanup_owner_forbidden' USING ERRCODE = 'PT403';
  END IF;
  SELECT cohort.owner_id INTO v_expected_owner
  FROM public.rba_owner_media_cleanup_cohorts cohort WHERE cohort.id = v_item.cohort_id;
  IF v_expected_owner <> p_owner_id OR v_item.seed_reason <> 'owner_review_pending' THEN
    RAISE EXCEPTION 'cleanup_owner_forbidden' USING ERRCODE = 'PT403';
  END IF;
  IF v_item.state <> 'quarantined' THEN
    RAISE EXCEPTION 'cleanup_item_not_reviewable' USING ERRCODE = 'PT409';
  END IF;
  IF v_item.has_canonical_gt AND p_decision LIKE 'delete_%' THEN
    RAISE EXCEPTION 'canonical_gt_delete_forbidden' USING ERRCODE = 'PT428';
  END IF;
  INSERT INTO public.rba_owner_media_cleanup_decisions
    (item_id, clip_id, owner_id, decision, reason, digest)
  VALUES (
    v_item.id, p_clip_id, p_owner_id, p_decision, nullif(btrim(p_reason), ''),
    encode(digest(v_item.id::text || '|' || p_decision || '|' || coalesce(btrim(p_reason), ''), 'sha256'), 'hex')
  ) ON CONFLICT (item_id) DO NOTHING RETURNING id INTO v_decision_id;
  IF v_decision_id IS NULL THEN
    RAISE EXCEPTION 'cleanup_already_decided' USING ERRCODE = 'PT410';
  END IF;
  UPDATE public.rba_owner_media_cleanup_items
  SET state = 'decision_recorded', updated_at = clock_timestamp()
  WHERE id = v_item.id;
  INSERT INTO public.rba_owner_media_cleanup_events
    (cohort_id, item_id, clip_id, event_type, actor_id, detail)
  VALUES (v_item.cohort_id, v_item.id, p_clip_id, 'owner_decided', p_owner_id,
          jsonb_build_object('decision', p_decision));
  RETURN jsonb_build_object('recorded', true, 'clip_id', p_clip_id);
END;
$$;

REVOKE ALL ON FUNCTION public.fn_list_rba_owner_media_cleanup_v1(uuid, timestamptz, uuid, integer)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_list_rba_owner_media_cleanup_v1(uuid, timestamptz, uuid, integer)
  TO service_role;
REVOKE ALL ON FUNCTION public.fn_get_rba_owner_media_cleanup_summary_v1(uuid)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_get_rba_owner_media_cleanup_summary_v1(uuid) TO service_role;
REVOKE ALL ON FUNCTION public.fn_get_rba_owner_media_cleanup_key_v1(uuid, uuid)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_get_rba_owner_media_cleanup_key_v1(uuid, uuid) TO service_role;
REVOKE ALL ON FUNCTION public.fn_decide_rba_owner_media_cleanup_v1(uuid, uuid, text, text)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_decide_rba_owner_media_cleanup_v1(uuid, uuid, text, text)
  TO service_role;

COMMIT;
