"""Rapports lisibles : résumé des durées, tableau CSV et document complet."""

from __future__ import annotations

import csv
import re
from pathlib import Path

from .media import audio_duration
from .models import DEFAULT_VIDEO_FACTOR, Inventory
from .transcribe import vtt_to_text
from .text import format_duration, format_minutes, module_label, plural

KIND_LABELS = {"video": "Vidéo", "article": "Article", "quiz": "Quiz", "fichier": "Fiche / fichier",
               "vide": "Vide", "inconnu": "Non visitée"}
KIND_PLURALS = {"video": ("vidéo", "vidéos"), "article": ("article", "articles"), "quiz": ("quiz", "quiz"),
                "fichier": ("fiche", "fiches"), "vide": ("page vide", "pages vides"),
                "inconnu": ("non visitée", "non visitées")}


def kind_count(kind: str, n: int) -> str:
    one, many = KIND_PLURALS.get(kind, (kind, kind))
    return f"{n} {many if n > 1 else one}"


def totals(inv: Inventory, video_factor: float = DEFAULT_VIDEO_FACTOR) -> dict:
    lessons = inv.lessons
    video_s = sum(l.video_duration_s or 0 for l in lessons)
    missing = [l for l in lessons if (l.kind == "video" or l.stream_missed) and not l.video_duration_s]
    reading = sum(l.reading_min for l in lessons)
    quiz = sum(l.quiz_minutes() for l in lessons)
    pdf_pages = sum(a.pages for l in lessons for a in l.attachments)
    study = sum(l.study_minutes(video_factor) for l in lessons)
    counts: dict[str, int] = {}
    for l in lessons:
        counts[l.kind] = counts.get(l.kind, 0) + 1
    return {"video_s": video_s, "videos_sans_duree": len(missing), "lecture_min": reading, "quiz_min": quiz,
            "pages_pdf": pdf_pages, "etude_min": study, "types": counts, "lecons": len(lessons),
            "erreurs": sum(1 for l in lessons if l.error)}


def write_summary(inv: Inventory, path: Path, video_factor: float = DEFAULT_VIDEO_FACTOR,
                  daily_minutes: float = 60) -> dict:
    from .planning import count_sessions

    t = totals(inv, video_factor)
    sessions = count_sessions(inv, daily_minutes, video_factor) if t["etude_min"] else 0
    lines = [f"# {inv.course_title or 'Formation'} : inventaire", "",
             f"Source : {inv.course_url}  ", f"Généré le : {inv.generated_at}", ""]
    if inv.progress:
        lines += [f"Progression affichée par Podia : {inv.progress[0]} sur {inv.progress[1]} terminés.", ""]
    lines += ["## En bref", "",
              "| | |", "|---|---|",
              f"| Leçons | {t['lecons']} ({', '.join(kind_count(k, n) for k, n in sorted(t['types'].items()))}) |",
              f"| **Vidéo (durée réelle)** | **{format_duration(t['video_s'])}** |",
              f"| Lecture des articles (~200 mots/min) | {format_minutes(t['lecture_min'])} |",
              f"| Quiz (estimation) | {format_minutes(t['quiz_min'])} |",
              f"| Fiches PDF | {t['pages_pdf']} pages |",
              f"| **Temps d'étude total estimé** (vidéo × {video_factor:g} pour pauses et notes) | **{format_minutes(t['etude_min'])}** |",
              f"| À raison d'au moins {format_minutes(daily_minutes)} par jour | **{plural(sessions, 'séance')}** |",
              ""]
    if t["videos_sans_duree"]:
        lines += [f"> {t['videos_sans_duree']} vidéo(s) sans durée connue : le total vidéo est sous-estimé "
                  "(le planning leur attribue une durée estimée).", ""]
    if t["erreurs"]:
        lines += [f"> {t['erreurs']} leçon(s) en erreur (voir la colonne « erreur » de inventaire.csv).", ""]
    lines += ["## Par module", "", "| Module | Leçons | Vidéo | Lecture | Étude estimée |", "|---|---|---|---|---|"]
    for idx, title, items in inv.modules():
        v = sum(l.video_duration_s or 0 for l in items)
        r = sum(l.reading_min for l in items)
        s = sum(l.study_minutes(video_factor) for l in items)
        lines.append(f"| {module_label(idx, title)} | {len(items)} | {format_duration(v) if v else '-'} | "
                     f"{format_minutes(r) if r else '-'} | {format_minutes(s)} |")
    lines += ["", "## Détail", ""]
    for idx, title, items in inv.modules():
        lines += [f"### {module_label(idx, title)}", ""]
        for l in items:
            bits = [KIND_LABELS.get(l.kind, l.kind)]
            if l.video_duration_s:
                bits.append(format_duration(l.video_duration_s))
            if l.reading_min and l.kind != "video":
                bits.append(f"lecture {format_minutes(l.reading_min)}")
            if l.attachments:
                bits.append(f"{len(l.attachments)} fichier(s)")
            if l.error:
                bits.append(f"⚠️ {l.error}")
            lines.append(f"{l.lesson_index}. [{l.title}]({l.url}) : {' · '.join(bits)}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return t


def write_csv(inv: Inventory, path: Path, video_factor: float = DEFAULT_VIDEO_FACTOR) -> None:
    """CSV au format Excel français (séparateur « ; », virgule décimale, UTF-8 avec BOM)."""
    def num(x: float) -> str:
        return f"{x:.1f}".replace(".", ",")

    def txt(value: str) -> str:
        # Excel prendrait « -50 % : … » ou « =… » pour une formule.
        return "'" + value if value[:1] in ("=", "+", "-", "@") else value

    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["n°", "module", "titre module", "leçon", "titre", "type", "durée vidéo (min)",
                    "mots", "lecture (min)", "quiz (min)", "pages PDF", "étude estimée (min)",
                    "audio", "transcription", "url", "erreur"])
        for l in inv.lessons:
            w.writerow([l.index, l.module_index, txt(l.module_title), l.lesson_index, txt(l.title), l.kind,
                        num((l.video_duration_s or 0) / 60), l.word_count, num(l.reading_min),
                        num(l.quiz_minutes()), sum(a.pages for a in l.attachments),
                        num(l.study_minutes(video_factor)), " | ".join(l.audio_files),
                        " | ".join(l.transcript_files), l.url, txt(l.error)])


