-- Owner가 직접 확인한 초기 오염 영상의 격리·삭제 원장.
-- 삭제 권한은 사람의 이어짐 자격검사 최종 판정만 사용하며 모델 출력은 참조하지 않는다.

BEGIN;

ALTER TABLE public.motion_clip_system_exclusions
  DROP CONSTRAINT IF EXISTS motion_clip_system_exclusions_reason_code_check;
ALTER TABLE public.motion_clip_system_exclusions
  ADD CONSTRAINT motion_clip_system_exclusions_reason_code_check CHECK (
    reason_code IN (
      'short_device_error',
      'owner_cleanup_candidate',
      'owner_gecko_absent',
      'owner_no_gecko_activity'
    )
  );

CREATE TABLE public.rba_owner_media_cleanup_cohorts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  experiment_id text NOT NULL UNIQUE CHECK (btrim(experiment_id) <> ''),
  owner_id uuid NOT NULL,
  manifest_digest text NOT NULL CHECK (manifest_digest ~ '^[0-9a-f]{64}$'),
  status text NOT NULL DEFAULT 'prepared' CHECK (
    status IN ('prepared','quarantining','owner_review','complete','failed')
  ),
  total_count integer NOT NULL CHECK (total_count = 951),
  confirmed_invalid_count integer NOT NULL CHECK (confirmed_invalid_count = 46),
  protected_gt_count integer NOT NULL CHECK (protected_gt_count = 1),
  owner_review_count integer NOT NULL CHECK (owner_review_count = 904),
  source_missing_count integer NOT NULL CHECK (source_missing_count = 7),
  reused_short_candidate_count integer NOT NULL CHECK (reused_short_candidate_count = 11),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE public.rba_owner_media_cleanup_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  cohort_id uuid NOT NULL REFERENCES public.rba_owner_media_cleanup_cohorts(id) ON DELETE RESTRICT,
  clip_id uuid NOT NULL UNIQUE REFERENCES public.motion_clips(id) ON DELETE RESTRICT,
  seed_reason text NOT NULL CHECK (
    seed_reason IN (
      'confirmed_gecko_absent','confirmed_no_gecko_activity',
      'protected_gt','owner_review_pending'
    )
  ),
  has_canonical_gt boolean NOT NULL,
  original_r2_key text NOT NULL CHECK (btrim(original_r2_key) <> ''),
  original_thumbnail_key text,
  source_r2_key text NOT NULL CHECK (btrim(source_r2_key) <> ''),
  source_thumbnail_key text,
  source_present boolean NOT NULL,
  thumbnail_present boolean NOT NULL,
  state text NOT NULL DEFAULT 'prepared' CHECK (
    state IN ('prepared','source_missing','moving','quarantined','decision_recorded','restored','media_deleted','move_failed')
  ),
  lease_stage text CHECK (lease_stage IN ('quarantine','delete_confirmed','restore_keep')),
  lease_from_state text,
  lease_token uuid,
  lease_expires_at timestamptz,
  worker_host text,
  last_error_code text,
  source_fingerprint jsonb,
  destination_fingerprint jsonb,
  quarantined_at timestamptz,
  media_deleted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (cohort_id, clip_id),
  CHECK ((lease_token IS NULL) = (lease_expires_at IS NULL)),
  CHECK (seed_reason NOT IN ('confirmed_gecko_absent','confirmed_no_gecko_activity') OR NOT has_canonical_gt),
  CHECK (seed_reason <> 'protected_gt' OR has_canonical_gt)
);

CREATE INDEX idx_rba_owner_media_cleanup_items_queue
  ON public.rba_owner_media_cleanup_items (cohort_id, state, seed_reason, created_at, id);

