"""Reconnaissance des lecteurs vidéo, durée des flux et téléchargement de l'audio."""

from __future__ import annotations

import base64
import glob
import hashlib
import html as html_lib
import json
import re
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, quote, urljoin, urlparse

from .models import MediaSource

# Manifestes HLS/DASH (Cloudflare Stream, lecteurs génériques).
MANIFEST_RE = re.compile(r"(?:/manifest/video\.(?:m3u8|mpd)|\.m3u8|\.mpd)$", re.I)   # appliqué au chemin
WISTIA_MEDIA_RE = re.compile(r"fast\.wistia\.(?:net|com)/embed/medias/([a-z0-9]{10})\b")
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
    m = WISTIA_MEDIA_RE.search(url)
    if m:
        return "wistia", f"wistia:{m.group(1)}"
    parsed = urlparse(url)
    if MANIFEST_RE.search(parsed.path):
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
    return bool(MANIFEST_RE.search(urlparse(url).path))


def cloudflare_manifest_from_iframe(url: str, site_origin: str = "", ext: str = "m3u8") -> str | None:
    """.../<jeton>/iframe?... -> .../<jeton>/manifest/video.m3u8?parentOrigin=<site>

    Le lecteur Cloudflare ne charge rien avant la lecture (preload=none) : on déduit
    donc l'adresse du flux de celle de l'iframe, comme le fait le lecteur lui-même.
    """
    m = CLOUDFLARE_RE.match(url)
    if not m:
        return None
    parsed = urlparse(url)
    host = re.sub(r"^(?:iframe|watch)\.", "", parsed.netloc, flags=re.I)   # ces hôtes ne servent que le lecteur
    parent = parse_qs(parsed.query).get("parentOrigin", [site_origin])[0]
    query = f"?parentOrigin={quote(parent, safe='')}" if parent else ""
    return f"{parsed.scheme}://{host}/{m.group('id')}/manifest/video.{ext}{query}"


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
    r"P(?:(?P<y>[\d.]+)Y)?(?:(?P<mo>[\d.]+)M)?(?:(?P<w>[\d.]+)W)?(?:(?P<d>[\d.]+)D)?"
    r"(?:T(?:(?P<h>[\d.]+)H)?(?:(?P<m>[\d.]+)M)?(?:(?P<s>[\d.]+)S)?)?$"
)


def parse_iso8601_duration(value: str) -> float | None:
    m = _ISO_RE.match((value or "").strip())
    if not m or not any(m.groupdict().values()):
        return None
    y, mo, w, d, h, mi, s = (float(m.group(k) or 0) for k in ("y", "mo", "w", "d", "h", "m", "s"))
    return (y * 365.25 + mo * 30.44 + w * 7 + d) * 86400 + h * 3600 + mi * 60 + s


def mpd_duration(text: str) -> float | None:
    m = re.search(r"mediaPresentationDuration\s*=\s*[\"']([^\"']+)[\"']", text or "")
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


def _copy_aac(inp, a, out) -> None:
    o = out.add_stream_from_template(a)
    for packet in inp.demux(a):
        if packet.dts is None:
            continue
        packet.stream = o
        out.mux(packet)


def _transcode_aac(inp, a, out) -> None:
    o = out.add_stream("aac", rate=a.codec_context.sample_rate or 44100)
    o.bit_rate = 128_000
    for frame in inp.decode(a):
        frame.pts = None
        for packet in o.encode(frame):
            out.mux(packet)
    for packet in o.encode(None):
        out.mux(packet)


def to_m4a(src: Path, dest: Path) -> Path:
    """Extrait la piste audio dans un .m4a : copie directe si AAC, sinon (ou si la copie échoue) réencodage AAC."""
    import av

    tmp = dest.with_name(dest.name + ".tmp")
    modes = ["copie", "reencodage"]
    try:
        for mode in modes:
            try:
                with av.open(str(src)) as inp:
                    if not inp.streams.audio:
                        raise RuntimeError("aucune piste audio dans le fichier téléchargé")
                    a = inp.streams.audio[0]
                    if mode == "copie" and a.codec_context.name != "aac":
                        continue
                    with av.open(str(tmp), "w", format="mp4") as out:
                        (_copy_aac if mode == "copie" else _transcode_aac)(inp, a, out)
                break
            except (av.FFmpegError, ValueError):
                # Horodatages non monotones (discontinuités HLS), etc. : on réencode.
                tmp.unlink(missing_ok=True)
                if mode == modes[-1]:
                    raise
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)
    return dest


def decoded_seconds(path: Path) -> float | None:
    """Durée réellement décodable (les trous d'un flux incomplet n'y sont pas comptés)."""
    try:
        import av
        with av.open(str(path)) as c:
            a = c.streams.audio[0]
            rate = a.codec_context.sample_rate or 0
            samples = sum(frame.samples for frame in c.decode(a))
        return samples / rate if rate else None
    except Exception:
        return None


# --- Téléchargement de l'audio (yt-dlp) --------------------------------------

class DrmProtected(Exception):
    pass


def _ytdlp_url(source: MediaSource) -> str:
    if source.kind == "wistia" and source.key.startswith("wistia:"):
        return source.key
    return source.url


def _outtmpl(stem: Path) -> dict:
    # « % » est un caractère spécial des modèles de nom de yt-dlp (titre « Frais 1%(annuel) »…).
    return {"default": str(stem).replace("%", "%%") + ".%(ext)s"}


