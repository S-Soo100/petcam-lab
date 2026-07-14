-- 목적: clip_prelabels evidence identity 에 frames_sampled 추가 (6→7컬럼).
--   sampler config 는 sampler_version 만으론 부족 — 샘플 프레임 수가 다르면 다른 입력이므로 다른 evidence.
-- 적용 이력: 2026-07-14 작성. 선행 `2026-07-14_activity_filter_evidence_identity.sql`(적용됨)은 **수정하지 않고**
--   forward migration 추가. clip_prelabels 0건이라 제약 교체 안전.
-- store 코드(activity_store.py)의 upsert on_conflict 7컬럼 + find_prelabel 7컬럼과 정합.

alter table public.clip_prelabels
  drop constraint if exists clip_prelabels_identity_key;

alter table public.clip_prelabels
  add constraint clip_prelabels_identity_key
  unique (clip_id, model_version, schema_version, checkpoint_sha256, threshold, sampler_version, frames_sampled);

-- === 검증 probe (apply 후) ===
--   select conname, pg_get_constraintdef(oid) from pg_constraint
--     where conrelid='public.clip_prelabels'::regclass and contype='u';   -- identity_key 7컬럼
-- === 롤백 ===
--   alter table public.clip_prelabels drop constraint clip_prelabels_identity_key;
--   alter table public.clip_prelabels add constraint clip_prelabels_identity_key
--     unique (clip_id, model_version, schema_version, checkpoint_sha256, threshold, sampler_version);
