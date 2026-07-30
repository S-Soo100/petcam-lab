-- Formal Blind30 disposable DB probe용 tutorial 최소 schema.
--
-- production 데이터를 복사하지 않고 fn_create_motion_blind_formal30이 읽는 onboarding
-- 자격 증명만 합성한다. 이 파일은 무작위 local 임시 DB에만 적용된다.

CREATE TABLE public.labeling_tutorial_sets (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  version text NOT NULL UNIQUE,
  status text NOT NULL CHECK (status IN ('draft','active','retired'))
);

CREATE TABLE public.labeling_tutorial_lessons (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tutorial_set_id uuid NOT NULL REFERENCES public.labeling_tutorial_sets(id),
  position integer NOT NULL CHECK (position BETWEEN 1 AND 5),
  clip_id uuid REFERENCES public.motion_clips(id),
  UNIQUE (tutorial_set_id, position)
);

CREATE TABLE public.labeling_tutorial_progress (
  tutorial_set_id uuid NOT NULL REFERENCES public.labeling_tutorial_sets(id),
  user_id uuid NOT NULL REFERENCES auth.users(id),
  current_run_no integer NOT NULL DEFAULT 1 CHECK (current_run_no >= 1),
  completed_at timestamptz,
  waived_at timestamptz,
  PRIMARY KEY (tutorial_set_id, user_id)
);

CREATE TABLE public.labeling_tutorial_attempts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tutorial_set_id uuid NOT NULL REFERENCES public.labeling_tutorial_sets(id),
  lesson_id uuid NOT NULL REFERENCES public.labeling_tutorial_lessons(id),
  user_id uuid NOT NULL REFERENCES auth.users(id),
  run_no integer NOT NULL CHECK (run_no >= 1),
  stage text NOT NULL CHECK (stage IN ('started','completed')),
  completed_at timestamptz,
  UNIQUE (tutorial_set_id, lesson_id, user_id, run_no)
);

GRANT SELECT ON TABLE
  public.labelers,
  public.labeler_applications,
  public.labeling_tutorial_sets,
  public.labeling_tutorial_lessons,
  public.labeling_tutorial_progress,
  public.labeling_tutorial_attempts
TO service_role;
