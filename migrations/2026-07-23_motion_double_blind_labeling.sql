-- 그룹 이중 블라인드 라벨링 — forward migration — 2026-07-23.
--
-- 설계 정본: docs/superpowers/specs/2026-07-23-double-blind-labeling-groups-design.md
-- 구현계획:   docs/superpowers/plans/2026-07-23-double-blind-labeling-groups.md Task 2
--
-- forward-only 신규 파일. 적용된 기존 마이그레이션(2026-07-22_motion_clip_labeling_v3.sql,
-- 2026-07-22_motion_clip_gt_decision_guard.sql)을 수정하지 않는다. legacy owner v3·튜토리얼·
-- VLM·Gate·Python 근거 파이프라인·활동 계산은 그대로 두고, group→camera→clip review slot→immutable
-- blind submission→consensus 경계만 추가한다.
--
-- 왜 SECURITY INVOKER + search_path='' 인가(설계 §7): 모든 상태 전환은 Next.js API 가 bearer
--   인증 + owner/labeler 판정 뒤 service_role 로만 호출한다. 함수는 호출자(service_role) 권한으로
--   실행되고, service_role 만 EXECUTE 를 부여받는다. 빈 search_path 로 모든 객체를 public. 로
--   스키마 한정해 search_path 오염 공격을 막는다. 모든 테이블 RLS ON + anon/authenticated REVOKE +
--   client policy 0.
--
-- 왜 append-only 트리거인가: service_role 유출/실수로도 immutable 사람 제출(submissions)과 감사
--   로그(consensus_events)를 UPDATE/DELETE/TRUNCATE 하지 못하게 실행 역할과 무관한 트리거로
--   강제한다(0A000).
--
-- 왜 initial_gt 만 비교하나(설계 §5.2): 두 사람의 immutable 최초 제출만 결정론적으로 비교한다.
--   AI/VLM 이후 값은 합의 입력이 아니라 이 스키마에 컬럼조차 두지 않는다.
--
-- 왜 canary 를 삭제하지 않나(설계 §6.3): 가역 canary(사람 제출을 검증 뒤 삭제)는 쓰지 않는다.
--   cohort_kind=live|canary + cohort_id 로 격리하고, 종료는 cohort status=closed(row 삭제 아님).
--
-- 에러 계약(API 매핑용 안정 SQLSTATE):
--   22023 invalid_parameter_value → 400  (enum/uuid/date/cursor/note/array 형식 오류)
--   P0002 no_data_found           → 404  (clip/slot/cohort/group 없음)
--   PT403 reviewer_forbidden      → 404  (본인 slot 아님 — API 는 404 로 은닉)
--   PT409 stale_state             → 409  (stale digest / owner resolve optimistic concurrency)
--   PT410 already_submitted       → 409  (같은 reviewer 중복/두 번째 제출)
--   PT423 slot_in_use             → 409  (다른 탭이 lease 보유)
--   PT424 stale_lease             → 410  (lease 만료/토큰 불일치)
--   PT425 group_invariant         → 409  (활성 2인 아님 / 카메라 중복 / 미승인 라벨러)
--   PT426 not_conflict            → 409  (conflict 아닌 consensus 를 owner resolve)
--   PT427 cohort_closed           → 410  (canary cohort 종료/미존재)
--   0A000 feature_not_supported   → append-only 위반
--
-- ⏳ production 미적용. 구현·테스트 후 owner 검토 경계에서 멈춘다(계획 Global Constraints).
-- migration apply·rollback probe 실행은 Task 8(owner 승인) 소관이다.

BEGIN;

-- ══════════════════════════════════════════════════════════════════
-- 1. review group / member / camera (설계 §2·§6)
-- ══════════════════════════════════════════════════════════════════
-- 활성 그룹은 정확히 2인, 카메라는 동시에 하나의 활성 그룹에만 속한다(관리 RPC + 부분 유니크).
CREATE TABLE public.motion_labeling_review_groups (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL UNIQUE CHECK (length(btrim(name)) BETWEEN 1 AND 80),
  active boolean NOT NULL DEFAULT true,
  created_by uuid NOT NULL REFERENCES auth.users(id),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

COMMENT ON TABLE public.motion_labeling_review_groups IS
  '이중 블라인드 라벨러 그룹. 활성 그룹은 정확히 2인(관리 RPC 강제). owner 는 그룹원이 아니다.';

CREATE TABLE public.motion_labeling_review_group_members (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  group_id uuid NOT NULL REFERENCES public.motion_labeling_review_groups(id),
  user_id uuid NOT NULL REFERENCES auth.users(id),
  assigned_by uuid NOT NULL REFERENCES auth.users(id),
  assigned_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  ended_at timestamptz
);
-- 한 사용자는 동시에 하나의 활성 그룹에만 속한다(설계 §2).
CREATE UNIQUE INDEX uq_motion_review_member_active
  ON public.motion_labeling_review_group_members (user_id)
  WHERE ended_at IS NULL;
CREATE INDEX idx_motion_review_member_group
  ON public.motion_labeling_review_group_members (group_id, ended_at);

CREATE TABLE public.motion_labeling_review_group_cameras (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  group_id uuid NOT NULL REFERENCES public.motion_labeling_review_groups(id),
  camera_id uuid NOT NULL REFERENCES public.cameras(id),
  assigned_by uuid NOT NULL REFERENCES auth.users(id),
  assigned_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  ended_at timestamptz
);
-- 한 카메라는 동시에 하나의 활성 그룹에만 속한다(설계 §2).
CREATE UNIQUE INDEX uq_motion_review_camera_active
  ON public.motion_labeling_review_group_cameras (camera_id)
  WHERE ended_at IS NULL;
CREATE INDEX idx_motion_review_camera_group
  ON public.motion_labeling_review_group_cameras (group_id, ended_at);

-- ══════════════════════════════════════════════════════════════════
-- 2. canary cohort (설계 §6.3)
-- ══════════════════════════════════════════════════════════════════
CREATE TABLE public.motion_blind_review_cohorts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  kind text NOT NULL DEFAULT 'canary' CHECK (kind IN ('canary')),
  status text NOT NULL DEFAULT 'open' CHECK (status IN ('open','closed')),
  label text CHECK (label IS NULL OR length(btrim(label)) BETWEEN 1 AND 80),
  group_id uuid REFERENCES public.motion_labeling_review_groups(id),
  created_by uuid NOT NULL REFERENCES auth.users(id),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  closed_at timestamptz,
  CHECK ((status = 'open' AND closed_at IS NULL)
      OR (status = 'closed' AND closed_at IS NOT NULL))
);

COMMENT ON TABLE public.motion_blind_review_cohorts IS
  '격리 preview canary 묶음. 종료 = status closed(설계 §6.3). row 삭제 금지(트리거).';

-- ══════════════════════════════════════════════════════════════════
-- 3. reviewer 개인 날짜 개방 상태 (설계 §6.4)
-- ══════════════════════════════════════════════════════════════════
-- (group, reviewer) 별 가장 오래 개방된 활동일. browser write path 없음 — RPC 만 초기화/후진.
CREATE TABLE public.motion_labeling_reviewer_progress (
  group_id uuid NOT NULL REFERENCES public.motion_labeling_review_groups(id),
  reviewer_id uuid NOT NULL REFERENCES auth.users(id),
  oldest_unlocked_activity_day date NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (group_id, reviewer_id)
);

-- ══════════════════════════════════════════════════════════════════
-- 4. clip review slot (설계 §6.1) — clip 당 서로 다른 reviewer 2개 snapshot
-- ══════════════════════════════════════════════════════════════════
CREATE TABLE public.motion_clip_review_slots (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  clip_id uuid NOT NULL REFERENCES public.motion_clips(id) ON DELETE RESTRICT,
  group_id uuid NOT NULL REFERENCES public.motion_labeling_review_groups(id),
  reviewer_id uuid NOT NULL REFERENCES auth.users(id),
  cohort_kind text NOT NULL DEFAULT 'live' CHECK (cohort_kind IN ('live','canary')),
  cohort_id uuid REFERENCES public.motion_blind_review_cohorts(id),
  activity_day_kst date NOT NULL,
  lease_token uuid,
  lease_expires_at timestamptz,
  submitted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  -- live 는 cohort_id 없음, canary 는 cohort_id 필수(설계 §6.3).
  CHECK ((cohort_kind = 'live' AND cohort_id IS NULL)
      OR (cohort_kind = 'canary' AND cohort_id IS NOT NULL))
);

-- slot reviewer uniqueness: 같은 clip 에 같은 reviewer 두 slot 금지(설계 §6.1).
-- live/canary 는 별도 부분 유니크로 나눠 NULL cohort_id 처리를 명확히 한다.
CREATE UNIQUE INDEX uq_motion_review_slot_live
  ON public.motion_clip_review_slots (clip_id, reviewer_id)
  WHERE cohort_kind = 'live';
CREATE UNIQUE INDEX uq_motion_review_slot_canary
  ON public.motion_clip_review_slots (clip_id, reviewer_id, cohort_id)
  WHERE cohort_kind = 'canary';

-- reviewer live 큐: (reviewer, cohort, activity_day, submitted) 로 미제출 최신순 조회.
CREATE INDEX idx_motion_review_slot_live_queue
  ON public.motion_clip_review_slots (reviewer_id, cohort_kind, activity_day_kst, submitted_at);
-- canary scope 조회.
CREATE INDEX idx_motion_review_slot_canary_scope
  ON public.motion_clip_review_slots (cohort_id, reviewer_id, submitted_at);
CREATE INDEX idx_motion_review_slot_clip
  ON public.motion_clip_review_slots (clip_id);
CREATE INDEX idx_motion_review_slot_group
  ON public.motion_clip_review_slots (group_id);

