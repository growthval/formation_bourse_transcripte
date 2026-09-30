"""Faux site Podia pour les tests de bout en bout (aucun accès réseau externe).

- site (127.0.0.1) : connexion par cookie, barre latérale, leçons vidéo/article/quiz ;
- « CDN » (localhost, autre origine) : lecteur en iframe et flux HLS audio qui exige un Referer,
  comme Cloudflare Stream avec des jetons signés.
"""

from __future__ import annotations

import base64
import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

COURSE = "demo-bourse"
MODULES = [
    ("101", "module-1-introduction", "Module 1: Introduction"),
    ("102", "module-2-se-lancer", "Module 2: Se lancer"),
]
# (module, id, slug, titre, type, visible dans la barre latérale)
LESSONS = [
    ("101", "1001", "introduction", "Introduction", "video_auto", True),
    ("101", "1002", "les-10-commandements", "Les 10 commandements de l'investisseur", "article", True),
    ("102", "1003", "se-lancer", "Se lancer", "video_click", True),
    ("102", "1004", "je-teste-mes-connaissances", "Je teste mes connaissances sur... Se lancer", "quiz", True),
    ("102", "1005", "decryptage-bonus", "Décryptage : bonus caché", "article", False),
]
ARTICLE = " ".join(["La diversification réduit le risque d'un portefeuille d'actions."] * 60)


def jwt(sub: str) -> str:
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{enc({'alg': 'RS256'})}.{enc({'sub': sub, 'exp': 9999999999})}.c2lnbmF0dXJl"


def make_hls(dest: Path, ffmpeg: str, seconds: int = 6) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                    "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "aac", "-b:a", "64k",
                    "-f", "hls", "-hls_time", "2", "-hls_playlist_type", "vod",
                    "-hls_segment_filename", str(dest / "seg_%03d.ts"), str(dest / "stream_audio.m3u8")],
                   check=True)
    (dest / "video.m3u8").write_text(
        "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-STREAM-INF:BANDWIDTH=70000,CODECS=\"mp4a.40.2\"\nstream_audio.m3u8\n")


def minimal_pdf(pages: int = 2) -> bytes:
    objs = ["<< /Type /Catalog /Pages 2 0 R >>",
            f"<< /Type /Pages /Kids [{' '.join(f'{3 + i} 0 R' for i in range(pages))}] /Count {pages} >>"]
    objs += ["<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>" for _ in range(pages)]
    out = b"%PDF-1.4\n"
    for i, o in enumerate(objs, start=1):
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    return out + b"trailer << /Root 1 0 R >>\n%%EOF\n"


