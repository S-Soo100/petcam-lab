-- motion_clips 사람 행동 GT의 append-only canonical 원장.
-- 기존 session/submission/consensus writer와 행은 변경하지 않고 별도 projection만 추가한다.

BEGIN;

CREATE TABLE public.motion_clip_gt_revisions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  clip_id uuid NOT NULL REFERENCES public.motion_clips(id) ON DELETE RESTRICT,
  revision_no integer NOT NULL CHECK (revision_no > 0),
  final_decision text NOT NULL
    CHECK (final_decision IN ('label', 'hold', 'exclude')),
  gt jsonb,
  source_type text NOT NULL CHECK (source_type IN (
    'blind_consensus', 'owner_adjudication', 'owner_override',
    'owner_direct_legacy', 'owner_single_adopt'
  )),
  source_table text NOT NULL,
  source_id uuid NOT NULL,
  source_version text NOT NULL,
  source_event_key text NOT NULL UNIQUE,
  parent_revision_id uuid REFERENCES public.motion_clip_gt_revisions(id),
  reason text,
  actor_id uuid,
  projection_run_id uuid,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (clip_id, revision_no),
  CHECK (
    (final_decision = 'label' AND gt IS NOT NULL AND jsonb_typeof(gt) = 'object')
    OR (final_decision IN ('hold', 'exclude') AND gt IS NULL)
  ),
  CHECK (
    source_type <> 'owner_override'
    OR (
      parent_revision_id IS NOT NULL
      AND actor_id IS NOT NULL
      AND char_length(btrim(reason)) BETWEEN 10 AND 500
    )
  )
);

CREATE TABLE public.motion_clip_gt_heads (
  clip_id uuid PRIMARY KEY REFERENCES public.motion_clips(id) ON DELETE RESTRICT,
  revision_id uuid NOT NULL UNIQUE REFERENCES public.motion_clip_gt_revisions(id),
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE public.motion_clip_gt_reconciliation (
  clip_id uuid PRIMARY KEY REFERENCES public.motion_clips(id) ON DELETE RESTRICT,
  consensus_id uuid NOT NULL REFERENCES public.motion_clip_consensus(id) ON DELETE RESTRICT,
  session_id uuid NOT NULL REFERENCES public.motion_clip_labeling_sessions(id) ON DELETE RESTRICT,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'resolved')),
  resolved_revision_id uuid REFERENCES public.motion_clip_gt_revisions(id),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  resolved_at timestamptz,
  CHECK (
    (status = 'pending' AND resolved_revision_id IS NULL AND resolved_at IS NULL)
    OR (status = 'resolved' AND resolved_revision_id IS NOT NULL AND resolved_at IS NOT NULL)
  )
);

CREATE TABLE public.motion_clip_gt_projection_runs (
  id uuid PRIMARY KEY,
  status text NOT NULL CHECK (status IN ('succeeded', 'failed')),
  scanned integer NOT NULL DEFAULT 0 CHECK (scanned >= 0),
  inserted integer NOT NULL DEFAULT 0 CHECK (inserted >= 0),
  error_code text CHECK (error_code IS NULL OR char_length(error_code) BETWEEN 1 AND 80),
  started_at timestamptz NOT NULL,
  finished_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CHECK (
    (status = 'succeeded' AND error_code IS NULL)
    OR (status = 'failed' AND error_code IS NOT NULL)
  )
);

CREATE INDEX idx_motion_clip_gt_revisions_clip_created
  ON public.motion_clip_gt_revisions (clip_id, created_at DESC);
CREATE INDEX idx_motion_clip_gt_reconciliation_status_created
  ON public.motion_clip_gt_reconciliation (status, created_at, clip_id);
CREATE INDEX idx_motion_clip_gt_projection_runs_finished
  ON public.motion_clip_gt_projection_runs (finished_at DESC, id DESC);

ALTER TABLE public.motion_clip_gt_revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.motion_clip_gt_heads ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.motion_clip_gt_reconciliation ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.motion_clip_gt_projection_runs ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.motion_clip_gt_revisions FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.motion_clip_gt_heads FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.motion_clip_gt_reconciliation FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.motion_clip_gt_projection_runs FROM PUBLIC, anon, authenticated;

GRANT ALL ON TABLE public.motion_clip_gt_revisions TO service_role;
GRANT ALL ON TABLE public.motion_clip_gt_heads TO service_role;
GRANT ALL ON TABLE public.motion_clip_gt_reconciliation TO service_role;
GRANT ALL ON TABLE public.motion_clip_gt_projection_runs TO service_role;

