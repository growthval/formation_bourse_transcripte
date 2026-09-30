"""Ligne de commande : python -m podia_formation <commande> ..."""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from . import __version__
from .models import DEFAULT_VIDEO_FACTOR, Attachment, Inventory, Lesson
from .text import clean_lesson_text, count_words, format_duration, format_minutes, plural, reading_minutes

DEFAULT_OUT = Path("formation")


def log(msg: str = "") -> None:
    print(msg, flush=True)


def rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


# --- inventaire + audio -------------------------------------------------------

def merge_listing(existing: Inventory | None, fresh: list[Lesson]) -> list[Lesson]:
    """Garde les données déjà collectées pour les leçons connues (reprise après interruption)."""
    if not existing:
        return fresh
    known = {l.lesson_id: l for l in existing.lessons}
    merged = []
    for lesson in fresh:
        old = known.get(lesson.lesson_id)
        if old:
            for attr in ("index", "url", "module_index", "module_id", "module_title", "lesson_index"):
                setattr(old, attr, getattr(lesson, attr))
            if lesson.title and not old.visited:
                old.title = lesson.title
            merged.append(old)
        else:
            merged.append(lesson)
    # Leçons absentes de la barre latérale (découvertes via « Continuer ») : remises à leur place,
    # juste après la leçon qui les précédait lors du lancement précédent.
    fresh_ids = {l.lesson_id for l in fresh}
    prev = None
    for old in existing.lessons:
        if old.lesson_id not in fresh_ids:
            pos = next((k + 1 for k, l in enumerate(merged) if l.lesson_id == prev), 0 if prev is None else len(merged))
            merged.insert(pos, old)
        prev = old.lesson_id
    return merged


def audio_done(lesson: Lesson, root: Path) -> bool:
    return bool(lesson.audio_files) and all((root / f).is_file() for f in lesson.audio_files)


