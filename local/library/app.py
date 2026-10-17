import base64
import hashlib
import hmac
import ipaddress
import json
import os
import mimetypes
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, Request, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse, StreamingResponse, Response
from mutagen import File as MutagenFile
from pydantic import BaseModel

ONLINE_ENRICH = os.environ.get("LIBRARY_ONLINE_ENRICH", "1") != "0"
ITUNES_SEARCH = "https://itunes.apple.com/search"

MUSIC_DIR = Path(os.environ.get("MUSIC_DIR", "/music")).resolve()
AUDIO_EXTS = {
    ".mp3", ".flac", ".m4a", ".m4b", ".mp4",
    ".ogg", ".oga", ".opus", ".wav", ".aac", ".aiff", ".aif",
}

app = FastAPI()

AUTH_USER = os.environ.get("SPINET_USERNAME", "").strip()
AUTH_HASH = os.environ.get("SPINET_PASSWORD_HASH", "").strip()
AUTH_PASS = "" if AUTH_HASH else os.environ.get("SPINET_PASSWORD", "")
AUTH_ON = bool(AUTH_USER and (AUTH_HASH or AUTH_PASS))
_LINK_KEY = hashlib.sha256(f"spinet-links|{AUTH_USER}|{AUTH_HASH or AUTH_PASS}".encode()).digest()
_accepted: set[str] = set()


def _password_ok(password: str) -> bool:
    if not AUTH_HASH:
        return hmac.compare_digest(password.encode(), AUTH_PASS.encode())
    try:
        scheme, iterations, salt, expected = AUTH_HASH.split(":")
        if scheme != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt), int(iterations))
        return hmac.compare_digest(digest, base64.b64decode(expected))
    except Exception:
        return False

_FAIL_LIMIT = 10
_FAIL_WINDOW = 600
_failures: dict[str, list[float]] = {}
_failures_lock = threading.Lock()

def _link_sig(track_id: str) -> str:
    return hmac.new(_LINK_KEY, track_id.encode(), hashlib.sha256).hexdigest()[:32]

def _signed(url: str, track_id: str) -> str:
    if not AUTH_ON:
        return url
    return f"{url}{'&' if '?' in url else '?'}sig={_link_sig(track_id)}"

def _client_ip(request: Request) -> str:
    peer = request.client.host if request.client else ""
    try:
        if peer and ipaddress.ip_address(peer).is_private:
            forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            if forwarded:
                return forwarded
    except ValueError:
        pass
    return peer

def _locked_out(ip: str) -> bool:
    now = time.time()
    with _failures_lock:
        recent = [t for t in _failures.get(ip, []) if now - t < _FAIL_WINDOW]
        _failures[ip] = recent
        return len(recent) >= _FAIL_LIMIT

def _note_failure(ip: str) -> None:
    with _failures_lock:
        _failures.setdefault(ip, []).append(time.time())

def _credentials_ok(request: Request) -> Optional[bool]:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("basic "):
        return None
    try:
        user, _, password = base64.b64decode(header[6:].strip()).decode("utf-8").partition(":")
    except Exception:
        return False
    seen = hashlib.sha256(header.encode()).hexdigest()
    if seen in _accepted:
        return True
    ok = hmac.compare_digest(user.encode(), AUTH_USER.encode()) and _password_ok(password)
    if ok:
        if len(_accepted) > 64:
            _accepted.clear()
        _accepted.add(seen)
    return ok

def _link_ok(request: Request) -> bool:
    sig = request.query_params.get("sig", "")
    parts = request.url.path.strip("/").split("/")
    if not sig or len(parts) != 2 or parts[0] not in ("file", "art"):
        return False
    track_id = parts[1].rsplit(".", 1)[0] if parts[0] == "file" else parts[1]
    return hmac.compare_digest(sig, _link_sig(track_id))

@app.middleware("http")
async def _require_sign_in(request: Request, call_next):
    if not AUTH_ON or request.url.path == "/health":
        return await call_next(request)
    if request.method in ("GET", "HEAD") and _link_ok(request):
        return await call_next(request)
    ip = _client_ip(request)
    if _locked_out(ip):
        return JSONResponse({"detail": "Too many wrong sign-ins. Try again in a few minutes."}, status_code=429)
    verdict = _credentials_ok(request)
    if verdict:
        with _failures_lock:
            _failures.pop(ip, None)
        return await call_next(request)
    if verdict is False:
        _note_failure(ip)
    return JSONResponse(
        {"detail": "This server needs a username and password."},
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="Spinet Server", charset="UTF-8"'},
    )