class FakePodia:
    def __init__(self, hls_dir: Path):
        self.hls_dir = hls_dir
        self.manifest_hits: list[dict] = []
        self.auto_login = True     # False : la page de connexion attend un humain (jamais dans les tests)
        self.site = ThreadingHTTPServer(("127.0.0.1", 0), self._site_handler())
        self.cdn = ThreadingHTTPServer(("127.0.0.1", 0), self._cdn_handler())
        self.site_url = f"http://127.0.0.1:{self.site.server_address[1]}"
        self.cdn_url = f"http://localhost:{self.cdn.server_address[1]}"

    def start(self) -> "FakePodia":
        for srv in (self.site, self.cdn):
            threading.Thread(target=srv.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        for srv in (self.site, self.cdn):
            srv.shutdown()
            srv.server_close()

    def lesson_url(self, lesson_id: str) -> str:
        for mod, lid, slug, *_ in LESSONS:
            if lid == lesson_id:
                mslug = next(s for m, s, _ in MODULES if m == mod)
                return f"{self.site_url}/p/courses/{COURSE}/{mod}-{mslug}/{lid}-{slug}"
        raise KeyError(lesson_id)

    # -- pages du site --
    def sidebar(self) -> str:
        parts = ['<aside class="course-sidebar"><div class="title">Investir en bourse</div>',
                 "<p>1 sur 5 terminés (20%)</p>"]
        for mod, mslug, mtitle in MODULES:
            parts.append(f'<section><button aria-expanded="true"><span>{mtitle}</span> ▾</button><ul>')
            for lmod, lid, slug, title, kind, visible in LESSONS:
                if lmod == mod and visible:
                    done = '<span class="status">Terminé</span>' if lid == "1001" else ""
                    parts.append(f'<li><a href="/p/courses/{COURSE}/{mod}-{mslug}/{lid}-{slug}">'
                                 f'<svg></svg>{title}{done}</a></li>')
            parts.append("</ul></section>")
        parts.append("</aside>")
        return "".join(parts)

    def lesson_page(self, lesson_id: str) -> str:
        idx = next(i for i, l in enumerate(LESSONS) if l[1] == lesson_id)
        _, lid, _, title, kind, _ = LESSONS[idx]
        body = ""
        if kind.startswith("video"):
            token = jwt(f"video{lid}")
            parent = quote(self.site_url, safe="")
            body = (f'<div class="player"><iframe src="{self.cdn_url}/{token}/iframe?mode={kind}'
                    f'&parentOrigin={parent}" allow="autoplay"></iframe></div>'
                    "<p>Dans ce module, vous allez découvrir pourquoi investir en actions est un excellent "
                    "moyen de faire croître son patrimoine.</p>")
        elif kind == "article":
            body = (f"<h2>Premier principe</h2><p>{ARTICLE}</p><ul><li>Investir tôt</li><li>Diversifier</li></ul>"
                    '<p><a href="/content-assets/fiche.pdf">Télécharger la fiche pratique</a></p>')
        elif kind == "quiz":
            body = "<form>" + "".join(
                f'<fieldset><legend>Question {q}</legend>'
                f'<label><input type="radio" name="q{q}" value="a"> Réponse A</label>'
                f'<label><input type="radio" name="q{q}" value="b"> Réponse B</label></fieldset>'
                for q in range(1, 5)) + "</form>"
        nav = ""
        if idx + 1 < len(LESSONS):
            nav += f'<a rel="next" href="{self.lesson_url(LESSONS[idx + 1][1])}">Continuer</a>'
        if idx:
            nav += f'<a rel="prev" href="{self.lesson_url(LESSONS[idx - 1][1])}">Précédent</a>'
        return (f"<!doctype html><html><head><meta charset='utf-8'><title>{title} | Investir en bourse</title>"
                f'<meta name="csrf-token" content="SECRET-CSRF"></head><body>{self.sidebar()}'
                f"<main><h1>{title}</h1><div class='lesson-content'>{body}</div>"
                f"<nav class='lesson-nav'>{nav}</nav><button>Marquer comme terminé</button></main></body></html>")

    def _site_handler(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def send(self, code, body=b"", ctype="text/html; charset=utf-8", headers=None):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                url = urlparse(self.path)
                logged = "sess=ok" in (self.headers.get("Cookie") or "")
                if url.path == "/login":
                    back = parse_qs(url.query).get("return_to", ["/"])[0]
                    script = ("<script>setTimeout(() => { document.cookie = 'sess=ok; path=/; max-age=86400';"
                              f" location.href = {json.dumps(back)}; }}, 700);</script>") if fake.auto_login else ""
                    html = f"<html><body><form><input type=email><input type=password></form>{script}</body></html>"
                    return self.send(200, html.encode())
                if url.path == "/content-assets/fiche.pdf":
                    if not logged:
                        return self.send(403, b"forbidden")
                    return self.send(200, minimal_pdf(2), "application/pdf")
                if url.path.startswith(f"/p/courses/{COURSE}"):
                    if not logged:
                        return self.send(302, headers={"Location": f"/login?return_to={quote(self.path)}"})
                    parts = url.path.rstrip("/").split("/")
                    if len(parts) == 4:      # page de la formation -> première leçon
                        return self.send(302, headers={"Location": fake.lesson_url("1001")})
                    lesson_id = parts[-1].split("-")[0]
                    return self.send(200, fake.lesson_page(lesson_id).encode())
                if url.path == "/":
                    return self.send(200, b"<html><body>Bibliotheque</body></html>")
                self.send(404, b"not found")

        return Handler

    # -- lecteur et flux --
    def _cdn_handler(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def send(self, code, body=b"", ctype="text/html; charset=utf-8"):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                url = urlparse(self.path)
                parts = url.path.strip("/").split("/")
                if len(parts) == 2 and parts[1] == "iframe":
                    mode = parse_qs(url.query).get("mode", [""])[0]
                    manifest = f"/{parts[0]}/manifest/video.m3u8?{url.query}"
                    load = ("fetch(M).then(r => r.text()).then(() => fetch(M.replace('video.m3u8', 'stream_audio.m3u8')));")
                    trigger = (load if mode == "video_auto" else
                               "HTMLMediaElement.prototype.play = function () { " + load + " return Promise.resolve(); };")
                    html = (f"<html><body><video id=v width=320 height=180></video><script>const M = {json.dumps(manifest)};"
                            f"{trigger}</script></body></html>")
                    return self.send(200, html.encode())
                if len(parts) == 3 and parts[1] == "manifest":
                    if parts[2].endswith(".m3u8"):
                        fake.manifest_hits.append({"path": url.path, "referer": self.headers.get("Referer"),
                                                   "origin": self.headers.get("Origin"),
                                                   "agent": self.headers.get("User-Agent")})
                    if not self.headers.get("Referer"):
                        return self.send(401, b"missing referer")
                    f = fake.hls_dir / parts[2]
                    if f.is_file():
                        ctype = "application/vnd.apple.mpegurl" if f.suffix == ".m3u8" else "video/mp2t"
                        return self.send(200, f.read_bytes(), ctype)
                self.send(404, b"not found")

        return Handler
