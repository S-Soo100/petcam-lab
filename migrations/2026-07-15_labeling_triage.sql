-- 라벨링 후보 격리함 (triage quarantine) — 2026-07-15.
--
-- 설계 정본: docs/superpowers/specs/2026-07-15-labeling-triage-quarantine-design.md
--
-- forward-only 신규 파일. 기존 마이그레이션을 수정하지 않는다.
-- 두 테이블 + append-only 이벤트 트리거 + service-role 전용 RPC 3개를 만든다.
--
-- 상태 모델(설계 §5.2): owner 결정이 항상 시스템 제안보다 우선한다.
--   owner_decision='label'  → 유효 '라벨링으로 보냄'(본 큐 포함)
--   owner_decision='skip'   → 유효 '라벨링 안 함'(본 큐 제외)
--   owner_decision null + suggested_route='quarantine' → '검토 필요'(본 큐 제외)
--   owner_decision null + suggested_route='label'      → 라벨링(본 큐 포함)
--   triage row 없음 / 분석 실패 / unknown              → 라벨링(본 큐 포함)
--
-- 보안(설계 §7): 두 테이블 RLS ON + client write policy 0건 + service_role 전용.
--   Next.js API 가 bearer 인증 + owner 판정 후 service_role 로 RPC 를 호출한다.
--   이벤트 테이블은 REVOKE 뿐 아니라 트리거로도 UPDATE/DELETE/TRUNCATE 를 차단한다
--   (service_role 유출/실수 대비 — 감사 로그 append-only 계약).
--
-- ⏳ production 미적용. 구현·테스트 후 사용자 검토에서 멈춘다(계획 Global Constraints).

BEGIN;

-- ── 1. 현재 라우팅 상태 테이블 (설계 §6.1) ─────────────────────────
CREATE TABLE public.clip_labeling_triage (
  clip_id uuid PRIMARY KEY REFERENCES public.camera_clips(id) ON DELETE CASCADE,
  suggested_route text NOT NULL CHECK (suggested_route IN ('label','quarantine')),
  suggestion_reason text NOT NULL CHECK (suggestion_reason IN ('gate_active','gate_absent','gate_static','manual')),
  suggestion_source text NOT NULL CHECK (char_length(suggestion_source) BETWEEN 1 AND 80),
  policy_version text NOT NULL CHECK (char_length(policy_version) BETWEEN 1 AND 80),
  evidence_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
  owner_decision text CHECK (owner_decision IN ('label','skip')),
  decided_by uuid REFERENCES auth.users(id) ON DELETE RESTRICT,
  decided_at timestamptz,
  decision_note text CHECK (decision_note IS NULL OR char_length(decision_note) <= 500),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  -- owner 결정 3필드는 all-null 이거나 all-set 이어야 한다(설계 §6.1).
  CHECK (
    (owner_decision IS NULL AND decided_by IS NULL AND decided_at IS NULL)
    OR
    (owner_decision IS NOT NULL AND decided_by IS NOT NULL AND decided_at IS NOT NULL)
  ),
  CHECK (jsonb_typeof(evidence_snapshot) = 'object')
);

COMMENT ON TABLE public.clip_labeling_triage IS
  '라벨링 후보 라우팅 상태. owner_decision 이 suggested_route 보다 항상 우선(설계 §5.2).';

-- 유효 상태 조회(격리함 탭/큐 필터)는 owner_decision + suggested_route 로 접힌다.
-- 목록 정렬은 updated_at DESC, clip_id DESC 커서 기준(설계 §8.1).
CREATE INDEX idx_clip_labeling_triage_effective_state
  ON public.clip_labeling_triage
  (owner_decision, suggested_route, updated_at DESC, clip_id DESC);

