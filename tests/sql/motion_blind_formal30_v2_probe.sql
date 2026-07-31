-- Formal Blind30 v2 exact-30 원자 예약 실증. 모든 합성 row는 마지막 ROLLBACK으로 제거된다.

BEGIN;

CREATE FUNCTION pg_temp.formal30_clip_id(p_index integer) RETURNS uuid
LANGUAGE sql IMMUTABLE AS $$
  SELECT ('10000000-0000-0000-0000-' || lpad(p_index::text, 12, '0'))::uuid;
$$;

CREATE FUNCTION pg_temp.formal30_clip_ids(
  p_count integer DEFAULT 30,
  p_start integer DEFAULT 1
) RETURNS uuid[]
LANGUAGE sql IMMUTABLE AS $$
  SELECT array_agg(pg_temp.formal30_clip_id(i) ORDER BY i)
  FROM generate_series(p_start, p_start + p_count - 1) AS i;
$$;

CREATE FUNCTION pg_temp.formal30_ordered_hash(p_clip_ids uuid[]) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
  SELECT pg_catalog.encode(
    pg_catalog.sha256(
      pg_catalog.convert_to(
        pg_catalog.array_to_string(p_clip_ids, '|'),
        'UTF8'
      )
    ),
    'hex'
  );
$$;

CREATE FUNCTION pg_temp.expect_formal30_error(
  p_clip_ids uuid[],
  p_reviewer_ids uuid[],
  p_actor_id uuid,
  p_group_id uuid,
  p_expected_state text
) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
  BEGIN
    PERFORM public.fn_create_motion_blind_formal30_v2(
      p_actor_id,
      p_group_id,
      p_clip_ids,
      p_reviewer_ids,
      repeat('a', 64),
      pg_temp.formal30_ordered_hash(p_clip_ids),
      clock_timestamp() - interval '1 minute'
    );
    RAISE EXCEPTION 'expected SQLSTATE %, call succeeded', p_expected_state;
  EXCEPTION WHEN OTHERS THEN
    IF SQLSTATE <> p_expected_state THEN
      RAISE;
    END IF;
  END;
END;
$$;

INSERT INTO auth.users (id) VALUES
  ('00000000-0000-0000-0000-000000000001'),
  ('00000000-0000-0000-0000-000000000002'),
  ('00000000-0000-0000-0000-000000000003'),
  ('00000000-0000-0000-0000-000000000004');

INSERT INTO public.cameras (id, name)
VALUES ('00000000-0000-0000-0000-000000000010', 'synthetic formal30 camera');

INSERT INTO public.motion_clips (id, camera_id, started_at, duration_sec, r2_key)
SELECT
  pg_temp.formal30_clip_id(i),
  '00000000-0000-0000-0000-000000000010',
  timestamptz '2026-07-30T19:00:00+00' + i * interval '1 minute',
  60,
  'synthetic/formal30/' || i
FROM generate_series(1, 70) AS i;

INSERT INTO public.labelers (user_id) VALUES
  ('00000000-0000-0000-0000-000000000002'),
  ('00000000-0000-0000-0000-000000000003'),
  ('00000000-0000-0000-0000-000000000004');
INSERT INTO public.labeler_applications (user_id, status, display_name) VALUES
  ('00000000-0000-0000-0000-000000000002', 'approved', 'reviewer-a'),
  ('00000000-0000-0000-0000-000000000003', 'approved', 'reviewer-b'),
  ('00000000-0000-0000-0000-000000000004', 'approved', 'reviewer-c');

INSERT INTO public.motion_labeling_review_groups (id, name, active, created_by) VALUES
  (
    '00000000-0000-0000-0000-000000000020',
    'formal30 qualified pair',
    true,
    '00000000-0000-0000-0000-000000000001'
  ),
  (
    '00000000-0000-0000-0000-000000000021',
    'formal30 inactive pair',
    false,
    '00000000-0000-0000-0000-000000000001'
  );
