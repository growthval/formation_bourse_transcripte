"""Tests du digest de flux et du registre des sources (sans réseau)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from vigie.flux import (Entree, clean, fold, matches, parse_date, parse_feed, render_digest, run_flux,
                        select_sources)
from vigie.sources import Source, check_feeds, missing_columns, read_sources

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)

RSS = ("""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel><title>Le Journal</title><atom:link href="https://journal.example/rss" rel="self"/>
<item><title>Taux : la BCE &amp; la Fed temporisent</title><link>https://journal.example/a1</link>
<pubDate>Wed, 01 Oct 2026 09:30:00 +0200</pubDate>
<description>&lt;p&gt;Les banques centrales &lt;b&gt;attendent&lt;/b&gt; de nouvelles donn&#233;es.&lt;/p&gt;</description></item>
<item><title>Vieil article</title><link>https://journal.example/a0</link><pubDate>Mon, 01 Sep 2026 09:00:00 GMT</pubDate></item>
<item><title>Sans lien mais avec guid</title><guid>https://journal.example/a2</guid>
<pubDate>Tue, 30 Sep 2026 22:00:00 GMT</pubDate><content:encoded>Résumé encodé</content:encoded></item>
</channel></rss>""").encode("utf-8")

ATOM = ("""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Blog IA</title>
<entry><title>Les labos et la sécurité</title><link rel="self" href="https://blog.example/self"/>
<link rel="alternate" href="https://blog.example/securite"/><published>2026-10-01T06:00:00Z</published>
<summary type="html">Un chercheur &lt;em&gt;quitte&lt;/em&gt; un laboratoire.</summary></entry>
<entry><title>Géopolitique de Taïwan</title><link href="https://blog.example/taiwan"/><updated>2026-09-30T18:30:00+02:00</updated></entry>
</feed>""").encode("utf-8")

RDF = ("""<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel rdf:about="https://old.example/"><title>Vieux flux</title></channel>
<item rdf:about="https://old.example/x"><title>Article RDF</title><link>https://old.example/x</link><dc:date>2026-10-01T01:00:00Z</dc:date></item>
</rdf:RDF>""").encode("utf-8")


def test_parse_rss_atom_and_rdf():
    rss = parse_feed(RSS, "Le Journal")
    assert [e.titre for e in rss] == ["Taux : la BCE & la Fed temporisent", "Vieil article", "Sans lien mais avec guid"]
    assert rss[0].lien == "https://journal.example/a1"
    assert rss[0].date == datetime(2026, 10, 1, 7, 30, tzinfo=timezone.utc)
    assert rss[0].resume == "Les banques centrales attendent de nouvelles données."
    assert rss[2].lien == "https://journal.example/a2" and rss[2].resume == "Résumé encodé"

    atom = parse_feed(ATOM, "Blog IA")
    assert atom[0].lien == "https://blog.example/securite"          # rel=alternate préféré à rel=self
    assert atom[0].resume == "Un chercheur quitte un laboratoire."
    assert atom[1].lien == "https://blog.example/taiwan"
    assert atom[1].date.astimezone(timezone.utc).hour == 16

    rdf = parse_feed(RDF, "Vieux flux")
    assert rdf[0].titre == "Article RDF" and rdf[0].date is not None


def test_parse_feed_rejects_html():
    import xml.etree.ElementTree as ET

    with pytest.raises(ET.ParseError):
        parse_feed(b"<html><body>Page d'erreur</body></html><p>", "x")


def test_dates_and_text_helpers():
    assert parse_date("") is None and parse_date("n'importe quoi") is None
    assert parse_date("2026-10-01T10:00:00").tzinfo is not None             # naïf -> UTC
    assert parse_date("Wed, 01 Oct 2026 09:30:00 +0200").utcoffset() == timedelta(hours=2)
    long = "mot " * 100
    out = clean(f"<p>{long}</p>", limit=50)
    assert out.endswith("…") and len(out) <= 52
    assert clean("A &amp;amp; B") == "A & B"
    assert fold("Géopolitique, Taïwan") == "geopolitique, taiwan"
    e = Entree("s", "Élections à Taïwan", "https://x", None, "")
    assert matches(e, ["taiwan"]) and not matches(e, ["chine"]) and matches(e, [])


def test_read_sources_accepts_excel_csv_with_semicolons_and_bom(tmp_path: Path):
    csv = tmp_path / "medias.csv"
    csv.write_bytes("﻿Nom;Pays;Langue;categorie;orientation;rss;site;notes;actif\n"
                    "# commentaire ignoré\n"
                    "Le Journal;France;fr;presse;centre;https://journal.example/rss;https://journal.example;;oui\n"
                    "Blog IA;États-Unis;en;ia;indépendant;https://blog.example/atom;;note;\n"
                    "Désactivée;;;presse;;https://off.example/rss;;;non\n"
                    ";;;;;;;;\n".encode("utf-8"))
    sources = read_sources(csv)
    assert [s.nom for s in sources] == ["Le Journal", "Blog IA", "Désactivée"]
    assert sources[0].active and sources[1].active and not sources[2].active
    assert sources[0].categorie_libelle == "Presse généraliste"
    assert sources[1].categorie_libelle == "Intelligence artificielle"
    assert missing_columns(csv) == []
    assert "rss" in missing_columns(tmp_path / "x.csv") if (tmp_path / "x.csv").write_text("nom,pays\nA,B\n") else True
    assert select_sources(sources, ["journal"]) == [sources[0]]
    assert [s.nom for s in select_sources(sources)] == ["Le Journal", "Blog IA"]


def test_read_sources_windows_encoding(tmp_path: Path):
    csv = tmp_path / "m.csv"
    csv.write_bytes("nom,pays\nLe Figaro,France\nZonebourse,Fran\xe7aise\n".encode("cp1252"))
    assert [s.pays for s in read_sources(csv)] == ["France", "Française"]


def _fake_fetch(mapping: dict[str, bytes]):
    def fetch(url: str) -> bytes:
        if url in mapping:
            return mapping[url]
        raise OSError(f"HTTP Error 404: Not Found ({url})")
    return fetch


def _sources_csv(tmp_path: Path) -> Path:
    csv = tmp_path / "medias.csv"
    csv.write_text("nom,pays,langue,categorie,orientation,rss,site,notes,actif\n"
                   "Le Journal,France,fr,presse,centre,https://journal.example/rss,,,oui\n"
                   "Blog IA,États-Unis,en,ia,,https://blog.example/atom,,,oui\n"
                   "Cassé,Italie,it,economie,,https://casse.example/rss,,,oui\n"
                   "Manuel,Japon,ja,presse,,,https://manuel.example,,oui\n", encoding="utf-8")
    return csv


def test_run_flux_writes_digest_with_period_filter_and_errors(tmp_path: Path):
    fetch = _fake_fetch({"https://journal.example/rss": RSS, "https://blog.example/atom": ATOM})
    logs: list[str] = []
    path = run_flux(_sources_csv(tmp_path), tmp_path / "journal", days=2, fetch_fn=fetch, now=NOW, log=logs.append)
    assert path.name == f"{NOW.astimezone():%Y-%m-%d}-flux.md"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# Flux de presse du")
    assert "## Presse généraliste" in text and "## Intelligence artificielle" in text
    assert "### Le Journal (France, fr)" in text
    assert "[Taux : la BCE & la Fed temporisent](https://journal.example/a1)" in text
    assert "Vieil article" not in text                       # hors période
    assert "Sans lien mais avec guid" in text
    assert text.index("Taux : la BCE") < text.index("Sans lien")   # plus récent d'abord
    assert "## Flux en erreur" in text and "- Cassé : HTTP Error 404" in text
    assert "Manuel" not in text                              # pas de flux : pas interrogée
    assert "2 source(s) lue(s)" in text and "4 article(s)" in text
    assert any("ERREUR Cassé" in l for l in logs)


def test_run_flux_keywords_only_and_max(tmp_path: Path):
    fetch = _fake_fetch({"https://journal.example/rss": RSS, "https://blog.example/atom": ATOM})
    path = run_flux(_sources_csv(tmp_path), tmp_path / "j", days=5, keywords=["taïwan", "fed"], only=["blog", "journal"],
                    max_per_source=1, fetch_fn=fetch, now=NOW, log=lambda _: None)
    text = path.read_text(encoding="utf-8")
    assert "Géopolitique de Taïwan" in text and "Taux : la BCE" in text
    assert "Les labos" not in text and "Sans lien" not in text
    assert "filtre : taïwan, fed" in text
    with pytest.raises(RuntimeError):
        run_flux(_sources_csv(tmp_path), tmp_path / "j", only=["inconnue"], fetch_fn=fetch, now=NOW, log=lambda _: None)


def test_render_digest_empty_source_and_undated():
    s = Source("Vide", "France", "fr", "presse", rss="https://v")
    u = Source("Sans date", "", "", "autre", rss="https://u")
    text = render_digest([s, u], {"Vide": [], "Sans date": [Entree("Sans date", "T", "https://u/1")]}, [], NOW, 1, [])
    assert "_Rien de nouveau sur la période._" in text
    assert "## Autres" in text and "— sans date" in text
    assert text.index("## Presse généraliste") < text.index("## Autres")


def test_check_feeds_reports_each_source(tmp_path: Path):
    sources = read_sources(_sources_csv(tmp_path)) + [Source("Off", rss="https://off", actif="non")]
    fetch = _fake_fetch({"https://journal.example/rss": RSS, "https://blog.example/atom": b"<rss><channel></channel></rss>"})
    results = check_feeds(sources, fetch, parse_feed, log=lambda _: None)
    status = {s.nom: (ok, msg) for s, ok, msg in results}
    assert status["Le Journal"][0] and "3 article(s)" in status["Le Journal"][1]
    assert not status["Blog IA"][0] and "vide" in status["Blog IA"][1]
    assert not status["Cassé"][0] and "404" in status["Cassé"][1]
    assert status["Manuel"][0] and "à la main" in status["Manuel"][1]
    assert status["Off"][0] and "désactivée" in status["Off"][1]


def test_cli_flux_and_sources(tmp_path: Path, monkeypatch, capsys):
    import vigie.cli as cli
    import vigie.flux as flux

    monkeypatch.setattr(flux, "fetch", _fake_fetch({"https://journal.example/rss": RSS, "https://blog.example/atom": ATOM}))
    csv = _sources_csv(tmp_path)
    assert cli.main(["flux", "--sources", str(csv), "--sortie", str(tmp_path / "out"), "--jours", "3"]) == 0
    out = capsys.readouterr().out
    assert "Digest écrit" in out and list((tmp_path / "out").glob("*-flux.md"))
    assert cli.main(["sources", "--sources", str(csv), "--tester"]) == 0
    out = capsys.readouterr().out
    assert "4 source(s), 4 active(s), 3 avec flux RSS." in out and "1 en erreur" in out
    assert cli.main(["flux", "--sources", str(tmp_path / "absent.csv")]) == 1
    assert "ERREUR" in capsys.readouterr().out


def test_sanitize_tolerates_leading_text_html_entities_and_bom():
    from vigie.flux import sanitize_xml

    dirty = ("\n\n<?xml version=\"1.0\"?><rss><channel><item><title>L&rsquo;Europe &amp; l&#39;IA&nbsp;!</title>"
             "<link>https://x/1</link></item></channel></rss>").encode("utf-8")
    entries = parse_feed(dirty, "s")
    assert entries[0].titre == "L’Europe & l'IA !"
    assert sanitize_xml(b"\xef\xbb\xbf  <feed xmlns=\"http://www.w3.org/2005/Atom\"></feed>").startswith(b"<feed")
    assert sanitize_xml(b"<p>&inconnue;</p>") == b"<p>&amp;inconnue;</p>"


def test_parse_date_fallback_formats():
    assert parse_date("Wed, 01 Oct 2026 08:00:00 JST") is not None
    assert parse_date("2026-10-01 08:00:00").day == 1
    assert parse_date("01/10/2026") is not None and parse_date("20261001").month == 10


def test_fetch_retries_once_with_browser_agent_on_403():
    import urllib.error

    from vigie.flux import BROWSER_AGENT, USER_AGENT, fetch

    calls = []

    def opener(url, agent, timeout):
        calls.append(agent)
        if agent == USER_AGENT:
            raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
        return b"<rss/>"
    assert fetch("https://x/rss", opener=opener) == b"<rss/>" and calls == [USER_AGENT, BROWSER_AGENT]

    def opener404(url, agent, timeout):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
    with pytest.raises(urllib.error.HTTPError):
        fetch("https://x/rss", opener=opener404)


def test_check_feeds_flags_stale_feeds(tmp_path: Path):
    old_rss = RSS.replace(b"01 Oct 2026", b"01 Oct 2024").replace(b"30 Sep 2026", b"30 Sep 2024").replace(b"01 Sep 2026", b"01 Sep 2024")
    sources = [Source("Vieux", rss="https://old"), Source("Frais", rss="https://journal.example/rss")]
    results = check_feeds(sources, _fake_fetch({"https://old": old_rss, "https://journal.example/rss": RSS}), parse_feed,
                          log=lambda _: None, now=NOW)
    status = {s.nom: (ok, msg) for s, ok, msg in results}
    assert not status["Vieux"][0] and "abandonné" in status["Vieux"][1]
    assert status["Frais"][0]
