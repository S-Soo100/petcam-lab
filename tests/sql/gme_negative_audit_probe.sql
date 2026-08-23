-- GME negative-audit migration runtime probe. Runner가 Task 1 producer manifest를 정확히 한 번 주입한다.
BEGIN;

CREATE TEMP TABLE probe_manifest (payload jsonb NOT NULL);
INSERT INTO probe_manifest(payload) VALUES (__GME_NEGATIVE_AUDIT_MANIFEST__::jsonb);

CREATE FUNCTION pg_temp.probe_assert(p_condition boolean, p_message text)
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  IF p_condition IS NOT TRUE THEN
    RAISE EXCEPTION 'probe_assertion_failed: %', p_message;
  END IF;
END;
$$;

CREATE FUNCTION pg_temp.expect_error(p_sql text, p_state text, p_message text DEFAULT NULL)
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  BEGIN
    EXECUTE p_sql;
  EXCEPTION WHEN OTHERS THEN
    IF SQLSTATE <> p_state OR (p_message IS NOT NULL AND SQLERRM <> p_message) THEN
      RAISE EXCEPTION 'unexpected_error: expected=%/% actual=%/% sql=%',
        p_state, p_message, SQLSTATE, SQLERRM, p_sql;
    END IF;
    RETURN;
  END;
  RAISE EXCEPTION 'expected_error_not_raised: %', p_sql;
END;
$$;

CREATE FUNCTION pg_temp.resign_manifest(p_payload jsonb)
RETURNS jsonb LANGUAGE sql AS $$
  SELECT (p_payload - 'manifest_sha256') || jsonb_build_object(
    'manifest_sha256',
    encode(sha256(convert_to(
      public.fn_gme_negative_audit_canonical_json(p_payload - 'manifest_sha256'), 'UTF8'
    )), 'hex')
  );
$$;

-- Runner는 이 구간을 그대로 추출해 두 연결의 실제 table-lock 경합에도 재사용한다.
-- GME_NEGATIVE_FIXTURE_BEGIN
INSERT INTO auth.users(id) VALUES
  ('00000000-0000-4000-8000-000000000001'),
  ('00000000-0000-4000-8000-000000000002'),
  ('00000000-0000-4000-8000-000000000003');

INSERT INTO public.motion_clips(id, started_at, duration_sec, r2_key)
SELECT
  (item ->> 'clip_id')::uuid,
  (item ->> 'started_at')::timestamptz,
  (item ->> 'duration_sec')::double precision,
  'probe/' || (item ->> 'clip_id') || '.mp4'
FROM probe_manifest, jsonb_array_elements(payload -> 'items') AS item;

INSERT INTO public.gme_jobs(id, clip_id, status, completed_at)
SELECT
  md5((item ->> 'clip_id') || ':job')::uuid,
  (item ->> 'clip_id')::uuid,
  'succeeded',
  (item ->> 'started_at')::timestamptz + interval '1 minute'
FROM probe_manifest, jsonb_array_elements(payload -> 'items') AS item;

INSERT INTO public.gme_runs(
  id, clip_id, job_id, detector_identity, status,
  candidate_moving_sec_any_gecko, visible_sec, max_simultaneous_geckos, state_intervals
)
SELECT
  (item ->> 'gme_run_id')::uuid,
  (item ->> 'clip_id')::uuid,
  md5((item ->> 'clip_id') || ':job')::uuid,
  item ->> 'detector_identity',
  'ok',
  CASE WHEN (item ->> 'gme_detected')::boolean THEN 1 ELSE 0 END,
  CASE WHEN (item ->> 'gme_detected')::boolean THEN 1 ELSE 0 END,
  CASE WHEN (item ->> 'gme_detected')::boolean THEN 1 ELSE 0 END,
  '[]'::jsonb
FROM probe_manifest, jsonb_array_elements(payload -> 'items') AS item;

UPDATE public.gme_jobs job
SET result_run_id = (item ->> 'gme_run_id')::uuid
FROM probe_manifest, jsonb_array_elements(payload -> 'items') AS item
WHERE job.clip_id = (item ->> 'clip_id')::uuid;