INSERT INTO public.motion_labeling_review_group_members
  (group_id, user_id, assigned_by)
VALUES
  (
    '00000000-0000-0000-0000-000000000020',
    '00000000-0000-0000-0000-000000000002',
    '00000000-0000-0000-0000-000000000001'
  ),
  (
    '00000000-0000-0000-0000-000000000020',
    '00000000-0000-0000-0000-000000000003',
    '00000000-0000-0000-0000-000000000001'
  );

INSERT INTO public.labeling_tutorial_sets (id, version, status)
VALUES ('00000000-0000-0000-0000-000000000030', 'tutorial-v1', 'active');
INSERT INTO public.labeling_tutorial_lessons (id, tutorial_set_id, position)
SELECT
  ('00000000-0000-0000-0000-' || lpad((30 + i)::text, 12, '0'))::uuid,
  '00000000-0000-0000-0000-000000000030',
  i
FROM generate_series(1, 5) AS i;
INSERT INTO public.labeling_tutorial_progress
  (tutorial_set_id, user_id, current_run_no, completed_at)
VALUES
  (
    '00000000-0000-0000-0000-000000000030',
    '00000000-0000-0000-0000-000000000002',
    1,
    clock_timestamp()
  ),
  (
    '00000000-0000-0000-0000-000000000030',
    '00000000-0000-0000-0000-000000000003',
    1,
    clock_timestamp()
  );
INSERT INTO public.labeling_tutorial_attempts
  (tutorial_set_id, lesson_id, user_id, run_no, stage, completed_at)
SELECT
  '00000000-0000-0000-0000-000000000030',
  lesson.id,
  reviewer.id,
  1,
  'completed',
  clock_timestamp()
FROM public.labeling_tutorial_lessons AS lesson
CROSS JOIN (
  VALUES
    ('00000000-0000-0000-0000-000000000002'::uuid),
    ('00000000-0000-0000-0000-000000000003'::uuid)
) AS reviewer(id);

-- 입력 shape 계약.
SELECT pg_temp.expect_formal30_error(
  pg_temp.formal30_clip_ids(29),
  ARRAY[
    '00000000-0000-0000-0000-000000000002'::uuid,
    '00000000-0000-0000-0000-000000000003'::uuid
  ],
  '00000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000020',
  '22023'
);
SELECT pg_temp.expect_formal30_error(
  pg_temp.formal30_clip_ids(31),
  ARRAY[
    '00000000-0000-0000-0000-000000000002'::uuid,
    '00000000-0000-0000-0000-000000000003'::uuid
  ],
  '00000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000020',
  '22023'
);
SELECT pg_temp.expect_formal30_error(
  pg_temp.formal30_clip_ids(29) || pg_temp.formal30_clip_id(29),
  ARRAY[
    '00000000-0000-0000-0000-000000000002'::uuid,
    '00000000-0000-0000-0000-000000000003'::uuid
  ],
  '00000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000020',
  '22023'
);

-- reviewer/group/tutorial 자격 계약.
SELECT pg_temp.expect_formal30_error(
  pg_temp.formal30_clip_ids(),
  ARRAY[
    '00000000-0000-0000-0000-000000000002'::uuid,
    '00000000-0000-0000-0000-000000000002'::uuid
  ],
  '00000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000020',
  'PT425'
);
SELECT pg_temp.expect_formal30_error(
  pg_temp.formal30_clip_ids(),
  ARRAY[
    '00000000-0000-0000-0000-000000000001'::uuid,
    '00000000-0000-0000-0000-000000000003'::uuid
  ],
  '00000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000020',
  'PT425'
);
SELECT pg_temp.expect_formal30_error(
  pg_temp.formal30_clip_ids(),
  ARRAY[
    '00000000-0000-0000-0000-000000000002'::uuid,
    '00000000-0000-0000-0000-000000000003'::uuid
  ],
  '00000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000021',
  'PT425'
);

