"""Tests de la commande vidéo (yt-dlp et Whisper remplacés par des doublures)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

import vigie.video as video
from podia_formation.transcribe import Segment
from vigie.video import (Transcripteur, VideoMeta, build_video_prompt, choose_subtitles, render_template,
                         run_video, update_index, vtt_to_segments, write_fiche)

INFO = {"id": "abc123XYZ_-", "title": "Personne n'est prêt pour 2027 : IA & bourse", "channel": "Finary",
        "upload_date": "20260915", "duration": 1500, "description": "Une vidéo.", "webpage_url": "https://www.youtube.com/watch?v=abc123XYZ_-",
        "subtitles": {}, "automatic_captions": {"fr-orig": [], "en": []}, "extractor_key": "Youtube",
        "chapters": [{"title": "Intro", "start_time": 0}, {"title": "Scénarios", "start_time": 300}]}

AUTO_VTT = """WEBVTT
Kind: captions
Language: fr

00:00:01.360 --> 00:00:03.350 align:start position:0%
 
bonjour<00:00:01.760><c> à</c><00:00:01.920><c> tous</c>

00:00:03.350 --> 00:00:03.360 align:start position:0%
bonjour à tous
 

00:00:03.360 --> 00:00:05.430 align:start position:0%
bonjour à tous
aujourd'hui<00:00:03.840><c> on</c><00:00:04.000><c> parle</c><00:00:04.320><c> de</c><00:00:04.480><c> 2027</c>

00:00:05.430 --> 00:00:05.440 align:start position:0%
aujourd'hui on parle de 2027
 
"""

MANUAL_VTT = """WEBVTT

1
00:00:00.000 --> 00:00:02.500
Bonjour à tous.

2
00:01:02.500 --> 01:00:05.000
Aujourd'hui, on parle de <b>2027</b>.

