-- 짧은 영상 장치 오류 격리·보존 forward migration.
--
-- 설계 정본: docs/superpowers/specs/2026-07-24-short-clip-device-error-retention-design.md
-- 구현계획:   docs/superpowers/plans/2026-07-24-short-clip-device-error-retention.md
--
-- 계약 요약(Task 1):
--   · `duration_sec < candidate_under_sec` 는 "장치 오류 후보" 신호일 뿐 자동 제외 조건이 아니다.
--   · 자동 격리는 카메라별 정책(enabled + round(duration) ∈ auto_exclude_display_seconds)일 때만.
--   · 사람 GT / research attachment 가 있으면 자동 격리하지 않는다(fail-closed).
--   · 상태 원장(motion_clip_system_exclusions)은 현재 상태, event 테이블은 append-only 전이.
--   · R2 삭제는 delete lease(token+만료) 로만 하고, motion_clips/사람 GT 는 절대 삭제하지 않는다.
--   · 모든 테이블 RLS ON + client policy 0, 모든 RPC service_role 전용.
--   · 시스템 자동 판정은 Owner UUID 를 decided_by 로 위조하지 않는다(복구 RPC 만 owner_labeled 를 쓴다).
--
-- forward-only: 이미 적용된 migration 은 수정하지 않는다. 이 파일은 아직 production 미적용이며,
-- Task 2 소비자 가드가 같은 파일 하단에 이어 붙는다.

-- ── 0. 표시 길이 유효성 helper (정책 CHECK 에서 사용) ─────────────────
-- auto_exclude_display_seconds 의 각 초는 0 이상이고 candidate_under_sec 미만이어야 한다.
-- (예: candidate=15 인데 20 을 등록하면 후보 범위를 벗어나 절대 매칭 안 됨 → 오설정 차단.)
-- SQL 함수 + IMMUTABLE 이라 CHECK 제약에서 호출 가능. 빈 배열은 통과(정책 미설정 카메라).
CREATE FUNCTION public.fn_valid_short_clip_seconds(
  p_candidate_under_sec double precision,
  p_seconds integer[]
) RETURNS boolean
LANGUAGE sql IMMUTABLE PARALLEL SAFE
SET search_path = ''
AS $$
  SELECT p_candidate_under_sec > 0
    AND COALESCE(bool_and(s >= 0 AND s < p_candidate_under_sec), true)
  FROM unnest(p_seconds) AS values_(s);
$$;

REVOKE ALL ON FUNCTION public.fn_valid_short_clip_seconds(double precision, integer[])
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_valid_short_clip_seconds(double precision, integer[])
  TO service_role;


-- ── 1. 카메라별 정책 ─────────────────────────────────────────────────
-- 정책 변경은 과거 판정을 재해석하지 않는다. 판정 시점의 rule_version/입력값은 clip 원장에 복사한다.
CREATE TABLE public.camera_short_clip_policies (
  camera_id uuid PRIMARY KEY REFERENCES public.cameras(id) ON DELETE RESTRICT,
  candidate_under_sec double precision NOT NULL CHECK (candidate_under_sec > 0),
  auto_exclude_display_seconds integer[] NOT NULL DEFAULT '{}',
  retention_hours integer NOT NULL DEFAULT 168 CHECK (retention_hours BETWEEN 24 AND 720),
  rule_version text NOT NULL CHECK (char_length(rule_version) BETWEEN 1 AND 100),
  enabled boolean NOT NULL DEFAULT false,
  created_by uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  updated_by uuid NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CHECK (public.fn_valid_short_clip_seconds(candidate_under_sec, auto_exclude_display_seconds))
);

COMMENT ON TABLE public.camera_short_clip_policies IS
  '카메라별 짧은 영상 자동 제외 정책. enabled + round(duration) ∈ auto_exclude_display_seconds 일 때만 격리.';


-- ── 2. 시스템 격리 원장(현재 상태) ──────────────────────────────────
CREATE TABLE public.motion_clip_system_exclusions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  clip_id uuid NOT NULL UNIQUE REFERENCES public.motion_clips(id) ON DELETE RESTRICT,
  camera_id uuid NOT NULL REFERENCES public.cameras(id) ON DELETE RESTRICT,
  state text NOT NULL CHECK (state IN ('candidate','quarantined','restored','media_deleted','deletion_blocked')),
  reason_code text NOT NULL CHECK (reason_code = 'short_device_error'),
  rule_version text NOT NULL,
  observed_duration_sec double precision NOT NULL CHECK (observed_duration_sec >= 0),
  displayed_duration_sec integer NOT NULL CHECK (displayed_duration_sec >= 0),
  detected_at timestamptz NOT NULL,
  quarantined_at timestamptz,
  delete_after timestamptz,
  restored_at timestamptz,
  restored_by uuid,
  restore_reason text,
  media_deleted_at timestamptz,
  delete_lease_token uuid,
  delete_lease_expires_at timestamptz,
  delete_worker_host text,
  delete_result_code text,
  delete_result_fingerprint text,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  -- quarantined/media_deleted 는 반드시 격리 시각 + 삭제 예정일을 가진다(보존 계약).
  CHECK (state NOT IN ('quarantined','media_deleted') OR (quarantined_at IS NOT NULL AND delete_after IS NOT NULL)),
  CHECK (state <> 'media_deleted' OR media_deleted_at IS NOT NULL)
);

COMMENT ON TABLE public.motion_clip_system_exclusions IS
  'clip 별 시스템 자동 제외 현재 상태. Owner 의 motion_clip_labeling_triage.owner_decision 이 우선.';

-- delete worker 는 delete_after 만료 quarantined 를 안정정렬로 claim 한다.
CREATE INDEX idx_motion_clip_system_exclusions_delete_due
  ON public.motion_clip_system_exclusions (state, delete_after)
  WHERE state = 'quarantined';
-- Owner 자동 제외 화면 keyset(detected_at DESC, id DESC).
CREATE INDEX idx_motion_clip_system_exclusions_detected
  ON public.motion_clip_system_exclusions (detected_at DESC, id DESC);


-- ── 3. append-only 전이 이벤트 ──────────────────────────────────────
-- 이벤트는 clip 보다 오래 보존한다(감사 증거). motion_clips CASCADE 를 걸면 append-only 트리거가
-- clip 삭제까지 막으므로 UUID 만 참조하고 ON DELETE RESTRICT.
CREATE TABLE public.motion_clip_system_exclusion_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  exclusion_id uuid NOT NULL REFERENCES public.motion_clip_system_exclusions(id) ON DELETE RESTRICT,
  clip_id uuid NOT NULL REFERENCES public.motion_clips(id) ON DELETE RESTRICT,
  event_type text NOT NULL CHECK (
    event_type IN (
      'candidate_detected','auto_quarantined','owner_restored',
      'delete_claimed','delete_completed','delete_failed','delete_blocked'
    )
  ),
  actor_id uuid,          -- Owner 복구만 사람 actor. 시스템 판정은 NULL(위조 금지).
  worker_host text,       -- 감지/삭제 worker host. 사람 이벤트는 NULL.
  rule_version text NOT NULL,
  reason_code text NOT NULL,
  before_state jsonb,
  after_state jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

COMMENT ON TABLE public.motion_clip_system_exclusion_events IS
  'Append-only. RPC 만 INSERT. UPDATE/DELETE/TRUNCATE 트리거 차단(0A000).';

CREATE INDEX idx_motion_clip_system_exclusion_events_clip
  ON public.motion_clip_system_exclusion_events (clip_id, created_at DESC);

-- append-only 강제: UPDATE/DELETE/TRUNCATE 를 0A000(feature_not_supported) 로 차단.
CREATE FUNCTION public.fn_block_short_clip_exclusion_event_mutation()
RETURNS trigger LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN
  RAISE EXCEPTION 'motion_clip_system_exclusion_events is append-only'
    USING ERRCODE = '0A000';
END;
$$;

