#!/usr/bin/env python3
"""Index folder NAS ke Supabase.

  python indexer.py --config config.yaml            # larian biasa (incremental)
  python indexer.py --config config.yaml --dry-run  # tunjuk apa yang akan dibuat, tiada tulis
  python indexer.py --config config.yaml --otp 123456  # jika akaun ada 2FA

Selamat dijalankan berulang (cth. setiap jam via Task Scheduler / cron):
- fail baharu  -> dimasukkan bersama tag teka dari folder + thumbnail
- fail berubah -> maklumat fail & thumbnail dikemas kini (tag yang disunting team TIDAK ditimpa)
- fail hilang  -> ditanda missing=true (tidak dipadam)
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone

from common import FileEntry, Supabase, infer_tags, load_config, media_kind, thumb_key
from sources import FileStationSource, LocalSource


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat() if ts else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--otp", help="kod 2FA jika perlu")
    ap.add_argument("--no-thumbs", action="store_true", help="langkau thumbnail (lebih laju)")
    ap.add_argument("--limit", type=int, default=0, help="had fail baharu (untuk ujian)")
    args = ap.parse_args()

    cfg = load_config(args.config)
    kind = cfg.get("source", "filestation")
    src = FileStationSource(cfg["filestation"], cfg) if kind == "filestation" else LocalSource(cfg["local"], cfg)
    db = None if args.dry_run else Supabase(cfg["supabase"]["url"], cfg["supabase"]["service_key"])

    t0 = time.time()
    existing: dict[str, dict] = {}
    if db:
        for row in db.fetch_all("id,nas_path,size_bytes,file_mtime,missing,thumb_key"):
            existing[row["nas_path"]] = row
    print(f"Dalam DB: {len(existing)} aset")

    src.login(args.otp)
    seen: set[str] = set()
    new_rows: list[dict] = []
    n_new = n_changed = n_same = n_thumb_fail = 0
    try:
        for root in cfg.get("roots", []):
            print(f"Imbas {root} ...")
            for e in src.walk(root):
                seen.add(e.nas_path)
                mk = media_kind(e.ext, cfg)
                old = existing.get(e.nas_path)
                mtime_iso = iso(e.mtime)
                if old and old["size_bytes"] == e.size and _same_time(old["file_mtime"], e.mtime) and not old["missing"]:
                    n_same += 1
                    continue
                if args.limit and not old and n_new >= args.limit:
                    continue

                if isinstance(src, LocalSource):
                    e.extra = src.probe(e, mk)
                thumb = None if args.no_thumbs else src.thumbnail(e, mk)
                tkey = thumb_key(e.nas_path) if thumb else None
                if not thumb and not args.no_thumbs:
                    n_thumb_fail += 1

                file_fields = {
                    "filename": e.filename, "ext": e.ext, "media_kind": mk,
                    "size_bytes": e.size, "file_mtime": mtime_iso, "file_ctime": iso(e.ctime),
                    "width": e.extra.get("width"), "height": e.extra.get("height"),
                    "duration_sec": e.extra.get("duration_sec"),
                    "indexed_at": datetime.now(timezone.utc).isoformat(), "missing": False,
                }
                if tkey:
                    file_fields["thumb_key"] = tkey

                if args.dry_run:
                    tags = infer_tags(e.nas_path, root, mk, cfg)
                    print(f"  {'BARU' if not old else 'UBAH'} {e.nas_path}  tags={tags}  thumb={'ya' if thumb else 'tiada'}")
                    n_new += 0 if old else 1
                    n_changed += 1 if old else 0
                    continue

                if thumb:
                    db.upload_thumb(tkey, thumb)
                if old:
                    db.patch(old["id"], file_fields)
                    n_changed += 1
                else:
                    new_rows.append({"nas_path": e.nas_path, **file_fields,
                                     **infer_tags(e.nas_path, root, mk, cfg)})
                    n_new += 1
                    if len(new_rows) >= 200:
                        db.insert(new_rows)
                        new_rows.clear()
                        print(f"  ... {n_new} baharu setakat ini")
        if new_rows and db:
            db.insert(new_rows)

        n_missing = 0
        if db and not args.limit:
            for path, row in existing.items():
                if path not in seen and not row["missing"] and _under_roots(path, cfg):
                    db.patch(row["id"], {"missing": True})
                    n_missing += 1
    finally:
        src.logout()

    print(f"Selesai dalam {time.time() - t0:.0f}s: {n_new} baharu, {n_changed} dikemas kini, "
          f"{n_same} tiada ubah, {n_missing if db else 0} hilang, {n_thumb_fail} tiada thumbnail")
    return 0


def _same_time(db_iso: str | None, epoch: float | None) -> bool:
    if not db_iso or not epoch:
        return db_iso is None and epoch is None
    try:
        return abs(datetime.fromisoformat(db_iso).timestamp() - float(epoch)) < 2
    except ValueError:
        return False


def _under_roots(path: str, cfg: dict) -> bool:
    return any(path.startswith(r.rstrip("/") + "/") for r in cfg.get("roots", []))


if __name__ == "__main__":
    sys.exit(main())
