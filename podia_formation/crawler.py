"""Parcours de la formation dans un vrai navigateur (Playwright).

L'utilisateur se connecte une fois dans la fenêtre ouverte ; le profil du
navigateur est conservé, la session reste donc valable aux lancements suivants.
Pour chaque leçon, on lit le texte de la page et on intercepte les requêtes du
lecteur vidéo pour récupérer l'adresse du flux (liens signés valables ~1 h).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urlparse

from .media import (
    classify_url,
    cloudflare_manifest_from_iframe,
    embed_urls_from_html,
    is_manifest,
    manifest_duration,
    replay_headers,
)
from .models import Attachment, Lesson, MediaSource
from .text import humanize_slug, normalize_for_match, safe_filename

LESSON_URL_RE = re.compile(
    r"/(?:p|view)/courses/(?P<course>[^/?#]+)/(?P<module>\d+)-(?P<module_slug>[^/?#]+)"
    r"/(?P<lesson>\d+)-(?P<lesson_slug>[^/?#]+)"
)
COURSE_URL_RE = re.compile(r"/(?:p|view)/courses/(?P<course>[^/?#]+)")
LOGIN_WORDS = ("login", "sign", "password", "verif", "two_factor", "2fa", "session", "auth", "connexion")
STATUS_WORDS = re.compile(r"\s*(?:terminée?|complétée?|completed?|verrouillée?|locked|en cours|nouveau)\s*$", re.I)

DEFAULT_PROFILE = Path.home() / ".podia_formation" / "navigateur"

# --- JavaScript exécuté dans la page -----------------------------------------

JS_COUNT_LESSON_LINKS = r"""
(course) => {
  const re = /\/(?:p|view)\/courses\/([^\/?#]+)\/\d+-[^\/?#]+\/\d+-[^\/?#]+/;
  let n = 0;
  for (const a of document.querySelectorAll('a[href]')) {
    let href = '';
    try { href = new URL(a.getAttribute('href'), location.href).pathname; } catch (e) { continue; }
    const m = href.match(re);
    if (m && (!course || m[1] === course)) n++;
  }
  return n;
}
"""

JS_SIDEBAR = r"""
() => {
  const LESSON = /\/(?:p|view)\/courses\/[^\/?#]+\/\d+-[^\/?#]+\/\d+-[^\/?#]+/;
  const MODULE = /\/(?:p|view)\/courses\/[^\/?#]+\/\d+-[^\/?#]+\/?$/;
  const abs = (h) => { try { return new URL(h, location.href).href; } catch (e) { return ''; } };
  const path = (h) => { try { return new URL(h).pathname; } catch (e) { return ''; } };
  const txt = (el) => (el.innerText || el.textContent || '').trim();
  const lessons = [...document.querySelectorAll('a[href]')].filter(a => LESSON.test(path(abs(a.getAttribute('href')))));
  const items = [];
  if (lessons.length) {
    const need = Math.ceil(lessons.length * 0.8);
    const count = (el) => lessons.filter(a => el.contains(a)).length;
    let root = lessons[0];
    while (root.parentElement && count(root) < need) root = root.parentElement;
    const HEAD = /^(H[1-6]|SUMMARY|BUTTON|HEADER|DT|LEGEND|STRONG)$/;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
    for (let n = walker.currentNode; n; n = walker.nextNode()) {
      if (n.tagName === 'A') {
        const href = abs(n.getAttribute('href'));
        if (LESSON.test(path(href))) { items.push({type: 'lesson', href, text: txt(n)}); continue; }
        if (MODULE.test(path(href))) { items.push({type: 'heading', text: txt(n)}); continue; }
      }
      if (n.closest('a')) continue;
      const head = HEAD.test(n.tagName) || ['button', 'heading'].includes(n.getAttribute('role')) || n.hasAttribute('aria-expanded');
      if (!head || lessons.some(a => n.contains(a))) continue;
      const t = txt(n).split('\n')[0].trim();
      if (t && t.length <= 160) items.push({type: 'heading', text: t});
    }
  }
  const body = document.body ? document.body.innerText : '';
  const m = body.match(/(\d+)\s*(?:sur|\/|of|out of)\s*(\d+)\s*(?:termin|complet|leçon|lesson)/i);
  return {items, progress: m ? [parseInt(m[1], 10), parseInt(m[2], 10)] : null, title: document.title || ''};
}
"""

JS_CONTENT = r"""
() => {
  const LESSON = /\/(?:p|view)\/courses\/[^\/?#]+\/\d+-[^\/?#]+\/\d+-[^\/?#]+/;
  const abs = (h) => { try { return new URL(h, location.href).href; } catch (e) { return ''; } };
  const isLesson = (a) => { try { return LESSON.test(new URL(abs(a.getAttribute('href'))).pathname); } catch (e) { return false; } };
  const lessonLinks = (el) => [...el.querySelectorAll('a[href]')].filter(isLesson).length;
  const climb = (start) => {
    let n = start;
    while (n.parentElement && n.parentElement !== document.documentElement && lessonLinks(n.parentElement) <= 3) n = n.parentElement;
    return n;
  };
  const starts = [];
  const h1 = document.querySelector('main h1') || document.querySelector('h1');
  if (h1) starts.push(h1);
  for (const sel of ['iframe', 'video', 'stream', 'main p', 'article p', 'p']) {
    const e = document.querySelector(sel);
    if (e) starts.push(e);
  }
  let root = null, best = -1;
  for (const s of starts) {
    const r = climb(s);
    const len = (r.innerText || '').length;
    if (len > best) { best = len; root = r; }
  }
  if (!root) root = document.body;

  // Conversion simple du contenu en Markdown.
  const SKIP = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'NAV', 'ASIDE', 'BUTTON', 'SVG', 'IFRAME', 'VIDEO', 'AUDIO',
                        'STREAM', 'INPUT', 'SELECT', 'TEXTAREA', 'TEMPLATE', 'CANVAS', 'IMG', 'LABEL']);
  const BLOCK = /^(H[1-6]|P|LI|BLOCKQUOTE|PRE|TR|DT|DD|FIGCAPTION|CAPTION)$/;
  const HAS_BLOCK = 'p,li,h1,h2,h3,h4,h5,h6,blockquote,pre,tr,dt,dd,figcaption';
  const out = [];
  const visit = (el) => {
    if (SKIP.has(el.tagName) || el.getAttribute('aria-hidden') === 'true') return;
    const st = getComputedStyle(el);
    if (st.display === 'none' || st.visibility === 'hidden') return;
    if (BLOCK.test(el.tagName)) {
      let t = el.tagName === 'TR'
        ? [...el.children].map(c => (c.innerText || '').trim()).join(' | ')
        : (el.innerText || '').replace(/\n{2,}/g, '\n').trim();
      if (!t) return;
      const tag = el.tagName;
      if (/^H[1-6]$/.test(tag)) t = '#'.repeat(Math.min(+tag[1], 4)) + ' ' + t.replace(/\n/g, ' ');
      else if (tag === 'LI') {
        const p = el.parentElement;
        const ordered = p && p.tagName === 'OL';
        t = (ordered ? ([...p.children].indexOf(el) + 1) + '. ' : '- ') + t.replace(/\n/g, ' ');
      } else if (tag === 'BLOCKQUOTE') t = t.split('\n').map(l => '> ' + l).join('\n');
      else if (tag === 'PRE') t = '```\n' + t + '\n```';
      out.push(t);
      return;
    }
    const direct = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
    if (direct && !el.querySelector(HAS_BLOCK)) {
      const t = (el.innerText || '').trim();
      if (t) out.push(t);
      return;
    }
    for (const c of el.children) visit(c);
  };
  visit(root);

  const files = [];
  for (const a of root.querySelectorAll('a[href]')) {
    const href = abs(a.getAttribute('href'));
    if (/\.pdf(?:[?#]|$)/i.test(href) || /\/content-assets\//i.test(href) || a.hasAttribute('download'))
      files.push({url: href, name: (a.getAttribute('download') || a.innerText || '').trim()});
  }
  for (const e of root.querySelectorAll('iframe[src], embed[src], object[data]')) {
    const src = abs(e.getAttribute('src') || e.getAttribute('data'));
    if (/\.pdf(?:[?#]|$)/i.test(src)) files.push({url: src, name: ''});
  }
  const media = [];
  for (const e of document.querySelectorAll('iframe[src], video, audio, source[src], stream[src], [data-src]')) {
    for (const v of [e.getAttribute('src'), e.getAttribute('data-src'), e.currentSrc]) if (v) media.push(abs(v));
  }
  const radios = [...root.querySelectorAll('input[type=radio]')];
  const radioGroups = new Set(radios.map((r, i) => r.name || ('_' + i))).size;
  let next = '';
  const rel = document.querySelector('a[rel=next][href]');
  if (rel && isLesson(rel)) next = abs(rel.getAttribute('href'));
  if (!next) {
    for (const a of document.querySelectorAll('a[href]')) {
      const t = (a.innerText || '').trim().toLowerCase();
      if ((t === 'continuer' || t === 'suivant' || t === 'next') && isLesson(a)) { next = abs(a.getAttribute('href')); break; }
    }
  }
  const player = !!root.querySelector('iframe, video, stream, audio') || !!document.querySelector('stream, video');
  return {
    title: h1 ? (h1.innerText || '').trim() : '',
    markdown: out.join('\n\n'),
    files, media, next, player,
    radioGroups,
    checkboxes: root.querySelectorAll('input[type=checkbox]').length,
    quizWords: /\b(quiz|questionnaire|question\s+\d+|bonne r[ée]ponse|valider mes r[ée]ponses)\b/i.test(root.innerText || ''),
  };
}
"""

JS_PLAY = r"""
() => {
  let n = 0;
  for (const v of document.querySelectorAll('video')) {
    v.muted = true;
    try { const p = v.play(); if (p && p.catch) p.catch(() => {}); n++; } catch (e) {}
  }
  if (!n) {
    const b = document.querySelector('button[aria-label*="play" i], button[aria-label*="lire" i], [class*="play" i][role=button], .vjs-big-play-button, .w-big-play-button');
    if (b) { try { b.click(); n++; } catch (e) {} }
  }
  return n;
}
"""

JS_PAUSE_AND_DURATION = r"""
() => {
  let d = null;
  for (const v of document.querySelectorAll('video, audio')) {
    try { v.pause(); } catch (e) {}
    if (isFinite(v.duration) && v.duration > 0) d = Math.max(d || 0, v.duration);
  }
  return d;
}
"""

JWT_RE = re.compile(r"eyJ[\w-]+\.[\w-]+\.[\w-]+")


# --- Construction de la liste des leçons (logique pure, testée) --------------

def course_slug_from_url(url: str) -> str:
    m = COURSE_URL_RE.search(urlparse(url).path)
    return m.group("course") if m else ""


def _clean_anchor_text(text: str) -> str:
    for line in (text or "").replace("\r", "").split("\n"):
        line = STATUS_WORDS.sub("", line.strip()).strip()
        if line:
            return line
    return ""


def _clean_heading(text: str) -> str:
    return re.sub(r"[\s▾▸▼►▲◂⌄⌃›‹]+$", "", (text or "").strip()).strip()


def choose_module_title(headings: list[str], module_slug: str) -> str:
    fallback = humanize_slug(module_slug)
    target = normalize_for_match(fallback)
    best, best_score = "", 0
    for candidate in reversed(headings):          # le plus proche de la première leçon d'abord
        candidate = _clean_heading(candidate)
        score = len(normalize_for_match(candidate) & target)
        if score > best_score:
            best, best_score = candidate, score
    return best or fallback


def build_lessons(items: list[dict], course: str) -> list[Lesson]:
    """Transforme les éléments de la barre latérale en leçons numérotées."""
    modules: dict[str, dict] = {}
    pending: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item.get("type") == "heading":
            text = _clean_heading(item.get("text", ""))
            if text and (not pending or pending[-1] != text):
                pending.append(text)
            continue
        href = item.get("href", "")
        m = LESSON_URL_RE.search(urlparse(href).path)
        if not m or (course and m.group("course") != course):
            continue
        lesson_id = m.group("lesson")
        if lesson_id in seen:
            continue
        seen.add(lesson_id)
        mod = modules.setdefault(m.group("module"), {
            "slug": m.group("module_slug"), "headings": pending, "lessons": [],
        })
        pending = []
        title = _clean_anchor_text(item.get("text", "")) or humanize_slug(m.group("lesson_slug"))
        mod["lessons"].append((lesson_id, href.split("#")[0], title))
    lessons: list[Lesson] = []
    for module_index, (module_id, mod) in enumerate(modules.items(), start=1):
        module_title = choose_module_title(mod["headings"], mod["slug"])
        for lesson_index, (lesson_id, href, title) in enumerate(mod["lessons"], start=1):
            lessons.append(Lesson(
                index=len(lessons) + 1, lesson_id=lesson_id, url=href, title=title,
                module_index=module_index, module_id=module_id, module_title=module_title,
                lesson_index=lesson_index,
            ))
    return lessons


def course_title(data: dict, course: str) -> str:
    """Titre de la formation : l'élément de page qui ressemble le plus au slug de l'URL."""
    candidates = [t.strip() for t in re.split(r"\s[|–—-]\s", data.get("title") or "") if t.strip()]
    candidates += [i.get("text", "") for i in data.get("items", []) if i.get("type") == "heading"]
    target = normalize_for_match(humanize_slug(course))
    best, best_score = "", 0
    for candidate in candidates:
        candidate = _clean_heading(candidate)
        words = normalize_for_match(candidate)
        score = len(words & target)
        if score > best_score or (score == best_score and score and len(words) < len(normalize_for_match(best))):
            best, best_score = candidate, score
    return best if best_score >= max(1, len(target) // 2) else humanize_slug(course)


def title_is_from_slug(lesson: Lesson) -> bool:
    m = LESSON_URL_RE.search(urlparse(lesson.url).path)
    return bool(m) and lesson.title == humanize_slug(m.group("lesson_slug"))


def renumber(lessons: list[Lesson]) -> None:
    """Renumérote après l'ajout d'une leçon découverte en cours de route."""
    module_order: dict[str, int] = {}
    counters: dict[str, int] = {}
    for i, lesson in enumerate(lessons, start=1):
        lesson.index = i
        lesson.module_index = module_order.setdefault(lesson.module_id, len(module_order) + 1)
        counters[lesson.module_id] = counters.get(lesson.module_id, 0) + 1
        lesson.lesson_index = counters[lesson.module_id]


def lesson_from_url(url: str, module_title: str = "") -> Lesson | None:
    m = LESSON_URL_RE.search(urlparse(url).path)
    if not m:
        return None
    return Lesson(
        index=0, lesson_id=m.group("lesson"), url=url.split("#")[0],
        title=humanize_slug(m.group("lesson_slug")), module_index=0, module_id=m.group("module"),
        module_title=module_title or humanize_slug(m.group("module_slug")), lesson_index=0,
    )


def classify_lesson(title: str, words: int, videos: int, radio_groups: int, checkboxes: int,
                    quiz_words: bool, attachments: int) -> str:
    if videos:
        return "video"
    if radio_groups or re.search(r"je teste|quiz|questionnaire|qcm", title or "", re.I) or (quiz_words and checkboxes):
        return "quiz"
    if attachments and words < 80:
        return "fichier"
    if words >= 30:
        return "article"
    return "vide"


def pdf_page_count(data: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page(?!s)\b", data))


def redact(text: str) -> str:
    text = JWT_RE.sub("eyJ...(jeton-masque)", text)
    return re.sub(r'(name="csrf-token"\s+content=")[^"]+', r"\1(masque)", text)


# --- Navigateur -------------------------------------------------------------

class NotLoggedIn(RuntimeError):
    pass


@dataclass
class VisitResult:
    title: str = ""
    markdown: str = ""
    videos: list[MediaSource] = field(default_factory=list)
    files: list[dict] = field(default_factory=list)
    next_url: str = ""
    radio_groups: int = 0
    checkboxes: int = 0
    quiz_words: bool = False
    player_seen: bool = False
    html: str = ""
    frame_urls: list[str] = field(default_factory=list)
    request_urls: list[str] = field(default_factory=list)


class Crawler:
    def __init__(self, browser: str = "auto", headless: bool = False, profile: Path | None = None,
                 executable: str | None = None, login_timeout: int = 900,
                 log: Callable[[str], None] = print):
        self.browser = browser
        self.headless = headless
        self.profile = Path(profile or DEFAULT_PROFILE)
        self.executable = executable
        self.login_timeout = login_timeout
        self.log = log
        self._pw = None
        self.context = None
        self.page = None
        self._media_requests: list = []
        self._all_urls: list[str] = []

    # -- cycle de vie --
    def __enter__(self) -> "Crawler":
        from playwright.sync_api import Error as PlaywrightError, sync_playwright

        self.profile.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        options = dict(
            user_data_dir=str(self.profile), headless=self.headless, locale="fr-FR",
            viewport={"width": 1366, "height": 900}, accept_downloads=True,
            # Les service workers masqueraient certaines requêtes du lecteur.
            service_workers="block",
            handle_sigint=False,      # Ctrl+C est géré par l'outil (sinon blocage à la fermeture)
            args=["--mute-audio", "--autoplay-policy=no-user-gesture-required",
                  "--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
        )
        if self.executable:
            attempts = [("chemin fourni", {"executable_path": self.executable})]
        elif self.browser == "auto":
            # Edge et Chrome lisent le H.264/AAC des vidéos, contrairement au Chromium de Playwright.
            attempts = [("Microsoft Edge", {"channel": "msedge"}), ("Google Chrome", {"channel": "chrome"}),
                        ("Chromium (Playwright)", {})]
        else:
            channel = {"chromium": None, "edge": "msedge", "msedge": "msedge", "chrome": "chrome"}.get(self.browser)
            attempts = [(self.browser, {"channel": channel} if channel else {})]
        errors = []
        for label, extra in attempts:
            try:
                self.context = self._pw.chromium.launch_persistent_context(**options, **extra)
                self.log(f"Navigateur : {label}")
                break
            except PlaywrightError as exc:
                errors.append(f"{label} : {str(exc).splitlines()[0]}")
        if self.context is None:
            self._pw.stop()
            raise RuntimeError(
                "Impossible de lancer un navigateur. Installez Chromium avec "
                "« python -m playwright install chromium », ou utilisez --navigateur chrome/msedge.\n"
                + "\n".join(errors))
        self.context.set_default_timeout(30_000)
        self.context.on("request", self._on_request)
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        return self

    def __exit__(self, *exc) -> None:
        # Après un Ctrl+C, la boucle interne de Playwright peut être morte : fermer bloquerait.
        fiber = getattr(self.context, "_dispatcher_fiber", None) or getattr(self._pw, "_dispatcher_fiber", None)
        if fiber is not None and getattr(fiber, "dead", False):
            return
        try:
            if self.context:
                self.context.close()
        except Exception:
            pass
        finally:
            try:
                if self._pw:
                    self._pw.stop()
            except Exception:
                pass

    def _on_request(self, request) -> None:
        url = request.url
        self._all_urls.append(url)
        if is_manifest(url) or (classify_url(url) and classify_url(url)[0] != "fichier"):
            self._media_requests.append(request)

    # -- attente --
    def _settle(self, ms_idle: int = 8000) -> None:
        try:
            self.page.wait_for_load_state("networkidle", timeout=ms_idle)
        except Exception:
            pass
        self.page.wait_for_timeout(800)

    def _lesson_link_count(self, course: str) -> int:
        try:
            return int(self.page.evaluate(JS_COUNT_LESSON_LINKS, course))
        except Exception:
            return 0

    def _wait_lessons(self, course: str, timeout_ms: int) -> bool:
        try:
            self.page.wait_for_function(f"({JS_COUNT_LESSON_LINKS})({course!r}) > 0", timeout=timeout_ms)
            return True
        except Exception:
            return self._lesson_link_count(course) > 0

    # -- connexion et liste des leçons --
    def open_course(self, start_url: str) -> dict:
        course = course_slug_from_url(start_url)
        if not course:
            raise ValueError("L'adresse doit contenir /p/courses/<nom-de-la-formation>.")
        page = self.page
        page.goto(start_url, wait_until="domcontentloaded", timeout=90_000)
        self._settle()
        if not self._wait_lessons(course, 10_000):
            if self.headless:
                raise NotLoggedIn("Session absente ou expirée : relancez sans --headless pour vous connecter.")
            origin = "{0.scheme}://{0.netloc}".format(urlparse(start_url))
            if not any(w in urlparse(page.url).path.lower() for w in LOGIN_WORDS):
                try:
                    page.goto(origin + "/login", wait_until="domcontentloaded", timeout=60_000)
                except Exception:
                    pass
            self.log("\n>>> Connectez-vous à Podia dans la fenêtre du navigateur qui vient de s'ouvrir "
                     "(e-mail, mot de passe, code reçu par e-mail si demandé).\n"
                     ">>> L'outil reprend tout seul une fois la connexion faite.\n")
            deadline = time.monotonic() + self.login_timeout
            while time.monotonic() < deadline:
                page.wait_for_timeout(2000)
                try:
                    if course in page.url and self._lesson_link_count(course) > 0:
                        break
                    path = urlparse(page.url).path.lower()
                    if not any(w in path for w in LOGIN_WORDS):
                        page.goto(start_url, wait_until="domcontentloaded", timeout=90_000)
                        if self._wait_lessons(course, 15_000):
                            break
                except Exception:
                    continue
            else:
                raise NotLoggedIn("Connexion non détectée dans le délai imparti.")
            self._settle()
        data = page.evaluate(JS_SIDEBAR)
        data["course"] = course
        data["url"] = page.url
        return data

    # -- visite d'une leçon --
    def visit(self, url: str, capture_video: bool = True) -> VisitResult:
        page = self.page
        self._media_requests.clear()
        self._all_urls.clear()
        page.goto(url, wait_until="domcontentloaded", timeout=90_000)
        self._settle()
        info = page.evaluate(JS_CONTENT)
        res = VisitResult(
            title=info.get("title", ""), markdown=info.get("markdown", ""), files=info.get("files", []),
            next_url=info.get("next", ""), radio_groups=int(info.get("radioGroups") or 0),
            checkboxes=int(info.get("checkboxes") or 0), quiz_words=bool(info.get("quizWords")),
            player_seen=bool(info.get("player")),
        )
        dom_urls = list(info.get("media", []))
        frame_urls = [f.url for f in page.frames]
        try:
            html = page.content()
        except Exception:
            html = ""
        dom_urls += embed_urls_from_html(html)
        dom_urls += frame_urls

        has_embed = any(classify_url(u) for u in dom_urls)
        videos, confirmed = self._collect_sources(url, dom_urls)
        if capture_video and (res.player_seen or has_embed) and not confirmed:
            # Aucun flux vérifié : on lance la lecture (muette) pour que le lecteur le demande.
            self._try_play()
            for _ in range(30):
                if self._manifest_requests():
                    break
                page.wait_for_timeout(500)
            page.wait_for_timeout(1000)
            videos, confirmed = self._collect_sources(url, dom_urls + [f.url for f in page.frames])
        element_duration = None
        for frame in page.frames:
            try:
                d = frame.evaluate(JS_PAUSE_AND_DURATION)
                if d:
                    element_duration = max(element_duration or 0, float(d))
            except Exception:
                pass
        res.videos = videos
        if element_duration and len(res.videos) == 1 and not res.videos[0].duration_s:
            res.videos[0].duration_s = element_duration
        res.html, res.frame_urls, res.request_urls = html, frame_urls, list(self._all_urls)
        return res

    def _manifest_requests(self) -> list:
        return [r for r in self._media_requests if is_manifest(r.url)]

    def _try_play(self) -> None:
        played = 0
        for frame in self.page.frames:
            try:
                played += int(frame.evaluate(JS_PLAY) or 0)
            except Exception:
                pass
        if played:
            return
        for selector in ('iframe[src*="cloudflarestream"]', 'iframe[src*="videodelivery"]', "stream", "video",
                         'iframe[src*="wistia"]', '[class*="player" i]', "iframe"):
            loc = self.page.locator(selector).first
            try:
                if loc.count():
                    loc.click(timeout=3000, force=True)
                    return
            except Exception:
                continue

    def _fetch_text(self, url: str, headers: dict) -> str:
        resp = self.context.request.get(url, headers=headers, timeout=30_000)
        if not resp.ok:
            raise RuntimeError(f"HTTP {resp.status}")
        return resp.text()

    def _collect_sources(self, page_url: str, dom_urls: list[str]) -> tuple[list[MediaSource], bool]:
        """Sources vidéo de la leçon, et True si au moins une est confirmée (manifeste lisible ou lecteur tiers)."""
        site = "{0.scheme}://{0.netloc}".format(urlparse(page_url))
        sources: dict[str, MediaSource] = {}
        # 1) Manifestes réellement demandés par le lecteur (le plus fiable).
        for req in self._media_requests:
            url = req.url
            if not is_manifest(url):
                continue
            kind, key = classify_url(url) or ("hls", url)
            if key in sources:
                continue
            try:
                headers = replay_headers(req.all_headers(), url, page_url)
            except Exception:
                headers = replay_headers({}, url, page_url)
            sources[key] = MediaSource(kind=kind, url=url, key=key, headers=headers)
        # 2) Lecteurs repérés dans la page sans requête de manifeste.
        for url in dom_urls:
            found = classify_url(url)
            if not found:
                continue
            kind, key = found
            if key in sources:
                continue
            if kind == "cloudflare":
                manifest = url if is_manifest(url) else cloudflare_manifest_from_iframe(url, site)
                if not manifest:
                    continue
                url = manifest
            if kind == "fichier" and not re.search(r"\.(?:mp4|m4a|mp3|m4v|webm)(?:[?#]|$)", url, re.I):
                continue
            sources[key] = MediaSource(kind=kind, url=url, key=key, headers=replay_headers({}, url, page_url))
        # 3) Les playlists HLS secondaires (variantes) d'un même master sont retirées.
        texts: dict[str, str] = {}
        for key, src in list(sources.items()):
            if src.kind in ("hls", "dash", "cloudflare") and is_manifest(src.url):
                try:
                    texts[key] = self._fetch_text(src.url, src.headers)
                except Exception:
                    texts[key] = ""
        masters = [texts[k] for k in texts if "#EXT-X-STREAM-INF" in texts[k] or "<MPD" in texts[k][:2000]]
        for key, text in texts.items():
            src = sources[key]
            if src.kind == "hls" and "#EXTINF" in text and masters:
                name = unquote(urlparse(src.url).path.rsplit("/", 1)[-1])
                if any(name and name in m for m in masters):
                    del sources[key]
                    continue
            if text:
                try:
                    src.duration_s = manifest_duration(src.url, lambda u, h=src.headers: (
                        text if u == src.url else self._fetch_text(u, h)))
                except Exception:
                    pass
        # Manifeste injoignable : on l'écarte s'il n'a pas été demandé par le lecteur lui-même.
        requested = {r.url for r in self._media_requests}
        for key in [k for k, t in texts.items() if not t and sources[k].url not in requested]:
            del sources[key]
        confirmed = any(texts.get(k) for k in sources) or any(
            s.kind in ("wistia", "vimeo", "youtube", "loom", "fichier") for s in sources.values())
        return list(sources.values()), confirmed

    def download_file(self, url: str, dest_dir: Path, stem: str, name_hint: str = "") -> Attachment | None:
        resp = self.context.request.get(url, timeout=120_000)
        if not resp.ok:
            raise RuntimeError(f"HTTP {resp.status}")
        ctype = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
        if ctype.startswith("image/") or ctype == "text/html":
            return None
        data = resp.body()
        base = unquote(urlparse(url).path.rsplit("/", 1)[-1]) or "fichier"
        disp = resp.headers.get("content-disposition") or ""
        m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", disp, re.I)
        if m:
            base = unquote(m.group(1))
        if "." not in base and ctype == "application/pdf":
            base += ".pdf"
        if re.fullmatch(r"eyJ[\w.-]+", base.rsplit(".", 1)[0]) and name_hint:
            base = safe_filename(name_hint) + ("." + base.rsplit(".", 1)[1] if "." in base else "")
        dest_dir.mkdir(parents=True, exist_ok=True)
        path = dest_dir / f"{stem} - {safe_filename(base, 70)}"
        path.write_bytes(data)
        pages = pdf_page_count(data) if (ctype == "application/pdf" or path.suffix.lower() == ".pdf") else 0
        return Attachment(url=url, name=base, path=str(path), pages=pages)

    def snapshot(self) -> VisitResult:
        """État de la page courante (pour un diagnostic sans visite de leçon)."""
        try:
            html = self.page.content()
        except Exception:
            html = ""
        return VisitResult(html=html, frame_urls=[f.url for f in self.page.frames],
                           request_urls=list(self._all_urls))

    def write_diagnostic(self, d: Path, name: str, res: VisitResult) -> None:
        """Page, requêtes réseau et capture d'écran d'une leçon, jetons masqués (pour dépannage)."""
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{name}.html").write_text(redact(res.html), encoding="utf-8")
        lines = ["# Cadres (iframes)", *res.frame_urls, "", "# Requêtes réseau pendant la visite", *res.request_urls]
        (d / f"{name}.reseau.txt").write_text(redact("\n".join(lines)), encoding="utf-8")
        try:
            self.page.screenshot(path=str(d / f"{name}.png"), full_page=True)
        except Exception:
            pass
