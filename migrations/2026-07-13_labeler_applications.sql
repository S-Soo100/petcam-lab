-- 라벨러 공개 가입 신청 + owner 승인 상태.
--
-- 상태: 작성 완료, production 미적용.
-- 적용 순서: 이 migration 적용 → 기존 labelers backfill 검증 → web preview 배포.
-- 실제 영상 접근 권한의 SOT는 public.labelers 이며, application.status 단독으로
-- 접근을 허용하면 안 된다.

BEGIN;

CREATE TABLE IF NOT EXISTS public.labeler_applications (
  user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  email TEXT NOT NULL,
  display_name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  reviewed_at TIMESTAMPTZ,
  reviewed_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  CONSTRAINT labeler_applications_display_name_check
    CHECK (
      display_name = BTRIM(display_name)
      AND CHAR_LENGTH(display_name) BETWEEN 1 AND 80
    ),
  CONSTRAINT labeler_applications_status_check
    CHECK (status IN ('pending', 'approved', 'rejected')),
  CONSTRAINT labeler_applications_review_check
    CHECK (
      (status = 'pending' AND reviewed_at IS NULL AND reviewed_by IS NULL)
      OR
      (status IN ('approved', 'rejected') AND reviewed_at IS NOT NULL)
    )
);

COMMENT ON TABLE public.labeler_applications IS
  '라벨링 웹 가입 신청. 승인 상태 기록이며 실제 영상 접근 권한 SOT는 labelers 테이블.';
COMMENT ON COLUMN public.labeler_applications.email IS
  '신청 당시 auth.users.email snapshot. 브라우저 입력값을 직접 신뢰하지 않는다.';
COMMENT ON COLUMN public.labeler_applications.status IS
  'pending/approved/rejected. deactivate는 rejected로 기록하고 labelers row를 제거한다.';

CREATE INDEX IF NOT EXISTS idx_labeler_applications_status_requested_at
  ON public.labeler_applications (status, requested_at DESC);

ALTER TABLE public.labeler_applications ENABLE ROW LEVEL SECURITY;

-- service_role API만 접근한다. 일반 로그인 사용자는 본인 신청도 테이블에 직접 쓰지 않고
-- JWT를 검증하는 Next.js route를 사용한다.
REVOKE ALL ON TABLE public.labeler_applications FROM PUBLIC;
REVOKE ALL ON TABLE public.labeler_applications FROM anon;
REVOKE ALL ON TABLE public.labeler_applications FROM authenticated;
GRANT ALL ON TABLE public.labeler_applications TO service_role;

-- 기존 라벨러가 migration 직후 pending/unregistered로 떨어지지 않도록 backfill한다.
-- added_by가 없던 legacy row는 reviewed_by를 NULL로 보존한다. review_check는
-- approved/rejected의 reviewed_at만 필수로 하므로 이 이력을 수용한다.
INSERT INTO public.labeler_applications (
  user_id,
  email,
  display_name,
  status,
  requested_at,
  reviewed_at,
  reviewed_by,
  updated_at
)
SELECT
  l.user_id,
  COALESCE(u.email, 'unknown-' || l.user_id::TEXT || '@invalid.local'),
  LEFT(
    COALESCE(
      NULLIF(BTRIM(u.raw_user_meta_data ->> 'display_name'), ''),
      NULLIF(SPLIT_PART(COALESCE(u.email, ''), '@', 1), ''),
      '기존 라벨러'
    ),
    80
  ),
  'approved',
  l.added_at,
  l.added_at,
  l.added_by,
  l.added_at
FROM public.labelers AS l
JOIN auth.users AS u ON u.id = l.user_id
ON CONFLICT (user_id) DO NOTHING;

-- 승인/거절/권한 해제를 단일 transaction 안에서 수행한다.
-- 이 함수는 service_role만 실행할 수 있고, 호출 전 Next.js API가 DEV_USER_ID로
-- owner를 검증한다. service_role 자체가 침해되면 DB 전체가 침해된 것이므로 함수가
-- 별도 owner allowlist를 중복 보유하지 않는다.
CREATE OR REPLACE FUNCTION public.fn_review_labeler_application(
  p_user_id UUID,
  p_reviewer_id UUID,
  p_decision TEXT
)
RETURNS public.labeler_applications
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_application public.labeler_applications%ROWTYPE;
BEGIN
  IF p_decision NOT IN ('approve', 'reject', 'deactivate') THEN
    RAISE EXCEPTION 'invalid decision'
      USING ERRCODE = '22023';
  END IF;

  IF p_user_id = p_reviewer_id THEN
    RAISE EXCEPTION 'owner cannot review own access'
      USING ERRCODE = '22023';
  END IF;

  SELECT *
  INTO v_application
  FROM public.labeler_applications
  WHERE user_id = p_user_id
  FOR UPDATE;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'application not found'
      USING ERRCODE = 'P0002';
  END IF;

  IF p_decision = 'approve' THEN
    INSERT INTO public.labelers (user_id, added_by, note)
    VALUES (p_user_id, p_reviewer_id, '라벨링 웹 owner 승인')
    ON CONFLICT (user_id) DO UPDATE
      SET added_by = EXCLUDED.added_by;

    UPDATE public.labeler_applications
    SET
      status = 'approved',
      reviewed_at = NOW(),
      reviewed_by = p_reviewer_id,
      updated_at = NOW()
    WHERE user_id = p_user_id
    RETURNING * INTO v_application;
  ELSE
    DELETE FROM public.labelers
    WHERE user_id = p_user_id;

    UPDATE public.labeler_applications
    SET
      status = 'rejected',
      reviewed_at = NOW(),
      reviewed_by = p_reviewer_id,
      updated_at = NOW()
    WHERE user_id = p_user_id
    RETURNING * INTO v_application;
  END IF;

  RETURN v_application;
END;
$$;

REVOKE ALL ON FUNCTION public.fn_review_labeler_application(UUID, UUID, TEXT)
  FROM PUBLIC;
REVOKE ALL ON FUNCTION public.fn_review_labeler_application(UUID, UUID, TEXT)
  FROM anon;
REVOKE ALL ON FUNCTION public.fn_review_labeler_application(UUID, UUID, TEXT)
  FROM authenticated;
GRANT EXECUTE ON FUNCTION public.fn_review_labeler_application(UUID, UUID, TEXT)
  TO service_role;

COMMENT ON FUNCTION public.fn_review_labeler_application(UUID, UUID, TEXT) IS
  'owner 승인/거절/권한 해제 원자 처리. approve는 labelers upsert, reject/deactivate는 labelers delete.';

COMMIT;

-- 적용 후 검증 쿼리:
--
-- SELECT status, COUNT(*)
-- FROM public.labeler_applications
-- GROUP BY status
-- ORDER BY status;
--
-- SELECT COUNT(*) AS approved_without_labeler
-- FROM public.labeler_applications AS a
-- LEFT JOIN public.labelers AS l ON l.user_id = a.user_id
-- WHERE a.status = 'approved' AND l.user_id IS NULL;
--
-- SELECT COUNT(*) AS unauthorized_table_policies
-- FROM pg_policies
-- WHERE schemaname = 'public' AND tablename = 'labeler_applications';
-- 기대값: approved_without_labeler = 0, unauthorized_table_policies = 0.

-- 롤백(웹 코드를 먼저 이전한 뒤 실행):
-- BEGIN;
-- DROP FUNCTION IF EXISTS public.fn_review_labeler_application(UUID, UUID, TEXT);
-- DROP TABLE IF EXISTS public.labeler_applications;
-- COMMIT;
