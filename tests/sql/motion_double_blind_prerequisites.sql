-- 이중 블라인드 하드닝 disposable DB 실증용 최소 prerequisite schema (Task 6).
--
-- migration 2026-07-23_motion_double_blind_labeling.sql 이 요구하는 외부 의존만 만든다.
-- production row·secret·email·R2 key·note·auth data 는 절대 복사하지 않는다. UUID + timestamptz
-- 타입은 production 과 동일하게 맞춘다. 이 파일은 오직 일회용 컨테이너에서만 적용된다.

-- Supabase 기본 role (bare postgres 에는 없음). migration 의 REVOKE ... FROM anon/authenticated 와
-- GRANT ... TO service_role 대상이라 먼저 만든다.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
    CREATE ROLE anon NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
    CREATE ROLE authenticated NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
    CREATE ROLE service_role NOLOGIN;
  END IF;
END $$;

-- auth.users — migration 의 모든 사람 FK 대상(created_by/reviewer_id/user_id/...).
CREATE SCHEMA IF NOT EXISTS auth;
CREATE TABLE IF NOT EXISTS auth.users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid()
);

-- public.cameras — group_cameras.camera_id FK 대상.
CREATE TABLE IF NOT EXISTS public.cameras (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text
);

-- public.motion_clips — review_slots/submissions/consensus 의 clip FK 대상. queue RPC 가 읽는
-- duration_sec(double precision)·r2_key·started_at(timestamptz)·camera_id 를 갖춘다.
CREATE TABLE IF NOT EXISTS public.motion_clips (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  camera_id uuid REFERENCES public.cameras(id),
  started_at timestamptz NOT NULL DEFAULT now(),
  duration_sec double precision,
  r2_key text
);

-- public.labelers — 접근 SOT. canary/reassign/manage RPC 가 존재만 확인한다(user_id).
CREATE TABLE IF NOT EXISTS public.labelers (
  user_id uuid PRIMARY KEY
);

-- public.labeler_applications — 승인 상태 SOT. workspace RPC 가 display_name 을 읽는다.
CREATE TABLE IF NOT EXISTS public.labeler_applications (
  user_id uuid PRIMARY KEY,
  status text NOT NULL DEFAULT 'pending',
  display_name text
);