def crawl(args, want_audio: bool) -> Inventory:
    from .crawler import Crawler, build_lessons, classify_lesson, course_title, lesson_from_url, renumber
    root: Path = args.sortie
    root.mkdir(parents=True, exist_ok=True)
    inv_path = root / "inventaire.json"
    existing = Inventory.load(inv_path) if inv_path.is_file() else None

    with Crawler(browser=args.navigateur, headless=args.headless, profile=args.profil,
                 executable=args.chemin_navigateur, log=log) as cr:
        data = cr.open_course(args.url)
        fresh = build_lessons(data["items"], data["course"])
        if not fresh:
            cr.write_diagnostic(root / "diagnostic", "page-formation", cr.snapshot())
            raise SystemExit("Aucune leçon trouvée dans la page. Relancez avec --diagnostic et envoyez le dossier "
                             "« diagnostic » pour analyse.")
        inv = Inventory(course_url=args.url, course_title=course_title(data, data["course"]),
                        site_origin="{0.scheme}://{0.netloc}".format(urlparse(args.url)),
                        progress=list(data.get("progress") or []))
        inv.lessons = merge_listing(existing, fresh)
        renumber(inv.lessons)
        inv.generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
        log(f"{len(inv.lessons)} leçons trouvées dans {len(inv.modules())} modules.")
        if inv.progress:
            log(f"Podia indique : {inv.progress[0]} sur {inv.progress[1]} terminés.")
            if inv.progress[1] != len(inv.lessons):
                log(f"⚠️ Podia annonce {inv.progress[1]} éléments mais {len(inv.lessons)} ont été listés "
                    "(les leçons manquantes seront ajoutées si elles sont découvertes en chemin).")
        inv.save(inv_path)

        i = 0
        diag_budget, auto_diag = 3, 5
        while i < len(inv.lessons):
            lesson = inv.lessons[i]
            i += 1
            needs_visit = (args.forcer or not lesson.visited or lesson.stream_missed
                           or (want_audio and lesson.kind == "video" and not lesson.drm
                               and not audio_done(lesson, root)))
            if not needs_visit:
                continue
            log(f"[{lesson.index}/{len(inv.lessons)}] M{lesson.module_index} · {lesson.title}")
            try:
                prev_kind, prev_duration = lesson.kind, lesson.video_duration_s
                res = cr.visit(lesson.url)
                apply_visit(cr, lesson, res, root)
                lesson.kind = classify_lesson(lesson.title, lesson.word_count, len(lesson.videos),
                                              res.radio_groups, res.checkboxes, res.quiz_words,
                                              len(lesson.attachments))
                if lesson.kind == "quiz":
                    lesson.quiz_questions = res.radio_groups
                    lesson.reading_min = 0.0
                missed = lesson.kind != "video" and res.player_seen and not lesson.videos
                lesson.stream_missed = missed          # sera retentée au prochain lancement
                if missed:
                    lesson.error = "lecteur vidéo repéré mais flux non capté"
                    if prev_kind == "video":           # garder ce qu'on savait déjà de cette vidéo
                        lesson.kind, lesson.video_duration_s = "video", prev_duration
                # Diagnostic : demandé (3 premières leçons) ou automatique en cas d'échec (5 au plus).
                if (args.diagnostic and diag_budget > 0) or (missed and auto_diag > 0):
                    cr.write_diagnostic(root / "diagnostic", lesson.stem, res)
                    if missed and not args.diagnostic:
                        auto_diag -= 1
                    else:
                        diag_budget -= 1
                lesson.visited = True
                summary = [lesson.kind]
                if lesson.video_duration_s:
                    summary.append(format_duration(lesson.video_duration_s))
                if lesson.word_count and lesson.kind != "video":
                    summary.append(f"{lesson.word_count} mots")
                log("    → " + ", ".join(summary))
                # Leçon suivante non listée (module replié dans la barre latérale, par exemple).
                nxt = lesson_from_url(res.next_url) if res.next_url else None
                if nxt:     # titre du module de la leçon découverte (pas forcément celui de la leçon courante)
                    nxt.module_title = next((l.module_title for l in inv.lessons if l.module_id == nxt.module_id),
                                            nxt.module_title)
                if nxt and all(l.lesson_id != nxt.lesson_id for l in inv.lessons):
                    log(f"    + leçon découverte via « Continuer » : {nxt.url}")
                    inv.lessons.insert(i, nxt)
                    renumber(inv.lessons)
                if want_audio and lesson.kind == "video" and lesson.videos and (not lesson.drm or args.forcer):
                    try:
                        fetch_audio(lesson, root)
                    except Exception as exc:
                        # Lien signé expiré ou refusé : on recharge la leçon pour en obtenir un neuf.
                        log(f"    nouvel essai avec un lien vidéo frais ({exc})")
                        fresh_res = cr.visit(lesson.url)
                        if fresh_res.videos:
                            lesson.videos = fresh_res.videos
                        try:
                            fetch_audio(lesson, root)
                        except Exception as exc2:
                            lesson.error = f"audio : {exc2}"[:300]
                            log(f"    ⚠️ {lesson.error}")
                time.sleep(1.0)      # rythme de navigation raisonnable
            except KeyboardInterrupt:
                inv.save(inv_path)
                raise
            except Exception as exc:     # une leçon en échec ne bloque pas les autres
                lesson.error = f"{type(exc).__name__}: {exc}"[:300]
                log(f"    ⚠️ {lesson.error}")
            inv.save(inv_path)
    return inv


def apply_visit(cr, lesson: Lesson, res, root: Path) -> None:
    from .crawler import title_is_from_slug

    if res.title and (not lesson.title or title_is_from_slug(lesson)):
        lesson.title = res.title
    lesson.error = ""
    text = clean_lesson_text(res.markdown, lesson.title)
    first = text.split("\n", 1)[0].lstrip("# ").strip()
    if first.casefold() == lesson.title.casefold():
        text = text.split("\n", 1)[1].strip() if "\n" in text else ""
    lesson.word_count = count_words(text)
    lesson.reading_min = reading_minutes(lesson.word_count)
    if text:
        path = root / "textes" / f"{lesson.stem}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {lesson.title}\n\n{text}\n\nSource : {lesson.url}\n", encoding="utf-8")
        lesson.article_file = rel(path, root)
    lesson.videos = res.videos
    known = [v for v in res.videos if v.duration_s]
    lesson.video_duration_s = sum(v.duration_s for v in known) if known else None
    attachments: list[Attachment] = []
    seen = set()
    for f in res.files:
        if f["url"] in seen:
            continue
        seen.add(f["url"])
        try:
            att = cr.download_file(f["url"], root / "fichiers", lesson.stem, f.get("name", ""))
            if att:
                att.path = rel(Path(att.path), root)
                attachments.append(att)
        except Exception as exc:
            log(f"    ⚠️ fichier non téléchargé ({f['url']}) : {exc}")
    lesson.attachments = attachments


