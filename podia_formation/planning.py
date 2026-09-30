"""Découpage de la formation en séances quotidiennes et export agenda (.ics)."""

from __future__ import annotations

import json
import math
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from .models import DEFAULT_VIDEO_FACTOR, Inventory, Lesson
from .text import format_minutes, plural

JOURS = {"lun": 0, "mar": 1, "mer": 2, "jeu": 3, "ven": 4, "sam": 5, "dim": 6}
JOURS_NOMS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre"]


def parse_days(value: str) -> list[int]:
    """'tous', 'semaine', 'week-end', 'lun,mer,ven', 'lun-ven', 'lundi mardi'… -> jours (0 = lundi)."""
    value = (value or "tous").strip().lower()
    named = {"tous": range(7), "all": range(7), "7/7": range(7), "semaine": range(5), "5/7": range(5),
             "week-end": (5, 6), "weekend": (5, 6), "we": (5, 6)}
    if value in named:
        return list(named[value])
    days: set[int] = set()
    bad: list[str] = []
    for token in (t for t in re.split(r"[\s,;/]+", value) if t):
        if token in ("au", "et", "à"):
            continue
        if token in named:
            days.update(named[token])
            continue
        if "-" in token:
            a, b = token.split("-", 1)
            if a[:3] in JOURS and b[:3] in JOURS:
                i, j = JOURS[a[:3]], JOURS[b[:3]]
                days.update((i + k) % 7 for k in range((j - i) % 7 + 1))    # « ven-lun » passe par le week-end
                continue
        if token[:3] in JOURS:
            days.add(JOURS[token[:3]])
        else:
            bad.append(token)
    if bad or not days:
        raise ValueError(f"Jours non reconnus : {', '.join(bad) or value} "
                         "(exemples : tous, semaine, week-end, lun,mer,ven, lun-ven)")
    return sorted(days)


def french_date(d: date) -> str:
    return f"{JOURS_NOMS[d.weekday()]} {d.day} {MOIS[d.month - 1]} {d.year}"


def minimum_partition(weights: list[float], minimum: float) -> list[list[int]]:
    """Découpe une suite (ordre conservé) en blocs d'au moins `minimum`, le plus nombreux et le plus réguliers possible.

    Le nombre de blocs est le maximum réalisable (coupe gloutonne) ; la programmation dynamique
    répartit ensuite les leçons en minimisant la somme des carrés des blocs, sous la contrainte.
    """
    n = len(weights)
    if n == 0:
        return []
    prefix = [0.0]
    for w in weights:
        prefix.append(prefix[-1] + w)
    if prefix[-1] < minimum:
        return [list(range(n))]
    parts, acc = 0, 0.0
    for w in weights:
        acc += w
        if acc >= minimum - 1e-9:
            parts, acc = parts + 1, 0.0
    INF = float("inf")
    cost = [[INF] * (n + 1) for _ in range(parts + 1)]
    back = [[0] * (n + 1) for _ in range(parts + 1)]
    cost[0][0] = 0.0
    for k in range(1, parts + 1):
        for j in range(1, n + 1):
            best, arg = INF, 0
            for i in range(j):
                block = prefix[j] - prefix[i]
                if block < minimum - 1e-9 or cost[k - 1][i] == INF:
                    continue
                c = cost[k - 1][i] + block * block
                if c < best:
                    best, arg = c, i
            cost[k][j], back[k][j] = best, arg
    bounds, j = [], n
    for k in range(parts, 0, -1):
        i = back[k][j]
        bounds.append((i, j))
        j = i
    return [list(range(i, j)) for i, j in reversed(bounds)]


@dataclass
class Session:
    number: int
    day: str                 # AAAA-MM-JJ
    start: str               # HH:MM
    minutes: float
    lessons: list[dict] = field(default_factory=list)   # index, titre, module, type, minutes, url


def lesson_label(lesson: Lesson) -> str:
    kind = {"video": "vidéo", "article": "article", "quiz": "quiz", "fichier": "fiche"}.get(lesson.kind, lesson.kind)
    return f"M{lesson.module_index} · {lesson.title} ({kind})"