INSERT INTO public.motion_clip_consensus(clip_id, status, final_decision, final_gt)
SELECT
  (item ->> 'clip_id')::uuid,
  'agreed',
  'label',
  '{"label":"게코-control","visibility":"visible"}'::jsonb
FROM probe_manifest, jsonb_array_elements(payload -> 'items') AS item
WHERE item ->> 'stratum' = 'positive_control';
-- GME_NEGATIVE_FIXTURE_END

-- 실제 parse/apply 결과: 7개 ledger, RLS, 0 policy, service-role insert/select, invoker RPC.
SELECT pg_temp.probe_assert(
  (SELECT count(*) = 7
   FROM pg_class relation
   JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
   WHERE namespace.nspname = 'public' AND relation.relkind = 'r'
     AND relation.relname IN (
       'gme_negative_audit_batches','gme_negative_audit_batch_events',
       'gme_negative_audit_items','gme_negative_audit_submissions',
       'gme_negative_audit_corrections','gme_negative_audit_adjudications',
       'gme_negative_audit_dataset_decisions'
     ) AND relation.relrowsecurity),
  'seven RLS ledgers missing'
);
SELECT pg_temp.probe_assert(
  (SELECT count(*) = 0 FROM pg_policies WHERE schemaname = 'public'
    AND tablename LIKE 'gme_negative_audit_%'),
  'blind ledgers must expose zero policies'
);
SELECT pg_temp.probe_assert(
  NOT EXISTS (
    SELECT 1
    FROM (VALUES
      ('gme_negative_audit_batches'),('gme_negative_audit_batch_events'),
      ('gme_negative_audit_items'),('gme_negative_audit_submissions'),
      ('gme_negative_audit_corrections'),('gme_negative_audit_adjudications'),
      ('gme_negative_audit_dataset_decisions')
    ) AS ledger(table_name)
    LEFT JOIN information_schema.role_table_grants grant_row
      ON grant_row.table_schema = 'public'
     AND grant_row.table_name = ledger.table_name
     AND grant_row.grantee = 'service_role'
    GROUP BY ledger.table_name
    HAVING count(*) FILTER (WHERE grant_row.privilege_type = 'SELECT') <> 1
        OR count(*) FILTER (WHERE grant_row.privilege_type = 'INSERT') <> 1
        OR count(*) FILTER (
             WHERE grant_row.privilege_type NOT IN ('SELECT','INSERT')
           ) <> 0
  ),
  'service_role ledger grants are not insert/select only'
);
SELECT pg_temp.probe_assert(
  (WITH rpc AS (
    SELECT procedure.oid, procedure.proacl
    FROM pg_proc procedure
    JOIN pg_namespace namespace ON namespace.oid = procedure.pronamespace
    WHERE namespace.nspname = 'public' AND procedure.proname IN (
      'fn_create_gme_negative_audit_batch','fn_list_gme_negative_audit_queue',
      'fn_get_gme_negative_audit_item','fn_submit_gme_negative_audit',
      'fn_append_gme_negative_audit_correction',
      'fn_append_gme_negative_audit_adjudication',
      'fn_append_gme_negative_audit_dataset_decision'
    )
  )
  SELECT count(*) = 7
     AND bool_and(has_function_privilege('service_role', oid, 'EXECUTE'))
     AND bool_and(NOT has_function_privilege('anon', oid, 'EXECUTE'))
     AND bool_and(NOT has_function_privilege('authenticated', oid, 'EXECUTE'))
     AND NOT EXISTS (
       SELECT 1 FROM rpc, LATERAL aclexplode(rpc.proacl) acl
       WHERE acl.grantee = 0 AND acl.privilege_type = 'EXECUTE'
     )
  FROM rpc),
  'runtime RPC execute ACL mismatch'
);
SELECT pg_temp.probe_assert(
  NOT EXISTS (
    SELECT 1 FROM pg_proc procedure
    JOIN pg_namespace namespace ON namespace.oid = procedure.pronamespace
    WHERE namespace.nspname = 'public'
      AND procedure.proname LIKE 'fn_%gme_negative_audit%'
      AND (procedure.prosecdef OR NOT ('search_path=""' = ANY(procedure.proconfig)))
  ),
  'audit functions must be invoker with empty search_path'
);