def write_full_document(inv: Inventory, root: Path, path: Path) -> None:
    """Toute la formation en un seul fichier : transcriptions et textes, dans l'ordre."""
    lines = [f"# {inv.course_title or 'Formation'}", "", f"Source : {inv.course_url}", ""]
    for idx, title, items in inv.modules():
        lines += [f"## {module_label(idx, title)}", ""]
        for l in items:
            lines += [f"### {l.lesson_index}. {l.title}", "", f"<{l.url}>", ""]
            if l.article_file:
                p = root / l.article_file
                if p.is_file():
                    body = p.read_text(encoding="utf-8").split("\n", 2)
                    text = body[2] if len(body) > 2 and body[0].startswith("# ") else "\n".join(body)
                    text = re.sub(r"\n*Source : \S+\s*$", "", text.strip())
                    # Les titres de l'article passent sous le niveau « ### leçon » du document.
                    text = re.sub(r"(?m)^(#{1,4}) ", lambda m: "#" * min(len(m.group(1)) + 3, 6) + " ", text)
                    lines += [text.strip(), ""]
            txts = [root / t for t in l.transcript_files if t.endswith(".txt") and (root / t).is_file()]
            for k, t in enumerate(txts, start=1):
                duration = l.video_duration_s
                if len(txts) > 1 and k - 1 < len(l.audio_files):
                    duration = audio_duration(root / l.audio_files[k - 1])
                label = f"Transcription de la vidéo {k}/{len(txts)}" if len(txts) > 1 else "Transcription de la vidéo"
                lines += [f"**{label} ({format_duration(duration)}) :**", "", t.read_text(encoding="utf-8").strip(), ""]
            if not txts and l.subtitle_files:
                # Pas encore de transcription Whisper : sous-titres fournis par la plateforme, s'il y en a.
                subs = sorted(l.subtitle_files, key=lambda f: (".fr" not in f, f))
                sub = root / subs[0]
                if sub.is_file():
                    lines += ["**Sous-titres fournis par la formation :**", "", vtt_to_text(sub), ""]
            elif l.kind == "video" and not txts:
                lines += ["_(transcription pas encore disponible)_", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
