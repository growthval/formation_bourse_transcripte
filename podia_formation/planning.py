"""Découpage de la formation en séances quotidiennes et export agenda (.ics)."""

from __future__ import annotations

import json
import math
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
    """'tous' ou 'lun,mar,mer' -> numéros de jours (0 = lundi)."""
    value = (value or "tous").strip().lower()
    if value in ("tous", "all", "7/7"):
        return list(range(7))
    if value in ("semaine", "5/7"):
        return list(range(5))
    days = sorted({JOURS[d.strip()[:3]] for d in value.split(",") if d.strip()[:3] in JOURS})
    if not days:
        raise ValueError(f"Jours non reconnus : {value!r} (exemple : lun,mar,mer,jeu,ven)")
    return days


def french_date(d: date) -> str:
    return f"{JOURS_NOMS[d.weekday()]} {d.day} {MOIS[d.month - 1]} {d.year}"


def balanced_partition(weights: list[float], parts: int) -> list[list[int]]:
    """Découpe une suite (ordre conservé) en `parts` blocs aussi égaux que possible.

    Programmation dynamique qui minimise la somme des écarts au carré à la moyenne.
    """
    n = len(weights)
    parts = max(1, min(parts, n))
    if n == 0:
        return []
    prefix = [0.0]
    for w in weights:
        prefix.append(prefix[-1] + w)
    target = prefix[-1] / parts
    INF = float("inf")
    cost = [[INF] * (n + 1) for _ in range(parts + 1)]
    back = [[0] * (n + 1) for _ in range(parts + 1)]
    cost[0][0] = 0.0
    for k in range(1, parts + 1):
        for j in range(k, n + 1):
            best, arg = INF, k - 1
            for i in range(k - 1, j):
                if cost[k - 1][i] == INF:
                    continue
                c = cost[k - 1][i] + (prefix[j] - prefix[i] - target) ** 2
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


def build_sessions(inv: Inventory, start_day: date, start_time: str = "20:00", target_minutes: float = 60,
                   days: list[int] | None = None, video_factor: float = DEFAULT_VIDEO_FACTOR,
                   from_index: int = 1) -> list[Session]:
    days = days if days is not None else list(range(7))
    lessons = [l for l in inv.lessons if l.index >= from_index and l.kind != "vide"]
    weights = [max(l.study_minutes(video_factor), 1.0) for l in lessons]
    total = sum(weights)
    # « au moins 1 h par jour » : on prend le nombre de séances qui donne une moyenne >= la cible.
    count = max(1, math.floor(total / target_minutes)) if total else 0
    groups = balanced_partition(weights, count)
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
                "minutes": round(weights[i], 1), "url": lessons[i].url, "libelle": lesson_label(lessons[i]),
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


def write_json(sessions: list[Session], path: Path) -> None:
    path.write_text(json.dumps([asdict(s) for s in sessions], ensure_ascii=False, indent=2), encoding="utf-8")


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
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
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
            f"UID:{uuid.uuid5(uuid.NAMESPACE_URL, course_url + s.day + str(s.number))}@podia-formation",
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
