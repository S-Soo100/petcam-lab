BEGIN;
-- 기존 probe: O→X 뒤 owner O 정정 1, 미관측 X→X 1, pending→O 1.
DO $$
DECLARE report jsonb; r jsonb;
BEGIN
  report := public.fn_highlight_quality_stats(now()-interval '1 hour', now()+interval '1 hour');
  SELECT value INTO r FROM jsonb_array_elements(report->'rows') WHERE value->>'detector_identity' = repeat('a',64);
  IF (r->>'o_to_o')::int IS DISTINCT FROM 1 OR (r->>'o_to_x')::int IS DISTINCT FROM 0 OR (r->>'x_to_x')::int IS DISTINCT FROM 1
    OR (r->>'correction_count')::int IS DISTINCT FROM 1 OR (r->>'reviewed_count')::int IS DISTINCT FROM 2 THEN
    RAISE EXCEPTION 'quality correction/count mismatch: %', r;
  END IF;
  SELECT value INTO r FROM jsonb_array_elements(report->'rows') WHERE value->>'detector_identity' IS NULL;
  IF (r->>'pending_initial')::int IS DISTINCT FROM 1 OR (r->>'reviewed_count')::int IS DISTINCT FROM 1 THEN
    RAISE EXCEPTION 'pending must stay separate: %', r;
  END IF;
  IF report->'shadow_rows' <> '[]'::jsonb THEN RAISE EXCEPTION 'existing O counted as shadow gain'; END IF;
END $$;

-- 원래 X이며 off 트리거가 맞은 clip만 추가 포착으로 세어.
SELECT * FROM public.fn_submit_highlight_verdict('00000000-0000-4000-8000-000000000007',
 '30000000-0000-4000-8000-000000000001',false,true,'initial',null,'gme-shadow-v1','gme-motion-v1',repeat('a',64));
DO $$
DECLARE report jsonb; r jsonb;
BEGIN
  report := public.fn_highlight_quality_stats(now()-interval '1 hour', now()+interval '1 hour');
  IF jsonb_array_length(report->'shadow_rows') IS DISTINCT FROM 2 THEN RAISE EXCEPTION 'two shadow triggers expected'; END IF;
  FOR r IN SELECT value FROM jsonb_array_elements(report->'shadow_rows') LOOP
    IF (r->>'additional_count')::int IS DISTINCT FROM 1 OR (r->>'human_o')::int IS DISTINCT FROM 1 THEN RAISE EXCEPTION 'shadow gain mismatch: %',r; END IF;
  END LOOP;
  IF public.fn_highlight_quality_stats(now()-interval '30 days',now()-interval '29 days') <> '{"rows":[],"shadow_rows":[]}'::jsonb
    THEN RAISE EXCEPTION 'empty window mismatch'; END IF;
  BEGIN
    PERFORM public.fn_highlight_quality_stats(now(),now()-interval '1 hour');
    RAISE EXCEPTION 'invalid window accepted';
  EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
  BEGIN
    PERFORM public.fn_highlight_quality_stats(now()-interval '32 days',now());
    RAISE EXCEPTION 'unbounded window accepted';
  EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
  IF has_function_privilege('anon','public.fn_highlight_quality_stats(timestamptz,timestamptz)','EXECUTE')
     OR has_function_privilege('authenticated','public.fn_highlight_quality_stats(timestamptz,timestamptz)','EXECUTE')
     OR NOT has_function_privilege('service_role','public.fn_highlight_quality_stats(timestamptz,timestamptz)','EXECUTE')
    THEN RAISE EXCEPTION 'quality RPC permissions'; END IF;
