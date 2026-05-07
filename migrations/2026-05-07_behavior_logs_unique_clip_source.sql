-- feature-vlm-worker-cloud.md §4-2 — idempotent VLM 워커
--
-- 적용 이력 (2026-05-07): Supabase MCP `apply_migration` 으로 production 적용 완료.
--   - 사전 dedup: 656 → 318 rows (338 dup 삭제, latest 1건 보존, ORDER BY created_at DESC, id DESC)
--   - CHECK 갱신: 'vlm_failed' 추가 (워커 영구 에러 시 idempotency 용 INSERT 허용)
--   - UNIQUE(clip_id, source) 추가
--
-- 목적:
--   1) 워커가 같은 clip 에 같은 source 로 중복 INSERT 못하게 차단 (UNIQUE).
--      폴링은 NOT EXISTS 로 1차 방어 (§4-1), 동시 워커 race 의 최후 보호막이 이 UNIQUE.
--   2) 영구 에러 시 워커가 `source='vlm_failed'` row 를 박을 수 있도록 CHECK 확장.
--      (그래야 같은 clip 무한 재시도 안 됨)
--
-- 사전 dedup (PoC 시절 button-driven inference 가 같은 clip 에 N 회 INSERT) — UNIQUE 추가 전 필수:
--
--   WITH ranked AS (
--     SELECT id, ROW_NUMBER() OVER (
--       PARTITION BY clip_id, source ORDER BY created_at DESC, id DESC
--     ) AS rn
--     FROM behavior_logs
--   )
--   DELETE FROM behavior_logs WHERE id IN (SELECT id FROM ranked WHERE rn > 1);
--
--   가장 최신 1건만 보존. PoC 시절 inference 가 여러 번 호출됐어도 마지막 것이 정답에
--   가까울 가능성. 더 보존이 필요하면 source='vlm_v0', 'vlm_v1' 같이 미리 분리.
--
-- 롤백:
--   ALTER TABLE behavior_logs DROP CONSTRAINT behavior_logs_clip_source_unique;
--   -- CHECK 는 원복 시 'vlm_failed' INSERT 차단되므로, 워커 멈춘 뒤에만:
--   ALTER TABLE behavior_logs DROP CONSTRAINT behavior_logs_source_check;
--   ALTER TABLE behavior_logs ADD CONSTRAINT behavior_logs_source_check
--     CHECK (source = ANY (ARRAY['vlm'::text, 'human'::text, 'yolo'::text]));

-- 1) source CHECK 갱신: 'vlm_failed' 추가.
--    기존 제약명을 pg_constraint 에서 동적으로 찾아 drop (네이밍 변동 대비).
DO $$
DECLARE
  cname text;
BEGIN
  SELECT con.conname INTO cname
  FROM pg_constraint con
  JOIN pg_class rel ON rel.oid = con.conrelid
  JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
  WHERE nsp.nspname = 'public'
    AND rel.relname = 'behavior_logs'
    AND con.contype = 'c'
    AND pg_get_constraintdef(con.oid) ILIKE '%source%';
  IF cname IS NOT NULL THEN
    EXECUTE format('ALTER TABLE public.behavior_logs DROP CONSTRAINT %I', cname);
  END IF;
END $$;

ALTER TABLE public.behavior_logs
  ADD CONSTRAINT behavior_logs_source_check
  CHECK (source = ANY (ARRAY['vlm'::text, 'human'::text, 'yolo'::text, 'vlm_failed'::text]));

-- 2) UNIQUE(clip_id, source). 사전 dedup 후에만 통과.
ALTER TABLE public.behavior_logs
  ADD CONSTRAINT behavior_logs_clip_source_unique UNIQUE (clip_id, source);