-- ══════════════════════════════════════════════════════════════════
-- 5. immutable blind submission (설계 §6) — reviewer 별 최초 결정
-- ══════════════════════════════════════════════════════════════════
CREATE TABLE public.motion_clip_blind_submissions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slot_id uuid NOT NULL REFERENCES public.motion_clip_review_slots(id) ON DELETE RESTRICT,
  clip_id uuid NOT NULL REFERENCES public.motion_clips(id) ON DELETE RESTRICT,
  group_id uuid NOT NULL REFERENCES public.motion_labeling_review_groups(id),
  reviewer_id uuid NOT NULL REFERENCES auth.users(id),
  cohort_kind text NOT NULL CHECK (cohort_kind IN ('live','canary')),
  cohort_id uuid REFERENCES public.motion_blind_review_cohorts(id),
  decision text NOT NULL CHECK (decision IN ('label','hold','exclude')),
  reason_code text NOT NULL CHECK (reason_code IN ('behavior_data','ambiguous','gecko_absent','capture_error','media_error')),
  initial_gt jsonb,
  note text CHECK (note IS NULL OR char_length(note) <= 2000),
  digest text NOT NULL,
  submitted_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  -- decision/GT shape(설계 §5.2): label 은 jsonb object GT 필수, 비-label 은 GT 없음.
  CHECK (
    (decision = 'label' AND initial_gt IS NOT NULL AND jsonb_typeof(initial_gt) = 'object')
    OR (decision <> 'label' AND initial_gt IS NULL)
  ),
  UNIQUE (slot_id)
);

COMMENT ON TABLE public.motion_clip_blind_submissions IS
  'reviewer 별 immutable 최초 제출. append-only(트리거). 상대 제출은 owner API/비교 서버만 읽는다.';

CREATE INDEX idx_motion_blind_submission_clip
  ON public.motion_clip_blind_submissions (clip_id, cohort_kind, cohort_id);
CREATE INDEX idx_motion_blind_submission_reviewer
  ON public.motion_clip_blind_submissions (reviewer_id, submitted_at);