DO $$
BEGIN
  BEGIN
    UPDATE public.labeler_applications
    SET status = 'pending'
    WHERE user_id = '00000000-0000-0000-0000-000000000002';
    PERFORM public.fn_create_motion_blind_formal30_v2(
      '00000000-0000-0000-0000-000000000001',
      '00000000-0000-0000-0000-000000000020',
      pg_temp.formal30_clip_ids(),
      ARRAY[
        '00000000-0000-0000-0000-000000000002'::uuid,
        '00000000-0000-0000-0000-000000000003'::uuid
      ],
      repeat('a', 64),
      pg_temp.formal30_ordered_hash(pg_temp.formal30_clip_ids()),
      clock_timestamp() - interval '1 minute'
    );
    RAISE EXCEPTION 'unapproved reviewer was accepted';
  EXCEPTION WHEN SQLSTATE 'PT425' THEN NULL;
  END;
END $$;

DO $$
BEGIN
  BEGIN
    UPDATE public.labeling_tutorial_attempts
    SET stage = 'started', completed_at = NULL
    WHERE user_id = '00000000-0000-0000-0000-000000000002'
      AND lesson_id = '00000000-0000-0000-0000-000000000035';
    PERFORM public.fn_create_motion_blind_formal30_v2(
      '00000000-0000-0000-0000-000000000001',
      '00000000-0000-0000-0000-000000000020',
      pg_temp.formal30_clip_ids(),
      ARRAY[
        '00000000-0000-0000-0000-000000000002'::uuid,
        '00000000-0000-0000-0000-000000000003'::uuid
      ],
      repeat('a', 64),
      pg_temp.formal30_ordered_hash(pg_temp.formal30_clip_ids()),
      clock_timestamp() - interval '1 minute'
    );
    RAISE EXCEPTION 'tutorial 4/5 reviewer was accepted';
  EXCEPTION WHEN SQLSTATE 'PT425' THEN NULL;
  END;
END $$;

DO $$
BEGIN
  BEGIN
    UPDATE public.labeling_tutorial_progress
    SET waived_at = clock_timestamp()
    WHERE user_id = '00000000-0000-0000-0000-000000000002';
    PERFORM public.fn_create_motion_blind_formal30_v2(
      '00000000-0000-0000-0000-000000000001',
      '00000000-0000-0000-0000-000000000020',
      pg_temp.formal30_clip_ids(),
      ARRAY[
        '00000000-0000-0000-0000-000000000002'::uuid,
        '00000000-0000-0000-0000-000000000003'::uuid
      ],
      repeat('a', 64),
      pg_temp.formal30_ordered_hash(pg_temp.formal30_clip_ids()),
      clock_timestamp() - interval '1 minute'
    );
    RAISE EXCEPTION 'tutorial waiver was accepted';
  EXCEPTION WHEN SQLSTATE 'PT425' THEN NULL;
  END;
END $$;

-- group creator가 아닌 actor를 넘겨 owner 경계를 우회할 수 없다.
SELECT pg_temp.expect_formal30_error(
  pg_temp.formal30_clip_ids(),
  ARRAY[
    '00000000-0000-0000-0000-000000000002'::uuid,
    '00000000-0000-0000-0000-000000000003'::uuid
  ],
  '00000000-0000-0000-0000-000000000004',
  '00000000-0000-0000-0000-000000000020',
  'PT425'
);

-- ordered-list hash는 전달된 array 순서와 직접 일치해야 한다.
DO $$
BEGIN
  BEGIN
    PERFORM public.fn_create_motion_blind_formal30_v2(
      '00000000-0000-0000-0000-000000000001',
      '00000000-0000-0000-0000-000000000020',
      pg_temp.formal30_clip_ids(),
      ARRAY[
        '00000000-0000-0000-0000-000000000002'::uuid,
        '00000000-0000-0000-0000-000000000003'::uuid
      ],
      repeat('a', 64),
      repeat('f', 64),
      clock_timestamp() - interval '1 minute'
    );
    RAISE EXCEPTION 'mismatched ordered-list hash was accepted';
  EXCEPTION WHEN SQLSTATE '22023' THEN NULL;
  END;
