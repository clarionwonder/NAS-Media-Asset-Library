-- Media Asset Library: skema Supabase (Postgres)
-- Untuk projek BAHARU. Jalankan sekali dalam SQL Editor atau sebagai migration.

create extension if not exists pg_trgm;

-- Status kebenaran guna
do $$ begin
  create type usage_status as enum (
    'belum_semak',          -- default, belum ditetapkan
    'bebas_guna',           -- boleh guna untuk apa-apa termasuk iklan
    'perlu_izin_partner',   -- iklan perlu izin partner dulu
    'dalaman_sahaja'        -- guna dalaman sahaja
  );
exception when duplicate_object then null; end $$;

-- array_to_string bukan IMMUTABLE; bungkus supaya boleh guna dalam generated column
create or replace function public.tags_to_text(text[]) returns text
language sql immutable parallel safe set search_path = '' as $$ select coalesce(array_to_string($1, ' '), '') $$;

create table if not exists public.assets (
  id              uuid primary key default gen_random_uuid(),
  nas_path        text not null unique,        -- cth: /Media/2025/MY/Raya/broll/clip01.mp4
  filename        text not null,
  ext             text,
  media_kind      text check (media_kind in ('video','image','other')),
  size_bytes      bigint,
  file_mtime      timestamptz,
  file_ctime      timestamptz,
  width           int,
  height          int,
  duration_sec    numeric,
  thumb_key       text,                        -- path dalam bucket 'thumbnails'

  -- Tag utama (diisi dari struktur folder, boleh disunting dalam UI)
  campaign        text,
  country         text,
  partner         text,
  year            int,
  asset_type      text,                        -- B-roll, Testimoni, Foto, ...
  tags            text[] not null default '{}',-- tag bebas tambahan
  usage           usage_status not null default 'belum_semak',
  usage_note      text,                        -- cth: "Izin partner sah sehingga Dis 2026"

  -- Cadangan AI (belum diterima)
  ai_suggestions  jsonb,                       -- {objects:[], location:"", people_count:n, tags:[], description:""}
  ai_tagged_at    timestamptz,

  indexed_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  updated_by      text,
  missing         boolean not null default false, -- fail tiada lagi di NAS

  search_text     text generated always as (
    lower(
      coalesce(filename,'') || ' ' || coalesce(nas_path,'') || ' ' ||
      coalesce(campaign,'') || ' ' || coalesce(country,'') || ' ' ||
      coalesce(partner,'') || ' ' || coalesce(asset_type,'') || ' ' ||
      coalesce(usage_note,'') || ' ' ||
      public.tags_to_text(tags) || ' ' ||
      coalesce(ai_suggestions::text,'')
    )
  ) stored
);

create index if not exists assets_search_trgm on public.assets using gin (search_text gin_trgm_ops);
create index if not exists assets_tags_gin     on public.assets using gin (tags);
create index if not exists assets_campaign     on public.assets (campaign);
create index if not exists assets_country      on public.assets (country);
create index if not exists assets_partner      on public.assets (partner);
create index if not exists assets_year         on public.assets (year);
create index if not exists assets_type         on public.assets (asset_type);
create index if not exists assets_usage        on public.assets (usage);
create index if not exists assets_mtime        on public.assets (file_mtime desc);

-- Kemas kini updated_at, dan pastikan pengguna team hanya ubah lajur tag/status
-- (indexer guna service_role dan boleh ubah semua lajur)
create or replace function public.touch_updated_at() returns trigger
language plpgsql set search_path = '' as $$
declare
  editable text[] := array['campaign','country','partner','year','asset_type','tags',
                           'usage','usage_note','updated_by','updated_at','search_text'];
begin
  if current_user in ('authenticated', 'anon')
     and (to_jsonb(new) - editable) is distinct from (to_jsonb(old) - editable) then
    raise exception 'Hanya tag dan status guna boleh disunting' using errcode = '42501';
  end if;
  new.updated_at := now();
  return new;
end $$;

create trigger assets_touch before update on public.assets
for each row execute function public.touch_updated_at();

-- Senarai nilai unik untuk dropdown penapis
create or replace view public.asset_facets with (security_invoker = true) as
select 'campaign' as facet, campaign as value, count(*) as n from public.assets where not missing and campaign is not null group by campaign
union all select 'country', country, count(*) from public.assets where not missing and country is not null group by country
union all select 'partner', partner, count(*) from public.assets where not missing and partner is not null group by partner
union all select 'year', year::text, count(*) from public.assets where not missing and year is not null group by year
union all select 'asset_type', asset_type, count(*) from public.assets where not missing and asset_type is not null group by asset_type;

-- ---------- Keselamatan (RLS) ----------
-- Hanya pengguna log masuk (team media/digital) boleh baca & sunting tag.
-- Indexer guna service_role key (bypass RLS) dan tidak pernah didedahkan ke frontend.
alter table public.assets enable row level security;

create policy "team boleh baca" on public.assets
  for select to authenticated using (true);

create policy "team boleh sunting tag" on public.assets
  for update to authenticated using (true) with check (true);

-- anon tiada polisi RLS, jadi tidak nampak apa-apa baris.

-- ---------- Storage untuk thumbnail ----------
insert into storage.buckets (id, name, public)
values ('thumbnails', 'thumbnails', false)
on conflict (id) do nothing;

create policy "team baca thumbnail" on storage.objects
  for select to authenticated using (bucket_id = 'thumbnails');
