-- feature-vlm-worker-cloud.md §4-1 폴링 fix (2026-05-07)
--
-- 적용 이력 (2026-05-07): Supabase MCP `apply_migration` 으로 production 적용 완료.
-- 검증: SELECT * FROM fn_vlm_pending_clips(20) → 정확히 1건 (예상한 pending) 반환.
--
-- 배경:
--   기존 worker.py 의 2-step diff (done set + camera_clips ASC limit*4) 가
--   "159건 모두 라벨됨 + 1건 (최신) 만 pending" 케이스에서 영원히 못 잡는 버그 발견.
--   클라이언트 cutoff (LIMIT) 가 backlog 위치보다 작으면 신규/임의 지점 pending 가
--   시야 밖. RPC 가 DB 안에서 NOT EXISTS subquery 로 직접 처리 → 클라이언트 cutoff 무관.
--
-- 보안:
--   SECURITY DEFINER + service_role EXECUTE 만 허용 (워커 라우트). anon/authenticated 회수.
--   RLS 우회는 의도 — 워커는 시스템 권한으로 모든 클립 폴링 필요.
--
-- 성능:
--   STABLE 마킹 → 같은 트랜잭션 안에서 캐싱 가능.
--   behavior_logs UNIQUE(clip_id, source) 인덱스 → NOT EXISTS subquery 빠름.
--
-- 동시성:
--   N대 워커가 같은 clip_id 받아도 INSERT 시 UNIQUE 23505 → race-loser 처리.

CREATE OR REPLACE FUNCTION public.fn_vlm_pending_clips(p_limit int DEFAULT 10)
RETURNS TABLE (
  id uuid,
  r2_key text,
  pet_id uuid,
  species_id text
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT
    cc.id,
    cc.r2_key,
    cc.pet_id,
    p.species_id
  FROM camera_clips cc
  LEFT JOIN pets p ON p.id = cc.pet_id
  WHERE cc.has_motion = true
    AND cc.r2_key IS NOT NULL
    AND NOT EXISTS (
      SELECT 1 FROM behavior_logs bl
      WHERE bl.clip_id = cc.id
        AND bl.source IN ('vlm', 'vlm_failed')
    )
  ORDER BY cc.started_at ASC
  LIMIT p_limit;
$$;

REVOKE ALL ON FUNCTION public.fn_vlm_pending_clips(int) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.fn_vlm_pending_clips(int) FROM anon;
REVOKE ALL ON FUNCTION public.fn_vlm_pending_clips(int) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.fn_vlm_pending_clips(int) TO service_role;

COMMENT ON FUNCTION public.fn_vlm_pending_clips(int) IS
  'VLM 워커 폴링 — has_motion=true & r2_key NOT NULL & behavior_logs 에 source IN (vlm, vlm_failed) row 없는 clip 들. ORDER BY started_at ASC (oldest first). service_role 전용.';
