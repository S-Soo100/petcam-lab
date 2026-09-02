-- production 첫 move probe에서 발견한 PL/pgSQL row 변수/SQL alias 이름 충돌(42702) 수정.
BEGIN;

CREATE OR REPLACE FUNCTION public.fn_complete_rba_owner_media_move_v1(
  p_item_id uuid, p_lease_token uuid, p_destination_r2_key text,
  p_destination_thumbnail_key text, p_source_fingerprint jsonb,
  p_destination_fingerprint jsonb
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  v_item public.rba_owner_media_cleanup_items%rowtype;
  v_updated integer;
  v_target_state text;
BEGIN
  SELECT cleanup_item.* INTO v_item
  FROM public.rba_owner_media_cleanup_items cleanup_item
  WHERE cleanup_item.id = p_item_id FOR UPDATE;
  IF NOT FOUND OR v_item.state <> 'moving' OR v_item.lease_token <> p_lease_token
     OR v_item.lease_expires_at <= clock_timestamp() THEN
    RAISE EXCEPTION 'cleanup_move_lease_invalid' USING ERRCODE = 'PT409';
  END IF;
  IF btrim(coalesce(p_destination_r2_key, '')) = '' THEN
    RAISE EXCEPTION 'cleanup_destination_invalid' USING ERRCODE = '22023';
  END IF;

  UPDATE public.motion_clips media
  SET r2_key = p_destination_r2_key,
      thumbnail_key = p_destination_thumbnail_key
  FROM public.rba_owner_media_cleanup_items cleanup_item
  WHERE cleanup_item.id = p_item_id AND media.id = cleanup_item.clip_id
    AND media.r2_key = cleanup_item.source_r2_key
    AND media.thumbnail_key IS NOT DISTINCT FROM cleanup_item.source_thumbnail_key;
  GET DIAGNOSTICS v_updated = ROW_COUNT;
  IF v_updated <> 1 THEN
    RAISE EXCEPTION 'media_key_cas_failed' USING ERRCODE = 'PT409';
  END IF;

  v_target_state := CASE v_item.lease_stage
    WHEN 'quarantine' THEN 'quarantined'
    WHEN 'delete_confirmed' THEN 'media_deleted'
    WHEN 'restore_keep' THEN 'restored'
  END;
  UPDATE public.rba_owner_media_cleanup_items AS current_item
  SET source_r2_key = p_destination_r2_key,
      source_thumbnail_key = p_destination_thumbnail_key,
      source_fingerprint = p_source_fingerprint,
      destination_fingerprint = p_destination_fingerprint,
      state = v_target_state,
      quarantined_at = CASE
        WHEN v_item.lease_stage = 'quarantine' THEN clock_timestamp()
        ELSE current_item.quarantined_at
      END,
      media_deleted_at = CASE
        WHEN v_item.lease_stage = 'delete_confirmed' THEN clock_timestamp()
        ELSE current_item.media_deleted_at
      END,
      lease_stage = NULL, lease_from_state = NULL, lease_token = NULL,
      lease_expires_at = NULL, worker_host = NULL, last_error_code = NULL,
      updated_at = clock_timestamp()
  WHERE current_item.id = p_item_id;
  IF v_target_state = 'media_deleted' THEN
    UPDATE public.motion_clip_system_exclusions
    SET state = 'media_deleted', media_deleted_at = clock_timestamp(),
        updated_at = clock_timestamp()
    WHERE clip_id = v_item.clip_id;
  ELSIF v_target_state = 'restored' THEN
    UPDATE public.motion_clip_system_exclusions
    SET state = 'restored', restored_at = clock_timestamp(),
        updated_at = clock_timestamp()
    WHERE clip_id = v_item.clip_id;
  END IF;
  INSERT INTO public.rba_owner_media_cleanup_events
    (cohort_id, item_id, clip_id, event_type, worker_host, detail)
  VALUES (
    v_item.cohort_id, v_item.id, v_item.clip_id, 'move_completed', v_item.worker_host,
    jsonb_build_object('stage', v_item.lease_stage, 'state', v_target_state)
  );
  RETURN jsonb_build_object('completed', true, 'state', v_target_state);
END;
$$;

REVOKE ALL ON FUNCTION public.fn_complete_rba_owner_media_move_v1(
  uuid, uuid, text, text, jsonb, jsonb
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_complete_rba_owner_media_move_v1(
  uuid, uuid, text, text, jsonb, jsonb
) TO service_role;

COMMIT;
