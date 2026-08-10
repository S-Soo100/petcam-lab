BEGIN;

CREATE TABLE public.yolo_model_versions (
  version text PRIMARY KEY CHECK (char_length(btrim(version)) BETWEEN 1 AND 128),
  artifact_digest text NOT NULL CHECK (artifact_digest ~ '^[0-9a-f]{64}$'),
  architecture text NOT NULL CHECK (char_length(btrim(architecture)) BETWEEN 1 AND 200),
  created_by uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.yolo_model_evaluations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  model_version text NOT NULL REFERENCES public.yolo_model_versions(version) ON DELETE RESTRICT,
  suite text NOT NULL CHECK (suite IN ('fixed_test','future_holdout')),
  manifest_digest text NOT NULL CHECK (manifest_digest ~ '^[0-9a-f]{64}$'),
  metrics jsonb NOT NULL CHECK (jsonb_typeof(metrics) = 'object'),
  passed boolean NOT NULL,
  recorded_by uuid NOT NULL,
  recorded_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (model_version, suite, manifest_digest)
);

CREATE TABLE public.yolo_model_approval_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  model_version text NOT NULL REFERENCES public.yolo_model_versions(version) ON DELETE RESTRICT,
  owner_id uuid NOT NULL,
  decision text NOT NULL CHECK (decision IN ('approve','reject')),
  reason text NOT NULL CHECK (char_length(btrim(reason)) BETWEEN 3 AND 1000),
  decided_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.yolo_model_activation_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  model_version text NOT NULL REFERENCES public.yolo_model_versions(version) ON DELETE RESTRICT,
  owner_id uuid NOT NULL,
  action text NOT NULL CHECK (action IN ('activate','rollback')),
  reason text NOT NULL CHECK (char_length(btrim(reason)) BETWEEN 3 AND 1000),
  activated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.yolo_dataset_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  version text NOT NULL UNIQUE CHECK (char_length(btrim(version)) BETWEEN 1 AND 128),
  status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','frozen')),
  manifest_digest text NOT NULL CHECK (manifest_digest ~ '^[0-9a-f]{64}$'),
  created_by uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.yolo_dataset_status_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  dataset_version_id uuid NOT NULL UNIQUE REFERENCES public.yolo_dataset_versions(id) ON DELETE RESTRICT,
  owner_id uuid NOT NULL,
  status text NOT NULL CHECK (status = 'frozen'),
  reason text NOT NULL CHECK (char_length(btrim(reason)) BETWEEN 3 AND 1000),
  recorded_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.yolo_bbox_tasks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  assignee_id uuid NOT NULL,
  media_kind text NOT NULL CHECK (media_kind IN ('image','video')),
  media_ref text NOT NULL CHECK (char_length(btrim(media_ref)) BETWEEN 1 AND 1000),
  frame_manifest jsonb NOT NULL CHECK (
    jsonb_typeof(frame_manifest) = 'array'
    AND jsonb_array_length(frame_manifest) BETWEEN 1 AND 3600
  ),
  model_version text NOT NULL REFERENCES public.yolo_model_versions(version) ON DELETE RESTRICT,
  prediction_snapshot jsonb NOT NULL CHECK (
    jsonb_typeof(prediction_snapshot) = 'object'
    AND (prediction_snapshot->>'model_version' = model_version) IS TRUE
    AND (prediction_snapshot->>'media_kind' = media_kind) IS TRUE
    AND (prediction_snapshot->>'provider_mode' IN ('fake','worker')) IS TRUE
    AND (jsonb_typeof(prediction_snapshot->'frames') = 'array') IS TRUE
  ),
  created_by uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.yolo_bbox_blind_submissions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  task_id uuid NOT NULL UNIQUE REFERENCES public.yolo_bbox_tasks(id) ON DELETE RESTRICT,
  contributor_id uuid NOT NULL,
  boxes jsonb NOT NULL CHECK (jsonb_typeof(boxes) = 'array'),
  no_gecko boolean NOT NULL,
  submitted_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.yolo_bbox_reveals (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  task_id uuid NOT NULL UNIQUE REFERENCES public.yolo_bbox_tasks(id) ON DELETE RESTRICT,
  submission_id uuid NOT NULL UNIQUE REFERENCES public.yolo_bbox_blind_submissions(id) ON DELETE RESTRICT,
  contributor_id uuid NOT NULL,
  revealed_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.yolo_bbox_revisions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  task_id uuid NOT NULL REFERENCES public.yolo_bbox_tasks(id) ON DELETE RESTRICT,
  contributor_id uuid NOT NULL,
  revision_no integer NOT NULL CHECK (revision_no > 0),
  boxes jsonb NOT NULL CHECK (jsonb_typeof(boxes) = 'array'),
  no_gecko boolean NOT NULL,
  reason text NOT NULL CHECK (char_length(btrim(reason)) BETWEEN 3 AND 1000),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (task_id, revision_no)
);

