"""Petits utilitaires texte : noms de fichiers, comptage de mots, durées."""

from __future__ import annotations

import math
import re
import unicodedata

# Vitesse de lecture d'un texte technique en français (mots par minute).
READING_WPM = 200

_WORD_RE = re.compile(r"[^\W_]+(?:[’'\-][^\W_]+)*", re.UNICODE)
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def count_words(text: str) -> int:
    return len(_WORD_RE.findall(text or ""))


def reading_minutes(words: int, wpm: int = READING_WPM) -> float:
    return round(words / wpm, 1) if words else 0.0


def safe_filename(name: str, max_len: int = 90) -> str:
    """Nom de fichier valide sous Windows, macOS et Linux (accents conservés)."""
    name = unicodedata.normalize("NFC", name or "")
    name = name.replace(":", " - ")
    name = re.sub(r'[<>"/\\|?*\x00-\x1f]', " ", name)
    name = re.sub(r"(?:\s*-\s*){2,}", " - ", name)
    name = re.sub(r"\s+", " ", name).strip(" -").rstrip(". ")
    if len(name) > max_len:
        name = name[:max_len].rstrip(". ")
    if not name:
        name = "sans titre"
    if name.split(".")[0].upper() in _WINDOWS_RESERVED:
        name = f"_{name}"
    return name


def humanize_slug(slug: str) -> str:
    """'341465-module-2-se-lancer' -> 'Module 2 se lancer'."""
    slug = re.sub(r"^\d+-", "", slug or "")
    words = [w for w in slug.split("-") if w]
    if not words:
        return ""
    text = " ".join(words)
    return text[0].upper() + text[1:]


def normalize_for_match(text: str) -> set[str]:
    """Mots significatifs sans accents, pour comparer un titre et un slug."""
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 1 and w != "module"}


def format_duration(seconds: float | None) -> str:
    """3725 -> '1 h 02 min' ; 125 -> '2 min 05 s'."""
    if seconds is None:
        return "?"
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h} h {m:02d} min"
    if m:
        return f"{m} min {s:02d} s"
    return f"{s} s"


def format_minutes(minutes: float) -> str:
    """95.4 -> '1 h 35' ; 42 -> '42 min'."""
    total = int(math.ceil(minutes - 1e-9))
    h, m = divmod(total, 60)
    if h:
        return f"{h} h {m:02d}"
    return f"{m} min"


def timestamp(seconds: float, srt: bool = False) -> str:
    ms = int(round(max(seconds, 0) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    if srt:
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


# Libellés d'interface à retirer du texte d'une leçon.
UI_LINES = {
    "continuer", "précédent", "precedent", "suivant", "terminer", "marquer comme terminé",
    "marquer comme terminée", "leçon terminée", "terminé", "terminée", "commencer",
    "complete", "completed", "mark as complete", "next", "previous", "continue",
}


def clean_lesson_text(text: str, title: str = "") -> str:
    lines = []
    title_norm = (title or "").strip().casefold()
    for raw in (text or "").replace("\r", "").split("\n"):
        line = raw.strip()
        if line.casefold() in UI_LINES:
            continue
        if title_norm and line.casefold() == title_norm and not lines:
            continue
        lines.append(line)
    out = "\n".join(lines)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def module_label(index: int, title: str) -> str:
    """'Module 2: Se lancer' reste tel quel ; 'Les actions' devient 'Module 3 : Les actions'."""
    if re.match(r"(?i)module\s*\d+", title or ""):
        return title
    return f"Module {index} : {title}" if title else f"Module {index}"


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'s' if n > 1 else ''}"