CREATE OR REPLACE FUNCTION public.fn_reject_motion_clip_gt_history_mutation()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = ''
AS $$
BEGIN
  RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = '0A000';
END;
$$;

REVOKE ALL ON FUNCTION public.fn_reject_motion_clip_gt_history_mutation() FROM PUBLIC;

CREATE TRIGGER trg_reject_motion_clip_gt_revision_mutation
  BEFORE UPDATE OR DELETE OR TRUNCATE ON public.motion_clip_gt_revisions
  FOR EACH STATEMENT EXECUTE FUNCTION public.fn_reject_motion_clip_gt_history_mutation();

CREATE TRIGGER trg_reject_motion_clip_gt_projection_run_mutation
  BEFORE UPDATE OR DELETE OR TRUNCATE ON public.motion_clip_gt_projection_runs
  FOR EACH STATEMENT EXECUTE FUNCTION public.fn_reject_motion_clip_gt_history_mutation();

CREATE OR REPLACE FUNCTION public.fn_validate_motion_clip_gt_link()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = ''
AS $$
DECLARE
  v_clip_id uuid;
BEGIN
  SELECT r.clip_id INTO v_clip_id
  FROM public.motion_clip_gt_revisions r
  WHERE r.id = NEW.revision_id;
  IF v_clip_id IS DISTINCT FROM NEW.clip_id THEN
    RAISE EXCEPTION 'head_revision_clip_mismatch' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.fn_validate_motion_clip_gt_link() FROM PUBLIC;

CREATE CONSTRAINT TRIGGER trg_validate_motion_clip_gt_head_link
  AFTER INSERT OR UPDATE ON public.motion_clip_gt_heads
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION public.fn_validate_motion_clip_gt_link();

CREATE OR REPLACE FUNCTION public.fn_validate_motion_clip_gt_parent()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = ''
AS $$
DECLARE
  v_parent_clip_id uuid;
BEGIN
  IF NEW.parent_revision_id IS NULL THEN
    RETURN NEW;
  END IF;
  SELECT r.clip_id INTO v_parent_clip_id
  FROM public.motion_clip_gt_revisions r
  WHERE r.id = NEW.parent_revision_id;
  IF v_parent_clip_id IS DISTINCT FROM NEW.clip_id THEN
    RAISE EXCEPTION 'parent_revision_clip_mismatch' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.fn_validate_motion_clip_gt_parent() FROM PUBLIC;

CREATE CONSTRAINT TRIGGER trg_validate_motion_clip_gt_parent
  AFTER INSERT OR UPDATE ON public.motion_clip_gt_revisions
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION public.fn_validate_motion_clip_gt_parent();

