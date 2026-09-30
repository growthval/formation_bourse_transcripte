"""Parcours de la formation dans un vrai navigateur (Playwright).

L'utilisateur se connecte une fois dans la fenêtre ouverte ; le profil du
navigateur est conservé, la session reste donc valable aux lancements suivants.
Pour chaque leçon, on lit le texte de la page et on récupère l'adresse du flux
vidéo (liens signés à durée de vie courte) : déduite de l'iframe du lecteur, ou
captée au moment où le lecteur la demande.
"""

from __future__ import annotations

import io
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urlparse

from . import media as _media
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
    r"/(?P<lesson>\d+)-(?P<lesson_slug>[^/?#]+)/?$"
)
COURSE_URL_RE = re.compile(r"/(?:p|view)/courses/(?P<course>[^/?#]+)")
# Pages de connexion : un segment entier de l'adresse (« /login », « /users/sign_in »…), jamais un morceau
# du titre d'une leçon (« …-points-a-verifier-… », « …-session-… »).
LOGIN_PATH_RE = re.compile(
    r"/(?:log_?in|sign_?in|sign_?up|sessions?|passwords?|verify|verification|two_factor|2fa|otp|"
    r"o?auth\w*|connexion|magic_link)(?=[/?#.]|$)", re.I)
STATUS_WORDS = re.compile(r"\s*(?:terminée?|complétée?|completed?|verrouillée?|locked|en cours|nouveau)\s*$", re.I)
NAV_WORDS = re.compile(r"^(continuer|suivant|leçon suivante|précédent|precedent|leçon précédente|reprendre|"
                       r"commencer|démarrer|demarrer|valider|marquer|terminer|next|previous|prev|resume|start|"
                       r"continue|mark)\b", re.I)

DEFAULT_PROFILE = Path.home() / ".podia_formation" / "navigateur"

# --- JavaScript exécuté dans la page -----------------------------------------

# Fonctions communes : liens de leçons (hors boutons de navigation) et conteneur du sommaire.
_JS_HELPERS = r"""
  const LESSON = /\/(?:p|view)\/courses\/([^\/?#]+)\/(\d+)-[^\/?#]+\/(\d+)-[^\/?#]+\/?$/;
  const MODULE = /\/(?:p|view)\/courses\/([^\/?#]+)\/(\d+)-[^\/?#]+\/?$/;
  const NAV = /^(continuer|suivant|leçon suivante|précédent|precedent|leçon précédente|reprendre|commencer|démarrer|demarrer|valider|marquer|terminer|next|previous|prev|resume|start|continue|mark)\b/i;
  const abs = (h) => { try { return new URL(h, location.href).href; } catch (e) { return ''; } };
  const pathOf = (h) => { try { return new URL(h, location.href).pathname; } catch (e) { return ''; } };
  const label = (a) => ((a.getAttribute('aria-label') || a.getAttribute('title') || a.innerText || a.textContent || '')
    .replace(/[→›»>▶←‹«<◀]+/g, ' ').replace(/\s+/g, ' ').trim());
  const lessonMatch = (a) => pathOf(a.getAttribute('href') || '').match(LESSON);
  const isNav = (a) => a.matches('[rel=next],[rel=prev],[data-method],[data-turbo-method]') || NAV.test(label(a));
  const curriculumLinks = (course) => [...document.querySelectorAll('a[href]')].filter(a => {
    const m = lessonMatch(a);
    return m && (!course || m[1] === course) && !isNav(a);
  });
  const depth = (el) => { let d = 0; while (el.parentElement) { el = el.parentElement; d++; } return d; };
  const curriculumRoot = (links) => {
    // L'élément le plus profond qui contient au moins 80 % des leçons distinctes : le sommaire.
    if (!links.length) return null;
    const id = (a) => lessonMatch(a)[3];
    const need = Math.ceil(new Set(links.map(id)).size * 0.8);
    const countIn = (el) => new Set(links.filter(a => el.contains(a)).map(id)).size;
    let best = null, bestDepth = -1;
    const tried = new Set();
    for (const a of links) {
      let n = a;
      while (n.parentElement && countIn(n) < need) n = n.parentElement;
      if (tried.has(n)) continue;
      tried.add(n);
      const d = depth(n);
      if (d > bestDepth) { best = n; bestDepth = d; }
    }
    return best;
  };
"""

JS_COUNT_LESSON_LINKS = "(course) => {" + _JS_HELPERS + "  return curriculumLinks(course).length;\n}"

JS_LOGIN_FORM = r"""
() => !!document.querySelector('input[type=password], input[autocomplete="one-time-code"], input[name*="code" i][inputmode=numeric]')
"""

# Signes d'une page vue sans être connecté (le sommaire de Zonebourse est public : il ne prouve rien).
JS_AUTH_STATE = r"""
() => {
  const txt = (e) => ((e.getAttribute('aria-label') || e.innerText || e.textContent || '') + '').replace(/\s+/g, ' ').trim();
  const els = [...document.querySelectorAll('a, button, [role=button]')];
  const LOGIN = /^(se connecter|connexion|connectez-vous|me connecter|s'identifier|log ?in|sign ?in)$/i;
  const LOGOUT = /(déconnexion|se déconnecter|log ?out|sign ?out)/i;
  const href = (e) => e.getAttribute('href') || '';
  const own = (h) => { try { return new URL(h, location.href).origin === location.origin; } catch (e) { return false; } };
  const loginLink = els.some(e => (LOGIN.test(txt(e)) && (!href(e) || own(href(e))))
                                  || (own(href(e)) && /\/(login|sign_in|signin)(?:[\/?#]|$)/i.test(href(e))));
  const logout = els.some(e => LOGOUT.test(txt(e)) || /\/(logout|sign_out|signout)(?:[\/?#]|$)/i.test(href(e)));
  const password = !!document.querySelector('input[type=password]');
  const body = document.body ? document.body.innerText.slice(0, 30000) : '';
  const gate = /(connectez-vous|identifiez-vous|log in|sign in|inscrivez-vous|achetez|acheter)[^.\n]{0,60}(accéder|continuer|voir|regarder|access|continue|view)/i.test(body);
  return {loginLink, logout, password, gate, textLength: body.length};
}
"""