REVOKE ALL ON FUNCTION public.fn_block_short_clip_exclusion_event_mutation() FROM PUBLIC;

CREATE TRIGGER trg_block_short_clip_exclusion_event_ud
  BEFORE UPDATE OR DELETE ON public.motion_clip_system_exclusion_events
  FOR EACH ROW EXECUTE FUNCTION public.fn_block_short_clip_exclusion_event_mutation();

CREATE TRIGGER trg_block_short_clip_exclusion_event_truncate
  BEFORE TRUNCATE ON public.motion_clip_system_exclusion_events
  FOR EACH STATEMENT EXECUTE FUNCTION public.fn_block_short_clip_exclusion_event_mutation();


-- ── 4. 내구성 있는 일일 Slack 알림 원장 ─────────────────────────────
-- KST 날짜당 1 카드. claim → (Slack) → complete(sent_at) / release(재시도) 로 at-least-once,
-- 중복 성공 없음.
CREATE TABLE public.short_clip_retention_notifications (
  summary_date_kst date PRIMARY KEY,
  claimed_at timestamptz NOT NULL,
  claim_token uuid NOT NULL,
  sent_at timestamptz,
  worker_host text NOT NULL CHECK (btrim(worker_host) <> '')
);

COMMENT ON TABLE public.short_clip_retention_notifications IS
  '짧은 영상 보존 일일 Slack 카드 내구성 claim(KST 날짜 unique). sent_at 채워지면 재전송 금지.';


-- ── 5. RLS: 모든 테이블 RLS ON + client policy 0 (service_role 만 우회) ──
ALTER TABLE public.camera_short_clip_policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.motion_clip_system_exclusions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.motion_clip_system_exclusion_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.short_clip_retention_notifications ENABLE ROW LEVEL SECURITY;

-- client role 은 테이블 직접 접근 권한 0. 모든 접근은 SECURITY DEFINER RPC 를 통한다.
REVOKE ALL ON TABLE public.camera_short_clip_policies FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.motion_clip_system_exclusions FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.motion_clip_system_exclusion_events FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.short_clip_retention_notifications FROM PUBLIC, anon, authenticated;


-- ── 6. 감지 후보 조회 RPC ───────────────────────────────────────────
-- duration_sec < p_candidate_under_sec 인 clip 을 oldest-first(started_at,id) keyset 으로 반환.
-- exclusion row 가 없거나 아직 candidate 인 것만 포함(quarantined/restored/media_deleted 는 제외).
CREATE FUNCTION public.fn_list_short_clip_detection_candidates(
  p_candidate_under_sec double precision,
  p_cursor_started_at timestamptz DEFAULT NULL,
  p_cursor_id uuid DEFAULT NULL,
  p_limit integer DEFAULT 100
) RETURNS TABLE (
  clip_id uuid, camera_id uuid, camera_name text, started_at timestamptz,
  duration_sec double precision, displayed_duration_sec integer, current_state text
)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
  IF p_candidate_under_sec IS NULL OR p_candidate_under_sec <= 0 THEN
    RAISE EXCEPTION 'candidate_under_sec must be > 0' USING ERRCODE = '22023';
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
    floor(m.duration_sec + 0.5)::integer AS displayed_duration_sec,
    COALESCE(sx.state, 'none') AS current_state
  FROM public.motion_clips m
  LEFT JOIN public.cameras cam ON cam.id = m.camera_id
  LEFT JOIN public.motion_clip_system_exclusions sx ON sx.clip_id = m.id
  WHERE m.duration_sec IS NOT NULL
    AND m.duration_sec < p_candidate_under_sec
    AND (sx.state IS NULL OR sx.state = 'candidate')
    AND (p_cursor_started_at IS NULL
         OR m.started_at > p_cursor_started_at
         OR (m.started_at = p_cursor_started_at AND m.id > p_cursor_id))
  ORDER BY m.started_at ASC, m.id ASC
  LIMIT LEAST(GREATEST(COALESCE(p_limit, 100), 1), 200);
END;
$$;


