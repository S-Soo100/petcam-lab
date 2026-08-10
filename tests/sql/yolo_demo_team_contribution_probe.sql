\set ON_ERROR_STOP on

INSERT INTO public.yolo_model_versions
  (version, artifact_digest, architecture, created_by)
VALUES
  ('yolo-v1', repeat('1', 64), 'YOLO gecko detector', '00000000-0000-4000-8000-000000000001'),
  ('yolo-v2', repeat('2', 64), 'YOLO gecko detector', '00000000-0000-4000-8000-000000000001');

INSERT INTO public.yolo_dataset_versions (id, version, manifest_digest, created_by)
VALUES (
  '00000000-0000-4000-8000-000000000100', 'dataset-v2-draft', repeat('a', 64),
  '00000000-0000-4000-8000-000000000001'
);

INSERT INTO public.yolo_bbox_tasks
  (id, assignee_id, media_kind, media_ref, frame_manifest, model_version, prediction_snapshot, created_by)
VALUES (
  '00000000-0000-4000-8000-000000000200',
  '00000000-0000-4000-8000-000000000002',
  'image', 'probe://image-1', '[{"frame_index":0,"timestamp_ms":0}]', 'yolo-v1',
  '{"request_id":"probe-request","media_kind":"image","model_version":"yolo-v1","provider_mode":"worker","processed_at":"2026-08-10T08:00:00Z","warning":"연구용 결과이며 오류 가능","contribution_status":"not_requested","frames":[{"frame_index":0,"timestamp_ms":0,"detections":[{"label":"gecko","confidence":0.9,"bbox":{"x":0.1,"y":0.2,"width":0.3,"height":0.4}}]}]}',
  '00000000-0000-4000-8000-000000000001'
);

DO $$
DECLARE workspace jsonb;
BEGIN
  workspace := public.fn_get_yolo_bbox_workspace('00000000-0000-4000-8000-000000000002');
  ASSERT workspace->>'enabled' = 'true';
  ASSERT NOT (workspace::text ~ '(prediction|model_version|confidence)');

  BEGIN
    PERFORM public.fn_reveal_yolo_bbox_prediction(
      '00000000-0000-4000-8000-000000000002',
      '00000000-0000-4000-8000-000000000200'
    );
    RAISE EXCEPTION 'missing reveal-before-submit error';
  EXCEPTION WHEN SQLSTATE 'PT409' THEN NULL;
  END;

  BEGIN
    PERFORM public.fn_submit_yolo_bbox_blind(
      '00000000-0000-4000-8000-000000000002',
      '00000000-0000-4000-8000-000000000200',
      '[{"frame_index":99,"bbox":{"x":0.1,"y":0.2,"width":0.3,"height":0.4}}]', false
    );
    RAISE EXCEPTION 'missing frame manifest error';
  EXCEPTION WHEN SQLSTATE '22023' THEN NULL;
  END;

  BEGIN
    PERFORM public.fn_submit_yolo_bbox_blind(
      '00000000-0000-4000-8000-000000000003',
      '00000000-0000-4000-8000-000000000200',
      '[{"frame_index":0,"bbox":{"x":0.1,"y":0.2,"width":0.3,"height":0.4}}]', false
    );
    RAISE EXCEPTION 'missing outsider error';
  EXCEPTION WHEN SQLSTATE 'PT403' THEN NULL;
  END;
END;
$$;

SELECT public.fn_submit_yolo_bbox_blind(
  '00000000-0000-4000-8000-000000000002',
  '00000000-0000-4000-8000-000000000200',
  '[{"frame_index":0,"bbox":{"x":0.1,"y":0.2,"width":0.3,"height":0.4}}]', false
);
SELECT public.fn_reveal_yolo_bbox_prediction(
  '00000000-0000-4000-8000-000000000002',
  '00000000-0000-4000-8000-000000000200'
);
SELECT public.fn_submit_yolo_bbox_revision(
  '00000000-0000-4000-8000-000000000002',
  '00000000-0000-4000-8000-000000000200',
  '[{"frame_index":0,"bbox":{"x":0.12,"y":0.22,"width":0.28,"height":0.38}}]', false,
  '모델 박스와 원본을 비교해 경계를 조정함'
);