def fetch_audio(lesson: Lesson, root: Path) -> None:
    """Audio de chaque vidéo de la leçon ; lève une erreur si aucune partie n'a pu être récupérée."""
    from .media import DrmProtected, audio_duration, download_audio, with_ext

    files, subtitles, durations, errors = [], [], [], []
    drm = 0
    for n, source in enumerate(lesson.videos, start=1):
        suffix = f" (partie {n})" if len(lesson.videos) > 1 else ""
        dest = root / "audio" / f"{lesson.stem}{suffix}"
        existing = with_ext(dest, ".m4a")
        if existing.is_file() and existing.stat().st_size > 0 and rel(existing, root) in lesson.audio_files:
            files.append(rel(existing, root))       # partie déjà récupérée lors d'un essai précédent
            continue
        try:
            path, subs = download_audio(source, dest, root / "sous-titres" / f"{lesson.stem}{suffix}", log=log)
        except DrmProtected:
            drm += 1
            errors.append(f"partie {n} : vidéo protégée par DRM")
            continue
        except Exception as exc:
            errors.append(f"partie {n} : {exc}")
            continue
        files.append(rel(path, root))
        subtitles += [rel(p, root) for p in subs]
        d = audio_duration(path)
        if d:
            durations.append(d)
            if not source.duration_s:
                source.duration_s = d
        log(f"    ♪ audio : {path.name}" + (f" (+ {len(subs)} fichier(s) de sous-titres)" if subs else ""))
    lesson.audio_files = files
    if subtitles:
        lesson.subtitle_files = subtitles
    if durations and not lesson.video_duration_s:
        lesson.video_duration_s = sum(durations)
    lesson.drm = bool(drm) and drm == len(lesson.videos)
    if errors:
        lesson.error = "; ".join(errors)[:300]
        log(f"    ⚠️ {lesson.error}")
        if not lesson.drm and len(files) < len(lesson.videos) - drm:
            raise RuntimeError(lesson.error)


# --- sonde (vérification sur une leçon) ------------------------------------------

def cmd_sonde(args) -> None:
    from .crawler import Crawler, build_lessons, classify_lesson
    from .media import jwt_claims, list_formats, token_in

    root: Path = args.sortie
    with Crawler(browser=args.navigateur, headless=args.headless, profile=args.profil,
                 executable=args.chemin_navigateur, log=log) as cr:
        data = cr.open_course(args.url)
        lessons = build_lessons(data["items"], data["course"])
        log(f"Connexion OK. Barre latérale : {len(lessons)} leçons, "
            f"{len({l.module_id for l in lessons})} modules."
            + (f" Podia indique {data['progress'][1]} éléments." if data.get("progress") else ""))
        for l in lessons[:3]:
            log(f"   ex. M{l.module_index} « {l.module_title} » → {l.title}")
        res = cr.visit(args.url)
        cr.write_diagnostic(root / "diagnostic", "sonde", res)
        words = count_words(clean_lesson_text(res.markdown, res.title))
        kind = classify_lesson(res.title, words, len(res.videos), res.radio_groups, res.checkboxes,
                               res.quiz_words, len(res.files))
        log(f"\nLeçon : {res.title or '?'} → type {kind}, {words} mots, {len(res.files)} fichier(s)")
        if res.player_seen and not res.videos:
            log("⚠️ Un lecteur vidéo est présent mais aucun flux n'a été capté : envoyez le dossier diagnostic.")
        for v in res.videos:
            token = token_in(v.url)
            claims = jwt_claims(token) if token else {}
            shown = v.url.replace(token, "eyJ…") if token else v.url
            log(f"Vidéo ({v.kind}) : {shown}")
            log(f"   durée : {format_duration(v.duration_s)}")
            if claims.get("exp"):
                remaining = claims["exp"] - time.time()
                log(f"   lien signé valable encore {format_duration(max(remaining, 0))} (vidéo {claims.get('sub', '?')})")
            try:
                formats = list_formats(v)
                audio_only = [f for f in formats if f.get("vcodec") == "none"]
                log(f"   {len(formats)} format(s), dont {len(audio_only)} audio seul : "
                    + ", ".join(str(f["format_id"]) for f in formats[:12]))
                if any(f.get("has_drm") for f in formats):
                    log("   ⚠️ DRM détecté : l'audio ne pourra pas être récupéré.")
            except Exception as exc:
                log(f"   ⚠️ yt-dlp ne lit pas ce flux : {exc}")
        if res.videos and not args.sans_audio:
            probe = Lesson(index=1, lesson_id="sonde", url=args.url, title=res.title or "sonde",
                           module_index=0, module_id="", module_title="", lesson_index=0, videos=res.videos)
            fetch_audio(probe, root / "sonde")
            if probe.audio_files:
                log(f"\n✅ Audio récupéré : {root / 'sonde' / probe.audio_files[0]}")
        log(f"\nDiagnostic (jetons masqués) : {root / 'diagnostic'}")


