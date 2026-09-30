import base64
import json

from podia_formation.media import (
    classify_url,
    cloudflare_manifest_from_iframe,
    embed_urls_from_html,
    jwt_claims,
    m3u8_duration,
    manifest_duration,
    mpd_duration,
    parse_iso8601_duration,
    replay_headers,
    token_in,
)

UID = "e178e09fd8f246b978bf8851df573b86"


def make_jwt(payload: dict) -> str:
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{enc({'alg': 'RS256', 'kid': 'k'})}.{enc(payload)}.c2lnbmF0dXJlLXRyZXMtbG9uZ3Vl"


TOKEN = make_jwt({"sub": UID, "kid": "k", "exp": 1790000000})
CF = "https://customer-010kwcw7rkskh8op.cloudflarestream.com"


def test_classify_cloudflare_token_uses_video_uid_as_key():
    kind, key = classify_url(f"{CF}/{TOKEN}/manifest/video.m3u8?parentOrigin=https%3A%2F%2Fx.podia.com")
    assert (kind, key) == ("cloudflare", f"cf:{UID}")
    # Même vidéo, autre jeton (nouvelle visite) : même clé.
    other = make_jwt({"sub": UID, "exp": 1790009999})
    assert classify_url(f"{CF}/{other}/iframe")[1] == key


def test_classify_other_players():
    assert classify_url(f"{CF}/{UID}/iframe") == ("cloudflare", f"cf:{UID}")
    assert classify_url("https://cdn.example.com/a/master.m3u8?x=1")[0] == "hls"
    assert classify_url("https://cdn.example.com/a/stream.mpd")[0] == "dash"
    assert classify_url("https://fast.wistia.net/embed/iframe/abcde12345") == ("wistia", "wistia:abcde12345")
    assert classify_url("https://player.vimeo.com/video/123456?h=abc123")[0] == "vimeo"
    assert classify_url("https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ")[0] == "youtube"
    assert classify_url("https://www.loom.com/embed/" + "a" * 32)[0] == "loom"
    assert classify_url("https://zonebourse.podia.com/p/courses/x") is None


def test_manifest_from_iframe_keeps_or_adds_parent_origin():
    url = cloudflare_manifest_from_iframe(f"{CF}/{TOKEN}/iframe?letterboxColor=transparent", "https://zonebourse.podia.com")
    assert url == f"{CF}/{TOKEN}/manifest/video.m3u8?parentOrigin=https%3A%2F%2Fzonebourse.podia.com"
    url = cloudflare_manifest_from_iframe(f"{CF}/{TOKEN}/iframe?parentOrigin=https%3A%2F%2Fa.b", "https://c.d")
    assert url.endswith("parentOrigin=https%3A%2F%2Fa.b")
    assert cloudflare_manifest_from_iframe("https://example.com/x") is None


def test_embed_urls_from_html_handles_escaped_json_entities_and_bare_tokens():
    html = (
        f'<div data-props="{{&quot;src&quot;:&quot;{CF}/{TOKEN}/iframe?a=1&amp;b=2&quot;}}"></div>'
        f'<script>var x = {{"u": "{CF.replace("/", chr(92) + "/")}\\/{TOKEN}\\/iframe"}}</script>'
        '<div class="wistia_embed wistia_async_abcde12345"></div>'
        '<iframe src="https://player.vimeo.com/video/42"></iframe>'
    )
    urls = embed_urls_from_html(html)
    assert any(u.startswith(f"{CF}/{TOKEN}/iframe") and "&quot;" not in u for u in urls)
    assert "wistia:abcde12345" in urls
    assert "https://player.vimeo.com/video/42" in urls
    # <stream src="jeton"> : on reconstruit l'iframe sur l'hôte Cloudflare vu dans la page.
    other = make_jwt({"sub": "0" * 32, "exp": 1})
    urls = embed_urls_from_html(f'<link href="{CF}/x"><stream src="{other}"></stream>')
    assert f"{CF}/{other}/iframe" in urls


def test_bare_token_without_video_uid_is_ignored():
    not_video = make_jwt({"sub": "user-42", "exp": 1})
    assert embed_urls_from_html(f'<meta content="{not_video}">') == []


def test_jwt_helpers():
    assert jwt_claims(TOKEN)["sub"] == UID
    assert jwt_claims("pas-un-jeton") == {}
    assert token_in(f"{CF}/{TOKEN}/manifest/video.m3u8") == TOKEN


def test_iso8601_and_mpd_duration():
    assert parse_iso8601_duration("PT12M3.5S") == 723.5
    assert parse_iso8601_duration("PT1H0M0S") == 3600
    assert parse_iso8601_duration("P0D") == 0
    assert parse_iso8601_duration("n'importe quoi") is None
    assert mpd_duration('<MPD mediaPresentationDuration="PT0H4M10.00S" minBufferTime="PT2S">') == 250


def test_m3u8_duration_follows_master_to_audio_rendition():
    master = ('#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="a",NAME="original",URI="audio/list.m3u8"\n'
              '#EXT-X-STREAM-INF:BANDWIDTH=1,AUDIO="a"\nvideo/list.m3u8\n')
    child = "#EXTM3U\n#EXTINF:4.0,\ns1.ts\n#EXTINF:4.0,\ns2.ts\n#EXTINF:2.5,\ns3.ts\n#EXT-X-ENDLIST\n"
    fetched = []

    def fetch(url):
        fetched.append(url)
        return child

    assert m3u8_duration(master, "https://h/x/manifest/video.m3u8", fetch) == 10.5
    assert fetched == ["https://h/x/manifest/audio/list.m3u8"]


def test_manifest_duration_dispatch():
    assert manifest_duration("https://h/v.mpd", lambda u: '<MPD mediaPresentationDuration="PT10S">') == 10
    assert manifest_duration("https://h/v.m3u8", lambda u: "#EXTM3U\n#EXTINF:3,\na.ts\n") == 3
    assert manifest_duration("https://h/v.m3u8", lambda u: "<html>") is None


def test_replay_headers_keeps_browser_headers_and_fills_origin():
    url = f"{CF}/{TOKEN}/manifest/video.m3u8?parentOrigin=https%3A%2F%2Fzonebourse.podia.com"
    h = replay_headers({"referer": f"{CF}/{TOKEN}/iframe", "user-agent": "UA", "cookie": "secret",
                        "accept": "*/*"}, url, "https://zonebourse.podia.com/p/courses/a/1-b/2-c")
    assert h["Referer"] == f"{CF}/{TOKEN}/iframe"
    assert h["User-Agent"] == "UA"
    assert h["Origin"] == "https://zonebourse.podia.com"
    assert "Cookie" not in h and "Accept" not in h
    h = replay_headers({}, "https://h/v.m3u8", "https://site.example/p/courses/x")
    assert h == {"Referer": "https://site.example/", "Origin": "https://site.example"}
