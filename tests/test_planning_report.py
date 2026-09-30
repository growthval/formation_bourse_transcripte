from datetime import date
from pathlib import Path

import pytest

from podia_formation.models import Attachment, Inventory, Lesson
from podia_formation.planning import (
    balanced_partition,
    build_sessions,
    parse_days,
    session_duration,
    write_ics,
    write_markdown,
)
from podia_formation.report import totals, write_csv, write_full_document, write_summary
from podia_formation.text import (
    count_words,
    format_duration,
    format_minutes,
    humanize_slug,
    module_label,
    safe_filename,
)


def lesson(i, module, kind, video_min=0.0, reading=0.0, questions=0, pages=0):
    l = Lesson(index=i, lesson_id=str(i), url=f"https://x/p/courses/c/{module}-m/{i}-l", title=f"Leçon {i}",
               module_index=module, module_id=str(module), module_title=f"Module {module}: Titre",
               lesson_index=i, kind=kind, visited=True)
    l.video_duration_s = video_min * 60 or None
    l.reading_min = reading
    l.quiz_questions = questions
    if pages:
        l.attachments = [Attachment(url="u", name="f.pdf", pages=pages)]
    return l


def course():
    inv = Inventory(course_url="https://x/p/courses/c", course_title="Investir en bourse")
    lessons = []
    for i in range(1, 41):
        kind = ["video", "article", "quiz", "video"][i % 4]
        lessons.append(lesson(i, 1 + i // 5, kind, video_min=18 if kind == "video" else 0,
                              reading=6 if kind == "article" else 0, questions=4 if kind == "quiz" else 0,
                              pages=2 if i == 7 else 0))
    inv.lessons = lessons
    return inv


def test_text_helpers():
    assert safe_filename('Fiche Pratique : "AAA", "BB-", "Junk"...') == "Fiche Pratique - AAA , BB- , Junk"
    assert safe_filename("CON") == "_CON"
    assert safe_filename("   ") == "sans titre"
    assert safe_filename("Quiz :") == "Quiz"
    assert len(safe_filename("x" * 300)) == 90
    assert count_words("L'investisseur prudent diversifie ; c'est-à-dire 3 actions.") == 6
    assert humanize_slug("341465-module-2-se-lancer") == "Module 2 se lancer"
    assert format_duration(3725) == "1 h 02 min" and format_duration(125) == "2 min 05 s"
    assert format_minutes(95.2) == "1 h 36" and format_minutes(42) == "42 min"
    assert module_label(3, "Les actions") == "Module 3 : Les actions"
    assert module_label(3, "Module 3: Les actions") == "Module 3: Les actions"


def test_study_minutes_rules():
    assert lesson(1, 1, "video", video_min=20).study_minutes(1.25) == 25
    assert lesson(1, 1, "quiz", questions=0).study_minutes() == 5        # quiz de taille inconnue
    assert lesson(1, 1, "quiz", questions=2).study_minutes() == 3        # minimum 3 min
    assert lesson(1, 1, "article", reading=4, pages=3).study_minutes() == 10


def test_balanced_partition_is_contiguous_and_complete():
    weights = [30, 5, 5, 50, 10, 10, 40, 20, 20, 20]
    groups = balanced_partition(weights, 4)
    assert len(groups) == 4
    assert [i for g in groups for i in g] == list(range(len(weights)))
    sums = [sum(weights[i] for i in g) for g in groups]
    assert max(sums) - min(sums) <= 30
    assert balanced_partition([], 3) == []
    assert balanced_partition([10, 10], 5) == [[0], [1]]


