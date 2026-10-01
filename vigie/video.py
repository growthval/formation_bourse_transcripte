"""Vidéos YouTube (ou tout site lu par yt-dlp) : informations, sous-titres ou audio + Whisper, fiche d'analyse,
recherche par mots-clés, identifiant des chaînes.

Réutilise l'outil de la formation (``podia_formation``) : téléchargement audio avec yt-dlp, transcription
faster-whisper, nettoyage et mise en forme des paragraphes. Chaque vidéo a son dossier dans
``veille/videos/<date> - <chaîne> - <titre>/`` : ``video.json``, ``transcription.(txt|md|srt)``, ``fiche.md``.
"""

from __future__ import annotations

import glob
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from podia_formation.media import download_audio, with_ext
from podia_formation.models import MediaSource
from podia_formation.text import format_duration, safe_filename
from podia_formation.transcribe import (HOTWORDS_MAX_TOKENS, PROMPT_MAX_TOKENS, Segment, _approx_tokens,
                                        output_paths, write_outputs)

from . import RACINE

CONTEXTE = ("Transcription d'une vidéo en français sur l'économie, la bourse, la géopolitique ou l'intelligence "
            "artificielle : actions, ETF, PEA, taux d'intérêt, inflation, banques centrales, Fed, BCE, Nvidia, "
            "OpenAI, Anthropic, DeepMind, Chine, États-Unis, Union européenne.")
TERMES = ["ETF", "PEA", "CAC 40", "S&P 500", "Nasdaq", "Fed", "BCE", "OpenAI", "Anthropic", "DeepMind",
          "Nvidia", "AGI", "LLM", "OTAN", "Taïwan", "Zonebourse", "Finary"]
DOSSIER_MAX = 110
# Piste audio d'origine d'abord : YouTube ajoute des doublages automatiques dans d'autres langues.
AUDIO_FORMAT = "ba[format_note*=original]/ba[language^=fr]/ba/b[height<=480]/wa*/w"
FICHE_MODELE = RACINE / "modeles" / "fiche-video.md"
FICHE_DEFAUT = """# {{titre}}

- **Chaîne** : {{chaine}}
- **Publiée le** : {{date}}
- **Adresse** : {{url}}
- **Durée** : {{duree}}
- **Transcription** : {{transcription}} ({{mode}})
- **Statut de la fiche** : à rédiger (commande `/analyse-video`)

## Thèse principale (une phrase)

## Arguments et preuves avancées

## Affirmations vérifiables (à recouper avec `/croiser`)

## Ce qui est omis, intérêts de l'auteur, registre

## Message réel derrière le message

## Ce que ça change pour le plan

## Sources
"""


@dataclass
class VideoMeta:
    id: str
    titre: str
    chaine: str
    url: str
    date: str = ""                      # AAAA-MM-JJ (date de publication)
    duree_s: float | None = None
    description: str = ""
    sous_titres: list[str] = field(default_factory=list)        # langues fournies par la chaîne
    sous_titres_auto: list[str] = field(default_factory=list)   # langues générées par YouTube
    chapitres: list[dict] = field(default_factory=list)
    site: str = "youtube"
    transcription: str = ""             # comment la transcription a été obtenue (vide : pas encore faite)
    recuperee_le: str = ""

    @classmethod
    def from_info(cls, info: dict, url: str = "") -> "VideoMeta":
        raw_date = str(info.get("upload_date") or info.get("release_date") or "")
        date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}" if re.fullmatch(r"\d{8}", raw_date) else ""
        if not date and info.get("timestamp"):
            date = datetime.fromtimestamp(int(info["timestamp"])).strftime("%Y-%m-%d")
        chapitres = [{"titre": c.get("title", ""), "debut_s": c.get("start_time")} for c in info.get("chapters") or []]
        return cls(
            id=str(info.get("id") or ""),
            titre=(info.get("title") or "Sans titre").strip(),
            chaine=(info.get("channel") or info.get("uploader") or info.get("uploader_id") or "Chaîne inconnue").strip(),
            url=info.get("webpage_url") or url,
            date=date,
            duree_s=float(info["duration"]) if info.get("duration") else None,
            description=(info.get("description") or "").strip(),
            sous_titres=sorted(info.get("subtitles") or {}),
            sous_titres_auto=sorted(info.get("automatic_captions") or {}),
            chapitres=chapitres,
            site=str(info.get("extractor_key") or "youtube").lower(),
        )

    @property
    def dossier(self) -> str:
        """« 2026-10-01 - Finary - Personne n'est prêt pour 2027 »."""
        return safe_filename(f"{self.date or 'sans-date'} - {self.chaine} - {self.titre}", DOSSIER_MAX)

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "VideoMeta":
        return cls(**json.loads(path.read_text(encoding="utf-8")))


