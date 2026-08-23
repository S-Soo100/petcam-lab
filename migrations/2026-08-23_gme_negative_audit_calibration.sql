BEGIN;

-- GME negative audit은 기존 GME/GT를 고치지 않고, frozen 입력과 사람 판정을 별도 원장에 쌓는다.
CREATE TABLE public.gme_negative_audit_batches (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
  schema_version text NOT NULL DEFAULT 'gme-negative-audit-v1'
    CHECK (schema_version = 'gme-negative-audit-v1'),
  batch_kind text NOT NULL CHECK (batch_kind IN ('calibration','preview_canary')),
  test_sheet_sha256 text NOT NULL CHECK (test_sheet_sha256 ~ '^[0-9a-f]{64}$'),
  manifest_sha256 text NOT NULL UNIQUE CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$'),
  seed text NOT NULL CHECK (btrim(seed) <> ''),
  cutoff timestamptz NOT NULL,
  detector_identity text NOT NULL CHECK (detector_identity ~ '^[0-9a-f]{64}$'),
  checkpoint_sha256 text NOT NULL CHECK (checkpoint_sha256 ~ '^[0-9a-f]{64}$'),
  negative_pool_sha256 text NOT NULL CHECK (negative_pool_sha256 ~ '^[0-9a-f]{64}$'),
  control_pool_sha256 text NOT NULL CHECK (control_pool_sha256 ~ '^[0-9a-f]{64}$'),
  selection_sha256 text NOT NULL CHECK (selection_sha256 ~ '^[0-9a-f]{64}$'),
  protected_manifest_sha256 jsonb NOT NULL
    CHECK (jsonb_typeof(protected_manifest_sha256) = 'array'),
  expected_negative_count integer NOT NULL,
  expected_control_count integer NOT NULL,
  expected_total_count integer NOT NULL,
  candidate_negative_count integer NOT NULL CHECK (candidate_negative_count >= expected_negative_count),
  candidate_control_count integer NOT NULL CHECK (candidate_control_count >= expected_control_count),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CHECK (
    (batch_kind = 'calibration'
      AND expected_negative_count = 120
      AND expected_control_count = 30
      AND expected_total_count = 150)
    OR
    (batch_kind = 'preview_canary'
      AND expected_negative_count = 4
      AND expected_control_count = 2
      AND expected_total_count = 6)
  ),
  CHECK (expected_total_count = expected_negative_count + expected_control_count)
);

CREATE TABLE public.gme_negative_audit_batch_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  batch_id uuid NOT NULL REFERENCES public.gme_negative_audit_batches(id) ON DELETE RESTRICT,
  event_type text NOT NULL
    CHECK (event_type IN ('prepared','opened','closed','scored','invalidated')),
  actor_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
  reason text CHECK (reason IS NULL OR char_length(btrim(reason)) BETWEEN 1 AND 2000),
  digest text NOT NULL UNIQUE CHECK (digest ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (batch_id, event_type)
);

CREATE TABLE public.gme_negative_audit_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  batch_id uuid NOT NULL REFERENCES public.gme_negative_audit_batches(id) ON DELETE RESTRICT,
  ordinal integer NOT NULL CHECK (ordinal > 0),
  clip_id uuid NOT NULL REFERENCES public.motion_clips(id) ON DELETE RESTRICT,
  stratum text NOT NULL CHECK (stratum IN ('random_negative','positive_control')),
  started_at timestamptz NOT NULL,
  duration_sec numeric NOT NULL CHECK (duration_sec > 0),
  camera_night_key text NOT NULL CHECK (btrim(camera_night_key) <> ''),
  episode_key text NOT NULL CHECK (btrim(episode_key) <> ''),
  gme_run_id uuid NOT NULL REFERENCES public.gme_runs(id) ON DELETE RESTRICT,
  detector_identity text NOT NULL CHECK (detector_identity ~ '^[0-9a-f]{64}$'),
  media_sha256 text NOT NULL CHECK (media_sha256 ~ '^[0-9a-f]{64}$'),
  media_dhash text NOT NULL CHECK (media_dhash ~ '^[0-9a-f]{16}$'),
  gme_detected boolean NOT NULL,
  human_gt_digest text CHECK (human_gt_digest IS NULL OR human_gt_digest ~ '^[0-9a-f]{64}$'),
  selection_provenance text NOT NULL CHECK (selection_provenance ~ '^[0-9a-f]{64}$'),
  assigned_reviewer_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (batch_id, ordinal),
  UNIQUE (batch_id, clip_id),
  UNIQUE (batch_id, media_sha256),
  CHECK (
    (stratum = 'random_negative' AND gme_detected IS FALSE AND human_gt_digest IS NULL)
    OR
    (stratum = 'positive_control' AND human_gt_digest IS NOT NULL)
  )
);

CREATE TABLE public.gme_negative_audit_submissions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  item_id uuid NOT NULL UNIQUE REFERENCES public.gme_negative_audit_items(id) ON DELETE RESTRICT,
  reviewer_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
  verdict text NOT NULL CHECK (verdict IN ('gecko_present','gecko_absent','uncertain','media_error')),
  representative_sec numeric,
  bbox jsonb,
  digest text NOT NULL UNIQUE CHECK (digest ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CHECK (
    (verdict = 'gecko_present' AND representative_sec IS NOT NULL AND bbox IS NOT NULL)
    OR
    (verdict <> 'gecko_present' AND representative_sec IS NULL AND bbox IS NULL)
  )
);

