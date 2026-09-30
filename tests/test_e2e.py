"""Test de bout en bout sur un faux site Podia : vrai navigateur, vrai yt-dlp, Whisper simulé.

Nécessite Playwright et un Chromium. Chemin du navigateur : variable PODIA_TEST_CHROMIUM,
sinon le Chromium du conteneur de développement ; le test est ignoré s'il est introuvable.
"""

import json
import os
import re
import shutil
import time
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


@pytest.fixture()
def fresh_site(site):
    site.manifest_hits.clear()
    site.expire_after, site.locked, site.lesson_pages_served, site.auto_login = None, set(), 0, True
    site.root_404 = False
    return site


@pytest.fixture()
def cdn_is_cloudflare(site, monkeypatch):
    """Le faux CDN local est traité comme Cloudflare Stream (chemin principal sur le vrai site)."""
    from podia_formation import media

    pattern = media.CLOUDFLARE_RE.pattern.replace(r"https?://(?:", r"https?://(?:localhost:\d+|", 1)
    monkeypatch.setattr(media, "CLOUDFLARE_RE", re.compile(pattern, re.I))


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


def common_args(tmp_path, profile):
    return ["--sortie", str(tmp_path / "sortie"), "--profil", str(profile), "--chemin-navigateur", CHROMIUM,
            "--headless"]


def test_full_pipeline(fresh_site, cdn_is_cloudflare, tmp_path, monkeypatch):
    from podia_formation import cli, transcribe

    site = fresh_site
    profile, out = tmp_path / "profil", tmp_path / "sortie"
    login_profile(profile, site)
    common = common_args(tmp_path, profile)

    # 1) audio (inclut l'inventaire)
    assert cli.main(["audio", site.lesson_url("1003"), *common, "--debut", "2026-10-01"]) == 0
    inv = json.loads((out / "inventaire.json").read_text(encoding="utf-8"))
    lessons = inv["lessons"]
    assert [l["lesson_id"] for l in lessons] == ["1001", "1002", "1003", "1004", "1005", "1006", "1007"]
    assert [l["kind"] for l in lessons] == ["video", "article", "video", "quiz", "article", "fichier", "video"]
    assert lessons[0]["title"] == "Introduction"                      # pas « Reprendre la formation »
    assert lessons[4]["title"] == "Décryptage : bonus caché"          # leçon cachée, titre de la page
    assert lessons[6]["module_title"] == "Module 3: Les actions"
    assert inv["course_title"] == "Investir en bourse" and inv["progress"] == [1, 7]
    assert lessons[3]["quiz_questions"] == 4
    assert lessons[1]["attachments"][0]["pages"] == 2 and lessons[5]["attachments"][0]["pages"] == 2
    for l in (lessons[0], lessons[2], lessons[6]):
        assert 5.5 < l["video_duration_s"] < 6.5
        assert (out / l["audio_files"][0]).stat().st_size > 10_000
        assert l["audio_files"][0].endswith(".m4a")
    assert "eyJ" not in json.dumps(inv).replace("eyJ-jeton-masque", "")  # jetons masqués
    # Flux déduit de l'iframe (sans lecture) et rejoué avec le Referer du site (le faux CDN renvoie 401 sinon).
    never = jwt("0123456789abcdef0123456789abcdef")
    assert any(never in h["path"] and h["referer"] == site.site_url + "/" for h in site.manifest_hits)
    article = (out / "textes" / "M01-L02 - Les 10 commandements de l'investisseur.md").read_text(encoding="utf-8")
    assert "Deuxième idée : investir tôt." in article and "Conclusion : rester patient." in article
    assert "- Investir tôt" in article and "Super cours" not in article     # commentaires exclus
    assert (out / "planning.ics").is_file() and (out / "resume.md").is_file()

    # 2) relance : rien à refaire (reprise)
    hits = len(site.manifest_hits)
    assert cli.main(["audio", site.lesson_url("1002"), *common]) == 0     # page sans vidéo
    assert len(site.manifest_hits) == hits

    # 3) transcription (Whisper simulé)
    monkeypatch.setattr(transcribe, "load_model", lambda *a, **k: (FakeWhisper(), "cpu"))
    assert cli.main(["transcrire", "--sortie", str(out)]) == 0
    txt = out / "transcriptions" / "M02-L01 - Se lancer.txt"
    assert txt.read_text(encoding="utf-8").strip() == "Bienvenue dans ce module. Parlons des actions."
    full = (out / "formation_complete.md").read_text(encoding="utf-8")
    assert "Parlons des actions." in full and "La diversification réduit le risque" in full

    # 4) planning seul, en semaine, à 18h30
    assert cli.main(["planning", "--sortie", str(out), "--debut", "03/10/2026", "--jours", "lun-ven",
                     "--heure", "18h30"]) == 0
    plan = json.loads((out / "planning.json").read_text(encoding="utf-8"))
    assert plan["seances"][0]["day"] == "2026-10-05"      # samedi 3 -> lundi 5
    assert plan["parametres"]["heure"] == "18:30"
    # 5) une relance de l'inventaire ne remplace pas ce planning personnalisé
    assert cli.main(["inventaire", site.lesson_url("1002"), *common]) == 0
    again = json.loads((out / "planning.json").read_text(encoding="utf-8"))
    assert again["parametres"]["heure"] == "18:30" and again["seances"][0]["day"] == "2026-10-05"


