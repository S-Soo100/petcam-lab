-- 봉인 평가 표본에서 항목 제거(owner 전용) — 2026-09-11 owner: "P4 Cam 2(dev) 표본 16건은 개발 중 찍힌 빈 사육장(게코 미관측)이라 무의미, 게코가 찍힌 옛 영상으로 대체".
-- 안전장치: 사람 확정(motion_clip_highlight_verdicts)이 이미 있는 항목은 절대 제거하지 않는다(라벨 붙은 표본은 봉인 유지). 제거된 수를 반환.
-- 등록은 기존 fn_register_eval_sample. 교체 절차·기록은 scripts/replace_eval_sample_stratum.py + experiments/highlight-eval-sample/<id>.json 의 amendments.
BEGIN;

CREATE FUNCTION public.fn_remove_eval_sample_items(p_sample_id text, p_clip_ids uuid[], p_actor uuid, p_is_owner boolean)
RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = '' AS $$
DECLARE
  v_n integer := 0;
BEGIN
  IF NOT coalesce(p_is_owner, false) THEN
    RAISE EXCEPTION 'owner only' USING ERRCODE = 'PT403';
  END IF;
  IF p_sample_id IS NULL OR p_sample_id !~ '^[a-z0-9-]{3,40}$' THEN
    RAISE EXCEPTION 'invalid sample id' USING ERRCODE = '22023';
  END IF;
  IF p_clip_ids IS NULL OR cardinality(p_clip_ids) = 0 THEN
    RAISE EXCEPTION 'clip ids required' USING ERRCODE = '22023';
  END IF;
  -- 사람 확정이 없는 항목만 제거. 확정된 항목은 남긴다(호출자가 반환 수로 알 수 있다).
  WITH del AS (
    DELETE FROM public.motion_clip_eval_samples s
     WHERE s.sample_id = p_sample_id
       AND s.clip_id = ANY (p_clip_ids)
       AND NOT EXISTS (SELECT 1 FROM public.motion_clip_highlight_verdicts v WHERE v.clip_id = s.clip_id)
    RETURNING 1
  )
  SELECT count(*)::integer INTO v_n FROM del;
  RETURN v_n;
END $$;

REVOKE ALL ON FUNCTION public.fn_remove_eval_sample_items(text, uuid[], uuid, boolean) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_remove_eval_sample_items(text, uuid[], uuid, boolean) TO service_role;

COMMIT;
