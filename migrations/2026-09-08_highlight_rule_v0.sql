BEGIN;

-- 하이라이트 1차 판정은 저장하지 않는다. (active 규칙 params × exact GME run)의 순수 계산이며,
-- 사람이 확정하는 순간에만 그때 보였던 값을 verdict row에 스냅샷한다(스펙 §4.2).

-- 선행 계약: 운영 라벨링 적격 가드(2026-08-06). 확정 RPC 가 test/격리/삭제 clip 을 fail-closed 로 막는 데 쓴다.
DO $$
BEGIN
  IF to_regprocedure('public.fn_is_motion_clip_production_labeling_eligible(uuid)') IS NULL THEN
    RAISE EXCEPTION 'fn_is_motion_clip_production_labeling_eligible prerequisite missing'
      USING ERRCODE = '55000';
  END IF;
END $$;

-- ── 규칙 버전 (append-only) ──────────────────────────────────────────
CREATE TABLE public.highlight_rule_versions (
  version text PRIMARY KEY CHECK (version ~ '^hl-rule-v[0-9]+$'),
  params jsonb NOT NULL,
  note text NOT NULL DEFAULT '',
  created_by uuid REFERENCES auth.users(id) ON DELETE RESTRICT,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CHECK (jsonb_typeof(params->'triggers') = 'array'),
  CHECK (jsonb_typeof(coalesce(params->'guards', '[]'::jsonb)) = 'array')
);
COMMENT ON TABLE public.highlight_rule_versions IS
  '하이라이트 규칙 파라미터 버전. 숫자만 바뀌고 함수 코드는 안 바뀐다(스펙 §4.1a).';

CREATE TABLE public.highlight_rule_activation_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  version text NOT NULL REFERENCES public.highlight_rule_versions(version) ON DELETE RESTRICT,
  actor_id uuid REFERENCES auth.users(id) ON DELETE RESTRICT,
  activated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX idx_highlight_rule_activation_events_latest
  ON public.highlight_rule_activation_events (activated_at DESC, id DESC);

-- ── 사람 확정 (append-only) ──────────────────────────────────────────
CREATE TABLE public.motion_clip_highlight_verdicts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  clip_id uuid NOT NULL REFERENCES public.motion_clips(id) ON DELETE RESTRICT,
  reviewer_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
  kind text NOT NULL CHECK (kind IN ('initial','correction')),
  rule_version text NOT NULL REFERENCES public.highlight_rule_versions(version) ON DELETE RESTRICT,
  gme_run_id uuid REFERENCES public.gme_runs(id) ON DELETE RESTRICT,
  initial_status text NOT NULL CHECK (initial_status IN ('decided','pending','failed')),
  initial boolean,
  initial_reason text NOT NULL,
  verdict boolean NOT NULL,
  changed boolean,
  change_reason text,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CHECK ((initial_status = 'decided' AND initial IS NOT NULL AND gme_run_id IS NOT NULL)
      OR (initial_status IN ('pending','failed') AND initial IS NULL AND gme_run_id IS NULL)),
  CHECK ((initial IS NULL AND changed IS NULL) OR (changed = (initial <> verdict))),
  CHECK (change_reason IS NULL OR change_reason IN ('false_detection','gecko_not_visible','camera_shake','too_short','interesting_low_numbers','other'))
);
COMMENT ON TABLE public.motion_clip_highlight_verdicts IS
  '검수자 최종값. initial 1건만 clip당 허용, owner 정정은 correction append. 최신 row가 현재값.';

CREATE UNIQUE INDEX uq_motion_clip_highlight_verdict_initial
  ON public.motion_clip_highlight_verdicts (clip_id) WHERE kind = 'initial';
CREATE INDEX idx_motion_clip_highlight_verdicts_clip_latest
  ON public.motion_clip_highlight_verdicts (clip_id, created_at DESC, id DESC);
CREATE INDEX idx_motion_clip_highlight_verdicts_rule_created
  ON public.motion_clip_highlight_verdicts (rule_version, created_at DESC);

-- ── append-only trigger + RLS (세 테이블 공통) ───────────────────────
CREATE FUNCTION public.fn_block_highlight_ledger_mutation()
RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
BEGIN
  RAISE EXCEPTION 'highlight ledgers are append-only' USING ERRCODE = '0A000';
END $$;