# --- transcription --------------------------------------------------------------

def parse_indices(value: str | None) -> set[int] | None:
    """« 3,5,10-12 » -> {3, 5, 10, 11, 12}."""
    if not value:
        return None
    out: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        try:
            if "-" in part:
                a, b = (int(x) for x in part.split("-", 1))
                if b < a:
                    raise ValueError
                out.update(range(a, b + 1))
            elif part:
                out.add(int(part))
        except ValueError:
            raise ValueError(f"--lecons : « {part} » n'est pas un numéro ou une plage valide (ex. 2,5,10-12)") from None
    return out


def cmd_transcrire(args) -> None:
    from .transcribe import (build_prompt, is_transcribed, load_model, read_terms, token_counter,
                             transcribe_file, write_outputs)

    root: Path = args.sortie
    inv_path = root / "inventaire.json"
    if not inv_path.is_file():
        raise SystemExit(f"{inv_path} introuvable : lancez d'abord la commande « audio ».")
    inv = Inventory.load(inv_path)
    user_terms = read_terms(args.vocabulaire) if args.vocabulaire else []     # lu avant le long chargement du modèle
    only = parse_indices(args.lecons)

    def parts(l: Lesson):
        for k, audio_rel in enumerate(l.audio_files, start=1):
            suffix = f" (partie {k})" if len(l.audio_files) > 1 else ""
            yield root / audio_rel, root / "transcriptions" / f"{l.stem}{suffix}"

    todo = [l for l in inv.lessons if l.audio_files and (only is None or l.index in only)
            and (args.forcer or not all(a.is_file() and is_transcribed(d, a) for a, d in parts(l)))]
    if not any(l.audio_files for l in inv.lessons):
        log("Aucun audio téléchargé : lancez d'abord la commande « audio ».")
        return
    if not todo:
        log("Aucune leçon correspondant à --lecons." if only is not None and not any(
            l.index in only and l.audio_files for l in inv.lessons) else "Toutes les transcriptions sont déjà faites.")
        write_reports(inv, root, args)
        return
    total_audio = sum(l.video_duration_s or 0 for l in todo)
    model, device = load_model(args.modele, args.appareil, args.precision, args.threads, log, args.beam)
    count = token_counter(model)
    log(f"Modèle prêt sur {'GPU' if device == 'cuda' else 'processeur (CPU)'}. "
        f"{len(todo)} leçon(s), {format_duration(total_audio)} d'audio à transcrire.")
    failures = 0
    warned = False
    for n, lesson in enumerate(todo, start=1):
        log(f"[{n}/{len(todo)}] {lesson.stem}")
        prompt, hotwords, dropped = build_prompt(inv.course_title, lesson.module_title, lesson.title,
                                                 user_terms, count)
        if dropped and not warned:
            log(f"    (vocabulaire trop long : {len(dropped)} terme(s) non rappelé(s) à Whisper)")
            warned = True
        outputs: list[str] = []
        for audio, dest in parts(lesson):
            if not audio.is_file():
                log(f"    ⚠️ fichier audio absent : {rel(audio, root)}")
                continue
            if not args.forcer and is_transcribed(dest, audio):
                outputs += [rel(p, root) for p in (dest.with_name(dest.name + e) for e in (".txt", ".md", ".srt"))]
                log("    déjà transcrit")
                continue
            try:
                segments, duration = transcribe_file(model, audio, prompt, hotwords, log=log, beam_size=args.beam)
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                segments = None
                if device == "cuda" and "memory" in str(exc).lower():
                    log("    ⚠️ mémoire GPU insuffisante : passage sur le processeur.")
                    try:
                        model, device = load_model(args.modele, "cpu", "", args.threads, log)
                        segments, duration = transcribe_file(model, audio, prompt, hotwords, log=log,
                                                             beam_size=args.beam)
                    except Exception as exc2:
                        exc = exc2
                if segments is None:
                    failures += 1
                    lesson.error = f"transcription : {type(exc).__name__}: {exc}"[:300]
                    log(f"    ⚠️ {lesson.error} (leçon ignorée ; relancez après correction)")
                    continue
            files = write_outputs(segments, dest, lesson.title, lesson.url, duration)
            outputs += [rel(p, root) for p in files]
        if outputs:
            lesson.transcript_files = outputs
            if lesson.error.startswith("transcription") and len(outputs) == 3 * len(lesson.audio_files):
                lesson.error = ""
        inv.save(inv_path)
    write_reports(inv, root, args)
    if failures:
        log(f"⚠️ {failures} partie(s) non transcrite(s) : voir la colonne « erreur » de inventaire.csv.")
    log(f"Transcriptions dans « {root / 'transcriptions'} », document complet : {root / 'formation_complete.md'}")