-- ══════════════════════════════════════════════════════════════════
-- 6. consensus (설계 §3.3·§5) — clip×cohort 당 현재 합의 상태 1건
-- ══════════════════════════════════════════════════════════════════
CREATE TABLE public.motion_clip_consensus (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  clip_id uuid NOT NULL REFERENCES public.motion_clips(id) ON DELETE RESTRICT,
  group_id uuid NOT NULL REFERENCES public.motion_labeling_review_groups(id),
  cohort_kind text NOT NULL DEFAULT 'live' CHECK (cohort_kind IN ('live','canary')),
  cohort_id uuid REFERENCES public.motion_blind_review_cohorts(id),
  status text NOT NULL DEFAULT 'awaiting'
    CHECK (status IN ('awaiting','agreed','conflict','owner_resolved')),
  comparator_version text,
  submission_a uuid REFERENCES public.motion_clip_blind_submissions(id),
  submission_b uuid REFERENCES public.motion_clip_blind_submissions(id),
  final_decision text CHECK (final_decision IN ('label','hold','exclude')),
  final_gt jsonb,
  differing_fields text[] NOT NULL DEFAULT '{}',
  resolution_choice text CHECK (resolution_choice IN ('a','b','new')),
  resolved_by uuid REFERENCES auth.users(id),
  resolved_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

COMMENT ON TABLE public.motion_clip_consensus IS
  'clip×cohort 당 현재 합의 상태 1건(멱등). API pure comparator 결과를 finalize RPC 가 검증 저장.';

-- clip×cohort 당 consensus 유일(중복 consensus 금지, 설계 §5.3).
CREATE UNIQUE INDEX uq_motion_consensus_live
  ON public.motion_clip_consensus (clip_id)
  WHERE cohort_kind = 'live';
CREATE UNIQUE INDEX uq_motion_consensus_canary
  ON public.motion_clip_consensus (clip_id, cohort_id)
  WHERE cohort_kind = 'canary';
-- owner conflict 기본 큐: live conflict 최신순 keyset.
CREATE INDEX idx_motion_consensus_conflict_queue
  ON public.motion_clip_consensus (status, updated_at DESC, clip_id DESC)
  WHERE cohort_kind = 'live';
CREATE INDEX idx_motion_consensus_group
  ON public.motion_clip_consensus (group_id);

-- ══════════════════════════════════════════════════════════════════
-- 7. consensus append-only 감사 이벤트 (설계 §4.5·§6)
-- ══════════════════════════════════════════════════════════════════
CREATE TABLE public.motion_clip_consensus_events (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  clip_id uuid NOT NULL,
  group_id uuid NOT NULL,
  cohort_kind text NOT NULL,
  cohort_id uuid,
  event_type text NOT NULL CHECK (event_type IN ('auto_compared','owner_resolved')),
  actor_id uuid REFERENCES auth.users(id),
  comparator_version text,
  result_status text,
  differing_fields text[],
  before_state jsonb,
  after_state jsonb NOT NULL,
  reason text CHECK (reason IS NULL OR char_length(reason) <= 2000),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

COMMENT ON TABLE public.motion_clip_consensus_events IS
  'Append-only(트리거). 자동 비교 + owner 최종 판정 감사. UPDATE/DELETE/TRUNCATE 금지(0A000).';

CREATE INDEX idx_motion_consensus_events_clip
  ON public.motion_clip_consensus_events (clip_id, created_at DESC);

-- ══════════════════════════════════════════════════════════════════
-- 8. append-only 강제 트리거 (submissions + consensus events)
-- ══════════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION public.fn_block_motion_blind_mutation()
RETURNS trigger LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN
  IF TG_OP IN ('UPDATE', 'DELETE', 'TRUNCATE') THEN
    RAISE EXCEPTION '% is append-only (UPDATE/DELETE/TRUNCATE 금지)', TG_TABLE_NAME
      USING ERRCODE = '0A000';
  END IF;
  RETURN NULL;
END;
$$;

REVOKE ALL ON FUNCTION public.fn_block_motion_blind_mutation() FROM PUBLIC;

DROP TRIGGER IF EXISTS trg_block_motion_blind_submission_mutation
  ON public.motion_clip_blind_submissions;
CREATE TRIGGER trg_block_motion_blind_submission_mutation
  BEFORE UPDATE OR DELETE ON public.motion_clip_blind_submissions
  FOR EACH ROW EXECUTE FUNCTION public.fn_block_motion_blind_mutation();

DROP TRIGGER IF EXISTS trg_block_motion_blind_submission_truncate
  ON public.motion_clip_blind_submissions;
CREATE TRIGGER trg_block_motion_blind_submission_truncate
  BEFORE TRUNCATE ON public.motion_clip_blind_submissions
  FOR EACH STATEMENT EXECUTE FUNCTION public.fn_block_motion_blind_mutation();

DROP TRIGGER IF EXISTS trg_block_motion_consensus_event_mutation
  ON public.motion_clip_consensus_events;
CREATE TRIGGER trg_block_motion_consensus_event_mutation
  BEFORE UPDATE OR DELETE ON public.motion_clip_consensus_events
  FOR EACH ROW EXECUTE FUNCTION public.fn_block_motion_blind_mutation();

DROP TRIGGER IF EXISTS trg_block_motion_consensus_event_truncate
  ON public.motion_clip_consensus_events;
CREATE TRIGGER trg_block_motion_consensus_event_truncate
  BEFORE TRUNCATE ON public.motion_clip_consensus_events
  FOR EACH STATEMENT EXECUTE FUNCTION public.fn_block_motion_blind_mutation();

-- cohort 는 삭제하지 않는다(설계 §6.3): DELETE/TRUNCATE 만 막고 UPDATE(open→closed) 허용.
CREATE OR REPLACE FUNCTION public.fn_block_motion_cohort_delete()
RETURNS trigger LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN
  RAISE EXCEPTION 'motion_blind_review_cohorts is not deletable (close via status)'
    USING ERRCODE = '0A000';
  RETURN NULL;
END;
$$;

REVOKE ALL ON FUNCTION public.fn_block_motion_cohort_delete() FROM PUBLIC;

DROP TRIGGER IF EXISTS trg_block_motion_cohort_delete ON public.motion_blind_review_cohorts;
CREATE TRIGGER trg_block_motion_cohort_delete
  BEFORE DELETE ON public.motion_blind_review_cohorts
  FOR EACH ROW EXECUTE FUNCTION public.fn_block_motion_cohort_delete();

DROP TRIGGER IF EXISTS trg_block_motion_cohort_truncate ON public.motion_blind_review_cohorts;
CREATE TRIGGER trg_block_motion_cohort_truncate
  BEFORE TRUNCATE ON public.motion_blind_review_cohorts
  FOR EACH STATEMENT EXECUTE FUNCTION public.fn_block_motion_cohort_delete();

-- immutable submission: 정의상 append-only 트리거가 UPDATE 를 막지만, 방어적으로 슬롯의
-- submitted_at·lease 외 컬럼은 변하지 않는다.

-- ══════════════════════════════════════════════════════════════════
-- 9. RLS + client write 차단 + service_role 전용 (설계 §7)
-- ══════════════════════════════════════════════════════════════════
ALTER TABLE public.motion_labeling_review_groups ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.motion_labeling_review_groups FROM PUBLIC;
REVOKE ALL ON TABLE public.motion_labeling_review_groups FROM anon;
REVOKE ALL ON TABLE public.motion_labeling_review_groups FROM authenticated;
GRANT ALL ON TABLE public.motion_labeling_review_groups TO service_role;

ALTER TABLE public.motion_labeling_review_group_members ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.motion_labeling_review_group_members FROM PUBLIC;
REVOKE ALL ON TABLE public.motion_labeling_review_group_members FROM anon;
REVOKE ALL ON TABLE public.motion_labeling_review_group_members FROM authenticated;
GRANT ALL ON TABLE public.motion_labeling_review_group_members TO service_role;

ALTER TABLE public.motion_labeling_review_group_cameras ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.motion_labeling_review_group_cameras FROM PUBLIC;
REVOKE ALL ON TABLE public.motion_labeling_review_group_cameras FROM anon;
REVOKE ALL ON TABLE public.motion_labeling_review_group_cameras FROM authenticated;
GRANT ALL ON TABLE public.motion_labeling_review_group_cameras TO service_role;

ALTER TABLE public.motion_blind_review_cohorts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.motion_blind_review_cohorts FROM PUBLIC;
REVOKE ALL ON TABLE public.motion_blind_review_cohorts FROM anon;
REVOKE ALL ON TABLE public.motion_blind_review_cohorts FROM authenticated;
GRANT ALL ON TABLE public.motion_blind_review_cohorts TO service_role;

ALTER TABLE public.motion_labeling_reviewer_progress ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.motion_labeling_reviewer_progress FROM PUBLIC;
REVOKE ALL ON TABLE public.motion_labeling_reviewer_progress FROM anon;
REVOKE ALL ON TABLE public.motion_labeling_reviewer_progress FROM authenticated;
GRANT ALL ON TABLE public.motion_labeling_reviewer_progress TO service_role;

ALTER TABLE public.motion_clip_review_slots ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.motion_clip_review_slots FROM PUBLIC;
REVOKE ALL ON TABLE public.motion_clip_review_slots FROM anon;
REVOKE ALL ON TABLE public.motion_clip_review_slots FROM authenticated;
GRANT ALL ON TABLE public.motion_clip_review_slots TO service_role;

ALTER TABLE public.motion_clip_blind_submissions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.motion_clip_blind_submissions FROM PUBLIC;
REVOKE ALL ON TABLE public.motion_clip_blind_submissions FROM anon;
REVOKE ALL ON TABLE public.motion_clip_blind_submissions FROM authenticated;
GRANT ALL ON TABLE public.motion_clip_blind_submissions TO service_role;

ALTER TABLE public.motion_clip_consensus ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.motion_clip_consensus FROM PUBLIC;
REVOKE ALL ON TABLE public.motion_clip_consensus FROM anon;
REVOKE ALL ON TABLE public.motion_clip_consensus FROM authenticated;
GRANT ALL ON TABLE public.motion_clip_consensus TO service_role;

ALTER TABLE public.motion_clip_consensus_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.motion_clip_consensus_events FROM PUBLIC;
REVOKE ALL ON TABLE public.motion_clip_consensus_events FROM anon;
REVOKE ALL ON TABLE public.motion_clip_consensus_events FROM authenticated;
GRANT ALL ON TABLE public.motion_clip_consensus_events TO service_role;

-- ══════════════════════════════════════════════════════════════════
-- 10. 활동일 경계 helper (설계 §3.1) — 순수 immutable
-- ══════════════════════════════════════════════════════════════════
-- 활동일 D = [D 07:00 KST, D+1 07:00 KST). from 반환.
CREATE OR REPLACE FUNCTION public.fn_motion_activity_day_start(p_day date)
RETURNS timestamptz LANGUAGE sql IMMUTABLE SET search_path = '' AS $$
  SELECT (p_day::timestamp + interval '7 hours') AT TIME ZONE 'Asia/Seoul';
$$;

REVOKE ALL ON FUNCTION public.fn_motion_activity_day_start(date) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_motion_activity_day_start(date) TO service_role;

-- ══════════════════════════════════════════════════════════════════
-- 11. 그룹 관리 RPC (설계 §2·§6·§7) — approved labeler 2인 + 카메라 중복 차단
-- ══════════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION public.fn_manage_motion_review_group(
  p_group_id uuid,
  p_actor_id uuid,
  p_name text,
  p_member_ids uuid[],
  p_camera_ids uuid[]
) RETURNS uuid
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  v_group_id uuid;
  v_uid uuid;
  v_cam uuid;
  v_approved_count integer;
BEGIN
  IF p_name IS NULL OR length(btrim(p_name)) NOT BETWEEN 1 AND 80 THEN
    RAISE EXCEPTION 'invalid group name' USING ERRCODE = '22023';
  END IF;
  -- 활성 그룹은 정확히 2인(설계 §2). reviewer 목록 길이 = 2.
  IF p_member_ids IS NULL OR array_length(p_member_ids, 1) <> 2
     OR p_member_ids[1] = p_member_ids[2] THEN
    RAISE EXCEPTION 'group_invariant: exactly two distinct members' USING ERRCODE = 'PT425';
  END IF;
  IF p_camera_ids IS NULL OR array_length(p_camera_ids, 1) NOT BETWEEN 1 AND 20 THEN
    RAISE EXCEPTION 'invalid camera list length' USING ERRCODE = '22023';
  END IF;

  -- 두 멤버가 approved labeler 인지 확인(설계 §2). labelers = 접근 SOT, application = 승인 상태.
  SELECT count(*) INTO v_approved_count
  FROM unnest(p_member_ids) AS m(user_id)
  WHERE EXISTS (SELECT 1 FROM public.labelers l WHERE l.user_id = m.user_id)
    AND EXISTS (
      SELECT 1 FROM public.labeler_applications a
      WHERE a.user_id = m.user_id AND a.status = 'approved');
  IF v_approved_count <> 2 THEN
    RAISE EXCEPTION 'group_invariant: members must be approved labelers' USING ERRCODE = 'PT425';
  END IF;

  -- 그룹 생성 또는 조회(락).
  IF p_group_id IS NULL THEN
    INSERT INTO public.motion_labeling_review_groups (name, created_by)
    VALUES (btrim(p_name), p_actor_id)
    RETURNING id INTO v_group_id;
  ELSE
    SELECT id INTO v_group_id FROM public.motion_labeling_review_groups
      WHERE id = p_group_id FOR UPDATE;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'review group not found' USING ERRCODE = 'P0002';
    END IF;
    UPDATE public.motion_labeling_review_groups
      SET name = btrim(p_name), active = true, updated_at = clock_timestamp()
      WHERE id = v_group_id;
  END IF;

  -- 다른 활성 그룹에 이미 속한 멤버/카메라는 재배정 불가(부분 유니크와 정합, 설계 §2).
  FOREACH v_uid IN ARRAY p_member_ids LOOP
    IF EXISTS (
      SELECT 1 FROM public.motion_labeling_review_group_members
      WHERE user_id = v_uid AND ended_at IS NULL AND group_id <> v_group_id) THEN
      RAISE EXCEPTION 'group_invariant: member active in another group' USING ERRCODE = 'PT425';
    END IF;
  END LOOP;
  FOREACH v_cam IN ARRAY p_camera_ids LOOP
    IF EXISTS (
      SELECT 1 FROM public.motion_labeling_review_group_cameras
      WHERE camera_id = v_cam AND ended_at IS NULL AND group_id <> v_group_id) THEN
      RAISE EXCEPTION 'group_invariant: camera active in another group' USING ERRCODE = 'PT425';
    END IF;
  END LOOP;

  -- 기존 활성 멤버/카메라 매핑 종료(제출·slot 은 보존, 설계 §6.4). 새 매핑 삽입.
  UPDATE public.motion_labeling_review_group_members
    SET ended_at = clock_timestamp()
    WHERE group_id = v_group_id AND ended_at IS NULL
      AND user_id <> ALL (p_member_ids);
  UPDATE public.motion_labeling_review_group_cameras
    SET ended_at = clock_timestamp()
    WHERE group_id = v_group_id AND ended_at IS NULL
      AND camera_id <> ALL (p_camera_ids);

  FOREACH v_uid IN ARRAY p_member_ids LOOP
    IF NOT EXISTS (
      SELECT 1 FROM public.motion_labeling_review_group_members
      WHERE group_id = v_group_id AND user_id = v_uid AND ended_at IS NULL) THEN
      INSERT INTO public.motion_labeling_review_group_members (group_id, user_id, assigned_by)
      VALUES (v_group_id, v_uid, p_actor_id);
    END IF;
  END LOOP;
  FOREACH v_cam IN ARRAY p_camera_ids LOOP
    IF NOT EXISTS (
      SELECT 1 FROM public.motion_labeling_review_group_cameras
      WHERE group_id = v_group_id AND camera_id = v_cam AND ended_at IS NULL) THEN
      INSERT INTO public.motion_labeling_review_group_cameras (group_id, camera_id, assigned_by)
      VALUES (v_group_id, v_cam, p_actor_id);
    END IF;
  END LOOP;

  RETURN v_group_id;
END;
$$;

-- ══════════════════════════════════════════════════════════════════
-- 12. slot materialization RPC (설계 §6.1·§6.4) — clip 당 reviewer 2 slot
-- ══════════════════════════════════════════════════════════════════
-- p_activity_day = 현재 기준 직전 닫힌 활동일(어제). 30일 보존창 [어제-29, 어제] 전체를
-- 한 번에 eager materialize 한다(설계 §6.4). 그래야 oldest_unlocked 후진이 "clip 없는 날"과
-- "아직 미생성 날"을 혼동하지 않는다. 늦은 clip 도 매 workspace 로드마다 ON CONFLICT DO NOTHING
-- 으로 편입된다. reviewer 의 활동일 개방 gating 은 workspace RPC 의 oldest_unlocked 가 담당한다.
CREATE OR REPLACE FUNCTION public.fn_ensure_motion_review_slots(
  p_reviewer_id uuid,
  p_activity_day date
) RETURNS integer
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  v_group_id uuid;
  v_members uuid[];
  v_from timestamptz;
  v_to timestamptz;
  v_inserted integer := 0;
  v_clip uuid;
  v_activity_day date;
  v_owned_group_id uuid;
  v_live_slot_count integer;
BEGIN
  -- 1) reviewer 의 활성 그룹 하나(설계 §6.1). 없으면 slot 0(미배정 상태).
  SELECT group_id INTO v_group_id
  FROM public.motion_labeling_review_group_members
  WHERE user_id = p_reviewer_id AND ended_at IS NULL
  FOR UPDATE;
  IF NOT FOUND THEN
    RETURN 0;
  END IF;

  -- 2) 활성 approved 멤버 정확히 2인(설계 §2). 멤버 행을 user_id 순으로 잠근 뒤(공통 잠금
  --    순서·deadlock 회피) 별도 문장으로 집계한다. aggregate 문장에는 FOR UPDATE 를 붙일 수
  --    없다(Postgres 런타임 오류: FOR UPDATE is not allowed with aggregate functions) —
  --    그래서 잠금(PERFORM 1 ... FOR UPDATE)과 집계(array_agg)를 분리한다.
  PERFORM 1
  FROM public.motion_labeling_review_group_members
  WHERE group_id = v_group_id AND ended_at IS NULL
  ORDER BY user_id
  FOR UPDATE;

  SELECT array_agg(user_id ORDER BY user_id)
  INTO v_members
  FROM public.motion_labeling_review_group_members
  WHERE group_id = v_group_id AND ended_at IS NULL;

  IF v_members IS NULL OR array_length(v_members, 1) <> 2 THEN
    RAISE EXCEPTION 'group_invariant: active group must have two members' USING ERRCODE = 'PT425';
  END IF;

  -- 3) 30일 보존창 [p_activity_day-29 07:00 KST, (p_activity_day+1) 07:00 KST).
  v_from := public.fn_motion_activity_day_start(p_activity_day - 29);
  v_to := public.fn_motion_activity_day_start(p_activity_day + 1);

  -- 4) 담당 카메라의 창 안 clip 마다 ownership 상태머신을 적용한다(설계 §6.1·§6.4).
  --    live clip 의 최초 group·reviewer pair 는 consensus row 로 불변 고정된다. 카메라나
  --    member 가 바뀌어도 기존 live clip 에 세 번째 slot 을 만들지 않는다. slot 교체는
  --    fn_reassign_motion_review_slot 한 경로만 허용한다(교차 삽입 금지).
  --    공통 잠금 순서: consensus → slots(id ASC). clip 은 id 순으로 처리해 교차 잠금을 줄인다.
  FOR v_clip, v_activity_day IN
    SELECT m.id,
           (m.started_at AT TIME ZONE 'Asia/Seoul' - interval '7 hours')::date
    FROM public.motion_clips m
    JOIN public.motion_labeling_review_group_cameras gc
      ON gc.camera_id = m.camera_id AND gc.group_id = v_group_id AND gc.ended_at IS NULL
    WHERE m.started_at >= v_from AND m.started_at < v_to
    ORDER BY m.id
  LOOP
    -- 4a) live consensus row 잠금/생성 = ownership anchor. 최초 생성한 그룹이 이 clip 을 소유한다.
    SELECT group_id INTO v_owned_group_id
    FROM public.motion_clip_consensus
    WHERE clip_id = v_clip AND cohort_kind = 'live'
    FOR UPDATE;
    IF NOT FOUND THEN
      INSERT INTO public.motion_clip_consensus
        (clip_id, group_id, cohort_kind, cohort_id, status)
      VALUES (v_clip, v_group_id, 'live', NULL, 'awaiting')
      ON CONFLICT (clip_id) WHERE cohort_kind = 'live' DO NOTHING
      RETURNING group_id INTO v_owned_group_id;
      IF v_owned_group_id IS NULL THEN
        -- 동시 ensure 가 먼저 생성했다 → 다시 잠그고 소유 그룹을 읽는다.
        SELECT group_id INTO v_owned_group_id
        FROM public.motion_clip_consensus
        WHERE clip_id = v_clip AND cohort_kind = 'live'
        FOR UPDATE;
      END IF;
    END IF;

    -- 4b) consensus group mismatch: 이 clip 은 다른 그룹이 이미 소유(카메라 이동 후 잔존) →
    --     세 번째 slot 을 만들지 않고 건너뛴다. ownership 은 최초 그룹에 고정된 채로 둔다.
    IF v_owned_group_id IS DISTINCT FROM v_group_id THEN
      CONTINUE;
    END IF;

    -- 4c) 기존 live slot 을 id 순으로 잠그고(공통 잠금 순서) 개수를 센다. 여기서도 aggregate 에
    --     FOR UPDATE 를 붙이지 않고 잠금·집계를 분리한다.
    PERFORM 1
    FROM public.motion_clip_review_slots
    WHERE clip_id = v_clip AND cohort_kind = 'live'
    ORDER BY id
    FOR UPDATE;

    SELECT count(*) INTO v_live_slot_count
    FROM public.motion_clip_review_slots
    WHERE clip_id = v_clip AND cohort_kind = 'live';

    -- 4d) ownership 상태머신: 0 이면 현재 2인 삽입, 2 면 기존 pair 보존, 그 외는 불변식 위반.
    IF v_live_slot_count = 0 THEN
      INSERT INTO public.motion_clip_review_slots
        (clip_id, group_id, reviewer_id, cohort_kind, cohort_id, activity_day_kst)
      SELECT v_clip, v_group_id, mem, 'live', NULL, v_activity_day
      FROM unnest(v_members) AS mem
      ON CONFLICT (clip_id, reviewer_id) WHERE cohort_kind = 'live' DO NOTHING;
      v_inserted := v_inserted + 1;
    ELSIF v_live_slot_count = 2 THEN
      -- 기존 reviewer pair 를 그대로 둔다(교차 삽입·재배정 없음).
      v_inserted := v_inserted + 1;
    ELSE
      RAISE EXCEPTION 'live clip must have zero or two slots' USING ERRCODE = 'PT425';
    END IF;
  END LOOP;

  RETURN v_inserted;