-- ── 7. DB-정본 감지·격리 판정 RPC ───────────────────────────────────
-- caller 는 clip UUID·now·write 플래그만 넘긴다. camera/duration/표시길이/정책은 DB 가 재도출한다.
-- 반환 route: candidate | quarantined | protected | reused | reused_restored | ineligible.
--   write=false(shadow): 쓰기 없이 "무엇이 될지" 만 계산해 반환.
--   write=true: 현재 상태에서 전이하고 정확히 1 개 event 를 append. 동일 상태 replay 는 event 0(멱등).
CREATE FUNCTION public.fn_record_short_clip_detection(
  p_clip_id uuid,
  p_now timestamptz,
  p_write boolean DEFAULT false
) RETURNS TABLE (route text, exclusion_id uuid, resulting_state text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  m public.motion_clips%rowtype;
  pol public.camera_short_clip_policies%rowtype;
  ex public.motion_clip_system_exclusions%rowtype;
  v_has_policy boolean := false;
  v_has_exclusion boolean := false;
  v_candidate_under double precision;
  v_rule_version text;
  v_retention_hours integer;
  v_displayed integer;
  v_quarantine_match boolean;
  v_protected boolean;
  v_target text;             -- 'quarantined' | 'protected' | 'candidate'
  v_route text;
  v_delete_after timestamptz;
BEGIN
  IF p_clip_id IS NULL OR p_now IS NULL THEN
    RAISE EXCEPTION 'clip_id and now are required' USING ERRCODE = '22023';
  END IF;

  -- lock 순서: motion_clips → exclusion.
  SELECT * INTO m FROM public.motion_clips WHERE id = p_clip_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'clip not found: %', p_clip_id USING ERRCODE = '22023';
  END IF;

  -- 정책(없어도 candidate 는 기록 가능; enabled 매칭만 quarantine 가능).
  SELECT * INTO pol FROM public.camera_short_clip_policies WHERE camera_id = m.camera_id;
  v_has_policy := FOUND;
  v_candidate_under := COALESCE(pol.candidate_under_sec, 15);
  v_rule_version := COALESCE(pol.rule_version, 'short-device-error-v1');
  v_retention_hours := COALESCE(pol.retention_hours, 168);

  -- duration 이 없거나 후보 범위를 벗어나면 대상 아님.
  IF m.duration_sec IS NULL OR m.duration_sec >= v_candidate_under THEN
    RETURN QUERY SELECT 'ineligible'::text, NULL::uuid, 'none'::text;
    RETURN;
  END IF;

  v_displayed := floor(m.duration_sec + 0.5)::integer;

  -- quarantine 시그니처 = enabled 정책 + 표시 길이 매칭.
  v_quarantine_match := v_has_policy
    AND pol.enabled
    AND array_length(pol.auto_exclude_display_seconds, 1) IS NOT NULL
    AND v_displayed = ANY (pol.auto_exclude_display_seconds);

  -- 사람 GT / research attachment 재검사(fail-closed): 있으면 자동 제외 금지.
  SELECT
    EXISTS (SELECT 1 FROM public.motion_clip_labeling_sessions WHERE clip_id = p_clip_id)
    OR EXISTS (SELECT 1 FROM public.motion_clip_review_slots WHERE clip_id = p_clip_id)
    OR EXISTS (SELECT 1 FROM public.motion_clip_blind_submissions WHERE clip_id = p_clip_id)
    OR EXISTS (SELECT 1 FROM public.motion_clip_consensus WHERE clip_id = p_clip_id)
    OR EXISTS (
      SELECT 1 FROM public.motion_clip_labeling_triage
      WHERE clip_id = p_clip_id AND owner_decision = 'label'
    )
    OR EXISTS (SELECT 1 FROM public.behavior_labels WHERE clip_id = p_clip_id)
    OR EXISTS (SELECT 1 FROM public.behavior_logs WHERE clip_id = p_clip_id)
  INTO v_protected;

  -- 목표 상태(현재 상태 무시한 "무엇이 되어야 하는가").
  IF v_quarantine_match AND v_protected THEN
    v_target := 'protected';       -- 격리 대상이지만 보호됨 → deletion_blocked
  ELSIF v_quarantine_match THEN
    v_target := 'quarantined';
  ELSE
    v_target := 'candidate';
  END IF;

  -- 현재 exclusion.
  SELECT * INTO ex FROM public.motion_clip_system_exclusions WHERE clip_id = p_clip_id FOR UPDATE;
  v_has_exclusion := FOUND;

  -- ── shadow(write=false): 쓰기 없이 목표 route 반환 ──
  IF NOT p_write THEN
    RETURN QUERY SELECT v_target,
      CASE WHEN v_has_exclusion THEN ex.id ELSE NULL::uuid END,
      CASE v_target WHEN 'protected' THEN 'deletion_blocked' ELSE v_target END;
    RETURN;
  END IF;

  -- ── write=true: 현재 상태에서 전이 ──
  v_delete_after := p_now + make_interval(hours => v_retention_hours);

  IF v_has_exclusion AND ex.state = 'restored' THEN
    -- 복구된 clip 은 같은 규칙으로 재격리하지 않는다.
    RETURN QUERY SELECT 'reused_restored'::text, ex.id, ex.state;
    RETURN;
  ELSIF v_has_exclusion AND ex.state = 'media_deleted' THEN
    RETURN QUERY SELECT 'reused'::text, ex.id, ex.state;
    RETURN;
  ELSIF v_has_exclusion AND ex.state = 'quarantined' THEN
    RETURN QUERY SELECT 'reused'::text, ex.id, ex.state;  -- 이미 격리(멱등, event 0)
    RETURN;
  ELSIF v_has_exclusion AND ex.state = 'deletion_blocked' THEN
    RETURN QUERY SELECT 'reused'::text, ex.id, ex.state;  -- 보호로 이미 차단(멱등)
    RETURN;
  END IF;

  -- 여기서 v_cur ∈ {none, candidate}.
  IF v_target = 'quarantined' THEN
    IF v_has_exclusion THEN
      UPDATE public.motion_clip_system_exclusions
        SET state = 'quarantined', rule_version = v_rule_version,
            displayed_duration_sec = v_displayed, observed_duration_sec = m.duration_sec,
            quarantined_at = p_now, delete_after = v_delete_after, updated_at = clock_timestamp()
        WHERE id = ex.id;
    ELSE
      INSERT INTO public.motion_clip_system_exclusions (
        clip_id, camera_id, state, reason_code, rule_version,
        observed_duration_sec, displayed_duration_sec, detected_at, quarantined_at, delete_after
      ) VALUES (
        p_clip_id, m.camera_id, 'quarantined', 'short_device_error', v_rule_version,
        m.duration_sec, v_displayed, p_now, p_now, v_delete_after
      ) RETURNING * INTO ex;
    END IF;
    INSERT INTO public.motion_clip_system_exclusion_events (
      exclusion_id, clip_id, event_type, actor_id, worker_host, rule_version, reason_code,
      before_state, after_state
    ) VALUES (
      ex.id, p_clip_id, 'auto_quarantined', NULL, NULL, v_rule_version, 'short_device_error',
      jsonb_build_object('state', CASE WHEN v_has_exclusion THEN 'candidate' ELSE 'none' END),
      jsonb_build_object('state', 'quarantined', 'displayed_duration_sec', v_displayed)
    );
    RETURN QUERY SELECT 'quarantined'::text, ex.id, 'quarantined'::text;
    RETURN;

  ELSIF v_target = 'protected' THEN
    IF v_has_exclusion THEN
      UPDATE public.motion_clip_system_exclusions
        SET state = 'deletion_blocked', rule_version = v_rule_version,
            displayed_duration_sec = v_displayed, observed_duration_sec = m.duration_sec,
            updated_at = clock_timestamp()
        WHERE id = ex.id;
    ELSE
      INSERT INTO public.motion_clip_system_exclusions (
        clip_id, camera_id, state, reason_code, rule_version,
        observed_duration_sec, displayed_duration_sec, detected_at
      ) VALUES (
        p_clip_id, m.camera_id, 'deletion_blocked', 'short_device_error', v_rule_version,
        m.duration_sec, v_displayed, p_now
      ) RETURNING * INTO ex;
    END IF;
    INSERT INTO public.motion_clip_system_exclusion_events (
      exclusion_id, clip_id, event_type, actor_id, worker_host, rule_version, reason_code,
      before_state, after_state
    ) VALUES (
      ex.id, p_clip_id, 'delete_blocked', NULL, NULL, v_rule_version, 'short_device_error',
      jsonb_build_object('state', CASE WHEN v_has_exclusion THEN 'candidate' ELSE 'none' END),
      jsonb_build_object('state', 'deletion_blocked', 'reason', 'protected_attachment')
    );
    RETURN QUERY SELECT 'protected'::text, ex.id, 'deletion_blocked'::text;
    RETURN;

  ELSE  -- v_target = 'candidate'
    IF v_has_exclusion THEN
      -- 이미 candidate → 멱등, event 0.
      RETURN QUERY SELECT 'reused'::text, ex.id, 'candidate'::text;
      RETURN;
    END IF;
    INSERT INTO public.motion_clip_system_exclusions (
      clip_id, camera_id, state, reason_code, rule_version,
      observed_duration_sec, displayed_duration_sec, detected_at
    ) VALUES (
      p_clip_id, m.camera_id, 'candidate', 'short_device_error', v_rule_version,
      m.duration_sec, v_displayed, p_now
    ) RETURNING * INTO ex;
    INSERT INTO public.motion_clip_system_exclusion_events (
      exclusion_id, clip_id, event_type, actor_id, worker_host, rule_version, reason_code,
      before_state, after_state
    ) VALUES (
      ex.id, p_clip_id, 'candidate_detected', NULL, NULL, v_rule_version, 'short_device_error',
      jsonb_build_object('state', 'none'),
      jsonb_build_object('state', 'candidate', 'displayed_duration_sec', v_displayed)
    );
    RETURN QUERY SELECT 'candidate'::text, ex.id, 'candidate'::text;
    RETURN;
  END IF;
END;
$$;


-- ── 8. Owner 복구 RPC (triage label 복귀 + 시스템 restored 를 한 트랜잭션) ──
-- quarantined 만 복구 가능. media_deleted 는 PT428, 그 외(none/candidate/restored/blocked)는 PT409.
-- lock 순서: motion_clips → motion_clip_labeling_triage → motion_clip_system_exclusions.
CREATE FUNCTION public.fn_restore_short_clip_exclusion(
  p_clip_id uuid,
  p_actor_id uuid,
  p_reason text,
  p_now timestamptz
) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  ex public.motion_clip_system_exclusions%rowtype;
  tri public.motion_clip_labeling_triage%rowtype;
  v_before_triage jsonb;
BEGIN
  IF p_clip_id IS NULL OR p_actor_id IS NULL OR p_now IS NULL THEN
    RAISE EXCEPTION 'clip_id, actor_id, now are required' USING ERRCODE = '22023';
  END IF;
  IF p_reason IS NULL OR char_length(p_reason) NOT BETWEEN 10 AND 500 THEN
    RAISE EXCEPTION 'reason must be 10..500 chars' USING ERRCODE = '22023';
  END IF;

  -- 1) motion_clips lock.
  PERFORM 1 FROM public.motion_clips WHERE id = p_clip_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'clip not found' USING ERRCODE = '22023';
  END IF;

  -- 2) triage lock(있으면).
  SELECT * INTO tri FROM public.motion_clip_labeling_triage WHERE clip_id = p_clip_id FOR UPDATE;
  v_before_triage := CASE
    WHEN FOUND THEN jsonb_build_object('owner_decision', tri.owner_decision)
    ELSE jsonb_build_object('owner_decision', NULL)
  END;

  -- 3) exclusion lock + 상태 검증.
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

  -- 4) triage upsert → owner_decision='label'(Owner actor/사유). 시스템은 이 경로로만 owner_labeled.
  INSERT INTO public.motion_clip_labeling_triage (
    clip_id, owner_decision, decided_by, decided_at, decision_note, created_at, updated_at
  ) VALUES (
    p_clip_id, 'label', p_actor_id, p_now, p_reason, p_now, p_now
  )
  ON CONFLICT (clip_id) DO UPDATE SET
    owner_decision = 'label', decided_by = p_actor_id, decided_at = p_now,
    decision_note = EXCLUDED.decision_note, updated_at = p_now;

  -- 5) triage append-only 감사.
  INSERT INTO public.motion_clip_labeling_triage_events (
    clip_id, event_type, actor_id, before_state, after_state, reason
  ) VALUES (
    p_clip_id, 'owner_labeled', p_actor_id, v_before_triage,
    jsonb_build_object('owner_decision', 'label'), p_reason
  );

  -- 6) 시스템 원장 restored + lease/deadline clear + actor/사유 기록.
  UPDATE public.motion_clip_system_exclusions
    SET state = 'restored', restored_at = p_now, restored_by = p_actor_id, restore_reason = p_reason,
        delete_after = NULL, delete_lease_token = NULL, delete_lease_expires_at = NULL,
        delete_worker_host = NULL, updated_at = clock_timestamp()
    WHERE id = ex.id;

  -- 7) 시스템 append-only 감사.
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