_MIME_BY_EXT = {
    ".mp3": "audio/mpeg",
    ".m4a": "audio/x-m4a",
    ".m4b": "audio/x-m4a",
    ".mp4": "video/mp4",
    ".aac": "audio/aac",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".opus": "audio/ogg",
    ".wav": "audio/wav",
    ".aiff": "audio/x-aiff",
    ".aif": "audio/x-aiff",
}

def _sniff_container(path: Path) -> Optional[str]:
    try:
        with open(path, "rb") as f:
            head = f.read(12)
        if len(head) >= 12 and head[4:8] == b"ftyp":
            return ".m4a"
        if head[:3] == b"ID3" or (
            len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0
        ):
            return ".mp3"
    except Exception:
        pass
    return None

def _mime_of(path: Path) -> str:
    sniffed = _sniff_container(path)
    if sniffed:
        return _MIME_BY_EXT[sniffed]
    return (
        _MIME_BY_EXT.get(path.suffix.lower())
        or mimetypes.guess_type(str(path))[0]
        or "application/octet-stream"
    )

_tracks: dict[str, Path] = {}

def _encode_id(rel_path: str) -> str:
    return base64.urlsafe_b64encode(rel_path.encode()).decode().rstrip("=")

def _decode_id(track_id: str) -> str:
    padding = "=" * (-len(track_id) % 4)
    return base64.urlsafe_b64decode(track_id + padding).decode()

UNKNOWN_ARTIST = "Unknown artist"

_NOISE = re.compile(r"[\(\[](official|lyric|audio|video|hd|4k|mv)[^\)\]]*[\)\]]", re.I)

def _parse_filename(stem: str) -> tuple[Optional[str], str]:
    cleaned = _NOISE.sub("", stem).strip(" -_")
    for sep in (" - ", " – ", " — "):
        if sep in cleaned:
            left, right = cleaned.split(sep, 1)
            left, right = left.strip(), right.strip()
            if left and right:
                return left, right
    return None, cleaned or stem

def _read_tags(path: Path) -> tuple[str, str, Optional[float]]:
    title, artist, duration = path.stem, UNKNOWN_ARTIST, None
    tag_title = tag_artist = None
    try:
        audio = MutagenFile(path, easy=True)
        if audio:
            if audio.tags:
                tag_title = (audio.tags.get("title") or [None])[0]
                tag_artist = (audio.tags.get("artist") or [None])[0]
            if audio.info and hasattr(audio.info, "length"):
                duration = audio.info.length
    except Exception:
        pass

    fn_artist, fn_title = _parse_filename(path.stem)
    title = tag_title or fn_title or title
    artist = tag_artist or fn_artist or UNKNOWN_ARTIST
    return title, artist, duration

ART_CACHE_DIR = MUSIC_DIR / ".spinet_art"

_ART_EXT_BY_MIME = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

def _art_cache_name(track_id: str, size: int = 0) -> str:
    digest = hashlib.sha1(track_id.encode()).hexdigest()
    return digest if size <= 0 else f"{digest}_{size}"

def _art_cache_read(track_id: str, size: int = 0) -> Optional[tuple[bytes, str]]:
    name = _art_cache_name(track_id, size)
    for mime, ext in _ART_EXT_BY_MIME.items():
        path = ART_CACHE_DIR / f"{name}{ext}"
        try:
            if path.exists():
                data = path.read_bytes()
                if data:
                    return data, mime
        except Exception:
            pass
    return None

def _art_cache_write(track_id: str, data: bytes, mime: str, size: int = 0) -> None:
    if not data:
        return
    try:
        ART_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        ext = _ART_EXT_BY_MIME.get(mime, ".jpg")
        (ART_CACHE_DIR / f"{_art_cache_name(track_id, size)}{ext}").write_bytes(data)
    except Exception:
        pass

