begin;

-- terra ai News 공개 아티클. 기존 영상·라벨링 도메인과 FK 없이 독립 유지한다.
-- 최초 생성 migration이므로 이름 충돌은 조용히 수용하지 않고 전체 transaction을 실패시킨다.
create table public.news_articles (
  id            uuid primary key default gen_random_uuid(),
  slug          text not null unique
                check (
                  char_length(slug) between 1 and 120
                  and slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'
                ),
  title         text not null
                check (char_length(btrim(title)) between 1 and 200),
  summary       text
                check (summary is null or char_length(summary) <= 500),
  thumbnail_url text
                check (thumbnail_url is null or char_length(thumbnail_url) <= 2048),
  body_md       text not null
                check (char_length(body_md) > 0 and char_length(body_md) <= 1000000),
  status        text not null default 'draft'
                check (status in ('draft', 'published')),
  published_at  timestamptz,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  check (status <> 'published' or published_at is not null)
);

comment on table public.news_articles is
  'terra ai News 공개 아티클. 소유 레포: terra-ai-promotion-website.';

create index news_articles_published_idx
  on public.news_articles (published_at desc, id desc)
  where status = 'published';

create function public.fn_news_articles_touch()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
  new.updated_at := pg_catalog.now();
  return new;
end;
$$;

revoke all on function public.fn_news_articles_touch()
  from public, anon, authenticated;

create trigger news_articles_touch
  before update on public.news_articles
  for each row execute function public.fn_news_articles_touch();

alter table public.news_articles enable row level security;

revoke all on table public.news_articles
  from public, anon, authenticated;
grant select on table public.news_articles
  to anon, authenticated;
grant select, insert, update, delete on table public.news_articles
  to service_role;

create policy news_articles_public_read
  on public.news_articles
  for select
  to anon, authenticated
  using (
    status = 'published'
    and published_at is not null
    and published_at <= now()
  );

commit;