# --- planning / rapports -------------------------------------------------------

PLANNING_DEFAULTS = {"debut": None, "heure": "20:00", "minutes": 60.0, "jours": "tous", "fuseau": "Europe/Paris",
                     "facteur_video": DEFAULT_VIDEO_FACTOR, "a_partir_de": 1}


def planning_params(args) -> tuple[dict, bool]:
    """Réglages du planning : ceux donnés en option, sinon ceux du planning précédent, sinon les défauts.

    Renvoie aussi True si au moins une option a été donnée explicitement.
    """
    from .planning import read_params

    saved = read_params(args.sortie / "planning.json")
    params, explicit = {}, False
    for key, default in PLANNING_DEFAULTS.items():
        value = getattr(args, key, None)
        explicit |= value is not None
        params[key] = value if value is not None else saved.get(key, default)
    return params, explicit


def write_reports(inv: Inventory, root: Path, args) -> dict:
    from .report import totals, write_csv, write_full_document, write_summary

    params, _ = planning_params(args)
    factor, minutes = params["facteur_video"], params["minutes"]
    t = totals(inv, factor)
    for name, write in (("resume.md", lambda p: write_summary(inv, p, factor, minutes)),
                        ("inventaire.csv", lambda p: write_csv(inv, p, factor)),
                        ("formation_complete.md", lambda p: write_full_document(inv, root, p))):
        try:
            write(root / name)
        except OSError as exc:
            log(f"⚠️ {name} non écrit ({exc}) : fermez-le s'il est ouvert (Excel…) puis relancez.")
    return t


def cmd_planning(args) -> None:
    from .planning import build_sessions, parse_days, write_ics, write_json, write_markdown

    root: Path = args.sortie
    inv_path = root / "inventaire.json"
    if not inv_path.is_file():
        raise SystemExit(f"{inv_path} introuvable : lancez d'abord la commande « inventaire ».")
    inv = Inventory.load(inv_path)
    params, _ = planning_params(args)
    start = date.fromisoformat(params["debut"]) if params["debut"] else date.today() + timedelta(days=1)
    params["debut"] = start.isoformat()
    sessions = build_sessions(inv, start, params["heure"], params["minutes"], parse_days(params["jours"]),
                              params["facteur_video"], params["a_partir_de"])
    if not sessions:
        log(f"Aucune leçon à planifier à partir de la n° {params['a_partir_de']} "
            f"(la formation en compte {len(inv.lessons)}).")
        return
    title = inv.course_title or "Formation"
    write_markdown(sessions, root / "planning.md", title, params["minutes"])
    write_json(sessions, root / "planning.json", params)
    write_ics(sessions, root / "planning.ics", title, params["fuseau"], params["minutes"], inv.course_url)
    estimated = sum(1 for s in sessions for l in s.lessons if l.get("estime"))
    log(f"Planning : {plural(len(sessions), 'séance')} du {sessions[0].day} au {sessions[-1].day}, "
        f"à {params['heure']} ({format_minutes(sum(s.minutes for s in sessions))} d'étude estimée).")
    if estimated:
        log(f"   ({plural(estimated, 'vidéo')} sans durée mesurée : durée estimée dans le planning.)")
    log(f"→ {root / 'planning.md'} et {root / 'planning.ics'} (à importer dans votre agenda).")


