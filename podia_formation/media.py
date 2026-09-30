"""Reconnaissance des lecteurs vidéo, durée des flux et téléchargement de l'audio."""

from __future__ import annotations

import base64
import glob
import html as html_lib
import json
import re
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, quote, urljoin, urlparse

from .models import MediaSource

# Manifestes HLS/DASH (Cloudflare Stream, lecteurs génériques).
MANIFEST_RE = re.compile(r"(?:/manifest/video\.(?:m3u8|mpd)|\.m3u8|\.mpd)(?:[?#]|$)", re.I)
CLOUDFLARE_RE = re.compile(
    r"https?://(?:customer-[a-z0-9]+\.cloudflarestream\.com|(?:iframe\.|watch\.)?videodelivery\.net"
    r"|(?:iframe\.|watch\.)?cloudflarestream\.com)"
    r"/(?P<id>[0-9a-f]{32}|eyJ[\w-]+\.[\w-]+\.[\w-]+)(?P<rest>/[^\s\"'<>]*)?",
    re.I,
)
EMBED_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("wistia", re.compile(r"(?:wistia_async_|fast\.wistia\.(?:net|com)/embed/(?:iframe|medias)/|data-wistia-?id=[\"']|media-id=[\"'])([a-z0-9]{10})\b")),
    ("vimeo", re.compile(r"https?://player\.vimeo\.com/video/\d+(?:\?h=[0-9a-f]+)?")),
    ("youtube", re.compile(r"https?://(?:www\.)?youtube(?:-nocookie)?\.com/embed/[\w-]{11}")),
    ("loom", re.compile(r"https?://(?:www\.)?loom\.com/(?:embed|share)/[0-9a-f]{32}")),
]
FILE_RE = re.compile(r"\.(?:mp4|m4a|mp3|m4v|webm|ogg|wav)(?:[?#]|$)", re.I)

# En-têtes à rejouer tels que le navigateur les a envoyés.
REPLAY_HEADERS = ("referer", "origin", "user-agent", "accept-language")


def jwt_claims(token: str) -> dict:
    try:
        payload = token.split(".")[1]
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def jwt_subject(token: str) -> str | None:
    return str(jwt_claims(token).get("sub") or "") or None


def token_in(url: str) -> str | None:
    m = re.search(r"eyJ[\w-]+\.[\w-]+\.[\w-]+", url or "")
    return m.group(0) if m else None


def classify_url(url: str) -> tuple[str, str] | None:
    """(type, clé de déduplication) d'une URL de média, ou None."""
    m = CLOUDFLARE_RE.match(url)
    if m:
        vid = m.group("id")
        if vid.startswith("eyJ"):
            vid = jwt_subject(vid) or vid
        return "cloudflare", f"cf:{vid}"
    if MANIFEST_RE.search(url):
        parsed = urlparse(url)
        kind = "dash" if ".mpd" in parsed.path.lower() else "hls"
        return kind, f"{kind}:{parsed.netloc}{parsed.path}"
    for kind, pattern in EMBED_PATTERNS:
        m = pattern.search(url)
        if m:
            ident = m.group(1) if m.groups() else m.group(0)
            return kind, f"{kind}:{ident}"
    if FILE_RE.search(urlparse(url).path):
        parsed = urlparse(url)
        return "fichier", f"fichier:{parsed.netloc}{parsed.path}"
    return None


def is_manifest(url: str) -> bool:
    return bool(MANIFEST_RE.search(url))


def cloudflare_manifest_from_iframe(url: str, site_origin: str = "", ext: str = "m3u8") -> str | None:
    """.../<jeton>/iframe?... -> .../<jeton>/manifest/video.m3u8?parentOrigin=<site>

    Le lecteur Cloudflare ne charge rien avant la lecture (preload=none) : on déduit
    donc l'adresse du flux de celle de l'iframe, comme le fait le lecteur lui-même.
    """
    m = CLOUDFLARE_RE.match(url)
    if not m:
        return None
    parsed = urlparse(url)
    parent = parse_qs(parsed.query).get("parentOrigin", [site_origin])[0]
    query = f"?parentOrigin={quote(parent, safe='')}" if parent else ""
    return f"{parsed.scheme}://{parsed.netloc}/{m.group('id')}/manifest/video.{ext}{query}"


_BARE_JWT_RE = re.compile(r"eyJ[\w-]{10,}\.eyJ[\w-]{10,}\.[\w-]{20,}")
_CF_HOST_RE = re.compile(r"customer-[a-z0-9]+\.cloudflarestream\.com", re.I)