def test_click_to_play_player(fresh_site, tmp_path):
    """Lecteur qui ne demande le flux qu'au clic sur « Lecture » (preload=none)."""
    from podia_formation import cli

    site = fresh_site
    profile = tmp_path / "profil"
    login_profile(profile, site)
    assert cli.main(["sonde", site.lesson_url("1003"), *common_args(tmp_path, profile)]) == 0
    click = jwt("video1003")
    assert any(click in h["path"] and "/iframe" in (h["referer"] or "") for h in site.manifest_hits)  # requête du lecteur
    out = tmp_path / "sortie"
    assert list((out / "sonde" / "audio").glob("*.m4a"))
    html = (out / "diagnostic" / "sonde.html").read_text(encoding="utf-8")
    assert "SECRET-CSRF" not in html and "eyJhbGci" not in html
    assert "eleve@example.com" not in html and "Valentin" not in html        # données personnelles masquées


def test_player_that_never_loads_and_inline_pdf_do_not_hang(fresh_site, tmp_path, capsys):
    from podia_formation import cli

    site = fresh_site
    profile = tmp_path / "profil"
    login_profile(profile, site)
    started = time.monotonic()
    assert cli.main(["sonde", site.lesson_url("1007"), *common_args(tmp_path, profile), "--sans-audio"]) == 0
    assert cli.main(["sonde", site.lesson_url("1006"), *common_args(tmp_path, profile), "--sans-audio"]) == 0
    assert time.monotonic() - started < 150
    out = capsys.readouterr().out
    assert "aucun flux n'a été capté" in out            # 1007 : signalé, sans blocage
    assert "type fichier" in out                        # 1006 : fiche PDF, pas une vidéo


def test_session_expiry_and_locked_lesson(fresh_site, tmp_path, capsys):
    from podia_formation import cli

    site = fresh_site
    profile, out = tmp_path / "profil", tmp_path / "sortie"
    login_profile(profile, site)
    site.locked = {"1002"}
    site.lesson_pages_served = 0
    site.expire_after = 3                      # la page de départ + 2 leçons, puis la session expire
    site.auto_login = False
    code = cli.main(["inventaire", site.lesson_url("1001"), *common_args(tmp_path, profile)])
    assert code == 1 and "la session a expiré" in capsys.readouterr().out
    lessons = {l["lesson_id"]: l for l in json.loads((out / "inventaire.json").read_text(encoding="utf-8"))["lessons"]}
    assert lessons["1001"]["visited"] and lessons["1001"]["kind"] == "video"
    assert not lessons["1002"]["visited"] and "inaccessible" in lessons["1002"]["error"]
    assert not lessons["1004"]["visited"]      # pas marquée « vide » : elle sera visitée au prochain lancement


