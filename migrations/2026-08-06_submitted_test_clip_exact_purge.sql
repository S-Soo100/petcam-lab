-- 이미 교차검수에 제출된 test clip 정확히 4개만 DB에서 제거한다.
-- R2 exact-object 삭제·부재 확인이 먼저 끝난 뒤 실행하는 forward-only migration이다.
-- 대상 UUID를 하드코딩하지 않고 test purpose + 실제 제출 이력의 교집합으로 다시 계산한다.

BEGIN;

LOCK TABLE public.motion_clips IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE public.motion_clip_review_slots IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE public.motion_clip_blind_submissions IN ACCESS EXCLUSIVE MODE;
LOCK TABLE public.motion_clip_consensus IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE public.gme_jobs IN ACCESS EXCLUSIVE MODE;
LOCK TABLE public.gme_runs IN ACCESS EXCLUSIVE MODE;

CREATE TEMP TABLE exact_purge_targets (
  clip_id uuid PRIMARY KEY
) ON COMMIT DROP;

INSERT INTO exact_purge_targets (clip_id)
SELECT DISTINCT m.id
FROM public.motion_clips m
JOIN public.motion_clip_blind_submissions s ON s.clip_id = m.id
WHERE m.clip_purpose = 'test';

DO $$
DECLARE
  target_count integer;
  slot_count integer;
  submission_count integer;
  consensus_count integer;
  gme_job_count integer;
  gme_run_count integer;
  loose_reference_count integer;
BEGIN
  SELECT count(*) INTO target_count FROM exact_purge_targets;
  IF target_count <> 4 THEN
    RAISE EXCEPTION 'expected exactly 4 submitted test clips, got %', target_count;
  END IF;

  SELECT count(*) INTO slot_count
  FROM public.motion_clip_review_slots s
  JOIN exact_purge_targets t ON t.clip_id = s.clip_id;
  IF slot_count <> 8 THEN
    RAISE EXCEPTION 'expected 8 review slots, got %', slot_count;
  END IF;

  SELECT count(*) INTO submission_count
  FROM public.motion_clip_blind_submissions s
  JOIN exact_purge_targets t ON t.clip_id = s.clip_id;
  IF submission_count <> 4 THEN
    RAISE EXCEPTION 'expected 4 blind submissions, got %', submission_count;
  END IF;

  SELECT count(*) INTO consensus_count
  FROM public.motion_clip_consensus c
  JOIN exact_purge_targets t ON t.clip_id = c.clip_id;
  IF consensus_count <> 4 THEN
    RAISE EXCEPTION 'expected 4 consensus rows, got %', consensus_count;
  END IF;

  SELECT count(*) INTO gme_job_count
  FROM public.gme_jobs j
  JOIN exact_purge_targets t ON t.clip_id = j.clip_id;
  IF gme_job_count <> 4 THEN
    RAISE EXCEPTION 'expected 4 gme jobs, got %', gme_job_count;
  END IF;

  SELECT count(*) INTO gme_run_count
  FROM public.gme_runs r
  JOIN exact_purge_targets t ON t.clip_id = r.clip_id;
  IF gme_run_count <> 4 THEN
    RAISE EXCEPTION 'expected 4 gme runs, got %', gme_run_count;
  END IF;

  SELECT
      (SELECT count(*) FROM public.clip_favorites x JOIN exact_purge_targets t ON t.clip_id = x.clip_id)
    + (SELECT count(*) FROM public.behavior_logs x JOIN exact_purge_targets t ON t.clip_id = x.clip_id)
    + (SELECT count(*) FROM public.behavior_labels x JOIN exact_purge_targets t ON t.clip_id = x.clip_id)
    + (SELECT count(*) FROM public.camera_clips x JOIN exact_purge_targets t ON t.clip_id = x.id)
    + (SELECT count(*) FROM public.motion_clip_system_exclusions x JOIN exact_purge_targets t ON t.clip_id = x.clip_id)
    + (SELECT count(*) FROM public.motion_clip_system_exclusion_events x JOIN exact_purge_targets t ON t.clip_id = x.clip_id)
    + (SELECT count(*) FROM public.motion_clip_labeling_triage x JOIN exact_purge_targets t ON t.clip_id = x.clip_id)
    + (SELECT count(*) FROM public.motion_clip_labeling_triage_events x JOIN exact_purge_targets t ON t.clip_id = x.clip_id)
    + (SELECT count(*) FROM public.motion_clip_labeling_sessions x JOIN exact_purge_targets t ON t.clip_id = x.clip_id)
    + (SELECT count(*) FROM public.motion_clip_labeling_session_revisions x JOIN exact_purge_targets t ON t.clip_id = x.clip_id)
    + (SELECT count(*) FROM public.motion_clip_consensus_events x JOIN exact_purge_targets t ON t.clip_id = x.clip_id)
    + (SELECT count(*) FROM public.rba_owner_media_cleanup_items x JOIN exact_purge_targets t ON t.clip_id = x.clip_id)
    + (SELECT count(*) FROM public.rba_owner_media_cleanup_decisions x JOIN exact_purge_targets t ON t.clip_id = x.clip_id)
    + (SELECT count(*) FROM public.rba_owner_media_cleanup_events x JOIN exact_purge_targets t ON t.clip_id = x.clip_id)
    + (SELECT count(*) FROM public.rba_boundary_review_pairs x JOIN exact_purge_targets t ON t.clip_id IN (x.left_clip_id, x.right_clip_id))
    + (SELECT count(*) FROM public.python_evidence_jobs x JOIN exact_purge_targets t ON t.clip_id = x.clip_id)
    + (SELECT count(*) FROM public.clip_python_evidence_runs x JOIN exact_purge_targets t ON t.clip_id = x.clip_id)
    + (SELECT count(*) FROM public.clip_vlm_jobs x JOIN exact_purge_targets t ON t.clip_id = x.clip_id)
    + (SELECT count(*) FROM public.clip_prelabels x JOIN exact_purge_targets t ON t.clip_id = x.clip_id)
    + (SELECT count(*) FROM public.clip_activity_assessments x JOIN exact_purge_targets t ON t.clip_id = x.clip_id)
  INTO loose_reference_count;

  IF loose_reference_count <> 0 THEN
    RAISE EXCEPTION 'unexpected loose or labeling references: %', loose_reference_count;
  END IF;