# --- yt-dlp ----------------------------------------------------------------------

def fetch_info(url: str) -> dict:
    """Métadonnées de la vidéo sans la télécharger."""
    from yt_dlp import YoutubeDL

    opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "skip_download": True}
    with YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False) or {}


def first_french(langs: list[str]) -> str | None:
    """Piste française : l'originale (« fr-orig ») avant une traduction automatique (« fr », « fr-FR »)."""
    fr = [l for l in langs if l.casefold().startswith("fr")]
    for keep in (lambda l: l.casefold().endswith("-orig"), lambda l: l.casefold() == "fr", lambda l: True):
        found = next((l for l in fr if keep(l)), None)
        if found:
            return found
    return None


def choose_subtitles(meta: VideoMeta, automatiques: bool = True) -> tuple[str, bool] | None:
    """(langue, automatiques ?) des sous-titres à utiliser au lieu de Whisper, ou None.

    Ordre : sous-titres fournis par la chaîne (relus), puis sous-titres automatiques de YouTube (ceux du
    panneau « Transcription » du site : immédiats, sans téléchargement, mais sans ponctuation et avec des
    erreurs sur les noms et les chiffres), puis Whisper sur l'audio (``--whisper``).
    """
    manual = first_french(meta.sous_titres)
    if manual:
        return manual, False
    if automatiques:
        auto = first_french(meta.sous_titres_auto)
        if auto:
            return auto, True
    return None


# --- Recherche et chaînes -----------------------------------------------------------

def normalize_entry(e: dict) -> dict:
    vid = str(e.get("id") or "")
    url = e.get("webpage_url") or e.get("url") or ""
    if url and not url.startswith("http"):
        url = f"https://www.youtube.com/watch?v={url}"
    if not url and vid:
        url = f"https://www.youtube.com/watch?v={vid}"
    raw = str(e.get("upload_date") or "")
    date = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}" if re.fullmatch(r"\d{8}", raw) else ""
    return {"id": vid, "titre": (e.get("title") or "").strip(), "chaine": (e.get("channel") or e.get("uploader") or "").strip(),
            "url": url, "date": date, "duree_s": e.get("duration"), "vues": e.get("view_count")}


def search_videos(query: str, n: int = 10) -> list[dict]:
    """Résultats de la recherche YouTube (sans clé d'API : yt-dlp interroge le site)."""
    from yt_dlp import YoutubeDL

    opts = {"quiet": True, "no_warnings": True, "extract_flat": True}
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{n}:{query}", download=False) or {}
    return [normalize_entry(e) for e in info.get("entries") or [] if e]


def render_search(query: str, results: list[dict], when: datetime) -> str:
    lines = [f"# Recherche YouTube : {query}", "", f"Le {when:%d/%m/%Y à %H:%M} · {len(results)} résultat(s). "
             "Pour analyser une vidéo : `vigie video \"<adresse>\"` puis `/analyse-video`.", "",
             "| Titre | Chaîne | Date | Durée | Vues | Adresse |", "|---|---|---|---|---|---|"]
    for r in results:
        vues = f"{r['vues']:,}".replace(",", " ") if isinstance(r.get("vues"), int) else "?"
        lines.append(f"| {r['titre'].replace('|', '¦')} | {r['chaine'].replace('|', '¦')} | {r['date'] or '?'} | "
                     f"{format_duration(r['duree_s'])} | {vues} | <{r['url']}> |")
    return "\n".join(lines) + "\n"