-- ── 9. fail-closed R2 삭제 lease RPC ────────────────────────────────
-- delete_after 만료 quarantined 를 SKIP LOCKED 로 claim. 보호 대상/active job 재검사 후 통과분만
-- 15분 lease 발급. 반환은 exclusion_id/clip_id/r2_key/lease_token 만(비밀 없음). blank r2_key 제외.
CREATE FUNCTION public.fn_claim_short_clip_media_deletions(
  p_limit integer,
  p_worker_host text,
  p_now timestamptz
) RETURNS TABLE (exclusion_id uuid, clip_id uuid, r2_key text, lease_token uuid)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  r record;
  v_protected boolean;
  v_token uuid;
BEGIN
  IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 30 THEN
    RAISE EXCEPTION 'p_limit out of range (1..30)' USING ERRCODE = '22023';
  END IF;
  IF p_worker_host IS NULL OR btrim(p_worker_host) = '' THEN
    RAISE EXCEPTION 'p_worker_host must be nonblank' USING ERRCODE = '22023';
  END IF;

  FOR r IN
    SELECT e.id AS excl_id, e.clip_id AS clip, m.r2_key AS key
    FROM public.motion_clip_system_exclusions e
    JOIN public.motion_clips m ON m.id = e.clip_id
    WHERE e.state = 'quarantined'
      AND e.delete_after IS NOT NULL
      AND e.delete_after <= p_now
      AND m.r2_key IS NOT NULL
      AND btrim(m.r2_key) <> ''
    ORDER BY e.delete_after ASC, e.id ASC
    FOR UPDATE OF e SKIP LOCKED
    LIMIT p_limit
  LOOP
    -- 보호 재검사: 사람 GT / research attachment / active machine job.
    -- (RETURNS TABLE 의 출력 변수 clip_id 와 충돌하지 않도록 서브쿼리 테이블을 alias 로 한정한다.)
    SELECT
      EXISTS (SELECT 1 FROM public.motion_clip_labeling_sessions ls WHERE ls.clip_id = r.clip)
      OR EXISTS (SELECT 1 FROM public.motion_clip_review_slots rs WHERE rs.clip_id = r.clip)
      OR EXISTS (SELECT 1 FROM public.motion_clip_blind_submissions bs WHERE bs.clip_id = r.clip)
      OR EXISTS (SELECT 1 FROM public.motion_clip_consensus mc WHERE mc.clip_id = r.clip)
      OR EXISTS (
        SELECT 1 FROM public.motion_clip_labeling_triage tr
        WHERE tr.clip_id = r.clip AND tr.owner_decision = 'label'
      )
      OR EXISTS (SELECT 1 FROM public.behavior_labels bl WHERE bl.clip_id = r.clip)
      OR EXISTS (SELECT 1 FROM public.behavior_logs bg WHERE bg.clip_id = r.clip)
      OR EXISTS (
        SELECT 1 FROM public.clip_vlm_jobs vj
        WHERE vj.clip_id = r.clip AND vj.status IN ('queued','submitted','failed_retryable')
      )
      OR EXISTS (
        SELECT 1 FROM public.python_evidence_jobs pj
        WHERE pj.clip_id = r.clip AND pj.status IN ('queued','processing','failed_retryable')
      )
    INTO v_protected;

    IF v_protected THEN
      UPDATE public.motion_clip_system_exclusions
        SET state = 'deletion_blocked', delete_lease_token = NULL, delete_lease_expires_at = NULL,
            delete_worker_host = NULL, updated_at = clock_timestamp()
        WHERE id = r.excl_id;
      INSERT INTO public.motion_clip_system_exclusion_events (
        exclusion_id, clip_id, event_type, actor_id, worker_host, rule_version, reason_code,
        before_state, after_state
      )
      SELECT r.excl_id, r.clip, 'delete_blocked', NULL, p_worker_host, e.rule_version, e.reason_code,
        jsonb_build_object('state', 'quarantined'),
        jsonb_build_object('state', 'deletion_blocked', 'reason', 'protected_at_delete')
      FROM public.motion_clip_system_exclusions e WHERE e.id = r.excl_id;
      CONTINUE;
    END IF;

    v_token := gen_random_uuid();
    UPDATE public.motion_clip_system_exclusions
      SET delete_lease_token = v_token,
          delete_lease_expires_at = p_now + make_interval(mins => 15),
          delete_worker_host = p_worker_host,
          updated_at = clock_timestamp()
      WHERE id = r.excl_id;
    INSERT INTO public.motion_clip_system_exclusion_events (
      exclusion_id, clip_id, event_type, actor_id, worker_host, rule_version, reason_code,
      before_state, after_state
    )
    SELECT r.excl_id, r.clip, 'delete_claimed', NULL, p_worker_host, e.rule_version, e.reason_code,
      jsonb_build_object('state', 'quarantined'),
      jsonb_build_object('state', 'quarantined', 'lease', 'granted')
    FROM public.motion_clip_system_exclusions e WHERE e.id = r.excl_id;

    exclusion_id := r.excl_id;
    clip_id := r.clip;
    r2_key := r.key;
    lease_token := v_token;
    RETURN NEXT;
  END LOOP;
END;
$$;


-- ── 10. 삭제 완료/실패 RPC (lease 검증) ─────────────────────────────
-- complete: 정확한 exclusion + lease token + 미만료 lease 일 때만 media_deleted 로 원자 전환 + 1 event.
CREATE FUNCTION public.fn_complete_short_clip_media_delete(
  p_exclusion_id uuid,
  p_lease_token uuid,
  p_result_fingerprint text,
  p_now timestamptz
) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  ex public.motion_clip_system_exclusions%rowtype;
BEGIN
  IF p_exclusion_id IS NULL OR p_lease_token IS NULL OR p_now IS NULL THEN
    RAISE EXCEPTION 'exclusion_id, lease_token, now are required' USING ERRCODE = '22023';
  END IF;
  SELECT * INTO ex FROM public.motion_clip_system_exclusions WHERE id = p_exclusion_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'exclusion not found' USING ERRCODE = '22023';
  END IF;
  -- stale/중복 완료 방어: quarantined + 자기 lease + 미만료 일 때만.
  IF ex.state <> 'quarantined' THEN
    RETURN false;
  END IF;
  IF ex.delete_lease_token IS DISTINCT FROM p_lease_token THEN
    RETURN false;
  END IF;
  IF ex.delete_lease_expires_at IS NULL OR ex.delete_lease_expires_at < p_now THEN
    RETURN false;
  END IF;

  UPDATE public.motion_clip_system_exclusions
    SET state = 'media_deleted', media_deleted_at = p_now,
        delete_result_code = 'deleted', delete_result_fingerprint = p_result_fingerprint,
        delete_lease_token = NULL, delete_lease_expires_at = NULL, updated_at = clock_timestamp()
    WHERE id = p_exclusion_id;
  INSERT INTO public.motion_clip_system_exclusion_events (
    exclusion_id, clip_id, event_type, actor_id, worker_host, rule_version, reason_code,
    before_state, after_state
  ) VALUES (
    ex.id, ex.clip_id, 'delete_completed', NULL, ex.delete_worker_host, ex.rule_version, ex.reason_code,
    jsonb_build_object('state', 'quarantined'),
    jsonb_build_object('state', 'media_deleted')
  );
  RETURN true;