CREATE TABLE public.yolo_bbox_owner_decisions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  revision_id uuid NOT NULL UNIQUE REFERENCES public.yolo_bbox_revisions(id) ON DELETE RESTRICT,
  owner_id uuid NOT NULL,
  decision text NOT NULL CHECK (decision IN ('approve','reject')),
  reason text NOT NULL CHECK (char_length(btrim(reason)) BETWEEN 3 AND 1000),
  decided_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.yolo_dataset_memberships (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  dataset_version_id uuid NOT NULL REFERENCES public.yolo_dataset_versions(id) ON DELETE RESTRICT,
  revision_id uuid NOT NULL REFERENCES public.yolo_bbox_revisions(id) ON DELETE RESTRICT,
  owner_decision_id uuid NOT NULL REFERENCES public.yolo_bbox_owner_decisions(id) ON DELETE RESTRICT,
  added_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (dataset_version_id, revision_id),
  UNIQUE (revision_id)
);

CREATE INDEX idx_yolo_bbox_tasks_assignee ON public.yolo_bbox_tasks (assignee_id, created_at, id);
CREATE INDEX idx_yolo_bbox_revisions_task ON public.yolo_bbox_revisions (task_id, revision_no DESC);
CREATE INDEX idx_yolo_model_evaluations_gate ON public.yolo_model_evaluations (model_version, suite, recorded_at DESC);
CREATE INDEX idx_yolo_model_approvals_gate ON public.yolo_model_approval_events (model_version, decided_at DESC, id DESC);

CREATE OR REPLACE FUNCTION public.fn_reject_yolo_history_mutation()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = '' AS $$
BEGIN
  RAISE EXCEPTION 'yolo history is append-only' USING ERRCODE = '0A000';
END;
$$;

CREATE TRIGGER trg_yolo_model_versions_immutable
  BEFORE UPDATE OR DELETE OR TRUNCATE ON public.yolo_model_versions
  FOR EACH STATEMENT EXECUTE FUNCTION public.fn_reject_yolo_history_mutation();
CREATE TRIGGER trg_yolo_model_evaluations_append_only
  BEFORE UPDATE OR DELETE OR TRUNCATE ON public.yolo_model_evaluations
  FOR EACH STATEMENT EXECUTE FUNCTION public.fn_reject_yolo_history_mutation();
CREATE TRIGGER trg_yolo_model_approval_events_append_only
  BEFORE UPDATE OR DELETE OR TRUNCATE ON public.yolo_model_approval_events
  FOR EACH STATEMENT EXECUTE FUNCTION public.fn_reject_yolo_history_mutation();
CREATE TRIGGER trg_yolo_model_activation_events_append_only
  BEFORE UPDATE OR DELETE OR TRUNCATE ON public.yolo_model_activation_events
  FOR EACH STATEMENT EXECUTE FUNCTION public.fn_reject_yolo_history_mutation();
CREATE TRIGGER trg_yolo_dataset_versions_immutable
  BEFORE UPDATE OR DELETE OR TRUNCATE ON public.yolo_dataset_versions
  FOR EACH STATEMENT EXECUTE FUNCTION public.fn_reject_yolo_history_mutation();
CREATE TRIGGER trg_yolo_dataset_status_events_append_only
  BEFORE UPDATE OR DELETE OR TRUNCATE ON public.yolo_dataset_status_events
  FOR EACH STATEMENT EXECUTE FUNCTION public.fn_reject_yolo_history_mutation();
CREATE TRIGGER trg_yolo_bbox_tasks_immutable
  BEFORE UPDATE OR DELETE OR TRUNCATE ON public.yolo_bbox_tasks
  FOR EACH STATEMENT EXECUTE FUNCTION public.fn_reject_yolo_history_mutation();
CREATE TRIGGER trg_yolo_bbox_blind_submissions_append_only
  BEFORE UPDATE OR DELETE OR TRUNCATE ON public.yolo_bbox_blind_submissions
  FOR EACH STATEMENT EXECUTE FUNCTION public.fn_reject_yolo_history_mutation();
CREATE TRIGGER trg_yolo_bbox_reveals_append_only
  BEFORE UPDATE OR DELETE OR TRUNCATE ON public.yolo_bbox_reveals
  FOR EACH STATEMENT EXECUTE FUNCTION public.fn_reject_yolo_history_mutation();