END $$;
-- 같은 rule 아래 detector/algorithm/활동일 경계를 따로 집계해.
DO $$
DECLARE n int; cid uuid; jid uuid; rid uuid; report jsonb; r jsonb;
BEGIN
  FOR n IN 10..12 LOOP
    cid := ('00000000-0000-4000-8000-'||lpad(n::text,12,'0'))::uuid;
    jid := gen_random_uuid(); rid := gen_random_uuid();
    INSERT INTO public.motion_clips(id,camera_id,started_at,duration_sec,r2_key)
      VALUES(cid,'40000000-0000-4000-8000-000000000001',
        CASE WHEN n=10 THEN '2000-01-01T21:59:00Z'::timestamptz ELSE '2000-01-01T22:00:00Z'::timestamptz END,60,'probe');
    INSERT INTO public.gme_jobs SELECT (jsonb_populate_record(NULL::public.gme_jobs,to_jsonb(j)||
      jsonb_build_object('id',jid,'clip_id',cid,'detector_identity',repeat('b',64),
        'algorithm_version',CASE WHEN n=12 THEN 'gme-motion-v2' ELSE 'gme-motion-v1' END))).*
      FROM public.gme_jobs j LIMIT 1;
    INSERT INTO public.gme_runs SELECT (jsonb_populate_record(NULL::public.gme_runs,to_jsonb(g)||
      jsonb_build_object('id',rid,'job_id',jid,'clip_id',cid,'detector_identity',repeat('b',64),
        'algorithm_version',CASE WHEN n=12 THEN 'gme-motion-v2' ELSE 'gme-motion-v1' END))).*
      FROM public.gme_runs g WHERE g.clip_id='00000000-0000-4000-8000-000000000001' LIMIT 1;
    INSERT INTO public.motion_clip_highlight_verdicts(id,clip_id,reviewer_id,kind,rule_version,gme_run_id,
      initial_status,initial,initial_reason,verdict,changed,created_at)
      VALUES(gen_random_uuid(),cid,'30000000-0000-4000-8000-000000000001','initial','hl-rule-v0',rid,
        'decided',true,'probe',true,false,now());
  END LOOP;
  report:=public.fn_highlight_quality_stats(now()-interval '1 hour',now()+interval '1 hour');
  IF (SELECT count(*) FROM jsonb_array_elements(report->'rows') WHERE value->>'detector_identity'=repeat('b',64)) <> 3
    THEN RAISE EXCEPTION 'detector/algorithm/day groups merged'; END IF;
  SELECT value INTO r FROM jsonb_array_elements(report->'rows')
    WHERE value->>'detector_identity'=repeat('b',64) AND value->>'activity_day'='2000-01-01';
  IF (r->>'reviewed_count')::int IS DISTINCT FROM 1 THEN RAISE EXCEPTION 'KST 7am boundary lost'; END IF;
  -- 종료시각 뒤의 정정이 과거 보고서를 바꾸면 안 돼.
  INSERT INTO public.motion_clip_highlight_verdicts(id,clip_id,reviewer_id,kind,rule_version,gme_run_id,
    initial_status,initial,initial_reason,verdict,changed,created_at)
    VALUES(gen_random_uuid(),cid,'30000000-0000-4000-8000-000000000002','correction','hl-rule-v1',rid,
      'decided',true,'probe',false,true,now()+interval '2 hours');
  INSERT INTO public.motion_clip_highlight_verdicts(id,clip_id,reviewer_id,kind,rule_version,gme_run_id,
    initial_status,initial,initial_reason,verdict,changed,change_reason,created_at)
    VALUES(gen_random_uuid(),cid,'30000000-0000-4000-8000-000000000002','correction','hl-rule-v1',rid,
      'decided',true,'probe',true,false,'gecko_visible_not_highlight',now()+interval '2 hours 1 minute');
  IF public.fn_highlight_quality_stats(now()-interval '1 hour',now()+interval '1 hour') IS DISTINCT FROM report
    THEN RAISE EXCEPTION 'future correction changed past report'; END IF;
  report:=public.fn_highlight_quality_stats(now()-interval '1 hour',now()+interval '3 hours');
  IF (SELECT sum((value->>'missed_visibility')::int) FROM jsonb_array_elements(report->'rows')) IS DISTINCT FROM 1::bigint
    THEN RAISE EXCEPTION 'incompatible reason inflated visibility miss'; END IF;
END $$;
-- 작은 합성 데이터에서는 seq scan이 싸므로 강제로 인덱스 사용 가능성만 검사해.
-- 이 검사는 production latency 측정이 아니야.
SET LOCAL enable_seqscan = off;
DO $$
DECLARE plan json;
BEGIN
  EXECUTE 'EXPLAIN (FORMAT JSON) SELECT clip_id FROM public.motion_clip_highlight_verdicts
    WHERE kind = ''initial'' AND created_at >= now()-interval ''1 hour'' AND created_at < now()+interval ''1 hour''' INTO plan;
  IF plan::text NOT LIKE '%idx_highlight_verdict_initial_created%' THEN
    RAISE EXCEPTION 'time range index not usable: %',plan;
  END IF;
END $$;
SET LOCAL enable_seqscan = on;
SET LOCAL ROLE service_role;
SELECT public.fn_highlight_quality_stats(now()-interval '1 hour',now()+interval '1 hour') IS NOT NULL;
RESET ROLE;
ROLLBACK;
