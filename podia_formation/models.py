"""Modèle de données de l'inventaire, sérialisé dans inventaire.json."""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .text import safe_filename

JWT_RE = re.compile(r"eyJ[\w-]+\.[\w-]+\.[\w-]+")

# Hypothèses d'estimation du temps d'étude (modifiables en ligne de commande).
DEFAULT_VIDEO_FACTOR = 1.25   # pauses et prise de notes pendant les vidéos
DEFAULT_QUIZ_MINUTES = 5.0    # quiz dont on ne connaît pas le nombre de questions
MINUTES_PER_QUESTION = 1.0
MINUTES_PER_PDF_PAGE = 2.0


@dataclass
class MediaSource:
    kind: str                      # cloudflare, hls, dash, wistia, vimeo, youtube, loom, fichier
    url: str
    key: str = ""                  # identifiant stable (déduplication)
    headers: dict = field(default_factory=dict)
    duration_s: float | None = None


@dataclass
class Attachment:
    url: str
    name: str
    path: str = ""
    pages: int = 0


@dataclass
class Lesson:
    index: int                     # rang global dans la formation (1..N)
    lesson_id: str
    url: str
    title: str
    module_index: int
    module_id: str
    module_title: str
    lesson_index: int              # rang dans le module
    kind: str = "inconnu"          # video, article, quiz, fichier, vide, inconnu
    visited: bool = False
    videos: list[MediaSource] = field(default_factory=list)
    video_duration_s: float | None = None
    word_count: int = 0
    reading_min: float = 0.0
    quiz_questions: int = 0
    attachments: list[Attachment] = field(default_factory=list)
    article_file: str = ""
    audio_files: list[str] = field(default_factory=list)
    subtitle_files: list[str] = field(default_factory=list)
    transcript_files: list[str] = field(default_factory=list)
    stream_missed: bool = False    # lecteur vu mais flux non capté : à retenter
    drm: bool = False              # vidéo protégée : ne pas retenter
    error: str = ""

    @property
    def stem(self) -> str:
        return f"M{self.module_index:02d}-L{self.lesson_index:02d} - {safe_filename(self.title, 80)}"

    def quiz_minutes(self) -> float:
        if self.kind != "quiz":
            return 0.0
        if self.quiz_questions:
            return max(3.0, self.quiz_questions * MINUTES_PER_QUESTION)
        return DEFAULT_QUIZ_MINUTES

    def study_minutes(self, video_factor: float = DEFAULT_VIDEO_FACTOR) -> float:
        minutes = (self.video_duration_s or 0) / 60 * video_factor
        minutes += self.reading_min
        minutes += self.quiz_minutes()
        minutes += sum(a.pages for a in self.attachments) * MINUTES_PER_PDF_PAGE
        return minutes


@dataclass
class Inventory:
    course_url: str
    course_title: str = ""
    site_origin: str = ""
    progress: list[int] = field(default_factory=list)   # [terminés, total] lu sur Podia
    generated_at: str = ""
    lessons: list[Lesson] = field(default_factory=list)

    def save(self, path: Path) -> None:
        # Les liens vidéo signés expirent vite et ne servent qu'au lancement en cours : on les masque.
        text = JWT_RE.sub("eyJ-jeton-masque", json.dumps(asdict(self), ensure_ascii=False, indent=2))
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        for attempt in range(6):          # antivirus / OneDrive peuvent verrouiller le fichier un instant
            try:
                tmp.replace(path)
                return
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.5)

    @classmethod
    def load(cls, path: Path) -> "Inventory":
        data = json.loads(path.read_text(encoding="utf-8"))
        lessons = []
        for raw in data.pop("lessons", []):
            raw["videos"] = [MediaSource(**v) for v in raw.get("videos", [])]
            raw["attachments"] = [Attachment(**a) for a in raw.get("attachments", [])]
            lessons.append(Lesson(**raw))
        return cls(lessons=lessons, **data)

    def modules(self) -> list[tuple[int, str, list[Lesson]]]:
        grouped: dict[int, tuple[str, list[Lesson]]] = {}
        for lesson in self.lessons:
            grouped.setdefault(lesson.module_index, (lesson.module_title, []))[1].append(lesson)
        return [(idx, title, items) for idx, (title, items) in sorted(grouped.items())]