-- Malformed imports must reject atomically; re-signing forces validation past the outer hash gate.
SELECT pg_temp.expect_error(
  format('SELECT * FROM public.fn_create_gme_negative_audit_batch(%L::uuid,%L::jsonb)',
    '00000000-0000-4000-8000-000000000001',
    (SELECT payload || jsonb_build_object('manifest_sha256', repeat('0',64)) FROM probe_manifest)::text),
  '22023', 'manifest_sha256_mismatch'
);
SELECT pg_temp.expect_error(
  format('SELECT * FROM public.fn_create_gme_negative_audit_batch(%L::uuid,%L::jsonb)',
    '00000000-0000-4000-8000-000000000001',
    (SELECT pg_temp.resign_manifest(jsonb_set(payload,'{items,0,duration_sec}','60'::jsonb))
     FROM probe_manifest)::text),
  '22023', 'invalid_manifest_item_identity'
);
SELECT pg_temp.expect_error(
  format('SELECT * FROM public.fn_create_gme_negative_audit_batch(%L::uuid,%L::jsonb)',
    '00000000-0000-4000-8000-000000000001',
    (SELECT pg_temp.resign_manifest(jsonb_set(
       payload,'{items,0,started_at}',to_jsonb('2026-08-20T00:00:00+00:00'::text)))
     FROM probe_manifest)::text),
  '22023', 'invalid_manifest_item_identity'
);
SELECT pg_temp.expect_error(
  format('SELECT * FROM public.fn_create_gme_negative_audit_batch(%L::uuid,%L::jsonb)',
    '00000000-0000-4000-8000-000000000001',
    (SELECT pg_temp.resign_manifest(jsonb_set(
       payload,'{cutoff}',to_jsonb('2026-08-21T00:00:00Z'::text))) FROM probe_manifest)::text),
  '22023', 'item_before_training_cutoff'
);
SELECT pg_temp.expect_error(
  format('SELECT * FROM public.fn_create_gme_negative_audit_batch(%L::uuid,%L::jsonb)',
    '00000000-0000-4000-8000-000000000001',
    (SELECT pg_temp.resign_manifest(jsonb_set(
       payload,'{items,0,selection_provenance}',to_jsonb(repeat('0',64))))
     FROM probe_manifest)::text),
  '22023', 'selection_provenance_mismatch'
);
SELECT pg_temp.expect_error(
  format('SELECT * FROM public.fn_create_gme_negative_audit_batch(%L::uuid,%L::jsonb)',
    '00000000-0000-4000-8000-000000000001',
    (SELECT pg_temp.resign_manifest(jsonb_set(
       payload,'{selection_sha256}',to_jsonb(repeat('0',64)))) FROM probe_manifest)::text),
  '22023', 'selection_sha256_mismatch'
);
SELECT pg_temp.probe_assert(
  (SELECT count(*) FROM public.gme_negative_audit_batches) = 0
  AND (SELECT count(*) FROM public.gme_negative_audit_items) = 0,
  'malformed import left partial rows'
);

CREATE TEMP TABLE probe_state(batch_id uuid, primary_item uuid, control_item uuid);
INSERT INTO probe_state(batch_id)
SELECT batch_id FROM public.fn_create_gme_negative_audit_batch(
  '00000000-0000-4000-8000-000000000001',
  (SELECT payload FROM probe_manifest)
);
UPDATE probe_state SET
  primary_item = (SELECT id FROM public.gme_negative_audit_items
                  WHERE batch_id = probe_state.batch_id AND stratum = 'random_negative'
                  ORDER BY ordinal LIMIT 1),
  control_item = (SELECT id FROM public.gme_negative_audit_items
                  WHERE batch_id = probe_state.batch_id AND stratum = 'positive_control'
                  ORDER BY ordinal LIMIT 1);