JS_EXPAND_MODULES = r"""
() => {
  let n = 0;
  for (const d of document.querySelectorAll('details:not([open])')) { d.open = true; n++; }
  for (const b of document.querySelectorAll('[aria-expanded="false"]')) {
    if (b.matches('a[href]') || b.closest('a[href]')) continue;
    if (!/module|section|chapitre|partie/i.test((b.innerText || b.getAttribute('aria-label') || '').trim())) continue;
    try { b.click(); n++; } catch (e) {}
  }
  return n;
}
"""

JS_SIDEBAR = "() => {" + _JS_HELPERS + r"""
  const links = curriculumLinks('');
  const root = curriculumRoot(links);
  const items = [];
  if (root) {
    const lessonSet = new Set(links);
    const HEAD = /^(H[1-6]|SUMMARY|BUTTON|HEADER|DT|LEGEND|STRONG)$/;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
    const txt = (el) => (el.innerText || el.textContent || '').trim();
    for (let n = walker.currentNode; n; n = walker.nextNode()) {
      if (n.tagName === 'A') {
        if (lessonSet.has(n)) { items.push({type: 'lesson', href: abs(n.getAttribute('href')), text: txt(n)}); continue; }
        if (MODULE.test(pathOf(n.getAttribute('href') || ''))) { items.push({type: 'heading', text: txt(n)}); continue; }
      }
      if (n.closest('a')) continue;
      const head = HEAD.test(n.tagName) || ['button', 'heading'].includes(n.getAttribute('role')) || n.hasAttribute('aria-expanded');
      if (!head || links.some(a => n.contains(a))) continue;
      const t = txt(n).split('\n')[0].trim();
      if (t && t.length <= 160) items.push({type: 'heading', text: t});
    }
  }
  const moduleLinks = [...document.querySelectorAll('a[href]')]
    .filter(a => MODULE.test(pathOf(a.getAttribute('href') || ''))).map(a => abs(a.getAttribute('href')));
  const cta = [...document.querySelectorAll('a[href]')].filter(a => lessonMatch(a) && isNav(a)).map(a => abs(a.getAttribute('href')));
  const body = document.body ? document.body.innerText : '';
  const m = body.match(/(\d+)\s*(?:sur|\/|of|out of)\s*(\d+)\s*(?:termin|compl[eé]t|le[çc]on|lesson|élément|element)/i);
  return {items, moduleLinks, cta, progress: m ? [parseInt(m[1], 10), parseInt(m[2], 10)] : null, title: document.title || ''};
}
"""