END $$;

-- 한 clip이 부적격이면 호출 전체가 0 row로 되돌아간다.
DO $$
DECLARE
  v_before integer;
BEGIN
  SELECT count(*) INTO v_before FROM public.motion_blind_review_cohorts;
  BEGIN
    UPDATE public.motion_clips
    SET r2_key = NULL
    WHERE id = pg_temp.formal30_clip_id(30);
    PERFORM public.fn_create_motion_blind_formal30_v2(
      '00000000-0000-0000-0000-000000000001',
      '00000000-0000-0000-0000-000000000020',
      pg_temp.formal30_clip_ids(),
      ARRAY[
        '00000000-0000-0000-0000-000000000002'::uuid,
        '00000000-0000-0000-0000-000000000003'::uuid
      ],
      repeat('a', 64),
      pg_temp.formal30_ordered_hash(pg_temp.formal30_clip_ids()),
      clock_timestamp() - interval '1 minute'
    );
    RAISE EXCEPTION 'ineligible clip was accepted';
  EXCEPTION WHEN SQLSTATE '22023' THEN NULL;
  END;
  ASSERT (SELECT count(*) FROM public.motion_blind_review_cohorts) = v_before;
  ASSERT (SELECT count(*) FROM public.motion_clip_review_slots WHERE cohort_kind = 'canary') = 0;
  ASSERT (SELECT count(*) FROM public.motion_clip_consensus WHERE cohort_kind = 'canary') = 0;
END $$;

-- T0 전에 시작했더라도 activity day가 닫히지 않은 clip은 허용하지 않는다.
DO $$
DECLARE
  v_t0 timestamptz := clock_timestamp() - interval '1 minute';
  v_activity_day date;
BEGIN
  v_activity_day := (
    v_t0 AT TIME ZONE 'Asia/Seoul' - interval '7 hours'
  )::date;
  BEGIN
    UPDATE public.motion_clips
    SET started_at = (
      v_activity_day::timestamp + interval '7 hours'
    ) AT TIME ZONE 'Asia/Seoul'
    WHERE id = pg_temp.formal30_clip_id(30);
    PERFORM public.fn_create_motion_blind_formal30_v2(
      '00000000-0000-0000-0000-000000000001',
      '00000000-0000-0000-0000-000000000020',
      pg_temp.formal30_clip_ids(),
      ARRAY[
        '00000000-0000-0000-0000-000000000002'::uuid,
        '00000000-0000-0000-0000-000000000003'::uuid
      ],
      repeat('a', 64),
      pg_temp.formal30_ordered_hash(pg_temp.formal30_clip_ids()),
      v_t0
    );
    RAISE EXCEPTION 'open activity day was accepted';
  EXCEPTION WHEN SQLSTATE '22023' THEN NULL;
  END;
END $$;

-- v1 T0 이전 old pool clip 한 건이 섞이면 전체를 거부한다.
DO $$
BEGIN
  BEGIN
    UPDATE public.motion_clips
    SET started_at = timestamptz '2026-07-31T03:44:27.183403+09:00'
      - interval '1 second'
    WHERE id = pg_temp.formal30_clip_id(30);
    PERFORM public.fn_create_motion_blind_formal30_v2(
      '00000000-0000-0000-0000-000000000001',
      '00000000-0000-0000-0000-000000000020',
      pg_temp.formal30_clip_ids(),
      ARRAY[
        '00000000-0000-0000-0000-000000000002'::uuid,
        '00000000-0000-0000-0000-000000000003'::uuid
      ],
      repeat('a', 64),
      pg_temp.formal30_ordered_hash(pg_temp.formal30_clip_ids()),
      clock_timestamp() - interval '1 minute'
    );
    RAISE EXCEPTION 'v1-era clip was accepted';
  EXCEPTION WHEN SQLSTATE '22023' THEN NULL;
  END;
