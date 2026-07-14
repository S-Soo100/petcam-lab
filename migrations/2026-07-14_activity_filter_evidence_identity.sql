-- 목적: clip_prelabels evidence identity 확장 — 멱등 키에 checkpoint_sha256 + threshold + sampler_version 추가.
--   audit(같은 clip 을 threshold 0.25 vs 0.10 재추론: 0.25=no_gecko, 0.10=gecko conf 0.14~0.21)에서
--   기존 (clip_id, model_version, schema_version) 키로는 서로 다른 threshold evidence 가 upsert 로
--   덮여 보존·비교 불가한 문제를 해결. evidence 는 "어떤 아티팩트/threshold/sampler 로 뽑았나"까지가 정체성.
-- 적용 이력: 2026-07-14 작성. 선행 `2026-07-14_activity_filter_v0.sql` 은 **수정하지 않고** forward migration 추가.
-- 안전: clip_prelabels 현재 0건 → 제약 교체에 중복 위험 없음(운영 데이터 있으면 사전 중복 검사 필요).
-- store 코드(activity_store.py)의 upsert on_conflict 6컬럼과 정합 — 이 제약이 없으면 ON CONFLICT 실패.

alter table public.clip_prelabels
  drop constraint if exists clip_prelabels_clip_id_model_version_schema_version_key;

alter table public.clip_prelabels
  add constraint clip_prelabels_identity_key
  unique (clip_id, model_version, schema_version, checkpoint_sha256, threshold, sampler_version);

-- === 검증 probe (apply 후) ===
--   select conname, pg_get_constraintdef(oid) from pg_constraint
--     where conrelid='public.clip_prelabels'::regclass and contype='u';   -- identity_key 6컬럼
-- === 롤백 ===
--   alter table public.clip_prelabels drop constraint clip_prelabels_identity_key;
--   alter table public.clip_prelabels
--     add constraint clip_prelabels_clip_id_model_version_schema_version_key
--     unique (clip_id, model_version, schema_version);
