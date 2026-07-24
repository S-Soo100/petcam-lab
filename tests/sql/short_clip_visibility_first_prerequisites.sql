-- short clip visibility-first disposable DB 추가 prerequisite schema.
--
-- 적용 순서: base(motion_double_blind_prerequisites) + motion_v3 + double_blind + role_reads
--            + short_clip_prereqs + 2026-07-24_short_clip 뒤, 2026-07-25_short_clip_visibility_first 앞.
--
-- 이 파일은 07-25 migration 이 요구하지만 위 체인이 만들지 않는 "핵심 앱 테이블 요소"만 만든다.
-- production 의 public.motion_clips 는 이미 owner_id 컬럼 + RLS + "own clips select" policy 를 갖췄고
-- (migration 이전부터 존재하는 코어 테이블), 여기서는 일회용 컨테이너에서 그 최소 형태를 재현한다.
-- production row·secret·R2 key 는 절대 복사하지 않는다.

-- owner_id: 앱 소유자 판정 컬럼(behavior_logs owner select 계약과 동일: motion_clips.owner_id).
ALTER TABLE public.motion_clips ADD COLUMN IF NOT EXISTS owner_id uuid;

-- auth.uid(): Supabase 내장 함수 재현. request.jwt.claims(JSON)의 sub 를 uuid 로 반환하고,
-- 미설정(서비스/시스템 컨텍스트)이면 NULL. helper·policy 가 owner 동일성 판정에 쓴다.
CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid
LANGUAGE sql STABLE AS $$
  SELECT nullif(
    current_setting('request.jwt.claims', true)::jsonb ->> 'sub', ''
  )::uuid;
$$;

-- motion_clips RLS + owner-only SELECT policy. 07-25 migration 이 이 policy 의 USING 을
-- helper(fn_motion_clip_visible_to_owner) 로 ALTER 한다(정책 존재가 ALTER 전제).
ALTER TABLE public.motion_clips ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'motion_clips'
      AND policyname = 'own clips select'
  ) THEN
    CREATE POLICY "own clips select" ON public.motion_clips
      FOR SELECT TO authenticated
      USING (owner_id = auth.uid());
  END IF;
END $$;

-- authenticated 는 RLS 통과분만, service_role 은 전량 read(운영/감사).
GRANT SELECT ON public.motion_clips TO authenticated, service_role;

-- service_role: production 은 BYPASSRLS 로 전량 read 한다. 로컬 재현은 cluster-global role 속성을
-- 건드리면(다른 probe 로 누수) 안 되므로, temp DB scope 의 permissive SELECT policy 로 같은 관측
-- (모든 상태 read)만 재현한다. authenticated 의 owner policy 와는 TO 대상이 달라 간섭하지 않는다.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public' AND tablename = 'motion_clips'
      AND policyname = 'service reads all clips'
  ) THEN
    CREATE POLICY "service reads all clips" ON public.motion_clips
      FOR SELECT TO service_role USING (true);
  END IF;
END $$;
