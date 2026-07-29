begin;

-- terra ai News 댓글 + 관리자. 기존 news_articles migration은 수정하지 않는다.
-- 브라우저 역할에는 테이블 쓰기를 열지 않고 검증된 RPC만 공개한다.

create table public.news_admins (
  user_id    uuid primary key references auth.users(id) on delete cascade,
  note       text check (note is null or pg_catalog.char_length(note) <= 200),
  created_at timestamptz not null default pg_catalog.now()
);

comment on table public.news_admins is
  'terra ai News 관리자 멤버십. 추가와 제거는 service_role 운영 절차로만 한다.';

alter table public.news_admins enable row level security;
revoke all on table public.news_admins from public, anon, authenticated;
grant select, insert, update, delete on table public.news_admins to service_role;

create function public.fn_is_news_admin()
returns boolean
language sql
security definer
stable
set search_path = ''
as $$
  select exists (
    select 1
    from public.news_admins a
    where a.user_id = auth.uid()
  );
$$;

revoke all on function public.fn_is_news_admin() from public, anon;
grant execute on function public.fn_is_news_admin()
  to authenticated, service_role;

create policy news_articles_admin_read
  on public.news_articles
  for select
  to authenticated
  using (public.fn_is_news_admin());

create table public.news_comments (
  id          uuid primary key default pg_catalog.gen_random_uuid(),
  article_id  uuid not null
              references public.news_articles(id) on delete cascade,
  nickname    text not null
              check (pg_catalog.char_length(pg_catalog.btrim(nickname)) between 1 and 20),
  body        text not null
              check (pg_catalog.char_length(pg_catalog.btrim(body)) between 1 and 1000),
  is_hidden   boolean not null default false,
  fingerprint text not null
              check (fingerprint ~ '^[0-9a-f]{64}$'),
  created_at  timestamptz not null default pg_catalog.now()
);

comment on table public.news_comments is
  'terra ai News 익명 댓글. 본인 수정·삭제는 없고 관리자 숨김·삭제만 허용한다.';
comment on column public.news_comments.fingerprint is
  'IP와 User-Agent의 SHA-256 pseudonymous identifier. 원본 헤더는 저장하지 않는다.';

create index news_comments_article_idx
  on public.news_comments (article_id, created_at desc, id desc)
  where is_hidden = false;

create index news_comments_rate_idx
  on public.news_comments (fingerprint, created_at desc);

alter table public.news_comments enable row level security;
revoke all on table public.news_comments from public, anon, authenticated;
grant select on table public.news_comments to anon, authenticated;
grant select, insert, update, delete on table public.news_comments to service_role;

create function public.fn_news_article_is_public(p_article_id uuid)
returns boolean
language sql
security definer
stable
set search_path = ''
as $$
  select exists (
    select 1
    from public.news_articles a
    where a.id = p_article_id
      and a.status = 'published'
      and a.published_at is not null
      and a.published_at <= pg_catalog.now()
  );
$$;

revoke all on function public.fn_news_article_is_public(uuid) from public;
grant execute on function public.fn_news_article_is_public(uuid)
  to anon, authenticated, service_role;

create policy news_comments_public_read
  on public.news_comments
  for select
  to anon, authenticated
  using (
    is_hidden = false
    and public.fn_news_article_is_public(article_id)
  );

create policy news_comments_admin_read
  on public.news_comments
  for select
  to authenticated
  using (public.fn_is_news_admin());

create function public.fn_submit_news_comment(
  p_slug     text,
  p_nickname text,
  p_body     text
)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_article_id uuid;
  v_comment_id uuid;
  v_nickname   text;
  v_body       text;
  v_headers    jsonb := '{}'::jsonb;
  v_fp         text;
  v_recent_1m  integer;
  v_recent_1h  integer;
begin
  select a.id
  into v_article_id
  from public.news_articles a
  where a.slug = p_slug
    and a.status = 'published'
    and a.published_at is not null
    and a.published_at <= pg_catalog.now();

  if v_article_id is null then
    raise exception 'article not found or not published'
      using errcode = 'P0002';
  end if;

  v_nickname := pg_catalog.btrim(pg_catalog.coalesce(p_nickname, ''));
  if v_nickname = '' then
    v_nickname := '익명';
  end if;
  if pg_catalog.char_length(v_nickname) > 20 then
    raise exception 'nickname too long' using errcode = '22001';
  end if;

  v_body := pg_catalog.btrim(pg_catalog.coalesce(p_body, ''));
  if v_body = '' then
    raise exception 'body required' using errcode = '22004';
  end if;
  if pg_catalog.char_length(v_body) > 1000 then
    raise exception 'body too long' using errcode = '22001';
  end if;

  if pg_catalog.nullif(
    pg_catalog.current_setting('request.headers', true),
    ''
  ) is not null then
    v_headers := pg_catalog.current_setting('request.headers', true)::jsonb;
  end if;

  -- news-comment-v1은 비밀 salt가 아니라 해시 용도를 분리하는 domain separator다.
  v_fp := pg_catalog.encode(
    pg_catalog.sha256(
      pg_catalog.convert_to(
        pg_catalog.coalesce(v_headers ->> 'x-forwarded-for', '')
        || '|'
        || pg_catalog.coalesce(v_headers ->> 'user-agent', '')
        || '|news-comment-v1',
        'UTF8'
      )
    ),
    'hex'
  );

  -- 동일 fingerprint의 동시 요청이 둘 다 count=0을 보는 race를 막는다.
  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(v_fp, 0)
  );

  select pg_catalog.count(*)
  into v_recent_1m
  from public.news_comments c
  where c.fingerprint = v_fp
    and c.created_at > pg_catalog.now() - interval '1 minute';

  if v_recent_1m >= 1 then
    raise exception 'too many requests' using errcode = '53400';
  end if;

  select pg_catalog.count(*)
  into v_recent_1h
  from public.news_comments c
  where c.fingerprint = v_fp
    and c.created_at > pg_catalog.now() - interval '1 hour';

  if v_recent_1h >= 5 then
    raise exception 'too many requests' using errcode = '53400';
  end if;

  insert into public.news_comments (
    article_id,
    nickname,
    body,
    fingerprint
  )
  values (
    v_article_id,
    v_nickname,
    v_body,
    v_fp
  )
  returning id into v_comment_id;

  return v_comment_id;