SELECT pg_temp.probe_assert(
  (SELECT count(*) FROM public.gme_negative_audit_batches) = 1
  AND (SELECT count(*) FROM public.gme_negative_audit_items) = 6
  AND (SELECT count(*) FROM public.gme_negative_audit_items WHERE stratum='random_negative') = 4
  AND (SELECT count(*) FROM public.gme_negative_audit_items WHERE stratum='positive_control') = 2
  AND (SELECT count(*) FROM public.gme_negative_audit_batch_events WHERE event_type='prepared') = 1,
  'preview import did not create exact 4+2 ledger'
);
SELECT pg_temp.probe_assert(
  public.fn_gme_negative_audit_ledger_digest(ARRAY[
    '11111111-1111-4111-8111-111111111111',
    '22222222-2222-4222-8222-222222222222',
    '게코 있음','null','{"x":0.1}'
  ]) = 'b691aa204934cc304b2863d54a50ffd870973343c8ff7ffe1d9dacdb27622611',
  'shared UTF8 digest fixture mismatch'
);

-- A directly inserted batch cannot start at opened: first event must be prepared.
INSERT INTO public.gme_negative_audit_batches(
  id,owner_id,schema_version,batch_kind,test_sheet_sha256,manifest_sha256,seed,cutoff,
  detector_identity,checkpoint_sha256,negative_pool_sha256,control_pool_sha256,
  selection_sha256,protected_manifest_sha256,expected_negative_count,expected_control_count,
  expected_total_count,candidate_negative_count,candidate_control_count
)
SELECT
  '30000000-0000-4000-8000-000000000001', owner_id, schema_version, batch_kind,
  test_sheet_sha256, repeat('d',64), seed || '-transition', cutoff, detector_identity,
  checkpoint_sha256, negative_pool_sha256, control_pool_sha256, selection_sha256,
  protected_manifest_sha256, expected_negative_count, expected_control_count,
  expected_total_count, candidate_negative_count, candidate_control_count
FROM public.gme_negative_audit_batches WHERE id = (SELECT batch_id FROM probe_state);
SELECT pg_temp.expect_error(
  $$INSERT INTO public.gme_negative_audit_batch_events(batch_id,event_type,actor_id,digest)
    VALUES ('30000000-0000-4000-8000-000000000001','opened',
      '00000000-0000-4000-8000-000000000001',repeat('e',64))$$,
  '22023', 'invalid_batch_event_transition'
);
INSERT INTO public.gme_negative_audit_batch_events(id,batch_id,event_type,actor_id,digest) VALUES
  ('31000000-0000-4000-8000-000000000001','30000000-0000-4000-8000-000000000001','prepared',
   '00000000-0000-4000-8000-000000000001',
   public.fn_gme_negative_audit_ledger_digest(ARRAY[
     '31000000-0000-4000-8000-000000000001','30000000-0000-4000-8000-000000000001',
     'prepared','00000000-0000-4000-8000-000000000001','null'
   ])),
  ('31000000-0000-4000-8000-000000000002','30000000-0000-4000-8000-000000000001','opened',
   '00000000-0000-4000-8000-000000000001',
   public.fn_gme_negative_audit_ledger_digest(ARRAY[
     '31000000-0000-4000-8000-000000000002','30000000-0000-4000-8000-000000000001',
     'opened','00000000-0000-4000-8000-000000000001','null'
   ]));

-- Imported batch opens only through the append-only transition ledger.
INSERT INTO public.gme_negative_audit_batch_events(id,batch_id,event_type,actor_id,digest)
SELECT '31000000-0000-4000-8000-000000000003', batch_id, 'opened',
       '00000000-0000-4000-8000-000000000001',
       public.fn_gme_negative_audit_ledger_digest(ARRAY[
         '31000000-0000-4000-8000-000000000003',batch_id::text,'opened',
         '00000000-0000-4000-8000-000000000001','null'
       ])
FROM probe_state;