JS_CONTENT = "() => {" + _JS_HELPERS + r"""
  const course = (location.pathname.match(/\/(?:p|view)\/courses\/([^\/?#]+)/) || [])[1] || '';
  const croot = curriculumRoot(curriculumLinks(course));
  const EXCL = 'nav, aside, [role=navigation], [id*=comment], [class*=comment], [class*=replies]';
  const outside = (el) => !(croot && (croot === el || croot.contains(el))) && !el.closest(EXCL);

  // Titre : candidats h1/h2 hors sommaire et commentaires, plus le titre de l'onglet.
  const titles = [...document.querySelectorAll('h1, h2')].filter(outside)
    .map(h => (h.innerText || '').trim()).filter(t => t && t.length < 200).slice(0, 8);
  const docTitle = (document.title || '').split(/\s[|–—-]\s/)[0].trim();

  // Zones de texte de la leçon (texte riche Podia/Trix en priorité), sinon remontée depuis le titre.
  const RICH = '.trix-content, [data-controller~="richtext"], .text-longform, #lesson-content, [class*="lesson-content"], [class*="lesson-body"]';
  let roots = [...document.querySelectorAll(RICH)].filter(outside);
  roots = roots.filter(r => !roots.some(o => o !== r && o.contains(r)));
  if (!roots.length) {
    const climb = (start) => {
      let n = start;
      while (n.parentElement && n.parentElement !== document.body && n.parentElement !== document.documentElement
             && !(croot && n.parentElement.contains(croot))) n = n.parentElement;
      return n;
    };
    const starts = [...document.querySelectorAll('main h1, h1, article, main, iframe, video, p')].filter(outside).slice(0, 12);
    let best = null, bestLen = -1;
    for (const s of starts) {
      const r = climb(s);
      const len = (r.innerText || '').length;
      if (len > bestLen) { best = r; bestLen = len; }
    }
    roots = best ? [best] : [document.body];
  }

  // Conversion en Markdown (le texte mêlé à des blocs est conservé).
  const SKIP = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'NAV', 'ASIDE', 'BUTTON', 'SVG', 'IFRAME', 'VIDEO', 'AUDIO',
                        'STREAM', 'INPUT', 'SELECT', 'TEXTAREA', 'TEMPLATE', 'CANVAS', 'IMG', 'LABEL', 'HEADER', 'FOOTER']);
  const BLOCK = /^(H[1-6]|P|LI|BLOCKQUOTE|PRE|TR|DT|DD|CAPTION)$/;
  const INLINE = new Set(['A', 'SPAN', 'STRONG', 'B', 'EM', 'I', 'U', 'S', 'CODE', 'SMALL', 'SUB', 'SUP', 'MARK',
                          'ABBR', 'TIME', 'Q', 'CITE', 'FONT', 'BR', 'DEL', 'INS']);
  const BLOCKY = 'p,div,li,ul,ol,h1,h2,h3,h4,h5,h6,table,figure,blockquote,pre,section,article';
  const out = [];
  const skip = (el) => {
    if (SKIP.has(el.tagName) || el.getAttribute('aria-hidden') === 'true' || !outside(el)) return true;
    const st = getComputedStyle(el);
    return st.display === 'none' || st.visibility === 'hidden';
  };
  const flush = (buf) => {
    const text = buf.join('');
    buf.length = 0;
    for (const p of text.split(/\n\s*\n/)) {
      const t = p.replace(/[ \t]*\n[ \t]*/g, '\n').replace(/[ \t]+/g, ' ').trim();
      if (t) out.push(t);
    }
  };
  const visit = (el) => {
    if (skip(el)) return;
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
    if (el.tagName === 'FIGURE' || el.tagName === 'ACTION-TEXT-ATTACHMENT') {
      const cap = el.querySelector('figcaption');
      if (cap && (cap.innerText || '').trim()) out.push((cap.innerText || '').trim());
      return;
    }
    const buf = [];
    for (const c of el.childNodes) {
      if (c.nodeType === 3) { buf.push(c.textContent.replace(/\s+/g, ' ')); continue; }
      if (c.nodeType !== 1) continue;
      if (c.tagName === 'BR') { buf.push('\n'); continue; }
      if (INLINE.has(c.tagName) && !c.querySelector(BLOCKY)) {
        if (!skip(c)) buf.push((c.innerText || c.textContent || '').replace(/[ \t]+/g, ' '));
        continue;
      }
      flush(buf);
      visit(c);
    }
    flush(buf);
  };
  for (const r of roots) visit(r);

  // Fichiers joints (PDF, pièces jointes Podia).
  const files = [];
  for (const r of roots) {
    for (const a of r.querySelectorAll('a[href]')) {
      const href = abs(a.getAttribute('href'));
      if (/\.pdf(?:[?#]|$)/i.test(href) || /\/content-assets\//i.test(href) || a.hasAttribute('download'))
        files.push({url: href, name: (a.getAttribute('download') || a.innerText || '').trim()});
    }
  }
  for (const e of document.querySelectorAll('iframe[src], embed[src], object[data]')) {
    const src = abs(e.getAttribute('src') || e.getAttribute('data'));
    if (/\.pdf(?:[?#]|$)/i.test(src) && outside(e)) files.push({url: src, name: ''});
  }

  // Lecteurs vidéo de la leçon (hors sommaire et commentaires).
  const PLAYER = /cloudflarestream|videodelivery|wistia|vimeo|youtube|loom\.com|vidyard|jwplayer|mux\.com|dailymotion/i;
  const media = [];
  for (const e of document.querySelectorAll('iframe[src], video, audio, source[src], stream[src], wistia-player, [data-src]')) {
    if (!outside(e)) continue;
    const mid = e.getAttribute('media-id');
    if (mid) media.push('wistia:' + mid);
    for (const v of [e.getAttribute('src'), e.getAttribute('data-src'), e.currentSrc]) if (v) media.push(abs(v));
  }
  const player = [...document.querySelectorAll('video, audio, stream, wistia-player, [class*=wistia_embed]')].some(outside)
    || [...document.querySelectorAll('iframe[src]')].some(f => {
         const src = f.getAttribute('src') || '';
         return outside(f) && !/\.pdf(?:[?#]|$)/i.test(src) && (PLAYER.test(src) || /\/iframe(?:[?#]|$)/.test(pathOf(src) + '#'));
       });
  // HTML à analyser, sans le sommaire ni les commentaires (vignettes d'autres vidéos).
  let scanHtml = '';
  try {
    if (croot) croot.setAttribute('data-pf-sommaire', '1');
    const clone = document.documentElement.cloneNode(true);
    clone.querySelectorAll('[data-pf-sommaire], [id*=comment], [class*=comment], script[src]').forEach(e => e.remove());
    scanHtml = clone.outerHTML;
  } catch (e) {}

  // Leçon suivante (lien « Continuer », jamais cliqué).
  const NEXT = /^(continuer|suivant|leçon suivante|next|next lesson|continue)\b/i;
  let next = '';
  for (const a of [...document.querySelectorAll('a[rel=next][href]'), ...document.querySelectorAll('a[href]')]) {
    const m = lessonMatch(a);
    if (!m || m[1] !== course || a.matches('[data-method],[data-turbo-method]')) continue;
    if (a.getAttribute('rel') === 'next' || NEXT.test(label(a))) { next = abs(a.getAttribute('href')); break; }
  }
  const text = roots.map(r => r.innerText || '').join('\n');
  const radios = roots.flatMap(r => [...r.querySelectorAll('input[type=radio]')]);
  return {
    titles, docTitle,
    markdown: out.join('\n\n'),
    files, media, next, player, scanHtml,
    radioGroups: new Set(radios.map((r, i) => r.name || ('_' + i))).size,
    checkboxes: roots.reduce((n, r) => n + r.querySelectorAll('input[type=checkbox]').length, 0),
    quizWords: /\b(quiz|questionnaire|question\s+\d+|bonne r[ée]ponse|valider mes r[ée]ponses)\b/i.test(text),
  };
}
"""

JS_PLAY = r"""
() => {
  let n = 0;
  for (const v of document.querySelectorAll('video')) {
    if (v.readyState === 0 && !v.currentSrc && !v.src && !v.querySelector('source[src]')) continue;   // lecteur sans source
    v.muted = true;
    try { const p = v.play(); if (p && p.catch) p.catch(() => {}); n++; } catch (e) {}
  }
  return n;
}
"""

JS_CLICK_PLAY_BUTTON = r"""
() => {
  const LABEL = /^(play|lire|lire la vidéo|lecture|démarrer la vidéo|play video)$/i;
  const b = [...document.querySelectorAll('button, [role=button]')].find(e =>
    LABEL.test((e.getAttribute('aria-label') || e.getAttribute('title') || e.innerText || '').trim()))
    || document.querySelector('.vjs-big-play-button, .w-big-play-button, [data-testid*="play" i]');
  if (!b) return 0;
  try { b.click(); return 1; } catch (e) { return 0; }
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


def is_login_url(url: str) -> bool:
    """Adresse d'une page de connexion ? Les pages de la formation n'en sont jamais une."""
    path = urlparse(url).path
    if COURSE_URL_RE.search(path):
        return False
    return bool(LOGIN_PATH_RE.search(path))


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


def slug_score(title: str, slug: str) -> float:
    """Ressemblance entre un titre et le slug de l'URL (0 à 1)."""
    target = normalize_for_match(humanize_slug(slug))
    words = normalize_for_match(title)
    if not target or not words:
        return 0.0
    return len(words & target) / len(target)