def find_channel(name: str, n: int = 8) -> dict | None:
    """Chaîne dont le nom correspond à ``name``, retrouvée par la recherche YouTube (quand l'adresse manque ou est fausse).

    Renvoie {"id", "nom", "url", "exact"} ; ``exact`` vaut False si seule une partie du nom correspond (à vérifier).
    """
    from yt_dlp import YoutubeDL

    from .flux import fold

    opts = {"quiet": True, "no_warnings": True, "extract_flat": True}
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{n}:{name}", download=False) or {}
    target = fold(name).strip()
    best: tuple[int, dict] | None = None
    for e in info.get("entries") or []:
        if not e:
            continue
        chan = str(e.get("channel") or e.get("uploader") or "").strip()
        cid = str(e.get("channel_id") or "")
        if not cid.startswith("UC") or not chan:
            continue
        f = fold(chan).strip()
        score = 2 if f == target else (1 if (f in target or target in f) else 0)
        if score and (best is None or score > best[0]):
            best = (score, {"id": cid, "nom": chan, "url": e.get("channel_url") or f"https://www.youtube.com/channel/{cid}",
                            "exact": score == 2})
    return best[1] if best else None


def channel_id(url: str) -> str:
    """Identifiant « UC… » d'une chaîne (nécessaire pour son flux de nouvelles vidéos)."""
    from yt_dlp import YoutubeDL

    opts = {"quiet": True, "no_warnings": True, "extract_flat": True, "playlist_items": "1"}
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False) or {}
    for key in ("channel_id", "uploader_id", "id"):
        value = str(info.get(key) or "")
        if value.startswith("UC"):
            return value
    return ""


def download_subtitles(url: str, lang: str, auto: bool, dest_stem: Path) -> Path | None:
    from yt_dlp import YoutubeDL

    dest_stem.parent.mkdir(parents=True, exist_ok=True)
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "skip_download": True,
            "writesubtitles": not auto, "writeautomaticsub": auto, "subtitleslangs": [lang],
            "subtitlesformat": "vtt/best", "outtmpl": {"default": str(dest_stem).replace("%", "%%") + ".%(ext)s"}}
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True) or {}
    for sub in (info.get("requested_subtitles") or {}).values():
        path = Path(sub.get("filepath") or "")
        if path.is_file() and path.stat().st_size > 0:
            return path
    found = sorted(dest_stem.parent.glob(glob.escape(dest_stem.name) + ".*.vtt"))
    return found[0] if found else None


# --- Sous-titres WebVTT → segments -------------------------------------------------

_CUE_RE = re.compile(r"^(?P<a>(?:\d{1,2}:)?\d{2}:\d{2}\.\d{3})\s+-->\s+(?P<b>(?:\d{1,2}:)?\d{2}:\d{2}\.\d{3})")
_TAG_RE = re.compile(r"<[^>]+>")


def _seconds(ts: str) -> float:
    parts = ts.split(":")
    h, m, s = ([0] + parts)[-3:] if len(parts) < 3 else parts
    return int(h) * 3600 + int(m) * 60 + float(s)


def vtt_to_segments(path: Path) -> list[Segment]:
    """Segments horodatés d'un fichier WebVTT.

    Les sous-titres automatiques de YouTube répètent la ligne précédente dans chaque cue (effet de
    défilement) : une ligne identique à la dernière ligne gardée est ignorée.
    """
    segments: list[Segment] = []
    last_line = ""
    start = end = None
    lines: list[str] = []

    def flush() -> None:
        nonlocal start, end, lines
        if start is not None and lines:
            segments.append(Segment(start, end if end is not None else start, " ".join(lines)))
        start, end, lines = None, None, []

    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines() + [""]:
        line = raw.strip()
        m = _CUE_RE.match(line)
        if m:
            flush()
            start, end = _seconds(m.group("a")), _seconds(m.group("b"))
            continue
        if not raw.rstrip("\r"):          # seule une ligne vide termine un cue (YouTube met des lignes « espace »)
            flush()
            continue
        if not line:
            continue
        if start is None or line == "WEBVTT" or line.startswith(("NOTE", "STYLE", "Kind:", "Language:")):
            continue
        text = " ".join(_TAG_RE.sub("", line).replace("&nbsp;", " ").split())
        if text and text != last_line:
            lines.append(text)
            last_line = text
    return segments