-- Runtime projection checks: actual returned JSON keys form the public allowlist.
SELECT pg_temp.probe_assert(
  (SELECT array_agg(key ORDER BY key) = ARRAY[
      'captured_at','completed','duration_sec','item_id','media_ready','ordinal','submitted','total'
    ]
   FROM jsonb_object_keys(to_jsonb((
     SELECT q FROM public.fn_list_gme_negative_audit_queue(
       '00000000-0000-4000-8000-000000000001') q LIMIT 1
   ))) key),
  'queue projection leaked or omitted fields'
);
SELECT pg_temp.probe_assert(
  (SELECT array_agg(key ORDER BY key) = ARRAY[
      'captured_at','duration_sec','effective_bbox','effective_representative_sec',
      'effective_verdict','initial_bbox','initial_representative_sec','initial_verdict',
      'item_id','media_ready','ordinal'
    ]
   FROM jsonb_object_keys(to_jsonb((
     SELECT detail FROM public.fn_get_gme_negative_audit_item(
       (SELECT primary_item FROM probe_state),
       '00000000-0000-4000-8000-000000000001') detail
   ))) key),
  'detail projection leaked or omitted fields'
);
SELECT pg_temp.probe_assert(
  (SELECT count(*) FROM public.fn_list_gme_negative_audit_queue(
    '00000000-0000-4000-8000-000000000003')) = 0
  AND (SELECT count(*) FROM public.fn_get_gme_negative_audit_item(
    (SELECT primary_item FROM probe_state),'00000000-0000-4000-8000-000000000003')) = 0,
  'wrong reviewer enumerated queue/detail'
);
SELECT pg_temp.expect_error(
  format('SELECT * FROM public.fn_submit_gme_negative_audit(%L::uuid,%L::uuid,%L,NULL,NULL)',
    (SELECT primary_item FROM probe_state), '00000000-0000-4000-8000-000000000003','gecko_absent'),
  'PT403', 'not_assigned'
);
SELECT pg_temp.expect_error(
  $$SELECT * FROM public.fn_submit_gme_negative_audit(
    'ffffffff-ffff-4fff-8fff-ffffffffffff','00000000-0000-4000-8000-000000000003',
    'gecko_absent',NULL,NULL)$$,
  'PT403', 'not_assigned'
);

-- Strict present geometry rejects before writing, then accepts one valid exact box.
SELECT pg_temp.expect_error(
  format('SELECT * FROM public.fn_submit_gme_negative_audit(%L::uuid,%L::uuid,%L,0,%L::jsonb)',
    (SELECT primary_item FROM probe_state), '00000000-0000-4000-8000-000000000001',
    'gecko_present', '{"x":0.1,"y":0.2,"width":0.3,"height":0.4,"extra":1}'),
  '22023', 'bbox_must_have_exact_numeric_keys'
);
SELECT pg_temp.probe_assert(
  (SELECT count(*) FROM public.gme_negative_audit_submissions) = 0,
  'invalid bbox wrote a partial submission'
);
SELECT * FROM public.fn_submit_gme_negative_audit(
  (SELECT primary_item FROM probe_state),
  '00000000-0000-4000-8000-000000000001',
  'gecko_present', 0.0000001,
  '{"x":0.1,"y":0.2,"width":0.3,"height":0.4}'::jsonb
);
SELECT pg_temp.expect_error(
  format('SELECT * FROM public.fn_submit_gme_negative_audit(%L::uuid,%L::uuid,%L,NULL,NULL)',
    (SELECT primary_item FROM probe_state), '00000000-0000-4000-8000-000000000001','gecko_absent'),
  'PT410', 'already_submitted'
);

-- Correction pins the effective digest; stale digest rejects and valid correction appends.
SELECT pg_temp.expect_error(
  format('SELECT * FROM public.fn_append_gme_negative_audit_correction(%L::uuid,%L::uuid,%L,0,%L::jsonb,%L,%L)',
    (SELECT primary_item FROM probe_state), '00000000-0000-4000-8000-000000000001',
    'gecko_present','{"x":0.1,"y":0.2,"width":0.3,"height":0.4}',
    'stale probe','0000000000000000000000000000000000000000000000000000000000000000'),
  'PT409', 'stale_submission_digest'
);
SELECT * FROM public.fn_append_gme_negative_audit_correction(
  (SELECT primary_item FROM probe_state),
  '00000000-0000-4000-8000-000000000001',
  'gecko_present', 0,
  '{"x":0.15,"y":0.15,"width":0.25,"height":0.25}'::jsonb,
  'representative box correction',
  (SELECT digest FROM public.gme_negative_audit_submissions
   WHERE item_id=(SELECT primary_item FROM probe_state))
);
SELECT pg_temp.expect_error(
  format('SELECT * FROM public.fn_append_gme_negative_audit_dataset_decision(%L::uuid,%L::uuid,%L,%L,%L)',
    (SELECT primary_item FROM probe_state), '00000000-0000-4000-8000-000000000001',
    'include_candidate','stale dataset digest',repeat('0',64)),
  'PT409', 'stale_effective_digest'
);
SELECT * FROM public.fn_append_gme_negative_audit_dataset_decision(
  (SELECT primary_item FROM probe_state),
  '00000000-0000-4000-8000-000000000001',
  'include_candidate','confirmed present negative',
  (SELECT digest FROM public.gme_negative_audit_corrections
   WHERE item_id=(SELECT primary_item FROM probe_state) ORDER BY created_at DESC,id DESC LIMIT 1)
);