CREATE TRIGGER trg_highlight_rule_versions_no_update_delete
  BEFORE UPDATE OR DELETE ON public.highlight_rule_versions
  FOR EACH ROW EXECUTE FUNCTION public.fn_block_highlight_ledger_mutation();
CREATE TRIGGER trg_highlight_rule_versions_no_truncate
  BEFORE TRUNCATE ON public.highlight_rule_versions
  FOR EACH STATEMENT EXECUTE FUNCTION public.fn_block_highlight_ledger_mutation();
CREATE TRIGGER trg_highlight_rule_activation_events_no_update_delete
  BEFORE UPDATE OR DELETE ON public.highlight_rule_activation_events
  FOR EACH ROW EXECUTE FUNCTION public.fn_block_highlight_ledger_mutation();
CREATE TRIGGER trg_highlight_rule_activation_events_no_truncate
  BEFORE TRUNCATE ON public.highlight_rule_activation_events
  FOR EACH STATEMENT EXECUTE FUNCTION public.fn_block_highlight_ledger_mutation();
CREATE TRIGGER trg_motion_clip_highlight_verdicts_no_update_delete
  BEFORE UPDATE OR DELETE ON public.motion_clip_highlight_verdicts
  FOR EACH ROW EXECUTE FUNCTION public.fn_block_highlight_ledger_mutation();
CREATE TRIGGER trg_motion_clip_highlight_verdicts_no_truncate
  BEFORE TRUNCATE ON public.motion_clip_highlight_verdicts
  FOR EACH STATEMENT EXECUTE FUNCTION public.fn_block_highlight_ledger_mutation();

ALTER TABLE public.highlight_rule_versions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.highlight_rule_versions FROM PUBLIC, anon, authenticated, service_role;
ALTER TABLE public.highlight_rule_activation_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.highlight_rule_activation_events FROM PUBLIC, anon, authenticated, service_role;
ALTER TABLE public.motion_clip_highlight_verdicts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.motion_clip_highlight_verdicts FROM PUBLIC, anon, authenticated, service_role;

-- ── 순수 계산: run row × params → O/X ────────────────────────────────
-- 트리거는 OR. on=false 트리거는 판정에 안 쓰고 shadow에 이름만 남긴다(스펙 §4.1a 제안 순서).
CREATE FUNCTION public.fn_highlight_rule_eval(p_run public.gme_runs, p_params jsonb)
RETURNS TABLE (initial boolean, reason text, fired text[], shadow text[], features jsonb)
LANGUAGE plpgsql IMMUTABLE SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  v_activity numeric := coalesce(p_run.candidate_moving_sec_any_gecko, 0);
  v_visible numeric := coalesce(p_run.visible_sec, 0);
  v_longest numeric := 0;
  v_bursts integer := 0;
  v_first numeric;
  v_trigger jsonb;
  v_name text;
  v_key text;
  v_on boolean;
  v_hit boolean;
  v_fired text[] := '{}';
  v_shadow text[] := '{}';
