"""Test de bout en bout sur un faux site Podia : vrai navigateur, vrai yt-dlp, Whisper simulé.

Nécessite Playwright et un Chromium. Chemin du navigateur : variable PODIA_TEST_CHROMIUM,
sinon le Chromium du conteneur de développement ; le test est ignoré s'il est introuvable.
"""

import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from fake_podia import FakePodia, jwt, make_hls

CHROMIUM = os.environ.get("PODIA_TEST_CHROMIUM", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
pytestmark = pytest.mark.skipif(not Path(CHROMIUM).exists(), reason="Chromium de test introuvable")


def ffmpeg_exe():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    imageio_ffmpeg = pytest.importorskip("imageio_ffmpeg")
    return imageio_ffmpeg.get_ffmpeg_exe()


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    pytest.importorskip("playwright")
    hls = tmp_path_factory.mktemp("hls")
    make_hls(hls, ffmpeg_exe())
    fake = FakePodia(hls).start()
    yield fake
    fake.stop()


def login_profile(profile: Path, site: FakePodia) -> None:
    """Simule la connexion de l'utilisateur (le faux /login pose un cookie persistant)."""
    from podia_formation.crawler import Crawler

    with Crawler(headless=True, profile=profile, executable=CHROMIUM, log=lambda m: None) as cr:
        cr.headless = False          # autorise l'attente de connexion malgré le mode invisible
        cr.login_timeout = 60
        data = cr.open_course(site.lesson_url("1003"))
    assert len(data["items"]) > 0


class FakeWhisper:
    def transcribe(self, audio, **kwargs):
        assert Path(audio).stat().st_size > 1000
        segs = iter([SimpleNamespace(start=0.0, end=2.0, text=" Bienvenue dans ce module."),
                     SimpleNamespace(start=2.5, end=5.5, text=" Parlons des actions.")])
        return segs, SimpleNamespace(duration=6.0)


def test_full_pipeline(site, tmp_path, monkeypatch):
    from podia_formation import cli, transcribe

    profile, out = tmp_path / "profil", tmp_path / "sortie"
    login_profile(profile, site)
    common = ["--sortie", str(out), "--profil", str(profile), "--chemin-navigateur", CHROMIUM, "--headless"]

    # 1) audio (inclut l'inventaire)
    assert cli.main(["audio", site.lesson_url("1003"), *common, "--debut", "2026-10-01"]) == 0
    inv = json.loads((out / "inventaire.json").read_text(encoding="utf-8"))
    lessons = inv["lessons"]
    assert [l["lesson_id"] for l in lessons] == ["1001", "1002", "1003", "1004", "1005"]
    assert [l["kind"] for l in lessons] == ["video", "article", "video", "quiz", "article"]
    assert lessons[4]["title"] == "Décryptage : bonus caché"          # leçon cachée, titre de la page
    assert lessons[3]["quiz_questions"] == 4
    assert lessons[1]["attachments"][0]["pages"] == 2
    for l in (lessons[0], lessons[2]):
        assert 5.5 < l["video_duration_s"] < 6.5
        assert (out / l["audio_files"][0]).stat().st_size > 10_000
        assert l["audio_files"][0].endswith(".m4a")
    assert "eyJ" not in json.dumps(inv).replace("eyJ-jeton-masque", "")  # jetons masqués
    # Le flux a été rejoué avec un Referer (le faux CDN renvoie 401 sinon) et le lecteur à clic a été déclenché.
    assert any(jwt("video1003") in h["path"] for h in site.manifest_hits)
    assert all(h["referer"] for h in site.manifest_hits)
    assert (out / "textes" / "M01-L02 - Les 10 commandements de l'investisseur.md").is_file()
    assert (out / "planning.ics").is_file() and (out / "resume.md").is_file()

    # 2) relance : rien à refaire (reprise)
    hits = len(site.manifest_hits)
    assert cli.main(["audio", site.lesson_url("1002"), *common]) == 0     # page sans vidéo
    assert len(site.manifest_hits) == hits

    # 3) transcription (Whisper simulé)
    monkeypatch.setattr(transcribe, "load_model", lambda name, device: (FakeWhisper(), "cpu"))
    assert cli.main(["transcrire", "--sortie", str(out)]) == 0
    txt = out / "transcriptions" / "M02-L01 - Se lancer.txt"
    assert txt.read_text(encoding="utf-8").strip() == "Bienvenue dans ce module. Parlons des actions."
    full = (out / "formation_complete.md").read_text(encoding="utf-8")
    assert "Parlons des actions." in full and "La diversification réduit le risque" in full

    # 4) planning seul, en semaine
    assert cli.main(["planning", "--sortie", str(out), "--debut", "2026-10-03", "--jours", "semaine"]) == 0
    plan = json.loads((out / "planning.json").read_text(encoding="utf-8"))
    assert plan[0]["day"] == "2026-10-05"      # samedi 3 -> lundi 5


def test_sonde(site, tmp_path):
    from podia_formation import cli

    profile, out = tmp_path / "profil", tmp_path / "sortie"
    login_profile(profile, site)
    assert cli.main(["sonde", site.lesson_url("1001"), "--sortie", str(out), "--profil", str(profile),
                     "--chemin-navigateur", CHROMIUM, "--headless"]) == 0
    html = (out / "diagnostic" / "sonde.html").read_text(encoding="utf-8")
    assert "SECRET-CSRF" not in html and "eyJhbGci" not in html
    assert list((out / "sonde" / "audio").glob("*.m4a"))


def test_headless_without_session_fails_cleanly(site, tmp_path, capsys, monkeypatch):
    from podia_formation import cli

    monkeypatch.setattr(site, "auto_login", False)
    code = cli.main(["inventaire", site.lesson_url("1001"), "--sortie", str(tmp_path / "o"), "--profil",
                     str(tmp_path / "vide"), "--chemin-navigateur", CHROMIUM, "--headless"])
    assert code == 1
    assert "Session absente" in capsys.readouterr().out
