"""Digest Markdown des flux RSS/Atom des sources, matière première de la commande « /veille »."""

from __future__ import annotations

import gzip
import html
import re
import unicodedata
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.entities import name2codepoint
from pathlib import Path
from typing import Callable, Iterable

from .sources import CATEGORIES, Chaine, Source, read_chaines, read_sources, short_error

USER_AGENT = "Mozilla/5.0 (compatible; vigie/0.1; veille personnelle)"
# Certains sites refusent (403) tout ce qui ne ressemble pas à un navigateur : second essai avec cet en-tête.
BROWSER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0"
TIMEOUT = 20
RESUME_MAX = 280
_TAG_RE = re.compile(r"<[^>]+>")
_XML_ENTITIES = {"amp", "lt", "gt", "quot", "apos"}
_ENTITY_RE = re.compile(rb"&([A-Za-z][A-Za-z0-9]*);")
_BARE_AMP_RE = re.compile(rb"&(?!(?:[A-Za-z][A-Za-z0-9]*|#[0-9]+|#x[0-9A-Fa-f]+);)")
_CONTROL_RE = re.compile(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]")
YOUTUBE_RE = re.compile(r"https?://(?:www\.|m\.)?(?:youtube\.com/(?:watch\?v=|shorts/)|youtu\.be/)([\w-]{11})")
_DATE_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y%m%d",
                 "%a, %d %b %Y %H:%M:%S", "%d %b %Y %H:%M:%S", "%d %b %Y")


@dataclass
class Entree:
    source: str
    titre: str
    lien: str
    date: datetime | None = None
    resume: str = ""


# --- Récupération ----------------------------------------------------------------

def _open(url: str, agent: str, timeout: float) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": agent,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
        "Accept-Encoding": "gzip, identity",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
        if resp.headers.get("Content-Encoding", "").lower() == "gzip" or data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
    return data


def fetch(url: str, timeout: float = TIMEOUT, opener: Callable[[str, str, float], bytes] = _open) -> bytes:
    """Télécharge un flux (bibliothèque standard seulement : rien à installer).

    Un refus 403 est retenté une fois avec un en-tête de navigateur ; une protection anti-robot
    plus stricte (défi Cloudflare…) reste en erreur : la source se lit alors à la main.
    """
    try:
        return opener(url, USER_AGENT, timeout)
    except urllib.error.HTTPError as exc:
        if exc.code != 403:
            raise
        return opener(url, BROWSER_AGENT, timeout)


# --- Analyse d'un flux -----------------------------------------------------------

def _text(el: ET.Element, *names: str) -> str:
    for name in names:
        node = el.find(f"{{*}}{name}")
        if node is not None:
            txt = (node.text or "").strip()
            if txt:
                return txt
    return ""


def parse_date(value: str) -> datetime | None:
    """Date RFC 822 (RSS), ISO 8601 (Atom, Dublin Core) ou formats courants, toujours renvoyée avec fuseau."""
    value = " ".join((value or "").split())
    if not value:
        return None
    dt = None
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            # Fuseau en toutes lettres inconnu (« JST »), formats maison : on retire le fuseau et on essaie.
            bare = re.sub(r"\s+(?:[A-Z]{2,5}|[+-]\d{4}|GMT[+-]\d+)$", "", value)
            for fmt in _DATE_FORMATS:
                try:
                    dt = datetime.strptime(bare, fmt)
                    break
                except ValueError:
                    continue
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _entity(m: re.Match) -> bytes:
    """Entité HTML (« &nbsp; », « &rsquo; ») interdite en XML sans DTD : convertie en caractère."""
    name = m.group(1).decode("ascii")
    if name in _XML_ENTITIES:
        return m.group(0)
    code = name2codepoint.get(name)
    return chr(code).encode("utf-8") if code else b"&amp;" + m.group(1) + b";"


def sanitize_xml(data: bytes) -> bytes:
    """Rend lisible un flux « presque » XML : texte ou lignes vides avant l'en-tête, BOM, entités HTML."""
    head = data[:4096]
    starts = [i for i in (head.find(b"<?xml"), head.find(b"<rss"), head.find(b"<feed"), head.find(b"<rdf:RDF")) if i >= 0]
    if starts and min(starts) > 0:
        data = data[min(starts):]
    data = data.lstrip(b"\xef\xbb\xbf \t\r\n")
    data = _ENTITY_RE.sub(_entity, data)
    data = _BARE_AMP_RE.sub(b"&amp;", data)        # « AT&T » : esperluette nue, interdite en XML
    return _CONTROL_RE.sub(b"", data)


