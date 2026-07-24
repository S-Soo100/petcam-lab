-- 짧은 오류 영상 visibility-first 운영 재배치 (forward-only)
--
-- 설계 정본: docs/superpowers/specs/2026-07-25-short-clip-visibility-first-design.md
-- 선행 migration: 2026-07-24_short_clip_device_error_retention.sql (수정 금지, 여기서 forward 교체만)
--
-- 무엇을 바꾸나:
--   1) 복구 RPC(fn_restore_short_clip_exclusion): "시스템 격리 해제" 와 "사람 판정 변경" 을 분리한다.
--      기존 계약은 복구 시 motion_clip_labeling_triage 를 owner_decision='label' 로 덮어써 사람의
--      skip/label 판정을 파괴했다(07-25 canary 사고). 이제 시스템 원장(motion_clip_system_exclusions)만
--      restored 로 바꾸고 owner_restored 감사만 남긴다. triage/triage_events 는 절대 건드리지 않는다.
--   2) 앱 가시성: SECURITY DEFINER helper 로 motion_clips SELECT policy 를 교체해 terminal 시스템 격리
--      (quarantined/media_deleted) clip 을 Owner 앱 조회에서 숨긴다. security_invoker view
--      (v_clip_effective_activity) 가 이 policy 를 자동 상속하므로 목록·단건·최신·활동집계가 함께 숨는다.
--
-- 무엇을 안 바꾸나: 07-24 테이블/트리거/삭제 lease RPC, DELETE policy, DELETE_ENABLED 스위치.
-- 물리 삭제(R2)는 이 설계의 운영 범위 밖이며 이 migration 은 어떤 삭제 statement 도 추가하지 않는다.

BEGIN;

-- ── 1. 앱 가시성 helper ─────────────────────────────────────────────
-- Owner 판정 = motion_clips.owner_id = auth.uid() (behavior_logs owner select 와 동일 계약).
-- 가시성 = 해당 clip 에 quarantined/media_deleted 시스템 격리가 없을 때만 true.
-- SECURITY DEFINER 로 client 가 직접 못 읽는 motion_clip_system_exclusions 를 대신 조회하되,
-- boolean 만 반환한다(raw exclusion 컬럼·rule·actor·R2 key 노출 0). 고정 빈 search_path 로
-- 스키마 하이재킹을 막고, auth.uid()/public.* 는 명시 스키마로 호출한다.
CREATE OR REPLACE FUNCTION public.fn_motion_clip_visible_to_owner(
  p_clip_id uuid,
  p_owner_id uuid
) RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
  SELECT
    p_owner_id = auth.uid()
    AND NOT EXISTS (
      SELECT 1
      FROM public.motion_clip_system_exclusions sx
      WHERE sx.clip_id = p_clip_id
        AND sx.state IN ('quarantined','media_deleted')
    );
$$;

-- helper 는 RLS USING 식(querying role=authenticated)에서 실행되므로 authenticated 에 EXECUTE 필요.
-- anon/PUBLIC 은 실행권 없음(앱 인증 사용자 + 신뢰 백엔드만).
REVOKE ALL ON FUNCTION public.fn_motion_clip_visible_to_owner(uuid,uuid)
  FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.fn_motion_clip_visible_to_owner(uuid,uuid)
  TO authenticated, service_role;


-- ── 2. motion_clips SELECT policy 를 helper 로 forward 교체 ──────────
-- 기존 owner-only 조건(owner_id = auth.uid())을 helper 호출로 바꾼다. helper 가 owner 동일성 +
-- terminal 격리 부재를 함께 판정하므로, 자동 격리 clip 이 목록/단건/최신/활동 view 에서 사라진다.
-- DELETE policy 와 service_role 우회는 그대로 둔다. rollback 은 USING 을 owner-only 로 되돌리는
-- forward migration 으로 한다(설계 §8).
ALTER POLICY "own clips select" ON public.motion_clips
  USING (public.fn_motion_clip_visible_to_owner(id, owner_id));