-- A control can be reviewed but can never enter Dataset v2 as a candidate.
SELECT * FROM public.fn_submit_gme_negative_audit(
  (SELECT control_item FROM probe_state),
  '00000000-0000-4000-8000-000000000001',
  'gecko_present', 1,
  '{"x":0.2,"y":0.2,"width":0.2,"height":0.2}'::jsonb
);
SELECT pg_temp.expect_error(
  format('SELECT * FROM public.fn_append_gme_negative_audit_dataset_decision(%L::uuid,%L::uuid,%L,%L,%L)',
    (SELECT control_item FROM probe_state), '00000000-0000-4000-8000-000000000001',
    'include_candidate','must reject control',
    (SELECT digest FROM public.gme_negative_audit_submissions
     WHERE item_id=(SELECT control_item FROM probe_state))),
  'PT409', 'control_cannot_have_dataset_decision'
);

-- Separate owner/reviewer fixture proves non-owner adjudication and digest pinning.
INSERT INTO public.gme_negative_audit_items(
  id,batch_id,ordinal,clip_id,stratum,started_at,duration_sec,camera_night_key,episode_key,
  gme_run_id,detector_identity,media_sha256,media_dhash,gme_detected,human_gt_digest,
  selection_provenance,assigned_reviewer_id
)
SELECT
  '40000000-0000-4000-8000-000000000001',
  '30000000-0000-4000-8000-000000000001',1,clip_id,'random_negative',started_at,
  duration_sec,camera_night_key,episode_key,gme_run_id,detector_identity,media_sha256,
  media_dhash,false,NULL,selection_provenance,'00000000-0000-4000-8000-000000000002'
FROM public.gme_negative_audit_items
WHERE id=(SELECT primary_item FROM probe_state);
SELECT * FROM public.fn_submit_gme_negative_audit(
  '40000000-0000-4000-8000-000000000001',
  '00000000-0000-4000-8000-000000000002',
  'gecko_present',0,'{"x":0.1,"y":0.1,"width":0.2,"height":0.2}'::jsonb
);
SELECT pg_temp.expect_error(
  format('SELECT * FROM public.fn_append_gme_negative_audit_adjudication(%L::uuid,%L::uuid,%L,0,%L::jsonb,%L,%L)',
    '40000000-0000-4000-8000-000000000001',
    '00000000-0000-4000-8000-000000000001','gecko_present',
    '{"x":0.1,"y":0.1,"width":0.2,"height":0.2}',
    'stale adjudication digest',repeat('0',64)),
  'PT409', 'stale_submission_digest'
);
SELECT pg_temp.expect_error(
  format('SELECT * FROM public.fn_append_gme_negative_audit_dataset_decision(%L::uuid,%L::uuid,%L,%L,%L)',
    '40000000-0000-4000-8000-000000000001',
    '00000000-0000-4000-8000-000000000001','include_candidate',
    'owner adjudication required',
    (SELECT digest FROM public.gme_negative_audit_submissions
     WHERE item_id='40000000-0000-4000-8000-000000000001')),
  'PT409', 'adjudication_required'
);
SELECT * FROM public.fn_append_gme_negative_audit_adjudication(
  '40000000-0000-4000-8000-000000000001',
  '00000000-0000-4000-8000-000000000001',
  'gecko_present',0,'{"x":0.1,"y":0.1,"width":0.2,"height":0.2}'::jsonb,
  'owner confirmed non-owner present review',
  (SELECT digest FROM public.gme_negative_audit_submissions
   WHERE item_id='40000000-0000-4000-8000-000000000001')
);
SELECT pg_temp.expect_error(
  format('SELECT * FROM public.fn_append_gme_negative_audit_dataset_decision(%L::uuid,%L::uuid,%L,%L,%L)',
    '40000000-0000-4000-8000-000000000001',
    '00000000-0000-4000-8000-000000000001','include_candidate',
    'stale post-adjudication digest',repeat('0',64)),
  'PT409', 'stale_effective_digest'
);
SELECT * FROM public.fn_append_gme_negative_audit_dataset_decision(
  '40000000-0000-4000-8000-000000000001',
  '00000000-0000-4000-8000-000000000001',
  'include_candidate','owner adjudicated present',
  (SELECT digest FROM public.gme_negative_audit_adjudications
   WHERE item_id='40000000-0000-4000-8000-000000000001')
);

