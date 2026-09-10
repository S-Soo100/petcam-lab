-- 라벨링 v4 동시 작업 충돌 완화 (UX ⑤, owner 결정 2026-09-08 "남은 추천 자동 진행").
-- 두 사람이 같은 카메라를 같은 시각부터 보면 "다음 영상"이 같은 clip 을 주고 뒤늦은 쪽이 409(방금 확정됐어)를
-- 반복해서 본다. 상세를 열 때 "보는 중" 표시(claim)를 남기고, 다음/이어서 라벨링은 남이 최근에 연 clip 을 건너뛴다.
--
-- 계약:
-- - claim 은 clip 당 1행(마지막으로 연 사람·시각). 권한·잠금이 아니라 힌트다 — 확정은 여전히 먼저 저장한 사람이 이긴다(PT409).
-- - 신선 기준(TTL)은 호출자가 넘긴다(웹 120초). 후보를 모두 남이 보고 있으면 호출자가 첫 후보를 그대로 쓴다.
-- - 테이블은 RPC 전용(service_role 직접 권한 없음, RLS on).
BEGIN;

CREATE TABLE public.motion_clip_view_claims (
  clip_id uuid PRIMARY KEY REFERENCES public.motion_clips(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  claimed_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_motion_clip_view_claims_claimed_at ON public.motion_clip_view_claims (claimed_at DESC);
ALTER TABLE public.motion_clip_view_claims ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.motion_clip_view_claims FROM PUBLIC, anon, authenticated, service_role;

-- 상세를 열 때 호출. 운영 비적격·미존재 clip 은 조용히 무시한다(힌트라 실패해도 흐름을 막지 않는다).
CREATE FUNCTION public.fn_claim_motion_clip_view(p_clip_id uuid, p_user_id uuid)
RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = '' AS $$
BEGIN
  IF p_clip_id IS NULL OR p_user_id IS NULL THEN RETURN; END IF;
  IF NOT EXISTS (SELECT 1 FROM public.motion_clips c WHERE c.id = p_clip_id) THEN RETURN; END IF;
  INSERT INTO public.motion_clip_view_claims (clip_id, user_id, claimed_at)
  VALUES (p_clip_id, p_user_id, now())
  ON CONFLICT (clip_id) DO UPDATE SET user_id = EXCLUDED.user_id, claimed_at = now();
END $$;

-- 후보 clip 들 중 "남이 TTL 안에 연" clip id 만 돌려준다.
CREATE FUNCTION public.fn_fresh_motion_clip_view_claims(p_clip_ids uuid[], p_exclude_user uuid, p_ttl_sec integer)
RETURNS TABLE (clip_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT v.clip_id
    FROM public.motion_clip_view_claims v
   WHERE v.clip_id = ANY (p_clip_ids)
     AND v.user_id IS DISTINCT FROM p_exclude_user
     AND v.claimed_at > now() - make_interval(secs => greatest(coalesce(p_ttl_sec, 120), 1));
$$;

REVOKE ALL ON FUNCTION public.fn_claim_motion_clip_view(uuid, uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_claim_motion_clip_view(uuid, uuid) TO service_role;
REVOKE ALL ON FUNCTION public.fn_fresh_motion_clip_view_claims(uuid[], uuid, integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_fresh_motion_clip_view_claims(uuid[], uuid, integer) TO service_role;

COMMIT;