END;
$$;

-- fail: 자기 lease 일 때만 lease clear(quarantined 유지). allowlist 코드 + SHA-256 fingerprint 만 저장.
CREATE FUNCTION public.fn_fail_short_clip_media_delete(
  p_exclusion_id uuid,
  p_lease_token uuid,
  p_result_code text,
  p_now timestamptz
) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  ex public.motion_clip_system_exclusions%rowtype;
BEGIN
  IF p_exclusion_id IS NULL OR p_lease_token IS NULL OR p_now IS NULL THEN
    RAISE EXCEPTION 'exclusion_id, lease_token, now are required' USING ERRCODE = '22023';
  END IF;
  IF p_result_code IS NULL OR p_result_code NOT IN (
    'r2_delete_failed','audit_write_failed','worker_host_mismatch','internal_error'
  ) THEN
    RAISE EXCEPTION 'result_code not allowlisted' USING ERRCODE = '22023';
  END IF;
  SELECT * INTO ex FROM public.motion_clip_system_exclusions WHERE id = p_exclusion_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'exclusion not found' USING ERRCODE = '22023';
  END IF;
  IF ex.state <> 'quarantined' THEN
    RETURN false;
  END IF;
  IF ex.delete_lease_token IS DISTINCT FROM p_lease_token THEN
    RETURN false;
  END IF;

  UPDATE public.motion_clip_system_exclusions
    SET delete_lease_token = NULL, delete_lease_expires_at = NULL, delete_worker_host = NULL,
        delete_result_code = p_result_code,
        delete_result_fingerprint = encode(sha256(convert_to(p_result_code, 'UTF8')), 'hex'),
        updated_at = clock_timestamp()
    WHERE id = p_exclusion_id;
  INSERT INTO public.motion_clip_system_exclusion_events (
    exclusion_id, clip_id, event_type, actor_id, worker_host, rule_version, reason_code,
    before_state, after_state
  ) VALUES (
    ex.id, ex.clip_id, 'delete_failed', NULL, ex.delete_worker_host, ex.rule_version, ex.reason_code,
    jsonb_build_object('state', 'quarantined'),
    jsonb_build_object('state', 'quarantined', 'result_code', p_result_code)
  );
  RETURN true;
END;
$$;


-- ── 11. Owner 자동 제외 목록 RPC (raw 비밀 미노출) ──────────────────
-- 자동 제외 화면용: quarantined/media_deleted/deletion_blocked 만. r2_key/lease/worker/fingerprint/
-- actor UUID 는 노출하지 않고, media_deleted 면 media_ready=false.
CREATE FUNCTION public.fn_list_short_clip_system_exclusions(
  p_cursor_detected_at timestamptz DEFAULT NULL,
  p_cursor_id uuid DEFAULT NULL,
  p_limit integer DEFAULT 50
) RETURNS TABLE (
  clip_id uuid, camera_name text, started_at timestamptz, duration_sec double precision,
  displayed_duration_sec integer, state text, rule_version text,
  quarantined_at timestamptz, delete_after timestamptz, media_deleted_at timestamptz,
  media_ready boolean
)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
  IF (p_cursor_detected_at IS NULL) <> (p_cursor_id IS NULL) THEN
    RAISE EXCEPTION 'cursor requires both detected_at and id' USING ERRCODE = '22023';
  END IF;
  RETURN QUERY
  SELECT
    e.clip_id AS clip_id,
    cam.name AS camera_name,
    m.started_at AS started_at,
    m.duration_sec AS duration_sec,
    e.displayed_duration_sec AS displayed_duration_sec,
    e.state AS state,
    e.rule_version AS rule_version,
    e.quarantined_at AS quarantined_at,
    e.delete_after AS delete_after,
    e.media_deleted_at AS media_deleted_at,
    (m.r2_key IS NOT NULL AND e.state <> 'media_deleted') AS media_ready
  FROM public.motion_clip_system_exclusions e
  JOIN public.motion_clips m ON m.id = e.clip_id
  LEFT JOIN public.cameras cam ON cam.id = e.camera_id
  WHERE e.state IN ('quarantined','media_deleted','deletion_blocked')
    AND (p_cursor_detected_at IS NULL
         OR e.detected_at < p_cursor_detected_at
         OR (e.detected_at = p_cursor_detected_at AND e.id < p_cursor_id))
  ORDER BY e.detected_at DESC, e.id DESC
  LIMIT LEAST(GREATEST(COALESCE(p_limit, 50), 1), 100);
END;
$$;


-- ── 12. 내구성 있는 일일 Slack claim RPC ────────────────────────────
-- claim: 아직 미전송이면 새 token 을 발급(재claim 허용). 이미 sent_at 이면 NULL(중복 성공 차단).
CREATE FUNCTION public.fn_claim_short_clip_retention_notification(
  p_summary_date_kst date,
  p_worker_host text,
  p_now timestamptz
) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  v_token uuid;
BEGIN
  IF p_summary_date_kst IS NULL OR p_now IS NULL THEN
    RAISE EXCEPTION 'summary_date_kst and now are required' USING ERRCODE = '22023';
  END IF;
  IF p_worker_host IS NULL OR btrim(p_worker_host) = '' THEN
    RAISE EXCEPTION 'worker_host must be nonblank' USING ERRCODE = '22023';
  END IF;

  INSERT INTO public.short_clip_retention_notifications (
    summary_date_kst, claimed_at, claim_token, worker_host
  ) VALUES (
    p_summary_date_kst, p_now, gen_random_uuid(), p_worker_host
  )
  ON CONFLICT (summary_date_kst) DO UPDATE
    SET claimed_at = EXCLUDED.claimed_at, claim_token = gen_random_uuid(),
        worker_host = EXCLUDED.worker_host
    WHERE public.short_clip_retention_notifications.sent_at IS NULL
  RETURNING claim_token INTO v_token;

  RETURN v_token;  -- NULL 이면 이미 전송됨(오늘 카드 중복 금지).
END;
$$;

-- complete: 자기 token 이고 아직 미전송이면 sent_at 기록.
CREATE FUNCTION public.fn_complete_short_clip_retention_notification(
  p_summary_date_kst date,
  p_claim_token uuid,
  p_now timestamptz
) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
  UPDATE public.short_clip_retention_notifications
    SET sent_at = p_now
    WHERE summary_date_kst = p_summary_date_kst
      AND claim_token = p_claim_token
      AND sent_at IS NULL;
  RETURN FOUND;
END;
$$;

-- release: Slack 실패 시 claim 해제(다음 사이클 재시도). 이미 전송된 것은 놓아주지 않는다.
CREATE FUNCTION public.fn_release_short_clip_retention_notification(
  p_summary_date_kst date,
  p_claim_token uuid
) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
  DELETE FROM public.short_clip_retention_notifications
    WHERE summary_date_kst = p_summary_date_kst
      AND claim_token = p_claim_token
      AND sent_at IS NULL;
  RETURN FOUND;
END;
$$;