def print_totals(t: dict, root: Path) -> None:
    log("")
    log("=" * 60)
    log(f"Vidéo : {format_duration(t['video_s'])}"
        + (f" ({t['videos_sans_duree']} vidéo(s) sans durée)" if t["videos_sans_duree"] else ""))
    log(f"Lecture des articles : {format_minutes(t['lecture_min'])} · Quiz : {format_minutes(t['quiz_min'])}"
        f" · Fiches PDF : {t['pages_pdf']} pages")
    log(f"Temps d'étude total estimé : {format_minutes(t['etude_min'])}")
    log(f"Détail : {root / 'resume.md'}")
    log("=" * 60)


# --- arguments ------------------------------------------------------------------

def _arg_error(msg: str):
    raise argparse.ArgumentTypeError(msg)


def arg_date(value: str) -> str:
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    _arg_error(f"date invalide « {value} » (ex. 2026-10-01 ou 01/10/2026)")


def arg_time(value: str) -> str:
    import re

    m = re.fullmatch(r"\s*(\d{1,2})\s*(?:[:hH]\s*(\d{2})?)?\s*", value)
    if not m or int(m.group(1)) > 23 or int(m.group(2) or 0) > 59:
        _arg_error(f"heure invalide « {value} » (ex. 20:00 ou 20h30)")
    return f"{int(m.group(1)):02d}:{int(m.group(2) or 0):02d}"


def arg_minutes(value: str) -> float:
    try:
        v = float(value.replace(",", "."))
    except ValueError:
        v = 0
    if not 5 <= v <= 600:
        _arg_error(f"durée invalide « {value} » (entre 5 et 600 minutes)")
    return v


def arg_factor(value: str) -> float:
    try:
        v = float(value.replace(",", "."))
    except ValueError:
        v = 0
    if not 0.5 <= v <= 5:
        _arg_error(f"facteur invalide « {value} » (entre 0,5 et 5)")
    return v


def arg_positive_int(value: str) -> int:
    if not value.strip().isdigit() or int(value) < 1:
        _arg_error(f"nombre invalide « {value} »")
    return int(value)


def arg_days(value: str) -> str:
    from .planning import parse_days

    try:
        parse_days(value)
    except ValueError as exc:
        _arg_error(str(exc))
    return value