CREATE TRIGGER trg_yolo_bbox_revisions_append_only
  BEFORE UPDATE OR DELETE OR TRUNCATE ON public.yolo_bbox_revisions
  FOR EACH STATEMENT EXECUTE FUNCTION public.fn_reject_yolo_history_mutation();
CREATE TRIGGER trg_yolo_bbox_owner_decisions_append_only
  BEFORE UPDATE OR DELETE OR TRUNCATE ON public.yolo_bbox_owner_decisions
  FOR EACH STATEMENT EXECUTE FUNCTION public.fn_reject_yolo_history_mutation();
CREATE TRIGGER trg_yolo_dataset_memberships_append_only
  BEFORE UPDATE OR DELETE OR TRUNCATE ON public.yolo_dataset_memberships
  FOR EACH STATEMENT EXECUTE FUNCTION public.fn_reject_yolo_history_mutation();

CREATE OR REPLACE FUNCTION public.fn_validate_yolo_boxes(p_boxes jsonb, p_no_gecko boolean)
RETURNS boolean
LANGUAGE plpgsql IMMUTABLE
SET search_path = '' AS $$
DECLARE
  item jsonb;
  box jsonb;
  frame_index numeric;
  x numeric;
  y numeric;
  width numeric;
  height numeric;
BEGIN
  IF jsonb_typeof(p_boxes) <> 'array' OR jsonb_array_length(p_boxes) > 100 THEN
    RETURN false;
  END IF;
  IF p_no_gecko <> (jsonb_array_length(p_boxes) = 0) THEN
    RETURN false;
  END IF;
  FOR item IN SELECT value FROM jsonb_array_elements(p_boxes) LOOP
    IF jsonb_typeof(item) <> 'object'
      OR jsonb_typeof(item->'frame_index') <> 'number'
      OR jsonb_typeof(item->'bbox') <> 'object' THEN
      RETURN false;
    END IF;
    frame_index := (item->>'frame_index')::numeric;
    IF frame_index < 0 OR frame_index <> trunc(frame_index) THEN RETURN false; END IF;
    box := item->'bbox';
    IF jsonb_typeof(box->'x') <> 'number'
      OR jsonb_typeof(box->'y') <> 'number'
      OR jsonb_typeof(box->'width') <> 'number'
      OR jsonb_typeof(box->'height') <> 'number' THEN
      RETURN false;
    END IF;
    x := (box->>'x')::numeric;
    y := (box->>'y')::numeric;
    width := (box->>'width')::numeric;
    height := (box->>'height')::numeric;
    IF x < 0 OR y < 0 OR width <= 0 OR height <= 0 OR x + width > 1 OR y + height > 1 THEN
      RETURN false;
    END IF;
  END LOOP;
  RETURN true;
END;
$$;

CREATE OR REPLACE FUNCTION public.fn_get_yolo_bbox_workspace(p_contributor_id uuid)
RETURNS jsonb
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = '' AS $$
  WITH assigned AS (
    SELECT t.id, t.media_kind, t.media_ref, t.frame_manifest, t.created_at,
           s.id AS submission_id, rv.id AS reveal_id, r.id AS revision_id,
           d.decision AS revision_decision
    FROM public.yolo_bbox_tasks t
    LEFT JOIN public.yolo_bbox_blind_submissions s ON s.task_id = t.id
    LEFT JOIN public.yolo_bbox_reveals rv ON rv.task_id = t.id
    LEFT JOIN LATERAL (
      SELECT id FROM public.yolo_bbox_revisions x WHERE x.task_id = t.id
      ORDER BY revision_no DESC LIMIT 1
    ) r ON true
    LEFT JOIN public.yolo_bbox_owner_decisions d ON d.revision_id = r.id
    WHERE t.assignee_id = p_contributor_id
  ), next_task AS (
    SELECT * FROM assigned
    WHERE revision_id IS NULL OR revision_decision = 'reject'
    ORDER BY created_at, id LIMIT 1
  )
  SELECT jsonb_build_object(
    'enabled', EXISTS (SELECT 1 FROM assigned),
    'total', (SELECT count(*) FROM assigned),
    'completed', (SELECT count(*) FROM assigned
                  WHERE revision_id IS NOT NULL AND revision_decision IS DISTINCT FROM 'reject'),
    'next_task', (
      SELECT jsonb_build_object(
        'task_id', id,
        'media_kind', media_kind,
        'media_ref', media_ref,
        'frame_manifest', frame_manifest,
        'stage', CASE
          WHEN submission_id IS NULL THEN 'blind'
          WHEN reveal_id IS NULL THEN 'submitted'
          ELSE 'revealed'
        END
      ) FROM next_task
    )
  );
$$;