-- ── 13. service_role 전용 grant ─────────────────────────────────────
REVOKE ALL ON FUNCTION public.fn_list_short_clip_detection_candidates(double precision, timestamptz, uuid, integer)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_list_short_clip_detection_candidates(double precision, timestamptz, uuid, integer)
  TO service_role;

REVOKE ALL ON FUNCTION public.fn_record_short_clip_detection(uuid, timestamptz, boolean)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_record_short_clip_detection(uuid, timestamptz, boolean)
  TO service_role;

REVOKE ALL ON FUNCTION public.fn_restore_short_clip_exclusion(uuid, uuid, text, timestamptz)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_restore_short_clip_exclusion(uuid, uuid, text, timestamptz)
  TO service_role;

REVOKE ALL ON FUNCTION public.fn_claim_short_clip_media_deletions(integer, text, timestamptz)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_claim_short_clip_media_deletions(integer, text, timestamptz)
  TO service_role;

REVOKE ALL ON FUNCTION public.fn_complete_short_clip_media_delete(uuid, uuid, text, timestamptz)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_complete_short_clip_media_delete(uuid, uuid, text, timestamptz)
  TO service_role;

REVOKE ALL ON FUNCTION public.fn_fail_short_clip_media_delete(uuid, uuid, text, timestamptz)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_fail_short_clip_media_delete(uuid, uuid, text, timestamptz)
  TO service_role;

REVOKE ALL ON FUNCTION public.fn_list_short_clip_system_exclusions(timestamptz, uuid, integer)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_list_short_clip_system_exclusions(timestamptz, uuid, integer)
  TO service_role;

REVOKE ALL ON FUNCTION public.fn_claim_short_clip_retention_notification(date, text, timestamptz)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_claim_short_clip_retention_notification(date, text, timestamptz)
  TO service_role;

REVOKE ALL ON FUNCTION public.fn_complete_short_clip_retention_notification(date, uuid, timestamptz)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_complete_short_clip_retention_notification(date, uuid, timestamptz)
  TO service_role;

REVOKE ALL ON FUNCTION public.fn_release_short_clip_retention_notification(date, uuid)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_release_short_clip_retention_notification(date, uuid)
  TO service_role;


-- ════════════════════════════════════════════════════════════════════
-- Task 2 — 소비자 가드 + media-deleted 읽기 시맨틱 (forward-only 재정의)
-- ════════════════════════════════════════════════════════════════════
-- 배포된 소비자 함수 본문을 그대로 복사하고, quarantined/media_deleted 를 "신규 소비"에서만
-- 제외하는 술어를 더한다. 기존 사람 GT / blind slot·submission / consensus / VLM·Python Evidence
-- 결과 row 는 조회·변경·삭제하지 않는다. media_deleted 는 r2_key 를 provenance 로 남긴 채
-- 재생 불가(media_ready=false)로 읽는다.
--
-- 관측: 자동 격리는 사람/research attachment 가 없는 clip 에만 일어나므로(보호 술어), blind slot
-- 을 가진 clip 은 애초에 격리되지 않는다. 따라서 blind_queue/ensure_slots 의 제외는 방어적이며
-- 기존 blind 작업을 지우지 않는다. 아래 술어는 전부 신규 선택/자재화 단계에만 적용된다.


-- ── 2.1 Owner 기본 큐 + 라벨러 큐 (fn_list_motion_clip_labeling_queue) ──
-- eligible 에서 quarantined/media_deleted 제외 + media_ready 에 media_deleted 가드.
CREATE OR REPLACE FUNCTION public.fn_list_motion_clip_labeling_queue(
  p_reviewer_id uuid,
  p_is_owner boolean,
  p_state text DEFAULT NULL,
  p_camera_ids uuid[] DEFAULT NULL,
  p_date_from timestamptz DEFAULT NULL,
  p_date_to timestamptz DEFAULT NULL,
  p_media text DEFAULT NULL,
  p_cursor_started_at timestamptz DEFAULT NULL,
  p_cursor_id uuid DEFAULT NULL,
  p_limit integer DEFAULT 31
) RETURNS TABLE (
  clip_id uuid, camera_id uuid, camera_name text, started_at timestamptz,
  duration_sec double precision, media_ready boolean, state text,
  session_stage text, state_updated_at timestamptz
)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
  -- 입력 검증(잘못된 값=22023 → API 400). cursor 는 둘 다 있거나 둘 다 없어야 한다.
  IF p_state IS NOT NULL AND p_state NOT IN ('unreviewed','label','hold','skip') THEN
    RAISE EXCEPTION 'invalid state filter: %', p_state USING ERRCODE = '22023';
  END IF;
  IF p_media IS NOT NULL AND p_media NOT IN ('ready','unavailable') THEN
    RAISE EXCEPTION 'invalid media filter: %', p_media USING ERRCODE = '22023';
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
    (m.r2_key IS NOT NULL AND NOT EXISTS (
      SELECT 1 FROM public.motion_clip_system_exclusions sx
      WHERE sx.clip_id = m.id AND sx.state = 'media_deleted'
    )) AS media_ready,
    COALESCE(t.owner_decision, 'unreviewed') AS state,
    s.stage AS session_stage,
    t.updated_at AS state_updated_at
  FROM public.motion_clips m
  LEFT JOIN public.cameras cam ON cam.id = m.camera_id
  LEFT JOIN public.motion_clip_labeling_triage t ON t.clip_id = m.id
  LEFT JOIN public.motion_clip_labeling_sessions s
    ON s.clip_id = m.id AND s.reviewed_by = p_reviewer_id
  WHERE
    (p_cursor_started_at IS NULL
     OR m.started_at < p_cursor_started_at
     OR (m.started_at = p_cursor_started_at AND m.id < p_cursor_id))
    AND (p_camera_ids IS NULL OR m.camera_id = ANY (p_camera_ids))
    AND (p_date_from IS NULL OR m.started_at >= p_date_from)
    AND (p_date_to IS NULL OR m.started_at < p_date_to)
    AND (p_media IS NULL
         OR (p_media = 'ready' AND m.r2_key IS NOT NULL)
         OR (p_media = 'unavailable' AND m.r2_key IS NULL))
    -- 짧은 영상 자동 제외: quarantined/media_deleted 는 기본 큐(owner·labeler)에서 숨긴다.
    -- 복구되면 state='restored' 라 다시 보인다.
    AND NOT EXISTS (
      SELECT 1 FROM public.motion_clip_system_exclusions sx
      WHERE sx.clip_id = m.id
        AND sx.state IN ('quarantined','media_deleted')
    )
    AND (
      CASE WHEN p_is_owner THEN
        -- owner: 전체. 선택적 state 필터만 적용(설계 §8.1).
        (p_state IS NULL
         OR (p_state = 'unreviewed' AND t.owner_decision IS NULL)
         OR (t.owner_decision = p_state))
      ELSE
        -- labeler: owner_decision='label' + 재생가능 + 본인 completed 없음(설계 §8.2).
        (t.owner_decision = 'label'
         AND m.r2_key IS NOT NULL
         AND NOT EXISTS (
           SELECT 1 FROM public.motion_clip_labeling_sessions cs
           WHERE cs.clip_id = m.id AND cs.reviewed_by = p_reviewer_id
             AND cs.stage = 'completed'))
      END
    )
  ORDER BY m.started_at DESC, m.id DESC
  LIMIT LEAST(GREATEST(p_limit, 1), 100);
END;
$$;