DO $$
BEGIN
  BEGIN
    PERFORM public.fn_submit_yolo_bbox_revision(
      '00000000-0000-4000-8000-000000000002',
      '00000000-0000-4000-8000-000000000200',
      '[{"frame_index":0,"bbox":{"x":0.12,"y":0.22,"width":0.28,"height":0.38}}]', false,
      'Owner 판정 전 중복 revision 차단 확인'
    );
    RAISE EXCEPTION 'missing pending revision gate';
  EXCEPTION WHEN SQLSTATE 'PT409' THEN NULL;
  END;
END;
$$;

DO $$
DECLARE revision_id uuid;
DECLARE owner_overview jsonb;
DECLARE workspace jsonb;
DECLARE replay jsonb;
BEGIN
  ASSERT (SELECT count(*) FROM public.yolo_dataset_memberships) = 0;
  owner_overview := public.fn_get_yolo_owner_overview('00000000-0000-4000-8000-000000000001');
  ASSERT jsonb_array_length(owner_overview->'reviews') = 1;
  ASSERT (owner_overview->'models'->0->>'owner_approved')::boolean = false;
  SELECT id INTO revision_id FROM public.yolo_bbox_revisions WHERE revision_no = 1;
  PERFORM public.fn_owner_decide_yolo_bbox_revision(
    '00000000-0000-4000-8000-000000000001', revision_id, 'reject',
    '꼬리 끝 경계를 다시 확인해', NULL
  );
  workspace := public.fn_get_yolo_bbox_workspace('00000000-0000-4000-8000-000000000002');
  ASSERT workspace->>'completed' = '0';
  ASSERT workspace->'next_task'->>'stage' = 'revealed';
  replay := public.fn_reveal_yolo_bbox_prediction(
    '00000000-0000-4000-8000-000000000002',
    '00000000-0000-4000-8000-000000000200'
  );
  ASSERT replay->>'owner_feedback' = '꼬리 끝 경계를 다시 확인해';
  PERFORM public.fn_submit_yolo_bbox_revision(
    '00000000-0000-4000-8000-000000000002',
    '00000000-0000-4000-8000-000000000200',
    '[{"frame_index":0,"bbox":{"x":0.11,"y":0.21,"width":0.29,"height":0.39}}]', false,
    'Owner 반려 사유에 따라 꼬리 경계를 다시 조정함'
  );
  owner_overview := public.fn_get_yolo_owner_overview('00000000-0000-4000-8000-000000000001');
  ASSERT jsonb_array_length(owner_overview->'reviews') = 1;
  SELECT id INTO revision_id FROM public.yolo_bbox_revisions ORDER BY revision_no DESC LIMIT 1;
  PERFORM public.fn_owner_decide_yolo_bbox_revision(
    '00000000-0000-4000-8000-000000000001', revision_id, 'approve',
    '수정된 사람 bbox와 원본을 확인해 승인함', '00000000-0000-4000-8000-000000000100'
  );
  ASSERT (SELECT count(*) FROM public.yolo_dataset_memberships) = 1;
  PERFORM public.fn_freeze_yolo_dataset(
    '00000000-0000-4000-8000-000000000001',
    '00000000-0000-4000-8000-000000000100',
    'Owner 승인 membership 확인 후 Dataset 고정'
  );
  owner_overview := public.fn_get_yolo_owner_overview('00000000-0000-4000-8000-000000000001');
  ASSERT jsonb_array_length(owner_overview->'datasets') = 0;
  BEGIN
    PERFORM public.fn_freeze_yolo_dataset(
      '00000000-0000-4000-8000-000000000001',
      '00000000-0000-4000-8000-000000000100',
      '중복 Dataset freeze 차단 확인'
    );
    RAISE EXCEPTION 'missing duplicate freeze gate';
  EXCEPTION WHEN SQLSTATE 'PT409' THEN NULL;
  END;
END;
$$;