def test_public_curriculum_is_not_mistaken_for_a_login(fresh_site, tmp_path, monkeypatch):
    """Sommaire visible sans connexion (cas Zonebourse) : l'outil doit demander la connexion, pas conclure « OK »."""
    from podia_formation.crawler import Crawler, NotLoggedIn

    site = fresh_site
    monkeypatch.setattr(site, "public_preview", True)
    monkeypatch.setattr(site, "auto_login", False)
    with Crawler(headless=True, profile=tmp_path / "p1", executable=CHROMIUM, log=lambda m: None) as cr:
        with pytest.raises(NotLoggedIn):
            cr.open_course(site.lesson_url("1003"))
    monkeypatch.setattr(site, "auto_login", True)       # l'utilisateur se connecte dans la fenêtre
    messages = []
    with Crawler(headless=True, profile=tmp_path / "p2", executable=CHROMIUM, log=messages.append) as cr:
        cr.headless = False
        cr.login_timeout = 60
        cr.open_course(site.lesson_url("1003"))
        assert any("Connexion réussie" in m for m in messages)
        res = cr.visit(site.lesson_url("1003"))
        assert res.videos and res.title == "Se lancer"


def test_login_in_an_unpiloted_browser_then_attach(fresh_site, tmp_path, monkeypatch):
    """Mode normal : navigateur ordinaire (non piloté pendant la connexion, pour Cloudflare), rattaché ensuite."""
    from podia_formation.crawler import Crawler

    site = fresh_site
    monkeypatch.setenv("PODIA_EXTRA_BROWSER_ARGS", "--headless=new --no-sandbox")
    monkeypatch.setattr(site, "public_preview", True)
    messages = []
    profile = tmp_path / "profil"
    with Crawler(headless=False, profile=profile, executable=CHROMIUM, log=messages.append) as cr:
        cr.login_timeout = 90
        assert cr.mode == "cdp"
        cr.open_course(site.lesson_url("1003"))
        assert any("Connexion réussie" in m for m in messages)
        res = cr.visit(site.lesson_url("1003"))
        assert res.videos and res.title == "Se lancer"
        proc = cr._proc
    assert proc.poll() is not None                       # navigateur fermé à la fin
    # Lancement suivant : la connexion est gardée dans le profil, aucune nouvelle connexion demandée.
    messages.clear()
    with Crawler(headless=False, profile=profile, executable=CHROMIUM, log=messages.append) as cr:
        cr.open_course(site.lesson_url("1003"))
        assert not any("pas encore connecté" in m for m in messages)
        assert cr.visit(site.lesson_url("1001")).videos


def test_course_address_returning_404_is_reported_without_login_loop(fresh_site, tmp_path, capsys):
    """Zonebourse : l'adresse de la formation sans la leçon renvoie 404 ; on le dit au lieu de redemander la connexion."""
    from podia_formation import cli

    site = fresh_site
    profile = tmp_path / "profil"
    login_profile(profile, site)
    site.root_404 = True
    site.auto_login = False
    root = site.lesson_url("1001").rsplit("/", 2)[0]
    assert cli.main(["inventaire", root, *common_args(tmp_path, profile)]) == 1
    out = capsys.readouterr().out
    assert "erreur 404" in out and "adresse complète d'une leçon" in out
    assert "pas encore connecté" not in out and "pas connecté" not in out
    assert cli.main(["inventaire", site.lesson_url("1001"), *common_args(tmp_path, profile)]) == 0


def test_headless_without_session_fails_cleanly(fresh_site, tmp_path, capsys, monkeypatch):
    from podia_formation import cli

    monkeypatch.setattr(fresh_site, "auto_login", False)
    code = cli.main(["inventaire", fresh_site.lesson_url("1001"), "--sortie", str(tmp_path / "o"), "--profil",
                     str(tmp_path / "vide"), "--chemin-navigateur", CHROMIUM, "--headless"])
    assert code == 1
    assert "pas connecté à Podia" in capsys.readouterr().out


def test_invalid_planning_option_is_rejected_before_any_work(tmp_path, capsys):
    from podia_formation import cli

    with pytest.raises(SystemExit):
        cli.main(["tout", "https://x.podia.com/p/courses/c", "--sortie", str(tmp_path), "--heure", "25h"])
    assert "heure invalide" in capsys.readouterr().err