-- ── 2.2 라벨러 live slot 자재화 (fn_ensure_motion_review_slots) ─────
-- 창 안 clip 자재화 대상에서 quarantined/media_deleted 를 제외한다. 기존 consensus/slot 은 건드리지 않는다.
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
  SELECT group_id INTO v_group_id
  FROM public.motion_labeling_review_group_members
  WHERE user_id = p_reviewer_id AND ended_at IS NULL;
  IF NOT FOUND THEN
    RETURN 0;
  END IF;

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

  v_from := public.fn_motion_activity_day_start(p_activity_day - 29);
  v_to := public.fn_motion_activity_day_start(p_activity_day + 1);

  FOR v_clip, v_activity_day IN
    SELECT m.id,
           (m.started_at AT TIME ZONE 'Asia/Seoul' - interval '7 hours')::date
    FROM public.motion_clips m
    JOIN public.motion_labeling_review_group_cameras gc
      ON gc.camera_id = m.camera_id AND gc.group_id = v_group_id AND gc.ended_at IS NULL
    WHERE m.started_at >= v_from AND m.started_at < v_to
      -- 짧은 영상 자동 제외: 격리/삭제된 clip 은 신규 live slot 을 만들지 않는다.
      AND NOT EXISTS (
        SELECT 1 FROM public.motion_clip_system_exclusions sx
        WHERE sx.clip_id = m.id
          AND sx.state IN ('quarantined','media_deleted')
      )
    ORDER BY m.id
  LOOP
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
        SELECT group_id INTO v_owned_group_id
        FROM public.motion_clip_consensus
        WHERE clip_id = v_clip AND cohort_kind = 'live'
        FOR UPDATE;
      END IF;
    END IF;

    IF v_owned_group_id IS DISTINCT FROM v_group_id THEN
      CONTINUE;
    END IF;

    PERFORM 1
    FROM public.motion_clip_review_slots
    WHERE clip_id = v_clip AND cohort_kind = 'live'
    ORDER BY id
    FOR UPDATE;

    SELECT count(*) INTO v_live_slot_count
    FROM public.motion_clip_review_slots
    WHERE clip_id = v_clip AND cohort_kind = 'live';

    IF v_live_slot_count = 0 THEN
      INSERT INTO public.motion_clip_review_slots
        (clip_id, group_id, reviewer_id, cohort_kind, cohort_id, activity_day_kst)
      SELECT v_clip, v_group_id, mem, 'live', NULL, v_activity_day
      FROM unnest(v_members) AS mem
      ON CONFLICT (clip_id, reviewer_id) WHERE cohort_kind = 'live' DO NOTHING;
      v_inserted := v_inserted + 1;
    ELSIF v_live_slot_count = 2 THEN
      v_inserted := v_inserted + 1;
    ELSE
      RAISE EXCEPTION 'live clip must have zero or two slots' USING ERRCODE = 'PT425';
    END IF;
  END LOOP;

  RETURN v_inserted;
END;
$$;


-- ── 2.3 라벨러 blind 큐 media_ready 가드 (fn_list_motion_blind_queue) ──
-- 격리는 보호 술어 때문에 slot 있는 clip 에 안 걸리므로 여기선 media_deleted media_ready 만 방어.
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
    (m.r2_key IS NOT NULL AND NOT EXISTS (
      SELECT 1 FROM public.motion_clip_system_exclusions sx
      WHERE sx.clip_id = m.id AND sx.state = 'media_deleted'
    )) AS media_ready,
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


-- ── 2.4 신규 Canary 자재화 (fn_manage_motion_blind_canary) ─────────
-- create 시 요청 clip 중 quarantined/media_deleted 가 하나라도 있으면 cohort/slot 생성 전에 PT428.
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
    UPDATE public.motion_blind_review_cohorts
      SET status = 'closed', closed_at = clock_timestamp()
      WHERE id = p_cohort_id AND status = 'open'
      RETURNING id INTO v_cohort_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'cohort_closed' USING ERRCODE = 'PT427';
    END IF;
    RETURN v_cohort_id;
  END IF;

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

  -- 짧은 영상 자동 제외: 요청 clip 중 quarantined/media_deleted 가 있으면 cohort/slot 생성 전에 거부.
  IF EXISTS (
    SELECT 1
    FROM unnest(p_clip_ids) AS requested(clip_id)
    JOIN public.motion_clip_system_exclusions sx ON sx.clip_id = requested.clip_id
    WHERE sx.state IN ('quarantined','media_deleted')
  ) THEN
    RAISE EXCEPTION 'system_excluded' USING ERRCODE = 'PT428';
  END IF;

  INSERT INTO public.motion_blind_review_cohorts (kind, status, label, group_id, created_by)
  VALUES ('canary', 'open', p_label, p_group_id, p_actor_id)
  RETURNING id INTO v_cohort_id;

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


-- ── 2.5 Python Evidence claim 후보 제외 (fn_claim_python_evidence_jobs) ──
-- claim 후보 서브쿼리에만 제외 술어를 넣는다. 기존 queued job row 는 update/delete 하지 않는다.
CREATE OR REPLACE FUNCTION public.fn_claim_python_evidence_jobs(p_limit integer, p_worker_host text, p_now timestamptz)
returns setof public.python_evidence_jobs
language plpgsql security invoker set search_path='' as $$
begin
  if p_limit is null or p_limit < 1 or p_limit > 200 then
    raise exception 'p_limit out of range (1..200)' using errcode='22023';
  end if;
  if p_worker_host is null or btrim(p_worker_host) = '' then
    raise exception 'p_worker_host must be nonblank' using errcode='22023';
  end if;
  update public.python_evidence_jobs
    set status='failed_retryable', next_attempt_at=p_now, lease_expires_at=null, updated_at=p_now
    where status='processing' and lease_expires_at is not null and lease_expires_at < p_now;

  return query
  update public.python_evidence_jobs j
    set status='processing',
        claimed_by=p_worker_host,
        claimed_at=p_now,
        lease_expires_at=p_now + interval '15 minutes',
        attempt_count=j.attempt_count + 1,
        updated_at=p_now
    where j.id in (
      select c.id from public.python_evidence_jobs c
      where c.status in ('queued','failed_retryable')
        and (c.next_attempt_at is null or c.next_attempt_at <= p_now)
        -- 짧은 영상 자동 제외: 격리/삭제된 clip 의 job 은 claim 후보에서 뺀다(job row 는 그대로 둔다).
        and not exists (
          select 1 from public.motion_clip_system_exclusions sx
          where sx.clip_id = c.clip_id
            and sx.state in ('quarantined','media_deleted')
        )
      order by priority desc, created_at asc, id asc
      for update skip locked
      limit p_limit
    )
    returning j.*;
end $$;