CREATE TABLE public.rba_owner_media_cleanup_decisions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  item_id uuid NOT NULL UNIQUE REFERENCES public.rba_owner_media_cleanup_items(id) ON DELETE RESTRICT,
  clip_id uuid NOT NULL UNIQUE REFERENCES public.motion_clips(id) ON DELETE RESTRICT,
  owner_id uuid NOT NULL,
  decision text NOT NULL CHECK (
    decision IN ('keep','delete_gecko_absent','delete_no_activity','uncertain')
  ),
  reason text CHECK (reason IS NULL OR char_length(reason) <= 1000),
  digest text NOT NULL CHECK (digest ~ '^[0-9a-f]{64}$'),
  submitted_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE public.rba_owner_media_cleanup_events (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  cohort_id uuid NOT NULL REFERENCES public.rba_owner_media_cleanup_cohorts(id) ON DELETE RESTRICT,
  item_id uuid REFERENCES public.rba_owner_media_cleanup_items(id) ON DELETE RESTRICT,
  clip_id uuid REFERENCES public.motion_clips(id) ON DELETE RESTRICT,
  event_type text NOT NULL CHECK (
    event_type IN ('prepared','source_missing_recorded','move_claimed','move_completed','move_failed','owner_decided')
  ),
  actor_id uuid,
  worker_host text,
  detail jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE FUNCTION public.fn_block_rba_owner_media_cleanup_history_mutation()
RETURNS trigger LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN
  RAISE EXCEPTION 'rba owner media cleanup history is append-only'
    USING ERRCODE = '0A000';
END;
$$;
REVOKE ALL ON FUNCTION public.fn_block_rba_owner_media_cleanup_history_mutation() FROM PUBLIC;

CREATE TRIGGER trg_rba_owner_media_cleanup_decisions_append_only
  BEFORE UPDATE OR DELETE OR TRUNCATE ON public.rba_owner_media_cleanup_decisions
  FOR EACH STATEMENT EXECUTE FUNCTION public.fn_block_rba_owner_media_cleanup_history_mutation();
CREATE TRIGGER trg_rba_owner_media_cleanup_events_append_only
  BEFORE UPDATE OR DELETE OR TRUNCATE ON public.rba_owner_media_cleanup_events
  FOR EACH STATEMENT EXECUTE FUNCTION public.fn_block_rba_owner_media_cleanup_history_mutation();

ALTER TABLE public.rba_owner_media_cleanup_cohorts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.rba_owner_media_cleanup_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.rba_owner_media_cleanup_decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.rba_owner_media_cleanup_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.rba_owner_media_cleanup_cohorts FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.rba_owner_media_cleanup_items FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.rba_owner_media_cleanup_decisions FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.rba_owner_media_cleanup_events FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON TABLE public.rba_owner_media_cleanup_cohorts TO service_role;
GRANT SELECT, INSERT, UPDATE ON TABLE public.rba_owner_media_cleanup_items TO service_role;
GRANT SELECT, INSERT ON TABLE public.rba_owner_media_cleanup_decisions TO service_role;
GRANT SELECT, INSERT ON TABLE public.rba_owner_media_cleanup_events TO service_role;

CREATE FUNCTION public.fn_rba_owner_cleanup_has_canonical_gt(p_clip_id uuid)
RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT EXISTS (
    SELECT 1
    FROM public.motion_clip_consensus c
    WHERE c.clip_id = p_clip_id
      AND c.status IN ('agreed','owner_resolved')
      AND c.final_decision = 'label'
      AND c.final_gt IS NOT NULL
  ) OR EXISTS (
    SELECT 1
    FROM public.motion_clip_labeling_sessions s
    WHERE s.clip_id = p_clip_id
      AND coalesce(s.current_gt, s.initial_gt) IS NOT NULL
  );
$$;
REVOKE ALL ON FUNCTION public.fn_rba_owner_cleanup_has_canonical_gt(uuid)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_rba_owner_cleanup_has_canonical_gt(uuid) TO service_role;

CREATE FUNCTION public.fn_prepare_rba_owner_media_cleanup_v1(
  p_experiment_id text,
  p_owner_id uuid,
  p_manifest_digest text,
  p_items jsonb
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  v_cohort_id uuid;
  v_total_count integer;
  v_confirmed_invalid_count integer;
  v_protected_gt_count integer;
  v_owner_review_count integer;
  v_source_missing_count integer;
  v_existing_candidate_count integer;
  v_duplicate_count integer;
  v_stratum_count integer;
  v_scope_count integer;
  v_mismatch_count integer;
BEGIN
  IF btrim(coalesce(p_experiment_id, '')) = ''
     OR p_owner_id IS NULL
     OR p_manifest_digest !~ '^[0-9a-f]{64}$'
     OR jsonb_typeof(p_items) <> 'array' THEN
    RAISE EXCEPTION 'cleanup_manifest_invalid' USING ERRCODE = '22023';
  END IF;

  CREATE TEMP TABLE cleanup_input ON COMMIT DROP AS
  SELECT
    (value->>'clip_id')::uuid AS clip_id,
    value->>'seed_reason' AS seed_reason,
    value->>'source_r2_key' AS source_r2_key,
    nullif(value->>'source_thumbnail_key', '') AS source_thumbnail_key,
    coalesce((value->>'source_present')::boolean, false) AS source_present,
    coalesce((value->>'thumbnail_present')::boolean, false) AS thumbnail_present
  FROM jsonb_array_elements(p_items);

  SELECT count(*), count(*) - count(DISTINCT clip_id),
         count(*) FILTER (WHERE seed_reason IN ('confirmed_gecko_absent','confirmed_no_gecko_activity')),
         count(*) FILTER (WHERE seed_reason = 'protected_gt'),
         count(*) FILTER (WHERE seed_reason = 'owner_review_pending')
  INTO v_total_count, v_duplicate_count, v_confirmed_invalid_count,
       v_protected_gt_count, v_owner_review_count
  FROM cleanup_input;

  IF v_total_count <> 951 OR v_confirmed_invalid_count <> 46
     OR v_protected_gt_count <> 1 OR v_owner_review_count <> 904
     OR v_duplicate_count <> 0 THEN
    RAISE EXCEPTION 'cleanup_frozen_counts_mismatch' USING ERRCODE = 'PT422';
  END IF;

  SELECT count(*) INTO v_source_missing_count
  FROM cleanup_input WHERE NOT source_present;
  IF v_source_missing_count <> 7 THEN
    RAISE EXCEPTION 'cleanup_source_missing_count_mismatch' USING ERRCODE = 'PT422';
  END IF;
  SELECT count(*) INTO v_mismatch_count
  FROM cleanup_input
  WHERE NOT source_present AND seed_reason <> 'owner_review_pending';
  IF v_mismatch_count <> 0 THEN
    RAISE EXCEPTION 'protected_or_delete_source_missing' USING ERRCODE = 'PT428';
  END IF;

  WITH effective_reviews AS (
    SELECT r.pair_id, coalesce(x.replacement_decision, r.decision) AS decision
    FROM public.rba_boundary_eligibility_reviews r
    LEFT JOIN public.rba_boundary_eligibility_corrections x ON x.review_id = r.id
  ), invalid_map AS (
    SELECT p.left_clip_id AS clip_id,
      CASE
        WHEN e.decision IN ('left_gecko_absent','both_gecko_absent') THEN 'confirmed_gecko_absent'
        WHEN e.decision IN ('left_no_gecko_activity','both_no_gecko_activity') THEN 'confirmed_no_gecko_activity'
      END AS seed_reason
    FROM public.rba_boundary_review_pairs p JOIN effective_reviews e ON e.pair_id = p.id
    WHERE e.decision IN (
      'left_gecko_absent','both_gecko_absent',
      'left_no_gecko_activity','both_no_gecko_activity'
    )
    UNION
    SELECT p.right_clip_id AS clip_id,
      CASE
        WHEN e.decision IN ('right_gecko_absent','both_gecko_absent') THEN 'confirmed_gecko_absent'
        WHEN e.decision IN ('right_no_gecko_activity','both_no_gecko_activity') THEN 'confirmed_no_gecko_activity'
      END AS seed_reason
    FROM public.rba_boundary_review_pairs p JOIN effective_reviews e ON e.pair_id = p.id
    WHERE e.decision IN (
      'right_gecko_absent','both_gecko_absent',
      'right_no_gecko_activity','both_no_gecko_activity'
    )
  )
  SELECT count(*) INTO v_mismatch_count
  FROM cleanup_input i
  WHERE i.seed_reason IN ('confirmed_gecko_absent','confirmed_no_gecko_activity')
    AND NOT EXISTS (
      SELECT 1 FROM invalid_map m
      WHERE m.clip_id = i.clip_id AND m.seed_reason = i.seed_reason
    );
  IF v_mismatch_count <> 0 THEN
    RAISE EXCEPTION 'confirmed_invalid_provenance_mismatch' USING ERRCODE = 'PT422';
  END IF;

  SELECT count(*) INTO v_mismatch_count
  FROM cleanup_input i
  LEFT JOIN public.motion_clips m ON m.id = i.clip_id
  WHERE m.id IS NULL OR btrim(coalesce(i.source_r2_key, '')) = ''
     OR m.r2_key IS DISTINCT FROM i.source_r2_key
     OR m.thumbnail_key IS DISTINCT FROM i.source_thumbnail_key;
  IF v_mismatch_count <> 0 THEN
    RAISE EXCEPTION 'cleanup_media_manifest_mismatch' USING ERRCODE = 'PT422';
  END IF;

  SELECT count(*) INTO v_mismatch_count
  FROM cleanup_input i
  WHERE public.fn_rba_owner_cleanup_has_canonical_gt(i.clip_id)
    <> (i.seed_reason = 'protected_gt');
  IF v_mismatch_count <> 0 THEN
    RAISE EXCEPTION 'canonical_gt_partition_mismatch' USING ERRCODE = 'PT422';
  END IF;

  SELECT count(*) INTO v_mismatch_count
  FROM cleanup_input i
  WHERE i.seed_reason IN ('confirmed_gecko_absent','confirmed_no_gecko_activity')
    AND public.fn_rba_owner_cleanup_has_canonical_gt(i.clip_id);
  IF v_mismatch_count <> 0 THEN
    RAISE EXCEPTION 'canonical_gt_delete_forbidden' USING ERRCODE = 'PT428';
  END IF;

  WITH contaminated_strata AS (
    SELECT DISTINCT m.camera_id, (m.started_at AT TIME ZONE 'Asia/Seoul')::date AS activity_date
    FROM cleanup_input i JOIN public.motion_clips m ON m.id = i.clip_id
    WHERE i.seed_reason IN ('confirmed_gecko_absent','confirmed_no_gecko_activity')
  )
  SELECT count(*) INTO v_stratum_count FROM contaminated_strata;
  IF v_stratum_count <> 2 THEN
    RAISE EXCEPTION 'cleanup_stratum_count_mismatch' USING ERRCODE = 'PT422';
  END IF;

  WITH contaminated_strata AS (
    SELECT DISTINCT m.camera_id, (m.started_at AT TIME ZONE 'Asia/Seoul')::date AS activity_date
    FROM cleanup_input i JOIN public.motion_clips m ON m.id = i.clip_id
    WHERE i.seed_reason IN ('confirmed_gecko_absent','confirmed_no_gecko_activity')
  )
  SELECT count(*) INTO v_scope_count
  FROM public.motion_clips m JOIN contaminated_strata s
    ON s.camera_id = m.camera_id
   AND s.activity_date = (m.started_at AT TIME ZONE 'Asia/Seoul')::date
  WHERE m.r2_key IS NOT NULL;
  IF v_scope_count <> 951 THEN
    RAISE EXCEPTION 'cleanup_full_camera_day_scope_mismatch' USING ERRCODE = 'PT422';
  END IF;

  SELECT count(*) INTO v_existing_candidate_count
  FROM cleanup_input i
  JOIN public.motion_clip_system_exclusions sx ON sx.clip_id = i.clip_id;
  IF v_existing_candidate_count <> 11 THEN
    RAISE EXCEPTION 'cleanup_existing_candidate_count_mismatch' USING ERRCODE = 'PT422';
  END IF;
  SELECT count(*) INTO v_mismatch_count
  FROM cleanup_input i
  JOIN public.motion_clip_system_exclusions sx ON sx.clip_id = i.clip_id
  WHERE sx.reason_code <> 'short_device_error' OR sx.state <> 'candidate'
     OR i.seed_reason <> 'owner_review_pending';
  IF v_mismatch_count <> 0 THEN
    RAISE EXCEPTION 'cleanup_existing_exclusion_conflict' USING ERRCODE = 'PT409';
  END IF;

  INSERT INTO public.rba_owner_media_cleanup_cohorts
    (experiment_id, owner_id, manifest_digest, total_count,
     confirmed_invalid_count, protected_gt_count, owner_review_count, source_missing_count,
     reused_short_candidate_count)
  VALUES (p_experiment_id, p_owner_id, p_manifest_digest, 951, 46, 1, 904, 7, 11)
  RETURNING id INTO v_cohort_id;

  INSERT INTO public.rba_owner_media_cleanup_items
    (cohort_id, clip_id, seed_reason, has_canonical_gt,
     original_r2_key, original_thumbnail_key, source_r2_key, source_thumbnail_key,
     source_present, thumbnail_present, state)
  SELECT v_cohort_id, i.clip_id, i.seed_reason,
         public.fn_rba_owner_cleanup_has_canonical_gt(i.clip_id),
         i.source_r2_key, i.source_thumbnail_key, i.source_r2_key, i.source_thumbnail_key,
         i.source_present, i.thumbnail_present,
         CASE WHEN i.source_present THEN 'prepared' ELSE 'source_missing' END
  FROM cleanup_input i;

  INSERT INTO public.motion_clip_system_exclusions
    (clip_id, camera_id, state, reason_code, rule_version,
     observed_duration_sec, displayed_duration_sec, detected_at,
     quarantined_at, delete_after)
  SELECT m.id, m.camera_id, 'quarantined',
    CASE i.seed_reason
      WHEN 'confirmed_gecko_absent' THEN 'owner_gecko_absent'
      WHEN 'confirmed_no_gecko_activity' THEN 'owner_no_gecko_activity'
      ELSE 'owner_cleanup_candidate'
    END,
    'rba-owner-media-cleanup-v1', coalesce(m.duration_sec, 0),
    greatest(0, floor(coalesce(m.duration_sec, 0) + 0.5)::integer),
    clock_timestamp(), clock_timestamp(), 'infinity'::timestamptz
  FROM cleanup_input i JOIN public.motion_clips m ON m.id = i.clip_id
  WHERE NOT EXISTS (
    SELECT 1 FROM public.motion_clip_system_exclusions sx WHERE sx.clip_id = i.clip_id
  );

  UPDATE public.motion_clip_system_exclusions sx
  SET state = 'quarantined', reason_code = 'owner_cleanup_candidate',
      rule_version = 'rba-owner-media-cleanup-v1',
      quarantined_at = clock_timestamp(), delete_after = 'infinity'::timestamptz,
      updated_at = clock_timestamp()
  FROM cleanup_input i
  WHERE sx.clip_id = i.clip_id
    AND sx.state = 'candidate' AND sx.reason_code = 'short_device_error';

  INSERT INTO public.rba_owner_media_cleanup_events
    (cohort_id, item_id, clip_id, event_type, actor_id, detail)
  SELECT v_cohort_id, i.id, i.clip_id, 'prepared', p_owner_id,
         jsonb_build_object(
           'seed_reason', i.seed_reason,
           'source_present', i.source_present,
           'thumbnail_present', i.thumbnail_present
         )
  FROM public.rba_owner_media_cleanup_items i WHERE i.cohort_id = v_cohort_id;

  RETURN jsonb_build_object(
    'prepared', true, 'cohort_id', v_cohort_id,
    'total', 951, 'confirmed_invalid', 46, 'protected_gt', 1,
    'owner_review', 904, 'source_missing', 7, 'owner_review_available', 897,
    'reused_short_candidates', 11
  );
END;
$$;

CREATE FUNCTION public.fn_list_rba_owner_media_cleanup_v1(
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
  SELECT m.id, m.started_at, m.duration_sec, c.name, i.seed_reason, i.state,
         i.has_canonical_gt, d.decision
  FROM public.rba_owner_media_cleanup_cohorts co
  JOIN public.rba_owner_media_cleanup_items i ON i.cohort_id = co.id
  JOIN public.motion_clips m ON m.id = i.clip_id
  LEFT JOIN public.cameras c ON c.id = m.camera_id
  LEFT JOIN public.rba_owner_media_cleanup_decisions d ON d.item_id = i.id
  WHERE co.owner_id = p_owner_id
    AND i.seed_reason IN ('owner_review_pending','protected_gt')
    AND i.state <> 'source_missing'
    AND (p_cursor_started_at IS NULL OR m.started_at > p_cursor_started_at
      OR (m.started_at = p_cursor_started_at AND m.id > p_cursor_clip_id))
  ORDER BY m.started_at, m.id LIMIT p_limit;
END;
$$;

CREATE FUNCTION public.fn_decide_rba_owner_media_cleanup_v1(
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
  SELECT i.* INTO v_item
  FROM public.rba_owner_media_cleanup_items i
  WHERE i.clip_id = p_clip_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'cleanup_owner_forbidden' USING ERRCODE = 'PT403';
  END IF;
  SELECT c.owner_id INTO v_expected_owner
  FROM public.rba_owner_media_cleanup_cohorts c WHERE c.id = v_item.cohort_id;
  IF v_expected_owner <> p_owner_id OR v_item.seed_reason <> 'owner_review_pending' THEN
    RAISE EXCEPTION 'cleanup_owner_forbidden' USING ERRCODE = 'PT403';
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

CREATE FUNCTION public.fn_claim_rba_owner_media_move_v1(
  p_stage text, p_worker_host text, p_limit integer DEFAULT 20
) RETURNS TABLE (
  item_id uuid, clip_id uuid, source_r2_key text, source_thumbnail_key text,
  seed_reason text, lease_token uuid
)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
  IF p_stage NOT IN ('quarantine','delete_confirmed','restore_keep')
     OR btrim(coalesce(p_worker_host, '')) = '' OR p_limit NOT BETWEEN 1 AND 30 THEN
    RAISE EXCEPTION 'cleanup_claim_invalid' USING ERRCODE = '22023';
  END IF;
  RETURN QUERY
  WITH candidates AS (
    SELECT i.id
    FROM public.rba_owner_media_cleanup_items i
    LEFT JOIN public.rba_owner_media_cleanup_decisions d ON d.item_id = i.id
    WHERE (i.lease_token IS NULL OR i.lease_expires_at <= clock_timestamp())
      AND (
        (p_stage = 'quarantine' AND i.state IN ('prepared','move_failed'))
        OR (p_stage = 'delete_confirmed' AND i.state = 'quarantined'
            AND i.seed_reason IN ('confirmed_gecko_absent','confirmed_no_gecko_activity'))
        OR (p_stage = 'restore_keep' AND i.state = 'decision_recorded' AND d.decision = 'keep')
      )
    ORDER BY i.created_at, i.id FOR UPDATE OF i SKIP LOCKED LIMIT p_limit
  ), claimed AS (
    UPDATE public.rba_owner_media_cleanup_items i
    SET lease_from_state = i.state, state = 'moving', lease_stage = p_stage,
        lease_token = gen_random_uuid(), lease_expires_at = clock_timestamp() + interval '10 minutes',
        worker_host = p_worker_host, updated_at = clock_timestamp()
    FROM candidates c WHERE i.id = c.id
    RETURNING i.*
  )
  SELECT c.id, c.clip_id, c.source_r2_key, c.source_thumbnail_key,
         c.seed_reason, c.lease_token FROM claimed c;
END;
$$;

CREATE FUNCTION public.fn_complete_rba_owner_media_move_v1(
  p_item_id uuid, p_lease_token uuid, p_destination_r2_key text,
  p_destination_thumbnail_key text, p_source_fingerprint jsonb,
  p_destination_fingerprint jsonb
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  i public.rba_owner_media_cleanup_items%rowtype;
  v_updated integer;
  v_target_state text;
BEGIN
  SELECT * INTO i FROM public.rba_owner_media_cleanup_items
  WHERE id = p_item_id FOR UPDATE;
  IF NOT FOUND OR i.state <> 'moving' OR i.lease_token <> p_lease_token
     OR i.lease_expires_at <= clock_timestamp() THEN
    RAISE EXCEPTION 'cleanup_move_lease_invalid' USING ERRCODE = 'PT409';
  END IF;
  IF btrim(coalesce(p_destination_r2_key, '')) = '' THEN
    RAISE EXCEPTION 'cleanup_destination_invalid' USING ERRCODE = '22023';
  END IF;

  UPDATE public.motion_clips m
  SET r2_key = p_destination_r2_key,
      thumbnail_key = p_destination_thumbnail_key
  FROM public.rba_owner_media_cleanup_items i
  WHERE i.id = p_item_id AND m.id = i.clip_id
    AND m.r2_key = i.source_r2_key
    AND m.thumbnail_key IS NOT DISTINCT FROM i.source_thumbnail_key;
  GET DIAGNOSTICS v_updated = ROW_COUNT;
  IF v_updated <> 1 THEN
    RAISE EXCEPTION 'media_key_cas_failed' USING ERRCODE = 'PT409';
  END IF;

  v_target_state := CASE i.lease_stage
    WHEN 'quarantine' THEN 'quarantined'
    WHEN 'delete_confirmed' THEN 'media_deleted'
    WHEN 'restore_keep' THEN 'restored'
  END;
  UPDATE public.rba_owner_media_cleanup_items
  SET source_r2_key = p_destination_r2_key,
      source_thumbnail_key = p_destination_thumbnail_key,
      source_fingerprint = p_source_fingerprint,
      destination_fingerprint = p_destination_fingerprint,
      state = v_target_state,
      quarantined_at = CASE WHEN i.lease_stage = 'quarantine' THEN clock_timestamp() ELSE quarantined_at END,
      media_deleted_at = CASE WHEN i.lease_stage = 'delete_confirmed' THEN clock_timestamp() ELSE media_deleted_at END,
      lease_stage = NULL, lease_from_state = NULL, lease_token = NULL,
      lease_expires_at = NULL, worker_host = NULL, last_error_code = NULL,
      updated_at = clock_timestamp()
  WHERE id = p_item_id;
  IF v_target_state = 'media_deleted' THEN
    UPDATE public.motion_clip_system_exclusions
    SET state = 'media_deleted', media_deleted_at = clock_timestamp(), updated_at = clock_timestamp()
    WHERE clip_id = i.clip_id;
  ELSIF v_target_state = 'restored' THEN
    UPDATE public.motion_clip_system_exclusions
    SET state = 'restored', restored_at = clock_timestamp(), updated_at = clock_timestamp()
    WHERE clip_id = i.clip_id;
  END IF;
  INSERT INTO public.rba_owner_media_cleanup_events
    (cohort_id, item_id, clip_id, event_type, worker_host, detail)
  VALUES (i.cohort_id, i.id, i.clip_id, 'move_completed', i.worker_host,
          jsonb_build_object('stage', i.lease_stage, 'state', v_target_state));
  RETURN jsonb_build_object('completed', true, 'state', v_target_state);
END;
$$;

CREATE FUNCTION public.fn_fail_rba_owner_media_move_v1(
  p_item_id uuid, p_lease_token uuid, p_error_code text
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  i public.rba_owner_media_cleanup_items%rowtype;
BEGIN
  SELECT * INTO i FROM public.rba_owner_media_cleanup_items
  WHERE id = p_item_id FOR UPDATE;
  IF NOT FOUND OR i.state <> 'moving' OR i.lease_token <> p_lease_token THEN
    RAISE EXCEPTION 'cleanup_move_lease_invalid' USING ERRCODE = 'PT409';
  END IF;
  UPDATE public.rba_owner_media_cleanup_items
  SET state = 'move_failed', last_error_code = left(coalesce(p_error_code, 'unknown'), 200),
      lease_stage = NULL, lease_from_state = NULL, lease_token = NULL,
      lease_expires_at = NULL, worker_host = NULL, updated_at = clock_timestamp()
  WHERE id = p_item_id;
  INSERT INTO public.rba_owner_media_cleanup_events
    (cohort_id, item_id, clip_id, event_type, worker_host, detail)
  VALUES (i.cohort_id, i.id, i.clip_id, 'move_failed', i.worker_host,
          jsonb_build_object('stage', i.lease_stage, 'error_code', left(coalesce(p_error_code, 'unknown'), 200)));
  RETURN jsonb_build_object('failed', true);
END;
$$;

REVOKE ALL ON FUNCTION public.fn_prepare_rba_owner_media_cleanup_v1(text, uuid, text, jsonb)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_prepare_rba_owner_media_cleanup_v1(text, uuid, text, jsonb)
  TO service_role;
REVOKE ALL ON FUNCTION public.fn_list_rba_owner_media_cleanup_v1(uuid, timestamptz, uuid, integer)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_list_rba_owner_media_cleanup_v1(uuid, timestamptz, uuid, integer)
  TO service_role;
REVOKE ALL ON FUNCTION public.fn_decide_rba_owner_media_cleanup_v1(uuid, uuid, text, text)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_decide_rba_owner_media_cleanup_v1(uuid, uuid, text, text)
  TO service_role;
REVOKE ALL ON FUNCTION public.fn_claim_rba_owner_media_move_v1(text, text, integer)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_claim_rba_owner_media_move_v1(text, text, integer)
  TO service_role;
REVOKE ALL ON FUNCTION public.fn_complete_rba_owner_media_move_v1(uuid, uuid, text, text, jsonb, jsonb)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_complete_rba_owner_media_move_v1(uuid, uuid, text, text, jsonb, jsonb)
  TO service_role;
REVOKE ALL ON FUNCTION public.fn_fail_rba_owner_media_move_v1(uuid, uuid, text)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_fail_rba_owner_media_move_v1(uuid, uuid, text)
  TO service_role;

COMMIT;