end;
$$;

revoke all on function public.fn_submit_news_comment(text, text, text)
  from public;
grant execute on function public.fn_submit_news_comment(text, text, text)
  to anon, authenticated, service_role;

create function public.fn_admin_save_news_article(
  p_id            uuid,
  p_slug          text,
  p_title         text,
  p_summary       text,
  p_thumbnail_url text,
  p_body_md       text,
  p_status        text,
  p_published_at  timestamptz
)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_id uuid;
begin
  if public.fn_is_news_admin() is not true then
    raise exception 'forbidden' using errcode = '42501';
  end if;

  if p_id is null then
    insert into public.news_articles (
      slug,
      title,
      summary,
      thumbnail_url,
      body_md,
      status,
      published_at
    )
    values (
      p_slug,
      p_title,
      p_summary,
      p_thumbnail_url,
      p_body_md,
      p_status,
      p_published_at
    )
    returning id into v_id;
  else
    update public.news_articles
    set
      slug = p_slug,
      title = p_title,
      summary = p_summary,
      thumbnail_url = p_thumbnail_url,
      body_md = p_body_md,
      status = p_status,
      published_at = p_published_at
    where id = p_id
    returning id into v_id;

    if v_id is null then
      raise exception 'article not found' using errcode = 'P0002';
    end if;
  end if;

  return v_id;
end;
$$;

create function public.fn_admin_delete_news_article(p_id uuid)
returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
  if public.fn_is_news_admin() is not true then
    raise exception 'forbidden' using errcode = '42501';
  end if;

  delete from public.news_articles
  where id = p_id;
end;
$$;

create function public.fn_admin_set_comment_hidden(
  p_id uuid,
  p_hidden boolean
)
returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
  if public.fn_is_news_admin() is not true then
    raise exception 'forbidden' using errcode = '42501';
  end if;

  update public.news_comments
  set is_hidden = p_hidden
  where id = p_id;
end;
$$;

create function public.fn_admin_delete_comment(p_id uuid)
returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
  if public.fn_is_news_admin() is not true then
    raise exception 'forbidden' using errcode = '42501';
  end if;

  delete from public.news_comments
  where id = p_id;
end;
$$;

revoke all on function public.fn_admin_save_news_article(
  uuid,
  text,
  text,
  text,
  text,
  text,
  text,
  timestamptz
) from public, anon;
revoke all on function public.fn_admin_delete_news_article(uuid)
  from public, anon;
revoke all on function public.fn_admin_set_comment_hidden(uuid, boolean)
  from public, anon;
revoke all on function public.fn_admin_delete_comment(uuid)
  from public, anon;

grant execute on function public.fn_admin_save_news_article(
  uuid,
  text,
  text,
  text,
  text,
  text,
  text,
  timestamptz
) to authenticated, service_role;
grant execute on function public.fn_admin_delete_news_article(uuid)
  to authenticated, service_role;
grant execute on function public.fn_admin_set_comment_hidden(uuid, boolean)
  to authenticated, service_role;
grant execute on function public.fn_admin_delete_comment(uuid)
  to authenticated, service_role;

-- Public bucket은 object 조회만 공개한다. 쓰기는 뉴스 관리자 JWT만 가능하다.
insert into storage.buckets (id, name, public)
values ('news-media', 'news-media', true);

create policy news_media_public_read
  on storage.objects
  for select
  to anon, authenticated
  using (bucket_id = 'news-media');

create policy news_media_admin_write
  on storage.objects
  for insert
  to authenticated
  with check (
    bucket_id = 'news-media'
    and public.fn_is_news_admin()
  );

create policy news_media_admin_modify
  on storage.objects
  for update
  to authenticated
  using (
    bucket_id = 'news-media'
    and public.fn_is_news_admin()
  )
  with check (
    bucket_id = 'news-media'
    and public.fn_is_news_admin()
  );

create policy news_media_admin_delete
  on storage.objects
  for delete
  to authenticated
  using (
    bucket_id = 'news-media'
    and public.fn_is_news_admin()
  );

commit;