-- ── 2.6 라벨링 라이브러리 조회 (fn_list_motion_labeling_library) ────
-- 과거 라벨 라이브러리 base 집합에서 quarantined/media_deleted 를 숨긴다(자동 제외 탭으로 이동).
CREATE OR REPLACE FUNCTION public.fn_list_motion_labeling_library(
  p_owner_id uuid,
  p_clip_id uuid DEFAULT NULL,
  p_label_state text DEFAULT NULL,
  p_camera_ids uuid[] DEFAULT NULL,
  p_date_from timestamptz DEFAULT NULL,
  p_date_to timestamptz DEFAULT NULL,
  p_time_from text DEFAULT NULL,
  p_time_to text DEFAULT NULL,
  p_label_source text DEFAULT NULL,
  p_final_decision text DEFAULT NULL,
  p_cursor_started_at timestamptz DEFAULT NULL,
  p_cursor_id uuid DEFAULT NULL,
  p_limit integer DEFAULT 31
) RETURNS TABLE (
  clip_id uuid, camera_id uuid, camera_name text, started_at timestamptz,
  duration_sec double precision, label_state text, label_source text,
  final_decision text, final_gt jsonb
)
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
BEGIN
  IF p_label_state IS NOT NULL
     AND p_label_state NOT IN ('final','awaiting','owner_review','unlabeled','re_review') THEN
    RAISE EXCEPTION 'invalid label state' USING ERRCODE='22023';
  END IF;
  IF p_label_source IS NOT NULL
     AND p_label_source NOT IN ('blind_consensus','owner_legacy','single_legacy','none') THEN
    RAISE EXCEPTION 'invalid label source' USING ERRCODE='22023';
  END IF;
  IF p_final_decision IS NOT NULL AND p_final_decision NOT IN ('label','hold','exclude') THEN
    RAISE EXCEPTION 'invalid final decision' USING ERRCODE='22023';
  END IF;
  IF (p_cursor_started_at IS NULL) <> (p_cursor_id IS NULL) THEN
    RAISE EXCEPTION 'cursor requires both fields' USING ERRCODE='22023';
  END IF;
  IF (p_time_from IS NULL) <> (p_time_to IS NULL)
     OR (p_time_from IS NOT NULL AND p_time_from !~ '^([01][0-9]|2[0-3]):[0-5][0-9]$')
     OR (p_time_to IS NOT NULL AND p_time_to !~ '^([01][0-9]|2[0-3]):[0-5][0-9]$') THEN
    RAISE EXCEPTION 'invalid time range' USING ERRCODE='22023';
  END IF;

  RETURN QUERY
  WITH base AS (
    SELECT m.id, m.camera_id, cam.name AS camera_name, m.started_at, m.duration_sec,
           lc.status AS live_status, lc.final_decision AS live_decision,
           lc.final_gt AS live_gt,
           cy.canary_status, cy.canary_decision, cy.canary_gt,
           ls.reviewed_by AS legacy_reviewer, ls.legacy_gt
    FROM public.motion_clips m
    LEFT JOIN public.cameras cam ON cam.id=m.camera_id
    LEFT JOIN public.motion_clip_consensus lc
      ON lc.clip_id=m.id AND lc.cohort_kind='live'
    LEFT JOIN LATERAL (
      SELECT cc.status AS canary_status, cc.final_decision AS canary_decision,
             cc.final_gt AS canary_gt
      FROM public.motion_clip_consensus cc
      JOIN public.motion_blind_review_cohorts co ON co.id=cc.cohort_id
      WHERE cc.clip_id=m.id AND cc.cohort_kind='canary'
      ORDER BY (co.status='open') DESC, co.created_at DESC, cc.id DESC
      LIMIT 1
    ) cy ON true
    LEFT JOIN LATERAL (
      SELECT s.reviewed_by, COALESCE(s.current_gt,s.initial_gt) AS legacy_gt
      FROM public.motion_clip_labeling_sessions s
      WHERE s.clip_id=m.id AND s.initial_gt IS NOT NULL
      ORDER BY (s.reviewed_by=p_owner_id) DESC, s.updated_at DESC, s.id DESC
      LIMIT 1
    ) ls ON true
    WHERE m.r2_key IS NOT NULL
      -- 짧은 영상 자동 제외: 격리/삭제된 clip 은 라이브러리에서 숨긴다(Owner 자동 제외 탭에서만 노출).
      AND NOT EXISTS (
        SELECT 1 FROM public.motion_clip_system_exclusions sx
        WHERE sx.clip_id=m.id AND sx.state IN ('quarantined','media_deleted')
      )
      AND (p_clip_id IS NULL OR m.id=p_clip_id)
      AND (p_camera_ids IS NULL OR m.camera_id=ANY(p_camera_ids))
      AND (p_date_from IS NULL OR m.started_at>=p_date_from)
      AND (p_date_to IS NULL OR m.started_at<=p_date_to)
      AND (
        p_time_from IS NULL
        OR (
          p_time_from<=p_time_to
          AND to_char(m.started_at AT TIME ZONE 'Asia/Seoul','HH24:MI')
              BETWEEN p_time_from AND p_time_to
        )
        OR (
          p_time_from>p_time_to
          AND (
            to_char(m.started_at AT TIME ZONE 'Asia/Seoul','HH24:MI')>=p_time_from
            OR to_char(m.started_at AT TIME ZONE 'Asia/Seoul','HH24:MI')<=p_time_to
          )
        )
      )
  ), classified AS (
    SELECT base.*,
      CASE
        WHEN canary_status IN ('agreed','owner_resolved') THEN 'final'
        WHEN canary_status IN ('awaiting','conflict') THEN 're_review'
        WHEN live_status IN ('agreed','owner_resolved') THEN 'final'
        WHEN live_status = 'conflict' THEN 'owner_review'
        WHEN live_status = 'awaiting' THEN 'awaiting'
        WHEN legacy_gt IS NOT NULL THEN 'final'
        ELSE 'unlabeled'
      END AS public_state,
      CASE
        WHEN canary_status IS NOT NULL THEN 'blind_consensus'
        WHEN live_status IS NOT NULL THEN 'blind_consensus'
        WHEN legacy_gt IS NOT NULL AND legacy_reviewer=p_owner_id THEN 'owner_legacy'
        WHEN legacy_gt IS NOT NULL THEN 'single_legacy'
        ELSE 'none'
      END AS public_source,
      CASE
        WHEN canary_status IN ('agreed','owner_resolved') THEN canary_decision
        WHEN canary_status IS NOT NULL THEN NULL::text
        WHEN live_status IN ('agreed','owner_resolved') THEN live_decision
        WHEN live_status IS NOT NULL THEN NULL::text
        WHEN legacy_gt IS NOT NULL THEN 'label'
        ELSE NULL::text
      END AS public_decision,
      CASE
        WHEN canary_status IN ('agreed','owner_resolved') THEN canary_gt
        WHEN canary_status IS NOT NULL THEN NULL::jsonb
        WHEN live_status IN ('agreed','owner_resolved') THEN live_gt
        WHEN live_status IS NOT NULL THEN NULL::jsonb
        WHEN legacy_gt IS NOT NULL THEN legacy_gt
        ELSE NULL::jsonb
      END AS public_gt
    FROM base
  )
  SELECT c.id, c.camera_id, c.camera_name, c.started_at, c.duration_sec,
         c.public_state, c.public_source, c.public_decision, c.public_gt
  FROM classified c
  WHERE (p_label_state IS NULL OR c.public_state=p_label_state)
    AND (p_label_source IS NULL OR c.public_source=p_label_source)
    AND (p_final_decision IS NULL OR c.public_decision=p_final_decision)
    AND (p_cursor_started_at IS NULL OR c.started_at<p_cursor_started_at
      OR (c.started_at=p_cursor_started_at AND c.id<p_cursor_id))
  ORDER BY c.started_at DESC, c.id DESC
  LIMIT LEAST(GREATEST(p_limit,1),101);
END;
$$;


-- ── 2.7 교체 함수 재-grant (service_role 전용, 원본 signature 유지) ──
REVOKE ALL ON FUNCTION public.fn_list_motion_clip_labeling_queue(
  uuid, boolean, text, uuid[], timestamptz, timestamptz, text, timestamptz, uuid, integer)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_list_motion_clip_labeling_queue(
  uuid, boolean, text, uuid[], timestamptz, timestamptz, text, timestamptz, uuid, integer)
  TO service_role;

REVOKE ALL ON FUNCTION public.fn_ensure_motion_review_slots(uuid, date)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_ensure_motion_review_slots(uuid, date) TO service_role;

REVOKE ALL ON FUNCTION public.fn_list_motion_blind_queue(
  uuid, date, text, uuid, timestamptz, uuid, integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_list_motion_blind_queue(
  uuid, date, text, uuid, timestamptz, uuid, integer) TO service_role;

REVOKE ALL ON FUNCTION public.fn_manage_motion_blind_canary(
  text, uuid, uuid, text, uuid, uuid[], uuid[]) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_manage_motion_blind_canary(
  text, uuid, uuid, text, uuid, uuid[], uuid[]) TO service_role;

REVOKE ALL ON FUNCTION public.fn_claim_python_evidence_jobs(integer, text, timestamptz)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_claim_python_evidence_jobs(integer, text, timestamptz)
  TO service_role;

REVOKE ALL ON FUNCTION public.fn_list_motion_labeling_library(
  uuid, uuid, text, uuid[], timestamptz, timestamptz, text, text, text, text, timestamptz, uuid, integer)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_list_motion_labeling_library(
  uuid, uuid, text, uuid[], timestamptz, timestamptz, text, text, text, text, timestamptz, uuid, integer)
  TO service_role;