def _downscale(data: bytes, size: int) -> Optional[tuple[bytes, str]]:
    if not _FFMPEG or size <= 0 or not data:
        return None
    try:
        proc = subprocess.run(
            [
                _FFMPEG, "-v", "error", "-i", "pipe:0",
                "-vf", f"scale={size}:{size}:force_original_aspect_ratio=decrease",
                "-f", "mjpeg", "-q:v", "5", "pipe:1",
            ],
            input=data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=15,
        )
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout, "image/jpeg"
    except Exception:
        pass
    return None

def _fetch_art(url: str) -> Optional[tuple[bytes, str]]:
    if not url:
        return None
    try:
        r = httpx.get(url, timeout=10.0, follow_redirects=True)
        if r.status_code == 200 and r.content:
            mime = r.headers.get("content-type", "image/jpeg").split(";")[0].strip()
            if not mime.startswith("image/"):
                mime = "image/jpeg"
            return r.content, mime
    except Exception:
        pass
    return None

def _container_of(path: Path) -> str:
    return _sniff_container(path) or path.suffix.lower()

def _embed_banner(path: Path, title: str, artist: str, art: Optional[tuple[bytes, str]]) -> None:
    ext = _container_of(path)
    try:
        if ext in _MP4_EXTS:
            from mutagen.mp4 import MP4, MP4Cover

            audio = MP4(path)
            if audio.tags is None:
                audio.add_tags()
            changed = False
            if title and not audio.tags.get("©nam"):
                audio.tags["©nam"] = [title]
                changed = True
            if artist and artist != UNKNOWN_ARTIST and not audio.tags.get("©ART"):
                audio.tags["©ART"] = [artist]
                changed = True
            if art and not audio.tags.get("covr"):
                data, mime = art
                fmt = MP4Cover.FORMAT_PNG if mime == "image/png" else MP4Cover.FORMAT_JPEG
                audio.tags["covr"] = [MP4Cover(data, imageformat=fmt)]
                changed = True
            if changed:
                audio.save()
        elif ext == ".mp3":
            from mutagen.id3 import ID3, APIC, TIT2, TPE1, ID3NoHeaderError

            try:
                tags = ID3(path)
            except ID3NoHeaderError:
                tags = ID3()
            changed = False
            if title and not tags.getall("TIT2"):
                tags.add(TIT2(encoding=3, text=[title]))
                changed = True
            if artist and artist != UNKNOWN_ARTIST and not tags.getall("TPE1"):
                tags.add(TPE1(encoding=3, text=[artist]))
                changed = True
            if art and not tags.getall("APIC"):
                data, mime = art
                tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=data))
                changed = True
            if changed:
                tags.save(path)
    except Exception:
        pass

