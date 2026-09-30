"""Transcription locale en français avec faster-whisper (Whisper d'OpenAI).

Réglages orientés qualité : modèle large-v3, langue forcée en français,
recherche en faisceau (beam search), filtre des silences (VAD) et un contexte
propre à chaque leçon (titre, module, vocabulaire boursier) qui aide Whisper à
écrire correctement les termes techniques et les noms propres.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from .text import format_duration, timestamp

DEFAULT_MODEL = "large-v3"

VOCABULAIRE = (
    "Zonebourse, bourse, actions, obligations, ETF, trackers, OPCVM, SICAV, PEA, PEA-PME, "
    "compte-titres, assurance-vie, PER, dividendes, rendement, capitalisation, CAC 40, SBF 120, "
    "S&P 500, Nasdaq, MSCI World, courtier, ordre à cours limité, PER (price earning ratio), "
    "BPA, EBITDA, free cash flow, bilan, compte de résultat, analyse fondamentale, analyse "
    "technique, moyenne mobile, RSI, support, résistance, volatilité, diversification, "
    "allocation d'actifs, intérêts composés, inflation, taux directeurs, BCE, Fed, notation AAA."
)


def build_prompt(course: str, module: str, lesson: str, extra_vocab: str = "") -> str:
    parts = [f"Formation « {course} »." if course else "",
             f"Module : {module}." if module else "",
             f"Leçon : {lesson}." if lesson else "",
             f"Vocabulaire : {VOCABULAIRE}",
             extra_vocab.strip()]
    return " ".join(p for p in parts if p)


@dataclass
class Segment:
    start: float
    end: float
    text: str


def pick_device(device: str = "auto") -> tuple[str, str]:
    """(appareil, précision) : GPU NVIDIA en float16 si présent, sinon CPU en int8."""
    if device == "auto":
        try:
            import ctranslate2
            device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        except Exception:
            device = "cpu"
    return device, ("float16" if device == "cuda" else "int8")


def load_model(name: str = DEFAULT_MODEL, device: str = "auto", compute_type: str = ""):
    from faster_whisper import WhisperModel

    device, default_ct = pick_device(device)
    return WhisperModel(name, device=device, compute_type=compute_type or default_ct), device


def clean_segments(segments: Iterable[Segment]) -> list[Segment]:
    """Retire les segments vides et les répétitions consécutives (hallucinations en boucle)."""
    out: list[Segment] = []
    for seg in segments:
        text = " ".join(seg.text.split())
        if not text:
            continue
        if len(out) >= 1 and text.casefold() == out[-1].text.casefold():
            continue
        out.append(Segment(seg.start, seg.end, text))
    return out


def paragraphs(segments: list[Segment], max_seconds: float = 75.0, pause: float = 1.5) -> list[tuple[float, str]]:
    """Regroupe les segments en paragraphes lisibles (pause marquée ou fin de phrase après ~1 min)."""
    paras: list[tuple[float, str]] = []
    current: list[Segment] = []
    for seg in segments:
        if current:
            gap = seg.start - current[-1].end
            long_enough = seg.start - current[0].start >= max_seconds
            ends_sentence = current[-1].text.rstrip().endswith((".", "!", "?", "…"))
            if gap >= pause and ends_sentence or long_enough and ends_sentence or gap >= 4:
                paras.append((current[0].start, " ".join(s.text for s in current)))
                current = []
        current.append(seg)
    if current:
        paras.append((current[0].start, " ".join(s.text for s in current)))
    return paras


def write_outputs(segments: list[Segment], dest_stem: Path, title: str, source_url: str,
                  duration: float | None) -> list[Path]:
    dest_stem.parent.mkdir(parents=True, exist_ok=True)
    txt, md, srt = (dest_stem.with_name(dest_stem.name + ext) for ext in (".txt", ".md", ".srt"))
    paras = paragraphs(segments)
    txt.write_text("\n\n".join(p for _, p in paras) + "\n", encoding="utf-8")
    md_lines = [f"# {title}", "", f"Source : {source_url}  ", f"Durée : {format_duration(duration)}", ""]
    md_lines += [f"**[{timestamp(start)}]** {p}\n" for start, p in paras]
    md.write_text("\n".join(md_lines), encoding="utf-8")
    srt_lines = []
    for i, seg in enumerate(segments, start=1):
        srt_lines += [str(i), f"{timestamp(seg.start, True)} --> {timestamp(seg.end, True)}", seg.text, ""]
    srt.write_text("\n".join(srt_lines), encoding="utf-8")
    return [txt, md, srt]


def transcribe_file(model, audio: Path, prompt: str, log: Callable[[str], None] = print,
                    beam_size: int = 5) -> tuple[list[Segment], float | None]:
    segments, info = model.transcribe(
        str(audio),
        language="fr",
        task="transcribe",
        beam_size=beam_size,
        best_of=5,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 700},
        condition_on_previous_text=True,
        initial_prompt=prompt,
    )
    total = getattr(info, "duration", None) or 0
    out: list[Segment] = []
    started = time.monotonic()
    last_report = 0.0
    for seg in segments:
        out.append(Segment(seg.start, seg.end, seg.text))
        now = time.monotonic()
        if total and now - last_report > 20:
            last_report = now
            log(f"      {seg.end / total:5.0%} ({format_duration(seg.end)} / {format_duration(total)}, "
                f"{format_duration(now - started)} écoulées)")
    return clean_segments(out), (total or None)
