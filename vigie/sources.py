"""Registre des sources : fichiers CSV de ``connaissances/sources/`` (médias, chaînes, personnes)."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Callable

COLONNES_MEDIAS = ["nom", "pays", "langue", "categorie", "orientation", "rss", "site", "notes", "actif"]
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


def missing_columns(path: Path, required: list[str] | None = None) -> list[str]:
    lines = [l for l in _decode(Path(path).read_bytes()).splitlines() if l.strip() and not l.lstrip().startswith("#")]
    if not lines:
        return list(required or COLONNES_MEDIAS)
    header = {c.strip().strip('"').casefold() for c in lines[0].split(_delimiter(lines[0]))}
    return [c for c in (required or COLONNES_MEDIAS) if c not in header]


def check_feeds(sources: list[Source], fetch: Callable[[str], bytes], parse: Callable[[bytes, str], list],
                log: Callable[[str], None] = print) -> list[tuple[Source, bool, str]]:
    """Interroge chaque flux et résume ce qu'il renvoie (commande « sources --tester »)."""
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
        msg = f"{len(entries)} article(s){latest}" if entries else "flux lu mais vide (adresse à vérifier)"
        results.append((s, bool(entries), msg))
        log(f"  {'OK     ' if entries else 'VIDE   '} {s.nom} : {msg}")
    return results


def short_error(exc: BaseException) -> str:
    text = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
    return text[:160]