-- ── 2. append-only 감사 이벤트 테이블 (설계 §6.2) ──────────────────
CREATE TABLE public.clip_labeling_triage_events (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  -- 이벤트는 append-only이며 원본 clip보다 오래 보존한다. FK CASCADE를 걸면
  -- 이벤트 DELETE 차단 트리거가 camera_clips 삭제까지 막으므로 UUID만 보존한다.
  clip_id uuid NOT NULL,
  event_type text NOT NULL CHECK (event_type IN (
    'suggested','owner_labeled','owner_skipped','owner_reset','manual_quarantined'
  )),
  actor_type text NOT NULL CHECK (actor_type IN ('system','owner')),
  actor_id uuid REFERENCES auth.users(id) ON DELETE RESTRICT,
  before_state jsonb,
  after_state jsonb NOT NULL,
  reason text CHECK (reason IS NULL OR char_length(reason) <= 500),
  created_at timestamptz NOT NULL DEFAULT now(),
  -- system 이벤트는 actor_id 없이도 되지만 owner 이벤트는 반드시 actor_id 를 남긴다.
  CHECK (actor_type = 'system' OR actor_id IS NOT NULL)
);

COMMENT ON TABLE public.clip_labeling_triage_events IS
  'Append-only. RPC 만 INSERT 한다. UPDATE/DELETE/TRUNCATE 는 트리거로 차단(0A000).';

CREATE INDEX idx_clip_labeling_triage_events_clip_created
  ON public.clip_labeling_triage_events (clip_id, created_at DESC);

-- ── 3. RLS + client write 차단 + service_role 전용 (설계 §7) ───────
ALTER TABLE public.clip_labeling_triage ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.clip_labeling_triage_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.clip_labeling_triage FROM PUBLIC, anon, authenticated;
REVOKE ALL ON public.clip_labeling_triage_events FROM PUBLIC, anon, authenticated;
GRANT ALL ON public.clip_labeling_triage TO service_role;
GRANT ALL ON public.clip_labeling_triage_events TO service_role;

-- ── 4. 이벤트 append-only 강제 트리거 (설계 §6.2) ──────────────────
-- 실행 역할(service_role 포함)과 무관하게 발동한다. INSERT 는 계속 허용.
CREATE OR REPLACE FUNCTION public.fn_block_labeling_triage_event_mutation()
RETURNS trigger LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN
  RAISE EXCEPTION 'clip_labeling_triage_events is append-only (UPDATE/DELETE/TRUNCATE 금지)'
    USING ERRCODE = '0A000';  -- feature_not_supported
END;
$$;

REVOKE ALL ON FUNCTION public.fn_block_labeling_triage_event_mutation() FROM PUBLIC;

DROP TRIGGER IF EXISTS trg_block_labeling_triage_event_row_mutation
  ON public.clip_labeling_triage_events;
CREATE TRIGGER trg_block_labeling_triage_event_row_mutation
  BEFORE UPDATE OR DELETE ON public.clip_labeling_triage_events
  FOR EACH ROW EXECUTE FUNCTION public.fn_block_labeling_triage_event_mutation();

-- TRUNCATE 는 행 트리거를 우회하므로 statement 단위로 따로 차단.
DROP TRIGGER IF EXISTS trg_block_labeling_triage_event_truncate
  ON public.clip_labeling_triage_events;
CREATE TRIGGER trg_block_labeling_triage_event_truncate
  BEFORE TRUNCATE ON public.clip_labeling_triage_events
  FOR EACH STATEMENT EXECUTE FUNCTION public.fn_block_labeling_triage_event_mutation();

