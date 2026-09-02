begin;

-- 개체를 사육장에 연결한다. 기존 행은 null이므로 이 migration은 데이터를 재작성하지 않는다.
alter table public.pets
  add column enclosure_id uuid
  constraint pets_enclosure_id_fkey
  references public.enclosures(id) on delete set null;

comment on column public.pets.enclosure_id is
  '이 개체가 배정된 사육장. null은 미배정이며 한 사육장에는 개체 한 마리만 배정한다.';

-- null은 여러 행에 허용하고 실제 사육장 배정만 1:1로 강제한다.
create unique index pets_enclosure_id_unique
  on public.pets (enclosure_id)
  where enclosure_id is not null;

-- 직접 UPDATE 경로도 다른 사용자 사육장을 참조하지 못하게 막는다.
create function public.pets_enclosure_owner_guard()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_owner uuid;
begin
  if new.enclosure_id is null then
    return new;
  end if;

  select e.owner_id
    into v_owner
    from public.enclosures e
   where e.id = new.enclosure_id;

  if not found then
    raise exception 'enclosure not found'
      using errcode = 'foreign_key_violation';
  end if;

  if new.user_id is null or v_owner is distinct from new.user_id then
    raise exception 'pet and enclosure ownership mismatch'
      using errcode = 'insufficient_privilege';
  end if;

  return new;
end;
$$;

revoke all on function public.pets_enclosure_owner_guard()
  from public, anon, authenticated;

create trigger pets_enclosure_owner_guard_trg
  before insert or update of enclosure_id, user_id on public.pets
  for each row execute function public.pets_enclosure_owner_guard();

-- Flutter가 사용하는 원자적 배정 경로. 같은 사용자의 동시 배정은 직렬화해
-- 부분 UNIQUE 오류나 교차 swap deadlock 대신 마지막 정상 요청이 완결되게 한다.
create function public.assign_pet_to_enclosure(
  p_pet_id uuid,
  p_enclosure_id uuid
)
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_uid uuid := auth.uid();
  v_pet_owner uuid;
  v_enclosure_owner uuid;
begin
  if v_uid is null then
    raise exception 'not authenticated'
      using errcode = 'invalid_authorization_specification';
  end if;

  -- 같은 사용자의 배정 변경을 한 줄로 세운다. 서로 다른 사용자는 소유권상
  -- 같은 pet/enclosure를 만질 수 없으므로 불필요하게 막지 않는다.
  perform pg_catalog.pg_advisory_xact_lock(
    1346720837,
    pg_catalog.hashtext(v_uid::text)
  );

  select p.user_id
    into v_pet_owner
    from public.pets p
   where p.id = p_pet_id
   for update;

  if not found then
    raise exception 'pet not found'
      using errcode = 'no_data_found';
  end if;

  if v_pet_owner is distinct from v_uid then
    raise exception 'pet is not owned by caller'
      using errcode = 'insufficient_privilege';
  end if;

  if p_enclosure_id is not null then
    select e.owner_id
      into v_enclosure_owner
      from public.enclosures e
     where e.id = p_enclosure_id
     for update;

    if not found then
      raise exception 'enclosure not found'
        using errcode = 'no_data_found';
    end if;

    if v_enclosure_owner is distinct from v_uid then
      raise exception 'enclosure is not owned by caller'
        using errcode = 'insufficient_privilege';
    end if;

    -- 이 migration 이전에는 배정이 0건이다. 이후 cross-owner 행이 발견되면
    -- 사용자 RPC가 남의 pet을 고치는 대신 운영 점검 대상으로 fail-closed한다.
    if exists (
      select 1
        from public.pets p
       where p.enclosure_id = p_enclosure_id
         and p.user_id <> v_uid
    ) then
      raise exception 'cross-owner enclosure assignment already exists'
        using errcode = 'integrity_constraint_violation';
    end if;

    update public.pets
       set enclosure_id = null,
           updated_at = pg_catalog.now()
     where enclosure_id = p_enclosure_id
       and user_id = v_uid
       and id <> p_pet_id;
  end if;

  update public.pets
     set enclosure_id = p_enclosure_id,
         updated_at = pg_catalog.now()
   where id = p_pet_id
     and user_id = v_uid;

  if not found then
    raise exception 'pet assignment target disappeared'
      using errcode = 'no_data_found';
  end if;
end;
$$;

revoke all on function public.assign_pet_to_enclosure(uuid, uuid)
  from public, anon, authenticated;
grant execute on function public.assign_pet_to_enclosure(uuid, uuid)
  to authenticated;

commit;
