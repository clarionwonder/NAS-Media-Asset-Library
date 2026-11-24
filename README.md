# NAS Media Asset Library — MVP

**Aplikasi:** https://clarionwonder.github.io/NAS-Media-Asset-Library/ (GitHub Pages, auto-deploy dari folder `frontend/` setiap push ke `main`)

**Status semasa (24 Nov 2026):**
- Supabase projek *Media Library* (Singapore). Skema: `supabase/schema.sql` + `supabase/002_drive_and_open_access.sql`.
- Sumber pertama: Google Drive, folder *GER Test Photo* (9 gambar). NAS menyusul.
- Mod terbuka: tiada log masuk (`REQUIRE_LOGIN: false`). Sesiapa ada URL boleh cari & sunting tag/status guna; lajur lain dikunci oleh trigger.
- Thumbnail Drive dipapar terus dari Google Drive, jadi pengguna perlu akses ke folder Drive tersebut.

Katalog boleh cari untuk footage dan gambar dalam Synology NAS, dengan tag dan status kebenaran guna.
Fail asal **kekal di NAS**. Yang disimpan di Supabase hanya metadata + thumbnail kecil (~50 KB setiap satu).

## Seni bina

```
 Synology NAS ──(File Station API / folder tempatan)──> indexer.py  (PC pejabat atau NAS, ikut jadual)
                                                          │  metadata + tag teka dari folder
                                                          ▼
                                               Supabase  (Postgres: jadual assets,
                                                          Storage: bucket thumbnails peribadi)
                                                          ▲                 ▲
                                    autotag.py ───────────┘                 │ log masuk emel (magic link)
        (Claude baca thumbnail, simpan CADANGAN tag)                        │
                                                                   frontend/index.html
                                                   cari · tapis · sunting tag/status · salin link
                                                                            │
                                                          klik link ──> DSM File Station (QuickConnect/VPN)
```

| Bahagian | Fail | Peranan |
|---|---|---|
| Skema | `supabase/schema.sql` | Jadual `assets`, enum status guna, carian trigram, view penapis, RLS, bucket thumbnail |
| Indexer | `indexer/indexer.py` | Imbas NAS, tambah fail baharu, kemas kini yang berubah, tanda yang hilang. **Tidak menimpa tag yang disunting team** |
| Sumber | `indexer/sources.py` | `filestation` (DSM Web API, jalan dari mana-mana PC) atau `local` (di NAS / SMB mount, guna ffmpeg untuk thumbnail video) |
| AI tag | `indexer/autotag.py` | Hantar thumbnail ke Claude, simpan objek / lokasi / bilangan orang / tag sebagai cadangan |
| Frontend | `frontend/index.html` + `config.js` | Satu fail statik; boleh hos di Web Station NAS, Cloudflare Pages atau GitHub Pages |

### Tag dari struktur folder
Indexer meneka `tahun / negara / kempen / jenis` dari laluan, ikut `path_patterns` dalam config.
Contoh `/Media/2025/MY/Raya/broll/clip01.mp4` → tahun 2025, Malaysia, kempen Raya, B-roll.
Team boleh betulkan dalam UI; suntingan kekal walaupun indexer berjalan semula.

### Status guna
`Belum semak` (lalai) · `Bebas guna` · `Iklan perlu izin partner` · `Dalaman sahaja`, dengan medan nota (cth. tarikh tamat izin).

## Persediaan

1. **Supabase**: jalankan `supabase/schema.sql` dalam SQL Editor. Di Authentication, tambah emel team (Invite user) dan matikan sign-up awam.
2. **Akaun NAS**: cipta pengguna DSM khas `indexer`, kebenaran *baca sahaja* pada shared folder media, tanpa 2FA.
   Untuk thumbnail video melalui File Station, hidupkan *Indexing Service* / thumbnail di DSM. Jika tidak, guna mod `local` (ffmpeg).
3. **Indexer**:
   ```bash
   cd indexer
   pip install -r requirements.txt
   cp config.example.yaml config.yaml    # isi url, folder, pola folder
   export SUPABASE_SERVICE_KEY=...  NAS_PASSWORD=...
   python indexer.py --dry-run --limit 50   # semak tekaan tag dulu
   python indexer.py                        # larian sebenar
   ```
   Jadualkan setiap jam (Windows Task Scheduler / cron / DSM Task Scheduler).
4. **AI auto-tag** (pilihan): `export ANTHROPIC_API_KEY=...` kemudian `python autotag.py --limit 20 --dry-run`, kemudian tanpa `--dry-run`.
   Model lalai `claude-opus-5-5`; untuk ribuan fail, `claude-haiku-5-5` dalam config jauh lebih murah.
5. **Frontend**: isi `frontend/config.js` (URL Supabase, anon key, alamat QuickConnect), hos dua fail itu.

## Auto-index & AI auto-tag automatik (GitHub Actions)

Workflow `.github/workflows/index.yml` berjalan **setiap jam** (dan boleh dijalankan manual di tab Actions):
1. `indexer.py --config config.actions.yaml` — imbas folder Google Drive, simpan metadata + thumbnail ke Supabase.
2. `autotag.py` — hantar thumbnail baharu ke Claude (lalai `claude-haiku-5-5`, ~USD 2 / 10k gambar) dan simpan
   cadangan tag (objek, lokasi, bilangan orang, jenis). Cadangan terus boleh dicari dalam aplikasi.

**Sediakan sekali (GitHub > Settings > Secrets and variables > Actions > New repository secret):**

| Secret | Dari mana |
|---|---|
| `SUPABASE_SERVICE_KEY` | Supabase > Project Settings > API Keys > `service_role` (atau secret key) |
| `ANTHROPIC_API_KEY` | console.anthropic.com > API Keys |
| `GDRIVE_SA_JSON` | Isi penuh fail JSON service account Google (lihat bawah) |

**Service account Google Drive:**
1. console.cloud.google.com → cipta projek → *APIs & Services > Library* → hidupkan **Google Drive API**.
2. *IAM & Admin > Service Accounts* → Create → (tiada peranan diperlukan) → *Keys > Add key > JSON* → muat turun.
3. Di Google Drive, **kongsi folder media kepada emel service account** (`...@...iam.gserviceaccount.com`) sebagai *Viewer*.
4. Tambah folder lain dalam `indexer/config.actions.yaml` di bawah `gdrive.folders`.

## Keselamatan
- `service_role` key hanya dalam indexer (PC/NAS), tidak pernah dalam frontend.
- Frontend guna anon key + RLS: hanya pengguna log masuk boleh baca, dan hanya lajur tag/status boleh disunting.
- Thumbnail dalam bucket peribadi, dipapar melalui signed URL 1 jam.
- Link "Salin link NAS" membuka File Station; penerima tetap perlu log masuk DSM sendiri, jadi tiada fail terdedah awam.

## Belum diuji / perlu disahkan
- Diuji: skema (Postgres 16, dijalankan dua kali), RLS lajur, mod `local` dengan fail contoh (tag, abai `@eaDir`, thumbnail video/gambar).
- **Belum diuji dengan NAS sebenar**: mod `filestation` dan format link File Station (`launchApp=...openfile`) perlu disahkan pada versi DSM anda.
