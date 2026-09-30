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


def test_prompt_keeps_lesson_context_at_the_end_and_hotwords_short():
    prompt, hotwords, dropped = build_prompt("Investir en bourse", "Module 3: Les actions", "Six tuyaux",
                                             ["Xavier Delmas"])
    assert prompt.endswith("Module 3: Les actions. Leçon : « Six tuyaux ».")   # fin conservée par Whisper
    assert "PEA" in prompt and "Module : Module" not in prompt
    assert hotwords.startswith("Six tuyaux. Xavier Delmas, Zonebourse")
    assert dropped == []
    many = [f"Terme{i}" for i in range(60)]
    _, hot, dropped = build_prompt("C", "M", "L", many, count_tokens=lambda t: len(t.split()))
    assert len(hot.split()) <= 50 and dropped and "Zonebourse" not in hot     # termes intégrés retirés d'abord


def test_read_terms_accepts_windows_encodings(tmp_path: Path):
    from podia_formation.transcribe import read_terms

    (tmp_path / "a.txt").write_bytes("\ufeffSociété Générale\r\n\r\nXavier Delmas\r\n".encode("utf-8"))
    (tmp_path / "b.txt").write_bytes("Société Générale\nCAC 40\n".encode("cp1252"))
    assert read_terms(tmp_path / "a.txt") == ["Société Générale", "Xavier Delmas"]
    assert read_terms(tmp_path / "b.txt") == ["Société Générale", "CAC 40"]


def test_transcribe_uses_quality_settings(tmp_path: Path):
    model = FakeModel([" Bonjour à tous.", " Bonjour à tous.", " Aujourd'hui, les actions."])
    segments, duration = transcribe_file(model, tmp_path / "a.m4a", "contexte", "Leçon. PEA", log=lambda m: None)
    assert model.kwargs["language"] == "fr"
    assert model.kwargs["hotwords"] == "Leçon. PEA"
    assert model.kwargs["hallucination_silence_threshold"] == 2.0 and model.kwargs["word_timestamps"]
    assert model.kwargs["beam_size"] == 5
    assert model.kwargs["vad_filter"] is True
    assert model.kwargs["initial_prompt"] == "contexte"
    assert [s.text for s in segments] == ["Bonjour à tous.", "Aujourd'hui, les actions."]   # répétition retirée
    assert duration == 15.0


def test_hallucination_and_loop_filter():
    segs = [Segment(0, 1, "Bonjour."), Segment(1, 2, "Bonjour !"), Segment(2, 3, "C'est ça."), Segment(3, 4, "Voilà."),
            Segment(4, 5, "C'est ça."), Segment(5, 6, "Voilà."), Segment(6, 7, "Sous-titrage Société Radio-Canada"),
            Segment(7, 8, "Texte répétitif", compression_ratio=3.1), Segment(8, 9, "Fin du cours.")]
    # La boucle A B A B est coupée dès sa 4e occurrence ; une simple reprise A B A peut être du vrai discours.
    assert [s.text for s in clean_segments(segs)] == ["Bonjour.", "C'est ça.", "Voilà.", "C'est ça.", "Fin du cours."]


def test_vtt_to_text(tmp_path: Path):
    from podia_formation.transcribe import vtt_to_text

    vtt = tmp_path / "s.fr.vtt"
    vtt.write_text("WEBVTT\n\n1\n00:00:00.000 --> 00:00:02.000\n<c>Bonjour</c> à tous\n\n"
                   "00:00:02.000 --> 00:00:04.000\nBonjour à tous\nParlons bourse.\n", encoding="utf-8")
    assert vtt_to_text(vtt) == "Bonjour à tous Parlons bourse."


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


def test_gpu_precision_order_for_small_cards():
    from podia_formation.transcribe import gpu_compute_types

    all_types = {"float32", "float16", "int8", "int8_float16", "int8_float32"}
    assert gpu_compute_types(all_types, 4096)[0] == "int8_float16"       # GTX 1650 (4 Go)
    assert gpu_compute_types(all_types, 12288)[0] == "float16"
    assert gpu_compute_types({"float32", "int8"}, None) == ["int8"]