-- SQL-produced rows lock the exact ID-bound formulas consumed by the independent scorer.
SELECT pg_temp.probe_assert(
  NOT EXISTS (
    SELECT 1 FROM public.gme_negative_audit_submissions row
    WHERE row.digest <> public.fn_gme_negative_audit_ledger_digest(ARRAY[
      row.id::text,row.item_id::text,row.reviewer_id::text,row.verdict,
      coalesce(row.representative_sec::text,'null'),
      public.fn_gme_negative_audit_canonical_json(coalesce(row.bbox,'null'::jsonb))
    ])
  ) AND NOT EXISTS (
    SELECT 1 FROM public.gme_negative_audit_corrections row
    WHERE row.digest <> public.fn_gme_negative_audit_ledger_digest(ARRAY[
      row.id::text,row.original_submission_id::text,row.expected_submission_digest,row.verdict,
      coalesce(row.representative_sec::text,'null'),
      public.fn_gme_negative_audit_canonical_json(coalesce(row.bbox,'null'::jsonb)),row.reason
    ])
  ) AND NOT EXISTS (
    SELECT 1 FROM public.gme_negative_audit_adjudications row
    WHERE row.digest <> public.fn_gme_negative_audit_ledger_digest(ARRAY[
      row.id::text,row.original_submission_id::text,row.effective_submission_digest,row.final_verdict,
      coalesce(row.representative_sec::text,'null'),
      public.fn_gme_negative_audit_canonical_json(coalesce(row.bbox,'null'::jsonb)),row.reason
    ])
  ) AND NOT EXISTS (
    SELECT 1 FROM public.gme_negative_audit_dataset_decisions row
    WHERE row.digest <> public.fn_gme_negative_audit_ledger_digest(ARRAY[
      row.id::text,row.item_id::text,row.decision,row.effective_submission_digest,row.reason
    ])
  ) AND NOT EXISTS (
    SELECT 1 FROM public.gme_negative_audit_batch_events row
    WHERE row.digest <> public.fn_gme_negative_audit_ledger_digest(ARRAY[
      row.id::text,row.batch_id::text,row.event_type,row.actor_id::text,coalesce(row.reason,'null')
    ])
  ),
  'canonical ledger digest formula mismatch'
);

-- Close ordering is existence-hiding PT403, duplicate PT410, then state PT427.
INSERT INTO public.gme_negative_audit_batch_events(id,batch_id,event_type,actor_id,digest)
SELECT '31000000-0000-4000-8000-000000000004',batch_id,'closed',
       '00000000-0000-4000-8000-000000000001',
       public.fn_gme_negative_audit_ledger_digest(ARRAY[
         '31000000-0000-4000-8000-000000000004',batch_id::text,'closed',
         '00000000-0000-4000-8000-000000000001','null'
       ])
FROM probe_state;
INSERT INTO public.gme_negative_audit_batch_events(id,batch_id,event_type,actor_id,digest)
VALUES (
  '31000000-0000-4000-8000-000000000005','30000000-0000-4000-8000-000000000001','closed',
  '00000000-0000-4000-8000-000000000001',
  public.fn_gme_negative_audit_ledger_digest(ARRAY[
    '31000000-0000-4000-8000-000000000005','30000000-0000-4000-8000-000000000001','closed',
    '00000000-0000-4000-8000-000000000001','null'
  ])
);

