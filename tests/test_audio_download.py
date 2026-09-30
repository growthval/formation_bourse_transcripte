"""Téléchargement audio réel (yt-dlp + PyAV) sur un petit serveur HLS local."""

import shutil
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from fake_podia import make_hls
from podia_formation.media import classify_url, decoded_seconds, download_audio, parse_iso8601_duration
from podia_formation.models import MediaSource


def ffmpeg_exe():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    return pytest.importorskip("imageio_ffmpeg").get_ffmpeg_exe()


class Handler(SimpleHTTPRequestHandler):
    broken: set = set()
    seen_referers: list = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        Handler.seen_referers.append(self.headers.get("Referer"))
        if Path(self.path).name in Handler.broken:
            self.send_error(403)
            return
        super().do_GET()


@pytest.fixture()
def server(tmp_path):
    hls = tmp_path / "hls"
    make_hls(hls, ffmpeg_exe(), seconds=8)
    Handler.broken, Handler.seen_referers = set(), []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(hls)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def source(base, duration=8.0):
    return MediaSource(kind="hls", url=f"{base}/video.m3u8", key="hls:x",
                       headers={"Referer": "https://site.example/"}, duration_s=duration)


def test_download_audio_with_special_characters_in_title(server, tmp_path):
    dest = tmp_path / "audio" / "M03-L04 - Frais 1%(annuel) [ETF] - l'essentiel..."
    path, subs = download_audio(source(server), dest, log=lambda m: None)
    assert path.name == dest.name + ".m4a"
    assert 7.5 < decoded_seconds(path) < 8.5
    assert not [p for p in path.parent.iterdir() if p != path]        # aucun fichier temporaire laissé
    assert "https://site.example/" in Handler.seen_referers             # en-têtes rejoués


def test_missing_segment_fails_instead_of_leaving_a_gap(server, tmp_path, monkeypatch):
    from podia_formation import media

    monkeypatch.setattr(media, "RETRIES", 1)
    monkeypatch.setattr(media, "RETRY_SLEEP_MAX", 0.0)
    Handler.broken = {"seg_002.ts"}
    with pytest.raises(RuntimeError, match="échec du téléchargement audio"):
        download_audio(source(server), tmp_path / "audio" / "lecon", log=lambda m: None)


def test_generic_extractor_is_tried_first_for_captured_manifests(monkeypatch, tmp_path):
    import yt_dlp

    calls = []

    def fake_extract(self, url, download=True, ie_key=None, **kw):
        calls.append(ie_key)
        raise yt_dlp.utils.DownloadError("refusé")

    monkeypatch.setattr(yt_dlp.YoutubeDL, "extract_info", fake_extract)
    src = MediaSource(kind="cloudflare", url="https://customer-x.cloudflarestream.com/" + "a" * 32
                      + "/manifest/video.m3u8", key="cf:a", headers={})
    with pytest.raises(RuntimeError):
        download_audio(src, tmp_path / "x", log=lambda m: None)
    assert calls == ["Generic", None]


def test_url_classification_details():
    assert classify_url("https://fast.wistia.net/embed/medias/abcde12345.m3u8") == ("wistia", "wistia:abcde12345")
    assert classify_url("https://tracker.example/t?u=video.m3u8") is None       # extension dans la requête seulement
    assert parse_iso8601_duration("P0Y0M0DT0H4M10.000S") == 250