END;
$$;

-- consensus가 submission_a/submission_b를 참조하므로 먼저 제거한다.
DELETE FROM public.motion_clip_consensus c
USING exact_purge_targets t
WHERE c.clip_id = t.clip_id;

ALTER TABLE public.motion_clip_blind_submissions
  DISABLE TRIGGER trg_block_motion_blind_submission_mutation;
DELETE FROM public.motion_clip_blind_submissions s
USING exact_purge_targets t
WHERE s.clip_id = t.clip_id;
ALTER TABLE public.motion_clip_blind_submissions
  ENABLE TRIGGER trg_block_motion_blind_submission_mutation;

DELETE FROM public.motion_clip_review_slots s
USING exact_purge_targets t
WHERE s.clip_id = t.clip_id;

-- gme_jobs.result_run_id와 gme_runs.job_id의 순환 참조를 먼저 끊는다.
UPDATE public.gme_jobs j
SET result_run_id = NULL
FROM exact_purge_targets t
WHERE j.clip_id = t.clip_id;

ALTER TABLE public.gme_runs DISABLE TRIGGER trg_block_gme_run_delete;
DELETE FROM public.gme_runs r
USING exact_purge_targets t
WHERE r.clip_id = t.clip_id;
ALTER TABLE public.gme_runs ENABLE TRIGGER trg_block_gme_run_delete;

DELETE FROM public.gme_jobs j
USING exact_purge_targets t
WHERE j.clip_id = t.clip_id;

DELETE FROM public.motion_clips m
USING exact_purge_targets t
WHERE m.id = t.clip_id;

DO $$
DECLARE
  remaining_count integer;
BEGIN
  SELECT
      (SELECT count(*) FROM public.motion_clips x JOIN exact_purge_targets t ON t.clip_id = x.id)
    + (SELECT count(*) FROM public.motion_clip_review_slots x JOIN exact_purge_targets t ON t.clip_id = x.clip_id)
    + (SELECT count(*) FROM public.motion_clip_blind_submissions x JOIN exact_purge_targets t ON t.clip_id = x.clip_id)
    + (SELECT count(*) FROM public.motion_clip_consensus x JOIN exact_purge_targets t ON t.clip_id = x.clip_id)
    + (SELECT count(*) FROM public.gme_jobs x JOIN exact_purge_targets t ON t.clip_id = x.clip_id)
    + (SELECT count(*) FROM public.gme_runs x JOIN exact_purge_targets t ON t.clip_id = x.clip_id)
  INTO remaining_count;

  IF remaining_count <> 0 THEN
    RAISE EXCEPTION 'exact purge postcondition failed: % rows remain', remaining_count;
  END IF;
END;
$$;

COMMIT;