-- Owner append paths must close atomically with the same latest-event lock.
SELECT pg_temp.expect_error(
  format('SELECT * FROM public.fn_append_gme_negative_audit_adjudication(%L::uuid,%L::uuid,%L,0,%L::jsonb,%L,%L)',
    '40000000-0000-4000-8000-000000000001',
    '00000000-0000-4000-8000-000000000001','gecko_present',
    '{"x":0.1,"y":0.1,"width":0.2,"height":0.2}','closed adjudication',
    (SELECT digest FROM public.gme_negative_audit_submissions
     WHERE item_id='40000000-0000-4000-8000-000000000001')),
  'PT427', 'batch_closed'
);
SELECT pg_temp.expect_error(
  format('SELECT * FROM public.fn_append_gme_negative_audit_dataset_decision(%L::uuid,%L::uuid,%L,%L,%L)',
    '40000000-0000-4000-8000-000000000001',
    '00000000-0000-4000-8000-000000000001','include_candidate','closed decision',
    (SELECT digest FROM public.gme_negative_audit_adjudications
     WHERE item_id='40000000-0000-4000-8000-000000000001')),
  'PT427', 'batch_closed'
);
SELECT pg_temp.expect_error(
  format('SELECT * FROM public.fn_submit_gme_negative_audit(%L::uuid,%L::uuid,%L,NULL,NULL)',
    (SELECT primary_item FROM probe_state), '00000000-0000-4000-8000-000000000001','gecko_absent'),
  'PT410', 'already_submitted'
);
SELECT pg_temp.expect_error(
  format('SELECT * FROM public.fn_submit_gme_negative_audit(%L::uuid,%L::uuid,%L,NULL,NULL)',
    (SELECT item.id FROM public.gme_negative_audit_items item
     LEFT JOIN public.gme_negative_audit_submissions submission ON submission.item_id=item.id
     WHERE item.batch_id=(SELECT batch_id FROM probe_state) AND submission.id IS NULL
     ORDER BY item.ordinal LIMIT 1),
    '00000000-0000-4000-8000-000000000001','gecko_absent'),
  'PT427', 'batch_closed'
);
SELECT pg_temp.expect_error(
  format('SELECT * FROM public.fn_submit_gme_negative_audit(%L::uuid,%L::uuid,%L,NULL,NULL)',
    (SELECT item.id FROM public.gme_negative_audit_items item
     LEFT JOIN public.gme_negative_audit_submissions submission ON submission.item_id=item.id
     WHERE item.batch_id=(SELECT batch_id FROM probe_state) AND submission.id IS NULL
     ORDER BY item.ordinal LIMIT 1),
    '00000000-0000-4000-8000-000000000003','gecko_absent'),
  'PT403', 'not_assigned'
);

-- Every one of the seven ledgers blocks UPDATE, DELETE, and TRUNCATE at runtime.
DO $$
DECLARE
  ledger text;
  operation text;
  statement text;
BEGIN
  FOREACH ledger IN ARRAY ARRAY[
    'gme_negative_audit_batches','gme_negative_audit_batch_events',
    'gme_negative_audit_items','gme_negative_audit_submissions',
    'gme_negative_audit_corrections','gme_negative_audit_adjudications',
    'gme_negative_audit_dataset_decisions'
  ] LOOP
    FOREACH operation IN ARRAY ARRAY['update','delete','truncate'] LOOP
      statement := CASE operation
        WHEN 'update' THEN format('UPDATE public.%I SET created_at=created_at', ledger)
        WHEN 'delete' THEN format('DELETE FROM public.%I', ledger)
        ELSE format('TRUNCATE public.%I CASCADE', ledger)
      END;
      PERFORM pg_temp.expect_error(
        statement, '0A000', 'GME negative audit ledgers are append-only'
      );
    END LOOP;
  END LOOP;
END;
$$;

SELECT 'GME_NEGATIVE_AUDIT_SCHEMA_OK';
SELECT 'GME_NEGATIVE_AUDIT_BLIND_OK';
SELECT 'GME_NEGATIVE_AUDIT_APPEND_ONLY_OK';

ROLLBACK;
