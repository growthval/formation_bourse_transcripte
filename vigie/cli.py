"""Ligne de commande : python -m vigie <commande> ... (ou vigie.bat sous Windows)."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from . import RACINE, __version__

SOURCES_DEFAUT = RACINE / "connaissances" / "sources" / "medias.csv"
CHAINES_DEFAUT = RACINE / "connaissances" / "sources" / "youtube.csv"
VIDEOS_DEFAUT = RACINE / "veille" / "videos"
JOURNAL_DEFAUT = RACINE / "veille" / "journal"


def log(msg: str = "") -> None:
    print(msg, flush=True)


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(RACINE).as_posix()
    except ValueError:
        return str(path)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m vigie",
                                description="Outils de veille : vidéos YouTube, flux de presse, registre des sources.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="commande", required=True)

    sp = sub.add_parser("video", help="récupère la transcription d'une ou plusieurs vidéos et prépare leur fiche d'analyse")
    sp.add_argument("urls", nargs="+", help="adresse(s) YouTube (ou autre site lu par yt-dlp)")
    sp.add_argument("--sortie", type=Path, default=VIDEOS_DEFAUT, help="dossier des vidéos (défaut : veille/videos)")
    sp.add_argument("--whisper", action="store_true",
                    help="transcrire l'audio avec Whisper au lieu des sous-titres (plus fidèle, mais long : téléchargement + calcul)")
    sp.add_argument("--sans-transcription", action="store_true", help="récupérer seulement les informations et l'audio")
    sp.add_argument("--forcer", action="store_true", help="refaire ce qui est déjà fait")
    sp.add_argument("--modele", default="large-v3",
                    help="modèle Whisper : large-v3 (défaut), francais, large-v3-turbo (3 à 4× plus rapide), medium, small")
    sp.add_argument("--appareil", default="auto", choices=["auto", "cpu", "cuda"], help="calcul sur CPU ou GPU NVIDIA")
    sp.add_argument("--precision", default="", choices=["", "int8", "float32", "float16", "int8_float16"])
    sp.add_argument("--threads", type=int, default=0, help="cœurs processeur (défaut : cœurs physiques)")
    sp.add_argument("--beam", type=int, default=5, help="largeur de recherche Whisper (5 par défaut)")
    sp.add_argument("--vocabulaire", default=None, help="fichier texte de termes à reconnaître (un par ligne)")

    sp = sub.add_parser("chercher", help="cherche des vidéos YouTube par mots-clés (sans clé d'API)")
    sp.add_argument("mots", nargs="+", help="mots-clés de la recherche")
    sp.add_argument("--nombre", type=int, default=10, help="nombre de résultats (défaut : 10)")
    sp.add_argument("--sortie", type=Path, default=VIDEOS_DEFAUT / "recherches",
                    help="dossier où enregistrer la liste (défaut : veille/videos/recherches)")

    sp = sub.add_parser("chaines", help="complète l'identifiant des chaînes YouTube du registre (pour suivre leurs nouvelles vidéos)")
    sp.add_argument("--chaines", type=Path, default=CHAINES_DEFAUT, help="registre CSV des chaînes")
    sp.add_argument("--sans-ecriture", action="store_true", help="afficher sans modifier le fichier")

    sp = sub.add_parser("flux", help="digest Markdown des derniers articles des sources et des nouvelles vidéos des chaînes")
    sp.add_argument("--jours", type=float, default=2, help="période couverte en jours (défaut : 2)")
    sp.add_argument("--filtre", default="", help="mots-clés séparés par des virgules (dans le titre ou le résumé)")
    sp.add_argument("--seulement", default="", help="n'interroger que ces sources (noms séparés par des virgules)")
    sp.add_argument("--max", type=int, default=20, help="articles au plus par source (défaut : 20)")
    sp.add_argument("--sans-videos", action="store_true", help="ne pas interroger les chaînes YouTube")
    sp.add_argument("--sources", type=Path, default=SOURCES_DEFAUT, help="registre CSV des médias")
    sp.add_argument("--chaines", type=Path, default=CHAINES_DEFAUT, help="registre CSV des chaînes")
    sp.add_argument("--sortie", type=Path, default=JOURNAL_DEFAUT, help="dossier du digest (défaut : veille/journal)")

    sp = sub.add_parser("sources", help="vérifie le registre des sources et teste les flux RSS")
    sp.add_argument("--sources", type=Path, default=SOURCES_DEFAUT, help="registre CSV des médias")
    sp.add_argument("--chaines", type=Path, default=CHAINES_DEFAUT, help="registre CSV des chaînes")
    sp.add_argument("--tester", action="store_true", help="interroger chaque flux RSS actif (médias et chaînes)")
    return p


def _youtube_hint(url: str, first: str) -> None:
    if "youtu" in url.lower() and any(k in first for k in ("JS runtime", "n challenge", "Deno", "nsig", "jsi")):
        log("  YouTube demande un moteur JavaScript : installez Deno (winget install DenoLand.Deno), "
            "rouvrez l'invite de commandes, ou mettez yt-dlp à jour (.venv\\Scripts\\python -m pip install -U yt-dlp).")


def cmd_video(args) -> int:
    from podia_formation.transcribe import read_terms

    from .video import Transcripteur, run_video

    terms = read_terms(args.vocabulaire) if args.vocabulaire else []
    transcripteur = Transcripteur(args.modele, args.appareil, args.precision, args.threads, args.beam, log)
    failures = 0
    for url in args.urls:
        try:
            run_video(url, args.sortie, transcripteur, whisper=args.whisper,
                      sans_transcription=args.sans_transcription, forcer=args.forcer, user_terms=terms, log=log)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            failures += 1
            first = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
            log(f"  ERREUR : {first}")
            _youtube_hint(url, first)
    if failures:
        log(f"\n{failures} vidéo(s) en échec sur {len(args.urls)}.")
    return 1 if failures == len(args.urls) else 0


def cmd_chercher(args) -> int:
    from podia_formation.text import format_duration, safe_filename

    from .video import render_search, search_videos

    query = " ".join(args.mots)
    log(f"Recherche YouTube : {query}")
    results = search_videos(query, args.nombre)
    if not results:
        log("Aucun résultat.")
        return 1
    for r in results:
        log(f"  - {r['titre']} — {r['chaine'] or '?'} ({format_duration(r['duree_s'])}) : {r['url']}")
    now = datetime.now()
    args.sortie.mkdir(parents=True, exist_ok=True)
    path = args.sortie / f"{now:%Y-%m-%d} - {safe_filename(query, 60)}.md"
    path.write_text(render_search(query, results, now), encoding="utf-8")
    log(f"\nListe enregistrée : {rel(path)}")
    log("Pour analyser une vidéo : vigie video \"<adresse>\" puis, dans Claude Code, /analyse-video")
    return 0


def cmd_chaines(args) -> int:
    from .sources import read_chaines, rewrite_rows
    from .video import channel_id

    if not args.chaines.is_file():
        raise RuntimeError(f"registre des chaînes introuvable : {args.chaines}")
    chaines = read_chaines(args.chaines)
    found: dict[str, str] = {}
    for c in chaines:
        if not c.active or not c.chaine:
            continue
        if c.id_chaine:
            log(f"  déjà   {c.nom} : {c.id_chaine}")
            continue
        try:
            cid = channel_id(c.chaine)
        except Exception as exc:
            first = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
            log(f"  ERREUR {c.nom} : {first}")
            _youtube_hint(c.chaine, first)
            continue
        if cid:
            found[c.nom] = cid
            log(f"  trouvé {c.nom} : {cid}")
        else:
            log(f"  ?      {c.nom} : identifiant non trouvé (adresse de chaîne à vérifier : {c.chaine})")
    if found and not args.sans_ecriture:
        n = rewrite_rows(args.chaines, lambda row: row.update(id_chaine=found.get(row.get("nom", ""), row.get("id_chaine", ""))),
                         ensure_columns=["id_chaine"])
        log(f"\n{n} identifiant(s) écrit(s) dans {rel(args.chaines)}. Les nouvelles vidéos de ces chaînes "
            "apparaîtront dans « vigie flux ».")
    elif found:
        log(f"\n{len(found)} identifiant(s) trouvé(s), fichier non modifié (--sans-ecriture).")
    return 0


def cmd_flux(args) -> int:
    from .flux import parse_keywords, run_flux

    if not args.sources.is_file():
        raise RuntimeError(f"registre des sources introuvable : {args.sources}")
    log(f"Flux des {args.jours:g} dernier(s) jour(s) ({rel(args.sources)})…")
    path = run_flux(args.sources, args.sortie, days=args.jours, keywords=parse_keywords(args.filtre),
                    only=parse_keywords(args.seulement), max_per_source=args.max, log=log,
                    chaines_path=None if args.sans_videos else args.chaines)
    log(f"\nDigest écrit : {rel(path)}")
    log("Prochaine étape, dans Claude Code : /veille")
    return 0


def cmd_sources(args) -> int:
    from .flux import fetch, parse_feed
    from .sources import Source, check_feeds, malformed_rows, missing_columns, read_chaines, read_sources

    if not args.sources.is_file():
        raise RuntimeError(f"registre des sources introuvable : {args.sources}")
    missing = missing_columns(args.sources)
    if missing:
        log(f"ATTENTION : colonnes absentes de {rel(args.sources)} : {', '.join(missing)}")
    for problem in malformed_rows(args.sources):
        log(f"ATTENTION : {rel(args.sources)}, {problem}")
    sources = read_sources(args.sources)
    active = [s for s in sources if s.active]
    with_rss = [s for s in active if s.rss]
    log(f"{len(sources)} source(s), {len(active)} active(s), {len(with_rss)} avec flux RSS.")
    chaines = []
    if args.chaines.is_file():
        for problem in malformed_rows(args.chaines):
            log(f"ATTENTION : {rel(args.chaines)}, {problem}")
        chaines = [c for c in read_chaines(args.chaines) if c.active]
        with_id = [c for c in chaines if c.flux]
        log(f"{len(chaines)} chaîne(s) YouTube active(s), {len(with_id)} avec identifiant"
            + ("" if len(with_id) == len(chaines) else " (lancez « vigie chaines » pour compléter)") + ".")
    if not args.tester:
        log("Ajoutez --tester pour interroger chaque flux.")
        return 0
    feeds = active + [Source(nom=f"{c.nom} (chaîne)", rss=c.flux) for c in chaines if c.flux]
    results = check_feeds(feeds, fetch, parse_feed, log)
    bad = [(s, msg) for s, ok, msg in results if not ok]
    log(f"\n{len(results) - len(bad)} flux OK, {len(bad)} en erreur.")
    for s, msg in bad:
        log(f"  - {s.nom} : {msg}")
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    args = build_parser().parse_args(argv)
    try:
        return {"video": cmd_video, "chercher": cmd_chercher, "chaines": cmd_chaines, "flux": cmd_flux,
                "sources": cmd_sources}[args.commande](args)
    except KeyboardInterrupt:
        log("\nInterrompu. Relancez la même commande : ce qui est déjà fait est conservé.")
        return 130
    except (RuntimeError, ValueError, OSError) as exc:
        log(f"\nERREUR : {exc}")
        return 1
