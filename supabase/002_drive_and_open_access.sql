-- Dijalankan selepas schema.sql (2026-11-24)

-- Sumber selain NAS (cth. Google Drive)
alter table public.assets add column if not exists source text not null default 'nas';
alter table public.assets add column if not exists web_url text;
alter table public.assets add column if not exists source_id text;
create index if not exists assets_source on public.assets (source);

-- Mod terbuka (tanpa log masuk), atas permintaan pemilik buat sementara.
-- Lajur yang boleh diubah tetap dihadkan oleh trigger touch_updated_at (tag & status sahaja).
-- Untuk kembali ke mod log masuk: buang 3 polisi ini dan set REQUIRE_LOGIN: true dalam frontend/config.js.
create policy "awam boleh baca" on public.assets for select to anon using (true);
create policy "awam boleh sunting tag" on public.assets for update to anon using (true) with check (true);
create policy "awam baca thumbnail" on storage.objects for select to anon using (bucket_id = 'thumbnails');
