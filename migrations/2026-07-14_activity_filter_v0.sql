-- 목적: 테스트 카메라 활동시간 필터 v0.
--   Gate evidence(clip_prelabels) + four-state 활동판정(clip_activity_assessments)
--   + 카메라별 독립 스위치(camera_activity_filter_settings) + 읽기계약 view.
--   앱 "활동시간"에서 명확한 비활동 clip(absent/static) 길이를 0으로 제외. 원본 motion_clips/R2 불변.
-- 적용 이력: 2026-07-14 작성. apply_migration MCP 적용 예정(rollback transaction probe 검증 후, 사용자 승인 필요).
-- 보안: RLS — service_role 만 write, authenticated 는 "자기 motion_clips 소속" 결과만 read.
--   설정 row 없으면 필터 비활성(fail-open). 카메라 UUID 하드코딩 없음(Phase 5 사용자가 INSERT).
-- FK: 기존 연구 테이블은 camera_clips(id) FK 지만, 이 세 테이블은 운영 SOT + Flutter 정합을 위해
--   motion_clips(id) FK (지시문 §157, motion_clips 직접 조회하는 앱 활동시간과 계약 일치).
-- 롤백: 파일 하단 주석 참조. 즉시 무력화는 settings.enabled=false (앱 재배포 없이 raw 복귀).

-- ============================================================================
-- 1. Gate evidence — clip_prelabels
-- ============================================================================
create table if not exists public.clip_prelabels (
  id                   uuid primary key default gen_random_uuid(),
  clip_id              uuid not null references public.motion_clips(id) on delete cascade,
  -- provenance (재현/감사: 어떤 artifact 가 만들었나)
  model_name           text not null,
  model_version        text not null,
  checkpoint_sha256    text not null,
  threshold            real not null,
  sampler_version      text not null,
  schema_version       text not null,
  frames_sampled       integer not null,
  -- evidence (손실 없이)
  gecko_visible        boolean not null,
  visibility_confidence real not null,
  best_frame_ts        real,
  gecko_bbox           jsonb,
  detected_objects     jsonb not null default '[]'::jsonb,
  motion_metrics       jsonb,
  producer_host        text,
  producer_run_id      text,
  created_at           timestamptz not null default now(),
  -- 멱등: 같은 clip + 같은 Gate 실행 버전
  unique (clip_id, model_version, schema_version)
);
create index if not exists idx_clip_prelabels_clip on public.clip_prelabels (clip_id);

-- ============================================================================
-- 2. 제품 판정 — clip_activity_assessments (evidence 와 분리)
-- ============================================================================
create table if not exists public.clip_activity_assessments (
  id             uuid primary key default gen_random_uuid(),
  clip_id        uuid not null references public.motion_clips(id) on delete cascade,
  prelabel_id    uuid not null references public.clip_prelabels(id) on delete cascade,
  decision       text not null check (decision in ('active','exclude_absent','exclude_static','unknown')),
  reason_code    text not null,
  measurements   jsonb,
  policy_version text not null,
  producer_host  text,
  producer_run_id text,
  created_at     timestamptz not null default now(),
  -- 멱등: 같은 clip + 같은 policy. 새 policy_version = 새 row(재평가 이력 보존, 덮어쓰지 않음)
  unique (clip_id, policy_version)
);
create index if not exists idx_clip_activity_assess_clip on public.clip_activity_assessments (clip_id);

-- ============================================================================
-- 3. 카메라별 독립 스위치 — camera_activity_filter_settings
-- ============================================================================
create table if not exists public.camera_activity_filter_settings (
  camera_id              uuid primary key references public.cameras(id) on delete cascade,
  enabled                boolean not null default false,
  exclude_absent_enabled boolean not null default false,   -- 독립 스위치
  exclude_static_enabled boolean not null default false,   -- 독립 스위치
  active_policy_version  text,
  updated_at             timestamptz not null default now(),
  updated_by             uuid references auth.users(id),    -- 최소 감사
  note                   text
);
-- 설정 row 가 없으면 필터 비활성 = fail-open. 테스트 카메라 UUID 는 여기에 넣지 않는다.