def arg_zone(value: str) -> str:
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(value)
    except Exception:
        _arg_error(f"fuseau horaire inconnu « {value} » (ex. Europe/Paris ; sous Windows : pip install tzdata)")
    return value


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m podia_formation",
        description="Inventaire, audio, transcription et planning d'une formation Podia à laquelle vous êtes inscrit.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="commande", required=True)

    def common(sp, url=True):
        if url:
            sp.add_argument("url", help="adresse de la formation ou d'une leçon (…/p/courses/…)")
        sp.add_argument("--sortie", type=Path, default=DEFAULT_OUT, help="dossier de sortie (défaut : ./formation)")
        sp.add_argument("--forcer", action="store_true", help="refaire même ce qui est déjà fait")

    def browser(sp):
        sp.add_argument("--navigateur", default="auto", choices=["auto", "chromium", "chrome", "msedge", "edge"],
                        help="navigateur à piloter (défaut : auto)")
        sp.add_argument("--headless", action="store_true", help="navigateur invisible (une fois connecté)")
        sp.add_argument("--profil", type=Path, default=None,
                        help="dossier du profil navigateur (défaut : ~/.podia_formation/navigateur)")
        sp.add_argument("--chemin-navigateur", default=None, help="exécutable Chromium/Chrome à utiliser")
        sp.add_argument("--diagnostic", action="store_true",
                        help="enregistre la page et les requêtes des 3 premières leçons visitées (dépannage)")

    def whisper(sp):
        sp.add_argument("--modele", default="large-v3",
                        help="large-v3 (défaut), francais (large-v3 affiné pour le français), "
                             "large-v3-turbo (3 à 4× plus rapide), medium, small, ou un dossier de modèle")
        sp.add_argument("--appareil", default="auto", choices=["auto", "cpu", "cuda"], help="calcul sur CPU ou GPU NVIDIA")
        sp.add_argument("--precision", default="", choices=["", "int8", "float32", "float16", "int8_float16"],
                        help="précision des calculs (défaut : int8 sur processeur ; float32 = un peu plus fidèle, 2× plus lent)")
        sp.add_argument("--threads", type=int, default=0, help="cœurs processeur à utiliser (défaut : tous les cœurs physiques)")
        sp.add_argument("--beam", type=int, default=5, help="largeur de recherche (5 par défaut ; plus = plus lent)")
        sp.add_argument("--vocabulaire", default=None, help="fichier texte de termes à reconnaître (un par ligne)")
        sp.add_argument("--lecons", default=None, help="seulement ces leçons (n° de l'inventaire), ex. « 2,5,10-12 »")

    def planning(sp):
        sp.add_argument("--debut", type=arg_date, default=None,
                        help="date de la première séance, AAAA-MM-JJ ou JJ/MM/AAAA (défaut : demain)")
        sp.add_argument("--heure", type=arg_time, default=None, help="heure de début des séances, ex. 20:00 ou 20h30 (défaut : 20:00)")
        sp.add_argument("--minutes", type=arg_minutes, default=None, help="durée minimale d'une séance en minutes (défaut : 60)")
        sp.add_argument("--jours", type=arg_days, default=None,
                        help="tous (défaut), semaine, week-end, lun,mer,ven, lun-ven…")
        sp.add_argument("--fuseau", type=arg_zone, default=None, help="fuseau horaire (défaut : Europe/Paris)")
        sp.add_argument("--facteur-video", type=arg_factor, default=None,
                        help="temps d'étude par minute de vidéo (défaut : 1.25 pour pauses et notes)")
        sp.add_argument("--a-partir-de", type=arg_positive_int, default=None,
                        help="n° de la première leçon à planifier (défaut : 1)")

    sp = sub.add_parser("sonde", help="vérifie sur UNE leçon que tout fonctionne (à lancer en premier)")
    common(sp); browser(sp)
    sp.add_argument("--sans-audio", action="store_true", help="ne pas télécharger l'audio de la leçon testée")
    sp = sub.add_parser("inventaire", help="liste les leçons, mesure les vidéos et les textes (sans rien télécharger)")
    common(sp); browser(sp); planning(sp)
    sp = sub.add_parser("audio", help="inventaire + téléchargement de l'audio des vidéos")
    common(sp); browser(sp); planning(sp)
    sp = sub.add_parser("transcrire", help="transcrit en texte les audios déjà téléchargés")
    common(sp, url=False); whisper(sp); planning(sp)
    sp = sub.add_parser("planning", help="génère le planning quotidien et le fichier agenda (.ics)")
    common(sp, url=False); planning(sp)
    sp = sub.add_parser("tout", help="inventaire + audio + transcription + planning")
    common(sp); browser(sp); whisper(sp); planning(sp)
    return p


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    args = build_parser().parse_args(argv)
    try:
        if args.commande in ("inventaire", "audio", "tout"):
            inv = crawl(args, want_audio=args.commande != "inventaire")
            t = write_reports(inv, args.sortie, args)
            print_totals(t, args.sortie)
            # Planning refait seulement s'il n'existe pas ou si des options de planning sont données :
            # un planning personnalisé (heure, jours…) n'est pas écrasé par une simple relance.
            _, explicit = planning_params(args)
            if explicit or not (args.sortie / "planning.json").is_file():
                try:
                    cmd_planning(args)       # avant la transcription : ne dépend que de l'inventaire
                except Exception as exc:
                    log(f"⚠️ Planning non généré : {exc}")
            if args.commande == "tout":
                cmd_transcrire(args)
        elif args.commande == "sonde":
            cmd_sonde(args)
        elif args.commande == "transcrire":
            cmd_transcrire(args)
        elif args.commande == "planning":
            cmd_planning(args)
    except KeyboardInterrupt:
        log("\nInterrompu. Relancez la même commande : le travail déjà fait est conservé.")
        return 130
    except (RuntimeError, ValueError, OSError) as exc:     # NotLoggedIn est une RuntimeError
        log(f"\n❌ {exc}")
        return 1
    except Exception as exc:
        first = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
        if type(exc).__module__.startswith("playwright"):
            log(f"\n❌ Podia injoignable ou trop lent : vérifiez la connexion Internet puis relancez. ({first})")
        else:
            log(f"\n❌ Erreur inattendue ({type(exc).__name__}) : {first}")
        return 1
    return 0