def build_lessons(items: list[dict], course: str) -> list[Lesson]:
    """Transforme les éléments de la barre latérale en leçons numérotées."""
    modules: dict[str, dict] = {}
    pending: list[str] = []
    seen: dict[str, list] = {}
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
        title = _clean_anchor_text(item.get("text", ""))
        if NAV_WORDS.match(title or ""):
            title = ""
        if lesson_id in seen:
            entry = seen[lesson_id]
            if title and not entry[2]:
                entry[2] = title                  # un doublon (version mobile…) porte parfois le titre
            continue
        mod = modules.setdefault(m.group("module"), {
            "slug": m.group("module_slug"), "headings": pending, "lessons": [],
        })
        pending = []
        entry = [lesson_id, href.split("#")[0].split("?")[0], title, m.group("lesson_slug")]
        seen[lesson_id] = entry
        mod["lessons"].append(entry)
    lessons: list[Lesson] = []
    for module_index, (module_id, mod) in enumerate(modules.items(), start=1):
        module_title = choose_module_title(mod["headings"], mod["slug"])
        for lesson_index, (lesson_id, href, title, slug) in enumerate(mod["lessons"], start=1):
            lessons.append(Lesson(
                index=len(lessons) + 1, lesson_id=lesson_id, url=href, title=title or humanize_slug(slug),
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


def pick_lesson_title(candidates: list[str], doc_title: str, lesson_slug: str) -> str:
    """Parmi les titres de la page, celui qui correspond le mieux à la leçon (et non à la formation)."""
    pool = [c for c in [*candidates, doc_title] if c and not NAV_WORDS.match(c)]
    if not pool:
        return ""
    scored = [(slug_score(c, lesson_slug), -i, c) for i, c in enumerate(pool)]
    best = max(scored)
    return best[2] if best[0] > 0 else ""


def better_title(current: str, candidate: str, lesson_slug: str) -> bool:
    """Remplacer le titre actuel ? (titre issu du slug, bouton de navigation, ou meilleure correspondance)."""
    if not candidate:
        return False
    if not current or NAV_WORDS.match(current) or current == humanize_slug(lesson_slug):
        return slug_score(candidate, lesson_slug) >= slug_score(current, lesson_slug)
    return False


def renumber(lessons: list[Lesson]) -> None:
    """Renumérote (après l'ajout d'une leçon découverte en cours de route).

    Les modules gardent le numéro de la formation (« Module 7 : … » -> M07) quand tous en ont un ;
    sinon ils sont numérotés dans l'ordre.
    """
    module_order: dict[str, int] = {}
    counters: dict[str, int] = {}
    numbers: dict[str, int | None] = {}
    for i, lesson in enumerate(lessons, start=1):
        lesson.index = i
        lesson.module_index = module_order.setdefault(lesson.module_id, len(module_order) + 1)
        counters[lesson.module_id] = counters.get(lesson.module_id, 0) + 1
        lesson.lesson_index = counters[lesson.module_id]
        m = re.match(r"(?i)\s*modules?\s*(\d+)", lesson.module_title or "")
        numbers.setdefault(lesson.module_id, int(m.group(1)) if m else None)
    values = list(numbers.values())
    if values and None not in values and len(set(values)) == len(values):
        for lesson in lessons:
            lesson.module_index = numbers[lesson.module_id]


def lesson_from_url(url: str, module_title: str = "") -> Lesson | None:
    m = LESSON_URL_RE.search(urlparse(url).path)
    if not m:
        return None
    return Lesson(
        index=0, lesson_id=m.group("lesson"), url=url.split("#")[0].split("?")[0],
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
    """Nombre de pages d'un PDF (pypdf si installé ; sinon lecture directe des objets)."""
    try:
        from pypdf import PdfReader
        return len(PdfReader(io.BytesIO(data)).pages)
    except Exception:
        pass
    pages = len(re.findall(rb"/Type\s*/Page(?!s)\b", data))
    counts = [int(c) for c in re.findall(rb"/Type\s*/Pages\b[^>]*?/Count\s+(\d+)", data)]
    counts += [int(c) for c in re.findall(rb"/Count\s+(\d+)[^>]*?/Type\s*/Pages\b", data)]
    return max([pages, *counts])


def redact(text: str) -> str:
    """Masque jetons, e-mails, signatures d'URL et données de compte avant d'écrire un diagnostic."""
    text = JWT_RE.sub("eyJ...(jeton-masque)", text)
    text = re.sub(r"([?&](?:X-Amz-[\w-]+|Signature|Key-Pair-Id|Policy|Expires|token|sig|signature)=)[^&\"'\s<>]+",
                  r"\1(masque)", text, flags=re.I)
    text = re.sub(r'(<input[^>]*name="[^"]*token[^"]*"[^>]*value=")[^"]+', r"\1(masque)", text, flags=re.I)
    text = re.sub(r'(<meta[^>]*content=")[^"]+("[^>]*name="csrf-token")', r"\1(masque)\2", text)
    text = re.sub(r'(name="(?:csrf-token|authenticity_token)"\s+(?:content|value)=")[^"]+', r"\1(masque)", text)
    text = re.sub(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", "(email-masque)", text)
    text = re.sub(r"cus_[A-Za-z0-9]+", "cus_(masque)", text)
    text = re.sub(r"((?:Podia\.Customer|currentUser|window\.\w*[Uu]ser)\s*=\s*)\{.*?\};?", r"\1{};", text, flags=re.S)
    return re.sub(r'("(?:first_name|last_name|full_name|name|email)"\s*:\s*)"[^"]*"', r'\1"(masque)"', text)


# --- Navigateur -------------------------------------------------------------

class NotLoggedIn(RuntimeError):
    pass


class LessonUnavailable(RuntimeError):
    pass


class PageNotFound(ValueError):
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


def _app_path(exe_name: str) -> list[str]:
    """Chemin déclaré dans le registre Windows (App Paths) pour un exécutable."""
    if sys.platform != "win32":
        return []
    try:
        import winreg
    except ImportError:
        return []
    found = []
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(hive, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe_name}") as key:
                found.append(winreg.QueryValue(key, None))
        except OSError:
            continue
    return found


def browser_candidates(kind: str) -> list[tuple[str, str]]:
    """Navigateurs installés sur l'ordinateur : [(nom, chemin de l'exécutable)]."""
    env = os.environ.get
    edge, chrome = [], []
    if sys.platform == "win32":
        for base in (env("PROGRAMFILES(X86)"), env("PROGRAMFILES"), env("LOCALAPPDATA")):
            if base:
                edge.append(str(Path(base, "Microsoft", "Edge", "Application", "msedge.exe")))
                chrome.append(str(Path(base, "Google", "Chrome", "Application", "chrome.exe")))
        edge += _app_path("msedge.exe")
        chrome += _app_path("chrome.exe")
    elif sys.platform == "darwin":
        edge.append("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge")
        chrome.append("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    else:
        import shutil
        edge += [w for w in (shutil.which("microsoft-edge"), shutil.which("microsoft-edge-stable")) if w]
        chrome += [w for w in (shutil.which("google-chrome"), shutil.which("google-chrome-stable"),
                               shutil.which("chromium"), shutil.which("chromium-browser")) if w]
    order = {"auto": [("Microsoft Edge", edge), ("Google Chrome", chrome)], "edge": [("Microsoft Edge", edge)],
             "msedge": [("Microsoft Edge", edge)], "chrome": [("Google Chrome", chrome)], "chromium": []}
    out = []
    for label, paths in order.get(kind, order["auto"]):
        for path in paths:
            if path and Path(path).is_file() and all(path != p for _, p in out):
                out.append((label, path))
    return out


class Crawler:
    """Navigateur de l'outil.

    Mode normal (fenêtre visible) : un Edge/Chrome ordinaire est lancé sans être piloté ; l'utilisateur
    s'y connecte lui-même (la vérification anti-robot de Cloudflare voit un navigateur normal), puis
    l'outil s'y rattache pour parcourir les leçons. Mode invisible (--headless) : navigateur piloté par
    Playwright, avec la connexion déjà enregistrée dans le profil.
    """

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
        self._browser = None
        self._proc = None
        self._port = 0
        self._exe = ""
        self.mode = "launch"
        self.context = None
        self.page = None
        self._media_requests: list = []
        self._all_urls: list[str] = []
        self.attachment_name_max = 70
        # Options supplémentaires du navigateur (tests automatiques uniquement).
        self.extra_args = os.environ.get("PODIA_EXTRA_BROWSER_ARGS", "").split()

    # -- cycle de vie --
    def __enter__(self) -> "Crawler":
        from playwright.sync_api import sync_playwright

        if sys.platform == "win32":
            # Requêtes faites hors du navigateur (manifestes, PDF) : utiliser les certificats de Windows.
            os.environ.setdefault("NODE_OPTIONS", "--use-system-ca")
        self.profile.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        try:
            if not self.headless:
                found = [("chemin fourni", self.executable)] if self.executable else browser_candidates(self.browser)
                if found:
                    label, self._exe = found[0]
                    self.mode = "cdp"
                    self._start_process("about:blank")
                    self._attach()
                    self.log(f"Navigateur : {label}")
                    return self
            self._launch_playwright()
        except Exception:
            self.__exit__()
            raise
        return self

    def _launch_playwright(self) -> None:
        from playwright.sync_api import Error as PlaywrightError

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
            raise RuntimeError(
                "Impossible de lancer un navigateur. Installez Chromium avec "
                "« python -m playwright install chromium », ou utilisez --navigateur chrome/msedge.\n"
                + "\n".join(errors))
        self.context.set_default_timeout(30_000)
        self.context.on("request", self._on_request)
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()

    # -- navigateur ordinaire, rattaché après coup (mode « cdp ») --
    def _devtools(self, path: str, method: str = "GET"):
        import json
        import urllib.request

        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request(f"http://127.0.0.1:{self._port}{path}", method=method)
        with opener.open(req, timeout=5) as resp:
            body = resp.read().decode("utf-8", "replace")
        return json.loads(body) if body.strip().startswith(("{", "[")) else body

    def _start_process(self, url: str) -> None:
        import socket
        import subprocess

        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self._port = sock.getsockname()[1]
        args = [self._exe, f"--user-data-dir={self.profile}", f"--remote-debugging-port={self._port}",
                "--no-first-run", "--no-default-browser-check", "--mute-audio",
                "--autoplay-policy=no-user-gesture-required", "--lang=fr-FR", *self.extra_args, url]
        self._proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            try:
                self._devtools("/json/version")
                return
            except Exception:
                if self._proc.poll() is not None:
                    break
                time.sleep(0.5)
        raise RuntimeError("Le navigateur ne répond pas. Fermez toutes les fenêtres du navigateur ouvertes par "
                           "l'outil (ou redémarrez l'ordinateur), puis relancez la commande.")

    def _attach(self) -> None:
        self._browser = self._pw.chromium.connect_over_cdp(f"http://127.0.0.1:{self._port}")
        self.context = self._browser.contexts[0] if self._browser.contexts else self._browser.new_context()
        self.context.set_default_timeout(30_000)
        self.context.on("request", self._on_request)
        pages = [pg for pg in self.context.pages if not pg.url.startswith(("devtools:", "chrome-extension:"))]
        self.page = pages[0] if pages else self.context.new_page()

    def _detach(self) -> None:
        try:
            if self._browser:
                self._browser.close()          # navigateur rattaché : se détache sans le fermer
        except Exception:
            pass
        self._browser, self.context, self.page = None, None, None

    def _close_process(self) -> None:
        """Ferme proprement le navigateur (les cookies de connexion sont enregistrés dans le profil)."""
        if self._browser:
            try:
                self._browser.new_browser_cdp_session().send("Browser.close")
            except Exception:
                pass
        self._detach()
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.wait(timeout=10)
            except Exception:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=5)
                except Exception:
                    self._proc.kill()
        self._proc = None

    def _tab_urls(self) -> list[str]:
        try:
            return [t.get("url", "") for t in self._devtools("/json/list") if t.get("type") == "page"]
        except Exception:
            return []

    def __exit__(self, *exc) -> None:
        # Après un Ctrl+C, la boucle interne de Playwright peut être morte : fermer bloquerait.
        fiber = (getattr(self.context, "_dispatcher_fiber", None) or getattr(self._browser, "_dispatcher_fiber", None)
                 or getattr(self._pw, "_dispatcher_fiber", None))
        dead = fiber is not None and getattr(fiber, "dead", False)
        if self.mode == "cdp":
            if dead:
                if self._proc and self._proc.poll() is None:
                    self._proc.terminate()
            else:
                self._close_process()
        elif not dead:
            try:
                if self.context:
                    self.context.close()
            except Exception:
                pass
        if not dead:
            try:
                if self._pw:
                    self._pw.stop()
            except Exception:
                pass

    def _on_request(self, request) -> None:
        url = request.url
        self._all_urls.append(url)
        found = classify_url(url)
        if is_manifest(url) or (found and found[0] != "fichier"):
            self._media_requests.append(request)

    # -- utilitaires --
    def _settle(self, ms_idle: int = 8000) -> None:
        try:
            self.page.wait_for_load_state("networkidle", timeout=ms_idle)
        except Exception:
            pass
        self.page.wait_for_timeout(800)

    @staticmethod
    def _frame_eval(frame, js: str, timeout: int = 3000):
        """Évalue du JS dans un cadre, sans jamais bloquer (cadres vides, visionneuses PDF…)."""
        try:
            if frame.is_detached() or not frame.url.startswith(("http://", "https://")):
                return None
            return frame.locator(":root").evaluate(js, timeout=timeout)
        except Exception:
            return None

    def _lesson_link_count(self, course: str) -> int:
        try:
            return int(self.page.evaluate(JS_COUNT_LESSON_LINKS, course))
        except Exception:
            return 0

    def _wait_lessons(self, course: str, timeout_ms: int) -> bool:
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            if self._lesson_link_count(course) > 0:
                return True
            self.page.wait_for_timeout(500)
        return self._lesson_link_count(course) > 0

    def _auth_state(self) -> dict:
        return self._frame_eval(self.page.main_frame, JS_AUTH_STATE) or {}

    def logged_out(self) -> bool:
        """La page est-elle vue sans être connecté ? (formulaire ou bouton « Se connecter » du site).

        Le texte des leçons n'est pas utilisé : un article sur les adages boursiers (« Achetez au son du
        canon… ») ressemblerait sinon à une page réservée aux inscrits.
        """
        state = self._auth_state()
        if is_login_url(self.page.url) or state.get("password"):
            return True
        if state.get("logout"):
            return False
        return bool(state.get("loginLink"))

    def _wait_stable(self, max_seconds: float = 6.0) -> None:
        """Attend que le contenu de la page (chargé par JavaScript) ait fini de s'afficher."""
        deadline = time.monotonic() + max_seconds
        last, stable = -1, 0
        while time.monotonic() < deadline:
            length = (self._auth_state() or {}).get("textLength", 0)
            stable = stable + 1 if length == last and length > 0 else 0
            if stable >= 2:
                return
            last = length
            self.page.wait_for_timeout(500)

    def _login_form_visible(self) -> bool:
        for frame in self.page.frames:
            if self._frame_eval(frame, JS_LOGIN_FORM):
                return True
        return is_login_url(self.page.url)

    # -- connexion et liste des leçons --
    def open_course(self, start_url: str) -> dict:
        course = course_slug_from_url(start_url)
        if not course:
            raise ValueError("L'adresse doit contenir /p/courses/<nom-de-la-formation>.")
        self._goto_start(start_url)
        self._settle()
        has_lessons = self._wait_lessons(course, 10_000)
        if self.logged_out():
            self._login(start_url, course)
        elif not has_lessons and not self._find_lesson_page(course):
            self._login(start_url, course)
        data = self._read_sidebar()                # la page a pu changer pendant la connexion
        listed = build_lessons(data["items"], course)
        on_lesson = bool(LESSON_URL_RE.search(urlparse(self.page.url).path))
        if listed and not on_lesson:
            # Page d'accueil de la formation (sommaire parfois partiel) : on relit le sommaire depuis une leçon.
            # Les leçons absentes du sommaire sont ensuite trouvées via « Continuer ».
            try:
                self.page.goto(listed[0].url, wait_until="domcontentloaded", timeout=90_000)
                self._settle()
                other = self._read_sidebar()
                if len(build_lessons(other["items"], course)) > len(listed):
                    data = other
            except Exception:
                pass
        data["course"] = course
        data["url"] = self.page.url
        return data

    def _read_sidebar(self) -> dict:
        try:
            if self.page.evaluate(JS_EXPAND_MODULES):
                self.page.wait_for_timeout(1200)       # modules repliés : on les déplie avant de lire
        except Exception:
            pass
        return self.page.evaluate(JS_SIDEBAR)

    def _find_lesson_page(self, course: str) -> bool:
        """Page d'accueil de la formation sans liste de leçons : on ouvre un module ou « Reprendre »."""
        try:
            data = self.page.evaluate(JS_SIDEBAR)
        except Exception:
            return False
        targets = [u for u in [*data.get("cta", []), *data.get("moduleLinks", [])] if course in u]
        for url in targets[:3]:
            try:
                self.page.goto(url, wait_until="domcontentloaded", timeout=90_000)
                self._settle()
                if self._wait_lessons(course, 8_000):
                    return True
            except Exception:
                continue
        return False

    def _goto_start(self, url: str) -> None:
        resp = self.page.goto(url, wait_until="domcontentloaded", timeout=90_000)
        if resp is not None and resp.status == 404:
            # Ex. l'adresse de la formation sans la leçon : Podia répond « page introuvable ».
            raise PageNotFound(f"Page introuvable (erreur 404) : {url}\n"
                               "Utilisez l'adresse complète d'une leçon, copiée depuis la barre d'adresse du "
                               "navigateur quand la leçon est affichée (…/p/courses/<formation>/<module>/<leçon>).")

    def _connected(self, start_url: str, course: str) -> bool:
        self._goto_start(start_url)
        self._settle()
        if self.logged_out():
            return False
        return self._wait_lessons(course, 10_000) or self._find_lesson_page(course)

    @staticmethod
    def _enter_listener():
        """Événement déclenché quand l'utilisateur appuie sur Entrée dans la console."""
        import threading

        pressed = threading.Event()

        def wait_enter() -> None:
            try:
                if sys.stdin and sys.stdin.readline():
                    pressed.set()
            except Exception:
                pass

        threading.Thread(target=wait_enter, daemon=True).start()
        return pressed

    def _open_tab(self, url: str) -> None:
        """Ouvre un onglet sans piloter le navigateur (la vérification Cloudflare reste normale)."""
        try:
            self._devtools("/json/new?" + url, method="PUT")
        except Exception:
            pass

    def _login_cdp(self, start_url: str, course: str) -> None:
        """Connexion dans un navigateur ordinaire, non piloté : la vérification Cloudflare passe normalement."""
        origin = "{0.scheme}://{0.netloc}".format(urlparse(start_url))
        self._close_process()
        self._start_process(origin + "/login")
        self.log("\n>>> Vous n'êtes pas encore connecté.\n"
                 ">>> Connectez-vous à Podia dans la fenêtre du navigateur qui vient de s'ouvrir : e-mail, "
                 "vérification\n>>> Cloudflare, mot de passe, puis le code reçu par e-mail si demandé "
                 "(cochez « faire confiance à cet appareil »).\n"
                 ">>> Ne fermez pas cette fenêtre. Quand vous êtes connecté, revenez ici et appuyez sur Entrée.\n")
        pressed = self._enter_listener()
        deadline = time.monotonic() + self.login_timeout
        quiet, auto_used, attempts = 0, False, 0
        while time.monotonic() < deadline:
            time.sleep(1.5)
            if self._proc is None or self._proc.poll() is not None:
                raise NotLoggedIn("La fenêtre du navigateur a été fermée avant la connexion.")
            urls = [u for u in self._tab_urls() if u.startswith(origin)]
            quiet = quiet + 1 if urls and not any(is_login_url(u) for u in urls) else 0
            auto = not auto_used and quiet >= 3          # détection automatique : une seule fois
            if not (pressed.is_set() or auto):
                continue
            auto_used = True
            attempts += 1
            self._attach()                       # l'outil ne prend la main qu'une fois la connexion faite
            ok, still_out = False, True
            try:
                ok = self._connected(start_url, course)
                still_out = self.logged_out()
            except PageNotFound:
                raise
            except Exception:
                pass
            if ok:
                self.log(">>> Connexion réussie.\n")
                self._settle()
                return
            self._detach()                       # on rend la main sans fermer la fenêtre
            if attempts >= 5:
                raise NotLoggedIn("Connexion non confirmée après plusieurs essais. Envoyez une capture de la fenêtre "
                                  "du navigateur et de cette console pour analyse.")
            if still_out:
                self._open_tab(origin + "/login")
                self.log(">>> Vous n'êtes pas encore connecté : terminez la connexion dans l'onglet ouvert, "
                         "puis appuyez de nouveau sur Entrée.")
            else:
                self.log(">>> La page de la formation ne s'affiche pas comme prévu. Vérifiez la fenêtre du navigateur, "
                         "puis appuyez de nouveau sur Entrée.")
            if pressed.is_set():
                pressed = self._enter_listener()
        raise NotLoggedIn("Connexion non détectée dans le délai imparti.")

    def _login(self, start_url: str, course: str) -> None:
        """Laisse l'utilisateur se connecter dans la fenêtre, puis vérifie la connexion."""
        if self.headless:
            raise NotLoggedIn("Vous n'êtes pas connecté à Podia : relancez sans --headless pour vous connecter.")
        if self.mode == "cdp":
            return self._login_cdp(start_url, course)
        import threading

        page = self.page
        origin = "{0.scheme}://{0.netloc}".format(urlparse(start_url))
        pressed = threading.Event()

        def wait_enter() -> None:
            try:
                if sys.stdin and sys.stdin.readline():
                    pressed.set()
            except Exception:
                pass

        def open_login_page() -> None:
            if not self._login_form_visible():
                try:
                    page.goto(origin + "/login", wait_until="domcontentloaded", timeout=60_000)
                except Exception:
                    pass

        def connected() -> bool:
            return self._connected(start_url, course)

        open_login_page()
        self.log("\n>>> Vous n'êtes pas encore connecté.\n"
                 ">>> Connectez-vous à Podia dans la fenêtre du navigateur (e-mail, mot de passe, puis le code reçu\n"
                 ">>> par e-mail si demandé ; cochez « faire confiance à cet appareil »). Ne fermez pas cette fenêtre.\n"
                 ">>> Quand vous êtes connecté, revenez ici et appuyez sur Entrée.\n")
        threading.Thread(target=wait_enter, daemon=True).start()
        deadline = time.monotonic() + self.login_timeout
        quiet_polls = 0
        while time.monotonic() < deadline:
            try:
                page.wait_for_timeout(1500)
            except Exception as exc:
                raise NotLoggedIn("La fenêtre du navigateur a été fermée avant la connexion.") from exc
            try:
                if pressed.is_set():
                    if connected():
                        break
                    self.log(">>> La connexion n'est pas encore détectée : terminez-la dans la fenêtre du navigateur,"
                             " puis appuyez de nouveau sur Entrée.")
                    pressed.clear()
                    threading.Thread(target=wait_enter, daemon=True).start()
                    open_login_page()
                    continue
                # Détection automatique : plus de formulaire de connexion pendant quelques secondes.
                quiet_polls = 0 if self._login_form_visible() else quiet_polls + 1
                if quiet_polls >= 3:
                    if connected():
                        break
                    quiet_polls = 0
                    open_login_page()
            except (NotLoggedIn, PageNotFound):
                raise
            except Exception:
                continue
        else:
            raise NotLoggedIn("Connexion non détectée dans le délai imparti.")
        self.log(">>> Connexion réussie.\n")
        self._settle()

    # -- visite d'une leçon --
    def visit(self, url: str, capture_video: bool = True, _retry: bool = False) -> VisitResult:
        page = self.page
        self._media_requests.clear()
        self._all_urls.clear()
        page.goto(url, wait_until="domcontentloaded", timeout=90_000)
        self._settle()
        self._wait_stable()
        wanted = LESSON_URL_RE.search(urlparse(url).path)
        landed = LESSON_URL_RE.search(urlparse(page.url).path)
        moved = wanted and (not landed or landed.group("lesson") != wanted.group("lesson"))
        if self.logged_out():
            # Session absente ou expirée : on laisse l'utilisateur se (re)connecter, puis on recommence.
            if self.headless or _retry:
                raise NotLoggedIn("Vous n'êtes pas connecté à Podia (ou la session a expiré) : "
                                  "relancez la commande sans --headless pour vous connecter.")
            self._login(url, course_slug_from_url(url))
            return self.visit(url, capture_video, _retry=True)
        if moved:
            raise LessonUnavailable(f"leçon inaccessible (verrouillée ou déplacée ?) : redirigé vers {page.url}")
        info = page.evaluate(JS_CONTENT)
        slug = wanted.group("lesson_slug") if wanted else ""
        res = VisitResult(
            title=pick_lesson_title(info.get("titles", []), info.get("docTitle", ""), slug),
            markdown=info.get("markdown", ""), files=info.get("files", []),
            next_url=info.get("next", ""), radio_groups=int(info.get("radioGroups") or 0),
            checkboxes=int(info.get("checkboxes") or 0), quiz_words=bool(info.get("quizWords")),
            player_seen=bool(info.get("player")),
        )
        dom_urls = list(info.get("media", []))
        frame_urls = [f.url for f in page.frames]
        dom_urls += embed_urls_from_html(info.get("scanHtml") or "")
        dom_urls += [u for u in frame_urls if classify_url(u)]
        videos, confirmed = self._collect_sources(url, dom_urls)
        if capture_video and res.player_seen and not confirmed:
            # Aucun flux vérifié : on lance la lecture (muette) pour que le lecteur le demande.
            self._try_play()
            videos, confirmed = self._collect_sources(url, dom_urls + [f.url for f in page.frames if classify_url(f.url)])
        element_duration = None
        for frame in page.frames:
            d = self._frame_eval(frame, JS_PAUSE_AND_DURATION)
            if d:
                element_duration = max(element_duration or 0, float(d))
        if element_duration and len(videos) == 1 and not videos[0].duration_s:
            videos[0].duration_s = element_duration
        res.videos = videos
        try:
            res.html = page.content()
        except Exception:
            res.html = ""
        res.frame_urls, res.request_urls = frame_urls, list(self._all_urls)
        return res

    def _manifest_requests(self) -> list:
        return [r for r in self._media_requests if is_manifest(r.url)]

    def _wait_manifest(self, seconds: float) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self._manifest_requests():
                return True
            self.page.wait_for_timeout(400)
        return bool(self._manifest_requests())

    def _try_play(self) -> None:
        deadline = time.monotonic() + 25
        # 1) lecture (muette) des éléments <video> qui ont une source
        if sum(int(self._frame_eval(f, JS_PLAY) or 0) for f in self.page.frames) and self._wait_manifest(5):
            return
        # 2) bouton « Lecture » du lecteur, dans l'iframe Cloudflare ou ailleurs
        for frame in self.page.frames:
            if time.monotonic() > deadline:
                return
            if self._frame_eval(frame, JS_CLICK_PLAY_BUTTON) and self._wait_manifest(5):
                return
        # 3) clic au centre de l'iframe du lecteur
        for selector in ('iframe[src*="cloudflarestream"]', 'iframe[src*="videodelivery"]', "stream",
                         'iframe[src*="wistia"]', "video"):
            if time.monotonic() > deadline:
                return
            loc = self.page.locator(selector).first
            try:
                if loc.count():
                    loc.click(timeout=3000)
                    if self._wait_manifest(6):
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
                m = _media.CLOUDFLARE_RE.match(url)
                rest = (m.group("rest") or "") if m else ""
                if rest and not rest.startswith(("/iframe", "/watch", "/manifest/")):
                    continue                     # vignette, téléchargement… d'une autre vidéo
                manifest = url if is_manifest(url) else cloudflare_manifest_from_iframe(url, site)
                if not manifest:
                    continue
                url = manifest
            if kind == "fichier" and not re.search(r"\.(?:mp4|m4a|mp3|m4v|webm)(?:[?#]|$)", url, re.I):
                continue
            sources[key] = MediaSource(kind=kind, url=url, key=key, headers=replay_headers({}, url, page_url))
        # 3) Vérification des manifestes ; les playlists secondaires (variantes) d'un même master sont retirées.
        def looks_like_manifest(text: str) -> bool:
            return text.lstrip().startswith("#EXTM3U") or "<MPD" in text[:2000]

        texts: dict[str, str] = {}
        for key, src in list(sources.items()):
            if src.kind in ("hls", "dash", "cloudflare") and is_manifest(src.url):
                try:
                    text = self._fetch_text(src.url, src.headers)
                except Exception:
                    text = ""
                texts[key] = text if looks_like_manifest(text) else ""
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
                    src.duration_s = manifest_duration(src.url, lambda u, h=src.headers, t=text, s=src.url: (
                        t if u == s else self._fetch_text(u, h)))
                except Exception:
                    pass
        # Manifeste injoignable : on l'écarte s'il n'a pas été demandé par le lecteur lui-même.
        requested = {r.url for r in self._media_requests}
        for key in [k for k, t in texts.items() if not t and k in sources and sources[k].url not in requested]:
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
        # Tronquer le nom sans perdre l'extension (sinon le PDF ne s'ouvre plus d'un double clic).
        ext = Path(base).suffix.lower() if 1 < len(Path(base).suffix) <= 6 else ""
        if not ext and ctype == "application/pdf":
            ext = ".pdf"
        name = safe_filename(Path(base).stem if ext else base, self.attachment_name_max)
        path = dest_dir / f"{stem} - {name}{ext}"
        n = 2
        while path.exists() and path.read_bytes() != data:
            path = dest_dir / f"{stem} - {name} ({n}){ext}"
            n += 1
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

    def write_diagnostic(self, d: Path, name: str, res: VisitResult, screenshot: bool = True) -> None:
        """Page, requêtes réseau et (sur demande) capture d'écran d'une leçon, données personnelles masquées."""
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{name}.html").write_text(redact(res.html), encoding="utf-8")
        lines = ["# Cadres (iframes)", *res.frame_urls, "", "# Requêtes réseau pendant la visite", *res.request_urls]
        (d / f"{name}.reseau.txt").write_text(redact("\n".join(lines)), encoding="utf-8")
        if screenshot:
            try:
                self.page.screenshot(path=str(d / f"{name}.png"), full_page=True)
            except Exception:
                pass