def test_build_sessions_at_least_target_on_average_and_respects_days():
    inv = course()
    total = sum(l.study_minutes() for l in inv.lessons)
    sessions = build_sessions(inv, date(2026, 10, 1), "20:00", 60, parse_days("tous"))
    assert len(sessions) == int(total // 60)
    assert sum(s.minutes for s in sessions) == pytest.approx(total, abs=0.5)
    assert sum(s.minutes for s in sessions) / len(sessions) >= 60
    assert [s.day for s in sessions[:3]] == ["2026-10-01", "2026-10-02", "2026-10-03"]
    covered = [l["index"] for s in sessions for l in s.lessons]
    assert covered == [l.index for l in inv.lessons]
    weekdays = build_sessions(inv, date(2026, 10, 2), "20:00", 60, parse_days("semaine"))
    assert all(date.fromisoformat(s.day).weekday() < 5 for s in weekdays)
    assert weekdays[1].day == "2026-10-05"     # vendredi 2 -> lundi 5
    later = build_sessions(inv, date(2026, 10, 1), from_index=21)
    assert later[0].lessons[0]["index"] == 21


def test_parse_days():
    assert parse_days("lun,mer,ven") == [0, 2, 4]
    assert parse_days("Lundi,Dimanche") == [0, 6]
    with pytest.raises(ValueError):
        parse_days("xyz")


def test_ics_is_valid_and_uses_paris_time(tmp_path: Path):
    inv = course()
    sessions = build_sessions(inv, date(2026, 10, 24), "20:00", 60)
    path = tmp_path / "planning.ics"
    write_ics(sessions, path, "Investir en bourse", "Europe/Paris", 60, inv.course_url)
    raw = path.read_bytes()
    assert raw.startswith(b"BEGIN:VCALENDAR\r\n") and raw.endswith(b"END:VCALENDAR\r\n")
    assert all(len(line) <= 75 for line in raw.split(b"\r\n"))
    text = raw.decode("utf-8")
    assert "DTSTART:20261024T180000Z" in text     # heure d'été (UTC+2)
    assert "DTSTART:20261025T190000Z" in text     # passage à l'heure d'hiver le 25 octobre (UTC+1)
    assert text.count("BEGIN:VEVENT") == len(sessions)
    assert session_duration(sessions[0], 60) >= 60


def test_reports(tmp_path: Path):
    inv = course()
    (tmp_path / "transcriptions").mkdir()
    (tmp_path / "transcriptions" / "M01-L01.txt").write_text("Bonjour et bienvenue.", encoding="utf-8")
    inv.lessons[0].transcript_files = ["transcriptions/M01-L01.txt"]
    t = write_summary(inv, tmp_path / "resume.md")
    assert t["video_s"] == 20 * 18 * 60
    summary = (tmp_path / "resume.md").read_text(encoding="utf-8")
    assert "**6 h 00 min**" in summary and "Module 1: Titre" in summary
    assert totals(inv)["types"]["quiz"] == 10
    write_csv(inv, tmp_path / "inventaire.csv")
    csv = (tmp_path / "inventaire.csv").read_bytes()
    assert csv.startswith("﻿".encode()) and b";18,0;" in csv
    write_full_document(inv, tmp_path, tmp_path / "complet.md")
    assert "Bonjour et bienvenue." in (tmp_path / "complet.md").read_text(encoding="utf-8")
    write_markdown(build_sessions(inv, date(2026, 10, 1)), tmp_path / "planning.md", "X", 60)
    assert "jeudi 1 octobre 2026" in (tmp_path / "planning.md").read_text(encoding="utf-8")


def test_inventory_roundtrip_masks_signed_tokens(tmp_path: Path):
    from podia_formation.models import MediaSource

    inv = course()
    token = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJhYmMifQ.c2lnbmF0dXJl"
    inv.lessons[0].videos = [MediaSource(kind="cloudflare", url=f"https://h/{token}/manifest/video.m3u8",
                                         key="cf:abc", headers={"Referer": f"https://h/{token}/iframe"})]
    path = tmp_path / "inventaire.json"
    inv.save(path)
    assert token not in path.read_text(encoding="utf-8")
    back = Inventory.load(path)
    assert back.lessons[0].videos[0].key == "cf:abc"
    assert back.lessons[6].attachments[0].pages == 2
    assert [l.lesson_id for l in back.lessons] == [l.lesson_id for l in inv.lessons]
