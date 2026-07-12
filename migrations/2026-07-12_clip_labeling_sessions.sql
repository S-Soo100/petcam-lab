-- Labeling Web v2: blind GT -> VLM review staged workflow.
-- prediction_snapshot은 GT 잠금 시 서버가 복사하며 클라이언트 입력을 받지 않는다.

create table if not exists public.clip_labeling_sessions (
  id uuid primary key default gen_random_uuid(),
  clip_id uuid not null references public.camera_clips(id) on delete cascade,
  reviewed_by uuid not null references auth.users(id) on delete cascade,
  stage text not null default 'draft'
    check (stage in ('draft', 'gt_locked', 'completed')),
  initial_gt jsonb,
  current_gt jsonb,
  prediction_snapshot jsonb,
  vlm_verdict text
    check (vlm_verdict in ('correct', 'partially_correct', 'incorrect', 'unjudgeable')),
  vlm_error_tags text[] not null default '{}',
  vlm_review_note text,
  completion_reason text
    check (completion_reason in ('vlm_reviewed', 'no_prediction')),
  gt_locked_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (clip_id, reviewed_by),
  check ((initial_gt is null and stage = 'draft') or initial_gt is not null),
  check ((stage <> 'completed') or completed_at is not null)
);

create index if not exists idx_clip_labeling_sessions_reviewer_stage
  on public.clip_labeling_sessions (reviewed_by, stage, updated_at desc);

alter table public.clip_labeling_sessions enable row level security;

drop policy if exists "reviewers read own labeling sessions"
  on public.clip_labeling_sessions;
create policy "reviewers read own labeling sessions"
  on public.clip_labeling_sessions for select
  using (reviewed_by = auth.uid());

drop policy if exists "reviewers create own labeling sessions"
  on public.clip_labeling_sessions;
create policy "reviewers create own labeling sessions"
  on public.clip_labeling_sessions for insert
  with check (reviewed_by = auth.uid());

drop policy if exists "reviewers update own labeling sessions"
  on public.clip_labeling_sessions;
create policy "reviewers update own labeling sessions"
  on public.clip_labeling_sessions for update
  using (reviewed_by = auth.uid())
  with check (reviewed_by = auth.uid());

create or replace function public.protect_initial_labeling_gt()
returns trigger
language plpgsql
as $$
begin
  if old.initial_gt is not null and new.initial_gt is distinct from old.initial_gt then
    raise exception 'initial_gt is immutable after GT lock';
  end if;
  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists protect_initial_labeling_gt
  on public.clip_labeling_sessions;
create trigger protect_initial_labeling_gt
before update on public.clip_labeling_sessions
for each row execute function public.protect_initial_labeling_gt();

comment on table public.clip_labeling_sessions is
  'Blind human GT followed by an exact VLM prediction review snapshot.';
comment on column public.clip_labeling_sessions.initial_gt is
  'Immutable first human answer, recorded before revealing VLM output.';
comment on column public.clip_labeling_sessions.prediction_snapshot is
  'Exact behavior_logs source=vlm row captured by the server at GT lock.';
