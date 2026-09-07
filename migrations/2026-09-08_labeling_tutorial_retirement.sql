-- 대화형 튜토리얼 트랙 퇴역 (owner 결정 2026-09-07, docs/decision-gate.md 2026-09-07 4차).
--
-- 화면(/labeling/tutorial)·API(/api/labeling-tutorial)·접근 게이트·팀 관리 진행률은 코드에서 제거했다.
-- 여기서는 DB 쪽만 정리한다:
-- - labeling_tutorial_sets/lessons/progress/attempts 테이블과 row 는 **보존**(역사 기록, DROP 없음).
-- - 튜토리얼 RPC 는 service_role EXECUTE 만 회수한다(존재할 때만, DROP 없음) — 이중 blind 퇴역
--   (2026-09-08_labeling_v4_simplification.sql)과 같은 패턴.
--
-- 시그니처 출처: migrations/2026-07-13_labeling_tutorial.sql §권한 + _hardening*.sql.
BEGIN;

DO $$
DECLARE
  sig text;
BEGIN
  FOREACH sig IN ARRAY ARRAY[
    'public.fn_seed_tutorial_lesson_from_owner(uuid, smallint, uuid, uuid, text, text, text, jsonb)',
    'public.fn_activate_tutorial_set(uuid, uuid)',
    'public.fn_acknowledge_tutorial_lesson(uuid, uuid)',
    'public.fn_reset_tutorial(uuid, uuid, uuid)',
    'public.fn_waive_tutorial(uuid, uuid, uuid, text)'
  ] LOOP
    IF to_regprocedure(sig) IS NOT NULL THEN
      EXECUTE format('REVOKE EXECUTE ON FUNCTION %s FROM service_role', sig);
    END IF;
  END LOOP;
END $$;

COMMIT;
