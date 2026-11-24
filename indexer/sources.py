"""Sumber fail: Synology File Station API, atau folder tempatan (di NAS / SMB mount)."""
from __future__ import annotations

import io
import json
import os
import subprocess
from pathlib import Path, PurePosixPath
from typing import Iterator

import requests

from common import FileEntry, is_ignored, media_kind

THUMB_MAX = 640  # px sisi terpanjang


def _to_jpeg(data: bytes) -> bytes | None:
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data))
        im.thumbnail((THUMB_MAX, THUMB_MAX))
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        out = io.BytesIO()
        im.save(out, "JPEG", quality=80)
        return out.getvalue()
    except Exception:
        return None


# ---------------- File Station API ----------------

class FileStationSource:
    """Guna DSM Web API (DSM 7.x). Berfungsi melalui LAN, VPN atau QuickConnect."""

    def __init__(self, cfg: dict, full_cfg: dict):
        self.base = cfg["base_url"].rstrip("/")
        self.cfg = cfg
        self.full = full_cfg
        self.s = requests.Session()
        self.s.verify = cfg.get("verify_ssl", True)
        self.sid = None

    def _api(self, params: dict, stream=False) -> requests.Response:
        if self.sid:
            params = {**params, "_sid": self.sid}
        r = self.s.get(f"{self.base}/webapi/entry.cgi", params=params, timeout=120, stream=stream)
        r.raise_for_status()
        return r

    def login(self, otp: str | None = None) -> None:
        p = {"api": "SYNO.API.Auth", "version": "6", "method": "login",
             "account": self.cfg["username"], "passwd": self.cfg["password"],
             "session": "FileStation", "format": "sid"}
        if otp:
            p["otp_code"] = otp
        j = self._api(p).json()
        if not j.get("success"):
            code = j.get("error", {}).get("code")
            hint = {400: "akaun/kata laluan salah", 403: "akaun perlukan 2FA (OTP)",
                    407: "IP disekat"}.get(code, "")
            raise SystemExit(f"Login NAS gagal (kod {code}) {hint}")
        self.sid = j["data"]["sid"]

    def logout(self) -> None:
        if self.sid:
            try:
                self._api({"api": "SYNO.API.Auth", "version": "6", "method": "logout",
                           "session": "FileStation"})
            except Exception:
                pass

    def walk(self, root: str) -> Iterator[FileEntry]:
        stack = [root]
        while stack:
            folder = stack.pop()
            offset = 0
            while True:
                j = self._api({
                    "api": "SYNO.FileStation.List", "version": "2", "method": "list",
                    "folder_path": folder, "offset": offset, "limit": 1000,
                    "additional": json.dumps(["size", "time", "type"]),
                }).json()
                if not j.get("success"):
                    print(f"  ! tak boleh senarai {folder}: {j.get('error')}")
                    break
                files = j["data"].get("files", [])
                for f in files:
                    path = f["path"]
                    if is_ignored(path, self.full):
                        continue
                    if f.get("isdir"):
                        stack.append(path)
                        continue
                    if not media_kind(PurePosixPath(path).suffix.lower().lstrip("."), self.full):
                        continue
                    add = f.get("additional", {})
                    t = add.get("time", {})
                    yield FileEntry(path, add.get("size"), t.get("mtime"), t.get("crtime"))
                offset += len(files)
                if not files or offset >= j["data"].get("total", 0):
                    break

    def thumbnail(self, entry: FileEntry, kind: str) -> bytes | None:
        try:
            r = self._api({"api": "SYNO.FileStation.Thumb", "version": "2", "method": "get",
                           "path": entry.nas_path, "size": self.cfg.get("thumb_size", "medium")})
        except requests.RequestException:
            return None
        if not r.headers.get("Content-Type", "").startswith("image"):
            return None  # NAS belum jana thumbnail (biasa untuk video jika indexing media dimatikan)
        return _to_jpeg(r.content)


# ---------------- Folder tempatan ----------------

class LocalSource:
    """Indexer berjalan di NAS (Task Scheduler / Container Manager) atau PC dengan SMB mount."""

    def __init__(self, cfg: dict, full_cfg: dict):
        self.mounts = cfg.get("mounts", [])
        self.full = full_cfg

    def login(self, otp=None):
        pass

    def logout(self):
        pass

    def _to_local(self, nas_path: str) -> Path | None:
        for m in self.mounts:
            nas = m["nas"].rstrip("/")
            if nas_path == nas or nas_path.startswith(nas + "/"):
                return Path(m["local"]) / nas_path[len(nas):].lstrip("/")
        return None

    def _to_nas(self, local: Path) -> str:
        for m in self.mounts:
            base = Path(m["local"])
            try:
                rel = local.relative_to(base)
            except ValueError:
                continue
            nas = m["nas"].rstrip("/")
            return nas if rel == Path(".") else nas + "/" + rel.as_posix()
        raise ValueError(local)

    def walk(self, root: str) -> Iterator[FileEntry]:
        base = self._to_local(root)
        if not base or not base.exists():
            print(f"  ! folder {root} tiada pemetaan/akses tempatan")
            return
        for dirpath, dirnames, filenames in os.walk(base):
            nas_dir = self._to_nas(Path(dirpath))
            dirnames[:] = [d for d in dirnames if not is_ignored(f"{nas_dir}/{d}/x", self.full)]
            for fn in filenames:
                nas_path = f"{nas_dir}/{fn}"
                if is_ignored(nas_path, self.full):
                    continue
                if not media_kind(PurePosixPath(fn).suffix.lower().lstrip("."), self.full):
                    continue
                st = os.stat(os.path.join(dirpath, fn))
                yield FileEntry(nas_path, st.st_size, st.st_mtime, getattr(st, "st_birthtime", None))

    def probe(self, entry: FileEntry, kind: str) -> dict:
        p = self._to_local(entry.nas_path)
        if kind == "video":
            try:
                out = subprocess.run(
                    ["ffprobe", "-v", "error", "-select_streams", "v:0",
                     "-show_entries", "stream=width,height:format=duration", "-of", "json", str(p)],
                    capture_output=True, text=True, timeout=60).stdout
                j = json.loads(out or "{}")
                st = (j.get("streams") or [{}])[0]
                return {"width": st.get("width"), "height": st.get("height"),
                        "duration_sec": float(j.get("format", {}).get("duration") or 0) or None}
            except Exception:
                return {}
        try:
            from PIL import Image
            with Image.open(p) as im:
                return {"width": im.width, "height": im.height}
        except Exception:
            return {}

    def thumbnail(self, entry: FileEntry, kind: str) -> bytes | None:
        p = self._to_local(entry.nas_path)
        if kind == "image":
            try:
                return _to_jpeg(p.read_bytes())
            except Exception:
                return None
        # video: ambil satu frame pada ~10% durasi (min 1s)
        dur = entry.extra.get("duration_sec") or 10
        ts = max(1.0, float(dur) * 0.1)
        try:
            out = subprocess.run(
                ["ffmpeg", "-v", "error", "-ss", f"{ts:.2f}", "-i", str(p), "-frames:v", "1",
                 "-vf", f"scale='min({THUMB_MAX},iw)':-2", "-f", "image2", "-c:v", "mjpeg", "-"],
                capture_output=True, timeout=120).stdout
            return out or None
        except Exception:
            return None