def _embedded_art(path: Path) -> Optional[tuple[bytes, str]]:
    try:
        audio = MutagenFile(path)
        if audio is None:
            return None
        tags = getattr(audio, "tags", None)
        if tags is not None and hasattr(tags, "getall"):
            for apic in tags.getall("APIC"):
                return apic.data, apic.mime or "image/jpeg"
        if tags is not None and "covr" in getattr(tags, "keys", lambda: [])():
            covr = tags["covr"][0]
            fmt = "image/png" if bytes(covr)[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
            return bytes(covr), fmt
        pics = getattr(audio, "pictures", None)
        if pics:
            return pics[0].data, pics[0].mime or "image/jpeg"
    except Exception:
        pass
    return None

_online_cache: dict[str, Optional[dict]] = {}

_COVER_MARKERS = (
    "originallyperformedby", "karaoke", "madefamousby", "inthestyleof",
    "tributeto", "tributeversion", "coverversion", "instrumentalversion",
    "backingtrack",
)

_artist_id_cache: dict[str, Optional[int]] = {}

def _artist_catalog(artist: str) -> list[dict]:
    name = re.split(r",|&|;", artist)[0].strip()
    if not name:
        return []
    try:
        if name not in _artist_id_cache:
            r = httpx.get(
                ITUNES_SEARCH,
                params={"term": name, "entity": "musicArtist", "limit": 1},
                timeout=6.0,
            )
            hits = (r.json().get("results") or []) if r.status_code == 200 else []
            _artist_id_cache[name] = hits[0].get("artistId") if hits else None
        artist_id = _artist_id_cache[name]
        if not artist_id:
            return []
        r = httpx.get(
            "https://itunes.apple.com/lookup",
            params={"id": artist_id, "entity": "song", "limit": 200},
            timeout=8.0,
        )
        if r.status_code != 200:
            return []
        return [x for x in (r.json().get("results") or [])
                if x.get("wrapperType") == "track"]
    except Exception:
        return []

def _itunes_lookup(artist: str, title: str) -> Optional[dict]:
    if not ONLINE_ENRICH:
        return None
    term = f"{artist} {title}".strip() if artist != UNKNOWN_ARTIST else title
    key = term.lower()
    if key in _online_cache:
        return _online_cache[key]
    result = None
    try:
        r = httpx.get(
            ITUNES_SEARCH,
            params={"term": term, "entity": "song", "limit": 5},
            timeout=6.0,
        )
        if r.status_code == 200:
            items = r.json().get("results") or []

            def norm(s):
                return "".join(ch for ch in (s or "").lower() if ch.isalnum())

            want_title = norm(title)
            want_artist = "" if artist == UNKNOWN_ARTIST else norm(
                re.split(r",|&|;", artist)[0]
            )
            def title_ok(t):
                return t and (t == want_title or want_title in t or t in want_title)

            def is_cover(t):
                return any(m in t for m in _COVER_MARKERS)

            def exact_artist(hit):
                if not want_artist:
                    return True
                a = norm(hit.get("artistName"))
                return bool(a) and (want_artist in a or a in want_artist)

            it = next(
                (
                    hit for hit in items
                    if title_ok(t := norm(hit.get("trackName")))
                    and not is_cover(t)
                    and exact_artist(hit)
                ),
                None,
            )
            if it is None and want_artist:
                it = next(
                    (
                        hit for hit in items
                        if title_ok(t := norm(hit.get("trackName")))
                        and not is_cover(t)
                        and want_artist in t
                    ),
                    None,
                )
            if it is None and artist != UNKNOWN_ARTIST:
                it = next(
                    (
                        hit for hit in _artist_catalog(artist)
                        if title_ok(t := norm(hit.get("trackName")))
                        and not is_cover(t)
                    ),
                    None,
                )
            if it:
                art = it.get("artworkUrl100")
                if art:
                    art = art.replace("100x100bb", "600x600bb")
                result = {"artist": it.get("artistName"), "artwork": art}
    except Exception:
        result = None
    _online_cache[key] = result
    return result

def _rescan() -> int:
    _tracks.clear()
    if not MUSIC_DIR.exists():
        return 0
    for path in MUSIC_DIR.rglob("*"):
        if path.is_file() and path.suffix.lower() in AUDIO_EXTS:
            rel = str(path.relative_to(MUSIC_DIR))
            _tracks[_encode_id(rel)] = path
    return len(_tracks)

_FFMPEG = shutil.which("ffmpeg")
_MP4_EXTS = {".m4a", ".mp4", ".m4b"}

def _is_faststart(path: Path) -> bool:
    try:
        saw_moov = False
        with open(path, "rb") as f:
            while True:
                header = f.read(8)
                if len(header) < 8:
                    return False
                size = int.from_bytes(header[:4], "big")
                kind = header[4:8]
                if kind == b"moov":
                    saw_moov = True
                elif kind in (b"sidx", b"moof"):
                    return False
                elif kind == b"mdat":
                    return saw_moov
                if size == 1:
                    size = int.from_bytes(f.read(8), "big")
                    f.seek(size - 16, 1)
                elif size == 0:
                    return saw_moov
                else:
                    f.seek(size - 8, 1)
    except Exception:
        return True

def _ensure_faststart(path: Path) -> None:
    if _FFMPEG is None:
        return
    is_mp4 = path.suffix.lower() in _MP4_EXTS or _sniff_container(path) == ".m4a"
    if not is_mp4 or _is_faststart(path):
        return
    tmp = path.with_name(path.stem + ".faststart" + path.suffix)
    try:
        proc = subprocess.run(
            [_FFMPEG, "-y", "-loglevel", "error", "-i", str(path),
             "-map", "0", "-map_metadata", "0",
             "-c", "copy", "-movflags", "+faststart", "-f", "mp4", str(tmp)],
            capture_output=True, timeout=300,
        )
        if proc.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
            _carry_over_mp4_tags(path, tmp)
            tmp.replace(path)
        else:
            tmp.unlink(missing_ok=True)
    except Exception:
        tmp.unlink(missing_ok=True)

def _carry_over_mp4_tags(old: Path, new: Path) -> None:
    try:
        from mutagen.mp4 import MP4

        src = MP4(old)
        if not src.tags:
            return
        dst = MP4(new)
        if dst.tags is None:
            dst.add_tags()
        changed = False
        for key in ("\xa9nam", "\xa9ART", "covr"):
            if src.tags.get(key) and not dst.tags.get(key):
                dst.tags[key] = src.tags[key]
                changed = True
        if changed:
            dst.save()
    except Exception:
        pass

def _enrich_file(path: Path) -> None:
    ext = _container_of(path)
    if ext == ".mp3":
        title, artist, _ = _read_tags(path)
        hit = _itunes_lookup(artist, title)
        art = _fetch_art(hit.get("artwork") if hit else "")
        _embed_banner(path, title, artist, art)
        return
    if ext not in _MP4_EXTS:
        return
    try:
        from mutagen.mp4 import MP4, MP4Cover

        title, artist, _ = _read_tags(path)
        audio = MP4(path)
        if audio.tags is None:
            audio.add_tags()
        changed = False
        if not audio.tags.get("\xa9nam") and title:
            audio.tags["\xa9nam"] = [title]
            changed = True
        if not audio.tags.get("\xa9ART") and artist and artist != UNKNOWN_ARTIST:
            audio.tags["\xa9ART"] = [artist]
            changed = True
        if not audio.tags.get("covr"):
            hit = _itunes_lookup(artist, title)
            art_url = hit.get("artwork") if hit else None
            if art_url:
                r = httpx.get(art_url, timeout=10.0, follow_redirects=True)
                if r.status_code == 200 and r.content:
                    fmt = (
                        MP4Cover.FORMAT_PNG
                        if r.content[:8] == b"\x89PNG\r\n\x1a\n"
                        else MP4Cover.FORMAT_JPEG
                    )
                    audio.tags["covr"] = [MP4Cover(r.content, imageformat=fmt)]
                    changed = True
        if changed:
            audio.save()
    except Exception:
        pass

def _repair_hybrid_id3_mp4(path: Path) -> None:
    try:
        with open(path, "rb") as f:
            head = f.read(10)
            if head[:3] != b"ID3" or len(head) < 10:
                return
            size = ((head[6] & 0x7F) << 21) | ((head[7] & 0x7F) << 14) | ((head[8] & 0x7F) << 7) | (head[9] & 0x7F)
            tag_end = 10 + size + (10 if (head[5] & 0x10) else 0)
            f.seek(tag_end)
            probe = f.read(12)
            if probe[4:8] != b"ftyp":
                return
            f.seek(tag_end)
            rest = f.read()
        tmp = path.with_name(path.stem + ".strip" + path.suffix)
        tmp.write_bytes(rest)
        tmp.replace(path)
    except Exception:
        pass

def _faststart_sweep() -> None:
    for p in list(_tracks.values()):
        _repair_hybrid_id3_mp4(p)
        _ensure_faststart(p)
    for p in list(_tracks.values()):
        _enrich_file(p)

@app.on_event("startup")
def startup():
    _rescan()
    threading.Thread(target=_faststart_sweep, daemon=True).start()

@app.post("/rescan")
def rescan():
    return {"tracks": _rescan()}

IMPORTED_DIR = MUSIC_DIR / "Imported"

_SAFE_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

TRANSFER_LOG = MUSIC_DIR / ".spinet_transfers.jsonl"

_transfer_lock = threading.Lock()

def _log_transfer(event: str, path: Path, **extra) -> None:
    try:
        parts = path.relative_to(MUSIC_DIR).parts
    except ValueError:
        parts = (path.name,)
    entry = {
        "at": int(time.time() * 1000),
        "event": event,
        "file": "/".join(parts),
        "folder": parts[0] if len(parts) > 1 else "",
        **extra,
    }
    try:
        with _transfer_lock:
            with open(TRANSFER_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass

@app.get("/transfers")
def transfers(limit: int = 200, folder: str = ""):
    if not TRANSFER_LOG.exists():
        return {"transfers": []}
    items = []
    try:
        with open(TRANSFER_LOG, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                if folder and entry.get("folder") != folder:
                    continue
                items.append(entry)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not read log: {exc}")
    items.reverse()
    if limit > 0:
        items = items[:limit]
    return {"transfers": items}

def _safe_filename(name: str) -> str:
    return _SAFE_NAME.sub("_", name).strip(" .") or "track"

def _target_dir(folder: str) -> Path:
    folder = _SAFE_NAME.sub("_", (folder or "").strip()).strip(" .")
    dest = (MUSIC_DIR / folder) if folder else IMPORTED_DIR
    dest.mkdir(parents=True, exist_ok=True)
    return dest

@app.post("/upload")
async def upload_track(
    file: UploadFile = File(...),
    folder: str = Form(""),
    title: str = Form(""),
    artist: str = Form(""),
    art_url: str = Form(""),
):
    filename = _safe_filename(file.filename or "upload")
    if not any(filename.lower().endswith(ext) for ext in AUDIO_EXTS):
        filename += ".mp3"

    target = _target_dir(folder)
    dest = target / filename
    if dest.exists():
        stem, ext = dest.stem, dest.suffix
        n = 1
        while (target / f"{stem} ({n}){ext}").exists():
            n += 1
        dest = target / f"{stem} ({n}){ext}"

    received = 0
    try:
        with open(dest, "wb") as f:
            while chunk := await file.read(1024 * 1024):
                f.write(chunk)
                received += len(chunk)
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Save failed: {e}")

    _repair_hybrid_id3_mp4(dest)

    actual = _sniff_container(dest)
    if actual and dest.suffix.lower() != actual and not (
        actual == ".m4a" and dest.suffix.lower() in {".mp4", ".m4b"}
    ):
        renamed = dest.with_suffix(actual)
        n = 1
        while renamed.exists():
            renamed = dest.with_name(f"{dest.stem} ({n})").with_suffix(actual)
            n += 1
        dest.rename(renamed)
        dest = renamed

    _ensure_faststart(dest)
    supplied_art = _fetch_art(art_url)
    if title or artist or supplied_art:
        _embed_banner(dest, title, artist or UNKNOWN_ARTIST, supplied_art)
    _enrich_file(dest)
    _rescan()
    rel = str(dest.relative_to(MUSIC_DIR))
    resolved = _embedded_art(dest) or supplied_art
    if resolved:
        _art_cache_write(_encode_id(rel), *resolved)
    size = dest.stat().st_size
    title, artist, _ = _read_tags(dest)
    _log_transfer("upload", dest, size=size, title=title, artist=artist)
    return {
        "saved": str(dest.relative_to(MUSIC_DIR)),
        "received": received,
        "size": size,
        "tracks": len(_tracks),
    }

def _track_item(track_id: str, path: Path, base_url: str) -> dict:
    title, artist, duration = _read_tags(path)
    if artist == UNKNOWN_ARTIST:
        hit = _itunes_lookup(artist, title)
        if hit and hit.get("artist"):
            artist = hit["artist"]
    return {
        "url": f"/watch?v={track_id}",
        "title": title,
        "uploaderName": artist,
        "thumbnail": _signed(f"{base_url}/art/{track_id}?v={int(path.stat().st_mtime)}", track_id),
        "duration": int(duration) if duration else None,
        "size": path.stat().st_size,
        "modified": int(path.stat().st_mtime),
        "type": "stream",
    }

def _scheme(request: Request) -> str:
    peer = request.client.host if request.client else ""
    try:
        if peer and ipaddress.ip_address(peer).is_private:
            forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
            if forwarded in ("http", "https"):
                return forwarded
    except ValueError:
        pass
    return request.url.scheme

def _base_url(request: Request) -> str:
    host = request.headers.get("host", request.url.hostname)
    return f"{_scheme(request)}://{host}"

def _playlist_id_of(path: Path) -> str:
    rel = path.relative_to(MUSIC_DIR)
    parts = rel.parts
    if len(parts) <= 1:
        return "__root__"
    return _encode_id(parts[0])

@app.get("/search")
def search(request: Request, q: str = "", filter: str = ""):
    query = q.lower().strip()
    base = _base_url(request)
    items = []
    for track_id, path in _tracks.items():
        title, artist, _ = _read_tags(path)
        if query and query not in title.lower() and query not in artist.lower():
            continue
        items.append(_track_item(track_id, path, base))
    limit = len(items) if not query else 50
    return {"items": items[:limit]}

@app.get("/playlists")
def playlists():
    counts: dict[str, int] = {}
    names: dict[str, str] = {}
    for path in _tracks.values():
        pid = _playlist_id_of(path)
        counts[pid] = counts.get(pid, 0) + 1
        if pid == "__root__":
            names[pid] = "Singles"
        else:
            names[pid] = path.relative_to(MUSIC_DIR).parts[0]

    result = []
    if _tracks:
        result.append({"id": "__all__", "name": "All tracks", "trackCount": len(_tracks)})
    folders = sorted(
        (pid for pid in counts if pid != "__root__"),
        key=lambda p: names[p].lower(),
    )
    for pid in folders:
        result.append({"id": pid, "name": names[pid], "trackCount": counts[pid]})
    if "__root__" in counts:
        result.append({"id": "__root__", "name": "Singles", "trackCount": counts["__root__"]})

    return {"playlists": result}

@app.get("/playlists/{playlist_id}")
def playlist_tracks(playlist_id: str, request: Request):
    base = _base_url(request)
    items = []
    for track_id, path in _tracks.items():
        if playlist_id == "__all__" or _playlist_id_of(path) == playlist_id:
            items.append(_track_item(track_id, path, base))
    return {"items": items}

@app.get("/art/{track_id}")
def art(track_id: str, size: int = 0):
    path = _tracks.get(track_id)
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="Track not found")

    def served(data: bytes, mime: str) -> Response:
        return Response(content=data, media_type=mime, headers={
            "Cache-Control": "public, max-age=86400",
        })

    size = max(0, min(size, 1024))
    if size:
        small = _art_cache_read(track_id, size)
        if small:
            return served(*small)

    def deliver(full: tuple[bytes, str]) -> Response:
        if not size:
            return served(*full)
        shrunk = _downscale(full[0], size)
        if shrunk is None:
            return served(*full)
        _art_cache_write(track_id, shrunk[0], shrunk[1], size)
        return served(*shrunk)

    cached = _art_cache_read(track_id)
    if cached:
        return deliver(cached)

    embedded = _embedded_art(path)
    if embedded:
        _art_cache_write(track_id, *embedded)
        return deliver(embedded)

    title, artist, _ = _read_tags(path)
    hit = _itunes_lookup(artist, title)
    fetched = _fetch_art(hit.get("artwork") if hit else "")
    if fetched:
        _art_cache_write(track_id, *fetched)
        return deliver(fetched)
    raise HTTPException(status_code=404, detail="No artwork")

@app.get("/streams/{track_id}")
def streams(track_id: str, request: Request):
    path = _tracks.get(track_id)
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="Track not found")
    mime = _mime_of(path)
    host = request.headers.get("host", request.url.hostname)
    scheme = _scheme(request)
    ext = path.suffix.lstrip(".").lower() or "mp3"
    return {
        "audioStreams": [{
            "url": _signed(f"{scheme}://{host}/file/{track_id}.{ext}", track_id),
            "bitrate": 0,
            "mimeType": mime,
        }]
    }

class MoveRequest(BaseModel):
    track_id: str
    folder: str = ""

@app.post("/move")
def move_track(req: MoveRequest):
    path = _tracks.get(req.track_id)
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="Track not found")
    dest_dir = _target_dir(req.folder)
    dest = dest_dir / path.name
    if dest == path:
        return {"moved": str(path.relative_to(MUSIC_DIR)), "id": req.track_id}
    if dest.exists():
        stem, ext = dest.stem, dest.suffix
        n = 1
        while (dest_dir / f"{stem} ({n}){ext}").exists():
            n += 1
        dest = dest_dir / f"{stem} ({n}){ext}"
    path.rename(dest)
    _rescan()
    rel = str(dest.relative_to(MUSIC_DIR))
    return {"moved": rel, "id": _encode_id(rel)}