def embed_urls_from_html(text: str) -> list[str]:
    """Adresses de lecteurs trouvées dans le HTML (attributs, JSON échappé, jetons isolés)."""
    text = html_lib.unescape(text.replace("\\/", "/").replace("\\u0026", "&").replace("\\u002F", "/"))
    found: list[str] = []
    for m in CLOUDFLARE_RE.finditer(text):
        found.append(m.group(0).split('"')[0].split("'")[0])
    for kind, pattern in EMBED_PATTERNS:
        for m in pattern.finditer(text):
            found.append(f"wistia:{m.group(1)}" if kind == "wistia" else m.group(0))
    # Jeton Cloudflare isolé (<stream src="eyJ...">, propriétés JSON) dont le « sub » est un identifiant vidéo.
    m = _CF_HOST_RE.search(text)
    host = m.group(0) if m else "cloudflarestream.com"
    for token in _BARE_JWT_RE.findall(text):
        sub = jwt_subject(token) or ""
        if re.fullmatch(r"[0-9a-f]{32}", sub) and token not in " ".join(found):
            found.append(f"https://{host}/{token}/iframe")
    return list(dict.fromkeys(found))


def replay_headers(all_headers: dict, url: str, page_url: str) -> dict:
    """En-têtes pour retélécharger un média hors du navigateur."""
    headers = {k.lower(): v for k, v in (all_headers or {}).items() if k.lower() in REPLAY_HEADERS}
    if "referer" not in headers or "origin" not in headers:
        parent = parse_qs(urlparse(url).query).get("parentOrigin", [""])[0]
        page = urlparse(page_url)
        origin = parent.rstrip("/") or f"{page.scheme}://{page.netloc}"
        headers.setdefault("referer", origin + "/")
        headers.setdefault("origin", origin)
    return {k.title(): v for k, v in headers.items()}


# --- Durée d'un flux -------------------------------------------------------

_ISO_RE = re.compile(
    r"P(?:(?P<d>[\d.]+)D)?(?:T(?:(?P<h>[\d.]+)H)?(?:(?P<m>[\d.]+)M)?(?:(?P<s>[\d.]+)S)?)?$"
)


def parse_iso8601_duration(value: str) -> float | None:
    m = _ISO_RE.match((value or "").strip())
    if not m or not any(m.groupdict().values()):
        return None
    d, h, mi, s = (float(m.group(k) or 0) for k in ("d", "h", "m", "s"))
    return d * 86400 + h * 3600 + mi * 60 + s


def mpd_duration(text: str) -> float | None:
    m = re.search(r'mediaPresentationDuration\s*=\s*"([^"]+)"', text or "")
    return parse_iso8601_duration(m.group(1)) if m else None


def m3u8_duration(text: str, base_url: str, fetch: Callable[[str], str]) -> float | None:
    """Somme des #EXTINF d'une playlist ; suit la première variante d'un master."""
    if "#EXTINF" in text:
        total = sum(float(x) for x in re.findall(r"#EXTINF:\s*([\d.]+)", text))
        return total or None
    uri = None
    m = re.search(r'#EXT-X-MEDIA:[^\n]*TYPE=AUDIO[^\n]*URI="([^"]+)"', text)
    if m:
        uri = m.group(1)
    else:
        lines = [l.strip() for l in text.splitlines()]
        for i, line in enumerate(lines):
            if line.startswith("#EXT-X-STREAM-INF"):
                uri = next((l for l in lines[i + 1:] if l and not l.startswith("#")), None)
                break
    if not uri:
        return None
    child_url = urljoin(base_url, uri)
    child = fetch(child_url)
    if "#EXTINF" not in child:
        return None
    return m3u8_duration(child, child_url, fetch)


def manifest_duration(url: str, fetch: Callable[[str], str]) -> float | None:
    text = fetch(url)
    if "<MPD" in text[:2000] or ".mpd" in urlparse(url).path.lower():
        return mpd_duration(text)
    if text.lstrip().startswith("#EXTM3U"):
        return m3u8_duration(text, url, fetch)
    return None


# --- Fichiers audio (PyAV, installé avec faster-whisper : pas besoin de ffmpeg) ---

def with_ext(stem: Path, ext: str) -> Path:
    """Ajoute une extension sans toucher aux points du titre (« sur... L'introduction »)."""
    return stem.with_name(stem.name + ext)


def audio_duration(path: Path) -> float | None:
    try:
        import av
        with av.open(str(path)) as container:
            if container.duration:
                return container.duration / 1_000_000
            stream = container.streams.audio[0]
            if stream.duration and stream.time_base:
                return float(stream.duration * stream.time_base)
    except Exception:
        return None
    return None


def to_m4a(src: Path, dest: Path) -> Path:
    """Extrait la piste audio dans un .m4a : copie directe si AAC, sinon réencodage AAC 128 kb/s."""
    import av

    tmp = dest.with_name(dest.name + ".tmp")
    with av.open(str(src)) as inp:
        if not inp.streams.audio:
            raise RuntimeError("aucune piste audio dans le fichier téléchargé")
        a = inp.streams.audio[0]
        with av.open(str(tmp), "w", format="mp4") as out:
            if a.codec_context.name == "aac":
                o = out.add_stream_from_template(a)
                for packet in inp.demux(a):
                    if packet.dts is None:
                        continue
                    packet.stream = o
                    out.mux(packet)
            else:
                o = out.add_stream("aac", rate=a.codec_context.sample_rate or 44100)
                o.bit_rate = 128_000
                for frame in inp.decode(a):
                    frame.pts = None
                    for packet in o.encode(frame):
                        out.mux(packet)
                for packet in o.encode(None):
                    out.mux(packet)
    tmp.replace(dest)
    return dest