-- projection batch is atomic: 후보별 예외를 삼키지 않아 RPC transaction 전체가 rollback된다.
CREATE OR REPLACE FUNCTION public.fn_project_motion_clip_canonical_gt(
  p_owner_id uuid,
  p_apply boolean,
  p_limit integer,
  p_after_source_id uuid,
  p_projection_run_id uuid
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  v_candidate record;
  v_consensus_id uuid;
  v_session_id uuid;
  v_revision_id uuid;
  v_revision_no integer;
  v_scanned integer := 0;
  v_inserted integer := 0;
  v_already_present integer := 0;
  v_conflicts integer := 0;
  v_next_after_source_id uuid := NULL;
BEGIN
  IF p_owner_id IS NULL OR p_projection_run_id IS NULL THEN
    RAISE EXCEPTION 'owner_and_projection_run_required' USING ERRCODE = '22023';
  END IF;
  IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 500 THEN
    RAISE EXCEPTION 'limit_out_of_range' USING ERRCODE = '22023';
  END IF;

  FOR v_candidate IN
    WITH candidates AS (
      SELECT
        c.id AS source_id,
        c.clip_id,
        c.final_decision,
        c.final_gt AS gt,
        CASE
          WHEN c.comparator_version = 'owner-single-adopt-v1' THEN 'owner_single_adopt'
          WHEN c.status = 'owner_resolved' THEN 'owner_adjudication'
          ELSE 'blind_consensus'
        END AS source_type,
        'motion_clip_consensus'::text AS source_table,
        COALESCE(c.comparator_version, 'unknown') AS source_version,
        'motion_clip_consensus:' || c.id::text || ':' || COALESCE(c.comparator_version, 'unknown') AS source_event_key
      FROM public.motion_clip_consensus c
      WHERE c.cohort_kind = 'live'
        AND c.status IN ('agreed', 'owner_resolved')
        AND c.final_decision IN ('label', 'hold', 'exclude')
        AND (c.final_decision <> 'label' OR c.final_gt IS NOT NULL)

      UNION ALL

      SELECT
        s.id AS source_id,
        s.clip_id,
        'label'::text AS final_decision,
        COALESCE(s.current_gt, s.initial_gt) AS gt,
        'owner_direct_legacy'::text AS source_type,
        'motion_clip_labeling_sessions'::text AS source_table,
        'motion-labeling-v3'::text AS source_version,
        'motion_clip_labeling_sessions:' || s.id::text || ':motion-labeling-v3' AS source_event_key
      FROM public.motion_clip_labeling_sessions s
      WHERE s.reviewed_by = p_owner_id
        AND s.stage = 'completed'
        AND COALESCE(s.current_gt, s.initial_gt) IS NOT NULL
    )
    SELECT c.*
    FROM candidates c
    WHERE (p_after_source_id IS NULL OR c.source_id > p_after_source_id)
      AND NOT EXISTS (
        SELECT 1 FROM public.motion_clip_gt_revisions r
        WHERE r.source_event_key = c.source_event_key
      )
      AND NOT EXISTS (
        SELECT 1 FROM public.motion_clip_gt_reconciliation q
        WHERE q.clip_id = c.clip_id
      )
    ORDER BY c.source_id
    LIMIT p_limit
  LOOP
    v_scanned := v_scanned + 1;
    v_next_after_source_id := v_candidate.source_id;

    SELECT c.id INTO v_consensus_id
    FROM public.motion_clip_consensus c
    WHERE c.clip_id = v_candidate.clip_id
      AND c.cohort_kind = 'live'
      AND c.status IN ('agreed', 'owner_resolved')
      AND c.final_decision IN ('label', 'hold', 'exclude')
      AND (c.final_decision <> 'label' OR c.final_gt IS NOT NULL)
    LIMIT 1;

    SELECT s.id INTO v_session_id
    FROM public.motion_clip_labeling_sessions s
    WHERE s.clip_id = v_candidate.clip_id
      AND s.reviewed_by = p_owner_id
      AND s.stage = 'completed'
      AND COALESCE(s.current_gt, s.initial_gt) IS NOT NULL
    ORDER BY s.updated_at DESC, s.id DESC
    LIMIT 1;

    IF v_consensus_id IS NOT NULL AND v_session_id IS NOT NULL THEN
      IF p_apply THEN
        INSERT INTO public.motion_clip_gt_reconciliation
          (clip_id, consensus_id, session_id)
        VALUES (v_candidate.clip_id, v_consensus_id, v_session_id)
        ON CONFLICT (clip_id) DO NOTHING;
        IF FOUND THEN
          v_conflicts := v_conflicts + 1;
        ELSE
          v_already_present := v_already_present + 1;
        END IF;
      ELSE
        v_conflicts := v_conflicts + 1;
      END IF;
      v_consensus_id := NULL;
      v_session_id := NULL;
      CONTINUE;
    END IF;

    IF NOT p_apply THEN
      v_inserted := v_inserted + 1;
      v_consensus_id := NULL;
      v_session_id := NULL;
      CONTINUE;
    END IF;

    PERFORM pg_advisory_xact_lock(hashtextextended(v_candidate.clip_id::text, 0));
    SELECT COALESCE(max(r.revision_no), 0) + 1
      INTO v_revision_no
    FROM public.motion_clip_gt_revisions r
    WHERE r.clip_id = v_candidate.clip_id;

    INSERT INTO public.motion_clip_gt_revisions (
      clip_id, revision_no, final_decision, gt, source_type, source_table,
      source_id, source_version, source_event_key, projection_run_id
    ) VALUES (
      v_candidate.clip_id, v_revision_no, v_candidate.final_decision,
      CASE WHEN v_candidate.final_decision = 'label' THEN v_candidate.gt ELSE NULL END,
      v_candidate.source_type, v_candidate.source_table, v_candidate.source_id,
      v_candidate.source_version, v_candidate.source_event_key, p_projection_run_id
    )
    ON CONFLICT (source_event_key) DO NOTHING
    RETURNING id INTO v_revision_id;

    IF v_revision_id IS NULL THEN
      v_already_present := v_already_present + 1;
    ELSE
      INSERT INTO public.motion_clip_gt_heads (clip_id, revision_id)
      VALUES (v_candidate.clip_id, v_revision_id)
      ON CONFLICT (clip_id) DO NOTHING;
      v_inserted := v_inserted + 1;
    END IF;

    v_consensus_id := NULL;
    v_session_id := NULL;
    v_revision_id := NULL;
  END LOOP;

  RETURN jsonb_build_object(
    'scanned', v_scanned,
    'inserted', v_inserted,
    'already_present', v_already_present,
    'conflicts', v_conflicts,
    'dry_run', NOT p_apply,
    'next_after_source_id', v_next_after_source_id
  );
END;
$$;

CREATE OR REPLACE FUNCTION public.fn_get_motion_clip_canonical_gt(
  p_clip_id uuid,
  p_actor_id uuid
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  v_reconciliation public.motion_clip_gt_reconciliation%ROWTYPE;
  v_consensus public.motion_clip_consensus%ROWTYPE;
  v_session public.motion_clip_labeling_sessions%ROWTYPE;
  v_revision public.motion_clip_gt_revisions%ROWTYPE;
BEGIN
  IF p_clip_id IS NULL OR p_actor_id IS NULL THEN
    RAISE EXCEPTION 'clip_and_actor_required' USING ERRCODE = '22023';
  END IF;

  SELECT * INTO v_reconciliation
  FROM public.motion_clip_gt_reconciliation q
  WHERE q.clip_id = p_clip_id AND q.status = 'pending';
  IF FOUND THEN
    SELECT * INTO v_consensus FROM public.motion_clip_consensus c
      WHERE c.id = v_reconciliation.consensus_id;
    SELECT * INTO v_session FROM public.motion_clip_labeling_sessions s
      WHERE s.id = v_reconciliation.session_id;
    RETURN jsonb_build_object(
      'status', 'conflict',
      'revision_id', NULL,
      'decision', NULL,
      'gt', NULL,
      'source_type', NULL,
      'updated_at', v_reconciliation.created_at,
      'candidates', jsonb_build_array(
        jsonb_build_object(
          'source', 'consensus', 'decision', v_consensus.final_decision,
          'gt', v_consensus.final_gt,
          'source_type', CASE
            WHEN v_consensus.comparator_version = 'owner-single-adopt-v1' THEN 'owner_single_adopt'
            WHEN v_consensus.status = 'owner_resolved' THEN 'owner_adjudication'
            ELSE 'blind_consensus'
          END
        ),
        jsonb_build_object(
          'source', 'direct', 'decision', 'label',
          'gt', COALESCE(v_session.current_gt, v_session.initial_gt),
          'source_type', 'owner_direct_legacy'
        )
      )
    );
  END IF;

  SELECT r.* INTO v_revision
  FROM public.motion_clip_gt_heads h
  JOIN public.motion_clip_gt_revisions r ON r.id = h.revision_id
  WHERE h.clip_id = p_clip_id;
  IF FOUND THEN
    RETURN jsonb_build_object(
      'status', 'final',
      'revision_id', v_revision.id,
      'decision', v_revision.final_decision,
      'gt', v_revision.gt,
      'source_type', v_revision.source_type,
      'source_version', v_revision.source_version,
      'updated_at', v_revision.created_at
    );
  END IF;

  SELECT * INTO v_consensus
  FROM public.motion_clip_consensus c
  WHERE c.clip_id = p_clip_id AND c.cohort_kind = 'live';
  IF FOUND AND v_consensus.status = 'awaiting' THEN
    RETURN jsonb_build_object(
      'status', 'review_in_progress', 'revision_id', NULL,
      'decision', NULL, 'gt', NULL, 'source_type', NULL,
      'updated_at', v_consensus.updated_at
    );
  END IF;
  IF FOUND AND v_consensus.status = 'conflict' THEN
    RETURN jsonb_build_object(
      'status', 'conflict', 'revision_id', NULL,
      'decision', NULL, 'gt', NULL, 'source_type', NULL,
      'updated_at', v_consensus.updated_at, 'candidates', NULL
    );
  END IF;

  RETURN jsonb_build_object(
    'status', 'none', 'revision_id', NULL,
    'decision', NULL, 'gt', NULL, 'source_type', NULL, 'updated_at', NULL
  );
END;
$$;

CREATE OR REPLACE FUNCTION public.fn_override_motion_clip_canonical_gt(
  p_clip_id uuid,
  p_actor_id uuid,
  p_expected_revision_id uuid,
  p_new_gt jsonb,
  p_reason text
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  v_head public.motion_clip_gt_heads%ROWTYPE;
  v_revision_id uuid := gen_random_uuid();
  v_revision_no integer;
BEGIN
  IF p_new_gt IS NULL OR jsonb_typeof(p_new_gt) <> 'object' THEN
    RAISE EXCEPTION 'new_gt_must_be_object' USING ERRCODE = '22023';
  END IF;
  IF p_reason IS NULL OR char_length(btrim(p_reason)) NOT BETWEEN 10 AND 500 THEN
    RAISE EXCEPTION 'reason_required' USING ERRCODE = '22023';
  END IF;
  IF p_actor_id IS NULL OR p_expected_revision_id IS NULL THEN
    RAISE EXCEPTION 'actor_and_expected_revision_required' USING ERRCODE = '22023';
  END IF;

  PERFORM pg_advisory_xact_lock(hashtextextended(p_clip_id::text, 0));
  SELECT * INTO v_head FROM public.motion_clip_gt_heads h
    WHERE h.clip_id = p_clip_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'canonical_head_not_found' USING ERRCODE = 'P0002';
  END IF;
  IF v_head.revision_id IS DISTINCT FROM p_expected_revision_id THEN
    RAISE EXCEPTION 'expected_revision_mismatch' USING ERRCODE = 'PT409';
  END IF;

  SELECT COALESCE(max(r.revision_no), 0) + 1 INTO v_revision_no
  FROM public.motion_clip_gt_revisions r WHERE r.clip_id = p_clip_id;

  INSERT INTO public.motion_clip_gt_revisions (
    id, clip_id, revision_no, final_decision, gt, source_type,
    source_table, source_id, source_version, source_event_key,
    parent_revision_id, reason, actor_id
  ) VALUES (
    v_revision_id, p_clip_id, v_revision_no, 'label', p_new_gt, 'owner_override',
    'motion_clip_gt_revisions', v_revision_id, 'owner-override-v1',
    'motion_clip_gt_revisions:' || v_revision_id::text || ':owner-override-v1',
    v_head.revision_id, btrim(p_reason), p_actor_id
  );

  UPDATE public.motion_clip_gt_heads
  SET revision_id = v_revision_id, updated_at = clock_timestamp()
  WHERE clip_id = p_clip_id;

  RETURN jsonb_build_object('revision_id', v_revision_id, 'status', 'final');
END;
$$;

CREATE OR REPLACE FUNCTION public.fn_resolve_motion_clip_gt_reconciliation(
  p_clip_id uuid,
  p_actor_id uuid,
  p_expected_head_revision_id uuid,
  p_selected_source text,
  p_new_gt jsonb,
  p_reason text
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  v_reconciliation public.motion_clip_gt_reconciliation%ROWTYPE;
  v_head_revision_id uuid;
  v_decision text;
  v_gt jsonb;
  v_revision_id uuid := gen_random_uuid();
  v_revision_no integer;
BEGIN
  IF p_selected_source NOT IN ('consensus', 'direct', 'new') THEN
    RAISE EXCEPTION 'invalid_selected_source' USING ERRCODE = '22023';
  END IF;
  IF p_actor_id IS NULL OR p_reason IS NULL
     OR char_length(btrim(p_reason)) NOT BETWEEN 10 AND 500 THEN
    RAISE EXCEPTION 'reason_required' USING ERRCODE = '22023';
  END IF;
  IF p_selected_source = 'new'
     AND (p_new_gt IS NULL OR jsonb_typeof(p_new_gt) <> 'object') THEN
    RAISE EXCEPTION 'new_gt_must_be_object' USING ERRCODE = '22023';
  END IF;

  PERFORM pg_advisory_xact_lock(hashtextextended(p_clip_id::text, 0));
  SELECT * INTO v_reconciliation
  FROM public.motion_clip_gt_reconciliation q
  WHERE q.clip_id = p_clip_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'reconciliation_not_found' USING ERRCODE = 'P0002';
  END IF;
  IF v_reconciliation.status <> 'pending' THEN
    RAISE EXCEPTION 'reconciliation_already_resolved' USING ERRCODE = 'PT409';
  END IF;

  SELECT h.revision_id INTO v_head_revision_id
  FROM public.motion_clip_gt_heads h
  WHERE h.clip_id = p_clip_id FOR UPDATE;
  IF v_head_revision_id IS DISTINCT FROM p_expected_head_revision_id THEN
    RAISE EXCEPTION 'expected_revision_mismatch' USING ERRCODE = 'PT409';
  END IF;

  IF p_selected_source = 'consensus' THEN
    SELECT c.final_decision,
           CASE WHEN c.final_decision = 'label' THEN c.final_gt ELSE NULL END
      INTO v_decision, v_gt
    FROM public.motion_clip_consensus c
    WHERE c.id = v_reconciliation.consensus_id;
  ELSIF p_selected_source = 'direct' THEN
    SELECT 'label', COALESCE(s.current_gt, s.initial_gt)
      INTO v_decision, v_gt
    FROM public.motion_clip_labeling_sessions s
    WHERE s.id = v_reconciliation.session_id;
  ELSE
    v_decision := 'label';
    v_gt := p_new_gt;
  END IF;

  IF v_decision IS NULL OR (v_decision = 'label' AND v_gt IS NULL) THEN
    RAISE EXCEPTION 'selected_source_invalid' USING ERRCODE = '22023';
  END IF;

  SELECT COALESCE(max(r.revision_no), 0) + 1 INTO v_revision_no
  FROM public.motion_clip_gt_revisions r WHERE r.clip_id = p_clip_id;

  INSERT INTO public.motion_clip_gt_revisions (
    id, clip_id, revision_no, final_decision, gt, source_type,
    source_table, source_id, source_version, source_event_key,
    parent_revision_id, reason, actor_id
  ) VALUES (
    v_revision_id, p_clip_id, v_revision_no, v_decision,
    CASE WHEN v_decision = 'label' THEN v_gt ELSE NULL END,
    'owner_adjudication', 'motion_clip_gt_reconciliation', v_revision_id,
    'owner-reconciliation-v1',
    'motion_clip_gt_reconciliation:' || v_revision_id::text || ':owner-reconciliation-v1',
    v_head_revision_id, btrim(p_reason), p_actor_id
  );

  INSERT INTO public.motion_clip_gt_heads (clip_id, revision_id)
  VALUES (p_clip_id, v_revision_id)
  ON CONFLICT (clip_id) DO UPDATE
    SET revision_id = EXCLUDED.revision_id, updated_at = clock_timestamp();

  UPDATE public.motion_clip_gt_reconciliation
  SET status = 'resolved', resolved_revision_id = v_revision_id,
      resolved_at = clock_timestamp()
  WHERE clip_id = p_clip_id;

  RETURN jsonb_build_object('revision_id', v_revision_id, 'status', 'final');
END;
$$;

CREATE OR REPLACE FUNCTION public.fn_record_motion_clip_gt_projection_run(
  p_run_id uuid,
  p_status text,
  p_scanned integer,
  p_inserted integer,
  p_error_code text,
  p_started_at timestamptz
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
  IF p_run_id IS NULL OR p_status NOT IN ('succeeded', 'failed')
     OR p_scanned IS NULL OR p_scanned < 0
     OR p_inserted IS NULL OR p_inserted < 0
     OR p_started_at IS NULL
     OR (p_status = 'succeeded' AND p_error_code IS NOT NULL)
     OR (p_status = 'failed' AND (p_error_code IS NULL OR char_length(p_error_code) NOT BETWEEN 1 AND 80)) THEN
    RAISE EXCEPTION 'invalid_projection_run' USING ERRCODE = '22023';
  END IF;
  INSERT INTO public.motion_clip_gt_projection_runs
    (id, status, scanned, inserted, error_code, started_at)
  VALUES (p_run_id, p_status, p_scanned, p_inserted, p_error_code, p_started_at)
  ON CONFLICT (id) DO NOTHING;
END;
$$;

CREATE OR REPLACE FUNCTION public.fn_get_motion_clip_gt_projection_health()
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  v_last_success_at timestamptz;
  v_last_error_code text;
  v_oldest_pending_at timestamptz;
  v_pending_count integer;
  v_lag_seconds integer;
  v_healthy boolean;
BEGIN
  SELECT r.finished_at INTO v_last_success_at
  FROM public.motion_clip_gt_projection_runs r
  WHERE r.status = 'succeeded'
  ORDER BY r.finished_at DESC, r.id DESC
  LIMIT 1;

  SELECT r.error_code INTO v_last_error_code
  FROM public.motion_clip_gt_projection_runs r
  WHERE r.status = 'failed'
    AND (v_last_success_at IS NULL OR r.finished_at > v_last_success_at)
  ORDER BY r.finished_at DESC, r.id DESC
  LIMIT 1;

  WITH eligible AS (
    SELECT c.clip_id, c.updated_at AS finalized_at,
           'motion_clip_consensus:' || c.id::text || ':' || COALESCE(c.comparator_version, 'unknown') AS source_event_key
    FROM public.motion_clip_consensus c
    WHERE c.cohort_kind = 'live'
      AND c.status IN ('agreed', 'owner_resolved')
      AND c.final_decision IN ('label', 'hold', 'exclude')
      AND (c.final_decision <> 'label' OR c.final_gt IS NOT NULL)

    UNION ALL

    SELECT s.clip_id, s.updated_at AS finalized_at,
           'motion_clip_labeling_sessions:' || s.id::text || ':motion-labeling-v3' AS source_event_key
    FROM public.motion_clip_labeling_sessions s
    WHERE s.stage = 'completed'
      AND COALESCE(s.current_gt, s.initial_gt) IS NOT NULL
  ), pending AS (
    SELECT e.finalized_at
    FROM eligible e
    WHERE NOT EXISTS (
      SELECT 1 FROM public.motion_clip_gt_revisions r
      WHERE r.source_event_key = e.source_event_key
    )
      AND NOT EXISTS (
        SELECT 1 FROM public.motion_clip_gt_reconciliation q
        WHERE q.clip_id = e.clip_id
      )
  )
  SELECT count(*)::integer, min(finalized_at)
    INTO v_pending_count, v_oldest_pending_at
  FROM pending;

  v_lag_seconds := CASE
    WHEN v_oldest_pending_at IS NULL THEN 0
    ELSE GREATEST(0, floor(extract(epoch FROM (clock_timestamp() - v_oldest_pending_at)))::integer)
  END;
  v_healthy := v_last_success_at IS NOT NULL
    AND clock_timestamp() - v_last_success_at <= interval '20 minutes'
    AND v_lag_seconds <= 1200;

  RETURN jsonb_build_object(
    'healthy', v_healthy,
    'last_success_at', v_last_success_at,
    'lag_seconds', v_lag_seconds,
    'pending_final_source_count', v_pending_count,
    'last_error_code', v_last_error_code
  );
END;
$$;

CREATE OR REPLACE FUNCTION public.fn_audit_motion_clip_canonical_gt()
RETURNS jsonb
LANGUAGE sql
SECURITY DEFINER
SET search_path = ''
AS $$
  WITH source_counts AS (
    SELECT
      count(*) FILTER (
        WHERE c.cohort_kind = 'live'
          AND c.status IN ('agreed', 'owner_resolved')
      )::integer AS live_final,
      count(*) FILTER (
        WHERE c.cohort_kind = 'live' AND c.status = 'awaiting'
      )::integer AS live_awaiting,
      count(*) FILTER (
        WHERE c.cohort_kind = 'live' AND c.status = 'conflict'
      )::integer AS live_conflict,
      count(*) FILTER (WHERE c.cohort_kind = 'canary')::integer AS canary
    FROM public.motion_clip_consensus c
  ), session_counts AS (
    SELECT count(*) FILTER (
      WHERE s.stage = 'completed'
    )::integer AS completed
    FROM public.motion_clip_labeling_sessions s
  ), canonical_counts AS (
    SELECT
      (SELECT count(*)::integer FROM public.motion_clip_gt_revisions) AS revisions,
      (SELECT count(*)::integer FROM public.motion_clip_gt_heads) AS heads,
      (SELECT count(*)::integer FROM public.motion_clip_gt_reconciliation
       WHERE status = 'pending') AS reconciliation_pending
  ), overlap AS (
    SELECT count(*)::integer AS value
    FROM public.motion_clip_consensus c
    WHERE c.cohort_kind = 'live'
      AND c.status IN ('agreed', 'owner_resolved')
      AND EXISTS (
        SELECT 1 FROM public.motion_clip_labeling_sessions s
        WHERE s.clip_id = c.clip_id AND s.stage = 'completed'
          AND COALESCE(s.current_gt, s.initial_gt) IS NOT NULL
      )
  ), integrity AS (
    SELECT count(*)::integer AS orphan_heads
    FROM public.motion_clip_gt_heads h
    LEFT JOIN public.motion_clip_gt_revisions r
      ON r.id = h.revision_id AND r.clip_id = h.clip_id
    WHERE r.id IS NULL
  ), expected_sources AS (
    SELECT c.clip_id, c.final_decision AS decision,
           CASE WHEN c.final_decision = 'label' THEN c.final_gt ELSE NULL END AS gt,
           'motion_clip_consensus:' || c.id::text || ':' || COALESCE(c.comparator_version, 'unknown') AS source_event_key
    FROM public.motion_clip_consensus c
    WHERE c.cohort_kind = 'live'
      AND c.status IN ('agreed', 'owner_resolved')
      AND c.final_decision IN ('label', 'hold', 'exclude')
      AND (c.final_decision <> 'label' OR c.final_gt IS NOT NULL)
    UNION ALL
    SELECT s.clip_id, 'label', COALESCE(s.current_gt, s.initial_gt),
           'motion_clip_labeling_sessions:' || s.id::text || ':motion-labeling-v3'
    FROM public.motion_clip_labeling_sessions s
    WHERE s.stage = 'completed'
      AND COALESCE(s.current_gt, s.initial_gt) IS NOT NULL
  ), parity_mismatches AS (
    SELECT count(*)::integer AS value
    FROM expected_sources e
    WHERE NOT EXISTS (
      SELECT 1 FROM public.motion_clip_gt_reconciliation q
      WHERE q.clip_id = e.clip_id
    )
      AND (
        NOT EXISTS (
          SELECT 1
          FROM public.motion_clip_gt_revisions r
          WHERE r.source_event_key = e.source_event_key
            AND r.final_decision = e.decision
            AND r.gt IS NOT DISTINCT FROM e.gt
        )
        OR NOT EXISTS (
          SELECT 1
          FROM public.motion_clip_gt_heads h
          JOIN public.motion_clip_gt_revisions current_revision
            ON current_revision.id = h.revision_id
            AND current_revision.clip_id = h.clip_id
          WHERE h.clip_id = e.clip_id
        )
      )
  ), digests AS (
    SELECT encode(extensions.digest(convert_to(
      COALESCE((
        SELECT string_agg(
          concat_ws('|', c.id::text, c.clip_id::text, c.cohort_kind, c.status,
            COALESCE(c.comparator_version, ''), COALESCE(c.final_decision, ''),
            COALESCE(c.final_gt::text, '')),
          E'\n' ORDER BY c.id
        ) FROM public.motion_clip_consensus c
      ), '') || E'\n--sessions--\n' || COALESCE((
        SELECT string_agg(
          concat_ws('|', s.id::text, s.clip_id::text, s.reviewed_by::text, s.stage,
            COALESCE(s.initial_gt::text, ''), COALESCE(s.current_gt::text, '')),
          E'\n' ORDER BY s.id
        ) FROM public.motion_clip_labeling_sessions s
      ), ''), 'UTF8'), 'sha256'), 'hex') AS source_digest
  )
  SELECT jsonb_build_object(
    'source_counts', jsonb_build_object(
      'live_final', sc.live_final,
      'direct_completed', ss.completed
    ),
    'canonical_counts', jsonb_build_object(
      'revisions', cc.revisions,
      'heads', cc.heads
    ),
    'excluded_counts', jsonb_build_object(
      'live_awaiting', sc.live_awaiting,
      'live_conflict', sc.live_conflict,
      'canary', sc.canary
    ),
    'overlap_count', o.value,
    'reconciliation_pending', cc.reconciliation_pending,
    'orphan_head_count', i.orphan_heads,
    'source_mutation_digest', d.source_digest,
    'parity_mismatch_count', p.value
  )
  FROM source_counts sc
  CROSS JOIN session_counts ss
  CROSS JOIN canonical_counts cc
  CROSS JOIN overlap o
  CROSS JOIN integrity i
  CROSS JOIN parity_mismatches p
  CROSS JOIN digests d;
$$;

REVOKE ALL ON FUNCTION public.fn_project_motion_clip_canonical_gt(uuid, boolean, integer, uuid, uuid)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_project_motion_clip_canonical_gt(uuid, boolean, integer, uuid, uuid)
  TO service_role;

REVOKE ALL ON FUNCTION public.fn_get_motion_clip_canonical_gt(uuid, uuid)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_get_motion_clip_canonical_gt(uuid, uuid)
  TO service_role;

REVOKE ALL ON FUNCTION public.fn_override_motion_clip_canonical_gt(uuid, uuid, uuid, jsonb, text)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_override_motion_clip_canonical_gt(uuid, uuid, uuid, jsonb, text)
  TO service_role;

REVOKE ALL ON FUNCTION public.fn_resolve_motion_clip_gt_reconciliation(uuid, uuid, uuid, text, jsonb, text)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_resolve_motion_clip_gt_reconciliation(uuid, uuid, uuid, text, jsonb, text)
  TO service_role;

REVOKE ALL ON FUNCTION public.fn_record_motion_clip_gt_projection_run(uuid, text, integer, integer, text, timestamptz)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_record_motion_clip_gt_projection_run(uuid, text, integer, integer, text, timestamptz)
  TO service_role;

REVOKE ALL ON FUNCTION public.fn_get_motion_clip_gt_projection_health()
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_get_motion_clip_gt_projection_health()
  TO service_role;

REVOKE ALL ON FUNCTION public.fn_audit_motion_clip_canonical_gt()
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_audit_motion_clip_canonical_gt()
  TO service_role;

COMMIT;
