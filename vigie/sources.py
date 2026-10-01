"""Registre des sources : fichiers CSV de ``connaissances/sources/`` (médias, chaînes, personnes)."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

COLONNES_MEDIAS = ["nom", "pays", "langue", "categorie", "orientation", "rss", "site", "notes", "actif"]
COLONNES_CHAINES = ["nom", "pays", "langue", "theme", "type", "chaine", "id_chaine", "notes", "actif"]
FLUX_CHAINE = "https://www.youtube.com/feeds/videos.xml?channel_id={id}"
OUI = {"oui", "o", "yes", "y", "1", "true", "vrai", "x"}
CATEGORIES = [
    ("presse", "Presse généraliste"),
    ("economie", "Économie, finance et marchés"),
    ("institution", "Institutions, banques centrales, statistiques"),
    ("geopolitique", "Géopolitique et relations internationales"),
    ("droit", "Droit international"),
    ("ia", "Intelligence artificielle"),
    ("autre", "Autres"),
]


@dataclass
class Source:
    nom: str
    pays: str = ""
    langue: str = ""
    categorie: str = ""
    orientation: str = ""
    rss: str = ""
    site: str = ""
    notes: str = ""
    actif: str = "oui"

    @property
    def active(self) -> bool:
        value = self.actif.strip().casefold()
        return not value or value in OUI

    @property
    def categorie_libelle(self) -> str:
        key = self.categorie.strip().casefold() or "autre"
        return dict(CATEGORIES).get(key, self.categorie.strip() or "Autres")


@dataclass
class Chaine:
    nom: str
    pays: str = ""
    langue: str = ""
    theme: str = ""
    type: str = ""
    chaine: str = ""          # adresse de la chaîne
    id_chaine: str = ""       # identifiant « UC… », rempli par « vigie chaines »
    notes: str = ""
    actif: str = "oui"

    @property
    def active(self) -> bool:
        value = self.actif.strip().casefold()
        return not value or value in OUI

    @property
    def flux(self) -> str:
        """Flux Atom des dernières vidéos (fourni par YouTube, sans clé d'API)."""
        return FLUX_CHAINE.format(id=self.id_chaine.strip()) if self.id_chaine.strip() else ""


def _decode(raw: bytes) -> str:
    """UTF-8 (avec ou sans BOM, comme l'enregistre Excel), sinon ANSI Windows."""
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252")


def _delimiter(header: str) -> str:
    """Excel en français enregistre les CSV avec « ; » : on accepte « ; » et « , »."""
    return ";" if header.count(";") > header.count(",") else ","


def read_sources(path: Path) -> list[Source]:
    """Lit un registre CSV. Les lignes vides ou commençant par « # » sont ignorées, les colonnes inconnues aussi."""
    lines = [l for l in _decode(Path(path).read_bytes()).splitlines() if l.strip() and not l.lstrip().startswith("#")]
    if not lines:
        return []
    reader = csv.DictReader(io.StringIO("\n".join(lines)), delimiter=_delimiter(lines[0]))
    known = {f.name for f in fields(Source)}
    out: list[Source] = []
    for row in reader:
        clean = {(k or "").strip().casefold(): (v or "").strip() for k, v in row.items() if k}
        if not clean.get("nom"):
            continue
        out.append(Source(**{k: v for k, v in clean.items() if k in known}))
    return out


def malformed_rows(path: Path) -> list[str]:
    """Lignes qui n'ont pas le nombre de colonnes de l'en-tête (un « ; » dans une note décale tout)."""
    lines = _decode(Path(path).read_bytes()).splitlines()
    header = next((l for l in lines if l.strip() and not l.lstrip().startswith("#")), "")
    if not header:
        return []
    delim = _delimiter(header)
    expected = len(next(csv.reader([header], delimiter=delim)))
    out = []
    for n, line in enumerate(lines, start=1):
        if not line.strip() or line.lstrip().startswith("#") or line == header:
            continue
        count = len(next(csv.reader([line], delimiter=delim)))
        if count != expected:
            out.append(f"ligne {n} : {count} colonnes au lieu de {expected} (un « {delim} » en trop ou en moins ?) : {line[:60]}…")
    return out


def read_chaines(path: Path) -> list[Chaine]:
    known = {f.name for f in fields(Chaine)}
    out: list[Chaine] = []
    for row in read_rows(path)[1]:
        clean = {k.casefold(): v for k, v in row.items()}
        if clean.get("nom"):
            out.append(Chaine(**{k: v for k, v in clean.items() if k in known}))
    return out


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """(colonnes, lignes) d'un registre, clés telles qu'écrites dans l'en-tête, commentaires ignorés."""
    lines = [l for l in _decode(Path(path).read_bytes()).splitlines() if l.strip() and not l.lstrip().startswith("#")]
    if not lines:
        return [], []
    delim = _delimiter(lines[0])
    columns = [c.strip() for c in next(csv.reader([lines[0]], delimiter=delim))]
    rows = []
    for values in csv.reader(lines[1:], delimiter=delim):
        if not any(v.strip() for v in values):
            continue
        rows.append({c: (values[i].strip() if i < len(values) else "") for i, c in enumerate(columns)})
    return columns, rows


def rewrite_rows(path: Path, mutate: Callable[[dict[str, str]], None], ensure_columns: list[str] = ()) -> int:
    """Réécrit un registre ligne à ligne (commentaires et ordre conservés), en appliquant ``mutate`` à chaque ligne.

    Les colonnes de ``ensure_columns`` sont ajoutées si absentes. Renvoie le nombre de lignes modifiées.
    Écrit en UTF-8 avec BOM, ce qu'Excel lit sans casser les accents.
    """
    raw_lines = _decode(Path(path).read_bytes()).splitlines()
    header_idx = next((i for i, l in enumerate(raw_lines) if l.strip() and not l.lstrip().startswith("#")), None)
    if header_idx is None:
        return 0
    delim = _delimiter(raw_lines[header_idx])
    columns = [c.strip() for c in next(csv.reader([raw_lines[header_idx]], delimiter=delim))]
    added = [c for c in ensure_columns if c not in columns]
    columns += added
    out, changed = [], 0

    def fmt(values: list[str]) -> str:
        buf = io.StringIO()
        csv.writer(buf, delimiter=delim, lineterminator="").writerow(values)
        return buf.getvalue()

    for i, line in enumerate(raw_lines):
        if i == header_idx:
            out.append(fmt(columns))
            continue
        if not line.strip() or line.lstrip().startswith("#"):
            out.append(line)
            continue
        values = next(csv.reader([line], delimiter=delim))
        row = {c: (values[k].strip() if k < len(values) else "") for k, c in enumerate(columns)}
        before = dict(row)
        mutate(row)
        if row != before or added:
            out.append(fmt([row.get(c, "") for c in columns]))
            changed += row != before
        else:
            out.append(line)
    Path(path).write_text("\n".join(out) + "\n", encoding="utf-8-sig")
    return changed


def missing_columns(path: Path, required: list[str] | None = None) -> list[str]:
    lines = [l for l in _decode(Path(path).read_bytes()).splitlines() if l.strip() and not l.lstrip().startswith("#")]
    if not lines:
        return list(required or COLONNES_MEDIAS)
    header = {c.strip().strip('"').casefold() for c in lines[0].split(_delimiter(lines[0]))}
    return [c for c in (required or COLONNES_MEDIAS) if c not in header]


STALE_DAYS = 30


def check_feeds(sources: list[Source], fetch: Callable[[str], bytes], parse: Callable[[bytes, str], list],
                log: Callable[[str], None] = print, now: datetime | None = None) -> list[tuple[Source, bool, str]]:
    """Interroge chaque flux et résume ce qu'il renvoie (commande « sources --tester »).

    Un flux qui répond mais dont le dernier article a plus de 30 jours est signalé « FIGÉ » : il est
    probablement abandonné par le média et donnerait un faux « rien de nouveau ».
    """
    now = now or datetime.now(timezone.utc)
    results: list[tuple[Source, bool, str]] = []
    for s in sources:
        if not s.active:
            results.append((s, True, "désactivée (colonne « actif »)"))
            continue
        if not s.rss:
            results.append((s, True, "pas de flux RSS renseigné : source consultée à la main"))
            continue
        try:
            entries = parse(fetch(s.rss), s.nom)
        except Exception as exc:
            results.append((s, False, short_error(exc)))
            log(f"  ERREUR  {s.nom} : {short_error(exc)}")
            continue
        dated = [e.date for e in entries if e.date]
        latest = f", dernier article le {max(dated):%d/%m/%Y}" if dated else ", articles sans date"
        stale = bool(dated) and (now - max(dated)).days > STALE_DAYS
        if not entries:
            ok, label, msg = False, "VIDE   ", "flux lu mais vide (adresse à vérifier)"
        elif stale:
            ok, label, msg = False, "FIGÉ   ", f"{len(entries)} article(s){latest} : flux probablement abandonné, adresse à changer ou à vider"
        else:
            ok, label, msg = True, "OK     ", f"{len(entries)} article(s){latest}"
        results.append((s, ok, msg))
        log(f"  {label} {s.nom} : {msg}")
    return results


def short_error(exc: BaseException) -> str:
    text = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
    return text[:160]