BEGIN
  SELECT coalesce(max((i->>'end_sec')::numeric - (i->>'start_sec')::numeric), 0),
         count(*)::integer,
         min((i->>'start_sec')::numeric)
    INTO v_longest, v_bursts, v_first
  FROM jsonb_array_elements(coalesce(p_run.state_intervals, '[]'::jsonb)) i
  WHERE i->>'state' = 'moving';

  features := jsonb_build_object(
    'activity_sec', round(v_activity, 1),
    'longest_moving_sec', round(v_longest, 1),
    'moving_burst_count', v_bursts,
    'first_moving_sec', round(v_first, 1),
    'visible_sec', round(v_visible, 1),
    'duration_sec', p_run.duration_sec
  );

  IF v_visible <= 0 THEN
    initial := false; reason := '게코 미관측'; fired := '{}'; shadow := '{}';
    RETURN NEXT; RETURN;
  END IF;

  FOR v_trigger IN SELECT value FROM jsonb_array_elements(p_params->'triggers') LOOP
    v_name := v_trigger->>'name';
    v_on := coalesce((v_trigger->>'on')::boolean, false);
    -- 모르는 트리거 이름 = fail-closed. 규칙 저장 시에도 같은 검사를 한다.
    IF v_name IS NULL OR v_name NOT IN ('long_activity','sustained_move','frequent_bursts','early_action') THEN
      RAISE EXCEPTION 'unknown highlight trigger: %', v_name USING ERRCODE = '22023';
    END IF;
    -- 필수 숫자 키를 이름으로 명시 검사한다. AND 단락(short-circuit) 때문에 첫 조건이 false 면
    -- 뒤 키가 빠져도 NULL 이 안 나와 통과하던 구멍을 막는다(frequent_bursts 의 bursts_gte).
    FOREACH v_key IN ARRAY CASE v_name
      WHEN 'long_activity' THEN ARRAY['activity_sec_gte']
      WHEN 'sustained_move' THEN ARRAY['longest_sec_gte']
      WHEN 'frequent_bursts' THEN ARRAY['activity_sec_gte', 'bursts_gte']
      WHEN 'early_action' THEN ARRAY['first_move_sec_lte']
    END LOOP
      IF jsonb_typeof(v_trigger->v_key) IS DISTINCT FROM 'number' THEN
        RAISE EXCEPTION 'highlight trigger % requires numeric parameter %', v_name, v_key
          USING ERRCODE = '22023';
      END IF;
    END LOOP;
    v_hit := CASE v_name
      WHEN 'long_activity' THEN v_activity >= (v_trigger->>'activity_sec_gte')::numeric
      WHEN 'sustained_move' THEN v_longest >= (v_trigger->>'longest_sec_gte')::numeric
      WHEN 'frequent_bursts' THEN v_activity >= (v_trigger->>'activity_sec_gte')::numeric
                                AND v_bursts >= (v_trigger->>'bursts_gte')::numeric
      WHEN 'early_action' THEN v_first IS NOT NULL
                                AND v_first <= (v_trigger->>'first_move_sec_lte')::numeric
    END;
    IF v_hit AND v_on THEN v_fired := v_fired || v_name;
    ELSIF v_hit THEN v_shadow := v_shadow || v_name;
    END IF;
  END LOOP;

  initial := cardinality(v_fired) > 0;
  fired := v_fired;
  shadow := v_shadow;
  reason := CASE WHEN initial
    THEN format('움직임 %s초 · 최장 연속 %s초', round(v_activity, 1), round(v_longest, 1))
    ELSE format('짧은 움직임 %s초 · 최장 연속 %s초', round(v_activity, 1), round(v_longest, 1))
  END;
  RETURN NEXT;
END $$;