CREATE OR REPLACE FUNCTION public.fn_submit_yolo_bbox_blind(
  p_contributor_id uuid, p_task_id uuid, p_boxes jsonb, p_no_gecko boolean
) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  task public.yolo_bbox_tasks%rowtype;
  submission_id uuid;
BEGIN
  SELECT * INTO task FROM public.yolo_bbox_tasks WHERE id = p_task_id FOR UPDATE;
  IF NOT FOUND OR task.assignee_id <> p_contributor_id THEN
    RAISE EXCEPTION 'contributor_forbidden' USING ERRCODE = 'PT403';
  END IF;
  IF NOT public.fn_validate_yolo_boxes(p_boxes, p_no_gecko) THEN
    RAISE EXCEPTION 'invalid_boxes' USING ERRCODE = '22023';
  END IF;
  IF EXISTS (
    SELECT 1 FROM jsonb_array_elements(p_boxes) submitted_box
    WHERE NOT EXISTS (
      SELECT 1 FROM jsonb_array_elements(task.frame_manifest) assigned_frame
      WHERE assigned_frame->>'frame_index' = submitted_box->>'frame_index'
    )
  ) THEN
    RAISE EXCEPTION 'box_frame_not_assigned' USING ERRCODE = '22023';
  END IF;
  INSERT INTO public.yolo_bbox_blind_submissions (task_id, contributor_id, boxes, no_gecko)
  VALUES (p_task_id, p_contributor_id, p_boxes, p_no_gecko)
  ON CONFLICT (task_id) DO NOTHING RETURNING id INTO submission_id;
  IF submission_id IS NULL THEN
    RAISE EXCEPTION 'blind_already_submitted' USING ERRCODE = 'PT409';
  END IF;
  RETURN jsonb_build_object('task_id', p_task_id, 'submission_id', submission_id, 'stage', 'submitted');
END;
$$;

CREATE OR REPLACE FUNCTION public.fn_reveal_yolo_bbox_prediction(
  p_contributor_id uuid, p_task_id uuid
) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  task public.yolo_bbox_tasks%rowtype;
  submission public.yolo_bbox_blind_submissions%rowtype;
  reveal public.yolo_bbox_reveals%rowtype;
BEGIN
  SELECT * INTO task FROM public.yolo_bbox_tasks WHERE id = p_task_id FOR UPDATE;
  IF NOT FOUND OR task.assignee_id <> p_contributor_id THEN
    RAISE EXCEPTION 'contributor_forbidden' USING ERRCODE = 'PT403';
  END IF;
  SELECT * INTO submission FROM public.yolo_bbox_blind_submissions
  WHERE task_id = p_task_id AND contributor_id = p_contributor_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'blind_submission_required' USING ERRCODE = 'PT409';
  END IF;
  INSERT INTO public.yolo_bbox_reveals (task_id, submission_id, contributor_id)
  VALUES (p_task_id, submission.id, p_contributor_id)
  ON CONFLICT (task_id) DO NOTHING;
  SELECT * INTO reveal FROM public.yolo_bbox_reveals WHERE task_id = p_task_id;
  RETURN jsonb_build_object(
    'task_id', p_task_id,
    'revealed_at', reveal.revealed_at,
    'prediction', task.prediction_snapshot,
    'blind_boxes', submission.boxes,
    'blind_no_gecko', submission.no_gecko,
    'working_boxes', coalesce((
      SELECT r.boxes
      FROM public.yolo_bbox_revisions r
      JOIN public.yolo_bbox_owner_decisions d ON d.revision_id = r.id AND d.decision = 'reject'
      WHERE r.task_id = p_task_id
      ORDER BY r.revision_no DESC LIMIT 1
    ), submission.boxes),
    'working_no_gecko', coalesce((
      SELECT r.no_gecko
      FROM public.yolo_bbox_revisions r
      JOIN public.yolo_bbox_owner_decisions d ON d.revision_id = r.id AND d.decision = 'reject'
      WHERE r.task_id = p_task_id
      ORDER BY r.revision_no DESC LIMIT 1
    ), submission.no_gecko),
    'owner_feedback', (
      SELECT d.reason
      FROM public.yolo_bbox_revisions r
      JOIN public.yolo_bbox_owner_decisions d ON d.revision_id = r.id AND d.decision = 'reject'
      WHERE r.task_id = p_task_id
      ORDER BY r.revision_no DESC LIMIT 1
    ),
    'stage', 'revealed'
  );
END;
$$;

CREATE OR REPLACE FUNCTION public.fn_submit_yolo_bbox_revision(
  p_contributor_id uuid, p_task_id uuid, p_boxes jsonb, p_no_gecko boolean, p_reason text
) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  task public.yolo_bbox_tasks%rowtype;
  next_revision integer;
  revision_id uuid;