CREATE TABLE public.gme_negative_audit_corrections (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  item_id uuid NOT NULL REFERENCES public.gme_negative_audit_items(id) ON DELETE RESTRICT,
  original_submission_id uuid NOT NULL REFERENCES public.gme_negative_audit_submissions(id) ON DELETE RESTRICT,
  reviewer_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
  verdict text NOT NULL CHECK (verdict IN ('gecko_present','gecko_absent','uncertain','media_error')),
  representative_sec numeric,
  bbox jsonb,
  reason text NOT NULL CHECK (char_length(btrim(reason)) BETWEEN 1 AND 2000),
  expected_submission_digest text NOT NULL CHECK (expected_submission_digest ~ '^[0-9a-f]{64}$'),
  digest text NOT NULL UNIQUE CHECK (digest ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (item_id, expected_submission_digest),
  CHECK (
    (verdict = 'gecko_present' AND representative_sec IS NOT NULL AND bbox IS NOT NULL)
    OR
    (verdict <> 'gecko_present' AND representative_sec IS NULL AND bbox IS NULL)
  )
);

CREATE TABLE public.gme_negative_audit_adjudications (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  item_id uuid NOT NULL UNIQUE REFERENCES public.gme_negative_audit_items(id) ON DELETE RESTRICT,
  original_submission_id uuid NOT NULL REFERENCES public.gme_negative_audit_submissions(id) ON DELETE RESTRICT,
  owner_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
  final_verdict text NOT NULL CHECK (final_verdict IN ('gecko_present','gecko_absent','uncertain','media_error')),
  representative_sec numeric,
  bbox jsonb,
  reason text NOT NULL CHECK (char_length(btrim(reason)) BETWEEN 1 AND 2000),
  effective_submission_digest text NOT NULL CHECK (effective_submission_digest ~ '^[0-9a-f]{64}$'),
  digest text NOT NULL UNIQUE CHECK (digest ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CHECK (
    (final_verdict = 'gecko_present' AND representative_sec IS NOT NULL AND bbox IS NOT NULL)
    OR
    (final_verdict <> 'gecko_present' AND representative_sec IS NULL AND bbox IS NULL)
  )
);

CREATE TABLE public.gme_negative_audit_dataset_decisions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  item_id uuid NOT NULL REFERENCES public.gme_negative_audit_items(id) ON DELETE RESTRICT,
  owner_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
  decision text NOT NULL CHECK (decision IN (
    'include_candidate','exclude_duplicate','exclude_holdout','exclude_quality','defer'
  )),
  reason text NOT NULL CHECK (char_length(btrim(reason)) BETWEEN 1 AND 2000),
  effective_submission_digest text NOT NULL CHECK (effective_submission_digest ~ '^[0-9a-f]{64}$'),
  adjudication_id uuid REFERENCES public.gme_negative_audit_adjudications(id) ON DELETE RESTRICT,
  digest text NOT NULL UNIQUE CHECK (digest ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX idx_gme_negative_audit_events_latest
  ON public.gme_negative_audit_batch_events (batch_id, created_at DESC, id DESC);
CREATE INDEX idx_gme_negative_audit_items_assignment
  ON public.gme_negative_audit_items (assigned_reviewer_id, batch_id, ordinal);
CREATE INDEX idx_gme_negative_audit_corrections_latest
  ON public.gme_negative_audit_corrections (item_id, created_at DESC, id DESC);
CREATE INDEX idx_gme_negative_audit_decisions_latest
  ON public.gme_negative_audit_dataset_decisions (item_id, created_at DESC, id DESC);

ALTER TABLE public.gme_negative_audit_batches ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.gme_negative_audit_batch_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.gme_negative_audit_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.gme_negative_audit_submissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.gme_negative_audit_corrections ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.gme_negative_audit_adjudications ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.gme_negative_audit_dataset_decisions ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.gme_negative_audit_batches FROM PUBLIC, anon, authenticated;
REVOKE ALL ON public.gme_negative_audit_batch_events FROM PUBLIC, anon, authenticated;
REVOKE ALL ON public.gme_negative_audit_items FROM PUBLIC, anon, authenticated;
REVOKE ALL ON public.gme_negative_audit_submissions FROM PUBLIC, anon, authenticated;
REVOKE ALL ON public.gme_negative_audit_corrections FROM PUBLIC, anon, authenticated;
REVOKE ALL ON public.gme_negative_audit_adjudications FROM PUBLIC, anon, authenticated;
REVOKE ALL ON public.gme_negative_audit_dataset_decisions FROM PUBLIC, anon, authenticated;

GRANT SELECT, INSERT ON public.gme_negative_audit_batches TO service_role;
GRANT SELECT, INSERT ON public.gme_negative_audit_batch_events TO service_role;
GRANT SELECT, INSERT ON public.gme_negative_audit_items TO service_role;
GRANT SELECT, INSERT ON public.gme_negative_audit_submissions TO service_role;
GRANT SELECT, INSERT ON public.gme_negative_audit_corrections TO service_role;
GRANT SELECT, INSERT ON public.gme_negative_audit_adjudications TO service_role;
GRANT SELECT, INSERT ON public.gme_negative_audit_dataset_decisions TO service_role;

CREATE FUNCTION public.fn_block_gme_negative_audit_mutation()
RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
BEGIN
  RAISE EXCEPTION 'GME negative audit ledgers are append-only' USING ERRCODE = '0A000';
END;
$$;

REVOKE ALL ON FUNCTION public.fn_block_gme_negative_audit_mutation()
  FROM PUBLIC, anon, authenticated;

CREATE TRIGGER trg_gme_negative_audit_batches_ud
  BEFORE UPDATE OR DELETE ON public.gme_negative_audit_batches
  FOR EACH ROW EXECUTE FUNCTION public.fn_block_gme_negative_audit_mutation();
CREATE TRIGGER trg_gme_negative_audit_batches_truncate
  BEFORE TRUNCATE ON public.gme_negative_audit_batches
  FOR EACH STATEMENT EXECUTE FUNCTION public.fn_block_gme_negative_audit_mutation();
CREATE TRIGGER trg_gme_negative_audit_batch_events_ud
  BEFORE UPDATE OR DELETE ON public.gme_negative_audit_batch_events
  FOR EACH ROW EXECUTE FUNCTION public.fn_block_gme_negative_audit_mutation();
CREATE TRIGGER trg_gme_negative_audit_batch_events_truncate
  BEFORE TRUNCATE ON public.gme_negative_audit_batch_events
  FOR EACH STATEMENT EXECUTE FUNCTION public.fn_block_gme_negative_audit_mutation();
CREATE TRIGGER trg_gme_negative_audit_items_ud
  BEFORE UPDATE OR DELETE ON public.gme_negative_audit_items
  FOR EACH ROW EXECUTE FUNCTION public.fn_block_gme_negative_audit_mutation();
CREATE TRIGGER trg_gme_negative_audit_items_truncate
  BEFORE TRUNCATE ON public.gme_negative_audit_items
  FOR EACH STATEMENT EXECUTE FUNCTION public.fn_block_gme_negative_audit_mutation();
CREATE TRIGGER trg_gme_negative_audit_submissions_ud
  BEFORE UPDATE OR DELETE ON public.gme_negative_audit_submissions
  FOR EACH ROW EXECUTE FUNCTION public.fn_block_gme_negative_audit_mutation();
CREATE TRIGGER trg_gme_negative_audit_submissions_truncate
  BEFORE TRUNCATE ON public.gme_negative_audit_submissions
  FOR EACH STATEMENT EXECUTE FUNCTION public.fn_block_gme_negative_audit_mutation();
CREATE TRIGGER trg_gme_negative_audit_corrections_ud
  BEFORE UPDATE OR DELETE ON public.gme_negative_audit_corrections
  FOR EACH ROW EXECUTE FUNCTION public.fn_block_gme_negative_audit_mutation();
CREATE TRIGGER trg_gme_negative_audit_corrections_truncate
  BEFORE TRUNCATE ON public.gme_negative_audit_corrections
  FOR EACH STATEMENT EXECUTE FUNCTION public.fn_block_gme_negative_audit_mutation();
CREATE TRIGGER trg_gme_negative_audit_adjudications_ud
  BEFORE UPDATE OR DELETE ON public.gme_negative_audit_adjudications
  FOR EACH ROW EXECUTE FUNCTION public.fn_block_gme_negative_audit_mutation();
CREATE TRIGGER trg_gme_negative_audit_adjudications_truncate
  BEFORE TRUNCATE ON public.gme_negative_audit_adjudications
  FOR EACH STATEMENT EXECUTE FUNCTION public.fn_block_gme_negative_audit_mutation();
CREATE TRIGGER trg_gme_negative_audit_dataset_decisions_ud
  BEFORE UPDATE OR DELETE ON public.gme_negative_audit_dataset_decisions
  FOR EACH ROW EXECUTE FUNCTION public.fn_block_gme_negative_audit_mutation();
CREATE TRIGGER trg_gme_negative_audit_dataset_decisions_truncate
  BEFORE TRUNCATE ON public.gme_negative_audit_dataset_decisions
  FOR EACH STATEMENT EXECUTE FUNCTION public.fn_block_gme_negative_audit_mutation();

-- event insert와 submission을 같은 batch-row lock으로 직렬화해 close/submit race를 막는다.
CREATE FUNCTION public.fn_validate_gme_negative_audit_batch_event()
RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  batch public.gme_negative_audit_batches%ROWTYPE;
  previous_event text;
BEGIN
  SELECT * INTO batch FROM public.gme_negative_audit_batches current_batch
  WHERE current_batch.id = NEW.batch_id FOR UPDATE;
  IF NOT FOUND OR batch.owner_id <> NEW.actor_id THEN
    RAISE EXCEPTION 'batch_event_owner_forbidden' USING ERRCODE = 'PT403';
  END IF;
  SELECT event.event_type INTO previous_event
  FROM public.gme_negative_audit_batch_events event
  WHERE event.batch_id = NEW.batch_id
  ORDER BY event.created_at DESC, event.id DESC LIMIT 1;
  IF (
    (NEW.event_type = 'prepared' AND previous_event IS NULL)
    OR (NEW.event_type = 'opened' AND previous_event = 'prepared')
    OR (NEW.event_type = 'closed' AND previous_event = 'opened')
    OR (NEW.event_type = 'scored' AND previous_event = 'closed')
    OR (NEW.event_type = 'invalidated' AND previous_event IN ('prepared','opened','closed'))
  ) IS NOT TRUE THEN
    RAISE EXCEPTION 'invalid_batch_event_transition' USING ERRCODE = '22023';
  END IF;
  RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.fn_validate_gme_negative_audit_batch_event()
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_validate_gme_negative_audit_batch_event() TO service_role;
CREATE TRIGGER trg_validate_gme_negative_audit_batch_event
  BEFORE INSERT ON public.gme_negative_audit_batch_events
  FOR EACH ROW EXECUTE FUNCTION public.fn_validate_gme_negative_audit_batch_event();

-- Python utf8-canonical-json-v1과 같은 manifest hash 입력을 만든다.
-- duration은 exponent 없는 decimal string이라 jsonb numeric 출력 차이를 원천 제거한다.
CREATE FUNCTION public.fn_gme_negative_audit_canonical_json(p_value jsonb)
RETURNS text LANGUAGE plpgsql IMMUTABLE SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  v_type text;
  v_result text;
BEGIN
  v_type := jsonb_typeof(p_value);
  IF v_type = 'object' THEN
    SELECT '{' || coalesce(string_agg(
      to_jsonb(entry.key)::text || ':' || public.fn_gme_negative_audit_canonical_json(entry.value),
      ',' ORDER BY entry.key
    ), '') || '}'
    INTO v_result
    FROM jsonb_each(p_value) AS entry;
    RETURN v_result;
  ELSIF v_type = 'array' THEN
    SELECT '[' || coalesce(string_agg(
      public.fn_gme_negative_audit_canonical_json(entry.value), ',' ORDER BY entry.ordinality
    ), '') || ']'
    INTO v_result
    FROM jsonb_array_elements(p_value) WITH ORDINALITY AS entry(value, ordinality);
    RETURN v_result;
  END IF;
  RETURN p_value::text;
END;
$$;

CREATE FUNCTION public.fn_gme_negative_audit_manifest_candidate(p_item jsonb)
RETURNS jsonb LANGUAGE sql IMMUTABLE SECURITY INVOKER SET search_path = '' AS $$
  SELECT jsonb_build_object(
    'clip_id', p_item ->> 'clip_id',
    'stratum', p_item ->> 'stratum',
    'started_at', p_item ->> 'started_at',
    'duration_sec', p_item ->> 'duration_sec',
    'camera_night_key', p_item ->> 'camera_night_key',
    'episode_key', p_item ->> 'episode_key',
    'gme_run_id', p_item ->> 'gme_run_id',
    'detector_identity', p_item ->> 'detector_identity',
    'media_sha256', p_item ->> 'media_sha256',
    'media_dhash', p_item ->> 'media_dhash',
    'gme_detected', p_item -> 'gme_detected',
    'human_gt_digest', p_item -> 'human_gt_digest'
  );
$$;

CREATE FUNCTION public.fn_validate_gme_negative_audit_verdict(
  p_verdict text,
  p_representative_sec numeric,
  p_bbox jsonb,
  p_duration_sec numeric
) RETURNS void LANGUAGE plpgsql IMMUTABLE SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  x numeric;
  y numeric;
  width numeric;
  height numeric;
BEGIN
  IF p_verdict NOT IN ('gecko_present','gecko_absent','uncertain','media_error') THEN
    RAISE EXCEPTION 'invalid_verdict' USING ERRCODE = '22023';
  END IF;
  IF p_verdict <> 'gecko_present' THEN
    IF p_representative_sec IS NOT NULL OR p_bbox IS NOT NULL THEN
      RAISE EXCEPTION 'non_present_requires_null_geometry' USING ERRCODE = '22023';
    END IF;
    RETURN;
  END IF;
  IF p_representative_sec IS NULL OR p_representative_sec < 0
     OR p_representative_sec > p_duration_sec THEN
    RAISE EXCEPTION 'representative_sec_out_of_range' USING ERRCODE = '22023';
  END IF;
  IF p_bbox IS NULL OR jsonb_typeof(p_bbox) <> 'object'
     OR NOT (p_bbox ?& ARRAY['x','y','width','height'])
     OR (SELECT count(*) FROM jsonb_object_keys(p_bbox)) <> 4
     OR EXISTS (
       SELECT 1 FROM jsonb_each(p_bbox) AS field
       WHERE jsonb_typeof(field.value) <> 'number'
     ) THEN
    RAISE EXCEPTION 'bbox_must_have_exact_numeric_keys' USING ERRCODE = '22023';
  END IF;
  x := (p_bbox ->> 'x')::numeric;
  y := (p_bbox ->> 'y')::numeric;
  width := (p_bbox ->> 'width')::numeric;
  height := (p_bbox ->> 'height')::numeric;
  IF x < 0 OR x > 1 OR y < 0 OR y > 1
     OR width <= 0 OR width > 1 OR height <= 0 OR height > 1
     OR x + width > 1 OR y + height > 1 THEN
    RAISE EXCEPTION 'bbox_out_of_range' USING ERRCODE = '22023';
  END IF;
END;
$$;

REVOKE ALL ON FUNCTION public.fn_gme_negative_audit_canonical_json(jsonb)
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.fn_gme_negative_audit_manifest_candidate(jsonb)
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.fn_validate_gme_negative_audit_verdict(text,numeric,jsonb,numeric)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_gme_negative_audit_canonical_json(jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION public.fn_gme_negative_audit_manifest_candidate(jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION public.fn_validate_gme_negative_audit_verdict(text,numeric,jsonb,numeric) TO service_role;

CREATE FUNCTION public.fn_create_gme_negative_audit_batch(
  p_owner_id uuid,
  p_manifest jsonb
) RETURNS TABLE (batch_id uuid, status text)
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  v_batch_id uuid := gen_random_uuid();
  v_batch_kind text;
  v_expected_negative integer;
  v_expected_control integer;
  v_expected_total integer;
  v_item jsonb;
  v_ordinal integer := 0;
  v_clip_id uuid;
  v_gme_run_id uuid;
  v_duration numeric;
  v_started_at timestamptz;
  v_cutoff timestamptz;
  v_top_count integer;
  v_item_count integer;
  v_distinct_clip integer;
  v_distinct_media integer;
  v_negative_count integer;
  v_control_count integer;
  v_manifest_sha text;
  v_actual_manifest_sha text;
  v_gt_digest text;
  v_candidate jsonb;
  v_expected_provenance text;
  v_selection_items jsonb;
  v_actual_selection_sha text;
BEGIN
  IF p_owner_id IS NULL OR NOT EXISTS (SELECT 1 FROM auth.users WHERE id = p_owner_id) THEN
    RAISE EXCEPTION 'owner_not_found' USING ERRCODE = '22023';
  END IF;
  IF p_manifest IS NULL OR jsonb_typeof(p_manifest) <> 'object' THEN
    RAISE EXCEPTION 'manifest_must_be_object' USING ERRCODE = '22023';
  END IF;
  SELECT count(*) INTO v_top_count FROM jsonb_object_keys(p_manifest);
  IF v_top_count <> 15 OR NOT (p_manifest ?& ARRAY[
    'schema_version','status','batch_kind','test_sheet_sha256','seed','cutoff',
    'detector_identity','checkpoint_sha256','candidate_counts','source_pools',
    'selection_sha256','protected_manifest_sha256','manifest_sha256_rule','items','manifest_sha256'
  ]) THEN
    RAISE EXCEPTION 'manifest_has_invalid_keys' USING ERRCODE = '22023';
  END IF;
  IF p_manifest ->> 'schema_version' IS DISTINCT FROM 'gme-negative-audit-v1'
     OR p_manifest ->> 'status' IS DISTINCT FROM 'prepared'
     OR p_manifest ->> 'manifest_sha256_rule' IS DISTINCT FROM 'sha256(utf8-canonical-json-v1-excluding-manifest_sha256)'
     OR jsonb_typeof(p_manifest -> 'schema_version') <> 'string'
     OR jsonb_typeof(p_manifest -> 'status') <> 'string'
     OR jsonb_typeof(p_manifest -> 'batch_kind') <> 'string'
     OR jsonb_typeof(p_manifest -> 'manifest_sha256_rule') <> 'string'
     OR jsonb_typeof(p_manifest -> 'candidate_counts') <> 'object'
     OR jsonb_typeof(p_manifest -> 'source_pools') <> 'object'
     OR jsonb_typeof(p_manifest -> 'protected_manifest_sha256') <> 'array'
     OR jsonb_typeof(p_manifest -> 'items') <> 'array' THEN
    RAISE EXCEPTION 'manifest_contract_mismatch' USING ERRCODE = '22023';
  END IF;
  IF (SELECT count(*) FROM jsonb_object_keys(p_manifest -> 'candidate_counts')) <> 2
     OR NOT ((p_manifest -> 'candidate_counts') ?& ARRAY['random_negative','positive_control'])
     OR (SELECT count(*) FROM jsonb_object_keys(p_manifest -> 'source_pools')) <> 2
     OR NOT ((p_manifest -> 'source_pools') ?& ARRAY['random_negative','positive_control']) THEN
    RAISE EXCEPTION 'manifest_pool_keys_mismatch' USING ERRCODE = '22023';
  END IF;
  IF EXISTS (
    SELECT 1 FROM jsonb_each(p_manifest -> 'source_pools') AS pool
    WHERE jsonb_typeof(pool.value) <> 'object'
      OR (SELECT count(*) FROM jsonb_object_keys(pool.value)) <> 2
      OR NOT (pool.value ?& ARRAY['count','sha256'])
  ) THEN
    RAISE EXCEPTION 'manifest_source_pool_shape_mismatch' USING ERRCODE = '22023';
  END IF;

  v_batch_kind := p_manifest ->> 'batch_kind';
  IF v_batch_kind = 'calibration' THEN
    v_expected_negative := 120; v_expected_control := 30; v_expected_total := 150;
  ELSIF v_batch_kind = 'preview_canary' THEN
    v_expected_negative := 4; v_expected_control := 2; v_expected_total := 6;
  ELSE
    RAISE EXCEPTION 'invalid_batch_kind' USING ERRCODE = '22023';
  END IF;

  IF coalesce(p_manifest ->> 'seed','') = ''
     OR p_manifest ->> 'test_sheet_sha256' !~ '^[0-9a-f]{64}$'
     OR p_manifest ->> 'selection_sha256' !~ '^[0-9a-f]{64}$'
     OR p_manifest ->> 'manifest_sha256' !~ '^[0-9a-f]{64}$'
     OR p_manifest ->> 'detector_identity' IS DISTINCT FROM 'd4654168af21d26697ab1bd9a5dc4a05bd92baf5c9328800915cc347803d05b6'
     OR p_manifest ->> 'checkpoint_sha256' IS DISTINCT FROM '2b128f105e898bc472ed66861583ab80007dae6e94b291db497d7a2f8081f84a'
     OR jsonb_typeof(p_manifest -> 'test_sheet_sha256') <> 'string'
     OR jsonb_typeof(p_manifest -> 'seed') <> 'string'
     OR jsonb_typeof(p_manifest -> 'cutoff') <> 'string'
     OR jsonb_typeof(p_manifest -> 'detector_identity') <> 'string'
     OR jsonb_typeof(p_manifest -> 'checkpoint_sha256') <> 'string'
     OR jsonb_typeof(p_manifest -> 'selection_sha256') <> 'string'
     OR jsonb_typeof(p_manifest -> 'manifest_sha256') <> 'string'
     OR p_manifest ->> 'cutoff' !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}([.][0-9]{1,6})?Z$' THEN
    RAISE EXCEPTION 'invalid_pinned_manifest_identity' USING ERRCODE = '22023';
  END IF;
  BEGIN
    v_cutoff := (p_manifest ->> 'cutoff')::timestamptz;
  EXCEPTION WHEN OTHERS THEN
    RAISE EXCEPTION 'invalid_cutoff' USING ERRCODE = '22023';
  END;

  IF jsonb_typeof(p_manifest -> 'candidate_counts' -> 'random_negative') <> 'number'
     OR jsonb_typeof(p_manifest -> 'candidate_counts' -> 'positive_control') <> 'number'
     OR jsonb_typeof(p_manifest -> 'source_pools' -> 'random_negative' -> 'count') <> 'number'
     OR jsonb_typeof(p_manifest -> 'source_pools' -> 'positive_control' -> 'count') <> 'number'
     OR jsonb_typeof(p_manifest -> 'source_pools' -> 'random_negative' -> 'sha256') <> 'string'
     OR jsonb_typeof(p_manifest -> 'source_pools' -> 'positive_control' -> 'sha256') <> 'string'
     OR (p_manifest -> 'candidate_counts' ->> 'random_negative') !~ '^[0-9]+$'
     OR (p_manifest -> 'candidate_counts' ->> 'positive_control') !~ '^[0-9]+$'
     OR (p_manifest -> 'source_pools' -> 'random_negative' ->> 'count') !~ '^[0-9]+$'
     OR (p_manifest -> 'source_pools' -> 'positive_control' ->> 'count') !~ '^[0-9]+$'
     OR (p_manifest -> 'source_pools' -> 'random_negative' ->> 'sha256') !~ '^[0-9a-f]{64}$'
     OR (p_manifest -> 'source_pools' -> 'positive_control' ->> 'sha256') !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'invalid_source_pool_identity' USING ERRCODE = '22023';
  END IF;
  IF (p_manifest -> 'candidate_counts' ->> 'random_negative')::integer < v_expected_negative
     OR (p_manifest -> 'candidate_counts' ->> 'positive_control')::integer < v_expected_control
     OR p_manifest -> 'candidate_counts' ->> 'random_negative'
        <> p_manifest -> 'source_pools' -> 'random_negative' ->> 'count'
     OR p_manifest -> 'candidate_counts' ->> 'positive_control'
        <> p_manifest -> 'source_pools' -> 'positive_control' ->> 'count' THEN
    RAISE EXCEPTION 'source_pool_count_mismatch' USING ERRCODE = '22023';
  END IF;
  IF EXISTS (
    SELECT 1 FROM jsonb_array_elements(p_manifest -> 'protected_manifest_sha256') AS protected(value)
    WHERE jsonb_typeof(protected.value) <> 'string'
       OR protected.value #>> '{}' !~ '^[0-9a-f]{64}$'
  ) OR (
    SELECT count(*) FROM jsonb_array_elements(p_manifest -> 'protected_manifest_sha256')
  ) <> (
    SELECT count(DISTINCT protected_value.value)
    FROM jsonb_array_elements_text(p_manifest -> 'protected_manifest_sha256')
      AS protected_value(value)
  ) THEN
    RAISE EXCEPTION 'invalid_protected_manifest_set' USING ERRCODE = '22023';
  END IF;

  v_manifest_sha := p_manifest ->> 'manifest_sha256';
  v_actual_manifest_sha := encode(sha256(convert_to(
    public.fn_gme_negative_audit_canonical_json(p_manifest - 'manifest_sha256'), 'UTF8'
  )), 'hex');
  IF v_manifest_sha <> v_actual_manifest_sha THEN
    RAISE EXCEPTION 'manifest_sha256_mismatch' USING ERRCODE = '22023';
  END IF;

  -- One-time import가 끝날 때까지 candidate lineage/consensus/clip metadata writer를 멈춘다.
  -- SHARE는 SELECT는 허용하지만 INSERT/UPDATE/DELETE의 ROW EXCLUSIVE와 충돌한다.
  LOCK TABLE public.motion_clips IN SHARE MODE;
  LOCK TABLE public.motion_clip_consensus IN SHARE MODE;
  LOCK TABLE public.gme_jobs IN SHARE MODE;
  LOCK TABLE public.gme_runs IN SHARE MODE;

  SELECT count(*), count(DISTINCT value ->> 'clip_id'), count(DISTINCT value ->> 'media_sha256'),
         count(*) FILTER (WHERE value ->> 'stratum' = 'random_negative'),
         count(*) FILTER (WHERE value ->> 'stratum' = 'positive_control')
  INTO v_item_count, v_distinct_clip, v_distinct_media, v_negative_count, v_control_count
  FROM jsonb_array_elements(p_manifest -> 'items');
  IF v_item_count <> v_expected_total OR v_distinct_clip <> v_expected_total
     OR v_distinct_media <> v_expected_total
     OR v_negative_count <> v_expected_negative OR v_control_count <> v_expected_control THEN
    RAISE EXCEPTION 'manifest_item_counts_mismatch' USING ERRCODE = '22023';
  END IF;

  FOR v_item IN SELECT value FROM jsonb_array_elements(p_manifest -> 'items') LOOP
    v_ordinal := v_ordinal + 1;
    IF jsonb_typeof(v_item) <> 'object'
       OR (SELECT count(*) FROM jsonb_object_keys(v_item)) <> 14
       OR NOT (v_item ?& ARRAY[
         'ordinal','clip_id','stratum','started_at','duration_sec','camera_night_key','episode_key',
         'gme_run_id','detector_identity','media_sha256','media_dhash','gme_detected',
         'human_gt_digest','selection_provenance'
       ]) THEN
      RAISE EXCEPTION 'manifest_item_has_invalid_keys' USING ERRCODE = '22023';
    END IF;
    IF v_item ->> 'ordinal' !~ '^[0-9]+$' OR (v_item ->> 'ordinal')::integer <> v_ordinal
       OR v_item ->> 'clip_id' !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
       OR v_item ->> 'gme_run_id' !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
       OR jsonb_typeof(v_item -> 'ordinal') <> 'number'
       OR jsonb_typeof(v_item -> 'clip_id') <> 'string'
       OR jsonb_typeof(v_item -> 'stratum') <> 'string'
       OR jsonb_typeof(v_item -> 'started_at') <> 'string'
       OR v_item ->> 'started_at' !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}([.][0-9]{1,6})?Z$'
       OR jsonb_typeof(v_item -> 'duration_sec') <> 'string'
       OR v_item ->> 'duration_sec' !~ '^(0|[1-9][0-9]*)([.][0-9]+)?$'
       OR (v_item ->> 'duration_sec')::numeric <= 0
       OR jsonb_typeof(v_item -> 'camera_night_key') <> 'string'
       OR jsonb_typeof(v_item -> 'episode_key') <> 'string'
       OR jsonb_typeof(v_item -> 'gme_run_id') <> 'string'
       OR jsonb_typeof(v_item -> 'detector_identity') <> 'string'
       OR jsonb_typeof(v_item -> 'media_sha256') <> 'string'
       OR jsonb_typeof(v_item -> 'media_dhash') <> 'string'
       OR jsonb_typeof(v_item -> 'gme_detected') <> 'boolean'
       OR jsonb_typeof(v_item -> 'selection_provenance') <> 'string'
       OR coalesce(v_item ->> 'camera_night_key','') = ''
       OR coalesce(v_item ->> 'episode_key','') = ''
       OR v_item ->> 'detector_identity' <> p_manifest ->> 'detector_identity'
       OR v_item ->> 'media_sha256' !~ '^[0-9a-f]{64}$'
       OR v_item ->> 'media_dhash' !~ '^[0-9a-f]{16}$'
       OR v_item ->> 'selection_provenance' !~ '^[0-9a-f]{64}$' THEN
      RAISE EXCEPTION 'invalid_manifest_item_identity' USING ERRCODE = '22023';
    END IF;
    BEGIN
      v_clip_id := (v_item ->> 'clip_id')::uuid;
      v_gme_run_id := (v_item ->> 'gme_run_id')::uuid;
      v_duration := (v_item ->> 'duration_sec')::numeric;
      v_started_at := (v_item ->> 'started_at')::timestamptz;
    EXCEPTION WHEN OTHERS THEN
      RAISE EXCEPTION 'invalid_manifest_item_cast' USING ERRCODE = '22023';
    END;
    IF v_started_at < v_cutoff THEN
      RAISE EXCEPTION 'item_before_training_cutoff' USING ERRCODE = '22023';
    END IF;
    v_candidate := public.fn_gme_negative_audit_manifest_candidate(v_item);
    v_expected_provenance := encode(sha256(convert_to(
      public.fn_gme_negative_audit_canonical_json(jsonb_build_object(
        'seed', p_manifest ->> 'seed',
        'ordinal', v_ordinal,
        'candidate', v_candidate
      )), 'UTF8'
    )), 'hex');
    IF v_item ->> 'selection_provenance' IS DISTINCT FROM v_expected_provenance THEN
      RAISE EXCEPTION 'selection_provenance_mismatch' USING ERRCODE = '22023';
    END IF;
    IF NOT EXISTS (
      SELECT 1 FROM public.motion_clips clip
      WHERE clip.id = v_clip_id AND clip.started_at = v_started_at
        AND clip.duration_sec::numeric = v_duration
    ) OR NOT EXISTS (
      SELECT 1 FROM public.gme_runs run
      WHERE run.id = v_gme_run_id AND run.clip_id = v_clip_id
        AND run.detector_identity = p_manifest ->> 'detector_identity' AND run.status = 'ok'
    ) THEN
      RAISE EXCEPTION 'frozen_clip_or_run_mismatch' USING ERRCODE = '22023';
    END IF;
    IF v_item ->> 'stratum' = 'random_negative' THEN
      IF jsonb_typeof(v_item -> 'gme_detected') <> 'boolean'
         OR (v_item ->> 'gme_detected')::boolean IS NOT FALSE
         OR v_item -> 'human_gt_digest' <> 'null'::jsonb
         OR NOT EXISTS (
           SELECT 1
           FROM public.gme_jobs job
           JOIN LATERAL public.fn_current_gme_activity(v_clip_id) AS gme ON true
           WHERE job.clip_id = v_clip_id AND job.status = 'succeeded'
             AND job.result_run_id = v_gme_run_id AND gme.run_id = v_gme_run_id
             AND gme.detected IS FALSE
         ) THEN
        RAISE EXCEPTION 'random_negative_lineage_mismatch' USING ERRCODE = '22023';
      END IF;
    ELSIF v_item ->> 'stratum' = 'positive_control' THEN
      v_gt_digest := v_item ->> 'human_gt_digest';
      IF v_gt_digest !~ '^[0-9a-f]{64}$' OR NOT EXISTS (
        SELECT 1 FROM public.motion_clip_consensus consensus
        WHERE consensus.clip_id = v_clip_id
          AND consensus.status IN ('agreed','owner_resolved')
          AND consensus.final_decision = 'label'
          AND jsonb_typeof(consensus.final_gt) = 'object'
          AND consensus.final_gt ->> 'visibility' IN ('visible','partial')
          AND encode(sha256(convert_to(
            public.fn_gme_negative_audit_canonical_json(consensus.final_gt), 'UTF8'
          )), 'hex') = v_gt_digest
      ) THEN
        RAISE EXCEPTION 'positive_control_consensus_mismatch' USING ERRCODE = '22023';
      END IF;
    ELSE
      RAISE EXCEPTION 'invalid_item_stratum' USING ERRCODE = '22023';
    END IF;
  END LOOP;

  IF EXISTS (
    SELECT 1
    FROM jsonb_array_elements(p_manifest -> 'items') AS manifest_item(value)
    WHERE manifest_item.value ->> 'stratum' = 'random_negative'
    GROUP BY manifest_item.value ->> 'episode_key'
    HAVING count(*) > 2
  ) THEN
    RAISE EXCEPTION 'random_negative_episode_cap_exceeded' USING ERRCODE = '22023';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM (
      SELECT
        (manifest_item.value ->> 'ordinal')::integer AS actual_ordinal,
        row_number() OVER (
          ORDER BY encode(sha256(convert_to(
            (p_manifest ->> 'seed') || ':blind-order:'
            || (manifest_item.value ->> 'stratum') || ':'
            || (manifest_item.value ->> 'clip_id'), 'UTF8'
          )), 'hex')
        )::integer AS expected_ordinal
      FROM jsonb_array_elements(p_manifest -> 'items') AS manifest_item(value)
    ) AS frozen_order
    WHERE frozen_order.actual_ordinal <> frozen_order.expected_ordinal
  ) THEN
    RAISE EXCEPTION 'blind_order_mismatch' USING ERRCODE = '22023';
  END IF;

  SELECT jsonb_agg(
    jsonb_build_object(
      'ordinal', (manifest_item.value ->> 'ordinal')::integer,
      'candidate', public.fn_gme_negative_audit_manifest_candidate(manifest_item.value),
      'selection_provenance', manifest_item.value ->> 'selection_provenance'
    ) ORDER BY (manifest_item.value ->> 'ordinal')::integer
  ) INTO v_selection_items
  FROM jsonb_array_elements(p_manifest -> 'items') AS manifest_item(value);
  v_actual_selection_sha := encode(sha256(convert_to(
    public.fn_gme_negative_audit_canonical_json(jsonb_build_object(
      'batch_kind', v_batch_kind,
      'seed', p_manifest ->> 'seed',
      'negative_pool_sha256', p_manifest -> 'source_pools' -> 'random_negative' ->> 'sha256',
      'control_pool_sha256', p_manifest -> 'source_pools' -> 'positive_control' ->> 'sha256',
      'items', v_selection_items
    )), 'UTF8'
  )), 'hex');
  IF p_manifest ->> 'selection_sha256' IS DISTINCT FROM v_actual_selection_sha THEN
    RAISE EXCEPTION 'selection_sha256_mismatch' USING ERRCODE = '22023';
  END IF;

  INSERT INTO public.gme_negative_audit_batches (
    id, owner_id, batch_kind, test_sheet_sha256, manifest_sha256, seed, cutoff,
    detector_identity, checkpoint_sha256, negative_pool_sha256, control_pool_sha256,
    selection_sha256, protected_manifest_sha256,
    expected_negative_count, expected_control_count, expected_total_count,
    candidate_negative_count, candidate_control_count
  ) VALUES (
    v_batch_id, p_owner_id, v_batch_kind, p_manifest ->> 'test_sheet_sha256', v_manifest_sha,
    p_manifest ->> 'seed', (p_manifest ->> 'cutoff')::timestamptz,
    p_manifest ->> 'detector_identity', p_manifest ->> 'checkpoint_sha256',
    p_manifest -> 'source_pools' -> 'random_negative' ->> 'sha256',
    p_manifest -> 'source_pools' -> 'positive_control' ->> 'sha256',
    p_manifest ->> 'selection_sha256', p_manifest -> 'protected_manifest_sha256',
    v_expected_negative, v_expected_control, v_expected_total,
    (p_manifest -> 'candidate_counts' ->> 'random_negative')::integer,
    (p_manifest -> 'candidate_counts' ->> 'positive_control')::integer
  );

  INSERT INTO public.gme_negative_audit_items (
    batch_id, ordinal, clip_id, stratum, started_at, duration_sec, camera_night_key,
    episode_key, gme_run_id, detector_identity, media_sha256, media_dhash, gme_detected,
    human_gt_digest, selection_provenance, assigned_reviewer_id
  )
  SELECT
    v_batch_id, (manifest_item.value ->> 'ordinal')::integer,
    (manifest_item.value ->> 'clip_id')::uuid,
    manifest_item.value ->> 'stratum',
    (manifest_item.value ->> 'started_at')::timestamptz,
    (manifest_item.value ->> 'duration_sec')::numeric,
    manifest_item.value ->> 'camera_night_key', manifest_item.value ->> 'episode_key',
    (manifest_item.value ->> 'gme_run_id')::uuid,
    manifest_item.value ->> 'detector_identity', manifest_item.value ->> 'media_sha256',
    manifest_item.value ->> 'media_dhash',
    (manifest_item.value ->> 'gme_detected')::boolean,
    nullif(manifest_item.value ->> 'human_gt_digest',''),
    manifest_item.value ->> 'selection_provenance', p_owner_id
  FROM jsonb_array_elements(p_manifest -> 'items') AS manifest_item(value);

  INSERT INTO public.gme_negative_audit_batch_events
    (batch_id, event_type, actor_id, digest)
  VALUES (
    v_batch_id, 'prepared', p_owner_id,
    encode(sha256(convert_to(v_batch_id::text || '|prepared|' || v_manifest_sha, 'UTF8')), 'hex')
  );
  RETURN QUERY SELECT v_batch_id, 'prepared'::text;
END;
$$;

CREATE FUNCTION public.fn_list_gme_negative_audit_queue(p_reviewer_id uuid)
RETURNS TABLE (
  item_id uuid,
  ordinal integer,
  captured_at timestamptz,
  duration_sec numeric,
  media_ready boolean,
  submitted boolean,
  completed integer,
  total integer
)
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = '' AS $$
  WITH current_batch AS (
    SELECT batch.id
    FROM public.gme_negative_audit_batches batch
    WHERE EXISTS (
      SELECT 1 FROM public.gme_negative_audit_items assigned
      WHERE assigned.batch_id = batch.id AND assigned.assigned_reviewer_id = p_reviewer_id
    )
      AND (
        SELECT event.event_type
        FROM public.gme_negative_audit_batch_events event
        WHERE event.batch_id = batch.id
        ORDER BY event.created_at DESC, event.id DESC LIMIT 1
      ) = 'opened'
    ORDER BY batch.created_at DESC, batch.id DESC LIMIT 1
  ), counts AS (
    SELECT count(*)::integer AS total,
           count(submission.id)::integer AS completed
    FROM public.gme_negative_audit_items item
    JOIN current_batch batch ON batch.id = item.batch_id
    LEFT JOIN public.gme_negative_audit_submissions submission ON submission.item_id = item.id
    WHERE item.assigned_reviewer_id = p_reviewer_id
  )
  SELECT item.id, item.ordinal, item.started_at, item.duration_sec,
         (clip.r2_key IS NOT NULL AND btrim(clip.r2_key) <> ''),
         (submission.id IS NOT NULL), counts.completed, counts.total
  FROM public.gme_negative_audit_items item
  JOIN current_batch batch ON batch.id = item.batch_id
  JOIN public.motion_clips clip ON clip.id = item.clip_id
  CROSS JOIN counts
  LEFT JOIN public.gme_negative_audit_submissions submission ON submission.item_id = item.id
  WHERE item.assigned_reviewer_id = p_reviewer_id
  ORDER BY item.ordinal;
$$;

CREATE FUNCTION public.fn_get_gme_negative_audit_item(p_item_id uuid, p_reviewer_id uuid)
RETURNS TABLE (
  item_id uuid,
  ordinal integer,
  captured_at timestamptz,
  duration_sec numeric,
  media_ready boolean,
  initial_verdict text,
  initial_representative_sec numeric,
  initial_bbox jsonb,
  effective_verdict text,
  effective_representative_sec numeric,
  effective_bbox jsonb
)
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = '' AS $$
  SELECT item.id, item.ordinal, item.started_at, item.duration_sec,
         (clip.r2_key IS NOT NULL AND btrim(clip.r2_key) <> ''),
         submission.verdict, submission.representative_sec, submission.bbox,
         coalesce(correction.verdict, submission.verdict),
         CASE WHEN correction.id IS NULL THEN submission.representative_sec ELSE correction.representative_sec END,
         CASE WHEN correction.id IS NULL THEN submission.bbox ELSE correction.bbox END
  FROM public.gme_negative_audit_items item
  JOIN public.motion_clips clip ON clip.id = item.clip_id
  LEFT JOIN public.gme_negative_audit_submissions submission ON submission.item_id = item.id
  LEFT JOIN LATERAL (
    SELECT latest.id, latest.verdict, latest.representative_sec, latest.bbox
    FROM public.gme_negative_audit_corrections latest
    WHERE latest.item_id = item.id
    ORDER BY latest.created_at DESC, latest.id DESC LIMIT 1
  ) correction ON true
  WHERE item.id = p_item_id AND item.assigned_reviewer_id = p_reviewer_id;
$$;

CREATE FUNCTION public.fn_submit_gme_negative_audit(
  p_item_id uuid,
  p_reviewer_id uuid,
  p_verdict text,
  p_representative_sec numeric,
  p_bbox jsonb
) RETURNS TABLE (submission_id uuid, status text)
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  v_item public.gme_negative_audit_items%ROWTYPE;
  v_submission_id uuid;
  v_digest text;
  v_state text;
BEGIN
  SELECT * INTO v_item FROM public.gme_negative_audit_items item
  WHERE item.id = p_item_id AND item.assigned_reviewer_id = p_reviewer_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'not_assigned' USING ERRCODE = 'PT403';
  END IF;
  PERFORM 1 FROM public.gme_negative_audit_batches batch
  WHERE batch.id = v_item.batch_id FOR SHARE;
  IF EXISTS (SELECT 1 FROM public.gme_negative_audit_submissions WHERE item_id = p_item_id) THEN
    RAISE EXCEPTION 'already_submitted' USING ERRCODE = 'PT410';
  END IF;
  SELECT event.event_type INTO v_state
  FROM public.gme_negative_audit_batch_events event
  WHERE event.batch_id = v_item.batch_id
  ORDER BY event.created_at DESC, event.id DESC LIMIT 1;
  IF v_state IS DISTINCT FROM 'opened' THEN
    RAISE EXCEPTION 'batch_closed' USING ERRCODE = 'PT427';
  END IF;
  -- strict helper enforces 0 <= representative_sec <= v_item.duration_sec and exact bbox.
  PERFORM public.fn_validate_gme_negative_audit_verdict(
    p_verdict, p_representative_sec, p_bbox, v_item.duration_sec
  );
  v_digest := encode(sha256(convert_to(
    p_item_id::text || '|' || p_reviewer_id::text || '|' || p_verdict || '|'
    || coalesce(p_representative_sec::text,'null') || '|'
    || public.fn_gme_negative_audit_canonical_json(coalesce(p_bbox, 'null'::jsonb)), 'UTF8'
  )), 'hex');
  INSERT INTO public.gme_negative_audit_submissions
    (item_id, reviewer_id, verdict, representative_sec, bbox, digest)
  VALUES (p_item_id, p_reviewer_id, p_verdict, p_representative_sec, p_bbox, v_digest)
  ON CONFLICT (item_id) DO NOTHING RETURNING id INTO v_submission_id;
  IF v_submission_id IS NULL THEN
    RAISE EXCEPTION 'already_submitted' USING ERRCODE = 'PT410';
  END IF;
  RETURN QUERY SELECT v_submission_id, 'submitted'::text;
END;
$$;

CREATE FUNCTION public.fn_append_gme_negative_audit_correction(
  p_item_id uuid,
  p_reviewer_id uuid,
  p_verdict text,
  p_representative_sec numeric,
  p_bbox jsonb,
  p_reason text,
  p_expected_submission_digest text
) RETURNS TABLE (correction_id uuid, status text)
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  v_item public.gme_negative_audit_items%ROWTYPE;
  v_submission public.gme_negative_audit_submissions%ROWTYPE;
  v_effective_digest text;
  v_state text;
  v_id uuid;
  v_digest text;
BEGIN
  SELECT * INTO v_item FROM public.gme_negative_audit_items item
  WHERE item.id = p_item_id AND item.assigned_reviewer_id = p_reviewer_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'not_assigned' USING ERRCODE = 'PT403'; END IF;
  SELECT * INTO v_submission FROM public.gme_negative_audit_submissions submission
  WHERE submission.item_id = p_item_id AND submission.reviewer_id = p_reviewer_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'submission_not_found' USING ERRCODE = 'PT404'; END IF;
  PERFORM 1 FROM public.gme_negative_audit_batches batch
  WHERE batch.id = v_item.batch_id FOR SHARE;
  SELECT event.event_type INTO v_state FROM public.gme_negative_audit_batch_events event
  WHERE event.batch_id = v_item.batch_id ORDER BY event.created_at DESC, event.id DESC LIMIT 1;
  IF v_state IS DISTINCT FROM 'opened' THEN
    RAISE EXCEPTION 'batch_closed' USING ERRCODE = 'PT427';
  END IF;
  SELECT coalesce((
    SELECT correction.digest FROM public.gme_negative_audit_corrections correction
    WHERE correction.item_id = p_item_id
    ORDER BY correction.created_at DESC, correction.id DESC LIMIT 1
  ), v_submission.digest) INTO v_effective_digest;
  IF p_expected_submission_digest IS DISTINCT FROM v_effective_digest THEN
    RAISE EXCEPTION 'stale_submission_digest' USING ERRCODE = 'PT409';
  END IF;
  IF char_length(btrim(coalesce(p_reason,''))) < 1 THEN
    RAISE EXCEPTION 'correction_reason_required' USING ERRCODE = '22023';
  END IF;
  PERFORM public.fn_validate_gme_negative_audit_verdict(
    p_verdict, p_representative_sec, p_bbox, v_item.duration_sec
  );
  v_digest := encode(sha256(convert_to(
    v_submission.id::text || '|' || v_effective_digest || '|' || p_verdict || '|'
    || coalesce(p_representative_sec::text,'null') || '|'
    || public.fn_gme_negative_audit_canonical_json(coalesce(p_bbox, 'null'::jsonb))
    || '|' || btrim(p_reason), 'UTF8'
  )), 'hex');
  INSERT INTO public.gme_negative_audit_corrections (
    item_id, original_submission_id, reviewer_id, verdict, representative_sec, bbox,
    reason, expected_submission_digest, digest
  ) VALUES (
    p_item_id, v_submission.id, p_reviewer_id, p_verdict, p_representative_sec, p_bbox,
    btrim(p_reason), v_effective_digest, v_digest
  ) ON CONFLICT (item_id, expected_submission_digest) DO NOTHING RETURNING id INTO v_id;
  IF v_id IS NULL THEN
    RAISE EXCEPTION 'stale_submission_digest' USING ERRCODE = 'PT409';
  END IF;
  RETURN QUERY SELECT v_id, 'corrected'::text;
END;
$$;

CREATE FUNCTION public.fn_append_gme_negative_audit_adjudication(
  p_item_id uuid,
  p_owner_id uuid,
  p_final_verdict text,
  p_representative_sec numeric,
  p_bbox jsonb,
  p_reason text,
  p_expected_submission_digest text
) RETURNS TABLE (adjudication_id uuid, status text)
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  v_item public.gme_negative_audit_items%ROWTYPE;
  v_submission public.gme_negative_audit_submissions%ROWTYPE;
  v_effective_verdict text;
  v_effective_digest text;
  v_id uuid;
  v_digest text;
BEGIN
  SELECT item.* INTO v_item
  FROM public.gme_negative_audit_items item
  JOIN public.gme_negative_audit_batches batch ON batch.id = item.batch_id
  WHERE item.id = p_item_id AND batch.owner_id = p_owner_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'owner_forbidden' USING ERRCODE = 'PT403'; END IF;
  SELECT * INTO v_submission FROM public.gme_negative_audit_submissions submission
  WHERE submission.item_id = p_item_id AND submission.reviewer_id <> p_owner_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'non_owner_submission_required' USING ERRCODE = 'PT409'; END IF;
  SELECT coalesce(correction.verdict, v_submission.verdict),
         coalesce(correction.digest, v_submission.digest)
  INTO v_effective_verdict, v_effective_digest
  FROM (SELECT 1) seed
  LEFT JOIN LATERAL (
    SELECT latest.verdict, latest.digest FROM public.gme_negative_audit_corrections latest
    WHERE latest.item_id = p_item_id
    ORDER BY latest.created_at DESC, latest.id DESC LIMIT 1
  ) correction ON true;
  IF v_effective_verdict = 'gecko_absent' THEN
    RAISE EXCEPTION 'absent_does_not_require_adjudication' USING ERRCODE = 'PT409';
  END IF;
  IF p_expected_submission_digest IS DISTINCT FROM v_effective_digest THEN
    RAISE EXCEPTION 'stale_submission_digest' USING ERRCODE = 'PT409';
  END IF;
  IF char_length(btrim(coalesce(p_reason,''))) < 1 THEN
    RAISE EXCEPTION 'adjudication_reason_required' USING ERRCODE = '22023';
  END IF;
  PERFORM public.fn_validate_gme_negative_audit_verdict(
    p_final_verdict, p_representative_sec, p_bbox, v_item.duration_sec
  );
  v_digest := encode(sha256(convert_to(
    v_submission.id::text || '|' || v_effective_digest || '|' || p_final_verdict || '|'
    || coalesce(p_representative_sec::text,'null') || '|'
    || public.fn_gme_negative_audit_canonical_json(coalesce(p_bbox, 'null'::jsonb))
    || '|' || btrim(p_reason), 'UTF8'
  )), 'hex');
  INSERT INTO public.gme_negative_audit_adjudications (
    item_id, original_submission_id, owner_id, final_verdict, representative_sec, bbox,
    reason, effective_submission_digest, digest
  ) VALUES (
    p_item_id, v_submission.id, p_owner_id, p_final_verdict, p_representative_sec, p_bbox,
    btrim(p_reason), v_effective_digest, v_digest
  ) ON CONFLICT (item_id) DO NOTHING RETURNING id INTO v_id;
  IF v_id IS NULL THEN RAISE EXCEPTION 'already_adjudicated' USING ERRCODE = 'PT410'; END IF;
  RETURN QUERY SELECT v_id, 'adjudicated'::text;
END;
$$;

CREATE FUNCTION public.fn_append_gme_negative_audit_dataset_decision(
  p_item_id uuid,
  p_owner_id uuid,
  p_decision text,
  p_reason text,
  p_expected_effective_digest text
) RETURNS TABLE (decision_id uuid, status text)
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  v_item public.gme_negative_audit_items%ROWTYPE;
  v_submission public.gme_negative_audit_submissions%ROWTYPE;
  v_adjudication public.gme_negative_audit_adjudications%ROWTYPE;
  v_effective_digest text;
  v_effective_verdict text;
  v_id uuid;
  v_digest text;
BEGIN
  SELECT item.* INTO v_item
  FROM public.gme_negative_audit_items item
  JOIN public.gme_negative_audit_batches batch ON batch.id = item.batch_id
  WHERE item.id = p_item_id AND batch.owner_id = p_owner_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'owner_forbidden' USING ERRCODE = 'PT403'; END IF;
  IF p_decision NOT IN (
    'include_candidate','exclude_duplicate','exclude_holdout','exclude_quality','defer'
  ) THEN RAISE EXCEPTION 'invalid_dataset_decision' USING ERRCODE = '22023'; END IF;
  IF char_length(btrim(coalesce(p_reason,''))) < 1 THEN
    RAISE EXCEPTION 'dataset_reason_required' USING ERRCODE = '22023';
  END IF;
  SELECT * INTO v_submission FROM public.gme_negative_audit_submissions submission
  WHERE submission.item_id = p_item_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'submission_not_found' USING ERRCODE = 'PT409'; END IF;
  SELECT * INTO v_adjudication FROM public.gme_negative_audit_adjudications adjudication
  WHERE adjudication.item_id = p_item_id;
  IF FOUND THEN
    v_effective_digest := v_adjudication.digest;
    v_effective_verdict := v_adjudication.final_verdict;
  ELSE
    SELECT coalesce(correction.digest, v_submission.digest),
           coalesce(correction.verdict, v_submission.verdict)
    INTO v_effective_digest, v_effective_verdict
    FROM (SELECT 1) seed
    LEFT JOIN LATERAL (
      SELECT latest.digest, latest.verdict FROM public.gme_negative_audit_corrections latest
      WHERE latest.item_id = p_item_id
      ORDER BY latest.created_at DESC, latest.id DESC LIMIT 1
    ) correction ON true;
  END IF;
  IF p_expected_effective_digest IS DISTINCT FROM v_effective_digest THEN
    RAISE EXCEPTION 'stale_effective_digest' USING ERRCODE = 'PT409';
  END IF;
  IF p_decision = 'include_candidate' AND v_item.stratum = 'positive_control' THEN
    RAISE EXCEPTION 'control_cannot_include_candidate' USING ERRCODE = 'PT409';
  END IF;
  IF p_decision = 'include_candidate' AND v_effective_verdict <> 'gecko_present' THEN
    RAISE EXCEPTION 'candidate_requires_present_verdict' USING ERRCODE = 'PT409';
  END IF;
  IF p_decision = 'include_candidate'
     AND v_submission.reviewer_id <> p_owner_id AND v_adjudication.id IS NULL THEN
    RAISE EXCEPTION 'adjudication_required' USING ERRCODE = 'PT409';
  END IF;
  v_digest := encode(sha256(convert_to(
    p_item_id::text || '|' || p_decision || '|' || v_effective_digest || '|'
    || btrim(p_reason), 'UTF8'
  )), 'hex');
  INSERT INTO public.gme_negative_audit_dataset_decisions (
    item_id, owner_id, decision, reason, effective_submission_digest, adjudication_id, digest
  ) VALUES (
    p_item_id, p_owner_id, p_decision, btrim(p_reason), v_effective_digest,
    v_adjudication.id, v_digest
  ) RETURNING id INTO v_id;
  RETURN QUERY SELECT v_id, 'decided'::text;
END;
$$;

REVOKE ALL ON FUNCTION public.fn_create_gme_negative_audit_batch(uuid,jsonb)
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.fn_list_gme_negative_audit_queue(uuid)
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.fn_get_gme_negative_audit_item(uuid,uuid)
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.fn_submit_gme_negative_audit(uuid,uuid,text,numeric,jsonb)
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.fn_append_gme_negative_audit_correction(uuid,uuid,text,numeric,jsonb,text,text)
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.fn_append_gme_negative_audit_adjudication(uuid,uuid,text,numeric,jsonb,text,text)
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.fn_append_gme_negative_audit_dataset_decision(uuid,uuid,text,text,text)
  FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.fn_create_gme_negative_audit_batch(uuid,jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION public.fn_list_gme_negative_audit_queue(uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.fn_get_gme_negative_audit_item(uuid,uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.fn_submit_gme_negative_audit(uuid,uuid,text,numeric,jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION public.fn_append_gme_negative_audit_correction(uuid,uuid,text,numeric,jsonb,text,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.fn_append_gme_negative_audit_adjudication(uuid,uuid,text,numeric,jsonb,text,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.fn_append_gme_negative_audit_dataset_decision(uuid,uuid,text,text,text) TO service_role;

COMMIT;
