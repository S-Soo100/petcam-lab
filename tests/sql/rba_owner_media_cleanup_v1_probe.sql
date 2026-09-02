BEGIN;

DO $$
DECLARE
  v_owner uuid := 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  v_camera_a uuid := 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
  v_camera_b uuid := 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
  v_clip uuid;
  v_pair uuid;
  v_items jsonb;
  v_result jsonb;
  v_count integer;
  idx integer;
  v_claim record;
BEGIN
  INSERT INTO public.cameras (id, name)
  VALUES (v_camera_a, 'camera-a'), (v_camera_b, 'camera-b');

  INSERT INTO public.motion_clips
    (id, camera_id, started_at, duration_sec, r2_key, thumbnail_key)
  SELECT
    ('10000000-0000-4000-8000-' || lpad(n::text, 12, '0'))::uuid,
    CASE WHEN n <= 280 THEN v_camera_a ELSE v_camera_b END,
    CASE WHEN n <= 280
      THEN '2026-06-30 00:00:00+09'::timestamptz + n * interval '1 minute'
      ELSE '2026-07-14 00:00:00+09'::timestamptz + (n - 280) * interval '1 minute'
    END,
    30, 'clips/test/' || n || '.mp4', 'thumbs/test/' || n || '.jpg'
  FROM generate_series(1, 951) AS values_(n);

  FOR idx IN 1..23 LOOP
    v_clip := ('10000000-0000-4000-8000-' || lpad(idx::text, 12, '0'))::uuid;
    INSERT INTO public.rba_boundary_review_pairs (left_clip_id, right_clip_id)
    VALUES (v_clip, v_clip) RETURNING id INTO v_pair;
    INSERT INTO public.rba_boundary_eligibility_reviews (pair_id, decision)
    VALUES (v_pair, 'both_gecko_absent');
  END LOOP;
  FOR idx IN 281..303 LOOP
    v_clip := ('10000000-0000-4000-8000-' || lpad(idx::text, 12, '0'))::uuid;
    INSERT INTO public.rba_boundary_review_pairs (left_clip_id, right_clip_id)
    VALUES (v_clip, v_clip) RETURNING id INTO v_pair;
    INSERT INTO public.rba_boundary_eligibility_reviews (pair_id, decision)
    VALUES (v_pair, 'both_no_gecko_activity');
  END LOOP;

  INSERT INTO public.motion_clip_labeling_sessions (clip_id, initial_gt)
  VALUES ('10000000-0000-4000-8000-000000000304', '{"primary_action":"static"}');

  INSERT INTO public.motion_clip_system_exclusions
    (clip_id, camera_id, state, reason_code, rule_version,
     observed_duration_sec, displayed_duration_sec, detected_at)
  SELECT id, camera_id, 'candidate', 'short_device_error', 'probe-old-rule',
         duration_sec, 30, clock_timestamp()
  FROM public.motion_clips
  WHERE substring(id::text from 25)::bigint BETWEEN 305 AND 315;

  SELECT jsonb_agg(jsonb_build_object(
    'clip_id', m.id,
    'seed_reason', CASE
      WHEN substring(m.id::text from 25)::bigint BETWEEN 1 AND 23
        THEN 'confirmed_gecko_absent'
      WHEN substring(m.id::text from 25)::bigint BETWEEN 281 AND 303
        THEN 'confirmed_no_gecko_activity'
      WHEN substring(m.id::text from 25)::bigint = 304 THEN 'protected_gt'
      ELSE 'owner_review_pending'
    END,
    'source_r2_key', m.r2_key,
    'source_thumbnail_key', m.thumbnail_key,
    'source_present', substring(m.id::text from 25)::bigint NOT BETWEEN 945 AND 951,
    'thumbnail_present', substring(m.id::text from 25)::bigint NOT BETWEEN 944 AND 951
  ) ORDER BY m.started_at, m.id)
  INTO v_items FROM public.motion_clips m;

  SELECT public.fn_prepare_rba_owner_media_cleanup_v1(
    'rba-owner-cleanup-v1', v_owner, repeat('a', 64), v_items
  ) INTO v_result;
  ASSERT (v_result->>'total')::integer = 951;
  ASSERT (v_result->>'source_missing')::integer = 7;
  ASSERT (v_result->>'owner_review_available')::integer = 897;

  SELECT count(*) INTO v_count FROM public.rba_owner_media_cleanup_items;
  ASSERT v_count = 951;
  SELECT count(*) INTO v_count
  FROM public.rba_owner_media_cleanup_items WHERE state = 'source_missing';
  ASSERT v_count = 7;
  SELECT count(*) INTO v_count FROM public.motion_clip_system_exclusions;
  ASSERT v_count = 951;

  SELECT * INTO v_claim
  FROM public.fn_claim_rba_owner_media_move_v1('quarantine', 'probe-host', 1);
  ASSERT v_claim.item_id IS NOT NULL;
  PERFORM public.fn_complete_rba_owner_media_move_v1(
    v_claim.item_id, v_claim.lease_token,
    'research-quarantine/rba-owner-cleanup-v1/probe/video.mp4',
    'research-quarantine/rba-owner-cleanup-v1/probe/thumb.jpg',
    '{}'::jsonb, '{}'::jsonb
  );
  SELECT count(*) INTO v_count
  FROM public.rba_owner_media_cleanup_items WHERE state = 'quarantined';
  ASSERT v_count = 1;

  UPDATE public.rba_owner_media_cleanup_items
  SET state = 'quarantined'
  WHERE clip_id = '10000000-0000-4000-8000-000000000305';

  PERFORM public.fn_decide_rba_owner_media_cleanup_v1(
    v_owner, '10000000-0000-4000-8000-000000000305', 'keep', NULL
  );
  BEGIN
    UPDATE public.rba_owner_media_cleanup_decisions SET decision = 'uncertain';
    RAISE EXCEPTION 'append-only decision update unexpectedly succeeded';
  EXCEPTION WHEN feature_not_supported THEN NULL;
  END;

  RAISE NOTICE 'RBA_OWNER_MEDIA_CLEANUP_PROBE_OK';
END;
$$;

ROLLBACK;

SELECT 'PROBE_RESIDUE=' || (
  (SELECT count(*) FROM public.rba_owner_media_cleanup_items)
  + (SELECT count(*) FROM public.motion_clips)
)::text;