BEGIN
  SELECT * INTO task FROM public.yolo_bbox_tasks WHERE id = p_task_id FOR UPDATE;
  IF NOT FOUND OR task.assignee_id <> p_contributor_id THEN
    RAISE EXCEPTION 'contributor_forbidden' USING ERRCODE = 'PT403';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM public.yolo_bbox_reveals
    WHERE task_id = p_task_id AND contributor_id = p_contributor_id
  ) THEN
    RAISE EXCEPTION 'prediction_reveal_required' USING ERRCODE = 'PT409';
  END IF;
  IF NOT public.fn_validate_yolo_boxes(p_boxes, p_no_gecko) THEN
    RAISE EXCEPTION 'invalid_boxes' USING ERRCODE = '22023';
  END IF;
  IF EXISTS (
    SELECT 1 FROM jsonb_array_elements(p_boxes) submitted_box
    WHERE NOT EXISTS (
      SELECT 1 FROM jsonb_array_elements(task.frame_manifest) assigned_frame
      WHERE assigned_frame->>'frame_index' = submitted_box->>'frame_index'
    )
  ) THEN
    RAISE EXCEPTION 'box_frame_not_assigned' USING ERRCODE = '22023';
  END IF;
  IF char_length(btrim(coalesce(p_reason, ''))) NOT BETWEEN 3 AND 1000 THEN
    RAISE EXCEPTION 'revision_reason_required' USING ERRCODE = '22023';
  END IF;
  IF EXISTS (
    SELECT 1
    FROM public.yolo_bbox_revisions r
    LEFT JOIN public.yolo_bbox_owner_decisions d ON d.revision_id = r.id
    WHERE r.task_id = p_task_id AND (d.id IS NULL OR d.decision = 'approve')
  ) THEN
    RAISE EXCEPTION 'revision_pending_or_complete' USING ERRCODE = 'PT409';
  END IF;
  SELECT coalesce(max(revision_no), 0) + 1 INTO next_revision
  FROM public.yolo_bbox_revisions WHERE task_id = p_task_id;
  INSERT INTO public.yolo_bbox_revisions
    (task_id, contributor_id, revision_no, boxes, no_gecko, reason)
  VALUES (p_task_id, p_contributor_id, next_revision, p_boxes, p_no_gecko, btrim(p_reason))
  RETURNING id INTO revision_id;
  RETURN jsonb_build_object('task_id', p_task_id, 'revision_id', revision_id, 'stage', 'owner_review');
END;
$$;

CREATE OR REPLACE FUNCTION public.fn_owner_decide_yolo_bbox_revision(
  p_owner_id uuid, p_revision_id uuid, p_decision text, p_reason text, p_dataset_version_id uuid
) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  decision_id uuid;
  locked_dataset_id uuid;
BEGIN
  IF p_decision NOT IN ('approve','reject') THEN
    RAISE EXCEPTION 'invalid_decision' USING ERRCODE = '22023';
  END IF;
  IF char_length(btrim(coalesce(p_reason, ''))) NOT BETWEEN 3 AND 1000 THEN
    RAISE EXCEPTION 'decision_reason_required' USING ERRCODE = '22023';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM public.yolo_bbox_revisions WHERE id = p_revision_id) THEN
    RAISE EXCEPTION 'revision_not_found' USING ERRCODE = 'PT404';
  END IF;
  IF p_decision = 'approve' THEN
    IF p_dataset_version_id IS NULL THEN
      RAISE EXCEPTION 'dataset_version_required' USING ERRCODE = '22023';
    END IF;
    SELECT id INTO locked_dataset_id
    FROM public.yolo_dataset_versions
    WHERE id = p_dataset_version_id AND status = 'draft'
    FOR UPDATE;
    IF locked_dataset_id IS NULL OR EXISTS (
      SELECT 1 FROM public.yolo_dataset_status_events
      WHERE dataset_version_id = p_dataset_version_id
    ) THEN
      RAISE EXCEPTION 'dataset_version_required' USING ERRCODE = '22023';
    END IF;
  END IF;
  INSERT INTO public.yolo_bbox_owner_decisions (revision_id, owner_id, decision, reason)
  VALUES (p_revision_id, p_owner_id, p_decision, btrim(p_reason))
  ON CONFLICT (revision_id) DO NOTHING RETURNING id INTO decision_id;
  IF decision_id IS NULL THEN
    RAISE EXCEPTION 'revision_already_decided' USING ERRCODE = 'PT409';
  END IF;
  IF p_decision = 'approve' THEN
    INSERT INTO public.yolo_dataset_memberships
      (dataset_version_id, revision_id, owner_decision_id)
    VALUES (p_dataset_version_id, p_revision_id, decision_id);
  END IF;
  RETURN jsonb_build_object(
    'revision_id', p_revision_id,
    'decision', p_decision,
    'dataset_version_id', CASE WHEN p_decision = 'approve' THEN p_dataset_version_id ELSE NULL END
  );
