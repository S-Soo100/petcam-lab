-- 요청4(A): behavior_logs owner SELECT RLS — 앱 크레캠 상세 "비디오 기록" 분류 필터/칩 활성화
-- 핸드오프: tera-ai-flutter/docs/backend-handoff-camera-detail-ux.md §요청4
--
-- 적용 이력 (2026-07-08): Supabase MCP apply_migration 으로 production 적용 + 자체검증 완료.
--   - 정책: "owner reads own clip labels" (SELECT, to authenticated)
--   - 검증 B(로직 재현): 전체 1539행 중 owner e2d0…=1167 만 노출, bogus owner=0.
--   - 검증 C(런타임): authenticated role + JWT sub 주입 시뮬레이션 → readable=1167 (B와 일치).
--
-- 배경:
--   behavior_logs 는 RLS on + 정책 0개 = authenticated 전면 차단 상태였음.
--   앱은 terra-api(api.terra-server.uk)가 아니라 Supabase 직결(RLS)로 이 테이블을 읽는데,
--   정책이 없어 본인 카메라 clip 의 VLM/human 분류를 못 읽음 → 상세 분류 필터/칩이 전부 0건.
--
--   owner 판정 = motion_clips.owner_id (⚠️ camera_clips.user_id 와 컬럼명 다름).
--   미러 규칙상 behavior_logs.clip_id = motion_clips.id (동일 UUID) → 등호 조인.
--
--   SELECT 만 부여 — 앱은 behavior_logs 에 쓰지 않음(HITL 쓰기는 behavior_labels).
--   service-role(백엔드/워커)은 RLS 우회 → 영향 없음. anon 은 정책 대상 아님 → deny 유지.
--
-- ⚠️ raw 노출: 본인 clip 한정이지만 reasoning/notes/corrected_to 원본 컬럼까지 읽힘.
--    앱은 SELECT 컬럼을 action/confidence/source 로 제한 권장. 대표라벨 1개+오탐 억제 큐레이션이
--    필요해지면 이 raw 정책 대신 curated VIEW 로 후속 전환(요청4 Option B 대체).
--
-- 롤백:
--   drop policy if exists "owner reads own clip labels" on public.behavior_logs;

drop policy if exists "owner reads own clip labels" on public.behavior_logs;

create policy "owner reads own clip labels" on public.behavior_logs
  for select
  to authenticated
  using (
    exists (
      select 1
      from public.motion_clips mc
      where mc.id = behavior_logs.clip_id
        and mc.owner_id = auth.uid()
    )
  );