def download_subtitles(url: str, opts: dict, dest_stem: Path, ie_key: str | None) -> list[Path]:
    """Sous-titres éventuels du flux (ajoutés par le formateur ou générés par Cloudflare). Sans garantie."""
    from yt_dlp import YoutubeDL

    dest_stem.parent.mkdir(parents=True, exist_ok=True)
    sub_opts = {**opts, "skip_download": True, "writesubtitles": True, "subtitleslangs": ["all"],
                "ignoreerrors": True, "outtmpl": _outtmpl(dest_stem)}
    sub_opts.pop("postprocessors", None)
    try:
        with YoutubeDL(sub_opts) as ydl:
            info = ydl.extract_info(url, download=True, ie_key=ie_key) or {}
    except Exception:
        return []
    paths = []
    for sub in (info.get("requested_subtitles") or {}).values():
        path = Path(sub.get("filepath") or "")
        if path.is_file() and path.stat().st_size > 0:
            paths.append(path)
    return paths


RETRIES = 5
RETRY_SLEEP_MAX = 10.0


def _backoff(n: int) -> float:
    """Pause avant le n-ième nouvel essai : 1, 2, 4, 8, 10 s…"""
    return min(2.0 ** n, RETRY_SLEEP_MAX)


_LEFTOVER_RE = re.compile(r"\.(?:part|ytdl|tmp)(?:-Frag\d+)?$")


def download_audio(source: MediaSource, dest_stem: Path, subs_stem: Path | None = None,
                   log: Callable[[str], None] = print) -> tuple[Path, list[Path]]:
    """Télécharge la piste audio d'une source : renvoie le .m4a et les éventuels sous-titres."""
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError

    dest_stem.parent.mkdir(parents=True, exist_ok=True)
    # Nom temporaire court : les fragments yt-dlp (« ….part-Frag123 ») dépasseraient vite 260 caractères sous Windows.
    raw_stem = dest_stem.parent / f".dl-{hashlib.sha1(dest_stem.name.encode()).hexdigest()[:10]}"
    base_opts = {
        # Piste audio seule si le lecteur en propose une, sinon la plus petite vidéo (l'audio en est extrait).
        "format": "ba/b[height<=480]/wa*/w",
        "outtmpl": _outtmpl(raw_stem),
        "http_headers": dict(source.headers),
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "retries": RETRIES,
        "fragment_retries": RETRIES,
        # Un segment manquant ferait un trou dans la transcription : on échoue plutôt que de le sauter.
        "skip_unavailable_fragments": False,
        "retry_sleep_functions": {"http": _backoff, "fragment": _backoff},
        "concurrent_fragment_downloads": 4,
        "overwrites": True,
    }
    url = _ytdlp_url(source)
    # Pour un flux capté : d'abord l'URL exacte vue par le navigateur (extracteur générique),
    # puis l'extracteur Cloudflare de yt-dlp en secours.
    attempts: list[str | None] = ["Generic", None] if source.kind in ("cloudflare", "hls", "dash") else [None]
    last_error: Exception | None = None
    for ie_key in attempts:
        label = "générique" if ie_key else "extracteur dédié"
        try:
            with YoutubeDL(base_opts) as ydl:
                info = ydl.extract_info(url, download=True, ie_key=ie_key)
            if not info:
                raise DownloadError("aucune information renvoyée")
            raw = None
            for item in info.get("requested_downloads") or []:
                path = Path(item.get("filepath") or "")
                if path.is_file():
                    raw = path
            if raw is None:
                found = [c for c in dest_stem.parent.glob(glob.escape(raw_stem.name) + ".*")
                         if not _LEFTOVER_RE.search(c.name)]
                raw = found[0] if found else None
            if raw is None:
                raise DownloadError("fichier audio introuvable après téléchargement")
            try:
                final = to_m4a(raw, with_ext(dest_stem, ".m4a"))
                raw.unlink(missing_ok=True)
            except ImportError:
                final = with_ext(dest_stem, raw.suffix)
                raw.replace(final)
            expected = source.duration_s
            got = decoded_seconds(final)
            if expected and got and got < 0.97 * expected - 2:
                raise DownloadError(f"audio incomplet ({got:.0f} s sur {expected:.0f} s)")
            subs = download_subtitles(url, base_opts, subs_stem, ie_key) if subs_stem else []
            return final, subs
        except DownloadError as exc:
            if "DRM" in str(exc):
                raise DrmProtected(str(exc)) from exc
            last_error = exc
            log(f"    essai yt-dlp échoué ({label}) : {exc}")
        except (RuntimeError, OSError, ValueError, KeyError) as exc:
            last_error = exc
            log(f"    essai échoué ({label}) : {type(exc).__name__}: {exc}")
    raise RuntimeError(f"échec du téléchargement audio : {last_error}")


def list_formats(source: MediaSource) -> list[dict]:
    """Formats proposés par le flux (commande « sonde »)."""
    from yt_dlp import YoutubeDL

    opts = {"quiet": True, "no_warnings": True, "http_headers": dict(source.headers), "noplaylist": True}
    ie_key = "Generic" if source.kind in ("cloudflare", "hls", "dash") else None
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(_ytdlp_url(source), download=False, process=False, ie_key=ie_key) or {}
    return [{k: f.get(k) for k in ("format_id", "ext", "acodec", "vcodec", "abr", "height", "has_drm")}
            for f in info.get("formats") or []] + [
        {"format_id": f"sous-titres:{lang}", "ext": "vtt"} for lang in (info.get("subtitles") or {})]