END;
$$;

-- ══════════════════════════════════════════════════════════════════
-- 13. 개인 미제출 큐 RPC (설계 §4·§7) — 본인 slot 최신순 keyset
-- ══════════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION public.fn_list_motion_blind_queue(
  p_reviewer_id uuid,
  p_activity_day date,
  p_cohort_kind text DEFAULT 'live',
  p_cohort_id uuid DEFAULT NULL,
  p_cursor_started_at timestamptz DEFAULT NULL,
  p_cursor_id uuid DEFAULT NULL,
  p_limit integer DEFAULT 31
) RETURNS TABLE (
  clip_id uuid, camera_id uuid, camera_name text, started_at timestamptz,
  duration_sec double precision, media_ready boolean, activity_day_kst date,
  lease_expires_at timestamptz
)
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
BEGIN
  IF p_cohort_kind NOT IN ('live','canary') THEN
    RAISE EXCEPTION 'invalid cohort kind' USING ERRCODE = '22023';
  END IF;
  IF (p_cohort_kind = 'canary') <> (p_cohort_id IS NOT NULL) THEN
    RAISE EXCEPTION 'cohort scope mismatch' USING ERRCODE = '22023';
  END IF;
  -- live 는 활동일 필수(순차 큐). canary 는 cohort 전체를 하루 구분 없이 처리한다(설계 §6.3).
  IF p_cohort_kind = 'live' AND p_activity_day IS NULL THEN
    RAISE EXCEPTION 'live queue requires activity day' USING ERRCODE = '22023';
  END IF;
  IF (p_cursor_started_at IS NULL) <> (p_cursor_id IS NULL) THEN
    RAISE EXCEPTION 'cursor requires both started_at and id' USING ERRCODE = '22023';
  END IF;

  RETURN QUERY
  SELECT
    m.id AS clip_id,
    m.camera_id AS camera_id,
    cam.name AS camera_name,
    m.started_at AS started_at,
    m.duration_sec AS duration_sec,
    (m.r2_key IS NOT NULL) AS media_ready,
    s.activity_day_kst AS activity_day_kst,
    s.lease_expires_at AS lease_expires_at
  FROM public.motion_clip_review_slots s
  JOIN public.motion_clips m ON m.id = s.clip_id
  LEFT JOIN public.cameras cam ON cam.id = m.camera_id
  WHERE s.reviewer_id = p_reviewer_id
    AND s.cohort_kind = p_cohort_kind
    AND (s.cohort_id IS NOT DISTINCT FROM p_cohort_id)
    AND (p_cohort_kind = 'canary' OR s.activity_day_kst = p_activity_day)
    AND s.submitted_at IS NULL
    AND (p_cursor_started_at IS NULL
         OR m.started_at < p_cursor_started_at
         OR (m.started_at = p_cursor_started_at AND m.id < p_cursor_id))
  ORDER BY m.started_at DESC, m.id DESC
  LIMIT LEAST(GREATEST(p_limit, 1), 100);
END;
$$;

-- ══════════════════════════════════════════════════════════════════
-- 14. workspace 집계 RPC (설계 §4·§6.4) — 상대 원문 0, 집계만
-- ══════════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION public.fn_get_motion_blind_workspace(
  p_reviewer_id uuid
) RETURNS TABLE (
  group_id uuid, group_name text,
  priority_activity_day date, oldest_unlocked_activity_day date,
  available_days date[],
  clip_total integer, own_submitted integer, partner_submitted integer,
  agreed_count integer, conflict_count integer, awaiting_count integer,
  late_added_count integer, members jsonb
)
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  v_group_id uuid;
  v_group_name text;
  v_current_day date;
  v_prev_closed date;
  v_floor date;
  v_oldest date;
  v_priority date;
