#!/usr/bin/env python3
"""AI auto-tag: baca thumbnail, simpan CADANGAN tag dalam ai_suggestions.
Team terima / tolak cadangan dalam UI; tiada tag sebenar diubah di sini.

  export ANTHROPIC_API_KEY=...
  python autotag.py --config config.yaml [--limit 50] [--dry-run]
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
from datetime import datetime, timezone

import anthropic

from common import Supabase, load_config

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["description", "objects", "location", "setting", "people_count", "tags", "suggested_asset_type"],
    "properties": {
        "description": {"type": "string", "description": "Satu ayat ringkas dalam Bahasa Melayu"},
        "objects": {"type": "array", "items": {"type": "string"}, "description": "Objek utama, huruf kecil, BM"},
        "location": {"type": "string", "description": "Jenis lokasi (cth. pejabat, pantai, kampung, kilang) atau 'tidak pasti'"},
        "setting": {"type": "string", "enum": ["dalam", "luar", "studio", "tidak pasti"]},
        "people_count": {"type": "integer", "description": "Bilangan orang kelihatan; 0 jika tiada"},
        "tags": {"type": "array", "items": {"type": "string"}, "description": "3-8 tag carian ringkas BM"},
        "suggested_asset_type": {"type": "string", "enum": ["B-roll", "Testimoni", "Foto", "Lain-lain"]},
    },
}

PROMPT = """Ini thumbnail satu aset media ({kind}) dari pustaka media syarikat.
Fail: {path}
Beri cadangan tag untuk memudahkan team media mencari aset ini. Tulis dalam Bahasa Melayu.
Testimoni = seorang bercakap ke kamera/temu bual. B-roll = rakaman suasana/aktiviti tanpa temu bual.
Jangan teka nama orang atau jenama yang tidak jelas kelihatan."""


def suggest(client: anthropic.Anthropic, model: str, img: bytes, kind: str, path: str) -> dict:
    req = dict(
        model=model,
        max_tokens=2000,
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": base64.standard_b64encode(img).decode()}},
            {"type": "text", "text": PROMPT.format(kind=kind, path=path)},
        ]}],
    )
    if model.startswith(("claude-opus-5", "claude-sonnet-5-5", "claude-fable")):
        # Jika model menolak imej (refusal), API cuba semula dengan model fallback secara automatik
        resp = client.beta.messages.create(**req, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
    else:
        resp = client.messages.create(**req)
    if resp.stop_reason == "refusal":
        raise RuntimeError("model menolak imej ini")
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--dry-run", action="store_true", help="cetak cadangan, tidak simpan")
    args = ap.parse_args()

    cfg = load_config(args.config)
    at = cfg.get("autotag", {})
    model = at.get("model", "claude-haiku-5-5")
    limit = args.limit or at.get("batch_limit", 200)
    db = Supabase(cfg["supabase"]["url"], cfg["supabase"]["service_key"])
    client = anthropic.Anthropic()

    todo = []
    for row in db.fetch_all("id,nas_path,media_kind,thumb_key",
                            "&ai_tagged_at=is.null&thumb_key=not.is.null&missing=is.false"):
        todo.append(row)
        if len(todo) >= limit:
            break
    print(f"{len(todo)} aset untuk di-tag (model {model})")

    ok = fail = 0
    for row in todo:
        try:
            img = db.download_thumb(row["thumb_key"])
            s = suggest(client, model, img, row["media_kind"], row["nas_path"])
        except (anthropic.RateLimitError, anthropic.APIConnectionError) as e:
            print(f"  ! berhenti sementara ({type(e).__name__}); cuba lagi nanti")
            break
        except Exception as e:
            print(f"  ! {row['nas_path']}: {e}")
            fail += 1
            continue
        print(f"  {row['nas_path']}: {', '.join(s['tags'])} | {s['people_count']} orang")
        if not args.dry_run:
            db.patch(row["id"], {"ai_suggestions": s,
                                 "ai_tagged_at": datetime.now(timezone.utc).isoformat()})
        ok += 1
    print(f"Selesai: {ok} berjaya, {fail} gagal")
    return 0


if __name__ == "__main__":
    sys.exit(main())