def lesson_weights(inv: Inventory, video_factor: float = DEFAULT_VIDEO_FACTOR,
                   from_index: int = 1) -> tuple[list[Lesson], list[float], list[bool]]:
    """Leçons à planifier, minutes d'étude de chacune, et si la durée est estimée."""
    lessons = [l for l in inv.lessons if l.index >= from_index and (l.kind != "vide" or l.stream_missed)]
    known = sorted(l.video_duration_s for l in inv.lessons if l.video_duration_s)
    typical = known[len(known) // 2] if known else 10 * 60      # médiane des vidéos mesurées
    weights, estimated = [], []
    for l in lessons:
        minutes = l.study_minutes(video_factor)
        guess = (l.kind == "video" or l.stream_missed) and not l.video_duration_s
        if guess:
            minutes += typical / 60 * video_factor
        weights.append(max(minutes, 1.0))
        estimated.append(guess)
    return lessons, weights, estimated


def count_sessions(inv: Inventory, target_minutes: float = 60, video_factor: float = DEFAULT_VIDEO_FACTOR,
                   from_index: int = 1) -> int:
    return len(minimum_partition(lesson_weights(inv, video_factor, from_index)[1], target_minutes))


def build_sessions(inv: Inventory, start_day: date, start_time: str = "20:00", target_minutes: float = 60,
                   days: list[int] | None = None, video_factor: float = DEFAULT_VIDEO_FACTOR,
                   from_index: int = 1) -> list[Session]:
    days = days if days is not None else list(range(7))
    lessons, weights, estimated = lesson_weights(inv, video_factor, from_index)
    # « 1 h par jour minimum » : chaque séance dure au moins la cible (sauf si tout tient en une seule).
    groups = minimum_partition(weights, target_minutes)
    sessions: list[Session] = []
    day = start_day
    for number, group in enumerate(groups, start=1):
        while day.weekday() not in days:
            day += timedelta(days=1)
        minutes = sum(weights[i] for i in group)
        sessions.append(Session(
            number=number, day=day.isoformat(), start=start_time, minutes=round(minutes, 1),
            lessons=[{
                "index": lessons[i].index, "titre": lessons[i].title, "module": lessons[i].module_title,
                "module_index": lessons[i].module_index, "type": lessons[i].kind,
                "minutes": round(weights[i], 1), "url": lessons[i].url, "estime": estimated[i],
                "libelle": lesson_label(lessons[i]) + (" (durée estimée)" if estimated[i] else ""),
            } for i in group],
        ))
        day += timedelta(days=1)
    return sessions


def session_duration(session: Session, target_minutes: float) -> int:
    """Durée du créneau d'agenda, arrondie au quart d'heure supérieur (au moins la cible)."""
    return int(max(target_minutes, math.ceil(session.minutes / 15) * 15))


def write_markdown(sessions: list[Session], path: Path, course_title: str, target_minutes: float) -> None:
    total = sum(s.minutes for s in sessions)
    lines = [f"# Planning : {course_title}", ""]
    if sessions:
        lines += [f"{plural(len(sessions), 'séance')}, du {french_date(date.fromisoformat(sessions[0].day))} "
                  f"au {french_date(date.fromisoformat(sessions[-1].day))}, "
                  f"pour {format_minutes(total)} d'étude estimée.", ""]
    for s in sessions:
        d = date.fromisoformat(s.day)
        lines.append(f"## Séance {s.number}/{len(sessions)} : {french_date(d)} à {s.start} "
                     f"({format_minutes(s.minutes)}, créneau {session_duration(s, target_minutes)} min)")
        lines.append("")
        for l in s.lessons:
            lines.append(f"- [{l['libelle']}]({l['url']}) : {format_minutes(l['minutes'])}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_json(sessions: list[Session], path: Path, params: dict | None = None) -> None:
    data = {"parametres": params or {}, "seances": [asdict(s) for s in sessions]}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_params(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("parametres", {}) if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _ics_escape(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n"))


def _fold(line: str) -> str:
    """Plie les lignes > 75 octets (RFC 5545)."""
    out, current = [], ""
    for ch in line:
        if len((current + ch).encode("utf-8")) > 74:
            out.append(current)
            current = " " + ch
        else:
            current += ch
    out.append(current)
    return "\r\n".join(out)


def write_ics(sessions: list[Session], path: Path, course_title: str, tz_name: str,
              target_minutes: float, course_url: str = "") -> None:
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(tz_name)
    now = datetime.now(timezone.utc)
    stamp, sequence = now.strftime("%Y%m%dT%H%M%SZ"), int(now.timestamp()) // 60 % 1_000_000
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//podia-formation//planning//FR", "CALSCALE:GREGORIAN"]
    for s in sessions:
        hh, mm = (int(x) for x in s.start.split(":"))
        start = datetime.combine(date.fromisoformat(s.day), time(hh, mm), tzinfo=tz)
        end = start + timedelta(minutes=session_duration(s, target_minutes))
        desc = [f"Séance {s.number}/{len(sessions)} ({format_minutes(s.minutes)} estimées)", ""]
        desc += [f"- {l['libelle']} : {format_minutes(l['minutes'])}" for l in s.lessons]
        if course_url:
            desc += ["", course_url]
        lines += [
            "BEGIN:VEVENT",
            # UID stable d'une génération à l'autre : réimporter met à jour les séances au lieu de les dupliquer.
            f"UID:{uuid.uuid5(uuid.NAMESPACE_URL, f'{course_url}#seance{s.number}')}@podia-formation",
            f"SEQUENCE:{sequence}",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{start.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
            f"DTEND:{end.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
            _fold("SUMMARY:" + _ics_escape(f"📈 {course_title} · séance {s.number}/{len(sessions)}")),
            _fold("DESCRIPTION:" + _ics_escape("\n".join(desc))),
            "BEGIN:VALARM", "ACTION:DISPLAY", "DESCRIPTION:Formation", "TRIGGER:-PT15M", "END:VALARM",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    path.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8", newline="")