BEGIN
  SELECT g.id, g.name INTO v_group_id, v_group_name
  FROM public.motion_labeling_review_group_members mem
  JOIN public.motion_labeling_review_groups g ON g.id = mem.group_id AND g.active
  WHERE mem.user_id = p_reviewer_id AND mem.ended_at IS NULL
  FOR UPDATE OF mem;
  IF NOT FOUND THEN
    -- 미배정 상태: 집계 없이 group_id NULL 반환(설계 §9 빈 상태).
    RETURN QUERY SELECT NULL::uuid, NULL::text, NULL::date, NULL::date,
      ARRAY[]::date[], 0, 0, 0, 0, 0, 0, 0, '[]'::jsonb;
    RETURN;
  END IF;

  v_current_day := (clock_timestamp() AT TIME ZONE 'Asia/Seoul' - interval '7 hours')::date;
  v_prev_closed := v_current_day - 1;
  v_floor := v_prev_closed - 29;  -- 30일 보존창(설계 §6.4).

  -- 개인 날짜 개방 상태 초기화(첫 진입=직전 닫힌 활동일).
  SELECT rp.oldest_unlocked_activity_day INTO v_oldest
  FROM public.motion_labeling_reviewer_progress rp
  WHERE rp.group_id = v_group_id AND rp.reviewer_id = p_reviewer_id
  FOR UPDATE;
  IF NOT FOUND THEN
    v_oldest := v_prev_closed;
    INSERT INTO public.motion_labeling_reviewer_progress
      (group_id, reviewer_id, oldest_unlocked_activity_day)
    VALUES (v_group_id, p_reviewer_id, v_oldest)
    ON CONFLICT (group_id, reviewer_id) DO NOTHING;
  END IF;

  -- oldest_unlocked 를 미제출 slot 없는 날은 건너뛰며 후진(설계 §6.4). 단조 후진(앞으로 X).
  WHILE v_oldest > v_floor
    AND NOT EXISTS (
      SELECT 1 FROM public.motion_clip_review_slots s
      WHERE s.reviewer_id = p_reviewer_id AND s.cohort_kind = 'live'
        AND s.activity_day_kst = v_oldest AND s.submitted_at IS NULL)
  LOOP
    v_oldest := v_oldest - 1;
  END LOOP;
  UPDATE public.motion_labeling_reviewer_progress rp
    SET oldest_unlocked_activity_day = v_oldest, updated_at = clock_timestamp()
    WHERE rp.group_id = v_group_id AND rp.reviewer_id = p_reviewer_id
      AND rp.oldest_unlocked_activity_day > v_oldest;

  -- 우선 활동일 = [v_oldest, v_prev_closed] 안 미제출 slot 있는 가장 최신 날(늦은 clip 우선).
  SELECT max(s.activity_day_kst) INTO v_priority
  FROM public.motion_clip_review_slots s
  WHERE s.reviewer_id = p_reviewer_id AND s.cohort_kind = 'live'
    AND s.submitted_at IS NULL
    AND s.activity_day_kst BETWEEN v_oldest AND v_prev_closed;

  RETURN QUERY
  WITH days AS (
    SELECT DISTINCT s.activity_day_kst AS d
    FROM public.motion_clip_review_slots s
    WHERE s.reviewer_id = p_reviewer_id AND s.cohort_kind = 'live'
      AND s.submitted_at IS NULL
      AND s.activity_day_kst BETWEEN v_oldest AND v_prev_closed
  ),
  member_counts AS (
    SELECT mem.user_id,
           COALESCE(la.display_name, 'labeler') AS display_name,
           (SELECT count(*) FROM public.motion_clip_review_slots ms
             WHERE ms.group_id = v_group_id AND ms.reviewer_id = mem.user_id
               AND ms.cohort_kind = 'live' AND ms.activity_day_kst = v_priority
               AND ms.submitted_at IS NOT NULL) AS submitted_count
    FROM public.motion_labeling_review_group_members mem
    LEFT JOIN public.labeler_applications la ON la.user_id = mem.user_id
    WHERE mem.group_id = v_group_id AND mem.ended_at IS NULL
  )
  SELECT
    v_group_id, v_group_name, v_priority, v_oldest,
    COALESCE((SELECT array_agg(d ORDER BY d DESC) FROM days), ARRAY[]::date[]),
    (SELECT count(DISTINCT c.clip_id)::integer FROM public.motion_clip_consensus c
       WHERE c.group_id = v_group_id AND c.cohort_kind = 'live'
         AND EXISTS (SELECT 1 FROM public.motion_clip_review_slots s2
           WHERE s2.clip_id = c.clip_id AND s2.reviewer_id = p_reviewer_id
             AND s2.cohort_kind = 'live' AND s2.activity_day_kst = v_priority)),
    (SELECT count(*)::integer FROM public.motion_clip_review_slots s3
       WHERE s3.reviewer_id = p_reviewer_id AND s3.cohort_kind = 'live'
         AND s3.activity_day_kst = v_priority AND s3.submitted_at IS NOT NULL),
    (SELECT count(*)::integer FROM public.motion_clip_review_slots s4
       WHERE s4.group_id = v_group_id AND s4.reviewer_id <> p_reviewer_id
         AND s4.cohort_kind = 'live' AND s4.activity_day_kst = v_priority
         AND s4.submitted_at IS NOT NULL),
    (SELECT count(*)::integer FROM public.motion_clip_consensus c2
       WHERE c2.group_id = v_group_id AND c2.cohort_kind = 'live' AND c2.status = 'agreed'),
    (SELECT count(*)::integer FROM public.motion_clip_consensus c3
       WHERE c3.group_id = v_group_id AND c3.cohort_kind = 'live' AND c3.status = 'conflict'),
    (SELECT count(*)::integer FROM public.motion_clip_consensus c4
       WHERE c4.group_id = v_group_id AND c4.cohort_kind = 'live' AND c4.status = 'awaiting'),
    (SELECT count(*)::integer FROM public.motion_clip_review_slots s5
       WHERE s5.reviewer_id = p_reviewer_id AND s5.cohort_kind = 'live'
         AND s5.submitted_at IS NULL
         AND s5.activity_day_kst > COALESCE(v_priority, v_floor)
         AND s5.activity_day_kst <= v_prev_closed),
    COALESCE((SELECT jsonb_agg(jsonb_build_object(
        'display_name', mc.display_name, 'submitted_count', mc.submitted_count))
      FROM member_counts mc), '[]'::jsonb);
END;
$$;

-- ══════════════════════════════════════════════════════════════════
-- 15. lease claim RPC (설계 §8) — 같은 reviewer 단일 탭 30분 lease
-- ══════════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION public.fn_claim_motion_review_slot(
  p_clip_id uuid,
  p_reviewer_id uuid,
  p_cohort_kind text,
  p_cohort_id uuid,
  p_new_token uuid,
  p_existing_token uuid DEFAULT NULL
) RETURNS TABLE (lease_token uuid, lease_expires_at timestamptz)
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  v_slot public.motion_clip_review_slots%ROWTYPE;
  v_now timestamptz := clock_timestamp();
BEGIN
  IF p_cohort_kind NOT IN ('live','canary') THEN
    RAISE EXCEPTION 'invalid cohort kind' USING ERRCODE = '22023';
  END IF;
  IF (p_cohort_kind = 'canary') <> (p_cohort_id IS NOT NULL) THEN
    RAISE EXCEPTION 'cohort scope mismatch' USING ERRCODE = '22023';
  END IF;
  IF p_new_token IS NULL THEN
    RAISE EXCEPTION 'lease token required' USING ERRCODE = '22023';
  END IF;

  SELECT * INTO v_slot FROM public.motion_clip_review_slots s
    WHERE s.clip_id = p_clip_id AND s.reviewer_id = p_reviewer_id
      AND s.cohort_kind = p_cohort_kind
      AND (s.cohort_id IS NOT DISTINCT FROM p_cohort_id)
    FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'reviewer_forbidden' USING ERRCODE = 'PT403';
  END IF;
  IF v_slot.submitted_at IS NOT NULL THEN
    RAISE EXCEPTION 'already_submitted' USING ERRCODE = 'PT410';
  END IF;

  -- 다른 탭이 아직 유효한 lease 를 다른 토큰으로 보유하면 거부(설계 §8 slot_in_use).
  IF v_slot.lease_token IS NOT NULL
     AND v_slot.lease_expires_at > v_now
     AND v_slot.lease_token <> p_new_token
     AND (p_existing_token IS NULL OR v_slot.lease_token <> p_existing_token) THEN
    RAISE EXCEPTION 'slot_in_use' USING ERRCODE = 'PT423';
  END IF;

  UPDATE public.motion_clip_review_slots
    SET lease_token = p_new_token,
        lease_expires_at = v_now + interval '30 minutes'
    WHERE id = v_slot.id
    RETURNING motion_clip_review_slots.lease_token, motion_clip_review_slots.lease_expires_at
    INTO lease_token, lease_expires_at;
  RETURN NEXT;
END;
$$;

-- ══════════════════════════════════════════════════════════════════
-- 16. 제출 RPC (설계 §5.3) — immutable 최초 제출 + 상대 제출 서버 전달
-- ══════════════════════════════════════════════════════════════════
-- 상대 제출 content 는 service_role 서버에게만 반환한다. 서버가 pure comparator 로 비교 후
-- finalize 를 호출하고, 브라우저에는 {status, differing_fields} 만 남긴다(설계 §5.1).
CREATE OR REPLACE FUNCTION public.fn_submit_motion_blind_review(
  p_clip_id uuid,
  p_reviewer_id uuid,
  p_cohort_kind text,
  p_cohort_id uuid,
  p_decision text,
  p_reason_code text,
  p_initial_gt jsonb,
  p_note text,
  p_lease_token uuid
) RETURNS TABLE (
  own_submission_id uuid, own_digest text, is_duplicate boolean,
  peer_present boolean, peer_submission_id uuid, peer_digest text,
  peer_decision text, peer_reason_code text, peer_initial_gt jsonb, peer_note text
)
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  v_slot public.motion_clip_review_slots%ROWTYPE;
  v_consensus public.motion_clip_consensus%ROWTYPE;
  v_now timestamptz := clock_timestamp();
  v_digest text;
  v_existing public.motion_clip_blind_submissions%ROWTYPE;
  v_new_id uuid;
  v_peer public.motion_clip_blind_submissions%ROWTYPE;