END $$;

-- live의 미제출 slot 및 awaiting consensus는 formal 후보로 허용한다.
INSERT INTO public.motion_clip_review_slots
  (clip_id, group_id, reviewer_id, cohort_kind, activity_day_kst)
VALUES
  (
    pg_temp.formal30_clip_id(1),
    '00000000-0000-0000-0000-000000000020',
    '00000000-0000-0000-0000-000000000002',
    'live',
    current_date - 2
  );
INSERT INTO public.motion_clip_consensus
  (clip_id, group_id, cohort_kind, status)
VALUES
  (
    pg_temp.formal30_clip_id(2),
    '00000000-0000-0000-0000-000000000020',
    'live',
    'awaiting'
  );

DO $$
DECLARE
  v_cohort uuid;
BEGIN
  v_cohort := public.fn_create_motion_blind_formal30_v2(
    '00000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000020',
    pg_temp.formal30_clip_ids(),
    ARRAY[
      '00000000-0000-0000-0000-000000000002'::uuid,
      '00000000-0000-0000-0000-000000000003'::uuid
    ],
    repeat('a', 64),
    pg_temp.formal30_ordered_hash(pg_temp.formal30_clip_ids()),
    clock_timestamp() - interval '1 minute'
  );
  ASSERT (SELECT count(*) FROM public.motion_blind_review_cohorts WHERE id = v_cohort) = 1;
  ASSERT (
    SELECT label LIKE 'b30v2:%'
    FROM public.motion_blind_review_cohorts
    WHERE id = v_cohort
  );
  ASSERT (
    SELECT count(*) FROM public.motion_clip_review_slots
    WHERE cohort_kind = 'canary' AND cohort_id = v_cohort
  ) = 60;
  ASSERT (
    SELECT count(*) FROM public.motion_clip_consensus
    WHERE cohort_kind = 'canary' AND cohort_id = v_cohort AND status = 'awaiting'
  ) = 30;
END $$;

-- formal 예약이 이긴 뒤 같은 clip의 기존 live slot 제출은 차단된다.
DO $$
DECLARE
  v_slot uuid;
BEGIN
  SELECT id INTO v_slot
  FROM public.motion_clip_review_slots
  WHERE clip_id = pg_temp.formal30_clip_id(1)
    AND cohort_kind = 'live';
  BEGIN
    INSERT INTO public.motion_clip_blind_submissions
      (slot_id, clip_id, group_id, reviewer_id, cohort_kind, decision, reason_code, initial_gt, digest)
    VALUES (
      v_slot,
      pg_temp.formal30_clip_id(1),
      '00000000-0000-0000-0000-000000000020',
      '00000000-0000-0000-0000-000000000002',
      'live',
      'hold',
      'ambiguous',
      NULL,
      repeat('f', 64)
    );
    RAISE EXCEPTION 'live submission after formal reservation was accepted';
  EXCEPTION WHEN SQLSTATE 'PT425' THEN NULL;
  END;
  ASSERT (SELECT count(*) FROM public.motion_clip_blind_submissions) = 0;
END $$;

-- 같은 manifest hash는 다른 30개에도 두 번째 provenance로 재사용할 수 없다.
SELECT pg_temp.expect_formal30_error(
  pg_temp.formal30_clip_ids(30, 41),
  ARRAY[
    '00000000-0000-0000-0000-000000000002'::uuid,
    '00000000-0000-0000-0000-000000000003'::uuid
  ],
  '00000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000020',
  '23505'
);

-- 동일 clip을 다시 예약하면 기존 60/30은 그대로다.
SELECT pg_temp.expect_formal30_error(
  pg_temp.formal30_clip_ids(),
  ARRAY[
    '00000000-0000-0000-0000-000000000002'::uuid,
    '00000000-0000-0000-0000-000000000003'::uuid
  ],
  '00000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000020',
  '22023'
);
DO $$
BEGIN
  ASSERT (SELECT count(*) FROM public.motion_clip_review_slots WHERE cohort_kind = 'canary') = 60;
  ASSERT (SELECT count(*) FROM public.motion_clip_consensus WHERE cohort_kind = 'canary') = 30;