def clean(text: str, limit: int = RESUME_MAX) -> str:
    """Texte brut d'un résumé HTML (souvent échappé deux fois dans les flux), tronqué proprement."""
    text = html.unescape(_TAG_RE.sub(" ", html.unescape(text or "")))
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return text


def _atom_link(el: ET.Element) -> str:
    links = el.findall("{*}link")
    for l in links:
        if l.get("rel", "alternate") == "alternate" and l.get("href"):
            return l.get("href", "")
    return next((l.get("href", "") for l in links if l.get("href")), "")


def parse_feed(data: bytes, source: str) -> list[Entree]:
    """Entrées d'un flux RSS 2.0, RSS 1.0 (RDF) ou Atom. Lève ``xml.etree.ElementTree.ParseError`` si ce n'est pas du XML."""
    root = ET.fromstring(sanitize_xml(data))
    kind = root.tag.split("}")[-1].casefold()
    out: list[Entree] = []
    if kind == "feed":                                     # Atom
        for e in root.findall("{*}entry"):
            desc = e.find(".//{*}description")              # flux YouTube : media:group/media:description
            out.append(Entree(source, clean(_text(e, "title"), 300), _atom_link(e),
                              parse_date(_text(e, "published", "updated")),
                              clean(_text(e, "summary", "content") or (desc.text if desc is not None else ""))))
    else:                                                  # RSS 2.0 (channel/item) ou RSS 1.0 (item à la racine)
        for it in root.iterfind(".//{*}item"):      # iterfind : le joker {*} ne marche pas avec iter()
            lien = _text(it, "link")
            if not lien:
                guid = _text(it, "guid")
                lien = guid if guid.startswith("http") else _atom_link(it)
            out.append(Entree(source, clean(_text(it, "title"), 300), lien,
                              parse_date(_text(it, "pubDate", "date", "published", "updated")),
                              clean(_text(it, "description", "summary", "encoded"))))
    return [e for e in out if e.titre or e.lien]


# --- Filtres ----------------------------------------------------------------------

def fold(text: str) -> str:
    """Minuscules sans accents, pour comparer « géopolitique » et « Geopolitique »."""
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().casefold()


def matches(entry: Entree, keywords: Iterable[str]) -> bool:
    words = [fold(k).strip() for k in keywords if k.strip()]
    if not words:
        return True
    hay = fold(f"{entry.titre} {entry.resume}")
    return any(w in hay for w in words)


def cited_videos(entries: Iterable[Entree]) -> list[tuple[str, Entree]]:
    """Adresses YouTube citées dans les articles (source externe qui renvoie vers une vidéo)."""
    seen: set[str] = set()
    out: list[tuple[str, Entree]] = []
    for e in entries:
        for m in YOUTUBE_RE.finditer(f"{e.lien} {e.resume}"):
            vid = m.group(1)
            if vid not in seen:
                seen.add(vid)
                out.append((f"https://www.youtube.com/watch?v={vid}", e))
    return out


def parse_keywords(value: str) -> list[str]:
    return [k.strip() for k in (value or "").split(",") if k.strip()]


def select_sources(sources: list[Source], only: Iterable[str] = ()) -> list[Source]:
    names = [fold(n).strip() for n in only if n.strip()]
    chosen = [s for s in sources if s.active and s.rss]
    if names:
        chosen = [s for s in chosen if any(n in fold(s.nom) for n in names)]
    return chosen


# --- Rendu ------------------------------------------------------------------------

def _date_label(entry: Entree, now: datetime) -> str:
    if not entry.date:
        return "sans date"
    local = entry.date.astimezone()
    return f"{local:%d/%m %H:%M}" if (now - entry.date) < timedelta(days=300) else f"{local:%d/%m/%Y}"


