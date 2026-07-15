-- Applied labeling triage migration forward-hardening.
-- Supabase default privileges grant newly created functions directly to API roles,
-- so revoking PUBLIC alone does not remove those explicit EXECUTE grants.
BEGIN;

REVOKE ALL ON FUNCTION public.fn_guard_labeling_session_vs_triage()
  FROM PUBLIC, anon, authenticated, service_role;

COMMIT;