-- ── active 규칙 = 최신 activation event ───────────────────────────────
CREATE FUNCTION public.fn_get_active_highlight_rule()
RETURNS TABLE (version text, params jsonb, activated_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT v.version, v.params, e.activated_at
  FROM public.highlight_rule_activation_events e
  JOIN public.highlight_rule_versions v ON v.version = e.version
  ORDER BY e.activated_at DESC, e.id DESC
  LIMIT 1
$$;

-- ── 1차 판정 (저장 없음) ────────────────────────────────────────────
CREATE FUNCTION public.fn_highlight_initial(
  p_clip_id uuid,
  p_engine_schema_version text,
  p_algorithm_version text,
  p_detector_identity text
) RETURNS TABLE (
  status text,            -- decided | pending | failed
  initial boolean,
  rule_version text,
  gme_run_id uuid,
  reason text,
  fired text[],
  shadow text[],
  features jsonb
)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = '' AS $$
DECLARE
  v_rule record;
  v_gme record;
  v_run public.gme_runs%ROWTYPE;
  v_eval record;
BEGIN
  SELECT * INTO v_rule FROM public.fn_get_active_highlight_rule();
  IF v_rule.version IS NULL THEN
    RAISE EXCEPTION 'no active highlight rule' USING ERRCODE = 'PT428';
  END IF;

  SELECT * INTO v_gme
  FROM public.fn_get_gme_observed_moving_time_v2(p_clip_id, p_engine_schema_version, p_algorithm_version, p_detector_identity);

  IF v_gme.measurement_status IN ('pending', 'failed') THEN
    status := v_gme.measurement_status; initial := NULL; rule_version := v_rule.version;
    gme_run_id := NULL; fired := '{}'; shadow := '{}'; features := NULL;
    reason := CASE WHEN v_gme.measurement_status = 'pending' THEN '분석 대기' ELSE '분석 실패' END;
    RETURN NEXT; RETURN;
  END IF;

  SELECT r.* INTO v_run FROM public.gme_runs r WHERE r.id = v_gme.run_id;
  SELECT * INTO v_eval FROM public.fn_highlight_rule_eval(v_run, v_rule.params);

  status := 'decided'; initial := v_eval.initial; rule_version := v_rule.version;
  gme_run_id := v_run.id; reason := v_eval.reason; fired := v_eval.fired;
  shadow := v_eval.shadow; features := v_eval.features;
  RETURN NEXT;
END $$;

-- ── 현재값: 사람 확정 있으면 그 값, 없으면 1차 판정 ───────────────────
CREATE FUNCTION public.fn_highlight_current(
  p_clip_id uuid,
  p_engine_schema_version text,
  p_algorithm_version text,
  p_detector_identity text
) RETURNS TABLE (
  source text,            -- human | rule
  status text,            -- decided | pending | failed  (human이면 항상 decided)
  value boolean,
  rule_version text,
  reason text,
  reviewer_id uuid,
  decided_at timestamptz,
  verdict_kind text
)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = '' AS $$
DECLARE
  v_verdict public.motion_clip_highlight_verdicts%ROWTYPE;
  v_initial record;
BEGIN
  SELECT * INTO v_verdict
  FROM public.motion_clip_highlight_verdicts v
  WHERE v.clip_id = p_clip_id
  ORDER BY v.created_at DESC, v.id DESC
  LIMIT 1;

  IF v_verdict.id IS NOT NULL THEN
    source := 'human'; status := 'decided'; value := v_verdict.verdict;
    rule_version := v_verdict.rule_version; reason := v_verdict.initial_reason;
    reviewer_id := v_verdict.reviewer_id; decided_at := v_verdict.created_at;
    verdict_kind := v_verdict.kind;
    RETURN NEXT; RETURN;
  END IF;

  SELECT * INTO v_initial FROM public.fn_highlight_initial(
    p_clip_id, p_engine_schema_version, p_algorithm_version, p_detector_identity);
  source := 'rule'; status := v_initial.status; value := v_initial.initial;
  rule_version := v_initial.rule_version; reason := v_initial.reason;
  reviewer_id := NULL; decided_at := NULL; verdict_kind := NULL;
  RETURN NEXT;
END $$;

-- ── 사람 확정 append ────────────────────────────────────────────────
CREATE FUNCTION public.fn_submit_highlight_verdict(
  p_clip_id uuid,
  p_reviewer_id uuid,
  p_is_owner boolean,
  p_verdict boolean,
  p_kind text,
  p_change_reason text,
  p_engine_schema_version text,
  p_algorithm_version text,
  p_detector_identity text
) RETURNS TABLE (verdict_id uuid, initial boolean, changed boolean, rule_version text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
  v_initial record;
  v_id uuid := gen_random_uuid();
  v_changed boolean;
BEGIN
  IF p_clip_id IS NULL OR p_reviewer_id IS NULL OR p_verdict IS NULL OR p_kind IS NULL THEN
    RAISE EXCEPTION 'required parameter is missing' USING ERRCODE = '22023';
  END IF;
  IF p_kind NOT IN ('initial', 'correction') THEN
    RAISE EXCEPTION 'invalid verdict kind' USING ERRCODE = '22023';
  END IF;
  IF p_change_reason IS NOT NULL AND p_change_reason NOT IN
     ('false_detection','gecko_not_visible','camera_shake','too_short','interesting_low_numbers','other') THEN
    RAISE EXCEPTION 'invalid change reason' USING ERRCODE = '22023';
  END IF;
  -- 운영 적격(production 목적 + canonical R2 경로 + 격리/삭제 아님)만 확정 가능.
  -- 미존재·비적격 모두 같은 P0002 로 접어 존재 여부를 새지 않게 한다.
  IF NOT public.fn_is_motion_clip_production_labeling_eligible(p_clip_id) THEN
    RAISE EXCEPTION 'motion clip not found' USING ERRCODE = 'P0002';
  END IF;
  -- 승인 라벨러 또는 owner만. 배정 카메라와 무관하게 누구나 확정 가능(v4 스펙 §4.1).
  IF NOT p_is_owner AND NOT EXISTS (
    SELECT 1 FROM public.labelers l WHERE l.user_id = p_reviewer_id
  ) THEN
    RAISE EXCEPTION 'reviewer is not an approved labeler' USING ERRCODE = 'PT403';
  END IF;
  IF p_kind = 'correction' AND NOT p_is_owner THEN
    RAISE EXCEPTION 'only owner can append a correction' USING ERRCODE = 'PT403';
  END IF;
  IF p_kind = 'correction' AND NOT EXISTS (
    SELECT 1 FROM public.motion_clip_highlight_verdicts v WHERE v.clip_id = p_clip_id AND v.kind = 'initial'
  ) THEN
    RAISE EXCEPTION 'nothing to correct' USING ERRCODE = 'P0002';
  END IF;

  SELECT * INTO v_initial FROM public.fn_highlight_initial(
    p_clip_id, p_engine_schema_version, p_algorithm_version, p_detector_identity);
  v_changed := CASE WHEN v_initial.initial IS NULL THEN NULL ELSE v_initial.initial <> p_verdict END;

  BEGIN
    INSERT INTO public.motion_clip_highlight_verdicts (
      id, clip_id, reviewer_id, kind, rule_version, gme_run_id, initial_status,
      initial, initial_reason, verdict, changed, change_reason
    ) VALUES (
      v_id, p_clip_id, p_reviewer_id, p_kind, v_initial.rule_version, v_initial.gme_run_id,
      v_initial.status, v_initial.initial, v_initial.reason, p_verdict, v_changed, p_change_reason
    );
  EXCEPTION WHEN unique_violation THEN
    -- 먼저 저장한 사람이 이긴다(v4 스펙 §4.2). 호출자는 "방금 확정됐어"로 안내한다.
    RAISE EXCEPTION 'clip already has an initial verdict' USING ERRCODE = 'PT409';
  END;

  verdict_id := v_id; initial := v_initial.initial; changed := v_changed;
  rule_version := v_initial.rule_version;
  RETURN NEXT;
END $$;

-- ── 규칙 버전 생성 + 활성화 (owner) ────────────────────────────────
CREATE FUNCTION public.fn_create_highlight_rule_version(
  p_version text,
  p_params jsonb,
  p_note text,
  p_actor_id uuid
) RETURNS TABLE (version text, activated_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
  v_probe public.gme_runs%ROWTYPE;
  v_dummy record;
  v_event_id uuid := gen_random_uuid();
BEGIN
  IF p_version IS NULL OR p_params IS NULL OR p_actor_id IS NULL THEN
    RAISE EXCEPTION 'required parameter is missing' USING ERRCODE = '22023';
  END IF;
  -- params 유효성은 eval을 합성 run에 한 번 돌려 확인한다(모르는 트리거·빠진 숫자 = 22023).
  v_probe.candidate_moving_sec_any_gecko := 1; v_probe.visible_sec := 1; v_probe.duration_sec := 60;
  v_probe.state_intervals := '[{"state":"moving","start_sec":0,"end_sec":1}]'::jsonb;
  SELECT * INTO v_dummy FROM public.fn_highlight_rule_eval(v_probe, p_params);

  INSERT INTO public.highlight_rule_versions (version, params, note, created_by)
  VALUES (p_version, p_params, coalesce(p_note, ''), p_actor_id);
  INSERT INTO public.highlight_rule_activation_events (id, version, actor_id)
  VALUES (v_event_id, p_version, p_actor_id);

  RETURN QUERY SELECT e.version, e.activated_at
  FROM public.highlight_rule_activation_events e WHERE e.id = v_event_id;
END $$;

-- ── 기존 버전 재활성화 (owner) — 잘못된 새 버전에서 검증된 버전으로 되돌릴 때 ────
CREATE FUNCTION public.fn_activate_highlight_rule_version(
  p_version text,
  p_actor_id uuid
) RETURNS TABLE (version text, activated_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
  v_event_id uuid := gen_random_uuid();
BEGIN
  IF p_version IS NULL OR p_actor_id IS NULL THEN
    RAISE EXCEPTION 'required parameter is missing' USING ERRCODE = '22023';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM public.highlight_rule_versions v WHERE v.version = p_version) THEN
    RAISE EXCEPTION 'unknown highlight rule version' USING ERRCODE = 'P0002';
  END IF;
  INSERT INTO public.highlight_rule_activation_events (id, version, actor_id)
  VALUES (v_event_id, p_version, p_actor_id);
  RETURN QUERY SELECT e.version, e.activated_at
  FROM public.highlight_rule_activation_events e WHERE e.id = v_event_id;
END $$;

-- ── 집계: 규칙 버전 × 카메라 유지율 (owner) ────────────────────────
CREATE FUNCTION public.fn_highlight_rule_stats(p_from timestamptz, p_to timestamptz)
RETURNS TABLE (
  rule_version text,
  camera_id uuid,
  camera_name text,
  verdict_count bigint,
  kept_count bigint,
  decided_count bigint,   -- 1차 판정이 있었던 확정 수(유지율 분모). pending/failed 확정은 제외.
  o_to_x bigint,
  x_to_o bigint,
  pending_initial bigint,
  reason_counts jsonb
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT
    v.rule_version,
    c.camera_id,
    cam.name,
    count(*)::bigint,
    count(*) FILTER (WHERE v.changed = false)::bigint,
    count(*) FILTER (WHERE v.initial IS NOT NULL)::bigint,
    count(*) FILTER (WHERE v.initial = true AND v.verdict = false)::bigint,
    count(*) FILTER (WHERE v.initial = false AND v.verdict = true)::bigint,
    count(*) FILTER (WHERE v.initial IS NULL)::bigint,
    coalesce((
      SELECT jsonb_object_agg(r.change_reason, r.n)
      FROM (
        SELECT v2.change_reason, count(*) AS n
        FROM public.motion_clip_highlight_verdicts v2
        JOIN public.motion_clips c2 ON c2.id = v2.clip_id
        WHERE v2.rule_version = v.rule_version AND c2.camera_id = c.camera_id
          AND v2.kind = 'initial' AND v2.change_reason IS NOT NULL
          AND v2.created_at >= p_from AND v2.created_at < p_to
        GROUP BY v2.change_reason
      ) r
    ), '{}'::jsonb)
  FROM public.motion_clip_highlight_verdicts v
  JOIN public.motion_clips c ON c.id = v.clip_id
  LEFT JOIN public.cameras cam ON cam.id = c.camera_id
  WHERE v.kind = 'initial' AND v.created_at >= p_from AND v.created_at < p_to
  GROUP BY v.rule_version, c.camera_id, cam.name
  ORDER BY v.rule_version DESC, cam.name NULLS LAST
$$;

-- ── 권한 ──────────────────────────────────────────────────────────
REVOKE ALL ON FUNCTION public.fn_highlight_rule_eval(public.gme_runs, jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_highlight_rule_eval(public.gme_runs, jsonb) TO service_role;
REVOKE ALL ON FUNCTION public.fn_get_active_highlight_rule() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_get_active_highlight_rule() TO service_role;
REVOKE ALL ON FUNCTION public.fn_highlight_initial(uuid, text, text, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_highlight_initial(uuid, text, text, text) TO service_role;
REVOKE ALL ON FUNCTION public.fn_highlight_current(uuid, text, text, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_highlight_current(uuid, text, text, text) TO service_role;
REVOKE ALL ON FUNCTION public.fn_submit_highlight_verdict(uuid, uuid, boolean, boolean, text, text, text, text, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_submit_highlight_verdict(uuid, uuid, boolean, boolean, text, text, text, text, text) TO service_role;
REVOKE ALL ON FUNCTION public.fn_create_highlight_rule_version(text, jsonb, text, uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_create_highlight_rule_version(text, jsonb, text, uuid) TO service_role;
REVOKE ALL ON FUNCTION public.fn_activate_highlight_rule_version(text, uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_activate_highlight_rule_version(text, uuid) TO service_role;
REVOKE ALL ON FUNCTION public.fn_highlight_rule_stats(timestamptz, timestamptz) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_highlight_rule_stats(timestamptz, timestamptz) TO service_role;

-- ── seed: v0 (owner 승인 2026-09-07) ─────────────────────────────────
INSERT INTO public.highlight_rule_versions (version, params, note, created_by) VALUES (
  'hl-rule-v0',
  '{"triggers": [
      {"name": "long_activity", "on": true, "activity_sec_gte": 10},
      {"name": "sustained_move", "on": true, "longest_sec_gte": 5},
      {"name": "frequent_bursts", "on": false, "activity_sec_gte": 3, "bursts_gte": 8},
      {"name": "early_action", "on": false, "first_move_sec_lte": 2}
    ], "guards": []}'::jsonb,
  'owner 승인 2026-09-07. long_activity 10s OR sustained_move 5s. 나머지 두 트리거는 shadow.',
  NULL
);
INSERT INTO public.highlight_rule_activation_events (version, actor_id) VALUES ('hl-rule-v0', NULL);

COMMIT;