BEGIN
  IF p_cohort_kind NOT IN ('live','canary') THEN
    RAISE EXCEPTION 'invalid cohort kind' USING ERRCODE = '22023';
  END IF;
  IF (p_cohort_kind = 'canary') <> (p_cohort_id IS NOT NULL) THEN
    RAISE EXCEPTION 'cohort scope mismatch' USING ERRCODE = '22023';
  END IF;
  IF p_decision NOT IN ('label','hold','exclude') THEN
    RAISE EXCEPTION 'invalid decision' USING ERRCODE = '22023';
  END IF;
  IF p_reason_code NOT IN ('behavior_data','ambiguous','gecko_absent','capture_error','media_error') THEN
    RAISE EXCEPTION 'invalid reason_code' USING ERRCODE = '22023';
  END IF;
  IF p_note IS NOT NULL AND char_length(p_note) > 2000 THEN
    RAISE EXCEPTION 'note too long' USING ERRCODE = '22023';
  END IF;
  -- decision/GT shape(설계 §5.2).
  IF p_decision = 'label' AND (p_initial_gt IS NULL OR jsonb_typeof(p_initial_gt) <> 'object') THEN
    RAISE EXCEPTION 'label_requires_valid_initial_gt' USING ERRCODE = '22023';
  END IF;
  IF p_decision <> 'label' AND p_initial_gt IS NOT NULL THEN
    RAISE EXCEPTION 'non_label_forbids_initial_gt' USING ERRCODE = '22023';
  END IF;

  -- 공통 잠금 순서(설계 §5·하드닝): 먼저 clip×cohort 의 공유 consensus row 를 잠근다. 두 reviewer
  -- 가 같은 consensus row 에서 경합하므로, 나중에 진입한 트랜잭션은 이 잠금에서 대기하다 먼저 커밋된
  -- 제출을 반드시 본다(peer_present=true). 모든 writer 가 consensus → slot(→ submission) 순서를 공유.
  -- consensus 는 ensure/canary 가 awaiting 으로 미리 만든다(설계 §6.1·§6.3). 없으면 무결성 위반.
  SELECT * INTO v_consensus
  FROM public.motion_clip_consensus c
  WHERE c.clip_id = p_clip_id
    AND c.cohort_kind = p_cohort_kind
    AND (c.cohort_id IS NOT DISTINCT FROM p_cohort_id)
  FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'consensus not found' USING ERRCODE = 'P0002';
  END IF;

  -- 본인 slot 락. 없으면 배정 밖(설계 §7) → PT403(API 404 은닉).
  SELECT * INTO v_slot FROM public.motion_clip_review_slots s
    WHERE s.clip_id = p_clip_id AND s.reviewer_id = p_reviewer_id
      AND s.cohort_kind = p_cohort_kind
      AND (s.cohort_id IS NOT DISTINCT FROM p_cohort_id)
    FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'reviewer_forbidden' USING ERRCODE = 'PT403';
  END IF;

  -- slot 과 consensus 의 그룹이 일치해야 한다(교차 그룹 오염 방지, 설계 §6.1).
  IF v_slot.group_id <> v_consensus.group_id THEN
    RAISE EXCEPTION 'group_invariant: slot/consensus group mismatch' USING ERRCODE = 'PT425';
  END IF;

  -- lease 검증(설계 §8): 토큰 일치 + 미만료. 아니면 stale_lease.
  IF v_slot.lease_token IS NULL OR v_slot.lease_token <> p_lease_token
     OR v_slot.lease_expires_at IS NULL OR v_slot.lease_expires_at <= v_now THEN
    RAISE EXCEPTION 'stale_lease' USING ERRCODE = 'PT424';
  END IF;

  v_digest := md5(
    coalesce(p_decision, '') || '|' || coalesce(p_reason_code, '') || '|' ||
    coalesce(p_initial_gt::text, '') || '|' || coalesce(p_note, ''));

  -- 이미 제출됐으면 멱등 판정(설계 §8): 같은 내용 = 기존 결과 반환, 다른 내용 = PT410.
  SELECT * INTO v_existing FROM public.motion_clip_blind_submissions b
    WHERE b.slot_id = v_slot.id FOR UPDATE;
  IF FOUND THEN
    IF v_existing.digest = v_digest THEN
      own_submission_id := v_existing.id; own_digest := v_existing.digest;
      is_duplicate := true;
    ELSE
      RAISE EXCEPTION 'already_submitted' USING ERRCODE = 'PT410';
    END IF;
  ELSE
    INSERT INTO public.motion_clip_blind_submissions
      (slot_id, clip_id, group_id, reviewer_id, cohort_kind, cohort_id,
       decision, reason_code, initial_gt, note, digest, submitted_at)
    VALUES (v_slot.id, p_clip_id, v_slot.group_id, p_reviewer_id, p_cohort_kind, p_cohort_id,
       p_decision, p_reason_code, p_initial_gt, p_note, v_digest, v_now)
    RETURNING id INTO v_new_id;
    UPDATE public.motion_clip_review_slots
      SET submitted_at = v_now, lease_token = NULL, lease_expires_at = NULL
      WHERE id = v_slot.id;
    own_submission_id := v_new_id; own_digest := v_digest; is_duplicate := false;
  END IF;

  -- 상대 제출(같은 clip×cohort, 다른 reviewer). 있으면 서버가 비교하도록 content 반환.
  SELECT * INTO v_peer FROM public.motion_clip_blind_submissions b
    WHERE b.clip_id = p_clip_id AND b.cohort_kind = p_cohort_kind
      AND (b.cohort_id IS NOT DISTINCT FROM p_cohort_id)
      AND b.reviewer_id <> p_reviewer_id
    ORDER BY b.submitted_at ASC
    LIMIT 1;
  IF FOUND THEN
    peer_present := true; peer_submission_id := v_peer.id; peer_digest := v_peer.digest;
    peer_decision := v_peer.decision; peer_reason_code := v_peer.reason_code;
    peer_initial_gt := v_peer.initial_gt; peer_note := v_peer.note;
  ELSE
    peer_present := false;
  END IF;
  RETURN NEXT;
END;
$$;

-- ══════════════════════════════════════════════════════════════════
-- 17. finalize RPC (설계 §5.3) — digest·버전 검증 후 consensus 멱등 저장
-- ══════════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION public.fn_finalize_motion_blind_consensus(
  p_clip_id uuid,
  p_cohort_kind text,
  p_cohort_id uuid,
  p_submission_a uuid,
  p_submission_b uuid,
  p_digest_a text,
  p_digest_b text,
  p_comparator_version text,
  p_status text,
  p_final_decision text,
  p_final_gt jsonb,
  p_differing_fields text[]
) RETURNS public.motion_clip_consensus
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  v_a public.motion_clip_blind_submissions%ROWTYPE;
  v_b public.motion_clip_blind_submissions%ROWTYPE;
  v_consensus public.motion_clip_consensus%ROWTYPE;
  v_did_transition boolean := false;
BEGIN
  IF p_comparator_version <> 'motion-blind-v1' THEN
    RAISE EXCEPTION 'unknown comparator version' USING ERRCODE = '22023';
  END IF;
  IF p_status NOT IN ('agreed','conflict') THEN
    RAISE EXCEPTION 'invalid finalize status' USING ERRCODE = '22023';
  END IF;

  -- agreed/conflict payload shape(설계 §5.2): agreed=최종 decision 필수(label 이면 GT object 필수),
  -- conflict=owner 판정 대상이라 final decision·GT 는 null 이어야 한다. 파라미터만으로 fail-fast.
  IF p_status = 'agreed' THEN
    IF p_final_decision IS NULL OR p_final_decision NOT IN ('label','hold','exclude') THEN
      RAISE EXCEPTION 'agreed requires final decision' USING ERRCODE = '22023';
    END IF;
    IF p_final_decision = 'label'
       AND (p_final_gt IS NULL OR jsonb_typeof(p_final_gt) <> 'object') THEN
      RAISE EXCEPTION 'agreed label requires final gt object' USING ERRCODE = '22023';
    END IF;
    IF p_final_decision <> 'label' AND p_final_gt IS NOT NULL THEN
      RAISE EXCEPTION 'agreed non-label forbids final gt' USING ERRCODE = '22023';
    END IF;
  ELSE
    IF p_final_decision IS NOT NULL OR p_final_gt IS NOT NULL THEN
      RAISE EXCEPTION 'conflict forbids final decision and gt' USING ERRCODE = '22023';
    END IF;
  END IF;

  -- 공통 잠금 순서(하드닝): consensus → 작은 UUID 제출 → 큰 UUID 제출. 제출을 consensus 보다 먼저
  -- 잠그지 않는다. consensus 는 ensure/canary 가 awaiting 으로 미리 만든다(설계 §6.1·§6.3).
  SELECT * INTO v_consensus FROM public.motion_clip_consensus c
    WHERE c.clip_id = p_clip_id AND c.cohort_kind = p_cohort_kind
      AND (c.cohort_id IS NOT DISTINCT FROM p_cohort_id)
    FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'consensus not found' USING ERRCODE = 'P0002';
  END IF;

  -- 두 제출을 UUID 오름차순으로 잠근 뒤(deadlock 회피) 파라미터 순서대로 로드한다.
  PERFORM 1 FROM public.motion_clip_blind_submissions
    WHERE id IN (p_submission_a, p_submission_b)
    ORDER BY id
    FOR UPDATE;
  SELECT * INTO v_a FROM public.motion_clip_blind_submissions WHERE id = p_submission_a;
  IF NOT FOUND THEN RAISE EXCEPTION 'submission not found' USING ERRCODE = 'P0002'; END IF;
  SELECT * INTO v_b FROM public.motion_clip_blind_submissions WHERE id = p_submission_b;
  IF NOT FOUND THEN RAISE EXCEPTION 'submission not found' USING ERRCODE = 'P0002'; END IF;

  -- digest 검증(설계 §5.3): 불일치=경합/stale → PT409(서버가 재조회).
  IF v_a.digest <> p_digest_a OR v_b.digest <> p_digest_b THEN
    RAISE EXCEPTION 'stale_state' USING ERRCODE = 'PT409';
  END IF;

  -- 교차 객체 identity fail-closed(하드닝): 두 제출은 같은 clip·group·cohort 의 서로 다른
  -- reviewer 제출이어야 한다. 하나라도 위반하면 22023 으로 거부한다(설계 §5.2·§5.3).
  IF p_submission_a = p_submission_b
     OR v_a.clip_id <> p_clip_id
     OR v_b.clip_id <> p_clip_id
     OR v_a.group_id <> v_b.group_id
     OR v_a.group_id <> v_consensus.group_id
     OR v_a.reviewer_id = v_b.reviewer_id
     OR v_a.cohort_kind <> p_cohort_kind
     OR v_b.cohort_kind <> p_cohort_kind
     OR v_a.cohort_id IS DISTINCT FROM p_cohort_id
     OR v_b.cohort_id IS DISTINCT FROM p_cohort_id
  THEN
    RAISE EXCEPTION 'finalize pair identity violation' USING ERRCODE = '22023';
  END IF;

  -- 멱등 전이: awaiting 일 때만 판정 저장 + auto_compared event. 이미 판정된 행(agreed/conflict/
  -- owner_resolved)은 그대로 반환하고 event 를 추가하지 않는다(중복 consensus·중복 event 금지).
  IF v_consensus.status = 'awaiting' THEN
    UPDATE public.motion_clip_consensus
      SET status = p_status, comparator_version = p_comparator_version,
          submission_a = p_submission_a, submission_b = p_submission_b,
          final_decision = p_final_decision, final_gt = p_final_gt,
          differing_fields = COALESCE(p_differing_fields, '{}'),
          updated_at = clock_timestamp()
      WHERE id = v_consensus.id
      RETURNING * INTO v_consensus;
    v_did_transition := true;
  END IF;

  IF v_did_transition THEN
    INSERT INTO public.motion_clip_consensus_events
      (clip_id, group_id, cohort_kind, cohort_id, event_type, actor_id,
       comparator_version, result_status, differing_fields, before_state, after_state)
    VALUES (p_clip_id, v_consensus.group_id, p_cohort_kind, p_cohort_id, 'auto_compared', NULL,
       p_comparator_version, v_consensus.status, v_consensus.differing_fields,
       NULL, to_jsonb(v_consensus));
  END IF;

  RETURN v_consensus;
