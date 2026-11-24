"""Kod kongsi: config, klien Supabase (REST), teka tag dari laluan."""
from __future__ import annotations

import fnmatch
import hashlib
import os
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Iterable

import requests
import yaml

_ENV = re.compile(r"\$\{([A-Z0-9_]+)\}")


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    raw = _ENV.sub(lambda m: os.environ.get(m.group(1), ""), raw)
    return yaml.safe_load(raw)


@dataclass
class FileEntry:
    nas_path: str
    size: int | None
    mtime: float | None          # epoch seconds
    ctime: float | None = None
    extra: dict = field(default_factory=dict)  # width/height/duration jika diketahui

    @property
    def filename(self) -> str:
        return PurePosixPath(self.nas_path).name

    @property
    def ext(self) -> str:
        return PurePosixPath(self.nas_path).suffix.lower().lstrip(".")


def media_kind(ext: str, cfg: dict) -> str | None:
    exts = cfg.get("extensions", {})
    if ext in [e.lower() for e in exts.get("video", [])]:
        return "video"
    if ext in [e.lower() for e in exts.get("image", [])]:
        return "image"
    return None


def is_ignored(path: str, cfg: dict) -> bool:
    return any(fnmatch.fnmatch(path, pat) for pat in cfg.get("ignore", []))


def thumb_key(nas_path: str) -> str:
    h = hashlib.sha1(nas_path.encode("utf-8")).hexdigest()
    return f"{h[:2]}/{h}.jpg"


# ---------- Teka tag dari struktur folder ----------

def _compile(pattern: str) -> re.Pattern:
    parts = []
    for seg in pattern.strip("/").split("/"):
        m = re.fullmatch(r"\{(\w+|\*)\}", seg)
        if m and m.group(1) == "*":
            parts.append(r"[^/]+")
        elif m:
            parts.append(rf"(?P<{m.group(1)}>[^/]+)")
        else:
            parts.append(re.escape(seg))
    # pattern sepadan dengan awalan folder; selebihnya subfolder/fail
    return re.compile("^" + "/".join(parts) + r"(?:/|$)", re.IGNORECASE)


def infer_tags(nas_path: str, root: str, kind: str, cfg: dict) -> dict:
    rel_dir = str(PurePosixPath(nas_path).parent)
    root = root.rstrip("/")
    if rel_dir.lower().startswith(root.lower()):
        rel_dir = rel_dir[len(root):].strip("/")
    out: dict[str, Any] = {}
    for pat in cfg.get("path_patterns", []):
        m = _compile(pat).match(rel_dir + "/")
        if m:
            out = {k: v for k, v in m.groupdict().items() if v}
            break

    if "year" in out:
        y = re.search(r"(19|20)\d{2}", out["year"])
        out["year"] = int(y.group(0)) if y else None
    if out.get("year") is None:
        y = re.search(r"(?<!\d)(20\d{2})(?!\d)", nas_path)
        out["year"] = int(y.group(1)) if y else None

    def alias(val, table):
        if not val:
            return val
        return (cfg.get(table) or {}).get(val.strip().lower(), val.strip())

    out["asset_type"] = alias(out.get("asset_type"), "asset_type_aliases")
    if out.get("asset_type") and out["asset_type"].lower() not in {
        v.lower() for v in (cfg.get("asset_type_aliases") or {}).values()
    }:
        # folder di tahap 'jenis' bukan jenis yang dikenali -> jangan teka
        out["asset_type"] = None
    if not out.get("asset_type"):
        out["asset_type"] = (cfg.get("default_asset_type") or {}).get(kind)
    out["country"] = alias(out.get("country"), "country_aliases")
    return {k: out.get(k) for k in ("year", "country", "campaign", "partner", "asset_type")}


# ---------- Supabase REST ----------

class Supabase:
    def __init__(self, url: str, service_key: str):
        if not url or not service_key:
            raise SystemExit("supabase.url dan supabase.service_key wajib diisi")
        self.url = url.rstrip("/")
        self.s = requests.Session()
        self.s.headers.update({
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
        })

    def _rest(self, method: str, path: str, **kw) -> requests.Response:
        r = self.s.request(method, f"{self.url}/rest/v1/{path}", timeout=60, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"Supabase {method} {path}: {r.status_code} {r.text[:500]}")
        return r

    def fetch_all(self, select: str, filters: str = "", page: int = 1000) -> Iterable[dict]:
        start = 0
        while True:
            r = self._rest("GET", f"assets?select={select}{filters}&order=id",
                           headers={"Range-Unit": "items", "Range": f"{start}-{start + page - 1}"})
            rows = r.json()
            yield from rows
            if len(rows) < page:
                return
            start += page

    def insert(self, rows: list[dict]) -> None:
        for i in range(0, len(rows), 200):
            self._rest("POST", "assets?on_conflict=nas_path",
                       json=rows[i:i + 200],
                       headers={"Prefer": "resolution=ignore-duplicates,return=minimal"})

    def patch(self, asset_id: str, fields: dict) -> None:
        self._rest("PATCH", f"assets?id=eq.{asset_id}", json=fields,
                   headers={"Prefer": "return=minimal"})

    def upload_thumb(self, key: str, data: bytes) -> None:
        r = self.s.post(f"{self.url}/storage/v1/object/thumbnails/{key}", data=data,
                        headers={"Content-Type": "image/jpeg", "x-upsert": "true"}, timeout=60)
        if r.status_code >= 400:
            raise RuntimeError(f"Upload thumbnail gagal: {r.status_code} {r.text[:300]}")

    def download_thumb(self, key: str) -> bytes:
        r = self.s.get(f"{self.url}/storage/v1/object/thumbnails/{key}", timeout=60)
        r.raise_for_status()
        return r.content
