-- 짧은 영상 격리·보존 disposable DB 실증용 추가 prerequisite schema.
--
-- base(motion_double_blind_prerequisites.sql) + motion_v3 + double_blind + role_reads 를 적용한 뒤,
-- 이 migration 이 참조하지만 위 4개가 만들지 않는 외부 테이블만 최소 형태로 만든다.
-- production row·secret·R2 key 는 절대 복사하지 않고 일회용 컨테이너에서만 적용한다.
--
-- 참조 관계:
--   · behavior_labels / behavior_logs — 보호 대상 attachment 술어(자동 격리·삭제 차단).
--   · clip_vlm_jobs / python_evidence_jobs — active machine job 재검사(삭제 차단) +
--     Task 2 가 forward-copy 하는 fn_claim_python_evidence_jobs 의 대상 테이블.
-- 컬럼은 이 migration 이 실제로 읽는/쓰는 것만 production 과 같은 타입으로 갖춘다.

CREATE TABLE IF NOT EXISTS public.behavior_labels (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  clip_id uuid NOT NULL REFERENCES public.motion_clips(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS public.behavior_logs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  clip_id uuid NOT NULL REFERENCES public.motion_clips(id) ON DELETE CASCADE
);

-- clip_vlm_jobs — active 상태(queued/submitted/failed_retryable)만 삭제 차단에 쓴다.
CREATE TABLE IF NOT EXISTS public.clip_vlm_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  clip_id uuid NOT NULL REFERENCES public.motion_clips(id) ON DELETE CASCADE,
  status text NOT NULL DEFAULT 'queued'
);

-- python_evidence_jobs — 삭제 차단 재검사 + fn_claim_python_evidence_jobs(setof rowtype) 대상.
-- claim 본문이 SET/READ 하는 컬럼만 갖춘다(production 은 상위집합).
CREATE TABLE IF NOT EXISTS public.python_evidence_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  clip_id uuid NOT NULL REFERENCES public.motion_clips(id) ON DELETE CASCADE,
  priority integer NOT NULL DEFAULT 0,
  status text NOT NULL DEFAULT 'queued',
  attempt_count integer NOT NULL DEFAULT 0,
  next_attempt_at timestamptz,
  claimed_at timestamptz,
  claimed_by text,
  lease_expires_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
