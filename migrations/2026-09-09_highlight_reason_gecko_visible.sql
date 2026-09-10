-- 하이라이트 사유 enum 확장: gecko_visible_not_highlight (UX ⑥, owner 결정 2026-09-08 "남은 추천 자동 진행").
-- 1차 판정이 "게코 미관측" X 인데 사람이 "게코 보여 · 하이라이트 아님 X" 를 고르면 판정은 그대로 X 라 changed=false 지만,
-- "GME 가 게코를 놓쳤다"는 검출기 연구용 신호를 사유로 남긴다(런북 §3: 규칙 튜닝 근거 아님, 검출기 누락 추적용).
-- 런북 §4.2 네 곳: ① CHECK ② fn_submit 검증 ③ fn_highlight_rule_stats FILTER ④ highlightV4.ts 라벨.
BEGIN;

-- ① CHECK 교체 (인라인 CHECK 자동 이름에 의존하지 않고 컬럼 기준으로 찾는다)
DO $$
DECLARE c text;
BEGIN
  FOR c IN
    SELECT conname FROM pg_constraint
     WHERE conrelid = 'public.motion_clip_highlight_verdicts'::regclass
       AND contype = 'c'
       AND pg_get_constraintdef(oid) LIKE '%change_reason%'
  LOOP
    EXECUTE format('ALTER TABLE public.motion_clip_highlight_verdicts DROP CONSTRAINT %I', c);
  END LOOP;
END $$;
ALTER TABLE public.motion_clip_highlight_verdicts
  ADD CONSTRAINT motion_clip_highlight_verdicts_change_reason_check
  CHECK (change_reason IS NULL OR change_reason IN
    ('false_detection','gecko_not_visible','camera_shake','too_short','interesting_low_numbers','gecko_visible_not_highlight','other'));

-- ② fn_submit_highlight_verdict — 검증 목록만 바뀐다(나머지 본문 동일).
CREATE OR REPLACE FUNCTION public.fn_submit_highlight_verdict(
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
     ('false_detection','gecko_not_visible','camera_shake','too_short','interesting_low_numbers','gecko_visible_not_highlight','other') THEN
    RAISE EXCEPTION 'invalid change reason' USING ERRCODE = '22023';
  END IF;
  IF NOT public.fn_is_motion_clip_production_labeling_eligible(p_clip_id) THEN
    RAISE EXCEPTION 'motion clip not found' USING ERRCODE = 'P0002';
  END IF;
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
    RAISE EXCEPTION 'clip already has an initial verdict' USING ERRCODE = 'PT409';
  END;

  verdict_id := v_id; initial := v_initial.initial; changed := v_changed;
  rule_version := v_initial.rule_version;
  RETURN NEXT;
END $$;

-- ③ fn_highlight_rule_stats — reason_counts 에 키 추가(나머지 동일).
CREATE OR REPLACE FUNCTION public.fn_highlight_rule_stats(p_from timestamptz, p_to timestamptz)
RETURNS TABLE (
  rule_version text,
  camera_id uuid,
  camera_name text,
  verdict_count bigint,
  kept_count bigint,
  decided_count bigint,
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
    jsonb_strip_nulls(jsonb_build_object(
      'false_detection',             nullif(count(*) FILTER (WHERE v.change_reason = 'false_detection'), 0),
      'gecko_not_visible',           nullif(count(*) FILTER (WHERE v.change_reason = 'gecko_not_visible'), 0),
      'camera_shake',                nullif(count(*) FILTER (WHERE v.change_reason = 'camera_shake'), 0),
      'too_short',                   nullif(count(*) FILTER (WHERE v.change_reason = 'too_short'), 0),
      'interesting_low_numbers',     nullif(count(*) FILTER (WHERE v.change_reason = 'interesting_low_numbers'), 0),
      'gecko_visible_not_highlight', nullif(count(*) FILTER (WHERE v.change_reason = 'gecko_visible_not_highlight'), 0),
      'other',                       nullif(count(*) FILTER (WHERE v.change_reason = 'other'), 0)
    ))
  FROM public.motion_clip_highlight_verdicts v
  JOIN public.motion_clips c ON c.id = v.clip_id
  LEFT JOIN public.cameras cam ON cam.id = c.camera_id
  WHERE v.kind = 'initial' AND v.created_at >= p_from AND v.created_at < p_to
  GROUP BY v.rule_version, c.camera_id, cam.name
  ORDER BY v.rule_version DESC, cam.name NULLS LAST
$$;

COMMIT;