END;
$$;

-- ══════════════════════════════════════════════════════════════════
-- 18. owner conflict 목록 RPC (설계 §4.5) — live conflict 최신순 keyset
-- ══════════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION public.fn_list_motion_blind_conflicts(
  p_cursor_updated_at timestamptz DEFAULT NULL,
  p_cursor_clip_id uuid DEFAULT NULL,
  p_limit integer DEFAULT 31
) RETURNS TABLE (
  clip_id uuid, camera_name text, started_at timestamptz,
  differing_fields text[], updated_at timestamptz
)
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
BEGIN
  IF (p_cursor_updated_at IS NULL) <> (p_cursor_clip_id IS NULL) THEN
    RAISE EXCEPTION 'cursor requires both updated_at and clip_id' USING ERRCODE = '22023';
  END IF;
  RETURN QUERY
  SELECT c.clip_id, cam.name AS camera_name, m.started_at AS started_at,
         c.differing_fields, c.updated_at
  FROM public.motion_clip_consensus c
  JOIN public.motion_clips m ON m.id = c.clip_id
  LEFT JOIN public.cameras cam ON cam.id = m.camera_id
  WHERE c.cohort_kind = 'live' AND c.status = 'conflict'
    AND (p_cursor_updated_at IS NULL
         OR c.updated_at < p_cursor_updated_at
         OR (c.updated_at = p_cursor_updated_at AND c.clip_id < p_cursor_clip_id))
  ORDER BY c.updated_at DESC, c.clip_id DESC
  LIMIT LEAST(GREATEST(p_limit, 1), 100);
END;
$$;

-- ══════════════════════════════════════════════════════════════════
-- 19. owner resolve RPC (설계 §4.5·§8) — conflict 만, append-only 이력
-- ══════════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION public.fn_resolve_motion_blind_consensus(
  p_clip_id uuid,
  p_cohort_kind text,
  p_cohort_id uuid,
  p_actor_id uuid,
  p_choice text,
  p_final_decision text,
  p_final_gt jsonb,
  p_reason text,
  p_expected_updated_at timestamptz
) RETURNS public.motion_clip_consensus
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  v_consensus public.motion_clip_consensus%ROWTYPE;
  v_before jsonb;
  v_final_decision text;
  v_final_gt jsonb;
BEGIN
  IF p_choice NOT IN ('a','b','new') THEN
    RAISE EXCEPTION 'invalid resolution choice' USING ERRCODE = '22023';
  END IF;
  IF p_reason IS NOT NULL AND char_length(p_reason) > 2000 THEN
    RAISE EXCEPTION 'reason too long' USING ERRCODE = '22023';
  END IF;

  SELECT * INTO v_consensus FROM public.motion_clip_consensus c
    WHERE c.clip_id = p_clip_id AND c.cohort_kind = p_cohort_kind
      AND (c.cohort_id IS NOT DISTINCT FROM p_cohort_id)
    FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'consensus not found' USING ERRCODE = 'P0002';
  END IF;
  -- conflict 만 owner resolve 대상(설계 §4.5). agreed 를 조용히 덮지 않는다.
  IF v_consensus.status <> 'conflict' THEN
    RAISE EXCEPTION 'not_conflict' USING ERRCODE = 'PT426';
  END IF;
  -- optimistic concurrency(설계 §8).
  IF v_consensus.updated_at IS DISTINCT FROM p_expected_updated_at THEN
    RAISE EXCEPTION 'stale_state' USING ERRCODE = 'PT409';
  END IF;

  IF p_choice = 'a' THEN
    SELECT decision, initial_gt INTO v_final_decision, v_final_gt
      FROM public.motion_clip_blind_submissions WHERE id = v_consensus.submission_a;
  ELSIF p_choice = 'b' THEN
    SELECT decision, initial_gt INTO v_final_decision, v_final_gt
      FROM public.motion_clip_blind_submissions WHERE id = v_consensus.submission_b;
  ELSE
    IF p_final_decision NOT IN ('label','hold','exclude') THEN
      RAISE EXCEPTION 'invalid final decision' USING ERRCODE = '22023';
    END IF;
    IF p_final_decision = 'label' AND (p_final_gt IS NULL OR jsonb_typeof(p_final_gt) <> 'object') THEN
      RAISE EXCEPTION 'label_requires_valid_initial_gt' USING ERRCODE = '22023';
    END IF;
    v_final_decision := p_final_decision;
    v_final_gt := CASE WHEN p_final_decision = 'label' THEN p_final_gt ELSE NULL END;
  END IF;

  v_before := to_jsonb(v_consensus);
  UPDATE public.motion_clip_consensus
    SET status = 'owner_resolved', final_decision = v_final_decision, final_gt = v_final_gt,
        resolution_choice = p_choice, resolved_by = p_actor_id, resolved_at = clock_timestamp(),
        updated_at = clock_timestamp()
    WHERE id = v_consensus.id
    RETURNING * INTO v_consensus;

  -- append-only 이력(overwrite 금지, 설계 §8). 원본 resolution 은 event 로 보존.
  INSERT INTO public.motion_clip_consensus_events
    (clip_id, group_id, cohort_kind, cohort_id, event_type, actor_id,
     result_status, differing_fields, before_state, after_state, reason)
  VALUES (p_clip_id, v_consensus.group_id, p_cohort_kind, p_cohort_id, 'owner_resolved',
     p_actor_id, 'owner_resolved', v_consensus.differing_fields, v_before,
     to_jsonb(v_consensus), p_reason);

  RETURN v_consensus;
END;
$$;

-- ══════════════════════════════════════════════════════════════════
-- 20. slot 재배정 RPC (설계 §6.1) — 미제출 slot 만 새 approved 멤버로
-- ══════════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION public.fn_reassign_motion_review_slot(
  p_slot_id uuid,
  p_actor_id uuid,
  p_new_reviewer_id uuid
) RETURNS public.motion_clip_review_slots
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  v_slot public.motion_clip_review_slots%ROWTYPE;
BEGIN
  SELECT * INTO v_slot FROM public.motion_clip_review_slots
    WHERE id = p_slot_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'slot not found' USING ERRCODE = 'P0002';
  END IF;
  -- 이미 제출된 slot 은 이동 불가(제출 보존, 설계 §6.1). 단일 제출을 합의로 승격하는 우회 없음.
  IF v_slot.submitted_at IS NOT NULL THEN
    RAISE EXCEPTION 'already_submitted' USING ERRCODE = 'PT410';
  END IF;
  -- 새 멤버는 approved labeler 여야 한다(설계 §2).
  IF NOT EXISTS (SELECT 1 FROM public.labelers l WHERE l.user_id = p_new_reviewer_id)
     OR NOT EXISTS (SELECT 1 FROM public.labeler_applications a
       WHERE a.user_id = p_new_reviewer_id AND a.status = 'approved') THEN
    RAISE EXCEPTION 'group_invariant: new reviewer must be approved labeler' USING ERRCODE = 'PT425';
  END IF;

  UPDATE public.motion_clip_review_slots
    SET reviewer_id = p_new_reviewer_id, lease_token = NULL, lease_expires_at = NULL
    WHERE id = p_slot_id
    RETURNING * INTO v_slot;
  RETURN v_slot;
END;
$$;

-- ══════════════════════════════════════════════════════════════════
-- 21. canary 관리 RPC (설계 §6.3·§10.2) — 격리 cohort 생성/종료
-- ══════════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION public.fn_manage_motion_blind_canary(
  p_action text,
  p_actor_id uuid,
  p_cohort_id uuid,
  p_label text,
  p_group_id uuid,
  p_clip_ids uuid[],
  p_reviewer_ids uuid[]
) RETURNS uuid
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  v_cohort_id uuid;
  v_clip uuid;