-- ============================================================================
-- 4. RLS — service_role write, authenticated owner read (behavior_logs 패턴)
-- ============================================================================
alter table public.clip_prelabels enable row level security;
alter table public.clip_activity_assessments enable row level security;
alter table public.camera_activity_filter_settings enable row level security;

create policy "owner reads own clip prelabels" on public.clip_prelabels
  for select to authenticated
  using (exists (select 1 from public.motion_clips mc
                 where mc.id = clip_prelabels.clip_id and mc.owner_id = auth.uid()));

create policy "owner reads own clip assessments" on public.clip_activity_assessments
  for select to authenticated
  using (exists (select 1 from public.motion_clips mc
                 where mc.id = clip_activity_assessments.clip_id and mc.owner_id = auth.uid()));

create policy "owner reads own camera filter settings" on public.camera_activity_filter_settings
  for select to authenticated
  using (exists (select 1 from public.cameras c
                 where c.id = camera_activity_filter_settings.camera_id and c.owner_id = auth.uid()));

-- write 정책 0건 → anon/authenticated write 불가. service_role 만 (RLS 우회).
revoke all on public.clip_prelabels from anon, authenticated;
revoke all on public.clip_activity_assessments from anon, authenticated;
revoke all on public.camera_activity_filter_settings from anon, authenticated;
grant select on public.clip_prelabels to authenticated;
grant select on public.clip_activity_assessments to authenticated;
grant select on public.camera_activity_filter_settings to authenticated;
grant all on public.clip_prelabels to service_role;
grant all on public.clip_activity_assessments to service_role;
grant all on public.camera_activity_filter_settings to service_role;

-- ============================================================================
-- 5. 읽기 계약 view — 전체·시간대별 활동시간이 같은 effective_activity_sec 사용
-- ============================================================================
create or replace view public.v_clip_effective_activity with (security_invoker = on) as
select
  mc.id            as clip_id,
  mc.camera_id,
  mc.owner_id,
  mc.started_at,
  mc.duration_sec  as raw_duration_sec,
  coalesce(caa.decision, 'pending') as activity_decision,
  case
    when s.camera_id is null or not s.enabled then mc.duration_sec
    when caa.decision = 'exclude_absent' and s.exclude_absent_enabled then 0::double precision
    when caa.decision = 'exclude_static' and s.exclude_static_enabled then 0::double precision
    else mc.duration_sec
  end              as effective_activity_sec,
  (caa.clip_id is null) as analysis_pending,
  s.active_policy_version as policy_version
from public.motion_clips mc
left join public.camera_activity_filter_settings s on s.camera_id = mc.camera_id
left join public.clip_activity_assessments caa
  on caa.clip_id = mc.id and caa.policy_version = s.active_policy_version;
-- security_invoker → motion_clips owner RLS 상속(자기 clip 만). 필터 미적용 카메라는 raw 반환.
grant select on public.v_clip_effective_activity to authenticated;

-- ============================================================================
-- 검증 probe (apply 후 수동/자동 실행)
-- ============================================================================
--  a) select count(*) from public.clip_prelabels;                       -- 0
--  b) 설정 없음 = raw: select clip_id, raw_duration_sec, effective_activity_sec, analysis_pending
--        from public.v_clip_effective_activity limit 5;                 -- effective == raw, pending=true
--  c) 타 owner read 거부: set role authenticated; set request.jwt.claims ... (다른 owner) →
--        select count(*) from public.clip_prelabels;                    -- 0 (RLS)

-- ============================================================================
-- 롤백 SQL (기능 완전 제거)
-- ============================================================================
--  즉시 무력화(권장, 앱 재배포 불필요):
--    update public.camera_activity_filter_settings set enabled = false;
--  완전 제거:
--    drop view  if exists public.v_clip_effective_activity;
--    drop table if exists public.clip_activity_assessments;
--    drop table if exists public.clip_prelabels;
--    drop table if exists public.camera_activity_filter_settings;