# --- Whisper ----------------------------------------------------------------------

def build_video_prompt(meta: VideoMeta, user_terms: list[str] | None = None,
                       count_tokens: Callable[[str], int] = _approx_tokens) -> tuple[str, str]:
    """(initial_prompt, hotwords) : contexte général + chaîne et titre, dans le budget de jetons de Whisper."""
    tail = f"Chaîne « {meta.chaine} ». Vidéo : « {meta.titre} »."
    prompt = f"{CONTEXTE} {tail}"
    if count_tokens(prompt) > PROMPT_MAX_TOKENS:
        prompt = tail
    terms = list(dict.fromkeys([*(user_terms or []), *TERMES]))
    head = meta.titre if count_tokens(meta.titre) <= HOTWORDS_MAX_TOKENS // 2 else ""
    while terms and count_tokens(f"{head}. {', '.join(terms)}") > HOTWORDS_MAX_TOKENS:
        terms.pop()
    hotwords = ". ".join(p for p in (head, ", ".join(terms)) if p)
    return prompt, hotwords


class Transcripteur:
    """Charge le modèle Whisper une seule fois pour plusieurs vidéos."""

    def __init__(self, modele: str = "large-v3", appareil: str = "auto", precision: str = "", threads: int = 0,
                 beam: int = 5, log: Callable[[str], None] = print):
        self.modele, self.appareil, self.precision, self.threads, self.beam, self.log = (
            modele, appareil, precision, threads, beam, log)
        self._model = None
        self.device = ""

    def _load(self):
        from podia_formation.transcribe import load_model

        if self._model is None:
            self._model, self.device = load_model(self.modele, self.appareil, self.precision, self.threads,
                                                  self.log, self.beam)
            self.log(f"Modèle prêt sur {'GPU' if self.device == 'cuda' else 'processeur (CPU)'}.")
        return self._model

    def run(self, audio: Path, meta: VideoMeta, user_terms: list[str] | None = None) -> tuple[list[Segment], float | None]:
        from podia_formation.transcribe import token_counter, transcribe_file

        model = self._load()
        prompt, hotwords = build_video_prompt(meta, user_terms, token_counter(model))
        return transcribe_file(model, audio, prompt, hotwords, log=self.log, beam_size=self.beam)

    @property
    def label(self) -> str:
        return f"Whisper {self.modele}" + (f" ({'GPU' if self.device == 'cuda' else 'CPU'})" if self.device else "")


# --- Fiche et index -----------------------------------------------------------------