END;
$$;

CREATE OR REPLACE FUNCTION public.fn_freeze_yolo_dataset(
  p_owner_id uuid, p_dataset_version_id uuid, p_reason text
) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  event_id uuid;
  locked_dataset_id uuid;
BEGIN
  IF char_length(btrim(coalesce(p_reason, ''))) NOT BETWEEN 3 AND 1000 THEN
    RAISE EXCEPTION 'dataset_freeze_reason_required' USING ERRCODE = '22023';
  END IF;
  SELECT id INTO locked_dataset_id
  FROM public.yolo_dataset_versions
  WHERE id = p_dataset_version_id AND status = 'draft'
  FOR UPDATE;
  IF locked_dataset_id IS NULL THEN
    RAISE EXCEPTION 'dataset_version_not_found' USING ERRCODE = 'PT404';
  END IF;
  IF EXISTS (
    SELECT 1 FROM public.yolo_dataset_status_events
    WHERE dataset_version_id = p_dataset_version_id
  ) THEN
    RAISE EXCEPTION 'dataset_already_frozen' USING ERRCODE = 'PT409';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM public.yolo_dataset_memberships
    WHERE dataset_version_id = p_dataset_version_id
  ) THEN
    RAISE EXCEPTION 'dataset_membership_required' USING ERRCODE = 'PT409';
  END IF;
  INSERT INTO public.yolo_dataset_status_events
    (dataset_version_id, owner_id, status, reason)
  VALUES (p_dataset_version_id, p_owner_id, 'frozen', btrim(p_reason))
  RETURNING id INTO event_id;
  RETURN jsonb_build_object(
    'event_id', event_id, 'dataset_version_id', p_dataset_version_id, 'status', 'frozen'
  );
END;
$$;

CREATE OR REPLACE FUNCTION public.fn_owner_decide_yolo_model(
  p_owner_id uuid, p_model_version text, p_decision text, p_reason text
) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  event_id uuid;
BEGIN
  IF p_decision NOT IN ('approve','reject') THEN
    RAISE EXCEPTION 'invalid_model_decision' USING ERRCODE = '22023';
  END IF;
  IF char_length(btrim(coalesce(p_reason, ''))) NOT BETWEEN 3 AND 1000 THEN
    RAISE EXCEPTION 'model_decision_reason_required' USING ERRCODE = '22023';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM public.yolo_model_versions WHERE version = p_model_version) THEN
    RAISE EXCEPTION 'model_version_not_found' USING ERRCODE = 'PT404';
  END IF;
  IF p_decision = 'approve' AND (
    NOT coalesce((
      SELECT passed FROM public.yolo_model_evaluations
      WHERE model_version = p_model_version AND suite = 'fixed_test'
      ORDER BY recorded_at DESC, id DESC LIMIT 1
    ), false) OR NOT coalesce((
      SELECT passed FROM public.yolo_model_evaluations
      WHERE model_version = p_model_version AND suite = 'future_holdout'
      ORDER BY recorded_at DESC, id DESC LIMIT 1
    ), false)
  ) THEN
    RAISE EXCEPTION 'model_evaluations_required' USING ERRCODE = 'PT409';
  END IF;
  INSERT INTO public.yolo_model_approval_events (model_version, owner_id, decision, reason)
  VALUES (p_model_version, p_owner_id, p_decision, btrim(p_reason)) RETURNING id INTO event_id;
  RETURN jsonb_build_object(
    'event_id', event_id, 'model_version', p_model_version, 'decision', p_decision
  );
END;
$$;

CREATE OR REPLACE FUNCTION public.fn_activate_yolo_model(
  p_owner_id uuid, p_model_version text, p_action text, p_reason text
) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  event_id uuid;
  latest_approval text;
  latest_approval_at timestamptz;
  fixed_passed boolean;
  fixed_recorded_at timestamptz;
  holdout_passed boolean;
  holdout_recorded_at timestamptz;