END $$;

-- 별도 clip set에서 기존 submission/canary history/live terminal을 각각 거부한다.
DO $$
DECLARE
  v_slot uuid;
BEGIN
  BEGIN
    INSERT INTO public.motion_clip_review_slots
      (clip_id, group_id, reviewer_id, cohort_kind, activity_day_kst)
    VALUES (
      pg_temp.formal30_clip_id(31),
      '00000000-0000-0000-0000-000000000020',
      '00000000-0000-0000-0000-000000000002',
      'live',
      current_date - 2
    ) RETURNING id INTO v_slot;
    INSERT INTO public.motion_clip_blind_submissions
      (slot_id, clip_id, group_id, reviewer_id, cohort_kind, decision, reason_code, initial_gt, digest)
    VALUES (
      v_slot,
      pg_temp.formal30_clip_id(31),
      '00000000-0000-0000-0000-000000000020',
      '00000000-0000-0000-0000-000000000002',
      'live',
      'hold',
      'ambiguous',
      NULL,
      repeat('c', 64)
    );
    PERFORM public.fn_create_motion_blind_formal30_v2(
      '00000000-0000-0000-0000-000000000001',
      '00000000-0000-0000-0000-000000000020',
      pg_temp.formal30_clip_ids(29) || pg_temp.formal30_clip_id(31),
      ARRAY[
        '00000000-0000-0000-0000-000000000002'::uuid,
        '00000000-0000-0000-0000-000000000003'::uuid
      ],
      repeat('d', 64),
      pg_temp.formal30_ordered_hash(
        pg_temp.formal30_clip_ids(29) || pg_temp.formal30_clip_id(31)
      ),
      clock_timestamp() - interval '1 minute'
    );
    RAISE EXCEPTION 'existing submission was accepted';
  EXCEPTION WHEN SQLSTATE '22023' THEN NULL;
  END;
END $$;

DO $$
BEGIN
  BEGIN
    INSERT INTO public.motion_clip_consensus
      (clip_id, group_id, cohort_kind, status)
    VALUES (
      pg_temp.formal30_clip_id(32),
      '00000000-0000-0000-0000-000000000020',
      'live',
      'conflict'
    );
    PERFORM public.fn_create_motion_blind_formal30_v2(
      '00000000-0000-0000-0000-000000000001',
      '00000000-0000-0000-0000-000000000020',
      pg_temp.formal30_clip_ids(29) || pg_temp.formal30_clip_id(32),
      ARRAY[
        '00000000-0000-0000-0000-000000000002'::uuid,
        '00000000-0000-0000-0000-000000000003'::uuid
      ],
      repeat('e', 64),
      pg_temp.formal30_ordered_hash(
        pg_temp.formal30_clip_ids(29) || pg_temp.formal30_clip_id(32)
      ),
      clock_timestamp() - interval '1 minute'
    );
    RAISE EXCEPTION 'live terminal consensus was accepted';
  EXCEPTION WHEN SQLSTATE '22023' THEN NULL;
  END;
END $$;

-- execute privilege는 service_role만 가진다.
DO $$
DECLARE
  v_signature text :=
    'public.fn_create_motion_blind_formal30_v2(uuid,uuid,uuid[],uuid[],text,text,timestamp with time zone)';
BEGIN
  ASSERT NOT has_function_privilege('anon', v_signature, 'EXECUTE');
  ASSERT NOT has_function_privilege('authenticated', v_signature, 'EXECUTE');
  ASSERT has_function_privilege('service_role', v_signature, 'EXECUTE');
END $$;

\echo FORMAL30_V2_PROBE_OK
ROLLBACK;