def render_template(text: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def write_fiche(dossier: Path, meta: VideoMeta, mode: str, template: Path = FICHE_MODELE) -> Path:
    """Fiche d'analyse pré-remplie (jamais écrasée si elle existe déjà : elle contient le travail d'analyse)."""
    fiche = dossier / "fiche.md"
    if fiche.is_file():
        return fiche
    text = template.read_text(encoding="utf-8") if template.is_file() else FICHE_DEFAUT
    fiche.write_text(render_template(text, {
        "titre": meta.titre, "chaine": meta.chaine, "date": meta.date or "inconnue", "url": meta.url,
        "duree": format_duration(meta.duree_s), "transcription": "transcription.md" if mode else "non faite",
        "mode": mode or "à lancer", "dossier": dossier.name,
    }), encoding="utf-8")
    return fiche


INDEX_HEADER = ["# Vidéos récupérées", "",
                "Une ligne par vidéo (mise à jour par `vigie video`). La fiche d'analyse se rédige avec "
                "`/analyse-video`, qui passe le statut à « analysée ».", "",
                "| Date | Chaîne | Titre | Dossier | Transcription | Statut |", "|---|---|---|---|---|---|"]


def update_index(root: Path, meta: VideoMeta, mode: str) -> Path:
    index = root / "index.md"
    lines = index.read_text(encoding="utf-8").splitlines() if index.is_file() else list(INDEX_HEADER)
    if not any(l.startswith("| Date |") for l in lines):
        lines = list(INDEX_HEADER) + [l for l in lines if l.startswith("| ") and not l.startswith("|---")]
    cell = lambda s: s.replace("|", "¦").strip()
    link = f"[{cell(meta.dossier)}](<{meta.dossier}/fiche.md>)"
    row = f"| {meta.date or '?'} | {cell(meta.chaine)} | {cell(meta.titre)} | {link} | {cell(mode) or 'non faite'} | récupérée |"
    key = f"(<{meta.dossier}/fiche.md>)"
    kept = []
    for l in lines:
        if key in l:
            if "| analysée |" in l:
                row = row.replace("| récupérée |", "| analysée |")
            continue
        kept.append(l)
    kept.append(row)
    index.write_text("\n".join(kept) + "\n", encoding="utf-8")
    return index


# --- Commande ---------------------------------------------------------------------

def run_video(url: str, out_root: Path, transcripteur: Transcripteur | None = None,
              whisper: bool = False, sans_transcription: bool = False, forcer: bool = False,
              user_terms: list[str] | None = None, log: Callable[[str], None] = print) -> Path:
    """Dossier de la vidéo, avec sa transcription (sous-titres ou Whisper) et sa fiche à rédiger."""
    log(f"Informations : {url}")
    meta = VideoMeta.from_info(fetch_info(url), url)
    dossier = out_root / meta.dossier
    dossier.mkdir(parents=True, exist_ok=True)
    meta_path = dossier / "video.json"
    if meta_path.is_file() and not forcer:
        previous = VideoMeta.load(meta_path)
        meta.transcription, meta.recuperee_le = previous.transcription, previous.recuperee_le
    meta.recuperee_le = meta.recuperee_le or datetime.now().strftime("%Y-%m-%d %H:%M")
    meta.save(meta_path)
    log(f"  {meta.chaine} — « {meta.titre} » ({meta.date or 'date inconnue'}, {format_duration(meta.duree_s)})")

    stem = dossier / "transcription"
    done = all(p.is_file() for p in output_paths(stem)) and meta.transcription
    if done and not forcer:
        log(f"  transcription déjà présente ({meta.transcription}) ; --forcer pour la refaire")
    else:
        mode = ""
        choice = None if whisper else choose_subtitles(meta)
        if choice:
            lang, auto = choice
            log(f"  sous-titres {'automatiques YouTube' if auto else 'fournis par la chaîne'} ({lang}) : récupération")
            try:
                vtt = download_subtitles(url, lang, auto, dossier / "sous-titres")
            except Exception as exc:
                vtt = None
                log(f"  sous-titres non récupérés ({str(exc).strip().splitlines()[0][:120]}) : passage par l'audio")
            segments = vtt_to_segments(vtt) if vtt else []
            if segments:
                write_outputs(segments, stem, meta.titre, meta.url, meta.duree_s)
                mode = (f"sous-titres automatiques YouTube ({lang}) : relire noms et chiffres" if auto
                        else f"sous-titres fournis par la chaîne ({lang})")
        if not mode:
            audio = with_ext(dossier / "audio", ".m4a")
            if not audio.is_file():        # --forcer refait la transcription, pas le téléchargement (supprimer le .m4a pour cela)
                log("  audio : téléchargement")
                source = MediaSource(kind=meta.site if meta.site in ("youtube", "vimeo") else "fichier",
                                     url=url, key=f"{meta.site}:{meta.id}", duration_s=meta.duree_s)
                audio, _ = download_audio(source, dossier / "audio", None, log=log, fmt=AUDIO_FORMAT)
            if sans_transcription:
                mode = ""
                log(f"  audio prêt : {audio.name} (transcription à lancer plus tard, sans --sans-transcription)")
            else:
                if transcripteur is None:
                    transcripteur = Transcripteur(log=log)
                log("  transcription Whisper (long : comptez 1 à 4 fois la durée de la vidéo sur CPU)")
                segments, duration = transcripteur.run(audio, meta, user_terms)
                write_outputs(segments, stem, meta.titre, meta.url, duration or meta.duree_s)
                mode = transcripteur.label
        meta.transcription = mode
        meta.save(meta_path)
    fiche = write_fiche(dossier, meta, meta.transcription)
    update_index(out_root, meta, meta.transcription)
    log(f"  dossier : {dossier}")
    log(f"  fiche à rédiger : {fiche.name} → dans Claude Code : /analyse-video \"{meta.dossier}\"")
    return dossier