@app.get("/file/{track_id}")
def file(track_id: str, request: Request):
    if "." in track_id:
        track_id = track_id.rsplit(".", 1)[0]
    path = _tracks.get(track_id)
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="Track not found")

    file_size = path.stat().st_size
    mime = _mime_of(path)
    range_header = request.headers.get("range")

    if range_header is None:
        def full_stream():
            with open(path, "rb") as f:
                while chunk := f.read(1024 * 64):
                    yield chunk
        return StreamingResponse(full_stream(), media_type=mime, headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(file_size),
        })

    start_str, _, end_str = range_header.replace("bytes=", "").partition("-")
    start = int(start_str) if start_str else 0
    end = int(end_str) if end_str else file_size - 1
    end = min(end, file_size - 1)
    length = end - start + 1

    def ranged_stream():
        with open(path, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(1024 * 64, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    return StreamingResponse(
        ranged_stream(),
        status_code=206,
        media_type=mime,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Content-Length": str(length),
        },
    )

@app.delete("/file/{track_id}")
def delete_file(track_id: str):
    path = _tracks.get(track_id)
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="Track not found")
    title, artist, _ = _read_tags(path)
    try:
        path.unlink()
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Delete failed: {exc}")
    _log_transfer("delete", path, title=title, artist=artist)
    remaining = _rescan()
    return {"deleted": track_id, "tracks": remaining}