NOTE fin
"""


def test_meta_from_info_and_folder_name():
    meta = VideoMeta.from_info(INFO)
    assert meta.date == "2026-09-15" and meta.duree_s == 1500 and meta.site == "youtube"
    assert meta.sous_titres == [] and meta.sous_titres_auto == ["en", "fr-orig"]
    assert meta.chapitres[1] == {"titre": "Scénarios", "debut_s": 300}
    assert meta.dossier == "2026-09-15 - Finary - Personne n'est prêt pour 2027 - IA & bourse"
    bare = VideoMeta.from_info({"id": "x", "title": "T"}, "https://u")
    assert bare.date == "" and bare.chaine == "Chaîne inconnue" and bare.url == "https://u"
    assert bare.dossier.startswith("sans-date - ")


def test_choose_subtitles_prefers_channel_subtitles_then_youtube_automatic_ones():
    from vigie.video import first_french

    meta = VideoMeta.from_info(INFO)
    assert choose_subtitles(meta) == ("fr-orig", True)              # par défaut : la transcription de YouTube
    assert choose_subtitles(meta, automatiques=False) is None
    meta.sous_titres = ["en", "fr-FR"]
    assert choose_subtitles(meta) == ("fr-FR", False)               # la chaîne a relu ses sous-titres
    assert first_french(["fr", "fr-orig", "en"]) == "fr-orig"       # piste d'origine avant la traduction automatique
    assert first_french(["fr-FR", "fr"]) == "fr" and first_french(["fr-CA"]) == "fr-CA" and first_french(["en"]) is None


def test_vtt_to_segments_dedupes_youtube_rolling_lines(tmp_path: Path):
    p = tmp_path / "auto.vtt"
    p.write_text(AUTO_VTT, encoding="utf-8")
    segs = vtt_to_segments(p)
    assert [s.text for s in segs] == ["bonjour à tous", "aujourd'hui on parle de 2027"]
    assert segs[0].start == pytest.approx(1.36) and segs[1].start == pytest.approx(3.36)
    p.write_text(MANUAL_VTT, encoding="utf-8")
    segs = vtt_to_segments(p)
    assert [s.text for s in segs] == ["Bonjour à tous.", "Aujourd'hui, on parle de 2027."]
    assert segs[1].start == 62.5 and segs[1].end == 3605.0


def test_build_video_prompt_respects_budgets():
    meta = VideoMeta.from_info(INFO)
    prompt, hot = build_video_prompt(meta, ["Xavier Delmas"])
    assert prompt.endswith("Chaîne « Finary ». Vidéo : « Personne n'est prêt pour 2027 : IA & bourse ».")
    assert hot.startswith("Personne n'est prêt pour 2027 : IA & bourse. Xavier Delmas, ETF")
    words = lambda t: len(t.split())
    prompt, hot = build_video_prompt(meta, [f"T{i}" for i in range(80)], count_tokens=words)
    assert words(hot) <= 50 and words(prompt) <= 150


def test_fiche_from_template_and_index(tmp_path: Path):
    meta = VideoMeta.from_info(INFO)
    template = tmp_path / "fiche-video.md"
    template.write_text("# {{titre}}\n{{chaine}} / {{date}} / {{duree}} / {{transcription}} / {{mode}} / {{dossier}}\n", encoding="utf-8")
    d = tmp_path / meta.dossier
    d.mkdir()
    fiche = write_fiche(d, meta, "Whisper large-v3", template)
    text = fiche.read_text(encoding="utf-8")
    assert "Finary / 2026-09-15 / 25 min 00 s / transcription.md / Whisper large-v3 /" in text and "{{" not in text
    fiche.write_text("analyse faite", encoding="utf-8")
    write_fiche(d, meta, "autre", template)                     # jamais écrasée
    assert fiche.read_text(encoding="utf-8") == "analyse faite"
    assert "{{" not in render_template(video.FICHE_DEFAUT, {k: "x" for k in ("titre", "chaine", "date", "url", "duree", "transcription", "mode")})

    index = update_index(tmp_path, meta, "Whisper large-v3")
    lines = index.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "# Vidéos récupérées" and lines[-1].startswith("| 2026-09-15 | Finary |")
    assert lines[-1].endswith("| Whisper large-v3 | récupérée |")
    # Mise à jour : une seule ligne par vidéo ; le statut « analysée » posé par /analyse-video est conservé.
    index.write_text(index.read_text(encoding="utf-8").replace("| récupérée |", "| analysée |"), encoding="utf-8")
    update_index(tmp_path, meta, "sous-titres fournis par la chaîne (fr)")
    rows = [l for l in index.read_text(encoding="utf-8").splitlines() if l.startswith("| 2026")]
    assert len(rows) == 1 and rows[0].endswith("| sous-titres fournis par la chaîne (fr) | analysée |")


class FakeTranscripteur:
    modele = "large-v3"
    device = "cpu"
    label = "Whisper large-v3 (CPU)"

    def __init__(self):
        self.calls = 0

    def run(self, audio, meta, terms=None):
        self.calls += 1
        assert audio.is_file()
        return [Segment(0.0, 2.0, "Bonjour."), Segment(2.5, 5.0, "On parle de 2027.")], 5.0


def test_run_video_with_channel_subtitles(tmp_path: Path, monkeypatch):
    info = dict(INFO, subtitles={"fr": [{"ext": "vtt"}]})
    monkeypatch.setattr(video, "fetch_info", lambda url: info)

    def fake_subs(url, lang, auto, dest_stem):
        assert (lang, auto) == ("fr", False)
        p = dest_stem.with_name(dest_stem.name + ".fr.vtt")
        p.write_text(MANUAL_VTT, encoding="utf-8")
        return p
    monkeypatch.setattr(video, "download_subtitles", fake_subs)
    monkeypatch.setattr(video, "download_audio", lambda *a, **k: pytest.fail("audio inutile avec des sous-titres"))
    logs: list[str] = []
    out = tmp_path / "videos"
    d = run_video("https://youtu.be/abc123XYZ_-", out, FakeTranscripteur(), log=logs.append)
    assert d == out / VideoMeta.from_info(info).dossier
    assert (d / "transcription.md").is_file() and (d / "transcription.srt").is_file() and (d / "fiche.md").is_file()
    md = (d / "transcription.md").read_text(encoding="utf-8")
    assert md.startswith("# Personne n'est prêt pour 2027 : IA & bourse") and "Bonjour à tous." in md
    meta = VideoMeta.load(d / "video.json")
    assert meta.transcription == "sous-titres fournis par la chaîne (fr)" and meta.recuperee_le
    assert "| récupérée |" in (out / "index.md").read_text(encoding="utf-8")
    # Relance : rien n'est refait.
    monkeypatch.setattr(video, "download_subtitles", lambda *a, **k: pytest.fail("déjà fait"))
    run_video("https://youtu.be/abc123XYZ_-", out, FakeTranscripteur(), log=logs.append)
    assert any("déjà présente" in l for l in logs)


def test_run_video_uses_youtube_transcript_by_default_and_whisper_on_request(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(video, "fetch_info", lambda url: INFO)              # pas de sous-titres de la chaîne, auto « fr-orig »

    def fake_subs(url, lang, auto, dest_stem):
        assert (lang, auto) == ("fr-orig", True)
        p = dest_stem.with_name(dest_stem.name + ".fr-orig.vtt")
        p.write_text(AUTO_VTT, encoding="utf-8")
        return p
    monkeypatch.setattr(video, "download_subtitles", fake_subs)
    monkeypatch.setattr(video, "download_audio", lambda *a, **k: pytest.fail("pas d'audio avec les sous-titres"))
    out = tmp_path / "videos"
    d = run_video(INFO["webpage_url"], out, FakeTranscripteur(), log=lambda _: None)
    assert "aujourd'hui on parle de 2027" in (d / "transcription.txt").read_text(encoding="utf-8")
    assert VideoMeta.load(d / "video.json").transcription.startswith("sous-titres automatiques YouTube (fr-orig)")
    # --whisper : on ignore les sous-titres, on télécharge l'audio d'origine et on transcrit
    calls = {}

    def fake_audio(source, dest_stem, subs_stem, log, fmt=None):
        calls["fmt"] = fmt
        p = dest_stem.with_name(dest_stem.name + ".m4a")
        p.write_bytes(b"audio")
        return p, []
    monkeypatch.setattr(video, "download_subtitles", lambda *a, **k: pytest.fail("--whisper ignore les sous-titres"))
    monkeypatch.setattr(video, "download_audio", fake_audio)
    t = FakeTranscripteur()
    run_video(INFO["webpage_url"], out, t, whisper=True, forcer=True, log=lambda _: None)
    assert t.calls == 1 and calls["fmt"] == video.AUDIO_FORMAT and "original" in calls["fmt"]
    assert VideoMeta.load(d / "video.json").transcription == "Whisper large-v3 (CPU)"


def test_run_video_falls_back_to_audio_and_whisper(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(video, "fetch_info", lambda url: dict(INFO, automatic_captions={}))
    monkeypatch.setattr(video, "download_subtitles", lambda *a, **k: pytest.fail("pas de sous-titres du tout"))

    def fake_audio(source, dest_stem, subs_stem, log, fmt=None):
        assert source.kind == "youtube" and source.duration_s == 1500
        p = dest_stem.with_name(dest_stem.name + ".m4a")
        p.write_bytes(b"audio")
        return p, []
    monkeypatch.setattr(video, "download_audio", fake_audio)
    out = tmp_path / "videos"
    t = FakeTranscripteur()
    # 1) audio seul
    d = run_video(INFO["webpage_url"], out, t, sans_transcription=True, log=lambda _: None)
    assert (d / "audio.m4a").is_file() and not (d / "transcription.md").exists() and t.calls == 0
    assert VideoMeta.load(d / "video.json").transcription == ""
    assert "| non faite | récupérée |" in (out / "index.md").read_text(encoding="utf-8")
    # 2) puis transcription Whisper, sans retélécharger l'audio
    monkeypatch.setattr(video, "download_audio", lambda *a, **k: pytest.fail("audio déjà là"))
    run_video(INFO["webpage_url"], out, t, log=lambda _: None)
    assert t.calls == 1 and "On parle de 2027." in (d / "transcription.txt").read_text(encoding="utf-8")
    assert VideoMeta.load(d / "video.json").transcription == "Whisper large-v3 (CPU)"
    # 3) sous-titres automatiques annoncés mais impossibles à récupérer : on repasse par l'audio + Whisper
    monkeypatch.setattr(video, "fetch_info", lambda url: INFO)
    monkeypatch.setattr(video, "download_subtitles", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("quota")))
    run_video(INFO["webpage_url"], out, t, forcer=True, log=lambda _: None)
    assert t.calls == 2


def test_cli_video_reports_failures(monkeypatch, capsys, tmp_path: Path):
    import vigie.cli as cli

    calls = []

    def fake_run(url, out, transcripteur, **kw):
        calls.append((url, kw["whisper"]))
        if "mauvaise" in url:
            raise RuntimeError("ERROR: n challenge solving failed: no JS runtime (Deno) found")
        return out
    monkeypatch.setattr("vigie.video.run_video", fake_run)
    code = cli.main(["video", "https://youtube.com/watch?v=ok", "https://youtube.com/watch?v=mauvaise",
                     "--whisper", "--sortie", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0 and calls == [("https://youtube.com/watch?v=ok", True), ("https://youtube.com/watch?v=mauvaise", True)]
    assert "1 vidéo(s) en échec sur 2" in out and "Deno" in out
    assert cli.main(["video", "https://youtube.com/watch?v=mauvaise", "--sortie", str(tmp_path)]) == 1
    assert isinstance(Transcripteur(log=lambda _: None).label, str)


class FakeYDL:
    """Imite yt_dlp.YoutubeDL pour la recherche et les chaînes."""
    answers: dict = {}
    opts_seen: list = []

    def __init__(self, opts):
        FakeYDL.opts_seen.append(opts)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=False, **kw):
        return FakeYDL.answers[url]


def test_search_videos_and_render(monkeypatch, tmp_path: Path):
    import yt_dlp

    from vigie.video import normalize_entry, render_search, search_videos

    FakeYDL.answers = {"ytsearch2:ia 2027 finary": {"entries": [
        {"id": "UUSUEcZg5Cw", "title": "Personne n'est prêt pour 2027", "channel": "Finary", "duration": 1500, "view_count": 123456,
         "url": "https://www.youtube.com/watch?v=UUSUEcZg5Cw"},
        {"id": "abc", "title": "Autre | vidéo", "uploader": "Chaîne", "upload_date": "20260930", "url": "abc"}, None]}}
    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)
    results = search_videos("ia 2027 finary", 2)
    assert [r["url"] for r in results] == ["https://www.youtube.com/watch?v=UUSUEcZg5Cw", "https://www.youtube.com/watch?v=abc"]
    assert results[1]["date"] == "2026-09-30" and results[0]["chaine"] == "Finary"
    assert FakeYDL.opts_seen[-1]["extract_flat"] is True
    md = render_search("ia 2027 finary", results, datetime(2026, 10, 1, 20, 0))
    assert "| Personne n'est prêt pour 2027 | Finary | ? | 25 min 00 s | 123 456 | <https://www.youtube.com/watch?v=UUSUEcZg5Cw> |" in md
    assert "Autre ¦ vidéo" in md
    assert normalize_entry({"id": "x"})["url"] == "https://www.youtube.com/watch?v=x"


def test_channel_id_and_cli_chaines(monkeypatch, tmp_path: Path, capsys):
    import yt_dlp

    import vigie.cli as cli
    from vigie.sources import read_chaines
    from vigie.video import channel_id

    FakeYDL.answers = {"https://www.youtube.com/@Finary": {"id": "UUxyz", "channel_id": "UCfinary0001", "channel": "Finary"},
                       "https://www.youtube.com/@inconnue": {"id": "PLxxx"}}
    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)
    assert channel_id("https://www.youtube.com/@Finary") == "UCfinary0001"
    assert channel_id("https://www.youtube.com/@inconnue") == ""
    csv = tmp_path / "youtube.csv"
    csv.write_text("nom;pays;langue;theme;type;chaine;notes;actif\n# commentaire\n"
                   "Finary;France;fr;finance;explicatif;https://www.youtube.com/@Finary;note, avec virgule;oui\n"
                   "Inconnue;;;;;https://www.youtube.com/@inconnue;;oui\n"
                   "Désactivée;;;;;https://www.youtube.com/@off;;non\n", encoding="utf-8")
    assert cli.main(["chaines", "--chaines", str(csv)]) == 0
    out = capsys.readouterr().out
    assert "trouvé Finary : UCfinary0001" in out and "identifiant non trouvé" in out and "1 identifiant(s) écrit(s)" in out
    text = csv.read_bytes().decode("utf-8-sig")
    assert text.splitlines()[0] == "nom;pays;langue;theme;type;chaine;notes;actif;id_chaine" and "# commentaire" in text
    chaines = {c.nom: c for c in read_chaines(csv)}
    assert chaines["Finary"].id_chaine == "UCfinary0001" and chaines["Finary"].notes == "note, avec virgule"
    assert chaines["Finary"].flux == "https://www.youtube.com/feeds/videos.xml?channel_id=UCfinary0001"
    assert chaines["Inconnue"].flux == "" and not chaines["Désactivée"].active
    # Relance : rien à faire, fichier inchangé.
    before = csv.read_bytes()
    assert cli.main(["chaines", "--chaines", str(csv)]) == 0 and csv.read_bytes() == before