-- ── 3. 복구 RPC forward 교체 — 시스템 격리 해제만, 사람 판정 불변 ────
-- 기존 이름/시그니처(uuid,uuid,text,timestamptz)를 유지해 API 호환. 입력 검증·clip lock·
-- media_deleted PT428·non-quarantined PT409·없음 PT409·활성 lease PT409 는 보존한다.
-- 제거: triage lock/upsert + triage append-only event(사람 판정 파괴 원인).
CREATE OR REPLACE FUNCTION public.fn_restore_short_clip_exclusion(
  p_clip_id uuid,
  p_actor_id uuid,
  p_reason text,
  p_now timestamptz
) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  ex public.motion_clip_system_exclusions%rowtype;
BEGIN
  IF p_clip_id IS NULL OR p_actor_id IS NULL OR p_now IS NULL THEN
    RAISE EXCEPTION 'clip_id, actor_id, now are required' USING ERRCODE = '22023';
  END IF;
  IF p_reason IS NULL OR char_length(p_reason) NOT BETWEEN 10 AND 500 THEN
    RAISE EXCEPTION 'reason must be 10..500 chars' USING ERRCODE = '22023';
  END IF;

  -- 1) motion_clips lock. (사람 판정 원장은 lock/읽기/쓰기 하지 않는다 = 완전 분리.)
  PERFORM 1 FROM public.motion_clips WHERE id = p_clip_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'clip not found' USING ERRCODE = '22023';
  END IF;

  -- 2) exclusion lock + 상태 검증.
  SELECT * INTO ex FROM public.motion_clip_system_exclusions WHERE clip_id = p_clip_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'no system exclusion to restore' USING ERRCODE = 'PT409';
  END IF;
  IF ex.state = 'media_deleted' THEN
    RAISE EXCEPTION 'media already deleted, cannot restore' USING ERRCODE = 'PT428';
  END IF;
  IF ex.state <> 'quarantined' THEN
    RAISE EXCEPTION 'only quarantined clips are restorable (state=%)', ex.state USING ERRCODE = 'PT409';
  END IF;
  -- 삭제 권한(lease)이 남아 있으면 Owner 복구가 worker 물리 삭제와 경합한다. 활성/만료 무관하게
  -- lease 존재 시 state 를 건드리기 전에 복구를 거부한다(fail-closed). worker complete/fail 회수 후만 복구.
  IF ex.delete_lease_token IS NOT NULL THEN
    RAISE EXCEPTION 'delete lease active, cannot restore while a delete grant exists'
      USING ERRCODE = 'PT409';
  END IF;

  -- 3) 시스템 원장만 restored + lease/deadline clear + actor/사유 기록.
  UPDATE public.motion_clip_system_exclusions
    SET state = 'restored', restored_at = p_now, restored_by = p_actor_id, restore_reason = p_reason,
        delete_after = NULL, delete_lease_token = NULL, delete_lease_expires_at = NULL,
        delete_worker_host = NULL, updated_at = clock_timestamp()
    WHERE id = ex.id;

  -- 4) 시스템 append-only 감사(사람 판정 event 아님).
  INSERT INTO public.motion_clip_system_exclusion_events (
    exclusion_id, clip_id, event_type, actor_id, worker_host, rule_version, reason_code,
    before_state, after_state
  ) VALUES (
    ex.id, p_clip_id, 'owner_restored', p_actor_id, NULL, ex.rule_version, ex.reason_code,
    jsonb_build_object('state', 'quarantined'),
    jsonb_build_object('state', 'restored')
  );

  RETURN 'restored';
END;
$$;

-- CREATE OR REPLACE 는 기존 권한을 보존하지만, service-role 전용 계약을 명시적으로 재확인한다.
REVOKE ALL ON FUNCTION public.fn_restore_short_clip_exclusion(uuid, uuid, text, timestamptz)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_restore_short_clip_exclusion(uuid, uuid, text, timestamptz)
  TO service_role;

COMMIT;
