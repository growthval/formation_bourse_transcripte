from pathlib import Path
from types import SimpleNamespace

from podia_formation.transcribe import (
    Segment,
    build_prompt,
    clean_segments,
    paragraphs,
    transcribe_file,
    write_outputs,
)


class FakeModel:
    """Imite faster_whisper.WhisperModel.transcribe (générateur + infos)."""

    def __init__(self, texts):
        self.texts = texts
        self.kwargs = None

    def transcribe(self, audio, **kwargs):
        self.kwargs = kwargs
        segs = (SimpleNamespace(start=i * 5.0, end=i * 5.0 + 4.5, text=t) for i, t in enumerate(self.texts))
        return segs, SimpleNamespace(duration=len(self.texts) * 5.0, language="fr")


def test_prompt_contains_lesson_context_and_vocabulary():
    prompt = build_prompt("Investir en bourse", "Module 3: Les actions", "Six tuyaux", "Xavier Delmas")
    assert "Module 3: Les actions" in prompt and "Six tuyaux" in prompt
    assert "PEA" in prompt and "Xavier Delmas" in prompt


def test_transcribe_uses_quality_settings(tmp_path: Path):
    model = FakeModel([" Bonjour à tous.", " Bonjour à tous.", " Aujourd'hui, les actions."])
    segments, duration = transcribe_file(model, tmp_path / "a.m4a", "contexte", log=lambda m: None)
    assert model.kwargs["language"] == "fr"
    assert model.kwargs["beam_size"] == 5
    assert model.kwargs["vad_filter"] is True
    assert model.kwargs["initial_prompt"] == "contexte"
    assert [s.text for s in segments] == ["Bonjour à tous.", "Aujourd'hui, les actions."]   # répétition retirée
    assert duration == 15.0


def test_paragraphs_split_on_pauses_after_sentence_end():
    segs = [Segment(0, 4, "Première phrase."), Segment(4.2, 8, "Suite du propos"),
            Segment(8.1, 10, "fin."), Segment(13, 15, "Nouveau paragraphe.")]
    paras = paragraphs(segs)
    assert [p for _, p in paras] == ["Première phrase. Suite du propos fin.", "Nouveau paragraphe."]
    assert paras[1][0] == 13


def test_outputs_keep_dotted_titles(tmp_path: Path):
    segs = clean_segments([Segment(0, 2, " Bonjour. "), Segment(2, 3, "   "), Segment(3.5, 65.25, "Au revoir.")])
    stem = tmp_path / "M02-L03 - Je teste mes connaissances sur... L'introduction"
    files = write_outputs(segs, stem, "Titre", "https://x", 65.25)
    assert [f.name for f in files] == [stem.name + ext for ext in (".txt", ".md", ".srt")]
    srt = files[2].read_text(encoding="utf-8")
    assert "00:00:03,500 --> 00:01:05,250" in srt
    md = files[1].read_text(encoding="utf-8")
    assert "**[00:00]** Bonjour." in md and "**[00:03]** Au revoir." in md   # pause de 1,5 s : nouveau paragraphe