# --- Téléchargement de l'audio (yt-dlp) --------------------------------------

class DrmProtected(Exception):
    pass


def _ytdlp_url(source: MediaSource) -> str:
    if source.kind == "wistia" and source.key.startswith("wistia:"):
        return source.key
    return source.url


def download_subtitles(url: str, opts: dict, dest_stem: Path) -> list[Path]:
    """Sous-titres éventuels du flux (ajoutés par le formateur ou générés par Cloudflare). Sans garantie."""
    from yt_dlp import YoutubeDL

    dest_stem.parent.mkdir(parents=True, exist_ok=True)
    sub_opts = {**opts, "skip_download": True, "writesubtitles": True, "subtitleslangs": ["all"],
                "ignoreerrors": True, "outtmpl": {"default": str(dest_stem) + ".%(ext)s"}}
    sub_opts.pop("postprocessors", None)
    try:
        with YoutubeDL(sub_opts) as ydl:
            info = ydl.extract_info(url, download=True) or {}
    except Exception:
        return []
    paths = []
    for sub in (info.get("requested_subtitles") or {}).values():
        path = Path(sub.get("filepath") or "")
        if path.is_file() and path.stat().st_size > 0:
            paths.append(path)
    return paths


def download_audio(source: MediaSource, dest_stem: Path, subs_stem: Path | None = None,
                   log: Callable[[str], None] = print) -> tuple[Path, list[Path]]:
    """Télécharge la piste audio d'une source : renvoie le .m4a et les éventuels sous-titres."""
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError

    dest_stem.parent.mkdir(parents=True, exist_ok=True)
    raw_stem = dest_stem.with_name(dest_stem.name + ".source")
    base_opts = {
        # Piste audio seule si le lecteur en propose une, sinon la plus petite vidéo (l'audio en est extrait).
        "format": "ba/b[height<=480]/wa*/w",
        "outtmpl": {"default": str(raw_stem) + ".%(ext)s"},
        "http_headers": dict(source.headers),
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "retries": 10,
        "fragment_retries": 10,
        "concurrent_fragment_downloads": 4,
        "overwrites": True,
    }
    url = _ytdlp_url(source)
    attempts = [{}]
    if source.kind in ("cloudflare", "hls", "dash"):
        # Rejouer l'URL exacte vue par le navigateur, puis l'extracteur dédié en secours.
        attempts = [{"force_generic_extractor": True}, {}]
    last_error: Exception | None = None
    for extra in attempts:
        try:
            with YoutubeDL({**base_opts, **extra}) as ydl:
                info = ydl.extract_info(url, download=True)
            if not info:
                raise DownloadError("aucune information renvoyée")
            raw = None
            for item in info.get("requested_downloads") or []:
                path = Path(item.get("filepath") or "")
                if path.is_file():
                    raw = path
            if raw is None:
                found = [c for c in dest_stem.parent.glob(glob.escape(raw_stem.name) + ".*")
                         if c.suffix not in (".part", ".ytdl", ".tmp")]
                raw = found[0] if found else None
            if raw is None:
                raise DownloadError("fichier audio introuvable après téléchargement")
            try:
                final = to_m4a(raw, with_ext(dest_stem, ".m4a"))
                raw.unlink(missing_ok=True)
            except ImportError:
                final = with_ext(dest_stem, raw.suffix)
                raw.replace(final)
            subs = download_subtitles(url, {**base_opts, **extra}, subs_stem) if subs_stem else []
            return final, subs
        except DownloadError as exc:
            if "DRM" in str(exc):
                raise DrmProtected(str(exc)) from exc
            last_error = exc
            log(f"    essai yt-dlp échoué ({'générique' if extra else 'extracteur dédié'}) : {exc}")
    raise RuntimeError(f"échec du téléchargement audio : {last_error}")


def list_formats(source: MediaSource) -> list[dict]:
    """Formats proposés par le flux (commande « sonde »)."""
    from yt_dlp import YoutubeDL

    opts = {"quiet": True, "no_warnings": True, "http_headers": dict(source.headers), "noplaylist": True}
    if source.kind in ("cloudflare", "hls", "dash"):
        opts["force_generic_extractor"] = True
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(_ytdlp_url(source), download=False, process=False) or {}
    return [{k: f.get(k) for k in ("format_id", "ext", "acodec", "vcodec", "abr", "height", "has_drm")}
            for f in info.get("formats") or []] + [
        {"format_id": f"sous-titres:{lang}", "ext": "vtt"} for lang in (info.get("subtitles") or {})]