DO $$
BEGIN
  BEGIN
    PERFORM public.fn_activate_yolo_model(
      '00000000-0000-4000-8000-000000000001', 'yolo-v1', 'activate', '초기 활성화'
    );
    RAISE EXCEPTION 'missing evaluation gate error';
  EXCEPTION WHEN SQLSTATE 'PT409' THEN NULL;
  END;
END;
$$;

DO $$
BEGIN
  BEGIN
    PERFORM public.fn_owner_decide_yolo_model(
      '00000000-0000-4000-8000-000000000001', 'yolo-v1', 'approve',
      '시험 전 모델 승인 차단 확인'
    );
    RAISE EXCEPTION 'missing model evaluation approval gate';
  EXCEPTION WHEN SQLSTATE 'PT409' THEN NULL;
  END;
END;
$$;

INSERT INTO public.yolo_model_evaluations
  (model_version, suite, manifest_digest, metrics, passed, recorded_by)
SELECT version, suite, encode(digest(version || '|' || suite, 'sha256'), 'hex'), '{"map50":0.9}', true,
       '00000000-0000-4000-8000-000000000001'
FROM (VALUES ('yolo-v1'), ('yolo-v2')) AS versions(version)
CROSS JOIN (VALUES ('fixed_test'), ('future_holdout')) AS suites(suite);

SELECT public.fn_owner_decide_yolo_model(
  '00000000-0000-4000-8000-000000000001', 'yolo-v1', 'approve', '두 시험 통과 확인'
);
SELECT public.fn_owner_decide_yolo_model(
  '00000000-0000-4000-8000-000000000001', 'yolo-v2', 'approve', '두 시험 통과 확인'
);

SELECT public.fn_activate_yolo_model(
  '00000000-0000-4000-8000-000000000001', 'yolo-v1', 'activate', '초기 활성화'
);
SELECT public.fn_activate_yolo_model(
  '00000000-0000-4000-8000-000000000001', 'yolo-v2', 'activate', '후속 활성화'
);
SELECT public.fn_activate_yolo_model(
  '00000000-0000-4000-8000-000000000001', 'yolo-v1', 'rollback', '즉시 롤백 점검'
);

INSERT INTO public.yolo_model_evaluations
  (model_version, suite, manifest_digest, metrics, passed, recorded_by)
VALUES (
  'yolo-v2', 'fixed_test', repeat('f', 64), '{"map50":0.1}', false,
  '00000000-0000-4000-8000-000000000001'
);

DO $$
DECLARE owner_overview jsonb;
BEGIN
  owner_overview := public.fn_get_yolo_owner_overview('00000000-0000-4000-8000-000000000001');
  ASSERT (SELECT (item->>'fixed_test_passed')::boolean
          FROM jsonb_array_elements(owner_overview->'models') item
          WHERE item->>'version' = 'yolo-v2') = false;
  ASSERT (SELECT (item->>'owner_approved')::boolean
          FROM jsonb_array_elements(owner_overview->'models') item
          WHERE item->>'version' = 'yolo-v2') = false;
  BEGIN
    PERFORM public.fn_activate_yolo_model(
      '00000000-0000-4000-8000-000000000001', 'yolo-v2', 'activate',
      '최신 시험 실패 모델 차단 확인'
    );
    RAISE EXCEPTION 'missing latest evaluation gate';
  EXCEPTION WHEN SQLSTATE 'PT409' THEN NULL;
  END;
END;
$$;

DO $$
BEGIN
  ASSERT (
    SELECT model_version FROM public.yolo_model_activation_events ORDER BY activated_at DESC, id DESC LIMIT 1
  ) = 'yolo-v1';
  BEGIN
    UPDATE public.yolo_bbox_blind_submissions SET no_gecko = true;
    RAISE EXCEPTION 'missing append-only error';
  EXCEPTION WHEN SQLSTATE '0A000' THEN NULL;
  END;
END;
$$;

SELECT 'YOLO_PROBE_OK';
SELECT 'YOLO_BLIND_OK';
SELECT 'YOLO_DATASET_GATE_OK';
SELECT 'YOLO_MODEL_ACTIVATION_OK';
SELECT 'YOLO_APPEND_ONLY_OK';