def render_digest(sources: list[Source], results: dict[str, list[Entree]], failures: list[tuple[str, str]],
                  now: datetime, days: float, keywords: list[str], videos: dict[str, list[Entree]] | None = None,
                  cited: list[tuple[str, Entree]] | None = None) -> str:
    local = now.astimezone()
    total = sum(len(v) for v in results.values())
    nvid = sum(len(v) for v in (videos or {}).values())
    hours = int(round(days * 24))
    lines = [f"# Flux de presse du {local:%d/%m/%Y}", "",
             f"Généré le {local:%d/%m/%Y à %H:%M} · {hours} dernières heures · {len(results)} source(s) lue(s) · "
             f"{total} article(s)" + (f" · {len(videos or {})} chaîne(s), {nvid} vidéo(s)" if videos else "")
             + (f" · filtre : {', '.join(keywords)}" if keywords else ""), "",
             "> Ce fichier n'est qu'une liste de titres. La lecture, le recoupement et l'analyse se font avec la "
             "commande `/veille` dans Claude Code, qui ouvre les articles utiles.", ""]
    by_cat: dict[str, list[Source]] = {}
    for s in sources:
        if s.nom in results:
            by_cat.setdefault(s.categorie_libelle, []).append(s)
    order = [label for _, label in CATEGORIES]
    for label in sorted(by_cat, key=lambda l: (order.index(l) if l in order else len(order), l)):
        lines += [f"## {label}", ""]
        for s in by_cat[label]:
            where = ", ".join(x for x in (s.pays, s.langue) if x)
            lines.append(f"### {s.nom}" + (f" ({where})" if where else ""))
            entries = results[s.nom]
            if not entries:
                lines += ["", "_Rien de nouveau sur la période._", ""]
                continue
            lines.append("")
            for e in entries:
                title = e.titre or e.lien
                head = f"[{title}]({e.lien})" if e.lien else title
                lines.append(f"- {head} — {_date_label(e, now)}" + (f" : {e.resume}" if e.resume else ""))
            lines.append("")
    if videos:
        lines += ["## Nouvelles vidéos des chaînes suivies", "",
                  "Pour en analyser une : `vigie video \"<adresse>\"` puis `/analyse-video`.", ""]
        for name, entries in videos.items():
            if not entries:
                continue
            lines.append(f"### {name}")
            lines.append("")
            for e in entries:
                lines.append(f"- [{e.titre or e.lien}]({e.lien}) — {_date_label(e, now)}" + (f" : {e.resume}" if e.resume else ""))
            lines.append("")
    if cited:
        lines += ["## Vidéos citées dans les articles", ""]
        lines += [f"- <{url}> — citée par {e.source} : [{e.titre}]({e.lien})" for url, e in cited]
        lines.append("")
    if failures:
        lines += ["## Flux en erreur", "",
                  "Adresse à vérifier dans `connaissances/sources/medias.csv` (ou source à consulter à la main) :", ""]
        lines += [f"- {name} : {msg}" for name, msg in failures]
        lines.append("")
    return "\n".join(lines)


# --- Commande ----------------------------------------------------------------------

def _collect(name: str, url: str, since: datetime, words: list[str], limit: int, fetch_fn, failures, log) -> list[Entree] | None:
    try:
        entries = parse_feed(fetch_fn(url), name)
    except Exception as exc:
        failures.append((name, short_error(exc)))
        log(f"  ERREUR {name} : {short_error(exc)}")
        return None
    kept = [e for e in entries if (e.date is None or e.date >= since) and matches(e, words)]
    kept.sort(key=lambda e: (e.date is None, -(e.date.timestamp() if e.date else 0)))
    return kept[:limit]


def run_flux(sources_path: Path, out_dir: Path, days: float = 2, keywords: Iterable[str] = (),
             only: Iterable[str] = (), max_per_source: int = 20, fetch_fn: Callable[[str], bytes] = fetch,
             now: datetime | None = None, log: Callable[[str], None] = print,
             chaines_path: Path | None = None) -> Path:
    """Interroge les flux (presse, puis chaînes YouTube si ``chaines_path`` est donné) et écrit
    ``<sortie>/AAAA-MM-JJ-flux.md``. Un flux en erreur n'arrête pas les autres."""
    all_sources = read_sources(sources_path)
    sources = select_sources(all_sources, only)
    if not sources:
        raise RuntimeError(f"aucune source active avec un flux RSS dans « {sources_path} »"
                           + (" pour ce filtre --seulement" if list(only) else ""))
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    words = list(keywords)
    results: dict[str, list[Entree]] = {}
    failures: list[tuple[str, str]] = []
    for s in sources:
        kept = _collect(s.nom, s.rss, since, words, max_per_source, fetch_fn, failures, log)
        if kept is not None:
            results[s.nom] = kept
            log(f"  {s.nom} : {len(kept)} article(s)")
    videos: dict[str, list[Entree]] = {}
    if chaines_path and Path(chaines_path).is_file() and not list(only):
        chaines = [c for c in read_chaines(chaines_path) if c.active and c.flux]
        for c in chaines:
            kept = _collect(c.nom, c.flux, since, words, max_per_source, fetch_fn, failures, log)
            if kept is not None:
                videos[c.nom] = kept
                log(f"  {c.nom} : {len(kept)} vidéo(s)")
    cited = cited_videos(e for entries in results.values() for e in entries)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{now.astimezone():%Y-%m-%d}-flux.md"
    path.write_text(render_digest(sources, results, failures, now, days, words, videos, cited), encoding="utf-8")
    return path
