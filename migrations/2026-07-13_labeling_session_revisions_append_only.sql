-- revision 감사 로그 append-only 강제 트리거 — 2026-07-13 (후속).
--
-- 원본(_labeling_session_revisions.sql)은 anon/authenticated 에서 REVOKE ALL 하고
-- service_role 에는 GRANT ALL 을 줬다. 그래서 service_role 로 도는 Next.js API 키가
-- (실수든 유출이든) clip_labeling_session_revisions 를 UPDATE·DELETE 할 수 있었다 →
-- append-only "감사 로그" 계약이 성립하지 않았다.
--
-- 트리거는 실행 역할과 무관하게(session_replication_role='replica' 슈퍼유저 우회 제외)
-- 발동하므로, service_role 을 포함해 누구도 UPDATE/DELETE/TRUNCATE 하지 못하게 여기서 강제한다.
-- INSERT 는 계속 허용(RPC 가 감사행을 추가하는 정상 경로).
--
-- ⚠️ 부수효과(의도): revision 을 참조하는 FK 는 ON DELETE CASCADE 다. 이 트리거가 있으면
--    revision 이 달린 camera_clip/session/auth.user 를 hard-delete 할 때 CASCADE 삭제가
--    이 트리거에 막혀 부모 삭제도 실패한다. 감사행은 영구 보존이 원칙이므로 의도된 동작이다.
--    부모를 지워야 하면 먼저 아카이브/분리한다(운영상 clip hard-delete 는 사실상 없음).
--
-- ✅ Supabase 적용 완료 2026-07-13 (MCP apply_migration). rollback probe 통과:
--    감사행 1건 INSERT 후 UPDATE·DELETE 시도 → 둘 다 0A000 로 차단, 전량 롤백.

BEGIN;

-- 이 함수는 RAISE 만 하고 DB 객체를 참조하지 않지만, search_path 를 고정해 린터 WARN 을 없앤다.
CREATE OR REPLACE FUNCTION public.fn_block_session_revision_mutation()
RETURNS trigger LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN
  RAISE EXCEPTION 'clip_labeling_session_revisions is append-only (UPDATE/DELETE/TRUNCATE 금지)'
    USING ERRCODE = '0A000';  -- feature_not_supported
END;
$$;

-- 트리거 함수는 트리거 발동 시 실행되므로 별도 EXECUTE 권한이 필요없다. 방어적으로 REVOKE.
REVOKE ALL ON FUNCTION public.fn_block_session_revision_mutation() FROM PUBLIC;

-- 행 단위 UPDATE/DELETE 차단.
DROP TRIGGER IF EXISTS trg_block_session_revision_row_mutation
  ON public.clip_labeling_session_revisions;
CREATE TRIGGER trg_block_session_revision_row_mutation
  BEFORE UPDATE OR DELETE ON public.clip_labeling_session_revisions
  FOR EACH ROW EXECUTE FUNCTION public.fn_block_session_revision_mutation();

-- TRUNCATE 는 행 트리거를 우회하므로 statement 단위로 따로 차단.
DROP TRIGGER IF EXISTS trg_block_session_revision_truncate
  ON public.clip_labeling_session_revisions;
CREATE TRIGGER trg_block_session_revision_truncate
  BEFORE TRUNCATE ON public.clip_labeling_session_revisions
  FOR EACH STATEMENT EXECUTE FUNCTION public.fn_block_session_revision_mutation();

COMMIT;

-- ── 검증 (DO 블록 롤백 probe, REPORT 참고) ─────────────────────────
-- BEGIN;
--   실제 completed 세션에서 감사행 1건 INSERT →
--   UPDATE ... → 0A000, DELETE ... → 0A000 확인 →
-- ROLLBACK; (INSERT 도 롤백, 잔류 0)

-- ── 롤백 ───────────────────────────────────────────────────────────
-- DROP TRIGGER IF EXISTS trg_block_session_revision_row_mutation ON public.clip_labeling_session_revisions;
-- DROP TRIGGER IF EXISTS trg_block_session_revision_truncate ON public.clip_labeling_session_revisions;
-- DROP FUNCTION IF EXISTS public.fn_block_session_revision_mutation();