BEGIN
  IF p_action NOT IN ('activate','rollback') THEN
    RAISE EXCEPTION 'invalid_activation_action' USING ERRCODE = '22023';
  END IF;
  IF char_length(btrim(coalesce(p_reason, ''))) NOT BETWEEN 3 AND 1000 THEN
    RAISE EXCEPTION 'activation_reason_required' USING ERRCODE = '22023';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM public.yolo_model_versions WHERE version = p_model_version) THEN
    RAISE EXCEPTION 'model_version_not_found' USING ERRCODE = 'PT404';
  END IF;
  SELECT passed, recorded_at INTO fixed_passed, fixed_recorded_at
  FROM public.yolo_model_evaluations
  WHERE model_version = p_model_version AND suite = 'fixed_test'
  ORDER BY recorded_at DESC, id DESC LIMIT 1;
  SELECT passed, recorded_at INTO holdout_passed, holdout_recorded_at
  FROM public.yolo_model_evaluations
  WHERE model_version = p_model_version AND suite = 'future_holdout'
  ORDER BY recorded_at DESC, id DESC LIMIT 1;
  IF fixed_passed IS DISTINCT FROM true OR holdout_passed IS DISTINCT FROM true THEN
    RAISE EXCEPTION 'model_evaluations_required' USING ERRCODE = 'PT409';
  END IF;
  SELECT decision, decided_at INTO latest_approval, latest_approval_at
  FROM public.yolo_model_approval_events
  WHERE model_version = p_model_version
  ORDER BY decided_at DESC, id DESC LIMIT 1;
  IF latest_approval IS DISTINCT FROM 'approve'
    OR latest_approval_at < greatest(fixed_recorded_at, holdout_recorded_at) THEN
    RAISE EXCEPTION 'model_owner_approval_required' USING ERRCODE = 'PT409';
  END IF;
  INSERT INTO public.yolo_model_activation_events (model_version, owner_id, action, reason)
  VALUES (p_model_version, p_owner_id, p_action, btrim(p_reason)) RETURNING id INTO event_id;
  RETURN jsonb_build_object(
    'event_id', event_id, 'active_model_version', p_model_version, 'action', p_action
  );
END;
$$;

CREATE OR REPLACE FUNCTION public.fn_get_yolo_owner_overview(p_owner_id uuid)
RETURNS jsonb
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = '' AS $$
  WITH active AS (
    SELECT model_version FROM public.yolo_model_activation_events
    ORDER BY activated_at DESC, id DESC LIMIT 1
  ), reviews AS (
    SELECT jsonb_agg(jsonb_build_object(
      'revision_id', r.id,
      'task_id', t.id,
      'media_kind', t.media_kind,
      'media_ref', t.media_ref,
      'frame_manifest', t.frame_manifest,
      'blind_boxes', s.boxes,
      'blind_no_gecko', s.no_gecko,
      'revision_boxes', r.boxes,
      'revision_no_gecko', r.no_gecko,
      'revision_reason', r.reason,
      'prediction', t.prediction_snapshot
    ) ORDER BY r.created_at, r.id) AS items
    FROM public.yolo_bbox_revisions r
    JOIN public.yolo_bbox_tasks t ON t.id = r.task_id
    JOIN public.yolo_bbox_blind_submissions s ON s.task_id = t.id
    WHERE NOT EXISTS (
      SELECT 1 FROM public.yolo_bbox_owner_decisions d WHERE d.revision_id = r.id
    )
  ), datasets AS (
    SELECT jsonb_agg(jsonb_build_object('id', id, 'version', version) ORDER BY created_at DESC, id DESC) AS items
    FROM public.yolo_dataset_versions v
    WHERE status = 'draft'
      AND NOT EXISTS (SELECT 1 FROM public.yolo_dataset_status_events e WHERE e.dataset_version_id = v.id)
  ), models AS (
    SELECT jsonb_agg(jsonb_build_object(
      'version', m.version,
      'fixed_test_passed', coalesce((
        SELECT e.passed FROM public.yolo_model_evaluations e
        WHERE e.model_version = m.version AND e.suite = 'fixed_test'
        ORDER BY e.recorded_at DESC, e.id DESC LIMIT 1
      ), false),
      'future_holdout_passed', coalesce((
        SELECT e.passed FROM public.yolo_model_evaluations e
        WHERE e.model_version = m.version AND e.suite = 'future_holdout'
        ORDER BY e.recorded_at DESC, e.id DESC LIMIT 1
      ), false),
      'owner_approved', coalesce((
        SELECT a.decision = 'approve'
          AND a.decided_at >= greatest(
            (SELECT e.recorded_at FROM public.yolo_model_evaluations e
             WHERE e.model_version = m.version AND e.suite = 'fixed_test'
             ORDER BY e.recorded_at DESC, e.id DESC LIMIT 1),
            (SELECT e.recorded_at FROM public.yolo_model_evaluations e
             WHERE e.model_version = m.version AND e.suite = 'future_holdout'
             ORDER BY e.recorded_at DESC, e.id DESC LIMIT 1)
          )
        FROM public.yolo_model_approval_events a
        WHERE a.model_version = m.version ORDER BY a.decided_at DESC, a.id DESC LIMIT 1
      ), false),
      'active', m.version = (SELECT model_version FROM active)
    ) ORDER BY m.created_at, m.version) AS items
    FROM public.yolo_model_versions m
  )
  SELECT jsonb_build_object(
    'reviews', coalesce((SELECT items FROM reviews), '[]'::jsonb),
    'datasets', coalesce((SELECT items FROM datasets), '[]'::jsonb),
    'models', coalesce((SELECT items FROM models), '[]'::jsonb),
    'active_model_version', (SELECT model_version FROM active)
  )
  WHERE p_owner_id IS NOT NULL;
