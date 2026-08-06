-- 기존 test 영상의 운영 교차검수 자재만 정리한다.
-- 제출이 한 건이라도 있는 정확한 4 clip은 다음 exact purge 단계까지 전체 slot/consensus를 보존한다.
-- motion_clips/R2/GME/GT는 이 migration에서 건드리지 않는다.

BEGIN;

LOCK TABLE public.motion_clip_review_slots IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE public.motion_clip_blind_submissions IN SHARE MODE;
LOCK TABLE public.motion_clip_consensus IN SHARE ROW EXCLUSIVE MODE;

CREATE TEMP TABLE submitted_test_clips ON COMMIT DROP AS
SELECT DISTINCT m.id AS clip_id
FROM public.motion_clips m
JOIN public.motion_clip_blind_submissions submission
  ON submission.clip_id = m.id
WHERE m.clip_purpose = 'test';

DO $$
DECLARE
  v_count integer;
BEGIN
  SELECT count(*) INTO v_count FROM submitted_test_clips;
  IF v_count <> 4 THEN
    RAISE EXCEPTION 'expected exactly 4 submitted test clips, found %', v_count
      USING ERRCODE = 'PT409';
  END IF;
END;
$$;

-- 향후 migration 적용 시점까지 test clip이 더 들어와도 안전하게 모두 정리하되,
-- 이미 제출된 네 clip은 partner slot까지 그대로 보존한다.
CREATE TEMP TABLE removable_test_clips ON COMMIT DROP AS
SELECT m.id AS clip_id
FROM public.motion_clips m
WHERE m.clip_purpose = 'test'
  AND NOT EXISTS (
    SELECT 1
    FROM submitted_test_clips submitted
    WHERE submitted.clip_id = m.id
  );

DELETE FROM public.motion_clip_review_slots slot
USING removable_test_clips removable
WHERE slot.clip_id = removable.clip_id;

DELETE FROM public.motion_clip_consensus consensus
USING removable_test_clips removable
WHERE consensus.clip_id = removable.clip_id;

DO $$
DECLARE
  v_survivor_count integer;
BEGIN
  SELECT count(DISTINCT slot.clip_id)
  INTO v_survivor_count
  FROM public.motion_clip_review_slots slot
  JOIN public.motion_clips m ON m.id = slot.clip_id
  WHERE m.clip_purpose = 'test'
    AND NOT EXISTS (
      SELECT 1
      FROM submitted_test_clips submitted
      WHERE submitted.clip_id = slot.clip_id
    );

  IF v_survivor_count <> 0 THEN
    RAISE EXCEPTION 'test review material survived cleanup: % clips', v_survivor_count
      USING ERRCODE = 'PT409';
  END IF;
END;
$$;

COMMIT;