-- ── 5. 시스템 제안 upsert RPC (설계 §6.3-1) ───────────────────────
-- service-role 전용. worker 가 Gate evidence 로 시스템 제안을 갱신한다.
-- owner 결정이 있으면 제안 필드만 갱신하고 유효 owner 결정을 덮지 않는다(설계 §3-2).
-- suggested_route='quarantine' 인데 이미 라벨링 세션이 있으면 거부(설계 §3-4, §6.3-1).
-- suggested_route='label' 은 세션과 무관하게 허용(fail-open).
CREATE OR REPLACE FUNCTION public.fn_upsert_clip_labeling_triage_suggestion(
  p_clip_id uuid,
  p_suggested_route text,
  p_suggestion_reason text,
  p_suggestion_source text,
  p_policy_version text,
  p_evidence_snapshot jsonb
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  v_row public.clip_labeling_triage%ROWTYPE;
  v_existing public.clip_labeling_triage%ROWTYPE;
  v_found boolean;
  v_changed boolean;
  v_before jsonb;
  v_has_motion boolean;
  v_r2_key text;
BEGIN
  -- (1) enum/JSON 성격 입력을 잠그기 전에 검증한다(잘못된 입력=22023 → API 400).
  IF p_suggested_route NOT IN ('label','quarantine') THEN
    RAISE EXCEPTION 'invalid suggested_route: %', p_suggested_route USING ERRCODE = '22023';
  END IF;
  IF p_suggestion_reason NOT IN ('gate_active','gate_absent','gate_static','manual') THEN
    RAISE EXCEPTION 'invalid suggestion_reason: %', p_suggestion_reason USING ERRCODE = '22023';
  END IF;
  IF p_suggestion_source IS NULL OR char_length(p_suggestion_source) NOT BETWEEN 1 AND 80 THEN
    RAISE EXCEPTION 'invalid suggestion_source' USING ERRCODE = '22023';
  END IF;
  IF p_policy_version IS NULL OR char_length(p_policy_version) NOT BETWEEN 1 AND 80 THEN
    RAISE EXCEPTION 'invalid policy_version' USING ERRCODE = '22023';
  END IF;
  IF p_evidence_snapshot IS NULL OR jsonb_typeof(p_evidence_snapshot) <> 'object' THEN
    RAISE EXCEPTION 'evidence_snapshot must be a JSON object' USING ERRCODE = '22023';
  END IF;

  -- (2) camera_clips 잠금(lock 순서 통일: camera_clips → triage, 세션 가드 트리거와 동일).
  --     없으면 P0002. 라벨 가능 계약: has_motion=true AND r2_key IS NOT NULL 아니면 fail-closed.
  SELECT has_motion, r2_key INTO v_has_motion, v_r2_key
    FROM public.camera_clips WHERE id = p_clip_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'camera_clip not found: %', p_clip_id USING ERRCODE = 'P0002';
  END IF;
  IF v_has_motion IS NOT TRUE OR v_r2_key IS NULL THEN
    RETURN jsonb_build_object('ok', false, 'code', 'not_labelable');
  END IF;

  -- (3) 기존 triage row 를 잠근다(있으면).
  SELECT * INTO v_existing FROM public.clip_labeling_triage
    WHERE clip_id = p_clip_id FOR UPDATE;
  v_found := FOUND;

  -- (4) quarantine 제안은 라벨링 세션이 있으면 거부(이미 시작한 작업 보호, 설계 §3-4).
  IF p_suggested_route = 'quarantine'
     AND EXISTS (SELECT 1 FROM public.clip_labeling_sessions WHERE clip_id = p_clip_id) THEN
    RETURN jsonb_build_object('ok', false, 'code', 'labeling_started');
  END IF;

  -- (5) 제안 필드가 전부 동일하면 no-op — 이벤트도 남기지 않는다.
  IF v_found THEN
    v_changed := NOT (
      v_existing.suggested_route   IS NOT DISTINCT FROM p_suggested_route
      AND v_existing.suggestion_reason IS NOT DISTINCT FROM p_suggestion_reason
      AND v_existing.suggestion_source IS NOT DISTINCT FROM p_suggestion_source
      AND v_existing.policy_version    IS NOT DISTINCT FROM p_policy_version
      AND v_existing.evidence_snapshot IS NOT DISTINCT FROM p_evidence_snapshot
    );
    IF NOT v_changed THEN
      RETURN jsonb_build_object('ok', true, 'changed', false, 'row', to_jsonb(v_existing));
    END IF;
  ELSE
    v_changed := true;
  END IF;

  -- (6) 제안 필드 + updated_at 만 갱신한다. owner_decision 계열은 절대 건드리지 않는다.
  IF v_found THEN
    v_before := to_jsonb(v_existing);
    UPDATE public.clip_labeling_triage
      SET suggested_route = p_suggested_route,
          suggestion_reason = p_suggestion_reason,
          suggestion_source = p_suggestion_source,
          policy_version = p_policy_version,
          evidence_snapshot = p_evidence_snapshot,
          updated_at = clock_timestamp()
      WHERE clip_id = p_clip_id
      RETURNING * INTO v_row;
  ELSE
    v_before := NULL;
    INSERT INTO public.clip_labeling_triage
      (clip_id, suggested_route, suggestion_reason, suggestion_source,
       policy_version, evidence_snapshot)
    VALUES (p_clip_id, p_suggested_route, p_suggestion_reason, p_suggestion_source,
       p_policy_version, p_evidence_snapshot)
    RETURNING * INTO v_row;
  END IF;

  -- (7) 제안 변경 시에만 'suggested' 이벤트 1건.
  INSERT INTO public.clip_labeling_triage_events
    (clip_id, event_type, actor_type, actor_id, before_state, after_state, reason)
  VALUES (p_clip_id, 'suggested', 'system', NULL, v_before, to_jsonb(v_row), p_suggestion_reason);

  RETURN jsonb_build_object('ok', true, 'changed', true, 'row', to_jsonb(v_row));
END;
$$;

-- ── 6. owner 결정 RPC (설계 §6.3-2, §8.3) ─────────────────────────
-- service-role 전용. API 가 owner 인증 후 호출한다.
-- label|skip|reset. optimistic concurrency(expected_updated_at) 로 stale 탭 차단.
CREATE OR REPLACE FUNCTION public.fn_decide_clip_labeling_triage(
  p_clip_id uuid,
  p_decided_by uuid,
  p_decision text,
  p_expected_updated_at timestamptz,
  p_note text
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  v_row public.clip_labeling_triage%ROWTYPE;
  v_before jsonb;
  v_event_type text;
BEGIN
  IF p_decision NOT IN ('label','skip','reset') THEN
    RAISE EXCEPTION 'invalid decision: %', p_decision USING ERRCODE = '22023';
  END IF;
  IF p_note IS NOT NULL AND char_length(p_note) > 500 THEN
    RAISE EXCEPTION 'note too long' USING ERRCODE = '22023';
  END IF;

  -- lock 순서 통일: camera_clips → triage(세션 가드 트리거·다른 RPC 와 동일 순서, deadlock 방지).
  -- clip 이 이미 삭제됐으면 triage 도 CASCADE 로 사라져 아래 not_found 로 떨어진다.
  PERFORM 1 FROM public.camera_clips WHERE id = p_clip_id FOR UPDATE;

  SELECT * INTO v_row FROM public.clip_labeling_triage
    WHERE clip_id = p_clip_id FOR UPDATE;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('ok', false, 'code', 'not_found');
  END IF;

  -- optimistic concurrency: 다른 화면에서 먼저 바뀌었으면 거부(설계 §8.3 409 stale_state).
  IF v_row.updated_at IS DISTINCT FROM p_expected_updated_at THEN
    RETURN jsonb_build_object('ok', false, 'code', 'stale_state');
  END IF;

  -- skip 은 이미 라벨링이 시작된 clip 에서 거부(설계 §5.3, §8.3 409 labeling_started).
  IF p_decision = 'skip'
     AND EXISTS (SELECT 1 FROM public.clip_labeling_sessions WHERE clip_id = p_clip_id) THEN
    RETURN jsonb_build_object('ok', false, 'code', 'labeling_started');
  END IF;

  v_before := to_jsonb(v_row);

  IF p_decision = 'reset' THEN
    -- owner 결정 4필드만 제거하고 시스템 evidence/제안은 보존한다(설계 §5.2).
    UPDATE public.clip_labeling_triage
      SET owner_decision = NULL,
          decided_by = NULL,
          decided_at = NULL,
          decision_note = NULL,
          updated_at = clock_timestamp()
      WHERE clip_id = p_clip_id
      RETURNING * INTO v_row;
    v_event_type := 'owner_reset';
  ELSE
    UPDATE public.clip_labeling_triage
      SET owner_decision = p_decision,
          decided_by = p_decided_by,
          decided_at = clock_timestamp(),
          decision_note = p_note,
          updated_at = clock_timestamp()
      WHERE clip_id = p_clip_id
      RETURNING * INTO v_row;
    v_event_type := CASE WHEN p_decision = 'label' THEN 'owner_labeled' ELSE 'owner_skipped' END;
  END IF;

  INSERT INTO public.clip_labeling_triage_events
    (clip_id, event_type, actor_type, actor_id, before_state, after_state, reason)
  VALUES (p_clip_id, v_event_type, 'owner', p_decided_by, v_before, to_jsonb(v_row), p_note);

  RETURN jsonb_build_object('ok', true, 'row', to_jsonb(v_row));
END;
$$;

-- ── 7. owner 수동 격리 RPC (설계 §6.3-3, §8.4) ────────────────────
-- service-role 전용. 시스템 evidence 없이 owner 가 본 큐에서 격리함으로 옮긴다.
-- owner 의 명시적 새 동작이므로 기존 owner_decision/결정 메타를 null 로 초기화해
-- '검토 필요'로 이동시킨다(설계 §6.3-3). 이미 세션이 있으면 거부한다.
CREATE OR REPLACE FUNCTION public.fn_manual_quarantine_clip_for_labeling(
  p_clip_id uuid,
  p_actor_id uuid,
  p_note text
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  v_row public.clip_labeling_triage%ROWTYPE;
  v_existing public.clip_labeling_triage%ROWTYPE;
  v_found boolean;
  v_changed boolean;
  v_before jsonb;
  v_r2_key text;
  v_has_motion boolean;
BEGIN
  IF p_note IS NOT NULL AND char_length(p_note) > 500 THEN
    RAISE EXCEPTION 'note too long' USING ERRCODE = '22023';
  END IF;

  -- clip 잠금(lock 순서 통일: camera_clips → triage). 라벨 가능 계약: has_motion=true AND r2_key NOT NULL.
  SELECT has_motion, r2_key INTO v_has_motion, v_r2_key
    FROM public.camera_clips WHERE id = p_clip_id FOR UPDATE;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('ok', false, 'code', 'not_found');
  END IF;
  IF v_has_motion IS NOT TRUE OR v_r2_key IS NULL THEN
    RETURN jsonb_build_object('ok', false, 'code', 'not_labelable');
  END IF;

  -- 이미 라벨링이 시작된 clip 은 수동 격리도 거부(설계 §8.4).
  IF EXISTS (SELECT 1 FROM public.clip_labeling_sessions WHERE clip_id = p_clip_id) THEN
    RETURN jsonb_build_object('ok', false, 'code', 'labeling_started');
  END IF;

  SELECT * INTO v_existing FROM public.clip_labeling_triage
    WHERE clip_id = p_clip_id FOR UPDATE;
  v_found := FOUND;

  -- 이미 owner 결정 없는 manual quarantine 상태면 no-op(이벤트 미기록).
  IF v_found THEN
    v_changed := NOT (
      v_existing.suggested_route = 'quarantine'
      AND v_existing.suggestion_reason = 'manual'
      AND v_existing.suggestion_source = 'owner_manual'
      AND v_existing.policy_version = 'manual-v1'
      AND v_existing.owner_decision IS NULL
      AND v_existing.decided_by IS NULL
      AND v_existing.decided_at IS NULL
      AND v_existing.decision_note IS NULL
    );
  ELSE
    v_changed := true;
  END IF;

  IF v_found AND NOT v_changed THEN
    RETURN jsonb_build_object('ok', true, 'changed', false, 'row', to_jsonb(v_existing));
  END IF;

  IF v_found THEN
    v_before := to_jsonb(v_existing);
    UPDATE public.clip_labeling_triage
      SET suggested_route = 'quarantine',
          suggestion_reason = 'manual',
          suggestion_source = 'owner_manual',
          policy_version = 'manual-v1',
          evidence_snapshot = '{}'::jsonb,
          owner_decision = NULL,
          decided_by = NULL,
          decided_at = NULL,
          decision_note = NULL,
          updated_at = clock_timestamp()
      WHERE clip_id = p_clip_id
      RETURNING * INTO v_row;
  ELSE
    v_before := NULL;
    INSERT INTO public.clip_labeling_triage
      (clip_id, suggested_route, suggestion_reason, suggestion_source,
       policy_version, evidence_snapshot)
    VALUES (p_clip_id, 'quarantine', 'manual', 'owner_manual', 'manual-v1', '{}'::jsonb)
    RETURNING * INTO v_row;
  END IF;

  INSERT INTO public.clip_labeling_triage_events
    (clip_id, event_type, actor_type, actor_id, before_state, after_state, reason)
  VALUES (p_clip_id, 'manual_quarantined', 'owner', p_actor_id, v_before, to_jsonb(v_row), p_note);

  RETURN jsonb_build_object('ok', true, 'changed', true, 'row', to_jsonb(v_row));
END;
$$;

-- ── 7.5. 세션↔격리 양방향 원자성 가드 트리거 (2차 하드닝) ──────────
-- production clip_labeling_sessions 는 authenticated 가 본인 세션을 직접 INSERT 하는 RLS 가 있어
-- Next.js 큐 필터만으론 부족하다. quarantine/skip 상태에서 새 세션 생성을 DB 에서 차단한다.
-- 계약: triage row 없음 / owner label / 미결정+시스템 label = 허용,
--       owner skip / 미결정+시스템 quarantine = 차단(PT409).
-- triage(REVOKE ALL) 를 읽어야 하므로 SECURITY DEFINER. lock 순서 camera_clips → triage(RPC 와 동일).
CREATE OR REPLACE FUNCTION public.fn_guard_labeling_session_vs_triage()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  v_triage public.clip_labeling_triage%ROWTYPE;
BEGIN
  -- clip_id 가 실제로 바뀌지 않는 UPDATE 는 검사 불필요(gt route resume upsert 오검출·불필요 lock 방지).
  IF TG_OP = 'UPDATE' AND NEW.clip_id IS NOT DISTINCT FROM OLD.clip_id THEN
    RETURN NEW;
  END IF;

  PERFORM 1 FROM public.camera_clips WHERE id = NEW.clip_id FOR UPDATE;
  SELECT * INTO v_triage FROM public.clip_labeling_triage
    WHERE clip_id = NEW.clip_id FOR UPDATE;
  IF FOUND THEN
    IF v_triage.owner_decision = 'skip'
       OR (v_triage.owner_decision IS NULL AND v_triage.suggested_route = 'quarantine') THEN
      RAISE EXCEPTION 'clip % is quarantined/skipped for labeling', NEW.clip_id
        USING ERRCODE = 'PT409';  -- triage_quarantined (API 가 409 로 매핑)
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.fn_guard_labeling_session_vs_triage() FROM PUBLIC;

DROP TRIGGER IF EXISTS trg_guard_labeling_session_vs_triage ON public.clip_labeling_sessions;
CREATE TRIGGER trg_guard_labeling_session_vs_triage
  BEFORE INSERT OR UPDATE OF clip_id ON public.clip_labeling_sessions
  FOR EACH ROW EXECUTE FUNCTION public.fn_guard_labeling_session_vs_triage();

-- ── 7.6. 격리함 카메라 필터 옵션 (owner 전용, 2차 하드닝) ──────────
-- product owner 소유 카메라가 아니라 "실제 triage 대상 카메라"만 준다(설계 §8.1 필터).
-- 테스트 카메라 계정과 product owner 가 분리돼 있어 /labels/filter-options 를 재사용하지 않는다.
CREATE OR REPLACE FUNCTION public.fn_triage_camera_options()
RETURNS TABLE(camera_id uuid, name text)
LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT DISTINCT cc.camera_id, cam.name
  FROM public.clip_labeling_triage t
  JOIN public.camera_clips cc ON cc.id = t.clip_id
  LEFT JOIN public.cameras cam ON cam.id = cc.camera_id
  ORDER BY cam.name NULLS LAST, cc.camera_id;
$$;

-- ── 8. 함수 실행권한 — service_role 전용 (설계 §7) ─────────────────
REVOKE ALL ON FUNCTION public.fn_upsert_clip_labeling_triage_suggestion(
  uuid, text, text, text, text, jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_upsert_clip_labeling_triage_suggestion(
  uuid, text, text, text, text, jsonb) TO service_role;

REVOKE ALL ON FUNCTION public.fn_decide_clip_labeling_triage(
  uuid, uuid, text, timestamptz, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_decide_clip_labeling_triage(
  uuid, uuid, text, timestamptz, text) TO service_role;

REVOKE ALL ON FUNCTION public.fn_manual_quarantine_clip_for_labeling(
  uuid, uuid, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_manual_quarantine_clip_for_labeling(
  uuid, uuid, text) TO service_role;

REVOKE ALL ON FUNCTION public.fn_triage_camera_options() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_triage_camera_options() TO service_role;

COMMIT;

-- ── 검증 (DO/트랜잭션 롤백 probe, REPORT 참고) ─────────────────────
-- 아래는 apply 후 트랜잭션 안에서 검증하고 전량 롤백하는 예시다. <clip>/<owner> 대입.
-- BEGIN;
--   -- suggestion + event atomicity: 첫 제안 → row 1건 + 'suggested' 이벤트 1건
--   SELECT public.fn_upsert_clip_labeling_triage_suggestion(
--     '<clip>'::uuid, 'quarantine', 'gate_absent', 'gate_activity_policy', 'gate-v2', '{}'::jsonb);
--   SELECT count(*) FROM public.clip_labeling_triage WHERE clip_id='<clip>';          -- 1
--   SELECT count(*) FROM public.clip_labeling_triage_events WHERE clip_id='<clip>';   -- 1
--
--   -- duplicate suggestion => changed=false, 이벤트 추가 없음
--   SELECT public.fn_upsert_clip_labeling_triage_suggestion(
--     '<clip>'::uuid, 'quarantine', 'gate_absent', 'gate_activity_policy', 'gate-v2', '{}'::jsonb);
--   SELECT count(*) FROM public.clip_labeling_triage_events WHERE clip_id='<clip>';   -- 여전히 1
--
--   -- owner label 이 이후 시스템 제안 뒤에도 유지된다
--   SELECT public.fn_decide_clip_labeling_triage(
--     '<clip>'::uuid, '<owner>'::uuid, 'label',
--     (SELECT updated_at FROM public.clip_labeling_triage WHERE clip_id='<clip>'), NULL);
--   SELECT public.fn_upsert_clip_labeling_triage_suggestion(
--     '<clip>'::uuid, 'quarantine', 'gate_static', 'gate_activity_policy', 'gate-v2', '{}'::jsonb);
--   SELECT owner_decision FROM public.clip_labeling_triage WHERE clip_id='<clip>';    -- 'label' 유지
--
--   -- session present => quarantine 제안/skip 결정 labeling_started
--   --   (세션 있는 <clip2> 로) fn_upsert(... 'quarantine' ...) => {ok:false,code:'labeling_started'}
--   --   fn_decide(<clip2>, ..., 'skip', ...)                   => {ok:false,code:'labeling_started'}
--
--   -- stale updated_at => stale_state
--   SELECT public.fn_decide_clip_labeling_triage(
--     '<clip>'::uuid, '<owner>'::uuid, 'skip', 'epoch'::timestamptz, NULL); -- {ok:false,code:'stale_state'}
--
--   -- event UPDATE/DELETE/TRUNCATE => 0A000
--   -- UPDATE public.clip_labeling_triage_events SET reason='x' WHERE clip_id='<clip>';  -- 0A000
--   -- DELETE FROM public.clip_labeling_triage_events WHERE clip_id='<clip>';            -- 0A000
--   -- TRUNCATE public.clip_labeling_triage_events;                                      -- 0A000
--
--   -- ── 세션↔격리 양방향 원자성 (2차 하드닝) ─────────────────────────
--   -- pending quarantine 에서 세션 INSERT 차단:
--   --   fn_upsert(... 'quarantine' 'gate_absent' ...) 로 <clipA> pending 만든 뒤
--   --   INSERT INTO clip_labeling_sessions(clip_id, reviewed_by, ...) VALUES('<clipA>', '<owner>', ...); -- PT409
--   -- owner skip 에서 세션 INSERT 차단:
--   --   fn_decide(<clipB>, <owner>, 'skip', ...) 뒤 INSERT ... clip_id='<clipB>';  -- PT409
--   -- owner label / 시스템 label / triage row 없음 에서 INSERT 허용:
--   --   fn_decide(<clipC>,<owner>,'label',...) 뒤 INSERT clip_id='<clipC>';         -- 성공
--   --   fn_upsert(<clipD>,'label',...) 뒤 INSERT clip_id='<clipD>';                 -- 성공
--   --   INSERT clip_id='<clipE(no triage)>';                                        -- 성공
--   -- not_labelable fail-closed: has_motion=false 또는 r2_key NULL 인 <clipF> 로
--   --   fn_upsert(<clipF>,'quarantine',...) / fn_manual_quarantine(<clipF>,...) => {ok:false,code:'not_labelable'}
-- ROLLBACK;  -- 모든 probe row 0 로 복귀(성공한 INSERT·suggestion 도 전량 롤백)

-- ── 롤백 ───────────────────────────────────────────────────────────
-- BEGIN;
-- DROP TRIGGER IF EXISTS trg_guard_labeling_session_vs_triage ON public.clip_labeling_sessions;
-- DROP FUNCTION IF EXISTS public.fn_guard_labeling_session_vs_triage();
-- DROP FUNCTION IF EXISTS public.fn_triage_camera_options();
-- DROP FUNCTION IF EXISTS public.fn_manual_quarantine_clip_for_labeling(uuid, uuid, text);
-- DROP FUNCTION IF EXISTS public.fn_decide_clip_labeling_triage(uuid, uuid, text, timestamptz, text);
-- DROP FUNCTION IF EXISTS public.fn_upsert_clip_labeling_triage_suggestion(uuid, text, text, text, text, jsonb);
-- DROP TRIGGER IF EXISTS trg_block_labeling_triage_event_truncate ON public.clip_labeling_triage_events;
-- DROP TRIGGER IF EXISTS trg_block_labeling_triage_event_row_mutation ON public.clip_labeling_triage_events;
-- DROP FUNCTION IF EXISTS public.fn_block_labeling_triage_event_mutation();
-- DROP TABLE IF EXISTS public.clip_labeling_triage_events;
-- DROP TABLE IF EXISTS public.clip_labeling_triage;
-- COMMIT;