$$;

CREATE OR REPLACE VIEW public.yolo_active_model AS
SELECT model_version, action, owner_id, reason, activated_at
FROM public.yolo_model_activation_events
ORDER BY activated_at DESC, id DESC
LIMIT 1;

ALTER TABLE public.yolo_model_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.yolo_model_evaluations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.yolo_model_approval_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.yolo_model_activation_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.yolo_dataset_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.yolo_dataset_status_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.yolo_bbox_tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.yolo_bbox_blind_submissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.yolo_bbox_reveals ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.yolo_bbox_revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.yolo_bbox_owner_decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.yolo_dataset_memberships ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.yolo_model_versions FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.yolo_model_evaluations FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.yolo_model_approval_events FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.yolo_model_activation_events FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.yolo_dataset_versions FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.yolo_dataset_status_events FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.yolo_bbox_tasks FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.yolo_bbox_blind_submissions FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.yolo_bbox_reveals FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.yolo_bbox_revisions FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.yolo_bbox_owner_decisions FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.yolo_dataset_memberships FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.yolo_active_model FROM PUBLIC, anon, authenticated;

GRANT SELECT, INSERT ON TABLE public.yolo_model_versions TO service_role;
GRANT SELECT, INSERT ON TABLE public.yolo_model_evaluations TO service_role;
GRANT SELECT, INSERT ON TABLE public.yolo_model_approval_events TO service_role;
GRANT SELECT, INSERT ON TABLE public.yolo_model_activation_events TO service_role;
GRANT SELECT, INSERT ON TABLE public.yolo_dataset_versions TO service_role;
GRANT SELECT, INSERT ON TABLE public.yolo_dataset_status_events TO service_role;
GRANT SELECT, INSERT ON TABLE public.yolo_bbox_tasks TO service_role;
GRANT SELECT, INSERT ON TABLE public.yolo_bbox_blind_submissions TO service_role;
GRANT SELECT, INSERT ON TABLE public.yolo_bbox_reveals TO service_role;
GRANT SELECT, INSERT ON TABLE public.yolo_bbox_revisions TO service_role;
GRANT SELECT, INSERT ON TABLE public.yolo_bbox_owner_decisions TO service_role;
GRANT SELECT, INSERT ON TABLE public.yolo_dataset_memberships TO service_role;
GRANT SELECT ON TABLE public.yolo_active_model TO service_role;

REVOKE ALL ON FUNCTION public.fn_reject_yolo_history_mutation() FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.fn_validate_yolo_boxes(jsonb, boolean) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.fn_get_yolo_bbox_workspace(uuid) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.fn_submit_yolo_bbox_blind(uuid, uuid, jsonb, boolean) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.fn_reveal_yolo_bbox_prediction(uuid, uuid) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.fn_submit_yolo_bbox_revision(uuid, uuid, jsonb, boolean, text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.fn_owner_decide_yolo_bbox_revision(uuid, uuid, text, text, uuid) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.fn_owner_decide_yolo_model(uuid, text, text, text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.fn_freeze_yolo_dataset(uuid, uuid, text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.fn_activate_yolo_model(uuid, text, text, text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.fn_get_yolo_owner_overview(uuid) FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.fn_get_yolo_bbox_workspace(uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.fn_validate_yolo_boxes(jsonb, boolean) TO service_role;
GRANT EXECUTE ON FUNCTION public.fn_submit_yolo_bbox_blind(uuid, uuid, jsonb, boolean) TO service_role;
GRANT EXECUTE ON FUNCTION public.fn_reveal_yolo_bbox_prediction(uuid, uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.fn_submit_yolo_bbox_revision(uuid, uuid, jsonb, boolean, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.fn_owner_decide_yolo_bbox_revision(uuid, uuid, text, text, uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.fn_owner_decide_yolo_model(uuid, text, text, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.fn_freeze_yolo_dataset(uuid, uuid, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.fn_activate_yolo_model(uuid, text, text, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.fn_get_yolo_owner_overview(uuid) TO service_role;

COMMIT;