NOWPLAYING_FILE = MUSIC_DIR / ".spinet_nowplaying.json"

class NowPlaying(BaseModel):
    track: dict
    positionMs: int = 0
    durationMs: int = 0
    updatedAt: int = 0
    device: str = ""
    isPlaying: bool = False
    queue: list = []
    queueIndex: int = 0
    sourceQueue: list = []
    history: list = []
    shuffle: bool = False
    repeat: str = "OFF"

@app.get("/nowplaying")
def get_nowplaying(compact: bool = False, history: bool = False):
    if not NOWPLAYING_FILE.exists():
        return {}
    try:
        data = json.loads(NOWPLAYING_FILE.read_text("utf-8"))
    except Exception:
        return {}
    if compact:
        drop = ("queue", "sourceQueue", "history")
    elif not history:
        drop = ("history",)
    else:
        drop = ()
    return {k: v for k, v in data.items() if k not in drop} if drop else data

@app.put("/nowplaying")
def put_nowplaying(state: NowPlaying):
    data = state.dict()
    if not data.get("updatedAt"):
        data["updatedAt"] = int(time.time() * 1000)
    try:
        NOWPLAYING_FILE.write_text(json.dumps(data), encoding="utf-8")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Save failed: {exc}")
    return {"ok": True, "updatedAt": data["updatedAt"]}

PLAYLIST_SYNC_FILE = MUSIC_DIR / ".spinet_playlists.json"

class PlaylistSync(BaseModel):
    playlists: list = []
    favorites: list = []
    updatedAt: int = 0
    device: str = ""
    playStatsJson: str = ""
    themes: list = []
    sources: list = []
    selectedThemeId: str = ""
    settingsOrderCsv: str = ""

@app.get("/syncplaylists")
def get_playlist_sync():
    if PLAYLIST_SYNC_FILE.exists():
        try:
            return json.loads(PLAYLIST_SYNC_FILE.read_text("utf-8"))
        except Exception:
            pass
    return {}

@app.put("/syncplaylists")
def put_playlist_sync(state: PlaylistSync):
    data = state.dict()
    if not data.get("updatedAt"):
        data["updatedAt"] = int(time.time() * 1000)
    try:
        PLAYLIST_SYNC_FILE.write_text(json.dumps(data), encoding="utf-8")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Save failed: {exc}")
    return {"ok": True, "updatedAt": data["updatedAt"]}

@app.get("/health")
def health():
    if AUTH_ON:
        return {"status": "ok", "auth": True}
    return {"status": "ok", "auth": False, "tracks": len(_tracks)}