BEGIN
  IF p_action NOT IN ('create','close') THEN
    RAISE EXCEPTION 'invalid canary action' USING ERRCODE = '22023';
  END IF;

  IF p_action = 'close' THEN
    -- 종료 = status closed 로 UPDATE(row 삭제 아님, 설계 §6.3).
    UPDATE public.motion_blind_review_cohorts
      SET status = 'closed', closed_at = clock_timestamp()
      WHERE id = p_cohort_id AND status = 'open'
      RETURNING id INTO v_cohort_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'cohort_closed' USING ERRCODE = 'PT427';
    END IF;
    RETURN v_cohort_id;
  END IF;

  -- create: clip 1..20, reviewer 정확히 2 distinct, group 필수(멤버십 검증에 필요).
  IF p_clip_ids IS NULL OR array_length(p_clip_ids, 1) NOT BETWEEN 1 AND 20 THEN
    RAISE EXCEPTION 'canary clip list must be 1..20' USING ERRCODE = '22023';
  END IF;
  IF p_reviewer_ids IS NULL OR array_length(p_reviewer_ids, 1) <> 2
     OR p_reviewer_ids[1] = p_reviewer_ids[2] THEN
    RAISE EXCEPTION 'group_invariant: canary needs two distinct reviewers' USING ERRCODE = 'PT425';
  END IF;
  IF p_group_id IS NULL THEN
    RAISE EXCEPTION 'canary requires group' USING ERRCODE = '22023';
  END IF;

  -- canary reviewer 2인 자격 강화(하드닝): 둘 다 (a) public.labelers 에 존재 + (b) 승인된
  -- labeler_applications + (c) p_group_id 의 현재 active member(ended_at IS NULL) 여야 한다.
  -- 셋을 모두 만족하는 distinct reviewer 가 정확히 2가 아니면 PT425. live 그룹과 동일한 자격
  -- 기준을 canary 에도 강제한다(설계 §2·§6.3) — 승인만 확인하던 기존 검사를 대체한다.
  IF (SELECT count(*) FROM unnest(p_reviewer_ids) AS r(uid)
      WHERE EXISTS (SELECT 1 FROM public.labelers l WHERE l.user_id = r.uid)
        AND EXISTS (SELECT 1 FROM public.labeler_applications a
          WHERE a.user_id = r.uid AND a.status = 'approved')
        AND EXISTS (SELECT 1 FROM public.motion_labeling_review_group_members gm
          WHERE gm.group_id = p_group_id
            AND gm.user_id = r.uid
            AND gm.ended_at IS NULL)) <> 2 THEN
    RAISE EXCEPTION 'group_invariant: canary reviewers must be approved active group members'
      USING ERRCODE = 'PT425';
  END IF;

  INSERT INTO public.motion_blind_review_cohorts (kind, status, label, group_id, created_by)
  VALUES ('canary', 'open', p_label, p_group_id, p_actor_id)
  RETURNING id INTO v_cohort_id;

  -- clip 당 reviewer 2 canary slot + consensus awaiting(설계 §6.3, live 큐와 분리).
  FOREACH v_clip IN ARRAY p_clip_ids LOOP
    PERFORM 1 FROM public.motion_clips WHERE id = v_clip FOR UPDATE;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'canary clip not found' USING ERRCODE = 'P0002';
    END IF;
    INSERT INTO public.motion_clip_review_slots
      (clip_id, group_id, reviewer_id, cohort_kind, cohort_id, activity_day_kst)
    SELECT v_clip, p_group_id, r.uid, 'canary', v_cohort_id,
           (m.started_at AT TIME ZONE 'Asia/Seoul' - interval '7 hours')::date
    FROM unnest(p_reviewer_ids) AS r(uid)
    JOIN public.motion_clips m ON m.id = v_clip
    ON CONFLICT (clip_id, reviewer_id, cohort_id) WHERE cohort_kind = 'canary' DO NOTHING;
    INSERT INTO public.motion_clip_consensus
      (clip_id, group_id, cohort_kind, cohort_id, status)
    VALUES (v_clip, p_group_id, 'canary', v_cohort_id, 'awaiting')
    ON CONFLICT (clip_id, cohort_id) WHERE cohort_kind = 'canary' DO NOTHING;
  END LOOP;

  RETURN v_cohort_id;
END;
$$;

-- ══════════════════════════════════════════════════════════════════
-- 22. 함수 실행권한 — service_role 전용 (설계 §7)
-- ══════════════════════════════════════════════════════════════════
REVOKE ALL ON FUNCTION public.fn_manage_motion_review_group(uuid, uuid, text, uuid[], uuid[])
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_manage_motion_review_group(uuid, uuid, text, uuid[], uuid[])
  TO service_role;

REVOKE ALL ON FUNCTION public.fn_ensure_motion_review_slots(uuid, date)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_ensure_motion_review_slots(uuid, date) TO service_role;

REVOKE ALL ON FUNCTION public.fn_list_motion_blind_queue(
  uuid, date, text, uuid, timestamptz, uuid, integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_list_motion_blind_queue(
  uuid, date, text, uuid, timestamptz, uuid, integer) TO service_role;

REVOKE ALL ON FUNCTION public.fn_get_motion_blind_workspace(uuid)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_get_motion_blind_workspace(uuid) TO service_role;

REVOKE ALL ON FUNCTION public.fn_claim_motion_review_slot(uuid, uuid, text, uuid, uuid, uuid)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_claim_motion_review_slot(uuid, uuid, text, uuid, uuid, uuid)
  TO service_role;

REVOKE ALL ON FUNCTION public.fn_submit_motion_blind_review(
  uuid, uuid, text, uuid, text, text, jsonb, text, uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_submit_motion_blind_review(
  uuid, uuid, text, uuid, text, text, jsonb, text, uuid) TO service_role;

REVOKE ALL ON FUNCTION public.fn_finalize_motion_blind_consensus(
  uuid, text, uuid, uuid, uuid, text, text, text, text, text, jsonb, text[])
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_finalize_motion_blind_consensus(
  uuid, text, uuid, uuid, uuid, text, text, text, text, text, jsonb, text[]) TO service_role;

REVOKE ALL ON FUNCTION public.fn_list_motion_blind_conflicts(timestamptz, uuid, integer)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_list_motion_blind_conflicts(timestamptz, uuid, integer)
  TO service_role;

REVOKE ALL ON FUNCTION public.fn_resolve_motion_blind_consensus(
  uuid, text, uuid, uuid, text, text, jsonb, text, timestamptz) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_resolve_motion_blind_consensus(
  uuid, text, uuid, uuid, text, text, jsonb, text, timestamptz) TO service_role;

REVOKE ALL ON FUNCTION public.fn_reassign_motion_review_slot(uuid, uuid, uuid)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_reassign_motion_review_slot(uuid, uuid, uuid) TO service_role;

REVOKE ALL ON FUNCTION public.fn_manage_motion_blind_canary(
  text, uuid, uuid, text, uuid, uuid[], uuid[]) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_manage_motion_blind_canary(
  text, uuid, uuid, text, uuid, uuid[], uuid[]) TO service_role;

COMMIT;

-- ══════════════════════════════════════════════════════════════════
-- 검증 (트랜잭션 rollback probe, REPORT/Task 8 참고 — 여기서 실행 안 함)
-- ══════════════════════════════════════════════════════════════════
-- 아래는 preview apply 후 트랜잭션 안에서 검증하고 전량 롤백하는 probe 예시다.
-- <owner>/<labelerA>/<labelerB>/<cam>/<clip*> 대입. 모든 probe 는 ROLLBACK 으로 합성 row 0 복귀.
-- BEGIN;
--   -- probe: 활성 2인 강제 — 1인/3인 배정 시 PT425
--   SELECT public.fn_manage_motion_review_group(NULL, '<owner>'::uuid, 'A그룹',
--     ARRAY['<labelerA>'::uuid], ARRAY['<cam>'::uuid]);                       -- PT425 group_invariant
--   -- probe: 정상 2인 + 카메라
--   SELECT public.fn_manage_motion_review_group(NULL, '<owner>'::uuid, 'A그룹',
--     ARRAY['<labelerA>'::uuid,'<labelerB>'::uuid], ARRAY['<cam>'::uuid]);
--   -- probe: 중복 활성 카메라 배정 → PT425 (다른 그룹에서 같은 카메라)
--   -- probe: slot materialization + wrong reviewer submit → PT403
--   SELECT public.fn_ensure_motion_review_slots('<labelerA>'::uuid, current_date - 1);
--   SELECT public.fn_submit_motion_blind_review('<clip>'::uuid, '<stranger>'::uuid,
--     'live', NULL, 'exclude', 'gecko_absent', NULL, NULL, gen_random_uuid());  -- PT403
--   -- probe: 중복 submit (다른 내용) → PT410
--   -- probe: stale digest finalize → PT409
--   -- probe: 두 제출 → 단일 consensus (중복 consensus 없음)
--   -- probe: append-only — submissions/events UPDATE·DELETE·TRUNCATE → 0A000
--   -- UPDATE public.motion_clip_blind_submissions SET note='x';               -- 0A000
--   -- DELETE FROM public.motion_clip_consensus_events;                        -- 0A000
--   -- probe: owner resolve on agreed → PT426, on conflict → owner_resolved append
--   -- probe: canary slot/submission 이 live 큐/progress/export 에서 제외됨
--   -- probe: cohort 삭제 시도 → 0A000 (close 로만 종료)
-- ROLLBACK;  -- 모든 probe row 0 로 복귀

-- ── 롤백 (별도 forward migration 으로만; 이 파일·기존 파일 편집 금지) ──
-- BEGIN;
-- DROP FUNCTION IF EXISTS public.fn_manage_motion_blind_canary(text, uuid, uuid, text, uuid, uuid[], uuid[]);
-- DROP FUNCTION IF EXISTS public.fn_reassign_motion_review_slot(uuid, uuid, uuid);
-- DROP FUNCTION IF EXISTS public.fn_resolve_motion_blind_consensus(uuid, text, uuid, uuid, text, text, jsonb, text, timestamptz);
-- DROP FUNCTION IF EXISTS public.fn_list_motion_blind_conflicts(timestamptz, uuid, integer);
-- DROP FUNCTION IF EXISTS public.fn_finalize_motion_blind_consensus(uuid, text, uuid, uuid, uuid, text, text, text, text, text, jsonb, text[]);
-- DROP FUNCTION IF EXISTS public.fn_submit_motion_blind_review(uuid, uuid, text, uuid, text, text, jsonb, text, uuid);
-- DROP FUNCTION IF EXISTS public.fn_claim_motion_review_slot(uuid, uuid, text, uuid, uuid, uuid);
-- DROP FUNCTION IF EXISTS public.fn_get_motion_blind_workspace(uuid);
-- DROP FUNCTION IF EXISTS public.fn_list_motion_blind_queue(uuid, date, text, uuid, timestamptz, uuid, integer);
-- DROP FUNCTION IF EXISTS public.fn_ensure_motion_review_slots(uuid, date);
-- DROP FUNCTION IF EXISTS public.fn_manage_motion_review_group(uuid, uuid, text, uuid[], uuid[]);
-- DROP FUNCTION IF EXISTS public.fn_motion_activity_day_start(date);
-- DROP TABLE IF EXISTS public.motion_clip_consensus_events;
-- DROP TABLE IF EXISTS public.motion_clip_consensus;
-- DROP TABLE IF EXISTS public.motion_clip_blind_submissions;
-- DROP TABLE IF EXISTS public.motion_clip_review_slots;
-- DROP TABLE IF EXISTS public.motion_labeling_reviewer_progress;
-- DROP TABLE IF EXISTS public.motion_blind_review_cohorts;
-- DROP TABLE IF EXISTS public.motion_labeling_review_group_cameras;
-- DROP TABLE IF EXISTS public.motion_labeling_review_group_members;
-- DROP TABLE IF EXISTS public.motion_labeling_review_groups;
-- DROP FUNCTION IF EXISTS public.fn_block_motion_cohort_delete();
-- DROP FUNCTION IF EXISTS public.fn_block_motion_blind_mutation();
-- COMMIT;
